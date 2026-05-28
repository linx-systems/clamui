# ClamUI System Audit View
"""
System security audit dashboard for ClamUI.

Provides a comprehensive security posture overview by checking:
- ClamAV health (database age, daemon status)
- Firewall configuration
- Mandatory access control (AppArmor/SELinux)
- Automatic security updates
- Intrusion detection systems
- SSH hardening
- Optional deep scans (Lynis, chkrootkit) via pkexec
"""

import logging
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..core.i18n import _
from ..core.system_audit import (
    TIER1_CHECKS,
    AuditCategory,
    AuditCheckResult,
    AuditReport,
    AuditSectionResult,
    AuditStatus,
    is_binary_installed,
    run_lynis_audit,
    run_rootkit_check,
)
from .compat import create_banner, safe_add_suffix
from .utils import resolve_icon_name
from .view_helpers import StatusLevel, clear_status_classes, set_status_class

logger = logging.getLogger(__name__)

# Status icon fallback chains — Gio.ThemedIcon tries each name in order.
# GTK stops at the first icon found by the theme even if it renders broken,
# so we put the most reliable icons FIRST (actions/emblems dirs are safest).
_STATUS_ICON_NAMES: dict[AuditStatus, list[str]] = {
    AuditStatus.PASS: [
        "emblem-ok-symbolic",
        "object-select-symbolic",
        "emblem-default-symbolic",
    ],
    AuditStatus.WARNING: [
        "dialog-warning-symbolic",
        "emblem-important-symbolic",
        "dialog-information-symbolic",
    ],
    AuditStatus.FAIL: [
        "process-stop-symbolic",
        "emblem-important-symbolic",
        "dialog-error-symbolic",
    ],
    AuditStatus.UNKNOWN: [
        "action-unavailable-symbolic",
        "find-location-symbolic",
        "dialog-question-symbolic",
    ],
    AuditStatus.SKIPPED: [
        "content-loading-symbolic",
        "action-unavailable-symbolic",
        "dialog-question-symbolic",
    ],
}

# Status to StatusLevel mapping for CSS classes
_STATUS_LEVELS: dict[AuditStatus, StatusLevel] = {
    AuditStatus.PASS: StatusLevel.SUCCESS,
    AuditStatus.WARNING: StatusLevel.WARNING,
    AuditStatus.FAIL: StatusLevel.ERROR,
}

_DEEP_SCAN_INFO_URLS = {
    "lynis": "https://cisofy.com/lynis/",
    "chkrootkit": "https://www.chkrootkit.org/",
}


class AuditView(Gtk.Box):
    """System security audit dashboard view."""

    def __init__(self, notification_manager=None, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)

        self._is_checking = False
        self._destroyed = False
        self._cached_report: AuditReport | None = None
        self._notification_manager = notification_manager
        self._is_first_run = True

        # Widget references for dynamic updates
        self._section_groups: dict[str, Adw.PreferencesGroup] = {}
        self._section_rows: dict[str, list[Adw.ActionRow]] = {}
        self._section_status_icons: dict[str, Gtk.Image] = {}
        self._section_spinners: dict[str, Gtk.Spinner] = {}

        # Optional collapsible wrapper for Portmaster (single instance — only
        # this section needs collapsed-when-absent behavior).
        self._portmaster_expander: Gtk.Expander | None = None
        self._portmaster_authorize_running = False

        # Deep scan state
        self._lynis_running = False
        self._rootkit_running = False
        self._lynis_button: Gtk.Button | None = None
        self._rootkit_button: Gtk.Button | None = None
        self._lynis_spinner: Gtk.Spinner | None = None
        self._rootkit_spinner: Gtk.Spinner | None = None
        self._deep_scan_install_rows: dict[str, Adw.ActionRow] = {}

        # Track whether initial data load has happened
        self._initial_load_done = False

        self._setup_ui()

        # Defer audit to when the view first becomes visible
        self.connect("map", self._on_first_map)

    # =========================================================================
    # UI Setup
    # =========================================================================

    def _setup_ui(self):
        """Build the audit view layout."""
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_spacing(18)

        # Main scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        # Header section
        self._create_header_section(content_box)

        # Summary banner (hidden until audit completes)
        self._summary_banner = create_banner()
        self._summary_banner.set_revealed(False)
        content_box.append(self._summary_banner)

        # Tier 1 check sections
        self._create_check_sections(content_box)

        # Deep scans section
        self._create_deep_scan_section(content_box)

        scrolled.set_child(content_box)
        self.append(scrolled)

    def _create_header_section(self, parent: Gtk.Box):
        """Create the header with title and refresh button."""
        header_group = Adw.PreferencesGroup()
        header_group.set_title(_("System Security Audit"))
        header_group.set_description(
            _("Check your system security posture and get recommendations")
        )

        # Refresh button + spinner in header
        refresh_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        refresh_box.set_valign(Gtk.Align.CENTER)

        self._refresh_spinner = Gtk.Spinner()
        self._refresh_spinner.set_visible(False)
        refresh_box.append(self._refresh_spinner)

        self._refresh_button = Gtk.Button()
        self._refresh_button.set_icon_name(resolve_icon_name("view-refresh-symbolic"))
        self._refresh_button.set_tooltip_text(_("Refresh Audit"))
        self._refresh_button.add_css_class("flat")
        self._refresh_button.connect("clicked", self._on_refresh_clicked)
        refresh_box.append(self._refresh_button)

        header_group.set_header_suffix(refresh_box)
        parent.append(header_group)

    def _create_check_sections(self, parent: Gtk.Box):
        """Create placeholder sections for each Tier 1 check category."""
        # Section definitions: (category_key, title, icon)
        sections = [
            (AuditCategory.CLAMAV_HEALTH, _("ClamAV Health"), "security-high-symbolic"),
            (AuditCategory.FIREWALL, _("Firewall"), "security-medium-symbolic"),
            (
                AuditCategory.MAC_FRAMEWORK,
                _("Access Control"),
                "system-lock-screen-symbolic",
            ),
            (
                AuditCategory.AUTO_UPDATES,
                _("Automatic Updates"),
                "software-update-available-symbolic",
            ),
            (
                AuditCategory.INTRUSION_DETECTION,
                _("Intrusion Detection"),
                "dialog-warning-symbolic",
            ),
            (AuditCategory.SSH_HARDENING, _("SSH Security"), "network-server-symbolic"),
            (AuditCategory.PORTMASTER, _("Portmaster"), "network-vpn-symbolic"),
        ]

        for category, title, _icon_name in sections:
            group = Adw.PreferencesGroup()
            group.set_title(title)

            # Status icon in header suffix
            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            header_box.set_valign(Gtk.Align.CENTER)

            spinner = Gtk.Spinner()
            spinner.start()
            header_box.append(spinner)

            # Initialize with themed icon for proper size allocation
            status_icon = self._create_status_image(AuditStatus.UNKNOWN)
            status_icon.set_visible(False)
            header_box.append(status_icon)

            group.set_header_suffix(header_box)

            # Placeholder "Checking..." row
            checking_row = Adw.ActionRow()
            checking_row.set_title(_("Checking..."))
            checking_row.set_subtitle(_("Running security check"))
            group.add(checking_row)

            # Store references
            key = category.value
            self._section_groups[key] = group
            self._section_rows[key] = [checking_row]
            self._section_spinners[key] = spinner
            self._section_status_icons[key] = status_icon

            if category is AuditCategory.PORTMASTER:
                # Wrap Portmaster in an expander so the section stays present
                # but collapses to just the hint label when Portmaster is not
                # detected (per user request: collapsed with hint when absent,
                # default-open when detected). _update_section_ui flips the
                # expanded state after the check completes.
                expander = Gtk.Expander()
                expander.set_label(_("Portmaster — checking…"))
                expander.set_expanded(True)
                expander.set_child(group)
                self._portmaster_expander = expander
                parent.append(expander)
            else:
                parent.append(group)

    def _create_deep_scan_section(self, parent: Gtk.Box):
        """Create the deep scans section with opt-in buttons."""
        self._deep_scan_group = Adw.PreferencesGroup()
        self._deep_scan_group.set_title(_("Deep Scans"))
        self._deep_scan_group.set_description(
            _("Require administrator privileges and may take several minutes")
        )

        # Lynis row — shows "Checking..." initially, updated after availability check
        self._lynis_row = self._create_deep_scan_action_row(
            _("Lynis Security Audit"), _("Checking availability...")
        )
        self._deep_scan_group.add(self._lynis_row)

        # chkrootkit row — same pattern
        self._rootkit_row = self._create_deep_scan_action_row(
            _("Rootkit Detection"), _("Checking availability...")
        )
        self._deep_scan_group.add(self._rootkit_row)

        # Deep scan results container (hidden until scan runs)
        self._deep_scan_results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._deep_scan_results_box.set_visible(False)

        parent.append(self._deep_scan_group)
        parent.append(self._deep_scan_results_box)

    def _create_deep_scan_action_row(self, title: str, subtitle: str) -> Adw.ActionRow:
        """Create a base ActionRow for a deep scan tool."""
        row = Adw.ActionRow()
        row.set_title(title)
        row.set_subtitle(subtitle)
        return row

    def _reset_deep_scan_rows(self):
        """Rebuild deep scan rows to avoid duplicated suffixes and command rows."""
        for row in (self._lynis_row, self._rootkit_row):
            if row is not None:
                self._deep_scan_group.remove(row)

        for row in self._deep_scan_install_rows.values():
            self._deep_scan_group.remove(row)
        self._deep_scan_install_rows = {}

        self._lynis_row = self._create_deep_scan_action_row(
            _("Lynis Security Audit"), _("Checking availability...")
        )
        self._rootkit_row = self._create_deep_scan_action_row(
            _("Rootkit Detection"), _("Checking availability...")
        )
        self._deep_scan_group.add(self._lynis_row)
        self._deep_scan_group.add(self._rootkit_row)

        self._lynis_button = None
        self._rootkit_button = None
        self._lynis_spinner = None
        self._rootkit_spinner = None

    def _setup_deep_scan_row(
        self,
        row: Adw.ActionRow,
        installed: bool,
        tool_name: str,
        description: str,
        info_url: str,
        install_command: str,
        on_run_clicked,
    ):
        """Configure a deep scan row based on whether the tool is installed."""
        row.set_subtitle(description)
        suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        suffix_box.set_valign(Gtk.Align.CENTER)

        info_button = Gtk.Button()
        info_button.set_icon_name(resolve_icon_name("help-about-symbolic"))
        info_button.set_tooltip_text(_("Learn more"))
        info_button.add_css_class("flat")
        info_button.add_css_class("dim-label")
        info_button.connect("clicked", self._on_info_clicked, info_url)
        suffix_box.append(info_button)

        if installed:
            spinner = Gtk.Spinner()
            spinner.set_visible(False)
            suffix_box.append(spinner)

            button = Gtk.Button()
            button.set_label(_("Run"))
            button.add_css_class("suggested-action")
            button.connect("clicked", on_run_clicked)
            suffix_box.append(button)

            safe_add_suffix(row, suffix_box)

            # Store references for spinner/button control
            if tool_name == "lynis":
                self._lynis_button = button
                self._lynis_spinner = spinner
            else:
                self._rootkit_button = button
                self._rootkit_spinner = spinner
        else:
            # Show "Not Installed" status + install command
            row.set_subtitle(_("{tool} is not installed").format(tool=tool_name))

            not_installed_icon = self._create_status_image(AuditStatus.UNKNOWN)
            not_installed_icon.set_valign(Gtk.Align.CENTER)
            suffix_box.append(not_installed_icon)
            safe_add_suffix(row, suffix_box)

            # Add install command row to the group
            cmd_row = self._create_command_row(install_command)
            self._deep_scan_group.add(cmd_row)
            self._deep_scan_install_rows[tool_name] = cmd_row

            # Disable button references
            if tool_name == "lynis":
                self._lynis_button = None
                self._lynis_spinner = None
            else:
                self._rootkit_button = None
                self._rootkit_spinner = None

    # =========================================================================
    # Audit Execution
    # =========================================================================

    def _on_first_map(self, widget):
        """Run audit when the view first becomes visible."""
        if not self._initial_load_done:
            self._initial_load_done = True
            self._run_audit_if_needed()

    def _run_audit_if_needed(self) -> bool:
        """Run audit if no cached results exist."""
        if self._cached_report is not None:
            self._display_cached_report()
        else:
            self._run_audit()
        return False  # Don't repeat

    def _run_audit(self):
        """Start background Tier 1 audit."""
        if self._is_checking:
            return
        self._set_checking_state(True)
        self._reset_sections_to_checking()
        thread = threading.Thread(target=self._run_checks_background, daemon=True)
        thread.start()

    def _run_checks_background(self):
        """Run all Tier 1 checks and deep scan availability in background thread."""
        if self._destroyed:
            return

        report = AuditReport(timestamp=time.time())

        for check_func in TIER1_CHECKS:
            if self._destroyed:
                return
            try:
                result = check_func()
                report.sections.append(result)
                # Progressive update: push each result to UI as it completes
                GLib.idle_add(self._update_section_ui, result)
            except Exception:
                logger.exception("Audit check failed: %s", check_func.__name__)

        # Check deep scan tool availability (runs in background, updates UI)
        if not self._destroyed:
            lynis_installed = is_binary_installed("lynis")
            chkrootkit_installed = is_binary_installed("chkrootkit")
            GLib.idle_add(
                self._update_deep_scan_availability,
                lynis_installed,
                chkrootkit_installed,
            )

        if not self._destroyed:
            GLib.idle_add(self._finalize_audit, report)

    def _update_deep_scan_availability(
        self, lynis_installed: bool, chkrootkit_installed: bool
    ) -> bool:
        """Update deep scan rows based on tool availability. Runs on main thread."""
        if self._destroyed:
            return False

        # Rebuild rows so repeated refreshes do not accumulate suffixes or
        # duplicate install command entries.
        self._reset_deep_scan_rows()

        # Determine install command based on package manager
        if is_binary_installed("apt"):
            lynis_cmd = "sudo apt install lynis"
            chkrootkit_cmd = "sudo apt install chkrootkit"
        elif is_binary_installed("dnf"):
            lynis_cmd = "sudo dnf install lynis"
            chkrootkit_cmd = "sudo dnf install chkrootkit"
        else:
            lynis_cmd = "sudo apt install lynis"
            chkrootkit_cmd = "sudo apt install chkrootkit"

        self._setup_deep_scan_row(
            self._lynis_row,
            lynis_installed,
            "lynis",
            _("Comprehensive system hardening analysis with scoring"),
            _DEEP_SCAN_INFO_URLS["lynis"],
            lynis_cmd,
            self._on_run_lynis,
        )
        self._setup_deep_scan_row(
            self._rootkit_row,
            chkrootkit_installed,
            "chkrootkit",
            _("Scan for known rootkits using chkrootkit"),
            _DEEP_SCAN_INFO_URLS["chkrootkit"],
            chkrootkit_cmd,
            self._on_run_rootkit,
        )

        return False  # Don't repeat

    def _finalize_audit(self, report: AuditReport) -> bool:
        """Complete the audit: update summary banner, cache results, and notify."""
        if self._destroyed:
            return False

        self._cached_report = report
        self._update_summary_banner(report)
        self._set_checking_state(False)

        # Notify on first run only, if there are issues
        if self._is_first_run and self._notification_manager is not None:
            self._is_first_run = False
            summary = report.summary
            warnings = summary.get(AuditStatus.WARNING, 0)
            issues = summary.get(AuditStatus.FAIL, 0)
            if warnings or issues:
                self._notification_manager.notify_audit_complete(warnings=warnings, issues=issues)

        return False  # Don't repeat

    # =========================================================================
    # UI Update Methods (called on main thread via GLib.idle_add)
    # =========================================================================

    def _update_section_ui(self, result: AuditSectionResult) -> bool:
        """Update a single section with check results."""
        if self._destroyed:
            return False

        key = result.category.value
        group = self._get_section_container(key)
        if group is None:
            return False

        # Remove all previously tracked rows
        for row in self._section_rows.get(key, []):
            group.remove(row)
        self._section_rows[key] = []

        # Add result rows (tracking them for later removal)
        new_rows: list[Adw.ActionRow] = []
        for check in result.checks:
            rows = self._add_check_row(group, check)
            new_rows.extend(rows)
        self._section_rows[key] = new_rows

        # Update header status icon
        spinner = self._section_spinners.get(key)
        status_icon = self._section_status_icons.get(key)
        if spinner:
            spinner.stop()
            spinner.set_visible(False)
        if status_icon:
            self._set_status_icon(status_icon, result.overall_status)
            status_icon.set_visible(True)

        # Portmaster collapses when nothing was detected. The hint stays
        # visible in the expander label so users still discover the feature.
        if result.category is AuditCategory.PORTMASTER and self._portmaster_expander is not None:
            self._apply_portmaster_expander_state(result)

        return False  # Don't repeat

    def _apply_portmaster_expander_state(self, result: AuditSectionResult):
        """Set the Portmaster expander label and expanded state from a result."""
        expander = self._portmaster_expander
        if expander is None:
            return
        if result.overall_status == AuditStatus.SKIPPED:
            expander.set_label(_("Portmaster — not detected (optional)"))
            expander.set_expanded(False)
        elif result.overall_status == AuditStatus.UNKNOWN:
            expander.set_label(_("Portmaster — could not probe"))
            expander.set_expanded(False)
        else:
            expander.set_label(_("Portmaster"))
            expander.set_expanded(True)

    def _add_check_row(
        self, group: Adw.PreferencesGroup, check: AuditCheckResult
    ) -> list[Adw.ActionRow]:
        """Add a single check result as ActionRow(s) to a group.

        Returns list of all rows added (for tracking/removal).
        """
        added: list[Adw.ActionRow] = []

        row = Adw.ActionRow()
        row.set_title(check.name)
        row.set_subtitle(check.detail)

        # Suffix box: info link + status icon
        suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        suffix_box.set_valign(Gtk.Align.CENTER)

        # Launch button (e.g., "Open Gufw")
        if check.launch_command:
            launch_button = Gtk.Button()
            launch_button.set_label(check.launch_label or _("Open"))
            launch_button.add_css_class("flat")
            launch_button.connect("clicked", self._on_launch_clicked, check.launch_command)
            suffix_box.append(launch_button)

        # Info link button (opens docs in browser)
        if check.info_url:
            info_button = Gtk.Button()
            info_button.set_icon_name(resolve_icon_name("help-about-symbolic"))
            info_button.set_tooltip_text(_("Learn more"))
            info_button.add_css_class("flat")
            info_button.add_css_class("dim-label")
            info_button.connect("clicked", self._on_info_clicked, check.info_url)
            suffix_box.append(info_button)

        # Status icon — use Gio.ThemedIcon for cross-theme fallbacks
        status_icon = self._create_status_image(check.status)
        suffix_box.append(status_icon)

        safe_add_suffix(row, suffix_box)

        group.add(row)
        added.append(row)

        # Recommendation row (if applicable)
        if check.recommendation and check.status != AuditStatus.PASS:
            rec_row = Adw.ActionRow()
            rec_row.set_title(check.recommendation)
            rec_row.add_css_class("dim-label")
            rec_row.set_activatable(False)
            group.add(rec_row)
            added.append(rec_row)

        # Install command row (if applicable)
        if check.install_command:
            cmd_row = self._create_command_row(check.install_command)
            group.add(cmd_row)
            added.append(cmd_row)

        return added

    def _create_command_row(self, command: str) -> Adw.ActionRow:
        """Create a row with a copyable command in a card frame."""
        row = Adw.ActionRow()
        row.set_activatable(False)

        # Command box with card frame + copy button (same pattern as ComponentsView)
        cmd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cmd_box.set_margin_top(4)
        cmd_box.set_margin_bottom(4)
        cmd_box.set_hexpand(True)

        # Command in a framed card
        cmd_frame = Gtk.Frame()
        cmd_frame.add_css_class("card")
        cmd_frame.set_hexpand(True)

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

        row.set_child(cmd_box)

        return row

    def _create_status_image(self, status: AuditStatus) -> Gtk.Image:
        """Create a Gtk.Image for the given audit status using themed icon fallbacks.

        Uses Gio.ThemedIcon with multiple fallback names so the icon renders
        correctly across all icon themes (Adwaita, Mint-Y, Breeze, Yaru, etc.).
        """
        names = _STATUS_ICON_NAMES.get(
            status,
            ["dialog-information-symbolic", "emblem-important-symbolic"],
        )
        themed_icon = Gio.ThemedIcon.new_from_names(names)
        image = Gtk.Image.new_from_gicon(themed_icon)
        image.set_pixel_size(16)

        # Apply color CSS class
        clear_status_classes(image)
        level = _STATUS_LEVELS.get(status)
        if level:
            set_status_class(image, level)
        else:
            image.add_css_class("dim-label")

        return image

    def _set_status_icon(self, icon: Gtk.Image, status: AuditStatus):
        """Update an existing Gtk.Image to show the given audit status."""
        names = _STATUS_ICON_NAMES.get(
            status,
            ["dialog-information-symbolic", "emblem-important-symbolic"],
        )
        themed_icon = Gio.ThemedIcon.new_from_names(names)
        icon.set_from_gicon(themed_icon)
        icon.set_pixel_size(16)

        clear_status_classes(icon)
        level = _STATUS_LEVELS.get(status)
        if level:
            set_status_class(icon, level)
        else:
            icon.add_css_class("dim-label")

    def _get_section_container(self, key: str):
        """Return the UI container used for a section key.

        Supports both the current `_section_groups` attribute and the legacy
        `_section_expanders` test fixture naming.
        """
        groups = getattr(self, "_section_groups", {}) or {}
        if key in groups:
            return groups[key]

        expanders = getattr(self, "_section_expanders", {}) or {}
        if key in expanders:
            return expanders[key]

        return None

    def _iter_section_containers(self):
        """Iterate over known section containers keyed by category."""
        containers = {}
        groups = getattr(self, "_section_groups", {}) or {}
        expanders = getattr(self, "_section_expanders", {}) or {}
        containers.update(groups)
        containers.update(expanders)
        return containers.items()

    def _update_summary_banner(self, report: AuditReport):
        """Update the summary banner with aggregate results."""
        summary = report.summary
        passed = summary.get(AuditStatus.PASS, 0)
        warnings = summary.get(AuditStatus.WARNING, 0)
        failed = summary.get(AuditStatus.FAIL, 0)

        if failed:
            title = _("{count} security issues need attention").format(count=failed)
        elif warnings:
            title = _("{count} checks need review").format(count=warnings)
            if passed:
                title = _("{review} · {passed} passed").format(review=title, passed=passed)
        else:
            title = _("Audit complete")

        self._summary_banner.set_title(title)
        self._summary_banner.set_revealed(True)

    def _display_cached_report(self):
        """Display results from cached report without re-running checks."""
        if self._cached_report is None:
            return

        for section_result in self._cached_report.sections:
            self._update_section_ui(section_result)

        self._update_summary_banner(self._cached_report)

    # =========================================================================
    # State Management
    # =========================================================================

    def _set_checking_state(self, is_checking: bool):
        """Toggle the checking state UI (spinner, button sensitivity)."""
        self._is_checking = is_checking

        if is_checking:
            self._refresh_button.set_sensitive(False)
            self._refresh_spinner.set_visible(True)
            self._refresh_spinner.start()
            self._summary_banner.set_revealed(False)
        else:
            self._refresh_button.set_sensitive(True)
            self._refresh_spinner.stop()
            self._refresh_spinner.set_visible(False)

    def _reset_sections_to_checking(self):
        """Reset all sections to their initial 'Checking...' state."""
        for key, group in self._iter_section_containers():
            # Remove all tracked rows
            for row in self._section_rows.get(key, []):
                group.remove(row)

            # Add placeholder
            checking_row = Adw.ActionRow()
            checking_row.set_title(_("Checking..."))
            checking_row.set_subtitle(_("Running security check"))
            group.add(checking_row)
            self._section_rows[key] = [checking_row]

            # Reset header icons
            spinner = self._section_spinners.get(key)
            status_icon = self._section_status_icons.get(key)
            if spinner:
                spinner.set_visible(True)
                spinner.start()
            if status_icon:
                status_icon.set_visible(False)

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _on_refresh_clicked(self, button: Gtk.Button):
        """Handle refresh button click."""
        if self._is_checking:
            return
        self._cached_report = None
        self._run_audit()

    def _on_launch_clicked(self, button: Gtk.Button, command: str):
        """Launch an application (e.g., firewall GUI) in the background.

        In Flatpak, GUI apps like gufw or firewall-config are on the host,
        so we use flatpak-spawn --host to launch them.
        """
        import subprocess

        from ..core.flatpak import is_flatpak

        # Sentinel: instead of spawning a subprocess, kick off Portmaster's
        # third-party authorization flow. Handled here (rather than in a
        # separate widget) to reuse the existing launch-button UX.
        if command == "__portmaster_authorize__":
            self._start_portmaster_authorize(button)
            return

        try:
            cmd = ["flatpak-spawn", "--host", command] if is_flatpak() else [command]
            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.warning("Could not launch: %s (not found)", command)
        except OSError as e:
            logger.warning("Could not launch %s: %s", command, e)

    def _start_portmaster_authorize(self, button: Gtk.Button):
        """Request a Portmaster app token in a background thread.

        The /api/v1/app/auth endpoint blocks until the user accepts or
        declines inside Portmaster's UI, so we must not block the main loop.
        On success the token is stored via keyring_manager and the Portmaster
        section is re-run to show the per-module rows.
        """
        if self._portmaster_authorize_running:
            return
        self._portmaster_authorize_running = True
        button.set_sensitive(False)

        def _worker():
            from ..core.keyring_manager import set_portmaster_token
            from ..core.portmaster_client import request_app_token

            token, err = request_app_token(read_scope="user")
            if not self._destroyed:
                GLib.idle_add(self._on_portmaster_authorize_done, button, token, err)
            if token:
                ok, msg = set_portmaster_token(token)
                if not ok:
                    logger.warning("Could not persist Portmaster token: %s", msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_portmaster_authorize_done(
        self, button: Gtk.Button, token: str | None, err: str | None
    ) -> bool:
        """Handle Portmaster authorization completion on the main thread."""
        self._portmaster_authorize_running = False
        if self._destroyed:
            return False
        button.set_sensitive(True)
        if err:
            logger.info("Portmaster authorization failed: %s", err)
        if token:
            # Re-run just the Portmaster section to pick up module status now
            # that we have a token. Reuse the existing audit-run path so the
            # spinner/status-icon UI is consistent.
            from ..core.system_audit import check_portmaster

            def _rerun():
                section = check_portmaster()
                if not self._destroyed:
                    GLib.idle_add(self._update_section_ui, section)

            threading.Thread(target=_rerun, daemon=True).start()
        return False

    def _on_info_clicked(self, button: Gtk.Button, url: str):
        """Open info URL in the default browser."""
        try:
            Gtk.show_uri(None, url, Gdk.CURRENT_TIME)
        except Exception:
            # Fallback: try Gio
            try:
                Gio.AppInfo.launch_default_for_uri(url, None)
            except Exception:
                logger.warning("Could not open URL: %s", url)

    def _on_copy_clicked(self, button: Gtk.Button, command: str):
        """Copy command text to clipboard with visual feedback."""
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

    def _on_run_lynis(self, button: Gtk.Button):
        """Run Lynis deep scan in background."""
        if self._lynis_running or self._lynis_button is None:
            return
        self._lynis_running = True
        self._lynis_button.set_sensitive(False)
        if self._lynis_spinner:
            self._lynis_spinner.set_visible(True)
            self._lynis_spinner.start()

        thread = threading.Thread(target=self._run_lynis_background, daemon=True)
        thread.start()

    def _run_lynis_background(self):
        """Execute Lynis audit in background thread."""
        if self._destroyed:
            return
        result = run_lynis_audit()
        if not self._destroyed:
            GLib.idle_add(self._on_deep_scan_complete, result, "lynis")

    def _on_run_rootkit(self, button: Gtk.Button):
        """Run chkrootkit scan in background."""
        if self._rootkit_running or self._rootkit_button is None:
            return
        self._rootkit_running = True
        self._rootkit_button.set_sensitive(False)
        if self._rootkit_spinner:
            self._rootkit_spinner.set_visible(True)
            self._rootkit_spinner.start()

        thread = threading.Thread(target=self._run_rootkit_background, daemon=True)
        thread.start()

    def _run_rootkit_background(self):
        """Execute chkrootkit in background thread."""
        if self._destroyed:
            return
        result = run_rootkit_check()
        if not self._destroyed:
            GLib.idle_add(self._on_deep_scan_complete, result, "rootkit")

    def _on_deep_scan_complete(self, result: AuditSectionResult, scan_type: str) -> bool:
        """Handle deep scan completion on main thread."""
        if self._destroyed:
            return False

        if scan_type == "lynis":
            self._lynis_running = False
            if self._lynis_button:
                self._lynis_button.set_sensitive(True)
            if self._lynis_spinner:
                self._lynis_spinner.stop()
                self._lynis_spinner.set_visible(False)
        elif scan_type == "rootkit":
            self._rootkit_running = False
            if self._rootkit_button:
                self._rootkit_button.set_sensitive(True)
            if self._rootkit_spinner:
                self._rootkit_spinner.stop()
                self._rootkit_spinner.set_visible(False)

        # Show results in the deep scan results area
        self._show_deep_scan_results(result)

        # Append to cached report if exists
        if self._cached_report is not None:
            # Remove previous result of same category
            self._cached_report.sections = [
                s for s in self._cached_report.sections if s.category != result.category
            ]
            self._cached_report.sections.append(result)

        return False  # Don't repeat

    def _show_deep_scan_results(self, result: AuditSectionResult):
        """Display deep scan results in a new PreferencesGroup."""
        self._deep_scan_results_box.set_visible(True)

        # Remove previous results group for this category if exists
        child = self._deep_scan_results_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            if hasattr(child, "_audit_category") and child._audit_category == result.category.value:
                self._deep_scan_results_box.remove(child)
            child = next_child

        # Create results group
        group = Adw.PreferencesGroup()
        group.set_title(result.title)
        group._audit_category = result.category.value  # Tag for replacement

        # Header status icon
        status_icon = self._create_status_image(result.overall_status)
        status_icon.set_valign(Gtk.Align.CENTER)
        group.set_header_suffix(status_icon)

        # Add check rows
        for check in result.checks:
            self._add_check_row(group, check)

        self._deep_scan_results_box.append(group)
