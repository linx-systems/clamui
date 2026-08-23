# ClamUI Application
"""
Main Adwaita Application class for ClamUI.

This module defines the ClamUIApp class, which is the central GTK4/Adwaita
application that manages the complete lifecycle of the ClamUI antivirus GUI.

Key Responsibilities:
    - Application lifecycle management (startup, activation, shutdown)
    - View management and navigation between different UI panels
    - System tray integration via TrayManager subprocess
    - Profile management integration for scan configurations
    - Settings and notification management coordination
    - GTK action setup for keyboard shortcuts and menu actions

The application uses GLib.idle_add for thread-safe UI updates when handling
callbacks from the tray indicator subprocess, ensuring all GTK operations
occur on the main thread.

Classes:
    ClamUIApp: Main Adw.Application subclass managing the application.

Example:
    from clamui.app import ClamUIApp

    app = ClamUIApp()
    exit_code = app.run(sys.argv)
"""

import logging
import os
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from . import __version__
from .app_lifecycle import AppLifecycleManager
from .core.clamav_config import (
    normalize_clamd_size_limit_units,
    parse_config,
    write_config_with_elevation,
)
from .core.clamav_detection import resolve_clamd_conf_path
from .core.i18n import _, ngettext
from .core.notification_manager import NotificationManager
from .core.settings_manager import SettingsManager
from .notification_dispatcher import NotificationDispatcher
from .profiles.models import ScanProfile
from .profiles.profile_manager import ProfileManager
from .tray_integration import TrayIntegration
from .ui.compat import open_paths_dialog, present_about_dialog
from .ui.window import MainWindow
from .view_coordinator import ViewCoordinator

logger = logging.getLogger(__name__)

LOG_PRIVACY_BANNER_DELAY_SECONDS = 1.0
LOG_PRIVACY_BANNER_MIN_VISIBLE_SECONDS = 5.0
LOG_PRIVACY_BANNER_POLL_INTERVAL_MS = 200
CLAMD_SIZE_LIMIT_MIGRATION_KEY = "clamd_size_limit_unit_migration_done"


class ClamUIApp(Adw.Application):
    """
    ClamUI GTK4/Adwaita Application.

    This is the main application class that handles application lifecycle,
    window management, and global application state.

    Main Methods (30 methods):
    - Lifecycle: __init__, app_name, version, do_activate, do_startup, do_shutdown
    - View access: scan_view, update_view, logs_view, components_view,
                   statistics_view, quarantine_view
    - View switching: _on_show_scan, _on_show_update, _on_show_logs,
                      _on_show_components, _on_show_statistics, _on_show_quarantine
    - Actions: _on_start_scan, _on_start_update, _on_scan_file, _on_scan_system,
               _on_quit, _on_preferences, _on_about
    - Tray: _on_tray_quick_scan, _on_tray_full_scan, _on_tray_update,
            _on_tray_quit, _on_tray_window_toggle, _on_tray_profile_select
    - Quick scan: _on_statistics_quick_scan, _do_tray_quick_scan
    - Settings: _get_quick_scan_profile, set_initial_scan_paths

    Collaboration:
    - AppLifecycleManager: Handles shutdown, device monitor, database dir
    - NotificationDispatcher: Manages desktop notifications
    - TrayIntegration: Handles tray menu actions and device events
    """

    def __init__(self):
        """Initialize the ClamUI application."""
        super().__init__(
            application_id="io.github.linx_systems.ClamUI",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )

        # Application metadata
        self._app_name = "ClamUI"
        self._version = __version__

        # Settings and notification management
        self._settings_manager = SettingsManager()
        self._notification_manager = NotificationManager(self._settings_manager)

        # Profile management
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "~/.config")
        config_dir = Path(xdg_config_home).expanduser() / "clamui"
        self._profile_manager = ProfileManager(config_dir)

        # View management
        self._scan_view = None
        self._update_view = None
        self._logs_view = None
        self._components_view = None
        self._statistics_view = None
        self._quarantine_view = None
        self._audit_view = None
        self._current_view = None

        # Tray indicator (initialized in do_startup if available)
        self._tray_indicator = None

        # Track first activation for start-minimized functionality
        self._first_activation = True

        # Initial scan paths from CLI
        self._initial_scan_paths: list[str] = []
        self._initial_use_virustotal: bool = False

        # Shared quarantine manager (lazy-initialized)
        self._quarantine_manager = None

        # Shared log manager (lazy-initialized, shared across views)
        self._log_manager = None

        # VirusTotal client (lazy-initialized)
        self._vt_client = None

        # Shared log privacy migration monitor
        self._startup_log_manager = None
        self._log_privacy_poll_id: int | None = None
        self._log_privacy_started_at: float | None = None
        self._log_privacy_banner_shown_at: float | None = None

        # Device monitor (initialized in do_startup)
        self._device_monitor = None

        # Scan state tracking
        self._is_scan_active = False

        # Collaborator objects
        self._lifecycle_manager = AppLifecycleManager(self)
        self._notification_dispatcher = NotificationDispatcher(self)
        self._tray_integration = TrayIntegration(self)
        self._view_coordinator = ViewCoordinator(self, logger)  # Init early for tests

    @property
    def app_name(self) -> str:
        """Get the application name."""
        return self._app_name

    @property
    def version(self) -> str:
        """Get the application version."""
        return self._version

    @property
    def notification_manager(self) -> NotificationManager:
        """Get the notification manager instance."""
        return self._notification_manager

    @property
    def settings_manager(self) -> SettingsManager:
        """Get the settings manager instance."""
        return self._settings_manager

    @property
    def profile_manager(self) -> ProfileManager:
        """Get the profile manager instance."""
        return self._profile_manager

    @property
    def tray_indicator(self):
        """Get the tray indicator instance (may be None if not available)."""
        return self._tray_indicator

    @property
    def is_scan_active(self) -> bool:
        """Check if a scan is currently in progress."""
        return self._is_scan_active

    @property
    def quarantine_manager(self):
        """
        Get the shared QuarantineManager instance, creating it lazily if needed.
        """
        if self._quarantine_manager is None:
            from .core.quarantine import QuarantineManager

            self._quarantine_manager = QuarantineManager(settings_manager=self._settings_manager)
        return self._quarantine_manager

    @property
    def log_manager(self):
        """
        Get the shared LogManager instance, creating it lazily if needed.

        Shared across views to avoid redundant path resolution and directory
        creation that occurs when each view creates its own LogManager.
        """
        if self._log_manager is None:
            from .core.log_manager import LogManager

            self._log_manager = LogManager()
        return self._log_manager

    def _preinit_quarantine_async(self) -> None:
        """
        Pre-initialize quarantine manager asynchronously in a background thread.
        """
        import threading

        def _init_thread():
            try:
                _ = self.quarantine_manager
                logger.debug("QuarantineManager pre-initialized in background")
                GLib.idle_add(self._preinit_quarantine_view)
            except Exception as e:
                logger.warning("Failed to pre-initialize QuarantineManager: %s", e)

        thread = threading.Thread(target=_init_thread, daemon=True)
        thread.start()

    def _preinit_quarantine_view(self) -> bool:
        """Pre-create the quarantine view widget after the manager is ready."""
        try:
            _ = self.quarantine_view
            logger.debug("QuarantineView pre-created in background")
        except Exception as e:
            logger.warning("Failed to pre-create QuarantineView: %s", e)
        return False

    @property
    def scan_view(self):
        """Get the scan view instance, creating it lazily if needed."""
        if self._scan_view is None:
            from .ui.scan_view import ScanView

            self._scan_view = ScanView(
                settings_manager=self._settings_manager,
                quarantine_manager=self.quarantine_manager,
                log_manager=self.log_manager,
            )
            self._scan_view.set_scan_state_changed_callback(self._on_scan_state_changed)
        return self._scan_view

    @property
    def update_view(self):
        """Get the update view instance, creating it lazily if needed."""
        if self._update_view is None:
            from .ui.update_view import UpdateView

            self._update_view = UpdateView()
        return self._update_view

    @property
    def logs_view(self):
        """Get the logs view instance, creating it lazily if needed."""
        if self._logs_view is None:
            from .ui.logs_view import LogsView

            self._logs_view = LogsView(log_manager=self.log_manager)
        return self._logs_view

    @property
    def components_view(self):
        """Get the components view instance, creating it lazily if needed."""
        if self._components_view is None:
            from .ui.components_view import ComponentsView

            self._components_view = ComponentsView(log_manager=self.log_manager)
        return self._components_view

    @property
    def statistics_view(self):
        """Get the statistics view instance, creating it lazily if needed."""
        if self._statistics_view is None:
            from .ui.statistics_view import StatisticsView

            self._statistics_view = StatisticsView(log_manager=self.log_manager)
        return self._statistics_view

    @property
    def quarantine_view(self):
        """Get the quarantine view instance, creating it lazily if needed."""
        if self._quarantine_view is None:
            from .ui.quarantine_view import QuarantineView

            self._quarantine_view = QuarantineView(
                quarantine_manager=self.quarantine_manager,
            )
        return self._quarantine_view

    @property
    def audit_view(self):
        """Get the audit view instance, creating it lazily if needed."""
        if self._audit_view is None:
            from .ui.audit_view import AuditView

            self._audit_view = AuditView(
                notification_manager=self._notification_manager,
            )
        return self._audit_view

    def do_activate(self):
        """Activate the application, creating the main window."""
        t0 = time.monotonic()
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
            logger.debug("MainWindow created in %.1f ms", (time.monotonic() - t0) * 1000)

        # Set scan view as the default content on first activation
        if self._first_activation:
            t1 = time.monotonic()
            win.set_content_view(self.scan_view)
            logger.debug("ScanView created in %.1f ms", (time.monotonic() - t1) * 1000)
            win.set_active_view("scan")
            self._current_view = "scan"

        win.present()
        logger.debug("do_activate completed in %.1f ms", (time.monotonic() - t0) * 1000)
        self._ensure_log_privacy_migration_monitor()

        if self._first_activation:
            self._first_activation = False
            start_minimized = self.settings_manager.get("start_minimized", False)
            if start_minimized:
                if self._tray_indicator:
                    win.hide()
                else:
                    logger.warning("start_minimized enabled but tray not available, showing window")

        if self._initial_scan_paths:
            self._process_initial_scan_paths()

    def _get_startup_log_manager(self):
        """Get the shared LogManager used to monitor privacy migration progress."""
        if self._startup_log_manager is None:
            self._startup_log_manager = self.log_manager
        return self._startup_log_manager

    def _format_log_privacy_status(self, processed_files: int, total_files: int) -> str:
        """Build the startup status text for persisted-log privacy migration."""
        if total_files <= 0:
            return _("Updating stored logs for privacy")

        return ngettext(
            "Updating stored log for privacy ({processed}/{total})",
            "Updating stored logs for privacy ({processed}/{total})",
            total_files,
        ).format(processed=min(processed_files, total_files), total=total_files)

    def _reset_log_privacy_banner_state(self) -> None:
        """Clear banner timing state once startup migration handling is finished."""
        self._log_privacy_started_at = None
        self._log_privacy_banner_shown_at = None

    def _show_log_privacy_progress_if_ready(self, win, status, now: float) -> None:
        """Show the progress banner only after migration has been running long enough."""
        if self._log_privacy_started_at is None:
            self._log_privacy_started_at = now

        if self._log_privacy_banner_shown_at is None:
            elapsed = now - self._log_privacy_started_at
            if elapsed < LOG_PRIVACY_BANNER_DELAY_SECONDS:
                win.set_activity_status(None)
                return

            self._log_privacy_banner_shown_at = now

        win.set_activity_status(
            self._format_log_privacy_status(
                processed_files=status.processed_files,
                total_files=status.total_files,
            )
        )

    def _should_keep_log_privacy_banner_visible(self, now: float) -> bool:
        """Keep the banner visible for a minimum dwell time once it appears."""
        if self._log_privacy_banner_shown_at is None:
            return False

        return (now - self._log_privacy_banner_shown_at) < LOG_PRIVACY_BANNER_MIN_VISIBLE_SECONDS

    def _ensure_log_privacy_migration_monitor(self) -> None:
        """Start monitoring the one-time persisted-log privacy migration."""
        win = self.props.active_window
        if win is None:
            return

        log_manager = self._get_startup_log_manager()
        log_manager.start_privacy_migration_async()
        status = log_manager.get_privacy_migration_status()
        now = time.monotonic()

        if status.is_running:
            self._show_log_privacy_progress_if_ready(win, status, now)
            if self._log_privacy_poll_id is None:
                self._log_privacy_poll_id = GLib.timeout_add(
                    LOG_PRIVACY_BANNER_POLL_INTERVAL_MS,
                    self._poll_log_privacy_migration,
                )
            return

        if self._should_keep_log_privacy_banner_visible(now):
            win.set_activity_status(
                self._format_log_privacy_status(
                    processed_files=status.processed_files,
                    total_files=status.total_files,
                ),
                show_spinner=False,
            )
            if self._log_privacy_poll_id is None:
                self._log_privacy_poll_id = GLib.timeout_add(
                    LOG_PRIVACY_BANNER_POLL_INTERVAL_MS,
                    self._poll_log_privacy_migration,
                )
            return

        win.set_activity_status(None)
        self._reset_log_privacy_banner_state()

    def _poll_log_privacy_migration(self) -> bool:
        """Refresh the main-window banner while persisted logs are being migrated."""
        win = self.props.active_window
        if win is None:
            self._log_privacy_poll_id = None
            return False

        status = self._get_startup_log_manager().get_privacy_migration_status()
        now = time.monotonic()
        if status.is_running:
            self._show_log_privacy_progress_if_ready(win, status, now)
            return True

        if self._should_keep_log_privacy_banner_visible(now):
            win.set_activity_status(
                self._format_log_privacy_status(
                    processed_files=status.processed_files,
                    total_files=status.total_files,
                ),
                show_spinner=False,
            )
            return True

        win.set_activity_status(None)
        self._reset_log_privacy_banner_state()
        self._log_privacy_poll_id = None
        return False

    def _preinit_heavy_resources(self) -> None:
        """Pre-initialize heavy resources in the background."""
        self._lifecycle_manager.preinit_heavy_resources()

    def do_command_line(self, command_line):
        """Handle command line arguments."""
        from .main import parse_arguments

        parsed_args = parse_arguments(command_line.get_arguments())
        file_paths, use_virustotal = parsed_args[:2]

        self._initial_scan_paths = file_paths
        self._initial_use_virustotal = use_virustotal

        self.activate()

        return 0

    def do_startup(self):
        """Initialize the application during startup."""
        Adw.Application.do_startup(self)

        self._configure_icon_theme()
        self._migrate_clamd_size_limits_once()

        self._lifecycle_manager.ensure_clamav_database_dir()
        self._lifecycle_manager.setup_device_monitor()

        if self._tray_indicator is None:
            self._setup_tray_indicator()

        self._setup_actions()

        self._preinit_heavy_resources()

    def _migrate_clamd_size_limits_once(self) -> None:
        """
        Repair buggy clamd size-limit values once on startup.

        Older ClamUI versions wrote MaxFileSize/MaxScanSize as bare integers
        even though the UI represented them in megabytes. This one-time
        migration rewrites positive bare integers to explicit megabyte values.
        """
        if self._settings_manager.get(CLAMD_SIZE_LIMIT_MIGRATION_KEY, False):
            return

        try:
            clamd_conf_path = resolve_clamd_conf_path(self._settings_manager)
            if not clamd_conf_path:
                logger.debug("Skipping clamd size-limit migration: no clamd.conf path found")
                return

            config, error = parse_config(clamd_conf_path)
            if error or config is None:
                logger.warning(
                    "Skipping clamd size-limit migration for %s: %s",
                    clamd_conf_path,
                    error or "parse failed",
                )
                return

            if not normalize_clamd_size_limit_units(config):
                logger.debug("No clamd size-limit migration needed for %s", clamd_conf_path)
                return

            success, error = write_config_with_elevation(config)
            if success:
                logger.info("Normalized clamd size-limit units in %s", clamd_conf_path)
            else:
                logger.warning(
                    "Failed to normalize clamd size-limit units in %s: %s",
                    clamd_conf_path,
                    error,
                )
        except Exception:
            logger.exception("Unexpected error during clamd size-limit migration")
        finally:
            self._settings_manager.set(CLAMD_SIZE_LIMIT_MIGRATION_KEY, True)

    def _configure_icon_theme(self) -> None:
        """Force a stable icon theme so icons render consistently across runtimes."""
        settings = Gtk.Settings.get_default()
        if settings is None:
            logger.debug("GTK settings unavailable; keeping current icon theme")
            return

        current_theme = settings.get_property("gtk-icon-theme-name")
        if current_theme == "Adwaita":
            return

        settings.set_property("gtk-icon-theme-name", "Adwaita")
        logger.info("Icon theme set to Adwaita (was %s)", current_theme)

    def _ensure_clamav_database_dir(self) -> None:
        """Ensure the ClamAV database directory exists."""
        self._lifecycle_manager.ensure_clamav_database_dir()

    def _setup_device_monitor(self) -> None:
        """Setup device monitor for auto-scanning."""
        self._lifecycle_manager.setup_device_monitor()

    def _on_device_scan_event(self, event_type: str, info: dict) -> None:
        """Handle device scan events from the device monitor."""
        self._tray_integration.handle_device_scan_event(event_type, info)

    def _setup_actions(self):
        """Set up application-level actions for view switching."""
        self._view_coordinator.setup_actions()

    def _setup_tray_indicator(self) -> None:
        """Setup the system tray indicator."""
        try:
            from .ui.tray_indicator import TrayIndicator

            self._tray_indicator = TrayIndicator(self)
            logger.info("Tray indicator initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize tray indicator: {e}")

    def _sync_profiles_to_tray(self, profiles: list) -> None:
        """Sync scan profiles to the tray menu."""
        if self._tray_indicator is None:
            return

        profile_data = [(p.id, p.name, p.description) for p in profiles]

        current_profile_id = None
        if self._scan_view is not None:
            current_profile = self._scan_view.get_selected_profile()
            if current_profile:
                current_profile_id = current_profile.id

        try:
            self._tray_indicator.set_profiles(profile_data, current_profile_id)
        except Exception as e:
            logger.warning(f"Failed to sync profiles to tray: {e}")

    def _get_quick_scan_profile(self) -> ScanProfile | None:
        """Get the Quick Scan profile from the profile manager."""
        return self._profile_manager.get_profile_by_name("Quick Scan")

    def _on_quit(self, action, param):
        """Handle the quit action."""
        self.quit()

    def _on_preferences(self, action, param):
        """Handle the preferences action."""
        from .ui.preferences.window import PreferencesWindow

        win = self.props.active_window
        if win:
            preferences = PreferencesWindow(
                settings_manager=self._settings_manager,
                tray_available=self._tray_indicator is not None,
                transient_for=win,
            )
            preferences.present()

    def _on_show_scan(self, action, param):
        """Handle the show-scan action."""
        win = self.props.active_window
        if win:
            win.set_content_view(self.scan_view)
            win.set_active_view("scan")
            self._current_view = "scan"

    def _on_show_update(self, action, param):
        """Handle the show-update action."""
        win = self.props.active_window
        if win:
            t0 = time.monotonic()
            view = self.update_view
            logger.debug("UpdateView ready in %.1f ms", (time.monotonic() - t0) * 1000)
            win.set_content_view(view)
            win.set_active_view("update")
            self._current_view = "update"

    def _on_show_logs(self, action, param):
        """Handle the show-logs action."""
        win = self.props.active_window
        if win:
            t0 = time.monotonic()
            view = self.logs_view
            logger.debug("LogsView ready in %.1f ms", (time.monotonic() - t0) * 1000)
            win.set_content_view(view)
            win.set_active_view("logs")
            self._current_view = "logs"

    def _on_show_components(self, action, param):
        """Handle the show-components action."""
        win = self.props.active_window
        if win:
            t0 = time.monotonic()
            view = self.components_view
            logger.debug("ComponentsView ready in %.1f ms", (time.monotonic() - t0) * 1000)
            win.set_content_view(view)
            win.set_active_view("components")
            self._current_view = "components"

    def _on_show_statistics(self, action, param):
        """Handle the show-statistics action."""
        win = self.props.active_window
        if win:
            t0 = time.monotonic()
            view = self.statistics_view
            logger.debug("StatisticsView ready in %.1f ms", (time.monotonic() - t0) * 1000)
            win.set_content_view(view)
            win.set_active_view("statistics")
            self._current_view = "statistics"

    def _on_show_audit(self, action, param):
        """Handle the show-audit action."""
        win = self.props.active_window
        if win:
            t0 = time.monotonic()
            view = self.audit_view
            logger.debug("AuditView ready in %.1f ms", (time.monotonic() - t0) * 1000)
            win.set_content_view(view)
            win.set_active_view("audit")
            self._current_view = "audit"

    def _on_start_scan(self, action, param):
        """Handle the start-scan action."""
        if self._scan_view is not None:
            self._scan_view._start_scan()

    def _on_start_update(self, action, param):
        """Handle the start-update action."""
        if self._update_view is not None:
            self._update_view._start_update()

    def _on_scan_file(self, action, param):
        """Handle the scan-file action — open file/folder chooser, then show in scan view."""
        win = self.props.active_window
        if not win:
            return

        open_paths_dialog(
            win,
            title=_("Select File or Folder"),
            on_selected=self._on_scan_file_selected,
            select_folders=True,
            multiple=False,
        )

    def _on_scan_file_selected(self, paths: list[str]):
        """Handle selected scan target paths from the file chooser."""
        if not paths:
            return  # User cancelled

        path = paths[0]

        win = self.props.active_window
        if not win:
            return

        win.set_content_view(self.scan_view)
        win.set_active_view("scan")
        self._current_view = "scan"
        self.scan_view._set_selected_path(path)

    def _on_scan_system(self, action, param):
        """Handle the scan-system action."""
        quick_scan_profile = self._get_quick_scan_profile()

        win = self.props.active_window
        if win:
            win.set_content_view(self.scan_view)
            win.set_active_view("scan")
            self._current_view = "scan"

            if quick_scan_profile:
                self.scan_view.refresh_profiles()
                self.scan_view.set_selected_profile(quick_scan_profile.id)
            else:
                home_dir = os.path.expanduser("~")
                self.scan_view._set_selected_path(home_dir)

            self.scan_view._start_scan()

    def _on_statistics_quick_scan(self):
        """Trigger a quick scan from the statistics view."""
        self._view_coordinator.trigger_statistics_quick_scan()

    def _on_show_quarantine(self, action, param):
        """Handle the show-quarantine action."""
        win = self.props.active_window
        if win:
            win.set_content_view(self.quarantine_view)
            win.set_active_view("quarantine")
            self._current_view = "quarantine"

    def _on_about(self, action, param):
        """Handle about action — show about dialog."""
        from .ui.utils import resolve_icon_name

        present_about_dialog(
            self.props.active_window,
            app_name=self._app_name,
            version=self._version,
            developer_name="ClamUI Contributors",
            license_type=Gtk.License.MIT_X11,
            comments="A graphical interface for ClamAV antivirus",
            website="https://github.com/linx-systems/clamui",
            issue_url="https://github.com/linx-systems/clamui/issues",
            icon_name=resolve_icon_name("security-high-symbolic"),
        )

    def _on_tray_quick_scan(self):
        """Trigger a quick scan from the tray."""
        GLib.idle_add(self._do_tray_quick_scan)

    def _do_tray_quick_scan(self):
        """Execute the quick scan from the tray."""
        self._tray_integration._do_tray_quick_scan()
        return False

    def _on_tray_full_scan(self):
        """Trigger a full system scan from the tray."""
        GLib.idle_add(self._do_tray_full_scan)

    def _do_tray_full_scan(self):
        """Execute the full scan from the tray."""
        self._tray_integration._do_tray_full_scan()
        return False

    def _on_tray_update(self):
        """Trigger database update from the tray."""
        GLib.idle_add(self._do_tray_update)

    def _do_tray_update(self):
        """Execute the database update from the tray."""
        self._tray_integration._do_tray_update()
        return False

    def _on_tray_quit(self):
        """Quit the application from the tray."""
        GLib.idle_add(self._do_tray_quit)

    def _do_tray_quit(self):
        """Execute the quit from the tray."""
        self._tray_integration._do_tray_quit()
        return False

    def _on_tray_window_toggle(self):
        """Toggle the main window visibility from the tray."""
        self._tray_integration.toggle_window()

    def _on_tray_profile_select(self, profile_id):
        """Select a scan profile from the tray menu."""
        GLib.idle_add(self._do_tray_profile_select, profile_id)

    def _do_tray_profile_select(self, profile_id):
        """Execute profile selection from the tray."""
        self._tray_integration._do_tray_profile_select(profile_id)

    def _on_scan_state_changed(self, is_scanning: bool, result=None) -> None:
        """Handle scan state changes."""
        self._is_scan_active = is_scanning

        if self._tray_indicator is not None:
            if is_scanning:
                # Show active scanning state and clear stale progress label.
                self._tray_indicator.update_status("scanning")
                self._tray_indicator.update_scan_progress(0)
            else:
                # Clear any scan progress indicator on completion.
                self._tray_indicator.update_scan_progress(0)

                if result is not None:
                    if result.has_threats:
                        self._tray_indicator.update_status("threat")
                    elif result.is_clean:
                        self._tray_indicator.update_status("protected")
                    else:
                        self._tray_indicator.update_status("warning")
                else:
                    self._tray_indicator.update_status("protected")

        if result is not None:
            self._notification_dispatcher.show_scan_result_notification(result)

    def do_shutdown(self):
        """Perform application shutdown."""
        self._lifecycle_manager.shutdown()
        Adw.Application.do_shutdown(self)

    def set_content_view(self, view_widget):
        """Set the main content view."""
        win = self.props.active_window
        if win:
            win.set_content_view(view_widget)

    def set_active_view(self, view_name: str):
        """Set the active view by name."""
        win = self.props.active_window
        if win:
            win.set_active_view(view_name)
            self._current_view = view_name

    def _show_window_toast(self, message: str) -> None:
        """Show a toast notification on the main window if one is available."""
        win = self.props.active_window
        if win is not None and hasattr(win, "add_toast"):
            win.add_toast(Adw.Toast.new(message))

    def set_initial_scan_paths(self, file_paths: list[str], use_virustotal: bool = False):
        """Store initial scan paths from CLI or file manager integration."""
        self._initial_scan_paths = file_paths
        self._initial_use_virustotal = use_virustotal
        self._process_initial_scan_paths()

    def _process_initial_scan_paths(self):
        """Process initial scan paths if provided."""
        if not self._initial_scan_paths:
            return

        if not self._scan_view:
            # Keep the request pending; do_activate re-processes it once the
            # scan view has been created.
            return

        if self._scan_view.is_scanning:
            # Repopulating the selection now would mutate the target list the
            # scan worker thread is using; drop the request and tell the user.
            self._initial_scan_paths = []
            self._initial_use_virustotal = False
            self._show_window_toast(
                _("A scan is already running — the new scan request was ignored")
            )
            return

        paths = self._initial_scan_paths
        self._initial_scan_paths = []

        use_vt = self._initial_use_virustotal
        self._initial_use_virustotal = False

        # Surface the scan UI so a second invocation does not start a scan
        # invisibly under whichever view is currently shown.
        self._view_coordinator.switch_to_view("scan", self.scan_view)

        if use_vt:
            # VirusTotal scans a single file per request; only the first
            # path is forwarded to the setup dialog and scan pipeline.
            if len(paths) > 1:
                ignored_count = len(paths) - 1
                self._show_window_toast(
                    ngettext(
                        "VirusTotal scans one file per request — "
                        "{count} additional selection was ignored",
                        "VirusTotal scans one file per request — "
                        "{count} additional selections were ignored",
                        ignored_count,
                    ).format(count=ignored_count)
                )
            self._scan_view._set_selected_path(paths[0])
            self._show_virustotal_setup_dialog(paths[0])
        else:
            # ClamAV scans every CLI-provided target (files and folders),
            # so populate the full selection before starting.
            self._scan_view._replace_selected_paths(paths)
            self._scan_view._start_scan()

    def _trigger_virustotal_scan(self, file_path: str, api_key: str) -> None:
        """Trigger a VirusTotal scan for the specified file."""
        import threading

        def on_scan_complete(result):
            try:
                from .core.log_manager import LogEntry, LogManager

                log_manager = LogManager()
                log_entry = LogEntry.from_virustotal_result_data(
                    vt_status=result.status.value,
                    file_path=result.file_path,
                    duration=result.duration,
                    sha256=result.sha256,
                    detections=result.detections,
                    total_engines=result.total_engines,
                    detection_details=[
                        {
                            "engine_name": d.engine_name,
                            "category": d.category,
                            "result": d.result,
                        }
                        for d in result.detection_details
                    ],
                    permalink=result.permalink,
                    error_message=result.error_message,
                )
                log_manager.save_log(log_entry)
            except Exception as e:
                logger.error(f"Failed to save VirusTotal log: {e}")

            # Show the results dialog regardless of whether logging succeeded.
            # (Previously this lived inside the try above and never ran, because
            # the log call referenced a nonexistent LogManager.add_virustotal_result
            # method that raised AttributeError.)
            self._show_virustotal_results_dialog(result)

        def scan_thread():
            try:
                from .core.virustotal import VirusTotalClient

                vt_client = VirusTotalClient(api_key)
                result = vt_client.scan_file_sync(file_path)
                GLib.idle_add(on_scan_complete, result)
            except Exception as e:
                logger.error(f"VirusTotal scan failed: {e}")

        threading.Thread(target=scan_thread, daemon=True).start()

    def _show_virustotal_setup_dialog(self, file_path: str):
        """Show the VirusTotal setup dialog."""
        from .ui.virustotal_setup_dialog import VirusTotalSetupDialog

        win = self.props.active_window
        if win:
            dialog = VirusTotalSetupDialog(win)
            dialog.connect(
                "scan-requested", lambda d, key: self._trigger_virustotal_scan(file_path, key)
            )
            dialog.present()

    def _show_virustotal_results_dialog(self, result):
        """Show the VirusTotal results dialog."""
        from .ui.virustotal_results_dialog import VirusTotalResultsDialog

        win = self.props.active_window
        if win:
            # VirusTotalResultsDialog.__init__ takes the result as its first
            # argument; the parent is set separately (mirrors the scan coordinator).
            dialog = VirusTotalResultsDialog(vt_result=result)
            dialog.set_transient_for(win)
            dialog.present()

    def _open_virustotal_website(self, url: str):
        """Open the VirusTotal website for a file."""
        try:
            from gi.repository import Gio

            Gio.AppInfo.launch_default_for_uri(url, None)
        except Exception as e:
            logger.error(f"Failed to open VirusTotal website: {e}")
