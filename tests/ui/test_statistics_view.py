# ClamUI StatisticsView Tests
"""
Unit tests for the StatisticsView component.

Tests cover:
- Initialization and setup
- Timeframe selection and switching
- Statistics display updates
- Protection status display
- Chart rendering and empty states
- Loading state management
- Format helper methods
- Quick action callbacks
- Refresh functionality
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
def statistics_view_class(mock_gi_modules):
    """Get StatisticsView class with mocked dependencies."""
    # Mock matplotlib for GTK4
    mock_matplotlib = mock.MagicMock()
    mock_figure = mock.MagicMock()
    mock_canvas = mock.MagicMock()
    mock_backend = mock.MagicMock()
    mock_backend.FigureCanvasGTK4Agg = mock_canvas

    # Use patch.dict to properly restore sys.modules after test
    with mock.patch.dict(
        sys.modules,
        {
            "matplotlib": mock_matplotlib,
            "matplotlib.figure": mock_figure,
            "matplotlib.backends.backend_gtk4agg": mock_backend,
        },
    ):
        # Clear any cached import
        if "src.ui.statistics_view" in sys.modules:
            del sys.modules["src.ui.statistics_view"]

        from src.ui.statistics_view import StatisticsView

        yield StatisticsView

    # Critical: Clear all src.* modules after test to prevent pollution
    _clear_src_modules()


@pytest.fixture
def mock_statistics_view(statistics_view_class):
    """Create a mock StatisticsView instance for testing."""
    # Create instance without calling __init__
    view = object.__new__(statistics_view_class)

    # Set up required attributes
    view._calculator = mock.MagicMock()
    view._current_timeframe = "weekly"
    view._is_loading = False
    view._current_stats = None
    view._current_protection = None
    view._on_quick_scan_requested = None

    # Mock UI elements
    view._status_spinner = mock.MagicMock()
    view._refresh_button = mock.MagicMock()
    view._protection_row = mock.MagicMock()
    view._status_badge = mock.MagicMock()
    view._last_scan_row = mock.MagicMock()
    view._total_scans_label = mock.MagicMock()
    view._files_scanned_label = mock.MagicMock()
    view._threats_label = mock.MagicMock()
    view._clean_scans_label = mock.MagicMock()
    view._duration_label = mock.MagicMock()
    view._stats_group = mock.MagicMock()
    view._chart_group = mock.MagicMock()
    view._canvas = mock.MagicMock()
    view._figure = mock.MagicMock()
    view._chart_empty_state = mock.MagicMock()
    view._timeframe_buttons = {
        "daily": mock.MagicMock(),
        "weekly": mock.MagicMock(),
        "monthly": mock.MagicMock(),
        "all": mock.MagicMock(),
    }

    # Mock internal methods
    view._set_loading_state = mock.MagicMock()
    view._load_statistics_async = mock.MagicMock()
    view._perform_load = mock.MagicMock()
    view._update_statistics_display = mock.MagicMock()
    view._update_protection_display = mock.MagicMock()
    view._update_chart = mock.MagicMock()
    view._show_empty_state = mock.MagicMock()
    view.get_root = mock.MagicMock(return_value=None)

    return view


class TestStatisticsViewInitialization:
    """Tests for StatisticsView initialization."""

    def test_default_timeframe_is_weekly(self, mock_statistics_view):
        """Test that default timeframe is set to weekly."""
        assert mock_statistics_view._current_timeframe == "weekly"

    def test_initial_loading_state_is_false(self, mock_statistics_view):
        """Test that initial loading state is False."""
        assert mock_statistics_view._is_loading is False

    def test_initial_stats_is_none(self, mock_statistics_view):
        """Test that initial stats is None."""
        assert mock_statistics_view._current_stats is None

    def test_initial_protection_is_none(self, mock_statistics_view):
        """Test that initial protection status is None."""
        assert mock_statistics_view._current_protection is None

    def test_quick_scan_callback_is_none(self, mock_statistics_view):
        """Test that quick scan callback is initially None."""
        assert mock_statistics_view._on_quick_scan_requested is None


class TestStatisticsViewTimeframeSwitching:
    """Tests for timeframe switching functionality."""

    def test_on_timeframe_toggled_updates_current_timeframe(
        self, mock_statistics_view, statistics_view_class
    ):
        """Test that toggling timeframe updates the current timeframe."""
        # Get the actual method from the class
        view = object.__new__(statistics_view_class)
        view._current_timeframe = "weekly"
        view._timeframe_buttons = {
            "daily": mock.MagicMock(),
            "weekly": mock.MagicMock(),
            "monthly": mock.MagicMock(),
            "all": mock.MagicMock(),
        }
        view._load_statistics_async = mock.MagicMock()

        # Create mock button that returns True for get_active
        mock_button = mock.MagicMock()
        mock_button.get_active.return_value = True

        # Call the method
        view._on_timeframe_toggled(mock_button, "monthly")

        assert view._current_timeframe == "monthly"

    def test_on_timeframe_toggled_reloads_statistics(self, statistics_view_class):
        """Test that toggling timeframe triggers reload."""
        view = object.__new__(statistics_view_class)
        view._current_timeframe = "weekly"
        view._timeframe_buttons = {
            "daily": mock.MagicMock(),
            "weekly": mock.MagicMock(),
            "monthly": mock.MagicMock(),
            "all": mock.MagicMock(),
        }
        view._load_statistics_async = mock.MagicMock()

        mock_button = mock.MagicMock()
        mock_button.get_active.return_value = True

        view._on_timeframe_toggled(mock_button, "daily")

        view._load_statistics_async.assert_called_once()

    def test_on_timeframe_toggled_ignores_inactive_button(self, statistics_view_class):
        """Test that toggling inactive button does nothing."""
        view = object.__new__(statistics_view_class)
        view._current_timeframe = "weekly"
        view._timeframe_buttons = {
            "daily": mock.MagicMock(),
            "weekly": mock.MagicMock(),
            "monthly": mock.MagicMock(),
            "all": mock.MagicMock(),
        }
        view._load_statistics_async = mock.MagicMock()

        mock_button = mock.MagicMock()
        mock_button.get_active.return_value = False

        view._on_timeframe_toggled(mock_button, "daily")

        # Should not change timeframe or reload
        assert view._current_timeframe == "weekly"
        view._load_statistics_async.assert_not_called()

    def test_on_timeframe_toggled_deactivates_other_buttons(self, statistics_view_class):
        """Test that toggling one button deactivates others."""
        view = object.__new__(statistics_view_class)
        view._current_timeframe = "weekly"

        mock_buttons = {
            "daily": mock.MagicMock(),
            "weekly": mock.MagicMock(),
            "monthly": mock.MagicMock(),
            "all": mock.MagicMock(),
        }
        view._timeframe_buttons = mock_buttons
        view._load_statistics_async = mock.MagicMock()

        mock_button = mock.MagicMock()
        mock_button.get_active.return_value = True

        view._on_timeframe_toggled(mock_button, "monthly")

        # Check that other buttons were deactivated
        mock_buttons["daily"].set_active.assert_called_with(False)
        mock_buttons["weekly"].set_active.assert_called_with(False)
        mock_buttons["all"].set_active.assert_called_with(False)


class TestStatisticsViewLoadingState:
    """Tests for loading state management."""

    def test_set_loading_state_true_shows_spinner(self, statistics_view_class):
        """Test that setting loading True shows spinner."""
        view = object.__new__(statistics_view_class)
        view._is_loading = False
        view._status_spinner = mock.MagicMock()
        view._refresh_button = mock.MagicMock()

        view._set_loading_state(True)

        assert view._is_loading is True
        view._status_spinner.set_visible.assert_called_with(True)
        view._status_spinner.start.assert_called_once()
        view._refresh_button.set_sensitive.assert_called_with(False)

    def test_set_loading_state_false_hides_spinner(self, statistics_view_class):
        """Test that setting loading False hides spinner."""
        view = object.__new__(statistics_view_class)
        view._is_loading = True
        view._status_spinner = mock.MagicMock()
        view._refresh_button = mock.MagicMock()

        view._set_loading_state(False)

        assert view._is_loading is False
        view._status_spinner.stop.assert_called_once()
        view._status_spinner.set_visible.assert_called_with(False)
        view._refresh_button.set_sensitive.assert_called_with(True)

    def test_load_statistics_async_prevents_double_load(self, statistics_view_class):
        """Test that async load prevents loading when already loading."""
        with mock.patch.dict(sys.modules, {"gi.repository": mock.MagicMock()}):
            view = object.__new__(statistics_view_class)
            view._is_loading = True
            view._set_loading_state = mock.MagicMock()

            result = view._load_statistics_async()

            assert result is False
            view._set_loading_state.assert_not_called()


class TestStatisticsViewFormatHelpers:
    """Tests for format helper methods."""

    def test_format_number_with_small_number(self, statistics_view_class):
        """Test formatting a small number."""
        view = object.__new__(statistics_view_class)
        result = view._format_number(42)
        assert result == "42"

    def test_format_number_with_thousands(self, statistics_view_class):
        """Test formatting a number with thousands."""
        view = object.__new__(statistics_view_class)
        result = view._format_number(1234)
        assert result == "1,234"

    def test_format_number_with_millions(self, statistics_view_class):
        """Test formatting a large number."""
        view = object.__new__(statistics_view_class)
        result = view._format_number(1234567)
        assert result == "1,234,567"

    def test_format_number_with_zero(self, statistics_view_class):
        """Test formatting zero."""
        view = object.__new__(statistics_view_class)
        result = view._format_number(0)
        assert result == "0"

    def test_format_duration_seconds(self, statistics_view_class):
        """Test formatting duration under a minute."""
        view = object.__new__(statistics_view_class)
        result = view._format_duration(45.5)
        assert result == "45.5s"

    def test_format_duration_minutes(self, statistics_view_class):
        """Test formatting duration in minutes."""
        view = object.__new__(statistics_view_class)
        result = view._format_duration(150)
        assert result == "2m 30s"

    def test_format_duration_hours(self, statistics_view_class):
        """Test formatting duration in hours."""
        view = object.__new__(statistics_view_class)
        result = view._format_duration(3900)  # 1h 5m
        assert result == "1h 5m"

    def test_format_duration_zero(self, statistics_view_class):
        """Test formatting zero duration."""
        view = object.__new__(statistics_view_class)
        result = view._format_duration(0)
        assert result == "0.0s"


class TestStatisticsViewDataPointsForTimeframe:
    """Tests for _get_data_points_for_timeframe method."""

    def test_daily_returns_six(self, statistics_view_class):
        """Test daily timeframe returns 6 data points."""
        view = object.__new__(statistics_view_class)
        result = view._get_data_points_for_timeframe("daily")
        assert result == 6

    def test_weekly_returns_seven(self, statistics_view_class):
        """Test weekly timeframe returns 7 data points."""
        view = object.__new__(statistics_view_class)
        result = view._get_data_points_for_timeframe("weekly")
        assert result == 7

    def test_monthly_returns_ten(self, statistics_view_class):
        """Test monthly timeframe returns 10 data points."""
        view = object.__new__(statistics_view_class)
        result = view._get_data_points_for_timeframe("monthly")
        assert result == 10

    def test_all_returns_twelve(self, statistics_view_class):
        """Test all timeframe returns 12 data points."""
        view = object.__new__(statistics_view_class)
        result = view._get_data_points_for_timeframe("all")
        assert result == 12

    def test_unknown_returns_twelve(self, statistics_view_class):
        """Test unknown timeframe defaults to 12 data points."""
        view = object.__new__(statistics_view_class)
        result = view._get_data_points_for_timeframe("unknown")
        assert result == 12


class TestStatisticsViewQuickScanCallback:
    """Tests for quick scan callback functionality."""

    def test_set_quick_scan_callback(self, statistics_view_class):
        """Test setting the quick scan callback."""
        view = object.__new__(statistics_view_class)
        view._on_quick_scan_requested = None

        callback = mock.MagicMock()
        view.set_quick_scan_callback(callback)

        assert view._on_quick_scan_requested is callback

    def test_on_quick_scan_clicked_calls_callback(self, statistics_view_class):
        """Test that quick scan click calls the callback."""
        view = object.__new__(statistics_view_class)
        callback = mock.MagicMock()
        view._on_quick_scan_requested = callback
        view.get_root = mock.MagicMock(return_value=None)

        mock_row = mock.MagicMock()
        view._on_quick_scan_clicked(mock_row)

        callback.assert_called_once()

    def test_on_quick_scan_clicked_without_callback_tries_action(self, statistics_view_class):
        """Test that quick scan click tries app action when no callback."""
        view = object.__new__(statistics_view_class)
        view._on_quick_scan_requested = None

        mock_app = mock.MagicMock()
        mock_app.activate_action = mock.MagicMock()
        view.get_root = mock.MagicMock(return_value=mock_app)

        mock_row = mock.MagicMock()
        view._on_quick_scan_clicked(mock_row)

        mock_app.activate_action.assert_called_once()


class TestStatisticsViewLogsClick:
    """Tests for view logs click functionality."""

    def test_on_view_logs_clicked_activates_action(self, statistics_view_class):
        """Test that view logs click activates the show-logs action."""
        view = object.__new__(statistics_view_class)

        mock_app = mock.MagicMock()
        mock_app.activate_action = mock.MagicMock()
        view.get_root = mock.MagicMock(return_value=mock_app)

        mock_row = mock.MagicMock()
        view._on_view_logs_clicked(mock_row)

        mock_app.activate_action.assert_called_once()


class TestStatisticsViewRefresh:
    """Tests for refresh functionality."""

    def test_on_refresh_clicked_loads_statistics(self, statistics_view_class):
        """Test that refresh button click triggers load."""
        view = object.__new__(statistics_view_class)
        view._load_statistics_async = mock.MagicMock()

        mock_button = mock.MagicMock()
        view._on_refresh_clicked(mock_button)

        view._load_statistics_async.assert_called_once()

    def test_refresh_statistics_public_method(self, statistics_view_class):
        """Test that public refresh_statistics method works."""
        with mock.patch.dict(sys.modules, {"gi.repository": mock.MagicMock()}):
            view = object.__new__(statistics_view_class)
            view._load_statistics_async = mock.MagicMock()

            # Mock GLib.idle_add to call the function immediately
            mock_glib = mock.MagicMock()
            mock_glib.idle_add = lambda f: f()

            with mock.patch.dict(sys.modules, {"gi.repository.GLib": mock_glib}):
                # The method should schedule loading
                view.refresh_statistics()


class TestStatisticsViewCalculator:
    """Tests for calculator property."""

    def test_calculator_property_returns_calculator(self, statistics_view_class):
        """Test that calculator property returns the internal calculator."""
        view = object.__new__(statistics_view_class)
        mock_calc = mock.MagicMock()
        view._calculator = mock_calc

        result = view.calculator

        assert result is mock_calc


class TestStatisticsViewShowEmptyState:
    """Tests for empty state display."""

    def test_show_empty_state_sets_zero_values(self, statistics_view_class):
        """Test that empty state sets all values to zero."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_empty_state()

        view._total_scans_label.set_label.assert_called_with("0")
        view._files_scanned_label.set_label.assert_called_with("0")
        view._threats_label.set_label.assert_called_with("0")
        view._clean_scans_label.set_label.assert_called_with("0")
        view._duration_label.set_label.assert_called_with("--")

    def test_show_empty_state_sets_no_data_badge(self, statistics_view_class):
        """Test that empty state sets 'No Data' badge."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_empty_state()

        view._status_badge.set_label.assert_called_with("No Data")


class TestStatisticsViewUpdateChart:
    """Tests for chart update functionality."""

    def test_update_chart_empty_data_shows_empty_state(self, statistics_view_class):
        """Test that empty data shows the empty state."""
        view = object.__new__(statistics_view_class)
        view._figure = mock.MagicMock()
        view._canvas = mock.MagicMock()
        view._chart_empty_state = mock.MagicMock()
        view._chart_group = mock.MagicMock()

        view._update_chart([])

        # With incremental updates, we don't clear the figure for empty data
        # since the canvas is hidden anyway - this is more efficient
        view._canvas.set_visible.assert_called_with(False)
        view._chart_empty_state.set_visible.assert_called_with(True)

    def test_update_chart_zero_scans_shows_empty_state(self, statistics_view_class):
        """Test that all-zero data shows empty state."""
        view = object.__new__(statistics_view_class)
        view._figure = mock.MagicMock()
        view._canvas = mock.MagicMock()
        view._chart_empty_state = mock.MagicMock()
        view._chart_group = mock.MagicMock()

        # Data with all zero scans
        data = [
            {"date": "2024-01-01", "scans": 0, "threats": 0},
            {"date": "2024-01-02", "scans": 0, "threats": 0},
        ]
        view._update_chart(data)

        view._canvas.set_visible.assert_called_with(False)
        view._chart_empty_state.set_visible.assert_called_with(True)

    def test_update_chart_with_data_shows_canvas(self, statistics_view_class):
        """Test that valid data shows the canvas."""
        view = object.__new__(statistics_view_class)
        view._figure = mock.MagicMock()
        view._canvas = mock.MagicMock()
        view._canvas.get_style_context.return_value.get_color.return_value = mock.MagicMock(
            red=0.1, green=0.1, blue=0.1
        )
        view._chart_empty_state = mock.MagicMock()
        view._chart_group = mock.MagicMock()
        # Initialize incremental chart state variables
        view._chart_ax = None
        view._chart_bars_scans = None
        view._chart_bars_threats = None
        view._chart_initialized = False

        # Data with some scans
        data = [
            {"date": "2024-01-01T00:00:00", "scans": 5, "threats": 1},
            {"date": "2024-01-02T00:00:00", "scans": 3, "threats": 0},
        ]
        view._update_chart(data)

        view._canvas.set_visible.assert_called_with(True)
        view._chart_empty_state.set_visible.assert_called_with(False)

    def test_update_chart_incremental_update_reuses_bars(self, statistics_view_class):
        """Test that incremental updates reuse existing bar containers."""
        view = object.__new__(statistics_view_class)
        view._figure = mock.MagicMock()
        mock_ax = mock.MagicMock()
        # Create mock bar containers with the right length (2 bars each)
        mock_bar1 = mock.MagicMock()
        mock_bar2 = mock.MagicMock()
        mock_bars_scans = [mock_bar1, mock_bar2]
        mock_bars_threats = [mock_bar1, mock_bar2]
        mock_ax.bar.side_effect = [mock_bars_scans, mock_bars_threats]
        view._figure.add_subplot.return_value = mock_ax
        view._canvas = mock.MagicMock()
        view._canvas.get_style_context.return_value.get_color.return_value = mock.MagicMock(
            red=0.1, green=0.1, blue=0.1
        )
        view._chart_empty_state = mock.MagicMock()
        view._chart_group = mock.MagicMock()
        # Initialize incremental chart state variables
        view._chart_ax = None
        view._chart_bars_scans = None
        view._chart_bars_threats = None
        view._chart_initialized = False

        # First update: should do full initialization
        data1 = [
            {"date": "2024-01-01T00:00:00", "scans": 5, "threats": 1},
            {"date": "2024-01-02T00:00:00", "scans": 3, "threats": 0},
        ]
        view._update_chart(data1)

        # Verify figure.clear and add_subplot were called (full init)
        view._figure.clear.assert_called_once()
        view._figure.add_subplot.assert_called_once()
        assert view._chart_initialized is True

        # Reset mocks for second update
        view._figure.clear.reset_mock()
        view._figure.add_subplot.reset_mock()

        # Second update with same number of data points: should do incremental update
        data2 = [
            {"date": "2024-01-03T00:00:00", "scans": 7, "threats": 2},
            {"date": "2024-01-04T00:00:00", "scans": 4, "threats": 1},
        ]
        view._update_chart(data2)

        # Verify figure.clear and add_subplot were NOT called (incremental)
        view._figure.clear.assert_not_called()
        view._figure.add_subplot.assert_not_called()

    def test_update_chart_reinitializes_when_data_points_change(self, statistics_view_class):
        """Test that chart reinitializes when number of data points changes."""
        view = object.__new__(statistics_view_class)
        view._figure = mock.MagicMock()
        mock_ax = mock.MagicMock()
        view._figure.add_subplot.return_value = mock_ax
        view._canvas = mock.MagicMock()
        view._canvas.get_style_context.return_value.get_color.return_value = mock.MagicMock(
            red=0.1, green=0.1, blue=0.1
        )
        view._chart_empty_state = mock.MagicMock()
        view._chart_group = mock.MagicMock()
        # Initialize incremental chart state variables
        view._chart_ax = None
        view._chart_bars_scans = None
        view._chart_bars_threats = None
        view._chart_initialized = False

        # First update with 2 data points
        data1 = [
            {"date": "2024-01-01T00:00:00", "scans": 5, "threats": 1},
            {"date": "2024-01-02T00:00:00", "scans": 3, "threats": 0},
        ]
        view._update_chart(data1)
        view._figure.clear.reset_mock()
        view._figure.add_subplot.reset_mock()

        # Second update with 3 data points: should reinitialize
        data2 = [
            {"date": "2024-01-01T00:00:00", "scans": 5, "threats": 1},
            {"date": "2024-01-02T00:00:00", "scans": 3, "threats": 0},
            {"date": "2024-01-03T00:00:00", "scans": 7, "threats": 2},
        ]
        view._update_chart(data2)

        # Verify figure.clear and add_subplot were called (reinit due to different count)
        view._figure.clear.assert_called_once()
        view._figure.add_subplot.assert_called_once()


class TestStatisticsViewUpdateProtectionDisplay:
    """Tests for protection display updates."""

    def test_update_protection_display_none_shows_unknown(self, statistics_view_class):
        """Test that None protection status shows unknown."""
        view = object.__new__(statistics_view_class)
        view._current_protection = None
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()

        view._update_protection_display()

        view._protection_row.set_subtitle.assert_called_with("Unable to determine status")
        view._protection_row_icon.set_from_icon_name.assert_called_with("dialog-question-symbolic")
        view._status_badge.set_label.assert_called_with("Unknown")

    def test_update_protection_display_protected(self, statistics_view_class):
        """Test that protected status shows correct UI."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.statistics_calculator": mock.MagicMock(),
            },
        ):
            # Create a mock ProtectionStatus
            mock_status = mock.MagicMock()
            mock_status.level = "protected"
            mock_status.message = "System is protected"
            mock_status.last_scan_timestamp = "2024-01-01T12:00:00"
            mock_status.last_scan_age_hours = 2.5

            view = object.__new__(statistics_view_class)
            view._current_protection = mock_status
            view._protection_row = mock.MagicMock()
            view._protection_row_icon = mock.MagicMock()
            view._status_badge = mock.MagicMock()
            view._last_scan_row = mock.MagicMock()

            # Import ProtectionLevel to check against
            view._update_protection_display()

            view._protection_row.set_subtitle.assert_called_with("System is protected")
            view._protection_row_icon.set_from_icon_name.assert_called_with(
                "object-select-symbolic"
            )
            view._status_badge.set_label.assert_called_with("Protected")
            view._status_badge.add_css_class.assert_called_with("success")

    def test_update_protection_display_at_risk(self, statistics_view_class):
        """Test that at_risk status shows warning UI."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.statistics_calculator": mock.MagicMock(),
            },
        ):
            mock_status = mock.MagicMock()
            mock_status.level = "at_risk"
            mock_status.message = "Last scan was over a week ago"
            mock_status.last_scan_timestamp = "2024-01-01T12:00:00"
            mock_status.last_scan_age_hours = 200

            view = object.__new__(statistics_view_class)
            view._current_protection = mock_status
            view._protection_row = mock.MagicMock()
            view._protection_row_icon = mock.MagicMock()
            view._status_badge = mock.MagicMock()
            view._last_scan_row = mock.MagicMock()

            view._update_protection_display()

            view._protection_row_icon.set_from_icon_name.assert_called_with(
                "dialog-warning-symbolic"
            )
            view._status_badge.set_label.assert_called_with("At Risk")
            view._status_badge.add_css_class.assert_called_with("warning")

    def test_update_protection_display_unprotected(self, statistics_view_class):
        """Test that unprotected status shows error UI."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.statistics_calculator": mock.MagicMock(),
            },
        ):
            mock_status = mock.MagicMock()
            mock_status.level = "unprotected"
            mock_status.message = "No scans performed yet"
            mock_status.last_scan_timestamp = None
            mock_status.last_scan_age_hours = None

            view = object.__new__(statistics_view_class)
            view._current_protection = mock_status
            view._protection_row = mock.MagicMock()
            view._protection_row_icon = mock.MagicMock()
            view._status_badge = mock.MagicMock()
            view._last_scan_row = mock.MagicMock()

            view._update_protection_display()

            view._protection_row_icon.set_from_icon_name.assert_called_with("dialog-error-symbolic")
            view._status_badge.set_label.assert_called_with("Unprotected")
            view._status_badge.add_css_class.assert_called_with("error")


class TestStatisticsViewUpdateStatisticsDisplay:
    """Tests for statistics display updates."""

    def test_update_statistics_display_none_shows_empty_state(self, statistics_view_class):
        """Test that None stats shows empty state."""
        view = object.__new__(statistics_view_class)
        view._current_stats = None
        view._show_empty_state = mock.MagicMock()

        view._update_statistics_display()

        view._show_empty_state.assert_called_once()

    def test_update_statistics_display_with_data(self, statistics_view_class):
        """Test that stats data updates all labels."""
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 10
        mock_stats.files_scanned = 1500
        mock_stats.threats_detected = 2
        mock_stats.clean_scans = 8
        mock_stats.average_duration = 45.5
        mock_stats.start_date = "2024-01-01T00:00:00"
        mock_stats.end_date = "2024-01-31T23:59:59"

        view = object.__new__(statistics_view_class)
        view._current_stats = mock_stats
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._stats_group = mock.MagicMock()
        view._format_number = lambda n: f"{n:,}"
        view._format_duration = lambda s: f"{s}s"
        view._show_empty_state = mock.MagicMock()

        view._update_statistics_display()

        view._total_scans_label.set_label.assert_called_with("10")
        view._files_scanned_label.set_label.assert_called_with("1,500")
        view._threats_label.set_label.assert_called_with("2")
        view._clean_scans_label.set_label.assert_called_with("8")

    def test_update_statistics_display_threats_adds_error_class(self, statistics_view_class):
        """Test that threats > 0 adds error CSS class."""
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 10
        mock_stats.files_scanned = 1500
        mock_stats.threats_detected = 5
        mock_stats.clean_scans = 5
        mock_stats.average_duration = 45.5
        mock_stats.start_date = None
        mock_stats.end_date = None

        view = object.__new__(statistics_view_class)
        view._current_stats = mock_stats
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._stats_group = mock.MagicMock()
        view._format_number = lambda n: f"{n:,}"
        view._format_duration = lambda s: f"{s}s"
        view._show_empty_state = mock.MagicMock()

        view._update_statistics_display()

        view._threats_label.add_css_class.assert_called_with("error")

    def test_update_statistics_display_no_threats_removes_error_class(self, statistics_view_class):
        """Test that threats = 0 removes error CSS class."""
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 10
        mock_stats.files_scanned = 1500
        mock_stats.threats_detected = 0
        mock_stats.clean_scans = 10
        mock_stats.average_duration = 45.5
        mock_stats.start_date = None
        mock_stats.end_date = None

        view = object.__new__(statistics_view_class)
        view._current_stats = mock_stats
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._stats_group = mock.MagicMock()
        view._format_number = lambda n: f"{n:,}"
        view._format_duration = lambda s: f"{s}s"
        view._show_empty_state = mock.MagicMock()

        view._update_statistics_display()

        view._threats_label.remove_css_class.assert_called_with("error")

    def test_update_statistics_display_zero_duration_shows_placeholder(self, statistics_view_class):
        """Test that zero duration shows placeholder."""
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 10
        mock_stats.files_scanned = 1500
        mock_stats.threats_detected = 0
        mock_stats.clean_scans = 10
        mock_stats.average_duration = 0
        mock_stats.start_date = None
        mock_stats.end_date = None

        view = object.__new__(statistics_view_class)
        view._current_stats = mock_stats
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._stats_group = mock.MagicMock()
        view._format_number = lambda n: f"{n:,}"
        view._format_duration = lambda s: f"{s}s"
        view._show_empty_state = mock.MagicMock()

        view._update_statistics_display()

        view._duration_label.set_label.assert_called_with("--")


class TestStatisticsViewImport:
    """Tests for StatisticsView import."""

    def test_import_statistics_view(self, mock_gi_modules):
        """Test that StatisticsView can be imported."""
        # Mock matplotlib for GTK4
        mock_matplotlib = mock.MagicMock()
        mock_figure = mock.MagicMock()
        mock_backend = mock.MagicMock()
        mock_backend.FigureCanvasGTK4Agg = mock.MagicMock()

        with mock.patch.dict(
            sys.modules,
            {
                "matplotlib": mock_matplotlib,
                "matplotlib.figure": mock_figure,
                "matplotlib.backends.backend_gtk4agg": mock_backend,
                "src.core.statistics_calculator": mock.MagicMock(),
            },
        ):
            from src.ui.statistics_view import StatisticsView

            assert StatisticsView is not None


# Module-level test function for verification
def test_statistics_view_basic(statistics_view_class):
    """
    Basic test function for pytest verification command.

    This test verifies the core StatisticsView functionality
    using the centralized mock setup from conftest.py.
    """
    # Test 1: Class can be imported
    assert statistics_view_class is not None

    # Test 2: Create mock instance and test format helpers
    view = object.__new__(statistics_view_class)

    # Test _format_number
    assert view._format_number(1234) == "1,234"
    assert view._format_number(0) == "0"

    # Test _format_duration
    assert view._format_duration(45.0) == "45.0s"
    assert view._format_duration(150) == "2m 30s"
    assert view._format_duration(3900) == "1h 5m"

    # Test _get_data_points_for_timeframe
    assert view._get_data_points_for_timeframe("daily") == 6
    assert view._get_data_points_for_timeframe("weekly") == 7
    assert view._get_data_points_for_timeframe("monthly") == 10
    assert view._get_data_points_for_timeframe("all") == 12


class TestStatisticsViewErrorState:
    """Tests for error state display."""

    def test_show_error_state_sets_dashes(self, statistics_view_class):
        """Test that error state sets all labels to dashes."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_error_state("Test error")

        view._total_scans_label.set_label.assert_called_with("--")
        view._files_scanned_label.set_label.assert_called_with("--")
        view._threats_label.set_label.assert_called_with("--")
        view._clean_scans_label.set_label.assert_called_with("--")
        view._duration_label.set_label.assert_called_with("--")

    def test_show_error_state_sets_error_badge(self, statistics_view_class):
        """Test that error state sets 'Error' badge with error class."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_error_state("Test error")

        view._status_badge.set_label.assert_called_with("Error")
        view._status_badge.add_css_class.assert_called_with("error")

    def test_show_error_state_sets_description(self, statistics_view_class):
        """Test that error state uses the provided error message as description."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_error_state("Custom error message")

        view._stats_group.set_description.assert_called_with("Custom error message")

    def test_show_error_state_default_message(self, statistics_view_class):
        """Test that error state uses default message when none provided."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_error_state()

        # Default message should be set
        view._stats_group.set_description.assert_called_once()
        call_arg = view._stats_group.set_description.call_args[0][0]
        assert "Unable to load statistics" in call_arg

    def test_show_error_state_sets_error_icon(self, statistics_view_class):
        """Test that error state shows the error icon."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_error_state()

        view._protection_row_icon.set_from_icon_name.assert_called_once()
        icon_arg = view._protection_row_icon.set_from_icon_name.call_args[0][0]
        assert "error" in icon_arg

    def test_show_error_state_removes_threat_styling(self, statistics_view_class):
        """Test that error state removes error class from threats label."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_error_state()

        view._threats_label.remove_css_class.assert_called_with("error")


class TestStatisticsViewPerformLoad:
    """Tests for the _perform_load method."""

    def test_perform_load_with_valid_data(self, statistics_view_class):
        """Test _perform_load updates UI when data is available."""
        view = object.__new__(statistics_view_class)
        view._calculator = mock.MagicMock()
        view._current_timeframe = "weekly"

        # Set up mock return values
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 5
        view._calculator.get_statistics.return_value = mock_stats
        view._calculator.get_protection_status.return_value = mock.MagicMock()
        view._calculator.get_scan_trend_data.return_value = [
            {"date": "2024-01-01", "scans": 1, "threats": 0}
        ]

        # Mock UI methods
        view._update_statistics_display = mock.MagicMock()
        view._update_protection_display = mock.MagicMock()
        view._update_chart = mock.MagicMock()
        view._set_loading_state = mock.MagicMock()
        view._show_empty_state = mock.MagicMock()
        view._show_error_state = mock.MagicMock()

        with mock.patch(
            "src.ui.statistics_view.GLib.idle_add",
            side_effect=lambda fn, *a: fn(*a),
        ):
            view._perform_load()

        # _perform_load now runs on a worker thread and delegates all UI work
        # to _apply_statistics_results via idle_add; the patched idle_add runs
        # that applier synchronously so the observable outcomes are testable.
        view._update_statistics_display.assert_called_once()
        view._update_protection_display.assert_called_once()
        view._update_chart.assert_called_once()
        view._set_loading_state.assert_called_with(False)

    def test_perform_load_no_stats_shows_empty(self, statistics_view_class):
        """Test _perform_load shows empty state when no scan history."""
        view = object.__new__(statistics_view_class)
        view._calculator = mock.MagicMock()
        view._current_timeframe = "weekly"

        # Return stats with zero scans
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 0
        view._calculator.get_statistics.return_value = mock_stats
        view._calculator.get_protection_status.return_value = mock.MagicMock()
        view._calculator.get_scan_trend_data.return_value = []

        view._update_statistics_display = mock.MagicMock()
        view._update_protection_display = mock.MagicMock()
        view._update_chart = mock.MagicMock()
        view._set_loading_state = mock.MagicMock()
        view._show_empty_state = mock.MagicMock()
        view._show_error_state = mock.MagicMock()

        with mock.patch(
            "src.ui.statistics_view.GLib.idle_add",
            side_effect=lambda fn, *a: fn(*a),
        ):
            view._perform_load()

        view._show_empty_state.assert_called_once()
        view._update_protection_display.assert_called_once()
        view._update_chart.assert_called_with([])

    def test_perform_load_complete_failure_shows_error(self, statistics_view_class):
        """Test _perform_load shows error state when all loading fails."""
        view = object.__new__(statistics_view_class)
        view._calculator = mock.MagicMock()
        view._current_timeframe = "weekly"

        # Simulate complete failure
        view._calculator.get_statistics.side_effect = Exception("DB error")
        view._calculator.get_protection_status.side_effect = Exception("DB error")
        view._calculator.get_scan_trend_data.side_effect = Exception("DB error")

        view._update_statistics_display = mock.MagicMock()
        view._update_protection_display = mock.MagicMock()
        view._update_chart = mock.MagicMock()
        view._set_loading_state = mock.MagicMock()
        view._show_empty_state = mock.MagicMock()
        view._show_error_state = mock.MagicMock()

        with mock.patch(
            "src.ui.statistics_view.GLib.idle_add",
            side_effect=lambda fn, *a: fn(*a),
        ):
            view._perform_load()

        view._show_error_state.assert_called_once()
        view._update_chart.assert_called_with([])

    def test_perform_load_always_resets_loading_state(self, statistics_view_class):
        """Test _perform_load always resets loading state in finally block."""
        view = object.__new__(statistics_view_class)
        view._calculator = mock.MagicMock()
        view._current_timeframe = "weekly"

        # Simulate data loading succeeding but UI update raising
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 5
        view._calculator.get_statistics.return_value = mock_stats
        view._calculator.get_protection_status.return_value = mock.MagicMock()
        view._calculator.get_scan_trend_data.return_value = []
        view._update_statistics_display = mock.MagicMock(side_effect=Exception("UI error"))
        view._update_protection_display = mock.MagicMock()
        view._update_chart = mock.MagicMock()
        view._set_loading_state = mock.MagicMock()
        view._show_empty_state = mock.MagicMock()
        view._show_error_state = mock.MagicMock()

        with mock.patch(
            "src.ui.statistics_view.GLib.idle_add",
            side_effect=lambda fn, *a: fn(*a),
        ):
            view._perform_load()

        # Loading state should ALWAYS be reset
        view._set_loading_state.assert_called_with(False)

    def test_perform_load_uses_correct_data_points(self, statistics_view_class):
        """Test _perform_load passes correct data points count per timeframe."""
        view = object.__new__(statistics_view_class)
        view._calculator = mock.MagicMock()
        view._current_timeframe = "daily"

        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 5
        view._calculator.get_statistics.return_value = mock_stats
        view._calculator.get_protection_status.return_value = mock.MagicMock()
        view._calculator.get_scan_trend_data.return_value = []

        view._update_statistics_display = mock.MagicMock()
        view._update_protection_display = mock.MagicMock()
        view._update_chart = mock.MagicMock()
        view._set_loading_state = mock.MagicMock()
        view._show_empty_state = mock.MagicMock()
        view._show_error_state = mock.MagicMock()

        view._perform_load()

        # Daily should use 6 data points
        view._calculator.get_scan_trend_data.assert_called_once_with("daily", 6)


class TestStatisticsViewLoadingStateTimeframeButtons:
    """Tests for loading state interaction with timeframe buttons."""

    def test_set_loading_true_disables_timeframe_buttons(self, statistics_view_class):
        """Test that loading state disables all timeframe buttons."""
        view = object.__new__(statistics_view_class)
        view._is_loading = False
        view._status_spinner = mock.MagicMock()
        view._refresh_button = mock.MagicMock()
        view._timeframe_buttons = {
            "daily": mock.MagicMock(),
            "weekly": mock.MagicMock(),
            "monthly": mock.MagicMock(),
            "all": mock.MagicMock(),
        }

        view._set_loading_state(True)

        for button in view._timeframe_buttons.values():
            button.set_sensitive.assert_called_with(False)

    def test_set_loading_false_enables_timeframe_buttons(self, statistics_view_class):
        """Test that ending loading state re-enables all timeframe buttons."""
        view = object.__new__(statistics_view_class)
        view._is_loading = True
        view._status_spinner = mock.MagicMock()
        view._refresh_button = mock.MagicMock()
        view._timeframe_buttons = {
            "daily": mock.MagicMock(),
            "weekly": mock.MagicMock(),
            "monthly": mock.MagicMock(),
            "all": mock.MagicMock(),
        }

        view._set_loading_state(False)

        for button in view._timeframe_buttons.values():
            button.set_sensitive.assert_called_with(True)

    def test_set_loading_exception_resets_flag(self, statistics_view_class):
        """Test that loading state flag is reset even if widget ops fail."""
        view = object.__new__(statistics_view_class)
        view._is_loading = False
        view._status_spinner = mock.MagicMock()
        view._status_spinner.set_visible.side_effect = Exception("Widget error")
        view._refresh_button = mock.MagicMock()
        view._timeframe_buttons = {}

        view._set_loading_state(True)

        # Flag should be reset to False on exception
        assert view._is_loading is False


class TestStatisticsViewChartScroll:
    """Tests for chart scroll event handling."""

    def test_on_chart_scroll_returns_true(self, statistics_view_class):
        """Test scroll handler returns True to stop event propagation."""
        view = object.__new__(statistics_view_class)

        # Mock canvas with no parent ScrolledWindow
        view._canvas = mock.MagicMock()
        view._canvas.get_parent.return_value = None

        result = view._on_chart_scroll(mock.MagicMock(), 0, 1)

        # Should still return True even without ScrolledWindow
        assert result is True

    def test_on_chart_scroll_with_scrolled_parent(self, statistics_view_class, mock_gi_modules):
        """Test scroll handler adjusts vadjustment when parent is ScrolledWindow."""
        # To make isinstance(widget, Gtk.ScrolledWindow) work with mocked GTK,
        # we make Gtk.ScrolledWindow a real class and create an instance of it
        gtk = mock_gi_modules["gtk"]

        class FakeScrolledWindow:
            pass

        gtk.ScrolledWindow = FakeScrolledWindow

        # Reimport to pick up the patched Gtk.ScrolledWindow
        _clear_src_modules()
        from src.ui.statistics_view import StatisticsView

        view = object.__new__(StatisticsView)

        mock_scrolled = FakeScrolledWindow()
        mock_vadj = mock.MagicMock()
        mock_vadj.get_value.return_value = 100
        mock_vadj.get_lower.return_value = 0
        mock_vadj.get_upper.return_value = 500
        mock_vadj.get_page_size.return_value = 200
        mock_scrolled.get_vadjustment = mock.MagicMock(return_value=mock_vadj)

        view._canvas = mock.MagicMock()
        view._canvas.get_parent.return_value = mock_scrolled

        result = view._on_chart_scroll(mock.MagicMock(), 0, 1)

        assert result is True
        mock_vadj.set_value.assert_called_once()
        # Scroll down: new_value = 100 + (1 * 50) = 150
        new_val = mock_vadj.set_value.call_args[0][0]
        assert new_val == 150

        _clear_src_modules()


class TestStatisticsViewEmptyStateContent:
    """Tests for empty state content in _show_empty_state."""

    def test_show_empty_state_clears_threat_styling(self, statistics_view_class):
        """Test that empty state removes error class from threats label."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_empty_state()

        view._threats_label.remove_css_class.assert_called_with("error")

    def test_show_empty_state_clears_all_badge_classes(self, statistics_view_class):
        """Test that empty state removes all status CSS classes from badge."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_empty_state()

        # Should remove success, warning, and error classes
        remove_calls = [c[0][0] for c in view._status_badge.remove_css_class.call_args_list]
        assert "success" in remove_calls
        assert "warning" in remove_calls
        assert "error" in remove_calls

    def test_show_empty_state_sets_info_icon(self, statistics_view_class):
        """Test that empty state shows the information icon."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_empty_state()

        icon_arg = view._protection_row_icon.set_from_icon_name.call_args[0][0]
        assert "information" in icon_arg

    def test_show_empty_state_sets_stats_group_description(self, statistics_view_class):
        """Test that empty state updates the stats group description."""
        view = object.__new__(statistics_view_class)
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()
        view._stats_group = mock.MagicMock()

        view._show_empty_state()

        view._stats_group.set_description.assert_called_once()
        desc = view._stats_group.set_description.call_args[0][0]
        assert "first scan" in desc.lower() or "statistics" in desc.lower()


class TestStatisticsViewProtectionDisplayLastScan:
    """Tests for last scan display in _update_protection_display."""

    def test_last_scan_with_hours_age(self, statistics_view_class):
        """Test last scan row displays hours-based age string."""
        view = object.__new__(statistics_view_class)
        mock_status = mock.MagicMock()
        mock_status.level = "protected"
        mock_status.message = "System is protected"
        mock_status.last_scan_timestamp = "2024-01-15T10:30:00"
        mock_status.last_scan_age_hours = 5.0

        view._current_protection = mock_status
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()

        view._update_protection_display()

        subtitle = view._last_scan_row.set_subtitle.call_args[0][0]
        assert "2024-01-15" in subtitle
        assert "hour" in subtitle

    def test_last_scan_less_than_hour(self, statistics_view_class):
        """Test last scan row displays 'less than an hour ago'."""
        view = object.__new__(statistics_view_class)
        mock_status = mock.MagicMock()
        mock_status.level = "protected"
        mock_status.message = "System is protected"
        mock_status.last_scan_timestamp = "2024-01-15T10:30:00"
        mock_status.last_scan_age_hours = 0.5

        view._current_protection = mock_status
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()

        view._update_protection_display()

        subtitle = view._last_scan_row.set_subtitle.call_args[0][0]
        assert "less than" in subtitle or "hour" in subtitle

    def test_last_scan_days_age(self, statistics_view_class):
        """Test last scan row displays days-based age string."""
        view = object.__new__(statistics_view_class)
        mock_status = mock.MagicMock()
        mock_status.level = "at_risk"
        mock_status.message = "Last scan was days ago"
        mock_status.last_scan_timestamp = "2024-01-10T10:30:00"
        mock_status.last_scan_age_hours = 72.0  # 3 days

        view._current_protection = mock_status
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()

        view._update_protection_display()

        subtitle = view._last_scan_row.set_subtitle.call_args[0][0]
        assert "day" in subtitle

    def test_last_scan_weeks_age(self, statistics_view_class):
        """Test last scan row displays weeks-based age string."""
        view = object.__new__(statistics_view_class)
        mock_status = mock.MagicMock()
        mock_status.level = "unprotected"
        mock_status.message = "Scan overdue"
        mock_status.last_scan_timestamp = "2024-01-01T10:30:00"
        mock_status.last_scan_age_hours = 336.0  # 2 weeks

        view._current_protection = mock_status
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()

        view._update_protection_display()

        subtitle = view._last_scan_row.set_subtitle.call_args[0][0]
        assert "week" in subtitle

    def test_last_scan_no_timestamp(self, statistics_view_class):
        """Test last scan row shows 'No scans recorded' when no timestamp."""
        view = object.__new__(statistics_view_class)
        mock_status = mock.MagicMock()
        mock_status.level = "unprotected"
        mock_status.message = "No scans performed"
        mock_status.last_scan_timestamp = None
        mock_status.last_scan_age_hours = None

        view._current_protection = mock_status
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()

        view._update_protection_display()

        subtitle = view._last_scan_row.set_subtitle.call_args[0][0]
        assert "No scans" in subtitle

    def test_last_scan_no_age_hours(self, statistics_view_class):
        """Test last scan row displays timestamp without age when age is None."""
        view = object.__new__(statistics_view_class)
        mock_status = mock.MagicMock()
        mock_status.level = "protected"
        mock_status.message = "Protected"
        mock_status.last_scan_timestamp = "2024-01-15T10:30:00"
        mock_status.last_scan_age_hours = None

        view._current_protection = mock_status
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()

        view._update_protection_display()

        subtitle = view._last_scan_row.set_subtitle.call_args[0][0]
        assert "2024-01-15" in subtitle

    def test_protection_display_unknown_level(self, statistics_view_class):
        """Test protection display with an unknown level value."""
        view = object.__new__(statistics_view_class)
        mock_status = mock.MagicMock()
        mock_status.level = "some_new_level"
        mock_status.message = "Unknown state"
        mock_status.last_scan_timestamp = None
        mock_status.last_scan_age_hours = None

        view._current_protection = mock_status
        view._protection_row = mock.MagicMock()
        view._protection_row_icon = mock.MagicMock()
        view._status_badge = mock.MagicMock()
        view._last_scan_row = mock.MagicMock()

        view._update_protection_display()

        view._status_badge.set_label.assert_called_with("Unknown")
        icon_arg = view._protection_row_icon.set_from_icon_name.call_args[0][0]
        assert "question" in icon_arg


class TestStatisticsViewUpdateStatisticsDateRange:
    """Tests for date range display in _update_statistics_display."""

    def test_date_range_with_valid_dates(self, statistics_view_class):
        """Test that valid date range is displayed in stats group description."""
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 10
        mock_stats.files_scanned = 500
        mock_stats.threats_detected = 0
        mock_stats.clean_scans = 10
        mock_stats.average_duration = 30.0
        mock_stats.start_date = "2024-01-01T00:00:00"
        mock_stats.end_date = "2024-01-31T23:59:59"

        view = object.__new__(statistics_view_class)
        view._current_stats = mock_stats
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._stats_group = mock.MagicMock()
        view._show_empty_state = mock.MagicMock()

        view._update_statistics_display()

        desc = view._stats_group.set_description.call_args[0][0]
        assert "Jan" in desc
        assert "2024" in desc

    def test_date_range_with_no_dates(self, statistics_view_class):
        """Test that 'all time' description is used when no date range."""
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 10
        mock_stats.files_scanned = 500
        mock_stats.threats_detected = 0
        mock_stats.clean_scans = 10
        mock_stats.average_duration = 30.0
        mock_stats.start_date = None
        mock_stats.end_date = None

        view = object.__new__(statistics_view_class)
        view._current_stats = mock_stats
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._stats_group = mock.MagicMock()
        view._show_empty_state = mock.MagicMock()

        view._update_statistics_display()

        desc = view._stats_group.set_description.call_args[0][0]
        assert "all time" in desc.lower()

    def test_positive_duration_formatted(self, statistics_view_class):
        """Test that positive average duration is formatted and displayed."""
        mock_stats = mock.MagicMock()
        mock_stats.total_scans = 10
        mock_stats.files_scanned = 500
        mock_stats.threats_detected = 0
        mock_stats.clean_scans = 10
        mock_stats.average_duration = 120.0
        mock_stats.start_date = None
        mock_stats.end_date = None

        view = object.__new__(statistics_view_class)
        view._current_stats = mock_stats
        view._total_scans_label = mock.MagicMock()
        view._files_scanned_label = mock.MagicMock()
        view._threats_label = mock.MagicMock()
        view._clean_scans_label = mock.MagicMock()
        view._duration_label = mock.MagicMock()
        view._stats_group = mock.MagicMock()
        view._show_empty_state = mock.MagicMock()

        view._update_statistics_display()

        duration_text = view._duration_label.set_label.call_args[0][0]
        assert "m" in duration_text  # 120s = 2m 0s
