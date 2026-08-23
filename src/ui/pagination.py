# ClamUI Pagination Controller
"""
Reusable pagination controller for GTK4 ListBox widgets.

Provides a generic pagination system with configurable batch sizes, scroll position
management, and 'Show More'/'Show All' button controls. Used to paginate large
lists of entries in logs_view.py and quarantine_view.py.
"""

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from ..core.i18n import _


class PaginatedListController:
    """
    Controller for paginating entries in a GTK ListBox.

    Manages pagination state, batch display, and 'Show More'/'Show All' controls
    for large lists. Accepts a row_factory callback to create view-specific rows.

    The controller is designed to be flexible:
    - Subclasses can override entries_to_display for filtering support
    - The row_factory callback enables view-specific row creation
    - Configurable initial_limit and batch_size for different use cases
    """

    # Default pagination thresholds
    DEFAULT_INITIAL_LIMIT = 25
    DEFAULT_BATCH_SIZE = 25

    def __init__(
        self,
        listbox: Gtk.ListBox,
        scrolled_window: Gtk.ScrolledWindow,
        row_factory: Callable,
        initial_limit: int = DEFAULT_INITIAL_LIMIT,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        """
        Initialize the pagination controller.

        Args:
            listbox: The GTK ListBox to paginate
            scrolled_window: The ScrolledWindow containing the listbox (for scroll position)
            row_factory: Callback function to create a row widget from an entry.
                         Should accept an entry object and return a Gtk.Widget.
            initial_limit: Number of entries to display initially (default: 25)
            batch_size: Number of entries to display per "Show More" batch (default: 25)
        """
        self._listbox = listbox
        self._scrolled_window = scrolled_window
        self._row_factory = row_factory
        self._initial_limit = initial_limit
        self._batch_size = batch_size

        # Pagination state
        self._displayed_count: int = 0
        self._all_entries: list = []
        self._load_more_row: Gtk.ListBoxRow | None = None

    @property
    def displayed_count(self) -> int:
        """
        Get the number of currently displayed entries.

        Returns:
            Number of entries currently shown in the listbox
        """
        return self._displayed_count

    @property
    def all_entries(self) -> list:
        """
        Get all entries managed by this controller.

        Returns:
            List of all entries
        """
        return self._all_entries

    @property
    def load_more_row(self) -> Gtk.ListBoxRow | None:
        """
        Get the current 'Load More' button row.

        Returns:
            The ListBoxRow containing Load More buttons, or None if not displayed
        """
        return self._load_more_row

    @property
    def entries_to_display(self) -> list:
        """
        Get the entries that should be displayed.

        By default, returns all_entries. Subclasses or views can override this
        property to provide filtered lists (e.g., for search functionality).

        Returns:
            List of entries to display (may be filtered)
        """
        return self._all_entries

    def reset_state(self):
        """
        Reset pagination state to initial values.

        Clears displayed_count, all_entries, and load_more_row.
        Does not modify the listbox itself.
        """
        self._displayed_count = 0
        self._all_entries = []
        self._load_more_row = None

    def display_batch(self, start_index: int, count: int):
        """
        Display a batch of entry rows starting from the given index.

        Creates rows using the row_factory callback and inserts them into the
        listbox. If load_more_row exists, new rows are inserted before it.
        Otherwise, rows are appended to the end of the listbox.

        Gracefully handles exceptions from row_factory by skipping failed entries
        and logging warnings.

        Args:
            start_index: Index in entries_to_display to start from
            count: Number of entries to display
        """
        entries = self.entries_to_display
        end_index = min(start_index + count, len(entries))

        for i in range(start_index, end_index):
            entry = entries[i]
            try:
                row = self._row_factory(entry)
                # Insert before the "Load More" button if it exists
                if self._load_more_row:
                    self._listbox.insert(row, self._displayed_count)
                else:
                    self._listbox.append(row)
                self._displayed_count += 1
            except Exception:
                # Skip entries that fail to render (corrupted data)
                continue

    def add_load_more_button(self, entries_label: str | None = None):
        """
        Add a 'Show More' and 'Show All' button row to the listbox.

        Creates a row with:
        - Progress label showing "Showing X of Y [entries_label]"
        - "Show More" button to load next batch_size entries
        - "Show All" button (only if remaining > batch_size)

        Both buttons have the 'pill' CSS class for consistent styling.

        Args:
            entries_label: Label for the items being paginated (e.g., "entries",
                          "logs", "filtered entries"). Used in progress text.
        """
        if entries_label is None:
            entries_label = _("entries")

        load_more_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        load_more_box.set_halign(Gtk.Align.CENTER)
        load_more_box.set_margin_top(12)
        load_more_box.set_margin_bottom(12)

        # Get the appropriate entry list
        entries = self.entries_to_display

        # Progress label
        remaining = len(entries) - self._displayed_count
        progress_label = Gtk.Label()
        progress_text = _("Showing {displayed} of {total} {label}").format(
            displayed=self._displayed_count,
            total=len(entries),
            label=entries_label,
        )
        progress_label.set_markup(f"<span size='small'>{progress_text}</span>")
        progress_label.add_css_class("dim-label")
        load_more_box.append(progress_label)

        # Button row
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.CENTER)

        # "Show More" button
        show_more_btn = Gtk.Button()
        show_more_btn.set_label(
            _("Show {count} More").format(count=min(self._batch_size, remaining))
        )
        show_more_btn.add_css_class("pill")
        show_more_btn.connect("clicked", self._on_load_more_clicked)
        button_box.append(show_more_btn)

        # "Show All" button (only if many remaining)
        if remaining > self._batch_size:
            show_all_btn = Gtk.Button()
            show_all_btn.set_label(
                _("Show All ({remaining} remaining)").format(remaining=remaining)
            )
            show_all_btn.add_css_class("pill")
            show_all_btn.connect("clicked", self._on_show_all_clicked)
            button_box.append(show_all_btn)

        load_more_box.append(button_box)

        # Wrap in ListBoxRow to ensure proper parent-child relationship
        load_more_row = Gtk.ListBoxRow()
        load_more_row.set_child(load_more_box)
        load_more_row.set_activatable(False)
        load_more_row.set_selectable(False)
        self._load_more_row = load_more_row
        self._listbox.append(load_more_row)

    def load_more(self, entries_label: str | None = None):
        """
        Load and display the next batch of entries.

        Handles 'Show More' button click:
        1. Preserves current scroll position
        2. Removes the load_more_row
        3. Displays the next batch_size entries
        4. Re-adds load_more_button if more entries remain
        5. Restores scroll position after layout

        Args:
            entries_label: Label for progress text (e.g., "entries", "logs")
        """
        # Preserve scroll position
        scroll_pos = None
        if self._scrolled_window:
            vadj = self._scrolled_window.get_vadjustment()
            scroll_pos = vadj.get_value()

        if self._load_more_row:
            self._listbox.remove(self._load_more_row)
            self._load_more_row = None

        entries = self.entries_to_display
        remaining = len(entries) - self._displayed_count
        batch_size = min(self._batch_size, remaining)
        self.display_batch(self._displayed_count, batch_size)

        if self._displayed_count < len(entries):
            self.add_load_more_button(entries_label)

        # Restore scroll position after layout
        if scroll_pos is not None:
            # Explicitly return False to remove callback after execution
            GLib.idle_add(lambda: (vadj.set_value(scroll_pos), False)[1])

    def show_all(self):
        """
        Load and display all remaining entries.

        Handles 'Show All' button click:
        1. Preserves current scroll position
        2. Removes the load_more_row
        3. Displays all remaining entries
        4. Restores scroll position after layout

        Does not re-add load_more_button since all entries are now displayed.
        """
        # Preserve scroll position
        scroll_pos = None
        if self._scrolled_window:
            vadj = self._scrolled_window.get_vadjustment()
            scroll_pos = vadj.get_value()

        if self._load_more_row:
            self._listbox.remove(self._load_more_row)
            self._load_more_row = None

        entries = self.entries_to_display
        remaining = len(entries) - self._displayed_count
        self.display_batch(self._displayed_count, remaining)

        # Restore scroll position after layout
        if scroll_pos is not None:
            # Explicitly return False to remove callback after execution
            GLib.idle_add(lambda: (vadj.set_value(scroll_pos), False)[1])

    def set_entries(self, entries: list, entries_label: str | None = None):
        """
        Set entries and display initial batch with pagination.

        This is the main entry point for loading new data. It:
        1. Clears the listbox
        2. Resets pagination state
        3. Stores the entries
        4. Displays the initial batch (up to initial_limit)
        5. Adds load_more_button if entries exceed initial_limit

        Args:
            entries: List of entry objects to paginate
            entries_label: Label for progress text (e.g., "entries", "logs")
        """
        # Clear existing rows (compatible with all GTK4 versions)
        while True:
            child = self._listbox.get_first_child()
            if child is None:
                break
            self._listbox.remove(child)

        # Reset pagination state
        self._all_entries = entries
        self._displayed_count = 0
        self._load_more_row = None

        # Handle empty entries - placeholder will be shown automatically
        if not entries:
            return

        # Display initial batch with pagination. Base decisions on the entries
        # that will actually be displayed (entries_to_display), not the raw
        # backing list: a subclass may override entries_to_display() to return
        # a filtered subset. Using len(entries) here would add a bogus
        # "Load More" button (e.g. "Show 0 More") and suppress the no-results
        # placeholder whenever a filter narrows the list below the initial limit.
        display_entries = self.entries_to_display
        initial_limit = min(self._initial_limit, len(display_entries))
        self.display_batch(0, initial_limit)

        # Add "Load More" button only if more displayable entries remain
        if len(display_entries) > self._initial_limit:
            self.add_load_more_button(entries_label)

    def _on_load_more_clicked(self, button):
        """
        Internal handler for 'Show More' button click.

        Delegates to load_more() method. Uses default entries_label.

        Args:
            button: The button that was clicked
        """
        self.load_more()

    def _on_show_all_clicked(self, button):
        """
        Internal handler for 'Show All' button click.

        Delegates to show_all() method.

        Args:
            button: The button that was clicked
        """
        self.show_all()
