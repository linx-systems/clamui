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
import stat
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# O_NOFOLLOW is required on every code path that opens user-controlled paths.
# It is available on Linux, macOS, and BSDs but not on Windows. ClamUI targets
# Linux only, so fail loudly at import time rather than silently degrading.
if not hasattr(os, "O_NOFOLLOW"):
    raise RuntimeError(
        "O_NOFOLLOW is not available on this platform. "
        "Quarantine file operations cannot be performed safely."
    )


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



def _unlinkat(path: Path) -> None:
    """Remove a file relative to its parent directory fd, without re-resolving the full path.

    Uses os.unlink(..., dir_fd=...) to anchor the operation to an already-opened
    parent directory, avoiding TOCTOU on path components.
    """
    parent_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        os.unlink(path.name, dir_fd=parent_fd)
    finally:
        with contextlib.suppress(OSError):
            os.close(parent_fd)


class SecureFileHandler:
    """
    Handler for secure file operations with permission management.

    Provides methods for moving files to/from quarantine with:
    - Atomic fd-based copy + unlink (O_NOFOLLOW throughout, no shutil.move)
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
            self._quarantine_dir.mkdir(
                parents=True, exist_ok=True, mode=self.QUARANTINE_DIR_PERMISSIONS
            )

            # O_NOFOLLOW rejects the quarantine dir being a symlink (ELOOP → error below).
            # fchmod via the resulting fd bypasses umask and avoids a path-based TOCTOU
            # window between mkdir and the permission set.
            dir_fd = os.open(
                self._quarantine_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fchmod(dir_fd, self.QUARANTINE_DIR_PERMISSIONS)
            finally:
                os.close(dir_fd)

            return (True, None)

        except PermissionError as e:
            return (False, f"Permission denied creating quarantine directory: {e}")
        except OSError as e:
            if e.errno == errno.ELOOP:
                return (
                    False,
                    f"Quarantine directory path is a symlink: {self._quarantine_dir}",
                )
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
            flags = os.O_RDONLY | os.O_NOFOLLOW
            fd: int | None = None
            try:
                fd = os.open(file_path, flags)
                with os.fdopen(fd, "rb") as f:
                    fd = None  # fdopen owns it now
                    for block in iter(lambda: f.read(self.HASH_BUFFER_SIZE), b""):
                        sha256_hash.update(block)
            except Exception:
                if fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                raise

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
            return (os.lstat(file_path).st_size, None)
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
            return (os.lstat(file_path).st_mode & 0o777, None)
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
        2. Resolves to a location inside self._quarantine_dir
           (symlink rejection is handled downstream by O_NOFOLLOW)

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

        # Resolve to handle .. and get absolute path for containment check.
        # Symlink rejection is handled downstream by O_NOFOLLOW; a separate
        # is_symlink() check here would introduce a new TOCTOU window.
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
            # Open source with O_NOFOLLOW — atomically rejects symlinks without a separate
            # is_symlink() check, eliminating the TOCTOU window between check and open.

            try:
                src_fd = os.open(source_path_obj, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError as e:
                if e.errno == errno.ELOOP:
                    return FileOperationResult(
                        status=FileOperationStatus.ERROR,
                        source_path=source_path,
                        destination_path=None,
                        file_size=0,
                        file_hash="",
                        error_message=f"Cannot quarantine symlinks for security reasons: {source_path}",
                    )
                if e.errno == errno.ENOENT:
                    return FileOperationResult(
                        status=FileOperationStatus.FILE_NOT_FOUND,
                        source_path=source_path,
                        destination_path=None,
                        file_size=0,
                        file_hash="",
                        error_message=f"Source file not found: {source_path}",
                    )
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED
                    if e.errno == errno.EACCES
                    else FileOperationStatus.ERROR,
                    source_path=source_path,
                    destination_path=None,
                    file_size=0,
                    file_hash="",
                    error_message=f"Cannot open source file: {e}",
                )

            file_size = 0
            original_permissions = 0o644
            destination: Path | None = None
            file_hash: str | None = None

            try:
                # fstat through the open fd — no TOCTOU between open and stat.
                try:
                    st = os.fstat(src_fd)
                except OSError as e:
                    return FileOperationResult(
                        status=FileOperationStatus.ERROR,
                        source_path=source_path,
                        destination_path=None,
                        file_size=0,
                        file_hash="",
                        error_message=f"Cannot stat source file: {e}",
                    )

                if not stat.S_ISREG(st.st_mode):
                    return FileOperationResult(
                        status=FileOperationStatus.ERROR,
                        source_path=source_path,
                        destination_path=None,
                        file_size=0,
                        file_hash="",
                        error_message=f"Source is not a regular file: {source_path}",
                    )

                file_size = st.st_size
                original_permissions = st.st_mode & 0o777

                # Ensure directory exists first — disk_usage() requires the path to exist
                # and must measure the correct filesystem.
                dir_ok, dir_error = self._ensure_quarantine_dir()
                if not dir_ok:
                    return FileOperationResult(
                        status=FileOperationStatus.PERMISSION_DENIED,
                        source_path=source_path,
                        destination_path=None,
                        file_size=file_size,
                        file_hash="",
                        error_message=dir_error,
                    )

                has_space, space_error = self._check_disk_space(file_size)
                if not has_space:
                    return FileOperationResult(
                        status=FileOperationStatus.DISK_FULL,
                        source_path=source_path,
                        destination_path=None,
                        file_size=file_size,
                        file_hash="",
                        error_message=space_error,
                    )

                quarantine_filename = self._generate_quarantine_filename(source_path_obj)
                destination = self._quarantine_dir / quarantine_filename

                # Open destination with O_CREAT|O_EXCL|O_NOFOLLOW — atomically creates and
                # rejects any pre-existing path, eliminating the exists()-then-create TOCTOU.
                dst_fd: int | None = None
                dst_created = False
                try:
                    dst_fd = os.open(
                        destination,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        self.QUARANTINE_FILE_PERMISSIONS,
                    )
                    dst_created = True
                    sha256_hash = hashlib.sha256()
                    while True:
                        block = os.read(src_fd, self.HASH_BUFFER_SIZE)
                        if not block:
                            break
                        sha256_hash.update(block)
                        os.write(dst_fd, block)
                    os.fsync(dst_fd)
                    # fchmod via fd before close — no path-based TOCTOU window, and
                    # bypasses umask so permissions are applied exactly as specified.
                    os.fchmod(dst_fd, self.QUARANTINE_FILE_PERMISSIONS)
                    os.close(dst_fd)
                    dst_fd = None
                    file_hash = sha256_hash.hexdigest()
                except OSError as e:
                    if dst_fd is not None:
                        with contextlib.suppress(OSError):
                            os.close(dst_fd)
                    if dst_created:
                        with contextlib.suppress(OSError):
                            _unlinkat(destination)
                    if e.errno == errno.EEXIST:
                        return FileOperationResult(
                            status=FileOperationStatus.ALREADY_EXISTS,
                            source_path=source_path,
                            destination_path=str(destination),
                            file_size=file_size,
                            file_hash="",
                            error_message=f"Destination already exists: {destination}",
                        )
                    if e.errno == errno.ENOSPC:
                        return FileOperationResult(
                            status=FileOperationStatus.DISK_FULL,
                            source_path=source_path,
                            destination_path=None,
                            file_size=file_size,
                            file_hash="",
                            error_message=f"Disk full during quarantine: {e}",
                        )
                    return FileOperationResult(
                        status=FileOperationStatus.PERMISSION_DENIED
                        if e.errno == errno.EACCES
                        else FileOperationStatus.ERROR,
                        source_path=source_path,
                        destination_path=None,
                        file_size=file_size,
                        file_hash="",
                        error_message=f"File operation error: {e}",
                    )

                # Before unlinking, verify the source path still names the same inode
                # we originally opened and copied. If an attacker swapped the file
                # between the copy and this point, the lstat would show a different
                # (st_dev, st_ino) and we abort rather than unlink the wrong file.
                # src_fd is still open (inode pinned), so st.st_ino is authoritative.
                try:
                    lst = os.lstat(source_path_obj)
                    if (lst.st_dev, lst.st_ino) != (st.st_dev, st.st_ino):
                        with contextlib.suppress(OSError):
                            if destination is not None:
                                _unlinkat(destination)
                        return FileOperationResult(
                            status=FileOperationStatus.ERROR,
                            source_path=source_path,
                            destination_path=str(destination) if destination else None,
                            file_size=file_size,
                            file_hash=file_hash or "",
                            error_message=f"Source file was replaced during quarantine; aborting: {source_path}",
                        )
                except OSError:
                    pass  # lstat failure: proceed — _unlinkat will raise ENOENT if gone

                # Unlink source while src_fd is still open (inode pinned) and via
                # _unlinkat() so the name is resolved relative to an already-opened
                # parent directory fd, closing the TOCTOU window on path components.
                try:
                    _unlinkat(source_path_obj)
                except OSError as e:
                    with contextlib.suppress(OSError):
                        if destination is not None:
                            _unlinkat(destination)
                    return FileOperationResult(
                        status=FileOperationStatus.PERMISSION_DENIED
                        if e.errno == errno.EACCES
                        else FileOperationStatus.ERROR,
                        source_path=source_path,
                        destination_path=str(destination) if destination else None,
                        file_size=file_size,
                        file_hash=file_hash or "",
                        error_message=f"Could not remove source file after copying to quarantine: {e}",
                    )

                return FileOperationResult(
                    status=FileOperationStatus.SUCCESS,
                    source_path=source_path,
                    destination_path=str(destination),
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=None,
                    original_permissions=original_permissions,
                )

            finally:
                with contextlib.suppress(OSError):
                    os.close(src_fd)

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

            # Open quarantine file with O_NOFOLLOW — rejects symlinks atomically, gives a
            # safe fd; eliminates exists()+is_file()+stat()+hash-open TOCTOU windows.
            try:
                src_fd = os.open(quarantine_path_obj, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    return FileOperationResult(
                        status=FileOperationStatus.FILE_NOT_FOUND,
                        source_path=quarantine_path,
                        destination_path=original_path,
                        file_size=0,
                        file_hash="",
                        error_message=f"Quarantined file not found: {quarantine_path}",
                    )
                if e.errno == errno.ELOOP:
                    return FileOperationResult(
                        status=FileOperationStatus.ERROR,
                        source_path=quarantine_path,
                        destination_path=original_path,
                        file_size=0,
                        file_hash="",
                        error_message=f"Security: quarantine path is a symlink: {quarantine_path}",
                    )
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED
                    if e.errno == errno.EACCES
                    else FileOperationStatus.ERROR,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=0,
                    file_hash="",
                    error_message=f"Cannot open quarantine file: {e}",
                )

            masked_permissions = original_permissions & 0o777
            destination_obj = Path(original_path)
            file_size = 0
            file_hash: str | None = None

            try:
                try:
                    st = os.fstat(src_fd)
                except OSError as e:
                    return FileOperationResult(
                        status=FileOperationStatus.ERROR,
                        source_path=quarantine_path,
                        destination_path=original_path,
                        file_size=0,
                        file_hash="",
                        error_message=f"Cannot stat quarantine file: {e}",
                    )

                if not stat.S_ISREG(st.st_mode):
                    return FileOperationResult(
                        status=FileOperationStatus.ERROR,
                        source_path=quarantine_path,
                        destination_path=original_path,
                        file_size=0,
                        file_hash="",
                        error_message=f"Quarantined path is not a regular file: {quarantine_path}",
                    )

                file_size = st.st_size

                # Create destination directory if needed
                try:
                    destination_obj.parent.mkdir(parents=True, exist_ok=True)
                except PermissionError as e:
                    return FileOperationResult(
                        status=FileOperationStatus.PERMISSION_DENIED,
                        source_path=quarantine_path,
                        destination_path=original_path,
                        file_size=file_size,
                        file_hash="",
                        error_message=f"Permission denied creating destination directory: {e}",
                    )
                except OSError as e:
                    return FileOperationResult(
                        status=FileOperationStatus.ERROR,
                        source_path=quarantine_path,
                        destination_path=original_path,
                        file_size=file_size,
                        file_hash="",
                        error_message=f"Error creating destination directory: {e}",
                    )

                # Open destination with O_CREAT|O_EXCL|O_NOFOLLOW — atomically creates and
                # rejects pre-existing paths (files and symlinks), eliminating both the
                # exists()-then-write and is_symlink()-then-write TOCTOU windows.
                dst_fd: int | None = None
                dst_created = False
                try:
                    dst_fd = os.open(
                        destination_obj,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        masked_permissions,
                    )
                    dst_created = True
                    sha256_hash = hashlib.sha256()
                    while True:
                        block = os.read(src_fd, self.HASH_BUFFER_SIZE)
                        if not block:
                            break
                        sha256_hash.update(block)
                        os.write(dst_fd, block)
                    os.fsync(dst_fd)
                    # fchmod via fd — no path-based window, bypasses umask.
                    os.fchmod(dst_fd, masked_permissions)
                    os.close(dst_fd)
                    dst_fd = None
                    file_hash = sha256_hash.hexdigest()
                except OSError as e:
                    if dst_fd is not None:
                        with contextlib.suppress(OSError):
                            os.close(dst_fd)
                    if dst_created:
                        with contextlib.suppress(OSError):
                            _unlinkat(destination_obj)
                    if e.errno == errno.EEXIST:
                        return FileOperationResult(
                            status=FileOperationStatus.ALREADY_EXISTS,
                            source_path=quarantine_path,
                            destination_path=original_path,
                            file_size=file_size,
                            file_hash="",
                            error_message=f"Destination file already exists: {original_path}",
                        )
                    if e.errno == errno.ELOOP:
                        return FileOperationResult(
                            status=FileOperationStatus.ERROR,
                            source_path=quarantine_path,
                            destination_path=original_path,
                            file_size=file_size,
                            file_hash="",
                            error_message=f"Security: destination is a symlink, possible attack: {original_path}",
                        )
                    return FileOperationResult(
                        status=FileOperationStatus.PERMISSION_DENIED
                        if e.errno == errno.EACCES
                        else FileOperationStatus.ERROR,
                        source_path=quarantine_path,
                        destination_path=original_path,
                        file_size=file_size,
                        file_hash="",
                        error_message=f"File operation error: {e}",
                    )

                # Unlink quarantine file while src_fd is still open (same inode-pinning
                # rationale as in move_to_quarantine; same _unlinkat parent-fd anchoring).
                try:
                    _unlinkat(quarantine_path_obj)
                except OSError as e:
                    logger.warning("Could not remove quarantine file after restore: %s", e)

                return FileOperationResult(
                    status=FileOperationStatus.SUCCESS,
                    source_path=quarantine_path,
                    destination_path=original_path,
                    file_size=file_size,
                    file_hash=file_hash or "",
                    error_message=None,
                    original_permissions=masked_permissions,
                )

            finally:
                with contextlib.suppress(OSError):
                    os.close(src_fd)

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
            for entry in self._quarantine_dir.iterdir():
                # lstat() in one call — avoids the is_file()+stat() TOCTOU window and
                # never follows symlinks, so stale/malicious symlinks are skipped cleanly.
                try:
                    st = os.lstat(entry)
                except OSError as e:
                    logger.debug("Failed to lstat quarantine entry: %s", e)
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                files.append(
                    {
                        "filename": entry.name,
                        "size": st.st_size,
                        "path": str(entry),
                        "modified": st.st_mtime,
                    }
                )
        except PermissionError as e:
            logger.warning("Permission denied accessing quarantine directory: %s", e)
        except OSError as e:
            logger.debug("Failed to list quarantine directory: %s", e)

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

            # Open with O_NOFOLLOW — confirms the target is a real file (not a symlink) and
            # captures size via fstat, eliminating the exists()+stat() TOCTOU window.
            try:
                fd = os.open(quarantine_path_obj, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    return FileOperationResult(
                        status=FileOperationStatus.FILE_NOT_FOUND,
                        source_path=quarantine_path,
                        destination_path=None,
                        file_size=0,
                        file_hash="",
                        error_message=f"Quarantined file not found: {quarantine_path}",
                    )
                if e.errno == errno.ELOOP:
                    return FileOperationResult(
                        status=FileOperationStatus.ERROR,
                        source_path=quarantine_path,
                        destination_path=None,
                        file_size=0,
                        file_hash="",
                        error_message=f"Security: quarantine path is a symlink: {quarantine_path}",
                    )
                return FileOperationResult(
                    status=FileOperationStatus.PERMISSION_DENIED
                    if e.errno == errno.EACCES
                    else FileOperationStatus.ERROR,
                    source_path=quarantine_path,
                    destination_path=None,
                    file_size=0,
                    file_hash="",
                    error_message=f"Cannot open quarantine file: {e}",
                )

            # Keep fd open through the unlink so the inode is pinned during the
            # operation — same rationale as move_to_quarantine.
            file_size = 0
            try:
                try:
                    st = os.fstat(fd)
                    file_size = st.st_size
                    # fchmod via fd — no path-based window between stat and chmod.
                    with contextlib.suppress(OSError):
                        os.fchmod(fd, 0o000)
                except OSError:
                    file_size = 0

                _unlinkat(quarantine_path_obj)

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
            finally:
                with contextlib.suppress(OSError):
                    os.close(fd)
