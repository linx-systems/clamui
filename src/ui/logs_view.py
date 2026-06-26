# ClamUI Logs View
"""
Logs interface component for ClamUI with historical logs list and daemon logs section.
"""

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk

from ..core.i18n import _
from ..core.log_manager import DaemonStatus, LogEntry, LogManager
from ..core.statistics_calculator import StatisticsCalculator
from .clipboard_helper import ClipboardHelper
from .compat import create_toolbar_view, safe_add_suffix, safe_add_titled_with_icon
from .file_export import CSV_FILTER, JSON_FILTER, TEXT_FILTER, FileExportHelper
from .fullscreen_dialog import FullscreenLogDialog
from .pagination import PaginatedListController
from .utils import add_row_icon, resolve_icon_name
from .view_helpers import EmptyStateConfig, create_empty_state, create_loading_row


class ClearLogsDialog(Adw.Window):
    """
    Confirmation dialog for clearing all logs.

    Uses Adw.Window instead of Adw.MessageDialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        def on_response(dialog, response):
            if response == "clear":
                # Clear the logs
                pass

        dialog = ClearLogsDialog()
        dialog.connect("response", on_response)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    __gsignals__ = {"response": (GObject.SignalFlags.RUN_LAST, None, (str,))}

    def __init__(self, **kwargs):
        """Initialize the clear logs confirmation dialog."""
        super().__init__(**kwargs)

        self._heading = _("Clear All Logs?")
        self._body = _(
            "This will permanently delete all historical logs. This action cannot be undone."
        )

        self.set_title(self._heading)
        self.set_default_size(400, -1)  # Natural height

        # Configure as modal dialog
        self.set_modal(True)
        self.set_deletable(True)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        # Create main container with toolbar view for header bar
        toolbar_view = create_toolbar_view()

        # Create header bar
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Main content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(24)

        # Warning icon
        warning_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
        warning_icon.set_pixel_size(48)
        warning_icon.add_css_class("warning")
        warning_icon.set_halign(Gtk.Align.CENTER)
        content_box.append(warning_icon)

        # Body text
        body_label = Gtk.Label()
        body_label.set_text(self._body)
        body_label.set_wrap(True)
        body_label.set_xalign(0.5)
        body_label.set_justify(Gtk.Justification.CENTER)
        content_box.append(body_label)

        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(12)

        # Cancel button
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(cancel_button)

        # Clear All button
        clear_button = Gtk.Button(label=_("Clear All"))
        clear_button.add_css_class("destructive-action")
        clear_button.connect("clicked", self._on_clear_clicked)
        button_box.append(clear_button)

        content_box.append(button_box)

        toolbar_view.set_content(content_box)
        self.set_content(toolbar_view)

    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self.emit("response", "cancel")
        self.close()

    def _on_clear_clicked(self, button):
        """Handle clear button click."""
        self.emit("response", "clear")
        self.close()

    def get_heading(self) -> str:
        """Get the dialog heading/title (for test compatibility)."""
        return self._heading

    def get_body(self) -> str:
        """Get the dialog body text (for test compatibility)."""
        return self._body


class LogsView(Gtk.Box):
    """
    Logs interface component for ClamUI.

    Provides the logs viewing interface with:
    - Historical logs list (scan and update operations)
    - Log detail view
    - Daemon status and live logs
    - Clear logs functionality

    Uses a tabbed interface to separate historical logs from daemon logs.
    """

    def __init__(self, log_manager=None, **kwargs):
        """
        Initialize the logs view.

        Args:
            log_manager: Optional shared LogManager instance. If not provided,
                a new one is created.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)

        # Use shared log manager if provided, otherwise create own
        self._log_manager = log_manager if log_manager is not None else LogManager()

        # Initialize statistics calculator with shared log manager
        self._statistics_calculator = StatisticsCalculator(log_manager=self._log_manager)

        # Currently selected log entry
        self._selected_log: LogEntry | None = None

        # Daemon log refresh timeout ID
        self._daemon_refresh_id: int | None = None
        # Guards against stacking daemon-log reads behind the 3s periodic tick.
        # Touched only on the GTK main loop (timer callback sets it, the idle_add
        # applier clears it), so no cross-thread synchronization is required.
        self._daemon_refresh_in_flight = False

        # Loading state for historical logs
        self._is_loading = False

        # Keep _all_log_entries for external access
        self._all_log_entries: list[LogEntry] = []

        # Set up the UI (this creates self._logs_listbox and self._logs_scrolled)
        self._setup_ui()

        # Track whether initial data load has happened
        self._initial_load_done = False

        # Create pagination controller
        self._pagination = PaginatedListController(
            listbox=self._logs_listbox,
            scrolled_window=self._logs_scrolled,
            row_factory=self._create_log_row,
        )

        # Defer data loading until view becomes visible
        self.connect("map", self._on_first_map)

    def _setup_ui(self):
        """Set up the logs view UI layout with tabbed interface."""
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_spacing(0)

        # Create view stack for tab content
        self._view_stack = Adw.ViewStack()
        self._view_stack.set_vexpand(True)
        self._view_stack.set_hexpand(True)

        # Create view switcher for tab navigation
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self._view_stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        switcher.set_margin_bottom(12)

        self.append(switcher)
        self.append(self._view_stack)

        # Create the historical logs tab (with list and details)
        self._create_historical_logs_tab()

        # Create the daemon logs tab
        self._create_daemon_logs_tab()

    def _create_historical_logs_tab(self):
        """Create the historical logs tab containing log list and details."""
        # Container for historical logs tab content
        # No outer ScrolledWindow - we want the detail section to expand
        tab_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tab_content.set_spacing(18)
        tab_content.set_margin_top(12)
        tab_content.set_margin_bottom(12)
        tab_content.set_margin_start(12)
        tab_content.set_margin_end(12)
        tab_content.set_vexpand(True)

        # Create the historical logs section (fixed height)
        self._create_historical_logs_section(tab_content)

        # Create the log detail section (expands to fill remaining space)
        self._create_log_detail_section(tab_content)

        # Add to view stack
        safe_add_titled_with_icon(
            self._view_stack,
            tab_content,
            "historical",
            _("Historical Logs"),
            resolve_icon_name("document-open-recent-symbolic"),
        )

    def _create_daemon_logs_tab(self):
        """Create the daemon logs tab."""
        # Container for daemon logs tab content
        tab_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tab_content.set_spacing(18)
        tab_content.set_margin_top(12)
        tab_content.set_margin_bottom(12)
        tab_content.set_margin_start(12)
        tab_content.set_margin_end(12)
        tab_content.set_vexpand(True)

        # Create the daemon logs section
        self._create_daemon_logs_section(tab_content)

        # Add to view stack
        safe_add_titled_with_icon(
            self._view_stack,
            tab_content,
            "daemon",
            _("ClamAV Daemon"),
            resolve_icon_name("utilities-terminal-symbolic"),
        )

    def _create_historical_logs_section(self, parent: Gtk.Box):
        """
        Create the historical logs list section.

        Args:
            parent: The parent container to add the section to
        """
        # Historical logs group
        logs_group = Adw.PreferencesGroup()
        logs_group.set_title(_("Historical Logs"))
        logs_group.set_description(_("Previous scan and update operations"))

        # Header box with Clear button
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_halign(Gtk.Align.END)

        # Clear logs button
        clear_button = Gtk.Button()
        clear_button.set_label(_("Clear All"))
        clear_button.add_css_class("flat")
        clear_button.connect("clicked", self._on_clear_logs_clicked)
        self._clear_button = clear_button

        # Export to JSON button
        export_json_button = Gtk.Button()
        export_json_button.set_icon_name(resolve_icon_name("document-save-symbolic"))
        export_json_button.set_tooltip_text(_("Export all logs to JSON"))
        export_json_button.add_css_class("flat")
        export_json_button.set_sensitive(False)  # Disabled until logs are loaded
        export_json_button.connect("clicked", self._on_export_all_json_clicked)
        self._export_all_json_button = export_json_button

        # Export to CSV button
        export_csv_button = Gtk.Button()
        export_csv_button.set_icon_name(resolve_icon_name("x-office-spreadsheet-symbolic"))
        export_csv_button.set_tooltip_text(_("Export all logs to CSV"))
        export_csv_button.add_css_class("flat")
        export_csv_button.set_sensitive(False)  # Disabled until logs are loaded
        export_csv_button.connect("clicked", self._on_export_all_csv_clicked)
        self._export_all_csv_button = export_csv_button

        # Refresh button
        refresh_button = Gtk.Button()
        refresh_button.set_icon_name(resolve_icon_name("view-refresh-symbolic"))
        refresh_button.set_tooltip_text(_("Refresh logs"))
        refresh_button.add_css_class("flat")
        refresh_button.connect("clicked", self._on_refresh_clicked)
        self._refresh_button = refresh_button

        # Loading spinner (hidden by default)
        self._logs_spinner = Gtk.Spinner()
        self._logs_spinner.set_visible(False)

        header_box.append(self._logs_spinner)
        header_box.append(refresh_button)
        header_box.append(export_csv_button)
        header_box.append(export_json_button)
        header_box.append(clear_button)
        logs_group.set_header_suffix(header_box)

        # Scrolled window for log entries
        self._logs_scrolled = Gtk.ScrolledWindow()
        self._logs_scrolled.set_min_content_height(150)
        self._logs_scrolled.set_max_content_height(250)
        self._logs_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._logs_scrolled.add_css_class("card")

        # ListBox for log entries
        self._logs_listbox = Gtk.ListBox()
        self._logs_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._logs_listbox.add_css_class("boxed-list")
        self._logs_listbox.connect("row-selected", self._on_log_selected)
        self._logs_listbox.set_placeholder(self._create_empty_state())

        self._logs_scrolled.set_child(self._logs_listbox)

        logs_group.add(self._logs_scrolled)
        parent.append(logs_group)

    def _create_empty_state(self) -> Gtk.Widget:
        """Create the empty state placeholder widget."""
        return create_empty_state(
            EmptyStateConfig(
                icon_name="document-open-recent-symbolic",
                title=_("No logs yet"),
                subtitle=_("Logs from scans and updates will appear here"),
            )
        )

    def _create_loading_state(self) -> Gtk.ListBoxRow:
        """
        Create a loading state placeholder row widget.

        Returns:
            Gtk.ListBoxRow containing spinner and loading text
        """
        return create_loading_row(_("Loading logs..."))

    def _create_log_detail_section(self, parent: Gtk.Box):
        """
        Create the log detail display section.

        Args:
            parent: The parent container to add the section to
        """
        # Log detail group
        detail_group = Adw.PreferencesGroup()
        detail_group.set_title(_("Log Details"))
        detail_group.set_description(_("Select a log entry above to view details"))
        self._detail_group = detail_group

        # Header box with copy, export, and fullscreen buttons
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_halign(Gtk.Align.END)
        header_box.set_spacing(6)

        # Copy to Clipboard button
        copy_button = Gtk.Button()
        copy_button.set_icon_name(resolve_icon_name("edit-copy-symbolic"))
        copy_button.set_tooltip_text(_("Copy to clipboard"))
        copy_button.add_css_class("flat")
        copy_button.set_sensitive(False)  # Disabled until log selected
        copy_button.connect("clicked", self._on_copy_detail_clicked)
        self._copy_detail_button = copy_button

        # Export to Text button
        export_text_button = Gtk.Button()
        export_text_button.set_icon_name(resolve_icon_name("document-save-symbolic"))
        export_text_button.set_tooltip_text(_("Export to text file"))
        export_text_button.add_css_class("flat")
        export_text_button.set_sensitive(False)  # Disabled until log selected
        export_text_button.connect("clicked", self._on_export_detail_text_clicked)
        self._export_detail_text_button = export_text_button

        # Export to CSV button
        export_csv_button = Gtk.Button()
        export_csv_button.set_icon_name(resolve_icon_name("x-office-spreadsheet-symbolic"))
        export_csv_button.set_tooltip_text(_("Export to CSV file"))
        export_csv_button.add_css_class("flat")
        export_csv_button.set_sensitive(False)  # Disabled until log selected
        export_csv_button.connect("clicked", self._on_export_detail_csv_clicked)
        self._export_detail_csv_button = export_csv_button

        # Export to JSON button
        export_json_button = Gtk.Button()
        export_json_button.set_icon_name(resolve_icon_name("document-save-symbolic"))
        export_json_button.set_tooltip_text(_("Export to JSON file"))
        export_json_button.add_css_class("flat")
        export_json_button.set_sensitive(False)  # Disabled until log selected
        export_json_button.connect("clicked", self._on_export_detail_json_clicked)
        self._export_detail_json_button = export_json_button

        # Fullscreen button
        fullscreen_button = Gtk.Button()
        fullscreen_button.set_icon_name(resolve_icon_name("view-fullscreen-symbolic"))
        fullscreen_button.set_tooltip_text(_("View fullscreen"))
        fullscreen_button.add_css_class("flat")
        fullscreen_button.connect("clicked", self._on_fullscreen_detail_clicked)
        self._fullscreen_detail_button = fullscreen_button

        header_box.append(copy_button)
        header_box.append(export_text_button)
        header_box.append(export_csv_button)
        header_box.append(export_json_button)
        header_box.append(fullscreen_button)
        detail_group.set_header_suffix(header_box)

        # Detail container - expands to fill remaining vertical space
        detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        detail_box.set_spacing(12)
        detail_box.set_vexpand(True)

        # Log detail text view in a scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(150)
        scrolled.set_vexpand(True)
        scrolled.add_css_class("card")

        self._detail_text = Gtk.TextView()
        self._detail_text.set_editable(False)
        self._detail_text.set_cursor_visible(False)
        self._detail_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._detail_text.set_left_margin(12)
        self._detail_text.set_right_margin(12)
        self._detail_text.set_top_margin(12)
        self._detail_text.set_bottom_margin(12)
        self._detail_text.add_css_class("monospace")

        # Set placeholder text
        buffer = self._detail_text.get_buffer()
        buffer.set_text(_("Select a log entry to view details."))

        scrolled.set_child(self._detail_text)
        detail_box.append(scrolled)

        detail_group.add(detail_box)
        parent.append(detail_group)

    def _create_daemon_logs_section(self, parent: Gtk.Box):
        """
        Create the daemon logs section.

        Args:
            parent: The parent container to add the section to
        """
        # Daemon logs group
        daemon_group = Adw.PreferencesGroup()
        daemon_group.set_title(_("ClamAV Daemon Logs"))
        daemon_group.set_description(_("Live logs from the clamd daemon"))
        self._daemon_group = daemon_group

        # Header box with export and fullscreen buttons
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_halign(Gtk.Align.END)

        # Export button
        export_button = Gtk.Button()
        export_button.set_icon_name(resolve_icon_name("document-save-symbolic"))
        export_button.set_tooltip_text(_("Export daemon logs to file"))
        export_button.add_css_class("flat")
        export_button.set_sensitive(False)  # Disabled until logs are loaded
        export_button.connect("clicked", self._on_export_daemon_logs_clicked)
        self._export_daemon_button = export_button

        # Fullscreen button
        fullscreen_button = Gtk.Button()
        fullscreen_button.set_icon_name(resolve_icon_name("view-fullscreen-symbolic"))
        fullscreen_button.set_tooltip_text(_("View fullscreen"))
        fullscreen_button.add_css_class("flat")
        fullscreen_button.connect("clicked", self._on_fullscreen_daemon_clicked)
        self._fullscreen_daemon_button = fullscreen_button

        header_box.append(export_button)
        header_box.append(fullscreen_button)
        daemon_group.set_header_suffix(header_box)

        # Status row
        self._daemon_status_row = Adw.ActionRow()
        self._daemon_status_row.set_title(_("Daemon Status"))
        self._daemon_status_row.set_subtitle(_("Checking..."))
        self._daemon_status_icon = add_row_icon(self._daemon_status_row, "dialog-question-symbolic")

        # Refresh toggle button for live updates
        self._live_toggle = Gtk.ToggleButton()
        self._live_toggle.set_icon_name(resolve_icon_name("media-playback-start-symbolic"))
        self._live_toggle.set_tooltip_text(_("Start live log updates"))
        self._live_toggle.set_valign(Gtk.Align.CENTER)
        self._live_toggle.connect("toggled", self._on_live_toggle)
        safe_add_suffix(self._daemon_status_row, self._live_toggle)

        daemon_group.add(self._daemon_status_row)

        # Daemon log text view in a scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(300)
        scrolled.set_vexpand(True)
        scrolled.add_css_class("card")
        scrolled.set_margin_top(12)

        self._daemon_text = Gtk.TextView()
        self._daemon_text.set_editable(False)
        self._daemon_text.set_cursor_visible(False)
        self._daemon_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._daemon_text.set_left_margin(12)
        self._daemon_text.set_right_margin(12)
        self._daemon_text.set_top_margin(12)
        self._daemon_text.set_bottom_margin(12)
        self._daemon_text.add_css_class("monospace")

        # Set placeholder text
        buffer = self._daemon_text.get_buffer()
        buffer.set_text(
            _("Daemon logs will appear here.")
            + "\n\n"
            + _("Click the play button to start live updates.")
        )

        scrolled.set_child(self._daemon_text)

        daemon_group.add(scrolled)
        parent.append(daemon_group)

        # Check daemon status on load
        GLib.idle_add(self._check_daemon_status)

    def _on_first_map(self, widget):
        """Load log data when the view first becomes visible."""
        if not self._initial_load_done:
            self._initial_load_done = True
            self._load_logs_async()

    def _load_logs_async(self):
        """
        Load and display historical logs asynchronously.

        This method is safe to call multiple times - it will prevent
        duplicate requests via the _is_loading flag (debouncing).

        Note: Row clearing is deferred to _on_logs_loaded() callback to avoid
        blocking the UI. The rows are cleared right before adding new ones.
        """
        # Prevent duplicate load requests
        if self._is_loading:
            return

        # Set loading state - let callback handle empty case
        self._set_loading_state(True)

        # Get logs from log manager asynchronously
        # Note: Rows are cleared in the callback, not here, to avoid
        # blocking the main thread with synchronous operations
        self._log_manager.get_logs_async(callback=self._on_logs_loaded, limit=100)

    def _on_logs_loaded(self, logs: list) -> bool:
        """
        Handle completion of async log loading.

        This callback is invoked on the main GTK thread when async loading
        completes. It populates the listbox with the loaded logs using pagination.

        Args:
            logs: List of LogEntry objects from the log manager

        Returns:
            False to prevent GLib.idle_add from repeating
        """
        # Wrap all UI operations in try/finally to ensure loading state is always reset
        try:
            # Store logs in _all_log_entries for external access
            self._all_log_entries = logs

            # Use pagination controller to display logs
            self._pagination.set_entries(logs, entries_label="logs")

            # Handle empty logs - placeholder will be shown automatically
            # by GTK ListBox since we set it with set_placeholder()
            if not logs:
                # Ensure clear and export buttons are disabled for empty state
                self._clear_button.set_sensitive(False)
                self._export_all_csv_button.set_sensitive(False)
                self._export_all_json_button.set_sensitive(False)
                return False

            # Update clear and export button sensitivity based on actual rendered rows
            has_logs = self._logs_listbox.get_row_at_index(0) is not None
            self._clear_button.set_sensitive(has_logs)
            self._export_all_csv_button.set_sensitive(has_logs)
            self._export_all_json_button.set_sensitive(has_logs)
        finally:
            # ALWAYS reset loading state to prevent stuck "Loading logs" forever
            self._set_loading_state(False)

        return False  # Don't repeat

    # Backward compatibility properties and methods for tests
    @property
    def _displayed_log_count(self) -> int:
        """Get the current displayed count from pagination controller (backward compatibility)."""
        return self._pagination.displayed_count if hasattr(self, "_pagination") else 0

    @_displayed_log_count.setter
    def _displayed_log_count(self, value: int):
        """Set the displayed count on pagination controller (backward compatibility)."""
        if hasattr(self, "_pagination"):
            self._pagination._displayed_count = value

    @property
    def _load_more_row(self):
        """Get the load more row from pagination controller (backward compatibility)."""
        return self._pagination.load_more_row if hasattr(self, "_pagination") else None

    @_load_more_row.setter
    def _load_more_row(self, value):
        """Set the load more row on pagination controller (backward compatibility)."""
        if hasattr(self, "_pagination"):
            self._pagination._load_more_row = value

    def _display_log_batch(self, start_index: int, count: int):
        """Display a batch of log rows (backward compatibility - delegates to pagination controller)."""
        if hasattr(self, "_pagination"):
            self._pagination.display_batch(start_index, count)

    def _add_load_more_button(self):
        """Add load more button (backward compatibility - delegates to pagination controller)."""
        if hasattr(self, "_pagination"):
            self._pagination.add_load_more_button(entries_label="logs")

    def _on_load_more_logs_clicked(self, button):
        """Handle load more button click (backward compatibility - delegates to pagination controller)."""
        if hasattr(self, "_pagination"):
            self._pagination.load_more(entries_label="logs")

    def _on_show_all_logs_clicked(self, button):
        """Handle show all button click (backward compatibility - delegates to pagination controller)."""
        if hasattr(self, "_pagination"):
            self._pagination.show_all()

    def _create_log_row(self, entry: LogEntry) -> Adw.ActionRow:
        """
        Create a list row for a log entry.

        Args:
            entry: The LogEntry to create a row for

        Returns:
            Adw.ActionRow widget
        """
        row = Adw.ActionRow()

        # Set icon based on log type
        if entry.type == "scan":
            add_row_icon(row, "folder-symbolic")
        else:  # update
            add_row_icon(row, "software-update-available-symbolic")

        # Set title with summary
        row.set_title(GLib.markup_escape_text(entry.summary))

        # Set subtitle with timestamp and status
        try:
            from datetime import datetime

            timestamp = datetime.fromisoformat(entry.timestamp)
            time_str = timestamp.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            time_str = entry.timestamp

        subtitle = f"{time_str} \u2022 {entry.status}"
        if entry.path:
            # Truncate long paths
            path_display = entry.path
            if len(path_display) > 40:
                path_display = "..." + path_display[-37:]
            subtitle += f" \u2022 {path_display}"
        row.set_subtitle(GLib.markup_escape_text(subtitle))

        # Add status indicator
        status_icon = Gtk.Image()
        if entry.status in ("clean", "success", "up_to_date"):
            status_icon.set_from_icon_name(resolve_icon_name("object-select-symbolic"))
            status_icon.add_css_class("success")
        elif entry.status in ("infected", "error"):
            status_icon.set_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
            status_icon.add_css_class("error")
        else:
            status_icon.set_from_icon_name(resolve_icon_name("dialog-information-symbolic"))
        status_icon.set_valign(Gtk.Align.CENTER)
        safe_add_suffix(row, status_icon)

        # Store entry ID in row for later retrieval
        row.set_name(entry.id)

        return row

    def _on_log_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None):
        """Handle log entry selection."""
        if row is None:
            self._selected_log = None
            buffer = self._detail_text.get_buffer()
            buffer.set_text(_("Select a log entry to view details."))
            # Disable copy/export buttons when no log is selected
            self._copy_detail_button.set_sensitive(False)
            self._export_detail_text_button.set_sensitive(False)
            self._export_detail_csv_button.set_sensitive(False)
            self._export_detail_json_button.set_sensitive(False)
            return

        log_id = row.get_name()
        entry = self._log_manager.get_log_by_id(log_id)

        if entry is None:
            return

        self._selected_log = entry
        self._display_log_details(entry)
        # Enable copy/export buttons when a log is selected
        self._copy_detail_button.set_sensitive(True)
        self._export_detail_text_button.set_sensitive(True)
        self._export_detail_csv_button.set_sensitive(True)
        self._export_detail_json_button.set_sensitive(True)

    def _display_log_details(self, entry: LogEntry):
        """
        Display the full details of a log entry.

        Args:
            entry: The LogEntry to display
        """
        lines = []

        # Header
        if entry.type == "scan":
            lines.append(_("SCAN LOG"))
        else:
            lines.append(_("UPDATE LOG"))

        lines.append("=" * 50)
        lines.append("")

        # Metadata
        lines.append(_("ID: {id}").format(id=entry.id))
        lines.append(_("Timestamp: {timestamp}").format(timestamp=entry.timestamp))
        lines.append(_("Type: {type}").format(type=entry.type))
        lines.append(_("Status: {status}").format(status=entry.status))

        if entry.path:
            lines.append(_("Path: {path}").format(path=entry.path))

        if entry.duration > 0:
            lines.append(_("Duration: {duration:.2f} seconds").format(duration=entry.duration))

        lines.append("")

        # Statistics Summary (for scan logs only)
        if entry.type == "scan":
            stats = self._statistics_calculator.extract_entry_statistics(entry)

            # Only show statistics section if we have meaningful data
            if (
                stats["files_scanned"] > 0
                or stats["directories_scanned"] > 0
                or stats["duration"] > 0
            ):
                lines.append(_("Statistics Summary:"))
                lines.append("-" * 50)

                if stats["files_scanned"] > 0:
                    lines.append(
                        _("  Files Scanned: {count}").format(
                            count="{:,}".format(stats["files_scanned"])
                        )
                    )

                if stats["directories_scanned"] > 0:
                    lines.append(
                        _("  Directories Scanned: {count}").format(
                            count="{:,}".format(stats["directories_scanned"])
                        )
                    )

                if stats["duration"] > 0:
                    # Format duration nicely
                    duration = stats["duration"]
                    if duration < 60:
                        duration_str = _("{seconds:.2f} seconds").format(seconds=duration)
                    elif duration < 3600:
                        minutes = int(duration // 60)
                        seconds = duration % 60
                        duration_str = _("{minutes}m {seconds:.0f}s").format(
                            minutes=minutes, seconds=seconds
                        )
                    else:
                        hours = int(duration // 3600)
                        minutes = int((duration % 3600) // 60)
                        duration_str = _("{hours}h {minutes}m").format(hours=hours, minutes=minutes)
                    lines.append(_("  Duration: {duration}").format(duration=duration_str))

                lines.append("")

        # Summary
        lines.append(_("Summary:"))
        lines.append(f"  {entry.summary}")
        lines.append("")

        # Full details
        if entry.details:
            lines.append("-" * 50)
            lines.append(_("Full Output:"))
            lines.append("-" * 50)
            lines.append(entry.details)

        # Update the text view
        buffer = self._detail_text.get_buffer()
        buffer.set_text("\n".join(lines))

    def _on_fullscreen_detail_clicked(self, button: Gtk.Button):
        """Handle fullscreen button click for log details."""
        # Get current content from detail text view
        buffer = self._detail_text.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        content = buffer.get_text(start, end, False)

        # Create and present the fullscreen dialog
        dialog = FullscreenLogDialog(title=_("Log Details"), content=content)
        dialog.set_transient_for(self.get_root())
        dialog.present()

    def _on_copy_detail_clicked(self, button: Gtk.Button):
        """
        Handle copy to clipboard button click for log details.

        Copies the currently displayed log details to the system clipboard.
        Uses ClipboardHelper for size-aware copying with appropriate feedback.
        """
        if self._selected_log is None:
            return

        # Get current content from detail text view
        buffer = self._detail_text.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        content = buffer.get_text(start, end, False)

        # Copy with size-aware feedback (redirects to export for large content)
        helper = ClipboardHelper(parent_widget=self)
        helper.copy_with_feedback(
            text=content,
            success_message="Log details copied to clipboard",
            error_message="Failed to copy to clipboard",
            on_too_large=lambda: self._on_export_detail_text_clicked(button),
        )

    def _on_export_detail_text_clicked(self, button: Gtk.Button):
        """
        Handle export to text file button click for log details.

        Opens a file save dialog to let the user choose a location,
        then writes the log details to a text file.
        """
        if self._selected_log is None:
            return

        helper = FileExportHelper(
            parent_widget=self,
            dialog_title="Export Log Details",
            filename_prefix="clamui_log",
            file_filter=TEXT_FILTER,
            content_generator=self._get_detail_text_content,
        )
        helper.show_save_dialog()

    def _on_export_detail_csv_clicked(self, button: Gtk.Button):
        """
        Handle export to CSV file button click for log details.

        Opens a file save dialog to let the user choose a location,
        then writes the log entry in CSV format.
        """
        if self._selected_log is None:
            return

        helper = FileExportHelper(
            parent_widget=self,
            dialog_title="Export Log Details as CSV",
            filename_prefix="clamui_log",
            file_filter=CSV_FILTER,
            content_generator=lambda: self._format_log_entry_as_csv(self._selected_log),
        )
        helper.show_save_dialog()

    def _on_export_detail_json_clicked(self, button: Gtk.Button):
        """
        Handle export to JSON file button click for log details.

        Opens a file save dialog to let the user choose a location,
        then writes the log entry in JSON format.
        """
        if self._selected_log is None:
            return

        helper = FileExportHelper(
            parent_widget=self,
            dialog_title="Export Log Details as JSON",
            filename_prefix="clamui_log",
            file_filter=JSON_FILTER,
            content_generator=lambda: self._format_log_entry_as_json(self._selected_log),
        )
        helper.show_save_dialog()

    def _format_log_entry_as_csv(self, entry: LogEntry) -> str:
        """
        Format a log entry as CSV with proper escaping.

        CSV schema: timestamp, type, status, path, summary, duration

        Args:
            entry: The LogEntry to format

        Returns:
            CSV formatted string
        """
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Write header row
        writer.writerow(["timestamp", "type", "status", "path", "summary", "duration"])

        # Write data row
        writer.writerow(
            [
                entry.timestamp,
                entry.type,
                entry.status,
                entry.path or "",
                entry.summary,
                f"{entry.duration:.2f}" if entry.duration > 0 else "0",
            ]
        )

        return output.getvalue()

    def _get_detail_text_content(self) -> str:
        """
        Get the current content from the detail text view.

        Returns:
            The text content currently displayed in the log detail view
        """
        buffer = self._detail_text.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        return buffer.get_text(start, end, False)

    def _format_log_entry_as_json(self, entry: LogEntry) -> str:
        """
        Format a single log entry as JSON.

        Args:
            entry: The LogEntry to format

        Returns:
            JSON formatted string
        """
        import json

        data = {
            "id": entry.id,
            "timestamp": entry.timestamp,
            "type": entry.type,
            "status": entry.status,
            "path": entry.path,
            "summary": entry.summary,
            "duration": entry.duration,
            "details": entry.details,
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def _format_all_logs_as_csv(self) -> str:
        """
        Format all log entries as CSV.

        Returns:
            CSV formatted string with all logs
        """
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Write header row
        writer.writerow(["timestamp", "type", "status", "path", "summary", "duration"])

        # Write data rows
        for entry in self._all_log_entries:
            writer.writerow(
                [
                    entry.timestamp,
                    entry.type,
                    entry.status,
                    entry.path or "",
                    entry.summary,
                    f"{entry.duration:.2f}" if entry.duration > 0 else "0",
                ]
            )

        return output.getvalue()

    def _format_all_logs_as_json(self) -> str:
        """
        Format all log entries as JSON.

        Returns:
            JSON formatted string with all logs
        """
        import json

        data = []
        for entry in self._all_log_entries:
            data.append(
                {
                    "id": entry.id,
                    "timestamp": entry.timestamp,
                    "type": entry.type,
                    "status": entry.status,
                    "path": entry.path,
                    "summary": entry.summary,
                    "duration": entry.duration,
                    "details": entry.details,
                }
            )
        return json.dumps(data, indent=2, ensure_ascii=False)

    def _show_export_toast(self, message: str, is_error: bool = False):
        """
        Show a toast notification for export operations.

        Args:
            message: The message to display
            is_error: Whether this is an error message
        """
        window = self.get_root()
        if hasattr(window, "add_toast"):
            toast = Adw.Toast.new(message)
            window.add_toast(toast)

    def _on_fullscreen_daemon_clicked(self, button: Gtk.Button):
        """Handle fullscreen button click for daemon logs."""
        # Get current content from daemon text view
        buffer = self._daemon_text.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        content = buffer.get_text(start, end, False)

        # Create and present the fullscreen dialog
        dialog = FullscreenLogDialog(title="Daemon Logs", content=content)
        dialog.set_transient_for(self.get_root())
        dialog.present()

    def _on_export_daemon_logs_clicked(self, button: Gtk.Button):
        """Handle export daemon logs button click."""
        # Get current content from daemon text view
        buffer = self._daemon_text.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        content = buffer.get_text(start, end, False)

        # Don't export placeholder text
        if "will appear here" in content:
            return

        helper = FileExportHelper(
            parent_widget=self,
            dialog_title="Export Daemon Logs",
            filename_prefix="clamd_logs",
            file_filter=TEXT_FILTER,
            content_generator=lambda: content,
            success_message="Exported daemon logs",
        )
        helper.show_save_dialog()

    def _on_export_all_csv_clicked(self, button: Gtk.Button):
        """
        Handle export all logs to CSV button click.

        Opens a file save dialog and exports all loaded logs to CSV format
        using LogManager.export_logs_to_file().
        """
        if not self._all_log_entries:
            return

        count = len(self._all_log_entries)
        helper = FileExportHelper(
            parent_widget=self,
            dialog_title="Export All Logs to CSV",
            filename_prefix="clamui_logs",
            file_filter=CSV_FILTER,
            content_generator=self._format_all_logs_as_csv,
            success_message=f"Exported {count} logs",
        )
        helper.show_save_dialog()

    def _on_export_all_json_clicked(self, button: Gtk.Button):
        """
        Handle export all logs to JSON button click.

        Opens a file save dialog and exports all loaded logs to JSON format
        using LogManager.export_logs_to_file().
        """
        if not self._all_log_entries:
            return

        count = len(self._all_log_entries)
        helper = FileExportHelper(
            parent_widget=self,
            dialog_title="Export All Logs to JSON",
            filename_prefix="clamui_logs",
            file_filter=JSON_FILTER,
            content_generator=self._format_all_logs_as_json,
            success_message=f"Exported {count} logs",
        )
        helper.show_save_dialog()

    def _on_clear_logs_clicked(self, button: Gtk.Button):
        """Handle clear logs button click."""
        # Show confirmation dialog using ClearLogsDialog for libadwaita < 1.5 compatibility
        dialog = ClearLogsDialog()
        dialog.connect("response", self._on_clear_dialog_response)
        dialog.set_transient_for(self.get_root())
        dialog.present()

    def _on_clear_dialog_response(self, dialog: ClearLogsDialog, response: str):
        """Handle clear confirmation dialog response."""
        if response == "clear":
            self._log_manager.clear_logs()

            # Reset pagination state before reloading
            self._all_log_entries = []
            if hasattr(self, "_pagination"):
                self._pagination.reset_state()

            self._load_logs_async()

            # Clear detail view
            buffer = self._detail_text.get_buffer()
            buffer.set_text(_("Select a log entry to view details."))
            self._selected_log = None

            # Disable copy/export buttons when logs are cleared
            self._copy_detail_button.set_sensitive(False)
            self._export_detail_text_button.set_sensitive(False)
            self._export_detail_csv_button.set_sensitive(False)
            self._export_detail_json_button.set_sensitive(False)

    def _on_refresh_clicked(self, button: Gtk.Button):
        """Handle refresh button click."""
        self._load_logs_async()

    def _set_loading_state(self, is_loading: bool):
        """
        Update UI to reflect loading state for historical logs.

        Shows a loading placeholder row with spinner in the listbox when loading,
        in addition to the header spinner indicator.

        Args:
            is_loading: Whether logs are currently being loaded
        """
        self._is_loading = is_loading

        try:
            if is_loading:
                # Show loading state in header first (fast, non-blocking)
                self._logs_spinner.set_visible(True)
                self._logs_spinner.start()
                self._refresh_button.set_sensitive(False)
                self._clear_button.set_sensitive(False)
                self._export_all_csv_button.set_sensitive(False)
                self._export_all_json_button.set_sensitive(False)

                # Clear existing rows and show loading placeholder in listbox
                # This is done synchronously but is fast enough for typical row counts
                self._logs_listbox.remove_all()
                loading_row = self._create_loading_state()
                self._logs_listbox.append(loading_row)
            else:
                # Restore normal header state
                self._logs_spinner.stop()
                self._logs_spinner.set_visible(False)
                self._refresh_button.set_sensitive(True)
                # Note: Listbox content is handled by the calling code
                # (_on_logs_loaded clears and repopulates)
        except Exception:
            # Ensure loading flag is reset even if widget operations fail
            # This prevents stuck loading state
            self._is_loading = False

    def _check_daemon_status(self) -> bool:
        """Kick off an off-main-thread daemon-status check.

        get_daemon_status() shells out to systemctl/pgrep, which can block the GTK
        main loop; run it on a worker thread and apply the result on the main loop.
        Scheduled once via GLib.idle_add on load, so returns False (no repeat).
        """
        threading.Thread(target=self._check_daemon_status_worker, daemon=True).start()
        return False

    def _check_daemon_status_worker(self) -> None:
        """Worker: read daemon status off the main loop, then schedule the UI update."""
        status, message = self._log_manager.get_daemon_status()
        GLib.idle_add(self._apply_daemon_status, status, message)

    def _apply_daemon_status(self, status, message) -> bool:
        """Apply a daemon-status result to the UI (runs on the GTK main loop)."""
        if status == DaemonStatus.RUNNING:
            self._daemon_status_row.set_subtitle(_("Running"))
            self._daemon_status_icon.set_from_icon_name(resolve_icon_name("object-select-symbolic"))
            # Remove any warning/error classes and add success
            self._daemon_status_row.remove_css_class("warning")
            self._daemon_status_row.remove_css_class("error")
            self._live_toggle.set_sensitive(True)
        elif status == DaemonStatus.STOPPED:
            self._daemon_status_row.set_subtitle(_("Stopped"))
            self._daemon_status_icon.set_from_icon_name(
                resolve_icon_name("media-playback-stop-symbolic")
            )
            self._live_toggle.set_sensitive(True)
        elif status == DaemonStatus.NOT_INSTALLED:
            self._daemon_status_row.set_subtitle(_("Not installed"))
            self._daemon_status_icon.set_from_icon_name(
                resolve_icon_name("dialog-information-symbolic")
            )
            self._live_toggle.set_sensitive(False)
            # Update daemon text with helpful message
            buffer = self._daemon_text.get_buffer()
            buffer.set_text(
                _(
                    "ClamAV daemon (clamd) is not installed.\n\n"
                    "The daemon is optional and provides faster scanning.\n"
                    "You can still use ClamUI for on-demand scanning without it."
                )
            )
        else:  # UNKNOWN
            self._daemon_status_row.set_subtitle(message or _("Unknown"))
            self._daemon_status_icon.set_from_icon_name(
                resolve_icon_name("dialog-question-symbolic")
            )
            self._live_toggle.set_sensitive(False)

        return False  # Don't repeat

    def _on_live_toggle(self, button: Gtk.ToggleButton):
        """Handle live log toggle button."""
        if button.get_active():
            # Start live updates
            button.set_icon_name(resolve_icon_name("media-playback-pause-symbolic"))
            button.set_tooltip_text(_("Stop live log updates"))
            self._start_daemon_log_refresh()
        else:
            # Stop live updates
            button.set_icon_name(resolve_icon_name("media-playback-start-symbolic"))
            button.set_tooltip_text(_("Start live log updates"))
            self._stop_daemon_log_refresh()

    def _start_daemon_log_refresh(self):
        """Start periodic daemon log refresh."""
        # Initial load
        self._refresh_daemon_logs()

        # Set up periodic refresh (every 3 seconds)
        self._daemon_refresh_id = GLib.timeout_add(3000, self._refresh_daemon_logs)

    def _stop_daemon_log_refresh(self):
        """Stop periodic daemon log refresh."""
        if self._daemon_refresh_id is not None:
            GLib.source_remove(self._daemon_refresh_id)
            self._daemon_refresh_id = None

    def _refresh_daemon_logs(self) -> bool:
        """Kick off an off-main-thread daemon-log refresh.

        read_daemon_logs() runs tail/journalctl, which can block the GTK main loop
        for seconds; do it on a worker thread and apply the result on the main loop.
        An in-flight guard prevents a slow read from stacking behind the 3s tick.
        Returns whether the periodic timer should keep firing.
        """
        if not self._daemon_refresh_in_flight:
            self._daemon_refresh_in_flight = True
            threading.Thread(target=self._refresh_daemon_logs_worker, daemon=True).start()
        # Keep the periodic timer alive while live refresh is active.
        return self._daemon_refresh_id is not None

    def _refresh_daemon_logs_worker(self) -> None:
        """Worker: read daemon logs off the main loop, then schedule the UI update."""
        success, content = self._log_manager.read_daemon_logs(num_lines=100)
        GLib.idle_add(self._apply_daemon_logs, success, content)

    def _apply_daemon_logs(self, success, content) -> bool:
        """Apply a daemon-log read result to the UI (runs on the GTK main loop)."""
        self._daemon_refresh_in_flight = False

        buffer = self._daemon_text.get_buffer()

        if success:
            buffer.set_text(content)
            # Scroll to bottom
            end_iter = buffer.get_end_iter()
            self._daemon_text.scroll_to_iter(end_iter, 0.0, False, 0.0, 0.0)
            # Enable export button when logs are available
            self._export_daemon_button.set_sensitive(True)
        else:
            buffer.set_text(f"Error loading daemon logs:\n\n{content}")
            # Disable export button on error
            self._export_daemon_button.set_sensitive(False)

        return False  # idle_add: run once

    def refresh_logs(self):
        """
        Public method to refresh the logs display.

        Can be called externally when new logs are added.
        """
        GLib.idle_add(self._load_logs_async)

    def do_unmap(self):
        """
        Handle widget unmapping (being hidden).

        This is called when the widget is hidden or removed from the widget tree.
        We use this to stop daemon log refresh to save resources.
        """
        # Stop daemon log refresh when view is hidden
        self._stop_daemon_log_refresh()
        if self._live_toggle.get_active():
            self._live_toggle.set_active(False)

        # Call parent implementation
        Gtk.Box.do_unmap(self)

    def do_map(self):
        """
        Handle widget mapping (being shown).

        This is called when the widget becomes visible.
        We do NOT trigger a reload here because do_map() is called frequently
        during UI updates (spinner visibility, row changes, etc.) and would
        cause infinite reload loops.

        The initial load is handled by __init__ and manual refreshes are
        triggered via the refresh button or refresh_logs() method.
        """
        # Call parent implementation first
        Gtk.Box.do_map(self)

    @property
    def log_manager(self) -> LogManager:
        """
        Get the log manager instance.

        Returns:
            The LogManager instance used by this view
        """
        return self._log_manager
