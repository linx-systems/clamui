# ClamUI Profile Manager Module
"""
Profile manager module for ClamUI providing scan profile lifecycle management.
Centralizes all profile operations including CRUD, validation, and import/export.
"""

import contextlib
import functools
import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ScanProfile
from .profile_storage import ProfileStorage

logger = logging.getLogger(__name__)

# Validation constants
MAX_PROFILE_NAME_LENGTH = 50
MIN_PROFILE_NAME_LENGTH = 1

# Migration version for XDG path updates
_XDG_MIGRATION_VERSION = 1


class ProfileManager:
    """
    Manager for scan profile lifecycle and operations.

    Provides methods for creating, reading, updating, and deleting
    scan profiles. Uses ProfileStorage for persistence.
    """

    # Default profile definitions
    # These are created on first run if not present in storage
    DEFAULT_PROFILES = [
        {
            "name": "Quick Scan",
            "description": "Fast scan of the Downloads folder for quick threat detection",
            "targets": ["~/Downloads"],
            "exclusions": {},
            "options": {},
        },
        {
            "name": "Full Scan",
            "description": "Comprehensive system-wide scan of all accessible directories",
            "targets": ["/"],
            "exclusions": {
                "paths": [
                    "/proc",
                    "/sys",
                    "/dev",
                    "/run",
                    "/tmp",
                    "/var/cache",
                    "/var/tmp",
                ]
            },
            "options": {},
        },
        {
            "name": "Home Folder",
            "description": "Scan of the user's home directory and personal files",
            "targets": ["~"],
            "exclusions": {
                "paths": [
                    "~/.cache",
                    "~/.local/share/Trash",
                ]
            },
            "options": {},
        },
    ]

    def __init__(self, config_dir: Path):
        """
        Initialize the ProfileManager.

        Args:
            config_dir: Directory for storing profile data.
                       Will be created if it doesn't exist.
        """
        self._config_dir = Path(config_dir)
        self._storage = ProfileStorage(self._config_dir / "profiles.json")

        # Thread lock for safe concurrent access
        self._lock = threading.Lock()

        # In-memory cache of profiles
        self._profiles: dict[str, ScanProfile] = {}

        # Load profiles on initialization
        self._load()

        # Ensure default profiles exist
        self._ensure_default_profiles()

        # Run migrations for existing profiles
        self._migrate_default_profiles_to_xdg()

    def _load(self) -> None:
        """Load profiles from storage into memory."""
        with self._lock:
            profiles = self._storage.load_profiles()
            self._profiles = {p.id: p for p in profiles}

    def _ensure_default_profiles(self) -> None:
        """
        Ensure all default profiles exist with XDG-resolved paths.

        Creates any missing default profiles from DEFAULT_PROFILES.
        For Quick Scan, uses xdg-user-dir to get the localized Downloads path.
        If xdg-user-dir returns None, falls back to the default path from
        DEFAULT_PROFILES. This is called during initialization to ensure
        built-in profiles are always available.
        """
        from ..core.flatpak import get_xdg_user_dir

        # Get names of existing default profiles
        existing_default_names: set[str] = set()
        with self._lock:
            for profile in self._profiles.values():
                if profile.is_default:
                    existing_default_names.add(profile.name)

        # Create any missing default profiles
        profiles_created = False
        for default_def in self.DEFAULT_PROFILES:
            if default_def["name"] not in existing_default_names:
                targets = list(default_def["targets"])

                # Resolve XDG paths for Quick Scan
                if default_def["name"] == "Quick Scan":
                    xdg_download = get_xdg_user_dir("DOWNLOAD")
                    if xdg_download:
                        targets = [xdg_download]

                timestamp = self._get_timestamp()
                profile = ScanProfile(
                    id=self._generate_id(),
                    name=default_def["name"],
                    targets=targets,
                    exclusions=dict(default_def["exclusions"]),
                    created_at=timestamp,
                    updated_at=timestamp,
                    is_default=True,
                    description=default_def["description"],
                    options=dict(default_def["options"]),
                )
                with self._lock:
                    self._profiles[profile.id] = profile
                profiles_created = True

        # Save if any profiles were created
        if profiles_created:
            self._save()

    def _save(self) -> bool:
        """
        Save all profiles to storage.

        Returns:
            True if saved successfully, False otherwise
        """
        with self._lock:
            profiles = list(self._profiles.values())
        return self._storage.save_profiles(profiles)

    def restore_default_profiles(self) -> int:
        """
        Restore all default profiles to their original state.

        Deletes existing default profiles (is_default=True) and recreates them
        from DEFAULT_PROFILES. Custom profiles are preserved.

        Returns:
            Number of profiles restored
        """
        with self._lock:
            # Find and remove all default profiles
            default_ids = [
                profile_id for profile_id, profile in self._profiles.items() if profile.is_default
            ]
            for profile_id in default_ids:
                del self._profiles[profile_id]

        # Save the changes (custom profiles only now)
        self._save()

        # Recreate defaults from scratch
        self._ensure_default_profiles()

        return len(default_ids)

    def _generate_id(self) -> str:
        """Generate a unique profile ID."""
        return str(uuid.uuid4())

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO 8601 format."""
        return datetime.now(UTC).isoformat()

    def _load_migration_state(self) -> dict[str, int]:
        """
        Load migration state from settings.

        Returns:
            Dictionary with migration version numbers
        """
        settings_path = self._config_dir / "settings.json"
        if settings_path.exists():
            try:
                with open(settings_path, encoding="utf-8") as f:
                    settings = json.load(f)
                    return settings.get("_migrations", {})
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load migration state: %s", e)
        return {}

    def _save_migration_state(self, state: dict[str, int]) -> None:
        """
        Save migration state to settings.

        Args:
            state: Dictionary with migration version numbers
        """
        settings_path = self._config_dir / "settings.json"
        settings: dict[str, Any] = {}
        if settings_path.exists():
            try:
                with open(settings_path, encoding="utf-8") as f:
                    settings = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not read settings before saving migration state: %s", e)

        settings["_migrations"] = state

        # Atomic write (temp file + rename) to avoid corrupting settings.json and
        # to mirror the owner-only permissions used elsewhere for config files.
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                suffix=".json",
                prefix="settings_",
                dir=self._config_dir,
            )
            try:
                try:
                    f = os.fdopen(fd, "w", encoding="utf-8")
                except Exception:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                    raise
                with f:
                    json.dump(settings, f, indent=2)
                Path(temp_path).replace(settings_path)
                os.chmod(settings_path, 0o600)
            except Exception:
                with contextlib.suppress(OSError):
                    Path(temp_path).unlink(missing_ok=True)
                raise
        except OSError as e:
            logger.error("Failed to save migration state: %s", e)

    def _migrate_default_profiles_to_xdg(self) -> None:
        """
        One-time migration: Update default profiles to use XDG paths.

        Replaces hardcoded ~/Downloads with xdg-user-dir DOWNLOAD result
        for the built-in "Quick Scan" profile.
        """
        from ..core.flatpak import get_xdg_user_dir

        # Check if migration already done
        migration_state = self._load_migration_state()
        if migration_state.get("xdg_migration_version", 0) >= _XDG_MIGRATION_VERSION:
            return

        modified = False
        with self._lock:
            for profile_id, profile in self._profiles.items():
                if profile.is_default and profile.name == "Quick Scan":
                    # Only migrate if still using the old hardcoded path
                    if profile.targets == ["~/Downloads"]:
                        xdg_download = get_xdg_user_dir("DOWNLOAD")
                        if xdg_download:
                            # Use immutable update pattern - create new profile
                            from dataclasses import replace

                            updated_profile = replace(
                                profile,
                                targets=[xdg_download],
                                updated_at=self._get_timestamp(),
                            )
                            self._profiles[profile_id] = updated_profile
                            modified = True
                            logger.info(
                                "Migrated Quick Scan target to XDG path: %s",
                                xdg_download,
                            )

        if modified:
            self._save()

        # Mark migration as complete
        migration_state["xdg_migration_version"] = _XDG_MIGRATION_VERSION
        self._save_migration_state(migration_state)

    @staticmethod
    @functools.lru_cache(maxsize=128)
    def _cached_expanduser(path_str: str) -> Path | None:
        """
        Cache-enabled path expansion for home directory.

        Uses LRU cache to avoid redundant expanduser() calls during validation.
        Thread-safe and handles exceptions gracefully.

        Args:
            path_str: Path string to expand (e.g., "~/Documents")

        Returns:
            Expanded Path object, or None if expansion fails
        """
        try:
            # Validate for null bytes (security/injection prevention)
            if "\x00" in path_str:
                return None
            return Path(path_str).expanduser()
        except (OSError, RuntimeError, ValueError):
            return None

    @staticmethod
    @functools.lru_cache(maxsize=128)
    def _cached_resolve(path_str: str) -> Path | None:
        """
        Cache-enabled path resolution to absolute canonical path.

        Uses LRU cache to avoid redundant resolve() syscalls during validation.
        Resolves symlinks and returns absolute path. Thread-safe and handles
        exceptions gracefully.

        Args:
            path_str: Path string to resolve

        Returns:
            Resolved Path object, or None if resolution fails
        """
        try:
            return Path(path_str).resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    @classmethod
    def clear_path_cache(cls) -> None:
        """
        Clear all path resolution caches.

        Clears the LRU caches for both _cached_expanduser() and _cached_resolve().
        This should be called when external filesystem changes occur that might
        affect path resolution results (e.g., symlinks changed, directories moved).

        Cache Lifecycle:
            - Caches are populated on first access during profile validation
            - Caches persist across multiple profile operations for performance
            - Caches should be cleared when filesystem state changes externally
            - Each cache holds up to 128 entries (LRU eviction policy)

        Thread Safety:
            This method is thread-safe. The underlying LRU cache implementations
            use locks internally for cache_clear() operations.

        Examples:
            >>> ProfileManager.clear_path_cache()  # Clear all caches
        """
        cls._cached_expanduser.cache_clear()
        cls._cached_resolve.cache_clear()

    @classmethod
    def get_cache_info(cls) -> dict[str, dict[str, int]]:
        """
        Get cache statistics for debugging and monitoring.

        Returns cache information for both _cached_expanduser() and
        _cached_resolve() methods. Useful for performance analysis and
        debugging cache behavior during validation.

        Returns:
            Dictionary with cache statistics for each cached method:
            {
                "expanduser": {
                    "hits": int,      # Number of cache hits
                    "misses": int,    # Number of cache misses
                    "maxsize": int,   # Maximum cache size
                    "currsize": int   # Current cache size
                },
                "resolve": {
                    "hits": int,
                    "misses": int,
                    "maxsize": int,
                    "currsize": int
                }
            }

        Thread Safety:
            This method is thread-safe. The underlying cache_info() calls
            are atomic snapshots of cache state.

        Examples:
            >>> info = ProfileManager.get_cache_info()
            >>> print(f"Expanduser cache hits: {info['expanduser']['hits']}")
            >>> print(f"Resolve cache hit rate: {info['resolve']['hits'] / (info['resolve']['hits'] + info['resolve']['misses'])}")
        """
        expanduser_info = cls._cached_expanduser.cache_info()
        resolve_info = cls._cached_resolve.cache_info()

        return {
            "expanduser": {
                "hits": expanduser_info.hits,
                "misses": expanduser_info.misses,
                "maxsize": expanduser_info.maxsize,
                "currsize": expanduser_info.currsize,
            },
            "resolve": {
                "hits": resolve_info.hits,
                "misses": resolve_info.misses,
                "maxsize": resolve_info.maxsize,
                "currsize": resolve_info.currsize,
            },
        }

    def _validate_name(self, name: str, exclude_id: str | None = None) -> None:
        """
        Validate a profile name.

        Args:
            name: The profile name to validate
            exclude_id: Optional profile ID to exclude from uniqueness check
                       (used when updating an existing profile)

        Raises:
            ValueError: If name is invalid (empty, too long, or duplicate)
        """
        # Check for empty or whitespace-only name
        if not name or not name.strip():
            raise ValueError("Profile name cannot be empty")

        stripped_name = name.strip()

        # Check name length
        if len(stripped_name) < MIN_PROFILE_NAME_LENGTH:
            raise ValueError("Profile name cannot be empty")

        if len(stripped_name) > MAX_PROFILE_NAME_LENGTH:
            raise ValueError(f"Profile name cannot exceed {MAX_PROFILE_NAME_LENGTH} characters")

        # Check for duplicate name
        if self.name_exists(stripped_name, exclude_id):
            raise ValueError(f"Profile name '{stripped_name}' already exists")

    def _validate_path_format(self, path: str) -> tuple[bool, str | None]:
        """
        Validate a path format.

        Checks that the path is a valid format (not necessarily existing).
        Allows ~ for home directory and relative/absolute paths.

        Args:
            path: The path string to validate

        Returns:
            Tuple of (is_valid, error_message):
            - (True, None) if path format is valid
            - (False, error_message) if path format is invalid
        """
        if not path or not path.strip():
            return (False, "Path cannot be empty")

        stripped_path = path.strip()

        # Check for null bytes (security)
        if "\x00" in stripped_path:
            return (False, "Path contains invalid characters")

        # Try to parse the path to check for basic validity
        try:
            # Expand ~ but don't require existence (use cached version)
            expanded = self._cached_expanduser(stripped_path)
            if expanded is None:
                return (False, f"Invalid path format: {stripped_path}")

            # Check that the path string is reasonable
            # (Path() can accept almost anything, so we do additional checks)

            # Reject paths with consecutive separators (except for // at start on some systems)
            if "//" in str(expanded)[1:] or "\\\\" in str(expanded):
                return (False, f"Invalid path format: {path}")

        except (OSError, RuntimeError, ValueError) as e:
            return (False, f"Invalid path format: {e}")

        return (True, None)

    def _validate_targets(self, targets: list[str]) -> list[str]:
        """
        Validate target paths.

        Validates each target path format. Non-existent paths are allowed
        as they may become valid later.

        Args:
            targets: List of target paths to validate

        Returns:
            List of warning messages (empty if no warnings)

        Raises:
            ValueError: If targets is not a list or contains invalid path formats
        """
        warnings: list[str] = []

        # Validate targets is a list
        if not isinstance(targets, list):
            raise ValueError("Targets must be a list of paths")

        # Validate each target path format
        for i, target in enumerate(targets):
            if not isinstance(target, str):
                raise ValueError(f"Target at index {i} must be a string")

            is_valid, error = self._validate_path_format(target)
            if not is_valid:
                raise ValueError(f"Invalid target path: {error}")

        return warnings

    def _validate_exclusions(self, exclusions: dict[str, Any], targets: list[str]) -> list[str]:
        """
        Validate exclusion settings.

        Validates exclusion structure and path formats. Also checks for
        circular exclusions (exclusion is parent of all targets).

        Args:
            exclusions: Dictionary of exclusion settings
            targets: List of target paths (for circular exclusion check)

        Returns:
            List of warning messages (empty if no warnings)

        Raises:
            ValueError: If exclusions structure is invalid or contains invalid paths
        """
        warnings: list[str] = []

        # Validate exclusions is a dict
        if not isinstance(exclusions, dict):
            raise ValueError("Exclusions must be a dictionary")

        # If exclusions is empty, it's valid
        if not exclusions:
            return warnings

        # Validate 'paths' key if present
        if "paths" in exclusions:
            paths = exclusions["paths"]

            if not isinstance(paths, list):
                raise ValueError("Exclusions 'paths' must be a list")

            for i, path in enumerate(paths):
                if not isinstance(path, str):
                    raise ValueError(f"Exclusion path at index {i} must be a string")

                is_valid, error = self._validate_path_format(path)
                if not is_valid:
                    raise ValueError(f"Invalid exclusion path: {error}")

            # Check for circular exclusions
            # (exclusion path that would exclude all targets)
            self._check_circular_exclusions(paths, targets, warnings)

        # Validate 'patterns' key if present (file patterns like *.tmp)
        if "patterns" in exclusions:
            patterns = exclusions["patterns"]

            if not isinstance(patterns, list):
                raise ValueError("Exclusions 'patterns' must be a list")

            for i, pattern in enumerate(patterns):
                if not isinstance(pattern, str):
                    raise ValueError(f"Exclusion pattern at index {i} must be a string")

                if not pattern.strip():
                    raise ValueError("Exclusion pattern cannot be empty")

        return warnings

    def _check_circular_exclusions(
        self,
        exclusion_paths: list[str],
        targets: list[str],
        warnings: list[str],
    ) -> None:
        """
        Check for circular exclusions where an exclusion would exclude all targets.

        Args:
            exclusion_paths: List of exclusion paths
            targets: List of target paths
            warnings: List to append warning messages to
        """
        if not targets or not exclusion_paths:
            return

        for exclusion in exclusion_paths:
            # Normalize the exclusion path using cached methods
            if exclusion.startswith("~"):
                # First expand ~, then resolve
                expanded = self._cached_expanduser(exclusion)
                if expanded is None:
                    continue
                excl_path = self._cached_resolve(str(expanded))
                if excl_path is None:
                    continue
            else:
                # Just resolve
                excl_path = self._cached_resolve(exclusion)
                if excl_path is None:
                    continue

            # Check if all targets are children of this exclusion
            all_excluded = True
            for target in targets:
                # Normalize the target path using cached methods
                if target.startswith("~"):
                    # First expand ~, then resolve
                    expanded = self._cached_expanduser(target)
                    if expanded is None:
                        all_excluded = False
                        break
                    target_path = self._cached_resolve(str(expanded))
                    if target_path is None:
                        all_excluded = False
                        break
                else:
                    # Just resolve
                    target_path = self._cached_resolve(target)
                    if target_path is None:
                        all_excluded = False
                        break

                # Check if target is the same as or is a child of exclusion
                if not (target_path == excl_path or self._is_subpath(target_path, excl_path)):
                    all_excluded = False
                    break

            if all_excluded and len(targets) > 0:
                warnings.append(f"Exclusion '{exclusion}' would exclude all scan targets")

    def _is_subpath(self, path: Path, parent: Path) -> bool:
        """
        Check if path is a subpath of parent.

        Args:
            path: The path to check
            parent: The potential parent path

        Returns:
            True if path is under parent, False otherwise
        """
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def _validate_profile(
        self,
        name: str,
        targets: list[str],
        exclusions: dict[str, Any],
        exclude_id: str | None = None,
    ) -> list[str]:
        """
        Validate all profile fields.

        Args:
            name: Profile name
            targets: List of target paths
            exclusions: Dictionary of exclusion settings
            exclude_id: Optional profile ID to exclude from name uniqueness check

        Returns:
            List of warning messages (non-fatal issues)

        Raises:
            ValueError: If validation fails for any required field
        """
        warnings: list[str] = []

        # Validate name (raises ValueError if invalid)
        self._validate_name(name, exclude_id)

        # Validate targets (raises ValueError if invalid format)
        target_warnings = self._validate_targets(targets)
        warnings.extend(target_warnings)

        # Validate exclusions (raises ValueError if invalid)
        exclusion_warnings = self._validate_exclusions(exclusions, targets)
        warnings.extend(exclusion_warnings)

        return warnings

    def create_profile(
        self,
        name: str,
        targets: list[str],
        exclusions: dict[str, Any],
        description: str = "",
        options: dict[str, Any] | None = None,
        is_default: bool = False,
    ) -> ScanProfile:
        """
        Create and save a new profile.

        Args:
            name: User-visible profile name
            targets: List of directories/files to scan
            exclusions: Dictionary of exclusion settings
            description: Optional description of the profile
            options: Optional scan engine options
            is_default: Whether this is a built-in profile

        Returns:
            The newly created ScanProfile

        Raises:
            ValueError: If validation fails
        """
        # Normalize the name once at the boundary so the stored, validated, and
        # deduplicated value all match (validation strips, but storage must too).
        name = name.strip()

        # Validate profile fields (raises ValueError if invalid)
        self._validate_profile(name, targets, exclusions or {})

        timestamp = self._get_timestamp()

        profile = ScanProfile(
            id=self._generate_id(),
            name=name,
            targets=list(targets),
            exclusions=dict(exclusions) if exclusions else {},
            created_at=timestamp,
            updated_at=timestamp,
            is_default=is_default,
            description=description,
            options=dict(options) if options else {},
        )

        with self._lock:
            self._profiles[profile.id] = profile

        self._save()
        return profile

    def get_profile(self, profile_id: str) -> ScanProfile | None:
        """
        Retrieve a profile by ID.

        Args:
            profile_id: The unique identifier of the profile

        Returns:
            The ScanProfile if found, None otherwise
        """
        with self._lock:
            return self._profiles.get(profile_id)

    def get_profile_by_name(self, name: str) -> ScanProfile | None:
        """
        Retrieve a profile by name.

        Args:
            name: The profile name to search for

        Returns:
            The ScanProfile if found, None otherwise
        """
        with self._lock:
            for profile in self._profiles.values():
                if profile.name == name:
                    return profile
        return None

    def update_profile(self, profile_id: str, **updates: Any) -> ScanProfile | None:
        """
        Update an existing profile.

        Args:
            profile_id: The unique identifier of the profile to update
            **updates: Keyword arguments for fields to update
                      (name, targets, exclusions, description, options)

        Returns:
            The updated ScanProfile if found, None otherwise

        Raises:
            ValueError: If validation fails or trying to change protected fields
        """
        with self._lock:
            profile = self._profiles.get(profile_id)
            if profile is None:
                return None

            # Determine final values (updated or existing)
            new_name = updates.get("name", profile.name)
            # Normalize once at the boundary so stored/validated/deduped names match.
            new_name = new_name.strip()
            # Default profiles are recreated by name at startup (see
            # _ensure_default_profiles), so renaming one orphans it and spawns a
            # duplicate default on the next launch. Defaults are already protected
            # from deletion and is_default changes; treat renaming the same way.
            if profile.is_default and new_name != profile.name:
                raise ValueError("Cannot rename a default profile")
            new_targets = updates.get("targets", profile.targets)
            new_exclusions = updates.get("exclusions", profile.exclusions)

        # Validate updated fields (raises ValueError if invalid)
        # Pass profile_id to exclude_id so name uniqueness check excludes this profile
        self._validate_profile(new_name, new_targets, new_exclusions, exclude_id=profile_id)

        with self._lock:
            profile = self._profiles.get(profile_id)
            if profile is None:
                return None

            # Create updated profile with new values
            updated_profile = ScanProfile(
                id=profile.id,
                name=new_name,
                targets=new_targets,
                exclusions=new_exclusions,
                created_at=profile.created_at,
                updated_at=self._get_timestamp(),
                is_default=profile.is_default,  # Cannot change is_default
                description=updates.get("description", profile.description),
                options=updates.get("options", profile.options),
            )

            self._profiles[profile_id] = updated_profile

        self._save()
        return updated_profile

    def delete_profile(self, profile_id: str) -> bool:
        """
        Delete a profile.

        Cannot delete default profiles.

        Args:
            profile_id: The unique identifier of the profile to delete

        Returns:
            True if deleted successfully, False if not found or is default

        Raises:
            ValueError: If attempting to delete a default profile
        """
        with self._lock:
            profile = self._profiles.get(profile_id)
            if profile is None:
                return False

            if profile.is_default:
                raise ValueError("Cannot delete default profile")

            del self._profiles[profile_id]

        self._save()
        return True

    def list_profiles(self) -> list[ScanProfile]:
        """
        Get all available profiles.

        Returns:
            List of all ScanProfile instances, sorted by name
        """
        with self._lock:
            profiles = list(self._profiles.values())
        return sorted(profiles, key=lambda p: p.name.lower())

    def get_all_profiles(self) -> dict[str, ScanProfile]:
        """
        Get a copy of all profiles as a dictionary.

        Returns:
            Dictionary mapping profile IDs to ScanProfile instances
        """
        with self._lock:
            return dict(self._profiles)

    def profile_exists(self, profile_id: str) -> bool:
        """
        Check if a profile exists.

        Args:
            profile_id: The unique identifier to check

        Returns:
            True if profile exists, False otherwise
        """
        with self._lock:
            return profile_id in self._profiles

    def name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        """
        Check if a profile name already exists.

        Args:
            name: The name to check
            exclude_id: Optional profile ID to exclude from check
                       (useful when updating a profile's name)

        Returns:
            True if name exists (excluding the specified ID), False otherwise
        """
        with self._lock:
            for profile in self._profiles.values():
                if profile.name == name and profile.id != exclude_id:
                    return True
        return False

    def reload(self) -> None:
        """Reload profiles from storage, discarding in-memory changes."""
        self._load()

    def export_profile(self, profile_id: str, export_path: Path) -> None:
        """
        Export a profile to a JSON file.

        Exports a single profile to a standalone JSON file for backup
        or sharing purposes.

        Args:
            profile_id: The unique identifier of the profile to export
            export_path: Path where the JSON file will be saved

        Raises:
            ValueError: If profile not found
            OSError: If file cannot be written
        """
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ValueError(f"Profile with ID '{profile_id}' not found")

        export_path = Path(export_path)

        # Prepare export data
        # Exclude is_default since imported profiles should not be default
        profile_data = profile.to_dict()
        export_data = {
            "export_version": 1,
            "profile": profile_data,
        }

        # Ensure parent directory exists
        export_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write using temp file + rename pattern
        fd, temp_path = tempfile.mkstemp(
            suffix=".json",
            prefix="profile_export_",
            dir=export_path.parent,
        )
        try:
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
            except Exception:
                with contextlib.suppress(OSError):
                    os.close(fd)
                raise

            with f:
                json.dump(export_data, f, indent=2)

            # Atomic rename
            Path(temp_path).replace(export_path)
        except Exception:
            # Clean up temp file on failure
            with contextlib.suppress(OSError):
                Path(temp_path).unlink(missing_ok=True)
            raise

    def import_profile(self, import_path: Path) -> ScanProfile:
        """
        Import a profile from a JSON file.

        Imports a profile from a standalone JSON file. The imported
        profile receives a new unique ID and is never marked as default.
        Duplicate names are handled by appending a numeric suffix.

        Args:
            import_path: Path to the JSON file to import

        Returns:
            The newly imported ScanProfile

        Raises:
            ValueError: If file format is invalid or required fields are missing
            OSError: If file cannot be read
            FileNotFoundError: If file does not exist
        """
        import_path = Path(import_path)

        if not import_path.exists():
            raise FileNotFoundError(f"Import file not found: {import_path}")

        # Read and parse the JSON file
        try:
            with open(import_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}") from e

        # Validate export format
        if not isinstance(data, dict):
            raise ValueError("Invalid export format: expected JSON object")

        # Support both versioned export format and raw profile format
        if "profile" in data:
            profile_data = data["profile"]
        else:
            # Assume the entire object is a profile (legacy format)
            profile_data = data

        if not isinstance(profile_data, dict):
            raise ValueError("Invalid export format: profile data must be an object")

        # Validate required fields
        required_fields = ["name"]
        for field in required_fields:
            if field not in profile_data:
                raise ValueError(f"Invalid profile data: missing required field '{field}'")

        # Extract profile data with defaults
        raw_name = profile_data.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("Invalid profile data: 'name' must be a non-empty string")
        name = raw_name.strip()
        targets = profile_data.get("targets", [])
        exclusions = profile_data.get("exclusions", {})
        description = str(profile_data.get("description", ""))
        options = profile_data.get("options", {})

        # Validate types
        if not isinstance(targets, list):
            raise ValueError("Invalid profile data: 'targets' must be a list")
        if not isinstance(exclusions, dict):
            raise ValueError("Invalid profile data: 'exclusions' must be an object")
        if not isinstance(options, dict):
            raise ValueError("Invalid profile data: 'options' must be an object")

        # Handle duplicate names by appending numeric suffix
        original_name = name
        final_name = self._make_unique_name(original_name)

        # Create the profile with a new ID
        # Imported profiles are never default
        return self.create_profile(
            name=final_name,
            targets=targets,
            exclusions=exclusions,
            description=description,
            options=options,
            is_default=False,
        )

    def _make_unique_name(self, name: str) -> str:
        """
        Ensure a profile name is unique by appending a numeric suffix if needed.

        Args:
            name: The proposed name

        Returns:
            A unique name (original if available, or with suffix like " (2)")
        """
        if not self.name_exists(name):
            return name

        # Try appending (2), (3), etc. until we find a unique name
        counter = 2
        while True:
            candidate = f"{name} ({counter})"
            # Ensure the candidate doesn't exceed max length
            if len(candidate) > MAX_PROFILE_NAME_LENGTH:
                # Truncate the base name to make room for suffix
                suffix = f" ({counter})"
                max_base = MAX_PROFILE_NAME_LENGTH - len(suffix)
                candidate = f"{name[:max_base]} ({counter})"

            if not self.name_exists(candidate):
                return candidate

            counter += 1

            # Safety limit to prevent infinite loop
            if counter > 1000:
                raise ValueError(f"Could not generate unique name for '{name}'")
