# ui/ - GTK4/Adwaita UI Layer

Parent: [`../../AGENTS.md`](../../AGENTS.md) | Subguides:
[`scan/AGENTS.md`](scan/AGENTS.md), [`preferences/AGENTS.md`](preferences/AGENTS.md)

The root guide owns package-import, i18n, thread-safety, and runtime-baseline
rules. Keep UI code compatible with that baseline; do not duplicate runtime pins
here.

## Routing and ownership

- `src/app.py` owns `ClamUIApp` lifecycle, lazy view instances, and the active
  view name. On first activation it creates `MainWindow`, installs
  `src/ui/scan_view.py:ScanView`, and selects `scan`.
- `window.py` owns the adaptive shell. Its sidebar callback activates
  `app.show-<view-id>`; `set_content_view()` replaces the displayed widget and
  `set_active_view()` synchronizes sidebar selection and the folded-window title.
- `sidebar.py` is the navigation-item source. `src/view_coordinator.py` registers
  the matching application actions and shortcuts; the corresponding handlers in
  `src/app.py` obtain the lazy view and update the window.
- Add a routed view by changing all three of those routing seams and adding the
  lazy property/handler in `src/app.py`. Keep the sidebar ID and
  `show-<view-id>` action aligned.

There are two `ViewCoordinator` implementations with different roles:

- `src/view_coordinator.py:ViewCoordinator` is the coordinator constructed by
  `ClamUIApp`. It registers actions, switches a supplied widget into the active
  window, and provides the statistics quick-scan route.
- `src/ui/coordinator.py:ViewCoordinator` is an AppContext-oriented view cache
  with `switch_to(view_name, window)`. It manages its own supported view set and
  is not constructed by the current `ClamUIApp` route. Do not add a second live
  routing path without a complete cutover.

## UI map

- `scan_view.py` is the active scan screen. See `scan/AGENTS.md` before changing
  the unintegrated modular scan package.
- `window.py` and `sidebar.py` implement navigation; `compat.py`,
  `view_helpers.py`, `utils.py`, `pagination.py`, and `file_export.py` provide
  shared UI behavior.
- `*_view.py` modules provide individual content screens; `*_dialog.py` modules
  provide dialogs. `preferences/` owns the settings window and pages.
- Tray modules use the tray subprocess boundary described by the root guide.

## Compatibility helpers

Use these helpers when the corresponding newer API is needed:

| Helper | Compatibility target |
|---|---|
| `create_entry_row(icon_name=None)` | `Adw.EntryRow` (1.2+) |
| `create_switch_row(icon_name=None)` | `Adw.SwitchRow` (1.4+) |
| `create_toolbar_view()` | `Adw.ToolbarView` (1.4+) |
| `create_banner()` | `Adw.Banner` (1.3+) |
| `present_about_dialog(parent, *, app_name, version, ...)` | `Adw.AboutDialog` (1.5+), with a `Gtk.AboutDialog` fallback |
| `open_paths_dialog(parent, *, title, on_selected, select_folders=False, multiple=False, initial_folder=None, filters=None)` | `Gtk.FileDialog` (GTK 4.10+), with a native chooser fallback |
| `save_path_dialog(parent, *, title, on_selected, initial_name=None, filters=None)` | `Gtk.FileDialog` saving, with a native chooser fallback |

The row, toolbar, and banner factories expose only the compatibility methods
implemented in `compat.py`; do not treat their returned base widgets as complete
replacements for every newer-widget API. Use the `safe_*` helpers in that module
for optional row, stack, and list APIs.

For a new modal dialog, use the compatible `Adw.Window` pattern:
`set_default_size()`, `set_transient_for()`, `set_content()`, and the
`close-request` signal. Build its header/content with `create_toolbar_view()`;
do not introduce `Adw.Dialog`-family APIs.

## Shared UI helpers

- `create_empty_state(EmptyStateConfig(...))` creates a placeholder box.
- `LoadingStateController(spinner, buttons, extra_buttons=None).set_loading(...)`
  keeps the spinner and related controls synchronized.
- `create_header_button_box(buttons, spacing=6, include_spinner=False)` returns
  `(header_box, spinner_or_none)`.
- `set_status_class(widget, StatusLevel)` applies one semantic status CSS class.
- Resolve themed icon names through `resolve_icon_name()` before assigning an
  icon to a widget.

## Async UI contract

Run slow work off the GTK main loop. Schedule every GTK mutation made from a
worker with `GLib.idle_add()`, including completion and error cleanup. Restore
the affected controls on every terminal path so no spinner or disabled control
is left behind.