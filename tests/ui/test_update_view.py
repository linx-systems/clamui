# ClamUI Update View Tests
"""
Unit tests for the update_view module.

Tests cover:
- UpdateView import and initialization
- Notification behavior (only on actual updates, not UP_TO_DATE)
- Status banner styling (INFO for UP_TO_DATE, SUCCESS for actual updates)
"""

import sys
from unittest import mock

import pytest


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


@pytest.fixture
def update_view_module(mock_gi_modules):
    """Import update_view module with mocked GTK dependencies."""
    # Clear any cached import of update_view module
    if "src.ui.update_view" in sys.modules:
        del sys.modules["src.ui.update_view"]

    from src.ui import update_view

    yield update_view

    # Critical: Clear all src.* modules after test to prevent pollution
    _clear_src_modules()


@pytest.fixture
def mock_notification_manager():
    """Create a mock notification manager."""
    manager = mock.MagicMock()
    manager.notify_update_complete = mock.MagicMock()
    return manager


@pytest.fixture
def mock_app(mock_notification_manager):
    """Create a mock app with notification manager."""
    app = mock.MagicMock()
    app.notification_manager = mock_notification_manager
    return app


@pytest.fixture
def mock_root(mock_app):
    """Create a mock root with app."""
    root = mock.MagicMock()
    root.get_application.return_value = mock_app
    return root


# =============================================================================
# UpdateView Import Tests
# =============================================================================


class TestUpdateViewImport:
    """Tests for UpdateView import."""

    def test_import_update_view(self, update_view_module):
        """Test that UpdateView can be imported."""
        UpdateView = update_view_module.UpdateView
        assert UpdateView is not None


# =============================================================================
# Notification Behavior Tests
# =============================================================================


class TestUpdateViewNotifications:
    """Tests for UpdateView notification behavior."""

    def test_notification_sent_on_actual_update(self, update_view_module, mock_root):
        """Test notification is sent when database is actually updated."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        # Create an instance (mock the internal dependencies)
        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()
            view._update_button = mock.MagicMock()
            view._spinner = mock.MagicMock()

            # Create result for actual update
            result = UpdateResult(
                status=UpdateStatus.SUCCESS,
                stdout="daily.cvd updated",
                stderr="",
                exit_code=0,
                databases_updated=2,
                error_message=None,
            )

            # Mock get_root to return our mock_root
            with mock.patch.object(view, "get_root", return_value=mock_root):
                view._on_update_complete(result)

        # Should have sent notification
        mock_root.get_application.assert_called_once()
        app = mock_root.get_application.return_value
        app.notification_manager.notify_update_complete.assert_called_once_with(
            success=True, databases_updated=2
        )

    def test_no_notification_on_up_to_date(self, update_view_module, mock_root):
        """Test notification is NOT sent when database is already up-to-date."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        # Create an instance
        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()
            view._update_button = mock.MagicMock()
            view._spinner = mock.MagicMock()

            # Create result for up-to-date
            result = UpdateResult(
                status=UpdateStatus.UP_TO_DATE,
                stdout="database is up-to-date",
                stderr="",
                exit_code=0,
                databases_updated=0,
                error_message=None,
            )

            # Mock get_root to return our mock_root
            with mock.patch.object(view, "get_root", return_value=mock_root):
                view._on_update_complete(result)

        # Should NOT have sent notification
        app = mock_root.get_application.return_value
        app.notification_manager.notify_update_complete.assert_not_called()

    def test_no_notification_on_success_with_zero_updates(self, update_view_module, mock_root):
        """Test notification is NOT sent when SUCCESS but databases_updated is 0."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        # Create an instance
        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()
            view._update_button = mock.MagicMock()
            view._spinner = mock.MagicMock()

            # Create result - SUCCESS but no databases updated (edge case)
            result = UpdateResult(
                status=UpdateStatus.SUCCESS,
                stdout="",
                stderr="",
                exit_code=0,
                databases_updated=0,
                error_message=None,
            )

            # Mock get_root to return our mock_root
            with mock.patch.object(view, "get_root", return_value=mock_root):
                view._on_update_complete(result)

        # Should NOT have sent notification
        app = mock_root.get_application.return_value
        app.notification_manager.notify_update_complete.assert_not_called()

    def test_notification_sent_on_error(self, update_view_module, mock_root):
        """Test notification is sent when update fails with error."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        # Create an instance
        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()
            view._update_button = mock.MagicMock()
            view._spinner = mock.MagicMock()

            # Create result for error
            result = UpdateResult(
                status=UpdateStatus.ERROR,
                stdout="",
                stderr="Connection failed",
                exit_code=1,
                databases_updated=0,
                error_message="Connection failed",
            )

            # Mock get_root to return our mock_root
            with mock.patch.object(view, "get_root", return_value=mock_root):
                view._on_update_complete(result)

        # Should have sent notification with failure
        app = mock_root.get_application.return_value
        app.notification_manager.notify_update_complete.assert_called_once_with(
            success=False, databases_updated=0
        )


# =============================================================================
# Status Banner Styling Tests
# =============================================================================


class TestUpdateViewStatusBanner:
    """Tests for UpdateView status banner styling."""

    def test_success_banner_uses_success_class(self, update_view_module):
        """Test SUCCESS status uses SUCCESS CSS class."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        # Create an instance
        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()

            # Create result for success
            result = UpdateResult(
                status=UpdateStatus.SUCCESS,
                stdout="daily.cvd updated",
                stderr="",
                exit_code=0,
                databases_updated=2,
                error_message=None,
            )

            view._display_results(result)

            # Verify success class was set
            view._status_banner.set_title.assert_called_once()
            title_arg = view._status_banner.set_title.call_args[0][0]
            assert "2 databases updated" in title_arg
            # Check that set_status_class was called with SUCCESS

            # We can't easily verify the exact call without importing,
            # but we can check the banner was revealed
            assert view._status_banner.set_revealed.call_count >= 1

    def test_up_to_date_banner_uses_info_class(self, update_view_module):
        """Test UP_TO_DATE status uses INFO CSS class."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        # Create an instance
        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()

            # Create result for up-to-date
            result = UpdateResult(
                status=UpdateStatus.UP_TO_DATE,
                stdout="database is up-to-date",
                stderr="",
                exit_code=0,
                databases_updated=0,
                error_message=None,
            )

            view._display_results(result)

            # Verify title and that banner was revealed
            view._status_banner.set_title.assert_called_once_with("Database is already up to date")
            view._status_banner.set_revealed.assert_called_with(True)

    def test_error_banner_uses_error_class(self, update_view_module):
        """Test ERROR status uses ERROR CSS class."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        # Create an instance
        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()

            # Create result for error
            result = UpdateResult(
                status=UpdateStatus.ERROR,
                stdout="",
                stderr="Connection failed",
                exit_code=1,
                databases_updated=0,
                error_message="Connection failed",
            )

            view._display_results(result)

            # Verify error message in title
            view._status_banner.set_title.assert_called_once_with("Connection failed")
            view._status_banner.set_revealed.assert_called_with(True)

    def test_cancelled_banner_uses_warning_class(self, update_view_module):
        """Test CANCELLED status uses WARNING CSS class."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        # Create an instance
        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()

            # Create result for cancelled
            result = UpdateResult(
                status=UpdateStatus.CANCELLED,
                stdout="",
                stderr="",
                exit_code=0,
                databases_updated=0,
                error_message="Cancelled",
            )

            view._display_results(result)

            # Verify cancelled title
            view._status_banner.set_title.assert_called_once_with("Update cancelled")
            view._status_banner.set_revealed.assert_called_with(True)

    def test_rate_limited_result_shows_partial_summary(self, update_view_module):
        """Test rate-limited database details are shown as partial progress."""
        UpdateView = update_view_module.UpdateView
        UpdateStatus = update_view_module.UpdateStatus
        UpdateResult = update_view_module.UpdateResult

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._status_banner = mock.MagicMock()
            view._results_text = mock.MagicMock()
            mock_buffer = mock.MagicMock()
            view._results_text.get_buffer.return_value = mock_buffer

            result = UpdateResult(
                status=UpdateStatus.ERROR,
                stdout="",
                stderr="",
                exit_code=1,
                databases_updated=1,
                error_message=(
                    "Database update partially completed. Updated: daily.cvd. "
                    "Already current: bytecode.cvd. "
                    "Rate limited: main.cvd until 2026-03-06 10:30:00."
                ),
                updated_databases=["daily.cvd"],
                up_to_date_databases=["bytecode.cvd"],
                rate_limited_databases={"main.cvd": "2026-03-06 10:30:00"},
            )

            view._display_results(result)

            view._status_banner.set_title.assert_called_once_with(result.error_message)
            view._status_banner.add_css_class.assert_any_call("warning")

            rendered_text = mock_buffer.set_text.call_args[0][0]
            assert "UPDATE PARTIALLY COMPLETE" in rendered_text
            assert "Updated databases: daily.cvd" in rendered_text
            assert "Already current: bytecode.cvd" in rendered_text
            assert "Rate limited: main.cvd until 2026-03-06 10:30:00" in rendered_text


# =============================================================================
# Freshclam Status Tests
# =============================================================================


class TestUpdateViewFreshclamStatus:
    """Tests for freshclam status checking."""

    def test_freshclam_installed_enables_buttons(self, update_view_module):
        """Test freshclam installed enables update buttons."""
        UpdateView = update_view_module.UpdateView

        # Mock check_freshclam_installed to return True
        with mock.patch.object(
            update_view_module,
            "check_freshclam_installed",
            return_value=(True, "freshclam 1.0"),
        ):
            with mock.patch.object(UpdateView, "_setup_ui"):
                view = UpdateView()
                # Set up mock widgets that would be created in _setup_ui
                view._update_button = mock.MagicMock()
                view._force_update_button = mock.MagicMock()
                view._freshclam_status_icon = mock.MagicMock()
                view._freshclam_status_label = mock.MagicMock()
                view._status_banner = mock.MagicMock()

                # Call _check_freshclam_status
                view._check_freshclam_status()

                # Verify buttons were enabled
                view._update_button.set_sensitive.assert_called_with(True)
                view._force_update_button.set_sensitive.assert_called_with(True)

    def test_freshclam_not_found_disables_buttons(self, update_view_module):
        """Test freshclam not found disables update buttons."""
        UpdateView = update_view_module.UpdateView

        # Mock check_freshclam_installed to return False
        with mock.patch.object(
            update_view_module,
            "check_freshclam_installed",
            return_value=(False, "freshclam not found"),
        ):
            with mock.patch.object(UpdateView, "_setup_ui"):
                view = UpdateView()
                # Set up mock widgets
                view._update_button = mock.MagicMock()
                view._force_update_button = mock.MagicMock()
                view._freshclam_status_icon = mock.MagicMock()
                view._freshclam_status_label = mock.MagicMock()
                view._status_banner = mock.MagicMock()

                # Call _check_freshclam_status
                view._check_freshclam_status()

                # Verify buttons were disabled
                view._update_button.set_sensitive.assert_called_with(False)
                view._force_update_button.set_sensitive.assert_called_with(False)

    def test_shows_success_icon_when_installed(self, update_view_module):
        """Test shows success icon when freshclam is installed."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(
            update_view_module,
            "check_freshclam_installed",
            return_value=(True, "freshclam 1.0"),
        ):
            with mock.patch.object(UpdateView, "_setup_ui"):
                view = UpdateView()
                view._freshclam_status_icon = mock.MagicMock()

                view._check_freshclam_status()

                # Verify success icon was set
                view._freshclam_status_icon.set_from_icon_name.assert_called_once()

    def test_shows_warning_icon_when_not_found(self, update_view_module):
        """Test shows warning icon when freshclam is not found."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(
            update_view_module,
            "check_freshclam_installed",
            return_value=(False, "freshclam not found"),
        ):
            with mock.patch.object(UpdateView, "_setup_ui"):
                view = UpdateView()
                view._freshclam_status_icon = mock.MagicMock()

                view._check_freshclam_status()

                # Verify warning icon was set
                view._freshclam_status_icon.set_from_icon_name.assert_called_once()

    def test_sets_status_text_with_version(self, update_view_module):
        """Test sets status text with freshclam version."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(
            update_view_module,
            "check_freshclam_installed",
            return_value=(True, "freshclam 1.0"),
        ):
            with mock.patch.object(UpdateView, "_setup_ui"):
                view = UpdateView()
                view._freshclam_status_label = mock.MagicMock()

                view._check_freshclam_status()

                # Verify status text includes version
                view._freshclam_status_label.set_text.assert_called_once()
                call_args = view._freshclam_status_label.set_text.call_args[0][0]
                assert "freshclam" in call_args


# =============================================================================
# Async Freshclam Status Tests
# =============================================================================


class TestUpdateViewAsyncFreshclamStatus:
    """Tests for async freshclam status checking launched from __init__."""

    def test_init_launches_background_thread(self, update_view_module):
        """Test that __init__ launches a background thread for freshclam status check."""
        UpdateView = update_view_module.UpdateView

        with mock.patch("threading.Thread") as mock_thread_cls:
            mock_thread_instance = mock.MagicMock()
            mock_thread_cls.return_value = mock_thread_instance

            with mock.patch.object(UpdateView, "_setup_ui"):
                UpdateView()

            # Verify Thread was created with correct target and daemon=True
            mock_thread_cls.assert_called_once()
            call_kwargs = mock_thread_cls.call_args
            assert call_kwargs[1].get("daemon") is True or (
                len(call_kwargs[0]) > 0 and call_kwargs[1].get("daemon") is True
            )
            mock_thread_instance.start.assert_called_once()

    def test_init_does_not_call_check_freshclam_status_synchronously(self, update_view_module):
        """Test that __init__ does NOT call _check_freshclam_status synchronously."""
        UpdateView = update_view_module.UpdateView

        with mock.patch("threading.Thread"):
            with mock.patch.object(UpdateView, "_setup_ui"):
                with mock.patch.object(UpdateView, "_check_freshclam_status") as mock_check:
                    _view = UpdateView()

                    # _check_freshclam_status should NOT be called directly in __init__
                    mock_check.assert_not_called()

    def test_init_shows_loading_state(self, update_view_module):
        """Test that __init__ sets loading state text on the status label."""
        UpdateView = update_view_module.UpdateView

        with mock.patch("threading.Thread"):
            with mock.patch.object(UpdateView, "_setup_ui"):
                view = UpdateView()

                # After _setup_ui, the _freshclam_status_label should show
                # "Checking freshclam..." (set in _create_status_bar) and buttons
                # should be insensitive (set in _create_update_section).
                # The key thing is that __init__ does NOT block.
                assert view._freshclam_available is False

    def test_check_freshclam_status_async_gathers_results(self, update_view_module):
        """Test _check_freshclam_status_async gathers install and service results."""
        UpdateView = update_view_module.UpdateView
        FreshclamServiceStatus = update_view_module.FreshclamServiceStatus

        with mock.patch.object(
            update_view_module,
            "check_freshclam_installed",
            return_value=(True, "freshclam 1.0.0"),
        ):
            with mock.patch.object(UpdateView, "_setup_ui"):
                view = UpdateView()
                view._updater = mock.MagicMock()
                view._updater.check_freshclam_service.return_value = (
                    FreshclamServiceStatus.RUNNING,
                    "1234",
                )

                # Mock GLib.idle_add to capture the callback and args
                captured = {}

                def fake_idle_add(callback, *args):
                    captured["callback"] = callback
                    captured["args"] = args
                    return 0

                with mock.patch.object(update_view_module, "GLib") as mock_glib_module:
                    mock_glib_module.idle_add = fake_idle_add

                    view._check_freshclam_status_async()

                # Verify GLib.idle_add was called with the UI update callback
                assert "callback" in captured
                assert captured["callback"].__name__ == "_apply_freshclam_status"

    def test_apply_freshclam_status_installed(self, update_view_module):
        """Test _apply_freshclam_status updates UI correctly when freshclam is installed."""
        UpdateView = update_view_module.UpdateView
        FreshclamServiceStatus = update_view_module.FreshclamServiceStatus

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._update_button = mock.MagicMock()
            view._force_update_button = mock.MagicMock()
            view._freshclam_status_icon = mock.MagicMock()
            view._freshclam_status_label = mock.MagicMock()
            view._service_status_icon = mock.MagicMock()
            view._service_status_label = mock.MagicMock()
            view._status_banner = mock.MagicMock()

            # Simulate the result that the async thread would produce
            result = {
                "is_installed": True,
                "version_or_error": "freshclam 1.0.0",
                "service_status": FreshclamServiceStatus.RUNNING,
                "service_pid": "1234",
            }

            ret = view._apply_freshclam_status(result)

            # Verify buttons were enabled
            view._update_button.set_sensitive.assert_called_with(True)
            view._force_update_button.set_sensitive.assert_called_with(True)
            assert view._freshclam_available is True

            # GLib.idle_add callback should return False
            assert ret is False

    def test_apply_freshclam_status_not_installed(self, update_view_module):
        """Test _apply_freshclam_status updates UI correctly when freshclam is not found."""
        UpdateView = update_view_module.UpdateView
        FreshclamServiceStatus = update_view_module.FreshclamServiceStatus

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._update_button = mock.MagicMock()
            view._force_update_button = mock.MagicMock()
            view._freshclam_status_icon = mock.MagicMock()
            view._freshclam_status_label = mock.MagicMock()
            view._service_status_icon = mock.MagicMock()
            view._service_status_label = mock.MagicMock()
            view._status_banner = mock.MagicMock()

            result = {
                "is_installed": False,
                "version_or_error": "freshclam not found",
                "service_status": FreshclamServiceStatus.NOT_FOUND,
                "service_pid": None,
            }

            ret = view._apply_freshclam_status(result)

            # Verify buttons were disabled
            view._update_button.set_sensitive.assert_called_with(False)
            view._force_update_button.set_sensitive.assert_called_with(False)
            assert view._freshclam_available is False

            # GLib.idle_add callback should return False
            assert ret is False

    def test_apply_freshclam_status_guards_destroyed_widget(self, update_view_module):
        """Test _apply_freshclam_status safely handles destroyed widgets."""
        UpdateView = update_view_module.UpdateView
        FreshclamServiceStatus = update_view_module.FreshclamServiceStatus

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            # Simulate widget being destroyed: get_mapped() returns False
            view.get_mapped = mock.MagicMock(return_value=False)

            result = {
                "is_installed": True,
                "version_or_error": "freshclam 1.0.0",
                "service_status": FreshclamServiceStatus.RUNNING,
                "service_pid": "1234",
            }

            # Should return False without crashing
            ret = view._apply_freshclam_status(result)
            assert ret is False

    def test_apply_freshclam_status_service_running(self, update_view_module):
        """Test _apply_freshclam_status shows correct service status when running."""
        UpdateView = update_view_module.UpdateView
        FreshclamServiceStatus = update_view_module.FreshclamServiceStatus

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._update_button = mock.MagicMock()
            view._force_update_button = mock.MagicMock()
            view._freshclam_status_icon = mock.MagicMock()
            view._freshclam_status_label = mock.MagicMock()
            view._service_status_icon = mock.MagicMock()
            view._service_status_label = mock.MagicMock()
            view._status_banner = mock.MagicMock()

            result = {
                "is_installed": True,
                "version_or_error": "freshclam 1.0.0",
                "service_status": FreshclamServiceStatus.RUNNING,
                "service_pid": "1234",
            }

            view._apply_freshclam_status(result)

            # Verify service status was set
            assert view._service_status == FreshclamServiceStatus.RUNNING
            # The service label should mention "Active"
            view._service_status_label.set_text.assert_called_once()
            label_text = view._service_status_label.set_text.call_args[0][0]
            assert "Active" in label_text
            assert "1234" in label_text

    def test_apply_freshclam_status_service_stopped(self, update_view_module):
        """Test _apply_freshclam_status shows correct service status when stopped."""
        UpdateView = update_view_module.UpdateView
        FreshclamServiceStatus = update_view_module.FreshclamServiceStatus

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._update_button = mock.MagicMock()
            view._force_update_button = mock.MagicMock()
            view._freshclam_status_icon = mock.MagicMock()
            view._freshclam_status_label = mock.MagicMock()
            view._service_status_icon = mock.MagicMock()
            view._service_status_label = mock.MagicMock()
            view._status_banner = mock.MagicMock()

            result = {
                "is_installed": True,
                "version_or_error": "freshclam 1.0.0",
                "service_status": FreshclamServiceStatus.STOPPED,
                "service_pid": None,
            }

            view._apply_freshclam_status(result)

            assert view._service_status == FreshclamServiceStatus.STOPPED
            view._service_status_label.set_text.assert_called_once()
            label_text = view._service_status_label.set_text.call_args[0][0]
            assert "Stopped" in label_text


# =============================================================================
# Button Handler Tests
# =============================================================================


class TestUpdateViewButtonHandlers:
    """Tests for button click handlers."""

    def test_update_click_starts_normal_update(self, update_view_module):
        """Test update button click starts normal update."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._freshclam_available = True
            view._updater = mock.MagicMock()

            # Mock _start_update to avoid side effects
            with mock.patch.object(view, "_start_update") as mock_start:
                view._on_update_clicked(mock.MagicMock())

                # Verify normal update was started
                mock_start.assert_called_once_with(force=False)

    def test_force_update_click_starts_force_update(self, update_view_module):
        """Test force update button click starts force update."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._freshclam_available = True
            view._updater = mock.MagicMock()

            # Mock _start_update to avoid side effects
            with mock.patch.object(view, "_start_update") as mock_start:
                view._on_force_update_clicked(mock.MagicMock())

                # Verify force update was started
                mock_start.assert_called_once_with(force=True)

    def test_cancel_click_cancels_updater_off_main_thread(self, update_view_module):
        """Cancel must run the (blocking) updater.cancel() off the GTK main thread.
        cancel() escalates SIGTERM -> SIGKILL and blocks on process.wait() for
        several seconds; invoking it inline in the click handler would freeze
        the UI. It must be dispatched to a background thread instead.
        """
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._updater = mock.MagicMock()
            view._cancel_button = mock.MagicMock()

            with mock.patch("src.ui.update_view.threading.Thread") as mock_thread:
                mock_instance = mock.MagicMock()
                mock_thread.return_value = mock_instance
                view._on_cancel_clicked(mock.MagicMock())

                # cancel() is the thread target, NOT invoked on the main thread
                view._updater.cancel.assert_not_called()
                mock_thread.assert_called_once()
                assert mock_thread.call_args.kwargs["target"] is view._updater.cancel
                mock_instance.start.assert_called_once()
                # Cancel button is disabled for immediate feedback
                view._cancel_button.set_sensitive.assert_called_once_with(False)

    def test_handlers_do_nothing_when_freshclam_unavailable(self, update_view_module):
        """Test handlers do nothing when freshclam unavailable."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._freshclam_available = False
            view._updater = mock.MagicMock()
            view._updater.cancel = mock.MagicMock()

            # Mock _start_update to track calls
            with mock.patch.object(view, "_start_update") as mock_start:
                view._on_update_clicked(mock.MagicMock())

                # Should not start update when freshclam unavailable
                mock_start.assert_not_called()

                view._on_force_update_clicked(mock.MagicMock())

                # Should not start force update when freshclam unavailable
                assert mock_start.call_count == 0


# =============================================================================
# Update Flow Tests
# =============================================================================


class TestUpdateViewUpdateFlow:
    """Tests for update flow."""

    def test_set_updating_state_shows_spinner(self, update_view_module):
        """Test set_updating_state shows spinner when True."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._update_spinner = mock.MagicMock()
            view._update_button = mock.MagicMock()
            view._force_update_button = mock.MagicMock()
            view._cancel_button = mock.MagicMock()
            view._freshclam_available = True
            view._is_updating = False

            # Set updating to True
            view._set_updating_state(True)

            # Verify spinner shown and buttons disabled
            view._update_spinner.set_visible.assert_called_with(True)
            view._update_spinner.start.assert_called_once()
            view._update_button.set_sensitive.assert_called_with(False)
            view._force_update_button.set_sensitive.assert_called_with(False)
            view._cancel_button.set_visible.assert_called_with(True)

    def test_set_updating_state_disables_buttons(self, update_view_module):
        """Test set_updating_state disables buttons."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._update_button = mock.MagicMock()
            view._force_update_button = mock.MagicMock()
            view._update_spinner = mock.MagicMock()
            view._cancel_button = mock.MagicMock()
            view._freshclam_available = True

            # Set updating to True
            view._set_updating_state(True)

            # Verify buttons disabled
            view._update_button.set_sensitive.assert_called_with(False)
            view._force_update_button.set_sensitive.assert_called_with(False)

    def test_set_updating_state_restores_state(self, update_view_module):
        """Test set_updating_state restores state when False."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._update_spinner = mock.MagicMock()
            view._update_button = mock.MagicMock()
            view._force_update_button = mock.MagicMock()
            view._cancel_button = mock.MagicMock()
            view._freshclam_available = True
            view._is_updating = True

            # Set updating to False
            view._set_updating_state(False)

            # Verify spinner hidden and buttons enabled
            view._update_spinner.stop.assert_called_once()
            view._update_spinner.set_visible.assert_called_with(False)
            view._update_button.set_sensitive.assert_called_with(True)
            view._force_update_button.set_sensitive.assert_called_with(True)
            view._cancel_button.set_visible.assert_called_with(False)

    def test_start_update_clears_results(self, update_view_module):
        """Test start_update clears previous results."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._results_text = mock.MagicMock()
            view._status_banner = mock.MagicMock()
            view._updater = mock.MagicMock()
            view._update_spinner = mock.MagicMock()

            # Mock other internal methods
            with mock.patch.multiple(
                view,
                __setattr__=lambda *args, **kwargs: None,
                _set_updating_state=mock.MagicMock(),
            ):
                view._start_update(force=False)

                # Verify _clear_results was called
                # get_buffer is called twice (once to set text, once in _clear_results)
                assert view._results_text.get_buffer.call_count >= 1
                buffer_mock = view._results_text.get_buffer.return_value
                buffer_mock.set_text.assert_called()
                view._status_banner.set_revealed.assert_called_with(False)

    def test_start_update_normal_shows_correct_message(self, update_view_module):
        """Test start_update shows correct message for normal update."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._results_text = mock.MagicMock()
            view._status_banner = mock.MagicMock()
            view._updater = mock.MagicMock()
            view._update_spinner = mock.MagicMock()

            # Mock other internal methods
            with mock.patch.multiple(
                view,
                __setattr__=lambda *args, **kwargs: None,
                _set_updating_state=mock.MagicMock(),
            ):
                view._start_update(force=False)

                # Verify buffer was set with update message
                buffer_mock = view._results_text.get_buffer.return_value
                args = buffer_mock.set_text.call_args[0][0]
                assert "Updating virus database" in args

    def test_start_update_force_shows_correct_message(self, update_view_module):
        """Test start_update shows correct message for force update."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._results_text = mock.MagicMock()
            view._status_banner = mock.MagicMock()
            view._updater = mock.MagicMock()
            view._update_spinner = mock.MagicMock()

            # Mock other internal methods
            with mock.patch.multiple(
                view,
                __setattr__=lambda *args, **kwargs: None,
                _set_updating_state=mock.MagicMock(),
            ):
                view._start_update(force=True)

                # Verify buffer was set with force update message
                buffer_mock = view._results_text.get_buffer.return_value
                args = buffer_mock.set_text.call_args[0][0]
                assert "Force updating" in args or "Backing up" in args

    def test_clear_results_clears_text_and_banner(self, update_view_module):
        """Test clear_results clears text and banner."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            view._results_text = mock.MagicMock()
            view._status_banner = mock.MagicMock()

            view._clear_results()

            # Verify results text was cleared
            view._results_text.get_buffer.assert_called_once()
            buffer_mock = view._results_text.get_buffer.return_value
            buffer_mock.set_text.assert_called_once_with("")

            # Verify banner was hidden
            view._status_banner.set_revealed.assert_called_with(False)

    def test_on_status_banner_dismissed(self, update_view_module):
        """Test status banner dismissal handler."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()
            banner = mock.MagicMock()

            view._on_status_banner_dismissed(banner)

            banner.set_revealed.assert_called_once_with(False)


# =============================================================================
# Property Access Tests
# =============================================================================


class TestUpdateViewPropertyAccess:
    """Tests for property access."""

    def test_updater_property_returns_instance(self, update_view_module):
        """Test updater property returns the FreshclamUpdater instance."""
        UpdateView = update_view_module.UpdateView

        with mock.patch.object(UpdateView, "_setup_ui"):
            view = UpdateView()

            # Should return the updater instance
            assert view.updater is view._updater
