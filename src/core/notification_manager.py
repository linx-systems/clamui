# ClamUI Notification Manager Module
"""
Notification manager module for ClamUI providing GNOME desktop notifications.
Uses Gio.Notification API for native GNOME integration.
"""

import logging

from gi.repository import Gio

from .i18n import _, ngettext
from .settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Manager for GNOME desktop notifications.

    Provides methods for sending notifications when scans complete,
    threats are detected, or virus definitions are updated.
    Notifications can be disabled via user settings.
    """

    # Notification IDs for deduplication
    NOTIFICATION_ID_SCAN = "scan-complete"
    NOTIFICATION_ID_UPDATE = "update-complete"
    NOTIFICATION_ID_SCHEDULED_SCAN = "scheduled-scan-complete"
    NOTIFICATION_ID_VT_SCAN = "virustotal-scan-complete"
    NOTIFICATION_ID_VT_RATE_LIMIT = "virustotal-rate-limit"
    NOTIFICATION_ID_VT_NO_KEY = "virustotal-no-key"
    NOTIFICATION_ID_DEVICE_SCAN_STARTED = "device-scan-started"
    NOTIFICATION_ID_DEVICE_SCAN_COMPLETE = "device-scan-complete"
    NOTIFICATION_ID_AUDIT = "audit-complete"

    def __init__(self, settings_manager: SettingsManager | None = None):
        """
        Initialize the NotificationManager.

        Args:
            settings_manager: Optional SettingsManager instance for checking
                              notification preferences. If not provided, a
                              default instance is created.
        """
        self._app: Gio.Application | None = None
        self._settings = settings_manager if settings_manager else SettingsManager()

    def set_application(self, app: Gio.Application) -> None:
        """
        Set the application reference for sending notifications.

        This must be called after the application is initialized,
        typically in do_startup().

        Args:
            app: The Gio.Application instance
        """
        self._app = app

    def notify_scan_complete(
        self, is_clean: bool, infected_count: int = 0, scanned_count: int = 0
    ) -> bool:
        """
        Send notification for scan completion.

        Args:
            is_clean: True if no threats were found
            infected_count: Number of infected files found
            scanned_count: Number of files scanned

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        if is_clean:
            title = _("Scan Complete")
            if scanned_count > 0:
                body = ngettext(
                    "No threats found ({count} file scanned)",
                    "No threats found ({count} files scanned)",
                    scanned_count,
                ).format(count=scanned_count)
            else:
                body = _("No threats found")
            priority = Gio.NotificationPriority.NORMAL
        else:
            title = _("Threats Detected!")
            body = ngettext(
                "{count} infected file found",
                "{count} infected files found",
                infected_count,
            ).format(count=infected_count)
            priority = Gio.NotificationPriority.URGENT

        return self._send(
            notification_id=self.NOTIFICATION_ID_SCAN,
            title=title,
            body=body,
            priority=priority,
            default_action="app.show-scan",
        )

    def notify_update_complete(self, success: bool, databases_updated: int = 0) -> bool:
        """
        Send notification for database update completion.

        Args:
            success: True if update completed successfully
            databases_updated: Number of databases updated

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        if success:
            title = _("Database Updated")
            if databases_updated > 0:
                body = ngettext(
                    "{count} database updated successfully",
                    "{count} databases updated successfully",
                    databases_updated,
                ).format(count=databases_updated)
            else:
                body = _("Virus definitions are up to date")
        else:
            title = _("Database Update Failed")
            body = _("Check the update view for details")

        return self._send(
            notification_id=self.NOTIFICATION_ID_UPDATE,
            title=title,
            body=body,
            priority=Gio.NotificationPriority.NORMAL,
            default_action="app.show-update",
        )

    def notify_scheduled_scan_complete(
        self,
        is_clean: bool,
        infected_count: int = 0,
        scanned_count: int = 0,
        quarantined_count: int = 0,
        target_path: str | None = None,
    ) -> bool:
        """
        Send notification for scheduled scan completion.

        Args:
            is_clean: True if no threats were found
            infected_count: Number of infected files found
            scanned_count: Number of files scanned
            quarantined_count: Number of files quarantined
            target_path: Optional path that was scanned

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        if is_clean:
            title = _("Scheduled Scan Complete")
            if scanned_count > 0:
                body = ngettext(
                    "No threats found ({count} file scanned)",
                    "No threats found ({count} files scanned)",
                    scanned_count,
                ).format(count=scanned_count)
            else:
                body = _("No threats found")
            priority = Gio.NotificationPriority.NORMAL
        else:
            title = _("Scheduled Scan: Threats Detected!")
            if quarantined_count > 0:
                body = _("{infected} infected file(s) found, {quarantined} quarantined").format(
                    infected=infected_count, quarantined=quarantined_count
                )
            else:
                body = ngettext(
                    "{count} infected file found",
                    "{count} infected files found",
                    infected_count,
                ).format(count=infected_count)
            priority = Gio.NotificationPriority.URGENT

        return self._send(
            notification_id=self.NOTIFICATION_ID_SCHEDULED_SCAN,
            title=title,
            body=body,
            priority=priority,
            default_action="app.show-scan",
        )

    def notify_virustotal_scan_complete(
        self,
        is_clean: bool,
        detections: int = 0,
        total_engines: int = 0,
        file_name: str | None = None,
        permalink: str | None = None,
    ) -> bool:
        """
        Send notification for VirusTotal scan completion.

        Args:
            is_clean: True if no threats were detected
            detections: Number of engines that detected threats
            total_engines: Total number of engines that scanned the file
            file_name: Optional name of the scanned file
            permalink: Optional VirusTotal permalink

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        if is_clean:
            title = _("VirusTotal: No Threats")
            if file_name:
                # Translators: use your language's quotation marks around {file_name}.
                body = _("'{file_name}' appears safe (0/{total} detections)").format(
                    file_name=file_name, total=total_engines
                )
            else:
                body = _("File appears safe (0/{total} detections)").format(total=total_engines)
            priority = Gio.NotificationPriority.NORMAL
        else:
            title = _("VirusTotal: Threats Detected!")
            if file_name:
                # Translators: use your language's quotation marks around {file_name}.
                body = _("'{file_name}' flagged by {detections}/{total} engines").format(
                    file_name=file_name, detections=detections, total=total_engines
                )
            else:
                body = _("File flagged by {detections}/{total} engines").format(
                    detections=detections, total=total_engines
                )
            priority = Gio.NotificationPriority.URGENT

        return self._send(
            notification_id=self.NOTIFICATION_ID_VT_SCAN,
            title=title,
            body=body,
            priority=priority,
            default_action="app.show-logs",
        )

    def notify_virustotal_rate_limit(self) -> bool:
        """
        Send notification when VirusTotal rate limit is exceeded.

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        return self._send(
            notification_id=self.NOTIFICATION_ID_VT_RATE_LIMIT,
            title=_("VirusTotal Rate Limit"),
            body=_("Too many requests. Try again in a minute or use the website."),
            priority=Gio.NotificationPriority.NORMAL,
            default_action="app.show-preferences",
        )

    def notify_virustotal_no_key(self) -> bool:
        """
        Send notification when VirusTotal API key is not configured.

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        return self._send(
            notification_id=self.NOTIFICATION_ID_VT_NO_KEY,
            title=_("VirusTotal Not Configured"),
            body=_("Add your API key in Preferences to scan with VirusTotal."),
            priority=Gio.NotificationPriority.NORMAL,
            default_action="app.show-preferences",
        )

    def notify_device_scan_started(self, device_name: str, mount_point: str) -> bool:
        """
        Send notification when a device scan starts.

        Args:
            device_name: Human-readable device name
            mount_point: Filesystem path where device is mounted

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        if not self._settings.get("device_auto_scan_notify", True):
            return False

        return self._send(
            notification_id=self.NOTIFICATION_ID_DEVICE_SCAN_STARTED,
            title=_("Scanning Device"),
            body=_("Scanning {device} ({path})").format(device=device_name, path=mount_point),
            priority=Gio.NotificationPriority.NORMAL,
            default_action="app.show-scan",
        )

    def notify_device_scan_complete(
        self,
        device_name: str,
        is_clean: bool,
        infected_count: int = 0,
        scanned_count: int = 0,
        quarantined_count: int = 0,
    ) -> bool:
        """
        Send notification when a device scan completes.

        Args:
            device_name: Human-readable device name
            is_clean: True if no threats were found
            infected_count: Number of infected files found
            scanned_count: Number of files scanned
            quarantined_count: Number of files auto-quarantined

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        if not self._settings.get("device_auto_scan_notify", True):
            return False

        if is_clean:
            title = _("Device Scan Complete")
            if scanned_count > 0:
                body = ngettext(
                    "{device}: No threats ({count} file scanned)",
                    "{device}: No threats ({count} files scanned)",
                    scanned_count,
                ).format(device=device_name, count=scanned_count)
            else:
                body = _("{device}: No threats found").format(device=device_name)
            priority = Gio.NotificationPriority.NORMAL
        else:
            title = _("Device Scan: Threats Detected!")
            if quarantined_count > 0:
                body = _("{device}: {infected} threat(s) found, {quarantined} quarantined").format(
                    device=device_name,
                    infected=infected_count,
                    quarantined=quarantined_count,
                )
            else:
                body = ngettext(
                    "{device}: {count} infected file found",
                    "{device}: {count} infected files found",
                    infected_count,
                ).format(device=device_name, count=infected_count)
            priority = Gio.NotificationPriority.URGENT

        return self._send(
            notification_id=self.NOTIFICATION_ID_DEVICE_SCAN_COMPLETE,
            title=title,
            body=body,
            priority=priority,
            default_action="app.show-scan",
        )

    def notify_audit_complete(self, warnings: int = 0, issues: int = 0) -> bool:
        """
        Send notification when security audit finds issues.

        Args:
            warnings: Number of checks with WARNING status
            issues: Number of checks with FAIL status

        Returns:
            True if notification was sent, False otherwise
        """
        if not self._can_notify():
            return False

        if warnings == 0 and issues == 0:
            return False

        title = _("Security Audit Complete")

        parts = []
        if issues:
            parts.append(ngettext("{count} issue", "{count} issues", issues).format(count=issues))
        if warnings:
            parts.append(
                ngettext("{count} warning", "{count} warnings", warnings).format(count=warnings)
            )
        body = _("Found {details}").format(details=", ".join(parts))

        return self._send(
            notification_id=self.NOTIFICATION_ID_AUDIT,
            title=title,
            body=body,
            priority=Gio.NotificationPriority.NORMAL,
            default_action="app.show-audit",
        )

    def _can_notify(self) -> bool:
        """
        Check if notifications are enabled and possible.

        Returns:
            True if notifications can be sent, False otherwise
        """
        if self._app is None:
            return False

        return self._settings.get("notifications_enabled", True)

    def _send(
        self,
        notification_id: str,
        title: str,
        body: str,
        priority: Gio.NotificationPriority,
        default_action: str,
    ) -> bool:
        """
        Send a notification.

        Args:
            notification_id: Unique ID for this notification (for deduplication)
            title: Notification title
            body: Notification body text
            priority: Notification priority (NORMAL or URGENT)
            default_action: Action to trigger when notification is clicked

        Returns:
            True if notification was sent successfully, False otherwise
        """
        if self._app is None:
            logger.debug("Cannot send notification '%s': no app reference", notification_id)
            return False

        try:
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            notification.set_priority(priority)
            notification.set_default_action(default_action)

            # Send the notification
            self._app.send_notification(notification_id, notification)
            return True
        except Exception as e:
            # Log failure if notifications unavailable
            # This handles cases where D-Bus notification service isn't running
            logger.debug("Failed to send notification '%s': %s", notification_id, e)
            return False

    def withdraw_notification(self, notification_id: str) -> bool:
        """
        Withdraw a previously sent notification.

        Args:
            notification_id: The ID of the notification to withdraw

        Returns:
            True if withdrawal was attempted, False if no app reference
        """
        if self._app is None:
            return False

        try:
            self._app.withdraw_notification(notification_id)
            return True
        except Exception as e:
            logger.debug("Failed to withdraw notification '%s': %s", notification_id, e)
            return False

    @property
    def notifications_enabled(self) -> bool:
        """
        Check if notifications are enabled in settings.

        Returns:
            True if notifications are enabled, False otherwise
        """
        return self._settings.get("notifications_enabled", True)

    @property
    def has_application(self) -> bool:
        """
        Check if application reference has been set.

        Returns:
            True if application is set, False otherwise
        """
        return self._app is not None
