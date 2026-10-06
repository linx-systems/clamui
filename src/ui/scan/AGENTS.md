# scan/ - Modular Scan Alternative

Parent: [`../AGENTS.md`](../AGENTS.md)

## Current integration boundary

`src/ui/scan_view.py:ScanView` is the active application screen:
`ClamUIApp.scan_view` imports and constructs it, then connects its scan-state
callback to the app. The active view implements its own profile selection,
target selection, progress display, scanning worker, and result display.

This package is a modular alternative that is not imported by the current
application route. Its local `ScanView` composes the selector, controller,
progress, and results components, but changes here do not change the screen
shown by ClamUIApp. For a user-visible scan UI change, edit
`src/ui/scan_view.py` and its existing helpers. Use this package only when
working explicitly on the modular implementation or performing a complete,
caller-wide cutover.

## Local components

- `scan_view.py` is the modular composition root. It wires
  `ProfileSelector`, `TargetSelector`, `ScanController`,
  `ScanProgressWidget`, and `ScanResultsWidget`.
- `scan_controller.py` owns modular multi-target scanning, cancellation, result
  aggregation, and callback delivery.
- `profile_selector.py` owns profile selection and profile-management launch.
  It accepts `get_profile_manager`; it emits `profile-selected`,
  `targets-changed`, and `start-scan-requested`.
- `target_selector.py` owns its modular target list and native file/folder
  picker. It accepts `is_scanning`, emits `targets-changed`, validates drops
  with `core.utils.validate_dropped_files()`, and exposes a copied `paths`
  list.
- `scan_progress_widget.py` and `scan_results_widget.py` render modular
  progress and result controls.
- `coordinator.py:ScanCoordinator` adapts the modular view cache to tray,
  quick/full/profile, and VirusTotal callbacks. It takes an AppContext and the
  UI-scoped `ViewCoordinator`; the current `ClamUIApp` does not construct it.

## State and thread contracts

### Active screen

The active `src/ui/scan_view.py:ScanView` guards each scan with
`_is_scanning`, snapshots selected targets for its worker, and aggregates the
per-target `ScanResult` values. Its scanner worker never mutates GTK directly:
target progress, live progress, completion, and errors return through
`GLib.idle_add()`. A progress-session token rejects callbacks left over from an
earlier scan.

The callback registered with `set_scan_state_changed_callback()` receives the
active screen's state notifications: start calls it with `True`; completion
calls it with `False, result`; an internal error calls it with `False, None`.
Consumers must therefore accept an optional result. Cancellation asks the shared
`Scanner` to cancel and the worker finalizes the UI.

### Modular controller

`ScanController.start_scan(paths, profile_exclusions=None,
on_target_progress=None)` rejects an empty or re-entrant start, starts a daemon
worker, and accepts `cancel()` for the current scan. Configure
`on_progress(progress, cumulative_files, total_targets)`, `on_complete(result)`,
and `on_state_change(state)` with `set_callbacks()`.

Progress, target-progress, completion, and the final state callback are
dispatched to the GTK main loop with `GLib.idle_add()`. `ScanState` declares
`IDLE`, `SCANNING`, and `CANCELLED`, but this controller reports work as
`SCANNING` and finalizes its state as `IDLE`; cancellation is represented by the
completed `ScanResult.status`. It invokes `on_complete(result)` before the
final `on_state_change(IDLE)` callback.

## Change locations

| Change | Active implementation |
|---|---|
| Scan screen layout, profile picker, target picker, progress, results, or scan controls | `src/ui/scan_view.py` |
| Main-window routing to the scan screen | `src/app.py`, `src/view_coordinator.py`, and `src/ui/window.py` |
| Shared scan result dialog | `src/ui/scan_results_dialog.py` |
| Compatibility file/folder picker | `src/ui/compat.py:open_paths_dialog()` |

Do not assume the modular components are used by the active screen, and do not
move active behavior into them without updating every application import,
callback, and routing call site.