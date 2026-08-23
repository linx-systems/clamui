# ClamUI File Manager Integration Dialog
"""
Dialog for configuring file manager context menu integration.

Shown on first Flatpak launch to offer installation of context menu
actions for supported file managers (Nemo, Nautilus, Dolphin).
Supports install, removal, and repair of partial installations.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..core.file_manager_integration import (
    FileManager,
    IntegrationInfo,
    IntegrationStatus,
    get_available_integrations,
    install_integration,
    remove_integration,
    repair_integration,
)
from ..core.i18n import _
from .compat import create_switch_row, create_toolbar_view
from .utils import enable_escape_to_close, resolve_icon_name

if TYPE_CHECKING:
    from ..core.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class FileManagerIntegrationDialog(Adw.Window):
    """
    A dialog for configuring file manager integration.

    Shown on first Flatpak launch when file manager integrations are available
    but not yet installed. Allows the user to select which file managers to
    integrate with, remove existing integrations, or repair partial ones.

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        dialog = FileManagerIntegrationDialog(
            settings_manager=settings_manager,
            on_complete=lambda: print("Done"),
        )
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    def __init__(
        self,
        settings_manager: "SettingsManager | None" = None,
        on_complete: Callable[[], None] | None = None,
        **kwargs,
    ):
        """
        Initialize the file manager integration dialog.

        Args:
            settings_manager: SettingsManager for saving preferences.
            on_complete: Callback when dialog is closed (installed or skipped).
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(**kwargs)

        self._settings_manager = settings_manager
        self._on_complete = on_complete
        self._integration_rows: dict[FileManager, Adw.ActionRow] = {}
        self._original_status: dict[FileManager, IntegrationStatus] = {}

        # Configure and set up the dialog
        self._setup_dialog()
        self._setup_ui()

    def _setup_dialog(self):
        """Configure the dialog properties."""
        self.set_title(_("File Manager Integration"))
        self.set_default_size(500, 450)

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

        # File managers section
        self._create_file_managers_section(preferences_page)

        # Actions section
        self._create_actions_section(preferences_page)

        scrolled.set_child(preferences_page)
        toolbar_view.set_content(scrolled)

        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

    def _create_info_section(self, preferences_page: Adw.PreferencesPage):
        """Create the information section."""
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("Add Context Menu Actions"))
        info_group.set_description(
            _(
                "ClamUI can add 'Scan with ClamUI' options to your file manager's "
                "right-click menu. This makes it easy to scan files and folders "
                "directly from your file browser."
            )
        )

        # Info row about what gets installed
        info_row = Adw.ActionRow()
        info_row.set_title(_("What gets installed?"))
        info_row.set_subtitle(
            _(
                "Small configuration files are added to your user profile. "
                "No system files are modified."
            )
        )

        info_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-information-symbolic"))
        info_icon.add_css_class("dim-label")
        info_row.add_prefix(info_icon)

        info_group.add(info_row)
        preferences_page.add(info_group)

    def _create_file_managers_section(self, preferences_page: Adw.PreferencesPage):
        """Create the file managers selection section."""
        fm_group = Adw.PreferencesGroup()
        fm_group.set_title(_("Available File Managers"))
        fm_group.set_description(_("Select which file managers to integrate with:"))

        # Get available integrations
        integrations = get_available_integrations()
        available_count = 0

        for integration in integrations:
            if integration.is_available:
                available_count += 1
                row = self._create_file_manager_row(integration)
                fm_group.add(row)
                self._integration_rows[integration.file_manager] = row
                self._original_status[integration.file_manager] = integration.status

        if available_count == 0:
            # No file managers detected
            no_fm_row = Adw.ActionRow()
            no_fm_row.set_title(_("No supported file managers detected"))
            no_fm_row.set_subtitle(_("ClamUI supports Nemo, Nautilus, and Dolphin file managers."))

            warning_icon = Gtk.Image.new_from_icon_name(
                resolve_icon_name("dialog-warning-symbolic")
            )
            warning_icon.add_css_class("dim-label")
            no_fm_row.add_prefix(warning_icon)

            fm_group.add(no_fm_row)

        preferences_page.add(fm_group)

    def _create_file_manager_row(self, integration: IntegrationInfo) -> Adw.ActionRow:
        """
        Create a switch row for a file manager integration.

        Rows are always sensitive (interactive) so users can toggle
        integrations on or off regardless of current state.

        Args:
            integration: The integration info.

        Returns:
            The created SwitchRow widget.
        """
        row = create_switch_row()
        row.set_title(integration.display_name)

        if integration.status == IntegrationStatus.INSTALLED:
            row.set_subtitle(
                _("{description} (installed)").format(description=_(integration.description))
            )
            row.set_active(True)
        elif integration.status == IntegrationStatus.PARTIAL:
            row.set_subtitle(
                _("{description} (incomplete - needs repair)").format(
                    description=_(integration.description)
                )
            )
            row.set_active(True)
        else:
            row.set_subtitle(_(integration.description))
            row.set_active(False)  # Off by default; user opts in to install

        # Add file manager icon
        icon_name = self._get_file_manager_icon(integration.file_manager)
        icon = Gtk.Image.new_from_icon_name(resolve_icon_name(icon_name))
        icon.add_css_class("dim-label")
        row.add_prefix(icon)

        return row

    def _get_file_manager_icon(self, file_manager: FileManager) -> str:
        """
        Get the icon name for a file manager.

        Args:
            file_manager: The file manager.

        Returns:
            Icon name string.
        """
        icons = {
            FileManager.NEMO: "folder-symbolic",
            FileManager.NAUTILUS: "folder-symbolic",
            FileManager.DOLPHIN: "folder-symbolic",
        }
        return icons.get(file_manager, "folder-symbolic")

    def _create_actions_section(self, preferences_page: Adw.PreferencesPage):
        """Create the action buttons section."""
        actions_group = Adw.PreferencesGroup()

        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(12)
        button_box.set_margin_bottom(12)

        # Cancel button
        cancel_button = Gtk.Button()
        cancel_button.set_label(_("Cancel"))
        cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(cancel_button)

        # Apply button
        apply_button = Gtk.Button()
        apply_button.set_label(_("Apply"))
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", self._on_apply_clicked)
        button_box.append(apply_button)

        actions_group.add(button_box)

        preferences_page.add(actions_group)

    def _on_cancel_clicked(self, _button: Gtk.Button):
        """Handle cancel button click."""
        self._save_preference_and_close()

    def _on_apply_clicked(self, _button: Gtk.Button):
        """Handle apply button click."""
        installed_count = 0
        removed_count = 0
        repaired_count = 0
        error_count = 0

        for file_manager, row in self._integration_rows.items():
            is_active = row.get_active()
            original = self._original_status.get(file_manager, IntegrationStatus.NOT_INSTALLED)

            if is_active and original == IntegrationStatus.NOT_INSTALLED:
                # Install new integration
                success, error = install_integration(file_manager)
                if success:
                    installed_count += 1
                    logger.info("Installed %s integration", file_manager.value)
                else:
                    error_count += 1
                    logger.error("Failed to install %s: %s", file_manager.value, error)

            elif is_active and original == IntegrationStatus.PARTIAL:
                # Repair partial integration
                success, error = repair_integration(file_manager)
                if success:
                    repaired_count += 1
                    logger.info("Repaired %s integration", file_manager.value)
                else:
                    error_count += 1
                    logger.error("Failed to repair %s: %s", file_manager.value, error)

            elif not is_active and original in (
                IntegrationStatus.INSTALLED,
                IntegrationStatus.PARTIAL,
            ):
                # Remove integration
                success, error = remove_integration(file_manager)
                if success:
                    removed_count += 1
                    logger.info("Removed %s integration", file_manager.value)
                else:
                    error_count += 1
                    logger.error("Failed to remove %s: %s", file_manager.value, error)

            # is_active + INSTALLED = no-op
            # not is_active + NOT_INSTALLED = no-op

        # Show result summary. On failure keep the dialog open — closing it
        # immediately would destroy the toast before the user could see that
        # anything failed (details are only in the log).
        self._show_result_toast(installed_count, removed_count, repaired_count, error_count)
        if error_count == 0:
            self._save_preference_and_close()

    def _show_result_toast(self, installed: int, removed: int, repaired: int, errors: int):
        """Show a summary toast of the apply results."""
        if errors > 0:
            parts = []
            total_ok = installed + removed + repaired
            if total_ok > 0:
                parts.append(_("{count} succeeded").format(count=total_ok))
            parts.append(_("{count} failed").format(count=errors))
            self._show_toast(", ".join(parts))
        else:
            parts = []
            if installed > 0:
                parts.append(_("{count} installed").format(count=installed))
            if removed > 0:
                parts.append(_("{count} removed").format(count=removed))
            if repaired > 0:
                parts.append(_("{count} repaired").format(count=repaired))
            if parts:
                self._show_toast(", ".join(parts))

    def _save_preference_and_close(self):
        """Save the prompted preference and close."""
        if self._settings_manager:
            self._settings_manager.set("file_manager_integration_prompted", True)

        self.close()

        if self._on_complete:
            self._on_complete()

    def _show_toast(self, message: str):
        """Show a toast notification."""
        toast = Adw.Toast.new(message)
        self._toast_overlay.add_toast(toast)
