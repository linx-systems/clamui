# ClamUI Settings Manager Module
"""
Settings manager module for ClamUI providing user preferences storage.
Stores user settings in JSON format following XDG conventions.
"""

import contextlib
import copy
import json
import logging
import os
import tempfile
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class _ListenerRef:
    """Track a settings listener without unnecessarily retaining bound methods."""

    def __init__(self, callback: Callable[[Any], None]):
        self._strong_callback: Callable[[Any], None] | None = None

        if getattr(callback, "__self__", None) is not None:
            self._ref = weakref.WeakMethod(callback)
            return

        try:
            self._ref = weakref.ref(callback)
        except TypeError:
            # Fallback for callables that cannot be weak-referenced.
            self._ref = None
            self._strong_callback = callback

    def get(self) -> Callable[[Any], None] | None:
        """Return the live callback, if it still exists."""
        if self._strong_callback is not None:
            return self._strong_callback
        if self._ref is None:
            return None
        return self._ref()

    def matches(self, callback: Callable[[Any], None]) -> bool:
        """Check whether this reference points at the provided callback."""
        return self.get() == callback


class SettingsManager:
    """
    Manager for user settings persistence.

    Provides methods for saving and loading user preferences
    stored in JSON format at ~/.config/clamui/settings.json.
    """

    DEFAULT_SETTINGS = {
        "language": "auto",  # "auto" = system default, or ISO code e.g. "de", "zh_CN"
        "notifications_enabled": True,
        "minimize_to_tray": False,
        "start_minimized": False,
        # Close behavior: None = first-run/unset, "minimize", "quit", "ask"
        "close_behavior": None,
        # Quarantine settings
        "quarantine_directory": "",  # Empty string means use default (~/.local/share/clamui/quarantine)
        # Scheduled scan settings
        "scheduled_scans_enabled": False,
        "schedule_frequency": "weekly",  # "daily", "weekly", "monthly"
        "schedule_time": "02:00",  # 24-hour format HH:MM
        "schedule_targets": [],  # List of directory paths to scan
        "schedule_skip_on_battery": True,
        "schedule_auto_quarantine": False,
        "schedule_day_of_week": 0,  # 0=Monday, 6=Sunday (for weekly scans)
        "schedule_day_of_month": 1,  # 1-28 (for monthly scans)
        "exclusion_patterns": [],
        # Scan backend settings
        "scan_backend": "auto",  # "auto", "daemon", "clamscan"
        "daemon_socket_path": "",  # Empty = auto-detect
        "clamd_conf_path": "",  # Empty = auto-detect
        "freshclam_conf_path": "",  # Empty = auto-detect
        "clamd_size_limit_unit_migration_done": False,
        # VirusTotal settings
        "virustotal_api_key": None,  # Fallback storage if keyring unavailable (gated by
        # allow_plaintext_api_key_fallback — default False, key is only written here
        # when the user has explicitly opted in via preferences)
        "allow_plaintext_api_key_fallback": False,
        "virustotal_remember_no_key_action": "none",  # "none", "open_website", "prompt"
        # Debug logging settings
        "debug_log_level": "WARNING",  # "DEBUG", "INFO", "WARNING", "ERROR"
        "debug_log_max_size_mb": 5,  # Max size per log file in MB
        "debug_log_max_files": 3,  # Number of backup files to keep
        # Live progress settings
        "show_live_progress": True,  # Show real-time file scanning progress
        # Device auto-scan settings
        "device_auto_scan_enabled": False,
        "device_auto_scan_types": ["removable", "external"],
        "device_auto_scan_notify": True,
        "device_auto_scan_max_size_gb": 32,
        "device_auto_scan_delay_seconds": 3,
        "device_auto_scan_auto_quarantine": False,
        "device_auto_scan_skip_on_battery": True,
    }

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize the SettingsManager.

        Args:
            config_dir: Optional custom config directory.
                        Defaults to XDG_CONFIG_HOME/clamui or ~/.config/clamui
        """
        if config_dir is not None:
            self._config_dir = Path(config_dir)
        else:
            xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "~/.config")
            self._config_dir = Path(xdg_config_home).expanduser() / "clamui"

        self._settings_file = self._config_dir / "settings.json"

        # Thread lock for safe concurrent access
        self._lock = threading.Lock()
        self._listeners: dict[str, list[_ListenerRef]] = {}

        # Load settings on initialization
        self._settings = self._load()

    def _load(self) -> dict:
        """
        Load settings from file.

        Returns:
            Dictionary of settings merged with defaults
        """
        with self._lock:
            try:
                if self._settings_file.exists():
                    with open(self._settings_file, encoding="utf-8") as f:
                        loaded = json.load(f)
                        # Verify loaded data is a dict
                        if not isinstance(loaded, dict):
                            # Non-dict JSON (arrays, null, primitives) is invalid
                            self._backup_corrupted_file()
                            return copy.deepcopy(self.DEFAULT_SETTINGS)
                        # Merge with defaults to ensure all keys exist
                        return {**copy.deepcopy(self.DEFAULT_SETTINGS), **loaded}
            except json.JSONDecodeError:
                # Handle corrupted files - backup for debugging
                self._backup_corrupted_file()
            except (OSError, PermissionError):
                # Handle permission issues silently
                logger.debug("Failed to load settings file %s", self._settings_file, exc_info=True)
            return copy.deepcopy(self.DEFAULT_SETTINGS)

    def save(self) -> bool:
        """
        Save settings to file using atomic write.

        Uses a temporary file and rename pattern to prevent
        corruption during write operations.

        Returns:
            True if saved successfully, False for ANY exception
            (including OSError, PermissionError, JSONEncodeError, etc.)
        """
        with self._lock:
            try:
                # Ensure parent directory exists
                self._config_dir.mkdir(parents=True, exist_ok=True)

                # Atomic write using temp file + rename
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
                        json.dump(self._settings, f, indent=2)

                    # Atomic rename
                    temp_path_obj = Path(temp_path)
                    temp_path_obj.replace(self._settings_file)

                    # Harden file permissions (owner read/write only)
                    # Settings may contain sensitive data like API keys in fallback storage
                    self._settings_file.chmod(0o600)
                    return True
                except Exception:
                    # Clean up temp file on failure
                    with contextlib.suppress(OSError):
                        Path(temp_path).unlink(missing_ok=True)
                    raise

            except Exception:
                # Catch all exceptions (including OSError, PermissionError)
                return False

    def _backup_corrupted_file(self) -> None:
        """
        Create a backup of a corrupted settings file.

        What Triggers Backup:
        - JSON decode errors during _load_settings() (malformed JSON syntax)
        - Settings file contains invalid JSON structure (not a dict)
        - File corruption due to incomplete writes (power loss, disk errors)
        - Manual editing errors by users (missing commas, unclosed brackets)

        Backup Behavior:
        - Renames settings.json → settings.json.corrupted
        - Preserves corrupted file for debugging/recovery
        - Won't overwrite existing .corrupted backups (keeps first corruption)
        - Allows app to start with default settings after backup

        Renames the corrupted file with a .corrupted suffix
        to preserve it for debugging purposes.
        """
        try:
            if self._settings_file.exists():
                backup_path = self._settings_file.with_suffix(
                    f"{self._settings_file.suffix}.corrupted"
                )
                # Don't overwrite existing backups
                if not backup_path.exists():
                    self._settings_file.rename(backup_path)
        except (OSError, PermissionError):
            # Silently fail - backup is best effort
            logger.debug("Failed to backup corrupted settings file", exc_info=True)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.

        Args:
            key: The setting key to retrieve
            default: Default value if key not found

        Returns:
            The setting value or default
        """
        with self._lock:
            return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        """
        Set a setting value and save to file.

        Args:
            key: The setting key to set
            value: The value to store

        Returns:
            True if saved successfully, False otherwise
        """
        should_notify = False
        with self._lock:
            previous = self._settings.get(key)
            self._settings[key] = value
            should_notify = previous != value

        saved = self.save()
        if should_notify:
            self._notify_listeners(key, value)
        return saved

    def reset_to_defaults(self) -> bool:
        """
        Reset all settings to defaults and save.

        Returns:
            True if saved successfully, False otherwise
        """
        changed_values: dict[str, Any] = {}
        with self._lock:
            previous_settings = dict(self._settings)
            self._settings = copy.deepcopy(self.DEFAULT_SETTINGS)
            changed_keys = set(previous_settings) | set(self._settings)
            for key in changed_keys:
                new_value = self._settings.get(key)
                if previous_settings.get(key) != new_value:
                    changed_values[key] = new_value

        saved = self.save()
        for key, value in changed_values.items():
            self._notify_listeners(key, value)
        return saved

    def get_all(self) -> dict:
        """
        Get a copy of all settings.

        Returns:
            Dictionary with all current settings
        """
        with self._lock:
            return dict(self._settings)

    def add_listener(self, key: str, callback: Callable[[Any], None]) -> None:
        """
        Register a callback for changes to a specific setting key.

        Args:
            key: Setting key to observe
            callback: Called with the new value after the setting changes
        """
        with self._lock:
            listeners = self._listeners.setdefault(key, [])
            listeners.append(_ListenerRef(callback))

    def remove_listener(self, key: str, callback: Callable[[Any], None]) -> None:
        """
        Remove a previously registered setting listener.

        Args:
            key: Setting key being observed
            callback: Callback previously passed to add_listener()
        """
        with self._lock:
            listeners = self._listeners.get(key)
            if not listeners:
                return

            remaining = [
                listener
                for listener in listeners
                if listener.get() is not None and not listener.matches(callback)
            ]

            if remaining:
                self._listeners[key] = remaining
            else:
                self._listeners.pop(key, None)

    def _notify_listeners(self, key: str, value: Any) -> None:
        """Notify listeners registered for a changed setting key."""
        with self._lock:
            listeners = list(self._listeners.get(key, []))

        stale_listeners = False
        for listener in listeners:
            callback = listener.get()
            if callback is None:
                stale_listeners = True
                continue

            try:
                callback(value)
            except Exception:
                logger.exception("Settings listener failed for key %s", key)

        if stale_listeners:
            with self._lock:
                current = self._listeners.get(key)
                if current is None:
                    return

                remaining = [listener for listener in current if listener.get() is not None]
                if remaining:
                    self._listeners[key] = remaining
                else:
                    self._listeners.pop(key, None)
