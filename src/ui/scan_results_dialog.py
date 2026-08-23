# ClamUI Scan Results Dialog
"""
Dialog component for displaying scan results with threat details and actions.
"""

import logging
import os
import threading
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ..core.clipboard import copy_to_clipboard
from ..core.i18n import _, ngettext
from ..core.quarantine import QuarantineManager, QuarantineStatus
from ..core.scanner import ScanResult, ScanStatus, ThreatDetail
from ..core.utils import format_flatpak_portal_path
from .clipboard_helper import ClipboardHelper
from .compat import create_toolbar_view, safe_add_suffix
from .file_export import TEXT_FILTER, FileExportHelper
from .utils import enable_escape_to_close, resolve_icon_name

if TYPE_CHECKING:
    from ..core.settings_manager import SettingsManager

logger = logging.getLogger(__name__)

# Pagination constants
INITIAL_DISPLAY_LIMIT = 25
LOAD_MORE_BATCH_SIZE = 25
LARGE_RESULT_THRESHOLD = 50


class ScanResultsDialog(Adw.Window):
    """
    A dialog for displaying scan results with threat details and actions.

    Provides:
    - Scan statistics summary
    - List of detected threats with severity badges
    - Per-threat actions (Quarantine, Exclude, Copy Path)
    - Bulk "Quarantine All" action

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        dialog = ScanResultsDialog(
            scan_result=result,
            quarantine_manager=quarantine_manager,
            settings_manager=settings_manager
        )
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    def __init__(
        self,
        scan_result: ScanResult,
        quarantine_manager: QuarantineManager,
        settings_manager: "SettingsManager | None" = None,
        **kwargs,
    ):
        """
        Initialize the scan results dialog.

        Args:
            scan_result: The ScanResult to display
            quarantine_manager: QuarantineManager for quarantine operations
            settings_manager: Optional SettingsManager for exclusion patterns
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._scan_result = scan_result
        self._quarantine_manager = quarantine_manager
        self._settings_manager = settings_manager

        # Pagination state
        self._displayed_threat_count = 0
        self._all_threat_details = scan_result.threat_details or []
        self._load_more_row: Gtk.ListBoxRow | None = None

        # Track unquarantined threats for bulk action
        self._unquarantined_threats: list[ThreatDetail] = list(self._all_threat_details)

        # UI references
        self._quarantine_all_button: Gtk.Button | None = None
        self._threats_list: Gtk.ListBox | None = None

        # Configure and set up the dialog
        self._setup_dialog()
        self._setup_ui()

    def _setup_dialog(self):
        """Configure the dialog properties."""
        self.set_title(_("Scan Results"))
        self.set_default_size(700, 500)

        # Configure as modal dialog
        self.set_modal(True)
        enable_escape_to_close(self)
        self.set_deletable(True)

    def _setup_ui(self):
        """Set up the dialog UI layout."""
        # Toast overlay for notifications
        self._toast_overlay = Adw.ToastOverlay()

        # Main container with toolbar view
        toolbar_view = create_toolbar_view()

        # Create header bar with actions
        header_bar = Adw.HeaderBar()

        # Copy-results button (left side). Copies to clipboard; very large
        # results are redirected to a file-export dialog.
        export_button = Gtk.Button()
        export_button.set_icon_name(resolve_icon_name("edit-copy-symbolic"))
        export_button.set_tooltip_text(_("Copy results to clipboard"))
        export_button.add_css_class("flat")
        export_button.connect("clicked", self._on_export_clicked)
        header_bar.pack_start(export_button)

        # Quarantine All button (right side, only if threats exist)
        if self._scan_result.infected_count > 0:
            self._quarantine_all_button = Gtk.Button()
            count = len(self._unquarantined_threats)
            self._quarantine_all_button.set_label(
                ngettext(
                    "Quarantine {n} Threat",
                    "Quarantine All ({n})",
                    count,
                ).format(n=count)
            )
            self._quarantine_all_button.add_css_class("suggested-action")
            self._quarantine_all_button.connect("clicked", self._on_quarantine_all_clicked)
            header_bar.pack_end(self._quarantine_all_button)

        toolbar_view.add_top_bar(header_bar)

        # Create scrolled content area
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)

        # Add statistics section
        self._create_stats_section(content_box)

        # Add threats section if there are threats
        if self._scan_result.infected_count > 0:
            self._create_threats_section(content_box)

        # Add skipped files section if there are skipped files
        if self._scan_result.skipped_count > 0:
            self._create_skipped_files_section(content_box)

        scrolled.set_child(content_box)
        toolbar_view.set_content(scrolled)

        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

    def _create_stats_section(self, parent: Gtk.Box):
        """Create the statistics section."""
        stats_group = Adw.PreferencesGroup()
        stats_group.set_title(_("Statistics"))

        # Create expander for detailed stats
        expander = Adw.ExpanderRow()
        expander.set_expanded(True)

        # Set title based on result status
        if self._scan_result.status == ScanStatus.CLEAN:
            expander.set_title(_("Scan Complete"))
            if self._scan_result.skipped_count > 0:
                expander.set_subtitle(
                    _("No threats found ({count} file(s) not accessible)").format(
                        count=self._scan_result.skipped_count
                    )
                )
            elif self._scan_result.warning_message:
                # Warnings without a skipped-file count (e.g. non-fatal scanner
                # warnings) — never render a bare "0 file(s)" subtitle.
                expander.set_subtitle(
                    _("No threats found ({warning})").format(
                        warning=GLib.markup_escape_text(self._scan_result.warning_message)
                    )
                )
            else:
                expander.set_subtitle(_("No threats found"))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("object-select-symbolic"))
            icon.add_css_class("success")
        elif self._scan_result.status == ScanStatus.INFECTED:
            threat_text = ngettext(
                "{n} threat",
                "{n} threats",
                self._scan_result.infected_count,
            ).format(n=self._scan_result.infected_count)
            expander.set_title(_("Threats Detected"))
            expander.set_subtitle(_("{threat_text} found").format(threat_text=threat_text))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
            icon.add_css_class("warning")
        elif self._scan_result.status == ScanStatus.CANCELLED:
            expander.set_title(_("Scan Cancelled"))
            if self._scan_result.infected_count > 0:
                threat_text = ngettext(
                    "{n} threat",
                    "{n} threats",
                    self._scan_result.infected_count,
                ).format(n=self._scan_result.infected_count)
                expander.set_subtitle(
                    _("Partial results - {threat_text} found").format(threat_text=threat_text)
                )
            else:
                expander.set_subtitle(_("Partial results shown"))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-information-symbolic"))
            icon.add_css_class("accent")
        else:
            expander.set_title(_("Scan Error"))
            expander.set_subtitle(
                GLib.markup_escape_text(self._scan_result.error_message or _("Unknown error"))
            )
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-error-symbolic"))
            icon.add_css_class("error")

        safe_add_suffix(expander, icon)

        # Stats content
        stats_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        stats_content.set_margin_start(12)
        stats_content.set_margin_end(12)
        stats_content.set_margin_top(8)
        stats_content.set_margin_bottom(8)

        # Add stat rows
        stats_content.append(
            self._create_stat_row(_("Files scanned:"), f"{self._scan_result.scanned_files:,}")
        )
        stats_content.append(
            self._create_stat_row(_("Directories:"), f"{self._scan_result.scanned_dirs:,}")
        )

        if self._scan_result.infected_count > 0:
            stats_content.append(
                self._create_stat_row(_("Threats found:"), str(self._scan_result.infected_count))
            )

        if self._scan_result.skipped_count > 0:
            stats_content.append(
                self._create_stat_row(_("Not accessible:"), str(self._scan_result.skipped_count))
            )

        if self._scan_result.error_message:
            stats_content.append(
                self._create_stat_row(_("Error:"), self._scan_result.error_message)
            )

        expander.add_row(stats_content)
        stats_group.add(expander)
        parent.append(stats_group)

    def _create_stat_row(self, label: str, value: str) -> Gtk.Box:
        """Create a row for displaying a statistic."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("stats-row")

        label_widget = Gtk.Label()
        label_widget.set_label(label)
        label_widget.set_xalign(0)
        label_widget.add_css_class("dim-label")
        label_widget.set_size_request(120, -1)
        row.append(label_widget)

        value_widget = Gtk.Label()
        value_widget.set_label(value)
        value_widget.set_xalign(0)
        value_widget.add_css_class("heading")
        row.append(value_widget)

        return row

    def _create_skipped_files_section(self, parent: Gtk.Box):
        """Create the skipped files section for files that couldn't be scanned."""
        skipped_group = Adw.PreferencesGroup()
        skipped_group.set_title(_("Files Not Accessible"))

        # Create expander row (collapsed by default)
        expander = Adw.ExpanderRow()
        expander.set_title(_("Permission Denied"))
        count = self._scan_result.skipped_count
        expander.set_subtitle(
            ngettext(
                "{n} file could not be scanned",
                "{n} files could not be scanned",
                count,
            ).format(n=count)
        )

        # Add info icon
        icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-information-symbolic"))
        icon.add_css_class("dim-label")
        safe_add_suffix(expander, icon)

        # Create list of skipped files
        skipped_files = self._scan_result.skipped_files or []

        # Limit the number of files shown to avoid performance issues
        max_display = 100
        display_files = skipped_files[:max_display]

        for file_path in display_files:
            row = Adw.ActionRow()
            row.set_title(GLib.markup_escape_text(file_path))
            row.add_css_class("property")
            expander.add_row(row)

        # Show truncation notice if needed
        if len(skipped_files) > max_display:
            truncate_row = Adw.ActionRow()
            truncate_row.set_title(
                _("... and {count} more").format(count=len(skipped_files) - max_display)
            )
            truncate_row.add_css_class("dim-label")
            expander.add_row(truncate_row)

        skipped_group.add(expander)
        parent.append(skipped_group)

    def _create_threats_section(self, parent: Gtk.Box):
        """Create the threats list section."""
        threats_group = Adw.PreferencesGroup()
        threats_group.set_title(_("Detected Threats"))

        # Warning banner for large result sets
        if len(self._all_threat_details) > LARGE_RESULT_THRESHOLD:
            warning_banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            warning_banner.add_css_class("large-result-warning")
            warning_banner.set_margin_bottom(8)

            warning_label = Gtk.Label()
            warning_label.set_markup(
                _(
                    "<b>Large result set:</b> Found {count} threats. Displaying first {limit}."
                ).format(
                    count=len(self._all_threat_details),
                    limit=INITIAL_DISPLAY_LIMIT,
                )
            )
            warning_label.set_wrap(True)
            warning_banner.append(warning_label)
            threats_group.add(warning_banner)

        # Threats list
        self._threats_list = Gtk.ListBox()
        self._threats_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._threats_list.add_css_class("boxed-list")

        # Load initial batch
        self._load_more_threats(INITIAL_DISPLAY_LIMIT)

        threats_group.add(self._threats_list)
        parent.append(threats_group)

    def _load_more_threats(self, count: int):
        """Load and display more threats."""
        if self._threats_list is None:
            return

        # Remove the previous "Show more" row first so new rows keep list
        # order and the button doesn't linger when the final batch exactly
        # exhausts the list.
        if self._load_more_row is not None:
            self._threats_list.remove(self._load_more_row)
            self._load_more_row = None

        start_idx = self._displayed_threat_count
        end_idx = min(start_idx + count, len(self._all_threat_details))

        for threat in self._all_threat_details[start_idx:end_idx]:
            threat_row = self._create_threat_row(threat)
            self._threats_list.append(threat_row)
            self._displayed_threat_count += 1

        # Add "Load More" button if there are more threats
        if self._displayed_threat_count < len(self._all_threat_details):
            load_more_row = Gtk.ListBoxRow()
            load_more_row.add_css_class("load-more-row")
            load_more_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            load_more_box.set_halign(Gtk.Align.CENTER)
            load_more_box.set_margin_top(8)
            load_more_box.set_margin_bottom(8)

            remaining = len(self._all_threat_details) - self._displayed_threat_count
            load_more_btn = Gtk.Button()
            load_more_btn.set_label(
                _("Show {count} more").format(count=min(LOAD_MORE_BATCH_SIZE, remaining))
            )
            load_more_btn.add_css_class("flat")
            load_more_btn.connect("clicked", self._on_load_more_clicked)
            load_more_box.append(load_more_btn)

            load_more_row.set_child(load_more_box)
            self._threats_list.append(load_more_row)
            self._load_more_row = load_more_row

    def _on_load_more_clicked(self, button):
        """Handle load more button click."""
        self._load_more_threats(LOAD_MORE_BATCH_SIZE)

    def _create_threat_row(self, threat: ThreatDetail) -> Gtk.ListBoxRow:
        """Create a list row for a single threat."""
        row = Gtk.ListBoxRow()
        row.set_activatable(False)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_margin_top(8)
        content_box.set_margin_bottom(8)

        # Header with threat name and severity
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        name_label = Gtk.Label()
        name_label.set_label(threat.threat_name)
        name_label.set_xalign(0)
        name_label.set_hexpand(True)
        name_label.set_wrap(True)
        name_label.add_css_class("monospace")
        header_box.append(name_label)

        severity_badge = Gtk.Label()
        severity_badge.set_label(threat.severity.upper())
        severity_badge.add_css_class("severity-badge")
        severity_badge.add_css_class(f"severity-{threat.severity}")
        header_box.append(severity_badge)

        content_box.append(header_box)

        # File path (format Flatpak portal paths for readability)
        path_label = Gtk.Label()
        path_label.set_label(format_flatpak_portal_path(threat.file_path))
        path_label.set_xalign(0)
        path_label.set_wrap(True)
        path_label.set_selectable(True)
        path_label.add_css_class("monospace")
        path_label.add_css_class("dim-label")
        path_label.set_size_request(400, -1)
        content_box.append(path_label)

        # Action buttons
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions_box.add_css_class("threat-actions")
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_margin_top(4)

        # Quarantine button
        quarantine_btn = Gtk.Button()
        quarantine_btn.set_label(_("Quarantine"))
        quarantine_btn.add_css_class("pill")
        quarantine_btn.add_css_class("threat-action-btn")
        quarantine_btn.connect("clicked", lambda btn: self._on_quarantine_single(btn, threat))
        actions_box.append(quarantine_btn)

        # Exclude button
        exclude_btn = Gtk.Button()
        exclude_btn.set_label(_("Exclude"))
        exclude_btn.add_css_class("pill")
        exclude_btn.add_css_class("threat-action-btn")
        exclude_btn.set_tooltip_text(_("Add file path to exclusion list"))
        exclude_btn.connect("clicked", lambda btn: self._on_add_exclusion(btn, threat))
        actions_box.append(exclude_btn)

        # Copy Path button
        copy_btn = Gtk.Button()
        copy_btn.set_label(_("Copy Path"))
        copy_btn.add_css_class("pill")
        copy_btn.add_css_class("flat")
        copy_btn.add_css_class("threat-action-btn")
        copy_btn.connect("clicked", lambda btn: self._on_copy_path(btn, threat))
        actions_box.append(copy_btn)

        content_box.append(actions_box)
        row.set_child(content_box)

        return row

    def _on_quarantine_single(self, button: Gtk.Button, threat: ThreatDetail):
        """Quarantine a single threat file."""
        result = self._quarantine_manager.quarantine_file(threat.file_path, threat.threat_name)

        if result.status == QuarantineStatus.SUCCESS:
            button.set_label(_("Quarantined"))
            button.set_sensitive(False)
            button.add_css_class("quarantined")

            # Remove from unquarantined list and update button
            if threat in self._unquarantined_threats:
                self._unquarantined_threats.remove(threat)
                self._update_quarantine_all_button()

            self._show_toast(
                _("Quarantined: {name}").format(name=os.path.basename(threat.file_path))
            )
        else:
            self._show_toast(_("Failed: {error}").format(error=result.error_message))

    def _on_add_exclusion(self, button: Gtk.Button, threat: ThreatDetail):
        """Add threat's file path to exclusion list."""
        if self._settings_manager is None:
            logger.warning("Cannot add exclusion: settings_manager is None")
            self._show_toast(_("Cannot access settings"))
            return

        # Get current exclusion patterns
        exclusions = self._settings_manager.get("exclusion_patterns", [])
        if not isinstance(exclusions, list):
            exclusions = []

        # Check if already excluded
        for excl in exclusions:
            if excl.get("pattern") == threat.file_path:
                button.set_label(_("Excluded"))
                button.set_sensitive(False)
                button.add_css_class("excluded")
                self._show_toast(_("Path already in exclusion list"))
                return

        # Add new exclusion
        new_exclusion = {
            "pattern": threat.file_path,
            "type": "file",
            "enabled": True,
        }
        exclusions.append(new_exclusion)
        self._settings_manager.set("exclusion_patterns", exclusions)

        button.set_label(_("Excluded"))
        button.set_sensitive(False)
        button.add_css_class("excluded")

        self._show_toast(
            _("Added to exclusions: {name}").format(name=os.path.basename(threat.file_path))
        )

    def _on_copy_path(self, button: Gtk.Button, threat: ThreatDetail):
        """Copy threat file path to clipboard."""
        copy_to_clipboard(threat.file_path)
        self._show_toast(_("Copied: {path}").format(path=threat.file_path))

    def _on_quarantine_all_clicked(self, button: Gtk.Button):
        """Handle quarantine all button click."""
        if not self._unquarantined_threats:
            return

        button.set_sensitive(False)
        button.set_label(_("Quarantining..."))

        threats_to_quarantine = list(self._unquarantined_threats)

        def quarantine_worker():
            success_count = 0
            error_count = 0

            for threat in threats_to_quarantine:
                result = self._quarantine_manager.quarantine_file(
                    threat.file_path, threat.threat_name
                )
                if result.status == QuarantineStatus.SUCCESS:
                    success_count += 1
                else:
                    error_count += 1
                    logger.warning(
                        f"Failed to quarantine {threat.file_path}: {result.error_message}"
                    )

            GLib.idle_add(self._on_quarantine_all_complete, success_count, error_count)

        thread = threading.Thread(target=quarantine_worker, daemon=True)
        thread.start()

    def _on_quarantine_all_complete(self, success_count: int, error_count: int):
        """Handle completion of bulk quarantine operation."""
        self._unquarantined_threats.clear()

        if self._quarantine_all_button:
            self._quarantine_all_button.set_visible(False)

        if error_count == 0:
            self._show_toast(
                ngettext(
                    "Quarantined {n} threat",
                    "Quarantined {n} threats",
                    success_count,
                ).format(n=success_count)
            )
        else:
            self._show_toast(
                _("Quarantined {success}, failed {failed}").format(
                    success=success_count, failed=error_count
                )
            )

        return False

    def _update_quarantine_all_button(self):
        """Update the quarantine all button label."""
        if self._quarantine_all_button is None:
            return

        count = len(self._unquarantined_threats)
        if count == 0:
            self._quarantine_all_button.set_visible(False)
        else:
            self._quarantine_all_button.set_label(
                ngettext(
                    "Quarantine {n} Threat",
                    "Quarantine All ({n})",
                    count,
                ).format(n=count)
            )

    def _on_export_clicked(self, button: Gtk.Button):
        """Handle export button click.

        Uses ClipboardHelper for size-aware copying. For very large scan
        outputs (>10 MB), redirects to file export instead.
        """
        if not self._scan_result.stdout:
            self._show_toast(_("No results to export"))
            return

        helper = ClipboardHelper(
            parent_widget=self,
            toast_manager=self._toast_overlay,
        )
        helper.copy_with_feedback(
            text=self._scan_result.stdout,
            success_message=_("Results copied to clipboard"),
            error_message=_("Failed to copy results"),
            on_too_large=lambda: self._export_results_to_file(button),
        )

    def _export_results_to_file(self, button: Gtk.Button):
        """Export scan results to a text file (fallback for large results)."""
        helper = FileExportHelper(
            parent_widget=self,
            dialog_title=_("Export Scan Results"),
            filename_prefix="clamui_scan_results",
            file_filter=TEXT_FILTER,
            content_generator=lambda: self._scan_result.stdout or "",
            toast_manager=self._toast_overlay,
        )
        helper.show_save_dialog()

    def _show_toast(self, message: str):
        """Show a toast notification."""
        toast = Adw.Toast.new(message)
        self._toast_overlay.add_toast(toast)
