# ClamUI Scanner Page Tests
"""Unit tests for the ScannerPage class."""

from types import SimpleNamespace
from unittest import mock

import pytest


class TestScannerPageImport:
    """Tests for importing the ScannerPage."""

    def test_import_scanner_page(self, mock_gi_modules):
        """Test that ScannerPage can be imported."""
        from src.ui.preferences.scanner_page import ScannerPage

        assert ScannerPage is not None

    def test_scanner_page_is_class(self, mock_gi_modules):
        """Test that ScannerPage is a class."""
        from src.ui.preferences.scanner_page import ScannerPage

        assert isinstance(ScannerPage, type)

    def test_scanner_page_inherits_from_mixin(self, mock_gi_modules):
        """Test that ScannerPage inherits from PreferencesPageMixin."""
        from src.ui.preferences.base import PreferencesPageMixin
        from src.ui.preferences.scanner_page import ScannerPage

        assert issubclass(ScannerPage, PreferencesPageMixin)


class TestScannerPageCreation:
    """Tests for ScannerPage.create_page() method."""

    @pytest.fixture
    def mock_config_path(self):
        """Provide a mock config path."""
        return "/etc/clamav/clamd.conf"

    @pytest.fixture
    def widgets_dict(self):
        """Provide an empty widgets dictionary."""
        return {}

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = "auto"
        return manager

    @pytest.fixture
    def mock_parent_window(self):
        """Provide a mock parent window."""
        return mock.MagicMock()

    def test_create_page_returns_preferences_page(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page returns an Adw.PreferencesPage."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

            # Should create a PreferencesPage
            adw.PreferencesPage.assert_called()

    def test_create_page_sets_title_and_icon(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page sets correct title and icon."""
        adw = mock_gi_modules["adw"]

        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

            # Should set title and icon_name
            adw.PreferencesPage.assert_called_with(
                title="Scanner Settings",
                icon_name="document-properties-symbolic",
            )

    def test_create_page_creates_file_location_group(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page creates file location group."""
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch(
            "src.ui.preferences.scanner_page._ScannerPageHelper._create_file_location_group"
        ) as mock_create_file_location:
            with mock.patch(
                "src.core.utils.check_clamd_connection",
                return_value=(True, "Connected"),
            ):
                ScannerPage.create_page(
                    mock_config_path,
                    widgets_dict,
                    mock_settings_manager,
                    True,
                    mock_parent_window,
                )

                # Should call _create_file_location_group
                mock_create_file_location.assert_called_once()

    def test_create_page_creates_all_widgets_when_clamd_available(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page creates all widgets when clamd is available."""
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

        # Check that all expected widgets are in the dict
        expected_widgets = [
            # Backend group
            "backend_row",
            "daemon_status_row",
            # File type scanning
            "ScanPE",
            "ScanELF",
            "ScanOLE2",
            "ScanPDF",
            "ScanHTML",
            "ScanArchive",
            # Performance
            "MaxFileSize",
            "MaxScanSize",
            "MaxRecursion",
            "MaxFiles",
            # Logging
            "LogFile",
            "LogVerbose",
            "LogSyslog",
        ]

        for widget_name in expected_widgets:
            assert widget_name in widgets_dict, f"Widget {widget_name} not created"

    def test_create_page_shows_unavailable_message_when_clamd_not_available(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page shows unavailable message when clamd is not available."""
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                False,
                mock_parent_window,
            )

        # Should create backend_row and daemon_status_row
        assert "backend_row" in widgets_dict
        assert "daemon_status_row" in widgets_dict

        # Should NOT create clamd-specific widgets
        clamd_widgets = [
            "ScanPE",
            "ScanELF",
            "MaxFileSize",
            "LogFile",
        ]
        for widget_name in clamd_widgets:
            assert widget_name not in widgets_dict

    def test_create_page_creates_backend_combo_row(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page creates backend ComboRow."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

        # Should create ComboRow
        adw.ComboRow.assert_called()

    def test_create_page_creates_switch_rows(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page creates SwitchRows for boolean settings."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

        # Switch rows are now ActionRows via create_switch_row compat
        # 8 switches + 1 entry row = 9 ActionRows minimum
        assert adw.ActionRow.call_count >= 8

    def test_create_page_creates_spin_buttons(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page creates SpinButtons for numeric settings (1.0+ compatible)."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

        # Should create SpinButtons for 4 performance settings
        # (using create_spin_row helper which uses Gtk.SpinButton)
        assert gtk.SpinButton.call_count >= 4

    def test_max_recursion_spin_row_uses_current_clamav_range(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test MaxRecursion offers ClamAV's accepted 1-100 range (issue #181)."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

        # create_spin_row builds one Gtk.Adjustment per spin row
        bounds = [
            (call.kwargs.get("lower"), call.kwargs.get("upper"))
            for call in gtk.Adjustment.call_args_list
        ]
        assert (1, 100) in bounds, f"No spin row with MaxRecursion range 1-100; got {bounds}"

    def test_max_recursion_spin_row_starts_at_clamav_default(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test MaxRecursion spin row starts at ClamAV's default of 17 (issue #181)."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

        initial_states = [
            (call.kwargs.get("value"), call.kwargs.get("lower"), call.kwargs.get("upper"))
            for call in gtk.Adjustment.call_args_list
        ]
        assert (17, 1, 100) in initial_states, (
            f"MaxRecursion spin row must start at 17 within 1-100; got {initial_states}"
        )

    def test_create_page_creates_entry_rows(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page creates EntryRow for LogFile."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

        # Entry rows are now ActionRows via create_entry_row compat
        adw.ActionRow.assert_called()

    def test_create_page_creates_daemon_status_row(
        self,
        mock_gi_modules,
        mock_config_path,
        widgets_dict,
        mock_settings_manager,
        mock_parent_window,
    ):
        """Test create_page creates daemon status row with connection check."""
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection") as mock_check_clamd:
            mock_check_clamd.return_value = (True, "Connected")

            ScannerPage.create_page(
                mock_config_path,
                widgets_dict,
                mock_settings_manager,
                True,
                mock_parent_window,
            )

            # Should check daemon connection
            mock_check_clamd.assert_called()

            # Should create daemon status row
            assert "daemon_status_row" in widgets_dict


class TestScannerPageBackendSelection:
    """Tests for backend selection functionality."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = "auto"
        return manager

    def test_create_page_sets_backend_from_settings_auto(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test create_page sets backend selection from settings (auto)."""
        mock_settings_manager.get.return_value = "auto"

        from src.ui.preferences.scanner_page import ScannerPage

        widgets_dict = {}
        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                "/etc/clamav/clamd.conf",
                widgets_dict,
                mock_settings_manager,
                True,
                None,
            )

        # Should set to index 0 for "auto" - use widgets_dict since ComboRow uses side_effect
        widgets_dict["backend_row"].set_selected.assert_called_with(0)

    def test_create_page_sets_backend_from_settings_daemon(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test create_page sets backend selection from settings (daemon)."""
        mock_settings_manager.get.return_value = "daemon"

        from src.ui.preferences.scanner_page import ScannerPage

        widgets_dict = {}
        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                "/etc/clamav/clamd.conf",
                widgets_dict,
                mock_settings_manager,
                True,
                None,
            )

        # Should set to index 1 for "daemon" - use widgets_dict since ComboRow uses side_effect
        widgets_dict["backend_row"].set_selected.assert_called_with(1)

    def test_create_page_sets_backend_from_settings_clamscan(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test create_page sets backend selection from settings (clamscan)."""
        mock_settings_manager.get.return_value = "clamscan"

        from src.ui.preferences.scanner_page import ScannerPage

        widgets_dict = {}
        with mock.patch("src.core.utils.check_clamd_connection", return_value=(True, "Connected")):
            ScannerPage.create_page(
                "/etc/clamav/clamd.conf",
                widgets_dict,
                mock_settings_manager,
                True,
                None,
            )

        # Should set to index 2 for "clamscan" - use widgets_dict since ComboRow uses side_effect
        widgets_dict["backend_row"].set_selected.assert_called_with(2)

    def test_update_backend_subtitle_sets_correct_subtitle_for_auto(self, mock_gi_modules):
        """Test _update_backend_subtitle sets correct subtitle for auto."""
        mock_row = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        ScannerPage._update_backend_subtitle(mock_row, 0)

        # Should set subtitle for auto
        mock_row.set_subtitle.assert_called()
        args = mock_row.set_subtitle.call_args[0]
        assert "Automatically uses daemon" in args[0] or "Recommended" in args[0]

    def test_update_backend_subtitle_sets_correct_subtitle_for_daemon(self, mock_gi_modules):
        """Test _update_backend_subtitle sets correct subtitle for daemon."""
        mock_row = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        ScannerPage._update_backend_subtitle(mock_row, 1)

        # Should set subtitle for daemon
        mock_row.set_subtitle.assert_called()
        args = mock_row.set_subtitle.call_args[0]
        assert "Fastest" in args[0] or "in-memory" in args[0]

    def test_update_backend_subtitle_sets_correct_subtitle_for_clamscan(self, mock_gi_modules):
        """Test _update_backend_subtitle sets correct subtitle for clamscan."""
        mock_row = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        ScannerPage._update_backend_subtitle(mock_row, 2)

        # Should set subtitle for clamscan
        mock_row.set_subtitle.assert_called()
        args = mock_row.set_subtitle.call_args[0]
        assert "compatible" in args[0] or "loads database" in args[0]

    def test_on_backend_changed_saves_to_settings_auto(self, mock_gi_modules):
        """Test _on_backend_changed saves 'auto' to settings."""
        mock_row = mock.MagicMock()
        mock_row.get_selected.return_value = 0
        mock_settings_manager = mock.MagicMock()
        parent_window = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        ScannerPage._on_backend_changed(mock_row, mock_settings_manager, parent_window)

        # Should save "auto" to settings
        mock_settings_manager.set.assert_called_with("scan_backend", "auto")

    def test_on_backend_changed_saves_to_settings_daemon(self, mock_gi_modules):
        """Test _on_backend_changed saves 'daemon' to settings."""
        mock_row = mock.MagicMock()
        mock_row.get_selected.return_value = 1
        mock_settings_manager = mock.MagicMock()
        parent_window = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        ScannerPage._on_backend_changed(mock_row, mock_settings_manager, parent_window)

        # Should save "daemon" to settings
        mock_settings_manager.set.assert_called_with("scan_backend", "daemon")

    def test_on_backend_changed_saves_to_settings_clamscan(self, mock_gi_modules):
        """Test _on_backend_changed saves 'clamscan' to settings."""
        mock_row = mock.MagicMock()
        mock_row.get_selected.return_value = 2
        mock_settings_manager = mock.MagicMock()
        parent_window = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        ScannerPage._on_backend_changed(mock_row, mock_settings_manager, parent_window)

        # Should save "clamscan" to settings
        mock_settings_manager.set.assert_called_with("scan_backend", "clamscan")

    def test_on_backend_changed_updates_subtitle(self, mock_gi_modules):
        """Test _on_backend_changed updates subtitle."""
        mock_row = mock.MagicMock()
        mock_row.get_selected.return_value = 0
        mock_settings_manager = mock.MagicMock()
        parent_window = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch.object(ScannerPage, "_update_backend_subtitle") as mock_update_subtitle:
            ScannerPage._on_backend_changed(mock_row, mock_settings_manager, parent_window)

            # Should update subtitle
            mock_update_subtitle.assert_called_once_with(mock_row, 0)

    def test_on_backend_changed_restores_persisted_selection_after_save_failure(
        self, mock_gi_modules
    ):
        """A rejected backend save restores the persisted selection and reports the failure."""
        from src.ui.preferences.scanner_page import ScannerPage

        mock_row = mock.MagicMock()
        mock_row.get_selected.return_value = 1
        mock_settings_manager = mock.MagicMock()
        mock_settings_manager.set.return_value = False
        mock_settings_manager.get.return_value = "clamscan"
        parent_window = mock.MagicMock()
        mock_row.set_selected.side_effect = lambda _selection: ScannerPage._on_backend_changed(
            mock_row, mock_settings_manager, parent_window
        )

        with mock.patch.object(ScannerPage, "_update_backend_subtitle") as mock_update_subtitle:
            ScannerPage._on_backend_changed(mock_row, mock_settings_manager, parent_window)

        mock_settings_manager.set.assert_called_once_with("scan_backend", "daemon")
        mock_row.set_selected.assert_called_once_with(2)
        mock_update_subtitle.assert_called_once_with(mock_row, 2)
        mock_gi_modules["adw"].Toast.new.assert_called_once_with(
            "Failed to save scan backend selection"
        )
        parent_window.add_toast.assert_called_once()


class TestScannerPageConfigSelectionPersistence:
    """Tests that failed clamd.conf persistence leaves the loaded configuration intact."""

    @staticmethod
    def _parent_window(settings_manager):
        parent_window = SimpleNamespace(
            _settings_manager=settings_manager,
            _clamd_conf_path="/etc/clamav/clamd.conf",
            _clamd_available=True,
            _clamd_config=object(),
        )
        parent_window._reload_clamd_config = mock.MagicMock()
        parent_window.add_toast = mock.MagicMock()
        return parent_window

    def test_detected_path_save_failure_keeps_current_configuration(self, mock_gi_modules):
        """A detected path is not exposed when saving it fails."""
        from src.ui.preferences import scanner_page

        settings_manager = mock.MagicMock()
        settings_manager.get.return_value = "auto"
        settings_manager.set.return_value = False
        parent_window = self._parent_window(settings_manager)
        loaded_config = parent_window._clamd_config
        path_row = mock.MagicMock()

        with (
            mock.patch.object(
                scanner_page._ScannerPageHelper,
                "_create_file_location_group",
                return_value=path_row,
            ) as create_file_location_group,
            mock.patch.object(scanner_page.threading, "Thread"),
            mock.patch.object(
                scanner_page, "detect_clamd_conf_path", return_value="/custom/clamd.conf"
            ),
        ):
            scanner_page.ScannerPage.create_page(
                "/etc/clamav/clamd.conf",
                {},
                settings_manager,
                False,
                parent_window,
            )
            create_file_location_group.call_args.kwargs["on_detect"]()

        settings_manager.set.assert_called_once_with("clamd_conf_path", "/custom/clamd.conf")
        path_row.set_subtitle.assert_not_called()
        assert parent_window._clamd_conf_path == "/etc/clamav/clamd.conf"
        assert parent_window._clamd_available is True
        assert parent_window._clamd_config is loaded_config
        parent_window._reload_clamd_config.assert_not_called()
        mock_gi_modules["adw"].Toast.new.assert_called_once_with(
            "Failed to save configuration file selection"
        )

    def test_browsed_path_save_failure_keeps_current_configuration(self, mock_gi_modules):
        """A browsed path is not exposed when saving it fails."""
        from src.ui.preferences.scanner_page import ScannerPage

        settings_manager = mock.MagicMock()
        settings_manager.set.return_value = False
        parent_window = self._parent_window(settings_manager)
        loaded_config = parent_window._clamd_config
        path_row = mock.MagicMock()
        dialog = mock.MagicMock()
        selected_file = mock.MagicMock()
        selected_file.get_path.return_value = "/custom/clamd.conf"
        dialog.open_finish.return_value = selected_file
        dialog.open.side_effect = lambda _parent, _cancellable, callback: callback(dialog, object())
        mock_gi_modules["gtk"].FileDialog.return_value = dialog

        ScannerPage._browse_for_config(
            parent_window, path_row, "clamd_conf_path", "_clamd_conf_path"
        )
        settings_manager.set.assert_called_once_with("clamd_conf_path", "/custom/clamd.conf")
        path_row.set_subtitle.assert_not_called()
        assert parent_window._clamd_conf_path == "/etc/clamav/clamd.conf"
        assert parent_window._clamd_available is True
        assert parent_window._clamd_config is loaded_config
        parent_window._reload_clamd_config.assert_not_called()
        mock_gi_modules["adw"].Toast.new.assert_called_once_with(
            "Failed to save configuration file selection"
        )

    def test_unresolved_portal_path_keeps_current_configuration(self, mock_gi_modules):
        """An unresolved portal path is neither persisted nor exposed."""
        from src.ui.preferences import scanner_page

        settings_manager = mock.MagicMock()
        parent_window = self._parent_window(settings_manager)
        loaded_config = parent_window._clamd_config
        path_row = mock.MagicMock()
        dialog = mock.MagicMock()
        selected_file = mock.MagicMock()
        selected_file.get_path.return_value = "/run/user/1000/doc/clamd.conf"
        dialog.open_finish.return_value = selected_file
        dialog.open.side_effect = lambda _parent, _cancellable, callback: callback(dialog, object())
        mock_gi_modules["gtk"].FileDialog.return_value = dialog

        with (
            mock.patch.object(scanner_page, "is_flatpak", return_value=True),
            mock.patch.object(scanner_page, "is_portal_path", return_value=True),
            mock.patch.object(scanner_page, "resolve_portal_path", return_value=None),
        ):
            scanner_page.ScannerPage._browse_for_config(
                parent_window, path_row, "clamd_conf_path", "_clamd_conf_path"
            )

        settings_manager.set.assert_not_called()
        path_row.set_subtitle.assert_not_called()
        assert parent_window._clamd_conf_path == "/etc/clamav/clamd.conf"
        assert parent_window._clamd_available is True
        assert parent_window._clamd_config is loaded_config
        parent_window._reload_clamd_config.assert_not_called()
        mock_gi_modules["adw"].Toast.new.assert_called_once_with(
            "Selected configuration file is not accessible from the host"
        )
        parent_window.add_toast.assert_called_once()


class TestScannerPageDaemonStatus:
    """Tests for daemon status functionality."""

    def test_on_refresh_daemon_status_updates_when_connected(self, mock_gi_modules):
        """Test _on_refresh_daemon_status updates status when daemon is connected."""
        mock_status_row = mock.MagicMock()
        mock_status_icon = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection") as mock_check_clamd:
            mock_check_clamd.return_value = (True, "Connected")

            with mock.patch(
                "src.ui.preferences.scanner_page.GLib.idle_add",
                side_effect=lambda fn, *a: fn(*a),
            ):
                ScannerPage._on_refresh_daemon_status(mock_status_row, mock_status_icon)

            # Should update subtitle to show connected
            mock_status_row.set_subtitle.assert_called()
            args = mock_status_row.set_subtitle.call_args[0]
            assert "Daemon available" in args[0]

    def test_on_refresh_daemon_status_updates_when_not_connected(self, mock_gi_modules):
        """Test _on_refresh_daemon_status updates status when daemon is not connected."""
        mock_status_row = mock.MagicMock()
        mock_status_icon = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection") as mock_check_clamd:
            mock_check_clamd.return_value = (False, "Connection refused")

            with mock.patch(
                "src.ui.preferences.scanner_page.GLib.idle_add",
                side_effect=lambda fn, *a: fn(*a),
            ):
                ScannerPage._on_refresh_daemon_status(mock_status_row, mock_status_icon)

            # Should update subtitle to show not connected
            mock_status_row.set_subtitle.assert_called()
            args = mock_status_row.set_subtitle.call_args[0]
            assert "Not available" in args[0] or "Connection refused" in args[0]


class TestScannerPageAsyncDaemonCheck:
    """Tests for asynchronous daemon status checking during page creation."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = "auto"
        return manager

    def test_create_page_does_not_call_check_clamd_synchronously(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test that create_page does NOT call check_clamd_connection synchronously."""
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.core.utils.check_clamd_connection") as mock_check:
            mock_check.return_value = (True, "Connected")

            with mock.patch("src.ui.preferences.scanner_page.threading"):
                ScannerPage.create_page(
                    "/etc/clamav/clamd.conf",
                    {},
                    mock_settings_manager,
                    True,
                    None,
                )

            # check_clamd_connection should NOT have been called during create_page
            # (it should be deferred to a background thread)
            mock_check.assert_not_called()

    def test_create_page_starts_background_thread_for_daemon_check(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test that create_page starts a background thread for daemon status check."""
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.ui.preferences.scanner_page.threading") as mock_threading:
            mock_thread = mock.MagicMock()
            mock_threading.Thread.return_value = mock_thread

            ScannerPage.create_page(
                "/etc/clamav/clamd.conf",
                {},
                mock_settings_manager,
                True,
                None,
            )

            # Should have created and started a daemon thread
            mock_threading.Thread.assert_called_once()
            call_kwargs = mock_threading.Thread.call_args[1]
            assert call_kwargs.get("daemon") is True
            mock_thread.start.assert_called_once()

    def test_create_page_passes_config_path_to_daemon_check(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test create_page passes clamd.conf path into the background daemon check."""
        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.ui.preferences.scanner_page.threading") as mock_threading:
            mock_thread = mock.MagicMock()
            mock_threading.Thread.return_value = mock_thread

            ScannerPage.create_page(
                "/etc/clamd.d/scan.conf",
                {},
                mock_settings_manager,
                True,
                None,
            )

            call_args = mock_threading.Thread.call_args[1]["args"]
            assert call_args[2] == "/etc/clamd.d/scan.conf"

    def test_create_page_shows_checking_status_initially(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test that create_page shows a 'Checking...' status initially."""
        from src.ui.preferences.scanner_page import ScannerPage

        widgets_dict = {}
        with mock.patch("src.ui.preferences.scanner_page.threading"):
            ScannerPage.create_page(
                "/etc/clamav/clamd.conf",
                widgets_dict,
                mock_settings_manager,
                True,
                None,
            )

        # The status row should exist and show a checking/loading message
        assert "daemon_status_row" in widgets_dict
        status_row = widgets_dict["daemon_status_row"]
        # Should have been set with a "checking" initial message
        status_row.set_subtitle.assert_called()
        initial_subtitle = status_row.set_subtitle.call_args_list[0][0][0]
        assert "Checking" in initial_subtitle or "checking" in initial_subtitle

    def test_daemon_check_background_updates_ui_via_idle_add(self, mock_gi_modules):
        """Test that the background daemon check updates UI via GLib.idle_add."""
        from src.ui.preferences.scanner_page import ScannerPage

        mock_status_row = mock.MagicMock()
        mock_status_icon = mock.MagicMock()

        with mock.patch("src.core.utils.check_clamd_connection") as mock_check:
            mock_check.return_value = (True, "Connected")

            with mock.patch("src.ui.preferences.scanner_page.GLib.idle_add") as mock_idle_add:
                # Call the background check method directly
                ScannerPage._check_daemon_status_background(mock_status_row, mock_status_icon)

                # Should have called GLib.idle_add to schedule UI update
                mock_idle_add.assert_called_once()

    def test_refresh_daemon_status_uses_background_thread(self, mock_gi_modules):
        """Test that _on_refresh_daemon_status uses a background thread."""
        from src.ui.preferences.scanner_page import ScannerPage

        mock_status_row = mock.MagicMock()
        mock_status_icon = mock.MagicMock()

        with mock.patch("src.ui.preferences.scanner_page.threading") as mock_threading:
            mock_thread = mock.MagicMock()
            mock_threading.Thread.return_value = mock_thread

            ScannerPage._on_refresh_daemon_status(mock_status_row, mock_status_icon)

            # Should create a daemon thread for the check
            mock_threading.Thread.assert_called_once()
            call_kwargs = mock_threading.Thread.call_args[1]
            assert call_kwargs.get("daemon") is True
            mock_thread.start.assert_called_once()


class TestScannerPageLearnMore:
    """Tests for learn more documentation link."""

    def test_on_learn_more_clicked_opens_documentation_when_exists(self, mock_gi_modules, tmp_path):
        """Test _on_learn_more_clicked opens documentation when file exists."""
        mock_parent_window = mock.MagicMock()

        from src.ui.preferences.scanner_page import ScannerPage

        # Mock the Path and exists check
        with mock.patch("src.ui.preferences.scanner_page.Path") as mock_path:
            with mock.patch("subprocess.Popen") as mock_popen:
                # Make the docs path exist
                mock_docs_path = mock.MagicMock()
                mock_docs_path.exists.return_value = True
                mock_docs_path.__str__.return_value = "/path/to/docs/SCAN_BACKENDS.md"
                mock_path.return_value.parent.parent.parent.parent = mock.MagicMock()
                mock_path.return_value.parent.parent.parent.parent.__truediv__.return_value = (
                    mock_docs_path
                )

                ScannerPage._on_learn_more_clicked(mock_parent_window)

                # Should open the file with xdg-open
                mock_popen.assert_called_once()

    def test_on_learn_more_clicked_shows_error_when_not_exists(self, mock_gi_modules):
        """Test _on_learn_more_clicked shows error when documentation doesn't exist."""
        adw = mock_gi_modules["adw"]
        mock_parent_window = mock.MagicMock()
        mock_dialog = mock.MagicMock()
        mock_window_class = mock.MagicMock(return_value=mock_dialog)

        from src.ui.preferences.scanner_page import ScannerPage

        # Mock the Path and exists check
        with mock.patch("src.ui.preferences.scanner_page.Path") as mock_path:
            with mock.patch.object(adw, "Window", mock_window_class):
                # Make the docs path not exist
                # Chain: Path(__file__).parent.parent.parent.parent / "docs" / "SCAN_BACKENDS.md"
                mock_docs_path = mock.MagicMock()
                mock_docs_path.exists.return_value = False
                # Need to chain two __truediv__ calls
                intermediate_mock = mock.MagicMock()
                intermediate_mock.__truediv__.return_value = mock_docs_path
                mock_path.return_value.parent.parent.parent.parent.__truediv__.return_value = (
                    intermediate_mock
                )

                ScannerPage._on_learn_more_clicked(mock_parent_window)

                # Should create and present Adw.Window-based error dialog
                mock_window_class.assert_called_once()
                mock_dialog.set_transient_for.assert_called_once_with(mock_parent_window)
                mock_dialog.present.assert_called_once()

    def test_on_learn_more_clicked_shows_error_when_open_fails(self, mock_gi_modules):
        """Test _on_learn_more_clicked shows error when opening file fails."""
        adw = mock_gi_modules["adw"]
        mock_parent_window = mock.MagicMock()
        mock_dialog = mock.MagicMock()
        mock_window_class = mock.MagicMock(return_value=mock_dialog)

        from src.ui.preferences.scanner_page import ScannerPage

        with mock.patch("src.ui.preferences.scanner_page.Path") as mock_path:
            with mock.patch("subprocess.Popen") as mock_popen:
                with mock.patch.object(adw, "Window", mock_window_class):
                    # Make the docs path exist
                    mock_docs_path = mock.MagicMock()
                    mock_docs_path.exists.return_value = True
                    mock_path.return_value.parent.parent.parent.parent = mock.MagicMock()
                    mock_path.return_value.parent.parent.parent.parent.__truediv__.return_value = (
                        mock_docs_path
                    )

                    # Make Popen raise an exception
                    mock_popen.side_effect = Exception("Failed to open")

                    ScannerPage._on_learn_more_clicked(mock_parent_window)

                    # Should create and present Adw.Window-based error dialog
                    mock_window_class.assert_called_once()
                    mock_dialog.set_transient_for.assert_called_once_with(mock_parent_window)
                    mock_dialog.present.assert_called_once()


class TestScannerPagePopulateFields:
    """Tests for ScannerPage.populate_fields() method."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config object."""
        config = mock.MagicMock()
        config.has_key = mock.MagicMock(return_value=True)
        config.get_value = mock.MagicMock(return_value="yes")
        return config

    @pytest.fixture
    def mock_widgets(self):
        """Create mock widgets dictionary."""
        return {
            "ScanPE": mock.MagicMock(),
            "ScanELF": mock.MagicMock(),
            "ScanOLE2": mock.MagicMock(),
            "ScanPDF": mock.MagicMock(),
            "ScanHTML": mock.MagicMock(),
            "ScanArchive": mock.MagicMock(),
            "MaxFileSize": mock.MagicMock(),
            "MaxScanSize": mock.MagicMock(),
            "MaxRecursion": mock.MagicMock(),
            "MaxFiles": mock.MagicMock(),
            "LogFile": mock.MagicMock(),
            "LogVerbose": mock.MagicMock(),
            "LogSyslog": mock.MagicMock(),
        }

    def test_populate_fields_handles_none_config(self, mock_gi_modules, mock_widgets):
        """Test populate_fields handles None config gracefully."""
        from src.ui.preferences.scanner_page import ScannerPage

        # Should not raise exception
        ScannerPage.populate_fields(None, mock_widgets)

    def test_populate_fields_sets_file_type_switches_yes(
        self, mock_gi_modules, mock_config, mock_widgets
    ):
        """Test populate_fields sets file type switches to True for 'yes'."""
        from src.ui.preferences.scanner_page import ScannerPage

        mock_config.get_value.return_value = "yes"

        ScannerPage.populate_fields(mock_config, mock_widgets)

        # Should call set_active(True) on all file type switches
        mock_widgets["ScanPE"].set_active.assert_called_with(True)
        mock_widgets["ScanELF"].set_active.assert_called_with(True)
        mock_widgets["ScanOLE2"].set_active.assert_called_with(True)
        mock_widgets["ScanPDF"].set_active.assert_called_with(True)
        mock_widgets["ScanHTML"].set_active.assert_called_with(True)
        mock_widgets["ScanArchive"].set_active.assert_called_with(True)

    def test_populate_fields_sets_file_type_switches_no(
        self, mock_gi_modules, mock_config, mock_widgets
    ):
        """Test populate_fields sets file type switches to False for 'no'."""
        from src.ui.preferences.scanner_page import ScannerPage

        mock_config.get_value.return_value = "no"

        ScannerPage.populate_fields(mock_config, mock_widgets)

        # Should call set_active(False) on all file type switches
        mock_widgets["ScanPE"].set_active.assert_called_with(False)
        mock_widgets["ScanELF"].set_active.assert_called_with(False)

    def test_populate_fields_sets_performance_values(
        self, mock_gi_modules, mock_config, mock_widgets
    ):
        """Test populate_fields sets performance numeric values."""
        from src.ui.preferences.scanner_page import ScannerPage

        def custom_get_value(key):
            if key in ("MaxFileSize", "MaxScanSize"):
                return "100M"
            if key in ("MaxRecursion", "MaxFiles"):
                return "100"
            return "yes"

        mock_config.get_value.side_effect = custom_get_value

        ScannerPage.populate_fields(mock_config, mock_widgets)

        # Should call set_value with integer
        mock_widgets["MaxFileSize"].set_value.assert_called_with(100)
        mock_widgets["MaxScanSize"].set_value.assert_called_with(100)
        mock_widgets["MaxRecursion"].set_value.assert_called_with(100)
        mock_widgets["MaxFiles"].set_value.assert_called_with(100)

    def test_populate_fields_handles_invalid_numeric_values(
        self, mock_gi_modules, mock_config, mock_widgets
    ):
        """Test populate_fields handles invalid numeric values gracefully."""
        from src.ui.preferences.scanner_page import ScannerPage

        # Set up config to have key but invalid value
        def custom_get_value(key):
            if key.startswith("Max"):
                return "not_a_number"
            return "yes"

        mock_config.get_value.side_effect = custom_get_value

        # Should not raise exception
        ScannerPage.populate_fields(mock_config, mock_widgets)

    def test_populate_fields_sets_log_file_path(self, mock_gi_modules, mock_config, mock_widgets):
        """Test populate_fields sets log file path."""
        from src.ui.preferences.scanner_page import ScannerPage

        mock_config.get_value.return_value = "/var/log/clamav/clamd.log"

        ScannerPage.populate_fields(mock_config, mock_widgets)

        # Should call set_text on LogFile
        mock_widgets["LogFile"].set_text.assert_called_with("/var/log/clamav/clamd.log")

    def test_populate_fields_sets_logging_switches(
        self, mock_gi_modules, mock_config, mock_widgets
    ):
        """Test populate_fields sets logging switch states."""
        from src.ui.preferences.scanner_page import ScannerPage

        mock_config.get_value.return_value = "yes"

        ScannerPage.populate_fields(mock_config, mock_widgets)

        # Should call set_active on logging switches
        mock_widgets["LogVerbose"].set_active.assert_called_with(True)
        mock_widgets["LogSyslog"].set_active.assert_called_with(True)

    def test_populate_fields_skips_missing_keys(self, mock_gi_modules, mock_config, mock_widgets):
        """Test populate_fields handles missing keys with defaults."""
        from src.ui.preferences.scanner_page import ScannerPage

        # Simulate missing keys
        mock_config.has_key.return_value = False

        ScannerPage.populate_fields(mock_config, mock_widgets)

        # Missing file-type keys must default to ON: ClamAV enables ScanPE etc.
        # by default when absent from clamd.conf, so showing them off would
        # write "ScanPE no" on the next save and disable scanning features.
        mock_widgets["ScanPE"].set_active.assert_called_with(True)
        # set_value should not be called for missing numeric keys (different helper)
        mock_widgets["MaxFileSize"].set_value.assert_not_called()


class TestScannerPageCollectData:
    """Tests for ScannerPage.collect_data() method."""

    @pytest.fixture
    def mock_widgets(self):
        """Create mock widgets dictionary with default return values."""
        widgets = {
            "ScanPE": mock.MagicMock(),
            "ScanELF": mock.MagicMock(),
            "ScanOLE2": mock.MagicMock(),
            "ScanPDF": mock.MagicMock(),
            "ScanHTML": mock.MagicMock(),
            "ScanArchive": mock.MagicMock(),
            "MaxFileSize": mock.MagicMock(),
            "MaxScanSize": mock.MagicMock(),
            "MaxRecursion": mock.MagicMock(),
            "MaxFiles": mock.MagicMock(),
            "LogFile": mock.MagicMock(),
            "LogVerbose": mock.MagicMock(),
            "LogSyslog": mock.MagicMock(),
        }

        # Set default return values
        widgets["ScanPE"].get_active.return_value = True
        widgets["ScanELF"].get_active.return_value = True
        widgets["ScanOLE2"].get_active.return_value = False
        widgets["ScanPDF"].get_active.return_value = True
        widgets["ScanHTML"].get_active.return_value = False
        widgets["ScanArchive"].get_active.return_value = True
        widgets["MaxFileSize"].get_value.return_value = 100
        widgets["MaxScanSize"].get_value.return_value = 200
        widgets["MaxRecursion"].get_value.return_value = 16
        widgets["MaxFiles"].get_value.return_value = 10000
        widgets["LogFile"].get_text.return_value = "/var/log/clamav/clamd.log"
        widgets["LogVerbose"].get_active.return_value = True
        widgets["LogSyslog"].get_active.return_value = False

        return widgets

    def test_collect_data_returns_dict(self, mock_gi_modules, mock_widgets):
        """Test collect_data returns a dictionary."""
        from src.ui.preferences.scanner_page import ScannerPage

        result = ScannerPage.collect_data(mock_widgets, True)

        assert isinstance(result, dict)

    def test_collect_data_returns_empty_dict_when_clamd_unavailable(
        self, mock_gi_modules, mock_widgets
    ):
        """Test collect_data returns empty dict when clamd is unavailable."""
        from src.ui.preferences.scanner_page import ScannerPage

        result = ScannerPage.collect_data(mock_widgets, False)

        assert result == {}

    def test_collect_data_converts_switches_to_yes_no(self, mock_gi_modules, mock_widgets):
        """Test collect_data converts switch states to yes/no strings."""
        from src.ui.preferences.scanner_page import ScannerPage

        result = ScannerPage.collect_data(mock_widgets, True)

        # True switches should be "yes"
        assert result["ScanPE"] == "yes"
        assert result["ScanELF"] == "yes"
        assert result["ScanPDF"] == "yes"
        assert result["LogVerbose"] == "yes"

        # False switches should be "no"
        assert result["ScanOLE2"] == "no"
        assert result["ScanHTML"] == "no"
        assert result["LogSyslog"] == "no"

    def test_collect_data_converts_numeric_to_string(self, mock_gi_modules, mock_widgets):
        """Test collect_data converts numeric values to strings."""
        from src.ui.preferences.scanner_page import ScannerPage

        result = ScannerPage.collect_data(mock_widgets, True)

        assert result["MaxFileSize"] == "100M"
        assert result["MaxScanSize"] == "200M"
        assert result["MaxRecursion"] == "16"
        assert result["MaxFiles"] == "10000"
        assert isinstance(result["MaxFileSize"], str)

    def test_collect_data_includes_log_file_path(self, mock_gi_modules, mock_widgets):
        """Test collect_data includes log file path."""
        from src.ui.preferences.scanner_page import ScannerPage

        result = ScannerPage.collect_data(mock_widgets, True)

        assert result["LogFile"] == "/var/log/clamav/clamd.log"

    def test_collect_data_excludes_empty_log_file(self, mock_gi_modules, mock_widgets):
        """Test collect_data excludes empty log file path."""
        from src.ui.preferences.scanner_page import ScannerPage

        # Set log file to empty
        mock_widgets["LogFile"].get_text.return_value = ""

        result = ScannerPage.collect_data(mock_widgets, True)

        # Empty log file should not be in result
        assert "LogFile" not in result

    def test_collect_data_always_includes_switches(self, mock_gi_modules, mock_widgets):
        """Test collect_data always includes switch values."""
        from src.ui.preferences.scanner_page import ScannerPage

        result = ScannerPage.collect_data(mock_widgets, True)

        # All switches should be present
        assert "ScanPE" in result
        assert "ScanELF" in result
        assert "ScanOLE2" in result
        assert "ScanPDF" in result
        assert "ScanHTML" in result
        assert "ScanArchive" in result
        assert "LogVerbose" in result
        assert "LogSyslog" in result

    def test_collect_data_includes_all_performance_settings(self, mock_gi_modules, mock_widgets):
        """Test collect_data includes all performance settings."""
        from src.ui.preferences.scanner_page import ScannerPage

        result = ScannerPage.collect_data(mock_widgets, True)

        # All performance settings should be present
        assert "MaxFileSize" in result
        assert "MaxScanSize" in result
        assert "MaxRecursion" in result
        assert "MaxFiles" in result

    def test_collect_data_skips_missing_widgets_without_crashing(self, mock_gi_modules):
        """Test collect_data handles missing widget keys safely."""
        from src.ui.preferences.scanner_page import ScannerPage

        partial_widgets = {
            "ScanPE": mock.MagicMock(get_active=lambda: True),
            "LogVerbose": mock.MagicMock(get_active=lambda: False),
        }

        result = ScannerPage.collect_data(partial_widgets, True)

        assert result["ScanPE"] == "yes"
        assert result["LogVerbose"] == "no"
        assert "MaxFileSize" not in result
        assert "LogFile" not in result

    def test_collect_data_skips_invalid_numeric_values(self, mock_gi_modules, mock_widgets):
        """Test collect_data ignores invalid numeric values instead of raising."""
        from src.ui.preferences.scanner_page import ScannerPage

        mock_widgets["MaxFileSize"].get_value.return_value = "invalid"
        mock_widgets["MaxFiles"].get_value.return_value = None

        result = ScannerPage.collect_data(mock_widgets, True)

        assert "MaxFileSize" not in result
        assert "MaxFiles" not in result


class TestScannerPageHelper:
    """Tests for _ScannerPageHelper class."""

    def test_helper_inherits_from_mixin(self, mock_gi_modules):
        """Test that _ScannerPageHelper inherits from PreferencesPageMixin."""
        from src.ui.preferences.base import PreferencesPageMixin
        from src.ui.preferences.scanner_page import _ScannerPageHelper

        assert issubclass(_ScannerPageHelper, PreferencesPageMixin)

    def test_helper_has_mixin_methods(self, mock_gi_modules):
        """Test that _ScannerPageHelper has mixin methods."""
        from src.ui.preferences.scanner_page import _ScannerPageHelper

        # Should have all mixin methods
        assert hasattr(_ScannerPageHelper, "_create_permission_indicator")
        assert hasattr(_ScannerPageHelper, "_create_file_location_group")

    def test_helper_can_be_instantiated(self, mock_gi_modules):
        """Test that _ScannerPageHelper can be instantiated."""
        from src.ui.preferences.scanner_page import _ScannerPageHelper

        # Should be able to create an instance
        instance = _ScannerPageHelper()
        assert instance is not None

    def test_helper_has_parent_window_attribute(self, mock_gi_modules):
        """Test that _ScannerPageHelper has _parent_window attribute."""
        from src.ui.preferences.scanner_page import _ScannerPageHelper

        instance = _ScannerPageHelper()
        assert hasattr(instance, "_parent_window")
