# ClamUI Update View
"""
Database update interface component for ClamUI with update button, progress display, and results.
"""

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ..core.i18n import _, ngettext
from ..core.updater import (
    FreshclamServiceStatus,
    FreshclamUpdater,
    UpdateMethod,
    UpdateResult,
    UpdateStatus,
)
from ..core.utils import check_freshclam_installed
from .compat import create_banner
from .utils import add_row_icon, resolve_icon_name
from .view_helpers import StatusLevel, set_status_class

logger = logging.getLogger(__name__)


class UpdateView(Gtk.Box):
    """
    Database update interface component for ClamUI.

    Provides the database update interface with:
    - Freshclam availability status
    - Update button with progress indication
    - Results display area
    """

    def __init__(self, **kwargs):
        """
        Initialize the update view.

        Args:
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)

        # Initialize updater
        self._updater = FreshclamUpdater()

        # Updating state
        self._is_updating = False

        # Freshclam availability
        self._freshclam_available = False

        # Service status
        self._service_status = FreshclamServiceStatus.UNKNOWN

        # Set up the UI
        self._setup_ui()

        # Check freshclam availability in background thread to avoid blocking the UI
        thread = threading.Thread(target=self._check_freshclam_status_async, daemon=True)
        thread.start()

    def _setup_ui(self):
        """Set up the update view UI layout."""
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_spacing(18)

        # Create the info section
        self._create_info_section()

        # Create the update button section
        self._create_update_section()

        # Create the results section
        self._create_results_section()

        # Create the status bar
        self._create_status_bar()

    def _create_info_section(self):
        """Create the info/description section."""
        # Info frame
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("Database Update"))
        info_group.set_description(
            _("Update ClamAV virus definitions to detect the latest threats")
        )

        # Info row explaining the update process
        info_row = Adw.ActionRow()
        info_row.set_title(_("Virus Definitions"))
        info_row.set_subtitle(_("Click 'Update Database' to download the latest virus signatures"))
        add_row_icon(info_row, "software-update-available-symbolic")

        info_group.add(info_row)
        self.append(info_group)

    def _create_update_section(self):
        """Create the update button section."""
        # Update button container
        update_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        update_box.set_halign(Gtk.Align.CENTER)
        update_box.set_spacing(12)

        # Spinner for update progress (hidden by default)
        self._update_spinner = Gtk.Spinner()
        self._update_spinner.set_visible(False)

        # Update button
        self._update_button = Gtk.Button()
        self._update_button.set_label(_("Update Database"))
        self._update_button.set_tooltip_text(_("Update Database (F6)"))
        self._update_button.add_css_class("suggested-action")
        self._update_button.add_css_class("pill")
        self._update_button.set_sensitive(False)  # Disabled until freshclam is verified
        self._update_button.connect("clicked", self._on_update_clicked)

        # Make the button larger
        self._update_button.set_size_request(160, 40)

        # Force Update button - less prominent than main Update button
        self._force_update_button = Gtk.Button()
        self._force_update_button.set_label(_("Force Update"))
        self._force_update_button.set_tooltip_text(
            _(
                "Force update: Backs up local databases, deletes them, then downloads fresh copies "
                "from mirrors. Automatically restores from backup if update fails."
            )
        )
        self._force_update_button.add_css_class("pill")
        self._force_update_button.set_sensitive(False)  # Disabled until freshclam is verified
        self._force_update_button.connect("clicked", self._on_force_update_clicked)

        # Cancel button (hidden by default)
        self._cancel_button = Gtk.Button()
        self._cancel_button.set_label(_("Cancel"))
        self._cancel_button.add_css_class("destructive-action")
        self._cancel_button.add_css_class("pill")
        self._cancel_button.set_visible(False)
        self._cancel_button.connect("clicked", self._on_cancel_clicked)

        update_box.append(self._update_spinner)
        update_box.append(self._update_button)
        update_box.append(self._force_update_button)
        update_box.append(self._cancel_button)

        self.append(update_box)

    def _create_results_section(self):
        """Create the results display section."""
        # Results frame
        results_group = Adw.PreferencesGroup()
        results_group.set_title(_("Update Results"))
        results_group.set_description(_("Results will appear here after updating"))
        self._results_group = results_group

        # Results container
        results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        results_box.set_spacing(12)

        # Status banner (hidden by default)
        self._status_banner = create_banner()
        self._status_banner.set_revealed(False)
        self._status_banner.set_button_label(_("Dismiss"))
        self._status_banner.connect("button-clicked", self._on_status_banner_dismissed)
        results_box.append(self._status_banner)

        # Results text view in a scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(200)
        scrolled.set_vexpand(True)
        scrolled.add_css_class("card")

        self._results_text = Gtk.TextView()
        self._results_text.set_editable(False)
        self._results_text.set_cursor_visible(False)
        self._results_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._results_text.set_left_margin(12)
        self._results_text.set_right_margin(12)
        self._results_text.set_top_margin(12)
        self._results_text.set_bottom_margin(12)
        self._results_text.add_css_class("monospace")

        # Set placeholder text
        buffer = self._results_text.get_buffer()
        buffer.set_text(
            _("No update results yet.")
            + "\n\n"
            + _("Click 'Update Database' to download the latest virus definitions.")
        )

        scrolled.set_child(self._results_text)
        results_box.append(scrolled)

        results_group.add(results_box)
        self.append(results_group)

    def _create_status_bar(self):
        """Create the status bar at the bottom."""
        # Status bar container
        status_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        status_container.set_spacing(6)

        # Freshclam status row
        freshclam_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        freshclam_box.set_halign(Gtk.Align.CENTER)
        freshclam_box.set_spacing(6)

        # Freshclam status icon
        self._freshclam_status_icon = Gtk.Image()
        self._freshclam_status_icon.set_from_icon_name(
            resolve_icon_name("dialog-question-symbolic")
        )

        # Freshclam status label
        self._freshclam_status_label = Gtk.Label()
        self._freshclam_status_label.set_text(_("Checking freshclam..."))
        self._freshclam_status_label.add_css_class("dim-label")

        freshclam_box.append(self._freshclam_status_icon)
        freshclam_box.append(self._freshclam_status_label)
        status_container.append(freshclam_box)

        # Service status row
        service_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        service_box.set_halign(Gtk.Align.CENTER)
        service_box.set_spacing(6)

        # Service status icon
        self._service_status_icon = Gtk.Image()
        self._service_status_icon.set_from_icon_name(resolve_icon_name("system-run-symbolic"))

        # Service status label
        self._service_status_label = Gtk.Label()
        self._service_status_label.set_text(_("Checking service..."))
        self._service_status_label.add_css_class("dim-label")

        service_box.append(self._service_status_icon)
        service_box.append(self._service_status_label)
        status_container.append(service_box)

        self.append(status_container)

    def _check_freshclam_status(self):
        """Check freshclam installation status and service status, then update UI."""
        is_installed, version_or_error = check_freshclam_installed()

        if is_installed:
            self._freshclam_available = True
            self._freshclam_status_icon.set_from_icon_name(
                resolve_icon_name("object-select-symbolic")
            )
            self._freshclam_status_icon.add_css_class("success")
            self._freshclam_status_label.set_text(
                _("freshclam: {version}").format(version=version_or_error)
            )

            # Enable update buttons
            self._update_button.set_sensitive(True)
            self._force_update_button.set_sensitive(True)

            # Check service status
            self._check_service_status()
        else:
            self._freshclam_available = False
            self._freshclam_status_icon.set_from_icon_name(
                resolve_icon_name("dialog-warning-symbolic")
            )
            self._freshclam_status_icon.add_css_class("warning")
            self._freshclam_status_label.set_text(version_or_error or _("freshclam not found"))

            # Disable update buttons and show error banner
            self._update_button.set_sensitive(False)
            self._force_update_button.set_sensitive(False)
            self._status_banner.set_title(version_or_error or _("freshclam not installed"))
            self._status_banner.set_revealed(True)

            # Hide service status when freshclam not available
            self._service_status_label.set_text(_("Service: N/A"))
            self._service_status = FreshclamServiceStatus.NOT_FOUND

        return False  # Don't repeat

    def _check_freshclam_status_async(self):
        """
        Run freshclam installation and service checks in a background thread.

        Gathers results from subprocess calls without blocking the GTK main thread,
        then schedules UI update on the main thread via GLib.idle_add.
        """
        try:
            is_installed, version_or_error = check_freshclam_installed()

            # Only check service status if freshclam is installed
            if is_installed:
                service_status, service_pid = self._updater.check_freshclam_service()
            else:
                service_status = FreshclamServiceStatus.NOT_FOUND
                service_pid = None

            result = {
                "is_installed": is_installed,
                "version_or_error": version_or_error,
                "service_status": service_status,
                "service_pid": service_pid,
            }

            GLib.idle_add(self._apply_freshclam_status, result)
        except Exception:
            # If subprocess calls fail, schedule a fallback UI update
            logger.warning(
                "Failed to check freshclam status; falling back to default UI state",
                exc_info=True,
            )
            result = {
                "is_installed": False,
                "version_or_error": _("Error checking freshclam status"),
                "service_status": FreshclamServiceStatus.UNKNOWN,
                "service_pid": None,
            }
            try:
                GLib.idle_add(self._apply_freshclam_status, result)
            except Exception:
                logger.debug(
                    "Skipping fallback freshclam UI update because the widget may be destroyed",
                    exc_info=True,
                )
                return  # Widget may be destroyed; nothing to do

    def _apply_freshclam_status(self, result):
        """
        Update UI with freshclam status results (called on main thread via GLib.idle_add).

        Args:
            result: Dict with keys is_installed, version_or_error, service_status, service_pid

        Returns:
            False to remove from idle (GLib.SOURCE_REMOVE)
        """
        # Guard against widget being destroyed before callback fires
        try:
            if not self.get_mapped():
                return False
        except Exception:
            logger.debug(
                "Skipping freshclam status update because the widget is unavailable",
                exc_info=True,
            )
            return False

        is_installed = result["is_installed"]
        version_or_error = result["version_or_error"]
        service_status = result["service_status"]
        service_pid = result["service_pid"]

        if is_installed:
            self._freshclam_available = True
            self._freshclam_status_icon.set_from_icon_name(
                resolve_icon_name("object-select-symbolic")
            )
            self._freshclam_status_icon.add_css_class("success")
            self._freshclam_status_label.set_text(
                _("freshclam: {version}").format(version=version_or_error)
            )

            # Enable update buttons
            self._update_button.set_sensitive(True)
            self._force_update_button.set_sensitive(True)
        else:
            self._freshclam_available = False
            self._freshclam_status_icon.set_from_icon_name(
                resolve_icon_name("dialog-warning-symbolic")
            )
            self._freshclam_status_icon.add_css_class("warning")
            self._freshclam_status_label.set_text(version_or_error or _("freshclam not found"))

            # Disable update buttons and show error banner
            self._update_button.set_sensitive(False)
            self._force_update_button.set_sensitive(False)
            self._status_banner.set_title(version_or_error or _("freshclam not installed"))
            self._status_banner.set_revealed(True)

        # Apply service status
        self._apply_service_status(service_status, service_pid)

        return False  # Remove from idle

    def _apply_service_status(self, service_status, pid):
        """
        Update service status UI elements.

        Args:
            service_status: FreshclamServiceStatus enum value
            pid: Process ID string or None
        """
        self._service_status = service_status

        # Remove any existing CSS classes
        for css_class in ["success", "warning", "error"]:
            self._service_status_icon.remove_css_class(css_class)

        if service_status == FreshclamServiceStatus.RUNNING:
            self._service_status_icon.set_from_icon_name(
                resolve_icon_name("media-playback-start-symbolic")
            )
            self._service_status_icon.add_css_class("success")
            pid_info = f" (PID {pid})" if pid else ""
            self._service_status_label.set_text(_("Service: Active") + pid_info)
        elif service_status == FreshclamServiceStatus.STOPPED:
            self._service_status_icon.set_from_icon_name(
                resolve_icon_name("media-playback-stop-symbolic")
            )
            self._service_status_icon.add_css_class("warning")
            self._service_status_label.set_text(_("Service: Stopped"))
        elif not self._freshclam_available:
            # Hide service status when freshclam not available
            self._service_status_label.set_text(_("Service: N/A"))
        else:  # NOT_FOUND or UNKNOWN
            self._service_status_icon.set_from_icon_name(resolve_icon_name("system-run-symbolic"))
            self._service_status_label.set_text(_("Service: Manual Mode"))

    def _check_service_status(self):
        """Check freshclam service status and update UI."""
        self._service_status, pid = self._updater.check_freshclam_service()
        self._apply_service_status(self._service_status, pid)

    def _on_status_banner_dismissed(self, banner):
        """
        Handle status banner dismiss button click.

        Hides the status banner when the user clicks the Dismiss button.

        Args:
            banner: The Adw.Banner that was dismissed
        """
        banner.set_revealed(False)

    def _on_update_clicked(self, button):
        """Handle update button click."""
        if not self._freshclam_available:
            return

        self._start_update(force=False)

    def _on_force_update_clicked(self, button):
        """Handle force update button click."""
        if not self._freshclam_available:
            return

        self._start_update(force=True)

    def _on_cancel_clicked(self, button):
        """Handle cancel button click.

        FreshclamUpdater.cancel() escalates SIGTERM -> SIGKILL and blocks on
        process.wait() for several seconds. Running it on the GTK main thread
        would freeze the UI, so it runs in a background thread. The updating
        state is reset by _on_update_complete once the worker thread observes
        the cancelled update (update_async always invokes the callback).
        """
        self._cancel_button.set_sensitive(False)
        threading.Thread(target=self._updater.cancel, daemon=True).start()

    def _start_update(self, force: bool = False):
        """
        Start the database update process.

        Args:
            force: If True, backup local databases, delete them, then download
                   fresh copies from mirrors.
        """
        self._set_updating_state(True)
        self._clear_results()

        # Update results text with appropriate message
        buffer = self._results_text.get_buffer()
        if force:
            buffer.set_text(
                _("Force updating virus database...")
                + "\n\n"
                + _(
                    "Backing up local databases, then deleting them to force fresh downloads from mirrors."
                )
                + "\n"
                + _("Previous databases will be restored if the update fails.")
                + "\n\n"
                + _("Please wait, this may take a few minutes.")
            )
        else:
            buffer.set_text(
                _("Updating virus database...")
                + "\n\n"
                + _("Please wait, this may take a few minutes.")
            )

        # Hide any previous status banner
        self._status_banner.set_revealed(False)

        # Start async update
        self._updater.update_async(callback=self._on_update_complete, force=force)

    def _set_updating_state(self, is_updating: bool):
        """
        Update UI to reflect updating state.

        Args:
            is_updating: Whether an update is in progress
        """
        self._is_updating = is_updating

        if is_updating:
            # Show updating state
            self._update_button.set_label(_("Updating..."))
            self._update_button.set_sensitive(False)
            self._force_update_button.set_sensitive(False)
            self._update_spinner.set_visible(True)
            self._update_spinner.start()
            # Re-enable in case a previous cancel left it insensitive
            self._cancel_button.set_sensitive(True)
            self._cancel_button.set_visible(True)
        else:
            # Restore normal state
            self._update_button.set_label(_("Update Database"))
            self._update_button.set_sensitive(self._freshclam_available)
            self._force_update_button.set_sensitive(self._freshclam_available)
            self._update_spinner.stop()
            self._update_spinner.set_visible(False)
            self._cancel_button.set_visible(False)

    def _on_update_complete(self, result: UpdateResult):
        """
        Handle update completion.

        Args:
            result: The update result from the updater
        """
        self._set_updating_state(False)
        self._display_results(result)

        # Send notification only on actual updates, not when already up-to-date
        root = self.get_root()
        if root:
            app = root.get_application()
            if app and hasattr(app, "notification_manager"):
                if result.status == UpdateStatus.SUCCESS and result.databases_updated > 0:
                    app.notification_manager.notify_update_complete(
                        success=True, databases_updated=result.databases_updated
                    )
                elif result.status == UpdateStatus.ERROR:
                    app.notification_manager.notify_update_complete(
                        success=False, databases_updated=0
                    )

        return False  # Don't repeat GLib.idle_add

    def _clear_results(self):
        """Clear the results display."""
        buffer = self._results_text.get_buffer()
        buffer.set_text("")
        self._status_banner.set_revealed(False)

    def _display_results(self, result: UpdateResult):
        """
        Display update results in the UI.

        Args:
            result: The update result to display
        """
        # Check if this was a service-triggered update
        is_service_update = result.update_method == UpdateMethod.SERVICE_SIGNAL
        has_rate_limits = bool(result.rate_limited_databases)
        has_partial_progress = bool(result.updated_databases or result.up_to_date_databases)

        # Update status banner based on result
        if result.status == UpdateStatus.SUCCESS:
            if is_service_update:
                self._status_banner.set_title(_("Update signal sent to freshclam service"))
            else:
                self._status_banner.set_title(
                    ngettext(
                        "Database updated successfully ({count} database updated)",
                        "Database updated successfully ({count} databases updated)",
                        result.databases_updated,
                    ).format(count=result.databases_updated)
                )
            set_status_class(self._status_banner, StatusLevel.SUCCESS)
        elif result.status == UpdateStatus.UP_TO_DATE:
            self._status_banner.set_title(_("Database is already up to date"))
            set_status_class(self._status_banner, StatusLevel.INFO)
        elif result.status == UpdateStatus.CANCELLED:
            self._status_banner.set_title(_("Update cancelled"))
            set_status_class(self._status_banner, StatusLevel.WARNING)
        else:  # ERROR
            self._status_banner.set_title(result.error_message or _("Update error occurred"))
            if has_rate_limits:
                set_status_class(self._status_banner, StatusLevel.WARNING)
            else:
                set_status_class(self._status_banner, StatusLevel.ERROR)

        self._status_banner.set_revealed(True)

        # Build results text
        lines = []

        # Header with update status
        if result.status == UpdateStatus.SUCCESS:
            if is_service_update:
                lines.append(_("UPDATE SIGNAL SENT TO FRESHCLAM SERVICE"))
            else:
                lines.append(_("UPDATE COMPLETE - DATABASE UPDATED"))
        elif result.status == UpdateStatus.UP_TO_DATE:
            lines.append(_("UPDATE COMPLETE - ALREADY UP TO DATE"))
        elif result.status == UpdateStatus.CANCELLED:
            lines.append(_("UPDATE CANCELLED"))
        elif has_rate_limits and has_partial_progress:
            lines.append(_("UPDATE PARTIALLY COMPLETE"))
        elif has_rate_limits:
            lines.append(_("UPDATE RATE LIMITED"))
        else:
            lines.append(_("UPDATE ERROR"))

        lines.append("=" * 50)
        lines.append("")

        # Summary
        lines.append(_("Summary:"))
        lines.append(_("  Status: {status}").format(status=result.status.value))
        lines.append(_("  Method: {method}").format(method=result.update_method.value))
        if result.databases_updated > 0:
            lines.append(_("  Databases updated: {count}").format(count=result.databases_updated))
        if result.updated_databases:
            lines.append(
                _("  Updated databases: {databases}").format(
                    databases=", ".join(result.updated_databases)
                )
            )
        if result.up_to_date_databases:
            lines.append(
                _("  Already current: {databases}").format(
                    databases=", ".join(result.up_to_date_databases)
                )
            )
        if result.rate_limited_databases:
            rate_limited_details = []
            for database, cooldown_until in result.rate_limited_databases.items():
                if cooldown_until:
                    rate_limited_details.append(
                        _("{database} until {cooldown}").format(
                            database=database,
                            cooldown=cooldown_until,
                        )
                    )
                else:
                    rate_limited_details.append(database)
            lines.append(
                _("  Rate limited: {databases}").format(databases=", ".join(rate_limited_details))
            )
        lines.append("")

        # Service-specific message
        if is_service_update and result.status == UpdateStatus.SUCCESS:
            lines.append(_("Note: The freshclam service is handling the update in the background."))
            lines.append(_("Check service logs for detailed progress:"))
            lines.append("  journalctl -u clamav-freshclam.service -f")
            lines.append("")

        # Error message if present
        if result.error_message:
            lines.append(_("Error: {message}").format(message=result.error_message))
            lines.append("")

        # Raw output section
        if result.stdout:
            lines.append("-" * 50)
            lines.append(_("freshclam Output:"))
            lines.append("-" * 50)
            lines.append(result.stdout)

        if result.stderr and result.status == UpdateStatus.ERROR:
            lines.append("-" * 50)
            lines.append(_("Error Output:"))
            lines.append("-" * 50)
            lines.append(result.stderr)

        # Update the text view
        buffer = self._results_text.get_buffer()
        buffer.set_text("\n".join(lines))

    @property
    def updater(self) -> FreshclamUpdater:
        """
        Get the updater instance.

        Returns:
            The FreshclamUpdater instance used by this view
        """
        return self._updater
