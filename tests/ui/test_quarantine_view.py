import sys
from types import SimpleNamespace
from unittest import mock

import pytest


@pytest.fixture
def quarantine_view_class(mock_gi_modules):
    with mock.patch.dict(sys.modules, {"src.core.quarantine": mock.MagicMock()}):
        sys.modules.pop("src.ui.quarantine_view", None)
        from src.ui.quarantine_view import QuarantineView

        yield QuarantineView

    for name in [name for name in sys.modules if name.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture
def quarantine_view(quarantine_view_class):
    view = object.__new__(quarantine_view_class)
    view._manager = mock.MagicMock()
    view._all_entries = []
    view._filtered_entries = []
    view._search_query = ""
    view._is_loading = False
    view._last_refresh_time = 0
    view._pagination = mock.MagicMock()
    view._listbox = mock.MagicMock()
    view._clear_old_button = mock.MagicMock()
    view._count_label = mock.MagicMock()
    view._storage_row = mock.MagicMock()
    view._set_loading_state = mock.MagicMock()
    view._update_storage_info = mock.MagicMock()
    view._on_quarantine_changed = mock.MagicMock()
    return view


@pytest.mark.parametrize(
    ("size", "formatted"),
    [
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024**2, "1.0 MB"),
        (1024**3, "1.00 GB"),
    ],
)
def test_format_file_size_respects_unit_boundaries(quarantine_view_class, size, formatted):
    module = sys.modules[quarantine_view_class.__module__]

    assert module.format_file_size(size) == formatted


def test_loading_entries_is_single_flight(quarantine_view):
    quarantine_view._load_entries_async()
    quarantine_view._is_loading = True
    quarantine_view._load_entries_async()

    quarantine_view._set_loading_state.assert_called_once_with(True)
    quarantine_view._manager.get_all_entries_async.assert_called_once_with(
        callback=quarantine_view._on_entries_loaded
    )


@pytest.mark.parametrize(
    ("entries", "expected_pagination", "clear_old_enabled"),
    [
        ([], mock.call([]), False),
        (
            [SimpleNamespace(file_size=1)],
            mock.call([SimpleNamespace(file_size=1)], "entries"),
            True,
        ),
    ],
)
def test_entries_loaded_updates_list_and_finishes_loading(
    quarantine_view, entries, expected_pagination, clear_old_enabled
):
    quarantine_view._on_entries_loaded(entries)

    assert quarantine_view._all_entries == entries
    quarantine_view._pagination.set_entries.assert_called_once_with(*expected_pagination.args)
    quarantine_view._clear_old_button.set_sensitive.assert_called_once_with(clear_old_enabled)
    quarantine_view._set_loading_state.assert_called_once_with(False)
    quarantine_view._on_quarantine_changed.assert_called_once_with(len(entries))


@pytest.mark.parametrize(
    ("query", "expected_indices"),
    [("eicar", [0]), ("downloads", [0]), ("trojan", [1]), ("missing", [])],
)
def test_search_matches_threat_or_path_case_insensitively(quarantine_view, query, expected_indices):
    entries = [
        SimpleNamespace(threat_name="Eicar-Test", original_path="/home/user/downloads/file"),
        SimpleNamespace(threat_name="Trojan.Generic", original_path=None),
    ]
    quarantine_view._all_entries = entries
    quarantine_view._search_query = query

    assert quarantine_view._filter_entries() == [entries[index] for index in expected_indices]


def test_search_handles_missing_entry_fields(quarantine_view):
    entry = SimpleNamespace(threat_name=None, original_path=None)
    quarantine_view._all_entries = [entry]
    quarantine_view._search_query = "eicar"

    assert quarantine_view._filter_entries() == []


def test_entry_row_sanitizes_raw_filename_for_gtk(quarantine_view):
    module = sys.modules[quarantine_view.__class__.__module__]
    entry = SimpleNamespace(
        id=1,
        threat_name="TestThreat",
        original_path="/tmp/infected_\udcff",
        detection_date="2024-01-01T00:00:00",
        file_size=1,
    )

    with mock.patch.object(
        module, "sanitize_surrogate_path", wraps=module.sanitize_surrogate_path
    ) as sanitize:
        quarantine_view._create_entry_row(entry)

    assert any(call.args[0] == entry.original_path for call in sanitize.call_args_list)


@pytest.mark.parametrize(
    ("all_entries", "filtered_entries", "expected_factory"),
    [
        ([SimpleNamespace(file_size=1)], [], "_create_no_results_state"),
        ([], [], "_create_empty_state"),
    ],
)
def test_search_without_matches_selects_the_right_empty_state(
    quarantine_view, all_entries, filtered_entries, expected_factory
):
    placeholder = mock.MagicMock()
    quarantine_view._all_entries = all_entries
    quarantine_view._search_query = "missing"
    quarantine_view._filter_entries = mock.MagicMock(return_value=filtered_entries)
    setattr(quarantine_view, expected_factory, mock.MagicMock(return_value=placeholder))

    quarantine_view._apply_search_filter()

    quarantine_view._listbox.set_placeholder.assert_called_once_with(placeholder)
    quarantine_view._pagination.set_entries.assert_called_once_with(all_entries)


def test_search_results_paginate_filtered_entries(quarantine_view):
    entry = SimpleNamespace(file_size=512)
    quarantine_view._all_entries = [entry]
    quarantine_view._search_query = "eicar"
    quarantine_view._filter_entries = mock.MagicMock(return_value=[entry])
    empty_state = mock.MagicMock()
    quarantine_view._create_empty_state = mock.MagicMock(return_value=empty_state)

    quarantine_view._apply_search_filter()

    quarantine_view._listbox.set_placeholder.assert_called_once_with(empty_state)
    quarantine_view._pagination.set_entries.assert_called_once_with([entry], "filtered entries")


@pytest.mark.parametrize(
    ("operation", "response"),
    [
        ("restore", "confirm"),
        ("restore", "cancel"),
        ("delete", "confirm"),
        ("delete", "cancel"),
    ],
)
def test_restore_and_delete_require_confirmation(quarantine_view, operation, response):
    entry = SimpleNamespace(id="entry-id")
    handler = getattr(quarantine_view, f"_on_{operation}_confirm_response")
    manager_method = getattr(quarantine_view._manager, f"{operation}_file_async")

    handler(mock.MagicMock(), response, entry)

    if response == "confirm":
        manager_method.assert_called_once_with(
            "entry-id", callback=getattr(quarantine_view, f"_on_{operation}_completed")
        )
    else:
        manager_method.assert_not_called()
