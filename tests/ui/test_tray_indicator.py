# ClamUI TrayIndicator Wrapper Tests
"""Unit tests for the tray_indicator compatibility wrapper."""

from __future__ import annotations

from unittest import mock

import pytest


class _FakeManager:
    """Test double for TrayManager used by tray_indicator tests."""

    start_result = True

    def __init__(self):
        self.action_callbacks = None
        self.window_toggle_callback = None
        self.profile_select_callback = None
        self.availability_callback = None
        self.is_available = False
        self.start_called = False
        self.update_profiles_calls = []
        self.status_calls = []
        self.progress_calls = []
        self.window_label_calls = []
        self.cleanup_called = False

    def set_action_callbacks(self, **kwargs):
        self.action_callbacks = kwargs

    def set_window_toggle_callback(self, on_toggle, get_visible=None):
        self.window_toggle_callback = (on_toggle, get_visible)

    def set_profile_select_callback(self, on_select):
        self.profile_select_callback = on_select

    def set_availability_callback(self, on_changed):
        self.availability_callback = on_changed

    def start(self):
        self.start_called = True
        return self.start_result

    def update_profiles(self, profiles, current_profile_id=None):
        self.update_profiles_calls.append((profiles, current_profile_id))

    def update_status(self, status):
        self.status_calls.append(status)

    def update_scan_progress(self, percentage):
        self.progress_calls.append(percentage)

    def update_window_menu_label(self, visible=True):
        self.window_label_calls.append(visible)

    def cleanup(self):
        self.cleanup_called = True


def _build_app():
    app = mock.MagicMock()
    app._on_tray_quick_scan = mock.MagicMock()
    app._on_tray_full_scan = mock.MagicMock()
    app._on_tray_update = mock.MagicMock()
    app._on_tray_quit = mock.MagicMock()
    app._on_tray_window_toggle = mock.MagicMock()
    app._on_tray_profile_select = mock.MagicMock()
    app._on_tray_availability_changed = mock.MagicMock()
    return app


def test_init_wires_callbacks_and_starts(monkeypatch, mock_gi_modules):
    """TrayIndicator should configure callbacks and start the manager."""
    from src.ui import tray_indicator

    monkeypatch.setattr(tray_indicator, "TrayManager", _FakeManager)
    app = _build_app()

    indicator = tray_indicator.TrayIndicator(app)

    assert isinstance(indicator._manager, _FakeManager)
    assert indicator._manager.start_called is True
    assert indicator._manager.action_callbacks == {
        "on_quick_scan": app._on_tray_quick_scan,
        "on_full_scan": app._on_tray_full_scan,
        "on_update": app._on_tray_update,
        "on_quit": app._on_tray_quit,
    }
    assert indicator._manager.window_toggle_callback == (app._on_tray_window_toggle, None)
    assert indicator._manager.profile_select_callback == app._on_tray_profile_select
    assert indicator._manager.availability_callback == app._on_tray_availability_changed


def test_availability_requires_registered_tray_host(monkeypatch, mock_gi_modules):
    """A started tray subprocess is not available before host registration."""
    from src.ui import tray_indicator

    monkeypatch.setattr(tray_indicator, "TrayManager", _FakeManager)
    indicator = tray_indicator.TrayIndicator(_build_app())

    assert indicator.is_available is False
    indicator._manager.is_available = True
    assert indicator.is_available is True


def test_init_raises_when_manager_fails_to_start(monkeypatch, mock_gi_modules):
    """TrayIndicator should raise when subprocess startup fails."""
    from src.ui import tray_indicator

    class _FailingManager(_FakeManager):
        start_result = False

    monkeypatch.setattr(tray_indicator, "TrayManager", _FailingManager)
    app = _build_app()

    with pytest.raises(RuntimeError, match="Tray subprocess failed to start"):
        tray_indicator.TrayIndicator(app)


def test_set_profiles_normalizes_tuple_and_dict(monkeypatch, mock_gi_modules):
    """set_profiles should normalize mixed profile formats for TrayManager."""
    from src.ui import tray_indicator

    monkeypatch.setattr(tray_indicator, "TrayManager", _FakeManager)
    app = _build_app()

    indicator = tray_indicator.TrayIndicator(app)
    indicator.set_profiles(
        [
            ("quick", "Quick Scan", "Scan common locations"),
            {"id": "full", "name": "Full Scan", "is_default": True},
            {"name": "missing-id"},
            "invalid",
        ],
        current_profile_id="full",
    )

    assert indicator._manager.update_profiles_calls == [
        (
            [
                {"id": "quick", "name": "Quick Scan", "is_default": False},
                {"id": "full", "name": "Full Scan", "is_default": True},
            ],
            "full",
        )
    ]


def test_forwarding_methods_delegate_to_manager(monkeypatch, mock_gi_modules):
    """Status/progress/window label and cleanup should delegate to manager."""
    from src.ui import tray_indicator

    monkeypatch.setattr(tray_indicator, "TrayManager", _FakeManager)
    app = _build_app()

    indicator = tray_indicator.TrayIndicator(app)
    manager = indicator._manager

    indicator.update_status("scanning")
    indicator.update_scan_progress(42)
    indicator.update_window_menu_label(visible=False)
    indicator.cleanup()

    assert manager.status_calls == ["scanning"]
    assert manager.progress_calls == [42]
    assert manager.window_label_calls == [False]
    assert manager.cleanup_called is True
    assert indicator._manager is None
