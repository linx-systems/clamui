# ClamUI Close Behavior Dialog
"""
Dialog for choosing close behavior when the user closes the window.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from collections.abc import Callable

from gi.repository import Adw, Gtk

from ..core.i18n import _
from .compat import create_toolbar_view
from .utils import enable_escape_to_close


class CloseBehaviorDialog(Adw.Window):
    """
    A dialog asking the user what to do when closing the window.

    Shows two options:
    - "Minimize to tray" - Hide the window but keep the app running
    - "Quit completely" - Exit the application

    Also includes a "Remember my choice" checkbox.

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        def on_response(choice: str | None, remember: bool):
            # choice is "minimize", "quit", or None if dismissed
            pass

        dialog = CloseBehaviorDialog(callback=on_response)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    def __init__(
        self,
        callback: Callable[[str | None, bool], None],
        **kwargs,
    ):
        """
        Initialize the close behavior dialog.

        Args:
            callback: Called with (choice, remember) when user makes a choice.
                     choice is "minimize", "quit", or None if dismissed.
                     remember is True if "Remember my choice" is checked.
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
        self.set_title(_("Close Application?"))
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
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(24)

        # Question text
        question_label = Gtk.Label()
        question_label.set_markup(_("What would you like to do when closing the window?"))
        question_label.set_wrap(True)
        question_label.set_xalign(0)
        content_box.append(question_label)

        # Options group
        options_group = Adw.PreferencesGroup()

        # Minimize to tray option
        self._minimize_row = Adw.ActionRow()
        self._minimize_row.set_title(_("Minimize to tray"))
        self._minimize_row.set_subtitle(
            _("Hide the window but keep ClamUI running in the background")
        )
        self._minimize_row.set_activatable(True)

        minimize_check = Gtk.CheckButton()
        minimize_check.set_group(None)  # Will be set below
        self._minimize_row.add_prefix(minimize_check)
        self._minimize_row.set_activatable_widget(minimize_check)
        self._minimize_check = minimize_check

        options_group.add(self._minimize_row)

        # Quit option
        self._quit_row = Adw.ActionRow()
        self._quit_row.set_title(_("Quit completely"))
        self._quit_row.set_subtitle(_("Close the window and exit ClamUI"))
        self._quit_row.set_activatable(True)

        quit_check = Gtk.CheckButton()
        quit_check.set_group(minimize_check)  # Same group as minimize
        self._quit_row.add_prefix(quit_check)
        self._quit_row.set_activatable_widget(quit_check)
        self._quit_check = quit_check
        quit_check.set_active(True)  # Default to quit for quicker exit

        options_group.add(self._quit_row)

        content_box.append(options_group)

        # Remember checkbox
        remember_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        remember_box.set_margin_top(8)

        self._remember_check = Gtk.CheckButton()
        self._remember_check.set_label(_("Remember my choice"))
        remember_box.append(self._remember_check)

        content_box.append(remember_box)

        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(12)

        # Cancel button
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(cancel_button)

        # Confirm button
        self._confirm_button = Gtk.Button(label=_("Confirm"))
        self._confirm_button.add_css_class("suggested-action")
        self._confirm_button.set_sensitive(True)  # Enabled - quit is default
        self._confirm_button.connect("clicked", self._on_confirm_clicked)
        button_box.append(self._confirm_button)

        content_box.append(button_box)

        toolbar_view.set_content(content_box)
        self.set_content(toolbar_view)

        # Connect check button signals to enable confirm button
        self._minimize_check.connect("toggled", self._on_option_toggled)
        self._quit_check.connect("toggled", self._on_option_toggled)

    def _on_option_toggled(self, button):
        """Handle option toggle - enable confirm button when an option is selected."""
        has_selection = self._minimize_check.get_active() or self._quit_check.get_active()
        self._confirm_button.set_sensitive(has_selection)

    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self._choice = None
        self.close()

    def _on_confirm_clicked(self, button):
        """Handle confirm button click."""
        if self._minimize_check.get_active():
            self._choice = "minimize"
        elif self._quit_check.get_active():
            self._choice = "quit"
        else:
            self._choice = None
        self.close()

    def _on_dialog_close_request(self, window):
        """Handle dialog close request - call the callback with the result."""
        remember = self._remember_check.get_active()
        if self._callback:
            self._callback(self._choice, remember)
        return False  # Allow the window to close
