# ClamUI Exclusions Page Tests
"""Unit tests for the ExclusionsPage class."""

import copy
from unittest import mock

import pytest


class _PersistentExclusionSettings:
    """In-memory settings double that models durable save success or failure."""

    def __init__(self, exclusions, save_succeeds=True):
        self.exclusions = copy.deepcopy(exclusions)
        self.save_succeeds = save_succeeds
        self.set_calls = []

    def get(self, key, default=None):
        if key == "exclusion_patterns":
            return copy.deepcopy(self.exclusions)
        return default

    def set(self, key, value):
        self.set_calls.append((key, copy.deepcopy(value)))
        if self.save_succeeds:
            self.exclusions = copy.deepcopy(value)
        return self.save_succeeds


class TestExclusionsPageImport:
    """Tests for importing the ExclusionsPage."""

    def test_import_exclusions_page(self, mock_gi_modules):
        """Test that ExclusionsPage can be imported."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        assert ExclusionsPage is not None

    def test_exclusions_page_is_class(self, mock_gi_modules):
        """Test that ExclusionsPage is a class."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        assert isinstance(ExclusionsPage, type)

    def test_exclusions_page_inherits_from_mixin(self, mock_gi_modules):
        """Test that ExclusionsPage inherits from PreferencesPageMixin."""
        from src.ui.preferences.base import PreferencesPageMixin
        from src.ui.preferences.exclusions_page import ExclusionsPage

        assert issubclass(ExclusionsPage, PreferencesPageMixin)

    def test_import_preset_exclusions_constant(self, mock_gi_modules):
        """Test that PRESET_EXCLUSIONS can be imported."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS

        assert PRESET_EXCLUSIONS is not None


class TestPresetExclusionsConstant:
    """Tests for PRESET_EXCLUSIONS constant."""

    def test_preset_exclusions_is_list(self, mock_gi_modules):
        """Test that PRESET_EXCLUSIONS is a list."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS

        assert isinstance(PRESET_EXCLUSIONS, list)

    def test_preset_exclusions_count(self, mock_gi_modules):
        """Test that PRESET_EXCLUSIONS has expected number of items."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS

        # Should have 6 preset exclusions
        assert len(PRESET_EXCLUSIONS) == 6

    def test_preset_exclusions_structure(self, mock_gi_modules):
        """Test that each preset exclusion has required keys."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS

        required_keys = {"pattern", "type", "enabled", "description"}
        for preset in PRESET_EXCLUSIONS:
            assert isinstance(preset, dict)
            assert set(preset.keys()) == required_keys

    def test_preset_exclusions_patterns(self, mock_gi_modules):
        """Test that PRESET_EXCLUSIONS contains expected patterns."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS

        expected_patterns = [
            "node_modules",
            ".git",
            ".venv",
            "build",
            "dist",
            "__pycache__",
        ]
        actual_patterns = [p["pattern"] for p in PRESET_EXCLUSIONS]
        assert actual_patterns == expected_patterns

    def test_preset_exclusions_all_enabled_by_default(self, mock_gi_modules):
        """Test that all presets are enabled by default."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS

        for preset in PRESET_EXCLUSIONS:
            assert preset["enabled"] is True

    def test_preset_exclusions_all_directories(self, mock_gi_modules):
        """Test that all presets are directory type."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS

        for preset in PRESET_EXCLUSIONS:
            assert preset["type"] == "directory"


class TestExclusionsPageCreation:
    """Tests for ExclusionsPage.create_page() method."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = []
        return manager

    def test_create_page_returns_preferences_page(self, mock_gi_modules, mock_settings_manager):
        """Test create_page returns an Adw.PreferencesPage."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page.create_page()

        # Should create a PreferencesPage
        adw.PreferencesPage.assert_called()

    def test_create_page_sets_title_and_icon(self, mock_gi_modules, mock_settings_manager):
        """Test create_page sets correct title and icon."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page.create_page()

        # Should set title and icon_name
        adw.PreferencesPage.assert_called_with(
            title="Exclusions",
            icon_name="action-unavailable-symbolic",
        )

    def test_create_page_creates_preference_groups(self, mock_gi_modules, mock_settings_manager):
        """Test create_page creates preference groups."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page.create_page()

        # Should create 2 PreferencesGroups (preset and custom)
        assert adw.PreferencesGroup.call_count == 2

    def test_create_page_creates_preset_switch_rows(self, mock_gi_modules, mock_settings_manager):
        """Test create_page creates SwitchRows for preset exclusions."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page.create_page()

        # Switch rows are now ActionRows via create_switch_row compat
        assert adw.ActionRow.call_count >= len(PRESET_EXCLUSIONS)

    def test_create_page_creates_custom_entry_row(self, mock_gi_modules, mock_settings_manager):
        """Test create_page creates EntryRow for adding custom exclusions."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page.create_page()

        # Entry rows are now ActionRows via create_entry_row compat
        adw.ActionRow.assert_called()

    def test_create_page_creates_add_button(self, mock_gi_modules, mock_settings_manager):
        """Test create_page creates add button for custom exclusions."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page.create_page()

        # Should create a Button
        assert gtk.Button.call_count >= 1

    def test_create_page_loads_custom_exclusions(self, mock_gi_modules, mock_settings_manager):
        """Test create_page loads existing custom exclusions."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        # Set up mock to return custom exclusions
        mock_settings_manager.get.return_value = [
            {"pattern": "/custom/path", "enabled": True},
            {"pattern": "*.tmp", "enabled": False},
        ]

        page = ExclusionsPage(mock_settings_manager)
        page.create_page()

        # Should call settings_manager.get to load exclusions
        mock_settings_manager.get.assert_called_with("exclusion_patterns", [])

    def test_create_page_without_settings_manager(self, mock_gi_modules):
        """Test create_page works without settings manager."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(None)
        # Should not raise exception
        result = page.create_page()
        assert result is not None


class TestExclusionsPageLoadCustomExclusions:
    """Tests for ExclusionsPage._load_custom_exclusions() method."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = []
        return manager

    def test_load_custom_exclusions_with_no_settings_manager(self, mock_gi_modules):
        """Test _load_custom_exclusions handles None settings manager."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(None)
        # Should not raise exception
        page._load_custom_exclusions()

    def test_load_custom_exclusions_with_empty_list(self, mock_gi_modules, mock_settings_manager):
        """Test _load_custom_exclusions with empty exclusion list."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = []

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()
        page._load_custom_exclusions()

        mock_settings_manager.get.assert_called_with("exclusion_patterns", [])

    def test_load_custom_exclusions_with_valid_patterns(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _load_custom_exclusions loads valid patterns."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "/custom/path", "enabled": True},
            {"pattern": "*.tmp", "enabled": False},
        ]

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row") as mock_add:
            page._load_custom_exclusions()
            # Should call _add_custom_exclusion_row for each pattern
            assert mock_add.call_count == 2
            mock_add.assert_any_call("/custom/path", True)
            mock_add.assert_any_call("*.tmp", False)

    def test_load_custom_exclusions_skips_empty_patterns(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _load_custom_exclusions skips empty patterns."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "/valid/path", "enabled": True},
            {"pattern": "", "enabled": True},  # Empty pattern
            {"pattern": "/another/path", "enabled": False},
        ]

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row") as mock_add:
            page._load_custom_exclusions()
            # Should only add valid patterns
            assert mock_add.call_count == 2

    def test_load_custom_exclusions_handles_missing_pattern_key(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _load_custom_exclusions handles missing pattern key."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "/valid/path", "enabled": True},
            {"enabled": True},  # Missing pattern key
        ]

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row") as mock_add:
            page._load_custom_exclusions()
            # Should only add valid patterns
            assert mock_add.call_count == 1

    def test_load_custom_exclusions_handles_non_list(self, mock_gi_modules, mock_settings_manager):
        """Test _load_custom_exclusions handles non-list return value."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = "not a list"

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        # Should not raise exception
        page._load_custom_exclusions()


class TestExclusionsPageAddCustomExclusionRow:
    """Tests for ExclusionsPage._add_custom_exclusion_row() method."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = []
        return manager

    def test_add_custom_exclusion_row_creates_switch_row(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _add_custom_exclusion_row creates a SwitchRow."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        page._add_custom_exclusion_row("/test/path", True)

        # Switch rows are now ActionRows via create_switch_row compat
        adw.ActionRow.assert_called()

    def test_add_custom_exclusion_row_sets_title(self, mock_gi_modules, mock_settings_manager):
        """Test _add_custom_exclusion_row sets row title to pattern."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_row = mock.MagicMock()
        adw.ActionRow.side_effect = lambda *args, **kwargs: mock_row

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        page._add_custom_exclusion_row("/test/path", True)

        mock_row.set_title.assert_called_with("/test/path")

    def test_add_custom_exclusion_row_sets_active_state(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _add_custom_exclusion_row sets enabled state."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_row = mock.MagicMock()
        adw.ActionRow.side_effect = lambda *args, **kwargs: mock_row

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        # Test enabled=True
        # create_switch_row patches set_active to delegate to Gtk.Switch via _compat_switch
        page._add_custom_exclusion_row("/test/path", True)
        mock_row._compat_switch.set_active.assert_called_with(True)

        # Test enabled=False
        mock_row.reset_mock()
        page._add_custom_exclusion_row("/another/path", False)
        mock_row._compat_switch.set_active.assert_called_with(False)

    def test_add_custom_exclusion_row_creates_remove_button(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _add_custom_exclusion_row creates remove button."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        page._add_custom_exclusion_row("/test/path", True)

        # Should create a Button for removal
        gtk.Button.assert_called()

    def test_add_custom_exclusion_row_adds_to_group(self, mock_gi_modules, mock_settings_manager):
        """Test _add_custom_exclusion_row adds row to group."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()

        page._add_custom_exclusion_row("/test/path", True)

        # Should add row to custom exclusions group
        page._custom_exclusions_group.add.assert_called()


class TestExclusionsPageAddCustomExclusion:
    """Tests for ExclusionsPage._on_add_custom_exclusion() method."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = []
        return manager

    def test_on_add_custom_exclusion_ignores_empty_pattern(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_add_custom_exclusion ignores empty pattern."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "   "  # Whitespace only

        page._on_add_custom_exclusion(None)

        # Should not call settings manager
        mock_settings_manager.set.assert_not_called()

    def test_on_add_custom_exclusion_ignores_without_settings_manager(self, mock_gi_modules):
        """Test _on_add_custom_exclusion ignores when no settings manager."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(None)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "/test/path"

        # Should not raise exception
        page._on_add_custom_exclusion(None)

    def test_on_add_custom_exclusion_adds_file_pattern(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_add_custom_exclusion adds file pattern (path starting with /)."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "/test/path"
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row"):
            page._on_add_custom_exclusion(None)

        # The custom record is appended alongside the canonical presets.
        call_args = mock_settings_manager.set.call_args[0]
        assert call_args[0] == "exclusion_patterns"
        custom = next(record for record in call_args[1] if record["pattern"] == "/test/path")
        assert custom["type"] == "file"
        assert custom["enabled"] is True

    def test_on_add_custom_exclusion_adds_generic_pattern(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_add_custom_exclusion adds generic pattern (not starting with /)."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "*.tmp"
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row"):
            page._on_add_custom_exclusion(None)

        # The custom record retains its generic pattern type.
        call_args = mock_settings_manager.set.call_args[0]
        custom = next(record for record in call_args[1] if record["pattern"] == "*.tmp")
        assert custom["type"] == "pattern"

    def test_on_add_custom_exclusion_strips_whitespace(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_add_custom_exclusion strips whitespace from pattern."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "  *.tmp  "
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row"):
            page._on_add_custom_exclusion(None)

        # The saved custom record uses the stripped pattern.
        call_args = mock_settings_manager.set.call_args[0]
        assert any(record["pattern"] == "*.tmp" for record in call_args[1])

    def test_on_add_custom_exclusion_avoids_duplicates(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_add_custom_exclusion avoids duplicate patterns."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "*.tmp", "type": "pattern", "enabled": True}
        ]

        page = ExclusionsPage(mock_settings_manager)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "*.tmp"
        page._custom_exclusions_group = mock.MagicMock()

        page._on_add_custom_exclusion(None)

        # Should not add duplicate
        mock_settings_manager.set.assert_not_called()

    def test_on_add_custom_exclusion_adds_to_ui(self, mock_gi_modules, mock_settings_manager):
        """Test _on_add_custom_exclusion adds row to UI."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "/test/path"
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row") as mock_add:
            page._on_add_custom_exclusion(None)

        # Should call _add_custom_exclusion_row
        mock_add.assert_called_with("/test/path", True)

    def test_on_add_custom_exclusion_clears_entry(self, mock_gi_modules, mock_settings_manager):
        """Test _on_add_custom_exclusion clears entry field after adding."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(mock_settings_manager)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "/test/path"
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row"):
            page._on_add_custom_exclusion(None)

        # Should clear the entry
        page._custom_entry_row.set_text.assert_called_with("")

    def test_on_add_custom_exclusion_handles_non_list_settings(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_add_custom_exclusion handles non-list settings gracefully."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = "not a list"

        page = ExclusionsPage(mock_settings_manager)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "/test/path"
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row"):
            page._on_add_custom_exclusion(None)

        # Invalid legacy data is replaced by canonical presets plus the custom record.
        call_args = mock_settings_manager.set.call_args[0]
        assert any(record["pattern"] == "/test/path" for record in call_args[1])


class TestExclusionsPageRemoveCustomExclusion:
    """Tests for ExclusionsPage._on_remove_custom_exclusion() method."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = []
        return manager

    def test_on_remove_custom_exclusion_ignores_without_settings_manager(self, mock_gi_modules):
        """Test _on_remove_custom_exclusion ignores when no settings manager."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(None)
        mock_row = mock.MagicMock()

        # Should not raise exception
        page._on_remove_custom_exclusion(None, mock_row, "/test/path")

    def test_on_remove_custom_exclusion_removes_from_settings(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_remove_custom_exclusion removes pattern from settings."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "/test/path", "type": "file", "enabled": True},
            {"pattern": "*.tmp", "type": "pattern", "enabled": True},
        ]

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()
        mock_row = mock.MagicMock()

        page._on_remove_custom_exclusion(None, mock_row, "/test/path")

        # The custom record is removed while any canonical presets remain.
        call_args = mock_settings_manager.set.call_args[0]
        assert call_args[0] == "exclusion_patterns"
        assert any(record["pattern"] == "*.tmp" for record in call_args[1])

    def test_on_remove_custom_exclusion_removes_from_ui(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_remove_custom_exclusion removes row from UI."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "/test/path", "type": "file", "enabled": True}
        ]

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()
        mock_row = mock.MagicMock()

        page._on_remove_custom_exclusion(None, mock_row, "/test/path")

        # Should remove row from group
        page._custom_exclusions_group.remove.assert_called_with(mock_row)

    def test_on_remove_custom_exclusion_handles_non_list_settings(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_remove_custom_exclusion handles non-list settings."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = "not a list"

        page = ExclusionsPage(mock_settings_manager)
        page._custom_exclusions_group = mock.MagicMock()
        mock_row = mock.MagicMock()

        # Should not raise exception
        page._on_remove_custom_exclusion(None, mock_row, "/test/path")


class TestExclusionsPageToggleExclusion:
    """Tests for ExclusionsPage._on_exclusion_toggled() method."""

    @pytest.fixture
    def mock_settings_manager(self):
        """Provide a mock settings manager."""
        manager = mock.MagicMock()
        manager.get.return_value = []
        return manager

    def test_on_exclusion_toggled_ignores_without_settings_manager(self, mock_gi_modules):
        """Test _on_exclusion_toggled ignores when no settings manager."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        page = ExclusionsPage(None)
        mock_row = mock.MagicMock()
        mock_row.get_active.return_value = True

        # Should not raise exception
        page._on_exclusion_toggled(mock_row, None, "/test/path")

    def test_on_exclusion_toggled_updates_enabled_state(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_exclusion_toggled updates enabled state in settings."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "/test/path", "type": "file", "enabled": True},
            {"pattern": "*.tmp", "type": "pattern", "enabled": False},
        ]

        page = ExclusionsPage(mock_settings_manager)
        mock_row = mock.MagicMock()
        mock_row.get_active.return_value = False

        page._on_exclusion_toggled(mock_row, None, "/test/path")

        # Should update enabled state
        call_args = mock_settings_manager.set.call_args[0]
        assert call_args[0] == "exclusion_patterns"
        # Find the updated exclusion
        for excl in call_args[1]:
            if excl["pattern"] == "/test/path":
                assert excl["enabled"] is False

    def test_on_exclusion_toggled_preserves_other_patterns(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_exclusion_toggled preserves other patterns."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "/test/path", "type": "file", "enabled": True},
            {"pattern": "*.tmp", "type": "pattern", "enabled": False},
        ]

        page = ExclusionsPage(mock_settings_manager)
        mock_row = mock.MagicMock()
        mock_row.get_active.return_value = False

        page._on_exclusion_toggled(mock_row, None, "/test/path")

        # The custom records both remain, together with canonical presets.
        call_args = mock_settings_manager.set.call_args[0]
        assert {"/test/path", "*.tmp"} <= {record["pattern"] for record in call_args[1]}

    def test_on_exclusion_toggled_handles_non_list_settings(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_exclusion_toggled handles non-list settings."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = "not a list"

        page = ExclusionsPage(mock_settings_manager)
        mock_row = mock.MagicMock()
        mock_row.get_active.return_value = True

        # Should not raise exception (but won't update since not a list)
        page._on_exclusion_toggled(mock_row, None, "/test/path")

    def test_on_exclusion_toggled_handles_pattern_not_found(
        self, mock_gi_modules, mock_settings_manager
    ):
        """Test _on_exclusion_toggled handles pattern not in settings."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        mock_settings_manager.get.return_value = [
            {"pattern": "*.tmp", "type": "pattern", "enabled": False},
        ]

        page = ExclusionsPage(mock_settings_manager)
        mock_row = mock.MagicMock()
        mock_row.get_active.return_value = True

        # Should not raise exception
        page._on_exclusion_toggled(mock_row, None, "/test/path")


class TestExclusionsPagePresetPersistence:
    """Regression tests for presets persisted with custom exclusions."""

    def test_empty_legacy_records_are_normalized_with_all_presets(self, mock_gi_modules):
        """Opening the page materializes the canonical preset records once."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        settings = _PersistentExclusionSettings([])

        ExclusionsPage(settings).create_page()

        assert len(settings.set_calls) == 1
        assert settings.exclusions == [
            {
                "pattern": preset["pattern"],
                "type": preset["type"],
                "enabled": preset["enabled"],
            }
            for preset in PRESET_EXCLUSIONS
        ]

    def test_legacy_custom_records_are_normalized_with_all_presets(self, mock_gi_modules):
        """Opening the page stores all presets without losing custom records."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        custom_records = [
            {"pattern": "*.tmp", "type": "pattern", "enabled": False},
            {"pattern": "/work/cache", "type": "file", "enabled": True},
        ]
        settings = _PersistentExclusionSettings(custom_records)

        ExclusionsPage(settings).create_page()

        persisted_patterns = [record["pattern"] for record in settings.exclusions]
        assert len(settings.set_calls) == 1
        assert all(persisted_patterns.count(preset["pattern"]) == 1 for preset in PRESET_EXCLUSIONS)
        assert all(record in settings.exclusions for record in custom_records)

    def test_repeated_page_load_does_not_duplicate_or_resave_presets(self, mock_gi_modules):
        """A normalized settings list remains unchanged on later page loads."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        settings = _PersistentExclusionSettings(
            [{"pattern": "*.tmp", "type": "pattern", "enabled": True}]
        )
        page = ExclusionsPage(settings)

        page.create_page()
        first_persisted = copy.deepcopy(settings.exclusions)
        page.create_page()

        assert settings.exclusions == first_persisted
        assert len(settings.set_calls) == 1
        assert all(
            sum(record["pattern"] == preset["pattern"] for record in settings.exclusions) == 1
            for preset in PRESET_EXCLUSIONS
        )

    def test_matching_persisted_preset_keeps_its_enabled_state(self, mock_gi_modules):
        """A saved preset record supplies the state rendered by its preset row."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.exclusions_page import ExclusionsPage

        created_rows = []

        def create_row(*args, **kwargs):
            row = mock.MagicMock()
            created_rows.append(row)
            return row

        adw.ActionRow.side_effect = create_row
        settings = _PersistentExclusionSettings(
            [
                {"pattern": "node_modules", "type": "directory", "enabled": False},
                {"pattern": "*.tmp", "type": "pattern", "enabled": True},
            ]
        )

        ExclusionsPage(settings).create_page()

        assert created_rows[0]._compat_switch.set_active.call_args == mock.call(False)
        matching_records = [
            record for record in settings.exclusions if record["pattern"] == "node_modules"
        ]
        assert matching_records == [
            {"pattern": "node_modules", "type": "directory", "enabled": False}
        ]

    def test_preset_records_are_not_rendered_as_custom_rows(self, mock_gi_modules):
        """Stored presets render only in the preset group."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        settings = _PersistentExclusionSettings(
            [
                {"pattern": "node_modules", "type": "directory", "enabled": False},
                {"pattern": "*.tmp", "type": "pattern", "enabled": True},
            ]
        )
        page = ExclusionsPage(settings)
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row") as add_row:
            page._load_custom_exclusions()

        add_row.assert_called_once_with("*.tmp", True)

    def test_toggling_a_preset_persists_one_updated_canonical_record(self, mock_gi_modules):
        """Toggling a preset updates it once while retaining custom records."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        custom_record = {"pattern": "*.tmp", "type": "pattern", "enabled": True}
        settings = _PersistentExclusionSettings([custom_record])
        page = ExclusionsPage(settings)
        page.create_page()
        row = mock.MagicMock()
        row.get_active.return_value = False

        page._on_exclusion_toggled(row, None, ".git")

        git_records = [record for record in settings.exclusions if record["pattern"] == ".git"]
        assert git_records == [{"pattern": ".git", "type": "directory", "enabled": False}]
        assert all(
            sum(record["pattern"] == preset["pattern"] for record in settings.exclusions) == 1
            for preset in PRESET_EXCLUSIONS
        )
        assert custom_record in settings.exclusions

    def test_adding_custom_exclusion_retains_preset_records(self, mock_gi_modules):
        """Adding a custom pattern does not remove persisted presets."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        presets = [
            {"pattern": preset["pattern"], "type": "directory", "enabled": True}
            for preset in PRESET_EXCLUSIONS
        ]
        settings = _PersistentExclusionSettings(presets)
        page = ExclusionsPage(settings)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "*.tmp"
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row"):
            page._on_add_custom_exclusion(None)

        assert {preset["pattern"] for preset in PRESET_EXCLUSIONS} <= {
            record["pattern"] for record in settings.exclusions
        }
        assert {"pattern": "*.tmp", "type": "pattern", "enabled": True} in settings.exclusions

    def test_removing_custom_exclusion_retains_preset_records(self, mock_gi_modules):
        """Removing a custom pattern does not remove persisted presets."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        presets = [
            {"pattern": preset["pattern"], "type": "directory", "enabled": True}
            for preset in PRESET_EXCLUSIONS
        ]
        settings = _PersistentExclusionSettings(
            presets + [{"pattern": "*.tmp", "type": "pattern", "enabled": True}]
        )
        page = ExclusionsPage(settings)
        page._custom_exclusions_group = mock.MagicMock()

        page._on_remove_custom_exclusion(None, mock.MagicMock(), "*.tmp")

        assert {preset["pattern"] for preset in PRESET_EXCLUSIONS} == {
            record["pattern"] for record in settings.exclusions
        }

    def test_toggling_custom_exclusion_retains_preset_records(self, mock_gi_modules):
        """Toggling a custom pattern does not remove persisted presets."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        presets = [
            {"pattern": preset["pattern"], "type": "directory", "enabled": True}
            for preset in PRESET_EXCLUSIONS
        ]
        settings = _PersistentExclusionSettings(
            presets + [{"pattern": "*.tmp", "type": "pattern", "enabled": True}]
        )
        page = ExclusionsPage(settings)
        row = mock.MagicMock()
        row.get_active.return_value = False

        page._on_exclusion_toggled(row, None, "*.tmp")

        assert {preset["pattern"] for preset in PRESET_EXCLUSIONS} <= {
            record["pattern"] for record in settings.exclusions
        }
        custom = next(record for record in settings.exclusions if record["pattern"] == "*.tmp")
        assert custom["enabled"] is False

    def test_failed_preset_save_restores_the_persisted_switch_state(self, mock_gi_modules):
        """A failed preset save reverses the control instead of claiming success."""
        from src.ui.preferences.exclusions_page import ExclusionsPage

        persisted = [{"pattern": "node_modules", "type": "directory", "enabled": True}]
        settings = _PersistentExclusionSettings(persisted, save_succeeds=False)
        page = ExclusionsPage(settings)
        row = mock.MagicMock()
        row.get_active.return_value = False

        page._on_exclusion_toggled(row, None, "node_modules")

        assert settings.exclusions == persisted
        row.set_active.assert_called_once_with(True)

    def test_failed_custom_save_keeps_the_entry_and_does_not_add_a_row(self, mock_gi_modules):
        """A failed custom save leaves the UI at its durable pre-save state."""
        from src.ui.preferences.exclusions_page import PRESET_EXCLUSIONS, ExclusionsPage

        presets = [
            {"pattern": preset["pattern"], "type": "directory", "enabled": True}
            for preset in PRESET_EXCLUSIONS
        ]
        settings = _PersistentExclusionSettings(presets, save_succeeds=False)
        page = ExclusionsPage(settings)
        page._custom_entry_row = mock.MagicMock()
        page._custom_entry_row.get_text.return_value = "*.tmp"
        page._custom_exclusions_group = mock.MagicMock()

        with mock.patch.object(page, "_add_custom_exclusion_row") as add_row:
            page._on_add_custom_exclusion(None)

        assert settings.exclusions == presets
        add_row.assert_not_called()
        page._custom_entry_row.set_text.assert_not_called()
