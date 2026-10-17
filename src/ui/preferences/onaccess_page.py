# ClamUI On-Access Scanning Page
"""
On-Access Scanning preference page for clamd.conf on-access settings.

This module provides the OnAccessPage class which handles the UI and logic
for configuring ClamAV on-access scanning settings (clamonacc).
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ...core.i18n import _
from ..compat import create_entry_row, create_switch_row
from ..utils import resolve_icon_name
from .base import (
    PreferencesPageMixin,
    create_spin_row,
    get_widget_active,
    get_widget_int_value,
    get_widget_text,
    populate_bool_field,
    populate_int_field,
    populate_multivalue_field,
    populate_text_field,
    styled_prefix_icon,
)


class OnAccessPage(PreferencesPageMixin):
    """
    On-Access Scanning preference page for clamd.conf configuration.

    This class creates and manages the UI for configuring ClamAV on-access
    scanning settings, including monitored paths, behavior, performance,
    and scan loop prevention.

    The page includes:
    - File location display for clamd.conf
    - Monitored paths group (include/exclude paths)
    - Behavior settings group (prevention mode, extra scanning, etc.)
    - Performance settings group (threads, file size limits, timeouts)
    - Scan loop prevention group (user/UID exclusions)

    Note: This class uses PreferencesPageMixin for shared utilities like
    permission indicators and file location displays.
    """

    @staticmethod
    def create_page(
        _config_path: str,
        widgets_dict: dict,
        clamd_available: bool,
        parent_window,
    ) -> Adw.PreferencesPage:
        """
        Create the On-Access Scanning preference page.

        Args:
            config_path: Path to the clamd.conf file
            widgets_dict: Dictionary to store widget references for later access
            clamd_available: Whether clamd.conf exists and is available
            parent_window: Parent window for presenting dialogs

        Returns:
            Configured Adw.PreferencesPage ready to be added to preferences window
        """
        page = Adw.PreferencesPage(
            title=_("On Access"),
            icon_name=resolve_icon_name("security-high-symbolic"),
        )

        # Create a temporary instance to use mixin methods
        temp_instance = _OnAccessPageHelper()
        temp_instance._parent_window = parent_window

        if clamd_available:
            # Create On-Access paths group
            OnAccessPage._create_onaccess_paths_group(page, widgets_dict, temp_instance)

            # Create behavior settings group
            OnAccessPage._create_onaccess_behavior_group(page, widgets_dict, temp_instance)

            # Create performance settings group
            OnAccessPage._create_onaccess_performance_group(page, widgets_dict, temp_instance)

            # Create exclusions group (required to prevent scan loops)
            OnAccessPage._create_onaccess_exclusions_group(page, widgets_dict, temp_instance)
        else:
            # Show message that clamd.conf is not available
            group = Adw.PreferencesGroup()
            group.set_title(_("Configuration Status"))
            row = Adw.ActionRow()
            row.set_title(_("On Access Configuration"))
            # Translators: the em dash separates two parts; use the dash and spacing usual in your
            # language.
            row.set_subtitle(_("clamd.conf not found — On Access settings unavailable"))
            group.add(row)
            page.add(group)

        return page

    @staticmethod
    def _create_onaccess_paths_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the On-Access Paths preferences group.

        Contains settings for:
        - OnAccessIncludePath: Directories to monitor for file access
        - OnAccessExcludePath: Directories to exclude from monitoring

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Monitored Paths"))
        group.set_description(_("Directories to monitor. Comma-separated."))
        group.set_header_suffix(helper._create_permission_indicator())

        # OnAccessIncludePath row
        include_path_row = create_entry_row()
        include_path_row.set_title(_("Include Paths"))
        include_path_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        include_path_row.set_show_apply_button(False)
        # Add folder icon as prefix
        include_path_row.add_prefix(styled_prefix_icon("folder-symbolic"))
        widgets_dict["OnAccessIncludePath"] = include_path_row
        group.add(include_path_row)

        # OnAccessExcludePath row
        exclude_path_row = create_entry_row()
        exclude_path_row.set_title(_("Exclude Paths"))
        exclude_path_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        exclude_path_row.set_show_apply_button(False)
        # Add folder icon as prefix
        exclude_path_row.add_prefix(styled_prefix_icon("folder-symbolic"))
        widgets_dict["OnAccessExcludePath"] = exclude_path_row
        group.add(exclude_path_row)

        page.add(group)

    @staticmethod
    def _create_onaccess_behavior_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the On-Access Behavior preferences group.

        Contains settings for:
        - OnAccessPrevention: Block access to infected files
        - OnAccessExtraScanning: Monitor file creation/moves via inotify
        - OnAccessDenyOnError: Deny access when scan fails
        - OnAccessDisableDDD: Disable Directory Descent Detection

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Behavior Settings"))
        group.set_description(_("On-Access scanning behavior"))
        group.set_header_suffix(helper._create_permission_indicator())

        # OnAccessPrevention switch
        prevention_row = create_switch_row("shield-safe-symbolic")
        prevention_row.set_title(_("Prevention Mode"))
        prevention_row.set_subtitle(_("Block access to infected files"))
        widgets_dict["OnAccessPrevention"] = prevention_row
        group.add(prevention_row)

        # OnAccessExtraScanning switch
        extra_scanning_row = create_switch_row("emblem-system-symbolic")
        extra_scanning_row.set_title(_("Extra Scanning"))
        extra_scanning_row.set_subtitle(_("Monitor file creation/moves via inotify"))
        widgets_dict["OnAccessExtraScanning"] = extra_scanning_row
        group.add(extra_scanning_row)

        # OnAccessDenyOnError switch
        deny_on_error_row = create_switch_row("action-unavailable-symbolic")
        deny_on_error_row.set_title(_("Deny on Error"))
        deny_on_error_row.set_subtitle(_("Deny access when scan fails (requires Prevention)"))
        widgets_dict["OnAccessDenyOnError"] = deny_on_error_row
        group.add(deny_on_error_row)

        # OnAccessDisableDDD switch
        disable_ddd_row = create_switch_row("folder-symbolic")
        disable_ddd_row.set_title(_("Disable DDD"))
        disable_ddd_row.set_subtitle(_("Disable Directory Descent Detection"))
        widgets_dict["OnAccessDisableDDD"] = disable_ddd_row
        group.add(disable_ddd_row)

        page.add(group)

    @staticmethod
    def _create_onaccess_performance_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the On-Access Performance preferences group.

        Contains settings for:
        - OnAccessMaxThreads: Maximum number of scanning threads
        - OnAccessMaxFileSize: Maximum file size to scan (in MB)
        - OnAccessCurlTimeout: Timeout for curl operations (seconds)
        - OnAccessRetryAttempts: Number of retry attempts when scan fails

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Performance Settings"))
        group.set_description(_("Scanning limits and performance"))
        group.set_header_suffix(helper._create_permission_indicator())

        # OnAccessMaxThreads spin row (1-64)
        max_threads_row, max_threads_spin = create_spin_row(
            title=_("Max Threads"),
            subtitle=_("Maximum number of scanning threads"),
            min_val=1,
            max_val=64,
            step=1,
        )
        max_threads_row.add_prefix(styled_prefix_icon("preferences-system-symbolic"))
        widgets_dict["OnAccessMaxThreads"] = max_threads_spin
        group.add(max_threads_row)

        # OnAccessMaxFileSize spin row (in MB, 0-4000)
        max_file_size_row, max_file_size_spin = create_spin_row(
            title=_("Max File Size (MB)"),
            subtitle=_("Maximum file size to scan (0 = unlimited)"),
            min_val=0,
            max_val=4000,
            step=1,
        )
        max_file_size_row.add_prefix(styled_prefix_icon("drive-harddisk-symbolic"))
        widgets_dict["OnAccessMaxFileSize"] = max_file_size_spin
        group.add(max_file_size_row)

        # OnAccessCurlTimeout spin row (in seconds, 0-3600)
        curl_timeout_row, curl_timeout_spin = create_spin_row(
            title=_("Curl Timeout (seconds)"),
            subtitle=_("Timeout for remote scanning operations (0 = disabled)"),
            min_val=0,
            max_val=3600,
            step=1,
        )
        curl_timeout_row.add_prefix(styled_prefix_icon("alarm-symbolic"))
        widgets_dict["OnAccessCurlTimeout"] = curl_timeout_spin
        group.add(curl_timeout_row)

        # OnAccessRetryAttempts spin row (0-10)
        retry_attempts_row, retry_attempts_spin = create_spin_row(
            title=_("Retry Attempts"),
            subtitle=_("Number of retry attempts when scan fails"),
            min_val=0,
            max_val=10,
            step=1,
        )
        retry_attempts_row.add_prefix(styled_prefix_icon("view-refresh-symbolic"))
        widgets_dict["OnAccessRetryAttempts"] = retry_attempts_spin
        group.add(retry_attempts_row)

        page.add(group)

    @staticmethod
    def _create_onaccess_exclusions_group(page: Adw.PreferencesPage, widgets_dict: dict, helper):
        """
        Create the On-Access Exclusions preferences group.

        Contains settings for:
        - OnAccessExcludeUname: Username to exclude from On-Access scanning
        - OnAccessExcludeUID: User ID to exclude from On-Access scanning
        - OnAccessExcludeRootUID: Exclude root user from On-Access scanning

        CRITICAL: At least one of these must be set to prevent infinite scan loops
        when the scanner process accesses files during scanning.

        Args:
            page: The preferences page to add the group to
            widgets_dict: Dictionary to store widget references
            helper: Helper instance with _create_permission_indicator method
        """
        group = Adw.PreferencesGroup()
        group.set_title(_("Scan Loop Prevention"))
        group.set_description(_("CRITICAL: Set at least one to prevent infinite loops"))
        group.set_header_suffix(helper._create_permission_indicator())

        # Warning banner row
        warning_row = Adw.ActionRow()
        warning_row.set_title(_("Required Configuration"))
        warning_row.set_subtitle(_("Exclude clamav user or UID to prevent scan loops"))
        warning_row.add_css_class("warning")
        # Add warning icon as prefix (not dim for emphasis)
        warning_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
        warning_icon.set_margin_start(12)
        warning_icon.add_css_class("warning")
        warning_row.add_prefix(warning_icon)
        group.add(warning_row)

        # OnAccessExcludeUname entry row
        exclude_uname_row = create_entry_row()
        exclude_uname_row.set_title(_("Exclude Username"))
        exclude_uname_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        exclude_uname_row.set_show_apply_button(False)
        # Add user icon as prefix
        exclude_uname_row.add_prefix(styled_prefix_icon("avatar-default-symbolic"))
        widgets_dict["OnAccessExcludeUname"] = exclude_uname_row
        group.add(exclude_uname_row)

        # OnAccessExcludeUID spin row (0-65534)
        exclude_uid_row, exclude_uid_spin = create_spin_row(
            title=_("Exclude User ID"),
            subtitle=_("User ID to exclude from On-Access scanning"),
            min_val=0,
            max_val=65534,
            step=1,
        )
        exclude_uid_row.add_prefix(styled_prefix_icon("avatar-default-symbolic"))
        widgets_dict["OnAccessExcludeUID"] = exclude_uid_spin
        group.add(exclude_uid_row)

        # OnAccessExcludeRootUID switch
        exclude_root_row = create_switch_row("avatar-default-symbolic")
        exclude_root_row.set_title(_("Exclude Root User"))
        exclude_root_row.set_subtitle(_("Exclude root (UID 0) from On-Access scanning"))
        widgets_dict["OnAccessExcludeRootUID"] = exclude_root_row
        group.add(exclude_root_row)

        page.add(group)

    @staticmethod
    def populate_fields(config, widgets_dict: dict):
        """
        Populate On-Access configuration fields from loaded clamd.conf config.

        Updates UI widgets with On-Access scanning values from the parsed
        clamd.conf file. On-Access settings control real-time file monitoring
        via clamonacc.

        Args:
            config: Parsed config object with has_key() and get_value()/get_values() methods
            widgets_dict: Dictionary containing widget references
        """
        if not config:
            return

        # Populate path settings (comma-separated multi-value fields)
        populate_multivalue_field(config, widgets_dict, "OnAccessIncludePath")
        populate_multivalue_field(config, widgets_dict, "OnAccessExcludePath")

        # Populate behavior switches
        for key in (
            "OnAccessPrevention",
            "OnAccessExtraScanning",
            "OnAccessDenyOnError",
            "OnAccessDisableDDD",
            "OnAccessExcludeRootUID",
        ):
            populate_bool_field(config, widgets_dict, key)

        # Populate performance settings (spin rows)
        for key in (
            "OnAccessMaxThreads",
            "OnAccessMaxFileSize",
            "OnAccessCurlTimeout",
            "OnAccessRetryAttempts",
            "OnAccessExcludeUID",
        ):
            populate_int_field(config, widgets_dict, key)

        # Populate text entry
        populate_text_field(config, widgets_dict, "OnAccessExcludeUname")

    @staticmethod
    def collect_data(widgets_dict: dict, clamd_available: bool) -> dict:
        """
        Collect On-Access scanning configuration data from form widgets.

        Args:
            widgets_dict: Dictionary containing widget references
            clamd_available: Whether clamd.conf is available

        Returns:
            Dictionary of configuration key-value pairs to save
        """
        if not clamd_available:
            return {}

        updates = {}

        # Collect path settings (comma-separated entries become multiple values)
        include_path = get_widget_text(widgets_dict, "OnAccessIncludePath", strip=True)
        if include_path:
            # Split comma-separated paths and store as list for multi-value config
            updates["OnAccessIncludePath"] = [
                p.strip() for p in include_path.split(",") if p.strip()
            ]

        exclude_path = get_widget_text(widgets_dict, "OnAccessExcludePath", strip=True)
        if exclude_path:
            updates["OnAccessExcludePath"] = [
                p.strip() for p in exclude_path.split(",") if p.strip()
            ]

        # Collect behavior switches
        for key in (
            "OnAccessPrevention",
            "OnAccessExtraScanning",
            "OnAccessDenyOnError",
            "OnAccessDisableDDD",
        ):
            value = get_widget_active(widgets_dict, key)
            if value is not None:
                updates[key] = "yes" if value else "no"

        # Collect performance settings (spin rows)
        for key in (
            "OnAccessMaxThreads",
            "OnAccessMaxFileSize",
            "OnAccessCurlTimeout",
            "OnAccessRetryAttempts",
            "OnAccessExcludeUID",
        ):
            value = get_widget_int_value(widgets_dict, key)
            if value is not None:
                updates[key] = str(value)

        # Collect user exclusion settings
        exclude_uname = get_widget_text(widgets_dict, "OnAccessExcludeUname", strip=True)
        if exclude_uname:
            updates["OnAccessExcludeUname"] = exclude_uname

        exclude_root_uid = get_widget_active(widgets_dict, "OnAccessExcludeRootUID")
        if exclude_root_uid is not None:
            updates["OnAccessExcludeRootUID"] = "yes" if exclude_root_uid else "no"

        return updates


class _OnAccessPageHelper(PreferencesPageMixin):
    """
    Helper class to provide access to mixin methods for static context.

    This is a workaround to allow static methods in OnAccessPage to use
    the mixin utilities (like _create_permission_indicator). In the future,
    when OnAccessPage is integrated into the full PreferencesWindow, this
    helper won't be needed.
    """

    def __init__(self):
        """Initialize helper with a parent window reference."""
        self._parent_window = None
