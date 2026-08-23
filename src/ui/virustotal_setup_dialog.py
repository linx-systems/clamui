# ClamUI VirusTotal Setup Dialog
"""
Dialog for configuring VirusTotal API key when not available.

Shown when user attempts to scan with VirusTotal but no API key is configured.
Provides options to:
- Enter an API key
- Open VirusTotal website for manual upload
- Remember the decision for future scans
"""

import logging
import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..core.i18n import _
from ..core.keyring_manager import set_api_key, validate_api_key_format
from .compat import create_switch_row, create_toolbar_view
from .utils import enable_escape_to_close, resolve_icon_name

if TYPE_CHECKING:
    from ..core.settings_manager import SettingsManager

logger = logging.getLogger(__name__)

# VirusTotal URLs
VT_API_KEY_URL = "https://www.virustotal.com/gui/my-apikey"
VT_UPLOAD_URL = "https://www.virustotal.com/gui/home/upload"


class VirusTotalSetupDialog(Adw.Window):
    """
    A dialog for configuring VirusTotal API key.

    Shown when user attempts to scan with VirusTotal but no API key is configured.
    Provides options to enter an API key, open the website, or remember the choice.

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        dialog = VirusTotalSetupDialog(
            settings_manager=settings_manager,
            on_key_saved=lambda key: start_scan(key),
            on_open_website=lambda: webbrowser.open(url),
        )
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    def __init__(
        self,
        settings_manager: "SettingsManager | None" = None,
        on_key_saved: Callable[[str], None] | None = None,
        on_open_website: Callable[[], None] | None = None,
        **kwargs,
    ):
        """
        Initialize the VirusTotal setup dialog.

        Args:
            settings_manager: SettingsManager for saving preferences.
            on_key_saved: Callback when API key is saved successfully.
                          Receives the saved API key.
            on_open_website: Callback when user chooses to open website.
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(**kwargs)

        self._settings_manager = settings_manager
        self._on_key_saved = on_key_saved
        self._on_open_website = on_open_website

        # Configure and set up the dialog
        self._setup_dialog()
        self._setup_ui()

    def _setup_dialog(self):
        """Configure the dialog properties."""
        self.set_title(_("VirusTotal Setup"))
        self.set_default_size(450, 400)

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

        # Create header bar
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Create scrolled content area
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Preferences page
        preferences_page = Adw.PreferencesPage()

        # Info section
        self._create_info_section(preferences_page)

        # API key section
        self._create_api_key_section(preferences_page)

        # Actions section
        self._create_actions_section(preferences_page)

        scrolled.set_child(preferences_page)
        toolbar_view.set_content(scrolled)

        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

    def _create_info_section(self, preferences_page: Adw.PreferencesPage):
        """Create the information section."""
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("VirusTotal API Key Required"))
        info_group.set_description(
            _(
                "To scan files with VirusTotal, you need a free API key. "
                "You can get one by creating a free account on virustotal.com."
            )
        )

        # Info row with link
        link_row = Adw.ActionRow()
        link_row.set_title(_("Get a free API key"))
        link_row.set_subtitle(_("Create an account at virustotal.com"))
        link_row.set_activatable(True)
        link_row.connect("activated", self._on_get_api_key_clicked)

        # Add chevron for navigation
        chevron = Gtk.Image.new_from_icon_name(resolve_icon_name("go-next-symbolic"))
        chevron.add_css_class("dim-label")
        link_row.add_suffix(chevron)

        info_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("network-server-symbolic"))
        info_icon.add_css_class("dim-label")
        link_row.add_prefix(info_icon)

        info_group.add(link_row)
        preferences_page.add(info_group)

    def _create_api_key_section(self, preferences_page: Adw.PreferencesPage):
        """Create the API key entry section."""
        api_key_group = Adw.PreferencesGroup()
        api_key_group.set_title(_("Enter API Key"))

        # Password entry row for API key
        # Using compatible helper for libadwaita 1.0+
        from .preferences.base import create_password_entry_row

        self._api_key_row = create_password_entry_row(_("API Key"))
        self._api_key_row.connect("changed", self._on_api_key_changed)
        self._api_key_row.connect("entry-activated", self._on_save_and_scan_clicked)
        api_key_group.add(self._api_key_row)

        # Validation message (hidden by default)
        self._validation_label = Gtk.Label()
        self._validation_label.set_halign(Gtk.Align.START)
        self._validation_label.set_margin_start(12)
        self._validation_label.set_margin_top(6)
        self._validation_label.add_css_class("error")
        self._validation_label.set_visible(False)
        api_key_group.add(self._validation_label)

        # Save and scan button
        save_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        save_box.set_halign(Gtk.Align.END)
        save_box.set_margin_top(12)

        self._save_button = Gtk.Button()
        self._save_button.set_label(_("Save & Scan"))
        self._save_button.add_css_class("suggested-action")
        self._save_button.set_sensitive(False)
        self._save_button.connect("clicked", self._on_save_and_scan_clicked)
        save_box.append(self._save_button)

        api_key_group.add(save_box)
        preferences_page.add(api_key_group)

    def _create_actions_section(self, preferences_page: Adw.PreferencesPage):
        """Create the alternative actions section."""
        actions_group = Adw.PreferencesGroup()
        actions_group.set_title(_("Alternative Options"))

        # Open website option
        website_row = Adw.ActionRow()
        website_row.set_title(_("Upload file manually"))
        website_row.set_subtitle(_("Open VirusTotal website to upload files without API key"))
        website_row.set_activatable(True)
        website_row.connect("activated", self._on_open_website_clicked)

        website_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("web-browser-symbolic"))
        website_icon.add_css_class("dim-label")
        website_row.add_prefix(website_icon)

        chevron = Gtk.Image.new_from_icon_name(resolve_icon_name("go-next-symbolic"))
        chevron.add_css_class("dim-label")
        website_row.add_suffix(chevron)

        actions_group.add(website_row)

        # Remember decision option
        self._remember_switch = create_switch_row()
        self._remember_switch.set_title(_("Remember my choice"))
        self._remember_switch.set_subtitle(_("Don't ask again when scanning without API key"))
        self._remember_switch.set_active(False)

        remember_icon = Gtk.Image.new_from_icon_name(
            resolve_icon_name("preferences-system-symbolic")
        )
        remember_icon.add_css_class("dim-label")
        self._remember_switch.add_prefix(remember_icon)

        actions_group.add(self._remember_switch)

        preferences_page.add(actions_group)

    def _on_get_api_key_clicked(self, row: Adw.ActionRow):
        """Open VirusTotal API key page."""
        try:
            webbrowser.open(VT_API_KEY_URL)
        except Exception as e:
            logger.error(f"Failed to open browser: {e}")
            self._show_toast(_("Failed to open browser"))

    def _on_api_key_changed(self, entry_row: Adw.ActionRow):
        """Handle API key entry changes."""
        api_key = entry_row.get_text().strip()

        if not api_key:
            self._save_button.set_sensitive(False)
            self._validation_label.set_visible(False)
            return

        # Validate API key format
        is_valid, error_msg = validate_api_key_format(api_key)

        if is_valid:
            self._save_button.set_sensitive(True)
            self._validation_label.set_visible(False)
        else:
            self._save_button.set_sensitive(False)
            self._validation_label.set_label(error_msg or _("Invalid API key format"))
            self._validation_label.set_visible(True)

    def _on_save_and_scan_clicked(self, widget):
        """Save the API key and trigger scan callback."""
        api_key = self._api_key_row.get_text().strip()

        if not api_key:
            return

        # Validate again
        is_valid, error_msg = validate_api_key_format(api_key)
        if not is_valid:
            self._show_toast(error_msg or _("Invalid API key"))
            return

        # Save to keyring
        success, message = set_api_key(api_key, self._settings_manager)

        if success:
            self._show_toast(message or _("API key saved"))

            # Close dialog and trigger callback
            self.close()

            if self._on_key_saved:
                self._on_key_saved(api_key)
        else:
            self._show_toast(
                _("Failed to save: {error}").format(error=message)
                if message
                else _("Failed to save API key")
            )

    def _on_open_website_clicked(self, row: Adw.ActionRow):
        """Open VirusTotal upload page."""
        # Save remember preference if enabled
        if self._remember_switch.get_active() and self._settings_manager:
            self._settings_manager.set("virustotal_remember_no_key_action", "open_website")

        try:
            webbrowser.open(VT_UPLOAD_URL)

            # Close dialog
            self.close()

            # Trigger callback if provided
            if self._on_open_website:
                self._on_open_website()

        except Exception as e:
            logger.error(f"Failed to open browser: {e}")
            self._show_toast(_("Failed to open browser"))

    def _show_toast(self, message: str):
        """Show a toast notification."""
        toast = Adw.Toast.new(message)
        self._toast_overlay.add_toast(toast)
