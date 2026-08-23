# ClamUI Database Missing Dialog
"""
Dialog shown when virus database is missing before a scan.

This dialog prompts the user to download the ClamAV virus database
when they attempt to scan without having the database files installed.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from collections.abc import Callable

from gi.repository import Adw, Gtk

from ..core.i18n import _
from .compat import create_toolbar_view
from .utils import enable_escape_to_close, resolve_icon_name


class DatabaseMissingDialog(Adw.Window):
    """
    Dialog prompting user to download the virus database or cancel scan.

    Shows a warning that the virus database is required for scanning,
    with options to navigate to the Update view to download it or cancel.

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        def on_response(choice: str | None):
            # choice is "download" or None if dismissed/cancelled
            if choice == "download":
                # Navigate to update view
                pass

        dialog = DatabaseMissingDialog(callback=on_response)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    def __init__(
        self,
        callback: Callable[[str | None], None],
        **kwargs,
    ):
        """
        Initialize the database missing dialog.

        Args:
            callback: Called with choice when user responds.
                     choice is "download" or None if dismissed/cancelled.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._callback = callback
        self._choice: str | None = None

        self._setup_dialog()
        self._setup_ui()

    def _setup_dialog(self):
        """Configure the dialog properties."""
        self.set_title(_("Virus Database Required"))
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

        # Warning icon and title row
        icon_title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        icon_title_box.set_halign(Gtk.Align.CENTER)

        # Warning icon
        warning_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
        warning_icon.set_pixel_size(48)
        warning_icon.add_css_class("warning")
        icon_title_box.append(warning_icon)

        content_box.append(icon_title_box)

        # Title label
        title_label = Gtk.Label()
        title_label.set_markup(_("<b>Virus Database Not Found</b>"))
        title_label.set_halign(Gtk.Align.CENTER)
        title_label.add_css_class("title-2")
        content_box.append(title_label)

        # Description label
        desc_label = Gtk.Label()
        desc_label.set_text(
            _(
                "ClamAV requires a virus database to scan files. "
                "The database needs to be downloaded before you can perform scans."
            )
        )
        desc_label.set_wrap(True)
        desc_label.set_xalign(0.5)
        desc_label.set_justify(Gtk.Justification.CENTER)
        desc_label.add_css_class("dim-label")
        content_box.append(desc_label)

        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(12)

        # Cancel button
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(cancel_button)

        # Download Now button
        download_button = Gtk.Button(label=_("Download Now"))
        download_button.add_css_class("suggested-action")
        download_button.connect("clicked", self._on_download_clicked)
        button_box.append(download_button)

        content_box.append(button_box)

        toolbar_view.set_content(content_box)
        self.set_content(toolbar_view)

    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self._choice = None
        self.close()

    def _on_download_clicked(self, button):
        """Handle download button click."""
        self._choice = "download"
        self.close()

    def _on_dialog_close_request(self, window):
        """Handle dialog close request - call the callback with the result."""
        if self._callback:
            self._callback(self._choice)
        return False  # Allow the window to close
