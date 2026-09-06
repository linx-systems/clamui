# ClamUI Scanner Settings Page
"""
Scanner Settings preference page for clamd.conf and scan backend settings.

This module provides the ScannerPage class which handles the UI and logic
for configuring ClamAV scanner settings and scan backend selection.
"""

import logging
import threading
from pathlib import Path

import gi

logger = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

# Check GTK version for FileDialog support (added in GTK 4.10)
try:
    _HAS_FILE_DIALOG = Gtk.get_minor_version() >= 10
except (TypeError, AttributeError):
    _HAS_FILE_DIALOG = False

from ...core.clamav_config import megabytes_to_size_value, size_value_to_megabytes
from ...core.clamav_detection import detect_clamd_conf_path
from ...core.flatpak import (
    get_clean_env,
    is_flatpak,
    is_portal_path,
    resolve_portal_path,
)
from ...core.i18n import _
from ..compat import create_entry_row, create_switch_row, create_toolbar_view
from ..utils import resolve_icon_name
from .base import (
    PreferencesPageMixin,
    create_navigation_row,
    create_spin_row,
    create_status_row,
    get_widget_active,
    get_widget_int_value,
    get_widget_text,
    populate_bool_field,
    populate_int_field,
    populate_text_field,
    styled_prefix_icon,
    update_status_row,
)


class ScannerPage(PreferencesPageMixin):
    """
    Scanner Settings preference page for scan backend and clamd.conf configuration.

    This class creates and manages the UI for configuring ClamAV scanner
    settings, including scan backend selection, file type scanning, performance,
    and logging settings.

    The page includes:
    - Scan backend selection (auto, daemon, clamscan) with auto-save
    - File location display for clamd.conf
    - File type scanning group (PE, ELF, OLE2, PDF, HTML, Archive)
    - Performance group (file size limits, recursion, max files)
    - Logging group (log file, verbose, syslog)

    Note: This class uses PreferencesPageMixin for shared utilities like
    permission indicators and file location displays.
    """

    @staticmethod
    def create_page(
        config_path: str,
        widgets_dict: dict,
        settings_manager,
        clamd_available: bool,
        parent_window,
    ) -> Adw.PreferencesPage:
        """
        Create the Scanner Settings preference page.

        Args:
            config_path: Path to the clamd.conf file
            widgets_dict: Dictionary to store widget references for later access
            settings_manager: SettingsManager instance for auto-save backend settings
            clamd_available: Whether clamd.conf exists and is available
            parent_window: Parent window for presenting dialogs

        Returns:
            Configured Adw.PreferencesPage ready to be added to preferences window
        """
        page = Adw.PreferencesPage(
            title=_("Scanner Settings"),
            icon_name=resolve_icon_name("document-properties-symbolic"),
        )

        # Create a temporary instance to use mixin methods
        temp_instance = _ScannerPageHelper()
        temp_instance._parent_window = parent_window

        # Create scan backend settings group (ClamUI settings, auto-saved)
        ScannerPage._create_scan_backend_group(
            page,
            widgets_dict,
            settings_manager,
            temp_instance,
            parent_window,
            config_path=config_path,
        )

        # Create file location group with detect/browse callbacks
        def _on_detect_clamd():
            detected = detect_clamd_conf_path()
            if detected:
                ScannerPage._apply_config_selection(
                    parent_window,
                    path_row,
                    "clamd_conf_path",
                    "_clamd_conf_path",
                    detected,
                    detected,
                    _("Detected: {path}").format(path=detected),
                )
            else:
                toast = Adw.Toast.new(_("No clamd.conf found in known locations"))
                parent_window.add_toast(toast)

        def _on_browse_clamd():
            ScannerPage._browse_for_config(
                parent_window, path_row, "clamd_conf_path", "_clamd_conf_path"
            )

        path_row = temp_instance._create_file_location_group(
            page,
            _("Configuration File"),
            config_path,
            _("clamd.conf location"),
            on_detect=_on_detect_clamd,
            on_browse=_on_browse_clamd,
        )

        if clamd_available:
            # Create file type scanning group
            ScannerPage._create_scanning_group(page, widgets_dict, temp_instance)

            # Create performance group
            ScannerPage._create_performance_group(page, widgets_dict, temp_instance)

            # Create logging group
            ScannerPage._create_logging_group(page, widgets_dict, temp_instance)
        else:
            # Show message that clamd.conf is not available
            group = Adw.PreferencesGroup()
            group.set_title(_("Configuration Status"))
            row = Adw.ActionRow()
            row.set_title(_("ClamD Configuration"))
            row.set_subtitle(_("clamd.conf not found - Scanner settings unavailable"))
            group.add(row)
            page.add(group)

        return page

    @staticmethod
    def _browse_for_config(parent_window, path_row, settings_key, attr_name):
        """
        Open a file picker to browse for a .conf config file.

        Uses Gtk.FileDialog on GTK 4.10+ with FileChooserNative fallback.

        Args:
            parent_window: The PreferencesWindow for transient parent and settings
            path_row: The Adw.ActionRow to update the subtitle on
            settings_key: Settings key to persist the selected path
            attr_name: Attribute name on parent_window to update
        """
        conf_filter = Gtk.FileFilter()
        conf_filter.set_name(_("Configuration files"))
        conf_filter.add_pattern("*.conf")

        def _apply_selection(file_path):
            if file_path:
                # In Flatpak, resolve portal paths to real host paths
                stored_path = file_path
                display_path = file_path
                if is_flatpak() and is_portal_path(file_path):
                    resolved = resolve_portal_path(file_path)
                    if not resolved:
                        parent_window.add_toast(
                            Adw.Toast.new(
                                _("Selected configuration file is not accessible from the host")
                            )
                        )
                        return
                    stored_path = resolved
                    display_path = resolved

                ScannerPage._apply_config_selection(
                    parent_window,
                    path_row,
                    settings_key,
                    attr_name,
                    stored_path,
                    display_path,
                    _("Selected: {path}").format(path=display_path),
                )

        # In Flatpak, /etc doesn't exist inside the sandbox.
        # The file chooser portal presents the host filesystem, but
        # only if we don't point it at a non-existent sandbox path.
        # Use /etc if it exists (native), otherwise let the portal decide.
        initial_path = "/etc"
        if is_flatpak() or not Path(initial_path).is_dir():
            initial_path = None

        if _HAS_FILE_DIALOG:
            dialog = Gtk.FileDialog()
            dialog.set_title(_("Select Configuration File"))
            if initial_path:
                dialog.set_initial_folder(Gio.File.new_for_path(initial_path))
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(conf_filter)
            dialog.set_filters(filters)
            dialog.set_default_filter(conf_filter)

            def _on_open_finish(dlg, result):
                try:
                    gfile = dlg.open_finish(result)
                    if gfile:
                        _apply_selection(gfile.get_path())
                except GLib.Error:
                    return  # User cancelled

            dialog.open(parent_window, None, _on_open_finish)
        else:
            dialog = Gtk.FileChooserNative.new(
                _("Select Configuration File"),
                parent_window,
                Gtk.FileChooserAction.OPEN,
                _("_Select"),
                _("_Cancel"),
            )
            dialog.add_filter(conf_filter)

            def _on_response(dlg, response):
                if response == Gtk.ResponseType.ACCEPT:
                    gfile = dlg.get_file()
                    if gfile:
                        _apply_selection(gfile.get_path())

            dialog.connect("response", _on_response)
            dialog.show()

    @staticmethod
    def _apply_config_selection(
        parent_window,
        path_row,
        settings_key,
        attr_name,
        stored_path,
        display_path,
        success_message,
    ):
        """Persist a configuration path before exposing it in the UI."""
        settings_manager = getattr(parent_window, "_settings_manager", None)
        if settings_manager and not settings_manager.set(settings_key, stored_path):
            toast = Adw.Toast.new(_("Failed to save configuration file selection"))
            parent_window.add_toast(toast)
            return False

        path_row.set_subtitle(display_path)
        setattr(parent_window, attr_name, stored_path)
        if attr_name == "_clamd_conf_path":
            parent_window._clamd_available = True
            parent_window._reload_clamd_config()
        parent_window.add_toast(Adw.Toast.new(success_message))
        return True

    @staticmethod
    def _create_scan_backend_group(
        page: Adw.PreferencesPage,
        widgets_dict: dict,
        settings_manager,
        helper,
        parent_window,
        config_path: str | None = None,
    ):
        """
        Create the Scan Backend preferences group.

        Allows users to select between different scan backends:
        - Auto: Prefer daemon if available, fallback to clamscan
        - Daemon: Use clamd daemon only (faster, requires daemon running)
        - Clamscan: Use standalone clamscan only

        In Flatpak mode, the daemon backend is available because commands
        are executed on the host via flatpak-spawn --host, where they can
        access the clamd socket normally.

        This group auto-saves changes immediately to settings.

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            settings_manager: SettingsManager for auto-saving backend selection
            helper: Helper instance with _create_permission_indicator method
            parent_window: Preferences window that displays save-failure toasts
            config_path: Resolved clamd.conf path for daemon reachability checks
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Scan Backend"))

        # Set description based on installation type
        if is_flatpak():
            group.set_description(
                _(
                    "Select how ClamUI performs scans. Daemon runs on host via flatpak-spawn. Auto-saved."
                )
            )
        else:
            group.set_description(_("Select how ClamUI performs scans. Auto-saved."))

        # Scan backend dropdown
        backend_row = Adw.ComboRow()
        backend_model = Gtk.StringList()
        backend_model.append(_("Auto (prefer daemon)"))
        backend_model.append(_("ClamAV Daemon (clamd)"))
        backend_model.append(_("Standalone Scanner (clamscan)"))
        backend_row.set_model(backend_model)
        backend_row.set_title(_("Scan Backend"))

        # Set current selection from settings
        current_backend = settings_manager.get("scan_backend", "auto")
        backend_map = {"auto": 0, "daemon": 1, "clamscan": 2}
        backend_row.set_selected(backend_map.get(current_backend, 0))

        # Set initial subtitle based on current selection
        ScannerPage._update_backend_subtitle(backend_row, backend_map.get(current_backend, 0))

        # Connect to selection changes - pass persistence context in lambda
        backend_row.connect(
            "notify::selected",
            lambda row, pspec: ScannerPage._on_backend_changed(
                row, settings_manager, parent_window
            ),
        )

        widgets_dict["backend_row"] = backend_row
        group.add(backend_row)

        # Daemon status indicator - show loading state initially
        status_row, status_icon = create_status_row(
            title=_("Daemon Status"),
            status_ok=True,
            ok_message=_("Checking daemon connection..."),
            error_message="",
        )
        status_row.set_subtitle(_("Checking daemon connection..."))
        widgets_dict["daemon_status_row"] = status_row
        widgets_dict["daemon_status_icon"] = status_icon
        group.add(status_row)

        # Start background thread to check daemon status
        thread = threading.Thread(
            target=ScannerPage._check_daemon_status_background,
            args=(status_row, status_icon, config_path),
            daemon=True,
        )
        thread.start()

        # Refresh button
        refresh_button = Gtk.Button()
        refresh_button.set_label(_("Refresh Status"))
        refresh_button.set_valign(Gtk.Align.CENTER)
        refresh_button.add_css_class("flat")
        refresh_button.connect(
            "clicked",
            lambda btn: ScannerPage._on_refresh_daemon_status(
                widgets_dict["daemon_status_row"],
                widgets_dict["daemon_status_icon"],
                config_path,
            ),
        )
        status_row.add_suffix(refresh_button)

        # Learn more row - links to documentation
        learn_more_row = create_navigation_row(
            title=_("Documentation"),
            subtitle=_("About scan backends"),
            icon_name="help-about-symbolic",
        )
        learn_more_row.connect(
            "activated",
            lambda row: ScannerPage._on_learn_more_clicked(helper._parent_window),
        )

        group.add(learn_more_row)

        page.add(group)

    @staticmethod
    def _update_backend_subtitle(row: Adw.ComboRow, selected: int):
        """
        Update the backend row subtitle based on the selected backend.

        Args:
            row: The ComboRow widget to update
            selected: Index of the selected backend (0=auto, 1=daemon, 2=clamscan)
        """
        subtitles = {
            0: _(
                "Recommended — Automatically uses daemon if available, falls back to clamscan for reliability"
            ),
            1: _(
                "Fastest — Instant startup with in-memory database, requires clamd service running"
            ),
            2: _("Most compatible — Works anywhere, loads database each scan (3-10 sec startup)"),
        }
        row.set_subtitle(subtitles.get(selected, subtitles[0]))

    @staticmethod
    def _on_backend_changed(row: Adw.ComboRow, settings_manager, parent_window):
        """
        Handle scan backend selection change.

        Auto-saves the selected backend to settings.

        Args:
            row: The ComboRow that changed
            settings_manager: SettingsManager to save the selection
            parent_window: Preferences window that displays save-failure toasts
        """
        if getattr(row, "_scanner_backend_restoring", False) is True:
            return

        backend_reverse_map = {0: "auto", 1: "daemon", 2: "clamscan"}
        backend_map = {"auto": 0, "daemon": 1, "clamscan": 2}
        selected = row.get_selected()
        backend = backend_reverse_map.get(selected, "auto")
        if settings_manager.set("scan_backend", backend):
            ScannerPage._update_backend_subtitle(row, selected)
            return

        persisted_backend = settings_manager.get("scan_backend", "auto")
        persisted_selection = backend_map.get(persisted_backend, 0)
        row._scanner_backend_restoring = True
        try:
            row.set_selected(persisted_selection)
        finally:
            row._scanner_backend_restoring = False
        ScannerPage._update_backend_subtitle(row, persisted_selection)
        parent_window.add_toast(Adw.Toast.new(_("Failed to save scan backend selection")))

    @staticmethod
    def _check_daemon_status_background(
        status_row: Adw.ActionRow,
        status_icon: Gtk.Image,
        config_path: str | None = None,
    ):
        """
        Check daemon connection status in background thread.

        Runs check_clamd_connection() and schedules UI update via GLib.idle_add.

        Args:
            status_row: The ActionRow displaying daemon status
            status_icon: The status icon widget to update
        """
        from ...core.utils import check_clamd_connection

        is_connected, message = check_clamd_connection(config_path=config_path)

        GLib.idle_add(
            ScannerPage._update_daemon_status_ui,
            status_row,
            status_icon,
            is_connected,
            message,
        )

    @staticmethod
    def _update_daemon_status_ui(
        status_row: Adw.ActionRow,
        status_icon: Gtk.Image,
        is_connected: bool,
        message: str,
    ) -> bool:
        """
        Update daemon status UI on the main thread.

        Args:
            status_row: The ActionRow displaying daemon status
            status_icon: The status icon widget to update
            is_connected: Whether the daemon is connected
            message: Status message from the connection check

        Returns:
            False to remove from GLib.idle_add
        """
        try:
            update_status_row(
                row=status_row,
                status_icon=status_icon,
                status_ok=is_connected,
                ok_message=_("Daemon available"),
                error_message=_("Not available: {message}").format(message=message),
            )
        except Exception:
            logger.debug("Daemon status widget no longer available")
        return False

    @staticmethod
    def _on_refresh_daemon_status(
        status_row: Adw.ActionRow,
        status_icon: Gtk.Image,
        config_path: str | None = None,
    ):
        """
        Refresh the daemon connection status asynchronously.

        Starts a background thread to check the daemon connection
        and updates the UI via GLib.idle_add when complete.

        Args:
            status_row: The ActionRow displaying daemon status
            status_icon: The status icon widget to update
        """
        thread = threading.Thread(
            target=ScannerPage._check_daemon_status_background,
            args=(status_row, status_icon, config_path),
            daemon=True,
        )
        thread.start()

    @staticmethod
    def _on_learn_more_clicked(parent_window):
        """
        Open the scan backends documentation file.

        Opens docs/SCAN_BACKENDS.md in the user's default application
        (typically a web browser or text editor) using xdg-open.

        Args:
            parent_window: Parent window to present error dialogs on
        """
        import subprocess

        # Get the path to the documentation file
        # From src/ui/preferences/scanner_page.py -> src/ui/preferences/ -> src/ui/ -> src/ -> project_root/
        docs_path = Path(__file__).parent.parent.parent.parent / "docs" / "SCAN_BACKENDS.md"

        # Check if file exists
        if not docs_path.exists():
            # Show error if documentation doesn't exist
            ScannerPage._show_message_dialog(
                parent_window,
                _("Documentation Not Found"),
                _(
                    "The scan backends documentation file could not be found. "
                    "It may have been moved or deleted."
                ),
            )
            return

        try:
            # Use xdg-open on Linux to open file in default application
            subprocess.Popen(
                ["xdg-open", str(docs_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=get_clean_env(),
            )
        except Exception as e:
            # Show error dialog if opening fails
            ScannerPage._show_message_dialog(
                parent_window,
                _("Error Opening Documentation"),
                _("Could not open documentation file: {error}").format(error=str(e)),
            )

    @staticmethod
    def _show_message_dialog(parent_window, title: str, message: str):
        """
        Show a simple message dialog with an OK button.

        Uses Adw.Window for compatibility with libadwaita < 1.5.

        Args:
            parent_window: Parent window for the dialog
            title: Dialog title/heading
            message: Message body text
        """
        dialog = Adw.Window()
        dialog.set_title(title)
        dialog.set_default_size(400, -1)
        dialog.set_modal(True)
        dialog.set_deletable(True)
        dialog.set_transient_for(parent_window)

        # Create content
        toolbar_view = create_toolbar_view()
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(24)

        # Message label
        label = Gtk.Label()
        label.set_text(message)
        label.set_wrap(True)
        label.set_xalign(0)
        content_box.append(label)

        # OK button
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(12)

        ok_button = Gtk.Button(label=_("OK"))
        ok_button.add_css_class("suggested-action")
        ok_button.connect("clicked", lambda btn: dialog.close())
        button_box.append(ok_button)

        content_box.append(button_box)
        toolbar_view.set_content(content_box)
        dialog.set_content(toolbar_view)

        dialog.present()

    @staticmethod
    def _create_scanning_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the File Type Scanning preferences group for clamd.conf.

        Contains settings for:
        - ScanPE: Scan PE files (Windows/DOS executables)
        - ScanELF: Scan ELF files (Unix/Linux executables)
        - ScanOLE2: Scan OLE2 files (Microsoft Office documents)
        - ScanPDF: Scan PDF files
        - ScanHTML: Scan HTML files
        - ScanArchive: Scan archive files (ZIP, RAR, etc.)

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("File Type Scanning"))
        group.set_description(_("Enable or disable scanning for specific file types"))
        group.set_header_suffix(helper._create_permission_indicator())

        # ScanPE switch
        scan_pe_row = create_switch_row("application-x-executable-symbolic")
        scan_pe_row.set_title(_("Scan PE Files"))
        scan_pe_row.set_subtitle(_("Scan Windows/DOS executable files"))
        widgets_dict["ScanPE"] = scan_pe_row
        group.add(scan_pe_row)

        # ScanELF switch
        scan_elf_row = create_switch_row("application-x-executable-symbolic")
        scan_elf_row.set_title(_("Scan ELF Files"))
        scan_elf_row.set_subtitle(_("Scan Unix/Linux executable files"))
        widgets_dict["ScanELF"] = scan_elf_row
        group.add(scan_elf_row)

        # ScanOLE2 switch
        scan_ole2_row = create_switch_row("x-office-document-symbolic")
        scan_ole2_row.set_title(_("Scan OLE2 Files"))
        scan_ole2_row.set_subtitle(_("Scan Microsoft Office documents"))
        widgets_dict["ScanOLE2"] = scan_ole2_row
        group.add(scan_ole2_row)

        # ScanPDF switch
        scan_pdf_row = create_switch_row("x-office-document-symbolic")
        scan_pdf_row.set_title(_("Scan PDF Files"))
        scan_pdf_row.set_subtitle(_("Scan PDF documents"))
        widgets_dict["ScanPDF"] = scan_pdf_row
        group.add(scan_pdf_row)

        # ScanHTML switch
        scan_html_row = create_switch_row("text-html-symbolic")
        scan_html_row.set_title(_("Scan HTML Files"))
        scan_html_row.set_subtitle(_("Scan HTML documents"))
        widgets_dict["ScanHTML"] = scan_html_row
        group.add(scan_html_row)

        # ScanArchive switch
        scan_archive_row = create_switch_row("package-x-generic-symbolic")
        scan_archive_row.set_title(_("Scan Archive Files"))
        scan_archive_row.set_subtitle(_("Scan compressed archives (ZIP, RAR, etc.)"))
        widgets_dict["ScanArchive"] = scan_archive_row
        group.add(scan_archive_row)

        page.add(group)

    @staticmethod
    def _create_performance_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the Performance preferences group for clamd.conf.

        Contains settings for:
        - MaxFileSize: Maximum file size to scan (in MB)
        - MaxScanSize: Maximum total scan size (in MB)
        - MaxRecursion: Maximum recursion depth for archives
        - MaxFiles: Maximum number of files to scan in an archive

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Performance and Limits"))
        group.set_description(_("Configure scanning limits and performance settings"))
        group.set_header_suffix(helper._create_permission_indicator())

        # MaxFileSize spin row (in MB, 0-4000)
        max_file_size_row, max_file_size_spin = create_spin_row(
            title=_("Max File Size (MB)"),
            subtitle=_("Maximum file size to scan (0 = unlimited)"),
            min_val=0,
            max_val=4000,
            step=1,
        )
        max_file_size_row.add_prefix(styled_prefix_icon("drive-harddisk-symbolic"))
        widgets_dict["MaxFileSize"] = max_file_size_spin
        group.add(max_file_size_row)

        # MaxScanSize spin row (in MB, 0-4000)
        max_scan_size_row, max_scan_size_spin = create_spin_row(
            title=_("Max Scan Size (MB)"),
            subtitle=_("Maximum total scan size (0 = unlimited)"),
            min_val=0,
            max_val=4000,
            step=1,
        )
        max_scan_size_row.add_prefix(styled_prefix_icon("drive-harddisk-symbolic"))
        widgets_dict["MaxScanSize"] = max_scan_size_spin
        group.add(max_scan_size_row)

        # MaxRecursion spin row (clamd accepts 1-100; default 17)
        max_recursion_row, max_recursion_spin = create_spin_row(
            title=_("Max Archive Recursion"),
            subtitle=_("Maximum recursion depth for archives"),
            min_val=1,
            max_val=100,
            step=1,
            initial_val=17,
        )
        max_recursion_row.add_prefix(styled_prefix_icon("folder-symbolic"))
        widgets_dict["MaxRecursion"] = max_recursion_spin
        group.add(max_recursion_row)

        # MaxFiles spin row (0-1000000)
        max_files_row, max_files_spin = create_spin_row(
            title=_("Max Files in Archive"),
            subtitle=_("Maximum number of files to scan in archive (0 = unlimited)"),
            min_val=0,
            max_val=1000000,
            step=1,
        )
        max_files_row.add_prefix(styled_prefix_icon("document-open-symbolic"))
        widgets_dict["MaxFiles"] = max_files_spin
        group.add(max_files_row)

        page.add(group)

    @staticmethod
    def _create_logging_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the Logging preferences group for clamd.conf.

        Contains settings for:
        - LogFile: Log file path
        - LogVerbose: Enable verbose logging
        - LogSyslog: Enable syslog logging

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Logging"))
        group.set_description(_("Configure logging options for the scanner"))
        group.set_header_suffix(helper._create_permission_indicator())

        # LogFile entry row
        log_file_row = create_entry_row("text-x-generic-symbolic")
        log_file_row.set_title(_("Log File Path"))
        log_file_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        log_file_row.set_show_apply_button(False)
        widgets_dict["LogFile"] = log_file_row
        group.add(log_file_row)

        # LogVerbose switch
        log_verbose_row = create_switch_row("utilities-terminal-symbolic")
        log_verbose_row.set_title(_("Verbose Logging"))
        log_verbose_row.set_subtitle(_("Enable detailed scanner logging"))
        widgets_dict["LogVerbose"] = log_verbose_row
        group.add(log_verbose_row)

        # LogSyslog switch
        log_syslog_row = create_switch_row("utilities-terminal-symbolic")
        log_syslog_row.set_title(_("Syslog Logging"))
        log_syslog_row.set_subtitle(_("Send log messages to system log"))
        widgets_dict["LogSyslog"] = log_syslog_row
        group.add(log_syslog_row)

        page.add(group)

    @staticmethod
    def populate_fields(config, widgets_dict: dict):
        """
        Populate clamd configuration fields from loaded config.

        Updates UI widgets with values from the parsed clamd.conf file.
        Only populates scanner-related fields (file type scanning, performance, logging).

        Args:
            config: Parsed config object with has_key() and get_value() methods
            widgets_dict: Dictionary containing widget references
        """
        if not config:
            return

        # Populate file type scanning switches. ClamAV enables all of these
        # by default when the key is absent from clamd.conf, so a missing key
        # must show as ON — defaulting to off would write "ScanPE no" etc. on
        # the next save and silently disable executable/document scanning.
        for key in (
            "ScanPE",
            "ScanELF",
            "ScanOLE2",
            "ScanPDF",
            "ScanHTML",
            "ScanArchive",
        ):
            populate_bool_field(config, widgets_dict, key, default=True)

        # Populate performance settings
        for key in ("MaxFileSize", "MaxScanSize"):
            if config.has_key(key):
                value_mb = size_value_to_megabytes(config.get_value(key))
                if value_mb is not None:
                    widgets_dict[key].set_value(value_mb)

        for key in ("MaxRecursion", "MaxFiles"):
            populate_int_field(config, widgets_dict, key)

        # Populate logging settings
        populate_text_field(config, widgets_dict, "LogFile")
        populate_bool_field(config, widgets_dict, "LogVerbose")
        populate_bool_field(config, widgets_dict, "LogSyslog")

    @staticmethod
    def collect_data(widgets_dict: dict, clamd_available: bool) -> dict:
        """
        Collect clamd configuration data from form widgets.

        Collects scanner-related settings (file type scanning, performance, logging).
        Does not include scan backend settings as those are auto-saved.

        Args:
            widgets_dict: Dictionary containing widget references
            clamd_available: Whether clamd.conf is available

        Returns:
            Dictionary of configuration key-value pairs to save
        """
        if not clamd_available:
            return {}

        updates = {}

        # Collect file type scanning settings
        for key in ("ScanPE", "ScanELF", "ScanOLE2", "ScanPDF", "ScanHTML", "ScanArchive"):
            value = get_widget_active(widgets_dict, key)
            if value is not None:
                updates[key] = "yes" if value else "no"

        # Collect performance settings
        for key in ("MaxFileSize", "MaxScanSize"):
            value = get_widget_int_value(widgets_dict, key)
            if value is not None:
                updates[key] = megabytes_to_size_value(value)

        for key in ("MaxRecursion", "MaxFiles"):
            value = get_widget_int_value(widgets_dict, key)
            if value is not None:
                updates[key] = str(value)

        # Collect logging settings
        log_file = get_widget_text(widgets_dict, "LogFile")
        if log_file:
            updates["LogFile"] = log_file

        for key in ("LogVerbose", "LogSyslog"):
            value = get_widget_active(widgets_dict, key)
            if value is not None:
                updates[key] = "yes" if value else "no"

        return updates


class _ScannerPageHelper(PreferencesPageMixin):
    """
    Helper class to provide access to mixin methods for static context.

    This is a workaround to allow static methods in ScannerPage to use
    the mixin utilities (like _create_permission_indicator). In the future,
    when ScannerPage is integrated into the full PreferencesWindow, this
    helper won't be needed.
    """

    def __init__(self):
        """Initialize helper with a parent window reference."""
        self._parent_window = None
