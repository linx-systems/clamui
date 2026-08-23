# ClamUI Database Updates Page
"""
Database Updates preference page for freshclam.conf settings.

This module provides the DatabasePage class which handles the UI and logic
for configuring ClamAV database update settings (freshclam.conf).
"""

from urllib.parse import urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

# Check GTK version for FileDialog support (added in GTK 4.10)
try:
    _HAS_FILE_DIALOG = Gtk.get_minor_version() >= 10
except (TypeError, AttributeError):
    _HAS_FILE_DIALOG = False

from ...core.clamav_detection import detect_freshclam_conf_path
from ...core.flatpak import (
    format_flatpak_portal_path,
    is_flatpak,
    is_portal_path,
    resolve_portal_path,
)
from ...core.i18n import N_, _
from ..compat import create_entry_row, create_switch_row
from ..utils import resolve_icon_name
from .base import (
    PreferencesPageMixin,
    get_widget_active,
    get_widget_int_value,
    get_widget_text,
    populate_bool_field,
    populate_int_field,
    populate_text_field,
    styled_prefix_icon,
)

# Suggested third-party signature databases (free, no registration required)
SUGGESTED_SIGNATURE_URLS = [
    {
        "url": "https://urlhaus.abuse.ch/downloads/urlhaus.ndb",
        "name": "URLhaus",
        "description": "Malware URL blocklist (updated every minute)",
    },
    {
        "url": "http://sigs.interserver.net/interserver256.hdb",
        "name": "InterServer",
        "description": "Hash-based malware signatures",
    },
    {
        "url": "http://sigs.interserver.net/interservertopline.db",
        "name": "InterServer",
        "description": "General malware detection database",
    },
    {
        "url": "http://sigs.interserver.net/shell.ldb",
        "name": "InterServer",
        "description": "Web shell and backdoor detection",
    },
]

# Third-party database providers with setup information
THIRD_PARTY_PROVIDERS = [
    {
        "name": "URLhaus",
        "icon": "security-high-symbolic",
        "description": N_("Free malware URL blocklist by abuse.ch, updated every minute"),
        "detail": N_("No registration required. Click 'Suggested' above to add."),
        "url": "https://urlhaus.abuse.ch/api/",
        "free": True,
        "registration": False,
    },
    {
        "name": "SecuriteInfo",
        "icon": "security-high-symbolic",
        "description": N_("Millions of signatures for zero-day malware, phishing, and spam"),
        "detail": N_(
            "Free registration required at securiteinfo.com. URLs contain your personal API key."
        ),
        "url": "https://www.securiteinfo.com",
        "free": True,
        "registration": True,
    },
    {
        "name": "SaneSecurity",
        "icon": "security-medium-symbolic",
        "description": N_("Macro malware, phishing, scam, and spam signatures (hourly updates)"),
        "detail": N_(
            "Requires 'fangfrisch' or 'clamav-unofficial-sigs' tool. "
            "Cannot be added as custom URL directly."
        ),
        "url": "https://sanesecurity.com",
        "free": True,
        "registration": False,
    },
    {
        "name": "InterServer",
        "icon": "security-medium-symbolic",
        "description": N_("Hash-based signatures, web shell detection, and general malware"),
        "detail": N_("No registration required. Click 'Suggested' above to add."),
        "url": "http://sigs.interserver.net",
        "free": True,
        "registration": False,
    },
]


def _parse_custom_urls(text: str) -> list[str]:
    """
    Parse pasted text into individual URLs.

    Handles:
    - Single URL
    - Multi-line URLs (newline separated)
    - Config format: "DatabaseCustomURL https://..." lines
    - Mixed content with auto prefix stripping

    Args:
        text: Raw pasted text

    Returns:
        List of cleaned URLs
    """
    urls = []
    prefix = "DatabaseCustomURL"
    valid_schemes = ("http://", "https://", "ftp://", "ftps://", "file://")

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Strip "DatabaseCustomURL " prefix if present (case-insensitive)
        if line.lower().startswith(prefix.lower()):
            line = line[len(prefix) :].strip()

        # Validate it looks like a URL
        if any(line.lower().startswith(scheme) for scheme in valid_schemes):
            urls.append(line)

    return urls


def _get_url_domain(url: str) -> str:
    """
    Extract domain from URL for display.

    Args:
        url: Full URL string

    Returns:
        Domain/hostname or empty string if parsing fails
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return ""


class DatabasePage(PreferencesPageMixin):
    """
    Database Updates preference page for freshclam.conf configuration.

    This class creates and manages the UI for configuring ClamAV database
    update settings, including paths, update behavior, and proxy settings.

    The page includes:
    - File location display for freshclam.conf
    - Paths group (database directory, log files, clamd notification)
    - Update behavior group (check frequency, database mirrors)
    - Proxy settings group (HTTP proxy configuration)

    Note: This class uses PreferencesPageMixin for shared utilities like
    permission indicators and file location displays.
    """

    @staticmethod
    def create_page(
        config_path: str, widgets_dict: dict, parent_window=None
    ) -> Adw.PreferencesPage:
        """
        Create the Database Updates preference page.

        Args:
            config_path: Path to the freshclam.conf file
            widgets_dict: Dictionary to store widget references for later access
            parent_window: Optional PreferencesWindow for detect/browse callbacks

        Returns:
            Configured Adw.PreferencesPage ready to be added to preferences window
        """
        page = Adw.PreferencesPage(
            title=_("Database Updates"),
            icon_name=resolve_icon_name("software-update-available-symbolic"),
        )

        # Create a temporary instance to use mixin methods
        # This is a workaround since these are class methods using mixin
        temp_instance = _DatabasePageHelper()

        # Set up detect/browse callbacks if parent_window is available
        on_detect = None
        on_browse = None
        if parent_window is not None:

            def _on_detect_freshclam():
                detected = detect_freshclam_conf_path()
                if detected:
                    path_row.set_subtitle(detected)
                    parent_window._freshclam_conf_path = detected
                    sm = getattr(parent_window, "_settings_manager", None)
                    if sm:
                        sm.set("freshclam_conf_path", detected)
                    parent_window._reload_freshclam_config()
                    toast = Adw.Toast.new(_("Detected: {path}").format(path=detected))
                    parent_window.add_toast(toast)
                else:
                    toast = Adw.Toast.new(_("No freshclam.conf found in known locations"))
                    parent_window.add_toast(toast)

            def _on_browse_freshclam():
                DatabasePage._browse_for_config(
                    parent_window, path_row, "freshclam_conf_path", "_freshclam_conf_path"
                )

            on_detect = _on_detect_freshclam
            on_browse = _on_browse_freshclam

        # Create file location group
        path_row = temp_instance._create_file_location_group(
            page,
            _("Configuration File"),
            config_path,
            _("freshclam.conf location"),
            on_detect=on_detect,
            on_browse=on_browse,
        )

        # Create paths group
        DatabasePage._create_paths_group(page, widgets_dict, temp_instance)

        # Create update behavior group
        DatabasePage._create_updates_group(page, widgets_dict, temp_instance)

        # Create custom signature URLs group
        DatabasePage._create_custom_urls_group(page, widgets_dict, temp_instance)

        # Create third-party providers info group
        DatabasePage._create_providers_info_group(page)

        # Create proxy settings group
        DatabasePage._create_proxy_group(page, widgets_dict, temp_instance)

        return page

    @staticmethod
    def _browse_for_config(parent_window, path_row, settings_key, attr_name):
        """
        Open a file picker to browse for a .conf config file.

        Uses Gtk.FileDialog on GTK 4.10+ with FileChooserNative fallback.

        Args:
            parent_window: The PreferencesWindow for transient parent and settings
            path_row: The Adw.ActionRow to update the subtitle on
            settings_key: Settings key to persist the selected path
            attr_name: Attribute name on parent_window to update
        """
        conf_filter = Gtk.FileFilter()
        conf_filter.set_name(_("Configuration files"))
        conf_filter.add_pattern("*.conf")

        def _apply_selection(file_path):
            if file_path:
                # In Flatpak, resolve portal paths to real host paths
                stored_path = file_path
                display_path = file_path
                if is_flatpak() and is_portal_path(file_path):
                    resolved = resolve_portal_path(file_path)
                    if resolved:
                        stored_path = resolved
                        display_path = resolved
                    else:
                        display_path = format_flatpak_portal_path(file_path)

                path_row.set_subtitle(display_path)
                setattr(parent_window, attr_name, stored_path)
                sm = getattr(parent_window, "_settings_manager", None)
                if sm:
                    sm.set(settings_key, stored_path)
                if attr_name == "_freshclam_conf_path":
                    parent_window._reload_freshclam_config()
                toast = Adw.Toast.new(_("Selected: {path}").format(path=display_path))
                parent_window.add_toast(toast)

        # In Flatpak, /etc doesn't exist inside the sandbox.
        # Skip setting initial folder so the portal presents host filesystem.
        from pathlib import Path

        initial_path = "/etc"
        if is_flatpak() or not Path(initial_path).is_dir():
            initial_path = None

        if _HAS_FILE_DIALOG:
            dialog = Gtk.FileDialog()
            dialog.set_title(_("Select Configuration File"))
            if initial_path:
                dialog.set_initial_folder(Gio.File.new_for_path(initial_path))
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(conf_filter)
            dialog.set_filters(filters)
            dialog.set_default_filter(conf_filter)

            def _on_open_finish(dlg, result):
                try:
                    gfile = dlg.open_finish(result)
                    if gfile:
                        _apply_selection(gfile.get_path())
                except GLib.Error:
                    return  # User cancelled

            dialog.open(parent_window, None, _on_open_finish)
        else:
            dialog = Gtk.FileChooserNative.new(
                _("Select Configuration File"),
                parent_window,
                Gtk.FileChooserAction.OPEN,
                _("_Select"),
                _("_Cancel"),
            )
            dialog.add_filter(conf_filter)

            def _on_response(dlg, response):
                if response == Gtk.ResponseType.ACCEPT:
                    gfile = dlg.get_file()
                    if gfile:
                        _apply_selection(gfile.get_path())

            dialog.connect("response", _on_response)
            dialog.show()

    @staticmethod
    def _create_paths_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the Paths preferences group.

        Contains settings for:
        - DatabaseDirectory: Where virus databases are stored
        - UpdateLogFile: Log file for update operations
        - NotifyClamd: Path to clamd.conf for reload notification
        - LogVerbose: Enable verbose logging
        - LogSyslog: Enable syslog logging

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Paths"))
        group.set_description(_("Configure database and log file locations"))
        group.set_header_suffix(helper._create_permission_indicator())

        # DatabaseDirectory row
        database_dir_row = create_entry_row()
        database_dir_row.set_title(_("Database Directory"))
        database_dir_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        database_dir_row.set_show_apply_button(False)
        # Add folder icon as prefix
        database_dir_row.add_prefix(styled_prefix_icon("folder-symbolic"))
        widgets_dict["DatabaseDirectory"] = database_dir_row
        group.add(database_dir_row)

        # UpdateLogFile row
        log_file_row = create_entry_row()
        log_file_row.set_title(_("Update Log File"))
        log_file_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        log_file_row.set_show_apply_button(False)
        # Add document icon as prefix
        log_file_row.add_prefix(styled_prefix_icon("text-x-generic-symbolic"))
        widgets_dict["UpdateLogFile"] = log_file_row
        group.add(log_file_row)

        # NotifyClamd row
        notify_clamd_row = create_entry_row()
        notify_clamd_row.set_title(_("Notify ClamD Config"))
        notify_clamd_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        notify_clamd_row.set_show_apply_button(False)
        # Add settings icon as prefix
        notify_clamd_row.add_prefix(styled_prefix_icon("emblem-system-symbolic"))
        widgets_dict["NotifyClamd"] = notify_clamd_row
        group.add(notify_clamd_row)

        # LogVerbose switch row
        log_verbose_row = create_switch_row("utilities-terminal-symbolic")
        log_verbose_row.set_title(_("Verbose Logging"))
        log_verbose_row.set_subtitle(_("Enable detailed logging for database updates"))
        widgets_dict["LogVerbose"] = log_verbose_row
        group.add(log_verbose_row)

        # LogSyslog switch row
        log_syslog_row = create_switch_row("utilities-terminal-symbolic")
        log_syslog_row.set_title(_("Syslog Logging"))
        log_syslog_row.set_subtitle(_("Send log messages to system log"))
        widgets_dict["LogSyslog"] = log_syslog_row
        group.add(log_syslog_row)

        page.add(group)

    @staticmethod
    def _create_updates_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the Update Behavior preferences group.

        Contains settings for:
        - Checks: Number of database update checks per day (0-50)
        - DatabaseMirror: Mirror URLs for database downloads

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Update Behavior"))
        group.set_description(_("Configure how often and where to check for updates"))
        group.set_header_suffix(helper._create_permission_indicator())

        # Checks spin row (0-50 updates per day)
        # Using compatible helper for libadwaita 1.0+
        from .base import create_spin_row

        checks_row, checks_spin = create_spin_row(
            title=_("Checks Per Day"),
            subtitle=_("Number of update checks per day (0 to disable)"),
            min_val=0,
            max_val=50,
            step=1,
        )
        checks_row.add_prefix(styled_prefix_icon("view-refresh-symbolic"))
        widgets_dict["Checks"] = checks_spin  # Store SpinButton for get/set_value()
        group.add(checks_row)

        # DatabaseMirror entry row (primary mirror)
        mirror_row = create_entry_row()
        mirror_row.set_title(_("Database Mirror"))
        mirror_row.set_input_purpose(Gtk.InputPurpose.URL)
        mirror_row.set_show_apply_button(False)
        # Add network icon as prefix
        mirror_row.add_prefix(styled_prefix_icon("network-server-symbolic"))
        widgets_dict["DatabaseMirror"] = mirror_row
        group.add(mirror_row)

        page.add(group)

    @staticmethod
    def _create_custom_urls_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the Custom Signature Databases preferences group.

        Allows users to add third-party signature database URLs (e.g., SecuriteInfo).
        Supports smart paste parsing that strips 'DatabaseCustomURL' prefixes.

        Contains:
        - List of custom URLs with remove buttons
        - Entry row for adding new URLs (single or multi-line paste)

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Custom Signature Databases"))
        group.set_description(
            _(
                "Third-party signature URLs (e.g., SecuriteInfo). "
                "Paste URLs or config lines - 'DatabaseCustomURL' prefix auto-stripped."
            )
        )
        group.set_header_suffix(helper._create_permission_indicator())

        # Initialize tracking for URL rows
        widgets_dict["_custom_url_rows"] = []
        widgets_dict["_custom_url_group"] = group

        # Entry row for adding new URLs
        entry_row = create_entry_row("list-add-symbolic")
        entry_row.set_title(_("Add URL(s)"))
        entry_row.set_subtitle(_("Paste URL or multi-line config block"))
        entry_row.set_input_purpose(Gtk.InputPurpose.URL)
        entry_row.set_show_apply_button(False)

        # Button box for Add and Suggested buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_valign(Gtk.Align.CENTER)

        # Add button
        add_button = Gtk.Button()
        add_button.set_label(_("Add"))
        add_button.set_tooltip_text(_("Add custom signature URL(s)"))
        add_button.connect(
            "clicked", DatabasePage._on_add_custom_url_clicked, entry_row, widgets_dict
        )
        button_box.append(add_button)

        # Suggested button
        suggested_button = Gtk.Button()
        suggested_button.set_label(_("Suggested"))
        suggested_button.set_tooltip_text(
            _("Add free community signature databases (URLhaus, InterServer)")
        )
        suggested_button.add_css_class("suggested-action")
        suggested_button.connect("clicked", DatabasePage._on_add_suggested_clicked, widgets_dict)
        button_box.append(suggested_button)

        entry_row.add_suffix(button_box)

        widgets_dict["_custom_url_entry"] = entry_row
        group.add(entry_row)

        page.add(group)

    @staticmethod
    def _on_add_custom_url_clicked(_button, entry_row, widgets_dict: dict):
        """
        Handle adding URLs from entry field.

        Args:
            _button: The button that was clicked (unused, required by GTK signal)
            entry_row: The entry row containing the URL text
            widgets_dict: Dictionary containing widget references
        """
        text = entry_row.get_text().strip()
        if not text:
            return

        urls = _parse_custom_urls(text)
        existing = {url for _, url in widgets_dict.get("_custom_url_rows", [])}

        for url in urls:
            if url not in existing:
                DatabasePage._add_custom_url_row(url, widgets_dict)

        entry_row.set_text("")

    @staticmethod
    def _add_custom_url_row(url: str, widgets_dict: dict):
        """
        Add a row for a custom URL with remove button.

        Args:
            url: The URL to add
            widgets_dict: Dictionary containing widget references
        """
        row = Adw.ActionRow()
        row.set_title(url)
        row.set_subtitle(_get_url_domain(url))
        row.add_prefix(styled_prefix_icon("web-browser-symbolic"))

        # Remove button
        remove_btn = Gtk.Button()
        remove_btn.set_icon_name(resolve_icon_name("user-trash-symbolic") or "user-trash-symbolic")
        remove_btn.add_css_class("flat")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.set_tooltip_text(_("Remove this URL"))
        remove_btn.connect(
            "clicked", DatabasePage._on_remove_custom_url_clicked, row, url, widgets_dict
        )
        row.add_suffix(remove_btn)

        group = widgets_dict.get("_custom_url_group")
        if group:
            # Insert before the entry row (entry row is always last)
            # We use add() which appends, so we need to reorder
            # For simplicity, just add to the group - GTK will handle ordering
            group.add(row)

        widgets_dict["_custom_url_rows"].append((row, url))

    @staticmethod
    def _on_remove_custom_url_clicked(_button, row, url: str, widgets_dict: dict):
        """
        Remove a custom URL row.

        Args:
            _button: The button that was clicked (unused, required by GTK signal)
            row: The row to remove
            url: The URL being removed
            widgets_dict: Dictionary containing widget references
        """
        group = widgets_dict.get("_custom_url_group")
        if group:
            group.remove(row)

        widgets_dict["_custom_url_rows"] = [
            (r, u) for r, u in widgets_dict.get("_custom_url_rows", []) if u != url
        ]

    @staticmethod
    def _on_add_suggested_clicked(_button, widgets_dict: dict):
        """
        Handle adding suggested signature URLs.

        Adds free, community-maintained signature databases that don't require
        registration (e.g., URLhaus).

        Args:
            _button: The button that was clicked (unused, required by GTK signal)
            widgets_dict: Dictionary containing widget references
        """
        existing = {url for _, url in widgets_dict.get("_custom_url_rows", [])}

        for sig in SUGGESTED_SIGNATURE_URLS:
            url = sig["url"]
            if url not in existing:
                DatabasePage._add_custom_url_row(url, widgets_dict)

    @staticmethod
    def _create_providers_info_group(page: Adw.PreferencesPage):
        """
        Create an informational group about popular third-party database providers.

        Displays provider name, description, registration requirements,
        and website URL for each provider in THIRD_PARTY_PROVIDERS.

        Args:
            page: The preferences page to add the group to
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Popular Signature Providers"))
        group.set_description(
            _(
                "Third-party databases can significantly improve detection rates. "
                "Providers marked with a key icon require free registration."
            )
        )

        for provider in THIRD_PARTY_PROVIDERS:
            row = Adw.ActionRow()
            row.set_title(provider["name"])

            # Build subtitle with description and registration note
            subtitle_parts = [_(provider["description"])]
            if provider["registration"]:
                subtitle_parts.append(_("Registration required") + " \u2022 " + provider["url"])
            else:
                subtitle_parts.append(provider["url"])
            row.set_subtitle("\n".join(subtitle_parts))

            # Provider icon
            icon_name = resolve_icon_name(provider["icon"])
            row.add_prefix(styled_prefix_icon(icon_name or provider["icon"]))

            # Registration badge suffix
            if provider["registration"]:
                key_icon = Gtk.Image.new_from_icon_name(
                    resolve_icon_name("dialog-password-symbolic") or "dialog-password-symbolic"
                )
                key_icon.set_tooltip_text(_("Free registration required"))
                key_icon.add_css_class("dim-label")
                key_icon.set_valign(Gtk.Align.CENTER)
                row.add_suffix(key_icon)

            row.set_activatable(False)
            group.add(row)

        # Tip row about fangfrisch
        tip_row = Adw.ActionRow()
        tip_row.set_title(_("Tip: fangfrisch"))
        tip_row.set_subtitle(
            _(
                "For SaneSecurity and other rsync-based providers, install the "
                "'fangfrisch' tool which handles downloading and updating "
                "signatures automatically."
            )
        )
        tip_row.add_prefix(
            styled_prefix_icon(
                resolve_icon_name("dialog-information-symbolic") or "dialog-information-symbolic"
            )
        )
        tip_row.set_activatable(False)
        group.add(tip_row)

        page.add(group)

    @staticmethod
    def _create_proxy_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the Proxy Settings preferences group.

        Contains settings for:
        - HTTPProxyServer: Proxy server hostname
        - HTTPProxyPort: Proxy port number
        - HTTPProxyUsername: Proxy authentication username
        - HTTPProxyPassword: Proxy authentication password

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Proxy Settings"))
        group.set_description(_("Configure HTTP proxy for database downloads (optional)"))
        group.set_header_suffix(helper._create_permission_indicator())

        # HTTPProxyServer entry row
        proxy_server_row = create_entry_row()
        proxy_server_row.set_title(_("Proxy Server"))
        proxy_server_row.set_input_purpose(Gtk.InputPurpose.URL)
        proxy_server_row.set_show_apply_button(False)
        # Add network icon as prefix
        proxy_server_row.add_prefix(styled_prefix_icon("network-workgroup-symbolic"))
        widgets_dict["HTTPProxyServer"] = proxy_server_row
        group.add(proxy_server_row)

        # HTTPProxyPort spin row (1-65535)
        # Using compatible helper for libadwaita 1.0+
        from .base import create_spin_row

        proxy_port_row, proxy_port_spin = create_spin_row(
            title=_("Proxy Port"),
            subtitle=_("Proxy server port number (0 to disable)"),
            min_val=0,
            max_val=65535,
            step=1,
        )
        proxy_port_row.add_prefix(styled_prefix_icon("network-server-symbolic"))
        widgets_dict["HTTPProxyPort"] = proxy_port_spin  # Store SpinButton for get/set_value()
        group.add(proxy_port_row)

        # HTTPProxyUsername entry row
        proxy_user_row = create_entry_row()
        proxy_user_row.set_title(_("Proxy Username"))
        proxy_user_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        proxy_user_row.set_show_apply_button(False)
        # Add user icon as prefix
        proxy_user_row.add_prefix(styled_prefix_icon("avatar-default-symbolic"))
        widgets_dict["HTTPProxyUsername"] = proxy_user_row
        group.add(proxy_user_row)

        # HTTPProxyPassword entry row (with password input)
        # Using compatible helper for libadwaita 1.0+
        from .base import create_password_entry_row

        proxy_pass_row = create_password_entry_row(_("Proxy Password"))
        proxy_pass_row.add_prefix(styled_prefix_icon("dialog-password-symbolic"))
        widgets_dict["HTTPProxyPassword"] = proxy_pass_row
        group.add(proxy_pass_row)

        page.add(group)

    @staticmethod
    def populate_fields(config, widgets_dict: dict):
        """
        Populate freshclam configuration fields from loaded config.

        Updates UI widgets with values from the parsed freshclam.conf file.

        Args:
            config: Parsed config object with has_key() and get_value() methods
            widgets_dict: Dictionary containing widget references
        """
        if not config:
            return

        # Populate text entry fields
        for key in (
            "DatabaseDirectory",
            "UpdateLogFile",
            "NotifyClamd",
            "DatabaseMirror",
            "HTTPProxyServer",
            "HTTPProxyUsername",
            "HTTPProxyPassword",
        ):
            populate_text_field(config, widgets_dict, key)

        # Populate boolean switches
        for key in ("LogVerbose", "LogSyslog"):
            populate_bool_field(config, widgets_dict, key)

        # Populate integer spin rows
        for key in ("Checks", "HTTPProxyPort"):
            populate_int_field(config, widgets_dict, key)

        # Load existing DatabaseCustomURL entries. Clear rows from any prior
        # populate first — reloading the config (e.g. after Detect/Browse)
        # would otherwise duplicate every URL row and write duplicated
        # DatabaseCustomURL lines on the next save.
        group = widgets_dict.get("_custom_url_group")
        for row, _url in widgets_dict.get("_custom_url_rows", []):
            if group:
                group.remove(row)
        if "_custom_url_rows" in widgets_dict:
            widgets_dict["_custom_url_rows"] = []
        if config.has_key("DatabaseCustomURL"):
            for url in config.get_values("DatabaseCustomURL"):
                if url:  # Skip empty values
                    DatabasePage._add_custom_url_row(url, widgets_dict)

    @staticmethod
    def collect_data(widgets_dict: dict) -> dict:
        """
        Collect freshclam configuration data from form widgets.

        Args:
            widgets_dict: Dictionary containing widget references

        Returns:
            Dictionary of configuration key-value pairs to save, or an empty
            dict when the page was never created (no widgets to read).
            Collecting from an empty widgets dict would report an empty
            DatabaseCustomURL list and strip the user's custom URLs on save.
        """
        if not widgets_dict:
            return {}

        updates = {}

        # Collect DatabaseDirectory
        db_dir = get_widget_text(widgets_dict, "DatabaseDirectory")
        if db_dir:
            updates["DatabaseDirectory"] = db_dir

        # Collect UpdateLogFile
        log_file = get_widget_text(widgets_dict, "UpdateLogFile")
        if log_file:
            updates["UpdateLogFile"] = log_file

        # Collect NotifyClamd
        notify_clamd = get_widget_text(widgets_dict, "NotifyClamd")
        if notify_clamd:
            updates["NotifyClamd"] = notify_clamd

        # Collect LogVerbose
        log_verbose = get_widget_active(widgets_dict, "LogVerbose")
        if log_verbose is not None:
            updates["LogVerbose"] = "yes" if log_verbose else "no"

        # Collect LogSyslog
        log_syslog = get_widget_active(widgets_dict, "LogSyslog")
        if log_syslog is not None:
            updates["LogSyslog"] = "yes" if log_syslog else "no"

        # Collect Checks
        checks_value = get_widget_int_value(widgets_dict, "Checks")
        if checks_value is not None:
            updates["Checks"] = str(checks_value)

        # Collect DatabaseMirror
        mirror = get_widget_text(widgets_dict, "DatabaseMirror")
        if mirror:
            updates["DatabaseMirror"] = mirror

        # Collect proxy settings
        proxy_server = get_widget_text(widgets_dict, "HTTPProxyServer")
        if proxy_server:
            updates["HTTPProxyServer"] = proxy_server

        proxy_port = get_widget_int_value(widgets_dict, "HTTPProxyPort")
        if proxy_port is not None and proxy_port > 0:
            updates["HTTPProxyPort"] = str(proxy_port)

        proxy_user = get_widget_text(widgets_dict, "HTTPProxyUsername")
        if proxy_user:
            updates["HTTPProxyUsername"] = proxy_user

        proxy_pass = get_widget_text(widgets_dict, "HTTPProxyPassword")
        if proxy_pass:
            updates["HTTPProxyPassword"] = proxy_pass

        # Collect DatabaseCustomURL list (multi-value option)
        # Always include the key, even when empty, so remove_key() can
        # blank the old lines in freshclam.conf when all URLs are cleared.
        custom_urls = [url for _, url in widgets_dict.get("_custom_url_rows", [])]
        updates["DatabaseCustomURL"] = custom_urls

        return updates


class _DatabasePageHelper(PreferencesPageMixin):
    """
    Helper class to provide access to mixin methods for static context.

    This is a workaround to allow static methods in DatabasePage to use
    the mixin utilities (like _create_permission_indicator). In the future,
    when DatabasePage is integrated into the full PreferencesWindow, this
    helper won't be needed.
    """

    pass
