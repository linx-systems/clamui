# ClamUI Scheduled Page Tests
"""Unit tests for the ScheduledPage class."""

from pathlib import Path
from unittest import mock

import pytest


class TestScheduledPageImport:
    """Tests for importing the ScheduledPage."""

    def test_import_scheduled_page(self, mock_gi_modules):
        """Test that ScheduledPage can be imported."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        assert ScheduledPage is not None

    def test_scheduled_page_is_class(self, mock_gi_modules):
        """Test that ScheduledPage is a class."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        assert isinstance(ScheduledPage, type)

    def test_scheduled_page_inherits_from_mixin(self, mock_gi_modules):
        """Test that ScheduledPage inherits from PreferencesPageMixin."""
        from src.ui.preferences.base import PreferencesPageMixin
        from src.ui.preferences.scheduled_page import ScheduledPage

        assert issubclass(ScheduledPage, PreferencesPageMixin)


class TestScheduledPageCreation:
    """Tests for ScheduledPage.create_page() method."""

    @pytest.fixture
    def widgets_dict(self):
        """Provide an empty widgets dictionary."""
        return {}

    def test_create_page_returns_preferences_page(self, mock_gi_modules, widgets_dict):
        """Test create_page returns an Adw.PreferencesPage."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Should create a PreferencesPage
        adw.PreferencesPage.assert_called()

    def test_create_page_sets_title_and_icon(self, mock_gi_modules, widgets_dict):
        """Test create_page sets correct title and icon."""
        adw = mock_gi_modules["adw"]

        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Should set title and icon_name
        adw.PreferencesPage.assert_called_with(
            title="Scheduled Scans",
            icon_name="alarm-symbolic",
        )

    def test_create_page_creates_all_widgets(self, mock_gi_modules, widgets_dict):
        """Test create_page creates all required widgets."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Check that all expected widgets are in the dict
        expected_widgets = [
            "enabled",
            "frequency",
            "time",
            "day_of_week",
            "day_of_month",
            "targets",
            "skip_on_battery",
            "auto_quarantine",
        ]

        for widget_name in expected_widgets:
            assert widget_name in widgets_dict, f"Widget {widget_name} not created"

    def test_create_page_creates_switch_rows(self, mock_gi_modules, widgets_dict):
        """Test create_page creates SwitchRows for boolean options."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Switch rows are now ActionRows via create_switch_row compat
        # 3 switches + 2 entry rows = 5 ActionRows minimum
        assert adw.ActionRow.call_count >= 3

    def test_create_page_creates_combo_rows(self, mock_gi_modules, widgets_dict):
        """Test create_page creates ComboRows for dropdowns."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Should create 2 ComboRows: frequency, day_of_week
        assert adw.ComboRow.call_count == 2

    def test_create_page_creates_entry_rows(self, mock_gi_modules, widgets_dict):
        """Test create_page creates EntryRows for text inputs."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Entry rows are now ActionRows via create_entry_row compat
        # 2 entry rows + 3 switch rows = 5 ActionRows minimum
        assert adw.ActionRow.call_count >= 5

    def test_create_page_creates_spin_button(self, mock_gi_modules, widgets_dict):
        """Test create_page creates SpinButton for day of month (1.0+ compatible)."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Should create 1 SpinButton: day_of_month
        # (using create_spin_row helper which uses Gtk.SpinButton)
        assert gtk.SpinButton.call_count == 1

    def test_create_page_sets_default_values(self, mock_gi_modules, widgets_dict):
        """Test create_page sets appropriate default values."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Check default values
        # ComboRows are unchanged - regular MagicMock
        widgets_dict["frequency"].set_selected.assert_called_with(1)  # Daily
        widgets_dict["day_of_week"].set_selected.assert_called_with(0)  # Monday
        # Entry rows have set_text patched to delegate to Gtk.Entry via compat layer
        widgets_dict["time"]._compat_entry.set_text.assert_called_with("02:00")
        widgets_dict["targets"]._compat_entry.set_text.assert_called_once()  # Home directory
        # Switch rows have set_active patched to delegate to Gtk.Switch via compat layer
        widgets_dict["skip_on_battery"]._compat_switch.set_active.assert_called_with(True)
        widgets_dict["auto_quarantine"]._compat_switch.set_active.assert_called_with(False)

    def test_create_page_creates_preference_group(self, mock_gi_modules, widgets_dict):
        """Test create_page creates preference group with correct title."""
        adw = mock_gi_modules["adw"]
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Should create PreferencesGroup
        adw.PreferencesGroup.assert_called()

    def test_create_page_creates_string_list_for_frequency(self, mock_gi_modules, widgets_dict):
        """Test create_page creates StringList for frequency options."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Should create StringList
        assert gtk.StringList.call_count >= 2  # frequency and day_of_week

    def test_create_page_creates_adjustment_for_day_of_month(self, mock_gi_modules, widgets_dict):
        """Test create_page creates Gtk.Adjustment for day of month spinner."""
        gtk = mock_gi_modules["gtk"]
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.create_page(widgets_dict)

        # Should create Adjustment with correct range (1-28)
        gtk.Adjustment.assert_called_with(
            value=1, lower=1, upper=28, step_increment=1, page_increment=5, page_size=0
        )


class TestScheduledPagePopulateFields:
    """Tests for ScheduledPage.populate_fields() method."""

    @pytest.fixture
    def widgets_dict(self):
        """Provide a mock widgets dictionary."""
        return {
            "enabled": mock.MagicMock(),
            "frequency": mock.MagicMock(),
            "time": mock.MagicMock(),
            "day_of_week": mock.MagicMock(),
            "day_of_month": mock.MagicMock(),
            "targets": mock.MagicMock(),
            "skip_on_battery": mock.MagicMock(),
            "auto_quarantine": mock.MagicMock(),
        }

    def test_populate_fields_with_none_config(self, mock_gi_modules, widgets_dict):
        """Test populate_fields handles None config gracefully."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        # Should not raise exception
        ScheduledPage.populate_fields(None, widgets_dict)

        # Should use default values
        widgets_dict["enabled"].set_active.assert_called_with(False)

    def test_populate_fields_with_empty_config(self, mock_gi_modules, widgets_dict):
        """Test populate_fields handles empty config dict."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        ScheduledPage.populate_fields({}, widgets_dict)

        # Should use default values
        widgets_dict["enabled"].set_active.assert_called_with(False)
        widgets_dict["frequency"].set_selected.assert_called_with(1)  # daily
        widgets_dict["time"].set_text.assert_called_with("02:00")

    def test_populate_fields_sets_enabled_switch(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets enabled switch correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"scheduled_scans_enabled": True}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["enabled"].set_active.assert_called_with(True)

    def test_populate_fields_sets_frequency_hourly(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets hourly frequency correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_frequency": "hourly"}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["frequency"].set_selected.assert_called_with(0)

    def test_populate_fields_sets_frequency_daily(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets daily frequency correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_frequency": "daily"}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["frequency"].set_selected.assert_called_with(1)

    def test_populate_fields_sets_frequency_weekly(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets weekly frequency correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_frequency": "weekly"}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["frequency"].set_selected.assert_called_with(2)

    def test_populate_fields_sets_frequency_monthly(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets monthly frequency correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_frequency": "monthly"}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["frequency"].set_selected.assert_called_with(3)

    def test_populate_fields_handles_invalid_frequency(self, mock_gi_modules, widgets_dict):
        """Test populate_fields handles invalid frequency value."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_frequency": "invalid"}
        ScheduledPage.populate_fields(config, widgets_dict)

        # Should default to daily (index 1)
        widgets_dict["frequency"].set_selected.assert_called_with(1)

    def test_populate_fields_sets_time(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets time correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_time": "15:30"}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["time"].set_text.assert_called_with("15:30")

    def test_populate_fields_sets_targets_from_list(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets targets from list correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_targets": ["/home/user", "/var/log"]}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["targets"].set_text.assert_called_with("/home/user, /var/log")

    def test_populate_fields_sets_targets_empty_list_to_home(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets targets to home directory when empty."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_targets": []}
        ScheduledPage.populate_fields(config, widgets_dict)

        # Should set to home directory
        call_args = widgets_dict["targets"].set_text.call_args[0][0]
        assert str(Path.home()) in call_args

    def test_populate_fields_sets_day_of_week(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets day of week correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_day_of_week": 3}  # Thursday
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["day_of_week"].set_selected.assert_called_with(3)

    def test_populate_fields_sets_day_of_month(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets day of month correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_day_of_month": 15}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["day_of_month"].set_value.assert_called_with(15)

    def test_populate_fields_sets_skip_on_battery(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets skip on battery correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_skip_on_battery": False}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["skip_on_battery"].set_active.assert_called_with(False)

    def test_populate_fields_sets_auto_quarantine(self, mock_gi_modules, widgets_dict):
        """Test populate_fields sets auto-quarantine correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {"schedule_auto_quarantine": True}
        ScheduledPage.populate_fields(config, widgets_dict)

        widgets_dict["auto_quarantine"].set_active.assert_called_with(True)

    def test_populate_fields_with_complete_config(self, mock_gi_modules, widgets_dict):
        """Test populate_fields with complete configuration."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {
            "scheduled_scans_enabled": True,
            "schedule_frequency": "weekly",
            "schedule_time": "03:30",
            "schedule_targets": ["/home/user/Documents", "/var/www"],
            "schedule_day_of_week": 5,  # Saturday
            "schedule_day_of_month": 20,
            "schedule_skip_on_battery": False,
            "schedule_auto_quarantine": True,
        }
        ScheduledPage.populate_fields(config, widgets_dict)

        # Verify all fields populated correctly
        widgets_dict["enabled"].set_active.assert_called_with(True)
        widgets_dict["frequency"].set_selected.assert_called_with(2)  # weekly
        widgets_dict["time"].set_text.assert_called_with("03:30")
        widgets_dict["targets"].set_text.assert_called_with("/home/user/Documents, /var/www")
        widgets_dict["day_of_week"].set_selected.assert_called_with(5)
        widgets_dict["day_of_month"].set_value.assert_called_with(20)
        widgets_dict["skip_on_battery"].set_active.assert_called_with(False)
        widgets_dict["auto_quarantine"].set_active.assert_called_with(True)

    def test_populate_fields_handles_missing_widgets(self, mock_gi_modules):
        """Test populate_fields does not crash when widgets are missing."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        config = {
            "scheduled_scans_enabled": True,
            "schedule_frequency": "weekly",
            "schedule_time": "03:30",
            "schedule_targets": ["/home/user/Documents"],
        }

        # Should not raise with an incomplete widget dictionary
        ScheduledPage.populate_fields(config, {})


class TestScheduledPageCollectData:
    """Tests for ScheduledPage.collect_data() method."""

    @pytest.fixture
    def widgets_dict(self):
        """Provide a mock widgets dictionary."""
        return {
            "enabled": mock.MagicMock(get_active=lambda: True),
            "frequency": mock.MagicMock(get_selected=lambda: 1),  # daily
            "time": mock.MagicMock(get_text=lambda: "02:00"),
            "day_of_week": mock.MagicMock(get_selected=lambda: 0),  # Monday
            "day_of_month": mock.MagicMock(get_value=lambda: 1),
            "targets": mock.MagicMock(get_text=lambda: "/home/user"),
            "skip_on_battery": mock.MagicMock(get_active=lambda: True),
            "auto_quarantine": mock.MagicMock(get_active=lambda: False),
        }

    def test_collect_data_returns_dict(self, mock_gi_modules, widgets_dict):
        """Test collect_data returns a dictionary."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        result = ScheduledPage.collect_data(widgets_dict)

        assert isinstance(result, dict)

    def test_collect_data_collects_enabled_state(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects enabled state."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        result = ScheduledPage.collect_data(widgets_dict)

        assert result["scheduled_scans_enabled"] is True

    def test_collect_data_collects_frequency_daily(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects daily frequency correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["frequency"].get_selected = lambda: 1
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_frequency"] == "daily"

    def test_collect_data_collects_frequency_hourly(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects hourly frequency correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["frequency"].get_selected = lambda: 0
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_frequency"] == "hourly"

    def test_collect_data_collects_frequency_weekly(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects weekly frequency correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["frequency"].get_selected = lambda: 2
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_frequency"] == "weekly"

    def test_collect_data_collects_frequency_monthly(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects monthly frequency correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["frequency"].get_selected = lambda: 3
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_frequency"] == "monthly"

    def test_collect_data_handles_invalid_frequency_index(self, mock_gi_modules, widgets_dict):
        """Test collect_data handles out-of-range frequency index."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["frequency"].get_selected = lambda: 99
        result = ScheduledPage.collect_data(widgets_dict)

        # Should default to "daily"
        assert result["schedule_frequency"] == "daily"

    def test_collect_data_collects_time(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects time correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["time"].get_text = lambda: "15:30"
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_time"] == "15:30"

    def test_collect_data_strips_whitespace_from_time(self, mock_gi_modules, widgets_dict):
        """Test collect_data strips whitespace from time."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["time"].get_text = lambda: "  03:45  "
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_time"] == "03:45"

    def test_collect_data_defaults_empty_time_to_0200(self, mock_gi_modules, widgets_dict):
        """Test collect_data defaults empty time to 02:00."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["time"].get_text = lambda: "   "
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_time"] == "02:00"

    def test_collect_data_parses_targets_to_list(self, mock_gi_modules, widgets_dict):
        """Test collect_data parses targets from comma-separated to list."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["targets"].get_text = lambda: "/home/user, /var/log, /etc"
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_targets"] == ["/home/user", "/var/log", "/etc"]

    def test_collect_data_strips_whitespace_from_targets(self, mock_gi_modules, widgets_dict):
        """Test collect_data strips whitespace from each target."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["targets"].get_text = lambda: "  /home/user  , /var/log,/etc  "
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_targets"] == ["/home/user", "/var/log", "/etc"]

    def test_collect_data_excludes_empty_targets(self, mock_gi_modules, widgets_dict):
        """Test collect_data excludes empty strings from targets."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["targets"].get_text = lambda: "/home/user, , /var/log,  , /etc"
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_targets"] == ["/home/user", "/var/log", "/etc"]

    def test_collect_data_handles_empty_targets(self, mock_gi_modules, widgets_dict):
        """Test collect_data handles empty targets string."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["targets"].get_text = lambda: ""
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_targets"] == []

    def test_collect_data_collects_day_of_week(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects day of week correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["day_of_week"].get_selected = lambda: 5  # Saturday
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_day_of_week"] == 5

    def test_collect_data_collects_day_of_month(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects day of month correctly."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["day_of_month"].get_value = lambda: 20.0
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_day_of_month"] == 20

    def test_collect_data_converts_day_of_month_to_int(self, mock_gi_modules, widgets_dict):
        """Test collect_data converts day of month to integer."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["day_of_month"].get_value = lambda: 15.5
        result = ScheduledPage.collect_data(widgets_dict)

        assert isinstance(result["schedule_day_of_month"], int)
        assert result["schedule_day_of_month"] == 15

    def test_collect_data_collects_skip_on_battery(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects skip on battery setting."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["skip_on_battery"].get_active = lambda: False
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_skip_on_battery"] is False

    def test_collect_data_collects_auto_quarantine(self, mock_gi_modules, widgets_dict):
        """Test collect_data collects auto-quarantine setting."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["auto_quarantine"].get_active = lambda: True
        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_auto_quarantine"] is True

    def test_collect_data_with_complete_form(self, mock_gi_modules, widgets_dict):
        """Test collect_data with complete form data."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["enabled"].get_active = lambda: True
        widgets_dict["frequency"].get_selected = lambda: 2  # weekly
        widgets_dict["time"].get_text = lambda: "03:30"
        widgets_dict["targets"].get_text = lambda: "/home/user/Documents, /var/www"
        widgets_dict["day_of_week"].get_selected = lambda: 5  # Saturday
        widgets_dict["day_of_month"].get_value = lambda: 20.0
        widgets_dict["skip_on_battery"].get_active = lambda: False
        widgets_dict["auto_quarantine"].get_active = lambda: True

        result = ScheduledPage.collect_data(widgets_dict)

        # Verify all fields collected correctly
        assert result == {
            "scheduled_scans_enabled": True,
            "schedule_frequency": "weekly",
            "schedule_time": "03:30",
            "schedule_targets": ["/home/user/Documents", "/var/www"],
            "schedule_day_of_week": 5,
            "schedule_day_of_month": 20,
            "schedule_skip_on_battery": False,
            "schedule_auto_quarantine": True,
        }

    def test_collect_data_has_all_required_keys(self, mock_gi_modules, widgets_dict):
        """Test collect_data returns all required keys."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        result = ScheduledPage.collect_data(widgets_dict)

        required_keys = [
            "scheduled_scans_enabled",
            "schedule_frequency",
            "schedule_time",
            "schedule_targets",
            "schedule_day_of_week",
            "schedule_day_of_month",
            "schedule_skip_on_battery",
            "schedule_auto_quarantine",
        ]

        for key in required_keys:
            assert key in result, f"Required key {key} not in result"

    def test_collect_data_returns_empty_when_page_never_created(self, mock_gi_modules):
        """collect_data must not fabricate defaults when the page has no widgets.

        Returning defaults for an empty widgets dict would overwrite the
        user's saved schedule (and disable the scheduler) whenever Save &
        Apply runs without the Scheduled page ever being opened.
        """
        from src.ui.preferences.scheduled_page import ScheduledPage

        assert ScheduledPage.collect_data({}) == {}

    def test_collect_data_handles_invalid_numeric_values(self, mock_gi_modules, widgets_dict):
        """Test collect_data falls back to defaults on invalid numeric values."""
        from src.ui.preferences.scheduled_page import ScheduledPage

        widgets_dict["frequency"].get_selected = lambda: "invalid"
        widgets_dict["day_of_month"].get_value = lambda: "not-a-number"

        result = ScheduledPage.collect_data(widgets_dict)

        assert result["schedule_frequency"] == "daily"
        assert result["schedule_day_of_month"] == 1
