import sys
from unittest import mock

import pytest


@pytest.fixture
def view_helpers_module(mock_gi_modules):
    sys.modules.pop("src.ui.view_helpers", None)
    from src.ui import view_helpers

    yield view_helpers

    for module in [name for name in sys.modules if name.startswith("src.")]:
        del sys.modules[module]


@pytest.mark.parametrize("level_name", ["SUCCESS", "WARNING", "ERROR", "INFO"])
def test_status_class_replaces_every_other_status_class(view_helpers_module, level_name):
    widget = mock.MagicMock()
    level = getattr(view_helpers_module.StatusLevel, level_name)

    view_helpers_module.set_status_class(widget, level)

    assert widget.add_css_class.call_args.args == (level.value,)
    removed = {call.args[0] for call in widget.remove_css_class.call_args_list}
    assert removed == {
        other.value for other in view_helpers_module.StatusLevel if other is not level
    }


def test_clear_status_classes_removes_every_status_class(view_helpers_module):
    widget = mock.MagicMock()

    view_helpers_module.clear_status_classes(widget)

    assert {call.args[0] for call in widget.remove_css_class.call_args_list} == {
        level.value for level in view_helpers_module.StatusLevel
    }


def test_empty_state_respects_subtitle_width_limit(view_helpers_module):
    Gtk = view_helpers_module.Gtk
    title_label, subtitle_label = mock.MagicMock(), mock.MagicMock()
    Gtk.Label.side_effect = [title_label, subtitle_label]
    config = view_helpers_module.EmptyStateConfig(
        icon_name="document-open-recent-symbolic",
        title="No entries",
        subtitle="A description",
        max_subtitle_chars=50,
    )

    view_helpers_module.create_empty_state(config)

    subtitle_label.set_max_width_chars.assert_called_once_with(50)
    subtitle_label.set_justify.assert_called_once_with(Gtk.Justification.CENTER)


def test_loading_row_cannot_be_selected_or_activated(view_helpers_module):
    row = view_helpers_module.create_loading_row("Loading")

    row.set_selectable.assert_called_once_with(False)
    row.set_activatable.assert_called_once_with(False)


@pytest.mark.parametrize("is_loading", [True, False])
def test_loading_state_controller_updates_spinner_and_all_buttons(view_helpers_module, is_loading):
    spinner = mock.MagicMock()
    buttons = [mock.MagicMock(), mock.MagicMock()]
    extra_button = mock.MagicMock()
    controller = view_helpers_module.LoadingStateController(
        spinner=spinner,
        buttons=buttons,
        extra_buttons=[extra_button],
    )

    controller.set_loading(is_loading)

    spinner.set_visible.assert_called_once_with(is_loading)
    for button in [*buttons, extra_button]:
        button.set_sensitive.assert_called_once_with(not is_loading)
    if is_loading:
        spinner.start.assert_called_once()
        spinner.stop.assert_not_called()
    else:
        spinner.stop.assert_called_once()
        spinner.start.assert_not_called()
