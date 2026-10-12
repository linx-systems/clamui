# ClamUI TrayIntegration Tests
"""Unit tests for tray window visibility toggling behavior."""

from unittest import mock

from src.tray_integration import TrayIntegration


def _make_app(active_window):
    app = mock.MagicMock()
    app.props.active_window = active_window
    app._tray_indicator = mock.MagicMock()
    app._tray_indicator.is_available = True
    return app


def test_toggle_window_hides_visible_window_and_updates_label():
    """Visible window should be hidden and menu label updated."""
    win = mock.MagicMock()
    win.is_visible.side_effect = [True, False]
    app = _make_app(win)

    integration = TrayIntegration(app)
    integration.toggle_window()

    win.hide_window.assert_called_once()
    win.show_window.assert_not_called()
    app._tray_indicator.update_window_menu_label.assert_called_once_with(visible=False)


def test_toggle_window_does_not_hide_without_registered_tray_host():
    """A stale tray action cannot hide the last reachable window."""
    win = mock.MagicMock()
    win.is_visible.return_value = True
    app = _make_app(win)
    app._tray_indicator.is_available = False

    TrayIntegration(app).toggle_window()

    win.hide_window.assert_not_called()


def test_toggle_window_shows_hidden_window_and_updates_label():
    """Hidden window should be shown and menu label updated."""
    win = mock.MagicMock()
    win.is_visible.side_effect = [False, True]
    app = _make_app(win)

    integration = TrayIntegration(app)
    integration.toggle_window()

    win.show_window.assert_called_once()
    win.hide_window.assert_not_called()
    app._tray_indicator.update_window_menu_label.assert_called_once_with(visible=True)


def test_toggle_window_uses_existing_hidden_window_when_no_active_window():
    """Toggle should recover a hidden window from app window list."""
    win = mock.MagicMock()
    win.is_visible.side_effect = [False, True]
    app = _make_app(None)
    app.get_windows.return_value = [win]

    integration = TrayIntegration(app)
    integration.toggle_window()

    app.activate.assert_not_called()
    win.show_window.assert_called_once()
    app._tray_indicator.update_window_menu_label.assert_called_once_with(visible=True)


def test_toggle_window_activates_app_when_no_window_is_active():
    """If no window is available, app should be activated before toggling."""
    win = mock.MagicMock()
    win.is_visible.side_effect = [False, True]
    app = _make_app(None)
    app.get_windows.side_effect = [[], [win]]

    integration = TrayIntegration(app)
    integration.toggle_window()

    app.activate.assert_called_once()
    win.show_window.assert_called_once()


def test_do_tray_profile_select_switches_to_scan_view_and_sets_profile():
    """Tray profile selection should navigate to scan view and apply the profile."""
    win = mock.MagicMock()
    scan_view = mock.MagicMock()
    app = _make_app(win)
    app._scan_view = scan_view
    app.scan_view = scan_view
    app._view_coordinator = mock.MagicMock()

    integration = TrayIntegration(app)

    result = integration._do_tray_profile_select("profile-123")

    app._view_coordinator.switch_to_view.assert_called_once_with("scan", scan_view)
    scan_view.set_selected_profile.assert_called_once_with("profile-123")
    assert result is False


def test_do_tray_profile_select_returns_false_without_scan_view():
    """Tray profile selection should no-op cleanly when scan view is unavailable."""
    app = _make_app(mock.MagicMock())
    app._scan_view = None
    app.scan_view = mock.MagicMock()
    app._view_coordinator = mock.MagicMock()

    integration = TrayIntegration(app)

    result = integration._do_tray_profile_select("profile-123")

    app._view_coordinator.switch_to_view.assert_not_called()
    app.scan_view.set_selected_profile.assert_not_called()
    assert result is False
