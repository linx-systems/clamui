# ClamUI File Export Helper
"""
Reusable file export dialog helper for GTK4 applications.

Provides a generic export workflow that handles:
- FileDialog setup with filters
- Async file selection callback
- File writing with error handling
- Toast notifications for success/failure

This eliminates duplication across export operations for different formats
(text, CSV, JSON, etc.) by extracting the common dialog/callback pattern.

Supports GTK 4.6+ with automatic fallback:
- GTK 4.10+: Uses modern Gtk.FileDialog API
- GTK 4.6-4.9: Falls back to Gtk.FileChooserNative
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from ..core.i18n import _

logger = logging.getLogger(__name__)

__all__ = ["CSV_FILTER", "JSON_FILTER", "TEXT_FILTER", "FileExportHelper", "FileFilter"]

# Check GTK version for FileDialog support (added in GTK 4.10)
# Handle edge cases where version detection fails (e.g., during testing with mocks)
try:
    _GTK_MINOR_VERSION = Gtk.get_minor_version()
    _HAS_FILE_DIALOG = _GTK_MINOR_VERSION >= 10
except (TypeError, AttributeError) as exc:
    # Fallback to older API if version detection fails
    logger.debug(
        "Failed to determine GTK minor version for FileDialog support; "
        "falling back to FileChooserNative. Error: %s",
        exc,
    )
    _HAS_FILE_DIALOG = False


@dataclass
class FileFilter:
    """Configuration for a file type filter in the export dialog."""

    name: str
    """Display name for the filter (e.g., "CSV Files")"""

    extension: str
    """File extension without the dot (e.g., "csv")"""

    mime_type: str | None = None
    """MIME type for the filter (e.g., "text/csv")"""


class FileExportHelper:
    """
    Helper class for file export operations with GTK4 FileDialog.

    Encapsulates the common pattern of:
    1. Creating a FileDialog with title and filters
    2. Setting a default filename with timestamp
    3. Handling async file selection callback
    4. Writing content with error handling
    5. Showing toast notifications

    This eliminates ~80 lines of duplicated code per export format.

    Example usage:
        def export_to_csv(self, button):
            helper = FileExportHelper(
                parent_widget=self,
                dialog_title="Export to CSV",
                filename_prefix="clamui_export",
                file_filter=FileFilter(name="CSV Files", extension="csv", mime_type="text/csv"),
                content_generator=lambda: self._format_as_csv(),
            )
            helper.show_save_dialog()
    """

    def __init__(
        self,
        parent_widget: Gtk.Widget,
        dialog_title: str,
        filename_prefix: str,
        file_filter: FileFilter,
        content_generator: Callable[[], str],
        success_message: str | None = None,
        toast_manager: Adw.ToastOverlay | None = None,
    ):
        """
        Initialize the file export helper.

        Args:
            parent_widget: Widget to get the parent window from (for dialog transient)
            dialog_title: Title for the save dialog (e.g., "Export Log Details")
            filename_prefix: Prefix for the generated filename (timestamp will be appended)
            file_filter: FileFilter configuration for the dialog
            content_generator: Callable that returns the content string to write.
                               Called at write time, not at dialog creation.
            success_message: Optional custom success message. If None, uses
                            "Exported to {filename}".
            toast_manager: Optional ToastOverlay for notifications. If None,
                          attempts to find one via parent_widget.get_root().
        """
        self._parent_widget = parent_widget
        self._dialog_title = dialog_title
        self._filename_prefix = filename_prefix
        self._file_filter = file_filter
        self._content_generator = content_generator
        self._success_message = success_message
        self._toast_manager = toast_manager
        # For GTK < 4.10 fallback: prevent garbage collection of FileChooserNative
        self._native_dialog: Gtk.FileChooserNative | None = None

    def show_save_dialog(self) -> None:
        """
        Open the file save dialog.

        Creates a FileDialog (GTK 4.10+) or FileChooserNative (GTK 4.6-4.9)
        with the configured title, filters, and default filename, then opens
        it asynchronously. The callback will handle file writing and notifications.
        """
        # Generate default filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = self._file_filter.extension
        default_name = f"{self._filename_prefix}_{timestamp}.{extension}"

        # Set up file filter
        gtk_filter = Gtk.FileFilter()
        gtk_filter.set_name(self._file_filter.name)
        if self._file_filter.mime_type:
            gtk_filter.add_mime_type(self._file_filter.mime_type)
        gtk_filter.add_pattern(f"*.{extension}")

        # Get the parent window
        window = self._parent_widget.get_root()

        if _HAS_FILE_DIALOG:
            # GTK 4.10+ path: Use modern FileDialog API
            self._show_file_dialog(window, gtk_filter, default_name)
        else:
            # GTK 4.6-4.9 fallback: Use FileChooserNative
            self._show_file_chooser_native(window, gtk_filter, default_name)

    def _show_file_dialog(
        self, window: Gtk.Window | None, gtk_filter: Gtk.FileFilter, default_name: str
    ) -> None:
        """Use GTK 4.10+ FileDialog API."""
        dialog = Gtk.FileDialog()
        dialog.set_title(self._dialog_title)
        dialog.set_initial_name(default_name)

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(gtk_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(gtk_filter)

        dialog.save(window, None, self._on_file_dialog_selected)

    def _on_file_dialog_selected(self, dialog: "Gtk.FileDialog", result: Gio.AsyncResult) -> None:
        """Handle FileDialog (GTK 4.10+) result."""
        try:
            file = dialog.save_finish(result)
            if file is None:
                return  # User cancelled
            self._write_to_file(file.get_path())
        except GLib.Error:
            # User cancelled the dialog
            return

    def _show_file_chooser_native(
        self, window: Gtk.Window | None, gtk_filter: Gtk.FileFilter, default_name: str
    ) -> None:
        """Use GTK 4.0+ FileChooserNative API (fallback for GTK < 4.10)."""
        dialog = Gtk.FileChooserNative.new(
            self._dialog_title,
            window,
            Gtk.FileChooserAction.SAVE,
            "_Save",
            "_Cancel",
        )
        dialog.set_current_name(default_name)
        dialog.add_filter(gtk_filter)

        # Store reference to prevent garbage collection
        self._native_dialog = dialog

        dialog.connect("response", self._on_file_chooser_response)
        dialog.show()

    def _on_file_chooser_response(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        """Handle FileChooserNative (GTK < 4.10) response."""
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file is not None:
                self._write_to_file(file.get_path())

        # Clean up reference
        self._native_dialog = None

    def _write_to_file(self, file_path: str | None) -> None:
        """
        Write content to the selected file.

        Handles extension enforcement, content generation, file writing,
        and toast notifications.

        Args:
            file_path: Path to write to, or None if invalid selection
        """
        if file_path is None:
            self._show_toast(_("Invalid file path selected"), is_error=True)
            return

        try:
            # Ensure correct extension
            extension = self._file_filter.extension
            if not file_path.endswith(f".{extension}"):
                file_path += f".{extension}"

            # Generate content
            content = self._content_generator()

            # Write to file
            with open(file_path, "w", encoding="utf-8", newline="") as f:
                f.write(content)

            # Show success feedback
            import os

            filename = os.path.basename(file_path)
            if self._success_message:
                message = self._success_message
            else:
                message = _("Exported to {filename}").format(filename=filename)
            self._show_toast(message)

        except PermissionError:
            self._show_toast(
                _("Permission denied - cannot write to selected location"), is_error=True
            )
        except OSError as e:
            self._show_toast(_("Error writing file: {error}").format(error=str(e)), is_error=True)
        except Exception as e:
            # Content generation (e.g. CSV/JSON formatting) or any other
            # unexpected failure must not propagate out of the async file
            # dialog callback as an unhandled exception — surface it to the
            # user via a toast instead of failing silently.
            logger.exception("Unexpected error during file export")
            self._show_toast(_("Error exporting file: {error}").format(error=str(e)), is_error=True)

    def _show_toast(self, message: str, is_error: bool = False) -> None:
        """
        Show a toast notification.

        Args:
            message: The message to display
            is_error: Whether this is an error message (currently unused but
                     available for future styling)
        """
        # First try the explicit toast_manager
        if self._toast_manager is not None:
            toast = Adw.Toast.new(message)
            self._toast_manager.add_toast(toast)
            return

        # Fall back to finding add_toast on the root window
        window = self._parent_widget.get_root()
        if hasattr(window, "add_toast"):
            toast = Adw.Toast.new(message)
            window.add_toast(toast)


# Pre-defined file filters for common export formats
TEXT_FILTER = FileFilter(name=_("Text Files"), extension="txt", mime_type="text/plain")
CSV_FILTER = FileFilter(name=_("CSV Files"), extension="csv", mime_type="text/csv")
JSON_FILTER = FileFilter(name=_("JSON Files"), extension="json", mime_type="application/json")
_PREDEFINED_FILTERS = (TEXT_FILTER, CSV_FILTER, JSON_FILTER)
