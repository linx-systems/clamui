# ClamUI NotificationManager Tests
"""Unit tests for the NotificationManager class."""

import tempfile
from unittest import mock

import pytest

from src.core.notification_manager import NotificationManager
from src.core.settings_manager import SettingsManager


class TestNotificationManagerInit:
    """Tests for NotificationManager initialization."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_init_without_settings_manager(self):
        """Test NotificationManager initializes with default SettingsManager."""
        manager = NotificationManager()
        assert manager._settings is not None
        assert isinstance(manager._settings, SettingsManager)

    def test_init_with_custom_settings_manager(self, temp_config_dir):
        """Test NotificationManager uses provided SettingsManager."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)
        assert manager._settings is settings

    def test_init_sets_app_to_none(self):
        """Test NotificationManager initializes with no application reference."""
        manager = NotificationManager()
        assert manager._app is None
        assert manager.has_application is False

    def test_notification_ids_are_defined(self):
        """Test that notification ID constants are defined."""
        assert NotificationManager.NOTIFICATION_ID_SCAN == "scan-complete"
        assert NotificationManager.NOTIFICATION_ID_UPDATE == "update-complete"


class TestNotificationManagerSetApplication:
    """Tests for NotificationManager.set_application method."""

    def test_set_application_stores_reference(self):
        """Test that set_application stores the app reference."""
        manager = NotificationManager()
        mock_app = mock.Mock()

        manager.set_application(mock_app)

        assert manager._app is mock_app
        assert manager.has_application is True

    def test_set_application_can_be_updated(self):
        """Test that application reference can be updated."""
        manager = NotificationManager()
        mock_app1 = mock.Mock()
        mock_app2 = mock.Mock()

        manager.set_application(mock_app1)
        assert manager._app is mock_app1

        manager.set_application(mock_app2)
        assert manager._app is mock_app2


class TestNotificationManagerCanNotify:
    """Tests for NotificationManager._can_notify logic."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_can_notify_returns_false_without_app(self, temp_config_dir):
        """Test that notifications are blocked without app reference."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)
        # No app set
        assert manager._can_notify() is False

    def test_can_notify_returns_false_when_disabled(self, temp_config_dir):
        """Test that notifications are blocked when disabled in settings."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", False)

        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        assert manager._can_notify() is False

    def test_can_notify_returns_true_when_enabled(self, temp_config_dir):
        """Test that notifications are allowed when enabled and app set."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)

        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        assert manager._can_notify() is True

    def test_can_notify_uses_default_enabled(self, temp_config_dir):
        """Test that notifications default to enabled."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        # Default should be True
        assert manager._can_notify() is True


class TestNotificationManagerNotifyScanComplete:
    """Tests for NotificationManager.notify_scan_complete method."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def notification_manager(self, temp_config_dir):
        """Create a NotificationManager with mock app and enabled notifications."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        return manager

    def test_notify_scan_complete_clean_returns_true(self, notification_manager):
        """Test notify_scan_complete returns True when notification sent."""
        with mock.patch("src.core.notification_manager.Gio"):
            result = notification_manager.notify_scan_complete(is_clean=True, scanned_count=100)
            assert result is True

    def test_notify_scan_complete_clean_creates_notification(self, notification_manager):
        """Test notify_scan_complete creates notification for clean scan."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scan_complete(is_clean=True, scanned_count=100)

            mock_gio.Notification.new.assert_called_once_with("Scan Complete")
            mock_notification.set_body.assert_called_once()
            body_arg = mock_notification.set_body.call_args[0][0]
            assert "No threats found" in body_arg
            assert "100" in body_arg

    def test_notify_scan_complete_clean_without_count(self, notification_manager):
        """Test notify_scan_complete with clean scan and no file count."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scan_complete(is_clean=True)

            mock_notification.set_body.assert_called_once_with("No threats found")

    def test_notify_scan_complete_infected_creates_urgent_notification(self, notification_manager):
        """Test notify_scan_complete creates urgent notification for threats."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scan_complete(is_clean=False, infected_count=3)

            mock_gio.Notification.new.assert_called_once_with("Threats Detected!")
            mock_notification.set_body.assert_called_once()
            body_arg = mock_notification.set_body.call_args[0][0]
            assert "3" in body_arg
            assert "infected" in body_arg

            # Verify URGENT priority
            mock_notification.set_priority.assert_called_once()
            priority_arg = mock_notification.set_priority.call_args[0][0]
            assert priority_arg == mock_gio.NotificationPriority.URGENT

    def test_notify_scan_complete_clean_uses_normal_priority(self, notification_manager):
        """Test clean scan notification uses NORMAL priority."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scan_complete(is_clean=True)

            mock_notification.set_priority.assert_called_once()
            priority_arg = mock_notification.set_priority.call_args[0][0]
            assert priority_arg == mock_gio.NotificationPriority.NORMAL

    def test_notify_scan_complete_sets_default_action(self, notification_manager):
        """Test scan notification sets click action to show scan view."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scan_complete(is_clean=True)

            mock_notification.set_default_action.assert_called_once_with("app.show-scan")

    def test_notify_scan_complete_sends_via_app(self, notification_manager):
        """Test scan notification is sent via the application."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scan_complete(is_clean=True)

            notification_manager._app.send_notification.assert_called_once_with(
                "scan-complete", mock_notification
            )

    def test_notify_scan_complete_returns_false_when_disabled(self, temp_config_dir):
        """Test notify_scan_complete returns False when notifications disabled."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", False)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        result = manager.notify_scan_complete(is_clean=True)
        assert result is False
        mock_app.send_notification.assert_not_called()

    def test_notify_scan_complete_returns_false_without_app(self, temp_config_dir):
        """Test notify_scan_complete returns False without app reference."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)

        result = manager.notify_scan_complete(is_clean=True)
        assert result is False


class TestNotificationManagerNotifyUpdateComplete:
    """Tests for NotificationManager.notify_update_complete method."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def notification_manager(self, temp_config_dir):
        """Create a NotificationManager with mock app and enabled notifications."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        return manager

    def test_notify_update_complete_success_returns_true(self, notification_manager):
        """Test notify_update_complete returns True when notification sent."""
        with mock.patch("src.core.notification_manager.Gio"):
            result = notification_manager.notify_update_complete(success=True, databases_updated=3)
            assert result is True

    def test_notify_update_complete_success_creates_notification(self, notification_manager):
        """Test notify_update_complete creates notification for successful update."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_update_complete(success=True, databases_updated=3)

            mock_gio.Notification.new.assert_called_once_with("Database Updated")
            mock_notification.set_body.assert_called_once()
            body_arg = mock_notification.set_body.call_args[0][0]
            assert "3" in body_arg
            assert "updated successfully" in body_arg

    def test_notify_update_complete_success_no_count(self, notification_manager):
        """Test notify_update_complete with success but no database count."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_update_complete(success=True)

            mock_notification.set_body.assert_called_once_with("Virus definitions are up to date")

    def test_notify_update_complete_failure_creates_notification(self, notification_manager):
        """Test notify_update_complete creates notification for failed update."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_update_complete(success=False)

            mock_gio.Notification.new.assert_called_once_with("Database Update Failed")
            mock_notification.set_body.assert_called_once()
            body_arg = mock_notification.set_body.call_args[0][0]
            assert "Check the update view" in body_arg

    def test_notify_update_complete_uses_normal_priority(self, notification_manager):
        """Test update notification uses NORMAL priority."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_update_complete(success=True)

            mock_notification.set_priority.assert_called_once()
            priority_arg = mock_notification.set_priority.call_args[0][0]
            assert priority_arg == mock_gio.NotificationPriority.NORMAL

    def test_notify_update_complete_sets_default_action(self, notification_manager):
        """Test update notification sets click action to show update view."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_update_complete(success=True)

            mock_notification.set_default_action.assert_called_once_with("app.show-update")

    def test_notify_update_complete_sends_via_app(self, notification_manager):
        """Test update notification is sent via the application."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_update_complete(success=True)

            notification_manager._app.send_notification.assert_called_once_with(
                "update-complete", mock_notification
            )

    def test_notify_update_complete_returns_false_when_disabled(self, temp_config_dir):
        """Test notify_update_complete returns False when notifications disabled."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", False)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        result = manager.notify_update_complete(success=True)
        assert result is False
        mock_app.send_notification.assert_not_called()


class TestNotificationManagerWithdrawNotification:
    """Tests for NotificationManager.withdraw_notification method."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_withdraw_notification_returns_false_without_app(self, temp_config_dir):
        """Test withdraw_notification returns False without app reference."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)

        result = manager.withdraw_notification("scan-complete")
        assert result is False

    def test_withdraw_notification_calls_app_method(self, temp_config_dir):
        """Test withdraw_notification calls app.withdraw_notification."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        result = manager.withdraw_notification("scan-complete")

        assert result is True
        mock_app.withdraw_notification.assert_called_once_with("scan-complete")

    def test_withdraw_notification_handles_exception(self, temp_config_dir):
        """Test withdraw_notification returns False on exception."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        mock_app.withdraw_notification.side_effect = Exception("Test error")
        manager.set_application(mock_app)

        result = manager.withdraw_notification("scan-complete")
        assert result is False


class TestNotificationManagerProperties:
    """Tests for NotificationManager properties."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_has_application_false_initially(self):
        """Test has_application returns False when no app is set."""
        manager = NotificationManager()
        assert manager.has_application is False

    def test_has_application_true_after_set(self):
        """Test has_application returns True after app is set."""
        manager = NotificationManager()
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        assert manager.has_application is True

    def test_notifications_enabled_default(self, temp_config_dir):
        """Test notifications_enabled returns True by default."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)
        assert manager.notifications_enabled is True

    def test_notifications_enabled_reflects_settings(self, temp_config_dir):
        """Test notifications_enabled reflects settings value."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", False)
        manager = NotificationManager(settings_manager=settings)
        assert manager.notifications_enabled is False


class TestNotificationManagerErrorHandling:
    """Tests for NotificationManager error handling."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def notification_manager(self, temp_config_dir):
        """Create a NotificationManager with mock app and enabled notifications."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        return manager

    def test_send_notification_handles_gio_exception(self, notification_manager):
        """Test that _send handles Gio.Notification exceptions gracefully."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_gio.Notification.new.side_effect = Exception("D-Bus unavailable")

            result = notification_manager.notify_scan_complete(is_clean=True)

            # Should return False but not crash
            assert result is False

    def test_send_notification_handles_app_send_exception(self, notification_manager):
        """Test that _send handles app.send_notification exceptions gracefully."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification
            notification_manager._app.send_notification.side_effect = Exception("Send failed")

            result = notification_manager.notify_scan_complete(is_clean=True)

            # Should return False but not crash
            assert result is False


class TestNotificationManagerNotificationIds:
    """Tests for notification ID usage and deduplication."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def notification_manager(self, temp_config_dir):
        """Create a NotificationManager with mock app and enabled notifications."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        return manager

    def test_scan_notifications_use_consistent_id(self, notification_manager):
        """Test that scan notifications use the same ID for deduplication."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            # Send multiple scan notifications
            notification_manager.notify_scan_complete(is_clean=True)
            notification_manager.notify_scan_complete(is_clean=False, infected_count=1)

            # Both should use the same notification ID
            calls = notification_manager._app.send_notification.call_args_list
            assert len(calls) == 2
            assert calls[0][0][0] == "scan-complete"
            assert calls[1][0][0] == "scan-complete"

    def test_update_notifications_use_consistent_id(self, notification_manager):
        """Test that update notifications use the same ID for deduplication."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            # Send multiple update notifications
            notification_manager.notify_update_complete(success=True)
            notification_manager.notify_update_complete(success=False)

            # Both should use the same notification ID
            calls = notification_manager._app.send_notification.call_args_list
            assert len(calls) == 2
            assert calls[0][0][0] == "update-complete"
            assert calls[1][0][0] == "update-complete"

    def test_scan_and_update_use_different_ids(self, notification_manager):
        """Test that scan and update notifications use different IDs."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scan_complete(is_clean=True)
            notification_manager.notify_update_complete(success=True)

            calls = notification_manager._app.send_notification.call_args_list
            assert len(calls) == 2
            assert calls[0][0][0] != calls[1][0][0]


class TestScheduledScanNotifications:
    """Tests for NotificationManager.notify_scheduled_scan_complete method."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def notification_manager(self, temp_config_dir):
        """Create a NotificationManager with mock app and enabled notifications."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        return manager

    def test_scheduled_scan_clean_returns_true(self, notification_manager):
        """Test clean scheduled scan notification returns True."""
        with mock.patch("src.core.notification_manager.Gio"):
            result = notification_manager.notify_scheduled_scan_complete(
                is_clean=True, scanned_count=200
            )
            assert result is True

    def test_scheduled_scan_clean_with_count(self, notification_manager):
        """Test clean scheduled scan shows file count in body."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(is_clean=True, scanned_count=500)

            mock_gio.Notification.new.assert_called_once_with("Scheduled Scan Complete")
            body = mock_notification.set_body.call_args[0][0]
            assert "No threats found" in body
            assert "500" in body

    def test_scheduled_scan_clean_no_count(self, notification_manager):
        """Test clean scheduled scan without file count."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(is_clean=True)

            body = mock_notification.set_body.call_args[0][0]
            assert "No threats found" in body

    def test_scheduled_scan_clean_normal_priority(self, notification_manager):
        """Test clean scheduled scan uses NORMAL priority."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(is_clean=True)

            priority = mock_notification.set_priority.call_args[0][0]
            assert priority == mock_gio.NotificationPriority.NORMAL

    def test_scheduled_scan_infected_title(self, notification_manager):
        """Test infected scheduled scan shows threat title."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(is_clean=False, infected_count=3)

            mock_gio.Notification.new.assert_called_once_with("Scheduled Scan: Threats Detected!")

    def test_scheduled_scan_infected_body(self, notification_manager):
        """Test infected scheduled scan shows infection count in body."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(is_clean=False, infected_count=3)

            body = mock_notification.set_body.call_args[0][0]
            assert "3" in body
            assert "infected" in body

    def test_scheduled_scan_infected_with_quarantine(self, notification_manager):
        """Test infected scan with quarantine count shows both counts."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(
                is_clean=False, infected_count=5, quarantined_count=3
            )

            body = mock_notification.set_body.call_args[0][0]
            assert "5" in body
            assert "3" in body
            assert "quarantined" in body

    def test_scheduled_scan_infected_urgent_priority(self, notification_manager):
        """Test infected scheduled scan uses URGENT priority."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(is_clean=False, infected_count=1)

            priority = mock_notification.set_priority.call_args[0][0]
            assert priority == mock_gio.NotificationPriority.URGENT

    def test_scheduled_scan_uses_correct_notification_id(self, notification_manager):
        """Test scheduled scan uses 'scheduled-scan-complete' ID."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(is_clean=True)

            notification_manager._app.send_notification.assert_called_once_with(
                "scheduled-scan-complete", mock_notification
            )

    def test_scheduled_scan_sets_default_action(self, notification_manager):
        """Test scheduled scan sets click action to show scan view."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_scheduled_scan_complete(is_clean=True)

            mock_notification.set_default_action.assert_called_once_with("app.show-scan")

    def test_scheduled_scan_returns_false_when_disabled(self, temp_config_dir):
        """Test scheduled scan returns False when notifications disabled."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", False)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        result = manager.notify_scheduled_scan_complete(is_clean=True)
        assert result is False
        mock_app.send_notification.assert_not_called()


class TestVirusTotalNotifications:
    """Tests for VirusTotal notification methods."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def notification_manager(self, temp_config_dir):
        """Create a NotificationManager with mock app and enabled notifications."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        return manager

    # --- notify_virustotal_scan_complete ---

    def test_vt_scan_clean_returns_true(self, notification_manager):
        """Test clean VT scan notification returns True."""
        with mock.patch("src.core.notification_manager.Gio"):
            result = notification_manager.notify_virustotal_scan_complete(
                is_clean=True, total_engines=70
            )
            assert result is True

    def test_vt_scan_clean_title(self, notification_manager):
        """Test clean VT scan uses 'No Threats' title."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(is_clean=True, total_engines=70)

            mock_gio.Notification.new.assert_called_once_with("VirusTotal: No Threats")

    def test_vt_scan_clean_with_filename(self, notification_manager):
        """Test clean VT scan includes filename in body."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(
                is_clean=True, total_engines=70, file_name="test.exe"
            )

            body = mock_notification.set_body.call_args[0][0]
            assert "test.exe" in body
            assert "0/70" in body

    def test_vt_scan_clean_without_filename(self, notification_manager):
        """Test clean VT scan uses generic message without filename."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(is_clean=True, total_engines=70)

            body = mock_notification.set_body.call_args[0][0]
            assert "safe" in body.lower() or "File" in body
            assert "0/70" in body

    def test_vt_scan_clean_normal_priority(self, notification_manager):
        """Test clean VT scan uses NORMAL priority."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(is_clean=True, total_engines=70)

            priority = mock_notification.set_priority.call_args[0][0]
            assert priority == mock_gio.NotificationPriority.NORMAL

    def test_vt_scan_infected_title(self, notification_manager):
        """Test infected VT scan uses 'Threats Detected' title."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(
                is_clean=False, detections=15, total_engines=70
            )

            mock_gio.Notification.new.assert_called_once_with("VirusTotal: Threats Detected!")

    def test_vt_scan_infected_with_filename(self, notification_manager):
        """Test infected VT scan includes filename and detection ratio."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(
                is_clean=False,
                detections=15,
                total_engines=70,
                file_name="malware.exe",
            )

            body = mock_notification.set_body.call_args[0][0]
            assert "malware.exe" in body
            assert "15" in body
            assert "70" in body

    def test_vt_scan_infected_without_filename(self, notification_manager):
        """Test infected VT scan uses generic message without filename."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(
                is_clean=False, detections=10, total_engines=70
            )

            body = mock_notification.set_body.call_args[0][0]
            assert "10" in body
            assert "70" in body

    def test_vt_scan_infected_urgent_priority(self, notification_manager):
        """Test infected VT scan uses URGENT priority."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(
                is_clean=False, detections=10, total_engines=70
            )

            priority = mock_notification.set_priority.call_args[0][0]
            assert priority == mock_gio.NotificationPriority.URGENT

    def test_vt_scan_uses_correct_notification_id(self, notification_manager):
        """Test VT scan uses 'virustotal-scan-complete' ID."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(is_clean=True, total_engines=70)

            notification_manager._app.send_notification.assert_called_once_with(
                "virustotal-scan-complete", mock_notification
            )

    def test_vt_scan_sets_default_action(self, notification_manager):
        """Test VT scan sets click action to show logs view."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_scan_complete(is_clean=True, total_engines=70)

            mock_notification.set_default_action.assert_called_once_with("app.show-logs")

    # --- notify_virustotal_rate_limit ---

    def test_vt_rate_limit_returns_true(self, notification_manager):
        """Test rate limit notification returns True when sent."""
        with mock.patch("src.core.notification_manager.Gio"):
            result = notification_manager.notify_virustotal_rate_limit()
            assert result is True

    def test_vt_rate_limit_title(self, notification_manager):
        """Test rate limit notification uses correct title."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_rate_limit()

            mock_gio.Notification.new.assert_called_once_with("VirusTotal Rate Limit")

    def test_vt_rate_limit_body(self, notification_manager):
        """Test rate limit notification body mentions retry."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_rate_limit()

            body = mock_notification.set_body.call_args[0][0]
            assert "requests" in body.lower() or "minute" in body.lower()

    def test_vt_rate_limit_uses_correct_id(self, notification_manager):
        """Test rate limit uses 'virustotal-rate-limit' notification ID."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_rate_limit()

            notification_manager._app.send_notification.assert_called_once_with(
                "virustotal-rate-limit", mock_notification
            )

    def test_vt_rate_limit_sets_preferences_action(self, notification_manager):
        """Test rate limit sets click action to show preferences."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_rate_limit()

            mock_notification.set_default_action.assert_called_once_with("app.show-preferences")

    # --- notify_virustotal_no_key ---

    def test_vt_no_key_returns_true(self, notification_manager):
        """Test no key notification returns True when sent."""
        with mock.patch("src.core.notification_manager.Gio"):
            result = notification_manager.notify_virustotal_no_key()
            assert result is True

    def test_vt_no_key_title(self, notification_manager):
        """Test no key notification uses correct title."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_no_key()

            mock_gio.Notification.new.assert_called_once_with("VirusTotal Not Configured")

    def test_vt_no_key_body(self, notification_manager):
        """Test no key notification body mentions API key."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_no_key()

            body = mock_notification.set_body.call_args[0][0]
            assert "API key" in body or "Preferences" in body

    def test_vt_no_key_uses_correct_id(self, notification_manager):
        """Test no key uses 'virustotal-no-key' notification ID."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_no_key()

            notification_manager._app.send_notification.assert_called_once_with(
                "virustotal-no-key", mock_notification
            )

    def test_vt_no_key_sets_preferences_action(self, notification_manager):
        """Test no key sets click action to show preferences."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_virustotal_no_key()

            mock_notification.set_default_action.assert_called_once_with("app.show-preferences")

    def test_vt_rate_limit_returns_false_when_disabled(self, temp_config_dir):
        """Test rate limit returns False when notifications disabled."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", False)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        result = manager.notify_virustotal_rate_limit()
        assert result is False

    def test_vt_no_key_returns_false_when_disabled(self, temp_config_dir):
        """Test no key returns False when notifications disabled."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", False)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        result = manager.notify_virustotal_no_key()
        assert result is False


class TestDeviceScanNotifications:
    """Tests for device scan notification methods."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def notification_manager(self, temp_config_dir):
        """Create a NotificationManager with mock app and enabled notifications."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        return manager

    # --- notify_device_scan_started ---

    def test_device_started_returns_true(self, notification_manager):
        """Test device scan started notification returns True."""
        with mock.patch("src.core.notification_manager.Gio"):
            result = notification_manager.notify_device_scan_started(
                device_name="USB Drive", mount_point="/media/usb"
            )
            assert result is True

    def test_device_started_title(self, notification_manager):
        """Test device scan started uses 'Scanning Device' title."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_started(
                device_name="USB Drive", mount_point="/media/usb"
            )

            mock_gio.Notification.new.assert_called_once_with("Scanning Device")

    def test_device_started_body_includes_device_and_path(self, notification_manager):
        """Test device scan started body includes device name and mount point."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_started(
                device_name="USB Drive", mount_point="/media/usb"
            )

            body = mock_notification.set_body.call_args[0][0]
            assert "USB Drive" in body
            assert "/media/usb" in body

    def test_device_started_uses_correct_id(self, notification_manager):
        """Test device scan started uses correct notification ID."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_started(
                device_name="USB Drive", mount_point="/media/usb"
            )

            notification_manager._app.send_notification.assert_called_once_with(
                "device-scan-started", mock_notification
            )

    def test_device_started_respects_notify_setting(self, temp_config_dir):
        """Test device scan started respects device_auto_scan_notify setting."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        settings.set("device_auto_scan_notify", False)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        result = manager.notify_device_scan_started(
            device_name="USB Drive", mount_point="/media/usb"
        )

        assert result is False
        mock_app.send_notification.assert_not_called()

    def test_device_started_default_notify_true(self, temp_config_dir):
        """Test device scan notify defaults to True when setting absent."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        # Don't set device_auto_scan_notify - should default to True
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        with mock.patch("src.core.notification_manager.Gio"):
            result = manager.notify_device_scan_started(
                device_name="USB Drive", mount_point="/media/usb"
            )
            assert result is True

    # --- notify_device_scan_complete ---

    def test_device_complete_clean_returns_true(self, notification_manager):
        """Test clean device scan complete returns True."""
        with mock.patch("src.core.notification_manager.Gio"):
            result = notification_manager.notify_device_scan_complete(
                device_name="USB Drive", is_clean=True, scanned_count=50
            )
            assert result is True

    def test_device_complete_clean_title(self, notification_manager):
        """Test clean device scan uses 'Device Scan Complete' title."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(
                device_name="USB Drive", is_clean=True, scanned_count=50
            )

            mock_gio.Notification.new.assert_called_once_with("Device Scan Complete")

    def test_device_complete_clean_body_with_count(self, notification_manager):
        """Test clean device scan body includes device name and count."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(
                device_name="USB Drive", is_clean=True, scanned_count=50
            )

            body = mock_notification.set_body.call_args[0][0]
            assert "USB Drive" in body
            assert "50" in body
            assert "No threats" in body or "threats" not in body.lower()

    def test_device_complete_clean_body_no_count(self, notification_manager):
        """Test clean device scan body without count."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(device_name="USB Drive", is_clean=True)

            body = mock_notification.set_body.call_args[0][0]
            assert "USB Drive" in body

    def test_device_complete_clean_normal_priority(self, notification_manager):
        """Test clean device scan uses NORMAL priority."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(device_name="USB Drive", is_clean=True)

            priority = mock_notification.set_priority.call_args[0][0]
            assert priority == mock_gio.NotificationPriority.NORMAL

    def test_device_complete_infected_title(self, notification_manager):
        """Test infected device scan uses threat title."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(
                device_name="USB Drive", is_clean=False, infected_count=2
            )

            mock_gio.Notification.new.assert_called_once_with("Device Scan: Threats Detected!")

    def test_device_complete_infected_body(self, notification_manager):
        """Test infected device scan body shows device and count."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(
                device_name="USB Drive", is_clean=False, infected_count=2
            )

            body = mock_notification.set_body.call_args[0][0]
            assert "USB Drive" in body
            assert "2" in body
            assert "infected" in body

    def test_device_complete_infected_with_quarantine(self, notification_manager):
        """Test infected device scan with quarantine shows both counts."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(
                device_name="USB Drive",
                is_clean=False,
                infected_count=5,
                quarantined_count=3,
            )

            body = mock_notification.set_body.call_args[0][0]
            assert "USB Drive" in body
            assert "5" in body
            assert "3" in body
            assert "quarantined" in body

    def test_device_complete_infected_urgent_priority(self, notification_manager):
        """Test infected device scan uses URGENT priority."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(
                device_name="USB Drive", is_clean=False, infected_count=1
            )

            priority = mock_notification.set_priority.call_args[0][0]
            assert priority == mock_gio.NotificationPriority.URGENT

    def test_device_complete_uses_correct_id(self, notification_manager):
        """Test device scan complete uses correct notification ID."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(device_name="USB Drive", is_clean=True)

            notification_manager._app.send_notification.assert_called_once_with(
                "device-scan-complete", mock_notification
            )

    def test_device_complete_sets_scan_action(self, notification_manager):
        """Test device scan complete sets click action to show scan view."""
        with mock.patch("src.core.notification_manager.Gio") as mock_gio:
            mock_notification = mock.Mock()
            mock_gio.Notification.new.return_value = mock_notification

            notification_manager.notify_device_scan_complete(device_name="USB Drive", is_clean=True)

            mock_notification.set_default_action.assert_called_once_with("app.show-scan")

    def test_device_complete_respects_notify_setting(self, temp_config_dir):
        """Test device scan complete respects device_auto_scan_notify setting."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        settings.set("device_auto_scan_notify", False)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)

        result = manager.notify_device_scan_complete(device_name="USB Drive", is_clean=True)

        assert result is False
        mock_app.send_notification.assert_not_called()


class TestNotificationDisabled:
    """Tests that all notification methods return False when notifications are disabled."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def disabled_manager(self, temp_config_dir):
        """Create a NotificationManager with notifications disabled."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", False)
        manager = NotificationManager(settings_manager=settings)
        mock_app = mock.Mock()
        manager.set_application(mock_app)
        return manager

    def test_scan_complete_disabled(self, disabled_manager):
        """Test notify_scan_complete returns False when disabled."""
        result = disabled_manager.notify_scan_complete(is_clean=True)
        assert result is False
        disabled_manager._app.send_notification.assert_not_called()

    def test_update_complete_disabled(self, disabled_manager):
        """Test notify_update_complete returns False when disabled."""
        result = disabled_manager.notify_update_complete(success=True)
        assert result is False
        disabled_manager._app.send_notification.assert_not_called()

    def test_scheduled_scan_disabled(self, disabled_manager):
        """Test notify_scheduled_scan_complete returns False when disabled."""
        result = disabled_manager.notify_scheduled_scan_complete(is_clean=True)
        assert result is False
        disabled_manager._app.send_notification.assert_not_called()

    def test_vt_scan_disabled(self, disabled_manager):
        """Test notify_virustotal_scan_complete returns False when disabled."""
        result = disabled_manager.notify_virustotal_scan_complete(is_clean=True, total_engines=70)
        assert result is False
        disabled_manager._app.send_notification.assert_not_called()

    def test_vt_rate_limit_disabled(self, disabled_manager):
        """Test notify_virustotal_rate_limit returns False when disabled."""
        result = disabled_manager.notify_virustotal_rate_limit()
        assert result is False
        disabled_manager._app.send_notification.assert_not_called()

    def test_vt_no_key_disabled(self, disabled_manager):
        """Test notify_virustotal_no_key returns False when disabled."""
        result = disabled_manager.notify_virustotal_no_key()
        assert result is False
        disabled_manager._app.send_notification.assert_not_called()

    def test_device_started_disabled(self, disabled_manager):
        """Test notify_device_scan_started returns False when disabled."""
        result = disabled_manager.notify_device_scan_started(
            device_name="USB", mount_point="/media/usb"
        )
        assert result is False
        disabled_manager._app.send_notification.assert_not_called()

    def test_device_complete_disabled(self, disabled_manager):
        """Test notify_device_scan_complete returns False when disabled."""
        result = disabled_manager.notify_device_scan_complete(device_name="USB", is_clean=True)
        assert result is False
        disabled_manager._app.send_notification.assert_not_called()


class TestNotificationManagerAllIds:
    """Tests for all notification ID constants."""

    def test_scheduled_scan_id_defined(self):
        """Test NOTIFICATION_ID_SCHEDULED_SCAN is defined."""
        assert NotificationManager.NOTIFICATION_ID_SCHEDULED_SCAN == "scheduled-scan-complete"

    def test_vt_scan_id_defined(self):
        """Test NOTIFICATION_ID_VT_SCAN is defined."""
        assert NotificationManager.NOTIFICATION_ID_VT_SCAN == "virustotal-scan-complete"

    def test_vt_rate_limit_id_defined(self):
        """Test NOTIFICATION_ID_VT_RATE_LIMIT is defined."""
        assert NotificationManager.NOTIFICATION_ID_VT_RATE_LIMIT == "virustotal-rate-limit"

    def test_vt_no_key_id_defined(self):
        """Test NOTIFICATION_ID_VT_NO_KEY is defined."""
        assert NotificationManager.NOTIFICATION_ID_VT_NO_KEY == "virustotal-no-key"

    def test_device_scan_started_id_defined(self):
        """Test NOTIFICATION_ID_DEVICE_SCAN_STARTED is defined."""
        assert NotificationManager.NOTIFICATION_ID_DEVICE_SCAN_STARTED == "device-scan-started"

    def test_device_scan_complete_id_defined(self):
        """Test NOTIFICATION_ID_DEVICE_SCAN_COMPLETE is defined."""
        assert NotificationManager.NOTIFICATION_ID_DEVICE_SCAN_COMPLETE == "device-scan-complete"

    def test_all_ids_are_unique(self):
        """Test that all notification IDs are unique."""
        ids = [
            NotificationManager.NOTIFICATION_ID_SCAN,
            NotificationManager.NOTIFICATION_ID_UPDATE,
            NotificationManager.NOTIFICATION_ID_SCHEDULED_SCAN,
            NotificationManager.NOTIFICATION_ID_VT_SCAN,
            NotificationManager.NOTIFICATION_ID_VT_RATE_LIMIT,
            NotificationManager.NOTIFICATION_ID_VT_NO_KEY,
            NotificationManager.NOTIFICATION_ID_DEVICE_SCAN_STARTED,
            NotificationManager.NOTIFICATION_ID_DEVICE_SCAN_COMPLETE,
        ]
        assert len(ids) == len(set(ids))


class TestNotificationManagerNoAppDefense:
    """BUG-012: defensive checks against _app is None.

    A code path that fires a notification before set_application() must
    fail gracefully (return False) instead of raising AttributeError on
    self._app.send_notification(...).
    """

    @pytest.fixture
    def temp_config_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_can_notify_returns_false_when_no_app(self, temp_config_dir):
        """_can_notify() must return False when no app reference is set."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        # Note: set_application() not called
        assert manager._app is None
        assert manager._can_notify() is False

    def test_send_before_set_application_does_not_crash(self, temp_config_dir):
        """_send() must not raise when called before set_application()."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)
        # No set_application called

        # Direct _send call should not raise — should return False.
        # Use mock.patch to avoid Gio side-effects in case the guard ever
        # fails and we accidentally reach Gio.Notification.new().
        with mock.patch("src.core.notification_manager.Gio"):
            result = manager._send(
                notification_id="test",
                title="t",
                body="b",
                priority=mock.MagicMock(),
                default_action="app.show-scan",
            )
        assert result is False

    def test_public_notify_methods_do_not_crash_without_app(self, temp_config_dir):
        """All notify_* public entrypoints return False (no crash) without app."""
        settings = SettingsManager(config_dir=temp_config_dir)
        settings.set("notifications_enabled", True)
        manager = NotificationManager(settings_manager=settings)
        assert manager._app is None

        # Each method returns False without raising AttributeError.
        assert manager.notify_scan_complete(is_clean=True, scanned_count=10) is False
        assert manager.notify_update_complete(success=True) is False
        assert manager.notify_scheduled_scan_complete(is_clean=True, scanned_count=5) is False
        assert manager.notify_virustotal_scan_complete(is_clean=True, total_engines=70) is False
        assert manager.notify_virustotal_rate_limit() is False
        assert manager.notify_virustotal_no_key() is False
        assert (
            manager.notify_device_scan_started(device_name="USB", mount_point="/media/usb") is False
        )

    def test_withdraw_notification_does_not_crash_without_app(self, temp_config_dir):
        """withdraw_notification() also guards against missing app."""
        settings = SettingsManager(config_dir=temp_config_dir)
        manager = NotificationManager(settings_manager=settings)
        assert manager._app is None
        assert manager.withdraw_notification("scan-complete") is False
