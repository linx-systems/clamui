# ClamUI Scan In Progress Dialog
"""
Dialog warning the user about closing during an active scan.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from collections.abc import Callable

from gi.repository import Adw, Gtk

from ..core.i18n import _
from .compat import create_toolbar_view
from .utils import enable_escape_to_close


class ScanInProgressDialog(Adw.Window):
    """
    A warning dialog shown when the user tries to close during an active scan.

    Shows two options:
    - "Keep Scanning" - Dismiss dialog and continue scanning
    - "Cancel Scan and Close" - Cancel the scan and proceed with close

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        def on_response(choice: str | None):
            # choice is "cancel_and_close" or None if dismissed/keep scanning
            pass

        dialog = ScanInProgressDialog(callback=on_response)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    def __init__(
        self,
        callback: Callable[[str | None], None] | None = None,
        **kwargs,
    ):
        """
        Initialize the scan in progress dialog.

        Args:
            callback: Called with choice when user makes a choice.
                     choice is "cancel_and_close" or None if dismissed/keep scanning.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._callback = callback
        self._choice: str | None = None

        # Configure the dialog
        self._setup_dialog()

        # Set up the UI
        self._setup_ui()

    def _setup_dialog(self):
        """Configure the dialog properties."""
        self.set_title(_("Scan in Progress"))
        self.set_default_size(400, -1)  # Natural height

        # Configure as modal dialog
        self.set_modal(True)
        enable_escape_to_close(self)
        self.set_deletable(True)

        # Connect to close-request signal for when user dismisses without choosing
        self.connect("close-request", self._on_dialog_close_request)

    def _setup_ui(self):
        """Set up the dialog UI layout."""
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

        # Warning icon and title
        icon_title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        icon_title_box.set_halign(Gtk.Align.CENTER)

        warning_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        warning_icon.set_pixel_size(48)
        warning_icon.add_css_class("warning")
        icon_title_box.append(warning_icon)

        title_label = Gtk.Label()
        title_label.set_markup(_("<b><big>Scan in Progress</big></b>"))
        title_label.set_halign(Gtk.Align.START)
        icon_title_box.append(title_label)

        content_box.append(icon_title_box)

        # Description text
        description_label = Gtk.Label()
        description_label.set_text(
            _(
                "A virus scan is currently running. If you close now, "
                "the scan will be cancelled and any partial results will be lost."
            )
        )
        description_label.set_wrap(True)
        description_label.set_xalign(0)
        description_label.set_max_width_chars(45)
        content_box.append(description_label)

        # Question text
        question_label = Gtk.Label()
        question_label.set_text(_("Do you want to cancel the scan and close?"))
        question_label.set_wrap(True)
        question_label.set_xalign(0)
        question_label.add_css_class("dim-label")
        content_box.append(question_label)

        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(12)

        # Keep Scanning button (secondary action)
        keep_scanning_button = Gtk.Button(label=_("Keep Scanning"))
        keep_scanning_button.connect("clicked", self._on_keep_scanning_clicked)
        button_box.append(keep_scanning_button)

        # Cancel and Close button (destructive action)
        cancel_close_button = Gtk.Button(label=_("Cancel Scan and Close"))
        cancel_close_button.add_css_class("destructive-action")
        cancel_close_button.connect("clicked", self._on_cancel_and_close_clicked)
        button_box.append(cancel_close_button)

        content_box.append(button_box)

        toolbar_view.set_content(content_box)
        self.set_content(toolbar_view)

    def _on_keep_scanning_clicked(self, button):
        """Handle Keep Scanning button click."""
        self._choice = None
        self.close()

    def _on_cancel_and_close_clicked(self, button):
        """Handle Cancel Scan and Close button click."""
        self._choice = "cancel_and_close"
        self.close()

    def _on_dialog_close_request(self, window):
        """Handle dialog close request - call the callback with the result."""
        if self._callback:
            self._callback(self._choice)
        return False  # Allow the window to close
