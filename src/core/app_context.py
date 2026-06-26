# App Context
"""
Shared application context for ClamUI.

This module provides a centralized container for application-wide state
and services, reducing the god object antipattern in ClamUIApp.

Key Responsibilities:
    - Hold references to core managers (settings, notifications, profiles)
    - Provide lazy initialization for heavy resources (quarantine, VirusTotal)
    - Track application state (scan active, tray available)
    - Coordinate between UI and core services

Design Pattern:
    AppContext follows the Service Locator pattern with lazy initialization.
    Heavy resources are only created when first accessed, reducing startup
    time and memory usage.

Usage:
    context = AppContext()
    settings = context.settings_manager
    quarantine = context.quarantine_manager  # Lazy init
"""

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import GLib

from ..profiles.profile_manager import ProfileManager
from .notification_manager import NotificationManager
from .settings_manager import SettingsManager

if TYPE_CHECKING:
    from .quarantine import QuarantineManager
    from .virustotal import VirusTotalClient

logger = logging.getLogger(__name__)


class AppContext:
    """
    Centralized application context holding shared state and services.

    This class encapsulates application-wide dependencies to avoid
    passing individual references throughout the codebase.

    Attributes:
        settings_manager: User preferences and configuration.
        notification_manager: Desktop notifications.
        profile_manager: Scan profiles management.
        quarantine_manager: Quarantine operations (lazy).
        vt_client: VirusTotal API client (lazy).
    """

    def __init__(self):
        """Initialize the application context with core services."""
        self._settings_manager = SettingsManager()
        self._notification_manager = NotificationManager(self._settings_manager)

        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "~/.config")
        config_dir = Path(xdg_config_home).expanduser() / "clamui"
        self._profile_manager = ProfileManager(config_dir)

        self._quarantine_manager: QuarantineManager | None = None
        self._vt_client: VirusTotalClient | None = None
        self._device_monitor = None
        self._tray_indicator = None

        self._is_scan_active = False

    @property
    def settings_manager(self) -> SettingsManager:
        """Get the settings manager instance."""
        return self._settings_manager

    @property
    def notification_manager(self) -> NotificationManager:
        """Get the notification manager instance."""
        return self._notification_manager

    @property
    def profile_manager(self) -> ProfileManager:
        """Get the profile manager instance."""
        return self._profile_manager

    @property
    def quarantine_manager(self) -> "QuarantineManager":
        """
        Get the quarantine manager, creating it lazily if needed.

        Returns:
            The shared QuarantineManager instance.
        """
        if self._quarantine_manager is None:
            from .quarantine import QuarantineManager

            self._quarantine_manager = QuarantineManager(settings_manager=self._settings_manager)
        return self._quarantine_manager

    def preinit_quarantine_async(self, callback: Callable[[], None] | None = None) -> None:
        """
        Initialize quarantine manager asynchronously in a background thread.

        This pre-warms the quarantine manager so it's ready when the user
        first navigates to the quarantine view, avoiding the first-time lag.

        Args:
            callback: Optional callback invoked on main thread after init completes.
        """
        if self._quarantine_manager is not None:
            if callback:
                GLib.idle_add(callback)
            return

        def _init_thread():
            try:
                _ = self.quarantine_manager
                logger.debug("QuarantineManager pre-initialized in background")
            except Exception as e:
                logger.warning("Failed to pre-initialize QuarantineManager: %s", e)
            finally:
                if callback:
                    GLib.idle_add(callback)

        thread = threading.Thread(target=_init_thread, daemon=True)
        thread.start()

    @property
    def vt_client(self) -> "VirusTotalClient | None":
        """Get the VirusTotal client (may be None if not configured)."""
        return self._vt_client

    @property
    def tray_indicator(self):
        """Get the tray indicator instance (may be None if not available)."""
        return self._tray_indicator

    @tray_indicator.setter
    def tray_indicator(self, value):
        """Set the tray indicator instance."""
        self._tray_indicator = value

    @property
    def device_monitor(self):
        """Get the device monitor instance."""
        return self._device_monitor

    @device_monitor.setter
    def device_monitor(self, value):
        """Set the device monitor instance."""
        self._device_monitor = value

    @property
    def is_scan_active(self) -> bool:
        """Check if a scan is currently in progress."""
        return self._is_scan_active

    @is_scan_active.setter
    def is_scan_active(self, value: bool):
        """Set the scan active state."""
        self._is_scan_active = value

    def get_or_create_vt_client(self, api_key: str) -> "VirusTotalClient":
        """
        Get or create a VirusTotal client with the given API key.

        Args:
            api_key: VirusTotal API key.

        Returns:
            VirusTotalClient instance.
        """
        if self._vt_client is None:
            from .virustotal import VirusTotalClient

            self._vt_client = VirusTotalClient(api_key)
        else:
            self._vt_client.set_api_key(api_key)
        return self._vt_client

    def cleanup(self) -> None:
        """
        Clean up all managed resources.

        Should be called during application shutdown.
        """
        if self._device_monitor is not None:
            try:
                self._device_monitor.stop()
                self._device_monitor = None
            except Exception as e:
                logger.warning("Error stopping device monitor: %s", e)

        if self._vt_client is not None:
            try:
                self._vt_client.close()
                self._vt_client = None
            except Exception as e:
                logger.warning("Error closing VirusTotal client: %s", e)

        if self._quarantine_manager is not None:
            try:
                self._quarantine_manager.close()
            except Exception as e:
                logger.warning("Error closing quarantine manager: %s", e)
