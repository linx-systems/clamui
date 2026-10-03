# scan/ - Scan Workflow (Coordinator Pattern)

8 modules. Composition scan UI. Replace big `scan_view.py`.

Parent: [`../AGENTS.md`](../AGENTS.md)

## Structure

```
scan/
├── scan_view.py            # Composition root - assembles all components
├── scan_controller.py      # ScanController - multi-target orchestration, threading, ScanState machine, cancellation
├── coordinator.py          # ScanCoordinator - tray-driven callbacks (quick/full/profile/VirusTotal) + scan-state tracking
├── profile_selector.py     # Profile dropdown + management buttons
├── target_selector.py      # File/folder selection + drag-and-drop
├── scan_progress_widget.py # Progress bar + file counter + ETA
├── scan_results_widget.py  # ScanResultsWidget - "View Results" button + threat count
└── __init__.py
```

## Architecture

```
ScanView (composition root - Gtk.Box)
├── ProfileSelector     ← profile dropdown, edit/create/import buttons
├── TargetSelector      ← file chooser, drag-and-drop, path validation
├── ScanController      ← start/cancel, backend selection, threading, ScanState
├── ScanProgressWidget  ← progress bar, files scanned, current file
└── ScanResultsWidget   ← "View Results" button, threat count
```

Each part test alone. `ScanView` tie together.

## Key Patterns

### State Flow
States `IDLE / SCANNING / CANCELLED` (`ScanState` enum in `scan_controller.py`). Done and error NOT enum — come through `on_complete` / result callbacks.

`ScanController` do transitions. Progress update via `GLib.idle_add()` from scan thread.

### Drag-and-Drop
`TargetSelector` take file drops. Use `validate_dropped_files()` from `core/path_validation.py` — throw away symlinks to protected dirs, paths not exist.

### Profile Integration
`ProfileSelector` load from `ProfileManager`. Chosen profile set scan targets, exclusions, backend. Profile change trigger `TargetSelector` update.

## Where to Look

| Task | Module | Notes |
|------|--------|-------|
| Add scan UI element | `scan_view.py` | Add component, wire in composition root |
| Change scan state logic | `scan_controller.py` | State transitions + threading |
| Modify file selection | `target_selector.py` | Drag-drop + file dialog |
| Change progress display | `scan_progress_widget.py` | GLib.idle_add for updates |
| Add scan orchestration | `coordinator.py` | `ScanCoordinator` - tray-driven quick/full/profile/VirusTotal callbacks + scan-state tracking |

## Anti-Patterns

- **Direct Scanner calls from UI**: Use `ScanController` — it do threading + cancellation
- **Progress updates without `GLib.idle_add()`**: Progress callback run on scan thread, not GTK thread
- **Monolithic changes**: Add new parts as separate widgets, wire in `scan_view.py`