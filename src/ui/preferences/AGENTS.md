# preferences/ - Preferences Pages

Parent: [`../AGENTS.md`](../AGENTS.md)

`window.py` owns sidebar navigation, page construction, config loading, and the
Save & Apply hand-off. Keep pages focused on their controls and their own
callbacks.

## Navigation and page lifecycle

`NAVIGATION_ITEMS` is the sidebar source of truth. Its current IDs, in display
order, are `behavior`, `exclusions`, `database`, `scanner`, `scheduled`,
`device_scan`, `onaccess`, `virustotal`, `debug`, and `save`.

`BehaviorPage` is the eager default page. Every other page is registered in
`PreferencesWindow._page_factories` and is constructed when selected.
`_ensure_page_created()` records completed factories in `_created_pages`; a
factory must therefore create the page and call `_add_page_to_stack(page_id,
page)`. Do not pre-create pages or add a second page directly to the stack.

Config paths and parsed configurations load in a worker thread. UI construction,
population, and rebuilding happen on the GTK main thread. A config-backed page
created before loading finishes can be rebuilt, so keep all of its widget
references in the window-owned dictionary and make `populate_fields()` safe to
call after construction.

## Adding or changing a page

1. Choose the existing factory shape that matches its state:
   - Instance pages retain dependencies in `__init__` and expose
     `create_page(self)`: `BehaviorPage`, `ExclusionsPage`, `DeviceScanPage`,
     `DebugPage`, and `SavePage`.
   - Static config/form pages receive their dependencies at construction:
     `DatabasePage.create_page(config_path, widgets_dict, parent_window=None)`,
     `ScannerPage.create_page(config_path, widgets_dict, settings_manager,
     clamd_available, parent_window)`,
     `ScheduledPage.create_page(widgets_dict)`, and
     `OnAccessPage.create_page(config_path, widgets_dict, clamd_available,
     parent_window)`.
   - `VirusTotalPage.create_page(settings_manager, parent_window=None)` is
     static but owns its callback state on the returned page rather than using a
     shared widget dictionary.
2. In `window.py`, import the page, add its `(page_id, icon_name, N_(label))`
   sidebar tuple, register its factory, and have the factory call
   `_add_page_to_stack()`. Add a window-owned widget dictionary only when the
   page needs deferred population or collection.
3. For a config-backed or deferred settings page, implement matching
   `populate_fields()` and `collect_data()` methods. Store the input widget,
   not an enclosing row: `create_spin_row()` returns `(row, spin_button)`.
   Extend `SavePage` construction and collection deliberately when the new
   data must be applied with Save & Apply; never make an unregistered
   dictionary silently write defaults.
4. Application settings that intentionally persist on interaction should use
   their `SettingsManager` callback pattern instead. Do not route those
   auto-saved controls through system-config writing.

## Shared helpers and compatibility

Use the helpers in `base.py` instead of duplicating widget access:

- `create_spin_row(title, subtitle, min_val, max_val, step=1, page_step=10,
  initial_val=None)` returns `(Adw.ActionRow, Gtk.SpinButton)`.
- `create_password_entry_row(title)`, `create_navigation_row(title,
  subtitle=None, icon_name=None)`, and `create_status_row(title, status_ok,
  ok_message, error_message)` provide compatible rows.
- Use `populate_bool_field`, `populate_int_field`, `populate_text_field`, or
  `populate_multivalue_field` to load a widget dictionary. Use the
  `get_widget_*` / `set_widget_*` helpers when collecting or changing values
  so missing lazy widgets are handled safely.

Follow the root UI compatibility baseline. Use `src/ui/compat.py` and these
base helpers rather than newer libadwaita widgets or dialog APIs. In
particular, use the compatible password and spin helpers, not
`Adw.PasswordEntryRow` or `Adw.SpinRow`.

## Text and privileged persistence

Wrap every user-visible string in `_()` from `core.i18n`; mark module-level
labels that are translated only when displayed with `N_()`. Use
`_("… {name}").format(name=value)`, not an f-string inside `_()`.

Do not write `clamd.conf` or `freshclam.conf` from a page. `SavePage` gathers
the configured widget dictionaries, validates proposed configs, backs up the
current files, and calls `write_configs_with_elevation()` off the GTK thread.
For Flatpak, system writes require the matching host privileged helper and
must fail closed when it is unavailable. Keep GTK updates on the main thread.