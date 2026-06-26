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
        scheduler.disable_schedule.return_value = None
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

    def test_save_configs_thread_with_changes_reports_success(self, mock_gi_modules, save_page):
        """When changes are actually applied, the success message is shown."""
        mock_button = mock.MagicMock()
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib") as mock_glib:
                    save_page._save_configs_thread(freshclam_updates, {}, {}, {}, mock_button)

        dialog_calls = [
            c
            for c in mock_glib.idle_add.call_args_list
            if c.args and c.args[0] == save_page._show_success_dialog
        ]
        assert len(dialog_calls) == 1
        assert "Configuration Saved" in dialog_calls[0].args[1]

    def test_save_configs_thread_saves_freshclam_config(self, mock_gi_modules, save_page):
        """Test _save_configs_thread saves freshclam.conf."""
        mock_button = mock.MagicMock()
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread(freshclam_updates, {}, {}, {}, mock_button)

                    # Should set values on window's freshclam config
                    save_page._window._freshclam_config.set_value.assert_called_with(
                        "DatabaseDirectory", "/var/lib/clamav"
                    )

                    # Should write freshclam config
                    mock_write.assert_called()

    def test_save_configs_thread_saves_clamd_config(self, mock_gi_modules, save_page):
        """Test _save_configs_thread saves clamd.conf."""
        mock_button = mock.MagicMock()
        clamd_updates = {"MaxFileSize": "100M"}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, clamd_updates, {}, {}, mock_button)

                    # Should set values on window's clamd config
                    save_page._window._clamd_config.set_value.assert_called_with(
                        "MaxFileSize", "100M"
                    )

                    # Should write clamd config
                    mock_write.assert_called()

    def test_save_configs_thread_writes_both_configs_in_single_call(
        self, mock_gi_modules, save_page
    ):
        """Test _save_configs_thread batches freshclam and clamd writes into one call."""
        mock_button = mock.MagicMock()
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}
        clamd_updates = {"MaxFileSize": "100M"}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread(
                        freshclam_updates,
                        clamd_updates,
                        {},
                        {},
                        mock_button,
                    )

                    mock_write.assert_called_once()
                    written_configs = mock_write.call_args.args[0]
                    assert written_configs == [
                        save_page._window._freshclam_config,
                        save_page._window._clamd_config,
                    ]

    def test_save_configs_thread_saves_onaccess_settings(self, mock_gi_modules, save_page):
        """Test _save_configs_thread saves on-access settings to clamd.conf."""
        mock_button = mock.MagicMock()
        onaccess_updates = {"OnAccessIncludePath": ["/home"]}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, {}, onaccess_updates, {}, mock_button)

                    # List values use add_value (after clearing existing) instead of set_value
                    save_page._window._clamd_config.add_value.assert_called_with(
                        "OnAccessIncludePath", "/home"
                    )

    def test_save_configs_thread_combines_scanner_and_onaccess(self, mock_gi_modules, save_page):
        """Test _save_configs_thread combines scanner and on-access settings."""
        mock_button = mock.MagicMock()
        clamd_updates = {"MaxFileSize": "100M"}
        onaccess_updates = {"OnAccessIncludePath": ["/home"]}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ) as mock_write:
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread(
                        {}, clamd_updates, onaccess_updates, {}, mock_button
                    )

                    # Scalar values use set_value
                    save_page._window._clamd_config.set_value.assert_any_call("MaxFileSize", "100M")
                    # List values use add_value (after clearing existing)
                    save_page._window._clamd_config.add_value.assert_any_call(
                        "OnAccessIncludePath", "/home"
                    )

                    # Should write clamd config once
                    mock_write.assert_called()

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

                    # Should set values on settings manager
                    assert save_page._settings_manager.set.call_count == len(scheduled_updates)

                    # Should save settings
                    save_page._settings_manager.save.assert_called_once()

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

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread({}, {}, {}, scheduled_updates, mock_button)

                    # Should disable scheduler
                    save_page._scheduler.disable_schedule.assert_called_once()

    def test_save_configs_thread_shows_success_dialog(self, mock_gi_modules, save_page):
        """Test _save_configs_thread shows success dialog when changes are applied."""
        mock_button = mock.MagicMock()
        glib = mock_gi_modules["glib"]
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                save_page._save_configs_thread(freshclam_updates, {}, {}, {}, mock_button)

                # Should call GLib.idle_add with _show_success_dialog
                glib.idle_add.assert_any_call(
                    save_page._show_success_dialog,
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

                # Should call GLib.idle_add with _show_error_dialog
                glib.idle_add.assert_any_call(
                    save_page._show_error_dialog,
                    "Save Failed",
                    mock.ANY,
                )

    def test_save_configs_thread_shows_error_on_settings_save_failure(
        self, mock_gi_modules, save_page
    ):
        """Test _save_configs_thread shows error on settings save failure."""
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

        save_page._settings_manager.save.return_value = False

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                save_page._save_configs_thread({}, {}, {}, scheduled_updates, mock_button)

                # Should call GLib.idle_add with _show_error_dialog
                glib.idle_add.assert_any_call(
                    save_page._show_error_dialog,
                    "Save Failed",
                    mock.ANY,
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

                # Should call GLib.idle_add with _show_error_dialog
                glib.idle_add.assert_any_call(
                    save_page._show_error_dialog,
                    "Save Failed",
                    mock.ANY,
                )

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
        """SavePage validation should check window's config, not stored copy."""
        from src.ui.preferences.save_page import SavePage

        # Create mock window with valid config
        mock_window = mock.MagicMock()
        mock_freshclam_config = mock.MagicMock()
        mock_window._freshclam_config = mock_freshclam_config

        # Create SavePage with None config (simulating bug)
        save_page = SavePage(
            window=mock_window,
            freshclam_config=None,  # Bug: None at init
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

        # Simulate save with freshclam updates
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

                                # Validation should use window's config (not None)
                                mock_validate.assert_called_with(mock_window._freshclam_config)

    def test_save_page_save_thread_uses_window_config(self, mock_gi_modules):
        """SavePage save thread should use window's config for set_value calls."""
        from src.ui.preferences.save_page import SavePage

        # Create mock window with configs
        mock_window = mock.MagicMock()
        mock_freshclam_config = mock.MagicMock()
        mock_window._freshclam_config = mock_freshclam_config

        # Create SavePage with None config
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
        freshclam_updates = {"DatabaseDirectory": "/var/lib/clamav"}

        with mock.patch("src.ui.preferences.save_page.backup_config"):
            with mock.patch(
                "src.ui.preferences.save_page.write_configs_with_elevation",
                return_value=(True, None),
            ):
                with mock.patch("src.ui.preferences.save_page.GLib"):
                    save_page._save_configs_thread(freshclam_updates, {}, {}, {}, mock_button)

                    # Should call set_value on window's config (not None)
                    mock_window._freshclam_config.set_value.assert_called_with(
                        "DatabaseDirectory", "/var/lib/clamav"
                    )
