# ClamUI Compatibility Module
"""
Factory functions and helpers for libadwaita/GTK compatibility.

Provides drop-in replacements for widgets introduced in libadwaita 1.2-1.4:
- create_entry_row() → replaces Adw.EntryRow (1.2+)
- create_switch_row() → replaces Adw.SwitchRow (1.4+)
- create_toolbar_view() → replaces Adw.ToolbarView (1.4+)
- create_banner() → replaces Adw.Banner (1.3+)

Also provides runtime fallbacks for APIs that are unavailable on Ubuntu 22.04:
- present_about_dialog() → uses Adw.AboutDialog when available, Gtk.AboutDialog otherwise
- open_paths_dialog() → uses Gtk.FileDialog on GTK 4.10+, FileChooserNative otherwise
- save_path_dialog() → uses Gtk.FileDialog on GTK 4.10+, FileChooserNative otherwise

Each factory returns a standard 1.0+ widget with monkey-patched methods
to match the higher-version API surface, so callers can use the same
method names regardless of runtime version.
"""

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from ..core.i18n import _

try:
    _GTK_MINOR_VERSION = Gtk.get_minor_version()
    _HAS_FILE_DIALOG = _GTK_MINOR_VERSION >= 10
except (TypeError, AttributeError):
    _HAS_FILE_DIALOG = False

_NATIVE_DIALOG_REFS: set[object] = set()


def create_entry_row(icon_name: str | None = None) -> Adw.ActionRow:
    """
    Create an entry row compatible with libadwaita 1.0+.

    Replaces Adw.EntryRow (1.2+) with Adw.ActionRow + Gtk.Entry suffix.

    Patched methods: set_text, get_text, set_input_purpose,
    set_show_apply_button, get_delegate, connect (redirects "changed"
    and "entry-activated" signals).

    Args:
        icon_name: Optional prefix icon name (styled with 12px margin, dim-label)

    Returns:
        Adw.ActionRow with entry-row-compatible API
    """
    row = Adw.ActionRow()

    # Add optional prefix icon with GNOME Settings styling
    if icon_name:
        from .utils import resolve_icon_name

        icon = Gtk.Image.new_from_icon_name(resolve_icon_name(icon_name))
        icon.set_margin_start(12)
        icon.add_css_class("dim-label")
        row.add_prefix(icon)

    entry = Gtk.Entry()
    entry.set_valign(Gtk.Align.CENTER)
    entry.set_hexpand(True)
    row.add_suffix(entry)
    row.set_activatable_widget(entry)

    # Store reference for internal use
    row._compat_entry = entry

    # Patch methods
    row.set_text = entry.set_text
    row.get_text = entry.get_text
    row.set_input_purpose = entry.set_input_purpose
    row.set_show_apply_button = lambda val: None  # No-op, not available in 1.0
    row.get_delegate = lambda: entry

    # Patch connect to redirect entry-specific signals
    _original_connect = row.connect

    def _patched_connect(signal_name, callback, *args):
        if signal_name == "changed":
            return entry.connect("changed", lambda e: callback(row), *args)
        if signal_name == "entry-activated":
            return entry.connect("activate", lambda e: callback(row), *args)
        return _original_connect(signal_name, callback, *args)

    row.connect = _patched_connect

    return row


def create_switch_row(icon_name: str | None = None) -> Adw.ActionRow:
    """
    Create a switch row compatible with libadwaita 1.0+.

    Replaces Adw.SwitchRow (1.4+) with Adw.ActionRow + Gtk.Switch suffix.

    Patched methods: set_active, get_active, connect (redirects
    "notify::active" signal).

    Args:
        icon_name: Optional prefix icon name (styled with 12px margin, dim-label)

    Returns:
        Adw.ActionRow with switch-row-compatible API
    """
    row = Adw.ActionRow()

    # Add optional prefix icon with GNOME Settings styling
    if icon_name:
        from .utils import resolve_icon_name

        icon = Gtk.Image.new_from_icon_name(resolve_icon_name(icon_name))
        icon.set_margin_start(12)
        icon.add_css_class("dim-label")
        row.add_prefix(icon)

    switch = Gtk.Switch()
    switch.set_valign(Gtk.Align.CENTER)
    row.add_suffix(switch)
    row.set_activatable_widget(switch)

    # Store reference for internal use
    row._compat_switch = switch

    # Patch methods
    row.set_active = switch.set_active
    row.get_active = switch.get_active

    # Patch connect to redirect switch-specific signals
    _original_connect = row.connect
    _switch_handler_ids = set()

    def _patched_connect(signal_name, callback, *args):
        if signal_name == "notify::active":
            handler_id = switch.connect("notify::active", lambda s, p: callback(row, p), *args)
            _switch_handler_ids.add(handler_id)
            return handler_id
        return _original_connect(signal_name, callback, *args)

    row.connect = _patched_connect

    # Patch handler_block/handler_unblock to forward switch-owned handlers
    _original_handler_block = row.handler_block
    _original_handler_unblock = row.handler_unblock

    def _patched_handler_block(handler_id):
        if handler_id in _switch_handler_ids:
            switch.handler_block(handler_id)
        else:
            _original_handler_block(handler_id)

    def _patched_handler_unblock(handler_id):
        if handler_id in _switch_handler_ids:
            switch.handler_unblock(handler_id)
        else:
            _original_handler_unblock(handler_id)

    row.handler_block = _patched_handler_block
    row.handler_unblock = _patched_handler_unblock

    return row


def create_toolbar_view() -> Gtk.Box:
    """
    Create a toolbar view compatible with libadwaita 1.0+.

    Replaces Adw.ToolbarView (1.4+) with a vertical Gtk.Box.

    Patched methods: add_top_bar (prepend), set_content (append with vexpand).

    Returns:
        Gtk.Box with toolbar-view-compatible API
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

    def _add_top_bar(widget):
        box.prepend(widget)

    def _set_content(widget):
        widget.set_vexpand(True)
        box.append(widget)

    box.add_top_bar = _add_top_bar
    box.set_content = _set_content

    return box


def create_banner() -> Gtk.Revealer:
    """
    Create a banner compatible with libadwaita 1.0+.

    Replaces Adw.Banner (1.3+) with Gtk.Revealer containing a label
    and optional action button.

    Patched methods: set_title, set_revealed, set_button_label,
    connect (redirects "button-clicked" signal).

    Returns:
        Gtk.Revealer with banner-compatible API
    """
    revealer = Gtk.Revealer()
    revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)

    inner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    inner_box.set_margin_start(12)
    inner_box.set_margin_end(12)
    inner_box.set_margin_top(8)
    inner_box.set_margin_bottom(8)
    inner_box.add_css_class("banner")

    label = Gtk.Label()
    label.set_hexpand(True)
    label.set_xalign(0)
    label.set_wrap(True)
    inner_box.append(label)

    button = Gtk.Button()
    button.set_valign(Gtk.Align.CENTER)
    button.set_visible(False)
    inner_box.append(button)

    revealer.set_child(inner_box)

    # Store references
    revealer._compat_label = label
    revealer._compat_button = button

    # Patch methods
    revealer.set_title = label.set_text

    def _set_revealed(val):
        revealer.set_reveal_child(val)

    revealer.set_revealed = _set_revealed

    def _set_button_label(text):
        button.set_label(text)
        button.set_visible(bool(text))

    revealer.set_button_label = _set_button_label

    # Patch connect to redirect banner-specific signals
    _original_connect = revealer.connect

    def _patched_connect(signal_name, callback, *args):
        if signal_name == "button-clicked":
            return button.connect("clicked", lambda b: callback(revealer), *args)
        return _original_connect(signal_name, callback, *args)

    revealer.connect = _patched_connect

    return revealer


def present_about_dialog(
    parent: Gtk.Window | None,
    *,
    app_name: str,
    version: str,
    developer_name: str | None = None,
    comments: str | None = None,
    website: str | None = None,
    issue_url: str | None = None,
    icon_name: str | None = None,
    license_type=None,
):
    """
    Present an about dialog using the newest supported API at runtime.

    Ubuntu 22.04 ships libadwaita 1.1.x, which does not provide
    Adw.AboutDialog. Fall back to Gtk.AboutDialog on older runtimes.
    """
    if hasattr(Adw, "AboutDialog"):
        about = Adw.AboutDialog()
        about.set_application_name(app_name)
        about.set_version(version)
        if developer_name:
            about.set_developer_name(developer_name)
        if license_type is not None:
            about.set_license_type(license_type)
        if comments:
            about.set_comments(comments)
        if website:
            about.set_website(website)
        if issue_url and hasattr(about, "set_issue_url"):
            about.set_issue_url(issue_url)
        if icon_name:
            about.set_application_icon(icon_name)
        if parent is not None:
            about.present(parent)
        else:
            about.present()
        return about

    about = Gtk.AboutDialog()
    if hasattr(about, "set_program_name"):
        about.set_program_name(app_name)
    elif hasattr(about, "set_application_name"):
        about.set_application_name(app_name)
    if hasattr(about, "set_version"):
        about.set_version(version)
    if developer_name:
        if hasattr(about, "set_authors"):
            about.set_authors([developer_name])
        elif hasattr(about, "set_developers"):
            about.set_developers([developer_name])
    if license_type is not None and hasattr(about, "set_license_type"):
        about.set_license_type(license_type)
    if comments and hasattr(about, "set_comments"):
        about.set_comments(comments)
    if website and hasattr(about, "set_website"):
        about.set_website(website)
    if icon_name:
        if hasattr(about, "set_logo_icon_name"):
            about.set_logo_icon_name(icon_name)
        elif hasattr(about, "set_application_icon"):
            about.set_application_icon(icon_name)
    if parent is not None and hasattr(about, "set_transient_for"):
        about.set_transient_for(parent)
    if parent is not None and hasattr(about, "set_modal"):
        about.set_modal(True)
    about.present()
    return about


def _create_filter_store(filters: list[Gtk.FileFilter] | None):
    if not filters:
        return None

    filter_store = Gio.ListStore.new(Gtk.FileFilter)
    for gtk_filter in filters:
        filter_store.append(gtk_filter)
    return filter_store


def _paths_from_list_model(files) -> list[str]:
    paths: list[str] = []
    if files is None:
        return paths

    for index in range(files.get_n_items()):
        file = files.get_item(index)
        if file is None:
            continue
        path = file.get_path()
        if path:
            paths.append(path)
    return paths


def open_paths_dialog(
    parent: Gtk.Window | None,
    *,
    title: str,
    on_selected: Callable[[list[str]], None],
    select_folders: bool = False,
    multiple: bool = False,
    initial_folder: Gio.File | None = None,
    filters: list[Gtk.FileFilter] | None = None,
):
    """
    Open a file or folder picker compatible with GTK 4.6+.

    Calls ``on_selected`` with a list of filesystem paths. The callback is not
    invoked when the dialog is dismissed or no local paths are returned.
    """

    def _emit_paths(paths: list[str]) -> None:
        if paths:
            on_selected(paths)

    if _HAS_FILE_DIALOG:
        dialog = Gtk.FileDialog()
        dialog.set_title(title)
        if initial_folder is not None:
            dialog.set_initial_folder(initial_folder)

        filter_store = _create_filter_store(filters)
        if filter_store is not None:
            dialog.set_filters(filter_store)
            dialog.set_default_filter(filters[0])

        def _on_finish(dlg, result):
            try:
                if select_folders and multiple:
                    files = dlg.select_multiple_folders_finish(result)
                    _emit_paths(_paths_from_list_model(files))
                elif select_folders:
                    file = dlg.select_folder_finish(result)
                    _emit_paths([file.get_path()] if file and file.get_path() else [])
                elif multiple:
                    files = dlg.open_multiple_finish(result)
                    _emit_paths(_paths_from_list_model(files))
                else:
                    file = dlg.open_finish(result)
                    _emit_paths([file.get_path()] if file and file.get_path() else [])
            except GLib.Error:
                return

        if select_folders and multiple:
            dialog.select_multiple_folders(parent, None, _on_finish)
        elif select_folders:
            dialog.select_folder(parent, None, _on_finish)
        elif multiple:
            dialog.open_multiple(parent, None, _on_finish)
        else:
            dialog.open(parent, None, _on_finish)

        return dialog

    action = Gtk.FileChooserAction.SELECT_FOLDER if select_folders else Gtk.FileChooserAction.OPEN
    dialog = Gtk.FileChooserNative.new(
        title,
        parent,
        action,
        _("_Open"),
        _("_Cancel"),
    )
    dialog.set_select_multiple(multiple)
    if initial_folder is not None:
        dialog.set_current_folder(initial_folder)
    for gtk_filter in filters or []:
        dialog.add_filter(gtk_filter)

    _NATIVE_DIALOG_REFS.add(dialog)

    def _on_response(dlg, response):
        try:
            if response == Gtk.ResponseType.ACCEPT:
                if multiple:
                    _emit_paths(_paths_from_list_model(dlg.get_files()))
                else:
                    file = dlg.get_file()
                    _emit_paths([file.get_path()] if file and file.get_path() else [])
        finally:
            _NATIVE_DIALOG_REFS.discard(dlg)

    dialog.connect("response", _on_response)
    dialog.show()
    return dialog


def save_path_dialog(
    parent: Gtk.Window | None,
    *,
    title: str,
    on_selected: Callable[[str], None],
    initial_name: str | None = None,
    filters: list[Gtk.FileFilter] | None = None,
):
    """Open a save dialog compatible with GTK 4.6+."""

    if _HAS_FILE_DIALOG:
        dialog = Gtk.FileDialog()
        dialog.set_title(title)
        if initial_name:
            dialog.set_initial_name(initial_name)

        filter_store = _create_filter_store(filters)
        if filter_store is not None:
            dialog.set_filters(filter_store)
            dialog.set_default_filter(filters[0])

        def _on_finish(dlg, result):
            try:
                file = dlg.save_finish(result)
                if file is None:
                    return
                path = file.get_path()
                if path:
                    on_selected(path)
            except GLib.Error:
                return

        dialog.save(parent, None, _on_finish)
        return dialog

    dialog = Gtk.FileChooserNative.new(
        title,
        parent,
        Gtk.FileChooserAction.SAVE,
        _("_Save"),
        _("_Cancel"),
    )
    if initial_name:
        dialog.set_current_name(initial_name)
    for gtk_filter in filters or []:
        dialog.add_filter(gtk_filter)

    _NATIVE_DIALOG_REFS.add(dialog)

    def _on_response(dlg, response):
        try:
            if response == Gtk.ResponseType.ACCEPT:
                file = dlg.get_file()
                if file is None:
                    return
                path = file.get_path()
                if path:
                    on_selected(path)
        finally:
            _NATIVE_DIALOG_REFS.discard(dlg)

    dialog.connect("response", _on_response)
    dialog.show()
    return dialog


# --- Safe method helpers for optional 1.2+/1.3+ methods ---


def safe_add_suffix(row, widget) -> None:
    """Call add_suffix if available, fall back to add_prefix.

    Adw.ActionRow has add_suffix since 1.0, but Adw.ExpanderRow only gained
    it in a later release.  On older libadwaita the widget is placed as a
    prefix instead so the information is still visible.
    """
    if hasattr(row, "add_suffix"):
        row.add_suffix(widget)
    elif hasattr(row, "add_prefix"):
        row.add_prefix(widget)


def safe_add_titled_with_icon(stack, child, name: str, title: str, icon_name: str):
    """Call add_titled_with_icon if available (libadwaita 1.2+).

    Falls back to add_titled() + page.set_icon_name() on older versions.
    """
    if hasattr(stack, "add_titled_with_icon"):
        return stack.add_titled_with_icon(child, name, title, icon_name)
    page = stack.add_titled(child, name, title)
    page.set_icon_name(icon_name)
    return page


def safe_set_subtitle_selectable(row, value: bool) -> None:
    """Call set_subtitle_selectable if available (libadwaita 1.3+)."""
    if hasattr(row, "set_subtitle_selectable"):
        row.set_subtitle_selectable(value)


def safe_set_title_lines(row, value: int) -> None:
    """Call set_title_lines if available (libadwaita 1.2+)."""
    if hasattr(row, "set_title_lines"):
        row.set_title_lines(value)


def safe_set_subtitle_lines(row, value: int) -> None:
    """Call set_subtitle_lines if available (libadwaita 1.2+)."""
    if hasattr(row, "set_subtitle_lines"):
        row.set_subtitle_lines(value)


def remove_all_children(listbox) -> None:
    """Remove every row from a Gtk.ListBox.

    Gtk.ListBox.remove_all() only exists on GTK 4.12+; iterate manually so
    the code works on the GTK 4.6 baseline (Ubuntu 22.04).
    """
    if hasattr(listbox, "remove_all"):
        listbox.remove_all()
        return
    while True:
        child = listbox.get_first_child()
        if child is None:
            break
        listbox.remove(child)


def safe_set_placeholder_text(entry, text: str) -> None:
    """Set placeholder text on a Gtk.SearchEntry if supported.

    Gtk.SearchEntry gained the placeholder-text property (and its
    set_placeholder_text accessor) in GTK 4.10; on older versions setting
    the property raises TypeError, so skip it entirely.
    """
    if hasattr(entry, "set_placeholder_text"):
        entry.set_placeholder_text(text)
