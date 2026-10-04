# ClamUI Tray Integration
"""
Tray integration for ClamUI.

This module handles system tray indicator management, tray menu actions,
and device scan event handling.
"""

import logging

logger = logging.getLogger(__name__)


class TrayIntegration:
    """Manages system tray indicator integration."""

    def __init__(self, app):
        """Initialize the tray integration."""
        self._app = app

    def setup_tray_indicator(self):
        """Initialize the tray indicator if available."""
        try:
            from .ui.tray_indicator import TrayIndicator

            self._app._tray_indicator = TrayIndicator(self._app)
            logger.info("Tray indicator initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize tray indicator: {e}")

    def cleanup_tray(self):
        """Cleanup tray indicator resources."""
        if self._app._tray_indicator is not None:
            try:
                self._app._tray_indicator.cleanup()
                self._app._tray_indicator = None
            except Exception as e:
                logger.warning(f"Error cleaning up tray: {e}")

    def sync_profiles_to_tray(self, profiles):
        """Sync scan profiles to the tray menu."""
        if self._app._tray_indicator is None:
            return

        profile_data = [(p.id, p.name, p.description) for p in profiles]

        current_profile_id = None
        if self._app.scan_view is not None:
            current_profile = self._app.scan_view.get_selected_profile()
            if current_profile:
                current_profile_id = current_profile.id

        try:
            self._app._tray_indicator.set_profiles(profile_data, current_profile_id)
        except Exception as e:
            logger.warning(f"Failed to sync profiles to tray: {e}")

    def trigger_quick_scan(self):
        """Trigger a quick scan from the tray menu."""
        from gi.repository import GLib

        GLib.idle_add(self._do_tray_quick_scan)

    def _do_tray_quick_scan(self):
        """Execute the quick scan from the tray."""
        # Activate the application (creates window if needed)
        self._app.activate()

        win = self._app.props.active_window
        if win is None:
            return False

        quick_scan_profile = self._app._get_quick_scan_profile()

        if quick_scan_profile:
            self._app.scan_view.refresh_profiles()
            self._app.scan_view.set_selected_profile(quick_scan_profile.id)
            self._app._view_coordinator.switch_to_view("scan", self._app.scan_view)
            self._app.scan_view._start_scan()
        else:
            import os

            home_dir = os.path.expanduser("~")
            self._app.scan_view._set_selected_path(home_dir)
            self._app._view_coordinator.switch_to_view("scan", self._app.scan_view)
            self._app.scan_view._start_scan()
            logger.warning("Quick Scan profile not found, falling back to home directory")

        return False

    def trigger_full_scan(self):
        """Trigger a full system scan from the tray menu."""
        from gi.repository import GLib

        GLib.idle_add(self._do_tray_full_scan)

    def _do_tray_full_scan(self):
        """Execute the full scan from the tray."""
        win = self._app.props.active_window
        if win is None:
            return False

        self._app._view_coordinator.switch_to_view("scan", self._app.scan_view)
        if self._app.scan_view:
            self._app.scan_view._set_selected_path("/")
            self._app.scan_view._start_scan()

        return False

    def trigger_update(self):
        """Trigger database update from the tray menu."""
        from gi.repository import GLib

        GLib.idle_add(self._do_tray_update)

    def _do_tray_update(self):
        """Execute the database update from the tray."""
        win = self._app.props.active_window
        if win is None:
            return False

        self._app._view_coordinator.switch_to_view("update", self._app.update_view)
        if self._app._update_view:
            self._app._update_view._start_update()

        return False

    def trigger_quit(self):
        """Quit the application from the tray menu."""
        from gi.repository import GLib

        GLib.idle_add(self._do_tray_quit)

    def _do_tray_quit(self):
        """Execute the quit from the tray."""
        self._app.quit()
        return False

    @staticmethod
    def _is_window_visible(win) -> bool:
        """Check window visibility across Gtk widget API variants."""
        if hasattr(win, "is_visible"):
            return bool(win.is_visible())
        if hasattr(win, "get_visible"):
            return bool(win.get_visible())
        return True

    def _get_window_for_toggle(self):
        """Get a window instance even when no active window is focused."""
        win = self._app.props.active_window
        if win is not None:
            return win

        if hasattr(self._app, "get_windows"):
            windows = self._app.get_windows()
            if windows:
                return windows[0]

        return None

    def _sync_window_menu_label(self, win) -> None:
        """Update tray menu label to match current window visibility."""
        tray = getattr(self._app, "_tray_indicator", None)
        if tray is None or not hasattr(tray, "update_window_menu_label"):
            return
        tray.update_window_menu_label(visible=self._is_window_visible(win))

    def _is_tray_available(self) -> bool:
        """Check whether the indicator is registered with a desktop host."""
        tray = getattr(self._app, "_tray_indicator", None)
        return tray is not None and bool(getattr(tray, "is_available", False))

    def toggle_window(self):
        """Toggle the main window visibility from the tray."""
        win = self._get_window_for_toggle()
        if win is None:
            # Ensure a window exists (e.g. app started minimized to tray).
            self._app.activate()
            win = self._get_window_for_toggle()

        if win is None:
            logger.warning("Tray toggle requested but no application window is available")
            return

        if self._is_window_visible(win):
            if not self._is_tray_available():
                logger.warning("Tray toggle ignored because no tray host is registered")
                return
            if hasattr(win, "hide_window"):
                win.hide_window()
            else:
                win.hide()
        else:
            if hasattr(win, "show_window"):
                win.show_window()
            else:
                win.present()

        self._sync_window_menu_label(win)

    def select_profile(self, profile_id):
        """Select a scan profile from the tray menu."""
        from gi.repository import GLib

        GLib.idle_add(self._do_tray_profile_select, profile_id)

    def _do_tray_profile_select(self, profile_id):
        """Execute profile selection from the tray."""
        if self._app._scan_view is None:
            return False

        self._app._view_coordinator.switch_to_view("scan", self._app.scan_view)
        self._app.scan_view.set_selected_profile(profile_id)
        return False

    def handle_device_scan_event(self, event_type, info):
        """Handle device scan events from the device monitor."""
        logger.info(f"Device scan event: {event_type}, info: {info}")

        if event_type == "new_file":
            if self._app.settings_manager.get("auto_scan", False):
                self._app.scan_view._scan_file(info)
        elif event_type == "file_modified":
            if self._app.settings_manager.get("scan_modified", False):
                self._app.scan_view._scan_file(info)
