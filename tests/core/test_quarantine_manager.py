# ClamUI QuarantineManager Tests
"""Unit tests for the QuarantineManager class."""

import os
import tempfile
from pathlib import Path

import pytest

# Import directly - quarantine modules use GLib only for async callbacks,
# which are mocked in tests via GLib.idle_add patching
from src.core.quarantine.database import QuarantineEntry
from src.core.quarantine.manager import (
    QuarantineManager,
    QuarantineResult,
    QuarantineStatus,
)


class TestQuarantineStatus:
    """Tests for the QuarantineStatus enum."""

    def test_quarantine_status_values(self):
        """Test QuarantineStatus enum has expected values."""
        assert QuarantineStatus.SUCCESS.value == "success"
        assert QuarantineStatus.FILE_NOT_FOUND.value == "file_not_found"
        assert QuarantineStatus.PERMISSION_DENIED.value == "permission_denied"
        assert QuarantineStatus.DISK_FULL.value == "disk_full"
        assert QuarantineStatus.DATABASE_ERROR.value == "database_error"
        assert QuarantineStatus.ALREADY_QUARANTINED.value == "already_quarantined"
        assert QuarantineStatus.ENTRY_NOT_FOUND.value == "entry_not_found"
        assert QuarantineStatus.RESTORE_DESTINATION_EXISTS.value == "restore_destination_exists"
        assert QuarantineStatus.INVALID_RESTORE_PATH.value == "invalid_restore_path"
        assert QuarantineStatus.ERROR.value == "error"


class TestQuarantineResult:
    """Tests for the QuarantineResult dataclass."""

    def test_quarantine_result_success(self):
        """Test QuarantineResult with successful status."""
        entry = QuarantineEntry(
            id=1,
            original_path="/test/file.exe",
            quarantine_path="/quarantine/file.quar",
            threat_name="TestThreat",
            detection_date="2024-01-01T10:00:00",
            file_size=1024,
            file_hash="abc123",
            original_permissions=0o644,
        )
        result = QuarantineResult(
            status=QuarantineStatus.SUCCESS,
            entry=entry,
            error_message=None,
        )

        assert result.is_success is True
        assert result.status == QuarantineStatus.SUCCESS
        assert result.entry == entry
        assert result.error_message is None

    def test_quarantine_result_failure(self):
        """Test QuarantineResult with failure status."""
        result = QuarantineResult(
            status=QuarantineStatus.FILE_NOT_FOUND,
            entry=None,
            error_message="File not found: /test/file.exe",
        )

        assert result.is_success is False
        assert result.status == QuarantineStatus.FILE_NOT_FOUND
        assert result.entry is None
        assert result.error_message == "File not found: /test/file.exe"

    def test_is_success_property_all_statuses(self):
        """Test is_success property returns correct values for all statuses."""
        # Only SUCCESS should return True
        for status in QuarantineStatus:
            result = QuarantineResult(
                status=status,
                entry=None,
                error_message=None,
            )
            if status == QuarantineStatus.SUCCESS:
                assert result.is_success is True
            else:
                assert result.is_success is False


class TestQuarantineManager:
    """Tests for the QuarantineManager class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=False,  # Disable for faster tests
        )
        yield mgr
        mgr._database.close()

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a temporary test file."""
        file_path = os.path.join(temp_dir, "test_infected.exe")
        with open(file_path, "wb") as f:
            f.write(b"This is test malware content for testing purposes.")
        return file_path

    def test_init_creates_quarantine_directory(self, temp_dir):
        """Test that QuarantineManager creates the quarantine directory on init."""
        quarantine_dir = os.path.join(temp_dir, "subdir", "quarantine")
        db_path = os.path.join(temp_dir, "subdir", "db.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=False,
        )
        assert Path(quarantine_dir).exists()
        mgr._database.close()

    def test_quarantine_directory_property(self, manager, temp_dir):
        """Test quarantine_directory property returns correct path."""
        expected = Path(temp_dir) / "quarantine"
        assert manager.quarantine_directory == expected

    def test_quarantine_file_success(self, manager, test_file):
        """Test successfully quarantining a file."""
        result = manager.quarantine_file(test_file, "Win.Trojan.Test")

        assert result.is_success is True
        assert result.status == QuarantineStatus.SUCCESS
        assert result.entry is not None
        assert result.entry.original_path == str(Path(test_file).resolve())
        assert result.entry.threat_name == "Win.Trojan.Test"
        assert result.entry.file_size > 0
        assert len(result.entry.file_hash) == 64  # SHA256 hex length
        assert result.error_message is None

        # Verify original file is moved
        assert not Path(test_file).exists()

        # Verify file is in quarantine
        assert Path(result.entry.quarantine_path).exists()

    def test_quarantine_file_sets_permissions(self, manager, test_file):
        """Test quarantined file has restrictive permissions."""
        result = manager.quarantine_file(test_file, "TestThreat")

        assert result.is_success is True

        # Check quarantined file permissions (should be 0o400 - read-only for owner)
        quarantine_path = Path(result.entry.quarantine_path)
        mode = quarantine_path.stat().st_mode & 0o777
        assert mode == 0o400

    def test_quarantine_file_directory_permissions(self, manager, test_file):
        """Test quarantine directory has restrictive permissions."""
        result = manager.quarantine_file(test_file, "TestThreat")

        assert result.is_success is True

        # Check quarantine directory permissions (should be 0o700 - owner only)
        mode = manager.quarantine_directory.stat().st_mode & 0o777
        assert mode == 0o700

    def test_quarantine_file_file_not_found(self, manager):
        """Test quarantining a file that doesn't exist."""
        result = manager.quarantine_file("/nonexistent/file.exe", "TestThreat")

        assert result.is_success is False
        assert result.status == QuarantineStatus.FILE_NOT_FOUND
        assert result.entry is None
        assert result.error_message is not None

    def test_quarantine_file_duplicate_path_allowed(self, manager, test_file):
        """Test quarantining a file at the same path multiple times (allowed)."""
        # First quarantine
        result1 = manager.quarantine_file(test_file, "TestThreat")
        assert result1.is_success is True
        entry1_id = result1.entry.id

        # Create a new file at the same path
        with open(test_file, "wb") as f:
            f.write(b"New content")

        # Quarantine again (same original path) - should succeed with new entry
        result2 = manager.quarantine_file(test_file, "TestThreat2")

        assert result2.is_success is True
        assert result2.entry is not None
        # Should have different entry IDs (unique entries)
        assert result2.entry.id != entry1_id
        # Both entries can have the same original_path
        assert result2.entry.original_path == result1.entry.original_path

    def test_quarantine_file_hash_calculation(self, manager, temp_dir):
        """Test that file hash is correctly calculated before quarantine."""
        # Create file with known content
        test_file = os.path.join(temp_dir, "hash_test.exe")
        content = b"Known content for hash testing"
        with open(test_file, "wb") as f:
            f.write(content)

        # Calculate expected hash
        import hashlib

        expected_hash = hashlib.sha256(content).hexdigest()

        result = manager.quarantine_file(test_file, "TestThreat")

        assert result.is_success is True
        assert result.entry.file_hash == expected_hash

    def test_quarantine_file_database_entry_created(self, manager, test_file):
        """Test that database entry is created on quarantine."""
        result = manager.quarantine_file(test_file, "TestThreat")

        assert result.is_success is True
        assert result.entry.id is not None

        # Verify entry can be retrieved from database
        entry = manager.get_entry(result.entry.id)
        assert entry is not None
        assert entry.original_path == result.entry.original_path


class TestQuarantineManagerRestore:
    """Tests for the QuarantineManager restore operations."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=False,
        )
        yield mgr
        mgr._database.close()

    @pytest.fixture
    def quarantined_file(self, manager, temp_dir):
        """Create and quarantine a test file."""
        file_path = os.path.join(temp_dir, "files", "test.exe")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(b"Test content for restore testing")

        result = manager.quarantine_file(file_path, "TestThreat")
        assert result.is_success is True
        return result.entry

    def test_restore_file_success(self, manager, quarantined_file):
        """Test successfully restoring a quarantined file."""
        result = manager.restore_file(quarantined_file.id)

        assert result.is_success is True
        assert result.status == QuarantineStatus.SUCCESS
        assert result.entry is not None

        # Verify file is restored to original location
        assert Path(quarantined_file.original_path).exists()

        # Verify quarantine file is removed
        assert not Path(quarantined_file.quarantine_path).exists()

        # Verify database entry is removed
        assert manager.get_entry(quarantined_file.id) is None

    def test_restore_file_entry_not_found(self, manager):
        """Test restoring a file with non-existent entry ID."""
        result = manager.restore_file(999999)

        assert result.is_success is False
        assert result.status == QuarantineStatus.ENTRY_NOT_FOUND
        assert result.error_message is not None

    def test_restore_file_destination_exists(self, manager, quarantined_file):
        """Test restoring a file when destination already exists."""
        # Create a file at the original location
        Path(quarantined_file.original_path).parent.mkdir(parents=True, exist_ok=True)
        with open(quarantined_file.original_path, "wb") as f:
            f.write(b"Existing file content")

        result = manager.restore_file(quarantined_file.id)

        assert result.is_success is False
        assert result.status == QuarantineStatus.RESTORE_DESTINATION_EXISTS
        assert result.error_message is not None

    def test_restore_file_creates_parent_directory(self, manager, temp_dir):
        """Test restore creates parent directory if it doesn't exist."""
        # Create and quarantine a file in a nested directory
        nested_dir = os.path.join(temp_dir, "nested", "deep", "path")
        os.makedirs(nested_dir, exist_ok=True)
        file_path = os.path.join(nested_dir, "test.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content")

        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True

        # Remove the nested directory
        import shutil

        shutil.rmtree(os.path.join(temp_dir, "nested"))

        # Restore should recreate the directory structure
        result = manager.restore_file(qresult.entry.id)

        assert result.is_success is True
        assert Path(file_path).exists()

    def test_restore_to_protected_directory_rejected(self, manager, temp_dir):
        """Test restore to protected system directory is rejected."""
        # Create and quarantine a file
        file_path = os.path.join(temp_dir, "test.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content")

        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True

        # Manually update the database to have a protected path
        # This simulates a corrupted/manipulated database
        import sqlite3

        db_path = manager._database._db_path
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE quarantine SET original_path = ? WHERE id = ?",
            ("/etc/malicious.conf", qresult.entry.id),
        )
        conn.commit()
        conn.close()

        # Attempt to restore should be rejected
        result = manager.restore_file(qresult.entry.id)

        assert result.is_success is False
        assert result.status == QuarantineStatus.INVALID_RESTORE_PATH
        assert result.error_message is not None
        assert "protected" in result.error_message.lower()

    def test_restore_to_etc_directory_rejected(self, manager, temp_dir):
        """Test restore to /etc directory is rejected."""
        # Create and quarantine a file
        file_path = os.path.join(temp_dir, "test.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content")

        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True

        # Update database to /etc path
        import sqlite3

        db_path = manager._database._db_path
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE quarantine SET original_path = ? WHERE id = ?",
            ("/etc/passwd", qresult.entry.id),
        )
        conn.commit()
        conn.close()

        result = manager.restore_file(qresult.entry.id)

        assert result.is_success is False
        assert result.status == QuarantineStatus.INVALID_RESTORE_PATH
        assert "/etc" in result.error_message

    def test_restore_to_var_directory_rejected(self, manager, temp_dir):
        """Test restore to /var directory is rejected."""
        # Create and quarantine a file
        file_path = os.path.join(temp_dir, "test.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content")

        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True

        # Update database to /var path
        import sqlite3

        db_path = manager._database._db_path
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE quarantine SET original_path = ? WHERE id = ?",
            ("/var/spool/malicious", qresult.entry.id),
        )
        conn.commit()
        conn.close()

        result = manager.restore_file(qresult.entry.id)

        assert result.is_success is False
        assert result.status == QuarantineStatus.INVALID_RESTORE_PATH
        assert "/var" in result.error_message


class TestQuarantineManagerPermissions:
    """Tests for quarantine/restore file permissions preservation."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=False,
        )
        yield mgr
        mgr._database.close()

    def test_quarantine_captures_original_permissions(self, manager, temp_dir):
        """Test that quarantining a file captures its original permissions."""
        # Create a file with specific permissions
        file_path = os.path.join(temp_dir, "executable.sh")
        with open(file_path, "wb") as f:
            f.write(b"#!/bin/bash\necho 'test'")
        os.chmod(file_path, 0o755)

        result = manager.quarantine_file(file_path, "TestThreat")

        assert result.is_success is True
        assert result.entry.original_permissions == 0o755

    def test_quarantine_captures_readonly_permissions(self, manager, temp_dir):
        """Test that quarantining a read-only file captures its permissions."""
        file_path = os.path.join(temp_dir, "readonly.txt")
        with open(file_path, "wb") as f:
            f.write(b"Read-only content")
        os.chmod(file_path, 0o444)

        result = manager.quarantine_file(file_path, "TestThreat")

        assert result.is_success is True
        assert result.entry.original_permissions == 0o444

    def test_restore_restores_original_permissions(self, manager, temp_dir):
        """Test that restoring a file restores its original permissions."""
        # Create a file with executable permissions
        file_path = os.path.join(temp_dir, "files", "script.sh")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(b"#!/bin/bash\necho 'test'")
        os.chmod(file_path, 0o755)

        # Quarantine the file
        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True
        assert qresult.entry.original_permissions == 0o755

        # Restore the file
        restore_result = manager.restore_file(qresult.entry.id)
        assert restore_result.is_success is True

        # Verify restored file has original permissions
        restored_mode = os.stat(file_path).st_mode & 0o777
        assert restored_mode == 0o755

    def test_restore_restores_readonly_permissions(self, manager, temp_dir):
        """Test that restoring a read-only file restores its permissions."""
        file_path = os.path.join(temp_dir, "files", "readonly.txt")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(b"Read-only content")
        os.chmod(file_path, 0o444)

        # Quarantine the file
        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True

        # Restore the file
        restore_result = manager.restore_file(qresult.entry.id)
        assert restore_result.is_success is True

        # Verify restored file has original read-only permissions
        restored_mode = os.stat(file_path).st_mode & 0o777
        assert restored_mode == 0o444

    def test_restore_restores_group_permissions(self, manager, temp_dir):
        """Test that group permissions are preserved on restore."""
        file_path = os.path.join(temp_dir, "files", "group_readable.txt")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(b"Group readable content")
        os.chmod(file_path, 0o640)

        # Quarantine and restore
        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True

        restore_result = manager.restore_file(qresult.entry.id)
        assert restore_result.is_success is True

        # Verify permissions
        restored_mode = os.stat(file_path).st_mode & 0o777
        assert restored_mode == 0o640

    def test_permissions_stored_in_database(self, manager, temp_dir):
        """Test that permissions are correctly stored and retrieved from database."""
        file_path = os.path.join(temp_dir, "test.sh")
        with open(file_path, "wb") as f:
            f.write(b"#!/bin/bash")
        os.chmod(file_path, 0o700)

        # Quarantine
        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True
        entry_id = qresult.entry.id

        # Retrieve from database and verify permissions
        entry = manager.get_entry(entry_id)
        assert entry is not None
        assert entry.original_permissions == 0o700

    def test_restore_strips_setuid_bits_from_destination(self, manager, temp_dir):
        """Regression for VULN-004: a tampered DB row with setuid/setgid/sticky
        bits MUST NOT propagate those bits onto a restored file's mode.

        Skipped on filesystems that don't honor setuid bits (e.g. some tmpfs
        configs and unprivileged sandboxes).
        """
        import sqlite3
        import stat as stat_module

        # Quick capability probe: write a temp file and try to chmod 0o4755.
        probe = os.path.join(temp_dir, ".setuid_probe")
        with open(probe, "wb") as f:
            f.write(b"probe")
        try:
            os.chmod(probe, 0o4755)
            mode = os.stat(probe).st_mode & 0o7777
            setuid_supported = bool(mode & stat_module.S_ISUID)
        except OSError:
            setuid_supported = False
        finally:
            if os.path.exists(probe):
                os.unlink(probe)
        if not setuid_supported:
            pytest.skip("filesystem does not honor setuid bits")

        # Create and quarantine a normal file.
        file_path = os.path.join(temp_dir, "files", "victim.sh")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(b"#!/bin/bash\necho hi")
        os.chmod(file_path, 0o755)

        qresult = manager.quarantine_file(file_path, "TestThreat")
        assert qresult.is_success is True
        entry_id = qresult.entry.id

        # Tamper with the DB to inject high-bit permissions (setuid+setgid+755).
        db_path = manager._database._db_path
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA ignore_check_constraints = ON")
            conn.execute(
                "UPDATE quarantine SET original_permissions = ? WHERE id = ?",
                (0o6755, entry_id),
            )
            conn.commit()
        finally:
            conn.close()

        # Restore — masking must strip the high bits.
        restore_result = manager.restore_file(entry_id)
        assert restore_result.is_success is True

        restored_mode = os.stat(file_path).st_mode & 0o7777
        assert restored_mode == 0o755, (
            f"Restored file mode is {oct(restored_mode)}; setuid/setgid leaked from tampered DB row"
        )


class TestQuarantineManagerDelete:
    """Tests for the QuarantineManager delete operations."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
        )
        yield mgr
        mgr._database.close()

    @pytest.fixture
    def quarantined_file(self, manager, temp_dir):
        """Create and quarantine a test file."""
        file_path = os.path.join(temp_dir, "test_delete.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content for delete testing")

        result = manager.quarantine_file(file_path, "TestThreat")
        assert result.is_success is True
        return result.entry

    def test_delete_file_success(self, manager, quarantined_file):
        """Test successfully deleting a quarantined file."""
        result = manager.delete_file(quarantined_file.id)

        assert result.is_success is True
        assert result.status == QuarantineStatus.SUCCESS
        assert result.entry is not None

        # Verify quarantine file is deleted
        assert not Path(quarantined_file.quarantine_path).exists()

        # Verify database entry is removed
        assert manager.get_entry(quarantined_file.id) is None

    def test_delete_file_entry_not_found(self, manager):
        """Test deleting a file with non-existent entry ID."""
        result = manager.delete_file(999999)

        assert result.is_success is False
        assert result.status == QuarantineStatus.ENTRY_NOT_FOUND
        assert result.error_message is not None

    def test_delete_file_permanently_removes(self, manager, quarantined_file):
        """Test that delete permanently removes the file."""
        quarantine_path = Path(quarantined_file.quarantine_path)
        assert quarantine_path.exists()

        result = manager.delete_file(quarantined_file.id)
        assert result.is_success is True

        # File should be completely gone
        assert not quarantine_path.exists()


class TestQuarantineManagerDatabaseFailure:
    """Tests for quarantine rollback when database operations fail."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
        )
        yield mgr
        mgr._database.close()

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a temporary test file."""
        file_path = os.path.join(temp_dir, "test_infected.exe")
        with open(file_path, "wb") as f:
            f.write(b"This is test malware content for testing purposes.")
        return file_path

    def test_database_failure_restores_file(self, manager, test_file):
        """Test that file is restored when database add_entry fails."""
        from unittest.mock import patch

        original_path = Path(test_file).resolve()
        original_content = original_path.read_bytes()

        # Mock the database add_entry to simulate failure
        with patch.object(manager._database, "add_entry", return_value=None):
            result = manager.quarantine_file(test_file, "TestThreat")

        # Should return database error
        assert result.is_success is False
        assert result.status == QuarantineStatus.DATABASE_ERROR
        assert result.entry is None
        assert "Failed to record quarantine entry" in result.error_message
        assert "restored to original location" in result.error_message

        # File should be restored to original location
        assert original_path.exists()
        assert original_path.read_bytes() == original_content

        # No entries should be in the database
        assert manager.get_all_entries() == []

    def test_database_failure_reports_orphan_on_rollback_failure(self, manager, test_file):
        """Test that orphaned file is reported when both DB and rollback fail."""
        from unittest.mock import MagicMock, patch

        original_path = Path(test_file).resolve()

        # Mock both database and file handler to simulate cascading failure
        with (
            patch.object(manager._database, "add_entry", return_value=None),
            patch.object(manager._file_handler, "restore_from_quarantine") as mock_restore,
        ):
            # Simulate restore failure
            mock_result = MagicMock()
            mock_result.is_success = False
            mock_result.error_message = "Simulated restore failure"
            mock_restore.return_value = mock_result

            result = manager.quarantine_file(test_file, "TestThreat")

        # Should return database error with orphan warning
        assert result.is_success is False
        assert result.status == QuarantineStatus.DATABASE_ERROR
        assert "Rollback also failed" in result.error_message
        assert "orphaned" in result.error_message

        # Original file should NOT exist (it was moved)
        assert not original_path.exists()

    def test_database_failure_with_successful_rollback_logs_info(self, manager, test_file, caplog):
        """Test that successful rollback is logged at INFO level."""
        import logging
        from unittest.mock import patch

        with (
            caplog.at_level(logging.INFO, logger="src.core.quarantine.manager"),
            patch.object(manager._database, "add_entry", return_value=None),
        ):
            result = manager.quarantine_file(test_file, "TestThreat")

        assert result.is_success is False
        # Check that rollback success was logged
        assert any("Successfully rolled back" in record.message for record in caplog.records)

    def test_database_failure_with_failed_rollback_logs_critical(self, manager, test_file, caplog):
        """Test that failed rollback is logged at CRITICAL level."""
        import logging
        from unittest.mock import MagicMock, patch

        with (
            caplog.at_level(logging.CRITICAL, logger="src.core.quarantine.manager"),
            patch.object(manager._database, "add_entry", return_value=None),
            patch.object(manager._file_handler, "restore_from_quarantine") as mock_restore,
        ):
            # Simulate restore failure
            mock_result = MagicMock()
            mock_result.is_success = False
            mock_result.error_message = "Permission denied"
            mock_restore.return_value = mock_result

            result = manager.quarantine_file(test_file, "TestThreat")

        assert result.is_success is False
        # Check that orphaned file was logged at CRITICAL level
        assert any(
            "ORPHANED QUARANTINE FILE" in record.message
            for record in caplog.records
            if record.levelno == logging.CRITICAL
        )

    def test_database_failure_preserves_file_permissions(self, manager, temp_dir):
        """Test that restored file has original permissions after rollback."""
        from unittest.mock import patch

        # Create file with specific permissions
        file_path = os.path.join(temp_dir, "executable.sh")
        with open(file_path, "wb") as f:
            f.write(b"#!/bin/bash\necho 'test'")
        os.chmod(file_path, 0o755)

        # Mock database failure
        with patch.object(manager._database, "add_entry", return_value=None):
            result = manager.quarantine_file(file_path, "TestThreat")

        assert result.is_success is False

        # File should be restored with original permissions
        restored_mode = os.stat(file_path).st_mode & 0o777
        assert restored_mode == 0o755


class TestQuarantineManagerQueries:
    """Tests for the QuarantineManager query operations."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=False,
        )
        yield mgr
        mgr._database.close()

    def test_get_all_entries(self, manager, temp_dir):
        """Test retrieving all quarantined entries."""
        # Initially empty
        entries = manager.get_all_entries()
        assert entries == []

        # Add some entries
        for i in range(3):
            file_path = os.path.join(temp_dir, f"test_{i}.exe")
            with open(file_path, "wb") as f:
                f.write(b"Test content")
            manager.quarantine_file(file_path, f"Threat{i}")

        # Verify all entries are retrieved
        entries = manager.get_all_entries()
        assert len(entries) == 3


class TestQuarantineManagerVerifyEntry:
    """Tests for the QuarantineManager verify_entry method."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
        )
        yield mgr
        mgr._database.close()

    @pytest.fixture
    def quarantined_file(self, manager, temp_dir):
        """Create and quarantine a test file."""
        file_path = os.path.join(temp_dir, "test.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content for verify testing")

        result = manager.quarantine_file(file_path, "TestThreat")
        assert result.is_success is True
        return result.entry

    def test_verify_entry_exists(self, manager, quarantined_file):
        """Test verify_entry returns True when file exists."""
        exists, error = manager.verify_entry(quarantined_file.id)

        assert exists is True
        assert error is None

    def test_verify_entry_not_found(self, manager):
        """Test verify_entry returns False for non-existent entry."""
        exists, error = manager.verify_entry(999999)

        assert exists is False
        assert error is not None
        assert "not found" in error.lower()

    def test_verify_entry_file_missing(self, manager, quarantined_file):
        """Test verify_entry returns False when file is missing from disk."""
        # Remove the quarantine file manually
        quarantine_path = Path(quarantined_file.quarantine_path)
        quarantine_path.unlink()

        exists, error = manager.verify_entry(quarantined_file.id)

        assert exists is False
        assert error is not None
        assert "missing" in error.lower()


class TestQuarantineManagerCleanupOrphaned:
    """Tests for the QuarantineManager cleanup_orphaned_entries method."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=False,
        )
        yield mgr
        mgr._database.close()

    def test_cleanup_orphaned_entries_empty(self, manager):
        """Test cleanup_orphaned_entries returns 0 when no entries exist."""
        removed = manager.cleanup_orphaned_entries()
        assert removed == 0

    def test_cleanup_orphaned_entries_no_orphans(self, manager, temp_dir):
        """Test cleanup_orphaned_entries returns 0 when all files exist."""
        # Create and quarantine some files
        for i in range(3):
            file_path = os.path.join(temp_dir, f"test_{i}.exe")
            with open(file_path, "wb") as f:
                f.write(b"Test content")
            manager.quarantine_file(file_path, f"Threat{i}")

        removed = manager.cleanup_orphaned_entries()
        assert removed == 0
        assert len(manager.get_all_entries()) == 3

    def test_cleanup_orphaned_entries_removes_orphans(self, manager, temp_dir):
        """Test cleanup_orphaned_entries removes entries with missing files."""
        # Create and quarantine some files
        entries = []
        for i in range(3):
            file_path = os.path.join(temp_dir, f"test_{i}.exe")
            with open(file_path, "wb") as f:
                f.write(b"Test content")
            result = manager.quarantine_file(file_path, f"Threat{i}")
            entries.append(result.entry)

        # Manually remove one quarantine file to create an orphan
        Path(entries[1].quarantine_path).unlink()

        removed = manager.cleanup_orphaned_entries()
        assert removed == 1
        assert len(manager.get_all_entries()) == 2

        # Verify the correct entry was removed
        assert manager.get_entry(entries[0].id) is not None
        assert manager.get_entry(entries[1].id) is None  # Orphan removed
        assert manager.get_entry(entries[2].id) is not None

    def test_cleanup_orphaned_entries_removes_all_orphans(self, manager, temp_dir):
        """Test cleanup_orphaned_entries removes all orphaned entries."""
        # Create and quarantine some files
        entries = []
        for i in range(3):
            file_path = os.path.join(temp_dir, f"test_{i}.exe")
            with open(file_path, "wb") as f:
                f.write(b"Test content")
            result = manager.quarantine_file(file_path, f"Threat{i}")
            entries.append(result.entry)

        # Remove all quarantine files to create orphans
        for entry in entries:
            Path(entry.quarantine_path).unlink()

        removed = manager.cleanup_orphaned_entries()
        assert removed == 3
        assert len(manager.get_all_entries()) == 0

    def test_cleanup_orphaned_entries_logs_warning(self, manager, temp_dir, caplog):
        """Test cleanup_orphaned_entries logs warnings for removed entries."""
        import logging

        # Create and quarantine a file
        file_path = os.path.join(temp_dir, "test.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content")
        result = manager.quarantine_file(file_path, "TestThreat")

        # Remove the quarantine file
        Path(result.entry.quarantine_path).unlink()

        with caplog.at_level(logging.WARNING, logger="src.core.quarantine.manager"):
            removed = manager.cleanup_orphaned_entries()

        assert removed == 1
        assert any("orphaned" in record.message.lower() for record in caplog.records)


class TestQuarantineManagerDbFailureAfterRestore:
    """Tests for handling database failures after file restore/delete operations."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        """Create a QuarantineManager with temporary directories."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=False,
        )
        yield mgr
        mgr._database.close()

    @pytest.fixture
    def quarantined_file(self, manager, temp_dir):
        """Create and quarantine a test file."""
        file_path = os.path.join(temp_dir, "files", "test.exe")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(b"Test content for DB failure testing")

        result = manager.quarantine_file(file_path, "TestThreat")
        assert result.is_success is True
        return result.entry

    def test_restore_logs_warning_on_db_failure(self, manager, quarantined_file, caplog):
        """Test that restore logs warning when remove_entry fails."""
        import logging
        from unittest.mock import patch

        # Mock remove_entry to fail
        with (
            caplog.at_level(logging.WARNING, logger="src.core.quarantine.manager"),
            patch.object(manager._database, "remove_entry", return_value=False),
        ):
            result = manager.restore_file(quarantined_file.id)

        # Restore should still succeed
        assert result.is_success is True

        # File should be restored
        assert Path(quarantined_file.original_path).exists()

        # Warning should be logged
        assert any(
            "Failed to remove database entry" in record.message
            and "restore" in record.message.lower()
            for record in caplog.records
        )

    def test_delete_logs_warning_on_db_failure(self, manager, quarantined_file, caplog):
        """Test that delete logs warning when remove_entry fails."""
        import logging
        from unittest.mock import patch

        quarantine_path = Path(quarantined_file.quarantine_path)

        # Mock remove_entry to fail
        with (
            caplog.at_level(logging.WARNING, logger="src.core.quarantine.manager"),
            patch.object(manager._database, "remove_entry", return_value=False),
        ):
            result = manager.delete_file(quarantined_file.id)

        # Delete should still succeed
        assert result.is_success is True

        # File should be deleted
        assert not quarantine_path.exists()

        # Warning should be logged
        assert any(
            "Failed to remove database entry" in record.message
            and "deletion" in record.message.lower()
            for record in caplog.records
        )

    def test_cleanup_fixes_orphaned_entry_after_restore_db_failure(self, manager, quarantined_file):
        """Test that cleanup_orphaned_entries fixes state after restore DB failure."""
        from unittest.mock import patch

        # Simulate DB failure during restore
        with patch.object(manager._database, "remove_entry", return_value=False):
            result = manager.restore_file(quarantined_file.id)

        assert result.is_success is True

        # Entry still exists in DB (orphaned)
        assert manager.get_entry(quarantined_file.id) is not None

        # File was restored (no longer in quarantine)
        assert not Path(quarantined_file.quarantine_path).exists()

        # Cleanup should remove the orphaned entry
        removed = manager.cleanup_orphaned_entries()
        assert removed == 1

        # Entry should now be gone
        assert manager.get_entry(quarantined_file.id) is None

    def test_cleanup_fixes_orphaned_entry_after_delete_db_failure(self, manager, quarantined_file):
        """Test that cleanup_orphaned_entries fixes state after delete DB failure."""
        from unittest.mock import patch

        # Simulate DB failure during delete
        with patch.object(manager._database, "remove_entry", return_value=False):
            result = manager.delete_file(quarantined_file.id)

        assert result.is_success is True

        # Entry still exists in DB (orphaned)
        assert manager.get_entry(quarantined_file.id) is not None

        # File was deleted from quarantine
        assert not Path(quarantined_file.quarantine_path).exists()

        # Cleanup should remove the orphaned entry
        removed = manager.cleanup_orphaned_entries()
        assert removed == 1

        # Entry should now be gone
        assert manager.get_entry(quarantined_file.id) is None


class TestQuarantineManagerPeriodicCleanup:
    """Tests for periodic cleanup functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for quarantine operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_periodic_cleanup_disabled_by_default_in_tests(self, temp_dir):
        """Test that periodic cleanup can be disabled."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=False,
        )

        assert mgr._enable_periodic_cleanup is False
        assert mgr._should_run_periodic_cleanup() is False
        mgr._database.close()

    def test_periodic_cleanup_enabled_when_requested(self, temp_dir):
        """Test that periodic cleanup can be enabled."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        assert mgr._enable_periodic_cleanup is True
        mgr._database.close()

    def test_should_run_cleanup_when_never_run(self, temp_dir):
        """Test that cleanup should run if never run before."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        # Should run when never run before (no timestamp file)
        assert mgr._should_run_periodic_cleanup() is True
        mgr._database.close()

    def test_should_not_run_cleanup_when_recently_run(self, temp_dir):
        """Test that cleanup should not run if recently run."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        # Set timestamp to now (simulating recent cleanup)
        mgr._set_last_cleanup_timestamp()

        # Reset the throttle timer so we can check immediately
        mgr._last_cleanup_check_time = 0.0

        # Should not run when recently run
        assert mgr._should_run_periodic_cleanup() is False
        mgr._database.close()

    def test_should_run_cleanup_when_interval_passed(self, temp_dir):
        """Test that cleanup should run after interval has passed."""
        import time

        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        # Set timestamp to 25 hours ago
        old_timestamp = time.time() - (25 * 3600)
        mgr._cleanup_timestamp_file.parent.mkdir(parents=True, exist_ok=True)
        mgr._cleanup_timestamp_file.write_text(str(old_timestamp))

        # Should run when interval has passed
        assert mgr._should_run_periodic_cleanup() is True
        mgr._database.close()

    def test_maybe_run_periodic_cleanup_removes_orphans(self, temp_dir):
        """Test that maybe_run_periodic_cleanup removes orphaned entries."""
        import time

        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        # Create and quarantine a file
        file_path = os.path.join(temp_dir, "test.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content")
        result = mgr.quarantine_file(file_path, "TestThreat")
        assert result.is_success is True

        # Manually remove the quarantine file to create an orphan
        Path(result.entry.quarantine_path).unlink()

        # Set old timestamp to trigger cleanup
        old_timestamp = time.time() - (25 * 3600)
        mgr._cleanup_timestamp_file.write_text(str(old_timestamp))

        # Run periodic cleanup
        removed = mgr.maybe_run_periodic_cleanup()
        assert removed == 1

        # Entry should be gone
        assert mgr.get_entry(result.entry.id) is None
        mgr._database.close()

    def test_get_all_entries_triggers_periodic_cleanup(self, temp_dir):
        """Test that get_all_entries triggers periodic cleanup."""
        import time

        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        # Create and quarantine a file
        file_path = os.path.join(temp_dir, "test.exe")
        with open(file_path, "wb") as f:
            f.write(b"Test content")
        result = mgr.quarantine_file(file_path, "TestThreat")
        assert result.is_success is True
        entry_id = result.entry.id

        # Manually remove the quarantine file to create an orphan
        Path(result.entry.quarantine_path).unlink()

        # Set old timestamp to trigger cleanup on next get_all_entries
        old_timestamp = time.time() - (25 * 3600)
        mgr._cleanup_timestamp_file.write_text(str(old_timestamp))

        # get_all_entries should trigger cleanup and return empty list
        entries = mgr.get_all_entries()
        assert len(entries) == 0

        # Entry should be gone
        assert mgr.get_entry(entry_id) is None
        mgr._database.close()

    def test_cleanup_timestamp_persists(self, temp_dir):
        """Test that cleanup timestamp is persisted to disk."""
        import time

        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        # Record cleanup time
        before = time.time()
        mgr._set_last_cleanup_timestamp()
        after = time.time()

        # Read back timestamp
        timestamp = mgr._get_last_cleanup_timestamp()
        assert before <= timestamp <= after

        # Create new manager instance - timestamp should persist
        mgr._database.close()
        mgr2 = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        timestamp2 = mgr2._get_last_cleanup_timestamp()
        assert timestamp2 == timestamp
        mgr2._database.close()

    def test_throttle_prevents_frequent_checks(self, temp_dir):
        """Test that checks are throttled to prevent excessive disk I/O."""
        quarantine_dir = os.path.join(temp_dir, "quarantine")
        db_path = os.path.join(temp_dir, "quarantine.db")
        mgr = QuarantineManager(
            quarantine_directory=quarantine_dir,
            database_path=db_path,
            enable_periodic_cleanup=True,
        )

        # First check should work
        result1 = mgr._should_run_periodic_cleanup()
        assert result1 is True  # Never run before

        # Immediate second check should be throttled (returns False due to throttle)
        result2 = mgr._should_run_periodic_cleanup()
        assert result2 is False  # Throttled

        mgr._database.close()
