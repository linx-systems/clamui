import sys
from unittest import mock

import pytest


@pytest.fixture
def window_class(mock_gi_modules):
    with mock.patch.dict(
        sys.modules,
        {
            "src.ui.sidebar": mock.MagicMock(),
            "src.ui.compat": mock.MagicMock(),
            "src.ui.close_behavior_dialog": mock.MagicMock(),
            "src.ui.utils": mock.MagicMock(resolve_icon_name=lambda name: name),
        },
    ):
        sys.modules.pop("src.ui.window", None)
        from src.ui.window import MainWindow

        yield MainWindow

    for name in [name for name in sys.modules if name.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture
def app():
    application = mock.MagicMock()
    application.settings_manager = mock.MagicMock()
    application.tray_indicator = mock.MagicMock()
    application.tray_indicator.is_available = True
    application.is_scan_active = False
    application.scan_view = None
    return application


@pytest.fixture
def window(window_class, app):
    view = object.__new__(window_class)
    view._application = app
    view._current_view_id = "scan"
    view._handling_minimize = False
    view._close_dialog_pending = False
    view._scan_dialog_pending = False
    view._content_area = mock.MagicMock()
    view._content_view_host = mock.MagicMock()
    view._sidebar = mock.MagicMock()
    view._leaflet = mock.MagicMock()
    view._leaflet.get_folded.return_value = False
    view._back_button = mock.MagicMock()
    view._title_label = mock.MagicMock()
    view._activity_banner = mock.MagicMock()
    view._activity_spinner = mock.MagicMock()
    view._activity_label = mock.MagicMock()
    return view


def test_minimize_to_tray_requires_enabled_setting_and_indicator(window, app):
    app.settings_manager.get.return_value = True
    assert window._should_minimize_to_tray() is True

    app.tray_indicator = None
    assert window._should_minimize_to_tray() is False


def test_close_with_unregistered_tray_allows_normal_close(window, app):
    """A spawned service without a host must not consume the close request."""
    app.tray_indicator.is_available = False

    assert window._on_close_request(window) is False


def test_pending_minimize_does_not_hide_after_tray_loss(window, app):
    """A host lost between minimize signal and idle callback leaves the window."""
    app.tray_indicator.is_available = False
    window.unminimize = mock.MagicMock()
    window.hide_window = mock.MagicMock()

    assert window._do_minimize_to_tray() is False
    window.unminimize.assert_not_called()
    window.hide_window.assert_not_called()


def test_minimized_surface_defers_hide_to_main_loop(window, app):
    app.settings_manager.get.return_value = True
    surface = mock.MagicMock()
    surface.get_state.return_value = 4
    module = sys.modules[window.__class__.__module__]
    module.Gdk = mock.MagicMock()
    module.Gdk.ToplevelState.MINIMIZED = 4
    module.GLib = mock.MagicMock()

    window._on_surface_state_changed(surface, None)

    module.GLib.idle_add.assert_called_once_with(window._do_minimize_to_tray)
    assert window._handling_minimize is False


def test_close_request_gives_active_scan_priority(window, app):
    app.is_scan_active = True
    window._show_scan_in_progress_dialog = mock.MagicMock()

    assert window._on_close_request(window) is True
    window._show_scan_in_progress_dialog.assert_called_once()


@pytest.mark.parametrize(
    ("behavior", "expected_result", "expected_method"),
    [
        ("minimize", True, "_do_close_to_tray"),
        ("quit", False, None),
        (None, True, "_show_close_behavior_dialog"),
    ],
)
def test_close_behavior_routes_to_expected_user_outcome(
    window, app, behavior, expected_result, expected_method
):
    app.settings_manager.get.return_value = behavior
    window._do_close_to_tray = mock.MagicMock()
    window._show_close_behavior_dialog = mock.MagicMock()

    assert window._on_close_request(window) is expected_result
    if expected_method:
        getattr(window, expected_method).assert_called_once()
    else:
        window._do_close_to_tray.assert_not_called()
        window._show_close_behavior_dialog.assert_not_called()


def test_close_without_tray_allows_normal_close(window, app):
    app.tray_indicator = None

    assert window._on_close_request(window) is False


@pytest.mark.parametrize(
    ("choice", "remember", "expected_action"),
    [(None, False, None), ("minimize", True, "minimize"), ("quit", False, "quit")],
)
def test_close_dialog_response_clears_pending_and_honors_choice(
    window, app, choice, remember, expected_action
):
    window._close_dialog_pending = True
    window._do_close_to_tray = mock.MagicMock()

    window._on_close_behavior_dialog_response(choice, remember)

    assert window._close_dialog_pending is False
    if expected_action == "minimize":
        window._do_close_to_tray.assert_called_once()
        app.settings_manager.set.assert_called_once_with("close_behavior", "minimize")
    elif expected_action == "quit":
        app.quit.assert_called_once()
    else:
        window._do_close_to_tray.assert_not_called()
        app.quit.assert_not_called()


@pytest.mark.parametrize("choice", [None, "cancel_and_close"])
def test_scan_close_confirmation_only_cancels_when_confirmed(window, choice):
    window._scan_dialog_pending = True
    window._cancel_active_scan = mock.MagicMock()
    window._proceed_with_close = mock.MagicMock()

    window._on_scan_dialog_response(choice)

    assert window._scan_dialog_pending is False
    if choice == "cancel_and_close":
        window._cancel_active_scan.assert_called_once()
        window._proceed_with_close.assert_called_once()
    else:
        window._cancel_active_scan.assert_not_called()
        window._proceed_with_close.assert_not_called()


def test_confirmed_scan_cancellation_reaches_active_scanner(window, app):
    scanner = mock.MagicMock()
    app.scan_view = mock.MagicMock(_cancel_all_requested=False, _scanner=scanner)

    window._cancel_active_scan()

    scanner.cancel.assert_called_once()


def test_sidebar_selection_navigates_to_content_only_when_folded(window, app):
    window._leaflet.get_folded.return_value = True
    window._update_title = mock.MagicMock()

    window._on_sidebar_selection("quarantine")

    assert window._current_view_id == "quarantine"
    app.activate_action.assert_called_once_with("show-quarantine", None)
    window._leaflet.navigate.assert_called_once()
    window._back_button.set_visible.assert_called_once_with(True)
    window._update_title.assert_called_once()


def test_content_replacement_removes_every_old_child(window):
    first, second, new_view = mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
    first.get_next_sibling.return_value = second
    second.get_next_sibling.return_value = None
    window._content_view_host.get_first_child.return_value = first

    window.set_content_view(new_view)

    assert window._content_view_host.remove.call_args_list == [
        mock.call(first),
        mock.call(second),
    ]
    window._content_view_host.append.assert_called_once_with(new_view)


@pytest.mark.parametrize(
    ("message", "show_spinner", "banner_visible"),
    [("Updating", True, True), ("Done", False, True), (None, True, False)],
)
def test_activity_status_keeps_banner_and_spinner_in_sync(
    window, message, show_spinner, banner_visible
):
    window.set_activity_status(message, show_spinner=show_spinner)

    window._activity_banner.set_reveal_child.assert_called_once_with(banner_visible)
    if message and show_spinner:
        window._activity_spinner.start.assert_called_once()
        window._activity_spinner.set_visible.assert_called_once_with(True)
    else:
        window._activity_spinner.stop.assert_called_once()
        window._activity_spinner.set_visible.assert_called_once_with(False)
