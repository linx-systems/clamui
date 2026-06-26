# ClamUI Save & Apply Page
"""
Save & Apply preference page for configuration persistence.

This module provides the SavePage class which handles saving all
preference changes to ClamAV configuration files and ClamUI settings.
"""

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ...core.clamav_config import (
    backup_config,
    validate_config,
    write_configs_with_elevation,
)
from ...core.i18n import _
from ..compat import create_toolbar_view, safe_set_subtitle_lines, safe_set_title_lines
from ..utils import resolve_icon_name
from .base import PreferencesPageMixin
from .database_page import DatabasePage
from .onaccess_page import OnAccessPage
from .scanner_page import ScannerPage
from .scheduled_page import ScheduledPage


class SavePage(PreferencesPageMixin):
    """
    Save & Apply preference page for configuration persistence.

    This class creates and manages the UI for saving all preference changes,
    including ClamAV configuration files (freshclam.conf, clamd.conf) and
    ClamUI application settings (scheduled scans).

    The page includes:
    - Information banners explaining auto-save vs manual save
    - Save & Apply button
    - Background thread processing with progress feedback
    - Error/success dialog handling

    Note: This class uses PreferencesPageMixin for shared dialog utilities.
    The save process validates configs, backs them up, writes with elevation,
    and handles scheduled scan enablement/disablement.
    """

    def __init__(
        self,
        window,
        freshclam_config,
        clamd_config,
        freshclam_conf_path: str,
        clamd_conf_path: str,
        clamd_available: bool,
        settings_manager,
        scheduler,
        freshclam_widgets: dict,
        clamd_widgets: dict,
        onaccess_widgets: dict,
        scheduled_widgets: dict,
    ):
        """
        Initialize the SavePage.

        Args:
            window: Parent PreferencesWindow instance (for dialog presentation and config access)
            freshclam_config: (Deprecated) Now accessed from window._freshclam_config
            clamd_config: (Deprecated) Now accessed from window._clamd_config
            freshclam_conf_path: Path to freshclam.conf file
            clamd_conf_path: Path to clamd.conf file
            clamd_available: Whether clamd.conf is available
            settings_manager: SettingsManager instance for app settings
            scheduler: Scheduler instance for scheduled scan management
            freshclam_widgets: Dictionary of freshclam form widgets
            clamd_widgets: Dictionary of clamd form widgets
            onaccess_widgets: Dictionary of on-access form widgets
            scheduled_widgets: Dictionary of scheduled scan form widgets

        Note:
            SavePage now accesses configs from window._freshclam_config and window._clamd_config
            to ensure it always has the latest loaded configs (not None from init time).
        """
        self._window = window
        # Note: Configs are accessed from window._freshclam_config and window._clamd_config
        # to ensure we always have the latest loaded configs (not None from init time)
        self._freshclam_conf_path = freshclam_conf_path
        self._clamd_conf_path = clamd_conf_path
        self._clamd_available = clamd_available
        self._settings_manager = settings_manager
        self._scheduler = scheduler

        # Store widget dictionaries for data collection
        self._freshclam_widgets = freshclam_widgets
        self._clamd_widgets = clamd_widgets
        self._onaccess_widgets = onaccess_widgets
        self._scheduled_widgets = scheduled_widgets

        # Track saving state
        self._is_saving = False
        self._scheduler_error = None

        # Store reference to save button
        self._save_button = None

    def _show_error_dialog(self, title: str, message: str):
        """
        Show an error dialog to the user.

        Overrides PreferencesPageMixin to use self._window as parent
        since SavePage is not a GTK widget.

        Args:
            title: Dialog title
            message: Error message text
        """
        self._show_simple_dialog(title, message)

    def _show_success_dialog(self, title: str, message: str):
        """
        Show a success dialog to the user.

        Overrides PreferencesPageMixin to use self._window as parent
        since SavePage is not a GTK widget.

        Args:
            title: Dialog title
            message: Success message text
        """
        self._show_simple_dialog(title, message)

    def _show_simple_dialog(self, title: str, message: str):
        """
        Show a simple message dialog with an OK button.

        Uses Adw.Window for compatibility with libadwaita < 1.5.

        Args:
            title: Dialog title/heading
            message: Message body text
        """
        dialog = Adw.Window()
        dialog.set_title(title)
        dialog.set_default_size(350, -1)
        dialog.set_modal(True)
        dialog.set_deletable(True)
        dialog.set_transient_for(self._window)

        # Create content
        toolbar_view = create_toolbar_view()
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(24)

        # Message label
        label = Gtk.Label()
        label.set_text(message)
        label.set_wrap(True)
        label.set_xalign(0)
        content_box.append(label)

        # OK button
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(12)

        ok_button = Gtk.Button(label=_("OK"))
        ok_button.add_css_class("suggested-action")
        ok_button.connect("clicked", lambda btn: dialog.close())
        button_box.append(ok_button)

        content_box.append(button_box)
        toolbar_view.set_content(content_box)
        dialog.set_content(toolbar_view)

        dialog.present()

    def create_page(self) -> Adw.PreferencesPage:
        """
        Create the Save & Apply preference page.

        This page provides information about save behavior and a button
        to save all configuration changes.

        Returns:
            Configured Adw.PreferencesPage ready to be added to preferences window
        """
        page = Adw.PreferencesPage(
            title=_("Save & Apply"),
            icon_name=resolve_icon_name("document-save-symbolic"),
        )

        # Information banner explaining what needs to be saved
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("Save Behavior"))

        # Auto-save settings info row
        auto_save_row = Adw.ActionRow()
        auto_save_row.set_title(_("Auto-Saved"))
        auto_save_row.set_subtitle(_("Scan Backend, Exclusions"))
        auto_save_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("emblem-default-symbolic"))
        auto_save_icon.add_css_class("success")
        auto_save_row.add_prefix(auto_save_icon)
        info_group.add(auto_save_row)

        # Manual save settings info row.  Running as root, every config path is
        # directly writable and the save flow skips pkexec, so drop the
        # "you will be asked for administrator permission" wording and the
        # warning lock icon that would otherwise mislead an already-privileged user.
        from ...core.privileged_paths import is_running_as_root

        manual_save_row = Adw.ActionRow()
        manual_save_row.set_title(_("Manual Save Required"))
        safe_set_title_lines(manual_save_row, 1)
        if is_running_as_root():
            manual_save_row.set_subtitle(
                _("Database Updates, Scanner, On-Access, Scheduled Scans.")
            )
            manual_icon_name = "emblem-default-symbolic"
            manual_icon_css = "success"
        else:
            manual_save_row.set_subtitle(
                _(
                    "Database Updates, Scanner, On-Access, Scheduled Scans. "
                    "When needed, you will be asked for administrator permission once."
                )
            )
            manual_icon_name = "system-lock-screen-symbolic"
            manual_icon_css = "warning"
        safe_set_subtitle_lines(manual_save_row, 2)
        lock_icon = Gtk.Image.new_from_icon_name(resolve_icon_name(manual_icon_name))
        lock_icon.add_css_class(manual_icon_css)
        manual_save_row.add_prefix(lock_icon)
        info_group.add(manual_save_row)

        page.add(info_group)

        # Save & apply button group
        button_group = Adw.PreferencesGroup()
        button_group.set_title(_("Apply Configuration"))

        # Save button row - using ActionRow to properly contain the button
        save_action_row = Adw.ActionRow()
        save_action_row.set_title(_("Save Configuration"))
        save_action_row.set_subtitle(_("Apply all pending changes at once."))
        safe_set_subtitle_lines(save_action_row, 1)

        # Create the save button
        self._save_button = Gtk.Button()
        self._save_button.set_label(_("Save & Apply"))
        self._save_button.add_css_class("suggested-action")
        self._save_button.set_valign(Gtk.Align.CENTER)
        self._save_button.connect("clicked", self._on_save_clicked)

        # Add button as suffix to the row
        save_action_row.add_suffix(self._save_button)

        button_group.add(save_action_row)
        page.add(button_group)

        return page

    def _on_save_clicked(self, button: Gtk.Button):
        """
        Handle save button click event.

        Validates configuration, backs up current configs, and saves
        changes using elevated privileges (pkexec) if needed.

        Args:
            button: The clicked button widget
        """
        # Prevent multiple simultaneous saves
        if self._is_saving:
            return

        self._is_saving = True
        button.set_sensitive(False)

        # Collect form data from all pages
        freshclam_updates = DatabasePage.collect_data(self._freshclam_widgets)
        clamd_updates = ScannerPage.collect_data(self._clamd_widgets, self._clamd_available)
        onaccess_updates = OnAccessPage.collect_data(self._onaccess_widgets, self._clamd_available)
        scheduled_updates = ScheduledPage.collect_data(self._scheduled_widgets)

        # Validate configurations
        if freshclam_updates:
            if not self._window._freshclam_config:
                self._show_error_dialog(
                    _("Configuration Error"),
                    _(
                        "Cannot save freshclam settings: Configuration failed to load.\n\n"
                        "This may be due to:\n"
                        "- Missing configuration file\n"
                        "- Insufficient permissions\n"
                        "- Disk space issues (Flatpak)\n\n"
                        "Check the application logs for details."
                    ),
                )
                self._is_saving = False
                button.set_sensitive(True)
                return

            is_valid, errors = validate_config(self._window._freshclam_config)
            if not is_valid:
                self._show_error_dialog(_("Validation Error"), "\n".join(errors))
                self._is_saving = False
                button.set_sensitive(True)
                return

        if clamd_updates and self._clamd_available:
            if not self._window._clamd_config:
                self._show_error_dialog(
                    _("Configuration Error"),
                    _(
                        "Cannot save clamd settings: Configuration failed to load.\n\n"
                        "Check that {path} exists and is readable."
                    ).format(path=self._clamd_conf_path),
                )
                self._is_saving = False
                button.set_sensitive(True)
                return

            is_valid, errors = validate_config(self._window._clamd_config)
            if not is_valid:
                self._show_error_dialog(_("Validation Error"), "\n".join(errors))
                self._is_saving = False
                button.set_sensitive(True)
                return

        # Run save in background thread
        save_thread = threading.Thread(
            target=self._save_configs_thread,
            args=(
                freshclam_updates,
                clamd_updates,
                onaccess_updates,
                scheduled_updates,
                button,
            ),
        )
        save_thread.daemon = True
        save_thread.start()

    def _save_configs_thread(
        self,
        freshclam_updates: dict,
        clamd_updates: dict,
        onaccess_updates: dict,
        scheduled_updates: dict,
        button: Gtk.Button,
    ):
        """
        Save configuration files in a background thread.

        Uses elevated privileges (pkexec) to write configuration files
        and manages error handling with thread-safe communication.

        Args:
            freshclam_updates: Dictionary of freshclam.conf updates
            clamd_updates: Dictionary of clamd.conf updates
            onaccess_updates: Dictionary of On-Access scanning settings (clamd.conf)
            scheduled_updates: Dictionary of scheduled scan settings
            button: The save button to re-enable after completion
        """
        try:
            # Backup configurations
            backup_config(self._freshclam_conf_path)
            if self._clamd_available:
                backup_config(self._clamd_conf_path)

            configs_to_write = []

            # Save freshclam.conf
            if freshclam_updates and self._window._freshclam_config:
                # Apply updates to config using set_value (or add_value for lists)
                for key, value in freshclam_updates.items():
                    if isinstance(value, list):
                        # Multi-value option: blank old lines, then add each value
                        self._window._freshclam_config.remove_key(key)
                        for v in value:
                            self._window._freshclam_config.add_value(key, v)
                    else:
                        self._window._freshclam_config.set_value(key, value)
                configs_to_write.append(self._window._freshclam_config)

            # Save clamd.conf (includes both scanner settings and On-Access settings)
            if (clamd_updates or onaccess_updates) and self._window._clamd_config:
                # Apply scanner updates to config using set_value (or add_value for lists)
                for key, value in clamd_updates.items():
                    if isinstance(value, list):
                        # Multi-value option: blank old lines, then add each value
                        self._window._clamd_config.remove_key(key)
                        for v in value:
                            self._window._clamd_config.add_value(key, v)
                    else:
                        self._window._clamd_config.set_value(key, value)
                # Apply On-Access updates to config using set_value (or add_value for lists)
                for key, value in onaccess_updates.items():
                    if isinstance(value, list):
                        # Multi-value option: blank old lines, then add each value
                        self._window._clamd_config.remove_key(key)
                        for v in value:
                            self._window._clamd_config.add_value(key, v)
                    else:
                        self._window._clamd_config.set_value(key, value)
                configs_to_write.append(self._window._clamd_config)

            if configs_to_write:
                success, error = write_configs_with_elevation(configs_to_write)
                if not success:
                    raise Exception(f"Failed to save configuration files: {error}")

            # Save scheduled scan settings
            if scheduled_updates:
                for key, value in scheduled_updates.items():
                    self._settings_manager.set(key, value)
                if not self._settings_manager.save():
                    raise Exception("Failed to save scheduled scan settings")

                # Enable or disable scheduler based on settings
                if scheduled_updates.get("scheduled_scans_enabled"):
                    success, error = self._scheduler.enable_schedule(
                        frequency=scheduled_updates.get("schedule_frequency", "daily"),
                        time=scheduled_updates.get("schedule_time", "02:00"),
                        targets=scheduled_updates.get("schedule_targets", []),
                        day_of_week=scheduled_updates.get("schedule_day_of_week", 0),
                        day_of_month=scheduled_updates.get("schedule_day_of_month", 1),
                        skip_on_battery=scheduled_updates.get("schedule_skip_on_battery", True),
                        auto_quarantine=scheduled_updates.get("schedule_auto_quarantine", False),
                    )
                    if not success:
                        raise Exception(f"Failed to enable scheduled scans: {error}")
                else:
                    # Disable scheduler if it was previously enabled
                    self._scheduler.disable_schedule()

            # Only report success if something was actually applied.  When the
            # user opens Save without modifying (or ever materializing) a
            # config-backed page, nothing is collected and nothing is written;
            # claiming "Configuration saved" in that case is misleading and was
            # one way the Flatpak persistence bug (#136) surfaced as a phantom
            # success.
            if configs_to_write or scheduled_updates:
                GLib.idle_add(
                    self._show_success_dialog,
                    _("Configuration Saved"),
                    _("Configuration saved. Active ClamAV services were restarted where needed."),
                )
            else:
                GLib.idle_add(
                    self._show_success_dialog,
                    _("No Changes to Apply"),
                    _(
                        "No configuration changes were detected, so nothing was saved. "
                        "Open a settings page and modify a value before saving."
                    ),
                )
        except Exception as e:
            # Store error for thread-safe handling
            self._scheduler_error = str(e)
            GLib.idle_add(self._show_error_dialog, _("Save Failed"), str(e))
        finally:
            self._is_saving = False
            GLib.idle_add(button.set_sensitive, True)
