# ClamUI Behavior Page Tests
"""
Tests for the BehaviorPage preferences component.
"""

import sys
from unittest.mock import MagicMock


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


class TestBehaviorPageImport:
    """Test that BehaviorPage can be imported correctly."""

    def test_import_behavior_page(self, mock_gi_modules):
        """Test that BehaviorPage can be imported."""
        from src.ui.preferences.behavior_page import BehaviorPage

        assert BehaviorPage is not None
        _clear_src_modules()


class TestBehaviorPageInit:
    """Test BehaviorPage initialization."""

    def test_init_with_settings_manager(self, mock_gi_modules):
        """Test initialization with settings manager."""
        settings_manager = MagicMock()

        from src.ui.preferences.behavior_page import BehaviorPage

        page = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        assert page._settings_manager is settings_manager
        assert page._tray_available is True
        _clear_src_modules()

    def test_init_without_settings_manager(self, mock_gi_modules):
        """Test initialization without settings manager."""
        from src.ui.preferences.behavior_page import BehaviorPage

        page = BehaviorPage()

        assert page._settings_manager is None
        assert page._tray_available is False
        _clear_src_modules()

    def test_init_tray_not_available(self, mock_gi_modules):
        """Test initialization with tray not available."""
        settings_manager = MagicMock()

        from src.ui.preferences.behavior_page import BehaviorPage

        page = BehaviorPage(settings_manager=settings_manager, tray_available=False)

        assert page._tray_available is False
        _clear_src_modules()


class TestBehaviorPageCreatePage:
    """Test BehaviorPage.create_page() method."""

    def test_create_page_returns_preferences_page(self, mock_gi_modules):
        """Test create_page returns an Adw.PreferencesPage."""
        adw = mock_gi_modules["adw"]
        mock_page = MagicMock()
        adw.PreferencesPage.return_value = mock_page

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(tray_available=True)
        page_instance.create_page()

        adw.PreferencesPage.assert_called()
        _clear_src_modules()

    def test_create_page_sets_title_and_icon(self, mock_gi_modules):
        """Test create_page sets appropriate title and icon."""
        adw = mock_gi_modules["adw"]

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(tray_available=True)
        page_instance.create_page()

        # Check PreferencesPage was created with expected args
        call_kwargs = adw.PreferencesPage.call_args[1]
        assert call_kwargs["title"] == "Behavior"
        assert call_kwargs["icon_name"] == "preferences-system-symbolic"
        _clear_src_modules()

    def test_create_page_with_tray_available(self, mock_gi_modules):
        """Test create_page creates window behavior group when tray available."""
        adw = mock_gi_modules["adw"]
        mock_page = MagicMock()
        mock_group = MagicMock()
        adw.PreferencesPage.return_value = mock_page
        adw.PreferencesGroup.return_value = mock_group

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(tray_available=True)
        page_instance.create_page()

        # Should create a preferences group for window behavior
        adw.PreferencesGroup.assert_called()
        mock_page.add.assert_called()
        _clear_src_modules()

    def test_create_page_without_tray_shows_info(self, mock_gi_modules):
        """Test create_page shows info message when tray not available."""
        adw = mock_gi_modules["adw"]
        mock_page = MagicMock()
        mock_group = MagicMock()
        adw.PreferencesPage.return_value = mock_page
        adw.PreferencesGroup.return_value = mock_group

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(tray_available=False)
        page_instance.create_page()

        # Should create groups: info group for window behavior + scan behavior group
        adw.PreferencesGroup.assert_called()
        # Window Behavior info group should be created first (when tray not available)
        # then Scan Behavior group is always added
        all_title_calls = [call[0][0] for call in mock_group.set_title.call_args_list]
        assert "Window Behavior" in all_title_calls
        assert "Scan Behavior" in all_title_calls
        _clear_src_modules()


class TestBehaviorPageStartMinimized:
    """Test the start-in-system-tray preference."""

    def test_load_start_minimized_updates_row_without_saving(self, mock_gi_modules):
        """Loading the saved value must not trigger the change handler."""
        settings_manager = MagicMock()
        settings_manager.get.return_value = True

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)
        mock_row = MagicMock()
        page_instance._start_minimized_row = mock_row
        page_instance._start_minimized_handler_id = 17

        page_instance._load_start_minimized()

        settings_manager.get.assert_called_once_with("start_minimized", False)
        mock_row.handler_block.assert_called_once_with(17)
        mock_row.set_active.assert_called_once_with(True)
        mock_row.handler_unblock.assert_called_once_with(17)
        settings_manager.set.assert_not_called()
        _clear_src_modules()

    def test_start_minimized_change_is_persisted(self, mock_gi_modules):
        """Changing the switch must persist the user-visible behavior."""
        settings_manager = MagicMock()

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)
        mock_row = MagicMock()
        mock_row.get_active.return_value = True

        page_instance._on_start_minimized_changed(mock_row, None)

        settings_manager.set.assert_called_once_with("start_minimized", True)
        _clear_src_modules()


class TestBehaviorPageCloseBehaviorOption:
    """Test close behavior ComboRow functionality."""

    def test_close_behavior_options_defined(self, mock_gi_modules):
        """Test that close behavior options are properly defined."""
        from src.ui.preferences.behavior_page import BehaviorPage

        assert BehaviorPage.CLOSE_BEHAVIOR_OPTIONS == ["minimize", "quit", "ask"]
        assert BehaviorPage.CLOSE_BEHAVIOR_LABELS == [
            "Minimize to tray",
            "Quit completely",
            "Always ask",
        ]
        _clear_src_modules()

    def test_load_close_behavior_minimize(self, mock_gi_modules):
        """Test loading close_behavior='minimize' setting."""
        settings_manager = MagicMock()
        settings_manager.get.return_value = "minimize"

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        # Create mock ComboRow
        mock_row = MagicMock()
        page_instance._close_behavior_row = mock_row

        page_instance._load_close_behavior()

        # "minimize" is index 0
        mock_row.set_selected.assert_called_with(0)
        _clear_src_modules()

    def test_load_close_behavior_quit(self, mock_gi_modules):
        """Test loading close_behavior='quit' setting."""
        settings_manager = MagicMock()
        settings_manager.get.return_value = "quit"

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        # Create mock ComboRow
        mock_row = MagicMock()
        page_instance._close_behavior_row = mock_row

        page_instance._load_close_behavior()

        # "quit" is index 1
        mock_row.set_selected.assert_called_with(1)
        _clear_src_modules()

    def test_load_close_behavior_ask(self, mock_gi_modules):
        """Test loading close_behavior='ask' setting."""
        settings_manager = MagicMock()
        settings_manager.get.return_value = "ask"

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        # Create mock ComboRow
        mock_row = MagicMock()
        page_instance._close_behavior_row = mock_row

        page_instance._load_close_behavior()

        # "ask" is index 2
        mock_row.set_selected.assert_called_with(2)
        _clear_src_modules()

    def test_load_close_behavior_none_defaults_to_ask(self, mock_gi_modules):
        """Test that None close_behavior defaults to 'ask'."""
        settings_manager = MagicMock()
        settings_manager.get.return_value = None

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        # Create mock ComboRow
        mock_row = MagicMock()
        page_instance._close_behavior_row = mock_row

        page_instance._load_close_behavior()

        # None defaults to "ask" (index 2)
        mock_row.set_selected.assert_called_with(2)
        _clear_src_modules()

    def test_on_close_behavior_changed_saves_setting(self, mock_gi_modules):
        """Test that changing close behavior saves the setting."""
        settings_manager = MagicMock()

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        # Create mock row that returns selected index 0 (minimize)
        mock_row = MagicMock()
        mock_row.get_selected.return_value = 0

        page_instance._on_close_behavior_changed(mock_row, None)

        settings_manager.set.assert_called_with("close_behavior", "minimize")
        _clear_src_modules()

    def test_on_close_behavior_changed_to_quit(self, mock_gi_modules):
        """Test that changing to quit saves correct setting."""
        settings_manager = MagicMock()

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        # Create mock row that returns selected index 1 (quit)
        mock_row = MagicMock()
        mock_row.get_selected.return_value = 1

        page_instance._on_close_behavior_changed(mock_row, None)

        settings_manager.set.assert_called_with("close_behavior", "quit")
        _clear_src_modules()

    def test_on_close_behavior_changed_to_ask(self, mock_gi_modules):
        """Test that changing to ask saves correct setting."""
        settings_manager = MagicMock()

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        # Create mock row that returns selected index 2 (ask)
        mock_row = MagicMock()
        mock_row.get_selected.return_value = 2

        page_instance._on_close_behavior_changed(mock_row, None)

        settings_manager.set.assert_called_with("close_behavior", "ask")
        _clear_src_modules()

    def test_on_close_behavior_changed_no_settings_manager(self, mock_gi_modules):
        """Test that change does nothing without settings manager."""
        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=None, tray_available=True)

        # Create mock row
        mock_row = MagicMock()
        mock_row.get_selected.return_value = 0

        # Should not raise exception
        page_instance._on_close_behavior_changed(mock_row, None)
        _clear_src_modules()

    def test_on_close_behavior_changed_invalid_index(self, mock_gi_modules):
        """Test that invalid index is handled gracefully."""
        settings_manager = MagicMock()

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(settings_manager=settings_manager, tray_available=True)

        # Create mock row with out-of-range index
        mock_row = MagicMock()
        mock_row.get_selected.return_value = 99

        # Should not raise exception and should not save
        page_instance._on_close_behavior_changed(mock_row, None)
        settings_manager.set.assert_not_called()
        _clear_src_modules()


class TestBehaviorPageParentWindow:
    """Test parent_window parameter functionality."""

    def test_init_with_parent_window(self, mock_gi_modules):
        """Test initialization with parent window."""
        settings_manager = MagicMock()
        parent_window = MagicMock()

        from src.ui.preferences.behavior_page import BehaviorPage

        page = BehaviorPage(
            settings_manager=settings_manager,
            tray_available=True,
            parent_window=parent_window,
        )

        assert page._parent_window is parent_window
        _clear_src_modules()

    def test_init_without_parent_window(self, mock_gi_modules):
        """Test initialization without parent window defaults to None."""
        from src.ui.preferences.behavior_page import BehaviorPage

        page = BehaviorPage()

        assert page._parent_window is None
        _clear_src_modules()


class TestBehaviorPageFileManagerIntegration:
    """Test file manager integration group functionality."""

    def test_create_page_adds_file_manager_group_in_flatpak(self, mock_gi_modules, monkeypatch):
        """Test that file manager group is added when running in Flatpak."""
        adw = mock_gi_modules["adw"]
        mock_page = MagicMock()
        mock_group = MagicMock()
        adw.PreferencesPage.return_value = mock_page
        adw.PreferencesGroup.return_value = mock_group

        from src.ui.preferences.behavior_page import BehaviorPage

        behavior_module = sys.modules["src.ui.preferences.behavior_page"]
        monkeypatch.setattr(behavior_module, "is_flatpak", lambda: True)

        page_instance = BehaviorPage(tray_available=True)
        page_instance.create_page()

        # Should add four groups: language + window behavior + scan behavior + file manager integration
        assert mock_page.add.call_count == 4
        _clear_src_modules()

    def test_create_page_no_file_manager_group_when_not_flatpak(self, mock_gi_modules, monkeypatch):
        """Test that file manager group is NOT added when not in Flatpak."""
        adw = mock_gi_modules["adw"]
        mock_page = MagicMock()
        mock_group = MagicMock()
        adw.PreferencesPage.return_value = mock_page
        adw.PreferencesGroup.return_value = mock_group

        from src.ui.preferences.behavior_page import BehaviorPage

        behavior_module = sys.modules["src.ui.preferences.behavior_page"]
        monkeypatch.setattr(behavior_module, "is_flatpak", lambda: False)

        page_instance = BehaviorPage(tray_available=True)
        page_instance.create_page()

        # Should add three groups: language + window behavior + scan behavior (no file manager group)
        assert mock_page.add.call_count == 3
        _clear_src_modules()

    def test_create_file_manager_group_returns_group(self, mock_gi_modules):
        """Test that _create_file_manager_group returns a PreferencesGroup."""
        adw = mock_gi_modules["adw"]
        gtk = mock_gi_modules["gtk"]
        mock_group = MagicMock()
        mock_row = MagicMock()
        mock_icon = MagicMock()
        adw.PreferencesGroup.return_value = mock_group
        adw.ActionRow.side_effect = lambda *args, **kwargs: mock_row
        gtk.Image.new_from_icon_name.return_value = mock_icon

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage()
        result = page_instance._create_file_manager_group()

        assert result is mock_group
        mock_group.set_title.assert_called_with("File Manager Integration")
        _clear_src_modules()

    def test_create_file_manager_group_creates_action_row(self, mock_gi_modules):
        """Test that _create_file_manager_group creates an activatable ActionRow."""
        adw = mock_gi_modules["adw"]
        gtk = mock_gi_modules["gtk"]
        mock_group = MagicMock()
        mock_row = MagicMock()
        mock_icon = MagicMock()
        adw.PreferencesGroup.return_value = mock_group
        adw.ActionRow.side_effect = lambda *args, **kwargs: mock_row
        gtk.Image.new_from_icon_name.return_value = mock_icon

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage()
        page_instance._create_file_manager_group()

        # Verify ActionRow was configured correctly
        mock_row.set_title.assert_called_with("Configure Integration")
        mock_row.set_subtitle.assert_called_with(
            "Install or manage 'Scan with ClamUI' menu actions"
        )
        mock_row.set_activatable.assert_called_with(True)
        mock_row.connect.assert_called()
        mock_group.add.assert_called_with(mock_row)
        _clear_src_modules()

    def test_file_manager_integration_click_opens_dialog(self, mock_gi_modules, monkeypatch):
        """Test that clicking the row opens FileManagerIntegrationDialog."""
        settings_manager = MagicMock()
        parent_window = MagicMock()

        # Mock the dialog class in the dialog module
        mock_dialog_class = MagicMock()
        mock_dialog_instance = MagicMock()
        mock_dialog_class.return_value = mock_dialog_instance

        import src.ui.file_manager_integration_dialog as dialog_module

        monkeypatch.setattr(dialog_module, "FileManagerIntegrationDialog", mock_dialog_class)

        from src.ui.preferences.behavior_page import BehaviorPage

        page_instance = BehaviorPage(
            settings_manager=settings_manager,
            tray_available=True,
            parent_window=parent_window,
        )

        # Call the click handler
        page_instance._on_file_manager_integration_clicked(MagicMock())

        # Verify dialog was created with correct arguments
        mock_dialog_class.assert_called_once_with(
            settings_manager=settings_manager,
        )
        # Adw.Window pattern: set_transient_for then present
        mock_dialog_instance.set_transient_for.assert_called_once_with(parent_window)
        mock_dialog_instance.present.assert_called_once()
        _clear_src_modules()
