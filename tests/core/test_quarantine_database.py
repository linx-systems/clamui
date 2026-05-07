# ClamUI QuarantineDatabase Tests
"""Unit tests for the QuarantineDatabase and QuarantineEntry classes."""

import os
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.quarantine.database import (
    QuarantineDatabase,
    QuarantineEntry,
)


class TestQuarantineEntry:
    """Tests for the QuarantineEntry dataclass."""

    def test_to_dict(self):
        """Test QuarantineEntry.to_dict serialization."""
        entry = QuarantineEntry(
            id=1,
            original_path="/home/user/malware.exe",
            quarantine_path="/var/clamui/quarantine/abc123.quar",
            threat_name="Win.Trojan.Generic",
            detection_date="2024-01-15T10:30:00",
            file_size=1024,
            file_hash="abc123def456",
            original_permissions=0o755,
        )
        data = entry.to_dict()

        assert data["id"] == 1
        assert data["original_path"] == "/home/user/malware.exe"
        assert data["quarantine_path"] == "/var/clamui/quarantine/abc123.quar"
        assert data["threat_name"] == "Win.Trojan.Generic"
        assert data["detection_date"] == "2024-01-15T10:30:00"
        assert data["file_size"] == 1024
        assert data["file_hash"] == "abc123def456"
        assert data["original_permissions"] == 0o755

    def test_from_row(self):
        """Test QuarantineEntry.from_row deserialization."""
        row = (
            42,
            "/original/path/file.exe",
            "/quarantine/path/uuid.quar",
            "Eicar-Test-Signature",
            "2024-02-20T14:00:00",
            2048,
            "sha256hashvalue",
            0o644,
        )
        entry = QuarantineEntry.from_row(row)

        assert entry.id == 42
        assert entry.original_path == "/original/path/file.exe"
        assert entry.quarantine_path == "/quarantine/path/uuid.quar"
        assert entry.threat_name == "Eicar-Test-Signature"
        assert entry.detection_date == "2024-02-20T14:00:00"
        assert entry.file_size == 2048
        assert entry.file_hash == "sha256hashvalue"
        assert entry.original_permissions == 0o644

    def test_from_row_without_permissions_uses_default(self):
        """Test QuarantineEntry.from_row handles missing permissions (migration)."""
        # Simulate a row from an old database without the permissions column
        row = (
            42,
            "/original/path/file.exe",
            "/quarantine/path/uuid.quar",
            "Eicar-Test-Signature",
            "2024-02-20T14:00:00",
            2048,
            "sha256hashvalue",
        )
        entry = QuarantineEntry.from_row(row)

        # Should use default permissions of 0o644
        assert entry.original_permissions == 0o644

    def test_roundtrip_serialization(self):
        """Test that to_dict and from_row are consistent."""
        original = QuarantineEntry(
            id=99,
            original_path="/test/malware.bin",
            quarantine_path="/quarantine/test.quar",
            threat_name="TestThreat",
            detection_date="2024-03-10T08:15:30",
            file_size=4096,
            file_hash="roundtriphash123",
            original_permissions=0o755,
        )
        data = original.to_dict()

        # Simulate database row from dict values
        row = (
            data["id"],
            data["original_path"],
            data["quarantine_path"],
            data["threat_name"],
            data["detection_date"],
            data["file_size"],
            data["file_hash"],
            data["original_permissions"],
        )
        restored = QuarantineEntry.from_row(row)

        assert restored.id == original.id
        assert restored.original_path == original.original_path
        assert restored.quarantine_path == original.quarantine_path
        assert restored.threat_name == original.threat_name
        assert restored.detection_date == original.detection_date
        assert restored.file_size == original.file_size
        assert restored.file_hash == original.file_hash
        assert restored.original_permissions == original.original_permissions


class TestQuarantineDatabase:
    """Tests for the QuarantineDatabase class."""

    @pytest.fixture
    def temp_db_dir(self):
        """Create a temporary directory for database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def db(self, temp_db_dir):
        """Create a QuarantineDatabase with a temporary database."""
        db_path = os.path.join(temp_db_dir, "test_quarantine.db")
        database = QuarantineDatabase(db_path=db_path)
        yield database
        database.close()

    def test_init_creates_database_directory(self, temp_db_dir):
        """Test that QuarantineDatabase creates the database directory on init."""
        db_path = os.path.join(temp_db_dir, "subdir", "nested", "quarantine.db")
        _db = QuarantineDatabase(db_path=db_path)
        assert Path(db_path).parent.exists()
        _db.close()

    def test_init_with_default_directory(self, monkeypatch):
        """Test QuarantineDatabase uses XDG_DATA_HOME by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("XDG_DATA_HOME", tmpdir)
            db = QuarantineDatabase()
            expected_path = Path(tmpdir) / "clamui" / "quarantine.db"
            assert db._db_path == expected_path
            db.close()

    def test_init_creates_schema(self, db, temp_db_dir):
        """Test that database schema is created on init."""
        # Verify the table exists by querying it
        db_path = os.path.join(temp_db_dir, "test_quarantine.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='quarantine'"
        )
        result = cursor.fetchone()
        conn.close()
        assert result is not None
        assert result[0] == "quarantine"

    def test_add_entry(self, db):
        """Test adding a quarantine entry."""
        entry_id = db.add_entry(
            original_path="/home/user/infected.exe",
            quarantine_path="/quarantine/uuid1.quar",
            threat_name="Win.Malware.Test",
            file_size=1024,
            file_hash="testhash123",
        )

        assert entry_id is not None
        assert entry_id > 0

    def test_add_entry_sets_detection_date(self, db):
        """Test that add_entry automatically sets detection_date."""
        before = datetime.now()
        entry_id = db.add_entry(
            original_path="/test/file.exe",
            quarantine_path="/quarantine/file.quar",
            threat_name="TestThreat",
            file_size=512,
            file_hash="hash1",
        )
        after = datetime.now()

        entry = db.get_entry(entry_id)
        detection_time = datetime.fromisoformat(entry.detection_date)
        assert before <= detection_time <= after

    def test_add_entry_duplicate_quarantine_path_fails(self, db):
        """Test that adding duplicate quarantine_path fails."""
        db.add_entry(
            original_path="/path1/file.exe",
            quarantine_path="/quarantine/unique.quar",
            threat_name="Threat1",
            file_size=100,
            file_hash="hash1",
        )
        # Same quarantine_path should fail (UNIQUE constraint)
        result = db.add_entry(
            original_path="/path2/file.exe",
            quarantine_path="/quarantine/unique.quar",
            threat_name="Threat2",
            file_size=200,
            file_hash="hash2",
        )
        assert result is None

    def test_get_entry(self, db):
        """Test retrieving a specific entry by ID."""
        entry_id = db.add_entry(
            original_path="/home/user/test.exe",
            quarantine_path="/quarantine/test.quar",
            threat_name="TestThreat",
            file_size=2048,
            file_hash="abc123",
        )

        entry = db.get_entry(entry_id)
        assert entry is not None
        assert entry.id == entry_id
        assert entry.original_path == "/home/user/test.exe"
        assert entry.quarantine_path == "/quarantine/test.quar"
        assert entry.threat_name == "TestThreat"
        assert entry.file_size == 2048
        assert entry.file_hash == "abc123"

    def test_get_entry_not_found(self, db):
        """Test get_entry returns None for non-existent ID."""
        result = db.get_entry(999999)
        assert result is None

    def test_get_entry_by_original_path(self, db):
        """Test retrieving an entry by original path."""
        db.add_entry(
            original_path="/specific/original/path.exe",
            quarantine_path="/quarantine/specific.quar",
            threat_name="SpecificThreat",
            file_size=3072,
            file_hash="specifichash",
        )

        entry = db.get_entry_by_original_path("/specific/original/path.exe")
        assert entry is not None
        assert entry.original_path == "/specific/original/path.exe"
        assert entry.threat_name == "SpecificThreat"

    def test_get_entry_by_original_path_not_found(self, db):
        """Test get_entry_by_original_path returns None for non-existent path."""
        result = db.get_entry_by_original_path("/nonexistent/path.exe")
        assert result is None

    def test_get_all_entries_empty(self, db):
        """Test get_all_entries returns empty list when no entries exist."""
        entries = db.get_all_entries()
        assert entries == []

    def test_get_all_entries_returns_saved_entries(self, db):
        """Test get_all_entries returns previously saved entries."""
        db.add_entry(
            original_path="/file1.exe",
            quarantine_path="/quarantine/file1.quar",
            threat_name="Threat1",
            file_size=100,
            file_hash="hash1",
        )
        time.sleep(0.01)  # Ensure different timestamps
        db.add_entry(
            original_path="/file2.exe",
            quarantine_path="/quarantine/file2.quar",
            threat_name="Threat2",
            file_size=200,
            file_hash="hash2",
        )

        entries = db.get_all_entries()
        assert len(entries) == 2

    def test_get_all_entries_sorted_by_date_descending(self, db, temp_db_dir):
        """Test that get_all_entries returns entries sorted by date (newest first)."""
        # Insert entries with explicit dates via direct SQL
        db_path = os.path.join(temp_db_dir, "test_quarantine.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO quarantine
            (original_path, quarantine_path, threat_name, detection_date, file_size, file_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "/oldest.exe",
                "/quarantine/oldest.quar",
                "ThreatOld",
                "2024-01-01T10:00:00",
                100,
                "hash1",
            ),
        )
        conn.execute(
            """
            INSERT INTO quarantine
            (original_path, quarantine_path, threat_name, detection_date, file_size, file_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "/newest.exe",
                "/quarantine/newest.quar",
                "ThreatNew",
                "2024-03-01T10:00:00",
                300,
                "hash3",
            ),
        )
        conn.execute(
            """
            INSERT INTO quarantine
            (original_path, quarantine_path, threat_name, detection_date, file_size, file_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "/middle.exe",
                "/quarantine/middle.quar",
                "ThreatMid",
                "2024-02-01T10:00:00",
                200,
                "hash2",
            ),
        )
        conn.commit()
        conn.close()

        entries = db.get_all_entries()
        assert len(entries) == 3
        assert entries[0].original_path == "/newest.exe"
        assert entries[1].original_path == "/middle.exe"
        assert entries[2].original_path == "/oldest.exe"

    def test_remove_entry(self, db):
        """Test removing a specific entry."""
        entry_id = db.add_entry(
            original_path="/to/remove.exe",
            quarantine_path="/quarantine/remove.quar",
            threat_name="RemoveThreat",
            file_size=512,
            file_hash="removehash",
        )

        # Verify it exists
        assert db.get_entry(entry_id) is not None

        # Remove it
        result = db.remove_entry(entry_id)
        assert result is True

        # Should be gone
        assert db.get_entry(entry_id) is None

    def test_remove_entry_not_found(self, db):
        """Test remove_entry returns False for non-existent ID."""
        result = db.remove_entry(999999)
        assert result is False

    def test_get_total_size(self, db):
        """Test calculating total size of quarantined files."""
        db.add_entry(
            original_path="/file1.exe",
            quarantine_path="/quarantine/file1.quar",
            threat_name="Threat1",
            file_size=1000,
            file_hash="hash1",
        )
        db.add_entry(
            original_path="/file2.exe",
            quarantine_path="/quarantine/file2.quar",
            threat_name="Threat2",
            file_size=2000,
            file_hash="hash2",
        )
        db.add_entry(
            original_path="/file3.exe",
            quarantine_path="/quarantine/file3.quar",
            threat_name="Threat3",
            file_size=3000,
            file_hash="hash3",
        )

        total = db.get_total_size()
        assert total == 6000

    def test_get_total_size_empty(self, db):
        """Test get_total_size returns 0 when no entries exist."""
        total = db.get_total_size()
        assert total == 0

    def test_get_entry_count(self, db):
        """Test get_entry_count returns correct count."""
        assert db.get_entry_count() == 0

        for i in range(5):
            db.add_entry(
                original_path=f"/file{i}.exe",
                quarantine_path=f"/quarantine/file{i}.quar",
                threat_name=f"Threat{i}",
                file_size=100 * i,
                file_hash=f"hash{i}",
            )

        assert db.get_entry_count() == 5

    def test_get_old_entries(self, db, temp_db_dir):
        """Test getting entries older than specified days."""
        db_path = os.path.join(temp_db_dir, "test_quarantine.db")
        conn = sqlite3.connect(db_path)

        # Old entry (60 days ago)
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        conn.execute(
            """
            INSERT INTO quarantine
            (original_path, quarantine_path, threat_name, detection_date, file_size, file_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("/old.exe", "/quarantine/old.quar", "OldThreat", old_date, 100, "oldhash"),
        )

        # Recent entry (5 days ago)
        recent_date = (datetime.now() - timedelta(days=5)).isoformat()
        conn.execute(
            """
            INSERT INTO quarantine
            (original_path, quarantine_path, threat_name, detection_date, file_size, file_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "/recent.exe",
                "/quarantine/recent.quar",
                "RecentThreat",
                recent_date,
                200,
                "recenthash",
            ),
        )
        conn.commit()
        conn.close()

        # Get entries older than 30 days
        old_entries = db.get_old_entries(days=30)
        assert len(old_entries) == 1
        assert old_entries[0].original_path == "/old.exe"

    def test_get_old_entries_empty(self, db):
        """Test get_old_entries returns empty list when no old entries exist."""
        # Add only recent entry
        db.add_entry(
            original_path="/recent.exe",
            quarantine_path="/quarantine/recent.quar",
            threat_name="RecentThreat",
            file_size=100,
            file_hash="hash",
        )

        old_entries = db.get_old_entries(days=30)
        assert len(old_entries) == 0


class TestQuarantineDatabasePermissionMasking:
    """Regression tests for VULN-004 — defense-in-depth permission masking.

    Original ``original_permissions`` values must be masked to ``& 0o777``
    on both write and read paths so that setuid/setgid/sticky bits cannot
    propagate from a tampered DB row into a restored file's mode.
    """

    @pytest.fixture
    def temp_db_dir(self):
        """Create a temporary directory for database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def db(self, temp_db_dir):
        """Create a QuarantineDatabase with a temporary database."""
        db_path = os.path.join(temp_db_dir, "test_quarantine.db")
        database = QuarantineDatabase(db_path=db_path)
        yield database
        database.close()

    def test_add_entry_masks_high_permission_bits(self, db, temp_db_dir):
        """add_entry must mask away setuid/setgid/sticky bits before insert."""
        db.add_entry(
            original_path="/home/user/setuid-malware",
            quarantine_path="/quarantine/setuid.quar",
            threat_name="SetuidThreat",
            file_size=4096,
            file_hash="setuidhash",
            original_permissions=0o6755,  # setuid + setgid + 0o755
        )

        # Read raw column value directly to verify storage was masked.
        db_path = os.path.join(temp_db_dir, "test_quarantine.db")
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT original_permissions FROM quarantine WHERE quarantine_path = ?",
                ("/quarantine/setuid.quar",),
            )
            (stored,) = cursor.fetchone()
        finally:
            conn.close()

        assert stored == 0o755, f"DB stored {oct(stored)}, expected {oct(0o755)}"

    def test_from_row_masks_high_permission_bits(self, db, temp_db_dir):
        """from_row must mask high bits even if the DB was tampered."""
        # Bypass the API and write a tampered row directly.
        db_path = os.path.join(temp_db_dir, "test_quarantine.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA ignore_check_constraints = ON")
            conn.execute(
                """
                INSERT INTO quarantine
                (original_path, quarantine_path, threat_name, detection_date,
                 file_size, file_hash, original_permissions)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "/home/user/tampered",
                    "/quarantine/tampered.quar",
                    "TamperedThreat",
                    "2026-04-30T00:00:00",
                    1024,
                    "tamperedhash",
                    0o6755,  # tampered: setuid + setgid + 755
                ),
            )
            conn.commit()
        finally:
            conn.close()

        entry = db.get_entry_by_original_path("/home/user/tampered")
        assert entry is not None
        # The materialized entry must NOT carry the high bits.
        assert entry.original_permissions == 0o755, (
            f"from_row returned {oct(entry.original_permissions)}, expected {oct(0o755)}"
        )

    def test_from_row_preserves_legacy_default_when_column_missing(self):
        """Legacy DB rows missing the column still default to 0o644 (regression guard)."""
        row = (
            1,
            "/legacy/file",
            "/quarantine/legacy.quar",
            "LegacyThreat",
            "2024-01-01T00:00:00",
            512,
            "legacyhash",
            # No original_permissions column
        )
        entry = QuarantineEntry.from_row(row)
        assert entry.original_permissions == 0o644

    def test_from_row_handles_none_permissions(self):
        """A NULL original_permissions value (corrupted row) must default safely."""
        row = (
            1,
            "/null/file",
            "/quarantine/null.quar",
            "NullThreat",
            "2024-01-01T00:00:00",
            512,
            "nullhash",
            None,
        )
        entry = QuarantineEntry.from_row(row)
        # Implementation may default to 0o644 — masking a None must NOT crash.
        assert entry.original_permissions == 0o644


class TestQuarantineDatabaseErrorLogging:
    """Tests for error logging in QuarantineDatabase."""

    @pytest.fixture
    def temp_db_dir(self):
        """Create a temporary directory for database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def db(self, temp_db_dir):
        """Create a QuarantineDatabase with a temporary database."""
        db_path = os.path.join(temp_db_dir, "test_quarantine.db")
        database = QuarantineDatabase(db_path=db_path)
        yield database
        database.close()

    def test_add_entry_logs_error_on_failure(self, db, caplog):
        """Test that add_entry logs error when database operation fails."""
        import logging

        # Add a valid entry first
        db.add_entry(
            original_path="/file1.exe",
            quarantine_path="/quarantine/unique.quar",
            threat_name="Threat1",
            file_size=100,
            file_hash="hash1",
        )

        # Try to add duplicate (violates UNIQUE constraint)
        with caplog.at_level(logging.ERROR):
            result = db.add_entry(
                original_path="/file2.exe",
                quarantine_path="/quarantine/unique.quar",  # Same quarantine_path
                threat_name="Threat2",
                file_size=200,
                file_hash="hash2",
            )

        assert result is None
        assert "Failed to add quarantine entry" in caplog.text
        assert "/file2.exe" in caplog.text

    def test_get_entry_logs_error_on_database_error(self, temp_db_dir, caplog):
        """Test that get_entry logs error when database is corrupted."""
        import logging

        # Create a corrupted database file
        db_path = os.path.join(temp_db_dir, "corrupted.db")
        with open(db_path, "w") as f:
            f.write("not a valid sqlite database")

        # Try to use the corrupted database
        with caplog.at_level(logging.ERROR):
            db = QuarantineDatabase(db_path=db_path, pool_size=0)
            result = db.get_entry(1)

        # Should log error about init and/or get_entry failure
        assert result is None
        assert "Failed to" in caplog.text

    def test_remove_entry_logs_error_on_failure(self, temp_db_dir, caplog):
        """Test that remove_entry logs error when operation fails."""
        import logging

        # Create a corrupted database file
        db_path = os.path.join(temp_db_dir, "corrupted.db")
        with open(db_path, "w") as f:
            f.write("not a valid sqlite database")

        with caplog.at_level(logging.ERROR):
            db = QuarantineDatabase(db_path=db_path, pool_size=0)
            result = db.remove_entry(1)

        assert result is False
        assert "Failed to" in caplog.text

    def test_init_database_logs_error_on_corrupted_db(self, temp_db_dir, caplog):
        """Test that _init_database logs error when database is corrupted."""
        import logging

        # Create a corrupted database file
        db_path = os.path.join(temp_db_dir, "corrupted.db")
        with open(db_path, "w") as f:
            f.write("this is not a valid sqlite database file")

        with caplog.at_level(logging.ERROR):
            QuarantineDatabase(db_path=db_path, pool_size=0)

        assert "Failed to initialize quarantine database" in caplog.text
        assert db_path in caplog.text
