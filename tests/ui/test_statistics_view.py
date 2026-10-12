import sys
from types import SimpleNamespace
from unittest import mock

import pytest


@pytest.fixture
def statistics_view_class(mock_gi_modules):
    matplotlib = mock.MagicMock()
    backend = mock.MagicMock()
    backend.FigureCanvasGTK4Agg = mock.MagicMock()
    with mock.patch.dict(
        sys.modules,
        {
            "matplotlib": matplotlib,
            "matplotlib.figure": mock.MagicMock(),
            "matplotlib.backends.backend_gtk4agg": backend,
        },
    ):
        sys.modules.pop("src.ui.statistics_view", None)
        from src.ui.statistics_view import StatisticsView

        yield StatisticsView

    for name in [name for name in sys.modules if name.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture
def statistics_view(statistics_view_class):
    view = object.__new__(statistics_view_class)
    view._current_timeframe = "weekly"
    view._is_loading = False
    view._status_spinner = mock.MagicMock()
    view._refresh_button = mock.MagicMock()
    view._timeframe_buttons = {
        name: mock.MagicMock() for name in ("daily", "weekly", "monthly", "all")
    }
    view._load_statistics_async = mock.MagicMock()
    return view


def test_timeframe_change_keeps_single_active_selection_and_reloads(statistics_view):
    selected = statistics_view._timeframe_buttons["monthly"]
    selected.get_active.return_value = True

    statistics_view._on_timeframe_toggled(selected, "monthly")

    assert statistics_view._current_timeframe == "monthly"
    for name, button in statistics_view._timeframe_buttons.items():
        if name != "monthly":
            button.set_active.assert_called_once_with(False)
    statistics_view._load_statistics_async.assert_called_once()


def test_inactive_timeframe_cannot_clear_current_selection(statistics_view):
    button = statistics_view._timeframe_buttons["daily"]
    button.get_active.return_value = False

    statistics_view._on_timeframe_toggled(button, "daily")

    assert statistics_view._current_timeframe == "weekly"
    button.set_active.assert_not_called()
    statistics_view._load_statistics_async.assert_not_called()


@pytest.mark.parametrize("is_loading", [True, False])
def test_loading_transition_updates_every_control(statistics_view, is_loading):
    statistics_view._set_loading_state(is_loading)

    assert statistics_view._is_loading is is_loading
    statistics_view._status_spinner.set_visible.assert_called_once_with(is_loading)
    statistics_view._refresh_button.set_sensitive.assert_called_once_with(not is_loading)
    for button in statistics_view._timeframe_buttons.values():
        button.set_sensitive.assert_called_once_with(not is_loading)
    if is_loading:
        statistics_view._status_spinner.start.assert_called_once()
    else:
        statistics_view._status_spinner.stop.assert_called_once()


def test_loading_widget_failure_clears_reentrancy_guard(statistics_view):
    statistics_view._status_spinner.set_visible.side_effect = RuntimeError("widget failed")

    statistics_view._set_loading_state(True)

    assert statistics_view._is_loading is False


def test_async_load_ignores_a_second_request(statistics_view_class):
    view = object.__new__(statistics_view_class)
    view._is_loading = True
    view._set_loading_state = mock.MagicMock()

    assert view._load_statistics_async() is False
    view._set_loading_state.assert_not_called()


@pytest.mark.parametrize("has_callback", [True, False])
def test_quick_scan_uses_callback_or_application_action(statistics_view_class, has_callback):
    view = object.__new__(statistics_view_class)
    callback = mock.MagicMock() if has_callback else None
    app = mock.MagicMock()
    view._on_quick_scan_requested = callback
    view.get_root = mock.MagicMock(return_value=app)

    view._on_quick_scan_clicked(mock.MagicMock())

    if has_callback:
        callback.assert_called_once()
        app.activate_action.assert_not_called()
    else:
        app.activate_action.assert_called_once_with("app.show-scan", None)


@pytest.fixture
def display_view(statistics_view_class):
    view = object.__new__(statistics_view_class)
    for name in (
        "_total_scans_label",
        "_files_scanned_label",
        "_threats_label",
        "_clean_scans_label",
        "_duration_label",
        "_protection_row",
        "_protection_row_icon",
        "_status_badge",
        "_last_scan_row",
        "_stats_group",
    ):
        setattr(view, name, mock.MagicMock())
    return view


def test_empty_and_error_states_clear_stale_threat_status(display_view):
    display_view._show_empty_state()

    assert [
        label.set_label.call_args.args[0]
        for label in (
            display_view._total_scans_label,
            display_view._files_scanned_label,
            display_view._threats_label,
            display_view._clean_scans_label,
        )
    ] == ["0"] * 4
    display_view._threats_label.remove_css_class.assert_called_with("error")
    assert {
        call.args[0] for call in display_view._status_badge.remove_css_class.call_args_list
    } == {
        "success",
        "warning",
        "error",
    }

    display_view._show_error_state("backend unavailable")

    display_view._status_badge.add_css_class.assert_called_with("error")
    display_view._stats_group.set_description.assert_called_with("backend unavailable")


@pytest.mark.parametrize(
    ("level", "expected_badge", "expected_class"),
    [
        ("protected", "Protected", "success"),
        ("at_risk", "At Risk", "warning"),
        ("unprotected", "Unprotected", "error"),
    ],
)
def test_protection_status_precedence_sets_the_right_badge(
    display_view, level, expected_badge, expected_class
):
    display_view._current_protection = SimpleNamespace(
        level=level,
        message="status",
        last_scan_timestamp=None,
        last_scan_age_hours=None,
    )

    display_view._update_protection_display()

    display_view._status_badge.set_label.assert_called_with(expected_badge)
    display_view._status_badge.add_css_class.assert_called_with(expected_class)


def test_unknown_protection_clears_stale_status_classes(display_view):
    display_view._current_protection = SimpleNamespace(
        level="unexpected", message="status", last_scan_timestamp=None, last_scan_age_hours=None
    )

    display_view._update_protection_display()

    display_view._status_badge.set_label.assert_called_with("Unknown")
    assert {
        call.args[0] for call in display_view._status_badge.remove_css_class.call_args_list
    } == {
        "success",
        "warning",
        "error",
        "info",
    }


@pytest.mark.parametrize(
    ("trend_data", "canvas_visible"),
    [([], False), ([{"date": "2024-01-01", "scans": 0}], False)],
)
def test_chart_without_renderable_data_shows_empty_state(
    statistics_view_class, trend_data, canvas_visible
):
    view = object.__new__(statistics_view_class)
    view._canvas = mock.MagicMock()
    view._chart_empty_state = mock.MagicMock()
    view._chart_group = mock.MagicMock()

    view._update_chart(trend_data)

    view._canvas.set_visible.assert_called_once_with(canvas_visible)
    view._chart_empty_state.set_visible.assert_called_once_with(True)


@pytest.fixture
def chart_view(statistics_view_class):
    view = object.__new__(statistics_view_class)
    view._figure = mock.MagicMock()
    axes = mock.MagicMock()
    scan_bars = [mock.MagicMock(), mock.MagicMock()]
    threat_bars = [mock.MagicMock(), mock.MagicMock()]
    axes.bar.side_effect = [scan_bars, threat_bars]
    view._figure.add_subplot.return_value = axes
    view._canvas = mock.MagicMock()
    view._canvas.get_style_context.return_value.get_color.return_value = SimpleNamespace(
        red=0.1, green=0.1, blue=0.1
    )
    view._chart_empty_state = mock.MagicMock()
    view._chart_group = mock.MagicMock()
    view._chart_initialized = False
    view._chart_ax = None
    view._chart_bars_scans = None
    view._chart_bars_threats = None
    return view


def test_chart_reuses_bars_for_same_length_data(chart_view):
    first = [
        {"date": "2024-01-01T00:00:00", "scans": 1, "threats": 0},
        {"date": "2024-01-02T00:00:00", "scans": 2, "threats": 1},
    ]
    chart_view._update_chart(first)
    chart_view._figure.clear.reset_mock()

    chart_view._update_chart(
        [
            {"date": "2024-01-03T00:00:00", "scans": 3, "threats": 2},
            {"date": "2024-01-04T00:00:00", "scans": 4, "threats": 0},
        ]
    )

    chart_view._figure.clear.assert_not_called()
    assert [bar.set_height.call_args.args[0] for bar in chart_view._chart_bars_scans] == [3, 4]


def test_chart_rebuilds_when_data_length_changes(chart_view):
    chart_view._update_chart(
        [
            {"date": "2024-01-01T00:00:00", "scans": 1, "threats": 0},
            {"date": "2024-01-02T00:00:00", "scans": 2, "threats": 1},
        ]
    )
    chart_view._figure.clear.reset_mock()
    chart_view._figure.add_subplot.reset_mock()
    axes = chart_view._figure.add_subplot.return_value
    axes.bar.side_effect = [
        [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()],
        [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()],
    ]

    chart_view._update_chart(
        [
            {"date": "2024-01-01T00:00:00", "scans": 1, "threats": 0},
            {"date": "2024-01-02T00:00:00", "scans": 2, "threats": 1},
            {"date": "2024-01-03T00:00:00", "scans": 3, "threats": 0},
        ]
    )

    chart_view._figure.clear.assert_called_once()
    chart_view._figure.add_subplot.assert_called_once_with(111)


def test_worker_result_is_marshalled_to_main_loop_and_finishes_loading(
    statistics_view_class,
):
    view = object.__new__(statistics_view_class)
    stats = SimpleNamespace(total_scans=1)
    protection = SimpleNamespace()
    view._current_timeframe = "weekly"
    view._calculator = mock.MagicMock()
    view._calculator.get_statistics.return_value = stats
    view._calculator.get_protection_status.return_value = protection
    view._calculator.get_scan_trend_data.return_value = []
    view._get_data_points_for_timeframe = mock.MagicMock(return_value=7)
    view._update_statistics_display = mock.MagicMock()
    view._update_protection_display = mock.MagicMock()
    view._update_chart = mock.MagicMock()
    view._show_empty_state = mock.MagicMock()
    view._show_error_state = mock.MagicMock()
    view._set_loading_state = mock.MagicMock()
    module = sys.modules[statistics_view_class.__module__]
    module.GLib.idle_add.side_effect = lambda callback, *args: callback(*args)

    view._perform_load()

    module.GLib.idle_add.assert_called_once()
    view._update_statistics_display.assert_called_once()
    view._update_protection_display.assert_called_once()
    view._update_chart.assert_called_once_with([])
    view._set_loading_state.assert_called_once_with(False)


@pytest.mark.parametrize(
    ("stats", "protection", "worker_error", "expected"),
    [
        (SimpleNamespace(total_scans=0), SimpleNamespace(), False, "empty"),
        (None, None, False, "error"),
        (None, SimpleNamespace(), True, "error"),
    ],
)
def test_result_fallbacks_distinguish_empty_data_from_errors(
    statistics_view_class, stats, protection, worker_error, expected
):
    view = object.__new__(statistics_view_class)
    view._show_empty_state = mock.MagicMock()
    view._show_error_state = mock.MagicMock()
    view._update_protection_display = mock.MagicMock()
    view._update_chart = mock.MagicMock()
    view._update_statistics_display = mock.MagicMock()
    view._set_loading_state = mock.MagicMock()

    assert view._apply_statistics_results(stats, protection, [], worker_error) is False

    if expected == "empty":
        view._show_empty_state.assert_called_once()
        view._update_protection_display.assert_called_once()
    else:
        view._show_error_state.assert_called_once()
    view._update_chart.assert_called_once_with([])
    view._set_loading_state.assert_called_once_with(False)
