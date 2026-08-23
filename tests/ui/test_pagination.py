# ClamUI Pagination Controller Tests
"""
Unit tests for the PaginatedListController component.

Tests cover:
- Initialization with default and custom parameters
- State management and reset functionality
- Property access (displayed_count, all_entries, load_more_row, entries_to_display)
- Configuration validation
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
def pagination_controller_class(mock_gi_modules):
    """Get PaginatedListController class with mocked dependencies."""
    # Clear any cached import of pagination module
    if "src.ui.pagination" in sys.modules:
        del sys.modules["src.ui.pagination"]

    from src.ui.pagination import PaginatedListController

    yield PaginatedListController

    # Critical: Clear all src.* modules after test to prevent pollution
    _clear_src_modules()


@pytest.fixture
def mock_listbox(mock_gi_modules):
    """Create a mock GTK ListBox."""
    listbox = mock.MagicMock()
    # Default to empty listbox - get_first_child returns None
    # Tests that need children should set side_effect explicitly
    listbox.get_first_child.return_value = None
    return listbox


@pytest.fixture
def mock_scrolled_window(mock_gi_modules):
    """Create a mock GTK ScrolledWindow."""
    return mock.MagicMock()


@pytest.fixture
def mock_row_factory():
    """Create a mock row factory callback."""
    return mock.MagicMock(return_value=mock.MagicMock())


@pytest.fixture
def pagination_controller(
    pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
):
    """Create a PaginatedListController instance with default parameters."""
    return pagination_controller_class(
        listbox=mock_listbox,
        scrolled_window=mock_scrolled_window,
        row_factory=mock_row_factory,
    )


class TestPaginationControllerImport:
    """Tests for PaginatedListController import."""

    def test_import_pagination_controller(self, mock_gi_modules):
        """Test that PaginatedListController can be imported."""
        from src.ui.pagination import PaginatedListController

        assert PaginatedListController is not None

    def test_default_constants_defined(self, mock_gi_modules):
        """Test that default pagination constants are defined."""
        from src.ui.pagination import PaginatedListController

        assert PaginatedListController.DEFAULT_INITIAL_LIMIT == 25
        assert PaginatedListController.DEFAULT_BATCH_SIZE == 25


class TestPaginationControllerInitialization:
    """Tests for PaginatedListController initialization."""

    def test_initialization_with_default_limits(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test initialization with default initial_limit and batch_size."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
        )

        assert controller._initial_limit == 25
        assert controller._batch_size == 25
        assert controller._listbox is mock_listbox
        assert controller._scrolled_window is mock_scrolled_window
        assert controller._row_factory is mock_row_factory

    def test_initialization_with_custom_limits(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test initialization with custom initial_limit and batch_size."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            initial_limit=50,
            batch_size=20,
        )

        assert controller._initial_limit == 50
        assert controller._batch_size == 20

    def test_initial_state_is_empty(self, pagination_controller):
        """Test that initial pagination state is empty."""
        assert pagination_controller._displayed_count == 0
        assert pagination_controller._all_entries == []
        assert pagination_controller._load_more_row is None

    def test_initial_displayed_count_is_zero(self, pagination_controller):
        """Test that initial displayed count is zero."""
        assert pagination_controller.displayed_count == 0

    def test_initial_all_entries_is_empty(self, pagination_controller):
        """Test that initial all_entries is empty list."""
        assert pagination_controller.all_entries == []

    def test_initial_load_more_row_is_none(self, pagination_controller):
        """Test that initial load_more_row is None."""
        assert pagination_controller.load_more_row is None


class TestPaginationControllerStateManagement:
    """Tests for state management and reset functionality."""

    def test_reset_state_clears_displayed_count(self, pagination_controller):
        """Test that reset_state clears displayed_count."""
        pagination_controller._displayed_count = 25
        pagination_controller.reset_state()

        assert pagination_controller._displayed_count == 0

    def test_reset_state_clears_all_entries(self, pagination_controller):
        """Test that reset_state clears all_entries."""
        pagination_controller._all_entries = ["entry1", "entry2", "entry3"]
        pagination_controller.reset_state()

        assert pagination_controller._all_entries == []

    def test_reset_state_clears_load_more_row(self, pagination_controller):
        """Test that reset_state clears load_more_row."""
        pagination_controller._load_more_row = mock.MagicMock()
        pagination_controller.reset_state()

        assert pagination_controller._load_more_row is None

    def test_reset_state_clears_all_state_together(self, pagination_controller):
        """Test that reset_state clears all pagination state in one call."""
        pagination_controller._displayed_count = 50
        pagination_controller._all_entries = ["entry1", "entry2"]
        pagination_controller._load_more_row = mock.MagicMock()

        pagination_controller.reset_state()

        assert pagination_controller._displayed_count == 0
        assert pagination_controller._all_entries == []
        assert pagination_controller._load_more_row is None

    def test_reset_state_does_not_modify_listbox(self, pagination_controller, mock_listbox):
        """Test that reset_state does not modify the listbox."""
        pagination_controller._displayed_count = 10
        pagination_controller._all_entries = ["entry1"]

        pagination_controller.reset_state()

        # Listbox should not be touched during reset_state
        mock_listbox.remove.assert_not_called()
        mock_listbox.append.assert_not_called()

    def test_reset_state_multiple_times(self, pagination_controller):
        """Test that reset_state can be called multiple times safely."""
        pagination_controller._displayed_count = 10
        pagination_controller._all_entries = ["entry1"]
        pagination_controller._load_more_row = mock.MagicMock()

        pagination_controller.reset_state()
        pagination_controller.reset_state()  # Second call

        assert pagination_controller._displayed_count == 0
        assert pagination_controller._all_entries == []
        assert pagination_controller._load_more_row is None


class TestPaginationControllerProperties:
    """Tests for property access methods."""

    def test_displayed_count_property_returns_count(self, pagination_controller):
        """Test that displayed_count property returns the internal count."""
        pagination_controller._displayed_count = 42
        assert pagination_controller.displayed_count == 42

    def test_displayed_count_property_reflects_changes(self, pagination_controller):
        """Test that displayed_count property reflects state changes."""
        assert pagination_controller.displayed_count == 0

        pagination_controller._displayed_count = 10
        assert pagination_controller.displayed_count == 10

        pagination_controller._displayed_count = 25
        assert pagination_controller.displayed_count == 25

    def test_all_entries_property_returns_entries(self, pagination_controller):
        """Test that all_entries property returns the internal entries list."""
        entries = ["entry1", "entry2", "entry3"]
        pagination_controller._all_entries = entries
        assert pagination_controller.all_entries == entries

    def test_all_entries_property_returns_same_reference(self, pagination_controller):
        """Test that all_entries property returns the same list reference."""
        entries = ["entry1", "entry2"]
        pagination_controller._all_entries = entries
        assert pagination_controller.all_entries is entries

    def test_load_more_row_property_returns_row(self, pagination_controller):
        """Test that load_more_row property returns the internal row."""
        mock_row = mock.MagicMock()
        pagination_controller._load_more_row = mock_row
        assert pagination_controller.load_more_row is mock_row

    def test_load_more_row_property_returns_none(self, pagination_controller):
        """Test that load_more_row property returns None when not set."""
        assert pagination_controller.load_more_row is None

    def test_entries_to_display_returns_all_entries(self, pagination_controller):
        """Test that entries_to_display property returns all_entries by default."""
        entries = ["entry1", "entry2", "entry3"]
        pagination_controller._all_entries = entries
        assert pagination_controller.entries_to_display == entries

    def test_entries_to_display_returns_same_reference(self, pagination_controller):
        """Test that entries_to_display returns the same reference as all_entries."""
        entries = ["entry1", "entry2"]
        pagination_controller._all_entries = entries
        assert pagination_controller.entries_to_display is entries

    def test_entries_to_display_empty_list(self, pagination_controller):
        """Test that entries_to_display returns empty list when no entries."""
        assert pagination_controller.entries_to_display == []

    def test_entries_to_display_reflects_changes(self, pagination_controller):
        """Test that entries_to_display reflects changes to all_entries."""
        assert pagination_controller.entries_to_display == []

        pagination_controller._all_entries = ["entry1"]
        assert pagination_controller.entries_to_display == ["entry1"]

        pagination_controller._all_entries = ["entry1", "entry2", "entry3"]
        assert pagination_controller.entries_to_display == ["entry1", "entry2", "entry3"]


class TestPaginationControllerConfiguration:
    """Tests for configuration parameters."""

    def test_custom_initial_limit_stored(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that custom initial_limit is stored correctly."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            initial_limit=100,
        )

        assert controller._initial_limit == 100

    def test_custom_batch_size_stored(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that custom batch_size is stored correctly."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            batch_size=50,
        )

        assert controller._batch_size == 50

    def test_all_custom_parameters_together(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test initialization with all custom parameters."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            initial_limit=75,
            batch_size=30,
        )

        assert controller._initial_limit == 75
        assert controller._batch_size == 30
        assert controller._listbox is mock_listbox
        assert controller._scrolled_window is mock_scrolled_window
        assert controller._row_factory is mock_row_factory

    def test_row_factory_is_callable(self, pagination_controller):
        """Test that row_factory can be called."""
        mock_entry = {"id": "test"}
        result = pagination_controller._row_factory(mock_entry)

        pagination_controller._row_factory.assert_called_once_with(mock_entry)
        assert result is not None


# Module-level test function for verification
def test_pagination_basic(mock_gi_modules):
    """
    Basic test function for pytest verification command.

    This test verifies the core PaginatedListController functionality
    using the centralized mock setup.
    """
    from src.ui.pagination import PaginatedListController

    # Test 1: Class can be imported
    assert PaginatedListController is not None

    # Test 2: Default constants are correct
    assert PaginatedListController.DEFAULT_INITIAL_LIMIT == 25
    assert PaginatedListController.DEFAULT_BATCH_SIZE == 25

    # Test 3: Create instance with default parameters
    mock_listbox = mock.MagicMock()
    mock_scrolled = mock.MagicMock()
    mock_factory = mock.MagicMock()

    controller = PaginatedListController(
        listbox=mock_listbox,
        scrolled_window=mock_scrolled,
        row_factory=mock_factory,
    )

    # Test 4: Initial state is correct
    assert controller.displayed_count == 0
    assert controller.all_entries == []
    assert controller.load_more_row is None
    assert controller.entries_to_display == []

    # Test 5: Reset state works
    controller._displayed_count = 10
    controller._all_entries = ["test1", "test2"]
    controller._load_more_row = mock.MagicMock()

    controller.reset_state()

    assert controller.displayed_count == 0
    assert controller.all_entries == []
    assert controller.load_more_row is None

    # All tests passed


class TestPaginationControllerDisplayBatch:
    """Tests for display_batch() functionality."""

    def test_display_batch_calls_row_factory_for_each_entry(
        self, pagination_controller, mock_row_factory, mock_listbox
    ):
        """Test that display_batch calls row_factory for each entry in the batch."""
        entries = ["entry1", "entry2", "entry3", "entry4", "entry5"]
        pagination_controller._all_entries = entries

        pagination_controller.display_batch(0, 3)

        # Should have called row_factory 3 times
        assert mock_row_factory.call_count == 3
        mock_row_factory.assert_any_call("entry1")
        mock_row_factory.assert_any_call("entry2")
        mock_row_factory.assert_any_call("entry3")

    def test_display_batch_appends_rows_to_listbox(
        self, pagination_controller, mock_row_factory, mock_listbox
    ):
        """Test that display_batch appends rows to listbox when no load_more_row."""
        entries = ["entry1", "entry2"]
        pagination_controller._all_entries = entries

        pagination_controller.display_batch(0, 2)

        # Should have appended 2 rows
        assert mock_listbox.append.call_count == 2

    def test_display_batch_inserts_before_load_more_row(
        self, pagination_controller, mock_row_factory, mock_listbox
    ):
        """Test that display_batch inserts rows before load_more_row when it exists."""
        entries = ["entry1", "entry2", "entry3"]
        pagination_controller._all_entries = entries
        pagination_controller._load_more_row = mock.MagicMock()

        pagination_controller.display_batch(0, 2)

        # Should have inserted 2 rows using insert() instead of append()
        assert mock_listbox.insert.call_count == 2
        mock_listbox.append.assert_not_called()

    def test_display_batch_increments_displayed_count(self, pagination_controller):
        """Test that display_batch increments displayed_count for each successful row."""
        entries = ["entry1", "entry2", "entry3"]
        pagination_controller._all_entries = entries
        assert pagination_controller._displayed_count == 0

        pagination_controller.display_batch(0, 3)

        assert pagination_controller._displayed_count == 3

    def test_display_batch_handles_row_factory_exception(self, pagination_controller, mock_listbox):
        """Test that display_batch handles row_factory exceptions gracefully."""
        entries = ["entry1", "entry2", "entry3"]
        pagination_controller._all_entries = entries

        # Mock row_factory to raise exception on second entry
        def failing_factory(entry):
            if entry == "entry2":
                raise ValueError("Test error")
            return mock.MagicMock()

        pagination_controller._row_factory = failing_factory

        # Should not raise exception
        pagination_controller.display_batch(0, 3)

        # Should have appended 2 rows (skipping the failed one)
        assert mock_listbox.append.call_count == 2
        # displayed_count should only count successful rows
        assert pagination_controller._displayed_count == 2

    def test_display_batch_respects_batch_size_limit(self, pagination_controller, mock_row_factory):
        """Test that display_batch only displays the requested count."""
        entries = ["entry1", "entry2", "entry3", "entry4", "entry5"]
        pagination_controller._all_entries = entries

        pagination_controller.display_batch(0, 2)

        # Should only call row_factory 2 times
        assert mock_row_factory.call_count == 2
        assert pagination_controller._displayed_count == 2

    def test_display_batch_handles_end_of_list(self, pagination_controller, mock_row_factory):
        """Test that display_batch handles batch size exceeding available entries."""
        entries = ["entry1", "entry2"]
        pagination_controller._all_entries = entries

        # Request 5 entries but only 2 are available
        pagination_controller.display_batch(0, 5)

        # Should only call row_factory 2 times
        assert mock_row_factory.call_count == 2
        assert pagination_controller._displayed_count == 2

    def test_display_batch_with_start_offset(self, pagination_controller, mock_row_factory):
        """Test that display_batch correctly starts from a given index."""
        entries = ["entry1", "entry2", "entry3", "entry4", "entry5"]
        pagination_controller._all_entries = entries

        # Start from index 2, display 2 entries
        pagination_controller.display_batch(2, 2)

        # Should call row_factory with entries 3 and 4
        assert mock_row_factory.call_count == 2
        mock_row_factory.assert_any_call("entry3")
        mock_row_factory.assert_any_call("entry4")

    def test_display_batch_updates_count_from_existing_value(
        self, pagination_controller, mock_row_factory
    ):
        """Test that display_batch increments from existing displayed_count."""
        entries = ["entry1", "entry2", "entry3"]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 10  # Already showing 10 entries

        pagination_controller.display_batch(0, 2)

        # Should increment from 10 to 12
        assert pagination_controller._displayed_count == 12

    def test_display_batch_uses_entries_to_display_property(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that display_batch uses entries_to_display property (for filtering)."""

        # Create a controller subclass with custom entries_to_display
        class FilteredController(pagination_controller_class):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._filtered_entries = []

            @property
            def entries_to_display(self):
                return self._filtered_entries

        controller = FilteredController(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
        )

        # Set filtered entries (not all_entries)
        controller._all_entries = ["entry1", "entry2", "entry3"]
        controller._filtered_entries = ["filtered1", "filtered2"]

        controller.display_batch(0, 2)

        # Should use filtered entries
        mock_row_factory.assert_any_call("filtered1")
        mock_row_factory.assert_any_call("filtered2")


class TestPaginationControllerSetEntries:
    """Tests for set_entries() entry point."""

    def test_set_entries_with_empty_list(self, pagination_controller, mock_listbox):
        """Test that set_entries handles empty list correctly."""
        # mock_listbox fixture defaults to empty (get_first_child returns None)
        pagination_controller.set_entries([])

        # Should have checked the listbox
        assert mock_listbox.get_first_child.called

        # State should be reset
        assert pagination_controller._all_entries == []
        assert pagination_controller._displayed_count == 0
        assert pagination_controller._load_more_row is None

        # Should not add any rows
        mock_listbox.append.assert_not_called()

    def test_set_entries_clears_existing_listbox(self, pagination_controller, mock_listbox):
        """Test that set_entries clears existing listbox content."""
        # Set up mock listbox with children
        mock_child1 = mock.MagicMock()
        mock_child2 = mock.MagicMock()

        # Mock get_first_child to return children, then None
        mock_listbox.get_first_child.side_effect = [mock_child1, mock_child2, None]

        pagination_controller.set_entries(["entry1"])

        # Should have called remove for each child
        assert mock_listbox.remove.call_count == 2
        mock_listbox.remove.assert_any_call(mock_child1)
        mock_listbox.remove.assert_any_call(mock_child2)

    def test_set_entries_resets_pagination_state(self, pagination_controller):
        """Test that set_entries resets all pagination state."""
        # Set up existing state
        pagination_controller._displayed_count = 50
        pagination_controller._all_entries = ["old1", "old2"]
        pagination_controller._load_more_row = mock.MagicMock()

        new_entries = ["new1", "new2", "new3"]
        pagination_controller.set_entries(new_entries)

        # State should be reset and new entries stored
        assert pagination_controller._all_entries == new_entries
        # displayed_count should reflect initial batch
        assert pagination_controller._displayed_count == 3
        # load_more_row should be cleared (no button needed for 3 entries)
        assert pagination_controller._load_more_row is None

    def test_set_entries_with_entries_below_initial_limit(
        self, pagination_controller, mock_row_factory, mock_listbox
    ):
        """Test set_entries with entries count <= initial_limit."""
        entries = ["entry1", "entry2", "entry3"]  # 3 entries, default limit is 25
        pagination_controller.set_entries(entries)

        # Should display all entries
        assert mock_row_factory.call_count == 3
        assert pagination_controller._displayed_count == 3

        # Should not add load_more_button (no need for pagination)
        # Check that no ListBoxRow was created (load_more_button creates a row)
        rows_added = sum(1 for call in mock_listbox.append.call_args_list)
        # All appends should be for entry rows, not for load_more_row
        assert rows_added == 3

    def test_set_entries_with_entries_equal_to_initial_limit(
        self, pagination_controller, mock_row_factory, mock_listbox
    ):
        """Test set_entries with entries count exactly equal to initial_limit."""
        # Create 25 entries (equal to default initial_limit)
        entries = [f"entry{i}" for i in range(25)]
        pagination_controller.set_entries(entries)

        # Should display all 25 entries
        assert mock_row_factory.call_count == 25
        assert pagination_controller._displayed_count == 25

        # Should not add load_more_button (no entries remaining)
        assert pagination_controller._load_more_row is None

    def test_set_entries_with_entries_above_initial_limit(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_gi_modules
    ):
        """Test set_entries with entries count > initial_limit adds load_more."""
        # Create a fresh controller with mocked add_load_more_button
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock.MagicMock(return_value=mock.MagicMock()),
            initial_limit=25,
        )

        # Mock add_load_more_button to track calls
        controller.add_load_more_button = mock.MagicMock()

        # Create 30 entries (more than initial_limit of 25)
        entries = [f"entry{i}" for i in range(30)]
        controller.set_entries(entries)

        # Should display only initial_limit entries
        assert controller._displayed_count == 25

        # Should add load_more_button since there are more entries
        # (default label is None; translated to "entries" at render time)
        controller.add_load_more_button.assert_called_once_with(None)

    def test_set_entries_filtered_subset_below_limit_no_load_more(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_gi_modules
    ):
        """Regression: a filtered subset below the initial limit must not add a
        'Load More' button even when the full backing list exceeds it.

        A subclass may override entries_to_display() to return a filtered subset
        (e.g. quarantine search). set_entries() must base its pagination
        decisions on the entries actually displayed, not the raw backing list;
        otherwise narrowing 30 entries down to 2 produces a bogus 'Show 0 More'
        button and suppresses the no-results placeholder.
        """

        class FilteredController(pagination_controller_class):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._filtered_entries = []

            @property
            def entries_to_display(self):
                return self._filtered_entries

        controller = FilteredController(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock.MagicMock(return_value=mock.MagicMock()),
            initial_limit=25,
        )
        controller.add_load_more_button = mock.MagicMock()

        # Filtered view has only 2 matching entries...
        controller._filtered_entries = ["match1", "match2"]
        # ...while the full backing list passed to set_entries has 30.
        controller.set_entries([f"entry{i}" for i in range(30)])

        # Only the 2 filtered entries should be displayed
        assert controller._displayed_count == 2
        # No load-more button: all filtered entries are already visible
        controller.add_load_more_button.assert_not_called()

    def test_set_entries_displays_initial_batch(self, pagination_controller, mock_row_factory):
        """Test that set_entries displays the initial batch correctly."""
        # Create 30 entries, initial_limit is 25
        entries = [f"entry{i}" for i in range(30)]
        pagination_controller.set_entries(entries)

        # Should have called row_factory 25 times (initial_limit)
        assert mock_row_factory.call_count == 25
        # Verify it called with first 25 entries
        for i in range(25):
            mock_row_factory.assert_any_call(f"entry{i}")

    def test_set_entries_with_custom_entries_label(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_gi_modules
    ):
        """Test that set_entries passes custom entries_label to add_load_more_button."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock.MagicMock(return_value=mock.MagicMock()),
            initial_limit=10,
        )

        # Mock add_load_more_button to track calls
        controller.add_load_more_button = mock.MagicMock()

        # Create enough entries to trigger pagination
        entries = [f"entry{i}" for i in range(20)]
        controller.set_entries(entries, entries_label="logs")

        # Should pass custom label to add_load_more_button
        controller.add_load_more_button.assert_called_once_with("logs")

    def test_set_entries_stores_all_entries(self, pagination_controller):
        """Test that set_entries stores all entries in _all_entries."""
        entries = [f"entry{i}" for i in range(30)]
        pagination_controller.set_entries(entries)

        # Should store all entries
        assert pagination_controller._all_entries == entries
        assert len(pagination_controller._all_entries) == 30

    def test_set_entries_can_be_called_multiple_times(self, pagination_controller, mock_listbox):
        """Test that set_entries can be called multiple times to reload data."""
        # First load
        first_entries = ["entry1", "entry2"]
        pagination_controller.set_entries(first_entries)

        assert pagination_controller._all_entries == first_entries
        assert pagination_controller._displayed_count == 2

        # Reset mock to track second call
        mock_listbox.reset_mock()
        mock_listbox.get_first_child.side_effect = [mock.MagicMock(), None]

        # Second load with different data
        second_entries = ["new1", "new2", "new3"]
        pagination_controller.set_entries(second_entries)

        assert pagination_controller._all_entries == second_entries
        assert pagination_controller._displayed_count == 3


# Module-level test function for verification
def test_pagination_display_batch_basic(mock_gi_modules):
    """
    Basic test function for display_batch and set_entries verification.

    This test verifies the display batch and set_entries functionality
    using the centralized mock setup.
    """
    from src.ui.pagination import PaginatedListController

    mock_listbox = mock.MagicMock()
    mock_scrolled = mock.MagicMock()
    mock_factory = mock.MagicMock(return_value=mock.MagicMock())

    controller = PaginatedListController(
        listbox=mock_listbox,
        scrolled_window=mock_scrolled,
        row_factory=mock_factory,
        initial_limit=5,
    )

    # Test 1: display_batch calls row_factory
    controller._all_entries = ["entry1", "entry2", "entry3"]
    controller.display_batch(0, 2)

    assert mock_factory.call_count == 2
    assert controller.displayed_count == 2

    # Test 2: set_entries with empty list
    mock_listbox.reset_mock()
    mock_listbox.get_first_child.return_value = None
    controller.set_entries([])

    assert controller.all_entries == []
    assert controller.displayed_count == 0

    # Test 3: set_entries with entries below limit
    mock_listbox.reset_mock()
    mock_listbox.get_first_child.return_value = None
    mock_factory.reset_mock()

    controller.set_entries(["a", "b", "c"])

    assert len(controller.all_entries) == 3
    assert controller.displayed_count == 3
    assert mock_factory.call_count == 3

    # Test 4: set_entries with entries above limit
    mock_listbox.reset_mock()
    mock_listbox.get_first_child.return_value = None
    mock_factory.reset_mock()

    # Mock add_load_more_button
    controller.add_load_more_button = mock.MagicMock()

    entries = [f"entry{i}" for i in range(10)]  # 10 > 5 (initial_limit)
    controller.set_entries(entries)

    assert len(controller.all_entries) == 10
    assert controller.displayed_count == 5  # Only initial limit displayed
    controller.add_load_more_button.assert_called_once()

    # All tests passed


class TestPaginationControllerLoadMore:
    """Tests for load_more() functionality."""

    def test_load_more_displays_batch_size_more_entries(
        self, pagination_controller, mock_row_factory, mock_listbox
    ):
        """Test that load_more() displays batch_size more entries."""
        # Create 60 entries, initial_limit is 25, batch_size is 25
        entries = [f"entry{i}" for i in range(60)]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 25
        pagination_controller._load_more_row = mock.MagicMock()

        # Mock add_load_more_button to track calls
        pagination_controller.add_load_more_button = mock.MagicMock()

        mock_row_factory.reset_mock()
        pagination_controller.load_more()

        # Should display next 25 entries (batch_size)
        assert mock_row_factory.call_count == 25
        assert pagination_controller._displayed_count == 50

    def test_load_more_readds_button_when_more_entries_remain(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that load_more() re-adds button when more entries remain."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            initial_limit=25,
            batch_size=25,
        )

        # Create 60 entries (25 displayed, 25 after load_more, 10 remaining)
        entries = [f"entry{i}" for i in range(60)]
        controller._all_entries = entries
        controller._displayed_count = 25
        controller._load_more_row = mock.MagicMock()

        # Mock add_load_more_button to track calls
        controller.add_load_more_button = mock.MagicMock()

        controller.load_more()

        # Should re-add load_more_button since 10 entries remain
        # (default label is None; translated to "entries" at render time)
        controller.add_load_more_button.assert_called_once_with(None)

    def test_load_more_does_not_readd_button_when_all_displayed(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that load_more() does not re-add button when all entries displayed."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            initial_limit=25,
            batch_size=25,
        )

        # Create 40 entries (25 displayed, 15 remaining - will all be shown)
        entries = [f"entry{i}" for i in range(40)]
        controller._all_entries = entries
        controller._displayed_count = 25
        controller._load_more_row = mock.MagicMock()

        # Mock add_load_more_button to track calls
        controller.add_load_more_button = mock.MagicMock()

        controller.load_more()

        # Should NOT re-add load_more_button since all entries are now displayed
        controller.add_load_more_button.assert_not_called()

    def test_load_more_removes_load_more_row_before_displaying(
        self, pagination_controller, mock_listbox
    ):
        """Test that load_more() removes load_more_row before displaying new entries."""
        entries = [f"entry{i}" for i in range(50)]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 25
        mock_load_more_row = mock.MagicMock()
        pagination_controller._load_more_row = mock_load_more_row

        pagination_controller.load_more()

        # Should have removed the load_more_row
        mock_listbox.remove.assert_called_once_with(mock_load_more_row)
        # load_more_row should be cleared
        assert pagination_controller._load_more_row is None

    def test_load_more_preserves_scroll_position(self, pagination_controller, mock_scrolled_window):
        """Test that load_more() preserves scroll position using GLib.idle_add."""
        entries = [f"entry{i}" for i in range(50)]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 25
        pagination_controller._load_more_row = mock.MagicMock()

        # Mock the vertical adjustment
        mock_vadj = mock.MagicMock()
        mock_vadj.get_value.return_value = 250.5
        mock_scrolled_window.get_vadjustment.return_value = mock_vadj

        pagination_controller.load_more()

        # Should have captured scroll position
        mock_vadj.get_value.assert_called()

        # GLib.idle_add would be called to restore scroll position
        # We can't directly test GLib.idle_add since it's mocked, but we
        # verify the scroll position was captured for restoration

    def test_load_more_with_custom_entries_label(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that load_more() passes custom entries_label to add_load_more_button."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            initial_limit=25,
            batch_size=25,
        )

        # Create 60 entries
        entries = [f"entry{i}" for i in range(60)]
        controller._all_entries = entries
        controller._displayed_count = 25
        controller._load_more_row = mock.MagicMock()

        # Mock add_load_more_button to track calls
        controller.add_load_more_button = mock.MagicMock()

        controller.load_more(entries_label="logs")

        # Should pass custom label
        controller.add_load_more_button.assert_called_once_with("logs")

    def test_load_more_respects_remaining_entries(self, pagination_controller, mock_row_factory):
        """Test that load_more() only displays remaining entries when less than batch_size."""
        # Create 35 entries (25 displayed, 10 remaining - less than batch_size of 25)
        entries = [f"entry{i}" for i in range(35)]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 25
        pagination_controller._load_more_row = mock.MagicMock()

        mock_row_factory.reset_mock()
        pagination_controller.load_more()

        # Should only display 10 remaining entries
        assert mock_row_factory.call_count == 10
        assert pagination_controller._displayed_count == 35

    def test_load_more_uses_entries_to_display_property(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that load_more() uses entries_to_display property (for filtering)."""

        # Create a controller subclass with custom entries_to_display
        class FilteredController(pagination_controller_class):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._filtered_entries = []

            @property
            def entries_to_display(self):
                return self._filtered_entries

        controller = FilteredController(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            batch_size=10,
        )

        # Set filtered entries
        controller._all_entries = [f"entry{i}" for i in range(50)]
        controller._filtered_entries = [f"filtered{i}" for i in range(30)]
        controller._displayed_count = 10
        controller._load_more_row = mock.MagicMock()

        mock_row_factory.reset_mock()
        controller.load_more()

        # Should display next 10 from filtered entries
        assert mock_row_factory.call_count == 10
        for i in range(10, 20):
            mock_row_factory.assert_any_call(f"filtered{i}")

    def test_load_more_button_click_handler(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that _on_load_more_clicked calls load_more() method."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
        )

        # Mock load_more method
        controller.load_more = mock.MagicMock()

        # Simulate button click
        mock_button = mock.MagicMock()
        controller._on_load_more_clicked(mock_button)

        # Should have called load_more
        controller.load_more.assert_called_once()


class TestPaginationControllerShowAll:
    """Tests for show_all() functionality."""

    def test_show_all_displays_all_remaining_entries(self, pagination_controller, mock_row_factory):
        """Test that show_all() displays all remaining entries."""
        # Create 60 entries (25 displayed, 35 remaining)
        entries = [f"entry{i}" for i in range(60)]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 25
        pagination_controller._load_more_row = mock.MagicMock()

        mock_row_factory.reset_mock()
        pagination_controller.show_all()

        # Should display all 35 remaining entries
        assert mock_row_factory.call_count == 35
        assert pagination_controller._displayed_count == 60

    def test_show_all_does_not_readd_button(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that show_all() does not re-add load_more_button."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
            initial_limit=25,
            batch_size=25,
        )

        # Create 60 entries
        entries = [f"entry{i}" for i in range(60)]
        controller._all_entries = entries
        controller._displayed_count = 25
        controller._load_more_row = mock.MagicMock()

        # Mock add_load_more_button to ensure it's not called
        controller.add_load_more_button = mock.MagicMock()

        controller.show_all()

        # Should NOT call add_load_more_button
        controller.add_load_more_button.assert_not_called()

    def test_show_all_removes_load_more_row_before_displaying(
        self, pagination_controller, mock_listbox
    ):
        """Test that show_all() removes load_more_row before displaying new entries."""
        entries = [f"entry{i}" for i in range(50)]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 25
        mock_load_more_row = mock.MagicMock()
        pagination_controller._load_more_row = mock_load_more_row

        pagination_controller.show_all()

        # Should have removed the load_more_row
        mock_listbox.remove.assert_called_once_with(mock_load_more_row)
        # load_more_row should be cleared
        assert pagination_controller._load_more_row is None

    def test_show_all_preserves_scroll_position(self, pagination_controller, mock_scrolled_window):
        """Test that show_all() preserves scroll position using GLib.idle_add."""
        entries = [f"entry{i}" for i in range(50)]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 25
        pagination_controller._load_more_row = mock.MagicMock()

        # Mock the vertical adjustment
        mock_vadj = mock.MagicMock()
        mock_vadj.get_value.return_value = 180.75
        mock_scrolled_window.get_vadjustment.return_value = mock_vadj

        pagination_controller.show_all()

        # Should have captured scroll position
        mock_vadj.get_value.assert_called()

        # GLib.idle_add would be called to restore scroll position
        # We can't directly test GLib.idle_add since it's mocked, but we
        # verify the scroll position was captured for restoration

    def test_show_all_with_no_scrolled_window(
        self, pagination_controller_class, mock_listbox, mock_row_factory
    ):
        """Test that show_all() works when scrolled_window is None."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=None,
            row_factory=mock_row_factory,
        )

        entries = [f"entry{i}" for i in range(50)]
        controller._all_entries = entries
        controller._displayed_count = 25
        controller._load_more_row = mock.MagicMock()

        # Should not raise exception even without scrolled_window
        controller.show_all()

        # Should still display all entries
        assert controller._displayed_count == 50

    def test_show_all_displays_correct_entries(self, pagination_controller, mock_row_factory):
        """Test that show_all() displays the correct remaining entries."""
        entries = [f"entry{i}" for i in range(40)]
        pagination_controller._all_entries = entries
        pagination_controller._displayed_count = 10
        pagination_controller._load_more_row = mock.MagicMock()

        mock_row_factory.reset_mock()
        pagination_controller.show_all()

        # Should display entries 10-39 (30 remaining entries)
        assert mock_row_factory.call_count == 30
        for i in range(10, 40):
            mock_row_factory.assert_any_call(f"entry{i}")

    def test_show_all_uses_entries_to_display_property(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that show_all() uses entries_to_display property (for filtering)."""

        # Create a controller subclass with custom entries_to_display
        class FilteredController(pagination_controller_class):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._filtered_entries = []

            @property
            def entries_to_display(self):
                return self._filtered_entries

        controller = FilteredController(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
        )

        # Set filtered entries
        controller._all_entries = [f"entry{i}" for i in range(50)]
        controller._filtered_entries = [f"filtered{i}" for i in range(30)]
        controller._displayed_count = 10
        controller._load_more_row = mock.MagicMock()

        mock_row_factory.reset_mock()
        controller.show_all()

        # Should display remaining 20 filtered entries
        assert mock_row_factory.call_count == 20
        for i in range(10, 30):
            mock_row_factory.assert_any_call(f"filtered{i}")

    def test_show_all_button_click_handler(
        self, pagination_controller_class, mock_listbox, mock_scrolled_window, mock_row_factory
    ):
        """Test that _on_show_all_clicked calls show_all() method."""
        controller = pagination_controller_class(
            listbox=mock_listbox,
            scrolled_window=mock_scrolled_window,
            row_factory=mock_row_factory,
        )

        # Mock show_all method
        controller.show_all = mock.MagicMock()

        # Simulate button click
        mock_button = mock.MagicMock()
        controller._on_show_all_clicked(mock_button)

        # Should have called show_all
        controller.show_all.assert_called_once()


# Module-level test function for verification
def test_pagination_load_more_show_all_basic(mock_gi_modules):
    """
    Basic test function for load_more and show_all verification.

    This test verifies the load_more and show_all functionality
    using the centralized mock setup.
    """
    from src.ui.pagination import PaginatedListController

    mock_listbox = mock.MagicMock()
    mock_scrolled = mock.MagicMock()
    mock_factory = mock.MagicMock(return_value=mock.MagicMock())

    # Mock vertical adjustment for scroll position
    mock_vadj = mock.MagicMock()
    mock_vadj.get_value.return_value = 100.0
    mock_scrolled.get_vadjustment.return_value = mock_vadj

    controller = PaginatedListController(
        listbox=mock_listbox,
        scrolled_window=mock_scrolled,
        row_factory=mock_factory,
        initial_limit=10,
        batch_size=5,
    )

    # Test 1: load_more displays next batch
    controller._all_entries = [f"entry{i}" for i in range(20)]
    controller._displayed_count = 10
    controller._load_more_row = mock.MagicMock()
    mock_factory.reset_mock()

    controller.load_more()

    assert mock_factory.call_count == 5  # batch_size
    assert controller.displayed_count == 15

    # Test 2: show_all displays all remaining
    controller._displayed_count = 10
    controller._load_more_row = mock.MagicMock()
    mock_factory.reset_mock()

    controller.show_all()

    assert mock_factory.call_count == 10  # All remaining
    assert controller.displayed_count == 20

    # Test 3: Scroll position is captured
    assert mock_vadj.get_value.call_count >= 2  # Called by both methods

    # All tests passed
