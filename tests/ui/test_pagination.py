import sys
from unittest import mock

import pytest


@pytest.fixture
def pagination_class(mock_gi_modules):
    sys.modules.pop("src.ui.pagination", None)
    from src.ui.pagination import PaginatedListController

    yield PaginatedListController

    for name in [name for name in sys.modules if name.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture
def pagination_controller(pagination_class):
    listbox = mock.MagicMock()
    listbox.get_first_child.return_value = None
    return pagination_class(
        listbox, mock.MagicMock(), mock.MagicMock(return_value=mock.MagicMock())
    )


@pytest.mark.parametrize(
    ("entries", "displayed", "has_more"),
    [(["one"], 1, False), (["one", "two"], 2, False), (["one", "two", "three"], 2, True)],
)
def test_set_entries_honors_initial_list_boundary(pagination_class, entries, displayed, has_more):
    listbox = mock.MagicMock()
    listbox.get_first_child.return_value = None
    row_factory = mock.MagicMock(return_value=mock.MagicMock())
    controller = pagination_class(listbox, mock.MagicMock(), row_factory, initial_limit=2)
    controller.add_load_more_button = mock.MagicMock()

    controller.set_entries(entries)

    assert controller.all_entries == entries
    assert controller.displayed_count == displayed
    assert row_factory.call_args_list == [mock.call(entry) for entry in entries[:displayed]]
    if has_more:
        controller.add_load_more_button.assert_called_once_with(None)
    else:
        controller.add_load_more_button.assert_not_called()


def test_set_entries_uses_filtered_entries_for_pagination_boundary(pagination_class):
    class FilteredController(pagination_class):
        @property
        def entries_to_display(self):
            return self.filtered_entries

    listbox = mock.MagicMock()
    listbox.get_first_child.return_value = None
    row_factory = mock.MagicMock(return_value=mock.MagicMock())
    controller = FilteredController(listbox, mock.MagicMock(), row_factory, initial_limit=2)
    controller.filtered_entries = ["match"]
    controller.add_load_more_button = mock.MagicMock()

    controller.set_entries(["one", "two", "three"])

    assert controller.displayed_count == 1
    row_factory.assert_called_once_with("match")
    controller.add_load_more_button.assert_not_called()


def test_display_batch_skips_bad_entry_without_losing_following_entries(
    pagination_controller,
):
    first_row, last_row = mock.MagicMock(), mock.MagicMock()
    pagination_controller._all_entries = ["first", "bad", "last"]
    pagination_controller._row_factory.side_effect = [first_row, ValueError("bad entry"), last_row]

    pagination_controller.display_batch(0, 3)

    assert pagination_controller.displayed_count == 2
    assert pagination_controller._listbox.append.call_args_list == [
        mock.call(first_row),
        mock.call(last_row),
    ]


def test_replacing_entries_removes_stale_rows_and_resets_count(pagination_controller):
    stale_row = mock.MagicMock()
    pagination_controller._listbox.get_first_child.side_effect = [stale_row, None]
    pagination_controller._displayed_count = 25
    pagination_controller._load_more_row = mock.MagicMock()

    pagination_controller.set_entries(["new"])

    pagination_controller._listbox.remove.assert_called_once_with(stale_row)
    assert pagination_controller.all_entries == ["new"]
    assert pagination_controller.displayed_count == 1
    assert pagination_controller.load_more_row is None


def test_load_more_keeps_scroll_position_and_readds_control(pagination_class):
    listbox = mock.MagicMock()
    row_factory = mock.MagicMock(return_value=mock.MagicMock())
    scrolled_window = mock.MagicMock()
    adjustment = mock.MagicMock()
    adjustment.get_value.return_value = 80
    scrolled_window.get_vadjustment.return_value = adjustment
    controller = pagination_class(listbox, scrolled_window, row_factory, batch_size=2)
    controller._all_entries = list(range(5))
    controller._displayed_count = 2
    load_more_row = mock.MagicMock()
    controller._load_more_row = load_more_row
    controller.add_load_more_button = mock.MagicMock()

    controller.load_more()

    listbox.remove.assert_called_once_with(load_more_row)
    assert controller.displayed_count == 4
    assert row_factory.call_args_list == [mock.call(2), mock.call(3)]
    controller.add_load_more_button.assert_called_once_with(None)
    restore_scroll = controller.__class__.__module__
    module = sys.modules[restore_scroll]
    restore_callback = module.GLib.idle_add.call_args.args[0]
    assert restore_callback() is False
    adjustment.set_value.assert_called_once_with(80)


def test_show_all_displays_remaining_entries_and_removes_control(pagination_class):
    listbox = mock.MagicMock()
    row_factory = mock.MagicMock(return_value=mock.MagicMock())
    controller = pagination_class(listbox, None, row_factory)
    controller._all_entries = list(range(5))
    controller._displayed_count = 2
    load_more_row = mock.MagicMock()
    controller._load_more_row = load_more_row

    controller.show_all()

    listbox.remove.assert_called_once_with(load_more_row)
    assert controller.displayed_count == 5
    assert row_factory.call_args_list == [mock.call(2), mock.call(3), mock.call(4)]
    assert controller.load_more_row is None
