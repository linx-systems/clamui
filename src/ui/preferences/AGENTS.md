# preferences/ - Modular Preferences System

13 modules (12 pages/helpers + `__init__`). Pages reach stack by **mixed** factory pattern: `create_page()` be **instance method** on some pages, `@staticmethod` on others, signatures differ per page (no uniform). `BehaviorPage` born eager as default visible page; all other pages lazy, born on first walk-to via `_page_factories` dict in `window.py`.

Parent: [`../AGENTS.md`](../AGENTS.md)

## Structure

```
preferences/
├── window.py          # PreferencesWindow - sidebar nav, lazy page creation
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

**`create_page()` signatures NOT uniform** - pick template matching page data source:
- **Config-backed pages** (read/write clamd.conf / freshclam.conf): `@staticmethod create_page(...)` take `widgets_dict`. Good templates: `scanner_page.py` (`ScannerPage`), `database_page.py` (`DatabasePage`). Params vary (e.g. `ScannerPage.create_page(config_path, widgets_dict, settings_manager, clamd_available, parent_window)`, `DatabasePage.create_page(config_path, widgets_dict, parent_window)`).
- **Simple settings pages** (read/write `settings.json`): **instance method** `create_page(self)`, deps stashed in `__init__`. Templates: `behavior_page.py`, `device_scan_page.py`, `exclusions_page.py`.

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
Only `BehaviorPage` born eager in `_create_pages()`; pages in `_page_factories` born on first walk-to via `_ensure_page_created()`. Now `NAVIGATION_ITEMS` order: behavior, exclusions, database, scanner, scheduled, device_scan, onaccess, virustotal, debug, save.

### 3. Write tests
`tests/ui/preferences/test_my_page.py` - use `mock_gi_modules` fixture.

## Key APIs from base.py

| Function | Purpose |
|----------|---------|
| `create_spin_row(title, subtitle, min_val, max_val, step=1, page_step=10, initial_val=None)` | Give back `(row, spin_button)` tuple; use `initial_val` when start value must differ from `min_val` |
| `create_password_entry_row(title)` | Password entry with visibility toggle |
| `populate_bool_field(config, widgets, key, default)` | Load bool into switch |
| `populate_int_field(config, widgets, key)` | Load int into spin button |
| `populate_text_field(config, widgets, key)` | Load text into entry |
| `create_status_row(title, status_ok, ok_message, error_message)` | Give back `(row, icon)` (icon be `Gtk.Image`) for status show |
| `styled_prefix_icon(icon_name)` | 12px-margin dim icon for row prefix |

## Anti-Patterns (preferences-specific)

- **Eager page creation**: Only `behavior_page` load eager - all others use lazy factory pattern
- **`Adw.SpinRow` / `Adw.PasswordEntryRow`**: Use `create_spin_row()` / `create_password_entry_row()` from base.py
- **Direct widget value access**: Use `populate_*` helpers for load, `collect_data()` for save
- **Storing row instead of spin_button**: `create_spin_row()` give back `(row, spin_button)` - stash `spin_button` in `widgets_dict` for `get_value()`/`set_value()`