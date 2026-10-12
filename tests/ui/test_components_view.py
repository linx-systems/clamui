import sys
from unittest import mock

import pytest


@pytest.fixture
def components_view_class(mock_gi_modules):
    sys.modules.pop("src.ui.components_view", None)
    from src.core.log_manager import DaemonStatus
    from src.ui.components_view import ComponentsView

    yield ComponentsView, DaemonStatus

    for name in [name for name in sys.modules if name.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture
def components_view(components_view_class):
    ComponentsView, _ = components_view_class
    view = object.__new__(ComponentsView)
    view._is_checking = False
    view._destroyed = False
    view._log_manager = mock.MagicMock()
    view._refresh_button = mock.MagicMock()
    view._refresh_spinner = mock.MagicMock()
    view._component_rows = {}
    view._status_icons = {}
    view._status_labels = {}
    view._guide_rows = {}
    return view


def test_atomic_setup_guides_layer_packages_then_require_reboot(components_view_class):
    """Atomic hosts must not be directed to Fedora Workstation's dnf commands."""
    ComponentsView, _ = components_view_class
    module = sys.modules[ComponentsView.__module__]

    for guide in module.SETUP_GUIDES.values():
        atomic_commands = [
            command for distro, command in guide["commands"] if distro == "Fedora Atomic"
        ]
        assert atomic_commands
        assert atomic_commands[0].startswith("sudo rpm-ostree install ")
        assert atomic_commands[0].endswith("sudo systemctl reboot")


def test_component_check_starts_daemon_worker_and_enters_loading_state(
    components_view, components_view_class
):
    ComponentsView, _ = components_view_class
    with mock.patch("src.ui.components_view.threading.Thread") as thread:
        worker = thread.return_value

        assert components_view._check_all_components() is False

    assert components_view._is_checking is True
    thread.assert_called_once_with(target=components_view._check_components_background, daemon=True)
    worker.start.assert_called_once()


def test_destroyed_view_does_not_probe_components(components_view):
    components_view._destroyed = True

    components_view._check_components_background()

    components_view._log_manager.get_daemon_status.assert_not_called()


def test_probe_failure_still_schedules_main_thread_reset(components_view):
    components_view._log_manager.get_daemon_status.side_effect = RuntimeError("probe failed")
    module = sys.modules[components_view.__class__.__module__]
    module.check_clamav_installed = mock.MagicMock(side_effect=RuntimeError("probe failed"))
    module.GLib = mock.MagicMock()

    components_view._check_components_background()

    module.GLib.idle_add.assert_called_once_with(components_view._update_components_ui, {})


@pytest.mark.parametrize("is_checking", [True, False])
def test_checking_state_updates_spinner_and_refresh_button(components_view, is_checking):
    components_view._set_checking_state(is_checking)

    assert components_view._is_checking is is_checking
    components_view._refresh_button.set_sensitive.assert_called_once_with(not is_checking)
    components_view._refresh_spinner.set_visible.assert_called_once_with(is_checking)
    if is_checking:
        components_view._refresh_spinner.start.assert_called_once()
    else:
        components_view._refresh_spinner.stop.assert_called_once()


def test_refresh_does_not_start_second_component_check(components_view):
    components_view._is_checking = True
    components_view._check_all_components = mock.MagicMock()

    components_view._on_refresh_clicked(mock.MagicMock())

    components_view._check_all_components.assert_not_called()


@pytest.mark.parametrize("installed", [True, False])
def test_component_status_shows_or_hides_setup_guide(components_view, installed):
    component_id = "clamscan"
    components_view._component_rows[component_id] = mock.MagicMock()
    components_view._status_icons[component_id] = mock.MagicMock()
    components_view._status_labels[component_id] = mock.MagicMock()
    components_view._guide_rows[component_id] = mock.MagicMock()

    components_view._update_component_status(component_id, installed, "version")

    components_view._guide_rows[component_id].set_visible.assert_called_once_with(not installed)
    components_view._component_rows[component_id].set_enable_expansion.assert_called_once_with(
        not installed
    )
    expected_class = "success" if installed else "warning"
    components_view._status_icons[component_id].add_css_class.assert_called_with(expected_class)


@pytest.mark.parametrize(
    ("status_name", "guide_visible", "status_class"),
    [
        ("RUNNING", False, "success"),
        ("STOPPED", True, "warning"),
        ("NOT_INSTALLED", True, "warning"),
    ],
)
def test_daemon_status_keeps_setup_available_until_running(
    components_view, components_view_class, status_name, guide_visible, status_class
):
    _, DaemonStatus = components_view_class
    component_id = "clamd"
    components_view._component_rows[component_id] = mock.MagicMock()
    components_view._status_icons[component_id] = mock.MagicMock()
    components_view._status_labels[component_id] = mock.MagicMock()
    components_view._guide_rows[component_id] = mock.MagicMock()

    components_view._update_daemon_status(
        component_id, getattr(DaemonStatus, status_name), "status"
    )

    components_view._guide_rows[component_id].set_visible.assert_called_once_with(guide_visible)
    components_view._component_rows[component_id].set_enable_expansion.assert_called_once_with(
        guide_visible
    )
    components_view._status_icons[component_id].add_css_class.assert_called_with(status_class)


def test_copy_feedback_reverts_only_while_view_is_alive(components_view):
    button = mock.MagicMock()
    clipboard = mock.MagicMock()
    button.get_clipboard.return_value = clipboard
    module = sys.modules[components_view.__class__.__module__]
    module.GLib = mock.MagicMock()

    components_view._on_copy_clicked(button, "command")
    restore_icon = module.GLib.timeout_add.call_args.args[1]

    clipboard.set.assert_called_once_with("command")
    restore_icon()
    assert button.set_icon_name.call_count == 2

    components_view._destroyed = True
    restore_icon()
    assert button.set_icon_name.call_count == 2
