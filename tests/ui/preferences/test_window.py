# ClamUI PreferencesWindow Integration Tests
"""Integration tests for the PreferencesWindow class."""

from unittest import mock

import pytest


class TestPreferencesWindowImport:
    """Tests for importing the PreferencesWindow."""

    def test_import_preferences_window(self, mock_gi_modules):
        """Test that PreferencesWindow can be imported."""
        from src.ui.preferences.window import PreferencesWindow

        assert PreferencesWindow is not None

    def test_preferences_window_is_class(self, mock_gi_modules):
        """Test that PreferencesWindow is a class."""
        from src.ui.preferences.window import PreferencesWindow

        assert isinstance(PreferencesWindow, type)

    def test_preferences_window_inherits_from_adw_window(self, mock_gi_modules):
        """Test that PreferencesWindow inherits from Adw.Window."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.window import PreferencesWindow

        # Check inheritance from Adw.Window (not Adw.PreferencesWindow)
        assert issubclass(PreferencesWindow, adw.Window)

    def test_preferences_window_inherits_from_mixin(self, mock_gi_modules):
        """Test that PreferencesWindow inherits from PreferencesPageMixin."""
        from src.ui.preferences.base import PreferencesPageMixin
        from src.ui.preferences.window import PreferencesWindow

        assert issubclass(PreferencesWindow, PreferencesPageMixin)


class TestPreferencesWindowInitialization:
    """Tests for PreferencesWindow initialization."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get_setting.return_value = None
        return manager

    @pytest.fixture
    def mock_parse_config(self):
        """Mock parse_config function."""
        with mock.patch("src.ui.preferences.window.parse_config") as mock_func:
            mock_func.return_value = ({}, None)
            yield mock_func

    @pytest.fixture
    def mock_path_exists(self):
        """Mock config_file_exists to control clamd availability."""
        with mock.patch("src.ui.preferences.window.config_file_exists") as mock_exists:
            mock_exists.return_value = True
            yield mock_exists

    @pytest.fixture
    def mock_scheduler(self):
        """Mock Scheduler class."""
        with mock.patch("src.ui.preferences.window.Scheduler") as mock_sched:
            yield mock_sched

    @pytest.fixture
    def mock_page_modules(self):
        """Mock all page modules."""
        with (
            mock.patch("src.ui.preferences.window.DatabasePage") as mock_db,
            mock.patch("src.ui.preferences.window.ScannerPage") as mock_scanner,
            mock.patch("src.ui.preferences.window.OnAccessPage") as mock_onaccess,
            mock.patch("src.ui.preferences.window.ScheduledPage") as mock_scheduled,
            mock.patch("src.ui.preferences.window.ExclusionsPage") as mock_exclusions,
            mock.patch("src.ui.preferences.window.SavePage") as mock_save,
            mock.patch("src.ui.preferences.window.VirusTotalPage") as mock_vt,
            mock.patch("src.ui.preferences.window.BehaviorPage") as mock_behavior,
            mock.patch("src.ui.preferences.window.DebugPage") as mock_debug,
        ):
            # Configure static page mocks to return page objects
            mock_db.create_page.return_value = mock.MagicMock()
            mock_scanner.create_page.return_value = mock.MagicMock()
            mock_onaccess.create_page.return_value = mock.MagicMock()
            mock_scheduled.create_page.return_value = mock.MagicMock()
            mock_vt.create_page.return_value = mock.MagicMock()

            # Configure instance-based page mocks
            mock_exclusions_instance = mock.MagicMock()
            mock_exclusions_instance.create_page.return_value = mock.MagicMock()
            mock_exclusions.return_value = mock_exclusions_instance

            mock_save_instance = mock.MagicMock()
            mock_save_instance.create_page.return_value = mock.MagicMock()
            mock_save.return_value = mock_save_instance

            mock_behavior_instance = mock.MagicMock()
            mock_behavior_instance.create_page.return_value = mock.MagicMock()
            mock_behavior.return_value = mock_behavior_instance

            mock_debug_instance = mock.MagicMock()
            mock_debug_instance.create_page.return_value = mock.MagicMock()
            mock_debug.return_value = mock_debug_instance

            # Configure populate_fields as no-op
            mock_db.populate_fields = mock.MagicMock()
            mock_scanner.populate_fields = mock.MagicMock()
            mock_onaccess.populate_fields = mock.MagicMock()
            mock_scheduled.populate_fields = mock.MagicMock()

            yield {
                "database": mock_db,
                "scanner": mock_scanner,
                "onaccess": mock_onaccess,
                "scheduled": mock_scheduled,
                "exclusions": mock_exclusions,
                "save": mock_save,
                "virustotal": mock_vt,
                "behavior": mock_behavior,
                "debug": mock_debug,
            }

    def test_initialization_calls_setup_ui(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that initialization calls _setup_ui.

        The background config-load thread is stubbed so __init__ stays
        synchronous and deterministic (GLib.idle_add is already a no-op
        under mock_gi_modules, so the applier never runs automatically).
        """
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "_setup_ui") as mock_setup:
            with mock.patch("src.ui.preferences.window.threading.Thread"):
                with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                    PreferencesWindow()
                    mock_setup.assert_called_once()

    def test_initialization_starts_config_load_thread(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that __init__ spawns a daemon thread running the config resolver.

        _load_configs was removed (U2): host I/O now runs on a daemon
        thread whose target is _resolve_config_paths_background, with
        results marshalled back via GLib.idle_add(_apply_loaded_configs).
        """
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "_setup_ui"):
            with mock.patch("src.ui.preferences.window.threading.Thread") as mock_thread:
                mock_thread_instance = mock.MagicMock()
                mock_thread.return_value = mock_thread_instance
                with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                    PreferencesWindow()

                    mock_thread.assert_called_once()
                    call_kwargs = mock_thread.call_args.kwargs
                    assert call_kwargs.get("daemon") is True
                    assert call_kwargs.get("target").__name__ == "_resolve_config_paths_background"
                    mock_thread_instance.start.assert_called_once()

    def test_initialization_with_settings_manager(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
        mock_settings_manager,
    ):
        """Test that settings_manager is stored when provided."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "_setup_ui"):
            with mock.patch("src.ui.preferences.window.threading.Thread"):
                with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                    window = PreferencesWindow(settings_manager=mock_settings_manager)
                    assert window._settings_manager == mock_settings_manager


class TestNavigationItems:
    """Tests for navigation sidebar items."""

    def test_navigation_items_defined(self, mock_gi_modules):
        """Test that NAVIGATION_ITEMS is defined with correct structure."""
        from src.ui.preferences.window import NAVIGATION_ITEMS

        assert isinstance(NAVIGATION_ITEMS, (list, tuple))
        assert (
            len(NAVIGATION_ITEMS) == 10
        )  # behavior, exclusions, database, scanner, scheduled, device_scan, onaccess, virustotal, debug, save

        # Check structure of each item
        for item in NAVIGATION_ITEMS:
            assert len(item) == 3
            page_id, icon_name, label = item
            assert isinstance(page_id, str)
            assert isinstance(icon_name, str)
            assert isinstance(label, str)
            assert icon_name.endswith("-symbolic")

    def test_navigation_items_contain_required_pages(self, mock_gi_modules):
        """Test that all required page IDs are in NAVIGATION_ITEMS."""
        from src.ui.preferences.window import NAVIGATION_ITEMS

        page_ids = [item[0] for item in NAVIGATION_ITEMS]

        required_pages = [
            "behavior",
            "exclusions",
            "database",
            "scanner",
            "scheduled",
            "onaccess",
            "virustotal",
            "debug",
            "save",
        ]

        for page in required_pages:
            assert page in page_ids, f"Missing required page: {page}"


class TestPreferencesSidebarRow:
    """Tests for PreferencesSidebarRow class."""

    def test_sidebar_row_import(self, mock_gi_modules):
        """Test that PreferencesSidebarRow can be imported."""
        from src.ui.preferences.window import PreferencesSidebarRow

        assert PreferencesSidebarRow is not None

    def test_sidebar_row_is_class(self, mock_gi_modules):
        """Test that PreferencesSidebarRow is a class."""
        from src.ui.preferences.window import PreferencesSidebarRow

        assert isinstance(PreferencesSidebarRow, type)

    def test_sidebar_row_inherits_from_listbox_row(self, mock_gi_modules):
        """Test that PreferencesSidebarRow inherits from Gtk.ListBoxRow."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.window import PreferencesSidebarRow

        assert issubclass(PreferencesSidebarRow, gtk.ListBoxRow)

    def test_sidebar_row_page_id_property(self, mock_gi_modules):
        """Test that PreferencesSidebarRow stores page_id."""
        from src.ui.preferences.window import PreferencesSidebarRow

        row = PreferencesSidebarRow("test_page", "folder-symbolic", "Test Label")
        assert row.page_id == "test_page"


class TestPreferencesWindowMethods:
    """Tests for PreferencesWindow methods."""

    @pytest.fixture
    def mock_page_modules(self):
        """Mock all page modules."""
        with (
            mock.patch("src.ui.preferences.window.DatabasePage") as mock_db,
            mock.patch("src.ui.preferences.window.ScannerPage") as mock_scanner,
            mock.patch("src.ui.preferences.window.OnAccessPage") as mock_onaccess,
            mock.patch("src.ui.preferences.window.ScheduledPage") as mock_scheduled,
            mock.patch("src.ui.preferences.window.ExclusionsPage") as mock_exclusions,
            mock.patch("src.ui.preferences.window.SavePage") as mock_save,
            mock.patch("src.ui.preferences.window.VirusTotalPage") as mock_vt,
            mock.patch("src.ui.preferences.window.BehaviorPage") as mock_behavior,
            mock.patch("src.ui.preferences.window.DebugPage") as mock_debug,
        ):
            # Configure static page mocks
            mock_db.create_page.return_value = mock.MagicMock()
            mock_scanner.create_page.return_value = mock.MagicMock()
            mock_onaccess.create_page.return_value = mock.MagicMock()
            mock_scheduled.create_page.return_value = mock.MagicMock()
            mock_vt.create_page.return_value = mock.MagicMock()

            # Configure instance-based page mocks
            for mock_class in [mock_exclusions, mock_save, mock_behavior, mock_debug]:
                instance = mock.MagicMock()
                instance.create_page.return_value = mock.MagicMock()
                mock_class.return_value = instance

            # Configure populate_fields
            mock_db.populate_fields = mock.MagicMock()
            mock_scanner.populate_fields = mock.MagicMock()
            mock_onaccess.populate_fields = mock.MagicMock()
            mock_scheduled.populate_fields = mock.MagicMock()

            yield

    @pytest.fixture
    def mock_scheduler(self):
        """Mock Scheduler class."""
        with mock.patch("src.ui.preferences.window.Scheduler") as mock_sched:
            yield mock_sched

    @pytest.fixture
    def mock_parse_config(self):
        """Mock parse_config function."""
        with mock.patch("src.ui.preferences.window.parse_config") as mock_func:
            mock_func.return_value = ({}, None)
            yield mock_func

    @pytest.fixture
    def mock_path_exists(self):
        """Mock config_file_exists."""
        with mock.patch("src.ui.preferences.window.config_file_exists") as mock_exists:
            mock_exists.return_value = True
            yield mock_exists

    def test_get_page_label_returns_label(self, mock_gi_modules):
        """Test _get_page_label returns the correct label."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "__init__", lambda x: None):
            window = PreferencesWindow.__new__(PreferencesWindow)
            label = window._get_page_label("database")
            assert label == "Database"

    def test_get_page_label_fallback(self, mock_gi_modules):
        """Test _get_page_label returns capitalized ID for unknown pages."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "__init__", lambda x: None):
            window = PreferencesWindow.__new__(PreferencesWindow)
            label = window._get_page_label("unknown_page")
            assert label == "Unknown_page"

    def test_add_toast_method_exists(self, mock_gi_modules):
        """Test that add_toast method exists."""
        from src.ui.preferences.window import PreferencesWindow

        assert hasattr(PreferencesWindow, "add_toast")

    def test_select_page_method_exists(self, mock_gi_modules):
        """Test that select_page method exists."""
        from src.ui.preferences.window import PreferencesWindow

        assert hasattr(PreferencesWindow, "select_page")


class TestPreferencesWindowProperties:
    """Tests for PreferencesWindow properties and attributes."""

    @pytest.fixture
    def mock_page_modules(self):
        """Mock all page modules."""
        with (
            mock.patch("src.ui.preferences.window.DatabasePage") as mock_db,
            mock.patch("src.ui.preferences.window.ScannerPage") as mock_scanner,
            mock.patch("src.ui.preferences.window.OnAccessPage") as mock_onaccess,
            mock.patch("src.ui.preferences.window.ScheduledPage") as mock_scheduled,
            mock.patch("src.ui.preferences.window.ExclusionsPage") as mock_exclusions,
            mock.patch("src.ui.preferences.window.SavePage") as mock_save,
            mock.patch("src.ui.preferences.window.VirusTotalPage") as mock_vt,
            mock.patch("src.ui.preferences.window.BehaviorPage") as mock_behavior,
            mock.patch("src.ui.preferences.window.DebugPage") as mock_debug,
        ):
            # Configure static page mocks
            mock_db.create_page.return_value = mock.MagicMock()
            mock_scanner.create_page.return_value = mock.MagicMock()
            mock_onaccess.create_page.return_value = mock.MagicMock()
            mock_scheduled.create_page.return_value = mock.MagicMock()
            mock_vt.create_page.return_value = mock.MagicMock()

            # Configure instance-based page mocks
            for mock_class in [mock_exclusions, mock_save, mock_behavior, mock_debug]:
                instance = mock.MagicMock()
                instance.create_page.return_value = mock.MagicMock()
                mock_class.return_value = instance

            # Configure populate_fields
            mock_db.populate_fields = mock.MagicMock()
            mock_scanner.populate_fields = mock.MagicMock()
            mock_onaccess.populate_fields = mock.MagicMock()
            mock_scheduled.populate_fields = mock.MagicMock()

            yield

    @pytest.fixture
    def mock_scheduler(self):
        """Mock Scheduler class."""
        with mock.patch("src.ui.preferences.window.Scheduler") as mock_sched:
            yield mock_sched

    @pytest.fixture
    def mock_parse_config(self):
        """Mock parse_config function."""
        with mock.patch("src.ui.preferences.window.parse_config") as mock_func:
            mock_func.return_value = ({}, None)
            yield mock_func

    @pytest.fixture
    def mock_path_exists(self):
        """Mock config_file_exists."""
        with mock.patch("src.ui.preferences.window.config_file_exists") as mock_exists:
            mock_exists.return_value = True
            yield mock_exists

    def test_window_has_widget_dictionaries(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that window initializes widget dictionaries."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "_setup_ui"):
            with mock.patch("src.ui.preferences.window.threading.Thread"):
                with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                    window = PreferencesWindow()
                    assert hasattr(window, "_freshclam_widgets")
                    assert hasattr(window, "_clamd_widgets")
                    assert hasattr(window, "_scheduled_widgets")
                    assert hasattr(window, "_onaccess_widgets")
                    assert isinstance(window._freshclam_widgets, dict)
                    assert isinstance(window._clamd_widgets, dict)

    def test_window_has_sidebar_attributes(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that window has sidebar-related attributes."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "_setup_ui"):
            with mock.patch("src.ui.preferences.window.threading.Thread"):
                with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                    window = PreferencesWindow()
                    assert hasattr(window, "_sidebar_rows")
                    assert isinstance(window._sidebar_rows, dict)


class TestConfigLoading:
    """Tests for configuration loading."""

    @pytest.fixture
    def mock_page_modules(self):
        """Mock all page modules."""
        with (
            mock.patch("src.ui.preferences.window.DatabasePage") as mock_db,
            mock.patch("src.ui.preferences.window.ScannerPage") as mock_scanner,
            mock.patch("src.ui.preferences.window.OnAccessPage") as mock_onaccess,
            mock.patch("src.ui.preferences.window.ScheduledPage") as mock_scheduled,
            mock.patch("src.ui.preferences.window.ExclusionsPage") as mock_exclusions,
            mock.patch("src.ui.preferences.window.SavePage") as mock_save,
            mock.patch("src.ui.preferences.window.VirusTotalPage") as mock_vt,
            mock.patch("src.ui.preferences.window.BehaviorPage") as mock_behavior,
            mock.patch("src.ui.preferences.window.DebugPage") as mock_debug,
        ):
            # Configure static page mocks
            mock_db.create_page.return_value = mock.MagicMock()
            mock_scanner.create_page.return_value = mock.MagicMock()
            mock_onaccess.create_page.return_value = mock.MagicMock()
            mock_scheduled.create_page.return_value = mock.MagicMock()
            mock_vt.create_page.return_value = mock.MagicMock()

            # Configure instance-based page mocks
            for mock_class in [mock_exclusions, mock_save, mock_behavior, mock_debug]:
                instance = mock.MagicMock()
                instance.create_page.return_value = mock.MagicMock()
                mock_class.return_value = instance

            # Configure populate_fields
            mock_db.populate_fields = mock.MagicMock()
            mock_scanner.populate_fields = mock.MagicMock()
            mock_onaccess.populate_fields = mock.MagicMock()
            mock_scheduled.populate_fields = mock.MagicMock()

            yield {
                "database": mock_db,
                "scanner": mock_scanner,
                "onaccess": mock_onaccess,
                "scheduled": mock_scheduled,
            }

    @pytest.fixture
    def mock_scheduler(self):
        """Mock Scheduler class."""
        with mock.patch("src.ui.preferences.window.Scheduler") as mock_sched:
            yield mock_sched

    @pytest.fixture
    def mock_path_exists(self):
        """Mock config_file_exists."""
        with mock.patch("src.ui.preferences.window.config_file_exists") as mock_exists:
            mock_exists.return_value = True
            yield mock_exists

    def test_load_configs_parses_freshclam(
        self,
        mock_gi_modules,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that _load_configs_io parses freshclam.conf.

        Config parsing was split out of the removed sync _load_configs
        into the worker-thread method _load_configs_io (U2). Drive it
        directly with the thread suppressed so the parse is deterministic.
        """
        from src.ui.preferences.window import PreferencesWindow

        mock_config = mock.MagicMock()
        mock_config.values = {"key": "value"}

        with mock.patch("src.ui.preferences.window.parse_config", return_value=(mock_config, None)):
            with mock.patch.object(PreferencesWindow, "_setup_ui"):
                with mock.patch("src.ui.preferences.window.threading.Thread"):
                    with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                        window = PreferencesWindow()
                        # Simulate the worker thread completing its I/O step.
                        window._load_configs_io()
                        assert window._freshclam_config == mock_config

    def test_load_configs_handles_error(
        self,
        mock_gi_modules,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that _load_configs_io records parse errors without raising.

        _load_configs_io stores the error in _freshclam_load_error for the
        main-thread applier (_apply_loaded_configs) to surface via toast;
        it must not raise on the worker thread.
        """
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch(
            "src.ui.preferences.window.parse_config",
            return_value=(None, "Parse error"),
        ):
            with mock.patch.object(PreferencesWindow, "_setup_ui"):
                with mock.patch("src.ui.preferences.window.threading.Thread"):
                    with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                        # Should not raise
                        window = PreferencesWindow()
                        window._load_configs_io()
                        assert window._freshclam_load_error == "Parse error"


class TestFlatpakSupport:
    """Tests for Flatpak-specific functionality."""

    @pytest.fixture
    def mock_page_modules(self):
        """Mock all page modules."""
        with (
            mock.patch("src.ui.preferences.window.DatabasePage") as mock_db,
            mock.patch("src.ui.preferences.window.ScannerPage") as mock_scanner,
            mock.patch("src.ui.preferences.window.OnAccessPage") as mock_onaccess,
            mock.patch("src.ui.preferences.window.ScheduledPage") as mock_scheduled,
            mock.patch("src.ui.preferences.window.ExclusionsPage") as mock_exclusions,
            mock.patch("src.ui.preferences.window.SavePage") as mock_save,
            mock.patch("src.ui.preferences.window.VirusTotalPage") as mock_vt,
            mock.patch("src.ui.preferences.window.BehaviorPage") as mock_behavior,
            mock.patch("src.ui.preferences.window.DebugPage") as mock_debug,
        ):
            # Configure static page mocks
            mock_db.create_page.return_value = mock.MagicMock()
            mock_scanner.create_page.return_value = mock.MagicMock()
            mock_onaccess.create_page.return_value = mock.MagicMock()
            mock_scheduled.create_page.return_value = mock.MagicMock()
            mock_vt.create_page.return_value = mock.MagicMock()

            # Configure instance-based page mocks
            for mock_class in [mock_exclusions, mock_save, mock_behavior, mock_debug]:
                instance = mock.MagicMock()
                instance.create_page.return_value = mock.MagicMock()
                mock_class.return_value = instance

            # Configure populate_fields
            mock_db.populate_fields = mock.MagicMock()
            mock_scanner.populate_fields = mock.MagicMock()
            mock_onaccess.populate_fields = mock.MagicMock()
            mock_scheduled.populate_fields = mock.MagicMock()

            yield

    @pytest.fixture
    def mock_scheduler(self):
        """Mock Scheduler class."""
        with mock.patch("src.ui.preferences.window.Scheduler") as mock_sched:
            yield mock_sched

    @pytest.fixture
    def mock_parse_config(self):
        """Mock parse_config function."""
        with mock.patch("src.ui.preferences.window.parse_config") as mock_func:
            mock_func.return_value = ({}, None)
            yield mock_func

    @pytest.fixture
    def mock_path_exists(self):
        """Mock config_file_exists."""
        with mock.patch("src.ui.preferences.window.config_file_exists") as mock_exists:
            mock_exists.return_value = True
            yield mock_exists

    def test_non_flatpak_uses_system_paths(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that non-Flatpak installation uses system config paths.

        Path resolution moved off __init__ into _resolve_config_paths_background
        (U2). Drive it explicitly (thread suppressed) and assert the resolved
        paths; parse_config/config_file_exists are mocked by the fixtures.
        """
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch("src.ui.preferences.window.is_flatpak", return_value=False):
            with mock.patch.object(PreferencesWindow, "_setup_ui"):
                with mock.patch("src.ui.preferences.window.threading.Thread"):
                    with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                        window = PreferencesWindow()
                        window._resolve_config_paths_background()
                        assert window._freshclam_conf_path == "/etc/clamav/freshclam.conf"
                        assert window._clamd_conf_path == "/etc/clamav/clamd.conf"

    def test_flatpak_prefers_saved_or_detected_host_freshclam_path(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Flatpak preferences should honor the persisted host freshclam.conf path."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch("src.ui.preferences.window.is_flatpak", return_value=True):
            with mock.patch(
                "src.ui.preferences.window.resolve_freshclam_conf_path",
                return_value="/etc/clamav/freshclam.conf",
            ):
                with mock.patch.object(PreferencesWindow, "_setup_ui"):
                    with mock.patch("src.ui.preferences.window.threading.Thread"):
                        with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                            window = PreferencesWindow()
                            window._resolve_config_paths_background()
                            assert window._freshclam_conf_path == "/etc/clamav/freshclam.conf"

    def test_flatpak_falls_back_to_host_freshclam_default(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test Flatpak uses host default when no freshclam config is found."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch("src.ui.preferences.window.is_flatpak", return_value=True):
            with mock.patch(
                "src.ui.preferences.window.resolve_freshclam_conf_path", return_value=None
            ):
                with mock.patch.object(PreferencesWindow, "_setup_ui"):
                    with mock.patch("src.ui.preferences.window.threading.Thread"):
                        with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                            window = PreferencesWindow()
                            window._resolve_config_paths_background()
                            assert window._freshclam_conf_path == "/etc/clamav/freshclam.conf"


class TestClamdAvailability:
    """Tests for clamd.conf availability detection."""

    @pytest.fixture
    def mock_page_modules(self):
        """Mock all page modules."""
        with (
            mock.patch("src.ui.preferences.window.DatabasePage") as mock_db,
            mock.patch("src.ui.preferences.window.ScannerPage") as mock_scanner,
            mock.patch("src.ui.preferences.window.OnAccessPage") as mock_onaccess,
            mock.patch("src.ui.preferences.window.ScheduledPage") as mock_scheduled,
            mock.patch("src.ui.preferences.window.ExclusionsPage") as mock_exclusions,
            mock.patch("src.ui.preferences.window.SavePage") as mock_save,
            mock.patch("src.ui.preferences.window.VirusTotalPage") as mock_vt,
            mock.patch("src.ui.preferences.window.BehaviorPage") as mock_behavior,
            mock.patch("src.ui.preferences.window.DebugPage") as mock_debug,
        ):
            # Configure static page mocks
            mock_db.create_page.return_value = mock.MagicMock()
            mock_scanner.create_page.return_value = mock.MagicMock()
            mock_onaccess.create_page.return_value = mock.MagicMock()
            mock_scheduled.create_page.return_value = mock.MagicMock()
            mock_vt.create_page.return_value = mock.MagicMock()

            # Configure instance-based page mocks
            for mock_class in [mock_exclusions, mock_save, mock_behavior, mock_debug]:
                instance = mock.MagicMock()
                instance.create_page.return_value = mock.MagicMock()
                mock_class.return_value = instance

            # Configure populate_fields
            mock_db.populate_fields = mock.MagicMock()
            mock_scanner.populate_fields = mock.MagicMock()
            mock_onaccess.populate_fields = mock.MagicMock()
            mock_scheduled.populate_fields = mock.MagicMock()

            yield

    @pytest.fixture
    def mock_scheduler(self):
        """Mock Scheduler class."""
        with mock.patch("src.ui.preferences.window.Scheduler") as mock_sched:
            yield mock_sched

    @pytest.fixture
    def mock_parse_config(self):
        """Mock parse_config function."""
        with mock.patch("src.ui.preferences.window.parse_config") as mock_func:
            mock_func.return_value = ({}, None)
            yield mock_func

    def test_clamd_available_when_file_exists(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test clamd is marked available when clamd.conf exists.

        Availability is now resolved in _resolve_config_paths_background (U2);
        drive it explicitly (thread suppressed) and assert the flag flips.
        """
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch("src.ui.preferences.window.is_flatpak", return_value=False):
            with mock.patch("src.ui.preferences.window.config_file_exists", return_value=True):
                with mock.patch.object(PreferencesWindow, "_setup_ui"):
                    with mock.patch("src.ui.preferences.window.threading.Thread"):
                        with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                            window = PreferencesWindow()
                            window._resolve_config_paths_background()
                            assert window._clamd_available is True

    def test_clamd_unavailable_when_file_missing(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test clamd is marked unavailable when clamd.conf doesn't exist."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch("src.ui.preferences.window.is_flatpak", return_value=False):
            with mock.patch("src.ui.preferences.window.config_file_exists", return_value=False):
                with mock.patch.object(PreferencesWindow, "_setup_ui"):
                    with mock.patch("src.ui.preferences.window.threading.Thread"):
                        with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                            window = PreferencesWindow()
                            window._resolve_config_paths_background()
                            assert window._clamd_available is False

    def test_flatpak_clamd_available_via_host_check(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test clamd is available in Flatpak when host config exists.

        Regression test: Previously used Path.exists() which checked the
        Flatpak sandbox filesystem where /etc/clamd.d/scan.conf doesn't
        exist. Now uses config_file_exists() which checks the HOST via
        flatpak-spawn. Path resolution + availability now run in
        _resolve_config_paths_background (U2); drive it explicitly.
        """
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch("src.ui.preferences.window.is_flatpak", return_value=True):
            with mock.patch(
                "src.ui.preferences.window.resolve_clamd_conf_path",
                return_value="/etc/clamd.d/scan.conf",
            ):
                with mock.patch(
                    "src.ui.preferences.window.config_file_exists", return_value=True
                ) as mock_exists:
                    with mock.patch(
                        "src.ui.preferences.window.resolve_freshclam_conf_path",
                        return_value="/etc/freshclam.conf",
                    ):
                        with mock.patch.object(PreferencesWindow, "_setup_ui"):
                            with mock.patch("src.ui.preferences.window.threading.Thread"):
                                with mock.patch.object(
                                    PreferencesWindow, "_populate_scheduled_fields"
                                ):
                                    window = PreferencesWindow()
                                    window._resolve_config_paths_background()
                                    assert window._clamd_available is True
                                    assert window._clamd_conf_path == "/etc/clamd.d/scan.conf"
                                    # Verify host-aware check was used
                                    mock_exists.assert_called_with("/etc/clamd.d/scan.conf")

    def test_flatpak_clamd_unavailable_when_host_config_missing(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test clamd is unavailable in Flatpak when host config missing."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch("src.ui.preferences.window.is_flatpak", return_value=True):
            with mock.patch("src.ui.preferences.window.resolve_clamd_conf_path", return_value=None):
                with mock.patch("src.ui.preferences.window.config_file_exists", return_value=False):
                    with mock.patch(
                        "src.ui.preferences.window.resolve_freshclam_conf_path",
                        return_value="/etc/freshclam.conf",
                    ):
                        with mock.patch.object(PreferencesWindow, "_setup_ui"):
                            with mock.patch("src.ui.preferences.window.threading.Thread"):
                                with mock.patch.object(
                                    PreferencesWindow, "_populate_scheduled_fields"
                                ):
                                    window = PreferencesWindow()
                                    window._resolve_config_paths_background()
                                    assert window._clamd_available is False

    def test_availability_uses_config_file_exists_not_path_exists(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that availability check uses config_file_exists (host-aware).

        Core regression test: verifies Path.exists() is NOT used for the
        clamd availability check. config_file_exists() uses flatpak-spawn
        in Flatpak mode to check the host filesystem. Resolution now runs
        in _resolve_config_paths_background (U2); drive it explicitly.
        """
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch("src.ui.preferences.window.is_flatpak", return_value=False):
            with mock.patch(
                "src.ui.preferences.window.resolve_clamd_conf_path",
                return_value="/etc/clamav/clamd.conf",
            ):
                with mock.patch(
                    "src.ui.preferences.window.config_file_exists", return_value=True
                ) as mock_cfe:
                    with mock.patch.object(PreferencesWindow, "_setup_ui"):
                        with mock.patch("src.ui.preferences.window.threading.Thread"):
                            with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                                window = PreferencesWindow()
                                window._resolve_config_paths_background()
                                assert window._clamd_available is True
                                # config_file_exists must be called for the
                                # availability check (not Path.exists)
                                mock_cfe.assert_called_with("/etc/clamav/clamd.conf")


class TestLazyPageCreation:
    """Tests for lazy preference page creation.

    Pages should be created on-demand when navigated to, not all at once
    during window initialization. Only the default page (behavior) should
    be created eagerly.
    """

    @pytest.fixture
    def mock_parse_config(self):
        """Mock parse_config function."""
        with mock.patch("src.ui.preferences.window.parse_config") as mock_func:
            mock_func.return_value = ({}, None)
            yield mock_func

    @pytest.fixture
    def mock_path_exists(self):
        """Mock config_file_exists to control clamd availability."""
        with mock.patch("src.ui.preferences.window.config_file_exists") as mock_exists:
            mock_exists.return_value = True
            yield mock_exists

    @pytest.fixture
    def mock_scheduler(self):
        """Mock Scheduler class."""
        with mock.patch("src.ui.preferences.window.Scheduler") as mock_sched:
            yield mock_sched

    @pytest.fixture
    def mock_page_modules(self):
        """Mock all page modules and track instantiation."""
        with (
            mock.patch("src.ui.preferences.window.DatabasePage") as mock_db,
            mock.patch("src.ui.preferences.window.ScannerPage") as mock_scanner,
            mock.patch("src.ui.preferences.window.OnAccessPage") as mock_onaccess,
            mock.patch("src.ui.preferences.window.ScheduledPage") as mock_scheduled,
            mock.patch("src.ui.preferences.window.ExclusionsPage") as mock_exclusions,
            mock.patch("src.ui.preferences.window.SavePage") as mock_save,
            mock.patch("src.ui.preferences.window.VirusTotalPage") as mock_vt,
            mock.patch("src.ui.preferences.window.BehaviorPage") as mock_behavior,
            mock.patch("src.ui.preferences.window.DebugPage") as mock_debug,
        ):
            # Configure static page mocks to return page objects
            mock_db.create_page.return_value = mock.MagicMock()
            mock_scanner.create_page.return_value = mock.MagicMock()
            mock_onaccess.create_page.return_value = mock.MagicMock()
            mock_scheduled.create_page.return_value = mock.MagicMock()
            mock_vt.create_page.return_value = mock.MagicMock()

            # Configure instance-based page mocks
            mock_exclusions_instance = mock.MagicMock()
            mock_exclusions_instance.create_page.return_value = mock.MagicMock()
            mock_exclusions.return_value = mock_exclusions_instance

            mock_save_instance = mock.MagicMock()
            mock_save_instance.create_page.return_value = mock.MagicMock()
            mock_save.return_value = mock_save_instance

            mock_behavior_instance = mock.MagicMock()
            mock_behavior_instance.create_page.return_value = mock.MagicMock()
            mock_behavior.return_value = mock_behavior_instance

            mock_debug_instance = mock.MagicMock()
            mock_debug_instance.create_page.return_value = mock.MagicMock()
            mock_debug.return_value = mock_debug_instance

            # Configure populate_fields as no-op
            mock_db.populate_fields = mock.MagicMock()
            mock_scanner.populate_fields = mock.MagicMock()
            mock_onaccess.populate_fields = mock.MagicMock()
            mock_scheduled.populate_fields = mock.MagicMock()

            yield {
                "database": mock_db,
                "scanner": mock_scanner,
                "onaccess": mock_onaccess,
                "scheduled": mock_scheduled,
                "exclusions": mock_exclusions,
                "save": mock_save,
                "virustotal": mock_vt,
                "behavior": mock_behavior,
                "debug": mock_debug,
            }

    @pytest.fixture
    def window_instance(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Create a PreferencesWindow instance with mocked dependencies."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "_setup_ui"):
            with mock.patch("src.ui.preferences.window.threading.Thread"):
                with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                    window = PreferencesWindow()
        return window, mock_page_modules

    def test_page_factories_registered(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that _page_factories dict is initialized with factory callables."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "_setup_ui"):
            with mock.patch("src.ui.preferences.window.threading.Thread"):
                with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                    window = PreferencesWindow()

        assert hasattr(window, "_page_factories")
        assert isinstance(window._page_factories, dict)
        # All non-default pages should have factories
        expected_lazy_pages = {
            "exclusions",
            "database",
            "device_scan",
            "scanner",
            "scheduled",
            "onaccess",
            "virustotal",
            "debug",
            "save",
        }
        assert set(window._page_factories.keys()) == expected_lazy_pages

    def test_created_pages_cache_initialized_empty(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that _created_pages set is initialized as an empty set."""
        from src.ui.preferences.window import PreferencesWindow

        with mock.patch.object(PreferencesWindow, "_setup_ui"):
            with mock.patch("src.ui.preferences.window.threading.Thread"):
                with mock.patch.object(PreferencesWindow, "_populate_scheduled_fields"):
                    window = PreferencesWindow()

        assert hasattr(window, "_created_pages")
        assert isinstance(window._created_pages, set)

    def test_behavior_page_marked_created_after_full_init(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that behavior page is in _created_pages after full initialization."""
        from src.ui.preferences.window import PreferencesWindow

        window = PreferencesWindow()

        # After full init, behavior should be the only page created
        assert "behavior" in window._created_pages
        # Lazy pages should NOT be in _created_pages
        for page_id in [
            "exclusions",
            "database",
            "scanner",
            "scheduled",
            "onaccess",
            "virustotal",
            "debug",
            "save",
        ]:
            assert page_id not in window._created_pages

    def test_only_behavior_page_created_at_init(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that only the behavior page is created during initialization."""
        from src.ui.preferences.window import PreferencesWindow

        PreferencesWindow()

        # BehaviorPage should have been instantiated
        mock_page_modules["behavior"].assert_called_once()

        # Other pages should NOT have been created yet
        mock_page_modules["database"].create_page.assert_not_called()
        mock_page_modules["scanner"].create_page.assert_not_called()
        mock_page_modules["scheduled"].create_page.assert_not_called()
        mock_page_modules["onaccess"].create_page.assert_not_called()
        mock_page_modules["virustotal"].create_page.assert_not_called()
        mock_page_modules["exclusions"].assert_not_called()
        mock_page_modules["debug"].assert_not_called()
        mock_page_modules["save"].assert_not_called()

    def test_page_created_on_navigation(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that navigating to a page creates it on demand."""
        from src.ui.preferences.window import PreferencesWindow

        window = PreferencesWindow()

        # Database page should not exist yet
        mock_page_modules["database"].create_page.assert_not_called()

        # Simulate navigating to database page
        window._ensure_page_created("database")

        # Now the database page should be created
        mock_page_modules["database"].create_page.assert_called_once()
        assert "database" in window._created_pages

    def test_page_created_only_once(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that a page is only created once even if navigated to multiple times."""
        from src.ui.preferences.window import PreferencesWindow

        window = PreferencesWindow()

        # Create database page twice
        window._ensure_page_created("database")
        window._ensure_page_created("database")

        # Should only be created once
        mock_page_modules["database"].create_page.assert_called_once()

    def test_sidebar_selection_triggers_lazy_creation(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that _on_sidebar_row_selected creates the page if needed."""
        from src.ui.preferences.window import PreferencesWindow

        window = PreferencesWindow()

        # Verify database page not created yet
        mock_page_modules["database"].create_page.assert_not_called()

        # Create a mock sidebar row for the database page
        mock_row = mock.MagicMock()
        mock_row.page_id = "database"

        # Simulate sidebar selection
        window._on_sidebar_row_selected(mock.MagicMock(), mock_row)

        # Database page should now be created
        mock_page_modules["database"].create_page.assert_called_once()

    def test_ensure_page_created_for_behavior_is_noop(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that _ensure_page_created is a no-op for already-created pages."""
        from src.ui.preferences.window import PreferencesWindow

        window = PreferencesWindow()

        # Behavior was already created at init
        behavior_call_count = mock_page_modules["behavior"].call_count

        # Ensure should not create it again
        window._ensure_page_created("behavior")
        assert mock_page_modules["behavior"].call_count == behavior_call_count

    def test_config_population_deferred_for_lazy_pages(
        self,
        mock_gi_modules,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that a lazily-created config page gets populated after the load applies.

        After U2, config parsing runs on a worker thread and field population
        is marshalled back through _apply_loaded_configs (GLib.idle_add, which
        is a no-op under mock_gi_modules). Suppress the thread, create the
        database page (no config yet, so populate_fields is NOT called), then
        drive the I/O step + the main-thread applier explicitly: the applier
        rebuilds the database page and runs _populate_freshclam_fields, which
        calls DatabasePage.populate_fields with the freshly-parsed config.
        """
        from src.ui.preferences.window import PreferencesWindow

        mock_config = mock.MagicMock()
        mock_config.values = {"key": "value"}

        with mock.patch(
            "src.ui.preferences.window.parse_config",
            return_value=(mock_config, None),
        ):
            with mock.patch("src.ui.preferences.window.threading.Thread"):
                window = PreferencesWindow()

            # Creating the page alone must NOT populate fields (config not loaded yet)
            window._ensure_page_created("database")
            mock_page_modules["database"].populate_fields.assert_not_called()

            # Simulate the worker thread finishing its I/O, then the idle_add
            # applier running on the main thread.
            window._load_configs_io()
            window._apply_loaded_configs()
            mock_page_modules["database"].populate_fields.assert_called()

    def test_all_pages_can_be_lazily_created(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that all lazy pages can be created through _ensure_page_created."""
        from src.ui.preferences.window import PreferencesWindow

        window = PreferencesWindow()

        lazy_pages = [
            "exclusions",
            "database",
            "scanner",
            "scheduled",
            "onaccess",
            "virustotal",
            "debug",
            "save",
        ]

        for page_id in lazy_pages:
            window._ensure_page_created(page_id)
            assert page_id in window._created_pages

    def test_unknown_page_id_handled_gracefully(
        self,
        mock_gi_modules,
        mock_parse_config,
        mock_path_exists,
        mock_scheduler,
        mock_page_modules,
    ):
        """Test that an unknown page_id does not crash."""
        from src.ui.preferences.window import PreferencesWindow

        window = PreferencesWindow()

        # Should not raise
        window._ensure_page_created("nonexistent_page")
        assert "nonexistent_page" not in window._created_pages
