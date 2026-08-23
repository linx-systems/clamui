# ClamUI QuarantineView Tests
"""
Unit tests for the QuarantineView component.

Tests cover:
- Initialization and setup
- Loading state management
- Quarantine entry display and pagination
- Restore and delete operations
- Clear old items functionality
- Storage info display
- format_file_size utility function
- Callback mechanism for quarantine changes
"""

import sys
from unittest import mock

import pytest


@pytest.fixture
def mock_quarantine_manager():
    """Create a mock QuarantineManager."""
    manager = mock.MagicMock()
    manager.get_all_entries_async = mock.MagicMock()
    manager.get_entry_count = mock.MagicMock(return_value=5)
    manager.get_total_size = mock.MagicMock(return_value=1024 * 1024)
    manager.restore_file_async = mock.MagicMock()
    manager.delete_file_async = mock.MagicMock()
    manager.cleanup_old_entries_async = mock.MagicMock()
    manager.get_old_entries = mock.MagicMock(return_value=[])
    return manager


@pytest.fixture
def mock_quarantine_entry():
    """Create a mock QuarantineEntry."""
    entry = mock.MagicMock()
    entry.id = "test-quarantine-id-123"
    entry.threat_name = "Eicar-Test-Signature"
    entry.original_path = "/home/user/downloads/malicious.exe"
    entry.detection_date = "2024-01-15T10:30:00"
    entry.file_size = 65536
    return entry


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


@pytest.fixture
def quarantine_view_class(mock_gi_modules):
    """Get QuarantineView class with mocked dependencies."""
    with mock.patch.dict(
        sys.modules,
        {
            "src.core.quarantine": mock.MagicMock(),
        },
    ):
        # Clear any cached import
        if "src.ui.quarantine_view" in sys.modules:
            del sys.modules["src.ui.quarantine_view"]

        from src.ui.quarantine_view import QuarantineView

        yield QuarantineView

    # Critical: Clear all src.* modules after test to prevent pollution
    _clear_src_modules()


@pytest.fixture
def mock_quarantine_view(quarantine_view_class, mock_quarantine_manager):
    """Create a mock QuarantineView instance for testing."""
    # Create instance without calling __init__
    view = object.__new__(quarantine_view_class)

    # Set up required attributes
    view._manager = mock_quarantine_manager
    view._is_loading = False
    view._all_entries = []
    view._on_quarantine_changed = None
    view._last_refresh_time = 0.0

    # Mock pagination controller (required for _displayed_count and _load_more_row properties)
    view._pagination = mock.MagicMock()
    view._pagination.displayed_count = 0
    view._pagination.load_more_row = None
    view._pagination._displayed_count = 0
    view._pagination._load_more_row = None

    # Mock UI elements
    view._status_banner = mock.MagicMock()
    view._storage_row = mock.MagicMock()
    view._count_label = mock.MagicMock()
    view._list_group = mock.MagicMock()
    view._listbox = mock.MagicMock()
    view._listbox.get_first_child.return_value = None  # Ensure loop terminates
    view._spinner = mock.MagicMock()
    view._refresh_button = mock.MagicMock()
    view._clear_old_button = mock.MagicMock()

    # Mock internal methods
    view._setup_ui = mock.MagicMock()
    view._load_entries_async = mock.MagicMock()
    view._set_loading_state = mock.MagicMock()
    view._create_entry_row = mock.MagicMock()
    view._update_storage_info = mock.MagicMock()
    view.get_root = mock.MagicMock(return_value=None)

    return view


class TestQuarantineViewImport:
    """Tests for QuarantineView import."""

    def test_import_quarantine_view(self, mock_gi_modules):
        """Test that QuarantineView can be imported."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.quarantine": mock.MagicMock(),
            },
        ):
            from src.ui.quarantine_view import QuarantineView

            assert QuarantineView is not None

    def test_import_from_ui_package(self, mock_gi_modules):
        """Test that QuarantineView is exported from src.ui package."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.quarantine": mock.MagicMock(),
                "src.core.log_manager": mock.MagicMock(),
                "src.core.utils": mock.MagicMock(),
                "src.ui.fullscreen_dialog": mock.MagicMock(),
                "src.ui.update_view": mock.MagicMock(),
                "src.ui.logs_view": mock.MagicMock(),
                "src.ui.components_view": mock.MagicMock(),
                "src.ui.preferences_dialog": mock.MagicMock(),
            },
        ):
            from src.ui import QuarantineView

            assert QuarantineView is not None

    def test_pagination_constants_defined(self, mock_gi_modules):
        """Test that pagination constants are defined."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.quarantine": mock.MagicMock(),
            },
        ):
            from src.ui.pagination import PaginatedListController

            assert PaginatedListController.DEFAULT_INITIAL_LIMIT == 25
            assert PaginatedListController.DEFAULT_BATCH_SIZE == 25


class TestFormatFileSize:
    """Tests for the format_file_size utility function."""

    def test_format_file_size_bytes(self, mock_gi_modules):
        """Test formatting file size in bytes."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.quarantine": mock.MagicMock(),
            },
        ):
            from src.ui.quarantine_view import format_file_size

            assert format_file_size(500) == "500 B"
            assert format_file_size(0) == "0 B"
            assert format_file_size(1023) == "1023 B"

    def test_format_file_size_kilobytes(self, mock_gi_modules):
        """Test formatting file size in kilobytes."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.quarantine": mock.MagicMock(),
            },
        ):
            from src.ui.quarantine_view import format_file_size

            assert format_file_size(1024) == "1.0 KB"
            assert format_file_size(2048) == "2.0 KB"
            assert format_file_size(1536) == "1.5 KB"

    def test_format_file_size_megabytes(self, mock_gi_modules):
        """Test formatting file size in megabytes."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.quarantine": mock.MagicMock(),
            },
        ):
            from src.ui.quarantine_view import format_file_size

            assert format_file_size(1024 * 1024) == "1.0 MB"
            assert format_file_size(2 * 1024 * 1024) == "2.0 MB"
            assert format_file_size(int(1.5 * 1024 * 1024)) == "1.5 MB"

    def test_format_file_size_gigabytes(self, mock_gi_modules):
        """Test formatting file size in gigabytes."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.quarantine": mock.MagicMock(),
            },
        ):
            from src.ui.quarantine_view import format_file_size

            assert format_file_size(1024 * 1024 * 1024) == "1.00 GB"
            assert format_file_size(2 * 1024 * 1024 * 1024) == "2.00 GB"


class TestQuarantineViewInitialization:
    """Tests for QuarantineView initialization."""

    def test_initial_loading_state_is_false(self, mock_quarantine_view):
        """Test that initial loading state is False."""
        assert mock_quarantine_view._is_loading is False

    def test_initial_displayed_count_is_zero(self, mock_quarantine_view):
        """Test that initial displayed count is zero."""
        assert mock_quarantine_view._displayed_count == 0

    def test_initial_all_entries_is_empty(self, mock_quarantine_view):
        """Test that initial all_entries is empty."""
        assert mock_quarantine_view._all_entries == []

    def test_initial_load_more_row_is_none(self, mock_quarantine_view):
        """Test that initial load_more_row is None."""
        assert mock_quarantine_view._load_more_row is None

    def test_initial_callback_is_none(self, mock_quarantine_view):
        """Test that initial quarantine changed callback is None."""
        assert mock_quarantine_view._on_quarantine_changed is None

    def test_initial_last_refresh_time_is_zero(self, mock_quarantine_view):
        """Test that initial last refresh time is zero."""
        assert mock_quarantine_view._last_refresh_time == 0.0


class TestQuarantineViewEntriesLoaded:
    """Tests for entries loading completion."""

    def test_on_entries_loaded_with_empty_list(
        self, quarantine_view_class, mock_quarantine_manager
    ):
        """Test handling empty entries list."""
        view = object.__new__(quarantine_view_class)
        view._is_loading = True
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None  # Ensure loop terminates
        view._clear_old_button = mock.MagicMock()
        view._all_entries = []
        view._displayed_count = 0
        view._load_more_row = None
        view._set_loading_state = mock.MagicMock()
        view._update_storage_info = mock.MagicMock()
        view._on_quarantine_changed = None
        view._last_refresh_time = 0.0
        view._manager = mock_quarantine_manager

        result = view._on_entries_loaded([])

        assert result is False
        view._clear_old_button.set_sensitive.assert_called_with(False)
        assert view._all_entries == []

    def test_on_entries_loaded_stores_entries(self, quarantine_view_class, mock_quarantine_entry):
        """Test that loaded entries are stored."""
        view = object.__new__(quarantine_view_class)
        view._is_loading = True
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None  # Ensure loop terminates
        view._clear_old_button = mock.MagicMock()
        view._all_entries = []
        view._displayed_count = 0
        view._load_more_row = None
        view._set_loading_state = mock.MagicMock()
        view._update_storage_info = mock.MagicMock()
        view._display_entry_batch = mock.MagicMock()
        view._add_load_more_button = mock.MagicMock()
        view._on_quarantine_changed = None
        view._last_refresh_time = 0.0
        view._manager = mock.MagicMock()
        # Initialize search state
        view._search_query = ""
        view._filtered_entries = []

        entries = [mock_quarantine_entry]
        view._on_entries_loaded(entries)

        assert view._all_entries == entries

    def test_on_entries_loaded_calls_callback(self, quarantine_view_class, mock_quarantine_entry):
        """Test that loaded entries trigger callback."""
        view = object.__new__(quarantine_view_class)
        view._is_loading = True
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None  # Ensure loop terminates
        view._clear_old_button = mock.MagicMock()
        view._all_entries = []
        view._displayed_count = 0
        view._load_more_row = None
        view._set_loading_state = mock.MagicMock()
        view._update_storage_info = mock.MagicMock()
        view._display_entry_batch = mock.MagicMock()
        view._add_load_more_button = mock.MagicMock()
        view._last_refresh_time = 0.0
        view._manager = mock.MagicMock()
        # Initialize search state
        view._search_query = ""
        view._filtered_entries = []

        callback = mock.MagicMock()
        view._on_quarantine_changed = callback

        entries = [mock_quarantine_entry]
        view._on_entries_loaded(entries)

        callback.assert_called_once_with(1)


class TestQuarantineViewPagination:
    """Tests for quarantine entry pagination."""

    def test_display_entry_batch_increments_count(
        self, quarantine_view_class, mock_quarantine_entry
    ):
        """Test that displaying entries delegates to pagination controller."""
        view = object.__new__(quarantine_view_class)
        view._all_entries = [mock_quarantine_entry, mock_quarantine_entry]
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None
        view._create_entry_row = mock.MagicMock(return_value=mock.MagicMock())
        # Initialize search state
        view._search_query = ""
        view._filtered_entries = []
        # Mock pagination controller
        view._pagination = mock.MagicMock()
        view._pagination.displayed_count = 0
        view._pagination.load_more_row = None

        view._display_entry_batch(0, 2)

        # Verify delegation to pagination controller
        view._pagination.display_batch.assert_called_once_with(0, 2)

    def test_on_load_more_clicked_removes_load_more_row(
        self, quarantine_view_class, mock_quarantine_entry
    ):
        """Test that clicking load more removes the load more row."""
        view = object.__new__(quarantine_view_class)
        view._all_entries = [mock_quarantine_entry] * 30
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None
        # Mock pagination controller
        load_more_row = mock.MagicMock()
        view._pagination = mock.MagicMock()
        view._pagination.displayed_count = 25
        view._pagination.load_more_row = load_more_row
        view._pagination._displayed_count = 25
        view._pagination._load_more_row = load_more_row
        # Initialize search state
        view._search_query = ""
        view._filtered_entries = []

        view._on_load_more_clicked(mock.MagicMock())

        # The pagination controller's load_more method is called
        view._pagination.load_more.assert_called()

    def test_on_show_all_clicked_displays_remaining(
        self, quarantine_view_class, mock_quarantine_entry
    ):
        """Test that clicking show all displays remaining entries."""
        view = object.__new__(quarantine_view_class)
        view._all_entries = [mock_quarantine_entry] * 50
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None
        # Mock pagination controller
        view._pagination = mock.MagicMock()
        view._pagination.displayed_count = 25
        view._pagination.load_more_row = mock.MagicMock()
        view._pagination._displayed_count = 25
        # Initialize search state
        view._search_query = ""
        view._filtered_entries = []

        view._on_show_all_clicked(mock.MagicMock())

        # The pagination controller's show_all method is called
        view._pagination.show_all.assert_called_once()


class TestQuarantineViewStorageInfo:
    """Tests for storage info display."""

    def test_update_storage_info_displays_size(
        self, quarantine_view_class, mock_quarantine_manager
    ):
        """Test that storage info displays total size."""
        view = object.__new__(quarantine_view_class)
        view._manager = mock_quarantine_manager
        view._manager.get_total_size.return_value = 1024 * 1024  # 1 MB
        view._manager.get_entry_count.return_value = 5
        view._storage_row = mock.MagicMock()
        view._count_label = mock.MagicMock()
        # Initialize search state (no active search)
        view._search_query = ""
        view._filtered_entries = []

        # Create mock entries
        mock_entries = [mock.MagicMock(file_size=1024 * 200) for _ in range(5)]
        view._update_storage_info(mock_entries)

        view._storage_row.set_subtitle.assert_called()
        view._count_label.set_text.assert_called_with("5 items")

    def test_update_storage_info_singular_item(
        self, quarantine_view_class, mock_quarantine_manager
    ):
        """Test that storage info displays singular 'item' for count of 1."""
        view = object.__new__(quarantine_view_class)
        view._manager = mock_quarantine_manager
        view._manager.get_total_size.return_value = 512
        view._manager.get_entry_count.return_value = 1
        view._storage_row = mock.MagicMock()
        view._count_label = mock.MagicMock()
        # Initialize search state (no active search)
        view._search_query = ""
        view._filtered_entries = []

        # Create mock entry
        mock_entries = [mock.MagicMock(file_size=512)]
        view._update_storage_info(mock_entries)

        view._count_label.set_text.assert_called_with("1 item")


class TestQuarantineViewSearch:
    """Tests for QuarantineView search filtering functionality."""

    def test_filter_entries_empty_query_returns_all(self, quarantine_view_class):
        """Test that empty search query returns all entries."""
        view = object.__new__(quarantine_view_class)

        # Create mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"

        view._all_entries = [entry1, entry2]
        view._search_query = ""

        result = view._filter_entries()

        assert len(result) == 2
        assert result == [entry1, entry2]

    def test_filter_entries_case_insensitive_matching(self, quarantine_view_class):
        """Test that search matching is case-insensitive."""
        view = object.__new__(quarantine_view_class)

        # Create mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"

        view._all_entries = [entry1, entry2]
        view._search_query = "EICAR"

        result = view._filter_entries()

        assert len(result) == 1
        assert result[0] == entry1

    def test_filter_entries_matches_threat_name(self, quarantine_view_class):
        """Test that search matches against threat_name field."""
        view = object.__new__(quarantine_view_class)

        # Create mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"

        view._all_entries = [entry1, entry2]
        view._search_query = "trojan"

        result = view._filter_entries()

        assert len(result) == 1
        assert result[0] == entry2

    def test_filter_entries_matches_original_path(self, quarantine_view_class):
        """Test that search matches against original_path field."""
        view = object.__new__(quarantine_view_class)

        # Create mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/downloads/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/documents/file2.exe"

        view._all_entries = [entry1, entry2]
        view._search_query = "downloads"

        result = view._filter_entries()

        assert len(result) == 1
        assert result[0] == entry1

    def test_filter_entries_partial_match_works(self, quarantine_view_class):
        """Test that partial substring matching works correctly."""
        view = object.__new__(quarantine_view_class)

        # Create mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"

        entry3 = mock.MagicMock()
        entry3.threat_name = "Trojan.Downloader"
        entry3.original_path = "/home/user/file3.exe"

        view._all_entries = [entry1, entry2, entry3]
        view._search_query = "troj"

        result = view._filter_entries()

        assert len(result) == 2
        assert entry2 in result
        assert entry3 in result

    def test_filter_entries_no_matches_returns_empty(self, quarantine_view_class):
        """Test that no matches returns empty list."""
        view = object.__new__(quarantine_view_class)

        # Create mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"

        view._all_entries = [entry1, entry2]
        view._search_query = "nonexistent"

        result = view._filter_entries()

        assert len(result) == 0
        assert result == []

    def test_filter_entries_handles_none_values(self, quarantine_view_class):
        """Test that None values in threat_name or original_path are handled gracefully."""
        view = object.__new__(quarantine_view_class)

        # Create mock entries with None values
        entry1 = mock.MagicMock()
        entry1.threat_name = None
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = None

        entry3 = mock.MagicMock()
        entry3.threat_name = "Eicar-Test-Signature"
        entry3.original_path = "/home/user/file3.exe"

        view._all_entries = [entry1, entry2, entry3]
        view._search_query = "eicar"

        result = view._filter_entries()

        # Should only match entry3, None values should not cause errors
        assert len(result) == 1
        assert result[0] == entry3

    def test_filter_entries_matches_either_field(self, quarantine_view_class):
        """Test that search matches if query appears in either threat_name or original_path."""
        view = object.__new__(quarantine_view_class)

        # Create mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/test/file2.exe"

        view._all_entries = [entry1, entry2]
        view._search_query = "test"

        result = view._filter_entries()

        # Should match both: entry1 by threat_name ("Test"), entry2 by path ("/test/")
        assert len(result) == 2
        assert entry1 in result
        assert entry2 in result


class TestQuarantineViewSearchIntegration:
    """Integration tests for search filter functionality."""

    def test_search_state_initialization(self, quarantine_view_class):
        """Test that search state variables are properly initialized."""
        view = object.__new__(quarantine_view_class)
        view._search_query = ""
        view._filtered_entries = []
        view._search_timeout_id = None

        assert view._search_query == ""
        assert view._filtered_entries == []
        assert view._search_timeout_id is None

    def test_apply_search_filter_clears_listbox(self, quarantine_view_class):
        """Test that _apply_search_filter clears the listbox before repopulating."""
        view = object.__new__(quarantine_view_class)

        # Set up mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"
        entry1.file_size = 512

        view._all_entries = [entry1]
        view._search_query = "eicar"
        view._filtered_entries = []

        # Mock pagination controller
        view._pagination = mock.MagicMock()
        view._pagination.displayed_count = 5
        view._pagination.load_more_row = mock.MagicMock()
        view._pagination._displayed_count = 5

        # Mock UI elements
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None  # Simulate empty after clear
        view._count_label = mock.MagicMock()
        view._storage_row = mock.MagicMock()

        # Mock methods
        view._filter_entries = mock.MagicMock(return_value=[entry1])
        view._update_storage_info = mock.MagicMock()

        view._apply_search_filter()

        # Verify pagination's set_entries was called (which clears and repopulates)
        view._pagination.set_entries.assert_called()

    def test_apply_search_filter_updates_display(self, quarantine_view_class):
        """Test that _apply_search_filter updates the display with filtered entries."""
        view = object.__new__(quarantine_view_class)

        # Set up mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"
        entry1.file_size = 512

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"
        entry2.file_size = 1024

        view._all_entries = [entry1, entry2]
        view._search_query = "eicar"
        view._filtered_entries = []

        # Mock pagination controller
        view._pagination = mock.MagicMock()
        view._pagination.displayed_count = 0
        view._pagination.load_more_row = None
        view._pagination._displayed_count = 0

        # Mock UI elements
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None
        view._count_label = mock.MagicMock()
        view._storage_row = mock.MagicMock()

        # Mock methods
        view._filter_entries = mock.MagicMock(return_value=[entry1])
        view._update_storage_info = mock.MagicMock()
        view._create_no_results_state = mock.MagicMock()
        view._create_empty_state = mock.MagicMock()

        view._apply_search_filter()

        # Verify filtered entries were updated
        view._filter_entries.assert_called_once()
        # Verify storage info was updated with all entries (not filtered)
        view._update_storage_info.assert_called_once_with(view._all_entries)
        # Verify pagination was updated with filtered results
        view._pagination.set_entries.assert_called()

    def test_apply_search_filter_shows_no_results_placeholder(self, quarantine_view_class):
        """Test that _apply_search_filter shows no-results placeholder when filter returns empty."""
        view = object.__new__(quarantine_view_class)

        # Set up mock entries (have entries, but search returns none)
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"
        entry1.file_size = 512

        view._all_entries = [entry1]
        view._search_query = "nonexistent"
        view._filtered_entries = []
        view._displayed_count = 0
        view._load_more_row = None

        # Mock UI elements
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None
        view._count_label = mock.MagicMock()
        view._storage_row = mock.MagicMock()

        # Mock methods
        view._filter_entries = mock.MagicMock(return_value=[])
        view._update_storage_info = mock.MagicMock()
        no_results_widget = mock.MagicMock()
        view._create_no_results_state = mock.MagicMock(return_value=no_results_widget)

        view._apply_search_filter()

        # Verify no-results placeholder was created and set
        view._create_no_results_state.assert_called_once()
        view._listbox.set_placeholder.assert_called_with(no_results_widget)

    def test_entries_to_display_returns_filtered_when_search_active(self, quarantine_view_class):
        """Test that _entries_to_display returns filtered entries when search is active."""
        view = object.__new__(quarantine_view_class)

        # Set up mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"

        view._all_entries = [entry1, entry2]
        view._filtered_entries = [entry1]
        view._search_query = "eicar"

        result = view._entries_to_display

        # Should return filtered entries when search is active
        assert result == [entry1]
        assert len(result) == 1

    def test_entries_to_display_returns_all_when_search_inactive(self, quarantine_view_class):
        """Test that _entries_to_display returns all entries when search is inactive."""
        view = object.__new__(quarantine_view_class)

        # Set up mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"

        view._all_entries = [entry1, entry2]
        view._filtered_entries = [entry1]
        view._search_query = ""

        result = view._entries_to_display

        # Should return all entries when search is empty
        assert result == [entry1, entry2]
        assert len(result) == 2

    def test_display_entry_batch_uses_filtered_entries(self, quarantine_view_class):
        """Test that pagination delegates correctly with filtered entries."""
        view = object.__new__(quarantine_view_class)

        # Set up mock entries
        entry1 = mock.MagicMock()
        entry1.threat_name = "Eicar-Test-Signature"
        entry1.original_path = "/home/user/file1.exe"

        entry2 = mock.MagicMock()
        entry2.threat_name = "Trojan.Generic"
        entry2.original_path = "/home/user/file2.exe"

        entry3 = mock.MagicMock()
        entry3.threat_name = "Trojan.Downloader"
        entry3.original_path = "/home/user/file3.exe"

        view._all_entries = [entry1, entry2, entry3]
        view._filtered_entries = [entry2, entry3]
        view._search_query = "trojan"

        # Mock pagination controller
        view._pagination = mock.MagicMock()
        view._pagination.displayed_count = 0
        view._pagination.load_more_row = None

        # Mock UI elements
        view._listbox = mock.MagicMock()
        view._listbox.get_first_child.return_value = None
        view._create_entry_row = mock.MagicMock(return_value=mock.MagicMock())

        # Display first batch - should delegate to pagination controller
        view._display_entry_batch(0, 2)

        # Verify delegation to pagination controller with correct arguments
        view._pagination.display_batch.assert_called_once_with(0, 2)

    def test_update_storage_info_shows_filtered_count(self, quarantine_view_class, mock_gi_modules):
        """Test that storage info shows filtered count when search is active."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.quarantine": mock.MagicMock(),
            },
        ):
            from src.ui.quarantine_view import format_file_size

            view = object.__new__(quarantine_view_class)
            view._manager = mock.MagicMock()

            # Set up mock entries
            entry1 = mock.MagicMock()
            entry1.file_size = 512

            entry2 = mock.MagicMock()
            entry2.file_size = 1024

            entry3 = mock.MagicMock()
            entry3.file_size = 2048

            all_entries = [entry1, entry2, entry3]
            view._all_entries = all_entries
            view._filtered_entries = [entry1, entry2]
            view._search_query = "test"

            # Mock UI elements
            view._count_label = mock.MagicMock()
            view._storage_row = mock.MagicMock()

            view._update_storage_info(all_entries)

            # Should show "2 of 3 items" format
            view._count_label.set_text.assert_called_with("2 of 3 items")
            # Size should still reflect all entries
            total_size = 512 + 1024 + 2048
            expected_size = format_file_size(total_size)
            view._storage_row.set_subtitle.assert_called_with(expected_size)

    def test_update_storage_info_shows_normal_count_when_no_search(self, quarantine_view_class):
        """Test that storage info shows normal count when search is inactive."""
        view = object.__new__(quarantine_view_class)
        view._manager = mock.MagicMock()

        # Set up mock entries
        entry1 = mock.MagicMock()
        entry1.file_size = 512

        entry2 = mock.MagicMock()
        entry2.file_size = 1024

        all_entries = [entry1, entry2]
        view._all_entries = all_entries
        view._filtered_entries = []
        view._search_query = ""

        # Mock UI elements
        view._count_label = mock.MagicMock()
        view._storage_row = mock.MagicMock()

        view._update_storage_info(all_entries)

        # Should show "2 items" format (normal)
        view._count_label.set_text.assert_called_with("2 items")

    def test_update_storage_info_handles_singular_filtered_count(self, quarantine_view_class):
        """Test that storage info handles singular item correctly when filtered."""
        view = object.__new__(quarantine_view_class)
        view._manager = mock.MagicMock()

        # Set up mock entries
        entry1 = mock.MagicMock()
        entry1.file_size = 512

        entry2 = mock.MagicMock()
        entry2.file_size = 1024

        all_entries = [entry1, entry2]
        view._all_entries = all_entries
        view._filtered_entries = [entry1]
        view._search_query = "test"

        # Mock UI elements
        view._count_label = mock.MagicMock()
        view._storage_row = mock.MagicMock()

        view._update_storage_info(all_entries)

        # Should show "1 of 2 items" format
        view._count_label.set_text.assert_called_with("1 of 2 items")


class TestQuarantineViewConfirmations:
    """Tests for the delete/restore confirmation flow."""

    def test_delete_confirm_response_triggers_delete(
        self, mock_quarantine_view, mock_quarantine_manager, mock_quarantine_entry
    ):
        """Confirming the dialog starts the async delete."""
        mock_quarantine_view._on_delete_confirm_response(
            mock.MagicMock(), "confirm", mock_quarantine_entry
        )

        mock_quarantine_manager.delete_file_async.assert_called_once()
        assert mock_quarantine_manager.delete_file_async.call_args[0][0] == mock_quarantine_entry.id

    def test_delete_cancel_response_does_not_delete(
        self, mock_quarantine_view, mock_quarantine_manager, mock_quarantine_entry
    ):
        """Cancelling the dialog must not delete anything."""
        mock_quarantine_view._on_delete_confirm_response(
            mock.MagicMock(), "cancel", mock_quarantine_entry
        )

        mock_quarantine_manager.delete_file_async.assert_not_called()

    def test_restore_confirm_response_triggers_restore(
        self, mock_quarantine_view, mock_quarantine_manager, mock_quarantine_entry
    ):
        """Confirming the dialog starts the async restore."""
        mock_quarantine_view._on_restore_confirm_response(
            mock.MagicMock(), "confirm", mock_quarantine_entry
        )

        mock_quarantine_manager.restore_file_async.assert_called_once()
        assert (
            mock_quarantine_manager.restore_file_async.call_args[0][0] == mock_quarantine_entry.id
        )

    def test_restore_cancel_response_does_not_restore(
        self, mock_quarantine_view, mock_quarantine_manager, mock_quarantine_entry
    ):
        """Cancelling the dialog must not restore anything."""
        mock_quarantine_view._on_restore_confirm_response(
            mock.MagicMock(), "cancel", mock_quarantine_entry
        )

        mock_quarantine_manager.restore_file_async.assert_not_called()


class TestQuarantineViewStorageInfoExtended:
    """Extended tests for storage info with additional edge cases."""

    def test_create_entry_row_truncates_long_path(
        self, quarantine_view_class, mock_quarantine_entry
    ):
        """Test that long paths are truncated in subtitle."""
        view = object.__new__(quarantine_view_class)
        mock_quarantine_entry.original_path = (
            "/home/user/very/long/path/that/exceeds/fifty/characters/limit/file.exe"
        )

        mock_row = mock.MagicMock()
        from gi.repository import Adw

        Adw.ExpanderRow.return_value = mock_row

        view._create_entry_row(mock_quarantine_entry)

        # Verify subtitle was set with truncated path
        calls = mock_row.set_subtitle.call_args_list
        if calls:
            subtitle = calls[0][0][0]
            assert subtitle.startswith("...")


# Module-level test function for verification
def test_quarantine_view_basic(mock_gi_modules):
    """
    Basic test function for pytest verification command.

    This test verifies the core QuarantineView functionality
    using a minimal mock setup.
    """
    with mock.patch.dict(
        sys.modules,
        {
            "src.core.quarantine": mock.MagicMock(),
        },
    ):
        from src.ui.pagination import PaginatedListController
        from src.ui.quarantine_view import (
            QuarantineView,
            format_file_size,
        )

        # Test 1: Class can be imported
        assert QuarantineView is not None

        # Test 2: Pagination constants are correct
        assert PaginatedListController.DEFAULT_INITIAL_LIMIT == 25
        assert PaginatedListController.DEFAULT_BATCH_SIZE == 25

        # Test 3: format_file_size function works
        assert format_file_size(0) == "0 B"
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(1024 * 1024) == "1.0 MB"
        assert format_file_size(1024 * 1024 * 1024) == "1.00 GB"

        # Test 4: Create mock instance and test basic methods
        view = object.__new__(QuarantineView)
        view._manager = mock.MagicMock()
        view._manager.get_entry_count.return_value = 5
        view._manager.get_total_size.return_value = 2048
        view._storage_row = mock.MagicMock()
        view._count_label = mock.MagicMock()
        # Initialize search state
        view._search_query = ""
        view._filtered_entries = []

        # Test _update_storage_info
        mock_entries = [mock.MagicMock(file_size=512) for _ in range(5)]
        view._update_storage_info(mock_entries)

        view._storage_row.set_subtitle.assert_called_with("2.5 KB")  # 512 * 5 = 2560 bytes
        view._count_label.set_text.assert_called_with("5 items")

        # All tests passed


class TestQuarantineViewSharedQuarantineManager:
    """Tests for shared QuarantineManager injection in QuarantineView."""

    def test_quarantine_view_uses_provided_manager(self, quarantine_view_class):
        """When quarantine_manager is passed, QuarantineView should use it."""
        qv_module = sys.modules["src.ui.quarantine_view"]

        original_qm = getattr(qv_module, "QuarantineManager", mock.MagicMock)
        mock_qm_class = mock.MagicMock()
        qv_module.QuarantineManager = mock_qm_class

        try:
            external_manager = mock.MagicMock(name="shared_qm")
            view = quarantine_view_class(quarantine_manager=external_manager)
            # The external manager should be used
            assert view._manager is external_manager
            # QuarantineManager() should NOT have been called
            mock_qm_class.assert_not_called()
        finally:
            qv_module.QuarantineManager = original_qm

    def test_quarantine_view_creates_own_manager_when_not_provided(self, quarantine_view_class):
        """When quarantine_manager is not passed, QuarantineView creates its own."""
        qv_module = sys.modules["src.ui.quarantine_view"]

        mock_qm_instance = mock.MagicMock(name="auto_created_qm")
        mock_qm_class = mock.MagicMock(return_value=mock_qm_instance)
        original_qm = getattr(qv_module, "QuarantineManager", mock.MagicMock)
        qv_module.QuarantineManager = mock_qm_class

        try:
            view = quarantine_view_class()
            # QuarantineManager() should have been called
            mock_qm_class.assert_called_once()
            assert view._manager is mock_qm_instance
        finally:
            qv_module.QuarantineManager = original_qm
