# ClamUI Secure File Handler Module
"""
Secure file handler for quarantine operations with atomic operations and permission management.

Provides secure file movement to/from quarantine with:
- Atomic operations (move, not copy-delete)
- SHA256 hash calculation for integrity verification
- Restrictive file permissions (0o700 directory, 0o400 files)
- Cross-platform path handling via pathlib
"""

import contextlib
import errno
import hashlib
import logging
import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class FileOperationStatus(Enum):
    """Status of a file operation."""

    SUCCESS = "success"
    ERROR = "error"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    ALREADY_EXISTS = "already_exists"
    DISK_FULL = "disk_full"
    INVALID_RESTORE_PATH = "invalid_restore_path"
    INVALID_QUARANTINE_PATH = "invalid_quarantine_path"


@dataclass
class FileOperationResult:
    """Result of a file operation."""

    status: FileOperationStatus
    source_path: str
    destination_path: str | None
    file_size: int
    file_hash: str
    error_message: str | None
    original_permissions: int = 0o644  # Original file permissions (st_mode & 0o777)

    @property
    def is_success(self) -> bool:
        """Check if the operation was successful."""
        return self.status == FileOperationStatus.SUCCESS


def _atomic_create_at_destination(source: Path, destination: Path, permissions: int) -> None:
    """Copy source into a newly created destination without following symlinks."""
    masked_permissions = permissions & 0o777
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd: int | None = None
    try:
        fd = os.open(destination, flags, masked_permissions)
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            fd = None
            shutil.copyfileobj(src, dst, length=SecureFileHandler.HASH_BUFFER_SIZE)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(destination, masked_permissions)
    except Exception:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            destination.unlink()
        raise


class SecureFileHandler:
    """
    Handler for secure file operations with permission management.

    Provides methods for moving files to/from quarantine with:
    - Atomic file operations using shutil.move
    - SHA256 hash calculation before operations
    - Restrictive permissions on quarantine directory and files
    - Thread-safe operations with file locking

    Example:
        >>> handler = SecureFileHandler("/home/user/.local/share/clamui/quarantine")
        >>> result = handler.move_to_quarantine("/home/user/infected.exe")
        >>> if result.is_success:
        ...     print(f"File quarantined at {result.destination_path}")
    """

    # Directory permission: owner read/write/execute only
    QUARANTINE_DIR_PERMISSIONS = 0o700

    # File permission: owner read-only (prevents execution)
    QUARANTINE_FILE_PERMISSIONS = 0o400

    # Buffer size for hash calculation (64KB)
    HASH_BUFFER_SIZE = 65536

    def __init__(self, quarantine_directory: str | None = None):
        """
        Initialize the SecureFileHandler.

        Args:
            quarantine_directory: Path to the quarantine directory.
                                  Defaults to XDG_DATA_HOME/clamui/quarantine
        """
        if quarantine_directory:
            self._quarantine_dir = Path(quarantine_directory).expanduser()
        else:
            xdg_data_home = os.environ.get("XDG_DATA_HOME", "~/.local/share")
            self._quarantine_dir = Path(xdg_data_home).expanduser() / "clamui" / "quarantine"

        # Thread lock for safe concurrent operations
        self._lock = threading.Lock()

        # Ensure quarantine directory exists with proper permissions
        self._ensure_quarantine_dir()

    @property
    def quarantine_directory(self) -> Path:
        """Get the quarantine directory path."""
        return self._quarantine_dir

    def _ensure_quarantine_dir(self) -> tuple[bool, str | None]:
        """
        Ensure the quarantine directory exists with proper permissions.

        Creates the directory if it doesn't exist and sets restrictive
        permissions (0o700 - owner read/write/execute only).

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Create directory with parents if it doesn't exist
            # Use mode= parameter to set permissions atomically, avoiding TOCTOU race
            # Note: mode is modified by umask, so we also call chmod after
            self._quarantine_dir.mkdir(
                parents=True, exist_ok=True, mode=self.QUARANTINE_DIR_PERMISSIONS
            )

            # Ensure restrictive permissions even if umask modified them
            os.chmod(self._quarantine_dir, self.QUARANTINE_DIR_PERMISSIONS)

            return (True, None)

        except PermissionError as e:
            return (False, f"Permission denied creating quarantine directory: {e}")
        except OSError as e:
            return (False, f"Error creating quarantine directory: {e}")

    def calculate_hash(self, file_path: Path) -> tuple[str | None, str | None]:
        """
        Calculate SHA256 hash of a file for integrity verification.

        Buffered Reading Benefit:
        - Reads file in 64KB chunks (HASH_BUFFER_SIZE) instead of loading entire file
        - Memory efficient for large files (e.g., 2GB file uses only 64KB RAM)
        - Prevents MemoryError on systems with limited RAM
        - Performance: ~same speed as read-all for small files, much better for large files
        - Example: Can hash a 10GB file using only 64KB of memory

        Uses buffered reading to handle large files efficiently without
        loading the entire file into memory.

        Args:
            file_path: Path to the file to hash

        Returns:
            Tuple of (hash_string, error_message):
            - (hash, None) if successful
            - (None, error_message) if failed

        Example:
            >>> handler = SecureFileHandler()
            >>> hash_value, error = handler.calculate_hash(Path("/path/to/file"))
            >>> if hash_value:
            ...     print(f"SHA256: {hash_value}")
        """
        try:
            sha256_hash = hashlib.sha256()

            with open(file_path, "rb") as f:
                for block in iter(lambda: f.read(self.HASH_BUFFER_SIZE), b""):
                    sha256_hash.update(block)

            return (sha256_hash.hexdigest(), None)

        except FileNotFoundError:
            return (None, f"File not found: {file_path}")
        except PermissionError:
            return (None, f"Permission denied reading file: {file_path}")
        except OSError as e:
            return (None, f"Error reading file: {e}")

    def get_file_size(self, file_path: Path) -> tuple[int, str | None]:
        """
        Get the size of a file in bytes.

        Args:
            file_path: Path to the file

        Returns:
            Tuple of (size_in_bytes, error_message):
            - (size, None) if successful
            - (-1, error_message) if failed
        """
        try:
            return (file_path.stat().st_size, None)
        except FileNotFoundError:
            return (-1, f"File not found: {file_path}")
        except PermissionError:
            return (-1, f"Permission denied accessing file: {file_path}")
        except OSError as e:
            return (-1, f"Error accessing file: {e}")

    def get_file_permissions(self, file_path: Path) -> tuple[int, str | None]:
        """
        Get the permissions of a file (st_mode & 0o777).

        Args:
            file_path: Path to the file

        Returns:
            Tuple of (permissions, error_message):
            - (permissions, None) if successful
            - (0o644, error_message) if failed (returns safe default)
        """
        try:
            return (file_path.stat().st_mode & 0o777, None)
        except FileNotFoundError:
            return (0o644, f"File not found: {file_path}")
        except PermissionError:
            return (0o644, f"Permission denied accessing file: {file_path}")
        except OSError as e:
            return (0o644, f"Error accessing file: {e}")

    def verify_file_integrity(self, file_path: str, expected_hash: str) -> tuple[bool, str | None]:
        """
        Verify file integrity by comparing hash.

        Args:
            file_path: Path to the file to verify
            expected_hash: Expected SHA256 hash

        Returns:
            Tuple of (is_valid, error_message)
        """
        actual_hash, error = self.calculate_hash(Path(file_path))
        if error:
            return (False, error)
        if actual_hash != expected_hash:
            return (False, "File hash mismatch - file may be corrupted")
        return (True, None)

    def _generate_quarantine_filename(self, original_path: Path) -> str:
        """
        Generate a unique filename for the quarantined file.

        Uses UUID to ensure uniqueness while preserving the original
        filename for identification.

        Args:
            original_path: Original file path

        Returns:
            Unique filename for quarantine storage

        Example:
            >>> handler._generate_quarantine_filename(Path("/home/user/malware.exe"))
            'a1b2c3d4-5678-90ab-cdef-1234567890ab_malware.exe'
        """
        unique_id = uuid.uuid4().hex[:16]
        original_name = original_path.name
        return f"{unique_id}_{original_name}"

    def _check_disk_space(self, file_size: int) -> tuple[bool, str | None]:
        """
        Check if there's enough disk space for the quarantine operation.

        Args:
            file_size: Size of the file to be quarantined in bytes

        Returns:
            Tuple of (has_space, error_message)
        """
        try:
            usage = shutil.disk_usage(self._quarantine_dir)
            # Require at least file_size + 10MB buffer
            required_space = file_size + (10 * 1024 * 1024)

            if usage.free < required_space:
                free_mb = usage.free / (1024 * 1024)
                return (False, f"Insufficient disk space. Only {free_mb:.1f} MB available")

            return (True, None)

        except OSError as e:
            return (False, f"Error checking disk space: {e}")

    def validate_restore_path(self, restore_path: str) -> tuple[bool, str | None]:
        """
        Validate a restore destination path for security.

        Checks that the restore path:
        1. Doesn't contain injection characters (newlines, null bytes)
        2. Doesn't point to protected system directories
        3. Resolves to a safe user-accessible location
        4. Symlinks in the path don't escape to protected directories

        This validation prevents attacks where a malicious actor could
        modify the quarantine database to restore files to system locations.

        Args:
            restore_path: The destination path to validate

        Returns:
            Tuple of (is_valid, error_message):
            - (True, None) if path is safe for restore
            - (False, error_message) if path is unsafe

        Example:
            >>> handler = SecureFileHandler()
            >>> is_valid, error = handler.validate_restore_path("/home/user/file.txt")
            >>> if is_valid:
            ...     print("Path is safe for restore")

            >>> is_valid, error = handler.validate_restore_path("/etc/passwd")
            >>> print(error)  # "Restore to protected system directory not allowed: /etc"
        """
        # Check for empty path
        if not restore_path or not restore_path.strip():
            return (False, "Restore path cannot be empty")

        # Security check: Reject paths with injection characters
        # These could be used to bypass validation or manipulate the filesystem
        if "\n" in restore_path or "\r" in restore_path:
            return (False, "Restore path contains illegal newline characters")

        if "\0" in restore_path:
            return (False, "Restore path contains illegal null bytes")

        # Convert to Path object for validation
        try:
            path_obj = Path(restore_path)
        except (ValueError, TypeError) as e:
            return (False, f"Invalid path format: {e}")

        # Define protected system directories that should never be restore targets
        # These directories contain critical system files and configuration
        protected_dirs = [
            Path("/etc"),  # System configuration
            Path("/var"),  # Variable data (includes system databases)
            Path("/usr"),  # System binaries and libraries
            Path("/bin"),  # Essential binaries
            Path("/sbin"),  # System binaries
            Path("/lib"),  # System libraries
            Path("/lib64"),  # 64-bit system libraries
            Path("/boot"),  # Boot files
            Path("/root"),  # Root user's home
            Path("/sys"),  # System virtual filesystem
            Path("/proc"),  # Process information virtual filesystem
        ]

        # Resolve the path to handle .. and symlinks
        try:
            resolved_path = path_obj.resolve()
        except (OSError, RuntimeError) as e:
            return (False, f"Cannot resolve restore path: {e}")

        # Check if the resolved path is under any protected directory
        for protected_dir in protected_dirs:
            try:
                # Check if resolved path is relative to (inside) the protected directory
                resolved_path.relative_to(protected_dir)
                # If we get here, the path IS inside the protected directory
                return (
                    False,
                    f"Restore to protected system directory not allowed: {protected_dir}",
                )
            except ValueError:
                # Path is not relative to this protected directory, continue checking
                continue

        # Check each component of the path for symlinks that might escape
        # to protected directories
        current_path = Path("/")
        for part in path_obj.parts[1:]:  # Skip the root "/"
            current_path = current_path / part

            # If this component is a symlink, check where it resolves to
            if current_path.is_symlink():
                try:
                    symlink_target = current_path.resolve()

                    # Check if the symlink target is in a protected directory
                    for protected_dir in protected_dirs:
                        try:
                            symlink_target.relative_to(protected_dir)
                            return (
                                False,
                                f"Path contains symlink to protected directory: "
                                f"{current_path} -> {symlink_target}",
                            )
                        except ValueError:
                            # Not in this protected directory, continue
                            continue

                except (OSError, RuntimeError) as e:
                    return (False, f"Error resolving symlink in path: {e}")

        # Path passed all security checks
        return (True, None)

    def _validate_quarantine_path(self, quarantine_path: str) -> tuple[bool, str | None]:
        """
        Validate that a path is inside the quarantine directory.

        Ensures the quarantine path:
        1. Is not empty
        2. Is not a symlink (prevents symlink attacks)
        3. Resolves to a location inside self._quarantine_dir

        This validation prevents attacks where a caller could pass an arbitrary
        filesystem path to restore_from_quarantine or delete_from_quarantine,
        potentially accessing or deleting files outside the quarantine directory.

        Args:
            quarantine_path: The quarantine path to validate

        Returns:
            Tuple of (is_valid, error_message):
            - (True, None) if path is a valid quarantine path
            - (False, error_message) if path is invalid

        Example:
            >>> handler = SecureFileHandler("/home/user/.local/share/clamui/quarantine")
            >>> is_valid, error = handler._validate_quarantine_path(
            ...     "/home/user/.local/share/clamui/quarantine/abc123_file.txt"
            ... )
            >>> if is_valid:
            ...     print("Path is valid quarantine path")
        """
        # Check for empty path
        if not quarantine_path or not quarantine_path.strip():
            return (False, "Quarantine path cannot be empty")

        # Convert to Path object
        try:
            path_obj = Path(quarantine_path)
        except (ValueError, TypeError) as e:
            return (False, f"Invalid path format: {e}")

        # Security check: Reject symlinks to prevent symlink attacks
        # A symlink could point outside the quarantine directory
        if path_obj.is_symlink():
            return (
                False,
                f"Quarantine path cannot be a symlink: {quarantine_path}",
            )

        # Resolve the path to handle .. and get absolute path
        try:
            resolved_path = path_obj.resolve()
            resolved_quarantine_dir = self._quarantine_dir.resolve()
        except (OSError, RuntimeError) as e:
            return (False, f"Cannot resolve quarantine path: {e}")

        # Check if the resolved path is inside the quarantine directory
        try:
            resolved_path.relative_to(resolved_quarantine_dir)
            # If we get here, the path IS inside the quarantine directory
            return (True, None)
        except ValueError:
            # Path is not inside the quarantine directory
            return (
                False,
                f"Path is not inside quarantine directory: {quarantine_path}",
            )

    def move_to_quarantine(
        self, source_path: str, threat_name: str | None = None
    ) -> FileOperationResult:
        """
        Move a file to the quarantine directory securely.

        Performs the following operations atomically:
        1. Validates the source file exists and is readable
        2. Calculates SHA256 hash for integrity verification
        3. Checks available disk space
        4. Moves the file to quarantine directory
        5. Sets restrictive permissions on the quarantined file

        Args:
            source_path: Path to the file to quarantine
            threat_name: Optional threat name for logging (not used in filename)

        Returns:
            FileOperationResult with operation status and details

        Example:
            >>> handler = SecureFileHandler()
            >>> result = handler.move_to_quarantine("/home/user/infected.exe")
            >>> if result.is_success:
            ...     print(f"Quarantined: {result.destination_path}")
            ...     print(f"Hash: {result.file_hash}")
        """
        source_path_obj = Path(source_path)

        with self._lock:
            # Security check: Reject symlinks to prevent symlink attacks
            # A malicious symlink could point to system files or escape quarantine
            if source_path_obj.is_symlink():
                target = source_path_obj.resolve()
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=source_path,
                    destination_path=None,
                    file_size=0,
                    file_hash="",
                    error_message=(
                        f"Cannot quarantine symlinks for security reasons: "
                        f"{source_path} -> {target}"
                    ),
                )

            source = source_path_obj.resolve()

            # Validate source file exists
            if not source.exists():
                return FileOperationResult(
                    status=FileOperationStatus.FILE_NOT_FOUND,
                    source_path=str(source),
                    destination_path=None,
                    file_size=0,
                    file_hash="",
                    error_message=f"Source file not found: {source}",
                )

            # Check if it's a file (not directory)
            if not source.is_file():
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=str(source),
                    destination_path=None,
                    file_size=0,
                    file_hash="",
                    error_message=f"Source is not a file: {source}",
                )

            # Get file size
            file_size, size_error = self.get_file_size(source)
            if size_error:
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=str(source),
                    destination_path=None,
                    file_size=0,
                    file_hash="",
                    error_message=size_error,
                )

            # Get original file permissions before quarantine
            original_permissions, _ = self.get_file_permissions(source)

            # Calculate hash before moving
            file_hash, hash_error = self.calculate_hash(source)
            if hash_error:
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=str(source),
                    destination_path=None,
                    file_size=file_size,
                    file_hash="",
                    error_message=hash_error,
                )

            # Ensure quarantine directory exists
            dir_ok, dir_error = self._ensure_quarantine_dir()
            if not dir_ok:
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=str(source),
                    destination_path=None,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=dir_error,
                )

            # Check disk space
            has_space, space_error = self._check_disk_space(file_size)
            if not has_space:
                return FileOperationResult(
                    status=FileOperationStatus.DISK_FULL,
                    source_path=str(source),
                    destination_path=None,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=space_error,
                )

            # Generate unique quarantine filename
            quarantine_filename = self._generate_quarantine_filename(source)
            destination = self._quarantine_dir / quarantine_filename

            # Check if destination already exists (shouldn't happen with UUID)
            if destination.exists():
                return FileOperationResult(
                    status=FileOperationStatus.ALREADY_EXISTS,
                    source_path=str(source),
                    destination_path=str(destination),
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Destination already exists: {destination}",
                )

            try:
                # Atomic move operation using shutil.move():
                # - Same filesystem: Uses os.rename() - atomic, instant
                # - Cross-filesystem: Falls back to copy+delete (not atomic but safe)
                #   * Copies file to destination with temp name
                #   * Verifies copy succeeded
                #   * Deletes source only after successful copy
                #   * If interrupted, source remains intact (no data loss)
                # Why not os.rename(): Fails across filesystems (e.g., /home to /tmp)
                # Why not copy+delete manually: shutil.move handles cross-fs automatically
                shutil.move(str(source), str(destination))

                # Set restrictive permissions on quarantined file
                os.chmod(destination, self.QUARANTINE_FILE_PERMISSIONS)

                return FileOperationResult(
                    status=FileOperationStatus.SUCCESS,
                    source_path=str(source),
                    destination_path=str(destination),
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=None,
                    original_permissions=original_permissions,
                )

            except PermissionError as e:
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=str(source),
                    destination_path=None,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Permission denied during move: {e}",
                )
            except shutil.Error as e:
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=str(source),
                    destination_path=None,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Move operation failed: {e}",
                )
            except OSError as e:
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=str(source),
                    destination_path=None,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"File operation error: {e}",
                )

    def restore_from_quarantine(
        self,
        quarantine_path: str,
        original_path: str,
        original_permissions: int = 0o644,
    ) -> FileOperationResult:
        """
        Restore a file from quarantine to its original or specified location.

        Performs the following operations:
        1. Validates the restore destination path for security
        2. Checks that the quarantined file exists
        3. Optionally calculates hash to verify integrity
        4. Moves the file from quarantine to the restore destination
        5. Restores original file permissions

        Args:
            quarantine_path: Path to the quarantined file
            original_path: Original or target path for restoration
            original_permissions: Original file permissions to restore (st_mode & 0o777)

        Returns:
            FileOperationResult with operation status and details

        Example:
            >>> handler = SecureFileHandler()
            >>> result = handler.restore_from_quarantine(
            ...     "/home/user/.local/share/clamui/quarantine/abc123_file.txt",
            ...     "/home/user/file.txt",
            ...     0o755  # Restore executable permissions
            ... )
            >>> if result.is_success:
            ...     print(f"Restored to: {result.destination_path}")
        """
        quarantine_path_obj = Path(quarantine_path)

        with self._lock:
            # Validate quarantine source path is inside quarantine directory
            is_valid, validation_error = self._validate_quarantine_path(quarantine_path)
            if not is_valid:
                return FileOperationResult(
                    status=FileOperationStatus.INVALID_QUARANTINE_PATH,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=0,
                    file_hash="",
                    error_message=validation_error,
                )

            # Validate restore destination path
            is_valid, validation_error = self.validate_restore_path(original_path)
            if not is_valid:
                return FileOperationResult(
                    status=FileOperationStatus.INVALID_RESTORE_PATH,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=0,
                    file_hash="",
                    error_message=validation_error,
                )

            # Check if quarantined file exists
            if not quarantine_path_obj.exists():
                return FileOperationResult(
                    status=FileOperationStatus.FILE_NOT_FOUND,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=0,
                    file_hash="",
                    error_message=f"Quarantined file not found: {quarantine_path}",
                )

            # Check if it's a file (not directory)
            if not quarantine_path_obj.is_file():
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=0,
                    file_hash="",
                    error_message=f"Quarantined path is not a file: {quarantine_path}",
                )

            # Get file size
            file_size, size_error = self.get_file_size(quarantine_path_obj)
            if size_error:
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=0,
                    file_hash="",
                    error_message=size_error,
                )

            # Calculate hash before moving
            file_hash, hash_error = self.calculate_hash(quarantine_path_obj)
            if hash_error:
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash="",
                    error_message=hash_error,
                )

            # Create destination directory if needed
            destination_obj = Path(original_path)
            try:
                destination_obj.parent.mkdir(parents=True, exist_ok=True)
            except PermissionError as e:
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Permission denied creating destination directory: {e}",
                )
            except OSError as e:
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Error creating destination directory: {e}",
                )

            # Check if destination already exists
            if destination_obj.exists():
                return FileOperationResult(
                    status=FileOperationStatus.ALREADY_EXISTS,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Destination file already exists: {original_path}",
                )

            # Security: Check for symlink attack (TOCTOU mitigation)
            if destination_obj.is_symlink():
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Security: destination is a symlink, possible attack: {original_path}",
                )

            masked_permissions = original_permissions & 0o777
            destination_created = False
            try:
                try:
                    os.link(quarantine_path_obj, destination_obj)
                    destination_created = True
                    os.chmod(destination_obj, masked_permissions)
                except OSError as e:
                    if e.errno == errno.EXDEV:
                        _atomic_create_at_destination(
                            quarantine_path_obj,
                            destination_obj,
                            masked_permissions,
                        )
                        destination_created = True
                    elif e.errno == errno.EEXIST:
                        return FileOperationResult(
                            status=FileOperationStatus.ALREADY_EXISTS,
                            source_path=quarantine_path,
                            destination_path=original_path,
                            file_size=file_size,
                            file_hash=file_hash or "",
                            error_message=f"Destination file already exists: {original_path}",
                        )
                    else:
                        raise

                quarantine_path_obj.unlink()

                return FileOperationResult(
                    status=FileOperationStatus.SUCCESS,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=None,
                    original_permissions=masked_permissions,
                )

            except PermissionError as e:
                if destination_created and quarantine_path_obj.exists():
                    with contextlib.suppress(OSError):
                        destination_obj.unlink()
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Permission denied during restore: {e}",
                )
            except shutil.Error as e:
                if destination_created and quarantine_path_obj.exists():
                    with contextlib.suppress(OSError):
                        destination_obj.unlink()
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"Move operation failed: {e}",
                )
            except OSError as e:
                if destination_created and quarantine_path_obj.exists():
                    with contextlib.suppress(OSError):
                        destination_obj.unlink()
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=f"File operation error: {e}",
                )

    def list_quarantined_files(self) -> list[dict]:
        """
        List all files currently in quarantine.

        Returns:
            List of dictionaries containing file information:
            - filename: The quarantined filename
            - size: File size in bytes
            - path: Full path to the quarantined file
            - modified: Last modified timestamp

        Example:
            >>> handler = SecureFileHandler()
            >>> files = handler.list_quarantined_files()
            >>> for file_info in files:
            ...     print(f"{file_info['filename']}: {file_info['size']} bytes")
        """
        files = []

        try:
            for file_path in self._quarantine_dir.iterdir():
                if file_path.is_file():
                    stat_info = file_path.stat()
                    files.append(
                        {
                            "filename": file_path.name,
                            "size": stat_info.st_size,
                            "path": str(file_path),
                            "modified": stat_info.st_mtime,
                        }
                    )
        except PermissionError as e:
            logger.warning("Permission denied accessing quarantine file: %s", e)
        except OSError as e:
            logger.debug("Failed to stat quarantine file: %s", e)

        return files

    def delete_from_quarantine(self, quarantine_path: str) -> FileOperationResult:
        """
        Permanently delete a file from quarantine.

        Args:
            quarantine_path: Path to the quarantined file to delete

        Returns:
            FileOperationResult with operation status and details

        Example:
            >>> handler = SecureFileHandler()
            >>> result = handler.delete_from_quarantine(
            ...     "/home/user/.local/share/clamui/quarantine/abc123_malware.exe"
            ... )
            >>> if result.is_success:
            ...     print("File permanently deleted")
        """
        quarantine_path_obj = Path(quarantine_path)

        with self._lock:
            # Validate quarantine path is inside quarantine directory
            is_valid, validation_error = self._validate_quarantine_path(quarantine_path)
            if not is_valid:
                return FileOperationResult(
                    status=FileOperationStatus.INVALID_QUARANTINE_PATH,
                    source_path=quarantine_path,
                    destination_path=None,
                    file_size=0,
                    file_hash="",
                    error_message=validation_error,
                )

            # Check if file exists
            if not quarantine_path_obj.exists():
                return FileOperationResult(
                    status=FileOperationStatus.FILE_NOT_FOUND,
                    source_path=quarantine_path,
                    destination_path=None,
                    file_size=0,
                    file_hash="",
                    error_message=f"Quarantined file not found: {quarantine_path}",
                )

            # Get file size before deletion
            file_size, size_error = self.get_file_size(quarantine_path_obj)
            if size_error:
                file_size = 0

            try:
                # Remove file permissions to prevent accidental execution
                with contextlib.suppress(OSError):
                    os.chmod(quarantine_path_obj, 0o000)

                # Delete the file
                quarantine_path_obj.unlink()

                return FileOperationResult(
                    status=FileOperationStatus.SUCCESS,
                    source_path=quarantine_path,
                    destination_path=None,
                    file_size=file_size,
                    file_hash="",
                    error_message=None,
                )

            except PermissionError as e:
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED,
                    source_path=quarantine_path,
                    destination_path=None,
                    file_size=file_size,
                    file_hash="",
                    error_message=f"Permission denied deleting file: {e}",
                )
            except OSError as e:
                return FileOperationResult(
                    status=FileOperationStatus.ERROR,
                    source_path=quarantine_path,
                    destination_path=None,
                    file_size=file_size,
                    file_hash="",
                    error_message=f"Error deleting file: {e}",
                )
