# ClamUI Behavior Page
"""
Behavior preference page for window and application behavior settings.

This module provides the BehaviorPage class which handles the UI and logic
for managing window behavior settings like close behavior and tray integration.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ...core.flatpak import is_flatpak
from ...core.i18n import N_, _, get_available_languages
from ..compat import create_switch_row
from ..utils import resolve_icon_name
from .base import PreferencesPageMixin, create_navigation_row, styled_prefix_icon


class BehaviorPage(PreferencesPageMixin):
    """
    Behavior preference page for window and application behavior.

    This class creates and manages the UI for window behavior settings,
    including close behavior (minimize to tray vs quit) and tray integration.

    The page includes:
    - Close behavior setting (minimize to tray, quit, or always ask)
    - File manager integration (Flatpak only)
    - All settings are auto-saved when modified

    Note: This page is only shown when a system tray is available.
    """

    # Mapping between close_behavior setting values and ComboRow indices
    CLOSE_BEHAVIOR_OPTIONS = ["minimize", "quit", "ask"]
    CLOSE_BEHAVIOR_LABELS = [
        N_("Minimize to tray"),
        N_("Quit completely"),
        N_("Always ask"),
    ]

    def __init__(
        self,
        settings_manager=None,
        tray_available: bool = False,
        parent_window=None,
    ):
        """
        Initialize the BehaviorPage.

        Args:
            settings_manager: Optional SettingsManager instance for storing settings
            tray_available: Whether the system tray is available
            parent_window: Parent window for presenting dialogs
        """
        self._settings_manager = settings_manager
        self._tray_available = tray_available
        self._parent_window = parent_window
        self._close_behavior_row = None
        self._close_behavior_handler_id = None
        self._start_minimized_row = None
        self._start_minimized_handler_id = None
        self._live_progress_row = None
        self._live_progress_handler_id = None
        self._language_row = None
        self._language_handler_id = None
        self._language_codes: list[str] = []

    def create_page(self) -> Adw.PreferencesPage:
        """
        Create the Behavior preference page.

        Returns:
            Configured Adw.PreferencesPage ready to be added to preferences window
        """
        page = Adw.PreferencesPage(
            title=_("Behavior"),
            icon_name=resolve_icon_name("preferences-system-symbolic"),
        )

        # Language group (always shown)
        language_group = self._create_language_group()
        page.add(language_group)

        # Window Behavior group (only if tray is available)
        if self._tray_available:
            window_group = self._create_window_behavior_group()
            page.add(window_group)
        else:
            # Show info message when tray is not available
            info_group = Adw.PreferencesGroup()
            info_group.set_title(_("Window Behavior"))
            info_group.set_description(
                _(
                    "System tray is not available. Window behavior settings "
                    "require a system tray to be active."
                )
            )
            page.add(info_group)

        # Scan Behavior group
        scan_group = self._create_scan_behavior_group()
        page.add(scan_group)

        # File Manager Integration group (only in Flatpak)
        if is_flatpak():
            file_manager_group = self._create_file_manager_group()
            page.add(file_manager_group)

        return page

    def _create_window_behavior_group(self) -> Adw.PreferencesGroup:
        """
        Create the Window Behavior preferences group.

        Returns:
            Configured Adw.PreferencesGroup for window behavior settings
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Window Behavior"))
        group.set_description(_("Configure what happens when closing the window"))

        # Close behavior combo row
        self._close_behavior_row = Adw.ComboRow()
        self._close_behavior_row.set_title(_("When closing window"))
        self._close_behavior_row.set_subtitle(
            _("Choose what happens when you close the main window")
        )
        self._close_behavior_row.add_prefix(styled_prefix_icon("window-close-symbolic"))

        # Create string list model for options
        model = Gtk.StringList()
        for label in self.CLOSE_BEHAVIOR_LABELS:
            model.append(_(label))
        self._close_behavior_row.set_model(model)

        # Connect signal
        self._close_behavior_handler_id = self._close_behavior_row.connect(
            "notify::selected", self._on_close_behavior_changed
        )

        # Load current value
        self._load_close_behavior()

        group.add(self._close_behavior_row)

        self._start_minimized_row = create_switch_row(icon_name="window-minimize-symbolic")
        self._start_minimized_row.set_title(_("Start in System Tray"))
        self._start_minimized_row.set_subtitle(
            _("Launch in the background and show only the tray icon")
        )
        self._start_minimized_handler_id = self._start_minimized_row.connect(
            "notify::active", self._on_start_minimized_changed
        )
        self._load_start_minimized()
        group.add(self._start_minimized_row)

        return group

    def _create_scan_behavior_group(self) -> Adw.PreferencesGroup:
        """
        Create the Scan Behavior preferences group.

        Returns:
            Configured Adw.PreferencesGroup for scan behavior settings
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Scan Behavior"))
        group.set_description(_("Configure how scans are displayed"))

        # Live progress toggle
        self._live_progress_row = create_switch_row(icon_name="view-refresh-symbolic")
        self._live_progress_row.set_title(_("Show Live Scan Progress"))
        self._live_progress_row.set_subtitle(
            _("Display files being scanned in real-time with detailed progress")
        )

        # Connect signal
        self._live_progress_handler_id = self._live_progress_row.connect(
            "notify::active", self._on_live_progress_changed
        )

        # Load current value
        self._load_live_progress()

        group.add(self._live_progress_row)

        return group

    def _create_language_group(self) -> Adw.PreferencesGroup:
        """Create the Language preferences group with a language selector."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Language"))
        group.set_description(_("Override the application language (requires restart)"))

        self._language_row = Adw.ComboRow()
        self._language_row.set_title(_("Language"))
        self._language_row.set_subtitle(_("Select the display language for the interface"))
        self._language_row.add_prefix(styled_prefix_icon("preferences-desktop-locale-symbolic"))

        # Build language list: "Automatic (System)" + available translations
        available = get_available_languages()
        self._language_codes = ["auto"] + [code for code, _name in available]
        display_names = [_("Automatic (System)")] + [name for _code, name in available]

        model = Gtk.StringList()
        for name in display_names:
            model.append(name)
        self._language_row.set_model(model)

        self._language_handler_id = self._language_row.connect(
            "notify::selected", self._on_language_changed
        )

        self._load_language()

        group.add(self._language_row)
        return group

    def _load_language(self):
        """Load the current language setting into the ComboRow."""
        if self._settings_manager is None or self._language_row is None:
            return

        current = self._settings_manager.get("language", "auto")
        if current in self._language_codes:
            index = self._language_codes.index(current)
        else:
            index = 0  # "auto"

        handler_id = self._language_handler_id
        if handler_id is not None:
            self._language_row.handler_block(handler_id)
        self._language_row.set_selected(index)
        if handler_id is not None:
            self._language_row.handler_unblock(handler_id)

    def _on_language_changed(self, row, pspec):
        """Handle language ComboRow changes."""
        if self._settings_manager is None:
            return

        selected_index = row.get_selected()
        if 0 <= selected_index < len(self._language_codes):
            value = self._language_codes[selected_index]
            self._settings_manager.set("language", value)

            # Show restart-required toast on the preferences window
            parent = self._parent_window
            if parent and hasattr(parent, "add_toast"):
                toast = Adw.Toast(title=_("Restart ClamUI to apply the new language"))
                toast.set_timeout(5)
                parent.add_toast(toast)

    def _load_live_progress(self):
        """Load the current live progress setting into the SwitchRow."""
        if self._settings_manager is None or self._live_progress_row is None:
            return

        enabled = self._settings_manager.get("show_live_progress", True)

        # Block signal during load to avoid triggering save
        handler_id = self._live_progress_handler_id
        if handler_id is not None:
            self._live_progress_row.handler_block(handler_id)
        self._live_progress_row.set_active(enabled)
        if handler_id is not None:
            self._live_progress_row.handler_unblock(handler_id)

    def _on_live_progress_changed(self, row, pspec):
        """
        Handle live progress SwitchRow changes.

        Args:
            row: The SwitchRow that was changed
            pspec: The property specification (unused)
        """
        if self._settings_manager is None:
            return

        enabled = row.get_active()
        self._settings_manager.set("show_live_progress", enabled)

    def _create_file_manager_group(self) -> Adw.PreferencesGroup:
        """
        Create the File Manager Integration preferences group.

        Returns:
            Configured Adw.PreferencesGroup for file manager integration settings
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("File Manager Integration"))
        group.set_description(
            _("Add context menu actions to scan files directly from your file manager")
        )

        row = create_navigation_row(
            title=_("Configure Integration"),
            subtitle=_("Install or manage 'Scan with ClamUI' menu actions"),
            icon_name="system-file-manager-symbolic",
        )
        row.connect("activated", self._on_file_manager_integration_clicked)

        group.add(row)
        return group

    def _on_file_manager_integration_clicked(self, _row):
        """Handle file manager integration row click."""
        from ..file_manager_integration_dialog import FileManagerIntegrationDialog

        dialog = FileManagerIntegrationDialog(
            settings_manager=self._settings_manager,
        )
        dialog.set_transient_for(self._parent_window)
        dialog.present()

    def _load_start_minimized(self):
        """Load the start-in-tray setting into its switch row."""
        if self._settings_manager is None or self._start_minimized_row is None:
            return

        enabled = self._settings_manager.get("start_minimized", False)
        handler_id = self._start_minimized_handler_id
        if handler_id is not None:
            self._start_minimized_row.handler_block(handler_id)
        self._start_minimized_row.set_active(enabled)
        if handler_id is not None:
            self._start_minimized_row.handler_unblock(handler_id)

    def _on_start_minimized_changed(self, row, pspec):
        """Persist whether normal launches should start in the system tray."""
        if self._settings_manager is None:
            return

        self._settings_manager.set("start_minimized", row.get_active())

    def _load_close_behavior(self):
        """Load the current close behavior setting into the ComboRow."""
        if self._settings_manager is None or self._close_behavior_row is None:
            return

        close_behavior = self._settings_manager.get("close_behavior", None)
        # Map setting value to ComboRow index, default to "ask" if not set
        if close_behavior in self.CLOSE_BEHAVIOR_OPTIONS:
            index = self.CLOSE_BEHAVIOR_OPTIONS.index(close_behavior)
        else:
            # Default to "ask" (index 2) for unset or invalid values
            index = 2

        # Block signal during load to avoid triggering save
        handler_id = self._close_behavior_handler_id
        if handler_id is not None:
            self._close_behavior_row.handler_block(handler_id)
        self._close_behavior_row.set_selected(index)
        if handler_id is not None:
            self._close_behavior_row.handler_unblock(handler_id)

    def _on_close_behavior_changed(self, row, pspec):
        """
        Handle close behavior ComboRow changes.

        Args:
            row: The ComboRow that was changed
            pspec: The property specification (unused)
        """
        if self._settings_manager is None:
            return

        selected_index = row.get_selected()
        if 0 <= selected_index < len(self.CLOSE_BEHAVIOR_OPTIONS):
            value = self.CLOSE_BEHAVIOR_OPTIONS[selected_index]
            self._settings_manager.set("close_behavior", value)
