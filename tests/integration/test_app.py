# ClamUI App Tests
"""Unit tests for the ClamUIApp application class."""

import sys
from types import SimpleNamespace
from unittest import mock

import pytest


# Create a mock setup function to prepare mocks before each test
@pytest.fixture(autouse=True)
def mock_gtk_modules():
    """Mock GTK/GI modules before importing app module."""
    # Create fresh mocks for each test
    mock_glib = mock.MagicMock()
    mock_gio = mock.MagicMock()
    mock_gtk = mock.MagicMock()
    mock_adw = mock.MagicMock()

    # GTK version functions (needed for file_export.py GTK version check)
    mock_gtk.get_minor_version = mock.MagicMock(return_value=14)
    mock_gtk.get_major_version = mock.MagicMock(return_value=4)

    # Configure mock Gio.SimpleAction
    mock_gio.SimpleAction.new.return_value = mock.MagicMock()
    mock_gio.ApplicationFlags.FLAGS_NONE = 0

    # Configure mock Adw.Application as a proper base class
    class MockAdwApplication:
        def __init__(self, **kwargs):
            self.application_id = kwargs.get("application_id", "")
            self.flags = kwargs.get("flags", 0)
            self.add_action = mock.MagicMock()
            self.set_accels_for_action = mock.MagicMock()
            self.quit = mock.MagicMock()
            self.props = mock.MagicMock()

    mock_adw.Application = MockAdwApplication
    mock_adw.AboutDialog = mock.MagicMock

    # Set up the gi mock
    mock_gi = mock.MagicMock()
    mock_gi.version_info = (
        3,
        48,
        0,
    )  # Required for matplotlib backend_gtk4.py comparison
    mock_gi.require_version = mock.MagicMock()
    mock_gi_repository = mock.MagicMock()
    mock_gi_repository.GLib = mock_glib
    mock_gi_repository.Gio = mock_gio
    mock_gi_repository.Gtk = mock_gtk
    mock_gi_repository.Adw = mock_adw

    # Store mocks for tests to access
    _mocks = {
        "gi": mock_gi,
        "gi.repository": mock_gi_repository,
        "Gio": mock_gio,
        "Adw": mock_adw,
        "Gtk": mock_gtk,
        "GLib": mock_glib,
    }

    # Mock matplotlib gtk backend to avoid import issues
    mock_backend = mock.MagicMock()

    # Patch modules
    with mock.patch.dict(
        sys.modules,
        {
            "gi": mock_gi,
            "gi.repository": mock_gi_repository,
            "matplotlib.backends.backend_gtk4": mock_backend,
            "matplotlib.backends.backend_gtk4agg": mock_backend,
            "src.ui.window": mock.MagicMock(),
            "src.ui.scan_view": mock.MagicMock(),
            "src.ui.update_view": mock.MagicMock(),
            "src.ui.logs_view": mock.MagicMock(),
            "src.ui.components_view": mock.MagicMock(),
            "src.ui.preferences": mock.MagicMock(),
            "src.ui.preferences.window": mock.MagicMock(),
            "src.ui.statistics_view": mock.MagicMock(),
        },
    ):
        # Need to remove and reimport the app module for fresh mocks
        if "src.app" in sys.modules:
            del sys.modules["src.app"]

        yield _mocks


@pytest.fixture
def gio_mock(mock_gtk_modules):
    """Get the Gio mock for tests."""
    return mock_gtk_modules["Gio"]


@pytest.fixture
def app(mock_gtk_modules):
    """Create a ClamUIApp instance for testing."""
    from src.app import ClamUIApp

    return ClamUIApp()


class TestClamUIAppSetup:
    """Tests for ClamUIApp initialization and setup."""

    def test_app_has_correct_application_id(self, app):
        """Test that the application has the correct application ID."""
        assert app.application_id == "io.github.linx_systems.ClamUI"

    def test_app_has_version(self, app):
        """Test that the application has a version string."""
        assert hasattr(app, "version")
        assert isinstance(app.version, str)
        assert len(app.version) > 0

    def test_app_has_app_name(self, app):
        """Test that the application has an app name."""
        assert hasattr(app, "app_name")
        assert app.app_name == "ClamUI"


class TestClamUIAppActions:
    """Tests for ClamUIApp actions including preferences."""

    def test_setup_actions_creates_quit_action(self, app, gio_mock):
        """Test that _setup_actions creates a quit action."""
        gio_mock.SimpleAction.new.reset_mock()
        app._setup_actions()

        # Find call to SimpleAction.new with "quit"
        quit_calls = [
            call for call in gio_mock.SimpleAction.new.call_args_list if call[0][0] == "quit"
        ]
        assert len(quit_calls) == 1

    def test_setup_actions_creates_about_action(self, app, gio_mock):
        """Test that _setup_actions creates an about action."""
        gio_mock.SimpleAction.new.reset_mock()
        app._setup_actions()

        # Find call to SimpleAction.new with "about"
        about_calls = [
            call for call in gio_mock.SimpleAction.new.call_args_list if call[0][0] == "about"
        ]
        assert len(about_calls) == 1

    def test_setup_actions_creates_preferences_action(self, app, gio_mock):
        """Test that _setup_actions creates a preferences action."""
        gio_mock.SimpleAction.new.reset_mock()
        app._setup_actions()

        # Find call to SimpleAction.new with "preferences"
        preferences_calls = [
            call for call in gio_mock.SimpleAction.new.call_args_list if call[0][0] == "preferences"
        ]
        assert len(preferences_calls) == 1

    def test_preferences_action_is_added_to_app(self, app):
        """Test that the preferences action is added to the application."""
        app._setup_actions()

        # Verify add_action was called
        app.add_action.assert_called()

    def test_preferences_keyboard_shortcut_set(self, app):
        """Test that Ctrl+, shortcut is set for preferences action."""
        app._setup_actions()

        # Find call to set_accels_for_action with "app.preferences"
        accel_calls = [
            call
            for call in app.set_accels_for_action.call_args_list
            if call[0][0] == "app.preferences"
        ]
        assert len(accel_calls) == 1
        # Verify the shortcut is Ctrl+comma
        assert accel_calls[0][0][1] == ["<Control>comma"]

    def test_quit_keyboard_shortcut_set(self, app):
        """Test that Ctrl+q shortcut is set for quit action."""
        app._setup_actions()

        # Find call to set_accels_for_action with "app.quit"
        accel_calls = [
            call for call in app.set_accels_for_action.call_args_list if call[0][0] == "app.quit"
        ]
        assert len(accel_calls) == 1
        assert accel_calls[0][0][1] == ["<Control>q"]


class TestClamUIAppPreferencesHandler:
    """Tests for the preferences action handler."""

    def test_on_preferences_handler_exists(self, app):
        """Test that the _on_preferences handler method exists."""
        assert hasattr(app, "_on_preferences")
        assert callable(app._on_preferences)

    def test_on_preferences_callable_without_error(self, app, mock_gtk_modules):
        """Test that _on_preferences can be called without raising errors."""
        # Set up mock active_window
        app.props = mock.MagicMock()
        app.props.active_window = mock.MagicMock()

        # Should not raise any exceptions
        app._on_preferences(None, None)


class TestClamUIAppViewSwitching:
    """Tests for view switching actions."""

    def test_setup_actions_creates_show_scan_action(self, app, gio_mock):
        """Test that _setup_actions creates a show-scan action."""
        gio_mock.SimpleAction.new.reset_mock()
        app._setup_actions()

        show_scan_calls = [
            call for call in gio_mock.SimpleAction.new.call_args_list if call[0][0] == "show-scan"
        ]
        assert len(show_scan_calls) == 1

    def test_setup_actions_creates_show_update_action(self, app, gio_mock):
        """Test that _setup_actions creates a show-update action."""
        gio_mock.SimpleAction.new.reset_mock()
        app._setup_actions()

        show_update_calls = [
            call for call in gio_mock.SimpleAction.new.call_args_list if call[0][0] == "show-update"
        ]
        assert len(show_update_calls) == 1

    def test_setup_actions_creates_show_logs_action(self, app, gio_mock):
        """Test that _setup_actions creates a show-logs action."""
        gio_mock.SimpleAction.new.reset_mock()
        app._setup_actions()

        show_logs_calls = [
            call for call in gio_mock.SimpleAction.new.call_args_list if call[0][0] == "show-logs"
        ]
        assert len(show_logs_calls) == 1

    def test_setup_actions_creates_show_components_action(self, app, gio_mock):
        """Test that _setup_actions creates a show-components action."""
        gio_mock.SimpleAction.new.reset_mock()
        app._setup_actions()

        show_components_calls = [
            call
            for call in gio_mock.SimpleAction.new.call_args_list
            if call[0][0] == "show-components"
        ]
        assert len(show_components_calls) == 1

    def test_on_show_scan_handler_exists(self, app):
        """Test that the _on_show_scan handler method exists."""
        assert hasattr(app, "_on_show_scan")
        assert callable(app._on_show_scan)

    def test_on_show_update_handler_exists(self, app):
        """Test that the _on_show_update handler method exists."""
        assert hasattr(app, "_on_show_update")
        assert callable(app._on_show_update)

    def test_on_show_logs_handler_exists(self, app):
        """Test that the _on_show_logs handler method exists."""
        assert hasattr(app, "_on_show_logs")
        assert callable(app._on_show_logs)

    def test_on_show_components_handler_exists(self, app):
        """Test that the _on_show_components handler method exists."""
        assert hasattr(app, "_on_show_components")
        assert callable(app._on_show_components)


class TestClamUIAppLifecycle:
    """Tests for application lifecycle methods."""

    def test_do_activate_method_exists(self, app):
        """Test that do_activate method exists."""
        assert hasattr(app, "do_activate")
        assert callable(app.do_activate)

    def test_do_startup_method_exists(self, app):
        """Test that do_startup method exists."""
        assert hasattr(app, "do_startup")
        assert callable(app.do_startup)

    def test_on_quit_handler_exists(self, app):
        """Test that the _on_quit handler method exists."""
        assert hasattr(app, "_on_quit")
        assert callable(app._on_quit)

    def test_on_about_handler_exists(self, app):
        """Test that the _on_about handler method exists."""
        assert hasattr(app, "_on_about")
        assert callable(app._on_about)

    def test_on_about_uses_compat_presenter(self, app):
        """Test that about action delegates to the compatibility presenter."""
        app.props = mock.MagicMock()
        app.props.active_window = mock.MagicMock()

        with mock.patch("src.app.present_about_dialog") as mock_present_about_dialog:
            app._on_about(None, None)

        mock_present_about_dialog.assert_called_once()
        call_kwargs = mock_present_about_dialog.call_args.kwargs
        assert call_kwargs["app_name"] == "ClamUI"
        assert call_kwargs["version"] == app.version
        assert call_kwargs["license_type"] == mock.ANY

    def test_on_scan_file_uses_compat_file_picker(self, app):
        """Test that scan-file action delegates to the compatibility picker."""
        app.props = mock.MagicMock()
        app.props.active_window = mock.MagicMock()

        with mock.patch("src.app.open_paths_dialog") as mock_open_paths_dialog:
            app._on_scan_file(None, None)

        mock_open_paths_dialog.assert_called_once()
        call_kwargs = mock_open_paths_dialog.call_args.kwargs
        assert call_kwargs["select_folders"] is True
        assert call_kwargs["multiple"] is False

    def test_configure_icon_theme_sets_adwaita_when_theme_differs(self, app):
        """Test that icon theme is forced to Adwaita when needed."""
        settings = mock.MagicMock()
        settings.get_property.return_value = "Mint-Y-Dark"

        with mock.patch("src.app.Gtk.Settings.get_default", return_value=settings):
            app._configure_icon_theme()

        settings.set_property.assert_called_once_with("gtk-icon-theme-name", "Adwaita")

    def test_configure_icon_theme_keeps_adwaita_when_already_set(self, app):
        """Test that icon theme is not changed when already Adwaita."""
        settings = mock.MagicMock()
        settings.get_property.return_value = "Adwaita"

        with mock.patch("src.app.Gtk.Settings.get_default", return_value=settings):
            app._configure_icon_theme()

        settings.set_property.assert_not_called()

    def test_configure_icon_theme_noop_when_settings_unavailable(self, app):
        """Test that icon theme setup is skipped when GTK settings are unavailable."""
        with mock.patch("src.app.Gtk.Settings.get_default", return_value=None):
            app._configure_icon_theme()

    def test_ensure_log_privacy_migration_monitor_waits_before_showing_status_and_schedules_poll(
        self, app, mock_gtk_modules
    ):
        """Test startup migration monitoring waits before showing the banner."""
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_manager = mock.MagicMock()
        mock_manager.get_privacy_migration_status.return_value = SimpleNamespace(
            is_running=True,
            processed_files=2,
            total_files=5,
        )
        app._startup_log_manager = mock_manager
        app._log_privacy_poll_id = None

        with mock.patch("src.app.time.monotonic", return_value=100.0):
            app._ensure_log_privacy_migration_monitor()

        mock_manager.start_privacy_migration_async.assert_called_once()
        assert app._log_privacy_started_at == 100.0
        assert app._log_privacy_banner_shown_at is None
        mock_window.set_activity_status.assert_called_once_with(None)
        mock_gtk_modules["GLib"].timeout_add.assert_called_once()

    def test_poll_log_privacy_migration_shows_status_after_delay(self, app):
        """Test the poller shows the banner once migration exceeds the delay threshold."""
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_manager = mock.MagicMock()
        mock_manager.get_privacy_migration_status.return_value = SimpleNamespace(
            is_running=True,
            processed_files=2,
            total_files=5,
        )
        app._startup_log_manager = mock_manager
        app._log_privacy_started_at = 10.0

        with mock.patch("src.app.time.monotonic", return_value=11.1):
            result = app._poll_log_privacy_migration()

        assert result is True
        assert app._log_privacy_banner_shown_at == 11.1
        mock_window.set_activity_status.assert_called_once_with(
            "Updating stored logs for privacy (2/5)"
        )

    def test_poll_log_privacy_migration_keeps_completion_banner_visible_until_minimum_time(
        self, app
    ):
        """Test the completed banner remains visible without a spinner for the dwell time."""
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_manager = mock.MagicMock()
        mock_manager.get_privacy_migration_status.return_value = SimpleNamespace(
            is_running=False,
            processed_files=3,
            total_files=3,
        )
        app._startup_log_manager = mock_manager
        app._log_privacy_started_at = 20.0
        app._log_privacy_banner_shown_at = 21.0

        with mock.patch("src.app.time.monotonic", return_value=24.0):
            result = app._poll_log_privacy_migration()

        assert result is True
        mock_window.set_activity_status.assert_called_once_with(
            "Updating stored logs for privacy (3/3)",
            show_spinner=False,
        )

    def test_poll_log_privacy_migration_hides_status_after_minimum_visible_time(self, app):
        """Test the poller hides the banner once the minimum visible time has elapsed."""
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_manager = mock.MagicMock()
        mock_manager.get_privacy_migration_status.return_value = SimpleNamespace(
            is_running=False,
            processed_files=3,
            total_files=3,
        )
        app._startup_log_manager = mock_manager
        app._log_privacy_started_at = 20.0
        app._log_privacy_banner_shown_at = 21.0
        app._log_privacy_poll_id = 99

        with mock.patch("src.app.time.monotonic", return_value=26.1):
            result = app._poll_log_privacy_migration()

        assert result is False
        assert app._log_privacy_poll_id is None
        assert app._log_privacy_started_at is None
        assert app._log_privacy_banner_shown_at is None
        mock_window.set_activity_status.assert_called_once_with(None)


class TestClamUIAppQuickScanProfile:
    """Tests for Quick Scan profile retrieval and application."""

    def test_get_quick_scan_profile_method_exists(self, app):
        """Test that the _get_quick_scan_profile helper method exists."""
        assert hasattr(app, "_get_quick_scan_profile")
        assert callable(app._get_quick_scan_profile)

    def test_get_quick_scan_profile_calls_profile_manager(self, app):
        """Test that _get_quick_scan_profile retrieves profile from profile manager."""
        # Mock the profile manager
        app._profile_manager = mock.MagicMock()
        mock_profile = mock.MagicMock()
        mock_profile.id = "quick-scan-profile-id"
        mock_profile.name = "Quick Scan"
        app._profile_manager.get_profile_by_name.return_value = mock_profile

        result = app._get_quick_scan_profile()

        app._profile_manager.get_profile_by_name.assert_called_once_with("Quick Scan")
        assert result == mock_profile

    def test_get_quick_scan_profile_returns_none_when_not_found(self, app):
        """Test that _get_quick_scan_profile returns None when profile not found."""
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        result = app._get_quick_scan_profile()

        assert result is None

    def test_on_statistics_quick_scan_handler_exists(self, app):
        """Test that the _on_statistics_quick_scan handler method exists."""
        assert hasattr(app, "_on_statistics_quick_scan")
        assert callable(app._on_statistics_quick_scan)

    def test_on_statistics_quick_scan_switches_to_scan_view(self, app, mock_gtk_modules):
        """Test that _on_statistics_quick_scan switches to scan view."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (fallback path)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler
        app._on_statistics_quick_scan()

        # Verify view switch
        mock_window.set_content_view.assert_called_once_with(mock_scan_view)
        mock_window.set_active_view.assert_called_once_with("scan")
        assert app._current_view == "scan"

    def test_on_statistics_quick_scan_applies_quick_scan_profile(self, app, mock_gtk_modules):
        """Test that _on_statistics_quick_scan applies the Quick Scan profile."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return a profile
        mock_profile = mock.MagicMock()
        mock_profile.id = "quick-scan-profile-id"
        mock_profile.name = "Quick Scan"
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = mock_profile

        # Call the handler
        app._on_statistics_quick_scan()

        # Verify profile is applied
        mock_scan_view.refresh_profiles.assert_called_once()
        mock_scan_view.set_selected_profile.assert_called_once_with("quick-scan-profile-id")

    def test_on_statistics_quick_scan_falls_back_to_home_when_profile_missing(
        self, app, mock_gtk_modules
    ):
        """Test that _on_statistics_quick_scan falls back to home directory when profile not found."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler
        with mock.patch("src.app.os.path.expanduser") as mock_expanduser:
            mock_expanduser.return_value = "/home/testuser"
            app._on_statistics_quick_scan()

            # Verify fallback to home directory
            mock_scan_view._set_selected_path.assert_called_once_with("/home/testuser")
        # Verify set_selected_profile was NOT called
        mock_scan_view.set_selected_profile.assert_not_called()

    def test_on_statistics_quick_scan_does_not_auto_start_scan(self, app, mock_gtk_modules):
        """Test that _on_statistics_quick_scan does NOT auto-start the scan."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval
        mock_profile = mock.MagicMock()
        mock_profile.id = "quick-scan-profile-id"
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = mock_profile

        # Call the handler
        app._on_statistics_quick_scan()

        # Verify _start_scan was NOT called (user must click Start Scan)
        mock_scan_view._start_scan.assert_not_called()

    def test_on_statistics_quick_scan_no_action_without_window(self, app, mock_gtk_modules):
        """Test that _on_statistics_quick_scan does nothing without active window."""
        app.props = mock.MagicMock()
        app.props.active_window = None

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view

        # Call the handler
        app._on_statistics_quick_scan()

        # Verify no scan view methods were called
        mock_scan_view.refresh_profiles.assert_not_called()
        mock_scan_view.set_selected_profile.assert_not_called()

    def test_on_statistics_quick_scan_lazy_loads_scan_view(self, app, mock_gtk_modules):
        """Test that _on_statistics_quick_scan lazily loads scan view if not created."""
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window
        # With lazy loading, even if _scan_view is None, accessing the property creates it
        app._scan_view = None

        # Mock profile manager to return no quick scan profile
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler - should create scan view via lazy loading
        app._on_statistics_quick_scan()

        # set_content_view should be called since lazy loading creates the view
        mock_window.set_content_view.assert_called_once()


class TestClamUIAppTrayQuickScan:
    """Tests for Tray Menu Quick Scan profile retrieval and application."""

    def test_on_tray_quick_scan_handler_exists(self, app):
        """Test that the _on_tray_quick_scan handler method exists."""
        assert hasattr(app, "_on_tray_quick_scan")
        assert callable(app._on_tray_quick_scan)

    def test_do_tray_quick_scan_handler_exists(self, app):
        """Test that the _do_tray_quick_scan handler method exists."""
        assert hasattr(app, "_do_tray_quick_scan")
        assert callable(app._do_tray_quick_scan)

    def test_do_tray_quick_scan_switches_to_scan_view(self, app, mock_gtk_modules):
        """Test that _do_tray_quick_scan switches to scan view."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (fallback path)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Mock activate to just set up the window
        app.activate = mock.MagicMock()

        # Call the handler
        app._do_tray_quick_scan()

        # Verify view switch
        mock_window.set_content_view.assert_called_once_with(mock_scan_view)
        mock_window.set_active_view.assert_called_once_with("scan")
        assert app._current_view == "scan"

    def test_do_tray_quick_scan_applies_quick_scan_profile(self, app, mock_gtk_modules):
        """Test that _do_tray_quick_scan applies the Quick Scan profile."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return a profile
        mock_profile = mock.MagicMock()
        mock_profile.id = "quick-scan-profile-id"
        mock_profile.name = "Quick Scan"
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = mock_profile

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        app._do_tray_quick_scan()

        # Verify profile is applied
        mock_scan_view.refresh_profiles.assert_called_once()
        mock_scan_view.set_selected_profile.assert_called_once_with("quick-scan-profile-id")

    def test_do_tray_quick_scan_starts_scan_after_profile_application(self, app, mock_gtk_modules):
        """Test that _do_tray_quick_scan starts the scan after applying profile."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return a profile
        mock_profile = mock.MagicMock()
        mock_profile.id = "quick-scan-profile-id"
        mock_profile.name = "Quick Scan"
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = mock_profile

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        app._do_tray_quick_scan()

        # Verify scan is started (unlike statistics quick scan, tray auto-starts)
        mock_scan_view._start_scan.assert_called_once()

    def test_do_tray_quick_scan_falls_back_to_home_when_profile_missing(
        self, app, mock_gtk_modules
    ):
        """Test that _do_tray_quick_scan falls back to home directory when profile not found."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        with mock.patch("src.app.os.path.expanduser") as mock_expanduser:
            mock_expanduser.return_value = "/home/testuser"
            app._do_tray_quick_scan()

            # Verify fallback to home directory
            mock_scan_view._set_selected_path.assert_called_once_with("/home/testuser")
        # Verify set_selected_profile was NOT called
        mock_scan_view.set_selected_profile.assert_not_called()

    def test_do_tray_quick_scan_starts_scan_in_fallback_case(self, app, mock_gtk_modules):
        """Test that _do_tray_quick_scan starts scan even when falling back to home directory."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        app._do_tray_quick_scan()

        # Verify scan is started even in fallback case
        mock_scan_view._start_scan.assert_called_once()

    def test_do_tray_quick_scan_calls_activate(self, app, mock_gtk_modules):
        """Test that _do_tray_quick_scan activates the application."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view

        # Mock profile retrieval
        mock_profile = mock.MagicMock()
        mock_profile.id = "quick-scan-profile-id"
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = mock_profile

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        app._do_tray_quick_scan()

        # Verify activate was called
        app.activate.assert_called_once()

    def test_do_tray_quick_scan_no_action_without_window(self, app, mock_gtk_modules):
        """Test that _do_tray_quick_scan does nothing without active window."""
        app.props = mock.MagicMock()
        app.props.active_window = None

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        app._do_tray_quick_scan()

        # Verify no scan view methods were called
        mock_scan_view.refresh_profiles.assert_not_called()
        mock_scan_view.set_selected_profile.assert_not_called()
        mock_scan_view._start_scan.assert_not_called()

    def test_do_tray_quick_scan_lazy_loads_scan_view(self, app, mock_gtk_modules):
        """Test that _do_tray_quick_scan lazily loads scan view if not created."""
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window
        # With lazy loading, even if _scan_view is None, accessing the property creates it
        app._scan_view = None

        # Mock activate
        app.activate = mock.MagicMock()

        # Mock profile manager to return no quick scan profile
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler - should create scan view via lazy loading
        result = app._do_tray_quick_scan()

        # Verify returns False (don't repeat)
        assert result is False

        # set_content_view should be called since lazy loading creates the view
        mock_window.set_content_view.assert_called_once()

    def test_do_tray_quick_scan_returns_false(self, app, mock_gtk_modules):
        """Test that _do_tray_quick_scan returns False (to prevent GLib.idle_add repeat)."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view

        # Mock profile retrieval
        mock_profile = mock.MagicMock()
        mock_profile.id = "quick-scan-profile-id"
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = mock_profile

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        result = app._do_tray_quick_scan()

        # Verify returns False (to stop GLib.idle_add repetition)
        assert result is False

    def test_on_tray_quick_scan_uses_glib_idle_add(self, app, mock_gtk_modules):
        """Test that _on_tray_quick_scan delegates to _do_tray_quick_scan via GLib.idle_add."""
        # This test verifies the thread-safety mechanism
        mock_glib = mock_gtk_modules["GLib"]

        # Call the handler
        app._on_tray_quick_scan()

        # Verify GLib.idle_add was called with _do_tray_quick_scan
        mock_glib.idle_add.assert_called_once_with(app._do_tray_quick_scan)


class TestClamUIAppQuickScanFallback:
    """Dedicated tests for Quick Scan fallback behavior when profile is not found."""

    def test_statistics_fallback_uses_expanduser_with_tilde(self, app, mock_gtk_modules):
        """Test that statistics quick scan fallback uses os.path.expanduser with '~'."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler and verify expanduser is called with "~"
        with mock.patch("src.app.os.path.expanduser") as mock_expanduser:
            mock_expanduser.return_value = "/home/testuser"
            app._on_statistics_quick_scan()

            # Verify expanduser was called with "~" to get home directory
            mock_expanduser.assert_any_call("~")

    def test_tray_fallback_uses_expanduser_with_tilde(self, app, mock_gtk_modules):
        """Test that tray quick scan fallback uses os.path.expanduser with '~'."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler and verify expanduser is called with "~"
        with mock.patch("src.app.os.path.expanduser") as mock_expanduser:
            mock_expanduser.return_value = "/home/testuser"
            app._do_tray_quick_scan()

            # Verify expanduser was called with "~" to get home directory
            mock_expanduser.assert_any_call("~")

    def test_statistics_fallback_does_not_call_refresh_profiles(self, app, mock_gtk_modules):
        """Test that statistics quick scan fallback does not call refresh_profiles."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler
        app._on_statistics_quick_scan()

        # Verify refresh_profiles was NOT called (only called when profile found)
        mock_scan_view.refresh_profiles.assert_not_called()

    def test_tray_fallback_does_not_call_refresh_profiles(self, app, mock_gtk_modules):
        """Test that tray quick scan fallback does not call refresh_profiles."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        app._do_tray_quick_scan()

        # Verify refresh_profiles was NOT called (only called when profile found)
        mock_scan_view.refresh_profiles.assert_not_called()

    def test_statistics_fallback_logs_warning(self, app, mock_gtk_modules):
        """Test that statistics quick scan fallback logs a warning message."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler and verify logging
        with mock.patch("src.view_coordinator.logger") as mock_logger:
            app._on_statistics_quick_scan()

            # Verify warning was logged about fallback
            mock_logger.warning.assert_called_once()
            warning_call = mock_logger.warning.call_args[0][0]
            assert "Quick Scan profile not found" in warning_call
            assert "falling back" in warning_call.lower()

    def test_tray_fallback_logs_warning(self, app, mock_gtk_modules):
        """Test that tray quick scan fallback logs a warning message."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler and verify logging
        with mock.patch("src.tray_integration.logger") as mock_logger:
            app._do_tray_quick_scan()

            # Verify warning was logged about fallback
            mock_logger.warning.assert_called_once()
            warning_call = mock_logger.warning.call_args[0][0]
            assert "Quick Scan profile not found" in warning_call
            assert "falling back" in warning_call.lower()

    def test_statistics_fallback_still_switches_to_scan_view(self, app, mock_gtk_modules):
        """Test that statistics quick scan fallback still switches to scan view."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler
        app._on_statistics_quick_scan()

        # Verify view switch still happens
        mock_window.set_content_view.assert_called_once_with(mock_scan_view)
        mock_window.set_active_view.assert_called_once_with("scan")
        assert app._current_view == "scan"

    def test_tray_fallback_still_switches_to_scan_view(self, app, mock_gtk_modules):
        """Test that tray quick scan fallback still switches to scan view."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler
        app._do_tray_quick_scan()

        # Verify view switch still happens
        mock_window.set_content_view.assert_called_once_with(mock_scan_view)
        mock_window.set_active_view.assert_called_once_with("scan")
        assert app._current_view == "scan"

    def test_statistics_fallback_path_is_set_correctly(self, app, mock_gtk_modules):
        """Test that statistics quick scan fallback sets the correct home path."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Call the handler with a specific home directory
        with mock.patch("src.app.os.path.expanduser") as mock_expanduser:
            mock_expanduser.return_value = "/home/specific_user"
            app._on_statistics_quick_scan()

            # Verify the expanded path is passed to _set_selected_path
            mock_scan_view._set_selected_path.assert_called_once_with("/home/specific_user")

    def test_tray_fallback_path_is_set_correctly(self, app, mock_gtk_modules):
        """Test that tray quick scan fallback sets the correct home path."""
        # Set up mocks
        mock_window = mock.MagicMock()
        app.props = mock.MagicMock()
        app.props.active_window = mock_window

        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._current_view = "statistics"

        # Mock profile retrieval to return None (trigger fallback)
        app._profile_manager = mock.MagicMock()
        app._profile_manager.get_profile_by_name.return_value = None

        # Mock activate
        app.activate = mock.MagicMock()

        # Call the handler with a specific home directory
        with mock.patch("src.app.os.path.expanduser") as mock_expanduser:
            mock_expanduser.return_value = "/home/specific_user"
            app._do_tray_quick_scan()

            # Verify the expanded path is passed to _set_selected_path
            mock_scan_view._set_selected_path.assert_called_once_with("/home/specific_user")


class TestClamUIAppScanStateTrayUpdates:
    """Regression tests for scan-state-driven tray updates."""

    def test_scan_start_sets_scanning_status_and_clears_progress(self, app):
        """Starting a scan should move tray to scanning state."""
        app._tray_indicator = mock.MagicMock()
        app._notification_dispatcher = mock.MagicMock()

        app._on_scan_state_changed(is_scanning=True, result=None)

        assert app._is_scan_active is True
        app._tray_indicator.update_status.assert_called_once_with("scanning")
        app._tray_indicator.update_scan_progress.assert_called_once_with(0)
        app._notification_dispatcher.show_scan_result_notification.assert_not_called()

    def test_scan_complete_clean_sets_protected_and_notifies(self, app):
        """Clean completion should set protected tray state and notify."""
        app._tray_indicator = mock.MagicMock()
        app._notification_dispatcher = mock.MagicMock()
        result = mock.MagicMock()
        result.has_threats = False
        result.is_clean = True

        app._on_scan_state_changed(is_scanning=False, result=result)

        assert app._is_scan_active is False
        app._tray_indicator.update_scan_progress.assert_called_once_with(0)
        app._tray_indicator.update_status.assert_called_once_with("protected")
        app._notification_dispatcher.show_scan_result_notification.assert_called_once_with(result)

    def test_scan_complete_threat_sets_threat_status(self, app):
        """Threat completion should set tray to threat state."""
        app._tray_indicator = mock.MagicMock()
        app._notification_dispatcher = mock.MagicMock()
        result = mock.MagicMock()
        result.has_threats = True
        result.is_clean = False

        app._on_scan_state_changed(is_scanning=False, result=result)

        app._tray_indicator.update_scan_progress.assert_called_once_with(0)
        app._tray_indicator.update_status.assert_called_once_with("threat")


class TestAppLifecycleDatabaseDir:
    """Regression tests for AppLifecycleManager database directory creation."""

    def test_ensure_db_dir_does_not_raise_when_fallback_also_fails(self, app):
        """If both the XDG dir and the /var/lib/clamav fallback fail, startup must
        not crash — ensure_clamav_database_dir should swallow the fallback OSError.
        """
        from pathlib import Path

        with mock.patch.object(Path, "mkdir", side_effect=OSError("permission denied")):
            # Must not raise; a normal user cannot create /var/lib/clamav, and an
            # unhandled OSError here propagates out of do_startup and aborts launch.
            app._lifecycle_manager.ensure_clamav_database_dir()


class TestClamUIAppVirusTotalScan:
    """Regression tests for the VirusTotal scan completion flow."""

    def test_trigger_virustotal_scan_logs_and_shows_dialog(self, app, mock_gtk_modules):
        """After a VT scan completes the result is logged via the real LogEntry/
        save_log API and the results dialog is shown.

        Regression: on_scan_complete called LogManager.add_virustotal_result (a
        method that does not exist), raising AttributeError that the surrounding
        try/except swallowed, so the results dialog (then inside the same try)
        never appeared after a VirusTotal scan. autospec=True makes the mocked
        LogManager enforce the real interface, so the old call would still raise.
        """
        from types import SimpleNamespace

        glib = mock_gtk_modules["GLib"]
        glib.idle_add.side_effect = lambda fn, *a: fn(*a)

        result = SimpleNamespace(
            status=SimpleNamespace(value="clean"),
            file_path="/tmp/sample",
            duration=1.0,
            sha256="abc123",
            detections=0,
            total_engines=70,
            detection_details=[],
            permalink="https://vt/sample",
            error_message=None,
        )

        fake_client = mock.MagicMock()
        fake_client.scan_file_sync.return_value = result

        app._show_virustotal_results_dialog = mock.MagicMock()

        def fake_thread(target=None, daemon=None):
            runner = mock.MagicMock()
            runner.start.side_effect = target
            return runner

        with (
            mock.patch("threading.Thread", side_effect=fake_thread),
            mock.patch("src.core.virustotal.VirusTotalClient", return_value=fake_client),
            mock.patch("src.core.log_manager.LogManager", autospec=True) as mock_lm,
        ):
            app._trigger_virustotal_scan("/tmp/sample", "api-key")

        # The results dialog must be shown (the bug skipped this entirely).
        app._show_virustotal_results_dialog.assert_called_once_with(result)
        # The result is persisted via the real save_log API, not add_virustotal_result.
        mock_lm.return_value.save_log.assert_called_once()

    def test_show_virustotal_results_dialog_uses_correct_constructor(self, app):
        """_show_virustotal_results_dialog passes the result as vt_result and sets
        the parent separately.

        Regression: it called VirusTotalResultsDialog(win, result), but the dialog's
        first argument is vt_result (not the parent) and it accepts only one
        positional arg -> TypeError once the dialog was actually reached (which the
        add_virustotal_result bug had been masking).
        """
        result = mock.MagicMock()
        app.props.active_window = mock.MagicMock()

        captured = {}

        class FakeDialog:
            def __init__(self, vt_result, **kwargs):
                captured["vt_result"] = vt_result

            def set_transient_for(self, win):
                captured["parent"] = win

            def present(self):
                captured["presented"] = True

        with mock.patch("src.ui.virustotal_results_dialog.VirusTotalResultsDialog", FakeDialog):
            app._show_virustotal_results_dialog(result)

        assert captured.get("vt_result") is result
        assert captured.get("parent") is app.props.active_window
        assert captured.get("presented") is True


class TestClamUIAppInitialScanPaths:
    """Regression tests for forwarding CLI-provided scan targets to the UI."""

    def test_multiple_clamav_paths_populate_all_targets(self, app):
        """All CLI paths must be forwarded to the scan view, not just the first.

        Regression: _process_initial_scan_paths called _set_selected_path(paths[0]),
        so launching ClamUI from a file manager with N selected files only scanned
        the first one ("Scan Target (1)" despite "Received N path(s)").
        """
        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._initial_scan_paths = ["/tmp/a.pdf", "/tmp/b.pdf"]
        app._initial_use_virustotal = False

        app._process_initial_scan_paths()

        mock_scan_view._replace_selected_paths.assert_called_once_with(["/tmp/a.pdf", "/tmp/b.pdf"])
        mock_scan_view._start_scan.assert_called_once_with()
        mock_scan_view._set_selected_path.assert_not_called()
        # State is consumed so a later activate() does not re-trigger the scan.
        assert app._initial_scan_paths == []
        assert app._initial_use_virustotal is False

    def test_single_clamav_path_uses_multi_target_api(self, app):
        """A single CLI path still goes through the multi-target replace API."""
        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._initial_scan_paths = ["/tmp/only.pdf"]
        app._initial_use_virustotal = False

        app._process_initial_scan_paths()

        mock_scan_view._replace_selected_paths.assert_called_once_with(["/tmp/only.pdf"])
        mock_scan_view._start_scan.assert_called_once_with()

    def test_virustotal_path_uses_first_only(self, app):
        """VirusTotal scans a single file per request, so only the first path is
        forwarded to the setup dialog and the ClamAV auto-scan is not started."""
        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._initial_scan_paths = ["/tmp/a.pdf", "/tmp/b.pdf"]
        app._initial_use_virustotal = True
        app._show_virustotal_setup_dialog = mock.MagicMock()

        app._process_initial_scan_paths()

        mock_scan_view._set_selected_path.assert_called_once_with("/tmp/a.pdf")
        app._show_virustotal_setup_dialog.assert_called_once_with("/tmp/a.pdf")
        mock_scan_view._replace_selected_paths.assert_not_called()
        mock_scan_view._start_scan.assert_not_called()

    def test_no_paths_is_noop(self, app):
        """With no pending paths nothing is forwarded to the scan view."""
        mock_scan_view = mock.MagicMock()
        app._scan_view = mock_scan_view
        app._initial_scan_paths = []

        app._process_initial_scan_paths()

        mock_scan_view._replace_selected_paths.assert_not_called()
        mock_scan_view._set_selected_path.assert_not_called()
        mock_scan_view._start_scan.assert_not_called()
