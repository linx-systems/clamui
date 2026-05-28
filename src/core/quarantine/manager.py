# ClamUI Quarantine Manager Module
"""
Quarantine manager module for ClamUI providing high-level quarantine operations.

Orchestrates the QuarantineDatabase and SecureFileHandler to provide:
- Moving detected threats to quarantine
- Restoring quarantined files to original locations
- Permanently deleting quarantined files
- Listing and managing quarantine entries
- Async operations for UI integration
- Periodic cleanup of orphaned database entries
"""

import logging
import os
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from gi.repository import GLib

from ..i18n import _
from .database import QuarantineDatabase, QuarantineEntry
from .file_handler import (
    FileOperationStatus,
    SecureFileHandler,
)

logger = logging.getLogger(__name__)


class QuarantineStatus(Enum):
    """Status of a quarantine operation."""

    SUCCESS = "success"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    DISK_FULL = "disk_full"
    DATABASE_ERROR = "database_error"
    ALREADY_QUARANTINED = "already_quarantined"
    ENTRY_NOT_FOUND = "entry_not_found"
    RESTORE_DESTINATION_EXISTS = "restore_destination_exists"
    INVALID_RESTORE_PATH = "invalid_restore_path"
    ERROR = "error"


@dataclass
class QuarantineResult:
    """Result of a quarantine operation."""

    status: QuarantineStatus
    entry: QuarantineEntry | None
    error_message: str | None

    @property
    def is_success(self) -> bool:
        """Check if the operation was successful."""
        return self.status == QuarantineStatus.SUCCESS


class QuarantineManager:
    """
    Manager for quarantine operations orchestrating database and file handling.

    Provides methods for moving files to quarantine, restoring them to
    original locations, permanently deleting them, and managing the
    quarantine list. Supports both synchronous and asynchronous operations
    for UI integration.

    Periodic Cleanup:
        The manager automatically cleans up orphaned database entries (entries
        whose files no longer exist on disk). Cleanup runs lazily during other
        operations (list_files, quarantine_file, etc.) after CLEANUP_INTERVAL_HOURS
        has passed since the last cleanup. This avoids blocking application startup
        and spreads cleanup overhead across normal usage.

    Example:
        >>> manager = QuarantineManager()
        >>> result = manager.quarantine_file("/home/user/malware.exe", "Win.Trojan.Generic")
        >>> if result.is_success:
        ...     print(f"File quarantined: {result.entry.quarantine_path}")
    """

    # Minimum interval between orphan cleanup runs (24 hours)
    CLEANUP_INTERVAL_HOURS = 24

    def __init__(
        self,
        quarantine_directory: str | None = None,
        database_path: str | None = None,
        enable_periodic_cleanup: bool = True,
    ):
        """
        Initialize the QuarantineManager.

        Args:
            quarantine_directory: Optional custom quarantine directory path.
                                  Defaults to XDG_DATA_HOME/clamui/quarantine
            database_path: Optional custom database path.
                           Defaults to XDG_DATA_HOME/clamui/quarantine.db
            enable_periodic_cleanup: Whether to enable periodic orphan cleanup.
                                     Defaults to True. Set to False for testing.
        """
        self._file_handler = SecureFileHandler(quarantine_directory)
        self._database = QuarantineDatabase(database_path)

        # Thread lock for safe concurrent access
        self._lock = threading.Lock()

        # Periodic cleanup state
        self._enable_periodic_cleanup = enable_periodic_cleanup
        self._last_cleanup_check_time: float = 0.0
        self._cleanup_timestamp_file = self._database._db_path.parent / ".last_orphan_cleanup"

    @property
    def quarantine_directory(self) -> Path:
        """Get the quarantine directory path."""
        return self._file_handler.quarantine_directory

    def close(self) -> None:
        """Close database connections and cleanup resources."""
        if self._database is not None:
            self._database.close()

    def quarantine_file(
        self,
        file_path: str,
        threat_name: str,
    ) -> QuarantineResult:
        """
        Move a file to quarantine and record metadata.

        Performs the following operations:
        1. Checks if file is already quarantined
        2. Moves file to quarantine directory securely
        3. Records metadata in database

        Args:
            file_path: Path to the file to quarantine
            threat_name: Name of the detected threat

        Returns:
            QuarantineResult with operation status and entry details

        Example:
            >>> manager = QuarantineManager()
            >>> result = manager.quarantine_file("/path/to/infected.exe", "Win.Trojan.Agent")
            >>> if result.is_success:
            ...     print(f"Quarantined at: {result.entry.quarantine_path}")
        """
        with self._lock:
            # Use abspath, not resolve(): resolve() follows symlinks, which would let an
            # attacker swap the scanned file for a symlink between scan and quarantine,
            # bypassing the O_NOFOLLOW guard in move_to_quarantine(). abspath() normalises
            # . and .. components without dereferencing any symlink in the path.
            source_str = os.path.abspath(file_path)

            # Move file to quarantine (duplicate paths allowed - each gets unique ID)
            file_result = self._file_handler.move_to_quarantine(source_str, threat_name)

            if not file_result.is_success:
                # Map file operation status to quarantine status
                status = self._map_file_status(file_result.status)
                return QuarantineResult(
                    status=status,
                    entry=None,
                    error_message=file_result.error_message,
                )

            # Add entry to database
            entry_id = self._database.add_entry(
                original_path=source_str,
                quarantine_path=file_result.destination_path or "",
                threat_name=threat_name,
                file_size=file_result.file_size,
                file_hash=file_result.file_hash,
                original_permissions=file_result.original_permissions,
            )

            if entry_id is None:
                # Database error - attempt to rollback by restoring the file
                logger.error(
                    "Database add_entry failed for %s. Attempting rollback...",
                    source_str,
                )
                rollback_success, rollback_error = self._rollback_quarantine(
                    file_result.destination_path or "",
                    source_str,
                    file_result.original_permissions,
                )
                if rollback_success:
                    error_msg = _(
                        "Failed to record quarantine entry in database. File has been restored to original location."
                    )
                else:
                    error_msg = _(
                        "Failed to record quarantine entry in database. Rollback also failed: {error}. File may be orphaned at: {path}"
                    ).format(error=rollback_error, path=file_result.destination_path)
                return QuarantineResult(
                    status=QuarantineStatus.DATABASE_ERROR,
                    entry=None,
                    error_message=error_msg,
                )

            # Retrieve the created entry
            entry = self._database.get_entry(entry_id)

            return QuarantineResult(
                status=QuarantineStatus.SUCCESS,
                entry=entry,
                error_message=None,
            )

    def quarantine_file_async(
        self,
        file_path: str,
        threat_name: str,
        callback: Callable[[QuarantineResult], None],
    ) -> None:
        """
        Move a file to quarantine asynchronously.

        The operation runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        Args:
            file_path: Path to the file to quarantine
            threat_name: Name of the detected threat
            callback: Function to call with QuarantineResult when complete
        """

        def _quarantine_thread():
            result = self.quarantine_file(file_path, threat_name)
            GLib.idle_add(callback, result)

        thread = threading.Thread(target=_quarantine_thread)
        thread.daemon = True
        thread.start()

    def restore_file(self, entry_id: int) -> QuarantineResult:
        """
        Restore a quarantined file to its original location.

        Performs the following operations:
        1. Retrieves entry from database
        2. Verifies file integrity via hash
        3. Moves file back to original location
        4. Removes entry from database

        Args:
            entry_id: The ID of the quarantine entry to restore

        Returns:
            QuarantineResult with operation status

        Example:
            >>> manager = QuarantineManager()
            >>> result = manager.restore_file(1)
            >>> if result.is_success:
            ...     print("File restored successfully")
        """
        with self._lock:
            # Get entry from database
            entry = self._database.get_entry(entry_id)
            if entry is None:
                return QuarantineResult(
                    status=QuarantineStatus.ENTRY_NOT_FOUND,
                    entry=None,
                    error_message=_("Quarantine entry not found: {id}").format(id=entry_id),
                )

            # Verify file integrity before restore
            is_valid, verify_error = self._file_handler.verify_file_integrity(
                entry.quarantine_path, entry.file_hash
            )

            if not is_valid:
                return QuarantineResult(
                    status=QuarantineStatus.ERROR,
                    entry=entry,
                    error_message=_("File integrity verification failed: {error}").format(
                        error=verify_error
                    ),
                )

            # Restore file to original location with original permissions
            file_result = self._file_handler.restore_from_quarantine(
                entry.quarantine_path,
                entry.original_path,
                entry.original_permissions,
            )

            if not file_result.is_success:
                status = self._map_file_status(file_result.status)
                # Special handling for destination exists
                if file_result.status == FileOperationStatus.ALREADY_EXISTS:
                    status = QuarantineStatus.RESTORE_DESTINATION_EXISTS
                return QuarantineResult(
                    status=status,
                    entry=entry,
                    error_message=file_result.error_message,
                )

            # Remove entry from database
            if not self._database.remove_entry(entry_id):
                # File restored but database entry remains - this creates an orphaned entry
                # Log warning so it can be identified and cleaned up later
                logger.warning(
                    "Failed to remove database entry %d after successful file restore. "
                    "Entry is now orphaned (file at %s no longer exists). "
                    "Run cleanup_orphaned_entries() to resolve.",
                    entry_id,
                    entry.quarantine_path,
                )

            return QuarantineResult(
                status=QuarantineStatus.SUCCESS,
                entry=entry,
                error_message=None,
            )

    def restore_file_async(
        self,
        entry_id: int,
        callback: Callable[[QuarantineResult], None],
    ) -> None:
        """
        Restore a quarantined file asynchronously.

        The operation runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        Args:
            entry_id: The ID of the quarantine entry to restore
            callback: Function to call with QuarantineResult when complete
        """

        def _restore_thread():
            result = self.restore_file(entry_id)
            GLib.idle_add(callback, result)

        thread = threading.Thread(target=_restore_thread)
        thread.daemon = True
        thread.start()

    def delete_file(self, entry_id: int) -> QuarantineResult:
        """
        Permanently delete a quarantined file.

        Performs the following operations:
        1. Retrieves entry from database
        2. Deletes the file from quarantine
        3. Removes entry from database

        Args:
            entry_id: The ID of the quarantine entry to delete

        Returns:
            QuarantineResult with operation status

        Example:
            >>> manager = QuarantineManager()
            >>> result = manager.delete_file(1)
            >>> if result.is_success:
            ...     print("File permanently deleted")
        """
        with self._lock:
            # Get entry from database
            entry = self._database.get_entry(entry_id)
            if entry is None:
                return QuarantineResult(
                    status=QuarantineStatus.ENTRY_NOT_FOUND,
                    entry=None,
                    error_message=_("Quarantine entry not found: {id}").format(id=entry_id),
                )

            # Delete the file
            file_result = self._file_handler.delete_from_quarantine(entry.quarantine_path)

            if not file_result.is_success:
                status = self._map_file_status(file_result.status)
                return QuarantineResult(
                    status=status,
                    entry=entry,
                    error_message=file_result.error_message,
                )

            # Remove entry from database
            if not self._database.remove_entry(entry_id):
                # File deleted but database entry remains - this creates an orphaned entry
                # Log warning so it can be identified and cleaned up later
                logger.warning(
                    "Failed to remove database entry %d after successful file deletion. "
                    "Entry is now orphaned (file at %s no longer exists). "
                    "Run cleanup_orphaned_entries() to resolve.",
                    entry_id,
                    entry.quarantine_path,
                )

            return QuarantineResult(
                status=QuarantineStatus.SUCCESS,
                entry=entry,
                error_message=None,
            )

    def delete_file_async(
        self,
        entry_id: int,
        callback: Callable[[QuarantineResult], None],
    ) -> None:
        """
        Permanently delete a quarantined file asynchronously.

        The operation runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        Args:
            entry_id: The ID of the quarantine entry to delete
            callback: Function to call with QuarantineResult when complete
        """

        def _delete_thread():
            result = self.delete_file(entry_id)
            GLib.idle_add(callback, result)

        thread = threading.Thread(target=_delete_thread)
        thread.daemon = True
        thread.start()

    def get_entry(self, entry_id: int) -> QuarantineEntry | None:
        """
        Retrieve a specific quarantine entry by ID.

        Args:
            entry_id: The ID of the quarantine entry

        Returns:
            QuarantineEntry if found, None otherwise
        """
        return self._database.get_entry(entry_id)

    def get_entry_by_original_path(self, original_path: str) -> QuarantineEntry | None:
        """
        Retrieve a quarantine entry by original file path.

        Args:
            original_path: The original path of the quarantined file

        Returns:
            QuarantineEntry if found, None otherwise
        """
        return self._database.get_entry_by_original_path(original_path)

    def get_all_entries(self) -> list[QuarantineEntry]:
        """
        Retrieve all quarantine entries, sorted by detection date (newest first).

        Note: This method may trigger periodic orphan cleanup if enough time
        has passed since the last cleanup (default: 24 hours).

        Returns:
            List of QuarantineEntry objects
        """
        # Trigger periodic cleanup if needed (runs synchronously but is fast)
        self.maybe_run_periodic_cleanup()

        return self._database.get_all_entries()

    def get_all_entries_async(
        self,
        callback: Callable[[list[QuarantineEntry]], None],
    ) -> None:
        """
        Retrieve all quarantine entries asynchronously.

        The operation runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        Note: This method may trigger periodic orphan cleanup if enough time
        has passed since the last cleanup (default: 24 hours).

        Args:
            callback: Function to call with list of QuarantineEntry objects when complete
        """

        def _get_entries_thread():
            try:
                # Periodic cleanup runs within get_all_entries
                entries = self.get_all_entries()
            except Exception as e:
                logger.debug("Failed to get quarantine entries async: %s", e)
                entries = []
            GLib.idle_add(callback, entries)

        thread = threading.Thread(target=_get_entries_thread)
        thread.daemon = True
        thread.start()

    def get_total_size(self) -> int:
        """
        Calculate the total size of all quarantined files.

        Returns:
            Total size in bytes
        """
        return self._database.get_total_size()

    def get_entry_count(self) -> int:
        """
        Get the total number of quarantine entries.

        Returns:
            Number of entries
        """
        return self._database.get_entry_count()

    def get_old_entries(self, days: int = 30) -> list[QuarantineEntry]:
        """
        Get entries older than the specified number of days.

        Args:
            days: Number of days to look back (default: 30)

        Returns:
            List of QuarantineEntry objects older than the specified days
        """
        return self._database.get_old_entries(days)

    def verify_entry(self, entry_id: int) -> tuple[bool, str | None]:
        """
        Verify if a quarantine entry's file exists on disk.

        Checks whether the quarantine file referenced by the database entry
        actually exists in the quarantine directory.

        Args:
            entry_id: The ID of the quarantine entry to verify

        Returns:
            Tuple of (exists, error_message):
            - (True, None) if the file exists
            - (False, error_message) if the entry doesn't exist or file is missing
        """
        entry = self._database.get_entry(entry_id)
        if entry is None:
            return (False, _("Quarantine entry not found: {id}").format(id=entry_id))

        # lstat() does not follow symlinks — a symlink in the quarantine dir
        # would not be treated as a present regular file.
        try:
            st = os.lstat(entry.quarantine_path)
        except OSError:
            return (False, f"Quarantine file missing: {entry.quarantine_path}")

        if not stat.S_ISREG(st.st_mode):
            return (False, f"Quarantine path is not a regular file: {entry.quarantine_path}")

        return (True, None)

    def cleanup_orphaned_entries(self) -> int:
        """
        Remove database entries whose quarantine files no longer exist.

        Scans all quarantine entries and removes any whose corresponding file
        has been deleted or is missing from disk. This can happen when:
        - A file was restored/deleted but remove_entry() failed
        - Files were manually deleted from the quarantine directory
        - Filesystem corruption or external cleanup occurred

        Returns:
            Number of orphaned entries removed
        """
        with self._lock:
            entries = self._database.get_all_entries()
            removed_count = 0

            for entry in entries:
                # lstat() does not follow symlinks — avoids a stale symlink in the
                # quarantine dir masking a missing file.
                try:
                    st = os.lstat(entry.quarantine_path)
                    file_present = stat.S_ISREG(st.st_mode)
                except OSError:
                    file_present = False
                if not file_present:
                    logger.warning(
                        "Removing orphaned quarantine entry %d: file missing at %s",
                        entry.id,
                        entry.quarantine_path,
                    )
                    if self._database.remove_entry(entry.id):
                        removed_count += 1
                    else:
                        logger.error(
                            "Failed to remove orphaned entry %d from database",
                            entry.id,
                        )

            if removed_count > 0:
                logger.info("Cleaned up %d orphaned quarantine entries", removed_count)

            return removed_count

    def cleanup_orphaned_entries_async(
        self,
        callback: Callable[[int], None],
    ) -> None:
        """
        Remove orphaned database entries asynchronously.

        The operation runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        Args:
            callback: Function to call with removed count when complete
        """

        def _cleanup_thread():
            removed_count = self.cleanup_orphaned_entries()
            GLib.idle_add(callback, removed_count)

        thread = threading.Thread(target=_cleanup_thread)
        thread.daemon = True
        thread.start()

    def _get_last_cleanup_timestamp(self) -> float:
        """
        Get the timestamp of the last orphan cleanup.

        Returns:
            Unix timestamp of last cleanup, or 0.0 if never run
        """
        try:
            if self._cleanup_timestamp_file.exists():
                return float(self._cleanup_timestamp_file.read_text().strip())
        except (OSError, ValueError) as e:
            logger.debug("Could not read cleanup timestamp: %s", e)
        return 0.0

    def _set_last_cleanup_timestamp(self) -> None:
        """Record the current time as the last cleanup timestamp."""
        try:
            self._cleanup_timestamp_file.parent.mkdir(parents=True, exist_ok=True)
            self._cleanup_timestamp_file.write_text(str(time.time()))
        except OSError as e:
            logger.debug("Could not write cleanup timestamp: %s", e)

    def _should_run_periodic_cleanup(self) -> bool:
        """
        Check if periodic cleanup should run based on time elapsed.

        Returns:
            True if cleanup should run, False otherwise
        """
        if not self._enable_periodic_cleanup:
            return False

        # Throttle check frequency to once per minute to avoid disk I/O
        current_time = time.time()
        if current_time - self._last_cleanup_check_time < 60:
            return False
        self._last_cleanup_check_time = current_time

        last_cleanup = self._get_last_cleanup_timestamp()
        hours_since_cleanup = (current_time - last_cleanup) / 3600

        return hours_since_cleanup >= self.CLEANUP_INTERVAL_HOURS

    def maybe_run_periodic_cleanup(self) -> int:
        """
        Run periodic cleanup if enough time has passed since the last run.

        This method is designed to be called during normal operations (e.g.,
        when listing entries) to lazily trigger cleanup without blocking
        application startup.

        Returns:
            Number of orphaned entries removed, or 0 if cleanup was skipped
        """
        if not self._should_run_periodic_cleanup():
            return 0

        logger.debug("Running periodic orphan cleanup...")
        removed = self.cleanup_orphaned_entries()
        self._set_last_cleanup_timestamp()

        if removed > 0:
            logger.info("Periodic cleanup removed %d orphaned quarantine entries", removed)

        return removed

    def maybe_run_periodic_cleanup_async(
        self,
        callback: Callable[[int], None] | None = None,
    ) -> None:
        """
        Run periodic cleanup asynchronously if enough time has passed.

        This is the preferred method for UI contexts. It checks if cleanup
        is needed and runs it in a background thread if so.

        Args:
            callback: Optional function to call with removed count when complete.
                      Only called if cleanup actually ran.
        """
        if not self._should_run_periodic_cleanup():
            return

        def _cleanup_thread():
            removed = self.cleanup_orphaned_entries()
            self._set_last_cleanup_timestamp()

            if removed > 0:
                logger.info("Periodic cleanup removed %d orphaned quarantine entries", removed)

            if callback is not None:
                GLib.idle_add(callback, removed)

        thread = threading.Thread(target=_cleanup_thread)
        thread.daemon = True
        thread.start()

    def cleanup_old_entries(self, days: int = 30) -> int:
        """
        Delete old quarantine entries and their files.

        Args:
            days: Delete entries older than this many days (default: 30)

        Returns:
            Number of entries removed
        """
        with self._lock:
            # Get old entries
            old_entries = self.get_old_entries(days)

            # Delete each file
            for entry in old_entries:
                try:
                    self._file_handler.delete_from_quarantine(entry.quarantine_path)
                except Exception as e:
                    # Continue even if file deletion fails
                    logger.warning(
                        "Failed to delete quarantined file %s: %s", entry.quarantine_path, e
                    )

            # Remove from database
            return self._database.cleanup_old_entries(days)

    def cleanup_old_entries_async(
        self,
        callback: Callable[[int], None],
        days: int = 30,
    ) -> None:
        """
        Delete old quarantine entries asynchronously.

        Args:
            callback: Function to call with removed count when complete
            days: Delete entries older than this many days (default: 30)
        """

        def _cleanup_thread():
            removed_count = self.cleanup_old_entries(days)
            GLib.idle_add(callback, removed_count)

        thread = threading.Thread(target=_cleanup_thread)
        thread.daemon = True
        thread.start()

    def _rollback_quarantine(
        self,
        quarantine_path: str,
        original_path: str,
        original_permissions: int,
    ) -> tuple[bool, str | None]:
        """
        Attempt to restore a file from quarantine to its original location.

        Used for rollback when database entry creation fails after a file
        has already been moved to quarantine.

        Args:
            quarantine_path: Path to the quarantined file
            original_path: Original path where the file should be restored
            original_permissions: Original file permissions to restore

        Returns:
            Tuple of (success, error_message):
            - (True, None) if rollback succeeded
            - (False, error_message) if rollback failed
        """
        try:
            restore_result = self._file_handler.restore_from_quarantine(
                quarantine_path,
                original_path,
                original_permissions,
            )
            if restore_result.is_success:
                logger.info(
                    "Successfully rolled back quarantine: restored %s to %s",
                    quarantine_path,
                    original_path,
                )
                return (True, None)
            else:
                error_msg = (
                    f"Rollback failed: could not restore {quarantine_path} to "
                    f"{original_path}: {restore_result.error_message}"
                )
                logger.critical(
                    "ORPHANED QUARANTINE FILE: %s - Database entry failed and rollback "
                    "also failed. File is orphaned and cannot be accessed through UI. "
                    "Error: %s",
                    quarantine_path,
                    restore_result.error_message,
                )
                return (False, error_msg)
        except Exception as e:
            error_msg = f"Rollback exception: {e}"
            logger.critical(
                "ORPHANED QUARANTINE FILE: %s - Database entry failed and rollback "
                "raised exception. File is orphaned and cannot be accessed through UI. "
                "Exception: %s",
                quarantine_path,
                e,
            )
            return (False, error_msg)

    def _map_file_status(self, file_status: FileOperationStatus) -> QuarantineStatus:
        """Map FileOperationStatus to QuarantineStatus."""
        status_map = {
            FileOperationStatus.SUCCESS: QuarantineStatus.SUCCESS,
            FileOperationStatus.FILE_NOT_FOUND: QuarantineStatus.FILE_NOT_FOUND,
            FileOperationStatus.PERMISSION_DENIED: QuarantineStatus.PERMISSION_DENIED,
            FileOperationStatus.DISK_FULL: QuarantineStatus.DISK_FULL,
            FileOperationStatus.INVALID_RESTORE_PATH: QuarantineStatus.INVALID_RESTORE_PATH,
            FileOperationStatus.ERROR: QuarantineStatus.ERROR,
        }
        return status_map.get(file_status, QuarantineStatus.ERROR)
