# System Tray Subprocess Architecture

## Overview

ClamUI uses a subprocess architecture for system tray integration. The main application runs with GTK4 (for modern
Adwaita UI), while the system tray indicator runs in a separate subprocess using pure GIO D-Bus (GTK-agnostic).

This document explains the architecture, IPC protocol, and threading model.

## Why a Subprocess?

**Reason**: Process isolation keeps the tray service independent from the main application lifecycle. If the tray
service crashes, the main application continues running. The subprocess can also be started/stopped independently.

**Technology**: The tray service implements the **StatusNotifierItem (SNI)** D-Bus protocol directly using GIO's D-Bus
API. This is GTK-agnostic and works with GTK4. Context menus are exported via the **DBusMenu** protocol using
`libdbusmenu-glib`.

**Solution**: Run the tray indicator in a separate Python subprocess, communicating with the main GTK4 application via
JSON messages over stdin/stdout pipes.

## Component Relationships

The system tray feature is split across four key files, organized by process boundary and GTK version:

```mermaid
graph LR
    subgraph MainProcess["Main Process - GTK4 Context"]
        App["app.py (ClamUIApp - GTK4/Adwaita)"]
        TrayMgr["tray_manager.py (TrayManager - GTK4)"]

        App -->|imports & creates| TrayMgr
    end

    subgraph Subprocess["Subprocess - GIO D-Bus Context"]
        TrayService["tray_service.py (TrayService - GIO D-Bus/DBusMenu)"]
        TrayIcons["tray_icons.py (Icon Generator - PIL/Python stdlib, No GTK dependency)"]

        TrayService -->|imports & uses| TrayIcons
    end

    TrayMgr -.->|spawns subprocess via subprocess.Popen| TrayService
    TrayMgr <-->|JSON IPC via stdin/stdout pipes| TrayService

    style App fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style TrayMgr fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style TrayService fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style TrayIcons fill:#f1f8e9,stroke:#689f38,stroke-width:2px
```

**Component Descriptions:**

| Component           | GTK Version | Role                                                                                                                                           |
|---------------------|-------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| **app.py**          | GTK4        | Main application class (`Adw.Application`). Creates and manages the `TrayManager` instance.                                                    |
| **tray_manager.py** | GTK4        | Spawns the tray subprocess, sends JSON commands via stdin, receives events via stdout. Thread-safe with `GLib.idle_add()` for callbacks.       |
| **tray_service.py** | None (GIO)  | Subprocess entry point. Uses GIO D-Bus for SNI protocol, libdbusmenu for context menus, processes commands from stdin, sends events to stdout. |
| **tray_icons.py**   | None        | Utility module for generating composite tray icons with status badges using PIL. No GTK dependency.                                            |

**Why This Split?**

- **Process Isolation**: Keeps tray service independent from main application lifecycle (crash isolation, independent
  restart).
- **Process Boundary**: `tray_manager.py` and `tray_service.py` communicate across a subprocess boundary via JSON over
  pipes.
- **Icon Generation**: `tray_icons.py` is GTK-agnostic and can be imported by either context.

## Runtime Architecture

```mermaid
graph TB
    subgraph MainProc["Main Process (GTK4)"]
        App["ClamUIApp (Adw.Application)"]
        TrayMgr["TrayManager"]
        StdoutReader["Stdout Reader Thread"]
        StderrReader["Stderr Reader Thread"]
        MainLoop["GTK4 Main Loop (GLib)"]

        App -->|manages| TrayMgr
        TrayMgr -->|spawns via subprocess.Popen| Subprocess
        TrayMgr -->|writes JSON commands| StdinPipe
        StdoutReader -->|reads JSON events| StdoutPipe
        StderrReader -->|reads logs| StderrPipe
        StdoutReader -->|GLib.idle_add| MainLoop
        MainLoop -->|executes callbacks| App
    end

    subgraph SubProc["Subprocess (GIO D-Bus)"]
        TrayService["TrayService"]
        SNI["StatusNotifierItem (D-Bus)"]
        DBusMenu["Dbusmenu.Server"]
        StdinReader["Stdin Reader Thread"]
        GLibLoop["GLib Main Loop"]

        TrayService -->|registers| SNI
        TrayService -->|creates| DBusMenu
        SNI -->|exports| DBusMenu
        StdinReader -->|reads JSON commands| StdinPipe
        StdinReader -->|GLib.idle_add| GLibLoop
        GLibLoop -->|updates state| TrayService
        TrayService -->|writes JSON events| StdoutPipe
    end

    subgraph IPCPipes["IPC Pipes"]
        StdinPipe["stdin pipe (JSON commands)"]
        StdoutPipe["stdout pipe (JSON events)"]
        StderrPipe["stderr pipe (log output)"]
    end

    Subprocess["tray_service.py (Python subprocess)"]

    style App fill:#e1f5ff
    style TrayMgr fill:#e1f5ff
    style TrayService fill:#fff4e1
    style SNI fill:#fff4e1
    style DBusMenu fill:#fff4e1
    style StdinPipe fill:#e8f5e9
    style StdoutPipe fill:#e8f5e9
    style StderrPipe fill:#f3e5f5
```

## Component Responsibilities

### Main Process Components

#### ClamUIApp (`src/app.py`)

- Main GTK4 application class inheriting from `Adw.Application`
- Manages application lifecycle and views
- Creates and owns the `TrayManager` instance
- Registers callbacks for tray menu actions

#### TrayManager (`src/ui/tray_manager.py`)

- Spawns the `tray_service.py` subprocess using `subprocess.Popen`
- Sends JSON commands to subprocess via stdin pipe
- Runs background threads to read stdout (events) and stderr (logs)
- Uses `GLib.idle_add()` to schedule callbacks on GTK4 main thread
- Implements message validation (size limits, nesting depth checks)
- Thread-safe with `threading.Lock()` for shared state

### Subprocess Components

#### TrayService (`src/ui/tray_service.py`)

- Standalone Python script that runs in separate process
- Implements StatusNotifierItem (SNI) D-Bus protocol using GIO's D-Bus API
- Creates context menu using `Dbusmenu.Server` (libdbusmenu-glib)
- Exposes both icon names and IconPixmap fallback data for stricter tray hosts
- Runs background thread to read stdin for commands
- Uses `GLib.idle_add()` to schedule updates on GLib main loop
- Sends JSON events to stdout

#### D-Bus Integration

- **StatusNotifierItem**: Exports `/StatusNotifierItem` and registers that object path with the watcher, so the host uses the connection's unique bus name
- **DBusMenu**: Exports context menu via `com.canonical.dbusmenu` protocol
- **Supported DEs**: KDE Plasma, Cinnamon, XFCE (with SNI plugin), MATE, Budgie
- Updates icon based on protection status via D-Bus property changes

## Threading Model

```mermaid
sequenceDiagram
    participant App as ClamUIApp (GTK4 Main)
    participant TrayMgr as TrayManager (GTK4 Main)
    participant StdoutThread as Stdout Reader (Background)
    participant Subprocess as tray_service.py
    participant StdinThread as Stdin Reader (Background)
    participant TrayService as TrayService (GLib Main)

    Note over App,TrayMgr: Main Process (GTK4)
    Note over Subprocess,TrayService: Subprocess (GIO D-Bus)

    App->>TrayMgr: start()
    TrayMgr->>Subprocess: subprocess.Popen([python, tray_service.py])
    activate Subprocess
    TrayMgr->>StdoutThread: threading.Thread(target=_read_stdout).start()
    activate StdoutThread

    Subprocess->>StdinThread: threading.Thread(target=_read_stdin).start()
    activate StdinThread
    Subprocess->>TrayService: create indicator and menu
    TrayService-->>Subprocess: {"event": "ready"}

    StdoutThread->>StdoutThread: for line in stdout
    StdoutThread->>StdoutThread: parse JSON
    StdoutThread->>App: GLib.idle_add(callback)
    Note over StdoutThread,App: Thread-safe callback on GTK4 main loop

    App->>TrayMgr: update_status("scanning")
    TrayMgr->>Subprocess: stdin.write({"action": "update_status", "status": "scanning"})

    StdinThread->>StdinThread: for line in stdin
    StdinThread->>StdinThread: parse JSON
    StdinThread->>TrayService: GLib.idle_add(update_status, "scanning")
    Note over StdinThread,TrayService: Thread-safe callback on GLib main loop

    TrayService->>TrayService: update icon

    Note over TrayService: User clicks menu item
    TrayService-->>Subprocess: {"event": "menu_action", "action": "quick_scan"}

    StdoutThread->>StdoutThread: receive event
    StdoutThread->>App: GLib.idle_add(on_quick_scan)

    deactivate StdinThread
    deactivate StdoutThread
    deactivate Subprocess
```

## Complete IPC Flow

This diagram shows the full lifecycle of the tray subprocess, including startup handshake, various command types, menu
actions, and shutdown:

```mermaid
sequenceDiagram
    participant App as ClamUIApp
    participant TrayMgr as TrayManager
    participant Pipe as stdin/stdout
    participant TrayService as TrayService
    participant User as User

    Note over App,TrayService: 1. Startup & Handshake
    App->>TrayMgr: start()
    TrayMgr->>TrayService: spawn subprocess.Popen()
    activate TrayService
    TrayService->>TrayService: Initialize GLib, export SNI object, register path with watcher, create DBusMenu
    TrayService-->>Pipe: {"event": "ready"}
    Pipe-->>TrayMgr: ready event
    TrayMgr->>TrayMgr: _ready = True
    TrayMgr-->>App: Tray ready

    Note over App,TrayService: 2. Command Flow - Status Updates
    App->>TrayMgr: update_status("scanning")
    TrayMgr->>Pipe: {"action": "update_status", "status": "scanning"}
    Pipe->>TrayService: command
    TrayService->>TrayService: Change icon to scanning
    TrayService->>TrayService: Update tooltip

    Note over App,TrayService: 3. Command Flow - Progress Updates
    App->>TrayMgr: update_progress(45)
    TrayMgr->>Pipe: {"action": "update_progress", "percentage": 45}
    Pipe->>TrayService: command
    TrayService->>TrayService: Update menu label: "Scanning... 45%"

    App->>TrayMgr: update_progress(100)
    TrayMgr->>Pipe: {"action": "update_progress", "percentage": 100}
    Pipe->>TrayService: command
    TrayService->>TrayService: Update menu label: "Scanning... 100%"

    App->>TrayMgr: update_progress(0)
    TrayMgr->>Pipe: {"action": "update_progress", "percentage": 0}
    Pipe->>TrayService: command
    TrayService->>TrayService: Clear progress

    Note over App,TrayService: 4. Command Flow - Profile Updates
    App->>TrayMgr: update_profiles([profiles], current_id)
    TrayMgr->>Pipe: {"action": "update_profiles", "profiles": [...], "current_profile_id": "..."}
    Pipe->>TrayService: command
    TrayService->>TrayService: Rebuild profiles submenu, Mark current profile

    Note over App,TrayService: 5. Menu Action Events - Quick Scan
    User->>TrayService: Click "Quick Scan"
    TrayService-->>Pipe: {"event": "menu_action", "action": "quick_scan"}
    Pipe-->>TrayMgr: menu_action event
    TrayMgr->>App: GLib.idle_add(on_quick_scan)
    App->>App: Start quick scan

    Note over App,TrayService: 6. Menu Action Events - Profile Selection
    User->>TrayService: Click profile menu item
    TrayService-->>Pipe: {"event": "menu_action", "action": "select_profile", "profile_id": "custom-profile-1"}
    Pipe-->>TrayMgr: menu_action event
    TrayMgr->>App: GLib.idle_add(on_profile_select, profile_id)
    App->>App: Switch to profile, Update UI

    Note over App,TrayService: 7. Menu Action Events - Toggle Window
    User->>TrayService: Click "Show/Hide Window"
    TrayService-->>Pipe: {"event": "menu_action", "action": "toggle_window"}
    Pipe-->>TrayMgr: menu_action event
    TrayMgr->>App: GLib.idle_add(on_toggle_window)
    App->>App: Show or hide main window
    App->>TrayMgr: update_window_visible(True)
    TrayMgr->>Pipe: {"action": "update_window_visible", "visible": true}
    Pipe->>TrayService: command
    TrayService->>TrayService: Update menu label: "Hide Window"

    Note over App,TrayService: 8. Menu Action Events - Update Database
    User->>TrayService: Click "Update Virus Database"
    TrayService-->>Pipe: {"event": "menu_action", "action": "update"}
    Pipe-->>TrayMgr: menu_action event
    TrayMgr->>App: GLib.idle_add(on_update)
    App->>App: Start freshclam update

    Note over App,TrayService: 9. Shutdown Flow
    User->>TrayService: Click "Quit"
    TrayService-->>Pipe: {"event": "menu_action", "action": "quit"}
    Pipe-->>TrayMgr: menu_action event
    TrayMgr->>App: GLib.idle_add(on_quit)
    App->>App: do_shutdown()
    App->>TrayMgr: stop()
    TrayMgr->>Pipe: {"action": "quit"}
    Pipe->>TrayService: command
    TrayService->>TrayService: GLib.MainLoop.quit()
    deactivate TrayService
    TrayMgr->>TrayMgr: Wait up to 2s for exit
    TrayMgr->>TrayMgr: Cleanup pipes and threads
```

### Thread Safety

Both processes use **GLib.idle_add()** to ensure operations happen on the correct main thread:

- **TrayManager**: Stdout reader thread schedules callbacks on GTK4 main loop
- **TrayService**: Stdin reader thread schedules D-Bus/state updates on GLib main loop

This prevents race conditions and thread-safety violations.

### Shared State Protection

**TrayManager** uses `threading.Lock()` to protect shared state:

```python
with self._state_lock:
    self._running = True
    self._ready = False
    self._current_status = "protected"
```

## IPC Protocol

Communication uses JSON messages over stdin/stdout pipes.

### Message Format

All messages are single-line JSON objects followed by a newline:

```json
{"event": "ready"}\n
{"action": "update_status", "status": "scanning"}\n
```

### Commands (Main → Subprocess)

Sent via **stdin** to the subprocess:

| Action                  | Parameters                                           | Description                                                                                               |
|-------------------------|------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `update_status`         | `status: str`                                        | Update icon to reflect protection status<br/>Values: `"protected"`, `"warning"`, `"scanning"`, `"threat"` |
| `update_progress`       | `percentage: int`                                    | Show scan progress percentage (0-100)<br/>Use 0 to clear                                                  |
| `update_window_visible` | `visible: bool`                                      | Update Show/Hide Window menu label                                                                        |
| `update_profiles`       | `profiles: List[dict]`<br/>`current_profile_id: str` | Update profiles submenu                                                                                   |
| `quit`                  | -                                                    | Gracefully stop the subprocess                                                                            |
| `ping`                  | -                                                    | Health check (expects `pong` response)                                                                    |

**Example**:

```json
{"action": "update_status", "status": "scanning"}
{"action": "update_progress", "percentage": 45}
```

### Events (Subprocess → Main)

Sent via **stdout** from the subprocess:

| Event         | Parameters                                     | Description                                                                                                                        |
|---------------|------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `ready`       | -                                              | Subprocess initialized and ready                                                                                                   |
| `menu_action` | `action: str`<br/>`profile_id: str` (optional) | User triggered menu action<br/>Actions: `"quick_scan"`, `"full_scan"`, `"update"`, `"quit"`, `"toggle_window"`, `"select_profile"` |
| `pong`        | -                                              | Response to `ping` command                                                                                                         |
| `error`       | `message: str`                                 | Error occurred in subprocess                                                                                                       |

**Example**:

```json
{"event": "ready"}
{"event": "menu_action", "action": "quick_scan"}
{"event": "menu_action", "action": "select_profile", "profile_id": "profile-123"}
```

### Security Considerations

**TrayManager** implements security validations:

1. **Message Size Limit**: Max 1MB per message to prevent memory exhaustion

   ```python
   MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB
   ```

2. **Nesting Depth Limit**: Max 10 levels to prevent stack overflow

   ```python
   MAX_NESTING_DEPTH = 10
   ```

3. **Message Structure Validation**: All messages must have an `"event"` field

## Startup and Shutdown

### Startup Flow

1. **ClamUIApp** creates **TrayManager** instance
2. **TrayManager.start()** spawns subprocess:
   ```python
   service_path = self._get_service_path()  # Resolves full path to tray_service.py
   self._process = subprocess.Popen(
       [sys.executable, service_path],
       stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True
   )
   ```
3. **TrayManager** starts stdout/stderr reader threads
4. **TrayService** exports the SNI object, registers `/StatusNotifierItem` with the watcher, and creates DBusMenu
5. **TrayService** sends `{"event": "ready"}` to stdout
6. **TrayManager** receives ready event and sets `_ready = True`

### Shutdown Flow

1. **ClamUIApp.do_shutdown()** calls **TrayManager.stop()**
2. **TrayManager** sends `{"action": "quit"}` command
3. **TrayService** receives command, calls `GLib.MainLoop.quit()`
4. **TrayManager** waits up to 2 seconds for graceful exit
5. If timeout expires, **TrayManager** terminates/kills subprocess
6. Reader threads exit when pipes close

## File Locations

| File                     | Description                         | GTK Version |
|--------------------------|-------------------------------------|-------------|
| `src/app.py`             | Main application class              | GTK4        |
| `src/ui/tray_manager.py` | Subprocess manager (main process)   | GTK4        |
| `src/ui/tray_service.py` | Tray indicator service (subprocess) | None (GIO)  |
| `src/ui/tray_icons.py`   | Icon generation utilities           | None (PIL)  |

## Common Patterns

### Sending a Command

```python
# In TrayManager (main process)
def update_status(self, status: str) -> None:
    self._send_command({"action": "update_status", "status": status})
```

### Handling an Event

```python
# In TrayManager (main process)
def _handle_menu_action(self, action: str, message: dict) -> None:
    if action == "quick_scan" and self._on_quick_scan:
        GLib.idle_add(self._on_quick_scan)  # Thread-safe callback
```

### Processing a Command in Subprocess

```python
# In TrayService (subprocess)
def handle_command(self, command: dict) -> None:
    action = command.get("action")
    if action == "update_status":
        status = command.get("status", "protected")
        GLib.idle_add(self.update_status, status)  # Thread-safe D-Bus update
```

## Troubleshooting

### Tray Icon Not Appearing

1. Check if libdbusmenu is installed:
   ```bash
   dpkg -l | grep libdbusmenu
   ```
2. Check if desktop environment supports StatusNotifierItem (SNI):
    - KDE Plasma: Built-in support
    - Cinnamon: Built-in support (xapp-sn-watcher)
    - XFCE: Requires `xfce4-statusnotifier-plugin`
    - GNOME: Requires extension (e.g., AppIndicator support)
3. Check subprocess logs in application output with `CLAMUI_DEBUG=1`
4. Verify D-Bus session bus is running

### Commands Not Working

1. Enable debug logging: `export CLAMUI_DEBUG=1`
2. Check for JSON parse errors in logs
3. Verify stdin/stdout pipes are not buffered
4. Check for subprocess crashes in main app logs

### Thread Safety Issues

1. Always use `GLib.idle_add()` for D-Bus/state operations from threads
2. Use `threading.Lock()` for shared state
3. Never call GLib/D-Bus methods directly from reader threads

## References

- **StatusNotifierItem Specification**: https://www.freedesktop.org/wiki/Specifications/StatusNotifierItem/
- **DBusMenu Specification**: https://github.com/AyatanaIndicators/libdbusmenu
- **GIO D-Bus Documentation**: https://docs.gtk.org/gio/class.DBusConnection.html
- **GTK4 Documentation**: https://docs.gtk.org/gtk4/
- **Python subprocess**: https://docs.python.org/3/library/subprocess.html
