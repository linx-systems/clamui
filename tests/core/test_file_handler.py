# ClamUI SecureFileHandler Tests
"""Unit tests for the SecureFileHandler path validation and restore error paths."""

import errno
import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from src.core.quarantine.database import QuarantineDatabase
from src.core.quarantine.file_handler import (
    FileOperationStatus,
    SecureFileHandler,
    _unlinkat,
)


class TestValidateRestorePath:
    """Tests for SecureFileHandler.validate_restore_path() method."""

    def test_valid_user_home_path(self):
        """Test that paths in user home directory are accepted."""
        handler = SecureFileHandler()

        # Test path in user's home directory
        user_path = str(Path.home() / "Documents" / "file.txt")
        is_valid, error = handler.validate_restore_path(user_path)

        assert is_valid is True
        assert error is None

    def test_valid_tmp_path(self, tmp_path):
        """Test that paths in /tmp are accepted."""
        handler = SecureFileHandler()

        # Test path in /tmp directory
        temp_path = str(tmp_path / "test_file.txt")
        is_valid, error = handler.validate_restore_path(temp_path)

        assert is_valid is True
        assert error is None

    def test_empty_path_rejected(self):
        """Test that empty paths are rejected."""
        handler = SecureFileHandler()

        # Test empty string
        is_valid, error = handler.validate_restore_path("")
        assert is_valid is False
        assert "cannot be empty" in error

        # Test whitespace-only string
        is_valid, error = handler.validate_restore_path("   ")
        assert is_valid is False
        assert "cannot be empty" in error

    def test_newline_character_rejected(self):
        """Test that paths containing newline characters are rejected."""
        handler = SecureFileHandler()

        # Test Unix newline
        path_with_newline = "/home/user/file\nmalicious.txt"
        is_valid, error = handler.validate_restore_path(path_with_newline)

        assert is_valid is False
        assert "newline" in error.lower()

        # Test carriage return
        path_with_cr = "/home/user/file\rmalicious.txt"
        is_valid, error = handler.validate_restore_path(path_with_cr)

        assert is_valid is False
        assert "newline" in error.lower()

    def test_null_byte_rejected(self):
        """Test that paths containing null bytes are rejected."""
        handler = SecureFileHandler()

        path_with_null = "/home/user/file\x00malicious.txt"
        is_valid, error = handler.validate_restore_path(path_with_null)

        assert is_valid is False
        assert "null" in error.lower()

    def test_etc_directory_rejected(self):
        """Test that paths in /etc directory are rejected."""
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/etc/passwd")

        assert is_valid is False
        assert "/etc" in error
        assert "protected" in error.lower()

    def test_var_directory_rejected(self):
        """Test that paths in /var directory are rejected."""
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/var/lib/important.db")

        assert is_valid is False
        assert "/var" in error
        assert "protected" in error.lower()

    def test_usr_directory_rejected(self):
        """Test that paths in /usr directory are rejected."""
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/usr/bin/malicious")

        assert is_valid is False
        assert "/usr" in error
        assert "protected" in error.lower()

    def test_bin_directory_rejected(self):
        """Test that paths in /bin directory are rejected.

        Note: On modern Linux systems, /bin is a symlink to /usr/bin,
        so the error message may reference /usr instead of /bin.
        """
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/bin/bash")

        assert is_valid is False
        # Error message may reference /usr/bin (symlink target) or /bin
        assert "protected" in error.lower()

    def test_sbin_directory_rejected(self):
        """Test that paths in /sbin directory are rejected.

        Note: On modern Linux systems, /sbin is a symlink to /usr/sbin,
        so the error message may reference /usr instead of /sbin.
        """
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/sbin/init")

        assert is_valid is False
        # Error message may reference /usr/sbin (symlink target) or /sbin
        assert "protected" in error.lower()

    def test_lib_directory_rejected(self):
        """Test that paths in /lib directory are rejected.

        Note: On modern Linux systems, /lib is a symlink to /usr/lib,
        so the error message may reference /usr instead of /lib.
        """
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/lib/systemd/system/service.conf")

        assert is_valid is False
        # Error message may reference /usr/lib (symlink target) or /lib
        assert "protected" in error.lower()

    def test_lib64_directory_rejected(self):
        """Test that paths in /lib64 directory are rejected."""
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/lib64/ld-linux-x86-64.so.2")

        assert is_valid is False
        assert "protected" in error.lower()

    def test_boot_directory_rejected(self):
        """Test that paths in /boot directory are rejected."""
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/boot/vmlinuz")

        assert is_valid is False
        assert "/boot" in error
        assert "protected" in error.lower()

    def test_root_directory_rejected(self):
        """Test that paths in /root directory are rejected."""
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/root/.bashrc")

        assert is_valid is False
        assert "/root" in error
        assert "protected" in error.lower()

    def test_sys_directory_rejected(self):
        """Test that paths in /sys directory are rejected."""
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/sys/class/net/eth0/mtu")

        assert is_valid is False
        assert "/sys" in error
        assert "protected" in error.lower()

    def test_proc_directory_rejected(self):
        """Test that paths in /proc directory are rejected."""
        handler = SecureFileHandler()

        is_valid, error = handler.validate_restore_path("/proc/sys/kernel/hostname")

        assert is_valid is False
        assert "/proc" in error
        assert "protected" in error.lower()

    def test_parent_directory_traversal_to_protected(self):
        """Test that paths using .. to reach protected directories are rejected."""
        handler = SecureFileHandler()

        # Attempt to use .. to escape to /etc
        # The resolve() method should handle this
        path_with_traversal = "/home/user/../../etc/passwd"
        is_valid, error = handler.validate_restore_path(path_with_traversal)

        assert is_valid is False
        assert "protected" in error.lower()

    def test_symlink_to_protected_directory(self, tmp_path):
        """Test that symlinks pointing to protected directories are rejected."""
        handler = SecureFileHandler()

        # Create a symlink to /etc
        symlink_path = tmp_path / "link_to_etc"
        try:
            symlink_path.symlink_to("/etc")

            # Try to restore to a path that includes this symlink
            restore_path = str(symlink_path / "passwd")
            is_valid, error = handler.validate_restore_path(restore_path)

            assert is_valid is False
            assert "symlink" in error.lower() or "protected" in error.lower()
        finally:
            # Clean up symlink
            if symlink_path.exists():
                symlink_path.unlink()

    def test_symlink_to_safe_directory(self, tmp_path):
        """Test that symlinks pointing to safe directories are accepted."""
        handler = SecureFileHandler()

        # Create a safe target directory
        safe_target = tmp_path / "safe_target"
        safe_target.mkdir()

        # Create a symlink to the safe directory
        symlink_path = tmp_path / "link_to_safe"
        try:
            symlink_path.symlink_to(safe_target)

            # Try to restore to a path that includes this symlink
            restore_path = str(symlink_path / "file.txt")
            is_valid, error = handler.validate_restore_path(restore_path)

            assert is_valid is True
            assert error is None
        finally:
            # Clean up symlink
            if symlink_path.exists():
                symlink_path.unlink()

    def test_nonexistent_path_in_safe_location(self, tmp_path):
        """Test that nonexistent paths in safe locations are accepted."""
        handler = SecureFileHandler()

        # The validation should accept paths that don't exist yet
        # as long as they're in a safe location
        nonexistent_path = str(tmp_path / "doesnt_exist" / "yet" / "file.txt")
        is_valid, error = handler.validate_restore_path(nonexistent_path)

        assert is_valid is True
        assert error is None

    def test_relative_path_resolves_safely(self, tmp_path):
        """Test that relative paths that resolve to safe locations are accepted."""
        handler = SecureFileHandler()

        # Change to tmp directory and use relative path
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            # Relative path that resolves to tmp_path
            relative_path = "./subdir/file.txt"
            is_valid, error = handler.validate_restore_path(relative_path)

            assert is_valid is True
            assert error is None
        finally:
            os.chdir(original_cwd)

    def test_invalid_path_format(self):
        """Test that invalid path formats are handled gracefully."""
        handler = SecureFileHandler()

        # Test with None - should be handled gracefully, not raise exception
        is_valid, error = handler.validate_restore_path(None)
        assert is_valid is False
        assert "Invalid path format" in error or "cannot be empty" in error


class TestRestoreFromQuarantineValidation:
    """Tests for path validation integration in restore_from_quarantine()."""

    def test_restore_rejects_invalid_path(self, tmp_path):
        """Test that restore_from_quarantine rejects invalid restore paths."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        # Create a fake quarantined file
        quarantine_file = tmp_path / "quarantine" / "test_file.quar"
        quarantine_file.parent.mkdir(parents=True, exist_ok=True)
        quarantine_file.write_text("fake quarantined content")

        # Try to restore to a protected directory
        result = handler.restore_from_quarantine(str(quarantine_file), "/etc/malicious.conf")

        assert result.status == FileOperationStatus.INVALID_RESTORE_PATH
        assert result.error_message is not None
        assert "protected" in result.error_message.lower()

    def test_restore_rejects_path_with_injection(self, tmp_path):
        """Test that restore_from_quarantine rejects paths with injection characters."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        # Create a fake quarantined file
        quarantine_file = tmp_path / "quarantine" / "test_file.quar"
        quarantine_file.parent.mkdir(parents=True, exist_ok=True)
        quarantine_file.write_text("fake quarantined content")

        # Try to restore to a path with newline injection
        result = handler.restore_from_quarantine(str(quarantine_file), "/tmp/file\nmalicious.txt")

        assert result.status == FileOperationStatus.INVALID_RESTORE_PATH
        assert result.error_message is not None
        assert "newline" in result.error_message.lower()

    def test_restore_accepts_valid_path(self, tmp_path):
        """Test that restore_from_quarantine accepts valid restore paths."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        # Create a fake quarantined file
        quarantine_file = tmp_path / "quarantine" / "test_file.quar"
        quarantine_file.parent.mkdir(parents=True, exist_ok=True)
        quarantine_file.write_text("fake quarantined content")

        # Try to restore to a safe location
        safe_restore_path = str(tmp_path / "restored" / "file.txt")
        result = handler.restore_from_quarantine(str(quarantine_file), safe_restore_path)

        # Should not fail due to path validation
        # (might fail for other reasons like missing hash, but not INVALID_RESTORE_PATH)
        assert result.status != FileOperationStatus.INVALID_RESTORE_PATH

    def test_restore_validation_before_file_operations(self, tmp_path):
        """Test that path validation occurs before any file operations."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        # Don't create the quarantined file - validation should happen first
        quarantine_file = tmp_path / "quarantine" / "nonexistent.quar"

        # Try to restore to protected directory
        result = handler.restore_from_quarantine(str(quarantine_file), "/etc/malicious.conf")

        # Should fail with INVALID_RESTORE_PATH, not FILE_NOT_FOUND
        # This proves validation happens before checking if source exists
        assert result.status == FileOperationStatus.INVALID_RESTORE_PATH
        assert "protected" in result.error_message.lower()


class TestValidateQuarantinePath:
    """Tests for SecureFileHandler._validate_quarantine_path() method."""

    def test_valid_quarantine_path(self, tmp_path):
        """Test that paths inside quarantine directory are accepted."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a file inside quarantine
        quarantine_file = quarantine_dir / "abc123_malware.exe"
        quarantine_file.write_text("fake quarantined content")

        is_valid, error = handler._validate_quarantine_path(str(quarantine_file))

        assert is_valid is True
        assert error is None

    def test_path_outside_quarantine_rejected(self, tmp_path):
        """Test that absolute paths outside quarantine directory are rejected."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a file outside quarantine
        outside_file = tmp_path / "outside" / "secret.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("secret content")

        is_valid, error = handler._validate_quarantine_path(str(outside_file))

        assert is_valid is False
        assert "not inside quarantine directory" in error

    def test_path_traversal_outside_quarantine_rejected(self, tmp_path):
        """Test that .. traversal to escape quarantine directory is rejected."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a file outside quarantine that we'll try to access via traversal
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("secret content")

        # Try to access via .. traversal
        traversal_path = str(quarantine_dir / ".." / "secret.txt")
        is_valid, error = handler._validate_quarantine_path(traversal_path)

        assert is_valid is False
        assert "not inside quarantine directory" in error

    def test_symlink_quarantine_path_rejected(self, tmp_path):
        """Test that symlinks inside quarantine directory are rejected."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a real file outside quarantine
        outside_file = tmp_path / "outside" / "secret.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("secret content")

        # Create a symlink inside quarantine pointing outside
        symlink_path = quarantine_dir / "symlink_to_secret"
        try:
            symlink_path.symlink_to(outside_file)

            is_valid, error = handler._validate_quarantine_path(str(symlink_path))

            assert is_valid is False
            assert "symlink" in error.lower()
        finally:
            if symlink_path.is_symlink():
                symlink_path.unlink()

    def test_empty_quarantine_path_rejected(self, tmp_path):
        """Test that empty paths are rejected."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Test empty string
        is_valid, error = handler._validate_quarantine_path("")
        assert is_valid is False
        assert "cannot be empty" in error

        # Test whitespace-only string
        is_valid, error = handler._validate_quarantine_path("   ")
        assert is_valid is False
        assert "cannot be empty" in error

    def test_nonexistent_path_inside_quarantine_accepted(self, tmp_path):
        """Test that nonexistent paths inside quarantine are accepted.

        This allows validation before file existence check in restore/delete.
        """
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Path that doesn't exist but is inside quarantine
        nonexistent_path = str(quarantine_dir / "nonexistent_file.quar")
        is_valid, error = handler._validate_quarantine_path(nonexistent_path)

        assert is_valid is True
        assert error is None


class TestRestoreFromQuarantinePathValidation:
    """Tests for quarantine path validation in restore_from_quarantine()."""

    def test_restore_rejects_quarantine_path_outside_dir(self, tmp_path):
        """Test that restore_from_quarantine rejects source paths outside quarantine."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a file outside quarantine
        outside_file = tmp_path / "outside" / "secret.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("secret content")

        # Try to restore from outside quarantine
        result = handler.restore_from_quarantine(
            str(outside_file), str(tmp_path / "restored" / "file.txt")
        )

        assert result.status == FileOperationStatus.INVALID_QUARANTINE_PATH
        assert result.error_message is not None
        assert "not inside quarantine directory" in result.error_message

    def test_restore_rejects_symlink_quarantine_path(self, tmp_path):
        """Test that restore_from_quarantine rejects symlink source paths."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a real file outside quarantine
        outside_file = tmp_path / "outside" / "secret.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("secret content")

        # Create a symlink inside quarantine pointing outside
        symlink_path = quarantine_dir / "symlink_to_secret"
        try:
            symlink_path.symlink_to(outside_file)

            result = handler.restore_from_quarantine(
                str(symlink_path), str(tmp_path / "restored" / "file.txt")
            )

            assert result.status == FileOperationStatus.INVALID_QUARANTINE_PATH
            assert "symlink" in result.error_message.lower()
        finally:
            if symlink_path.is_symlink():
                symlink_path.unlink()

    def test_restore_quarantine_path_validation_before_restore_path_validation(self, tmp_path):
        """Test that quarantine path validation happens before restore path validation."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a file outside quarantine
        outside_file = tmp_path / "outside" / "secret.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("secret content")

        # Try to restore from outside quarantine to a protected directory
        # Should fail with INVALID_QUARANTINE_PATH, not INVALID_RESTORE_PATH
        result = handler.restore_from_quarantine(str(outside_file), "/etc/malicious.conf")

        assert result.status == FileOperationStatus.INVALID_QUARANTINE_PATH


class TestDeleteFromQuarantinePathValidation:
    """Tests for quarantine path validation in delete_from_quarantine()."""

    def test_delete_rejects_quarantine_path_outside_dir(self, tmp_path):
        """Test that delete_from_quarantine rejects paths outside quarantine."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a file outside quarantine
        outside_file = tmp_path / "outside" / "important.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("important content")

        # Try to delete file outside quarantine
        result = handler.delete_from_quarantine(str(outside_file))

        assert result.status == FileOperationStatus.INVALID_QUARANTINE_PATH
        assert result.error_message is not None
        assert "not inside quarantine directory" in result.error_message
        # Verify file still exists
        assert outside_file.exists()

    def test_delete_rejects_symlink_quarantine_path(self, tmp_path):
        """Test that delete_from_quarantine rejects symlink paths."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a real file outside quarantine
        outside_file = tmp_path / "outside" / "important.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("important content")

        # Create a symlink inside quarantine pointing outside
        symlink_path = quarantine_dir / "symlink_to_important"
        try:
            symlink_path.symlink_to(outside_file)

            result = handler.delete_from_quarantine(str(symlink_path))

            assert result.status == FileOperationStatus.INVALID_QUARANTINE_PATH
            assert "symlink" in result.error_message.lower()
            # Verify the target file still exists
            assert outside_file.exists()
        finally:
            if symlink_path.is_symlink():
                symlink_path.unlink()

    def test_delete_rejects_path_traversal(self, tmp_path):
        """Test that delete_from_quarantine rejects .. traversal paths."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a file outside quarantine
        outside_file = tmp_path / "important.txt"
        outside_file.write_text("important content")

        # Try to delete via .. traversal
        traversal_path = str(quarantine_dir / ".." / "important.txt")
        result = handler.delete_from_quarantine(traversal_path)

        assert result.status == FileOperationStatus.INVALID_QUARANTINE_PATH
        assert "not inside quarantine directory" in result.error_message
        # Verify file still exists
        assert outside_file.exists()

    def test_delete_accepts_valid_quarantine_path(self, tmp_path):
        """Test that delete_from_quarantine accepts valid paths inside quarantine."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a file inside quarantine
        quarantine_file = quarantine_dir / "abc123_malware.exe"
        quarantine_file.write_text("fake quarantined content")

        result = handler.delete_from_quarantine(str(quarantine_file))

        assert result.status == FileOperationStatus.SUCCESS
        assert not quarantine_file.exists()


class TestRestorePermissionErrors:
    """Tests for permission-related errors in restore_from_quarantine()."""

    def test_restore_source_file_unreadable(self, tmp_path):
        """Test restore fails when source quarantine file is unreadable."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file with no read permissions
        quarantine_file = quarantine_dir / "abc123_secret.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o000)

        restore_path = tmp_path / "restored" / "file.txt"

        try:
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            # Should fail due to permission denied reading file for hash/size
            assert result.status == FileOperationStatus.PERMISSION_DENIED
            assert result.error_message is not None
            assert "permission" in result.error_message.lower()
        finally:
            # Restore permissions for cleanup
            os.chmod(quarantine_file, 0o644)

    def test_restore_destination_directory_not_writable(self, tmp_path):
        """Test restore fails when destination directory is not writable."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        # Create a destination directory with no write permissions
        dest_dir = tmp_path / "readonly_dest"
        dest_dir.mkdir(mode=0o500)
        restore_path = dest_dir / "file.txt"

        try:
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            # Should fail due to permission denied during move
            assert result.status == FileOperationStatus.PERMISSION_DENIED
            assert result.error_message is not None
        finally:
            # Restore permissions for cleanup
            os.chmod(dest_dir, 0o755)

    def test_restore_cannot_create_parent_directory(self, tmp_path):
        """Test restore fails when parent directory cannot be created."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        # Create a read-only directory - can't create subdirs inside
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir(mode=0o500)
        restore_path = readonly_dir / "subdir" / "file.txt"

        try:
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            # Should fail due to permission denied creating directory
            assert result.status == FileOperationStatus.PERMISSION_DENIED
            assert result.error_message is not None
            assert "directory" in result.error_message.lower()
        finally:
            # Restore permissions for cleanup
            os.chmod(readonly_dir, 0o755)

    def test_restore_fchmod_fails_after_copy(self, tmp_path):
        """Test that restore reports PERMISSION_DENIED when fchmod fails after copy."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "file.txt"

        import errno as _errno

        with mock.patch(
            "os.fchmod",
            side_effect=PermissionError(_errno.EACCES, "Cannot change permissions"),
        ):
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path), 0o755)

            assert result.status == FileOperationStatus.PERMISSION_DENIED
            assert result.error_message is not None

    def test_restore_link_permission_error(self, tmp_path):
        """Test restore fails with PERMISSION_DENIED when os.link raises PermissionError."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "file.txt"

        import errno as _errno

        with mock.patch(
            "os.write",
            side_effect=PermissionError(_errno.EACCES, "Permission denied during restore"),
        ):
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            assert result.status == FileOperationStatus.PERMISSION_DENIED
            assert "permission denied" in result.error_message.lower()


class TestRestoreFileConflicts:
    """Tests for file conflict errors in restore_from_quarantine()."""

    def test_restore_fails_when_file_already_exists(self, tmp_path):
        """Test restore fails when a regular file already exists at restore location."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        # Create a file that already exists at restore destination
        restore_path = tmp_path / "existing_file.txt"
        restore_path.write_text("I already exist!")

        result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

        assert result.status == FileOperationStatus.ALREADY_EXISTS
        assert result.error_message is not None
        assert "already exists" in result.error_message.lower()
        # Original file should remain unchanged
        assert restore_path.read_text() == "I already exist!"

    def test_restore_fails_when_symlink_exists_at_location(self, tmp_path):
        """Test restore fails when a symlink exists at restore location."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        # Create a target for the symlink
        symlink_target = tmp_path / "target.txt"
        symlink_target.write_text("symlink target")

        # Create a symlink at the restore location
        restore_path = tmp_path / "symlink_at_dest"
        restore_path.symlink_to(symlink_target)

        try:
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            assert result.status == FileOperationStatus.ALREADY_EXISTS
            assert result.error_message is not None
            assert "already exists" in result.error_message.lower()
        finally:
            if restore_path.is_symlink():
                restore_path.unlink()

    def test_restore_fails_when_directory_exists_at_location(self, tmp_path):
        """Test restore fails when a directory exists at restore location."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        # Create a directory at the restore location
        restore_path = tmp_path / "existing_directory"
        restore_path.mkdir()

        result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

        assert result.status == FileOperationStatus.ALREADY_EXISTS
        assert result.error_message is not None
        assert "already exists" in result.error_message.lower()


class TestRestoreIntegrityChecks:
    """Tests for integrity check failures in restore_from_quarantine()."""

    def test_restore_fails_when_file_is_not_regular_file(self, tmp_path):
        """Test restore fails when quarantine path is not a regular file."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a directory inside quarantine instead of a file
        quarantine_subdir = quarantine_dir / "not_a_file"
        quarantine_subdir.mkdir()

        restore_path = tmp_path / "restored" / "file.txt"

        result = handler.restore_from_quarantine(str(quarantine_subdir), str(restore_path))

        assert result.status == FileOperationStatus.ERROR
        assert result.error_message is not None
        assert "not a regular file" in result.error_message.lower()

    def test_restore_fails_when_quarantine_file_not_found(self, tmp_path):
        """Test restore fails when quarantined file doesn't exist."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Reference a file that doesn't exist
        nonexistent_file = quarantine_dir / "nonexistent.txt"
        restore_path = tmp_path / "restored" / "file.txt"

        result = handler.restore_from_quarantine(str(nonexistent_file), str(restore_path))

        assert result.status == FileOperationStatus.FILE_NOT_FOUND
        assert result.error_message is not None
        assert "not found" in result.error_message.lower()

    def test_restore_read_fails(self, tmp_path):
        """Test restore fails when reading the quarantine file raises an I/O error."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "file.txt"

        with mock.patch("os.read", side_effect=OSError("I/O error reading file")):
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            assert result.status == FileOperationStatus.ERROR
            assert result.error_message is not None

    def test_restore_fstat_fails(self, tmp_path):
        """Test restore fails when fstat on the quarantine file raises an error."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "file.txt"

        with mock.patch("os.fstat", side_effect=OSError("Cannot stat quarantine file")):
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            assert result.status == FileOperationStatus.ERROR
            assert result.error_message is not None


class TestRestoreShutilErrors:
    """Tests for shutil.move errors in restore_from_quarantine()."""

    def test_restore_write_error(self, tmp_path):
        """Test restore fails with ERROR status when writing to destination raises OSError."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "file.txt"

        with mock.patch("os.write", side_effect=OSError("Disk I/O error")):
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            assert result.status == FileOperationStatus.ERROR
            assert result.error_message is not None

    def test_restore_oserror(self, tmp_path):
        """Test restore fails with ERROR status on generic OSError during copy."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "file.txt"

        with mock.patch("os.write", side_effect=OSError("Disk I/O error")):
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            assert result.status == FileOperationStatus.ERROR
            assert result.error_message is not None

    def test_restore_mkdir_oserror(self, tmp_path):
        """Test restore fails when mkdir raises OSError."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("quarantined content")
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "subdir" / "file.txt"

        # Mock Path.mkdir to raise OSError
        with mock.patch.object(Path, "mkdir", side_effect=OSError("Filesystem error")):
            result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

            assert result.status == FileOperationStatus.ERROR
            assert "directory" in result.error_message.lower()


class TestRestoreSuccessfulOperation:
    """Tests for successful restore operations with various edge cases."""

    def test_restore_success_with_custom_permissions(self, tmp_path):
        """Test successful restore with custom file permissions."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_script.sh"
        quarantine_file.write_text("#!/bin/bash\necho hello")
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "script.sh"
        original_permissions = 0o755

        result = handler.restore_from_quarantine(
            str(quarantine_file), str(restore_path), original_permissions
        )

        assert result.status == FileOperationStatus.SUCCESS
        assert result.is_success
        assert restore_path.exists()
        # Check permissions were restored
        actual_perms = stat.S_IMODE(restore_path.stat().st_mode)
        assert actual_perms == original_permissions
        assert result.original_permissions == original_permissions

    def test_restore_success_creates_parent_directories(self, tmp_path):
        """Test successful restore creates nested parent directories."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text("content")
        os.chmod(quarantine_file, 0o400)

        # Restore to deeply nested path
        restore_path = tmp_path / "a" / "b" / "c" / "d" / "file.txt"

        result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

        assert result.status == FileOperationStatus.SUCCESS
        assert restore_path.exists()
        assert restore_path.read_text() == "content"

    def test_restore_returns_correct_file_hash(self, tmp_path):
        """Test successful restore returns the correct file hash."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file with known content
        test_content = "Hello, World!"
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text(test_content)
        os.chmod(quarantine_file, 0o400)

        # Calculate expected hash before restore
        expected_hash, _ = handler.calculate_hash(quarantine_file)

        restore_path = tmp_path / "restored" / "file.txt"

        result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

        assert result.status == FileOperationStatus.SUCCESS
        assert result.file_hash == expected_hash
        assert len(result.file_hash) == 64  # SHA256 hex digest length

    def test_restore_returns_correct_file_size(self, tmp_path):
        """Test successful restore returns the correct file size."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir(mode=0o700)
        handler = SecureFileHandler(str(quarantine_dir))

        # Create a quarantined file with known size
        test_content = "X" * 1000  # 1000 bytes
        quarantine_file = quarantine_dir / "abc123_file.txt"
        quarantine_file.write_text(test_content)
        os.chmod(quarantine_file, 0o400)

        restore_path = tmp_path / "restored" / "file.txt"

        result = handler.restore_from_quarantine(str(quarantine_file), str(restore_path))

        assert result.status == FileOperationStatus.SUCCESS
        assert result.file_size == 1000


class TestVerifyFileIntegrity:
    """Tests for verify_file_integrity() method used in restore operations."""

    def test_verify_integrity_success(self, tmp_path):
        """Test verify_file_integrity returns True for matching hash."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Calculate the actual hash
        actual_hash, _ = handler.calculate_hash(test_file)

        is_valid, error = handler.verify_file_integrity(str(test_file), actual_hash)

        assert is_valid is True
        assert error is None

    def test_verify_integrity_hash_mismatch(self, tmp_path):
        """Test verify_file_integrity returns False for mismatched hash."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Use a wrong hash
        wrong_hash = "a" * 64

        is_valid, error = handler.verify_file_integrity(str(test_file), wrong_hash)

        assert is_valid is False
        assert "mismatch" in error.lower()
        assert "corrupted" in error.lower()

    def test_verify_integrity_file_not_found(self, tmp_path):
        """Test verify_file_integrity handles missing files."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        nonexistent_file = tmp_path / "nonexistent.txt"

        is_valid, error = handler.verify_file_integrity(str(nonexistent_file), "abc123")

        assert is_valid is False
        assert "not found" in error.lower()

    def test_verify_integrity_permission_denied(self, tmp_path):
        """Test verify_file_integrity handles permission errors."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        os.chmod(test_file, 0o000)

        try:
            is_valid, error = handler.verify_file_integrity(str(test_file), "abc123")

            assert is_valid is False
            assert "permission" in error.lower()
        finally:
            os.chmod(test_file, 0o644)


# ── TOCTOU security tests ──────────────────────────────────────────────────────


class TestUnlinkat:
    """Security tests for the _unlinkat() helper.

    _unlinkat() anchors the unlink to an already-opened parent directory fd
    (os.unlink with dir_fd=), reducing the TOCTOU window to the single final
    name component inside that directory.  The parent is opened with
    O_NOFOLLOW|O_DIRECTORY, so a symlink masquerading as the parent is rejected.
    """

    def test_removes_regular_file(self, tmp_path):
        """Happy path: file inside a subdirectory is removed."""
        d = tmp_path / "dir"
        d.mkdir()
        f = d / "file.txt"
        f.write_text("data")

        _unlinkat(f)

        assert not f.exists()

    def test_nonexistent_file_raises_oserror(self, tmp_path):
        """Removing a nonexistent file raises OSError (ENOENT)."""
        with pytest.raises(OSError) as exc:
            _unlinkat(tmp_path / "nonexistent.txt")
        assert exc.value.errno == errno.ENOENT

    def test_parent_symlink_rejected(self, tmp_path):
        """O_NOFOLLOW|O_DIRECTORY on the parent rejects a symlink-as-parent.

        This guards against an attacker swapping an intermediate path component
        to a symlink between the moment we open the parent and the unlink call.

        On Linux, O_NOFOLLOW|O_DIRECTORY applied to a symlink-to-directory
        raises ENOTDIR (the kernel refuses to treat the un-followed symlink
        as a directory) rather than ELOOP.  Both indicate the symlink was NOT
        followed — either errno is acceptable here.
        """
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "link"
        link_dir.symlink_to(real_dir)

        f = real_dir / "file.txt"
        f.write_text("data")

        # path.parent resolves to the symlink path, not the real dir
        with pytest.raises(OSError) as exc:
            _unlinkat(link_dir / "file.txt")
        assert exc.value.errno in (errno.ELOOP, errno.ENOTDIR)

        assert f.exists()  # real file must be untouched

    def test_uses_dir_fd_not_absolute_path(self, tmp_path):
        """_unlinkat passes dir_fd= to os.unlink rather than the full path.

        If the full path were re-resolved at unlink time, an intermediate
        component could be swapped.  Verify dir_fd is present in the call.
        """
        d = tmp_path / "dir"
        d.mkdir()
        f = d / "file.txt"
        f.write_text("data")

        captured = {}
        real_unlink = os.unlink

        def spy_unlink(path, *args, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return real_unlink(path, *args, **kwargs)

        with mock.patch("os.unlink", side_effect=spy_unlink):
            _unlinkat(f)

        # The name passed to unlink must be just the basename, not the full path
        assert captured["path"] == "file.txt"
        assert "dir_fd" in captured["kwargs"]
        assert isinstance(captured["kwargs"]["dir_fd"], int)

    def test_removes_symlink_itself_not_target(self, tmp_path):
        """When the name inside the directory is a symlink, unlinkat removes
        the symlink entry, leaving the target file intact."""
        d = tmp_path / "dir"
        d.mkdir()
        target = tmp_path / "target.txt"
        target.write_text("keep me")
        link = d / "link"
        link.symlink_to(target)

        _unlinkat(link)

        assert not link.exists()
        assert target.exists()


class TestMoveToQuarantineTOCTOU:
    """Tests that move_to_quarantine() resists TOCTOU attacks.

    The key invariants:
    - Source opened with O_NOFOLLOW → symlink swap between scan and quarantine
      is caught at open time, not after a separate is_symlink() check.
    - fstat(S_ISREG) on the open fd → non-regular-file injection is caught
      without a TOCTOU window between stat and open.
    - Destination created with O_CREAT|O_EXCL|O_NOFOLLOW → pre-planted symlink
      at the destination is rejected atomically.
    """

    def test_symlink_source_rejected(self, tmp_path):
        """O_NOFOLLOW in move_to_quarantine rejects a symlink as the source file.

        Simulates the scan-to-quarantine race: attacker replaces the scanned
        regular file with a symlink pointing to a sensitive file.
        """
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        target = tmp_path / "sensitive.txt"
        target.write_text("sensitive data")
        symlink = tmp_path / "infected.exe"
        symlink.symlink_to(target)

        result = handler.move_to_quarantine(str(symlink))

        assert result.status == FileOperationStatus.ERROR
        assert "symlink" in result.error_message.lower()

    def test_symlink_source_leaves_target_untouched(self, tmp_path):
        """When the symlink source is rejected, the symlink target is not moved."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        target = tmp_path / "sensitive.txt"
        target.write_text("original content")
        symlink = tmp_path / "link"
        symlink.symlink_to(target)

        handler.move_to_quarantine(str(symlink))

        assert target.exists()
        assert target.read_text() == "original content"

    def test_char_device_rejected_as_not_regular_file(self, tmp_path):
        """fstat S_ISREG check rejects character devices.

        An attacker could replace the target file with a device node between scan
        and quarantine.  The fstat check on the already-open fd catches this
        without a separate stat+open window.  /dev/null is used here instead of a
        FIFO because opening a FIFO for reading blocks without a writer.
        """
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        result = handler.move_to_quarantine("/dev/null")

        assert result.status == FileOperationStatus.ERROR
        assert "not a regular file" in result.error_message.lower()

    def test_directory_rejected_as_not_regular_file(self, tmp_path):
        """fstat S_ISREG check rejects a directory passed as the source."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        subdir = tmp_path / "subdir"
        subdir.mkdir()

        result = handler.move_to_quarantine(str(subdir))

        assert result.status == FileOperationStatus.ERROR
        assert "not a regular file" in result.error_message.lower()

    def test_success_source_removed(self, tmp_path):
        """Successful quarantine atomically removes the source file."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        source = tmp_path / "malware.exe"
        source.write_text("malware payload")

        result = handler.move_to_quarantine(str(source))

        assert result.is_success
        assert not source.exists()

    def test_success_content_preserved(self, tmp_path):
        """Successful quarantine preserves file content exactly."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        content = "malware payload " * 100
        source = tmp_path / "malware.exe"
        source.write_text(content)

        result = handler.move_to_quarantine(str(source))

        assert result.is_success
        assert Path(result.destination_path).read_text() == content

    def test_success_restrictive_permissions_on_destination(self, tmp_path):
        """Destination file in quarantine is set to 0o400 via fchmod on the fd
        (no path-based TOCTOU between write and chmod)."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        source = tmp_path / "malware.exe"
        source.write_text("data")

        result = handler.move_to_quarantine(str(source))

        assert result.is_success
        actual = stat.S_IMODE(Path(result.destination_path).stat().st_mode)
        assert actual == SecureFileHandler.QUARANTINE_FILE_PERMISSIONS

    def test_abspath_does_not_dereference_symlinks(self, tmp_path):
        """os.path.abspath() normalises . and .. without following symlinks.

        If the caller used Path.resolve() instead, a symlink swap between scan
        and quarantine would cause resolve() to return the target path *before*
        O_NOFOLLOW could act, defeating the guard.  This test documents and
        locks in the abspath behaviour.
        """
        target = tmp_path / "sensitive.txt"
        target.write_text("sensitive")
        link = tmp_path / "infected.exe"
        link.symlink_to(target)

        abspath_result = os.path.abspath(str(link))
        resolve_result = str(link.resolve())

        # abspath preserves the symlink name in the path
        assert Path(abspath_result).name == "infected.exe"
        # resolve() would expose the underlying target
        assert Path(resolve_result).name == "sensitive.txt"


class TestCalculateHashSecurity:
    """Tests that calculate_hash() rejects symlinks via O_NOFOLLOW."""

    def test_symlink_rejected(self, tmp_path):
        """calculate_hash opens with O_NOFOLLOW, so a symlink source is rejected."""
        handler = SecureFileHandler(str(tmp_path / "quarantine"))

        target = tmp_path / "real.txt"
        target.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(target)

        hash_val, error = handler.calculate_hash(link)

        assert hash_val is None
        assert error is not None


class TestListQuarantinedFilesSecurity:
    """Tests that list_quarantined_files() uses lstat and is not confused by symlinks."""

    def test_symlinks_not_listed(self, tmp_path):
        """list_quarantined_files uses lstat so symlinks planted in the quarantine
        directory are not reported as quarantined files."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        real_file = quarantine_dir / "abc123_malware.exe"
        real_file.write_text("malware")

        outside = tmp_path / "outside.txt"
        outside.write_text("outside")
        evil_link = quarantine_dir / "evil_link"
        evil_link.symlink_to(outside)

        try:
            files = handler.list_quarantined_files()
            names = {f["filename"] for f in files}
            assert "abc123_malware.exe" in names
            assert "evil_link" not in names
        finally:
            if evil_link.is_symlink():
                evil_link.unlink()

    def test_directories_not_listed(self, tmp_path):
        """list_quarantined_files skips subdirectories (lstat S_ISREG check)."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        subdir = quarantine_dir / "subdir"
        subdir.mkdir()
        real_file = quarantine_dir / "file.txt"
        real_file.write_text("data")

        files = handler.list_quarantined_files()
        names = {f["filename"] for f in files}

        assert "file.txt" in names
        assert "subdir" not in names

    def test_lstat_no_toctou_between_isfile_and_stat(self, tmp_path):
        """list_quarantined_files performs a single lstat() call per entry,
        eliminating the is_file()+stat() TOCTOU window.  Verify that a symlink
        swapped in after the directory listing does not inflate the file count."""
        quarantine_dir = tmp_path / "quarantine"
        quarantine_dir.mkdir()
        handler = SecureFileHandler(str(quarantine_dir))

        real_file = quarantine_dir / "legit.txt"
        real_file.write_text("data")

        # Plant a dead symlink (points to nothing) — lstat sees S_ISLNK, skipped
        dead_link = quarantine_dir / "dead_link"
        dead_link.symlink_to(quarantine_dir / "nonexistent_target")
        try:
            files = handler.list_quarantined_files()
            assert len(files) == 1
            assert files[0]["filename"] == "legit.txt"
        finally:
            if dead_link.is_symlink():
                dead_link.unlink()


class TestDatabasePermissionSecurity:
    """Tests that _secure_db_file_permissions() resists symlink attacks.

    Change 4: database.py now opens each DB file with O_NOFOLLOW before
    fchmod, so a symlink planted at a WAL/SHM path cannot redirect the
    chmod to an arbitrary file.
    """

    def test_symlink_at_wal_path_silently_skipped(self, tmp_path):
        """A symlink planted at the .db-wal path is silently skipped (ELOOP → continue).

        Without O_NOFOLLOW, fchmod on the symlink would follow it and change
        permissions on the symlink target.
        """
        db_path = tmp_path / "quarantine.db"
        db = QuarantineDatabase(str(db_path), pool_size=0)

        wal_path = Path(str(db_path) + "-wal")
        sensitive = tmp_path / "sensitive.txt"
        sensitive.write_text("sensitive")
        original_mode = stat.S_IMODE(sensitive.stat().st_mode)

        if not wal_path.exists():
            wal_path.symlink_to(sensitive)
            try:
                db._secure_db_file_permissions()  # must not raise

                # Sensitive file permissions must NOT have been changed to 0o600
                assert stat.S_IMODE(sensitive.stat().st_mode) == original_mode
            finally:
                if wal_path.is_symlink():
                    wal_path.unlink()

        db.close()

    def test_main_db_file_has_restrictive_permissions(self, tmp_path):
        """The main .db file is set to 0o600 after initialisation."""
        db_path = tmp_path / "test_quarantine.db"
        db = QuarantineDatabase(str(db_path), pool_size=0)
        try:
            actual = stat.S_IMODE(db_path.stat().st_mode)
            assert actual == QuarantineDatabase.DB_FILE_PERMISSIONS
        finally:
            db.close()
