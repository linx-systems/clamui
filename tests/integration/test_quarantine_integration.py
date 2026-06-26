# ClamUI Quarantine Integration Tests
"""
Integration tests for complete quarantine workflows.

Tests the interaction between QuarantineManager, QuarantineDatabase,
SecureFileHandler, and settings to verify complete workflows work correctly.
"""

import os
import stat
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Import directly - quarantine modules use GLib only for async callbacks,
# which are mocked in tests via GLib.idle_add patching
from src.core.quarantine.database import QuarantineDatabase
from src.core.quarantine.file_handler import SecureFileHandler
from src.core.quarantine.manager import (
    QuarantineManager,
    QuarantineStatus,
)
from src.core.settings_manager import SettingsManager


class TestQuarantineWorkflow:
    """Integration tests for the complete quarantine workflow."""

    @pytest.fixture
    def temp_environment(self):
        """Create a temporary environment for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create directories for testing
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            quarantine_dir = Path(tmpdir) / "quarantine"
            db_path = Path(tmpdir) / "quarantine.db"

            yield {
                "tmpdir": tmpdir,
                "source_dir": source_dir,
                "quarantine_dir": quarantine_dir,
                "db_path": db_path,
            }

    @pytest.fixture
    def manager(self, temp_environment):
        """Create a QuarantineManager for testing."""
        mgr = QuarantineManager(
            quarantine_directory=str(temp_environment["quarantine_dir"]),
            database_path=str(temp_environment["db_path"]),
        )
        yield mgr
        # Explicitly close the database to prevent resource warnings
        mgr._database.close()

    def create_test_file(
        self, source_dir: Path, name: str = "test_threat.exe", content: bytes = b"malware content"
    ):
        """Helper to create a test file for quarantine testing."""
        file_path = source_dir / name
        file_path.write_bytes(content)
        return file_path

    def test_quarantine_workflow_complete(self, temp_environment, manager):
        """Test complete quarantine workflow: file → quarantine → database entry."""
        # Create a test file simulating a threat
        test_file = self.create_test_file(
            temp_environment["source_dir"], "infected.exe", b"Simulated malware content for testing"
        )
        original_path = str(test_file)
        original_size = test_file.stat().st_size

        # Step 1: Quarantine the file
        result = manager.quarantine_file(original_path, "Win.Trojan.Test")

        # Verify operation succeeded
        assert result.is_success is True
        assert result.status == QuarantineStatus.SUCCESS
        assert result.entry is not None

        # Step 2: Verify original file is removed
        assert not test_file.exists()

        # Step 3: Verify file is in quarantine directory
        quarantine_path = Path(result.entry.quarantine_path)
        assert quarantine_path.exists()
        assert quarantine_path.parent == temp_environment["quarantine_dir"]

        # Step 4: Verify database entry was created correctly
        assert result.entry.original_path == str(Path(original_path).resolve())
        assert result.entry.threat_name == "Win.Trojan.Test"
        assert result.entry.file_size == original_size
        assert len(result.entry.file_hash) == 64  # SHA256

        # Step 5: Verify file permissions are restrictive
        quarantine_mode = quarantine_path.stat().st_mode & 0o777
        assert quarantine_mode == 0o400  # Read-only for owner

        # Step 6: Verify quarantine directory permissions
        dir_mode = temp_environment["quarantine_dir"].stat().st_mode & 0o777
        assert dir_mode == 0o700  # Owner only

        # Step 7: Verify entry can be retrieved from database
        retrieved_entry = manager.get_entry(result.entry.id)
        assert retrieved_entry is not None
        assert retrieved_entry.original_path == result.entry.original_path
        assert retrieved_entry.threat_name == result.entry.threat_name

    def test_quarantine_updates_counts_and_size(self, temp_environment, manager):
        """Test that quarantine operations update entry count and total size."""
        # Initial state
        assert manager.get_entry_count() == 0
        assert manager.get_total_size() == 0

        # Quarantine first file
        file1 = self.create_test_file(
            temp_environment["source_dir"], "file1.exe", b"content1" * 100
        )
        file1_size = file1.stat().st_size
        result1 = manager.quarantine_file(str(file1), "Threat1")
        assert result1.is_success

        assert manager.get_entry_count() == 1
        assert manager.get_total_size() == file1_size

        # Quarantine second file
        file2 = self.create_test_file(
            temp_environment["source_dir"], "file2.exe", b"content2" * 200
        )
        file2_size = file2.stat().st_size
        result2 = manager.quarantine_file(str(file2), "Threat2")
        assert result2.is_success

        assert manager.get_entry_count() == 2
        assert manager.get_total_size() == file1_size + file2_size

    def test_quarantine_prevents_duplicates(self, temp_environment, manager):
        """Test that quarantining the same file twice is prevented."""
        # Create and quarantine a file
        test_file = self.create_test_file(temp_environment["source_dir"], "duplicate.exe")
        str(test_file.resolve())
        result1 = manager.quarantine_file(str(test_file), "FirstThreat")
        assert result1.is_success

        # Restore the file to original location
        result2 = manager.restore_file(result1.entry.id)
        assert result2.is_success

        # Re-quarantine should work since entry was removed
        result3 = manager.quarantine_file(str(test_file), "SecondThreat")
        assert result3.is_success
        assert manager.get_entry_count() == 1


class TestRestoreWorkflow:
    """Integration tests for the complete restore workflow."""

    @pytest.fixture
    def temp_environment(self):
        """Create a temporary environment for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            quarantine_dir = Path(tmpdir) / "quarantine"
            db_path = Path(tmpdir) / "quarantine.db"

            yield {
                "tmpdir": tmpdir,
                "source_dir": source_dir,
                "quarantine_dir": quarantine_dir,
                "db_path": db_path,
            }

    @pytest.fixture
    def manager(self, temp_environment):
        """Create a QuarantineManager for testing."""
        mgr = QuarantineManager(
            quarantine_directory=str(temp_environment["quarantine_dir"]),
            database_path=str(temp_environment["db_path"]),
        )
        yield mgr
        # Explicitly close the database to prevent resource warnings
        mgr._database.close()

    def create_and_quarantine_file(self, temp_environment, manager, name: str = "test.exe"):
        """Helper to create and quarantine a test file."""
        file_path = temp_environment["source_dir"] / name
        content = b"Test file content for " + name.encode()
        file_path.write_bytes(content)

        result = manager.quarantine_file(str(file_path), "TestThreat")
        assert result.is_success
        return result.entry, content

    def test_restore_workflow_complete(self, temp_environment, manager):
        """Test complete restore workflow: quarantine → restore → database entry removed."""
        # Quarantine a file
        entry, original_content = self.create_and_quarantine_file(
            temp_environment, manager, "restore_test.exe"
        )
        original_path = Path(entry.original_path)

        # Verify file is in quarantine
        assert not original_path.exists()
        assert Path(entry.quarantine_path).exists()
        assert manager.get_entry_count() == 1

        # Step 1: Restore the file
        result = manager.restore_file(entry.id)

        # Verify restore succeeded
        assert result.is_success is True
        assert result.status == QuarantineStatus.SUCCESS

        # Step 2: Verify file is back at original location
        assert original_path.exists()
        assert original_path.read_bytes() == original_content

        # Step 3: Verify file is removed from quarantine
        assert not Path(entry.quarantine_path).exists()

        # Step 4: Verify database entry is removed
        assert manager.get_entry(entry.id) is None
        assert manager.get_entry_count() == 0

        # Step 5: Verify total size is updated
        assert manager.get_total_size() == 0

    def test_restore_verifies_integrity(self, temp_environment, manager):
        """Test that restore verifies file integrity before restoring."""
        entry, _ = self.create_and_quarantine_file(temp_environment, manager, "integrity_test.exe")

        # Tamper with the quarantined file
        quarantine_path = Path(entry.quarantine_path)
        os.chmod(quarantine_path, stat.S_IRUSR | stat.S_IWUSR)
        quarantine_path.write_bytes(b"Tampered content")
        os.chmod(quarantine_path, 0o400)

        # Restore should fail due to integrity check
        result = manager.restore_file(entry.id)
        assert result.is_success is False
        assert result.status == QuarantineStatus.ERROR
        assert "integrity" in result.error_message.lower() or "hash" in result.error_message.lower()

    def test_restore_destination_exists_error(self, temp_environment, manager):
        """Test restore fails if destination already exists."""
        entry, _ = self.create_and_quarantine_file(temp_environment, manager, "existing_test.exe")
        original_path = Path(entry.original_path)

        # Create a file at the original location
        original_path.write_bytes(b"New file content")

        # Restore should fail
        result = manager.restore_file(entry.id)
        assert result.is_success is False
        assert result.status == QuarantineStatus.RESTORE_DESTINATION_EXISTS

    def test_restore_nonexistent_entry_fails(self, temp_environment, manager):
        """Test restore fails for non-existent entry."""
        result = manager.restore_file(999)
        assert result.is_success is False
        assert result.status == QuarantineStatus.ENTRY_NOT_FOUND


class TestDeleteWorkflow:
    """Integration tests for the complete delete workflow."""

    @pytest.fixture
    def temp_environment(self):
        """Create a temporary environment for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            quarantine_dir = Path(tmpdir) / "quarantine"
            db_path = Path(tmpdir) / "quarantine.db"

            yield {
                "tmpdir": tmpdir,
                "source_dir": source_dir,
                "quarantine_dir": quarantine_dir,
                "db_path": db_path,
            }

    @pytest.fixture
    def manager(self, temp_environment):
        """Create a QuarantineManager for testing."""
        mgr = QuarantineManager(
            quarantine_directory=str(temp_environment["quarantine_dir"]),
            database_path=str(temp_environment["db_path"]),
        )
        yield mgr
        # Explicitly close the database to prevent resource warnings
        mgr._database.close()

    def create_and_quarantine_file(
        self, temp_environment, manager, name: str = "test.exe", size: int = 1000
    ):
        """Helper to create and quarantine a test file."""
        file_path = temp_environment["source_dir"] / name
        content = b"x" * size
        file_path.write_bytes(content)

        result = manager.quarantine_file(str(file_path), "TestThreat")
        assert result.is_success
        return result.entry

    def test_delete_workflow_complete(self, temp_environment, manager):
        """Test complete delete workflow: quarantine → delete → removed from system."""
        # Quarantine a file
        entry = self.create_and_quarantine_file(temp_environment, manager, "delete_test.exe", 2000)
        quarantine_path = Path(entry.quarantine_path)
        file_size = entry.file_size

        # Verify initial state
        assert quarantine_path.exists()
        assert manager.get_entry_count() == 1
        assert manager.get_total_size() == file_size

        # Step 1: Delete the quarantined file
        result = manager.delete_file(entry.id)

        # Verify delete succeeded
        assert result.is_success is True
        assert result.status == QuarantineStatus.SUCCESS

        # Step 2: Verify file is permanently removed
        assert not quarantine_path.exists()

        # Step 3: Verify database entry is removed
        assert manager.get_entry(entry.id) is None

        # Step 4: Verify counts are updated
        assert manager.get_entry_count() == 0

        # Step 5: Verify storage recalculated (total size reduced)
        assert manager.get_total_size() == 0

    def test_delete_multiple_files_updates_size(self, temp_environment, manager):
        """Test deleting multiple files updates total size correctly."""
        # Quarantine multiple files
        entry1 = self.create_and_quarantine_file(temp_environment, manager, "file1.exe", 1000)
        entry2 = self.create_and_quarantine_file(temp_environment, manager, "file2.exe", 2000)
        self.create_and_quarantine_file(temp_environment, manager, "file3.exe", 3000)

        total_size = manager.get_total_size()
        assert total_size == 1000 + 2000 + 3000
        assert manager.get_entry_count() == 3

        # Delete middle file
        result = manager.delete_file(entry2.id)
        assert result.is_success

        assert manager.get_entry_count() == 2
        assert manager.get_total_size() == 1000 + 3000

        # Delete first file
        result = manager.delete_file(entry1.id)
        assert result.is_success

        assert manager.get_entry_count() == 1
        assert manager.get_total_size() == 3000

    def test_delete_nonexistent_entry_fails(self, temp_environment, manager):
        """Test delete fails for non-existent entry."""
        result = manager.delete_file(999)
        assert result.is_success is False
        assert result.status == QuarantineStatus.ENTRY_NOT_FOUND


class TestCleanupOldItemsWorkflow:
    """Integration tests for the cleanup old items workflow."""

    @pytest.fixture
    def temp_environment(self):
        """Create a temporary environment for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            quarantine_dir = Path(tmpdir) / "quarantine"
            db_path = Path(tmpdir) / "quarantine.db"

            yield {
                "tmpdir": tmpdir,
                "source_dir": source_dir,
                "quarantine_dir": quarantine_dir,
                "db_path": db_path,
            }

    @pytest.fixture
    def manager(self, temp_environment):
        """Create a QuarantineManager for testing."""
        mgr = QuarantineManager(
            quarantine_directory=str(temp_environment["quarantine_dir"]),
            database_path=str(temp_environment["db_path"]),
        )
        yield mgr
        # Explicitly close the database to prevent resource warnings
        mgr._database.close()

    def create_and_quarantine_file(self, temp_environment, manager, name: str = "test.exe"):
        """Helper to create and quarantine a test file."""
        file_path = temp_environment["source_dir"] / name
        file_path.write_bytes(b"Test content")

        result = manager.quarantine_file(str(file_path), "TestThreat")
        assert result.is_success
        return result.entry

    def test_cleanup_old_entries_workflow(self, temp_environment, manager):
        """Test cleanup old entries removes files older than threshold."""
        # Create and quarantine files
        entry1 = self.create_and_quarantine_file(temp_environment, manager, "recent.exe")
        entry2 = self.create_and_quarantine_file(temp_environment, manager, "old1.exe")
        entry3 = self.create_and_quarantine_file(temp_environment, manager, "old2.exe")

        assert manager.get_entry_count() == 3

        # Manually update detection dates to simulate old entries
        # We need to access the database directly for this test
        import sqlite3

        db_path = str(temp_environment["db_path"])
        old_date = (datetime.now() - timedelta(days=45)).isoformat()

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE quarantine SET detection_date = ? WHERE id = ?", (old_date, entry2.id)
            )
            conn.execute(
                "UPDATE quarantine SET detection_date = ? WHERE id = ?", (old_date, entry3.id)
            )
            conn.commit()
        finally:
            conn.close()

        # Get old entries
        old_entries = manager.get_old_entries(days=30)
        assert len(old_entries) == 2

        # Cleanup old entries
        removed_count = manager.cleanup_old_entries(days=30)

        # Verify cleanup results
        assert removed_count == 2
        assert manager.get_entry_count() == 1

        # Verify only recent entry remains
        remaining_entry = manager.get_entry(entry1.id)
        assert remaining_entry is not None
        assert manager.get_entry(entry2.id) is None
        assert manager.get_entry(entry3.id) is None

        # Verify files are deleted
        assert not Path(entry2.quarantine_path).exists()
        assert not Path(entry3.quarantine_path).exists()
        assert Path(entry1.quarantine_path).exists()


class TestConfigChange:
    """Integration tests for configuration changes."""

    @pytest.fixture
    def temp_environment(self):
        """Create a temporary environment for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            config_dir = Path(tmpdir) / "config"
            quarantine_dir1 = Path(tmpdir) / "quarantine1"
            quarantine_dir2 = Path(tmpdir) / "quarantine2"
            db_path = Path(tmpdir) / "quarantine.db"

            yield {
                "tmpdir": tmpdir,
                "source_dir": source_dir,
                "config_dir": config_dir,
                "quarantine_dir1": quarantine_dir1,
                "quarantine_dir2": quarantine_dir2,
                "db_path": db_path,
            }

    def test_quarantine_directory_setting_in_defaults(self, temp_environment):
        """Test that quarantine_directory setting exists in SettingsManager defaults."""
        settings = SettingsManager(config_dir=str(temp_environment["config_dir"]))
        assert "quarantine_directory" in settings.DEFAULT_SETTINGS

    def test_new_manager_uses_different_directory(self, temp_environment):
        """Test that creating a manager with different directory uses new path."""
        source_dir = temp_environment["source_dir"]

        # Create file
        file1 = source_dir / "test1.exe"
        file1.write_bytes(b"content1")

        # First manager with quarantine_dir1
        manager1 = QuarantineManager(
            quarantine_directory=str(temp_environment["quarantine_dir1"]),
            database_path=str(temp_environment["db_path"]),
        )
        result1 = manager1.quarantine_file(str(file1), "Threat1")
        assert result1.is_success
        assert str(temp_environment["quarantine_dir1"]) in str(
            Path(result1.entry.quarantine_path).parent
        )

        # Create another file
        file2 = source_dir / "test2.exe"
        file2.write_bytes(b"content2")

        # Second manager with quarantine_dir2
        manager2 = QuarantineManager(
            quarantine_directory=str(temp_environment["quarantine_dir2"]),
            database_path=str(temp_environment["db_path"]),
        )
        result2 = manager2.quarantine_file(str(file2), "Threat2")
        assert result2.is_success
        assert str(temp_environment["quarantine_dir2"]) in str(
            Path(result2.entry.quarantine_path).parent
        )

        # Verify files are in their respective directories
        assert Path(result1.entry.quarantine_path).parent == temp_environment["quarantine_dir1"]
        assert Path(result2.entry.quarantine_path).parent == temp_environment["quarantine_dir2"]

        # Cleanup
        manager1._database.close()
        manager2._database.close()


class TestEdgeCases:
    """Integration tests for edge cases and error handling."""

    @pytest.fixture
    def temp_environment(self):
        """Create a temporary environment for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            quarantine_dir = Path(tmpdir) / "quarantine"
            db_path = Path(tmpdir) / "quarantine.db"

            yield {
                "tmpdir": tmpdir,
                "source_dir": source_dir,
                "quarantine_dir": quarantine_dir,
                "db_path": db_path,
            }

    @pytest.fixture
    def manager(self, temp_environment):
        """Create a QuarantineManager for testing."""
        mgr = QuarantineManager(
            quarantine_directory=str(temp_environment["quarantine_dir"]),
            database_path=str(temp_environment["db_path"]),
        )
        yield mgr
        # Explicitly close the database to prevent resource warnings
        mgr._database.close()

    def test_empty_file_quarantine(self, temp_environment, manager):
        """Test quarantining an empty file."""
        empty_file = temp_environment["source_dir"] / "empty.exe"
        empty_file.write_bytes(b"")

        result = manager.quarantine_file(str(empty_file), "EmptyThreat")
        assert result.is_success
        assert result.entry.file_size == 0

    def test_unicode_filename(self, temp_environment, manager):
        """Test quarantining a file with unicode characters in name."""
        unicode_file = temp_environment["source_dir"] / "测试文件_тест_αβγ.exe"
        unicode_file.write_bytes(b"content")

        result = manager.quarantine_file(str(unicode_file), "UnicodeFile")
        assert result.is_success
        assert not unicode_file.exists()
        assert Path(result.entry.quarantine_path).exists()

    def test_filename_with_spaces(self, temp_environment, manager):
        """Test quarantining a file with spaces in the name."""
        space_file = temp_environment["source_dir"] / "file with spaces.exe"
        space_file.write_bytes(b"content")

        result = manager.quarantine_file(str(space_file), "SpaceFile")
        assert result.is_success
        assert not space_file.exists()
        assert Path(result.entry.quarantine_path).exists()

    def test_large_file_quarantine(self, temp_environment, manager):
        """Test quarantining a larger file."""
        large_file = temp_environment["source_dir"] / "large.exe"
        # Create a 1MB file
        large_file.write_bytes(b"x" * (1024 * 1024))

        result = manager.quarantine_file(str(large_file), "LargeFile")
        assert result.is_success
        assert result.entry.file_size == 1024 * 1024
        assert len(result.entry.file_hash) == 64

    def test_get_entry_by_original_path(self, temp_environment, manager):
        """Test retrieving entry by original path."""
        test_file = temp_environment["source_dir"] / "test.exe"
        test_file.write_bytes(b"content")
        original_path = str(test_file.resolve())

        result = manager.quarantine_file(str(test_file), "TestThreat")
        assert result.is_success

        # Retrieve by original path
        entry = manager.get_entry_by_original_path(original_path)
        assert entry is not None
        assert entry.id == result.entry.id
        assert entry.threat_name == "TestThreat"

    def test_get_all_entries_ordering(self, temp_environment, manager):
        """Test that get_all_entries returns entries in correct order (newest first)."""
        # Create and quarantine files with slight delays
        import time

        for i in range(3):
            file_path = temp_environment["source_dir"] / f"file{i}.exe"
            file_path.write_bytes(f"content{i}".encode())
            manager.quarantine_file(str(file_path), f"Threat{i}")
            time.sleep(0.01)  # Small delay to ensure different timestamps

        entries = manager.get_all_entries()
        assert len(entries) == 3

        # Entries should be newest first
        for i in range(len(entries) - 1):
            assert entries[i].detection_date >= entries[i + 1].detection_date


class TestDatabaseAndFileHandlerIntegration:
    """Integration tests for database and file handler working together."""

    @pytest.fixture
    def temp_environment(self):
        """Create a temporary environment for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            quarantine_dir = Path(tmpdir) / "quarantine"
            db_path = Path(tmpdir) / "quarantine.db"

            yield {
                "tmpdir": tmpdir,
                "source_dir": source_dir,
                "quarantine_dir": quarantine_dir,
                "db_path": db_path,
            }

    def test_database_and_file_handler_consistency(self, temp_environment):
        """Test that database and file handler stay in sync."""
        db = QuarantineDatabase(str(temp_environment["db_path"]))
        fh = SecureFileHandler(str(temp_environment["quarantine_dir"]))

        try:
            # Create test file
            test_file = temp_environment["source_dir"] / "test.exe"
            test_file.write_bytes(b"test content")

            # Move file using file handler
            result = fh.move_to_quarantine(str(test_file), "TestThreat")
            assert result.is_success

            # Add entry to database
            entry_id = db.add_entry(
                original_path=str(test_file),
                quarantine_path=result.destination_path,
                threat_name="TestThreat",
                file_size=result.file_size,
                file_hash=result.file_hash,
            )
            assert entry_id is not None

            # Verify consistency
            entry = db.get_entry(entry_id)
            assert entry is not None
            assert Path(entry.quarantine_path).exists()
            assert entry.file_size == result.file_size
            assert entry.file_hash == result.file_hash
        finally:
            db.close()

    def test_hash_verification_integration(self, temp_environment):
        """Test hash verification works correctly with file handler and database."""
        db = QuarantineDatabase(str(temp_environment["db_path"]))
        fh = SecureFileHandler(str(temp_environment["quarantine_dir"]))

        try:
            # Create test file
            test_file = temp_environment["source_dir"] / "test.exe"
            original_content = b"original content for hashing"
            test_file.write_bytes(original_content)

            # Quarantine file
            result = fh.move_to_quarantine(str(test_file), "TestThreat")
            assert result.is_success

            # Store in database
            entry_id = db.add_entry(
                original_path=str(test_file),
                quarantine_path=result.destination_path,
                threat_name="TestThreat",
                file_size=result.file_size,
                file_hash=result.file_hash,
            )

            entry = db.get_entry(entry_id)

            # Verify integrity
            is_valid, error = fh.verify_file_integrity(entry.quarantine_path, entry.file_hash)
            assert is_valid is True
            assert error is None

            # Now tamper with file and verify detection
            quarantine_path = Path(entry.quarantine_path)
            os.chmod(quarantine_path, stat.S_IRUSR | stat.S_IWUSR)
            quarantine_path.write_bytes(b"tampered content")
            os.chmod(quarantine_path, 0o400)

            # Verify should now fail
            is_valid, error = fh.verify_file_integrity(entry.quarantine_path, entry.file_hash)
            assert is_valid is False
            assert "mismatch" in error.lower()
        finally:
            db.close()


class TestQuarantineDirectorySettingWiring:
    """The ``quarantine_directory`` setting must actually drive where files go.

    Regression coverage: the setting existed in DEFAULT_SETTINGS (and the docs)
    but was never wired to QuarantineManager, so it silently had no effect.
    """

    def test_injected_setting_is_honored(self, tmp_path):
        """An injected SettingsManager's quarantine_directory is used."""
        custom = tmp_path / "configured_quarantine"
        settings = SettingsManager(config_dir=str(tmp_path / "config"))
        settings.set("quarantine_directory", str(custom))

        mgr = QuarantineManager(
            database_path=str(tmp_path / "q.db"),
            enable_periodic_cleanup=False,
            settings_manager=settings,
        )
        try:
            assert mgr.quarantine_directory == custom
            src = tmp_path / "evil.exe"
            src.write_bytes(b"malware content")
            result = mgr.quarantine_file(str(src), "Test.Threat")
            assert result.is_success
            assert Path(result.entry.quarantine_path).parent == custom
        finally:
            mgr._database.close()

    def test_explicit_directory_overrides_setting(self, tmp_path):
        """An explicit quarantine_directory argument wins over the setting."""
        configured = tmp_path / "configured"
        explicit = tmp_path / "explicit"
        settings = SettingsManager(config_dir=str(tmp_path / "config"))
        settings.set("quarantine_directory", str(configured))

        mgr = QuarantineManager(
            quarantine_directory=str(explicit),
            database_path=str(tmp_path / "q.db"),
            enable_periodic_cleanup=False,
            settings_manager=settings,
        )
        try:
            assert mgr.quarantine_directory == explicit
        finally:
            mgr._database.close()

    def test_empty_setting_falls_back_to_default(self, tmp_path, monkeypatch):
        """An empty setting falls back to the XDG default location."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        settings = SettingsManager(config_dir=str(tmp_path / "config"))
        # quarantine_directory defaults to "" -> use the XDG default.
        mgr = QuarantineManager(
            enable_periodic_cleanup=False,
            settings_manager=settings,
        )
        try:
            assert mgr.quarantine_directory == tmp_path / "data" / "clamui" / "quarantine"
        finally:
            mgr._database.close()

    def test_lazy_default_reads_setting_from_disk(self, tmp_path, monkeypatch):
        """With no injected SettingsManager (the CLI path), the setting is still honored."""
        custom = tmp_path / "cli_quarantine"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        # Persist the setting where a lazily-created SettingsManager() will read it.
        SettingsManager().set("quarantine_directory", str(custom))

        # No settings_manager injected -> the manager must lazily read it from disk.
        mgr = QuarantineManager(enable_periodic_cleanup=False)
        try:
            assert mgr.quarantine_directory == custom
        finally:
            mgr._database.close()
