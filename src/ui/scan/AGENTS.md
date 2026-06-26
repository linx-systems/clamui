# scan/ — Scan Workflow (Coordinator Pattern)

8 modules. Composition-based scan UI replacing monolithic `scan_view.py`.

Parent: [`../AGENTS.md`](../AGENTS.md)

## Structure

```
scan/
├── scan_view.py            # Composition root — assembles all components
├── scan_controller.py      # ScanController — multi-target orchestration, threading, ScanState machine, cancellation
├── coordinator.py          # ScanCoordinator — tray-driven callbacks (quick/full/profile/VirusTotal) + scan-state tracking
├── profile_selector.py     # Profile dropdown + management buttons
├── target_selector.py      # File/folder selection + drag-and-drop
├── scan_progress_widget.py # Progress bar + file counter + ETA
├── scan_results_widget.py  # ScanResultsWidget — "View Results" button + threat count
└── __init__.py
```

## Architecture

```
ScanView (composition root — Gtk.Box)
├── ProfileSelector     ← profile dropdown, edit/create/import buttons
├── TargetSelector      ← file chooser, drag-and-drop, path validation
├── ScanController      ← start/cancel, backend selection, threading, ScanState
├── ScanProgressWidget  ← progress bar, files scanned, current file
└── ScanResultsWidget   ← "View Results" button, threat count
```

Each component is independently testable. `ScanView` wires them together.

## Key Patterns

### State Flow
States are `IDLE / SCANNING / CANCELLED` (the `ScanState` enum in `scan_controller.py`). Completion and errors are NOT enum members — they are delivered through `on_complete` / result callbacks.

`ScanController` manages transitions. Progress updates via `GLib.idle_add()` from scan thread.

### Drag-and-Drop
`TargetSelector` accepts file drops. Uses `validate_dropped_files()` from `core/path_validation.py` — rejects symlinks to protected dirs, non-existent paths.

### Profile Integration
`ProfileSelector` loads from `ProfileManager`. Selected profile determines scan targets, exclusions, and backend. Profile changes trigger `TargetSelector` update.

## Where to Look

| Task | Module | Notes |
|------|--------|-------|
| Add scan UI element | `scan_view.py` | Add component, wire in composition root |
| Change scan state logic | `scan_controller.py` | State transitions + threading |
| Modify file selection | `target_selector.py` | Drag-drop + file dialog |
| Change progress display | `scan_progress_widget.py` | GLib.idle_add for updates |
| Add scan orchestration | `coordinator.py` | `ScanCoordinator` — tray-driven quick/full/profile/VirusTotal callbacks + scan-state tracking |

## Anti-Patterns

- **Direct Scanner calls from UI**: Go through `ScanController` — it handles threading + cancellation
- **Progress updates without `GLib.idle_add()`**: Progress callback runs on scan thread, not GTK thread
- **Monolithic changes**: Add new components as separate widgets, wire in `scan_view.py`
