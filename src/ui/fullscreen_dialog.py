# ClamUI Fullscreen Log Dialog
"""
Fullscreen dialog component for displaying log content in an expanded view.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..core.i18n import N_, _
from .compat import create_toolbar_view
from .utils import enable_escape_to_close


class FullscreenLogDialog(Adw.Window):
    """
    A maximized dialog for displaying log content in fullscreen.

    Provides a read-only text view with monospace font styling for viewing
    log content in an expanded, easier-to-read format.

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        dialog = FullscreenLogDialog(
            title="Scan Results",
            content="Log content here..."
        )
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    # Placeholder text for empty content
    EMPTY_PLACEHOLDER = N_("No content to display")

    def __init__(self, title: str, content: str = "", **kwargs):
        """
        Initialize the fullscreen log dialog.

        Args:
            title: Dialog title shown in header
            content: Initial text content to display
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        # Store the title
        self._title = title

        # Configure the dialog
        self._setup_dialog()

        # Set up the UI
        self._setup_ui()

        # Set initial text content
        self.set_text_content(content)

    def _setup_dialog(self):
        """Configure the dialog properties."""
        # Set dialog title
        self.set_title(self._title)

        # Make dialog follow content size with reasonable defaults
        self.set_default_size(900, 600)

        # Configure as modal dialog
        self.set_modal(True)
        enable_escape_to_close(self)

        # Allow the dialog to be closed
        self.set_deletable(True)

    def _setup_ui(self):
        """Set up the dialog UI layout."""
        # Create main container with toolbar view for header bar
        toolbar_view = create_toolbar_view()

        # Create header bar
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Create scrolled window for text content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.add_css_class("card")
        scrolled.set_margin_start(12)
        scrolled.set_margin_end(12)
        scrolled.set_margin_top(12)
        scrolled.set_margin_bottom(12)

        # Create text view with monospace styling
        self._text_view = Gtk.TextView()
        self._text_view.set_editable(False)
        self._text_view.set_cursor_visible(False)
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.set_left_margin(12)
        self._text_view.set_right_margin(12)
        self._text_view.set_top_margin(12)
        self._text_view.set_bottom_margin(12)
        self._text_view.add_css_class("monospace")

        scrolled.set_child(self._text_view)
        toolbar_view.set_content(scrolled)

        # Set the toolbar view as the dialog content
        self.set_content(toolbar_view)

    def set_text_content(self, content: str) -> None:
        """
        Update the displayed text content.

        Args:
            content: The text content to display. If empty, shows placeholder.
        """
        buffer = self._text_view.get_buffer()

        if content:
            buffer.set_text(content)
        else:
            buffer.set_text(_(self.EMPTY_PLACEHOLDER))

    def get_text_content(self) -> str:
        """
        Get the current text content.

        Returns:
            The current text content, or empty string if only placeholder shown.
        """
        buffer = self._text_view.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        text = buffer.get_text(start, end, False)

        # Return empty string if only placeholder is shown
        if text == _(self.EMPTY_PLACEHOLDER):
            return ""

        return text

    def get_text_buffer(self) -> Gtk.TextBuffer:
        """
        Get the underlying text buffer for live updates.

        This allows external code to connect to the buffer for live
        content synchronization during active operations like scans.

        Returns:
            The Gtk.TextBuffer used by the dialog's text view.
        """
        return self._text_view.get_buffer()
