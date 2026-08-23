# ClamUI VirusTotal Results Dialog
"""
Dialog component for displaying VirusTotal scan results.

Shows scan results including detection ratio, engine details, and provides
actions like viewing on VirusTotal website and exporting results.
"""

import json
import logging
import os
import webbrowser
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..core.clipboard import copy_to_clipboard
from ..core.i18n import _
from ..core.virustotal import VTScanResult, VTScanStatus
from .compat import create_toolbar_view
from .utils import enable_escape_to_close, resolve_icon_name

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Pagination constants
INITIAL_DISPLAY_LIMIT = 25
LOAD_MORE_BATCH_SIZE = 25
LARGE_RESULT_THRESHOLD = 50


class VirusTotalResultsDialog(Adw.Window):
    """
    A dialog for displaying VirusTotal scan results.

    Provides:
    - File information (path, SHA256)
    - Detection ratio (e.g., 5/72 engines)
    - List of engine detections with categories
    - "View on VirusTotal" button
    - Export to JSON functionality

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        dialog = VirusTotalResultsDialog(vt_result=result)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    def __init__(
        self,
        vt_result: VTScanResult,
        **kwargs,
    ):
        """
        Initialize the VirusTotal results dialog.

        Args:
            vt_result: The VTScanResult to display
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._vt_result = vt_result

        # Pagination state
        self._displayed_detection_count = 0
        self._all_detections = vt_result.detection_details or []
        self._load_more_row: Gtk.ListBoxRow | None = None

        # UI references
        self._detections_list: Gtk.ListBox | None = None

        # Configure and set up the dialog
        self._setup_dialog()
        self._setup_ui()

    def _setup_dialog(self):
        """Configure the dialog properties."""
        self.set_title(_("VirusTotal Results"))
        self.set_default_size(600, 450)

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

        # Copy-results button (left side). Copies JSON to clipboard; very
        # large results are redirected to a file-export dialog.
        export_button = Gtk.Button()
        export_button.set_icon_name(resolve_icon_name("edit-copy-symbolic"))
        export_button.set_tooltip_text(_("Copy results as JSON"))
        export_button.add_css_class("flat")
        export_button.connect("clicked", self._on_export_clicked)
        header_bar.pack_start(export_button)

        # View on VirusTotal button (right side)
        if self._vt_result.permalink:
            vt_button = Gtk.Button()
            vt_button.set_label(_("View on VirusTotal"))
            vt_button.add_css_class("suggested-action")
            vt_button.connect("clicked", self._on_view_vt_clicked)
            header_bar.pack_end(vt_button)

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

        # Add summary section
        self._create_summary_section(content_box)

        # Add file info section
        self._create_file_info_section(content_box)

        # Add detections section if there are detections
        if self._vt_result.detections > 0:
            self._create_detections_section(content_box)

        scrolled.set_child(content_box)
        toolbar_view.set_content(scrolled)

        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

    def _create_summary_section(self, parent: Gtk.Box):
        """Create the scan summary section."""
        summary_group = Adw.PreferencesGroup()
        summary_group.set_title(_("Scan Summary"))

        # Create status row
        status_row = Adw.ActionRow()

        # Set title and icon based on status
        if self._vt_result.status == VTScanStatus.CLEAN:
            status_row.set_title(_("No threats detected"))
            status_row.set_subtitle(_("File appears to be safe"))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("object-select-symbolic"))
            icon.add_css_class("success")
        elif self._vt_result.status == VTScanStatus.DETECTED:
            ratio = f"{self._vt_result.detections}/{self._vt_result.total_engines}"
            status_row.set_title(
                _("{count} engines detected threats").format(count=self._vt_result.detections)
            )
            status_row.set_subtitle(_("Detection ratio: {ratio}").format(ratio=ratio))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
            icon.add_css_class("warning")
        elif self._vt_result.status == VTScanStatus.NOT_FOUND:
            status_row.set_title(_("File not in database"))
            status_row.set_subtitle(_("This file has not been scanned before"))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-information-symbolic"))
            icon.add_css_class("dim-label")
        elif self._vt_result.status == VTScanStatus.PENDING:
            status_row.set_title(_("Analysis in progress"))
            status_row.set_subtitle(_("Check back later for results"))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("emblem-synchronizing-symbolic"))
            icon.add_css_class("dim-label")
        elif self._vt_result.status == VTScanStatus.RATE_LIMITED:
            status_row.set_title(_("Rate limit exceeded"))
            status_row.set_subtitle(self._vt_result.error_message or _("Too many requests"))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
            icon.add_css_class("warning")
        elif self._vt_result.status == VTScanStatus.FILE_TOO_LARGE:
            status_row.set_title(_("File too large"))
            status_row.set_subtitle(self._vt_result.error_message or _("Maximum size is 650MB"))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-error-symbolic"))
            icon.add_css_class("error")
        else:
            status_row.set_title(_("Scan Error"))
            status_row.set_subtitle(self._vt_result.error_message or _("Unknown error"))
            icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-error-symbolic"))
            icon.add_css_class("error")

        status_row.add_prefix(icon)
        summary_group.add(status_row)

        # Add scan date if available
        if self._vt_result.scan_date:
            date_row = Adw.ActionRow()
            date_row.set_title(_("Last scanned"))
            date_row.set_subtitle(self._format_scan_date(self._vt_result.scan_date))
            date_icon = Gtk.Image.new_from_icon_name(
                resolve_icon_name("x-office-calendar-symbolic")
            )
            date_icon.add_css_class("dim-label")
            date_row.add_prefix(date_icon)
            summary_group.add(date_row)

        parent.append(summary_group)

    def _format_scan_date(self, iso_date: str) -> str:
        """Format ISO date string for display."""
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            return iso_date

    def _create_file_info_section(self, parent: Gtk.Box):
        """Create the file information section."""
        file_group = Adw.PreferencesGroup()
        file_group.set_title(_("File Information"))

        # File path row
        if self._vt_result.file_path:
            path_row = Adw.ActionRow()
            path_row.set_title(_("File"))
            path_row.set_subtitle(os.path.basename(self._vt_result.file_path))
            path_row.set_tooltip_text(self._vt_result.file_path)

            # Copy path button
            copy_path_btn = Gtk.Button()
            copy_path_btn.set_icon_name(resolve_icon_name("edit-copy-symbolic"))
            copy_path_btn.set_valign(Gtk.Align.CENTER)
            copy_path_btn.add_css_class("flat")
            copy_path_btn.set_tooltip_text(_("Copy file path"))
            copy_path_btn.connect("clicked", self._on_copy_path_clicked)
            path_row.add_suffix(copy_path_btn)

            file_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("text-x-generic-symbolic"))
            file_icon.add_css_class("dim-label")
            path_row.add_prefix(file_icon)

            file_group.add(path_row)

        # SHA256 hash row
        if self._vt_result.sha256:
            hash_row = Adw.ActionRow()
            hash_row.set_title("SHA256")  # i18n: no-translate
            # Show truncated hash in subtitle
            truncated_hash = f"{self._vt_result.sha256[:16]}...{self._vt_result.sha256[-16:]}"
            hash_row.set_subtitle(truncated_hash)
            hash_row.set_tooltip_text(self._vt_result.sha256)

            # Copy hash button
            copy_hash_btn = Gtk.Button()
            copy_hash_btn.set_icon_name(resolve_icon_name("edit-copy-symbolic"))
            copy_hash_btn.set_valign(Gtk.Align.CENTER)
            copy_hash_btn.add_css_class("flat")
            copy_hash_btn.set_tooltip_text(_("Copy SHA256 hash"))
            copy_hash_btn.connect("clicked", self._on_copy_hash_clicked)
            hash_row.add_suffix(copy_hash_btn)

            hash_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-password-symbolic"))
            hash_icon.add_css_class("dim-label")
            hash_row.add_prefix(hash_icon)

            file_group.add(hash_row)

        parent.append(file_group)

    def _create_detections_section(self, parent: Gtk.Box):
        """Create the detections list section."""
        detections_group = Adw.PreferencesGroup()
        detections_group.set_title(_("Detection Details"))

        # Warning banner for large result sets
        if len(self._all_detections) > LARGE_RESULT_THRESHOLD:
            warning_label = Gtk.Label()
            warning_label.set_markup(
                _("<small>Showing first {limit} of {total} detections</small>").format(
                    limit=INITIAL_DISPLAY_LIMIT,
                    total=len(self._all_detections),
                )
            )
            warning_label.add_css_class("dim-label")
            warning_label.set_margin_bottom(8)
            detections_group.add(warning_label)

        # Detections list
        self._detections_list = Gtk.ListBox()
        self._detections_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._detections_list.add_css_class("boxed-list")

        # Load initial batch
        self._load_more_detections(INITIAL_DISPLAY_LIMIT)

        detections_group.add(self._detections_list)
        parent.append(detections_group)

    def _load_more_detections(self, count: int):
        """Load and display more detections."""
        if self._detections_list is None:
            return

        # Remove the previous "Show more" row first so new rows keep list
        # order and the button doesn't linger when the final batch exactly
        # exhausts the list.
        if self._load_more_row is not None:
            self._detections_list.remove(self._load_more_row)
            self._load_more_row = None

        start_idx = self._displayed_detection_count
        end_idx = min(start_idx + count, len(self._all_detections))

        for detection in self._all_detections[start_idx:end_idx]:
            detection_row = self._create_detection_row(detection)
            self._detections_list.append(detection_row)
            self._displayed_detection_count += 1

        # Add "Load More" button if there are more detections
        if self._displayed_detection_count < len(self._all_detections):
            load_more_row = Gtk.ListBoxRow()
            load_more_row.add_css_class("load-more-row")
            load_more_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            load_more_box.set_halign(Gtk.Align.CENTER)
            load_more_box.set_margin_top(8)
            load_more_box.set_margin_bottom(8)

            remaining = len(self._all_detections) - self._displayed_detection_count
            load_more_btn = Gtk.Button()
            load_more_btn.set_label(
                _("Show {count} more").format(count=min(LOAD_MORE_BATCH_SIZE, remaining))
            )
            load_more_btn.add_css_class("flat")
            load_more_btn.connect("clicked", self._on_load_more_clicked)
            load_more_box.append(load_more_btn)

            load_more_row.set_child(load_more_box)
            self._detections_list.append(load_more_row)
            self._load_more_row = load_more_row

    def _on_load_more_clicked(self, button):
        """Handle load more button click."""
        self._load_more_detections(LOAD_MORE_BATCH_SIZE)

    def _create_detection_row(self, detection) -> Gtk.ListBoxRow:
        """Create a list row for a single detection."""
        row = Gtk.ListBoxRow()
        row.set_activatable(False)

        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_margin_top(8)
        content_box.set_margin_bottom(8)

        # Engine name
        name_label = Gtk.Label()
        name_label.set_label(detection.engine_name)
        name_label.set_xalign(0)
        name_label.set_hexpand(True)
        name_label.add_css_class("heading")
        content_box.append(name_label)

        # Detection result (threat name)
        if detection.result:
            result_label = Gtk.Label()
            result_label.set_label(detection.result)
            result_label.set_xalign(0)
            result_label.add_css_class("monospace")
            result_label.add_css_class("dim-label")
            result_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
            result_label.set_max_width_chars(30)
            result_label.set_tooltip_text(detection.result)
            content_box.append(result_label)

        # Category badge
        category_badge = Gtk.Label()
        category_badge.set_label(detection.category.capitalize())
        category_badge.add_css_class("caption")

        # Color based on category
        if detection.category == "malicious":
            category_badge.add_css_class("error")
        elif detection.category == "suspicious":
            category_badge.add_css_class("warning")
        else:
            category_badge.add_css_class("dim-label")

        content_box.append(category_badge)

        row.set_child(content_box)
        return row

    def _on_view_vt_clicked(self, button: Gtk.Button):
        """Open the VirusTotal permalink in browser."""
        if self._vt_result.permalink:
            try:
                webbrowser.open(self._vt_result.permalink)
            except Exception as e:
                logger.error(f"Failed to open browser: {e}")
                self._show_toast(_("Failed to open browser"))

    def _on_copy_path_clicked(self, button: Gtk.Button):
        """Copy file path to clipboard."""
        if copy_to_clipboard(self._vt_result.file_path):
            self._show_toast(_("File path copied"))
        else:
            self._show_toast(_("Failed to copy"))

    def _on_copy_hash_clicked(self, button: Gtk.Button):
        """Copy SHA256 hash to clipboard."""
        if copy_to_clipboard(self._vt_result.sha256):
            self._show_toast(_("SHA256 hash copied"))
        else:
            self._show_toast(_("Failed to copy"))

    def _on_export_clicked(self, button: Gtk.Button):
        """Export scan results to JSON and copy to clipboard."""
        export_data = {
            "file_path": self._vt_result.file_path,
            "sha256": self._vt_result.sha256,
            "status": self._vt_result.status.value,
            "detections": self._vt_result.detections,
            "total_engines": self._vt_result.total_engines,
            "scan_date": self._vt_result.scan_date,
            "permalink": self._vt_result.permalink,
            "detection_details": [
                {
                    "engine": d.engine_name,
                    "category": d.category,
                    "result": d.result,
                }
                for d in self._all_detections
            ],
        }

        if self._vt_result.error_message:
            export_data["error_message"] = self._vt_result.error_message

        json_str = json.dumps(export_data, indent=2)

        if copy_to_clipboard(json_str):
            self._show_toast(_("Results copied to clipboard as JSON"))
        else:
            self._show_toast(_("Failed to copy results"))

    def _show_toast(self, message: str):
        """Show a toast notification."""
        toast = Adw.Toast.new(message)
        self._toast_overlay.add_toast(toast)
