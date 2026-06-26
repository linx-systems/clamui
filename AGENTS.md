# AGENTS.md — ClamUI AI Assistant Guide

> Canonical AI-assistant guide for this repository. Also read by Claude Code, Cursor, Aider, Continue, and Zed via the AGENTS.md convention. `CLAUDE.md` is a stub that redirects here — keep updates to this file.

## Project Overview

ClamUI is a modern Linux desktop application providing a graphical user interface for ClamAV antivirus. Built with **PyGObject**, **GTK4**, and **libadwaita** for native GNOME integration.

**Key Facts:**

- Python 3.11+ required
- GTK4/libadwaita UI (targets libadwaita 1.1+ for Ubuntu 22.04 / Pop!\_OS 22.04 baseline)
- ClamAV integration via subprocess (clamscan, clamdscan, freshclam)
- Distributed as native Debian package, AppImage, and Flatpak
- VirusTotal integration for enhanced threat analysis
- Translations: de, en, es, fr, it, zh_CN (see `po/LINGUAS`)
- MIT licensed

## Repository Structure (top level)

```
clamui/
├── src/                    Application source — read per-dir AGENTS.md (below)
│   ├── main.py             Application entry point
│   ├── app.py              Adw.Application (lifecycle, views, tray)
│   ├── cli/                CLI entry points + command router
│   ├── core/               Business logic, no UI dependencies
│   ├── profiles/           Scan profile management
│   └── ui/                 GTK4/Adwaita UI components
├── tests/                  Mirrors src/ (core/, ui/, profiles/, integration/, e2e/)
├── docs/                   Developer + user docs (table below)
│   ├── architecture/       Architectural notes (e.g. tray-subprocess)
│   └── user-guide/         End-user pages (getting-started, scanning, quarantine, …)
├── po/                     Translations (de, en, es, fr, it, zh_CN) + POTFILES.in, clamui.pot
├── scripts/                Dev + packaging scripts (local-run, update-pot, nemo actions, hooks/)
├── appimage/               AppImage build (build-appimage.sh)
├── flathub/                Flatpak manifest + generated Python deps
├── debian/                 Debian packaging
├── data/                   Desktop integration (.desktop, nemo_action, metainfo.xml)
├── icons/                  Application icons
├── website/                Astro marketing site
├── planning/, thoughts/    Internal planning / AI-tooling context snapshots
└── pyproject.toml          Project config + dependencies
```

### Hierarchical context docs (read the nearest one before editing)

Each source subdirectory has a concise local `AGENTS.md` with scope-specific architectural framing — tighter than this root file. When working inside one of these directories, read its `AGENTS.md` first:

- [`src/core/AGENTS.md`](src/core/AGENTS.md) — business-logic layer (no UI deps)
- [`src/core/quarantine/AGENTS.md`](src/core/quarantine/AGENTS.md) — SQLite quarantine subsystem
- [`src/ui/AGENTS.md`](src/ui/AGENTS.md) — GTK4/Adwaita UI layer
- [`src/ui/scan/AGENTS.md`](src/ui/scan/AGENTS.md) — scan workflow (coordinator pattern, replaces monolithic `scan_view.py`)
- [`src/ui/preferences/AGENTS.md`](src/ui/preferences/AGENTS.md) — modular preferences pages

## Architecture Documentation

For detailed technical documentation on specific architectural patterns, see the `docs/` directory:

| Document                                                                       | Description                                         |
| ------------------------------------------------------------------------------ | --------------------------------------------------- |
| [`docs/architecture/tray-subprocess.md`](docs/architecture/tray-subprocess.md) | System tray subprocess architecture (GIO D-Bus/SNI) |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)                               | Comprehensive configuration reference               |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)                                   | Development environment setup                       |
| [`docs/INSTALL.md`](docs/INSTALL.md)                                           | Installation guide                                  |
| [`docs/SCAN_BACKENDS.md`](docs/SCAN_BACKENDS.md)                               | Scan backend options and performance                |
| [`docs/SIGNING.md`](docs/SIGNING.md)                                           | Package signing and verification                    |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)                           | Common issues and solutions                         |
| [`docs/TRANSLATING.md`](docs/TRANSLATING.md)                                   | Translation contributing guide                      |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)                                     | End-user documentation                              |

### System Tray Subprocess Architecture

**Location**: [`docs/architecture/tray-subprocess.md`](docs/architecture/tray-subprocess.md)

ClamUI uses a subprocess architecture for system tray integration:

- **Main process** (GTK4): `ClamUIApp` and `TrayManager`
- **Subprocess** (GIO D-Bus): `TrayService` using StatusNotifierItem protocol + libdbusmenu
- **IPC**: JSON messages over stdin/stdout pipes

The subprocess uses pure GIO D-Bus (GTK-agnostic) to implement the SNI protocol, with `Dbusmenu` (GLib API) for context menus. The documentation includes:

- Runtime architecture diagrams showing process boundaries and threading models
- Complete IPC protocol specification (commands, events, message formats)
- Sequence diagrams for startup, status updates, and menu actions
- Component relationships between `app.py`, `tray_manager.py`, `tray_service.py`, and `tray_icons.py`
- Security considerations and troubleshooting guides

**When to reference this:**

- Implementing features that update the system tray (status, progress, icons)
- Debugging IPC communication issues between main app and tray
- Understanding why certain operations require thread-safe callbacks
- Contributing to tray-related code in `src/ui/tray_*.py`

## Development Commands

### Setup

```bash
# Install system dependencies (Ubuntu/Debian)
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
    libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev clamav

# Build dependencies for Pillow (tray icon support)
sudo apt install libjpeg-dev zlib1g-dev

# Install Python dependencies with uv
uv sync --dev

# Install git hooks (REQUIRED)
./scripts/hooks/install-hooks.sh

# Run from source
uv run clamui
```

**Important:** The pre-commit hook is **required** for development. It prevents absolute `src.*` imports which break when ClamUI is installed as a Debian package. See [Import Conventions](#import-conventions-package-compatibility) for details.

### Testing

```bash
# Run full test suite (fast local default, no coverage)
pytest

# Run specific test file
pytest tests/core/test_scanner.py -v

# Run with coverage report
pytest --cov=src --cov-report=term-missing

# Run only core tests (faster)
pytest tests/core -v

# Skip e2e tests (CI default)
pytest --ignore=tests/e2e
```

### Linting

```bash
# Check code style
uv run ruff check src/ tests/

# Check formatting
uv run ruff format --check src/ tests/

# Auto-fix issues
uv run ruff check src/ tests/ --fix
uv run ruff format src/ tests/
```

Important: Always run `uv run ruff format src/ tests/` and `uv run ruff check --fix` before committing to ensure code consistency.

## Code Patterns & Conventions

### Import Conventions (Package Compatibility)

**Always use relative imports** within the `src/` package to ensure compatibility when installed as `clamui`:

```python
# CORRECT - relative imports (work in both development and installed)
from ..core.clipboard import copy_to_clipboard
from .view_helpers import create_empty_state

# WRONG - absolute src imports (break when installed)
from src.core.clipboard import copy_to_clipboard
```

The package is installed as `clamui`, not `src`. Absolute `src.*` imports only work during development but fail when installed via pip/deb/flatpak.

### Internationalization (i18n)

All user-facing strings must be translatable using gettext. The i18n module is at `src/core/i18n.py`.

**Import pattern:**

```python
from ..core.i18n import _, ngettext
```

**Simple strings:**

```python
label.set_text(_("Scan Complete"))
```

**Format strings (NEVER use f-strings inside `_()`):**

```python
# CORRECT
label.set_text(_("Found {count} threats").format(count=n))

# WRONG - xgettext cannot extract f-strings
label.set_text(_(f"Found {n} threats"))
```

**Plurals:**

```python
msg = ngettext("{n} file scanned", "{n} files scanned", count).format(n=count)
```

**Module-level constants (deferred translation):**

```python
from ..core.i18n import N_
ITEMS = [N_("Scan"), N_("Update")]  # Mark for extraction only
# At display time:
label.set_text(_(item))
```

**Do NOT translate:**

- Logger messages (`logger.debug/info/warning/error`)
- Developer-facing exception messages
- CSS class names, D-Bus paths, settings keys, technical identifiers
- Shell commands shown to users (e.g., `"sudo apt install clamav"`)

**After adding/changing translatable strings:**

Run `./scripts/update-pot.sh` to regenerate the POT template. To add a new language, see [`docs/TRANSLATING.md`](docs/TRANSLATING.md).

### Async Operations (GTK Thread Safety)

All long-running operations use background threads with `GLib.idle_add()` for UI updates:

```python
def scan_async(self, path: str, callback: Callable[[ScanResult], None]) -> None:
    def scan_thread():
        result = self.scan_sync(path)
        GLib.idle_add(callback, result)  # Schedule callback on main thread

    thread = threading.Thread(target=scan_thread, daemon=True)
    thread.start()
```

### Scanner Type System

Scanner results use a shared type system defined in `scanner_types.py`:

```python
from src.core.scanner_types import ScanStatus, ThreatDetail, ScanResult

# ScanStatus enum: CLEAN, INFECTED, ERROR, CANCELLED
# ThreatDetail dataclass for structured threat information
# ScanResult dataclass with computed properties (is_clean, has_threats)
```

### Threat Classification

Threats are classified by severity and category using `threat_classifier.py`:

```python
from ..core.threat_classifier import classify_threat_severity, categorize_threat, ThreatSeverity

severity = classify_threat_severity("Trojan.GenericKD")  # Returns ThreatSeverity.HIGH
category = categorize_threat("Trojan.GenericKD")          # Returns "Trojan"
# ThreatSeverity: CRITICAL, HIGH, MEDIUM, LOW
```

### Input Sanitization

Always sanitize user input before logging to prevent log injection attacks:

```python
from ..core.sanitize import sanitize_log_line, sanitize_log_text, sanitize_path_for_logging

# Removes ANSI escape sequences, control characters, Unicode bidirectional overrides
safe_output = sanitize_log_line(clamav_output)            # single line
safe_block = sanitize_log_text(multiline_clamav_output)   # multi-line variant
safe_path = sanitize_path_for_logging(user_provided_path)
```

### Path Validation

Validate paths before file operations, especially with user input:

```python
from ..core.path_validation import validate_path, check_symlink_safety

is_valid, error = validate_path(user_path)
is_safe, target = check_symlink_safety(symlink_path)
```

### Dataclasses for Results

Use `@dataclass` for structured data with properties for computed values:

```python
@dataclass
class ScanResult:
    status: ScanStatus
    infected_files: list[str]
    infected_count: int

    @property
    def is_clean(self) -> bool:
        return self.status == ScanStatus.CLEAN
```

### Error Handling Pattern

Return tuples of `(success: bool, error_or_value: Optional[str])`:

```python
def check_clamav_installed() -> Tuple[bool, Optional[str]]:
    # Returns (True, version_string) or (False, error_message)
```

### Flatpak Support

Commands that execute on the host system must be wrapped:

```python
from src.core.flatpak import wrap_host_command, is_flatpak

cmd = wrap_host_command(["clamscan", "--version"])
# In Flatpak: ['flatpak-spawn', '--host', 'clamscan', '--version']
# Native: ['clamscan', '--version']
```

Flatpak packaging does **not** bundle ClamAV. Flatpak builds require host `clamscan` and `freshclam`; daemon mode
also requires host `clamd`/`clamdscan`. Do not add `/app/bin` bundled-ClamAV fallbacks or sandbox database
assumptions. Keep ClamAV subprocesses and host config access behind `flatpak-spawn --host`.

Additional Flatpak utilities in `flatpak.py`:

- `which_host_command()` - Resolve host binaries from inside Flatpak
- `read_host_file()` - Read host config files from inside Flatpak
- `format_flatpak_portal_path()` - Format paths from Flatpak portal
- `get_clamav_database_dir()` / `ensure_freshclam_config()` - Legacy sandbox database/config helpers; do not use for new Flatpak ClamAV runtime paths

### GTK4 Widget Patterns

- Inherit from appropriate base class (`Gtk.Box`, `Adw.PreferencesWindow`, etc.)
- Use `gi.require_version()` before importing
- Set CSS classes via `add_css_class()`

### libadwaita Version Compatibility

Targets **libadwaita 1.1+** (Ubuntu 22.04 / Pop!\_OS 22.04 baseline). **Do not use APIs introduced after 1.1.** Runtime fallbacks for missing APIs live in `src/ui/compat.py`. The `adw-compat` skill has the exhaustive API migration reference.

| Avoid (1.2+)                     | Use instead (1.0+)                                                            |
| -------------------------------- | ----------------------------------------------------------------------------- |
| `Adw.PasswordEntryRow`           | `create_password_entry_row()` from `preferences/base.py`                      |
| `Adw.SpinRow`                    | `create_spin_row()` from `preferences/base.py` (returns `(row, spin_button)`) |
| `Adw.Dialog` / `Adw.AlertDialog` | `Adw.Window` (see pattern below)                                              |

**Dialog pattern (`Adw.Window` + `set_content`/`set_default_size`/`close-request`):**

```python
class MyDialog(Adw.Window):
    def __init__(self, parent: Gtk.Window | None = None):
        super().__init__()
        self.set_title("Dialog Title")
        self.set_default_size(400, 300)   # not set_content_width/height
        self.set_modal(True)
        self.set_deletable(True)          # not set_can_close
        self.set_content(content_widget)  # not set_child
        if parent:
            self.set_transient_for(parent)
        self.connect("close-request", self._on_close_request)  # not "closed"
```

Present with `dialog.set_transient_for(parent); dialog.present()` — **not** `dialog.present(parent)` (that's 1.5+).

**Compatibility helpers (`src/ui/preferences/base.py`):**

```python
from .base import create_password_entry_row, create_spin_row

api_key_row = create_password_entry_row("API Key")
row, spin_button = create_spin_row(title="Max File Size (MB)", min_val=0, max_val=4000, step=1)
widgets_dict["MaxFileSize"] = spin_button  # store SpinButton, not row
group.add(row)
```

### Icon Usage (Adwaita Only)

Always use standard Adwaita symbolic icons. Never use:

- Application-specific icons (e.g., `org.gnome.Nautilus-symbolic`)
- KDE/Breeze icons
- Non-standard icon names

**Safe Adwaita icons for common use cases:**

- File/folder: `folder-symbolic`, `folder-open-symbolic`
- Info: `dialog-information-symbolic`
- Warning: `dialog-warning-symbolic`
- Error: `dialog-error-symbolic`
- Settings: `preferences-system-symbolic`
- Security: `security-high-symbolic`, `security-medium-symbolic`

Reference: https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/named-icons.html

### Thread Locks

Use `threading.Lock()` for shared state in managers:

```python
class QuarantineManager:
    def __init__(self):
        self._lock = threading.Lock()

    def quarantine_file(self, path: str) -> QuarantineResult:
        with self._lock:
            # Thread-safe operations
```

### Modular Preferences Pattern

Preferences pages inherit from `PreferencesPageMixin`:

```python
from .base import PreferencesPageMixin

# create_page() is a @staticmethod for config-backed pages (DatabasePage,
# ScannerPage) or an instance method for simple settings pages
# (BehaviorPage, ExclusionsPage). The signature varies per page.
class DatabasePage(PreferencesPageMixin):
    @staticmethod
    def create_page(config_path, widgets_dict, parent_window=None) -> Adw.PreferencesPage:
        ...
```

### Reusable Export Dialog Pattern

Use `FileExportHelper` for file export dialogs:

```python
from src.ui.file_export import FileExportHelper, FileFilter

FileExportHelper.show_export_dialog(
    filters=[FileFilter(name="CSV Files", extension="csv")],
    initial_name="scan_results.csv",
    content_generator=lambda: format_results_as_csv(result),
    on_success=lambda: show_toast("Export successful")
)
```

### Pagination Pattern

Use `PaginatedListController` for large lists:

```python
from src.ui.pagination import PaginatedListController

controller = PaginatedListController(
    list_box=self.list_box,
    initial_limit=50,
    batch_size=50
)
controller.set_items(items, create_row_func)
```

### VirusTotal Integration Pattern

Use `VirusTotalClient` for threat analysis:

```python
from ..core.virustotal import VirusTotalClient, VTScanStatus

client = VirusTotalClient(api_key)
result = client.scan_file_sync(file_path)  # Handles rate limiting internally
# Async variant: client.scan_file_async(file_path, callback)

if result.status == VTScanStatus.DETECTED:
    print(f"Detections: {result.detections}/{result.total_engines}")
```

### Secure API Key Storage

Use the module-level functions in `keyring_manager` for secure credential storage (there is no `KeyringManager` class):

```python
from ..core.keyring_manager import get_api_key, set_api_key, delete_api_key

set_api_key(api_key)   # Stores the VirusTotal key in the system keyring
key = get_api_key()    # Returns the stored key or None
delete_api_key()       # Removes the stored key
# Each accepts an optional settings_manager arg enabling plaintext fallback when opted in.
```

## Testing Guidelines

### GTK Mocking (conftest.py)

Tests use centralized GTK mocking from `tests/conftest.py`:

```python
def test_something(mock_gi_modules):
    gtk = mock_gi_modules['gtk']
    from src.ui.some_view import SomeView
    # SomeView can be imported with mocked GTK
```

### Fixtures

- `tmp_path`: Pytest's temporary directory (use for file I/O tests)
- `eicar_file`: EICAR test file for antivirus testing
- `eicar_directory`: Directory with EICAR + clean files
- `mock_scanner`: Pre-configured Scanner mock

### Test File Naming

- Tests mirror source structure: `src/core/scanner.py` -> `tests/core/test_scanner.py`
- Preferences tests: `src/ui/preferences/scanner_page.py` -> `tests/ui/preferences/test_scanner_page.py`
- Prefix test methods with `test_`
- Use descriptive docstrings

### Coverage Requirements

- **Overall minimum**: 50% (fail_under in pyproject.toml)
- **Target coverage**: 80%+ for src/core, 70%+ for src/ui

## Key Modules Reference

### Scanner (`src/core/scanner.py`)

- Supports three backends: `"auto"`, `"daemon"`, `"clamscan"`
- Parses ClamAV exit codes: 0=clean, 1=infected, 2=error
- Uses `scanner_types.py` for result types
- Uses `threat_classifier.py` for threat classification
- Saves scan logs via `LogManager`

### Scanner Types (`src/core/scanner_types.py`)

- `ScanStatus` enum: CLEAN, INFECTED, ERROR, CANCELLED
- `ThreatDetail` dataclass: file_path, threat_name, category, severity
- `ScanResult` dataclass: status, path, infected_files, scanned_files, scanned_dirs, infected_count, threat_details, skipped_files/skipped_count, warning_message, error_message; properties `is_clean`, `has_threats`, `has_warnings`

### Threat Classifier (`src/core/threat_classifier.py`)

- `ThreatSeverity` enum: CRITICAL, HIGH, MEDIUM, LOW
- Pattern-based classification for 70+ threat types
- Category mapping (Trojan, Ransomware, Adware, etc.)
- `classify_threat_severity(name) -> ThreatSeverity` and `categorize_threat(name) -> str` functions

### VirusTotal Client (`src/core/virustotal.py`)

- `VirusTotalClient(api_key=None)` with API v3 support; `scan_file_sync(path)` and `scan_file_async(path, callback)`
- SHA256 hash lookups (`check_file_hash`) for known files
- File upload (`upload_file`) for unknown files; code constant `VT_MAX_FILE_SIZE` = 650 MB (standard `POST /files` caps at 32 MB, larger goes via `/files/upload_url`)
- Rate limiting: 4 requests/minute **and** 500 requests/day (free tier)
- Exponential backoff retry logic
- `VTScanStatus` enum: CLEAN, DETECTED, ERROR, PENDING, RATE_LIMITED, NOT_FOUND, FILE_TOO_LARGE
- `VTScanResult` dataclass: status, file_path, sha256, `detections`, `total_engines`, detection_details, scan_date, permalink, error_message, duration

### Sanitization (`src/core/sanitize.py`)

- `sanitize_log_line()` - Removes ANSI, control chars, null bytes (single line)
- `sanitize_log_text()` - Multi-line variant (sanitizes each line)
- `sanitize_path_for_logging()` - Safe path representation for logs
- Prevents log injection attacks
- Removes Unicode bidirectional overrides

### Path Validation (`src/core/path_validation.py`)

- `validate_path()` - Validates path existence and permissions
- `check_symlink_safety()` - Checks symlink targets
- `validate_dropped_files()` - Validates file manager drops (returns valid paths + errors)
- `get_path_info()` - Extracts file metadata

### ClamAV Detection (`src/core/clamav_detection.py`)

- `check_clamav_installed()` - Check installation and version
- `get_clamav_path()` / `get_freshclam_path()` - Locate host/native ClamAV executables
- `check_database_available()` - Check host/native virus database availability
- `check_clamd_connection()` - Test daemon connectivity

### Keyring Manager (`src/core/keyring_manager.py`)

- Secure storage using system keyring (GNOME Keyring, KWallet)
- Fallback to settings.json when keyring unavailable
- `get_api_key()`, `set_api_key()`, `delete_api_key()`

### Scheduler (`src/core/scheduler.py`)

- Detects systemd vs cron availability
- Creates systemd user timers or crontab entries
- Validates paths for injection attacks
- Uses `shlex.quote()` for safe command building

### System Audit (`src/core/system_audit.py` + `src/ui/audit_view.py`)

- Security-posture auditor surfaced by `AuditView` and the sidebar "Audit" entry
- Tier 1 `run_audit()`: ClamAV health, firewall, MAC framework, auto-updates, intrusion detection, SSH hardening, Portmaster
- Tier 2 `run_deep_audit()`: adds Lynis and chkrootkit scans
- Result types: `AuditStatus`, `AuditCategory`, `AuditCheckResult`, `AuditSectionResult`, `AuditReport`
- Optional Portmaster (safing.io) probe via `src/core/portmaster_client.py`

### ClamAV Config (`src/core/clamav_config.py`)

- Parser/writer for `clamd.conf` / `freshclam.conf` preserving comments and formatting
- `ClamAVConfig` (get/set/add/remove values, `to_string`), `parse_config()`, `write_config()`
- `write_config_with_elevation()` / `write_configs_with_elevation()` apply changes via a single `pkexec` call (allowlist enforced by `privileged_paths.py`)

### Device Monitor (`src/core/device_monitor.py`)

- `DeviceMonitor` (Gio.VolumeMonitor) drives USB/removable-media auto-scan
- `DeviceType` (REMOVABLE/EXTERNAL/NETWORK/INTERNAL/UNKNOWN), `MountInfo`

### Statistics Calculator (`src/core/statistics_calculator.py`)

- `StatisticsCalculator` aggregates scan history for `StatisticsView`
- `Timeframe` (DAILY/WEEKLY/MONTHLY/ALL), `ProtectionLevel`, `ScanStatistics`, `ProtectionStatus`

### QuarantineManager (`src/core/quarantine/manager.py`)

- Orchestrates `QuarantineDatabase` + `SecureFileHandler`
- Uses `ConnectionPool` for efficient database access
- Verifies file integrity via SHA-256 hashing
- Supports async operations with callbacks

### ProfileManager (`src/profiles/profile_manager.py`)

- Creates default profiles on first run (Quick Scan, Full Scan, Home Folder)
- Validates names, paths, and exclusion patterns
- Supports import/export with duplicate name handling

### ClamUIApp (`src/app.py`)

- Main `Adw.Application` class
- Manages view lifecycle and navigation
- Handles tray integration via subprocess (GIO D-Bus for SNI protocol)
- Implements start-minimized functionality

### Preferences System (`src/ui/preferences/`)

- `PreferencesWindow` - Main window orchestrating all pages
- `PreferencesPageMixin` - Base class with shared utilities
- Individual page classes for each settings category:
  - `BehaviorPage` — close behavior, notifications, tray
  - `DatabasePage` — freshclam settings
  - `ExclusionsPage` — exclusion patterns
  - `OnAccessPage` — on-access scanning
  - `ScannerPage` — clamd configuration
  - `ScheduledPage` — scheduled scans
  - `VirusTotalPage` — VirusTotal API setup
  - `DebugPage` — diagnostics, logging controls
  - `DeviceScanPage` — removable-device scan configuration
  - `SavePage` — save & apply with permission elevation

### UI Helpers (`src/ui/view_helpers.py`)

- `StatusLevel` enum for consistent styling
- `set_status_class()` for status banners
- `create_empty_state()` for empty list states
- Loading indicator helpers

### Pagination (`src/ui/pagination.py`)

- `PaginatedListController` class
- Configurable batch sizes and initial limits
- "Show More"/"Show All" controls
- Used by logs_view.py and quarantine_view.py

### File Export (`src/ui/file_export.py`)

- `FileExportHelper` class
- `FileFilter` dataclass for file type filters
- Async file selection with cancellation
- Error handling and toast notifications

## Configuration & Settings

### Settings Location

- XDG compliant: `~/.config/clamui/settings.json`
- Profiles: `~/.config/clamui/profiles.json`
- Quarantine DB: `~/.local/share/clamui/quarantine.db`
- Quarantine files: `~/.local/share/clamui/quarantine/`
- Logs: `~/.local/share/clamui/logs/`

### Key Settings

```json
{
  "scan_backend": "auto", // "auto", "daemon", "clamscan"
  "start_minimized": false,
  "minimize_to_tray": false,
  "notifications_enabled": true,
  "show_live_progress": true,
  "device_auto_scan_enabled": false,
  "exclusion_patterns": [] // Global exclusions
}
```

VirusTotal is configured via **Preferences → VirusTotal** (the API key lives in the system keyring), not via settings keys. `DEFAULT_SETTINGS` in `settings_manager.py` defines 34 keys total; see [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for the full list.

#### Scan Backend Options

`scan_backend` ∈ {`"auto"` (default), `"daemon"`, `"clamscan"`}. Auto prefers clamd when available (instant startup, parallel via `--multiscan`/`--fdpass`), falls back to clamscan (3–10 sec startup, always available). See [`docs/SCAN_BACKENDS.md`](docs/SCAN_BACKENDS.md) for performance tables, daemon setup, and troubleshooting.

## CI/CD Workflows

### test.yml

- Runs on **ubuntu-24.04 and ubuntu-22.04**, Python 3.11 / 3.12 / 3.13
- Uses xvfb for headless GTK testing
- Python 3.12 uploads `coverage.xml` (30-day retention); `fail_under` is 50
- Includes a libadwaita-1.1 compatibility test on ubuntu-22.04

### Other workflows

- **lint.yml** — ubuntu-22.04 / py3.12; `ruff check` + `ruff format`; blocks absolute `src.*` imports
- **build-appimage.yml** — ubuntu-24.04; builds AppImage + `.zsync` (7-day artifact); smoke tests; optional GPG signing on tags
- **build-flatpak.yml** — x86_64 (ubuntu-22.04) + aarch64 (ubuntu-24.04-arm); flathub-infra builder gnome-49; 7-day artifact
- **build-deb.yml** — ubuntu-22.04; runs `build-deb.sh`; optional `dpkg-sig`
- **build-all.yml** — manual dispatch; chains the deb/flatpak/appimage builds
- **release.yml** — on a `v*` tag, creates a draft release from `RELEASE_NOTES.md`
- **codeql.yml** — push/PR/weekly CodeQL analysis (Python)
- **i18n.yml** — on `po/**` changes, runs `check-translations.sh` + `check-potfiles.sh`
- **dependency-review.yml** — dependency review on PRs
- **dependency-audit.yml** — push/PR/weekly Python dependency vulnerability audit
- **deploy-website.yml** — builds and deploys the Astro marketing site (`website/`) to GitHub Pages on website changes, releases, and weekly

## Security Considerations

1. **Input Sanitization**: Use `sanitize_log_line()` before logging user/external input
2. **Path Validation**: Always validate paths with `validate_path()` before operations
3. **Symlink Safety**: Check symlinks with `check_symlink_safety()` before following
4. **Command Injection**: Use `shlex.quote()` for user-provided paths in shell commands
5. **Scheduler Security**: `_validate_target_paths()` checks for newlines/null bytes
6. **Quarantine Integrity**: SHA-256 hash verification before restore
7. **API Key Storage**: Use the `keyring_manager` module functions (`get_api_key`/`set_api_key`/`delete_api_key`) for secure credential storage
8. **Secrets**: Never commit `.env` files or credentials

## Common Tasks

### Adding a New View

1. Create `src/ui/new_view.py` inheriting from `Gtk.Box` or similar
2. Add a lazy `@property` for it in `ClamUIApp` (`src/app.py`) — views are **not** instantiated in `do_activate()`
3. Register a `show-<view>` action in `ViewCoordinator.setup_actions()` (`src/view_coordinator.py`) and add an `_on_show_<view>` callback in `app.py` (`_setup_actions()` delegates to `ViewCoordinator`)
4. Add a `("<id>", "<icon>-symbolic", N_("Label"))` tuple to `NAVIGATION_ITEMS` in `src/ui/sidebar.py`
5. Write tests in `tests/ui/test_new_view.py`

### Adding a Core Feature

1. Create module in `src/core/`
2. Use dataclasses for results, enums for statuses
3. Implement both sync and async methods
4. Add thread locks for shared state
5. Use `sanitize_log_line()` for any user/external input logging
6. Write comprehensive tests

### Adding a Preferences Page

1. Create `src/ui/preferences/new_page.py` inheriting from `PreferencesPageMixin`
2. Implement `create_page()` (an instance method, or `@staticmethod` for config-backed pages)
3. Add page instantiation in `PreferencesWindow.__init__()`
4. Write tests in `tests/ui/preferences/test_new_page.py`

### Modifying Scan Profiles

1. Default profiles defined in `ProfileManager.DEFAULT_PROFILES`
2. Validation in `_validate_profile()`, `_validate_targets()`, `_validate_exclusions()`
3. Storage in `ProfileStorage` using atomic file writes

## Debugging Tips

1. **GTK Issues**: Check `GLib.idle_add()` usage for thread safety
2. **Flatpak**: Test with `is_flatpak()` detection
3. **ClamAV Not Found**: Check `check_clamav_installed()` in `clamav_detection.py`
4. **Daemon Issues**: Verify clamd socket with `get_clamd_socket_path()`
5. **Test Failures**: Ensure `mock_gi_modules` fixture is used for UI tests
6. **VirusTotal Issues**: Check API key with `keyring_manager.get_api_key()`, verify rate limiting
7. **Sanitization Issues**: Check `sanitize.py` for character filtering

## Entry Points (pyproject.toml)

```toml
[project.scripts]
clamui = "src.main:main"
clamui-scheduled-scan = "src.cli.scheduled_scan:main"
clamui-apply-preferences = "src.cli.apply_preferences:main"
```

The `src/cli/` package uses a command router (`router.py`) whose `CLI_SUBCOMMANDS` dispatches 7 subcommands: `scan`, `quarantine`, `profile`, `status`, `history`, `help`, and `install-privileged-helper`. These map to `scan_cmd.py`, `quarantine_cmd.py`, `profile_cmd.py`, `status_cmd.py`, `history_cmd.py`, `help_cmd.py`, and `install_helper.py` (plus `output.py` helpers). `install_helper.py` registers `clamui install-privileged-helper`, which installs the `clamui-apply-preferences` wrapper plus the polkit policy (`io.github.linx_systems.ClamUI.policy`) so system ClamAV config writes can elevate via `pkexec`. To add a subcommand, create a `*_cmd.py` module and register it in `router.py`.

## Dependencies

Key runtime dependencies:

- `PyGObject>=3.56.3` / `pycairo>=1.29.0` - GTK4/Adwaita bindings (provided by system/GNOME runtime)
- `psutil>=7.2.2` - Battery status (scheduled-scan skip-on-battery)
- `matplotlib>=3.11.0` - Statistics view charts
- `requests>=2.34.2` / `urllib3>=2.7.0` / `certifi>=2026.6.17` - VirusTotal HTTP + TLS
- `keyring>=25.7.0` - Secure credential storage (VirusTotal API key)
- `Pillow>=12.2.0` - Tray icon generation (composite status badges)
- `cairosvg>=2.9.0` - SVG to PNG conversion for tray icons

**Build dependencies for Pillow (Ubuntu/Debian):**
```bash
sudo apt install libjpeg-dev zlib1g-dev
```

## Flatpak Development

### Flatpak Python Dependencies

Python dependencies for the Flatpak build are managed using:

- **Build dependencies**: `flatpak-pip-generator` from [flatpak-builder-tools](https://github.com/flatpak/flatpak-builder-tools/tree/master/pip)
- **Runtime dependencies**: `req2flatpak` (prefers binary wheels for faster builds)

**Files:**

- `flathub/requirements-build.txt` - Build dependencies (hatchling)
- `flathub/requirements-runtime.txt` - Runtime dependencies with minimum versions
- `flathub/requirements-runtime-pinned.txt` - Pinned versions for req2flatpak
- `flathub/python3-build-deps.json` - Generated build dependencies (commit to git)
- `flathub/python3-runtime-deps.json` - Generated runtime dependencies (commit to git)

**Note:** PyGObject and pycairo are provided by the GNOME runtime and excluded from generation.

### Flatpak-Specific Code

The `src/core/flatpak.py` module handles Flatpak-specific functionality:

- `is_flatpak()` - Detect if running in Flatpak sandbox
- `wrap_host_command()` - Wrap commands for host execution
- `which_host_command()` - Find host executables from inside Flatpak
- `read_host_file()` - Read host ClamAV config files from inside Flatpak

Flatpak ClamUI requires ClamAV on the host. The manifests must not compile or install ClamAV, `json-c`, or Rust SDK
extensions solely for ClamAV.

### Regenerating Flatpak Dependencies

When dependencies in `pyproject.toml` change:

```bash
# Install the generators
pipx install flatpak-pip-generator
pipx install req2flatpak

# Ensure the GNOME SDK is installed
flatpak install flathub org.gnome.Sdk//49

cd flathub/

# 1. Generate build dependencies (uses flatpak-pip-generator)
flatpak_pip_generator \
    --runtime='org.gnome.Sdk//49' \
    --requirements-file='requirements-build.txt' \
    --output='python3-build-deps' \
    --checker-data

# 2. Update requirements-runtime-pinned.txt with new versions
#    Then generate runtime dependencies for BOTH architectures (x86_64 and aarch64)
req2flatpak \
    -r requirements-runtime-pinned.txt \
    -t 313-x86_64 313-aarch64 \
    -o python3-runtime-deps.json
```

**Note:** The `-t` flag accepts multiple space-separated targets. Using `313-x86_64 313-aarch64` generates a single JSON file with architecture-specific entries for binary wheels and shared entries for pure Python wheels.

### Testing Flatpak Build

```bash
# Build the Flatpak
flatpak-builder --force-clean build-dir flathub/io.github.linx_systems.ClamUI.yml

# Run the built application
flatpak-builder --run build-dir flathub/io.github.linx_systems.ClamUI.yml clamui
```

## AppImage Development

### Prerequisites

```bash
# Install AppImage build tools (Ubuntu/Debian)
sudo apt install wget file patchelf desktop-file-utils libgdk-pixbuf2.0-dev
```

### Building an AppImage

```bash
# Run from project root
./appimage/build-appimage.sh
```

The script:
1. Creates a Python virtual environment with GTK4/libadwaita
2. Bundles all dependencies into an AppDir structure
3. Downloads and uses `linuxdeploy` + `linuxdeploy-plugin-gtk` for GTK runtime bundling
4. Produces `ClamUI-<version>-x86_64.AppImage` (~96 MB)

**Note:** The AppImage bundles Python and GTK4/libadwaita but requires ClamAV to be installed on the host system. ClamAV cannot be bundled as it requires system-level virus database updates.

### Testing the AppImage

```bash
# Make executable and run
chmod +x ClamUI-*-x86_64.AppImage
./ClamUI-*-x86_64.AppImage
```

See `appimage/build-appimage.sh` for detailed build configuration.

---

## Packaging Notes

- Flatpak uses `--filesystem=host` (read-write) for full scanning + quarantine operations and runs host ClamAV tools through `flatpak-spawn --host`.
- Debian packages require Python 3.11+.
- Flatpak and AppImage both require host ClamAV; neither should be treated as owning the virus database.
- `urllib3>=2.7.0` is pinned for CVE fix (decompression-bomb bypass on redirects).
- See [`RELEASE_NOTES.md`](RELEASE_NOTES.md) and [`SECURITY.md`](SECURITY.md) for historical security-hardening changes and current advisories.
