# ClamUI Main Window
"""
Main application window for ClamUI.

Uses GNOME Settings-style layout with AdwLeaflet for adaptive sidebar navigation.
"""

import logging
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..core.i18n import _
from .close_behavior_dialog import CloseBehaviorDialog
from .compat import create_toolbar_view
from .sidebar import NavigationSidebar
from .utils import resolve_icon_name

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    """
    Main application window for ClamUI.

    This window provides a GNOME Settings-style layout with an adaptive
    sidebar navigation using AdwLeaflet for responsive behavior.
    """

    def __init__(self, application: Adw.Application, **kwargs):
        """
        Initialize the main window.

        Args:
            application: The parent Adw.Application instance
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(application=application, **kwargs)

        # Store application reference for settings access
        self._application = application

        # Set window properties
        self.set_title("ClamUI")  # i18n: no-translate
        self.set_default_size(900, 700)
        self.set_size_request(400, 400)

        # Track current view for title updates
        self._current_view_id = "scan"

        # Set up minimize-to-tray handling
        self._setup_minimize_to_tray()

        # Create the main layout
        self._setup_ui()

    def _setup_minimize_to_tray(self) -> None:
        """
        Set up minimize-to-tray and close-to-tray functionality.

        Connects to window state changes to detect minimize events.
        When minimize_to_tray setting is enabled and tray is available,
        the window will hide to tray instead of minimizing to taskbar.

        Also connects to close-request to handle close-to-tray behavior.
        """
        # Track if we're handling minimize-to-tray to prevent recursion
        self._handling_minimize = False

        # Track if a close behavior dialog is currently shown
        self._close_dialog_pending = False

        # Track if a scan-in-progress dialog is currently shown
        self._scan_dialog_pending = False

        # Connect to the window's surface to detect state changes
        # We need to do this after the window is realized
        self.connect("realize", self._on_window_realized)

        # Connect to close-request to handle close-to-tray behavior
        self.connect("close-request", self._on_close_request)

    def _on_window_realized(self, window) -> None:
        """
        Handle window realization.

        Connects to the surface state notify signal to detect minimize events.
        """
        surface = self.get_surface()
        if surface is not None:
            # Connect to surface state changes to detect minimize
            surface.connect("notify::state", self._on_surface_state_changed)

    def _on_surface_state_changed(self, surface, pspec) -> None:
        """
        Handle surface state changes.

        When the window is minimized (MINIMIZED state set) and
        minimize_to_tray is enabled, hide the window to tray instead.

        Args:
            surface: The Gdk.Surface whose state changed
            pspec: The property specification
        """
        if self._handling_minimize:
            return

        state = surface.get_state()

        # Check if minimized state was just set
        if state & Gdk.ToplevelState.MINIMIZED and self._should_minimize_to_tray():
            self._handling_minimize = True
            try:
                # Unminimize first, then hide to tray
                # Use idle_add to defer after state change completes
                GLib.idle_add(self._do_minimize_to_tray)
            finally:
                self._handling_minimize = False

    def _should_minimize_to_tray(self) -> bool:
        """
        Check if minimize-to-tray should be used.

        Returns:
            True if minimize_to_tray setting is enabled and tray is available
        """
        # Check if we have access to settings manager
        if not hasattr(self._application, "settings_manager"):
            return False

        settings = self._application.settings_manager
        if settings is None:
            return False

        # Check if minimize_to_tray is enabled
        if not settings.get("minimize_to_tray", False):
            return False

        # Check if tray indicator is available
        if not hasattr(self._application, "tray_indicator"):
            return False

        tray = self._application.tray_indicator
        return tray is not None

    def _do_minimize_to_tray(self) -> bool:
        """
        Perform the minimize-to-tray action.

        Called from idle to ensure state changes have completed.

        Returns:
            False to remove from idle queue
        """
        # Restore window from minimized state first
        self.unminimize()

        # Then hide to tray
        self.hide_window()

        logger.debug("Window minimized to tray")

        # Update tray menu label if tray is available (window is now hidden)
        if hasattr(self._application, "tray_indicator"):
            tray = self._application.tray_indicator
            if tray is not None and hasattr(tray, "update_window_menu_label"):
                tray.update_window_menu_label(visible=False)

        return False  # Remove from idle queue

    def _on_close_request(self, window) -> bool:
        """
        Handle window close request.

        First checks if a scan is in progress (shows confirmation dialog).
        Then, depending on the close_behavior setting:
        - None (unset): Show dialog to ask user
        - "ask": Show dialog every time
        - "minimize": Hide to tray
        - "quit": Allow normal close

        Args:
            window: The window requesting close

        Returns:
            True to prevent close, False to allow close
        """
        # Check for active scan FIRST (before any other close handling)
        if self._is_scan_active() and not self._scan_dialog_pending:
            self._show_scan_in_progress_dialog()
            return True  # Prevent close while dialog is shown

        # If a scan dialog is pending, prevent additional close requests
        if self._scan_dialog_pending:
            return True

        # If tray is not available, always allow normal close
        if not self._is_tray_available():
            logger.debug("Tray not available, allowing normal close")
            return False

        # If a close behavior dialog is already pending, prevent additional requests
        if self._close_dialog_pending:
            return True

        # Get the close behavior setting
        close_behavior = self._get_close_behavior()

        if close_behavior == "minimize":
            # Hide to tray
            self._do_close_to_tray()
            return True  # Prevent close

        if close_behavior == "quit":
            # Allow normal close
            return False

        # close_behavior is None (first run) or "ask" - show dialog
        self._show_close_behavior_dialog()
        return True  # Prevent close while dialog is shown

    def _is_tray_available(self) -> bool:
        """
        Check if system tray is available.

        Returns:
            True if tray indicator is available and active
        """
        if not hasattr(self._application, "tray_indicator"):
            return False

        tray = self._application.tray_indicator
        return tray is not None

    def _get_close_behavior(self) -> str | None:
        """
        Get the current close behavior setting.

        Returns:
            "minimize", "quit", "ask", or None if not set
        """
        if not hasattr(self._application, "settings_manager"):
            return None

        settings = self._application.settings_manager
        if settings is None:
            return None

        return settings.get("close_behavior", None)

    def _do_close_to_tray(self) -> None:
        """
        Hide the window to the system tray.

        Similar to minimize-to-tray but triggered by close action.
        """
        self.hide_window()

        logger.debug("Window closed to tray")

        # Update tray menu label
        if hasattr(self._application, "tray_indicator"):
            tray = self._application.tray_indicator
            if tray is not None and hasattr(tray, "update_window_menu_label"):
                tray.update_window_menu_label(visible=False)

    def _show_close_behavior_dialog(self) -> None:
        """
        Show the close behavior dialog.

        Presents a dialog asking the user whether to minimize to tray
        or quit completely, with an option to remember the choice.
        """
        self._close_dialog_pending = True

        dialog = CloseBehaviorDialog(callback=self._on_close_behavior_dialog_response)
        dialog.set_transient_for(self)
        dialog.present()

    def _on_close_behavior_dialog_response(self, choice: str | None, remember: bool) -> None:
        """
        Handle the close behavior dialog response.

        Args:
            choice: "minimize", "quit", or None if dismissed
            remember: True if user wants to save their choice
        """
        self._close_dialog_pending = False

        if choice is None:
            # User dismissed dialog without choosing - do nothing
            logger.debug("Close dialog dismissed without choice")
            return

        # Save preference if "Remember my choice" was checked
        if remember and hasattr(self._application, "settings_manager"):
            settings = self._application.settings_manager
            if settings is not None:
                settings.set("close_behavior", choice)
                logger.info(f"Saved close behavior preference: {choice}")

        # Execute the chosen action
        if choice == "minimize":
            self._do_close_to_tray()
        elif choice == "quit":
            # Actually quit the application
            self._application.quit()

    # Scan-in-progress close handling

    def _is_scan_active(self) -> bool:
        """
        Check if a scan is currently in progress.

        Returns:
            True if the application reports an active scan
        """
        if not hasattr(self._application, "is_scan_active"):
            return False
        return self._application.is_scan_active

    def _show_scan_in_progress_dialog(self) -> None:
        """
        Show the scan in progress confirmation dialog.

        Presents a dialog warning the user that a scan is running,
        offering to cancel and close or continue scanning.
        """
        from .scan_in_progress_dialog import ScanInProgressDialog

        self._scan_dialog_pending = True

        dialog = ScanInProgressDialog(callback=self._on_scan_dialog_response)
        dialog.set_transient_for(self)
        dialog.present()

    def _on_scan_dialog_response(self, choice: str | None) -> None:
        """
        Handle the scan in progress dialog response.

        Args:
            choice: "cancel_and_close" or None if dismissed/keep scanning
        """
        self._scan_dialog_pending = False

        if choice is None:
            # User chose to keep scanning or dismissed dialog - do nothing
            logger.debug("Scan dialog dismissed, continuing scan")
            return

        if choice == "cancel_and_close":
            # Cancel the active scan
            self._cancel_active_scan()
            # Proceed with close (will go through normal close flow)
            self._proceed_with_close()

    def _cancel_active_scan(self) -> None:
        """
        Cancel the currently active scan.

        Accesses the scan view through the application and triggers cancellation.
        """
        if not hasattr(self._application, "scan_view"):
            return

        scan_view = self._application.scan_view
        if scan_view is None:
            return

        # Set cancel flag and cancel current scan
        if hasattr(scan_view, "_cancel_all_requested"):
            scan_view._cancel_all_requested = True
        if hasattr(scan_view, "_scanner") and scan_view._scanner is not None:
            scan_view._scanner.cancel()

        logger.info("Active scan cancelled due to window close")

    def _proceed_with_close(self) -> None:
        """
        Proceed with the close operation after canceling a scan.

        Re-triggers the close request which will now follow the normal
        close behavior flow (tray dialog if applicable, or quit).
        """
        # Use idle_add to allow scan cancellation to complete
        GLib.idle_add(self._do_proceed_with_close)

    def _do_proceed_with_close(self) -> bool:
        """
        Actually proceed with close after idle.

        Returns:
            False to remove from idle queue
        """
        # Re-trigger close request - scan should no longer be active
        # This will now go through the normal tray/quit flow
        if self._is_tray_available():
            # Check close behavior setting
            close_behavior = self._get_close_behavior()
            if close_behavior == "minimize":
                self._do_close_to_tray()
            elif close_behavior == "quit":
                self._application.quit()
            else:
                # Show the close behavior dialog
                self._show_close_behavior_dialog()
        else:
            # No tray, just quit
            self._application.quit()

        return False  # Remove from idle queue

    def _setup_ui(self):
        """Set up the window UI layout with AdwLeaflet for adaptive navigation."""
        # Create the header bar
        self._header_bar = self._create_header_bar()

        # Create the content area (startup banner + active view)
        self._content_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._content_area.set_vexpand(True)
        self._content_area.set_hexpand(True)

        # Create the navigation sidebar
        self._sidebar = NavigationSidebar(on_view_selected=self._on_sidebar_selection)

        # Create the leaflet for adaptive layout
        self._leaflet = Adw.Leaflet()
        self._leaflet.set_transition_type(Adw.LeafletTransitionType.SLIDE)
        self._leaflet.set_can_unfold(True)

        # Add sidebar page to leaflet
        self._sidebar_page = self._leaflet.append(self._sidebar)
        self._sidebar_page.set_name("sidebar")

        # Add separator (non-navigable so navigation skips directly to content)
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        separator_page = self._leaflet.append(separator)
        separator_page.set_navigatable(False)

        # Add content page to leaflet
        self._content_page = self._leaflet.append(self._content_area)
        self._content_page.set_name("content")

        # Connect to folded state changes for adaptive header
        self._leaflet.connect("notify::folded", self._on_leaflet_folded_changed)

        self._activity_banner = self._create_activity_banner()
        self._content_area.append(self._activity_banner)

        self._content_view_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._content_view_host.set_vexpand(True)
        self._content_view_host.set_hexpand(True)
        self._content_area.append(self._content_view_host)

        # Add toast overlay for in-app notifications
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._leaflet)

        # Use ToolbarView to properly integrate the HeaderBar as a titlebar
        toolbar_view = create_toolbar_view()
        toolbar_view.add_top_bar(self._header_bar)
        toolbar_view.set_content(self._toast_overlay)

        self.set_content(toolbar_view)

        # Show placeholder content (will be replaced with ScanView in integration)
        self._show_placeholder()

    def _create_activity_banner(self) -> Gtk.Revealer:
        """Create the transient activity banner shown for startup maintenance work."""
        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_reveal_child(False)

        banner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        banner_box.set_margin_start(12)
        banner_box.set_margin_end(12)
        banner_box.set_margin_top(8)
        banner_box.set_margin_bottom(8)
        banner_box.add_css_class("banner")

        self._activity_spinner = Gtk.Spinner()
        self._activity_spinner.set_visible(False)
        banner_box.append(self._activity_spinner)

        self._activity_label = Gtk.Label()
        self._activity_label.set_hexpand(True)
        self._activity_label.set_xalign(0)
        self._activity_label.set_wrap(True)
        banner_box.append(self._activity_label)

        revealer.set_child(banner_box)
        return revealer

    def _create_header_bar(self) -> Adw.HeaderBar:
        """
        Create the application header bar.

        Returns:
            Configured Adw.HeaderBar
        """
        header_bar = Adw.HeaderBar()

        # Enable window control buttons
        header_bar.set_show_start_title_buttons(True)
        header_bar.set_show_end_title_buttons(True)

        # Back button (hidden when not folded)
        self._back_button = Gtk.Button.new_from_icon_name(resolve_icon_name("go-previous-symbolic"))
        self._back_button.set_tooltip_text(_("Back to navigation"))
        self._back_button.connect("clicked", self._on_back_clicked)
        self._back_button.set_visible(False)  # Hidden initially
        header_bar.pack_start(self._back_button)

        # Title widget
        self._title_label = Gtk.Label(label="ClamUI")
        self._title_label.add_css_class("title")
        header_bar.set_title_widget(self._title_label)

        # Menu button on the right
        menu_button = self._create_menu_button()
        header_bar.pack_end(menu_button)

        # Scan System button (primary action)
        self._scan_system_button = Gtk.Button()
        self._scan_system_button.set_icon_name(resolve_icon_name("drive-harddisk-symbolic"))
        self._scan_system_button.set_tooltip_text(_("Scan System (Quick Scan)"))
        self._scan_system_button.add_css_class("suggested-action")
        self._scan_system_button.set_action_name("app.scan-system")
        header_bar.pack_end(self._scan_system_button)

        # Scan File button
        self._scan_file_button = Gtk.Button()
        self._scan_file_button.set_icon_name(resolve_icon_name("document-open-symbolic"))
        self._scan_file_button.set_tooltip_text(_("Scan File or Folder"))
        self._scan_file_button.set_action_name("app.scan-file")
        header_bar.pack_end(self._scan_file_button)

        return header_bar

    def _on_leaflet_folded_changed(self, leaflet, pspec) -> None:
        """
        Handle leaflet folded state changes.

        Updates the header bar to show/hide back button and update title.
        """
        is_folded = leaflet.get_folded()

        # Show back button only when folded and viewing content
        visible_child = leaflet.get_visible_child()
        show_back = is_folded and visible_child == self._content_area

        self._back_button.set_visible(show_back)

        # Update title based on folded state
        self._update_title()

    def _on_back_clicked(self, button) -> None:
        """Handle back button click - navigate to sidebar."""
        self._leaflet.navigate(Adw.NavigationDirection.BACK)
        self._back_button.set_visible(False)
        self._update_title()

    def _on_sidebar_selection(self, view_id: str) -> None:
        """
        Handle sidebar view selection.

        Args:
            view_id: The selected view identifier
        """
        self._current_view_id = view_id

        # Guard against callback during initialization (before leaflet exists)
        if not hasattr(self, "_leaflet"):
            return

        # Activate the corresponding app action
        action_name = f"show-{view_id}"
        self._application.activate_action(action_name, None)

        # If folded, navigate to content
        if self._leaflet.get_folded():
            self._leaflet.navigate(Adw.NavigationDirection.FORWARD)
            self._back_button.set_visible(True)
            self._update_title()

    def _update_title(self) -> None:
        """Update the header title based on current state."""
        is_folded = self._leaflet.get_folded()
        visible_child = self._leaflet.get_visible_child()

        if is_folded and visible_child == self._content_area:
            # Show current view name when folded and viewing content
            label = self._sidebar.get_view_label(self._current_view_id)
            self._title_label.set_label(label)
        else:
            # Show app name when sidebar is visible
            self._title_label.set_label("ClamUI")  # i18n: no-translate

    def set_active_view(self, view_name: str):
        """
        Update the sidebar selection based on the active view.

        Args:
            view_name: The name of the active view
        """
        self._current_view_id = view_name
        self._sidebar.select_view(view_name)
        self._update_title()

    def _create_menu_button(self) -> Gtk.MenuButton:
        """
        Create the primary menu button.

        Returns:
            Configured Gtk.MenuButton
        """
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name(resolve_icon_name("open-menu-symbolic"))
        menu_button.set_tooltip_text(_("Menu (F10)"))

        # Create menu model
        menu = Gio.Menu()
        menu.append(_("Preferences"), "app.preferences")
        menu.append(_("About ClamUI"), "app.about")
        menu.append(_("Quit"), "app.quit")

        menu_button.set_menu_model(menu)

        return menu_button

    def _show_placeholder(self):
        """Show placeholder content in the content area."""
        placeholder = Adw.StatusPage()
        placeholder.set_title("ClamUI")  # i18n: no-translate
        placeholder.set_description(_("ClamAV Desktop Scanner"))
        placeholder.set_icon_name(resolve_icon_name("security-high-symbolic"))
        placeholder.set_vexpand(True)

        self._content_view_host.append(placeholder)

    def set_content_view(self, view: Gtk.Widget):
        """
        Set the main content view.

        Removes any existing content and sets the new view.

        Args:
            view: The widget to display in the content area
        """
        # Remove existing content
        child = self._content_view_host.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._content_view_host.remove(child)
            child = next_child

        # Add the new view
        view.set_vexpand(True)
        view.set_hexpand(True)
        self._content_view_host.append(view)

    def add_toast(self, toast: Adw.Toast) -> None:
        """
        Add a toast notification to the window.

        Args:
            toast: The Adw.Toast instance to display
        """
        self._toast_overlay.add_toast(toast)

    def set_activity_status(self, message: str | None, *, show_spinner: bool = True) -> None:
        """Show or hide the transient startup activity banner."""
        if not hasattr(self, "_activity_banner"):
            return

        if message:
            self._activity_label.set_label(message)
            if show_spinner:
                self._activity_spinner.set_visible(True)
                self._activity_spinner.start()
            else:
                self._activity_spinner.stop()
                self._activity_spinner.set_visible(False)
            self._activity_banner.set_reveal_child(True)
            return

        self._activity_spinner.stop()
        self._activity_spinner.set_visible(False)
        self._activity_banner.set_reveal_child(False)

    @property
    def content_area(self) -> Gtk.Box:
        """
        Get the content area widget.

        Returns:
            The content area Gtk.Box
        """
        return self._content_area

    @property
    def sidebar(self) -> NavigationSidebar:
        """
        Get the navigation sidebar.

        Returns:
            The NavigationSidebar instance
        """
        return self._sidebar

    def toggle_visibility(self) -> None:
        """
        Toggle the window's visibility.

        If the window is visible, hide it. If hidden, show and present it.
        """
        if self.is_visible():
            self.hide_window()
        else:
            self.show_window()

    def show_window(self) -> None:
        """
        Show the window and bring it to front.

        Restores the window from hidden state and presents it to the user.
        """
        self.set_visible(True)
        self.present()

    def hide_window(self) -> None:
        """
        Hide the window.

        The window remains in memory but is not visible to the user.
        """
        self.set_visible(False)
