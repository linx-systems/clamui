# ClamUI Profile Storage Module
"""
Profile storage module for ClamUI providing JSON-based profile persistence.
Stores scan profiles in JSON format with thread-safe access and atomic writes.
"""

import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from ..core.sanitize import sanitize_log_line
from .models import ScanProfile

logger = logging.getLogger(__name__)


class ProfileStorage:
    """
    Storage handler for scan profile persistence.

    Provides methods for saving and loading scan profiles
    stored in JSON format. Supports atomic file writes and
    handles corruption gracefully with backup preservation.
    """

    # JSON schema version for future compatibility
    SCHEMA_VERSION = 1

    def __init__(self, storage_path: Path):
        """
        Initialize the ProfileStorage.

        Args:
            storage_path: Path to the JSON file for storing profiles.
                         The parent directory will be created if it doesn't exist.
        """
        self._storage_path = Path(storage_path)

        # Thread lock for safe concurrent access
        self._lock = threading.Lock()

    @property
    def storage_path(self) -> Path:
        """Get the storage file path."""
        return self._storage_path

    def load_profiles(self) -> list[ScanProfile]:
        """
        Load all profiles from storage.

        Returns:
            List of ScanProfile instances. Returns empty list if
            file doesn't exist or is corrupted.
        """
        with self._lock:
            try:
                if self._storage_path.exists():
                    with open(self._storage_path, encoding="utf-8") as f:
                        data = json.load(f)
                        # Handle both versioned and legacy formats
                        if isinstance(data, dict) and "profiles" in data:
                            profiles_data = data.get("profiles", [])
                        elif isinstance(data, list):
                            profiles_data = data
                        else:
                            profiles_data = []

                        profiles: list[ScanProfile] = []
                        for entry in profiles_data:
                            try:
                                profiles.append(ScanProfile.from_dict(entry))
                            except (KeyError, TypeError):
                                # Skip a single malformed record but keep the rest;
                                # only a top-level container failure is treated as corrupt.
                                logger.warning(
                                    "Skipping malformed profile record: %s",
                                    sanitize_log_line(repr(entry)),
                                )
                        return profiles
            except (json.JSONDecodeError, OSError, PermissionError):
                # Handle corrupted files or permission issues
                # Backup corrupted file for debugging
                self._backup_corrupted_file()
            return []

    def save_profiles(self, profiles: list[ScanProfile]) -> bool:
        """
        Save all profiles to storage using atomic write.

        Uses a temporary file and rename pattern to prevent
        corruption during write operations.

        Args:
            profiles: List of ScanProfile instances to save

        Returns:
            True if saved successfully, False otherwise
        """
        with self._lock:
            try:
                # Ensure parent directory exists
                self._storage_path.parent.mkdir(parents=True, exist_ok=True)

                # Prepare data with schema version
                data = {
                    "version": self.SCHEMA_VERSION,
                    "profiles": [p.to_dict() for p in profiles],
                }

                # Atomic write using temp file + rename
                fd, temp_path = tempfile.mkstemp(
                    suffix=".json",
                    prefix="profiles_",
                    dir=self._storage_path.parent,
                )
                try:
                    try:
                        f = os.fdopen(fd, "w", encoding="utf-8")
                    except Exception:
                        with contextlib.suppress(OSError):
                            os.close(fd)
                        raise

                    with f:
                        json.dump(data, f, indent=2)

                    # Atomic rename
                    temp_path_obj = Path(temp_path)
                    temp_path_obj.replace(self._storage_path)
                    # Restrict permissions to owner-only (profiles contain user paths)
                    os.chmod(self._storage_path, 0o600)
                    return True
                except Exception:
                    # Clean up temp file on failure
                    with contextlib.suppress(OSError):
                        Path(temp_path).unlink(missing_ok=True)
                    raise

            except Exception:
                # Catch all exceptions (including OSError, PermissionError)
                logger.warning(
                    "Failed to save scan profiles to %s",
                    self._storage_path,
                    exc_info=True,
                )
                return False

    def _backup_corrupted_file(self) -> None:
        """
        Create a backup of a corrupted storage file.

        Renames the corrupted file with a .corrupted suffix
        to preserve it for debugging purposes.
        """
        try:
            if self._storage_path.exists():
                backup_path = self._storage_path.with_suffix(
                    f"{self._storage_path.suffix}.corrupted"
                )
                # Don't overwrite existing backups
                if not backup_path.exists():
                    self._storage_path.rename(backup_path)
        except (OSError, PermissionError):
            # Silently fail - backup is best effort
            logger.debug("Failed to backup corrupted profile storage file", exc_info=True)

    def get_profile_by_id(self, profile_id: str) -> ScanProfile | None:
        """
        Load a specific profile by ID.

        Args:
            profile_id: The unique identifier of the profile

        Returns:
            The ScanProfile if found, None otherwise
        """
        profiles = self.load_profiles()
        for profile in profiles:
            if profile.id == profile_id:
                return profile
        return None

    def delete_storage(self) -> bool:
        """
        Delete the storage file.

        Useful for testing or resetting to clean state.

        Returns:
            True if deleted successfully or file didn't exist,
            False on permission/OS errors
        """
        with self._lock:
            try:
                if self._storage_path.exists():
                    self._storage_path.unlink()
                return True
            except (OSError, PermissionError):
                return False

    def exists(self) -> bool:
        """
        Check if the storage file exists.

        Returns:
            True if the storage file exists, False otherwise
        """
        return self._storage_path.exists()
