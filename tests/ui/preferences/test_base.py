# ClamUI Preferences Base Module Tests
"""Unit tests for the PreferencesPageMixin class."""

from unittest import mock

import pytest


class TestPreferencesPageMixinImport:
    """Tests for importing the PreferencesPageMixin."""

    def test_import_mixin(self, mock_gi_modules):
        """Test that PreferencesPageMixin can be imported."""
        from src.ui.preferences.base import PreferencesPageMixin

        assert PreferencesPageMixin is not None

    def test_mixin_is_class(self, mock_gi_modules):
        """Test that PreferencesPageMixin is a class."""
        from src.ui.preferences.base import PreferencesPageMixin

        assert isinstance(PreferencesPageMixin, type)


class TestPreferencesPageMixinMethods:
    """Tests for PreferencesPageMixin utility methods."""

    @pytest.fixture
    def test_class(self, mock_gi_modules):
        """Create a test class that uses the mixin."""
        from src.ui.preferences.base import PreferencesPageMixin

        # Create a test class that inherits from the mixin
        # and provides a mock 'self' for dialog presentation
        class TestWindow(PreferencesPageMixin):
            """Test window class using the mixin."""

            def __init__(self):
                pass

        return TestWindow

    @pytest.fixture
    def test_instance(self, test_class):
        """Create an instance of the test class."""
        return test_class()

    def test_create_permission_indicator_returns_box(self, test_instance, mock_gi_modules):
        """Test _create_permission_indicator returns a Gtk.Box."""
        result = test_instance._create_permission_indicator()

        # Should return a box (MockGtkBox is a real class, not MagicMock)
        assert result is not None

    def test_create_permission_indicator_creates_lock_icon(self, test_instance, mock_gi_modules):
        """Test _create_permission_indicator creates a lock icon."""
        gtk = mock_gi_modules["gtk"]

        test_instance._create_permission_indicator()

        # Should create an Image with the lock icon
        gtk.Image.new_from_icon_name.assert_called_with("system-lock-screen-symbolic")

    def test_create_permission_indicator_sets_tooltip(self, test_instance, mock_gi_modules):
        """Test _create_permission_indicator sets tooltip on the icon."""
        gtk = mock_gi_modules["gtk"]
        mock_icon = mock.MagicMock()
        gtk.Image.new_from_icon_name.return_value = mock_icon

        test_instance._create_permission_indicator()

        # Should set tooltip text
        mock_icon.set_tooltip_text.assert_called_with("Requires administrator privileges to modify")

    def test_create_permission_indicator_omits_lock_when_root(self, test_instance, mock_gi_modules):
        """When already running as root, no lock icon is created: elevation is
        not required, so flagging the group as admin-only would mislead."""
        gtk = mock_gi_modules["gtk"]
        gtk.Image.new_from_icon_name.reset_mock()

        with mock.patch("src.core.privileged_paths.is_running_as_root", return_value=True):
            result = test_instance._create_permission_indicator()

        # Still returns a (empty) box, but no lock icon is built.
        assert result is not None
        gtk.Image.new_from_icon_name.assert_not_called()

    def test_open_folder_in_file_manager_nonexistent_folder(self, test_instance, mock_gi_modules):
        """Test _open_folder_in_file_manager shows error for nonexistent folder."""
        adw = mock_gi_modules["adw"]
        mock_dialog = mock.MagicMock()
        mock_window_class = mock.MagicMock(return_value=mock_dialog)

        # Temporarily replace Adw.Window with a MagicMock for call tracking
        with mock.patch.object(adw, "Window", mock_window_class):
            # Try to open a folder that doesn't exist
            test_instance._open_folder_in_file_manager("/nonexistent/folder")

            # Should create an Adw.Window-based dialog (path validation catches it early)
            mock_window_class.assert_called()
            actual_title = mock_dialog.set_title.call_args[0][0]
            assert actual_title in ("Folder Not Found", "Invalid Path")
            mock_dialog.set_modal.assert_called_with(True)
            mock_dialog.present.assert_called_once()

    def test_open_folder_in_file_manager_opens_existing_folder(
        self, test_instance, mock_gi_modules, tmp_path
    ):
        """Test _open_folder_in_file_manager opens existing folder."""
        with mock.patch("subprocess.Popen") as mock_popen:
            # Create a temporary folder
            test_folder = str(tmp_path)

            test_instance._open_folder_in_file_manager(test_folder)

            # Should call xdg-open with the folder path
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args == ["xdg-open", test_folder]

    def test_open_folder_in_file_manager_handles_subprocess_error(
        self, test_instance, mock_gi_modules, tmp_path
    ):
        """Test _open_folder_in_file_manager handles subprocess errors."""
        adw = mock_gi_modules["adw"]
        mock_dialog = mock.MagicMock()
        mock_window_class = mock.MagicMock(return_value=mock_dialog)

        with mock.patch.object(adw, "Window", mock_window_class):
            with mock.patch("subprocess.Popen", side_effect=Exception("Test error")):
                test_folder = str(tmp_path)

                test_instance._open_folder_in_file_manager(test_folder)

                # Should create an Adw.Window-based dialog
                mock_window_class.assert_called()
                mock_dialog.set_title.assert_called_with("Error Opening Folder")
                mock_dialog.set_modal.assert_called_with(True)
                mock_dialog.present.assert_called_once()

    def test_show_error_dialog_creates_alert(self, test_instance, mock_gi_modules):
        """Test _show_error_dialog creates an Adw.Window-based dialog."""
        adw = mock_gi_modules["adw"]
        mock_dialog = mock.MagicMock()
        mock_window_class = mock.MagicMock(return_value=mock_dialog)

        with mock.patch.object(adw, "Window", mock_window_class):
            test_instance._show_error_dialog("Test Error", "This is a test error message")

            # Should create an Adw.Window-based dialog
            mock_window_class.assert_called_once()
            mock_dialog.set_title.assert_called_with("Test Error")
            mock_dialog.set_modal.assert_called_with(True)
            mock_dialog.set_deletable.assert_called_with(True)
            mock_dialog.present.assert_called_once()

    def test_show_success_dialog_creates_alert(self, test_instance, mock_gi_modules):
        """Test _show_success_dialog creates an Adw.Window-based dialog."""
        adw = mock_gi_modules["adw"]
        mock_dialog = mock.MagicMock()
        mock_window_class = mock.MagicMock(return_value=mock_dialog)

        with mock.patch.object(adw, "Window", mock_window_class):
            test_instance._show_success_dialog("Success", "Operation completed successfully")

            # Should create an Adw.Window-based dialog
            mock_window_class.assert_called_once()
            mock_dialog.set_title.assert_called_with("Success")
            mock_dialog.set_modal.assert_called_with(True)
            mock_dialog.set_deletable.assert_called_with(True)
            mock_dialog.present.assert_called_once()

    def test_create_file_location_group_creates_group(self, test_instance, mock_gi_modules):
        """Test _create_file_location_group creates a PreferencesGroup."""
        adw = mock_gi_modules["adw"]
        mock_page = mock.MagicMock()
        mock_group = mock.MagicMock()
        adw.PreferencesGroup.return_value = mock_group

        test_instance._create_file_location_group(
            mock_page, "Test Group", "/path/to/file.conf", "Test description"
        )

        # Should create a PreferencesGroup
        adw.PreferencesGroup.assert_called_once()
        mock_group.set_title.assert_called_with("Test Group")
        mock_group.set_description.assert_called_with("Test description")

    def test_create_file_location_group_creates_action_row(self, test_instance, mock_gi_modules):
        """Test _create_file_location_group creates an ActionRow."""
        adw = mock_gi_modules["adw"]
        mock_page = mock.MagicMock()
        mock_row = mock.MagicMock()
        adw.ActionRow.side_effect = lambda *args, **kwargs: mock_row

        test_instance._create_file_location_group(
            mock_page, "Test Group", "/path/to/file.conf", "Test description"
        )

        # Should create an ActionRow
        adw.ActionRow.assert_called_once()
        mock_row.set_title.assert_called_with("File Location")
        mock_row.set_subtitle.assert_called_with("/path/to/file.conf")

    def test_create_file_location_group_adds_folder_icon(self, test_instance, mock_gi_modules):
        """Test _create_file_location_group adds a folder icon."""
        gtk = mock_gi_modules["gtk"]
        adw = mock_gi_modules["adw"]
        mock_page = mock.MagicMock()
        mock_row = mock.MagicMock()
        adw.ActionRow.side_effect = lambda *args, **kwargs: mock_row

        test_instance._create_file_location_group(
            mock_page, "Test Group", "/path/to/file.conf", "Test description"
        )

        # Should create a folder icon
        gtk.Image.new_from_icon_name.assert_called()
        # Check if folder-open-symbolic was used
        calls = gtk.Image.new_from_icon_name.call_args_list
        assert any("folder-open-symbolic" in str(call) for call in calls)

    def test_create_file_location_group_adds_open_button(self, test_instance, mock_gi_modules):
        """Test _create_file_location_group adds an open folder button."""
        gtk = mock_gi_modules["gtk"]
        adw = mock_gi_modules["adw"]
        mock_page = mock.MagicMock()
        mock_row = mock.MagicMock()
        mock_button = mock.MagicMock()
        adw.ActionRow.side_effect = lambda *args, **kwargs: mock_row
        gtk.Button.return_value = mock_button

        test_instance._create_file_location_group(
            mock_page, "Test Group", "/path/to/file.conf", "Test description"
        )

        # Should create a Button
        gtk.Button.assert_called_once()
        mock_button.set_label.assert_called_with("Open Folder")
        mock_button.set_tooltip_text.assert_called_with("Open containing folder in file manager")

    def test_create_file_location_group_button_opens_parent_dir(
        self, test_instance, mock_gi_modules, tmp_path
    ):
        """Test _create_file_location_group button opens parent directory."""
        gtk = mock_gi_modules["gtk"]
        mock_page = mock.MagicMock()
        mock_button = mock.MagicMock()
        gtk.Button.return_value = mock_button

        # Create a test file
        test_file = tmp_path / "test.conf"
        test_file.write_text("test")

        test_instance._create_file_location_group(
            mock_page, "Test Group", str(test_file), "Test description"
        )

        # Get the callback connected to the button
        mock_button.connect.assert_called()
        connect_call = mock_button.connect.call_args
        assert connect_call[0][0] == "clicked"
        callback = connect_call[0][1]

        # Test that callback opens the parent directory
        with mock.patch.object(test_instance, "_open_folder_in_file_manager") as mock_open:
            callback(mock_button)
            mock_open.assert_called_once_with(str(tmp_path))

    def test_create_file_location_group_button_uses_updated_row_path(
        self, test_instance, mock_gi_modules, tmp_path
    ):
        """Test open folder button uses the row's current file path."""
        adw = mock_gi_modules["adw"]
        gtk = mock_gi_modules["gtk"]
        mock_page = mock.MagicMock()
        mock_row = mock.MagicMock()
        mock_button = mock.MagicMock()
        adw.ActionRow.side_effect = lambda *args, **kwargs: mock_row
        gtk.Button.return_value = mock_button

        initial_file = tmp_path / "default" / "clamd.conf"
        updated_file = tmp_path / "custom" / "clamd-custom.conf"

        test_instance._create_file_location_group(
            mock_page, "Test Group", str(initial_file), "Test description"
        )

        mock_row.get_subtitle.return_value = str(updated_file)

        callback = mock_button.connect.call_args[0][1]

        with mock.patch.object(test_instance, "_open_folder_in_file_manager") as mock_open:
            callback(mock_button)
            mock_open.assert_called_once_with(str(updated_file.parent))

    def test_create_file_location_group_adds_to_page(self, test_instance, mock_gi_modules):
        """Test _create_file_location_group adds group to page."""
        adw = mock_gi_modules["adw"]
        mock_page = mock.MagicMock()
        mock_group = mock.MagicMock()
        adw.PreferencesGroup.return_value = mock_group

        test_instance._create_file_location_group(
            mock_page, "Test Group", "/path/to/file.conf", "Test description"
        )

        # Should add the group to the page
        mock_page.add.assert_called_with(mock_group)


class TestPreferencesPageMixinInheritance:
    """Tests for PreferencesPageMixin inheritance patterns."""

    def test_mixin_can_be_inherited(self, mock_gi_modules):
        """Test that PreferencesPageMixin can be inherited by other classes."""
        from src.ui.preferences.base import PreferencesPageMixin

        class CustomPage(PreferencesPageMixin):
            pass

        assert issubclass(CustomPage, PreferencesPageMixin)

    def test_mixin_methods_available_in_subclass(self, mock_gi_modules):
        """Test that mixin methods are available in subclasses."""
        from src.ui.preferences.base import PreferencesPageMixin

        class CustomPage(PreferencesPageMixin):
            pass

        # All mixin methods should be available
        assert hasattr(CustomPage, "_create_permission_indicator")
        assert hasattr(CustomPage, "_open_folder_in_file_manager")
        assert hasattr(CustomPage, "_show_error_dialog")
        assert hasattr(CustomPage, "_show_success_dialog")
        assert hasattr(CustomPage, "_create_file_location_group")

    def test_mixin_methods_are_callable(self, mock_gi_modules):
        """Test that mixin methods are callable."""
        from src.ui.preferences.base import PreferencesPageMixin

        class CustomPage(PreferencesPageMixin):
            def __init__(self):
                pass

        instance = CustomPage()

        # All methods should be callable
        assert callable(instance._create_permission_indicator)
        assert callable(instance._open_folder_in_file_manager)
        assert callable(instance._show_error_dialog)
        assert callable(instance._show_success_dialog)
        assert callable(instance._create_file_location_group)


class TestPopulateBoolField:
    """Tests for the populate_bool_field helper function."""

    def test_populate_bool_field_with_existing_key_yes(self, mock_gi_modules):
        """Test populate_bool_field sets widget active when config has 'yes'."""
        from src.ui.preferences.base import populate_bool_field

        # Create a mock config with LogVerbose = "yes"
        mock_config = mock.MagicMock()
        mock_config.has_key.return_value = True
        mock_config.get_value.return_value = "yes"

        # Create mock widget
        mock_widget = mock.MagicMock()
        widgets_dict = {"LogVerbose": mock_widget}

        # Populate the field
        populate_bool_field(mock_config, widgets_dict, "LogVerbose")

        # Verify widget was set to active (True)
        mock_config.has_key.assert_called_once_with("LogVerbose")
        mock_config.get_value.assert_called_once_with("LogVerbose")
        mock_widget.set_active.assert_called_once_with(True)

    def test_populate_bool_field_with_existing_key_no(self, mock_gi_modules):
        """Test populate_bool_field sets widget inactive when config has 'no'."""
        from src.ui.preferences.base import populate_bool_field

        # Create a mock config with LogVerbose = "no"
        mock_config = mock.MagicMock()
        mock_config.has_key.return_value = True
        mock_config.get_value.return_value = "no"

        # Create mock widget
        mock_widget = mock.MagicMock()
        widgets_dict = {"LogVerbose": mock_widget}

        # Populate the field
        populate_bool_field(mock_config, widgets_dict, "LogVerbose")

        # Verify widget was set to inactive (False)
        mock_widget.set_active.assert_called_once_with(False)

    def test_populate_bool_field_with_missing_key_default_false(self, mock_gi_modules):
        """Test populate_bool_field uses default=False when key is missing."""
        from src.ui.preferences.base import populate_bool_field

        # Create a mock config that doesn't have LogVerbose
        mock_config = mock.MagicMock()
        mock_config.has_key.return_value = False

        # Create mock widget
        mock_widget = mock.MagicMock()
        widgets_dict = {"LogVerbose": mock_widget}

        # Populate the field with default=False
        populate_bool_field(mock_config, widgets_dict, "LogVerbose", default=False)

        # Verify widget was set to False (default)
        mock_config.has_key.assert_called_once_with("LogVerbose")
        # get_value should NOT be called since key doesn't exist
        mock_config.get_value.assert_not_called()
        mock_widget.set_active.assert_called_once_with(False)

    def test_populate_bool_field_with_missing_key_default_true(self, mock_gi_modules):
        """Test populate_bool_field uses default=True when key is missing."""
        from src.ui.preferences.base import populate_bool_field

        # Create a mock config that doesn't have LogVerbose
        mock_config = mock.MagicMock()
        mock_config.has_key.return_value = False

        # Create mock widget
        mock_widget = mock.MagicMock()
        widgets_dict = {"LogVerbose": mock_widget}

        # Populate the field with default=True
        populate_bool_field(mock_config, widgets_dict, "LogVerbose", default=True)

        # Verify widget was set to True (default)
        mock_widget.set_active.assert_called_once_with(True)

    def test_populate_bool_field_case_insensitive(self, mock_gi_modules):
        """Test populate_bool_field handles 'YES' and 'Yes' correctly."""
        from src.ui.preferences.base import populate_bool_field

        # Test with uppercase 'YES'
        mock_config = mock.MagicMock()
        mock_config.has_key.return_value = True
        mock_config.get_value.return_value = "YES"

        mock_widget = mock.MagicMock()
        widgets_dict = {"LogVerbose": mock_widget}

        populate_bool_field(mock_config, widgets_dict, "LogVerbose")

        # Should convert to lowercase and set active
        mock_widget.set_active.assert_called_once_with(True)

    def test_populate_bool_field_handles_missing_widget(self, mock_gi_modules):
        """Test populate_bool_field safely handles missing widget keys."""
        from src.ui.preferences.base import populate_bool_field

        mock_config = mock.MagicMock()
        mock_config.has_key.return_value = True
        mock_config.get_value.return_value = "yes"

        # Should not raise when widget key is missing
        populate_bool_field(mock_config, {}, "LogVerbose")
