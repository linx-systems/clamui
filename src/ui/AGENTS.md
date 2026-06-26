# ui/ — GTK4/Adwaita UI Layer

30 modules + 2 subpackages (scan/, preferences/). Depends on `core/` for business logic. (`app.py`, `notification_dispatcher.py`, `app_lifecycle.py` live at src/ root, not here.)

Parent: [`../../AGENTS.md`](../../AGENTS.md) | Subs: [`scan/AGENTS.md`](scan/AGENTS.md), [`preferences/AGENTS.md`](preferences/AGENTS.md)

## Structure

```
ui/
├── window.py              # Main window — sidebar nav, content switching
├── sidebar.py             # NavigationSidebar — 7 nav items
├── coordinator.py         # View lifecycle — lazy loading, view switching
├── scan_view.py           # Legacy scan view (being replaced by scan/)
├── logs_view.py           # Scan history with pagination + daemon mode
├── quarantine_view.py     # Quarantine management with search
├── statistics_view.py     # Statistics dashboard (matplotlib)
├── components_view.py     # ClamAV component status checker
├── update_view.py         # Database update interface
├── audit_view.py          # Security audit dashboard (Tier1/Tier2)
├── compat.py              # libadwaita 1.0+ compatibility factories
├── view_helpers.py        # Shared patterns (empty state, loading, status)
├── utils.py               # resolve_icon_name(), present_dialog()
├── pagination.py          # PaginatedListController for large lists
├── file_export.py         # FileExportHelper (CSV/JSON/TEXT)
├── clipboard_helper.py    # Clipboard operations
├── eicar_helper.py        # EICAR test-file helper
├── scan_results_dialog.py # Results dialog with quarantine actions
├── scan_in_progress_dialog.py      # Active-scan blocking dialog
├── database_missing_dialog.py      # Missing DB prompt
├── close_behavior_dialog.py        # Close-to-tray vs quit choice
├── file_manager_integration_dialog.py  # Nemo/Nautilus install dialog
├── fullscreen_dialog.py            # Fullscreen log viewer
├── profile_dialogs.py     # Profile create/edit/import/export dialogs
├── virustotal_*.py        # VirusTotal results + setup dialogs
├── tray_manager.py        # System tray subprocess launcher
├── tray_service.py        # Tray D-Bus service (GIO, runs in subprocess)
├── tray_indicator.py      # Low-level SNI tray widget
├── tray_icons.py          # Tray icon management
├── scan/                  # Modular scan workflow → scan/AGENTS.md
└── preferences/           # Settings pages → preferences/AGENTS.md
```

## Key Patterns

### Compatibility Layer (`compat.py`) — USE THESE, NOT RAW WIDGETS

| Factory | Replaces | Version |
|---------|----------|---------|
| `create_entry_row()` | `Adw.EntryRow` | 1.2+ |
| `create_switch_row()` | `Adw.SwitchRow` | 1.4+ |
| `create_toolbar_view()` | `Adw.ToolbarView` | 1.4+ |
| `create_banner()` | `Adw.Banner` | 1.3+ |
| `present_about_dialog()` | `Adw.AboutDialog` (→ `Gtk.AboutDialog`) | 1.2+ |
| `open_paths_dialog()` / `save_path_dialog()` | `Gtk.FileDialog` (→ `Gtk.FileChooserNative`) | GTK 4.10+ |

Factory functions monkey-patch method APIs to match higher-version signatures. Callers use identical methods regardless of runtime libadwaita version.

### View Helpers (`view_helpers.py`) — ALWAYS USE THESE

- `create_empty_state(EmptyStateConfig(...))` — placeholder for empty lists
- `LoadingStateController` — spinner + button sensitivity management
- `create_header_button_box(buttons=[...])` — consistent header layouts
- `set_status_class(widget, StatusLevel.SUCCESS)` — semantic CSS class management

### Dialog Pattern (ALL dialogs inherit `Adw.Window`)
```python
class MyDialog(Adw.Window):
    def __init__(self, parent=None):
        super().__init__(title=_("Title"), modal=True, deletable=True)
        self.set_default_size(400, 300)
        if parent:
            self.set_transient_for(parent)
        toolbar_view = create_toolbar_view()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        toolbar_view.set_content(content)
        self.set_content(toolbar_view)
```

### Thread Safety
```python
# Background work → GLib.idle_add for UI update
def _do_background():
    result = expensive_operation()
    GLib.idle_add(self._update_ui, result)

threading.Thread(target=_do_background, daemon=True).start()
```

**Always reset loading state in `finally` blocks** — prevents stuck spinners.

### View Lifecycle — TWO coordinators
- **`src/ui/coordinator.py`** (`ViewCoordinator`, UI-scoped): lazy-loads & caches 6 content views via `@property` (`_scan_view` etc.); switched via `switch_to(view_name, window)`. Views: scan, update, logs, components, statistics, quarantine.
- **`src/view_coordinator.py`** (`ViewCoordinator`, app-level): `setup_actions()` registers actions+accels, `switch_to_view(name, widget)`, `get_current_view()`.

The sidebar (`sidebar.py`, `NAVIGATION_ITEMS`) exposes **7** destinations: scan, update, logs, components, quarantine, statistics, audit. `audit_view` (AuditView) is instantiated directly, NOT via the lazy `ui/coordinator.py`.

## Where to Look

| Task | Module | Notes |
|------|--------|-------|
| Add a view | `sidebar.py` (`NAVIGATION_ITEMS`) + `view_coordinator.py` (`setup_actions`) + `app.py` (lazy `@property`) | Register nav item, action, and view property |
| Add a dialog | Inherit `Adw.Window` | Use `create_toolbar_view()` for header |
| Paginate a list | `pagination.py` | `PaginatedListController(listbox, ...)` |
| Export data | `file_export.py` | `FileExportHelper.show_export_dialog(...)` |
| Icon creation | `utils.py` | Always `resolve_icon_name(name, fallback)` |
| Status styling | `view_helpers.py` | `set_status_class(widget, StatusLevel.X)` |

## Anti-Patterns (ui-specific)

- **Raw `Adw.EntryRow`/`SwitchRow`/etc.**: Use compat factories — breaks Ubuntu 22.04
- **`Adw.Dialog`**: Use `Adw.Window` — `Adw.Dialog` requires libadwaita 1.5+
- **Icons without `resolve_icon_name()`**: Breaks on non-GNOME themes
- **Emoji in status indicators**: Use semantic icons (`object-select-symbolic`, `dialog-warning-symbolic`)
- **`GLib.idle_add()` missing**: All background→UI updates MUST go through it
- **No loading state reset in `finally`**: Causes permanently stuck spinners
