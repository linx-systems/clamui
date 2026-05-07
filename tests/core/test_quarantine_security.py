# ClamUI Quarantine Security Tests (VULN-003, VULN-004)
"""Security-focused unit tests for the quarantine restore/delete redesign.

Covers:
- VULN-003 (HIGH): TOCTOU on restore destination — symlink at original_path must
  not be followed; the existing target must be untouched.
- VULN-004 (MED): setuid/setgid/sticky bits stored in DB must be stripped on
  both write (add_entry) and read (from_row) and never restored to disk.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.core.quarantine.database import QuarantineDatabase, QuarantineEntry
from src.core.quarantine.file_handler import (
    _atomic_create_at_destination,
)
from src.core.quarantine.manager import QuarantineManager


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def manager(temp_dir):
    quarantine_dir = os.path.join(temp_dir, "quarantine")
    db_path = os.path.join(temp_dir, "quarantine.db")
    mgr = QuarantineManager(
        quarantine_directory=quarantine_dir,
        database_path=db_path,
        enable_periodic_cleanup=False,
    )
    yield mgr
    mgr.close()


def _make_test_file(path: str, content: bytes = b"infected payload") -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


class TestRestoreSymlinkAttack:
    """VULN-003: TOCTOU on restore destination."""

    def test_restore_refuses_symlink_at_destination(self, manager, temp_dir):
        """A symlink at original_path must NOT be followed on restore.

        Setup:
            quarantine a file at /tmp/.../files/payload.bin
            attacker replaces original_path with a symlink to /tmp/.../target
            target file holds known content
        Expectation:
            restore fails; target is untouched (hash unchanged)
        """
        target = os.path.join(temp_dir, "target_secret")
        target_content = b"this must NOT be overwritten"
        _make_test_file(target, target_content)
        target_hash_before = hashlib.sha256(target_content).hexdigest()

        original = os.path.join(temp_dir, "files", "payload.bin")
        _make_test_file(original, b"original benign payload")
        result = manager.quarantine_file(original, "Test.Trojan")
        assert result.is_success

        # Attacker substitutes a symlink at original_path pointing to target.
        os.symlink(target, original)
        assert os.path.islink(original)

        restore_result = manager.restore_file(result.entry.id)

        assert restore_result.is_success is False, (
            "Restore must refuse to follow a symlink at the destination"
        )

        # Target must be untouched.
        with open(target, "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == target_hash_before

    def test_atomic_create_O_NOFOLLOW_rejects_symlink_dst(self, temp_dir):
        """Direct test of helper: O_NOFOLLOW must reject pre-existing symlink at dst."""
        # Create a "source" file inside the quarantine dir.
        src = Path(temp_dir) / "source.bin"
        src.write_bytes(b"source content")

        # Real existing target the symlink points at.
        real_target = Path(temp_dir) / "real_target.bin"
        real_target.write_bytes(b"untouched")

        dst_dir = Path(temp_dir) / "dst_dir"
        dst_dir.mkdir()
        dst_path = dst_dir / "victim.bin"
        os.symlink(str(real_target), str(dst_path))

        with pytest.raises(OSError):
            _atomic_create_at_destination(src, dst_path, 0o644)

        # real_target must be untouched (still 'untouched')
        assert real_target.read_bytes() == b"untouched"


class TestRestoreStripsSetuidBits:
    """VULN-004: setuid/setgid/sticky must be stripped before restore."""

    def test_restore_strips_setuid_bits(self, manager, temp_dir):
        original = os.path.join(temp_dir, "files", "binary.exe")
        _make_test_file(original, b"binary content")
        result = manager.quarantine_file(original, "Test.Threat")
        assert result.is_success
        entry_id = result.entry.id

        # Attacker tampers with DB to inject setuid+setgid+sticky bits.
        # Even if the DB layer masks at write time, we directly inject raw bits
        # to verify the read/restore path also enforces masking.
        raw_conn = sqlite3.connect(manager._database._db_path)
        try:
            raw_conn.execute("PRAGMA ignore_check_constraints = ON")
            raw_conn.execute(
                "UPDATE quarantine SET original_permissions = ? WHERE id = ?",
                (0o6755, entry_id),
            )
            raw_conn.commit()
        finally:
            raw_conn.close()

        restore_result = manager.restore_file(entry_id)
        assert restore_result.is_success, restore_result.error_message

        mode = os.stat(original).st_mode & 0o7777
        # Suid/sgid/sticky bits must be stripped; only 0o755 allowed.
        assert mode & 0o7000 == 0, f"Setuid/setgid/sticky bits present: {oct(mode)}"
        assert mode == 0o755, f"Expected 0o755, got {oct(mode)}"

    def test_add_entry_masks_setuid_at_write_time(self, temp_dir):
        db_path = os.path.join(temp_dir, "qd.db")
        db = QuarantineDatabase(db_path=db_path, pool_size=0)
        try:
            entry_id = db.add_entry(
                original_path="/tmp/setuid.bin",
                quarantine_path="/tmp/q/setuid.bin",
                threat_name="T",
                file_size=100,
                file_hash="h" * 64,
                original_permissions=0o6755,  # setuid+setgid+rwxr-xr-x
            )
            assert entry_id is not None

            raw = sqlite3.connect(db_path)
            try:
                row = raw.execute(
                    "SELECT original_permissions FROM quarantine WHERE id = ?",
                    (entry_id,),
                ).fetchone()
            finally:
                raw.close()
            assert row[0] == 0o755, f"Expected stored value 0o755, got {oct(row[0])}"
        finally:
            db.close()

    def test_from_row_masks_setuid(self):
        """Even if a tampered DB row contains setuid bits, from_row strips them."""
        row = (
            1,
            "/orig/path",
            "/q/path",
            "T",
            "2024-01-01T00:00:00",
            100,
            "h" * 64,
            0o6755,  # tampered raw bits
        )
        entry = QuarantineEntry.from_row(row)
        assert entry.original_permissions == 0o755


class TestSchemaCheckConstraints:
    """Schema-level CHECK constraint must reject bogus permission values."""

    def test_schema_check_rejects_invalid_perms(self, temp_dir):
        db_path = os.path.join(temp_dir, "check.db")
        db = QuarantineDatabase(db_path=db_path, pool_size=0)
        try:
            raw = sqlite3.connect(db_path)
            try:
                with pytest.raises(sqlite3.IntegrityError):
                    raw.execute(
                        """
                        INSERT INTO quarantine
                        (original_path, quarantine_path, threat_name, detection_date,
                         file_size, file_hash, original_permissions)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("/o", "/q", "T", "2024-01-01T00:00:00", 100, "h", 1023),
                    )
            finally:
                raw.close()
        finally:
            db.close()

    def test_schema_check_rejects_invalid_state(self, temp_dir):
        db_path = os.path.join(temp_dir, "check2.db")
        db = QuarantineDatabase(db_path=db_path, pool_size=0)
        try:
            raw = sqlite3.connect(db_path)
            try:
                with pytest.raises(sqlite3.IntegrityError):
                    raw.execute(
                        """
                        INSERT INTO quarantine
                        (original_path, quarantine_path, threat_name, detection_date,
                         file_size, file_hash, original_permissions, state)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("/o", "/q2", "T", "2024-01-01T00:00:00", 100, "h", 0o644, "garbage"),
                    )
            finally:
                raw.close()
        finally:
            db.close()


class TestCrossFilesystemFallback:
    """When os.link returns EXDEV, we must take the NOFOLLOW-create + copy path."""

    def test_cross_filesystem_fallback(self, manager, temp_dir, monkeypatch):
        original = os.path.join(temp_dir, "files", "x.bin")
        content = b"cross-fs payload"
        _make_test_file(original, content)
        result = manager.quarantine_file(original, "T")
        assert result.is_success

        # Monkeypatch os.link to simulate EXDEV.
        real_link = os.link

        def fake_link(*args, **kwargs):
            raise OSError(18, "Invalid cross-device link")  # EXDEV

        monkeypatch.setattr(os, "link", fake_link)
        try:
            restore = manager.restore_file(result.entry.id)
            assert restore.is_success, restore.error_message
            # Restored file content matches original.
            with open(original, "rb") as f:
                assert f.read() == content
        finally:
            monkeypatch.setattr(os, "link", real_link)
