# ClamUI Components View
"""
Components status view for ClamUI displaying ClamAV component availability and setup guides.
"""

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ..core.flatpak import is_flatpak
from ..core.i18n import N_, _
from ..core.log_manager import DaemonStatus, LogManager
from ..core.utils import (
    check_clamav_installed,
    check_clamdscan_installed,
    check_freshclam_installed,
)
from .compat import safe_add_suffix
from .utils import add_row_icon, resolve_icon_name
from .view_helpers import StatusLevel, clear_status_classes, set_status_class

logger = logging.getLogger(__name__)

# Setup guide content for each component
# NOTE: "title" and "notes" use N_() for deferred translation (translated at display time).
# "commands" contain shell commands which must NOT be translated.
# Distro names (Ubuntu/Debian, Fedora, Arch Linux) are proper nouns and not translated.
SETUP_GUIDES = {
    "clamscan": {
        "title": N_("clamscan Installation"),
        "commands": [
            ("Ubuntu/Debian", "sudo apt install clamav"),
            ("Fedora", "sudo dnf install clamav"),
            ("Arch Linux", "sudo pacman -S clamav"),
        ],
        "notes": N_(
            "clamscan is the on-demand virus scanner. After installation, update the virus database with freshclam."
        ),
    },
    "freshclam": {
        "title": N_("freshclam Installation"),
        "commands": [
            ("Ubuntu/Debian", "sudo apt install clamav-freshclam"),
            ("Fedora", "sudo dnf install clamav-update"),
            ("Arch Linux", "sudo pacman -S clamav"),
        ],
        "notes": N_(
            "freshclam updates the virus database. Enable the service for automatic updates:"
        )
        + "\nsudo systemctl enable clamav-freshclam\nsudo systemctl start clamav-freshclam",
    },
    "clamdscan": {
        "title": N_("clamdscan Installation"),
        "commands": [
            ("Ubuntu/Debian", "sudo apt install clamav-daemon"),
            ("Fedora", "sudo dnf install clamd"),
            ("Arch Linux", "sudo pacman -S clamav"),
        ],
        "notes": N_(
            "clamdscan is a client for the clamd daemon, providing faster scanning. Requires clamd daemon to be running."
        ),
    },
    "clamd": {
        "title": N_("clamd Daemon Setup"),
        "commands": [
            (
                "Ubuntu/Debian",
                "sudo apt install clamav-daemon\nsudo systemctl enable clamav-daemon\nsudo systemctl start clamav-daemon",
            ),
            (
                "Fedora",
                "sudo dnf install clamd clamav-update\nsudo freshclam\nsudo systemctl enable clamd@scan\nsudo systemctl start clamd@scan",
            ),
            (
                "Arch Linux",
                "sudo pacman -S clamav\nsudo systemctl enable clamav-daemon\nsudo systemctl start clamav-daemon",
            ),
        ],
        "notes": N_("clamd is the ClamAV daemon for faster scanning.")
        + " "
        + N_("Configuration file location is auto-detected in Preferences.")
        + " "
        + N_(
            "On Fedora, ClamUI uses /etc/clamd.d/scan.conf. If the daemon is running but still unavailable, verify socket permissions and test with: clamdscan --config-file=/etc/clamd.d/scan.conf --ping 3"
        ),
    },
}


class ComponentsView(Gtk.Box):
    """
    Components status view for ClamUI.

    Provides the components status interface with:
    - Status display for each ClamAV component
    - Expandable setup guides with installation commands
    - Refresh button to re-check component status
    """

    def __init__(self, log_manager=None, **kwargs):
        """
        Initialize the components view.

        Args:
            log_manager: Optional shared LogManager instance. If not provided,
                a new one is created.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)

        # Use shared log manager if provided, otherwise create own
        self._log_manager = log_manager if log_manager is not None else LogManager()

        # Is checking state
        self._is_checking = False

        # Widget destruction flag for safe background thread callbacks
        self._destroyed = False

        # Component status widgets storage
        self._component_rows = {}
        self._status_icons = {}
        self._status_labels = {}
        self._guide_rows = {}

        # Track whether initial data load has happened
        self._initial_load_done = False

        # Set up the UI
        self._setup_ui()

        # Defer data loading until view becomes visible
        self.connect("map", self._on_first_map)

    def _setup_ui(self):
        """Set up the components view UI layout."""
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_spacing(18)

        # Create the info section
        self._create_info_section()

        # Create the components status section (includes refresh button in header)
        self._create_components_section()

    def _create_info_section(self):
        """Create the info/description section."""
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("ClamAV Components"))
        info_group.set_description(
            _("Check the status of ClamAV components and get setup instructions")
        )

        # Info row explaining the view
        info_row = Adw.ActionRow()
        info_row.set_title(_("Component Status"))
        info_row.set_subtitle(_("View installation status and setup guides for ClamAV tools"))
        add_row_icon(info_row, "applications-system-symbolic")

        info_group.add(info_row)
        self.append(info_group)

    def _create_components_section(self):
        """Create the components status section with expandable rows."""
        # Create scrolled window to contain components with max height
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(400)
        scrolled.set_propagate_natural_height(True)

        components_group = Adw.PreferencesGroup()
        components_group.set_title(_("Components Status"))
        # Set description based on whether running in Flatpak
        if is_flatpak():
            components_group.set_description(
                _(
                    "ClamAV tools must be installed on the host system. "
                    "Flatpak runs them through flatpak-spawn."
                )
            )
        else:
            components_group.set_description(
                _("Expand each component for installation instructions")
            )
        self._components_group = components_group

        # Add refresh button to the header
        self._create_refresh_header_widget(components_group)

        # Create component rows
        self._create_component_row(
            components_group, "clamscan", _("Virus Scanner"), "security-high-symbolic"
        )
        self._create_component_row(
            components_group,
            "freshclam",
            _("Database Updater"),
            "software-update-available-symbolic",
        )

        # Daemon components are shown for both native and Flatpak installations
        # In Flatpak, daemon commands run on the host via flatpak-spawn --host
        self._create_component_row(
            components_group,
            "clamdscan",
            _("Daemon Scanner Client"),
            "network-server-symbolic",
        )
        self._create_component_row(
            components_group, "clamd", _("Scanner Daemon"), "system-run-symbolic"
        )

        scrolled.set_child(components_group)
        self.append(scrolled)

    def _create_component_row(
        self, group: Adw.PreferencesGroup, component_id: str, title: str, icon_name: str
    ):
        """
        Create an expandable row for a component with status and setup guide.

        Args:
            group: The PreferencesGroup to add the row to
            component_id: Identifier for the component (clamscan, freshclam, etc.)
            title: Display title for the component
            icon_name: Icon name for the component
        """
        # Create expander row
        expander = Adw.ExpanderRow()
        expander.set_title(title)
        expander.set_subtitle(_("Checking..."))
        add_row_icon(expander, icon_name)

        # Add status suffix widget
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_box.set_valign(Gtk.Align.CENTER)

        status_icon = Gtk.Image()
        status_icon.set_from_icon_name(resolve_icon_name("dialog-question-symbolic"))
        status_box.append(status_icon)

        status_label = Gtk.Label()
        status_label.set_text(_("Checking"))
        status_label.add_css_class("dim-label")
        status_box.append(status_label)

        safe_add_suffix(expander, status_box)

        # Store references for updating
        self._component_rows[component_id] = expander
        self._status_icons[component_id] = status_icon
        self._status_labels[component_id] = status_label

        # Add setup guide content
        self._add_setup_guide(expander, component_id)

        group.add(expander)

    def _add_setup_guide(self, expander: Adw.ExpanderRow, component_id: str):
        """
        Add setup guide content to an expander row.

        Args:
            expander: The ExpanderRow to add content to
            component_id: Component identifier for guide lookup
        """
        guide = SETUP_GUIDES.get(component_id, {})

        # Create inner content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)

        # Add installation commands for each distro
        commands = guide.get("commands", [])
        for distro, command in commands:
            command_row = self._create_command_row(distro, command)
            content_box.append(command_row)

        # Add notes if present
        notes = guide.get("notes", "")
        if notes:
            notes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            notes_box.set_margin_top(6)

            notes_label = Gtk.Label()
            notes_label.set_markup(f"<small><i>{GLib.markup_escape_text(notes)}</i></small>")
            notes_label.set_wrap(True)
            notes_label.set_xalign(0)
            notes_label.add_css_class("dim-label")

            notes_box.append(notes_label)
            content_box.append(notes_box)

        # Wrap in ActionRow for proper styling
        guide_row = Adw.ActionRow()
        guide_row.set_activatable(False)
        guide_row.set_child(content_box)

        expander.add_row(guide_row)

        # Store guide row reference so we can hide/show it based on installation status
        self._guide_rows[component_id] = guide_row

    def _create_command_row(self, distro: str, command: str) -> Gtk.Box:
        """
        Create a row displaying a command with copy button.

        Args:
            distro: Distribution name
            command: Command(s) to display

        Returns:
            Box widget containing the command display
        """
        row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        # Distro label
        distro_label = Gtk.Label()
        distro_label.set_markup(f"<b>{GLib.markup_escape_text(distro)}:</b>")
        distro_label.set_xalign(0)
        row_box.append(distro_label)

        # Command box with copy button
        cmd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Command label in a frame
        cmd_frame = Gtk.Frame()
        cmd_frame.add_css_class("card")

        cmd_label = Gtk.Label()
        cmd_label.set_text(command)
        cmd_label.set_xalign(0)
        cmd_label.set_selectable(True)
        cmd_label.add_css_class("monospace")
        cmd_label.set_margin_top(6)
        cmd_label.set_margin_bottom(6)
        cmd_label.set_margin_start(8)
        cmd_label.set_margin_end(8)

        cmd_frame.set_child(cmd_label)
        cmd_box.append(cmd_frame)

        # Copy button
        copy_button = Gtk.Button()
        copy_button.set_icon_name(resolve_icon_name("edit-copy-symbolic"))
        copy_button.set_tooltip_text(_("Copy to clipboard"))
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.add_css_class("flat")
        copy_button.connect("clicked", self._on_copy_clicked, command)
        cmd_box.append(copy_button)

        row_box.append(cmd_box)

        return row_box

    def _on_copy_clicked(self, button: Gtk.Button, command: str):
        """
        Handle copy button click.

        Args:
            button: The clicked button
            command: Command text to copy
        """
        clipboard = button.get_clipboard()
        clipboard.set(command)

        button.set_icon_name(resolve_icon_name("object-select-symbolic"))
        GLib.timeout_add(
            1500,
            lambda: (
                button.set_icon_name(resolve_icon_name("edit-copy-symbolic"))
                if not self._destroyed
                else None
            ),
        )

    def _create_refresh_header_widget(self, group: Adw.PreferencesGroup):
        """
        Create and add refresh button to the preferences group header.

        Args:
            group: The PreferencesGroup to add the header widget to
        """
        # Create container for refresh button and spinner
        refresh_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        refresh_box.set_valign(Gtk.Align.CENTER)

        # Refresh spinner (hidden by default)
        self._refresh_spinner = Gtk.Spinner()
        self._refresh_spinner.set_visible(False)
        refresh_box.append(self._refresh_spinner)

        # Refresh button
        self._refresh_button = Gtk.Button()
        self._refresh_button.set_icon_name(resolve_icon_name("view-refresh-symbolic"))
        self._refresh_button.set_tooltip_text(_("Refresh Status"))
        self._refresh_button.add_css_class("flat")
        self._refresh_button.connect("clicked", self._on_refresh_clicked)
        refresh_box.append(self._refresh_button)

        group.set_header_suffix(refresh_box)

    def _on_first_map(self, widget):
        """Load component data when the view first becomes visible."""
        if not self._initial_load_done:
            self._initial_load_done = True
            self._check_all_components()

    def _on_refresh_clicked(self, button: Gtk.Button):
        """Handle refresh button click."""
        if self._is_checking:
            return

        self._check_all_components()

    def _set_checking_state(self, is_checking: bool):
        """
        Update UI to reflect checking state.

        Args:
            is_checking: Whether status check is in progress
        """
        self._is_checking = is_checking

        if is_checking:
            self._refresh_button.set_sensitive(False)
            self._refresh_spinner.set_visible(True)
            self._refresh_spinner.start()
        else:
            self._refresh_button.set_sensitive(True)
            self._refresh_spinner.stop()
            self._refresh_spinner.set_visible(False)

    def _check_all_components(self):
        """Start background component status check."""
        self._set_checking_state(True)
        thread = threading.Thread(target=self._check_components_background, daemon=True)
        thread.start()
        return False  # Don't repeat (for GLib.idle_add)

    def _check_components_background(self):
        """Run all subprocess checks in a background thread.

        Collects results from all ClamAV component checks, then
        schedules a UI update on the main thread via GLib.idle_add.
        """
        if self._destroyed:
            return

        results = {}

        try:
            # Check clamscan
            results["clamscan"] = check_clamav_installed()

            # Check freshclam
            results["freshclam"] = check_freshclam_installed()

            # Check clamdscan (runs on host via flatpak-spawn in Flatpak mode)
            results["clamdscan"] = check_clamdscan_installed()

            # Check clamd daemon (runs on host via flatpak-spawn in Flatpak mode)
            daemon_status, daemon_message = self._log_manager.get_daemon_status()
            results["clamd"] = (daemon_status.value, daemon_message)
        except Exception:
            # A failing subprocess/daemon check must never strand the worker
            # thread: the UI update (which resets the checking state and stops
            # the spinner) is always scheduled, even with partial results.
            logger.exception("Component status check failed")
        finally:
            if not self._destroyed:
                GLib.idle_add(self._update_components_ui, results)

    def _update_components_ui(self, results):
        """Update component status UI on the main thread.

        Called via GLib.idle_add from the background thread.

        Args:
            results: Dict mapping component_id to check results
        """
        if self._destroyed:
            return False

        # Update clamscan, freshclam, clamdscan
        for component_id in ("clamscan", "freshclam", "clamdscan"):
            if component_id in results:
                is_installed, version_or_error = results[component_id]
                self._update_component_status(component_id, is_installed, version_or_error)

        # Update clamd daemon status
        if "clamd" in results:
            status_value, daemon_message = results["clamd"]
            daemon_status = DaemonStatus(status_value)
            self._update_daemon_status("clamd", daemon_status, daemon_message)

        # Reset checking state
        self._set_checking_state(False)

        return False  # Don't repeat

    def _update_component_status(self, component_id: str, is_installed: bool, message: str):
        """
        Update the status display for a component.

        Args:
            component_id: Component identifier
            is_installed: Whether component is installed
            message: Version string or error message
        """
        expander = self._component_rows.get(component_id)
        status_icon = self._status_icons.get(component_id)
        status_label = self._status_labels.get(component_id)

        if not expander or not status_icon or not status_label:
            return

        # Remove previous CSS classes
        clear_status_classes(status_icon)

        if is_installed:
            status_icon.set_from_icon_name(resolve_icon_name("object-select-symbolic"))
            set_status_class(status_icon, StatusLevel.SUCCESS)
            status_label.set_text(_("Installed"))
            expander.set_subtitle(message or _("Installed"))

            # Hide installation guide and disable expander for installed components
            guide_row = self._guide_rows.get(component_id)
            if guide_row:
                guide_row.set_visible(False)
            expander.set_enable_expansion(False)
        else:
            status_icon.set_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
            set_status_class(status_icon, StatusLevel.WARNING)
            status_label.set_text(_("Not installed"))
            expander.set_subtitle(_("Not installed - expand for setup instructions"))

            # Show installation guide and enable expander for not installed components
            guide_row = self._guide_rows.get(component_id)
            if guide_row:
                guide_row.set_visible(True)
            expander.set_enable_expansion(True)

    def _update_daemon_status(self, component_id: str, status: DaemonStatus, message: str):
        """
        Update the status display for the clamd daemon.

        Args:
            component_id: Component identifier (should be "clamd")
            status: DaemonStatus enum value
            message: Status message
        """
        expander = self._component_rows.get(component_id)
        status_icon = self._status_icons.get(component_id)
        status_label = self._status_labels.get(component_id)

        if not expander or not status_icon or not status_label:
            return

        # Remove previous CSS classes
        clear_status_classes(status_icon)

        guide_row = self._guide_rows.get(component_id)

        if status == DaemonStatus.RUNNING:
            status_icon.set_from_icon_name(resolve_icon_name("object-select-symbolic"))
            set_status_class(status_icon, StatusLevel.SUCCESS)
            status_label.set_text(_("Running"))
            expander.set_subtitle(_("Daemon is running"))
            # Hide guide and disable expansion when daemon is running
            if guide_row:
                guide_row.set_visible(False)
            expander.set_enable_expansion(False)
        elif status == DaemonStatus.STOPPED:
            status_icon.set_from_icon_name(resolve_icon_name("media-playback-stop-symbolic"))
            set_status_class(status_icon, StatusLevel.WARNING)
            status_label.set_text(_("Stopped"))
            expander.set_subtitle(_("Daemon is installed but not running"))
            # Show guide and enable expansion for stopped daemon
            if guide_row:
                guide_row.set_visible(True)
            expander.set_enable_expansion(True)
        elif status == DaemonStatus.NOT_INSTALLED:
            status_icon.set_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
            set_status_class(status_icon, StatusLevel.WARNING)
            status_label.set_text(_("Not installed"))
            expander.set_subtitle(_("Not installed - expand for setup instructions"))
            # Show guide and enable expansion for not installed daemon
            if guide_row:
                guide_row.set_visible(True)
            expander.set_enable_expansion(True)
        else:  # UNKNOWN
            status_icon.set_from_icon_name(resolve_icon_name("dialog-question-symbolic"))
            status_label.set_text(_("Unknown"))
            expander.set_subtitle(message or _("Unable to determine status"))
            # Show guide and enable expansion for unknown status
            if guide_row:
                guide_row.set_visible(True)
            expander.set_enable_expansion(True)
