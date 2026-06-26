# preferences/ — Modular Preferences System

13 modules (12 pages/helpers + `__init__`). Pages reach the stack via a **mixed** factory pattern: `create_page()` is an **instance method** on some pages and a `@staticmethod` on others, with per-page signatures (not uniform). `BehaviorPage` is built eagerly as the default visible page; every other page is lazy, created on first navigation via the `_page_factories` dict in `window.py`.

Parent: [`../AGENTS.md`](../AGENTS.md)

## Structure

```
preferences/
├── window.py          # PreferencesWindow — sidebar nav, lazy page creation
├── base.py            # PreferencesPageMixin + widget helper functions
├── scanner_page.py    # Scanner backend settings (TEMPLATE for new pages)
├── database_page.py   # Freshclam database settings
├── behavior_page.py   # Close behavior, notifications, tray
├── exclusions_page.py # Exclusion pattern management
├── scheduled_page.py  # Scheduled scan configuration
├── onaccess_page.py   # On-access scanning settings
├── device_scan_page.py# Device scanning settings
├── virustotal_page.py # VirusTotal API configuration
├── save_page.py       # Save & apply with pkexec elevation
└── debug_page.py      # Debug/logging options
```

## Recipe: Adding a New Preferences Page

### 1. Create the page module

**`create_page()` signatures are NOT uniform** — pick a template matching the page's data source:
- **Config-backed pages** (read/write clamd.conf / freshclam.conf): `@staticmethod create_page(...)` taking a `widgets_dict`. Good templates: `scanner_page.py` (`ScannerPage`), `database_page.py` (`DatabasePage`). Exact params vary (e.g. `ScannerPage.create_page(config_path, widgets_dict, settings_manager, clamd_available, parent_window)`, `DatabasePage.create_page(config_path, widgets_dict, parent_window)`).
- **Simple settings pages** (read/write `settings.json`): **instance method** `create_page(self)` with deps stored in `__init__`. Templates: `behavior_page.py`, `device_scan_page.py`, `exclusions_page.py`.

Static `widgets_dict` form (config-backed; ScannerPage/DatabasePage style):

```python
from ..compat import create_switch_row, create_entry_row
from .base import PreferencesPageMixin, create_spin_row, populate_bool_field

class MyPage(PreferencesPageMixin):
    @staticmethod
    def create_page(widgets_dict: dict, settings_manager, parent_window) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(
            title=_("My Settings"),
            icon_name=resolve_icon_name("preferences-system-symbolic"),
        )
        group = Adw.PreferencesGroup(title=_("Group Title"))
        # Add rows to group, store widgets in widgets_dict
        page.add(group)
        return page

    @staticmethod
    def populate_fields(config: dict, widgets_dict: dict):
        populate_bool_field(config, widgets_dict, "my_key", default=True)

    @staticmethod
    def collect_data(widgets_dict: dict) -> dict:
        return {"my_key": widgets_dict["my_key"].get_active()}
```

### 2. Register in window.py
```python
# 1. Add a (page_id, icon, N_(label)) tuple to NAVIGATION_ITEMS:
("my_page", "preferences-system-symbolic", N_("My Settings")),

# 2. Wire a factory into the lazy _page_factories dict (in __init__):
self._page_factories = {
    ...,
    "my_page": self._create_my_page,
}

# 3. Implement the factory; build the page, then add via the stack helper:
def _create_my_page(self):
    # static form shown; instance pages do MyPage(...).create_page() instead
    page = MyPage.create_page(self._my_widgets, parent_window=self)
    self._add_page_to_stack("my_page", page)
```
Only `BehaviorPage` is built eagerly in `_create_pages()`; pages in `_page_factories` are created on first navigation via `_ensure_page_created()`. Current `NAVIGATION_ITEMS` order: behavior, exclusions, database, scanner, scheduled, device_scan, onaccess, virustotal, debug, save.

### 3. Write tests
`tests/ui/preferences/test_my_page.py` — use `mock_gi_modules` fixture.

## Key APIs from base.py

| Function | Purpose |
|----------|---------|
| `create_spin_row(title, subtitle, min_val, max_val, step=1, page_step=10)` | Returns `(row, spin_button)` tuple |
| `create_password_entry_row(title)` | Password entry with visibility toggle |
| `populate_bool_field(config, widgets, key, default)` | Load bool into switch |
| `populate_int_field(config, widgets, key)` | Load int into spin button |
| `populate_text_field(config, widgets, key)` | Load text into entry |
| `create_status_row(title, status_ok, ok_message, error_message)` | Returns `(row, icon)` (icon is a `Gtk.Image`) for status display |
| `styled_prefix_icon(icon_name)` | 12px-margin dim icon for row prefix |

## Anti-Patterns (preferences-specific)

- **Eager page creation**: Only `behavior_page` loads eagerly — all others use lazy factory pattern
- **`Adw.SpinRow` / `Adw.PasswordEntryRow`**: Use `create_spin_row()` / `create_password_entry_row()` from base.py
- **Direct widget value access**: Use `populate_*` helpers for loading, `collect_data()` for saving
- **Storing row instead of spin_button**: `create_spin_row()` returns `(row, spin_button)` — store the `spin_button` in `widgets_dict` for `get_value()`/`set_value()`
