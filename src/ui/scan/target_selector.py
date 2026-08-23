# Target Selector Component
"""
Target selector widget for scan paths.

Single responsibility:
- File/folder selection via native dialogs
- Drag-and-drop support
- Multi-path management with add/remove
"""

import os
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GObject, Gtk, Pango

from ...core.i18n import _
from ...core.utils import format_scan_path, validate_dropped_files
from ..compat import open_paths_dialog
from ..utils import resolve_icon_name


class PathRow(Gtk.ListBoxRow):
    """A single path entry with remove button."""

    def __init__(self, path: str, on_remove: Callable[[str], None]):
        super().__init__()
        self.path = path
        self._on_remove = on_remove

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        is_dir = Path(path).is_dir()
        icon_name = "folder-symbolic" if is_dir else "text-x-generic-symbolic"
        icon = Gtk.Image.new_from_icon_name(resolve_icon_name(icon_name))
        box.append(icon)

        label = Gtk.Label(label=format_scan_path(path))
        label.set_hexpand(True)
        label.set_xalign(0)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        label.set_tooltip_text(path)
        box.append(label)

        remove_btn = Gtk.Button()
        remove_btn.set_icon_name(resolve_icon_name("window-close-symbolic"))
        remove_btn.add_css_class("flat")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.set_tooltip_text(_("Remove target"))
        remove_btn.update_property([Gtk.AccessibleProperty.LABEL], [_("Remove target")])
        remove_btn.connect("clicked", self._on_remove_clicked)
        box.append(remove_btn)

        self.set_child(box)

    def _on_remove_clicked(self, button):
        self._on_remove(self.path)


class TargetSelector(Adw.PreferencesGroup):
    """
    Widget for selecting scan targets (files/folders).

    Signals:
        targets-changed: Emitted when target list changes (paths: list[str])
    """

    def __init__(self, is_scanning: Callable[[], bool] = lambda: False):
        super().__init__()
        self.set_title(_("Scan Targets"))
        self.set_description(_("Drop files here or click Add"))

        self._paths: list[str] = []
        self._normalized: set[str] = set()
        self._is_scanning = is_scanning

        self._setup_ui()
        self._setup_drop_target()

    def _setup_ui(self):
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_halign(Gtk.Align.END)

        self._add_files_btn = Gtk.Button()
        self._add_files_btn.set_icon_name(resolve_icon_name("document-new-symbolic"))
        self._add_files_btn.set_tooltip_text(_("Add files"))
        self._add_files_btn.add_css_class("flat")
        self._add_files_btn.connect("clicked", self._on_add_files)
        header_box.append(self._add_files_btn)

        self._add_folders_btn = Gtk.Button()
        self._add_folders_btn.set_icon_name(resolve_icon_name("folder-new-symbolic"))
        self._add_folders_btn.set_tooltip_text(_("Add folders"))
        self._add_folders_btn.add_css_class("flat")
        self._add_folders_btn.connect("clicked", self._on_add_folders)
        header_box.append(self._add_folders_btn)

        self._clear_btn = Gtk.Button()
        self._clear_btn.set_label(_("Clear All"))
        self._clear_btn.add_css_class("flat")
        self._clear_btn.set_visible(False)
        self._clear_btn.connect("clicked", self._on_clear_all)
        header_box.append(self._clear_btn)

        self.set_header_suffix(header_box)

        self._listbox = Gtk.ListBox()
        self._listbox.add_css_class("boxed-list")
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.add(self._listbox)

        self._placeholder = Gtk.Label(label=_("No targets selected"))
        self._placeholder.add_css_class("dim-label")
        self._placeholder.set_margin_top(12)
        self._placeholder.set_margin_bottom(12)
        self._listbox.append(self._placeholder)

    def _setup_drop_target(self):
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        drop.connect("enter", lambda *args: Gdk.DragAction.COPY)
        drop.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(drop)

    def _on_drop(self, target, value, x, y) -> bool:
        if self._is_scanning():
            self._show_error(_("Cannot add targets while scanning"))
            return False

        files = value.get_files()
        paths = [f.get_path() for f in files if f.get_path()]
        valid, errors = validate_dropped_files(paths)

        for p in valid:
            self.add_path(p)

        if errors and not valid:
            self._show_error(errors[0])

        return len(valid) > 0

    def _on_add_files(self, button):
        self._show_file_dialog(select_folders=False)

    def _on_add_folders(self, button):
        self._show_file_dialog(select_folders=True)

    def _show_file_dialog(self, select_folders: bool):
        open_paths_dialog(
            self.get_root(),
            title=_("Select Folders") if select_folders else _("Select Files"),
            on_selected=self._add_dialog_paths,
            select_folders=select_folders,
            multiple=True,
        )

    def _add_dialog_paths(self, paths: list[str]) -> None:
        """Add paths selected through the file chooser dialog."""
        for path in paths:
            if path:
                self.add_path(path)

    def add_path(self, path: str) -> bool:
        normalized = os.path.normpath(path)
        if normalized in self._normalized:
            return False

        self._normalized.add(normalized)
        self._paths.append(path)

        self._placeholder.set_visible(False)
        row = PathRow(path, self.remove_path)
        self._listbox.append(row)

        self._update_ui()
        self.emit("targets-changed", self._paths.copy())
        return True

    def remove_path(self, path: str) -> bool:
        normalized = os.path.normpath(path)
        if normalized not in self._normalized:
            return False

        self._normalized.discard(normalized)
        self._paths = [p for p in self._paths if os.path.normpath(p) != normalized]

        child = self._listbox.get_first_child()
        while child:
            if hasattr(child, "path") and os.path.normpath(child.path) == normalized:
                self._listbox.remove(child)
                break
            child = child.get_next_sibling()

        self._placeholder.set_visible(len(self._paths) == 0)
        self._update_ui()
        self.emit("targets-changed", self._paths.copy())
        return True

    def set_paths(self, paths: list[str]):
        self.clear()
        for p in paths:
            self.add_path(p)

    def clear(self):
        self._paths.clear()
        self._normalized.clear()

        child = self._listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            if child != self._placeholder:
                self._listbox.remove(child)
            child = next_child

        self._placeholder.set_visible(True)
        self._update_ui()
        self.emit("targets-changed", [])

    def _on_clear_all(self, button):
        self.clear()

    def _update_ui(self):
        count = len(self._paths)
        if count == 0:
            self.set_title(_("Scan Targets"))
            self.set_description(_("Drop files here or click Add"))
        elif count == 1:
            self.set_title(_("Scan Target (1)"))
            self.set_description("")
        else:
            self.set_title(_("Scan Targets ({count})").format(count=count))
            self.set_description("")

        self._clear_btn.set_visible(count > 1)

    def _show_error(self, message: str):
        root = self.get_root()
        if root and hasattr(root, "add_toast"):
            root.add_toast(Adw.Toast.new(message))

    @property
    def paths(self) -> list[str]:
        return self._paths.copy()


GObject.type_register(TargetSelector)
GObject.signal_new(
    "targets-changed", TargetSelector, GObject.SignalFlags.RUN_FIRST, None, (object,)
)
