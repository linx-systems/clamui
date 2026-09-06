# ClamUI Save Page Tests
"""Unit tests for the SavePage class."""

from unittest import mock

import pytest


class TestSavePageImport:
    """Tests for importing the SavePage."""

    def test_import_save_page(self, mock_gi_modules):
        """Test that SavePage can be imported."""
        from src.ui.preferences.save_page import SavePage

        assert SavePage is not None

    def test_save_page_is_class(self, mock_gi_modules):
        """Test that SavePage is a class."""
        from src.ui.preferences.save_page import SavePage

        assert isinstance(SavePage, type)

    def test_save_page_inherits_from_mixin(self, mock_gi_modules):
        """Test that SavePage inherits from PreferencesPageMixin."""
        from src.ui.preferences.base import PreferencesPageMixin
        from src.ui.preferences.save_page import SavePage

        assert issubclass(SavePage, PreferencesPageMixin)


class TestSavePageCreation:
    """Tests for SavePage.create_page() method."""

    @pytest.fixture
    def mock_window(self):
        """Provide a mock PreferencesWindow."""
        return mock.MagicMock()

    @pytest.fixture
    def mock_configs(self):
        """Provide mock config objects."""
        freshclam_config = mock.MagicMock()
        clamd_config = mock.MagicMock()
        return freshclam_config, clamd_config

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        return manager

    @pytest.fixture
    def mock_scheduler(self):
        """Provide a mock scheduler."""
        scheduler = mock.MagicMock()
        return scheduler

    @pytest.fixture
    def mock_widgets(self):
        """Provide mock widget dictionaries."""
        return {}, {}, {}, {}

    @pytest.fixture
    def save_page(
        self,
        mock_gi_modules,
        mock_window,
        mock_configs,
        mock_settings_manager,
        mock_scheduler,
        mock_widgets,
    ):
        """Create a SavePage instance with mocks."""
        from src.ui.preferences.save_page import SavePage

        freshclam_config, clamd_config = mock_configs
        freshclam_widgets, clamd_widgets, onaccess_widgets, scheduled_widgets = mock_widgets

        return SavePage(
            window=mock_window,
            freshclam_config=freshclam_config,
            clamd_config=clamd_config,
            freshclam_conf_path="/etc/clamav/freshclam.conf",
            clamd_conf_path="/etc/clamav/clamd.conf",
            clamd_available=True,
            settings_manager=mock_settings_manager,
            scheduler=mock_scheduler,
            freshclam_widgets=freshclam_widgets,
            clamd_widgets=clamd_widgets,
            onaccess_widgets=onaccess_widgets,
            scheduled_widgets=scheduled_widgets,
        )

    def test_create_page_returns_preferences_page(self, mock_gi_modules, save_page):
        """Test create_page returns an Adw.PreferencesPage."""
        adw = mock_gi_modules["adw"]

        save_page.create_page()

        # Should create a PreferencesPage
        adw.PreferencesPage.assert_called()

    def test_create_page_sets_title_and_icon(self, mock_gi_modules, save_page):
        """Test create_page sets correct title and icon."""
        adw = mock_gi_modules["adw"]

        save_page.create_page()

        # Should set title and icon_name
        adw.PreferencesPage.assert_called_with(
            title="Save & Apply",
            icon_name="document-save-symbolic",
        )

    def test_create_page_creates_preference_groups(self, mock_gi_modules, save_page):
        """Test create_page creates preference groups."""
        adw = mock_gi_modules["adw"]

        save_page.create_page()

        # Should create 2 PreferencesGroups (info and button)
        assert adw.PreferencesGroup.call_count == 2

    def test_create_page_creates_info_rows(self, mock_gi_modules, save_page):
        """Test create_page creates info rows."""
        adw = mock_gi_modules["adw"]

        save_page.create_page()

        # Should create 2 ActionRows for info (auto-save and manual save)
        assert adw.ActionRow.call_count >= 2

    def test_create_page_creates_save_button(self, mock_gi_modules, save_page):
        """Test create_page creates save button."""
        gtk = mock_gi_modules["gtk"]

        save_page.create_page()

        # Should create a Button
        gtk.Button.assert_called()

    def test_create_page_save_button_has_suggested_action_style(self, mock_gi_modules, save_page):
        """Test save button has suggested-action CSS class."""
        gtk = mock_gi_modules["gtk"]
        mock_button = mock.MagicMock()
        gtk.Button.return_value = mock_button

        save_page.create_page()

        # Should add suggested-action CSS class
        mock_button.add_css_class.assert_called_with("suggested-action")

    def test_create_page_save_button_has_label(self, mock_gi_modules, save_page):
        """Test save button has correct label."""
        gtk = mock_gi_modules["gtk"]
        mock_button = mock.MagicMock()
        gtk.Button.return_value = mock_button

        save_page.create_page()

        # Should set label
        mock_button.set_label.assert_called_with("Save & Apply")

    def test_create_page_save_button_connects_signal(self, mock_gi_modules, save_page):
        """Test save button connects clicked signal."""
        gtk = mock_gi_modules["gtk"]
        mock_button = mock.MagicMock()
        gtk.Button.return_value = mock_button

        save_page.create_page()

        # Should connect clicked signal
        mock_button.connect.assert_called_with("clicked", save_page._on_save_clicked)

    def test_create_page_creates_info_icons(self, mock_gi_modules, save_page):
        """Test create_page creates info icons."""
        gtk = mock_gi_modules["gtk"]

        save_page.create_page()

        # Should create Image widgets for icons (success and warning)
        assert gtk.Image.new_from_icon_name.call_count >= 2

    @staticmethod
    def _record_action_rows(adw):
        """Make Adw.ActionRow() append every instance it builds to a list so
        their set_subtitle() calls can be inspected afterwards (the fixture
        otherwise returns a throwaway mock per call). Returns that list."""
        rows: list = []

        def _make(*_args, **_kwargs):
            row = mock.MagicMock()
            rows.append(row)
            return row

        adw.ActionRow.side_effect = _make
        return rows

    @staticmethod
    def _subtitles(rows):
        return [c.args[0] for row in rows for c in row.set_subtitle.call_args_list]

    def test_create_page_mentions_admin_permission_when_not_root(self, mock_gi_modules, save_page):
        """When not root, the manual-save row warns about the pkexec prompt."""
        rows = self._record_action_rows(mock_gi_modules["adw"])

        with mock.patch("src.core.privileged_paths.is_running_as_root", return_value=False):
            save_page.create_page()

        assert any("administrator permission" in s for s in self._subtitles(rows))

    def test_create_page_omits_admin_permission_when_root(self, mock_gi_modules, save_page):
        """Running as root, no config write needs pkexec, so the manual-save row
        drops the 'you will be asked for administrator permission' wording."""
        rows = self._record_action_rows(mock_gi_modules["adw"])

        with mock.patch("src.core.privileged_paths.is_running_as_root", return_value=True):
            save_page.create_page()

        assert not any("administrator permission" in s for s in self._subtitles(rows))


class TestSavePageSaveClicked:
    """Tests for SavePage._on_save_clicked() method."""

    @pytest.fixture
    def mock_window(self):
        """Provide a mock PreferencesWindow."""
        return mock.MagicMock()

    @pytest.fixture
    def mock_configs(self):
        """Provide mock config objects."""
        freshclam_config = mock.MagicMock()
        clamd_config = mock.MagicMock()
        return freshclam_config, clamd_config

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        return manager

    @pytest.fixture
    def mock_scheduler(self):
        """Provide a mock scheduler."""
        scheduler = mock.MagicMock()
        return scheduler

    @pytest.fixture
    def mock_widgets(self):
        """Provide mock widget dictionaries with required widgets."""
        freshclam_widgets = {}
        clamd_widgets = {}
        onaccess_widgets = {}
        scheduled_widgets = {}
        return freshclam_widgets, clamd_widgets, onaccess_widgets, scheduled_widgets

    @pytest.fixture
    def save_page(
        self,
        mock_gi_modules,
        mock_window,
        mock_configs,
        mock_settings_manager,
        mock_scheduler,
        mock_widgets,
    ):
        """Create a SavePage instance with mocks."""
        from src.ui.preferences.save_page import SavePage

        freshclam_config, clamd_config = mock_configs
        freshclam_widgets, clamd_widgets, onaccess_widgets, scheduled_widgets = mock_widgets

        return SavePage(
            window=mock_window,
            freshclam_config=freshclam_config,
            clamd_config=clamd_config,
            freshclam_conf_path="/etc/clamav/freshclam.conf",
            clamd_conf_path="/etc/clamav/clamd.conf",
            clamd_available=True,
            settings_manager=mock_settings_manager,
            scheduler=mock_scheduler,
            freshclam_widgets=freshclam_widgets,
            clamd_widgets=clamd_widgets,
            onaccess_widgets=onaccess_widgets,
            scheduled_widgets=scheduled_widgets,
        )

    def test_save_clicked_sets_saving_flag(self, mock_gi_modules, save_page):
        """Test _on_save_clicked sets _is_saving flag."""
        mock_button = mock.MagicMock()

        with mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(True, None),
                        ):
                            with mock.patch("src.ui.preferences.save_page.threading.Thread"):
                                save_page._on_save_clicked(mock_button)

                                # Should set _is_saving to True
                                assert save_page._is_saving is True

    def test_save_clicked_disables_button(self, mock_gi_modules, save_page):
        """Test _on_save_clicked disables save button."""
        mock_button = mock.MagicMock()

        with mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(True, None),
                        ):
                            with mock.patch("src.ui.preferences.save_page.threading.Thread"):
                                save_page._on_save_clicked(mock_button)

                                # Should disable button
                                mock_button.set_sensitive.assert_called_with(False)

    def test_save_clicked_prevents_multiple_saves(self, mock_gi_modules, save_page):
        """Test _on_save_clicked prevents multiple simultaneous saves."""
        mock_button = mock.MagicMock()
        save_page._is_saving = True

        save_page._on_save_clicked(mock_button)

        # Should return early without disabling button again
        mock_button.set_sensitive.assert_not_called()

    def test_save_clicked_collects_data_from_all_pages(self, mock_gi_modules, save_page):
        """Test _on_save_clicked collects data from all pages."""
        mock_button = mock.MagicMock()

        with mock.patch(
            "src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}
        ) as mock_db:
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ) as mock_scanner:
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ) as mock_onaccess:
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ) as mock_scheduled:
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(True, None),
                        ):
                            with mock.patch("src.ui.preferences.save_page.threading.Thread"):
                                save_page._on_save_clicked(mock_button)

                                # Should collect data from all pages
                                mock_db.assert_called_once()
                                mock_scanner.assert_called_once()
                                mock_onaccess.assert_called_once()
                                mock_scheduled.assert_called_once()

    def test_save_clicked_validates_freshclam_config(self, mock_gi_modules, save_page):
        """Test _on_save_clicked validates freshclam config."""
        mock_button = mock.MagicMock()

        with mock.patch(
            "src.ui.preferences.save_page.DatabasePage.collect_data",
            return_value={"DatabaseDirectory": "/var/lib/clamav"},
        ):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(True, None),
                        ) as mock_validate:
                            with mock.patch("src.ui.preferences.save_page.threading.Thread"):
                                save_page._on_save_clicked(mock_button)

                                # Should validate freshclam config
                                mock_validate.assert_called()

    def test_save_clicked_validates_clamd_config(self, mock_gi_modules, save_page):
        """Test _on_save_clicked validates clamd config."""
        mock_button = mock.MagicMock()

        with mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data",
                return_value={"MaxFileSize": "100M"},
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(True, None),
                        ) as mock_validate:
                            with mock.patch("src.ui.preferences.save_page.threading.Thread"):
                                save_page._on_save_clicked(mock_button)

                                # Should validate clamd config
                                assert mock_validate.call_count >= 1

    def test_save_clicked_shows_error_on_validation_failure(self, mock_gi_modules, save_page):
        """Test _on_save_clicked shows error dialog on validation failure."""
        mock_button = mock.MagicMock()

        with mock.patch(
            "src.ui.preferences.save_page.DatabasePage.collect_data",
            return_value={"DatabaseDirectory": "/invalid"},
        ):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(False, "Invalid path"),
                        ):
                            with mock.patch.object(save_page, "_show_error_dialog") as mock_error:
                                save_page._on_save_clicked(mock_button)

                                # Should show error dialog
                                mock_error.assert_called_once()

    def test_save_clicked_re_enables_button_on_validation_failure(self, mock_gi_modules, save_page):
        """Test _on_save_clicked re-enables button on validation failure."""
        mock_button = mock.MagicMock()

        with mock.patch(
            "src.ui.preferences.save_page.DatabasePage.collect_data",
            return_value={"DatabaseDirectory": "/invalid"},
        ):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(False, "Invalid path"),
                        ):
                            with mock.patch.object(save_page, "_show_error_dialog"):
                                save_page._on_save_clicked(mock_button)

                                # Should re-enable button after error
                                assert mock_button.set_sensitive.call_count == 2
                                mock_button.set_sensitive.assert_called_with(True)

    def test_save_clicked_resets_saving_flag_on_validation_failure(
        self, mock_gi_modules, save_page
    ):
        """Test _on_save_clicked resets _is_saving flag on validation failure."""
        mock_button = mock.MagicMock()

        with mock.patch(
            "src.ui.preferences.save_page.DatabasePage.collect_data",
            return_value={"DatabaseDirectory": "/invalid"},
        ):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(False, "Invalid path"),
                        ):
                            with mock.patch.object(save_page, "_show_error_dialog"):
                                save_page._on_save_clicked(mock_button)

                                # Should reset _is_saving to False
                                assert save_page._is_saving is False

    def test_save_clicked_spawns_background_thread(self, mock_gi_modules, save_page):
        """Test _on_save_clicked spawns background thread for save."""
        mock_button = mock.MagicMock()

        with mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(True, None),
                        ):
                            with mock.patch(
                                "src.ui.preferences.save_page.threading.Thread"
                            ) as mock_thread:
                                save_page._on_save_clicked(mock_button)

                                # Should create a thread
                                mock_thread.assert_called_once()

    def test_save_clicked_spawns_daemon_thread(self, mock_gi_modules, save_page):
        """Test _on_save_clicked spawns daemon thread."""
        mock_button = mock.MagicMock()

        with mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(True, None),
                        ):
                            with mock.patch(
                                "src.ui.preferences.save_page.threading.Thread"
                            ) as mock_thread:
                                mock_thread_instance = mock.MagicMock()
                                mock_thread.return_value = mock_thread_instance

                                save_page._on_save_clicked(mock_button)

                                # Should set daemon = True
                                assert mock_thread_instance.daemon is True

    def test_save_clicked_starts_background_thread(self, mock_gi_modules, save_page):
        """Test _on_save_clicked starts the background thread."""
        mock_button = mock.MagicMock()

        with mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}):
            with mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}
            ):
                with mock.patch(
                    "src.ui.preferences.save_page.OnAccessPage.collect_data",
                    return_value={},
                ):
                    with mock.patch(
                        "src.ui.preferences.save_page.ScheduledPage.collect_data",
                        return_value={},
                    ):
                        with mock.patch(
                            "src.ui.preferences.save_page.validate_config",
                            return_value=(True, None),
                        ):
                            with mock.patch(
                                "src.ui.preferences.save_page.threading.Thread"
                            ) as mock_thread:
                                mock_thread_instance = mock.MagicMock()
                                mock_thread.return_value = mock_thread_instance

                                save_page._on_save_clicked(mock_button)

                                # Should start the thread
                                mock_thread_instance.start.assert_called_once()


class TestSavePageSaveConfigsThread:
    """Tests for SavePage._save_configs_thread() method."""

    @staticmethod
    def _real_clamd_config():
        """Return an empty real clamd config for persistence assertions."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig

        return ClamAVConfig(file_path=Path("/etc/clamav/clamd.conf"))

    @pytest.fixture
    def mock_window(self):
        """Provide a mock PreferencesWindow."""
        return mock.MagicMock()

    @pytest.fixture
    def mock_configs(self):
        """Provide mock config objects."""
        freshclam_config = mock.MagicMock()
        clamd_config = mock.MagicMock()
        return freshclam_config, clamd_config

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.save.return_value = True
        return manager

    @pytest.fixture
    def mock_scheduler(self):
        """Provide a mock scheduler."""
        scheduler = mock.MagicMock()
        scheduler.enable_schedule.return_value = (True, None)
        scheduler.disable_schedule.return_value = (True, None)
        return scheduler

    @pytest.fixture
    def mock_widgets(self):
        """Provide mock widget dictionaries."""
        return {}, {}, {}, {}

    @pytest.fixture
    def save_page(
        self,
        mock_gi_modules,
        mock_window,
        mock_configs,
        mock_settings_manager,
        mock_scheduler,
        mock_widgets,
    ):
        """Create a SavePage instance with mocks."""
        from src.ui.preferences.save_page import SavePage

        freshclam_config, clamd_config = mock_configs
        freshclam_widgets, clamd_widgets, onaccess_widgets, scheduled_widgets = mock_widgets

        return SavePage(
            window=mock_window,
            freshclam_config=freshclam_config,
            clamd_config=clamd_config,
            freshclam_conf_path="/etc/clamav/freshclam.conf",
            clamd_conf_path="/etc/clamav/clamd.conf",
            clamd_available=True,
            settings_manager=mock_settings_manager,
            scheduler=mock_scheduler,
            freshclam_widgets=freshclam_widgets,
            clamd_widgets=clamd_widgets,
            onaccess_widgets=onaccess_widgets,
            scheduled_widgets=scheduled_widgets,
        )

    def test_save_configs_thread_backs_up_configs(self, mock_gi_modules, save_page):
        """Test _save_configs_thread backs up configuration files."""
        mock_button = mock.MagicMock()

        with mock.patch("src.ui.preferences.save_page.backup_config") as mock_backup:
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, {}, {}, {}, mock_button)

                    # Should backup both configs
                    assert mock_backup.call_count == 2
                    mock_backup.assert_any_call("/etc/clamav/freshclam.conf")
                    mock_backup.assert_any_call("/etc/clamav/clamd.conf")

    def test_save_configs_thread_no_changes_reports_no_changes(self, mock_gi_modules, save_page):
        """No updates collected -> honest 'No Changes' message, not a phantom
        success (one way the Flatpak bug #136 surfaced)."""
        mock_button = mock.MagicMock()

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib") as mock_glib:
                    save_page._save_configs_thread({}, {}, {}, {}, mock_button)

        # Nothing was written...
        mock_write.assert_not_called()
        # ...and the dialog reports "No Changes", not a phantom "Configuration Saved".
        # (idle_add is also used to re-enable the button, so filter to dialog calls.)
        dialog_calls = [
            c
            for c in mock_glib.idle_add.call_args_list
            if c.args and c.args[0] == save_page._show_success_dialog
        ]
        assert len(dialog_calls) == 1
        assert "No Changes" in dialog_calls[0].args[1]

    def test_save_configs_thread_skips_unchanged_materialized_config(
        self, mock_gi_modules, save_page
    ):
        """Materialized config-backed pages do not force a helper when unchanged."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue

        mock_button = mock.MagicMock()
        config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        config.raw_lines = ["DatabaseDirectory /var/lib/clamav\n"]
        config.values = {
            "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav", line_number=1)]
        }
        save_page._window._freshclam_config = config

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib") as mock_glib:
                    save_page._save_configs_thread(
                        {"DatabaseDirectory": "/var/lib/clamav"},
                        {},
                        {},
                        {},
                        mock_button,
                    )

        mock_write.assert_not_called()
        dialog_calls = [
            c
            for c in mock_glib.idle_add.call_args_list
            if c.args and c.args[0] == save_page._show_success_dialog
        ]
        assert len(dialog_calls) == 1
        assert "No Changes" in dialog_calls[0].args[1]

    def test_flatpak_clamscan_missing_helper_fails_without_retargeting_clamd_config(
        self, mock_gi_modules, save_page, mock_settings_manager
    ):
        """Clamscan mode must fail closed when the host writer is unavailable."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue

        mock_button = mock.MagicMock()
        host_path = Path("/etc/clamav/clamd.conf")
        clamd_config = ClamAVConfig(file_path=host_path)
        clamd_config.raw_lines = ["MaxFileSize 50M\n"]
        clamd_config.values = {"MaxFileSize": [ClamAVConfigValue(value="50M", line_number=1)]}
        save_page._window._clamd_config = clamd_config
        save_page._window._clamd_conf_path = str(host_path)
        mock_settings_manager.get.side_effect = lambda key, default=None: (
            "clamscan" if key == "scan_backend" else default
        )
        glib = mock_gi_modules["glib"]

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch("src.ui.preferences.save_page.is_flatpak", return_value=True),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(False, "host helper not installed"),
            ) as mock_write,
        ):
            save_page._save_configs_thread({}, {"MaxFileSize": "100M"}, {}, {}, mock_button)

        mock_write.assert_called_once()
        written_config = mock_write.call_args.args[0][0]
        assert written_config.file_path == host_path
        assert written_config.get_value("MaxFileSize") == "100M"
        mock_settings_manager.set.assert_not_called()
        mock_settings_manager.save.assert_not_called()
        assert save_page._clamd_conf_path == str(host_path)
        assert save_page._window._clamd_conf_path == str(host_path)
        assert save_page._window._clamd_config is clamd_config
        glib.idle_add.assert_any_call(save_page._show_error_dialog, "Save Failed", mock.ANY)
        assert not any(
            call.args and call.args[0] == save_page._show_success_dialog
            for call in glib.idle_add.call_args_list
        )

    def test_flatpak_auto_without_clamd_missing_helper_fails_without_retargeting_config(
        self, mock_gi_modules, save_page, mock_settings_manager
    ):
        """Auto mode without clamd must retain the host config destination on failure."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue

        mock_button = mock.MagicMock()
        host_path = Path("/etc/clamav/clamd.conf")
        clamd_config = ClamAVConfig(file_path=host_path)
        clamd_config.raw_lines = ["MaxFileSize 50M\n"]
        clamd_config.values = {"MaxFileSize": [ClamAVConfigValue(value="50M", line_number=1)]}
        save_page._clamd_available = False
        save_page._window._clamd_config = clamd_config
        save_page._window._clamd_conf_path = str(host_path)
        mock_settings_manager.get.side_effect = lambda key, default=None: (
            "auto" if key == "scan_backend" else default
        )
        glib = mock_gi_modules["glib"]

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch("src.ui.preferences.save_page.is_flatpak", return_value=True),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(False, "host helper not installed"),
            ) as mock_write,
        ):
            save_page._save_configs_thread({}, {"MaxFileSize": "100M"}, {}, {}, mock_button)

        mock_write.assert_called_once()
        written_config = mock_write.call_args.args[0][0]
        assert written_config.file_path == host_path
        assert written_config.get_value("MaxFileSize") == "100M"
        mock_settings_manager.set.assert_not_called()
        mock_settings_manager.save.assert_not_called()
        assert save_page._clamd_conf_path == str(host_path)
        assert save_page._window._clamd_conf_path == str(host_path)
        assert save_page._window._clamd_config is clamd_config
        glib.idle_add.assert_any_call(save_page._show_error_dialog, "Save Failed", mock.ANY)
        assert not any(
            call.args and call.args[0] == save_page._show_success_dialog
            for call in glib.idle_add.call_args_list
        )

    def test_save_configs_thread_with_changes_reports_success(self, mock_gi_modules, save_page):
        """A main-thread callback reports success after a successful config write."""
        mock_button = mock.MagicMock()
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}
        show_success = mock.MagicMock()
        save_page._show_success_dialog = show_success
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
        ):
            save_page._save_configs_thread(freshclam_updates, {}, {}, {}, mock_button)

        show_success.assert_not_called()
        commit_callback, commit_args = idle_callbacks[0]
        commit_callback(*commit_args)
        show_success.assert_not_called()
        success_callback, success_args = idle_callbacks[1]
        success_callback(*success_args)
        show_success.assert_called_once()

    def test_save_configs_thread_warning_commits_configs_and_reports_warning(
        self, mock_gi_modules, save_page
    ):
        """A successful write warning commits candidates and replaces normal success."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue

        mock_button = mock.MagicMock()
        live_config = ClamAVConfig(
            file_path=Path("/etc/clamav/freshclam.conf"),
            values={
                "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav-old", line_number=1)]
            },
            raw_lines=["DatabaseDirectory /var/lib/clamav-old\n"],
        )
        save_page._window._freshclam_config = live_config
        show_success = mock.MagicMock()
        save_page._show_success_dialog = show_success
        idle_callbacks = []
        warning = "Configuration was applied, but staging cleanup failed for /tmp/staging: denied"

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, warning),
            ),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
        ):
            save_page._save_configs_thread(
                {"DatabaseDirectory": "/var/lib/clamav"}, {}, {}, {}, mock_button
            )

        assert save_page._window._freshclam_config is live_config
        commit_callback, commit_args = idle_callbacks[0]
        commit_callback(*commit_args)
        assert (
            save_page._window._freshclam_config.get_value("DatabaseDirectory") == "/var/lib/clamav"
        )

        warning_callback, warning_args = idle_callbacks[1]
        warning_callback(*warning_args)
        show_success.assert_called_once_with(
            "Configuration Saved with Warning",
            f"Configuration saved with a warning:\n\n{warning}",
        )
        assert show_success.call_args.args[0] != "Configuration Saved"

    def test_save_configs_thread_saves_freshclam_config(self, mock_gi_modules, save_page):
        """A successful write commits the freshclam proposal, not the live config."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue

        mock_button = mock.MagicMock()
        live_config = ClamAVConfig(
            file_path=Path("/etc/clamav/freshclam.conf"),
            values={
                "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav-old", line_number=1)]
            },
            raw_lines=["DatabaseDirectory /var/lib/clamav-old\n"],
        )
        save_page._window._freshclam_config = live_config
        written_proposals = []
        idle_callbacks = []

        def assert_uncommitted_before_write(configs):
            assert len(configs) == 1
            proposal = configs[0]
            written_proposals.append(proposal)
            assert proposal is not live_config
            assert proposal.file_path == Path("/etc/clamav/freshclam.conf")
            assert proposal.get_value("DatabaseDirectory") == "/var/lib/clamav"
            assert live_config.get_value("DatabaseDirectory") == "/var/lib/clamav-old"
            assert save_page._window._freshclam_config is live_config
            return (True, None)

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return 1

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                side_effect=assert_uncommitted_before_write,
            ),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
        ):
            save_page._save_configs_thread(
                {"DatabaseDirectory": "/var/lib/clamav"}, {}, {}, {}, mock_button
            )

        assert save_page._window._freshclam_config is live_config
        commit_callback, commit_args = idle_callbacks[0]
        assert commit_args == ()
        commit_callback()
        assert save_page._window._freshclam_config is written_proposals[0]

    def test_save_configs_thread_saves_clamd_config(self, mock_gi_modules, save_page):
        """Test _save_configs_thread saves clamd.conf."""
        mock_button = mock.MagicMock()
        clamd_updates = {"MaxFileSize": "100M"}
        save_page._window._clamd_config = self._real_clamd_config()

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, clamd_updates, {}, {}, mock_button)

                    written_config = mock_write.call_args.args[0][0]
                    assert written_config.get_value("MaxFileSize") == "100M"

    def test_save_configs_thread_writes_both_configs_in_single_call(
        self, mock_gi_modules, save_page
    ):
        """The writer receives both changed config proposals in one batch."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig

        mock_button = mock.MagicMock()
        live_freshclam_config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        live_clamd_config = ClamAVConfig(file_path=Path("/etc/clamav/clamd.conf"))
        save_page._window._freshclam_config = live_freshclam_config
        save_page._window._clamd_config = live_clamd_config

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write,
            mock.patch("src.ui.preferences.save_page.GLib"),
        ):
            save_page._save_configs_thread(
                {"DatabaseDirectory": "/var/lib/clamav"},
                {"MaxFileSize": "100M"},
                {},
                {},
                mock_button,
            )

        mock_write.assert_called_once()
        written_by_path = {config.file_path: config for config in mock_write.call_args.args[0]}
        assert set(written_by_path) == {
            Path("/etc/clamav/freshclam.conf"),
            Path("/etc/clamav/clamd.conf"),
        }
        freshclam_proposal = written_by_path[Path("/etc/clamav/freshclam.conf")]
        clamd_proposal = written_by_path[Path("/etc/clamav/clamd.conf")]
        assert freshclam_proposal is not live_freshclam_config
        assert clamd_proposal is not live_clamd_config
        assert freshclam_proposal.get_value("DatabaseDirectory") == "/var/lib/clamav"
        assert clamd_proposal.get_value("MaxFileSize") == "100M"

    def test_save_configs_thread_commits_configs_once_before_success_on_main_thread(
        self, mock_gi_modules, save_page
    ):
        """Config proposals commit once before the main-thread success callback."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig

        mock_button = mock.MagicMock()
        live_freshclam_config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        live_clamd_config = ClamAVConfig(file_path=Path("/etc/clamav/clamd.conf"))
        save_page._window._freshclam_config = live_freshclam_config
        save_page._window._clamd_config = live_clamd_config
        show_success = mock.MagicMock()
        save_page._show_success_dialog = show_success
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write,
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
        ):
            save_page._save_configs_thread(
                {"DatabaseDirectory": "/var/lib/clamav"},
                {"MaxFileSize": "100M"},
                {},
                {},
                mock_button,
            )

        written_freshclam_config, written_clamd_config = mock_write.call_args.args[0]
        assert save_page._window._freshclam_config is live_freshclam_config
        assert save_page._window._clamd_config is live_clamd_config
        show_success.assert_not_called()

        assert len(idle_callbacks) == 3
        commit_callback, commit_args = idle_callbacks[0]
        commit_callback(*commit_args)

        assert save_page._window._freshclam_config is written_freshclam_config
        assert save_page._window._clamd_config is written_clamd_config
        show_success.assert_not_called()

        success_callback, success_args = idle_callbacks[1]
        success_callback(*success_args)
        show_success.assert_called_once()

        # Re-enabling the button is a separate UI operation.
        assert idle_callbacks[2] == (mock_button.set_sensitive, (True,))

    def test_save_configs_thread_saves_onaccess_settings(self, mock_gi_modules, save_page):
        """Test _save_configs_thread saves on-access settings to clamd.conf."""
        mock_button = mock.MagicMock()
        onaccess_updates = {"OnAccessIncludePath": ["/home"]}
        save_page._window._clamd_config = self._real_clamd_config()

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, {}, onaccess_updates, {}, mock_button)

                    written_config = mock_write.call_args.args[0][0]
                    assert written_config.get_values("OnAccessIncludePath") == ["/home"]

    def test_save_configs_thread_combines_scanner_and_onaccess(self, mock_gi_modules, save_page):
        """Test _save_configs_thread combines scanner and on-access settings."""
        mock_button = mock.MagicMock()
        clamd_updates = {"MaxFileSize": "100M"}
        onaccess_updates = {"OnAccessIncludePath": ["/home"]}
        save_page._window._clamd_config = self._real_clamd_config()

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread(
                        {}, clamd_updates, onaccess_updates, {}, mock_button
                    )

                    written_config = mock_write.call_args.args[0][0]
                    assert written_config.get_value("MaxFileSize") == "100M"
                    assert written_config.get_values("OnAccessIncludePath") == ["/home"]

    def test_save_configs_thread_saves_scheduled_settings(self, mock_gi_modules, save_page):
        """Test _save_configs_thread saves scheduled scan settings."""
        mock_button = mock.MagicMock()
        scheduled_updates = {
            "scheduled_scans_enabled": False,
            "schedule_frequency": "daily",
            "schedule_time": "02:00",
            "schedule_targets": ["/home"],
            "schedule_day_of_week": "Monday",
            "schedule_day_of_month": 1,
            "schedule_skip_on_battery": True,
            "schedule_auto_quarantine": False,
        }

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, {}, {}, scheduled_updates, mock_button)

                    save_page._settings_manager.set_many.assert_called_once_with(scheduled_updates)
                    save_page._settings_manager.set.assert_not_called()
                    save_page._settings_manager.save.assert_not_called()

    def test_save_configs_thread_does_not_apply_schedule_after_batch_persistence_failure(
        self, mock_gi_modules, save_page
    ):
        """A failed batch leaves every durable schedule value and scheduler state unchanged."""

        class OneKeyFailingSettingsManager:
            def __init__(self, durable_values, failing_key):
                self._durable_values = durable_values.copy()
                self._failing_key = failing_key
                self.set = mock.MagicMock(side_effect=self._set)
                self.set_many = mock.MagicMock(side_effect=self._set_many)
                self.save = mock.MagicMock(return_value=True)

            def _set(self, key, value):
                self._durable_values[key] = value
                return key != self._failing_key

            def _set_many(self, updates):
                if self._failing_key in updates:
                    return False
                self._durable_values.update(updates)
                return True

            def get(self, key, default=None):
                return self._durable_values.get(key, default)

        mock_button = mock.MagicMock()
        scheduled_updates = {
            "scheduled_scans_enabled": True,
            "schedule_frequency": "daily",
            "schedule_time": "03:30",
            "schedule_targets": ["/home"],
            "schedule_day_of_week": 2,
            "schedule_day_of_month": 15,
            "schedule_skip_on_battery": False,
            "schedule_auto_quarantine": True,
        }
        original_values = {
            "scheduled_scans_enabled": False,
            "schedule_frequency": "weekly",
            "schedule_time": "02:00",
            "schedule_targets": ["/original"],
            "schedule_day_of_week": 0,
            "schedule_day_of_month": 1,
            "schedule_skip_on_battery": True,
            "schedule_auto_quarantine": False,
        }
        settings_manager = OneKeyFailingSettingsManager(original_values, "schedule_targets")
        save_page._settings_manager = settings_manager
        show_success = mock.MagicMock()
        save_page._show_success_dialog = show_success
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        with mock.patch(
            "src.ui.preferences.save_page.GLib.idle_add",
            side_effect=capture_idle_callback,
        ):
            save_page._save_configs_thread({}, {}, {}, scheduled_updates, mock_button)

        settings_manager.set_many.assert_called_once_with(scheduled_updates)
        settings_manager.set.assert_not_called()
        settings_manager.save.assert_not_called()
        assert {key: settings_manager.get(key) for key in original_values} == original_values
        save_page._scheduler.enable_schedule.assert_not_called()
        save_page._scheduler.disable_schedule.assert_not_called()
        assert not any(callback is show_success for callback, _args in idle_callbacks)

    def test_save_configs_thread_enables_scheduler(self, mock_gi_modules, save_page):
        """Test _save_configs_thread enables scheduler when enabled."""
        mock_button = mock.MagicMock()
        scheduled_updates = {
            "scheduled_scans_enabled": True,
            "schedule_frequency": "daily",
            "schedule_time": "02:00",
            "schedule_targets": ["/home"],
            "schedule_day_of_week": "Monday",
            "schedule_day_of_month": 1,
            "schedule_skip_on_battery": True,
            "schedule_auto_quarantine": False,
        }

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, {}, {}, scheduled_updates, mock_button)

                    # Should enable scheduler
                    save_page._scheduler.enable_schedule.assert_called_once()

    def test_save_configs_thread_disables_scheduler(self, mock_gi_modules, save_page):
        """Test _save_configs_thread disables scheduler when disabled."""
        mock_button = mock.MagicMock()
        scheduled_updates = {
            "scheduled_scans_enabled": False,
            "schedule_frequency": "daily",
            "schedule_time": "02:00",
            "schedule_targets": ["/home"],
            "schedule_day_of_week": "Monday",
            "schedule_day_of_month": 1,
            "schedule_skip_on_battery": True,
            "schedule_auto_quarantine": False,
        }

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ),
            mock.patch("src.ui.preferences.save_page.GLib"),
        ):
            save_page._save_configs_thread({}, {}, {}, scheduled_updates, mock_button)

        save_page._scheduler.disable_schedule.assert_called_once()

    def test_save_configs_thread_shows_success_dialog(self, mock_gi_modules, save_page):
        """The main-thread callback reports the success message for config changes."""
        mock_button = mock.MagicMock()
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}
        show_success = mock.MagicMock()
        save_page._show_success_dialog = show_success
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
        ):
            save_page._save_configs_thread(freshclam_updates, {}, {}, {}, mock_button)

        commit_callback, commit_args = idle_callbacks[0]
        commit_callback(*commit_args)
        show_success.assert_not_called()
        success_callback, success_args = idle_callbacks[1]
        success_callback(*success_args)
        show_success.assert_called_once_with(
            "Configuration Saved",
            "Configuration saved. Active ClamAV services were restarted where needed.",
        )

    def test_save_configs_thread_shows_error_on_write_failure(self, mock_gi_modules, save_page):
        """Test _save_configs_thread shows error on write failure."""
        mock_button = mock.MagicMock()
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}
        glib = mock_gi_modules["glib"]

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(False, "Permission denied"),
            ):
                save_page._save_configs_thread(freshclam_updates, {}, {}, {}, mock_button)

                glib.idle_add.assert_any_call(
                    save_page._show_error_dialog,
                    "Save Failed",
                    mock.ANY,
                )
                assert not any(
                    call.args and call.args[0] == save_page._show_success_dialog
                    for call in glib.idle_add.call_args_list
                )

    def test_save_configs_thread_shows_error_on_batch_settings_persistence_failure(
        self, mock_gi_modules, save_page
    ):
        """Test _save_configs_thread shows an error when the settings batch fails."""
        mock_button = mock.MagicMock()
        scheduled_updates = {
            "scheduled_scans_enabled": False,
            "schedule_frequency": "daily",
            "schedule_time": "02:00",
            "schedule_targets": ["/home"],
            "schedule_day_of_week": "Monday",
            "schedule_day_of_month": 1,
            "schedule_skip_on_battery": True,
            "schedule_auto_quarantine": False,
        }
        glib = mock_gi_modules["glib"]
        save_page._settings_manager.set_many.return_value = False

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                save_page._save_configs_thread({}, {}, {}, scheduled_updates, mock_button)

                glib.idle_add.assert_any_call(
                    save_page._show_error_dialog,
                    "Save Failed",
                    mock.ANY,
                )
                assert not any(
                    call.args and call.args[0] == save_page._show_success_dialog
                    for call in glib.idle_add.call_args_list
                )

    def test_save_configs_thread_shows_error_on_scheduler_enable_failure(
        self, mock_gi_modules, save_page
    ):
        """Test _save_configs_thread shows error on scheduler enable failure."""
        mock_button = mock.MagicMock()
        scheduled_updates = {
            "scheduled_scans_enabled": True,
            "schedule_frequency": "daily",
            "schedule_time": "02:00",
            "schedule_targets": ["/home"],
            "schedule_day_of_week": "Monday",
            "schedule_day_of_month": 1,
            "schedule_skip_on_battery": True,
            "schedule_auto_quarantine": False,
        }
        glib = mock_gi_modules["glib"]

        save_page._scheduler.enable_schedule.return_value = (False, "Scheduler error")

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                save_page._save_configs_thread({}, {}, {}, scheduled_updates, mock_button)

                glib.idle_add.assert_any_call(
                    save_page._show_error_dialog,
                    "Changes Partially Applied",
                    mock.ANY,
                )
                error_call = next(
                    call
                    for call in glib.idle_add.call_args_list
                    if call.args and call.args[0] == save_page._show_error_dialog
                )
                assert "Scheduled scan preferences" in error_call.args[2]
                assert "Scheduler error" in error_call.args[2]
                assert "Review your settings and save again." in error_call.args[2]
                assert not any(
                    call.args and call.args[0] == save_page._show_success_dialog
                    for call in glib.idle_add.call_args_list
                )

    def test_save_configs_thread_commits_written_config_when_scheduler_disable_fails(
        self, mock_gi_modules, save_page
    ):
        """A later scheduler failure cannot leave durable config changes stale in memory."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig

        mock_button = mock.MagicMock()
        live_config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        save_page._window._freshclam_config = live_config
        save_page._settings_manager.set_many.return_value = True
        save_page._scheduler.disable_schedule.return_value = (False, "Scheduler error")
        show_error = mock.MagicMock()
        show_success = mock.MagicMock()
        save_page._show_error_dialog = show_error
        save_page._show_success_dialog = show_success
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write,
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
        ):
            save_page._save_configs_thread(
                {"DatabaseDirectory": "/var/lib/clamav"},
                {},
                {},
                {"scheduled_scans_enabled": False},
                mock_button,
            )

        written_config = mock_write.call_args.args[0][0]
        assert save_page._window._freshclam_config is live_config
        assert len(idle_callbacks) == 3

        commit_callback, commit_args = idle_callbacks[0]
        commit_callback(*commit_args)
        assert save_page._window._freshclam_config is written_config

        error_callback, error_args = idle_callbacks[1]
        error_callback(*error_args)
        show_error.assert_called_once_with(
            "Changes Partially Applied",
            "The following changes were saved before another change failed:\n"
            "ClamAV configuration files, Scheduled scan preferences\n\n"
            "Error: Failed to disable scheduled scans: Scheduler error\n\n"
            "Review your settings and save again.",
        )
        show_success.assert_not_called()

    def test_save_configs_thread_re_enables_button_on_success(self, mock_gi_modules, save_page):
        """Test _save_configs_thread re-enables button on success."""
        mock_button = mock.MagicMock()
        glib = mock_gi_modules["glib"]

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                save_page._save_configs_thread({}, {}, {}, {}, mock_button)

                # Should call GLib.idle_add to re-enable button
                glib.idle_add.assert_any_call(mock_button.set_sensitive, True)

    def test_save_configs_thread_re_enables_button_on_error(self, mock_gi_modules, save_page):
        """Test _save_configs_thread re-enables button on error."""
        mock_button = mock.MagicMock()
        glib = mock_gi_modules["glib"]

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(False, "Error"),
            ):
                save_page._save_configs_thread({}, {}, {}, {}, mock_button)

                # Should call GLib.idle_add to re-enable button
                glib.idle_add.assert_any_call(mock_button.set_sensitive, True)

    def test_save_configs_thread_resets_saving_flag_on_success(self, mock_gi_modules, save_page):
        """Test _save_configs_thread resets _is_saving flag on success."""
        mock_button = mock.MagicMock()
        save_page._is_saving = True

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, {}, {}, {}, mock_button)

                    # Should reset _is_saving to False
                    assert save_page._is_saving is False

    def test_save_configs_thread_resets_saving_flag_on_error(self, mock_gi_modules, save_page):
        """Test _save_configs_thread resets _is_saving flag on error."""
        mock_button = mock.MagicMock()
        save_page._is_saving = True

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(False, "Error"),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, {}, {}, {}, mock_button)

                    # Should reset _is_saving to False
                    assert save_page._is_saving is False

    def test_save_configs_thread_stores_scheduler_error(self, mock_gi_modules, save_page):
        """Test _save_configs_thread stores scheduler error on freshclam write failure."""
        mock_button = mock.MagicMock()

        # Pass non-empty freshclam_updates to trigger the write path
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(False, "Write failed"),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread(freshclam_updates, {}, {}, {}, mock_button)

                    # Should store error message
                    assert save_page._scheduler_error is not None
                    assert "Write failed" in save_page._scheduler_error


class TestSavePageWindowConfigAccess:
    """Tests for SavePage accessing config from window instead of storing its own copy."""

    def test_save_page_accesses_window_freshclam_config(self, mock_gi_modules):
        """SavePage should access window's freshclam_config, not store its own copy."""
        from src.ui.preferences.save_page import SavePage

        # Create mock window with configs (simulating _load_configs() populating them)
        mock_window = mock.MagicMock()
        mock_window._freshclam_config = mock.MagicMock()
        mock_window._clamd_config = None

        # Create SavePage with None configs (simulating the initialization order bug)
        save_page = SavePage(
            window=mock_window,
            freshclam_config=None,  # Bug: passing None at init time
            clamd_config=None,
            freshclam_conf_path="/etc/clamav/freshclam.conf",
            clamd_conf_path="/etc/clamav/clamd.conf",
            clamd_available=False,
            settings_manager=mock.MagicMock(),
            scheduler=mock.MagicMock(),
            freshclam_widgets={},
            clamd_widgets={},
            onaccess_widgets={},
            scheduled_widgets={},
        )

        # Verify SavePage can access window's config (not its own None copy)
        # This should NOT raise AttributeError
        assert save_page._window._freshclam_config is not None
        assert save_page._window._freshclam_config == mock_window._freshclam_config

    def test_save_page_accesses_window_clamd_config(self, mock_gi_modules):
        """SavePage should access window's clamd_config, not store its own copy."""
        from src.ui.preferences.save_page import SavePage

        # Create mock window with configs
        mock_window = mock.MagicMock()
        mock_window._freshclam_config = None
        mock_window._clamd_config = mock.MagicMock()

        # Create SavePage with None configs
        save_page = SavePage(
            window=mock_window,
            freshclam_config=None,
            clamd_config=None,
            freshclam_conf_path="/etc/clamav/freshclam.conf",
            clamd_conf_path="/etc/clamav/clamd.conf",
            clamd_available=True,
            settings_manager=mock.MagicMock(),
            scheduler=mock.MagicMock(),
            freshclam_widgets={},
            clamd_widgets={},
            onaccess_widgets={},
            scheduled_widgets={},
        )

        # Verify SavePage can access window's config
        assert save_page._window._clamd_config is not None
        assert save_page._window._clamd_config == mock_window._clamd_config

    def test_save_page_validation_uses_window_config(self, mock_gi_modules):
        """Validation receives a proposal based on the window's freshclam config."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue
        from src.ui.preferences.save_page import SavePage

        mock_window = mock.MagicMock()
        live_config = ClamAVConfig(
            file_path=Path("/etc/clamav/freshclam.conf"),
            values={
                "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav-old", line_number=1)]
            },
            raw_lines=["DatabaseDirectory /var/lib/clamav-old\n"],
        )
        mock_window._freshclam_config = live_config

        save_page = SavePage(
            window=mock_window,
            freshclam_config=None,
            clamd_config=None,
            freshclam_conf_path="/etc/clamav/freshclam.conf",
            clamd_conf_path="/etc/clamav/clamd.conf",
            clamd_available=False,
            settings_manager=mock.MagicMock(),
            scheduler=mock.MagicMock(),
            freshclam_widgets={},
            clamd_widgets={},
            onaccess_widgets={},
            scheduled_widgets={},
        )

        mock_button = mock.MagicMock()

        with (
            mock.patch(
                "src.ui.preferences.save_page.DatabasePage.collect_data",
                return_value={"DatabaseDirectory": "/var/lib/clamav"},
            ),
            mock.patch("src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.OnAccessPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.ScheduledPage.collect_data", return_value={}),
            mock.patch(
                "src.ui.preferences.save_page.validate_config",
                return_value=(True, None),
            ) as mock_validate,
            mock.patch("src.ui.preferences.save_page.threading.Thread"),
        ):
            save_page._on_save_clicked(mock_button)

        validated_proposal = mock_validate.call_args.args[0]
        assert validated_proposal is not live_config
        assert validated_proposal.file_path == Path("/etc/clamav/freshclam.conf")
        assert validated_proposal.get_value("DatabaseDirectory") == "/var/lib/clamav"
        assert mock_window._freshclam_config is live_config
        assert live_config.get_value("DatabaseDirectory") == "/var/lib/clamav-old"

    def test_save_page_save_thread_uses_window_config(self, mock_gi_modules):
        """The save worker writes then commits a proposal based on the window config."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue
        from src.ui.preferences.save_page import SavePage

        mock_window = mock.MagicMock()
        live_config = ClamAVConfig(
            file_path=Path("/etc/clamav/freshclam.conf"),
            values={
                "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav-old", line_number=1)]
            },
            raw_lines=["DatabaseDirectory /var/lib/clamav-old\n"],
        )
        mock_window._freshclam_config = live_config

        save_page = SavePage(
            window=mock_window,
            freshclam_config=None,
            clamd_config=None,
            freshclam_conf_path="/etc/clamav/freshclam.conf",
            clamd_conf_path="/etc/clamav/clamd.conf",
            clamd_available=False,
            settings_manager=mock.MagicMock(),
            scheduler=mock.MagicMock(),
            freshclam_widgets={},
            clamd_widgets={},
            onaccess_widgets={},
            scheduled_widgets={},
        )

        written_proposals = []
        idle_callbacks = []

        def assert_uncommitted_before_write(configs):
            assert len(configs) == 1
            proposal = configs[0]
            written_proposals.append(proposal)
            assert proposal is not live_config
            assert proposal.file_path == Path("/etc/clamav/freshclam.conf")
            assert proposal.get_value("DatabaseDirectory") == "/var/lib/clamav"
            assert mock_window._freshclam_config is live_config
            assert live_config.get_value("DatabaseDirectory") == "/var/lib/clamav-old"
            return (True, None)

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return 1

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                side_effect=assert_uncommitted_before_write,
            ),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
        ):
            save_page._save_configs_thread(
                {"DatabaseDirectory": "/var/lib/clamav"}, {}, {}, {}, mock.MagicMock()
            )

        assert mock_window._freshclam_config is live_config
        commit_callback, commit_args = idle_callbacks[0]
        assert commit_args == ()
        commit_callback()
        assert mock_window._freshclam_config is written_proposals[0]


class _InlineSaveThread:
    """``threading.Thread`` stand-in that runs the save worker inline.

    ``_on_save_clicked`` hands the write off to a background thread; running
    that worker inline keeps the hand-off deterministic while still exercising
    the real ``_save_configs_thread`` body and the real writer boundary.
    """

    def __init__(self, target, args=(), kwargs=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self.daemon = False

    def start(self):
        self._target(*self._args, **self._kwargs)


class TestSavePageProspectiveConfigValidation:
    """Save must validate the config it is about to write (issue #181).

    Validating the stored clamd.conf before the collected updates are applied
    has two user-visible failures: an out-of-range value already on disk blocks
    the very edit that repairs it, and an out-of-range edit is written because
    the pre-update config still looked valid.
    """

    @staticmethod
    def _clamd_config(max_recursion):
        """Real clamd config holding a single MaxRecursion line."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue

        return ClamAVConfig(
            file_path=Path("/etc/clamav/clamd.conf"),
            values={"MaxRecursion": [ClamAVConfigValue(value=max_recursion, line_number=1)]},
            raw_lines=[f"MaxRecursion {max_recursion}\n"],
        )

    @staticmethod
    def _error_messages(glib, error_dialog):
        """Error text surfaced directly or handed to the main loop."""
        messages = [call.args[1] for call in error_dialog.call_args_list if len(call.args) > 1]
        messages.extend(
            call.args[2]
            for call in glib.idle_add.call_args_list
            if call.args and call.args[0] is error_dialog and len(call.args) > 2
        )
        return messages

    @pytest.fixture
    def save_page(self, mock_gi_modules):
        """SavePage backed by a real clamd config so validation really runs."""
        from src.ui.preferences.save_page import SavePage

        window = mock.MagicMock()
        window._freshclam_config = None
        window._clamd_config = None
        settings_manager = mock.MagicMock()
        settings_manager.save.return_value = True

        return SavePage(
            window=window,
            freshclam_config=None,
            clamd_config=None,
            freshclam_conf_path="/etc/clamav/freshclam.conf",
            clamd_conf_path="/etc/clamav/clamd.conf",
            clamd_available=True,
            settings_manager=settings_manager,
            scheduler=mock.MagicMock(),
            freshclam_widgets={},
            clamd_widgets={},
            onaccess_widgets={},
            scheduled_widgets={},
        )

    def test_stale_out_of_range_max_recursion_is_repaired_by_valid_edit(
        self, mock_gi_modules, save_page
    ):
        """A stored MaxRecursion=255 must not block the edit that corrects it."""
        glib = mock_gi_modules["glib"]
        button = mock.MagicMock()
        live_config = self._clamd_config("255")
        save_page._window._clamd_config = live_config
        written = []
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        def fake_write(configs):
            written.extend(configs)
            return (True, None)

        with (
            mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}),
            mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data",
                return_value={"MaxRecursion": "100"},
            ),
            mock.patch("src.ui.preferences.save_page.OnAccessPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.ScheduledPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch("src.ui.preferences.save_page.is_flatpak", return_value=False),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                side_effect=fake_write,
            ),
            mock.patch("src.ui.preferences.save_page.threading.Thread", _InlineSaveThread),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
            mock.patch.object(save_page, "_show_error_dialog") as error_dialog,
            mock.patch.object(save_page, "_show_success_dialog") as success_dialog,
        ):
            save_page._on_save_clicked(button)

            # The correcting edit is accepted, not rejected because of the stale value.
            assert self._error_messages(glib, error_dialog) == []

            # ...and the corrected value reaches the writer.
            assert len(written) == 1
            assert str(written[0].file_path) == "/etc/clamav/clamd.conf"
            assert written[0].get_value("MaxRecursion") == "100"
            assert "MaxRecursion 100" in written[0].to_string()
            assert save_page._window._clamd_config is live_config

            commit_callback, commit_args = idle_callbacks[0]
            commit_callback(*commit_args)

            assert save_page._window._clamd_config is written[0]
            success_dialog.assert_not_called()
            success_callback, success_args = idle_callbacks[1]
            success_callback(*success_args)
            success_dialog.assert_called_once()
            assert "Configuration Saved" in success_dialog.call_args.args[0]

    def test_out_of_range_max_recursion_edit_is_rejected_before_any_write(
        self, mock_gi_modules, save_page
    ):
        """A collected MaxRecursion=101 never reaches the config or the writer."""
        glib = mock_gi_modules["glib"]
        button = mock.MagicMock()
        clamd_config = self._clamd_config("17")
        save_page._window._clamd_config = clamd_config
        before = clamd_config.to_string()

        with (
            mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}),
            mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data",
                return_value={"MaxRecursion": "101"},
            ),
            mock.patch("src.ui.preferences.save_page.OnAccessPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.ScheduledPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch("src.ui.preferences.save_page.is_flatpak", return_value=False),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write,
            mock.patch("src.ui.preferences.save_page.threading.Thread", _InlineSaveThread),
            mock.patch.object(save_page, "_show_error_dialog") as error_dialog,
        ):
            save_page._on_save_clicked(button)

        # Nothing is persisted...
        mock_write.assert_not_called()

        # ...the live config is left exactly as it was...
        assert clamd_config.get_value("MaxRecursion") == "17"
        assert clamd_config.to_string() == before

        # ...and the rejection names the offending option.
        messages = self._error_messages(glib, error_dialog)
        assert any("MaxRecursion" in message for message in messages)

    def test_writer_failure_leaves_live_clamd_config_unchanged(self, mock_gi_modules, save_page):
        """A failed write must not commit the validated proposal in memory."""
        button = mock.MagicMock()
        clamd_config = self._clamd_config("17")
        save_page._window._clamd_config = clamd_config
        before = clamd_config.to_string()

        with (
            mock.patch("src.ui.preferences.save_page.DatabasePage.collect_data", return_value={}),
            mock.patch(
                "src.ui.preferences.save_page.ScannerPage.collect_data",
                return_value={"MaxRecursion": "100"},
            ),
            mock.patch("src.ui.preferences.save_page.OnAccessPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.ScheduledPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch("src.ui.preferences.save_page.is_flatpak", return_value=False),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(False, "write failed"),
            ),
            mock.patch("src.ui.preferences.save_page.threading.Thread", _InlineSaveThread),
        ):
            save_page._on_save_clicked(button)

        assert save_page._window._clamd_config is clamd_config
        assert clamd_config.get_value("MaxRecursion") == "17"
        assert clamd_config.to_string() == before

    @staticmethod
    def _freshclam_config(value, key="DatabaseDirectory"):
        """Real freshclam config holding a single option line."""
        from pathlib import Path

        from src.core.clamav_config import ClamAVConfig, ClamAVConfigValue

        return ClamAVConfig(
            file_path=Path("/etc/clamav/freshclam.conf"),
            values={key: [ClamAVConfigValue(value=value, line_number=1)]},
            raw_lines=[f"{key} {value}\n"],
        )

    def test_invalid_freshclam_edit_is_rejected_before_writer_or_thread(
        self, mock_gi_modules, save_page
    ):
        """A collected Checks=51 is rejected without changing the loaded config."""
        glib = mock_gi_modules["glib"]
        button = mock.MagicMock()
        freshclam_config = self._freshclam_config("12", key="Checks")
        save_page._window._freshclam_config = freshclam_config
        before = freshclam_config.to_string()

        with (
            mock.patch(
                "src.ui.preferences.save_page.DatabasePage.collect_data",
                return_value={"Checks": "51"},
            ),
            mock.patch("src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.OnAccessPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.ScheduledPage.collect_data", return_value={}),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write,
            mock.patch("src.ui.preferences.save_page.threading.Thread") as mock_thread,
            mock.patch.object(save_page, "_show_error_dialog") as error_dialog,
        ):
            save_page._on_save_clicked(button)

        mock_thread.assert_not_called()
        mock_write.assert_not_called()
        assert save_page._window._freshclam_config is freshclam_config
        assert freshclam_config.get_value("Checks") == "12"
        assert freshclam_config.to_string() == before
        assert any("Checks" in message for message in self._error_messages(glib, error_dialog))

    def test_stale_invalid_freshclam_value_is_repaired_in_written_proposal(
        self, mock_gi_modules, save_page
    ):
        """A valid Checks repair validates and persists the repaired proposal."""
        glib = mock_gi_modules["glib"]
        button = mock.MagicMock()
        freshclam_config = self._freshclam_config("51", key="Checks")
        save_page._window._freshclam_config = freshclam_config
        written = []
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        def fake_write(configs):
            written.extend(configs)
            return (True, None)

        with (
            mock.patch(
                "src.ui.preferences.save_page.DatabasePage.collect_data",
                return_value={"Checks": "12"},
            ),
            mock.patch("src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.OnAccessPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.ScheduledPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch("src.ui.preferences.save_page.is_flatpak", return_value=False),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                side_effect=fake_write,
            ),
            mock.patch("src.ui.preferences.save_page.threading.Thread", _InlineSaveThread),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
            mock.patch.object(save_page, "_show_error_dialog") as error_dialog,
            mock.patch.object(save_page, "_show_success_dialog") as success_dialog,
        ):
            save_page._on_save_clicked(button)

            assert self._error_messages(glib, error_dialog) == []
            assert len(written) == 1
            proposal = written[0]
            assert proposal is not freshclam_config
            assert str(proposal.file_path) == "/etc/clamav/freshclam.conf"
            assert proposal.get_value("Checks") == "12"
            assert proposal.to_string() == "Checks 12\n"
            assert save_page._window._freshclam_config is freshclam_config
            assert freshclam_config.get_value("Checks") == "51"

            commit_callback, commit_args = idle_callbacks[0]
            commit_callback(*commit_args)

            assert save_page._window._freshclam_config is proposal
            success_dialog.assert_not_called()
            success_callback, success_args = idle_callbacks[1]
            success_callback(*success_args)
            success_dialog.assert_called_once()
            assert "Configuration Saved" in success_dialog.call_args.args[0]

    def test_failed_freshclam_write_retries_without_mutating_live_config(
        self, mock_gi_modules, save_page
    ):
        """A helper recovery retries the original freshclam proposal."""
        from pathlib import Path

        glib = mock_gi_modules["glib"]
        button = mock.MagicMock()
        host_path = Path("/etc/clamav/freshclam.conf")
        freshclam_config = self._freshclam_config("/var/lib/clamav")
        save_page._window._freshclam_config = freshclam_config
        before = freshclam_config.to_string()
        writes = []
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        def fake_write(configs):
            writes.append(configs)
            if len(writes) == 1:
                return (False, "host helper not installed")
            return (True, None)

        with (
            mock.patch(
                "src.ui.preferences.save_page.DatabasePage.collect_data",
                return_value={"DatabaseDirectory": "/srv/clamav"},
            ),
            mock.patch("src.ui.preferences.save_page.ScannerPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.OnAccessPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.ScheduledPage.collect_data", return_value={}),
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch("src.ui.preferences.save_page.is_flatpak", return_value=True),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                side_effect=fake_write,
            ),
            mock.patch("src.ui.preferences.save_page.threading.Thread", _InlineSaveThread),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
            mock.patch.object(save_page, "_show_error_dialog") as error_dialog,
            mock.patch.object(save_page, "_show_success_dialog") as success_dialog,
        ):
            save_page._on_save_clicked(button)

            assert save_page._window._freshclam_config is freshclam_config
            assert freshclam_config.get_value("DatabaseDirectory") == "/var/lib/clamav"
            assert freshclam_config.to_string() == before
            assert len(writes) == 1
            assert any(
                "host helper not installed" in message
                for message in self._error_messages(glib, error_dialog)
            )

            callbacks_before_retry = len(idle_callbacks)
            save_page._on_save_clicked(button)

            assert len(writes) == 2
            retry_proposal = writes[1][0]
            assert retry_proposal is not freshclam_config
            assert retry_proposal.file_path == host_path
            assert retry_proposal.get_value("DatabaseDirectory") == "/srv/clamav"
            assert save_page._window._freshclam_config is freshclam_config
            assert freshclam_config.get_value("DatabaseDirectory") == "/var/lib/clamav"
            assert freshclam_config.to_string() == before

            retry_commit_callback, retry_commit_args = idle_callbacks[callbacks_before_retry]
            retry_commit_callback(*retry_commit_args)

            assert save_page._window._freshclam_config is retry_proposal
            assert (
                save_page._window._freshclam_config.get_value("DatabaseDirectory") == "/srv/clamav"
            )
            assert (
                save_page._window._freshclam_config.to_string() == "DatabaseDirectory /srv/clamav\n"
            )
            success_dialog.assert_not_called()
            retry_success_callback, retry_success_args = idle_callbacks[callbacks_before_retry + 1]
            retry_success_callback(*retry_success_args)
            success_dialog.assert_called_once()
            assert "Configuration Saved" in success_dialog.call_args.args[0]

    def test_flatpak_host_write_commits_proposal_without_retargeting_config(
        self, mock_gi_modules, save_page
    ):
        """A successful Flatpak host write keeps the real clamd.conf path live."""
        from pathlib import Path

        button = mock.MagicMock()
        host_path = Path("/etc/clamav/clamd.conf")
        live_config = self._clamd_config("17")
        save_page._window._clamd_config = live_config
        save_page._window._clamd_conf_path = str(host_path)
        save_page._settings_manager.get.return_value = "clamscan"
        proposal = save_page._prospective_clamd_config({"MaxRecursion": "100"}, {})
        written = []
        idle_callbacks = []

        def capture_idle_callback(callback, *args):
            idle_callbacks.append((callback, args))
            return len(idle_callbacks)

        def fake_write(configs):
            written.extend(configs)
            return (True, None)

        with (
            mock.patch("src.ui.preferences.save_page.backup_config"),
            mock.patch("src.ui.preferences.save_page.is_flatpak", return_value=True),
            mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                side_effect=fake_write,
            ),
            mock.patch(
                "src.ui.preferences.save_page.GLib.idle_add",
                side_effect=capture_idle_callback,
            ),
            mock.patch.object(save_page, "_show_success_dialog") as success_dialog,
        ):
            save_page._save_configs_thread(
                {},
                {"MaxRecursion": "100"},
                {},
                {},
                button,
                proposal,
            )

            assert len(written) == 1
            assert written[0].file_path == host_path
            assert written[0].get_value("MaxRecursion") == "100"
            save_page._settings_manager.set.assert_not_called()
            save_page._settings_manager.save.assert_not_called()
            assert save_page._window._clamd_config is live_config

            commit_callback, commit_args = idle_callbacks[0]
            commit_callback(*commit_args)
            success_dialog.assert_not_called()
            success_callback, success_args = idle_callbacks[1]
            success_callback(*success_args)
            success_dialog.assert_called_once()
            assert save_page._clamd_conf_path == str(host_path)
            assert save_page._window._clamd_conf_path == str(host_path)
            assert save_page._window._clamd_config.file_path == host_path
            assert save_page._window._clamd_config.get_value("MaxRecursion") == "100"
