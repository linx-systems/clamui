# ClamUI Application Lifecycle Management
"""
Application lifecycle management for ClamUI.

This module handles the application startup, activation, and shutdown
sequences, including resource initialization and cleanup.
"""

import logging
from pathlib import Path

from .core.device_monitor import DeviceMonitor

logger = logging.getLogger(__name__)


class AppLifecycleManager:
    """Manages application lifecycle events and resource initialization."""

    def __init__(self, app):
        """Initialize the lifecycle manager."""
        self._app = app

    def ensure_clamav_database_dir(self) -> None:
        """Ensure the ClamAV database directory exists."""
        db_dir = self._get_database_dir()

        try:
            db_dir.mkdir(parents=True, exist_ok=True)
            db_dir.chmod(0o700)
            logger.debug(f"ClamAV database directory ensured: {db_dir}")
        except OSError as e:
            logger.warning(f"Failed to create XDG database dir {db_dir}: {e}; trying fallback")
            fallback_db_dir = Path("/var/lib/clamav")
            try:
                fallback_db_dir.mkdir(parents=True, exist_ok=True)
            except OSError as fallback_error:
                logger.warning(
                    f"Failed to create fallback database dir {fallback_db_dir}: {fallback_error}"
                )

    def _get_database_dir(self) -> Path:
        """Get the ClamAV database directory path."""
        xdg_data_home = Path(
            __import__("os").environ.get("XDG_DATA_HOME", "~/.local/share")
        ).expanduser()
        return xdg_data_home / "clamui" / "database"

    def setup_device_monitor(self) -> None:
        """Initialize the device monitor for auto-scanning on file changes."""
        try:
            self._app._device_monitor = DeviceMonitor(
                self._app.settings_manager,
                self._app.quarantine_manager,
            )
            logger.info("Device monitor initialized")
        except Exception as e:
            logger.error(f"Failed to initialize device monitor: {e}")
            self._app._device_monitor = None

    def stop_device_monitor(self) -> None:
        """Stop the device monitor gracefully."""
        if self._app._device_monitor is not None:
            try:
                self._app._device_monitor.stop()
                self._app._device_monitor = None
                logger.info("Device monitor stopped")
            except Exception as e:
                logger.warning(f"Error stopping device monitor: {e}")

    def preinit_heavy_resources(self) -> None:
        """Pre-initialize heavy resources in the background."""
        self._app._preinit_quarantine_async()

    def preinit_quarantine_view(self) -> bool:
        """Pre-create the quarantine view widget after the manager is ready."""
        try:
            # Access property to create
            _ = self._app.quarantine_view
            logger.debug("Quarantine view pre-created")
        except Exception as e:
            logger.warning(f"Failed to pre-create quarantine view: {e}")
        return False

    def shutdown(self) -> None:
        """Perform application shutdown cleanup."""
        cleanup_tasks = [
            ("device_monitor", self._cleanup_device_monitor),
            ("scan", self._cleanup_scan),
            ("tray", self._cleanup_tray),
            ("vt_client", self._cleanup_vt_client),
            ("quarantine", self._cleanup_quarantine),
        ]

        for task_name, cleanup_func in cleanup_tasks:
            try:
                cleanup_func()
            except (AttributeError, RuntimeError) as e:
                logger.warning(f"Cleanup {task_name}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error during {task_name} cleanup: {e}")

    def _cleanup_device_monitor(self) -> None:
        """Cleanup device monitor resources."""
        if self._app._device_monitor is not None:
            self._app._device_monitor.stop()
            self._app._device_monitor = None

    def _cleanup_scan(self) -> None:
        """Cleanup scan resources."""
        if self._app._scan_view is not None and hasattr(self._app._scan_view, "_scanner"):
            try:
                self._app._scan_view._scanner.cancel()
            except Exception as e:
                logger.warning(f"Error cancelling scan: {e}")

    def _cleanup_tray(self) -> None:
        """Cleanup tray indicator resources."""
        if self._app._tray_indicator is not None:
            try:
                self._app._tray_indicator.cleanup()
            except Exception as e:
                logger.warning(f"Error cleaning up tray: {e}")

    def _cleanup_vt_client(self) -> None:
        """Cleanup VirusTotal client resources."""
        if self._app._vt_client is not None:
            self._app._vt_client = None

    def _cleanup_quarantine(self) -> None:
        """Cleanup quarantine manager resources."""
        if self._app._quarantine_manager is not None:
            try:
                self._app._quarantine_manager.close()
            except Exception as e:
                logger.warning(f"Error closing quarantine manager: {e}")
