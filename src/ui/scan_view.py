# ClamUI Scan View
"""
Scan interface component for ClamUI with folder picker, scan button, and results display.
"""

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..core.i18n import _, ngettext
from ..core.quarantine import QuarantineManager
from ..core.scanner import Scanner, ScanProgress, ScanResult, ScanStatus
from ..core.utils import (
    format_scan_path,
    is_flatpak,
    validate_dropped_files,
)
from .clipboard_helper import ClipboardHelper
from .compat import create_banner, open_paths_dialog
from .eicar_helper import (
    EICAR_TEST_STRING as _EICAR_HELPER_STRING,
)
from .eicar_helper import (
    cleanup_eicar_path,
    create_eicar_temp,
    register_eicar_atexit_cleanup,
)
from .fullscreen_dialog import FullscreenLogDialog
from .profile_dialogs import ProfileListDialog
from .scan_results_dialog import ScanResultsDialog
from .utils import add_row_icon, resolve_icon_name
from .view_helpers import StatusLevel, set_status_class

# Check GTK version for CssProvider.load_from_string() (added in GTK 4.12)
# Older versions (e.g., GTK 4.6 on Ubuntu 22.04) only have load_from_data()
try:
    _GTK_MINOR_VERSION = Gtk.get_minor_version()
    _HAS_CSS_LOAD_STRING = _GTK_MINOR_VERSION >= 12
except (TypeError, AttributeError):
    _HAS_CSS_LOAD_STRING = False

if TYPE_CHECKING:
    from ..core.settings_manager import SettingsManager
    from ..profiles.models import ScanProfile
    from ..profiles.profile_manager import ProfileManager

logger = logging.getLogger(__name__)

# EICAR test string - industry-standard antivirus test pattern.
# Re-exported from eicar_helper so existing imports keep working.
EICAR_TEST_STRING = _EICAR_HELPER_STRING
STATUS_DETAIL_SUMMARY_MAX_CHARS = 160
STATUS_DETAIL_MIN_HEIGHT = 120
STATUS_DETAIL_MAX_HEIGHT = 260


class ScanView(Gtk.Box):
    """
    Scan interface component for ClamUI.

    Provides the main scanning interface with:
    - Folder/file selection
    - Scan button with progress indication
    - Results display area
    """

    def __init__(
        self,
        settings_manager: "SettingsManager | None" = None,
        quarantine_manager: "QuarantineManager | None" = None,
        log_manager=None,
        **kwargs,
    ):
        """
        Initialize the scan view.

        Args:
            settings_manager: Optional SettingsManager for exclusion patterns
            quarantine_manager: Optional shared QuarantineManager instance.
                If not provided, a new one is created.
            log_manager: Optional shared LogManager instance. Passed to Scanner
                to avoid creating a redundant instance.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)

        # Store settings manager
        self._settings_manager = settings_manager

        # Initialize scanner with shared log_manager and settings manager
        self._scanner = Scanner(log_manager=log_manager, settings_manager=settings_manager)

        # Use shared quarantine manager if provided, otherwise create own
        self._quarantine_manager = quarantine_manager or QuarantineManager()

        # Current selected paths (supports multiple targets)
        self._selected_paths: list[str] = []
        # Normalized paths for O(1) duplicate checking
        self._normalized_paths: set[str] = set()

        # Scanning state
        self._is_scanning = False
        self._cancel_all_requested = False

        # Temp file path for EICAR test (for cleanup)
        self._eicar_temp_path: str = ""
        # atexit unregister handle for the EICAR cleanup safety net.
        # Replaced with a real unregister callable when the EICAR temp file
        # is created; reset to a no-op once it has been cleaned up.
        self._eicar_atexit_unregister = lambda: None
        # Optional one-shot backend override for the current scan session.
        self._scan_backend_override: str | None = None
        # Optional one-shot daemon mode override for the current scan session.
        self._scan_daemon_force_stream = False

        # Current scan result (for dialog)
        self._current_result: ScanResult | None = None

        # Scan state change callback (for tray integration)
        self._on_scan_state_changed = None

        # Progress section state
        self._progress_section: Gtk.Box | None = None
        self._progress_bar: Gtk.ProgressBar | None = None
        self._progress_label: Gtk.Label | None = None
        self._pulse_timeout_id: int | None = None

        # Live progress Adwaita widgets
        self._progress_group: Adw.PreferencesGroup | None = None
        self._current_file_row: Adw.ActionRow | None = None
        self._file_spinner: Gtk.Spinner | None = None
        self._stats_row: Adw.ActionRow | None = None
        self._threat_group: Adw.PreferencesGroup | None = None
        self._live_threat_list: Gtk.ListBox | None = None
        self._live_threat_count: int = 0

        # Throttling and visibility state
        self._last_progress_update: float = 0.0  # For throttling UI updates
        self._updates_paused: bool = False  # Pause updates when view is hidden
        self._is_view_visible: bool = True  # Track view visibility

        # Multi-target scan tracking
        self._current_target_idx: int = 1  # Current target (1-based)
        self._total_target_count: int = 0  # Total targets being scanned
        self._cumulative_files_scanned: int = 0  # Files from completed targets
        self._progress_session_id: int = 0  # Monotonic token to ignore stale progress callbacks

        # View results section state
        self._view_results_section: Gtk.Box | None = None
        self._view_results_button: Gtk.Button | None = None

        # Detailed status output state
        self._status_detail_group: Adw.PreferencesGroup | None = None
        self._status_detail_text: Gtk.TextView | None = None
        self._status_detail_copy_button: Gtk.Button | None = None
        self._status_detail_fullscreen_button: Gtk.Button | None = None
        self._status_detail_content: str = ""
        self._status_detail_title_text: str = ""

        # Profile management state
        self._selected_profile: ScanProfile | None = None
        self._profile_list: list[ScanProfile] = []
        self._profile_string_list: Gtk.StringList | None = None
        self._profile_dropdown: Gtk.DropDown | None = None

        # Set up the UI
        self._setup_ui()
        self._bind_settings_listeners()

        # Connect to parent changes for visibility tracking
        self.connect("notify::parent", self._on_parent_changed)

    def _setup_ui(self):
        """Set up the scan view UI layout."""
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_spacing(12)

        # Set up CSS for drag-and-drop visual feedback
        self._setup_drop_css()

        # Create the profile selector section
        self._create_profile_section()

        # Create the selection section
        self._create_selection_section()

        # Create the scan button section
        self._create_scan_section()

        # Create the progress section (hidden initially)
        self._create_progress_section()

        # Create the view results button (hidden initially)
        self._create_view_results_section()

        # Create the backend indicator
        self._create_backend_indicator()

        # Create the status bar
        self._create_status_bar()
        self._create_status_detail_section()

        # Set up drag-and-drop support
        self._setup_drop_target()

    def _bind_settings_listeners(self) -> None:
        """Subscribe to live settings updates that affect the scan view."""
        if self._settings_manager is None:
            return

        add_listener = getattr(self._settings_manager, "add_listener", None)
        if callable(add_listener):
            add_listener("scan_backend", self._on_scan_backend_setting_changed)

    def _setup_drop_css(self):
        """Set up CSS styling for drag-and-drop visual feedback and severity badges."""
        css_provider = Gtk.CssProvider()
        css_string = """
            .drop-active {
                border: 2px dashed @accent_color;
                border-radius: 12px;
                background-color: alpha(@accent_bg_color, 0.1);
            }

            /* Severity badge styles */
            .severity-badge {
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 0.85em;
                font-weight: bold;
            }

            /* Critical severity: Ransomware, rootkits, bootkits - most dangerous threats
               Uses @error_bg_color (red) to indicate danger and urgency
               Adapts to theme (darker in light mode, lighter in dark mode) */
            .severity-critical {
                background-color: @error_bg_color;
                color: white;
            }

            /* High severity: Trojans, worms, backdoors, exploits - serious threats
               Uses lighter(@error_bg_color) to create orange tone (between red and yellow)
               Semantically between critical error and medium warning */
            .severity-high {
                background-color: lighter(@error_bg_color);
                color: white;
            }

            /* Medium severity: Adware, PUAs (Potentially Unwanted Applications), spyware
               Uses @warning_bg_color and @warning_fg_color (yellow/amber) for caution
               Standard warning semantics for concerning but less severe threats */
            .severity-medium {
                background-color: @warning_bg_color;
                color: @warning_fg_color;
            }

            /* Low severity: Test signatures (EICAR), generic/heuristic detections
               Uses @accent_bg_color (blue) for informational, low-risk items
               Accent color indicates "note this" without alarm */
            .severity-low {
                background-color: @accent_bg_color;
                color: white;
            }

            /* Threat card styling */
            .threat-card {
                margin: 4px 0;
            }

            .recommended-action {
                padding: 8px 12px;
                background-color: alpha(@card_bg_color, 0.5);
                border-radius: 6px;
                margin: 4px 0;
            }

            /* Large result warning banner */
            .large-result-warning {
                background-color: alpha(@warning_color, 0.15);
                border: 1px solid @warning_color;
                border-radius: 6px;
                padding: 12px;
                margin-bottom: 8px;
            }

            /* Load more button styling */
            .load-more-row {
                padding: 12px;
            }

            /* Progress section styling */
            .progress-section {
                padding: 12px 0;
            }

            .progress-bar-compact {
                min-height: 6px;
                border-radius: 3px;
            }

            .progress-status {
                font-size: 0.9em;
                margin-top: 6px;
            }

            /* Stats section styling */
            .stats-row {
                padding: 4px 12px;
            }

            .stats-label {
                min-width: 120px;
            }

            .stats-value {
                font-weight: bold;
            }

            .stats-icon-success {
                color: @success_color;
            }

            .stats-icon-warning {
                color: @warning_color;
            }

            .stats-icon-error {
                color: @error_color;
            }

            /* Threat action buttons */
            .threat-actions {
                margin-top: 8px;
                padding-top: 8px;
                border-top: 1px solid alpha(@borders, 0.3);
            }

            .threat-action-btn {
                min-height: 24px;
                padding: 4px 10px;
                font-size: 0.85em;
            }

            .threat-action-btn.quarantined {
                opacity: 0.6;
            }

            .threat-action-btn.excluded {
                opacity: 0.6;
            }

            /* Status banner background styling */
            .success .banner {
                background-color: alpha(@success_bg_color, 0.3);
                border-radius: 6px;
                padding: 12px;
            }

            .warning .banner {
                background-color: alpha(@warning_bg_color, 0.3);
                border-radius: 6px;
                padding: 12px;
            }

            .error .banner {
                background-color: alpha(@error_bg_color, 0.3);
                border-radius: 6px;
                padding: 12px;
            }
        """
        if _HAS_CSS_LOAD_STRING:
            css_provider.load_from_string(css_string)
        else:
            css_provider.load_from_data(css_string.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _setup_drop_target(self):
        """Set up drag-and-drop file handling."""
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_drop)
        drop_target.connect("enter", self._on_drag_enter)
        drop_target.connect("leave", self._on_drag_leave)
        # Set propagation phase to CAPTURE so events are intercepted before
        # reaching child widgets (like TextView) that might swallow them
        drop_target.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        # Add drop target to the entire ScanView widget
        self.add_controller(drop_target)

    def _on_drop(self, target, value, x, y) -> bool:
        """
        Handle file drop.

        Extracts file paths from the dropped Gdk.FileList and adds all valid
        paths as scan targets.

        Args:
            target: The DropTarget controller
            value: The dropped value (Gdk.FileList)
            x: X coordinate of drop location
            y: Y coordinate of drop location

        Returns:
            True if drop was accepted, False otherwise
        """
        # Remove visual feedback (leave signal is not emitted on drop)
        self.remove_css_class("drop-active")

        # Reject drops during active scan
        if self._is_scanning:
            self._show_drop_error(
                _("Scan in progress - please wait until the current scan completes")
            )
            return False

        # Extract files from Gdk.FileList
        files = value.get_files()
        if not files:
            self._show_drop_error(_("No files were dropped"))
            return False

        # Get paths from Gio.File objects (None for remote files)
        paths = [gio_file.get_path() for gio_file in files]

        # Validate paths using utility function
        valid_paths, errors = validate_dropped_files(paths)

        if valid_paths:
            # Add all valid paths to the selection
            for path in valid_paths:
                self._add_path(path)
            return True

        # No valid paths - show error and reject drop
        if errors:
            # Show the first error (most relevant for user)
            self._show_drop_error(errors[0])
        else:
            self._show_drop_error(_("Unable to accept dropped files"))
        return False

    def _on_drag_enter(self, target, x, y) -> Gdk.DragAction:
        """
        Visual feedback when drag enters the drop zone.

        Adds the 'drop-active' CSS class to highlight the widget
        as a valid drop target.

        Args:
            target: The DropTarget controller
            x: X coordinate of drag position
            y: Y coordinate of drag position

        Returns:
            Gdk.DragAction.COPY to indicate the drop is accepted
        """
        self.add_css_class("drop-active")
        return Gdk.DragAction.COPY

    def _on_drag_leave(self, target):
        """
        Cleanup visual feedback when drag leaves the drop zone.

        Removes the 'drop-active' CSS class to restore normal appearance.

        Args:
            target: The DropTarget controller
        """
        self.remove_css_class("drop-active")

    def _on_status_banner_dismissed(self, banner):
        """
        Handle status banner dismiss button click.

        Hides the status banner when the user clicks the Dismiss button.

        Args:
            banner: The Adw.Banner that was dismissed
        """
        banner.set_revealed(False)
        self._hide_status_details(clear_content=False)

    def _show_drop_error(self, message: str):
        """
        Display an error message for invalid file drops.

        Uses the status banner to show a user-friendly error message
        when dropped files cannot be accepted (remote files, permission
        errors, non-existent paths, etc.).

        Args:
            message: The error message to display
        """
        self._set_status_message(message, StatusLevel.ERROR)
        self._show_toast(message)

    def _create_status_detail_section(self) -> None:
        """Create the bounded detail panel used for long scan output."""
        detail_group = Adw.PreferencesGroup()
        detail_group.set_title(_("Scan details"))
        detail_group.set_description(_("Detailed scan output appears here when available"))
        detail_group.set_visible(False)
        self._status_detail_group = detail_group

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_halign(Gtk.Align.END)

        copy_button = Gtk.Button()
        copy_button.set_icon_name(resolve_icon_name("edit-copy-symbolic"))
        copy_button.set_tooltip_text(_("Copy details"))
        copy_button.add_css_class("flat")
        copy_button.set_sensitive(False)
        copy_button.connect("clicked", self._on_copy_status_details_clicked)
        self._status_detail_copy_button = copy_button

        fullscreen_button = Gtk.Button()
        fullscreen_button.set_icon_name(resolve_icon_name("view-fullscreen-symbolic"))
        fullscreen_button.set_tooltip_text(_("View details fullscreen"))
        fullscreen_button.add_css_class("flat")
        fullscreen_button.set_sensitive(False)
        fullscreen_button.connect("clicked", self._on_fullscreen_status_details_clicked)
        self._status_detail_fullscreen_button = fullscreen_button

        header_box.append(copy_button)
        header_box.append(fullscreen_button)
        detail_group.set_header_suffix(header_box)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(STATUS_DETAIL_MIN_HEIGHT)
        scrolled.set_max_content_height(STATUS_DETAIL_MAX_HEIGHT)
        scrolled.add_css_class("card")

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_left_margin(12)
        text_view.set_right_margin(12)
        text_view.set_top_margin(12)
        text_view.set_bottom_margin(12)
        text_view.add_css_class("monospace")
        self._status_detail_text = text_view

        scrolled.set_child(text_view)
        detail_group.add(scrolled)
        self.append(detail_group)

    def _set_status_detail_content(self, content: str) -> None:
        """Update the stored detail content and the visible text buffer."""
        self._status_detail_content = content

        text_view = getattr(self, "_status_detail_text", None)
        if text_view is None:
            return

        buffer = text_view.get_buffer()
        buffer.set_text(content)

    def _show_status_details(
        self,
        title: str,
        content: str,
        description: str | None = None,
    ) -> None:
        """Reveal the status detail panel with the provided content."""
        detail_text = content.strip()
        if not detail_text:
            self._hide_status_details(clear_content=True)
            return

        self._status_detail_title_text = title
        self._set_status_detail_content(detail_text)

        detail_group = getattr(self, "_status_detail_group", None)
        if detail_group is not None:
            detail_group.set_title(title)
            if description is not None:
                detail_group.set_description(description)
            detail_group.set_visible(True)

        copy_button = getattr(self, "_status_detail_copy_button", None)
        if copy_button is not None:
            copy_button.set_sensitive(True)

        fullscreen_button = getattr(self, "_status_detail_fullscreen_button", None)
        if fullscreen_button is not None:
            fullscreen_button.set_sensitive(True)

    def _hide_status_details(self, clear_content: bool = True) -> None:
        """Hide the status detail panel and optionally clear its content."""
        detail_group = getattr(self, "_status_detail_group", None)
        if detail_group is not None:
            detail_group.set_visible(False)

        copy_button = getattr(self, "_status_detail_copy_button", None)
        if copy_button is not None:
            copy_button.set_sensitive(False)

        fullscreen_button = getattr(self, "_status_detail_fullscreen_button", None)
        if fullscreen_button is not None:
            fullscreen_button.set_sensitive(False)

        if clear_content:
            self._status_detail_title_text = ""
            self._set_status_detail_content("")

    def _set_status_message(
        self,
        title: str,
        level: StatusLevel,
        detail_content: str | None = None,
        detail_title: str | None = None,
        detail_description: str | None = None,
    ) -> None:
        """Update the status banner and optional detail panel together."""
        self._status_banner.set_title(title)
        set_status_class(self._status_banner, level)
        self._status_banner.set_revealed(True)

        if detail_content and detail_title:
            self._show_status_details(detail_title, detail_content, detail_description)
        else:
            self._hide_status_details(clear_content=True)

    def _summarize_status_detail(self, detail: str) -> str:
        """Collapse multi-line detail text into a short banner-friendly summary."""
        summary = next((line.strip() for line in detail.splitlines() if line.strip()), "")
        if not summary:
            return _("Unknown error")
        if len(summary) > STATUS_DETAIL_SUMMARY_MAX_CHARS:
            return summary[: STATUS_DETAIL_SUMMARY_MAX_CHARS - 3].rstrip() + "..."
        return summary

    def _should_show_status_details(self, detail: str) -> bool:
        """Return True when the detail content merits a dedicated panel."""
        detail_text = detail.strip()
        return bool(detail_text) and (
            "\n" in detail_text or len(detail_text) > STATUS_DETAIL_SUMMARY_MAX_CHARS
        )

    def _build_scan_error_details(self, result: ScanResult) -> str:
        """Build detailed error output for the status detail panel."""
        sections: list[str] = []
        error_message = (result.error_message or "").strip()
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()

        if error_message and error_message not in {stderr, stdout}:
            sections.append(_("Summary:"))
            sections.append(error_message)

        if stderr:
            if sections:
                sections.append("")
            sections.append(_("Error output:"))
            sections.append(stderr)

        if stdout and stdout != stderr:
            if sections:
                sections.append("")
            sections.append(_("Scan output:"))
            sections.append(stdout)

        if not sections and error_message:
            sections.append(error_message)

        return "\n".join(sections).strip()

    def _on_copy_status_details_clicked(self, button: Gtk.Button) -> None:
        """Copy the current status detail content to the clipboard."""
        detail_text = getattr(self, "_status_detail_content", "").strip()
        if not detail_text:
            return

        helper = ClipboardHelper(parent_widget=self)
        helper.copy_with_feedback(
            text=detail_text,
            success_message=_("Scan details copied to clipboard"),
            error_message=_("Failed to copy scan details"),
            too_large_message=_(
                "Scan details are too large to copy. Use fullscreen to inspect the full output."
            ),
        )

    def _on_fullscreen_status_details_clicked(self, button: Gtk.Button) -> None:
        """Open the current status detail content in the fullscreen viewer."""
        detail_text = getattr(self, "_status_detail_content", "").strip()
        if not detail_text:
            return

        title = self._status_detail_title_text or _("Scan details")
        dialog = FullscreenLogDialog(title=title, content=detail_text)
        root = self.get_root()
        if root is not None:
            dialog.set_transient_for(root)
        dialog.present()

    def _show_toast(self, message: str) -> None:
        """
        Show a toast notification for user feedback.

        Args:
            message: The message to display in the toast
        """
        root = self.get_root()
        if root is None:
            return
        if hasattr(root, "add_toast"):
            toast = Adw.Toast.new(message)
            root.add_toast(toast)

    def _create_profile_section(self):
        """Create the scan profile selector section."""
        # Profile selection frame
        profile_group = Adw.PreferencesGroup()
        profile_group.set_title(_("Scan Profile"))
        self._profile_group = profile_group

        # Profile selection row
        profile_row = Adw.ActionRow()
        profile_row.set_title(_("Profile"))
        add_row_icon(profile_row, "document-properties-symbolic")
        self._profile_row = profile_row

        # Create string list for dropdown
        self._profile_string_list = Gtk.StringList()
        self._profile_string_list.append(_("No Profile (Manual)"))

        # Create the dropdown
        self._profile_dropdown = Gtk.DropDown()
        self._profile_dropdown.set_model(self._profile_string_list)
        self._profile_dropdown.set_selected(0)  # Default to "No Profile"
        self._profile_dropdown.set_valign(Gtk.Align.CENTER)
        self._profile_dropdown.connect("notify::selected", self._on_profile_selected)

        # Create manage profiles button
        manage_profiles_btn = Gtk.Button()
        manage_profiles_btn.set_icon_name(resolve_icon_name("emblem-system-symbolic"))
        manage_profiles_btn.set_tooltip_text(_("Manage profiles"))
        manage_profiles_btn.add_css_class("flat")
        manage_profiles_btn.set_valign(Gtk.Align.CENTER)
        manage_profiles_btn.connect("clicked", self._on_manage_profiles_clicked)
        self._manage_profiles_btn = manage_profiles_btn

        # Button box to contain dropdown and manage button
        profile_control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        profile_control_box.set_valign(Gtk.Align.CENTER)
        profile_control_box.append(self._profile_dropdown)
        profile_control_box.append(manage_profiles_btn)

        profile_row.add_suffix(profile_control_box)
        profile_group.add(profile_row)

        self.append(profile_group)

        # Load profiles after widget is realized (to access profile manager)
        self.connect("realize", self._on_realize_load_profiles)

    def _on_realize_load_profiles(self, widget):
        """Load profiles when the widget is realized and has access to the application."""
        self.refresh_profiles()

    def _get_profile_manager(self) -> "ProfileManager | None":
        """
        Get the ProfileManager from the application.

        Returns:
            ProfileManager instance or None if not available
        """
        root = self.get_root()
        if root is None:
            return None

        app = root.get_application() if hasattr(root, "get_application") else None
        if app is None:
            return None

        if hasattr(app, "profile_manager"):
            return app.profile_manager

        return None

    def refresh_profiles(self):
        """
        Refresh the profile dropdown with current profiles from ProfileManager.

        This method can be called externally to update the dropdown when
        profiles are added, edited, or deleted.
        """
        profile_manager = self._get_profile_manager()
        if profile_manager is None:
            logger.debug("ProfileManager not available, skipping profile refresh")
            return

        # Store current selection to restore if possible
        current_selection = self._profile_dropdown.get_selected() if self._profile_dropdown else 0
        current_profile_id = None
        if current_selection > 0 and current_selection - 1 < len(self._profile_list):
            current_profile_id = self._profile_list[current_selection - 1].id

        # Get updated profile list
        self._profile_list = profile_manager.list_profiles()

        # Clear and rebuild the string list
        # GTK4 StringList doesn't have a clear method, so rebuild
        remaining_items = self._profile_string_list.get_n_items()
        while remaining_items > 0:
            self._profile_string_list.remove(0)
            remaining_items -= 1

        # Add "No Profile" option
        self._profile_string_list.append(_("No Profile (Manual)"))

        # Add each profile
        for profile in self._profile_list:
            self._profile_string_list.append(profile.name)

        # Restore selection
        if current_profile_id:
            for i, profile in enumerate(self._profile_list):
                if profile.id == current_profile_id:
                    self._profile_dropdown.set_selected(i + 1)  # +1 for "No Profile" option
                    return

        # Default to "No Profile"
        self._profile_dropdown.set_selected(0)

    def _on_profile_selected(self, dropdown, param_spec):
        """
        Handle profile selection change.

        Args:
            dropdown: The Gtk.DropDown that was changed
            param_spec: The GParamSpec for the 'selected' property
        """
        selected_idx = dropdown.get_selected()

        if selected_idx == 0:
            # "No Profile" selected
            self._selected_profile = None
        else:
            # Profile selected
            profile_idx = selected_idx - 1  # Adjust for "No Profile" option
            if 0 <= profile_idx < len(self._profile_list):
                self._selected_profile = self._profile_list[profile_idx]
                # Apply all profile targets to the path list
                if self._selected_profile.targets:
                    self._clear_paths()
                    valid_count = 0
                    for target in self._selected_profile.targets:
                        # Expand ~ in paths
                        expanded = os.path.expanduser(target) if target.startswith("~") else target
                        if os.path.exists(expanded):
                            self._add_path(expanded)
                            valid_count += 1
                    # Warn if no valid targets were found
                    if valid_count == 0:
                        self._show_toast(
                            _("Profile '{name}' has no valid targets").format(
                                name=self._selected_profile.name
                            )
                        )
            else:
                self._selected_profile = None

    def _on_manage_profiles_clicked(self, button):
        """
        Handle manage profiles button click.

        Opens the profile management dialog.

        Args:
            button: The Gtk.Button that was clicked
        """
        root = self.get_root()
        if root is not None and isinstance(root, Gtk.Window):
            profile_manager = self._get_profile_manager()
            dialog = ProfileListDialog(profile_manager=profile_manager)
            # Set callback for when a profile is selected to run
            dialog.set_on_profile_selected(self._on_profile_run_from_dialog)
            # Refresh profiles when dialog is closed
            dialog.connect("close-request", self._on_profiles_dialog_closed)
            dialog.set_transient_for(root)
            dialog.present()

    def _on_profiles_dialog_closed(self, dialog):
        """
        Handle profile dialog closed.

        Refreshes the profile dropdown to reflect any changes.

        Args:
            dialog: The ProfileListDialog that was closed
        """
        self.refresh_profiles()

    def _on_profile_run_from_dialog(self, profile: "ScanProfile"):
        """
        Handle profile selection from manage profiles dialog.

        Selects the profile in the dropdown and starts the scan.

        Args:
            profile: The ScanProfile that was selected to run
        """
        # Refresh profiles first to ensure the list is up to date
        self.refresh_profiles()
        # Select the profile in the dropdown
        self.set_selected_profile(profile.id)
        # Start the scan with the selected profile
        self._start_scan()

    def _create_selection_section(self):
        """Create the file/folder selection UI section with multi-path support."""
        # Container for selection UI
        self._selection_group = Adw.PreferencesGroup()
        self._selection_group.set_title(_("Scan Targets"))
        self._selection_group.set_description(_("Drop files here or click Add"))

        # Header suffix with Add buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)

        # Add Files button
        self._add_files_button = Gtk.Button()
        self._add_files_button.set_icon_name(resolve_icon_name("document-new-symbolic"))
        self._add_files_button.set_tooltip_text(_("Add files"))
        self._add_files_button.add_css_class("flat")
        self._add_files_button.connect("clicked", self._on_select_file_clicked)
        button_box.append(self._add_files_button)

        # Add Folders button
        self._add_folders_button = Gtk.Button()
        self._add_folders_button.set_icon_name(resolve_icon_name("folder-new-symbolic"))
        self._add_folders_button.set_tooltip_text(_("Add folders"))
        self._add_folders_button.add_css_class("flat")
        self._add_folders_button.connect("clicked", self._on_select_folder_clicked)
        button_box.append(self._add_folders_button)

        # Clear All button (visible when multiple paths exist)
        self._clear_all_button = Gtk.Button()
        self._clear_all_button.set_icon_name(resolve_icon_name("edit-clear-all-symbolic"))
        self._clear_all_button.set_tooltip_text(_("Clear all"))
        self._clear_all_button.add_css_class("flat")
        self._clear_all_button.connect("clicked", self._on_clear_all_clicked)
        self._clear_all_button.set_visible(False)
        button_box.append(self._clear_all_button)

        self._selection_group.set_header_suffix(button_box)

        # Paths list box
        self._paths_listbox = Gtk.ListBox()
        self._paths_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._paths_listbox.add_css_class("boxed-list")

        # Placeholder row for empty list
        self._paths_placeholder = Adw.ActionRow()
        self._paths_placeholder.set_title(_("No targets added"))
        self._paths_placeholder.set_subtitle(_("Drop files here or click Add Files/Folders"))
        add_row_icon(self._paths_placeholder, "folder-symbolic")
        self._paths_placeholder.add_css_class("dim-label")
        self._paths_listbox.append(self._paths_placeholder)

        self._selection_group.add(self._paths_listbox)
        self.append(self._selection_group)

    def _create_path_row(self, path: str) -> Adw.ActionRow:
        """
        Create a row for displaying a scan target path.

        Args:
            path: The file or folder path to display

        Returns:
            Configured Adw.ActionRow with path and remove button
        """
        row = Adw.ActionRow()

        # Format path for display
        formatted_path = format_scan_path(path)
        row.set_title(GLib.markup_escape_text(formatted_path))

        # Set tooltip with full path
        row.set_tooltip_text(path)

        # Choose icon based on path type
        icon_name = "folder-symbolic" if os.path.isdir(path) else "text-x-generic-symbolic"
        add_row_icon(row, icon_name)

        # Remove button
        remove_btn = Gtk.Button()
        remove_btn.set_icon_name(resolve_icon_name("edit-delete-symbolic"))
        remove_btn.set_tooltip_text(_("Remove"))
        remove_btn.add_css_class("flat")
        remove_btn.add_css_class("error")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.connect("clicked", lambda btn: self._on_remove_path_clicked(path, row))

        row.add_suffix(remove_btn)

        # Store the path as data on the row for later reference
        row.path = path

        return row

    def _on_remove_path_clicked(self, path: str, row: Adw.ActionRow):
        """
        Handle remove button click for a path row.

        Args:
            path: The path to remove
            row: The row widget to remove from the listbox
        """
        self._remove_path(path)

    def _on_clear_all_clicked(self, button):
        """Handle clear all button click."""
        self._clear_paths()

    def _on_select_file_clicked(self, button):
        """
        Handle select file button click.

        Opens a file chooser dialog to select one or more files.

        Args:
            button: The Gtk.Button that was clicked
        """
        root = self.get_root()
        if root is None or not isinstance(root, Gtk.Window):
            return

        open_paths_dialog(
            root,
            title=_("Select Files to Scan"),
            on_selected=self._replace_selected_paths,
            select_folders=False,
            multiple=True,
            initial_folder=self._get_initial_selection_folder(),
        )

    def _on_select_folder_clicked(self, button):
        """
        Handle select folder button click.

        Opens a file chooser dialog to select one or more folders.

        Args:
            button: The Gtk.Button that was clicked
        """
        root = self.get_root()
        if root is None or not isinstance(root, Gtk.Window):
            return

        open_paths_dialog(
            root,
            title=_("Select Folders to Scan"),
            on_selected=self._replace_selected_paths,
            select_folders=True,
            multiple=True,
            initial_folder=self._get_initial_selection_folder(),
        )

    def _get_initial_selection_folder(self) -> Gio.File | None:
        """Return the best initial folder for file chooser dialogs."""
        if not self._selected_paths:
            return None

        first_path = self._selected_paths[0]
        initial_dir = first_path if os.path.isdir(first_path) else os.path.dirname(first_path)
        if not os.path.isdir(initial_dir):
            return None
        return Gio.File.new_for_path(initial_dir)

    def _replace_selected_paths(self, paths: list[str]) -> None:
        """Replace the current selection with the paths chosen in a dialog."""
        if not paths:
            return

        self._clear_paths()
        for path in paths:
            self._add_path(path)

    def show_file_picker(self) -> None:
        """
        Show the file selection dialog.

        Public method for external callers (e.g., header bar buttons) to
        trigger the file picker. Opens a dialog to select files or folders.
        """
        self._on_select_folder_clicked(None)

    def _set_selected_path(self, path: str):
        """
        Set a single selected path, replacing any existing selection.

        This is a convenience method that clears the current selection
        and adds a single path. For adding multiple paths, use _add_path().

        Args:
            path: The file or folder path to scan
        """
        self._clear_paths()
        self._add_path(path)

    def _add_path(self, path: str) -> bool:
        """
        Add a path to the selection if not already present.

        Args:
            path: The file or folder path to add

        Returns:
            True if the path was added, False if it was a duplicate
        """
        # Normalize path for O(1) duplicate check
        normalized = os.path.normpath(path)
        if normalized in self._normalized_paths:
            return False

        self._normalized_paths.add(normalized)
        self._selected_paths.append(path)

        # Hide placeholder and add path row to listbox
        self._paths_placeholder.set_visible(False)
        row = self._create_path_row(path)
        self._paths_listbox.append(row)

        self._update_selection_header()
        return True

    def _remove_path(self, path: str) -> bool:
        """
        Remove a path from the selection.

        Args:
            path: The file or folder path to remove

        Returns:
            True if the path was removed, False if it wasn't in the list
        """
        normalized = os.path.normpath(path)
        if normalized not in self._normalized_paths:
            return False

        self._normalized_paths.discard(normalized)
        for i, existing in enumerate(self._selected_paths):
            if os.path.normpath(existing) == normalized:
                self._selected_paths.pop(i)

                # Find and remove the corresponding row from listbox
                child = self._paths_listbox.get_first_child()
                while child:
                    next_child = child.get_next_sibling()
                    # Check if this is a path row (not the placeholder)
                    if hasattr(child, "path") and os.path.normpath(child.path) == normalized:
                        self._paths_listbox.remove(child)
                        break
                    child = next_child

                # Show placeholder if no paths remain
                if not self._selected_paths:
                    self._paths_placeholder.set_visible(True)

                self._update_selection_header()
                return True
        return False

    def _clear_paths(self):
        """Clear all selected paths and reset the listbox."""
        self._selected_paths.clear()
        self._normalized_paths.clear()

        # Remove all path rows from listbox (keep placeholder)
        child = self._paths_listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            # Remove only path rows, not the placeholder
            if child != self._paths_placeholder:
                self._paths_listbox.remove(child)
            child = next_child

        # Show placeholder
        self._paths_placeholder.set_visible(True)
        self._update_selection_header()

    def get_selected_paths(self) -> list[str]:
        """
        Get the list of currently selected paths.

        Returns:
            A copy of the selected paths list
        """
        return self._selected_paths.copy()

    def _update_selection_header(self):
        """Update the selection group header and Clear All button visibility."""
        path_count = len(self._selected_paths)

        # Update group title with count
        if path_count == 0:
            self._selection_group.set_title(_("Scan Targets"))
            self._selection_group.set_description(_("Drop files here or click Add"))
        elif path_count == 1:
            self._selection_group.set_title(_("Scan Target (1)"))
            self._selection_group.set_description("")
        else:
            self._selection_group.set_title(_("Scan Targets ({count})").format(count=path_count))
            self._selection_group.set_description("")

        # Show/hide Clear All button
        self._clear_all_button.set_visible(path_count > 1)

    def _create_scan_section(self):
        """Create the scan control section."""
        scan_group = Adw.PreferencesGroup()

        # Button container
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_spacing(12)
        button_box.set_margin_top(8)
        button_box.set_margin_bottom(8)

        # Scan button
        self._scan_button = Gtk.Button()
        self._scan_button.set_label(_("Start Scan"))
        self._scan_button.set_tooltip_text(_("Start Scan (F5)"))
        self._scan_button.add_css_class("suggested-action")
        self._scan_button.set_size_request(150, -1)
        self._scan_button.connect("clicked", self._on_scan_clicked)
        button_box.append(self._scan_button)

        # EICAR Test button
        self._eicar_button = Gtk.Button()
        self._eicar_button.set_label(_("EICAR Test"))
        self._update_eicar_tooltip()
        self._eicar_button.set_size_request(120, -1)
        self._eicar_button.connect("clicked", self._on_eicar_test_clicked)
        button_box.append(self._eicar_button)

        # Cancel button - hidden initially, shown during scanning
        self._cancel_button = Gtk.Button()
        self._cancel_button.set_label(_("Cancel"))
        self._cancel_button.set_tooltip_text(_("Cancel the current scan"))
        self._cancel_button.add_css_class("destructive-action")
        self._cancel_button.set_size_request(120, -1)
        self._cancel_button.set_visible(False)
        self._cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(self._cancel_button)

        scan_group.add(button_box)

        self.append(scan_group)

    def _create_progress_section(self):
        """Create the Adwaita-styled progress section (initially hidden).

        Uses Adw.PreferencesGroup with ActionRows for a polished look that
        matches the rest of the app. The progress group contains the bar,
        current-file row, and stats row. A separate threat group appears
        only when infections are detected during a live scan.
        """
        # Container box to hold both groups
        self._progress_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._progress_section.set_visible(False)

        # --- Scan Progress group ---
        self._progress_group = Adw.PreferencesGroup()
        self._progress_group.set_title(_("Scan Progress"))

        # Progress bar inside a simple wrapper for group padding
        bar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar_box.set_margin_start(12)
        bar_box.set_margin_end(12)
        bar_box.set_margin_top(4)
        bar_box.set_margin_bottom(4)
        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.add_css_class("progress-bar-compact")
        bar_box.append(self._progress_bar)

        # Status label below the bar (percentage / "Scanning...")
        self._progress_label = Gtk.Label()
        self._progress_label.set_label(_("Scanning..."))
        self._progress_label.add_css_class("dim-label")
        self._progress_label.set_xalign(0)
        self._progress_label.set_margin_top(4)
        bar_box.append(self._progress_label)

        self._progress_group.add(bar_box)

        # Currently scanning row (visible only with live progress)
        self._current_file_row = Adw.ActionRow()
        self._current_file_row.set_title(_("Currently scanning"))
        self._current_file_row.set_subtitle(_("Waiting for scan data..."))
        self._current_file_row.set_subtitle_lines(1)
        # Spinner prefix
        self._file_spinner = Gtk.Spinner()
        self._file_spinner.set_spinning(True)
        self._current_file_row.add_prefix(self._file_spinner)
        self._current_file_row.set_visible(False)
        self._progress_group.add(self._current_file_row)

        # Stats row (visible only with live progress)
        self._stats_row = Adw.ActionRow()
        self._stats_row.set_title(_("Scanned 0 files"))
        stats_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("document-open-symbolic"))
        self._stats_row.add_prefix(stats_icon)
        self._stats_row.set_visible(False)
        self._progress_group.add(self._stats_row)

        self._progress_section.append(self._progress_group)

        # --- Threats Detected group (hidden until first threat) ---
        self._threat_group = Adw.PreferencesGroup()
        self._threat_group.set_title(_("Threats Detected"))
        self._threat_group.set_visible(False)

        # Scrolled window with max height for the threat list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(200)
        scrolled.set_propagate_natural_height(True)

        self._live_threat_list = Gtk.ListBox()
        self._live_threat_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._live_threat_list.add_css_class("boxed-list")
        scrolled.set_child(self._live_threat_list)

        self._threat_group.add(scrolled)
        self._progress_section.append(self._threat_group)

        self.append(self._progress_section)

    def _start_progress_pulse(self):
        """Start the progress bar pulsing animation."""
        if self._pulse_timeout_id is not None:
            return  # Already pulsing

        def pulse_callback():
            if self._progress_bar is not None:
                self._progress_bar.pulse()
            return True  # Continue pulsing

        self._pulse_timeout_id = GLib.timeout_add(100, pulse_callback)

    def _stop_progress_pulse(self):
        """Stop the progress bar pulsing animation and hide progress section."""
        if self._pulse_timeout_id is not None:
            GLib.source_remove(self._pulse_timeout_id)
            self._pulse_timeout_id = None

        if self._progress_section is not None:
            self._progress_section.set_visible(False)

        # Stop spinner and hide live progress rows
        if self._file_spinner is not None:
            self._file_spinner.set_spinning(False)
        if self._current_file_row is not None:
            self._current_file_row.set_visible(False)
        if self._stats_row is not None:
            self._stats_row.set_visible(False)

        # Clear and hide threat list
        if self._live_threat_list is not None:
            while True:
                row = self._live_threat_list.get_row_at_index(0)
                if row is None:
                    break
                self._live_threat_list.remove(row)
        if self._threat_group is not None:
            self._threat_group.set_visible(False)
        self._live_threat_count = 0

    def do_unmap(self):
        """
        Handle widget unmapping (being hidden or removed from the widget tree).

        Cleans up any active GLib timeout sources to prevent callbacks from
        firing on a destroyed widget.
        """
        if self._pulse_timeout_id is not None:
            GLib.source_remove(self._pulse_timeout_id)
            self._pulse_timeout_id = None
        Gtk.Box.do_unmap(self)

    def _on_parent_changed(self, widget, pspec):
        """
        Handle parent changes for visibility tracking.

        Pauses UI updates when the view is hidden to conserve resources,
        and resumes updates when the view becomes visible again.
        """
        was_visible = self._is_view_visible
        self._is_view_visible = self.get_parent() is not None

        if self._is_view_visible and not was_visible:
            self._on_view_shown()
        elif not self._is_view_visible and was_visible:
            self._on_view_hidden()

    def _on_view_hidden(self):
        """Pause UI updates when view is hidden."""
        self._updates_paused = True
        # Don't stop the pulse here - let it continue so the scan continues
        # Just pause the frequent progress updates

    def _on_view_shown(self):
        """Resume UI updates when view becomes visible."""
        self._updates_paused = False
        # Force an immediate update on next progress callback

    def _update_live_progress(
        self,
        progress: ScanProgress,
        scan_session_id: int | None = None,
        target_idx: int | None = None,
        completed_files_before_target: int | None = None,
    ):
        """
        Update the UI with live scan progress.

        This is called from the scan thread via GLib.idle_add for thread safety.
        Updates Adw.ActionRow widgets for current file, stats, and threat list.

        Args:
            progress: The ScanProgress with current scan state
            scan_session_id: Optional scan session token for stale callback filtering
            target_idx: Optional target index for stale callback filtering
            completed_files_before_target: Optional completed-file baseline for this target
        """
        # Ignore stale callbacks from a previous scan session.
        if scan_session_id is not None and scan_session_id != getattr(
            self, "_progress_session_id", scan_session_id
        ):
            return False

        # Ignore delayed callbacks from previous targets in a multi-target scan.
        if target_idx is not None and target_idx != getattr(
            self, "_current_target_idx", target_idx
        ):
            return False

        if not getattr(self, "_is_scanning", False):
            return False

        if self._updates_paused:
            return False  # Don't update UI when view is hidden

        try:
            self._apply_progress_updates(progress, completed_files_before_target)
        except Exception:
            logger.debug("Error in live progress update", exc_info=True)
        return False

    def _apply_progress_updates(
        self,
        progress: ScanProgress,
        completed_files_before_target: int | None = None,
    ):
        """Apply progress data to the Adwaita widgets.

        Separated from _update_live_progress so that any exception is caught
        and logged instead of being silently swallowed by GLib.idle_add.
        """
        # Update progress bar
        if self._progress_bar is not None:
            if progress.percentage is not None:
                # Stop pulsing — we now have deterministic progress
                if self._pulse_timeout_id is not None:
                    GLib.source_remove(self._pulse_timeout_id)
                    self._pulse_timeout_id = None
                self._progress_bar.set_fraction(progress.percentage / 100)
            # If percentage is None, keep pulsing (handled by _start_progress_pulse)

        # Update progress label with percentage and target context
        if self._progress_label is not None and progress.percentage is not None:
            pct = int(progress.percentage)
            overflow_suffix = " +" if progress.estimate_exceeded else ""
            if self._total_target_count > 1:
                self._progress_label.set_text(
                    _("Target {current} of {total} \u2014 {pct}%{overflow}").format(
                        current=self._current_target_idx,
                        total=self._total_target_count,
                        pct=pct,
                        overflow=overflow_suffix,
                    )
                )
            else:
                self._progress_label.set_text(
                    _("Scanning... {pct}%{overflow}").format(pct=pct, overflow=overflow_suffix)
                )

        # Update current file row subtitle with the file being scanned
        if self._current_file_row is not None and progress.current_file:
            display_path = self._format_path_for_display(progress.current_file)
            self._current_file_row.set_subtitle(GLib.markup_escape_text(display_path))

        # Update stats row with cumulative counts for multi-target scans
        if self._stats_row is not None:
            completed_files = (
                completed_files_before_target
                if completed_files_before_target is not None
                else self._cumulative_files_scanned
            )
            total_scanned = completed_files + progress.files_scanned

            # Handle overflow case for the stats row title
            if progress.estimate_exceeded and progress.files_total:
                self._stats_row.set_title(
                    _("Scanned {scanned} files").format(
                        scanned=f"{progress.files_scanned:,}",
                    )
                )
                if self._total_target_count > 1:
                    self._stats_row.set_subtitle(
                        _("Target {current} of {total} ({cumulative} total)").format(
                            current=self._current_target_idx,
                            total=self._total_target_count,
                            cumulative=f"{total_scanned:,}",
                        )
                    )
                else:
                    self._stats_row.set_subtitle("")
            elif self._total_target_count > 1:
                if progress.files_total:
                    self._stats_row.set_title(
                        _("Scanned {scanned} / {total} files").format(
                            scanned=f"{progress.files_scanned:,}",
                            total=f"{progress.files_total:,}",
                        )
                    )
                else:
                    self._stats_row.set_title(
                        _("Scanned {scanned} files").format(
                            scanned=f"{progress.files_scanned:,}",
                        )
                    )
                self._stats_row.set_subtitle(
                    _("Target {current} of {total} ({cumulative} total)").format(
                        current=self._current_target_idx,
                        total=self._total_target_count,
                        cumulative=f"{total_scanned:,}",
                    )
                )
            elif progress.files_total:
                self._stats_row.set_title(
                    _("Scanned {scanned} / {total} files").format(
                        scanned=f"{progress.files_scanned:,}",
                        total=f"{progress.files_total:,}",
                    )
                )
                self._stats_row.set_subtitle("")
            else:
                self._stats_row.set_title(
                    _("Scanned {scanned} files").format(
                        scanned=f"{progress.files_scanned:,}",
                    )
                )
                self._stats_row.set_subtitle("")

        # Append new threats to the live threat list
        if progress.infected_count > self._live_threat_count:
            threats = progress.infected_threats or {}
            for file_path in progress.infected_files[self._live_threat_count :]:
                threat_name = threats.get(file_path, _("Unknown threat"))
                self._append_threat_row(file_path, threat_name)
            self._live_threat_count = progress.infected_count

    def _append_threat_row(self, file_path: str, threat_name: str):
        """Append a new threat row to the live threat list.

        Args:
            file_path: Full path to the infected file
            threat_name: ClamAV threat signature name
        """
        if self._live_threat_list is None or self._threat_group is None:
            return

        row = Adw.ActionRow()
        row.set_title(Path(file_path).name)
        row.set_subtitle(threat_name)
        row.set_tooltip_text(file_path)

        icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
        icon.add_css_class("warning")
        row.add_prefix(icon)

        self._live_threat_list.append(row)

        # Update group title with count and show
        self._threat_group.set_title(
            ngettext(
                "Threats Detected ({n})",
                "Threats Detected ({n})",
                self._live_threat_count + 1,
            ).format(n=self._live_threat_count + 1)
        )
        self._threat_group.set_visible(True)

    def _format_path_for_display(self, path: str) -> str:
        """
        Format a file path for display in the progress area.

        Shows only the filename and parent directory for long paths.

        Args:
            path: The full file path

        Returns:
            A truncated path suitable for display
        """
        # Use the existing format_scan_path utility
        display_path = format_scan_path(path)

        # If still too long, show just filename
        if len(display_path) > 60:
            path_obj = Path(path)
            parent = path_obj.parent.name
            filename = path_obj.name
            if parent:
                display_path = f".../{parent}/{filename}"
            else:
                display_path = filename

            # Truncate filename if still too long
            if len(display_path) > 60:
                display_path = "..." + display_path[-57:]

        return display_path

    def _create_progress_callback(
        self,
        scan_session_id: int | None = None,
        target_idx: int | None = None,
        completed_files_before_target: int = 0,
    ):
        """
        Create a throttled progress callback for the scanner.

        Returns:
            A callback function that schedules UI updates via GLib.idle_add
            with throttling to limit updates to ~10/second. Threat detection
            events bypass the throttle since they are rare and important.
        """
        MIN_UPDATE_INTERVAL = 0.1  # 100ms between updates
        last_infected_count = 0
        last_update = 0.0

        def progress_callback(progress: ScanProgress):
            nonlocal last_infected_count, last_update
            now = time.monotonic()

            # Bypass throttle for new threat detections — these are rare
            # and must reach the UI immediately
            is_new_threat = progress.infected_count > last_infected_count
            if is_new_threat:
                last_infected_count = progress.infected_count
            elif last_update > 0 and now - last_update < MIN_UPDATE_INTERVAL:
                return  # Throttle - skip this update

            last_update = now
            self._last_progress_update = now

            # Schedule UI update on main thread
            GLib.idle_add(
                self._update_live_progress,
                progress,
                scan_session_id,
                target_idx,
                completed_files_before_target,
            )

        return progress_callback

    def _create_view_results_section(self):
        """Create the view results button section (initially hidden)."""
        self._view_results_section = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._view_results_section.set_halign(Gtk.Align.CENTER)
        self._view_results_section.set_margin_top(8)
        self._view_results_section.set_margin_bottom(8)
        self._view_results_section.set_visible(False)

        self._view_results_button = Gtk.Button()
        self._view_results_button.set_label(_("View Results"))
        self._view_results_button.add_css_class("suggested-action")
        self._view_results_button.add_css_class("pill")
        self._view_results_button.set_size_request(200, -1)
        self._view_results_button.connect("clicked", self._on_view_results_clicked)
        self._view_results_section.append(self._view_results_button)

        self.append(self._view_results_section)

    def _show_view_results(self, threat_count: int):
        """Show the view results button with appropriate label."""
        if self._view_results_button is None or self._view_results_section is None:
            return

        if threat_count > 0:
            self._view_results_button.set_label(
                ngettext(
                    "View Results ({n} Threat)",
                    "View Results ({n} Threats)",
                    threat_count,
                ).format(n=threat_count)
            )
            self._view_results_button.remove_css_class("suggested-action")
            self._view_results_button.add_css_class("destructive-action")
        else:
            self._view_results_button.set_label(_("View Results"))
            self._view_results_button.remove_css_class("destructive-action")
            self._view_results_button.add_css_class("suggested-action")

        self._view_results_section.set_visible(True)

    def _hide_view_results(self):
        """Hide the view results button."""
        if self._view_results_section is not None:
            self._view_results_section.set_visible(False)

    def _on_view_results_clicked(self, button):
        """Open the scan results dialog."""
        if self._current_result is None:
            return

        root = self.get_root()
        if root is None:
            return

        dialog = ScanResultsDialog(
            scan_result=self._current_result,
            quarantine_manager=self._quarantine_manager,
            settings_manager=self._settings_manager,
        )
        dialog.set_transient_for(root)
        dialog.present()

    def _on_scan_clicked(self, button):
        """
        Handle scan button click.

        Starts the scan operation if a path is selected.

        Args:
            button: The Gtk.Button that was clicked
        """
        if not self._selected_paths:
            self._set_status_message(
                _("Please select a file or folder to scan"),
                StatusLevel.WARNING,
            )
            return

        # Check if virus database is available before scanning
        if not self._check_database_and_prompt():
            return

        self._scan_backend_override = None
        self._scan_daemon_force_stream = False
        self._start_scanning()

    def _check_database_and_prompt(self) -> bool:
        """
        Check if virus database is available and show dialog if not.

        Returns:
            True if database is available, False if missing (dialog shown)
        """
        from ..core.clamav_detection import check_database_available

        db_available, error_msg = check_database_available()
        if not db_available:
            logger.warning("Database not available: %s", error_msg)
            self._show_database_missing_dialog()
            return False
        return True

    def _show_database_missing_dialog(self):
        """Show dialog when virus database is missing."""
        from .database_missing_dialog import DatabaseMissingDialog

        root = self.get_root()
        if root is None:
            return

        def on_dialog_response(choice: str | None):
            if choice == "download":
                app = root.get_application()
                if app is not None:
                    app.activate_action("show-update", None)

        dialog = DatabaseMissingDialog(callback=on_dialog_response)
        dialog.set_transient_for(root)
        dialog.present()

    def _on_eicar_test_clicked(self, button):
        """
        Handle EICAR test button click.

        Creates an EICAR test file in a temp directory and scans it to verify
        antivirus detection is working properly.

        Args:
            button: The Gtk.Button that was clicked
        """
        # Refresh backend-dependent UI text before running the test.
        self._update_backend_label()
        active_backend = self._scanner.get_active_backend()

        # Check if virus database is available before creating test file
        if not self._check_database_and_prompt():
            return

        try:
            # Create EICAR test file
            # In Flatpak, /tmp is sandboxed and NOT accessible to host commands.
            # Use ~/.cache/clamui/ which is accessible from both Flatpak AND host
            # via the --filesystem=host permission.
            if is_flatpak():
                cache_dir = Path.home() / ".cache" / "clamui"
                cache_dir.mkdir(parents=True, exist_ok=True)
                temp_dir = str(cache_dir)
            else:
                temp_dir = None  # Use system default
            self._eicar_temp_path = create_eicar_temp(parent_dir=temp_dir)
            # Belt-and-braces cleanup: if the app is force-quit / crashes mid-
            # scan, the normal _on_scan_complete cleanup never runs and the
            # EICAR file lingers — the next scan of that directory then flags
            # it as a real threat (UI-010). Register an atexit handler as a
            # safety net; the unregister handle is invoked on the happy path
            # to avoid a redundant double-unlink at interpreter shutdown.
            self._eicar_atexit_unregister = register_eicar_atexit_cleanup(self._eicar_temp_path)

            # The daemon fast path may ask clamd to open the temporary file
            # server-side, which can fail for fresh user-owned EICAR files.
            # Keep normal scans on the daemon backend, but force clamdscan to
            # use --stream for the self-test so the verification path is reliable.
            if active_backend == "daemon":
                self._scan_backend_override = "daemon"
                self._scan_daemon_force_stream = True
            else:
                self._scan_backend_override = None
                self._scan_daemon_force_stream = False

            # Set the EICAR file as scan target and start scan
            self._set_selected_path(self._eicar_temp_path)
            # The EICAR test path will be shown in the listbox via _set_selected_path
            self._start_scanning()

        except OSError as e:
            logger.error(f"Failed to create EICAR test file: {e}")
            self._set_status_message(
                _("Failed to create EICAR test file: {error}").format(error=e),
                StatusLevel.ERROR,
            )

    def _start_scanning(self):
        """Start the scanning process."""
        self._is_scanning = True
        self._cancel_all_requested = False
        self._progress_session_id = getattr(self, "_progress_session_id", 0) + 1
        self._scan_button.set_sensitive(False)
        self._eicar_button.set_sensitive(False)
        self._selection_group.set_sensitive(False)
        self._cancel_button.set_visible(True)

        # Reset progress tracking state
        self._last_progress_update = 0.0
        self._updates_paused = False
        self._current_target_idx = 1
        self._total_target_count = len(self._selected_paths)
        self._cumulative_files_scanned = 0
        self._live_threat_count = 0

        # Update cancel button text based on number of targets
        path_count = len(self._selected_paths)
        if path_count > 1:
            self._cancel_button.set_label(_("Cancel All"))
            self._cancel_button.set_tooltip_text(_("Cancel all remaining scans"))
        else:
            self._cancel_button.set_label(_("Cancel"))
            self._cancel_button.set_tooltip_text(_("Cancel the current scan"))

        # Dismiss any previous status banner
        self._status_banner.set_revealed(False)
        self._hide_status_details(clear_content=True)

        # Hide previous results button
        self._hide_view_results()

        # Show progress section with status message
        if self._progress_section is not None:
            show_live_progress = True
            if self._settings_manager is not None:
                show_live_progress = self._settings_manager.get("show_live_progress", True)

            if path_count == 1:
                display_path = format_scan_path(self._selected_paths[0])
                if len(display_path) > 50:
                    display_path = "..." + display_path[-47:]
                if show_live_progress:
                    self._progress_label.set_label(
                        _("Scanning {path} \u2014 File count pending").format(path=display_path)
                    )
                else:
                    self._progress_label.set_label(_("Scanning {path}").format(path=display_path))
            else:
                if show_live_progress:
                    self._progress_label.set_label(
                        _("Scanning {count} items \u2014 File count pending").format(
                            count=path_count
                        )
                    )
                else:
                    self._progress_label.set_label(
                        _("Scanning {count} items").format(count=path_count)
                    )

            # Show/hide live progress rows based on setting
            if self._current_file_row is not None:
                self._current_file_row.set_visible(show_live_progress)
                self._current_file_row.set_subtitle(_("Waiting for scan data..."))
            if self._file_spinner is not None:
                self._file_spinner.set_spinning(show_live_progress)
            if self._stats_row is not None:
                self._stats_row.set_visible(show_live_progress)
                self._stats_row.set_title(_("Scanned 0 files"))
                self._stats_row.set_subtitle("")

            # Clear any leftover threat rows
            if self._live_threat_list is not None:
                while True:
                    row = self._live_threat_list.get_row_at_index(0)
                    if row is None:
                        break
                    self._live_threat_list.remove(row)
            if self._threat_group is not None:
                self._threat_group.set_visible(False)

            self._progress_section.set_visible(True)
            self._start_progress_pulse()

        # Notify external handlers (e.g., tray menu)
        if self._on_scan_state_changed:
            self._on_scan_state_changed(self._is_scanning)

        # Run scan in background
        GLib.idle_add(self._run_scan_async)

    def _run_scan_async(self):
        """Run the scan in a background thread."""
        import threading

        thread = threading.Thread(target=self._scan_worker, daemon=True)
        thread.start()
        return False

    def _scan_worker(self):
        """
        Perform the actual scan on all selected paths.

        This runs in a background thread to avoid blocking the UI.
        Scans each selected path sequentially and aggregates results.
        """
        try:
            if not self._selected_paths:
                # Should not happen, but handle gracefully
                result = ScanResult(
                    status=ScanStatus.ERROR,
                    path="",
                    stdout="",
                    stderr="",
                    exit_code=2,
                    infected_files=[],
                    scanned_files=0,
                    scanned_dirs=0,
                    infected_count=0,
                    error_message="No paths selected for scanning",
                    threat_details=[],
                )
                GLib.idle_add(self._on_scan_complete, result)
                return

            # Check if live progress is enabled
            show_live_progress = True
            if self._settings_manager is not None:
                show_live_progress = self._settings_manager.get("show_live_progress", True)

            scan_session_id = getattr(self, "_progress_session_id", 0)

            # Get profile exclusions if a profile is selected
            profile_exclusions = None
            if self._selected_profile is not None:
                profile_exclusions = {
                    "paths": self._selected_profile.exclusions.get("paths", []),
                    "patterns": self._selected_profile.exclusions.get("patterns", []),
                }

            # Track aggregated results
            total_scanned_files = 0
            total_scanned_dirs = 0
            total_infected_count = 0
            all_infected_files: list[str] = []
            all_threat_details: list = []
            all_stdout: list[str] = []
            all_stderr: list[str] = []
            has_errors = False
            error_messages: list[str] = []
            final_status = ScanStatus.CLEAN

            target_count = len(self._selected_paths)
            backend_override = self._scan_backend_override
            daemon_force_stream = self._scan_daemon_force_stream

            for idx, target_path in enumerate(self._selected_paths, start=1):
                # Check if cancel all was requested before starting next target
                if self._cancel_all_requested:
                    logger.info(f"Cancel all requested, skipping target {idx}/{target_count}")
                    final_status = ScanStatus.CANCELLED
                    break

                completed_files_before_target = total_scanned_files

                # Update progress to show current target
                GLib.idle_add(
                    self._update_scan_progress,
                    idx,
                    target_count,
                    target_path,
                    scan_session_id,
                    completed_files_before_target,
                )

                # Create target-scoped callback so stale updates are ignored
                progress_callback = None
                if show_live_progress:
                    progress_callback = self._create_progress_callback(
                        scan_session_id,
                        idx,
                        completed_files_before_target,
                    )

                # Scan this target with progress callback if enabled
                result = self._scanner.scan_sync(
                    target_path,
                    recursive=True,
                    profile_exclusions=profile_exclusions,
                    progress_callback=progress_callback,
                    backend_override=backend_override,
                    daemon_force_stream=daemon_force_stream,
                )

                # Check if scan was cancelled (either this target or cancel all)
                if result.status == ScanStatus.CANCELLED or self._cancel_all_requested:
                    # Aggregate partial results from this cancelled target
                    total_scanned_files += result.scanned_files
                    total_scanned_dirs += result.scanned_dirs
                    total_infected_count += result.infected_count
                    all_infected_files.extend(result.infected_files)
                    all_threat_details.extend(result.threat_details)
                    final_status = ScanStatus.CANCELLED
                    break

                # Aggregate results
                total_scanned_files += result.scanned_files
                total_scanned_dirs += result.scanned_dirs
                total_infected_count += result.infected_count
                all_infected_files.extend(result.infected_files)
                all_threat_details.extend(result.threat_details)

                if result.stdout:
                    all_stdout.append(f"=== {target_path} ===\n{result.stdout}")
                if result.stderr:
                    all_stderr.append(f"=== {target_path} ===\n{result.stderr}")

                # Track status
                if result.status == ScanStatus.ERROR:
                    has_errors = True
                    if result.error_message:
                        error_messages.append(f"{target_path}: {result.error_message}")
                elif result.status == ScanStatus.INFECTED:
                    final_status = ScanStatus.INFECTED

            # Determine final status if not cancelled
            if final_status != ScanStatus.CANCELLED:
                if total_infected_count > 0:
                    final_status = ScanStatus.INFECTED
                elif has_errors:
                    final_status = ScanStatus.ERROR
                else:
                    final_status = ScanStatus.CLEAN

            # Build aggregated result
            aggregated_result = ScanResult(
                status=final_status,
                path=(
                    ", ".join(self._selected_paths) if target_count > 1 else self._selected_paths[0]
                ),
                stdout="\n\n".join(all_stdout),
                stderr="\n\n".join(all_stderr),
                exit_code=(1 if final_status == ScanStatus.INFECTED else (2 if has_errors else 0)),
                infected_files=all_infected_files,
                scanned_files=total_scanned_files,
                scanned_dirs=total_scanned_dirs,
                infected_count=total_infected_count,
                error_message="; ".join(error_messages) if error_messages else None,
                threat_details=all_threat_details,
            )

            # Schedule UI update on main thread
            GLib.idle_add(self._on_scan_complete, aggregated_result)
        except Exception as e:
            logger.error("Scan error: %s", e)
            GLib.idle_add(
                self._on_scan_error,
                str(e).encode("utf-8", errors="replace").decode("utf-8"),
            )

    def _update_scan_progress(
        self,
        current_idx: int,
        total_count: int,
        current_path: str,
        scan_session_id: int | None = None,
        completed_files_before_target: int | None = None,
    ):
        """
        Update the progress display with current scan target.

        This is called from the scan worker thread via GLib.idle_add
        to update the UI on the main thread.

        Args:
            current_idx: Current target index (1-based)
            total_count: Total number of targets
            current_path: Path currently being scanned
            scan_session_id: Optional scan session token for stale callback filtering
            completed_files_before_target: Optional completed-file baseline for this target
        """
        if scan_session_id is not None and scan_session_id != getattr(
            self, "_progress_session_id", scan_session_id
        ):
            return False

        if not getattr(self, "_is_scanning", False):
            return False

        if self._progress_label is None:
            return False

        self._current_target_idx = current_idx
        self._total_target_count = total_count
        if completed_files_before_target is not None:
            self._cumulative_files_scanned = completed_files_before_target
        # Ensure first progress update for a new target is not throttled.
        self._last_progress_update = 0.0

        # Format path for display
        display_path = format_scan_path(current_path)
        if len(display_path) > 40:
            display_path = "..." + display_path[-37:]

        if total_count == 1:
            self._progress_label.set_label(_("Scanning {path}").format(path=display_path))
        else:
            self._progress_label.set_label(
                _("Target {current} of {total}: {path}").format(
                    current=current_idx, total=total_count, path=display_path
                )
            )

        # Reset progress bar for new target — restart pulsing until
        # real progress data arrives from the scanner
        if self._progress_bar is not None:
            self._progress_bar.set_fraction(0.0)
        self._start_progress_pulse()
        return False

    def _on_scan_complete(self, result: ScanResult):
        """
        Handle scan completion.

        Updates the UI with scan results and shows the view results button.

        Args:
            result: The ScanResult object containing scan findings
        """
        # Clean up temp EICAR file (and drop the atexit safety net so it
        # doesn't fire a second unlink at interpreter shutdown).
        if self._eicar_temp_path:
            cleanup_eicar_path(self._eicar_temp_path)
            self._eicar_temp_path = ""
            self._eicar_atexit_unregister()
            self._eicar_atexit_unregister = lambda: None
        self._scan_backend_override = None
        self._scan_daemon_force_stream = False

        # Stop progress animation and hide progress section
        self._stop_progress_pulse()

        # Store the result for dialog
        self._current_result = result

        # Update scanning state
        self._is_scanning = False
        self._scan_button.set_sensitive(True)
        self._eicar_button.set_sensitive(True)
        self._selection_group.set_sensitive(True)
        self._cancel_button.set_visible(False)

        # Notify external handlers
        if self._on_scan_state_changed:
            self._on_scan_state_changed(self._is_scanning, result)

        # Show view results button and update status banner
        if result.status == ScanStatus.INFECTED:
            self._show_view_results(result.infected_count)
            self._set_status_message(
                _("Scan complete - {count} threat(s) detected").format(count=result.infected_count),
                StatusLevel.WARNING,
            )
        elif result.status == ScanStatus.CLEAN:
            self._show_view_results(0)
            if result.has_warnings:
                # Clean but with warnings about skipped files
                status_message = _(
                    "Scan complete - No threats found ({count} file(s) not accessible)"
                ).format(count=result.skipped_count)
            else:
                status_message = _("Scan complete - No threats found")
            self._set_status_message(status_message, StatusLevel.SUCCESS)
        elif result.status == ScanStatus.CANCELLED:
            self._show_view_results(result.infected_count)
            self._set_status_message(_("Scan cancelled"), StatusLevel.WARNING)
        elif result.status == ScanStatus.ERROR:
            self._show_view_results(0)
            error_detail = (
                result.error_message or result.stderr or result.stdout or _("Unknown error")
            )
            detail_content = self._build_scan_error_details(result)
            self._set_status_message(
                _("Scan error: {detail}").format(
                    detail=self._summarize_status_detail(error_detail)
                ),
                StatusLevel.ERROR,
                detail_content=(
                    detail_content if self._should_show_status_details(detail_content) else None
                ),
                detail_title=_("Detailed scan error output"),
                detail_description=_("Detailed ClamAV output from the latest failed scan"),
            )
            logger.error(
                "Scan failed: %s, stdout=%r, stderr=%r",
                error_detail,
                result.stdout,
                result.stderr,
            )
        else:
            self._show_view_results(0)
            self._set_status_message(
                _("Scan completed with status: {status}").format(status=result.status.value),
                StatusLevel.WARNING,
            )

    def _on_scan_error(self, error_msg: str):
        """
        Handle scan errors.

        Args:
            error_msg: The error message to display
        """
        # Clean up temp EICAR file (and drop the atexit safety net).
        if self._eicar_temp_path:
            cleanup_eicar_path(self._eicar_temp_path)
            self._eicar_temp_path = ""
            self._eicar_atexit_unregister()
            self._eicar_atexit_unregister = lambda: None
        self._scan_backend_override = None
        self._scan_daemon_force_stream = False

        # Stop progress animation and hide progress section
        self._stop_progress_pulse()

        self._is_scanning = False
        self._scan_button.set_sensitive(True)
        self._eicar_button.set_sensitive(True)
        self._selection_group.set_sensitive(True)
        self._cancel_button.set_visible(False)

        # Notify external handlers
        if self._on_scan_state_changed:
            self._on_scan_state_changed(self._is_scanning, None)

        detail_text = error_msg.strip()
        self._set_status_message(
            _("Scan error: {detail}").format(detail=self._summarize_status_detail(detail_text)),
            StatusLevel.ERROR,
            detail_content=(detail_text if self._should_show_status_details(detail_text) else None),
            detail_title=_("Detailed scan error output"),
            detail_description=_("Detailed application error output from the latest failed scan"),
        )

    def _on_cancel_clicked(self, button: Gtk.Button) -> None:
        """Handle cancel button click.

        For multi-target scans, this sets _cancel_all_requested to skip
        remaining targets after the current scan completes or is cancelled.
        """
        logger.info("Scan cancelled by user")
        self._cancel_all_requested = True
        self._scanner.cancel()
        # The scan thread will check _cancel_all_requested and skip remaining targets
        # _on_scan_complete will handle the UI update

    def _create_backend_indicator(self):
        """Create a small indicator showing the active scan backend."""
        self._backend_label = Gtk.Label()
        self._backend_label.set_halign(Gtk.Align.CENTER)
        self._backend_label.add_css_class("dim-label")
        self._backend_label.add_css_class("caption")
        self._update_backend_label()
        self.append(self._backend_label)

    def _get_eicar_tooltip_text(self, backend: str) -> str:
        """Get EICAR button tooltip text for the active backend."""
        return _("Run a scan with EICAR test file to verify antivirus detection")

    def _update_eicar_tooltip(self, backend: str | None = None) -> None:
        """Update EICAR tooltip text for current backend."""
        if not hasattr(self, "_eicar_button"):
            return
        backend_name = backend if backend is not None else self._scanner.get_active_backend()
        self._eicar_button.set_tooltip_text(self._get_eicar_tooltip_text(backend_name))

    def _on_scan_backend_setting_changed(self, _backend: str) -> None:
        """Refresh backend UI when the configured scan backend changes."""
        GLib.idle_add(self._refresh_backend_indicator)

    def _refresh_backend_indicator(self) -> bool:
        """Update backend-dependent UI from the current scanner settings."""
        self._update_backend_label()
        return False

    def _update_backend_label(self):
        """Update the backend label with the current backend name."""
        backend = self._scanner.get_active_backend()
        backend_names = {
            "daemon": "clamd (daemon)",
            "clamscan": "clamscan (standalone)",
        }
        backend_display = backend_names.get(backend, backend)
        self._backend_label.set_label(_("Backend: {name}").format(name=backend_display))
        self._update_eicar_tooltip(backend)

    def _create_status_bar(self):
        """Create the status banner."""
        self._status_banner = create_banner()
        self._status_banner.set_title(_("Ready to scan"))
        self._status_banner.set_button_label(_("Dismiss"))
        self._status_banner.connect("button-clicked", self._on_status_banner_dismissed)
        self.append(self._status_banner)

    def set_on_scan_state_changed(self, callback):
        """
        Set a callback for scan state changes.

        Used by the main window to update the tray menu when scanning starts/stops.

        Args:
            callback: Function to call with (is_scanning: bool) parameter
        """
        self._on_scan_state_changed = callback

    def set_scan_state_changed_callback(self, callback):
        """Alias for set_on_scan_state_changed for backwards compatibility."""
        self.set_on_scan_state_changed(callback)

    def get_selected_profile(self) -> "ScanProfile | None":
        """Return the currently selected scan profile."""
        return self._selected_profile

    def set_selected_profile(self, profile_id: str) -> bool:
        """
        Set the selected profile by ID.

        Args:
            profile_id: The ID of the profile to select

        Returns:
            True if the profile was found and selected, False otherwise
        """
        if not self._profile_dropdown or not self._profile_list:
            return False

        for idx, profile in enumerate(self._profile_list):
            if profile.id == profile_id:
                # Add 1 to account for "No Profile" option at index 0
                self._profile_dropdown.set_selected(idx + 1)
                self._selected_profile = profile
                return True

        return False

    def _start_scan(self):
        """Start the scan operation programmatically."""
        self._on_scan_clicked(None)
