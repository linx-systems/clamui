# AGENTS.md - ClamUI AI Assistant Guide

> Big AI guide for repo. Claude Code, Cursor, Aider, Continue, Zed read dis too via AGENTS.md way. `CLAUDE.md` just stub point here - change dis file.

## Project Overview

ClamUI = Linux desktop app. Pretty face for ClamAV antivirus. Make with **PyGObject**, **GTK4**, **libadwaita** so GNOME happy.

**Key Facts:**

- Need Python 3.11+; GTK 4.6+, libadwaita 1.1+
- All package use host `clamscan` + `freshclam`; daemon mode also want host `clamd` + `clamdscan`. ClamUI never carry engine or database.
- Ship as Debian package, AppImage, Flatpak
- VirusTotal opt-in only
- Tongues: de, en, es, zh_CN, it, fr, pt_BR, hu (look `po/LINGUAS`)
- MIT license

## Repository Structure (top level)

```
clamui/
├── src/                    Application source - see local guides where listed below
│   ├── main.py             Application entry point
│   ├── app.py              Adw.Application (lifecycle, views, tray)
│   ├── cli/                CLI entry points + command router
│   ├── core/               Business logic, no UI dependencies
│   ├── profiles/           Scan profile management
│   └── ui/                 GTK4/Adwaita UI components
├── tests/                  Mirrors src/ (core/, ui/, profiles/, integration/, e2e/)
├── website/                Astro + Starlight site; docs source at `website/src/content/docs/docs/`
├── po/                     Translations (de, en, es, zh_CN, it, fr, pt_BR, hu) + POTFILES.in, clamui.pot
├── scripts/                Dev + packaging scripts (local-run, update-pot, nemo actions, hooks/)
├── appimage/               AppImage build (build-appimage.sh)
├── flathub/                Flatpak manifest + generated Python deps
├── debian/                 Debian packaging
├── data/                   Desktop integration (.desktop, nemo_action, metainfo.xml)
├── icons/                  Application icons
├── screenshots/            Canonical README and website screenshot sources
├── CODE_OF_CONDUCT.md      Community behavior and enforcement standards
├── CONTRIBUTING.md         Contributor workflow and pull-request guidance
└── pyproject.toml          Project config + dependencies
```

### Hierarchical context docs (read the nearest one before editing)

Local guide only for area below. Read right one before edit there; other dir follow dis root guide:

- [`src/core/AGENTS.md`](src/core/AGENTS.md) - brain layer (no UI dep)
- [`src/core/quarantine/AGENTS.md`](src/core/quarantine/AGENTS.md) - SQLite quarantine part
- [`src/ui/AGENTS.md`](src/ui/AGENTS.md) - GTK4/Adwaita UI layer
- [`src/ui/scan/AGENTS.md`](src/ui/scan/AGENTS.md) - scan-flow components; active view is [`src/ui/scan_view.py`](src/ui/scan_view.py)
- [`src/ui/preferences/AGENTS.md`](src/ui/preferences/AGENTS.md) - small preferences page

## Documentation

Truth docs live: [`website/src/content/docs/docs/`](website/src/content/docs/docs/), serve at
[`/docs/`](https://clamui.com/docs/).

| Source | Public page |
| --- | --- |
| [`contributing/architecture.md`](website/src/content/docs/docs/contributing/architecture.md) | [Tray architecture](https://clamui.com/docs/contributing/architecture/) |
| [`reference/configuration.md`](website/src/content/docs/docs/reference/configuration.md) | [Configuration](https://clamui.com/docs/reference/configuration/) |
| [`contributing/development.md`](website/src/content/docs/docs/contributing/development.md) | [Development](https://clamui.com/docs/contributing/development/) |
| [`installation.md`](website/src/content/docs/docs/installation.md) | [Installation](https://clamui.com/docs/installation/) |
| [`reference/scan-backends.md`](website/src/content/docs/docs/reference/scan-backends.md) | [Scan backends](https://clamui.com/docs/reference/scan-backends/) |
| [`contributing/signing.md`](website/src/content/docs/docs/contributing/signing.md) | [Signing](https://clamui.com/docs/contributing/signing/) |
| [`troubleshooting.md`](website/src/content/docs/docs/troubleshooting.md) | [Troubleshooting](https://clamui.com/docs/troubleshooting/) |
| [`contributing/translating.md`](website/src/content/docs/docs/contributing/translating.md) | [Translating](https://clamui.com/docs/contributing/translating/) |
| [`index.md`](website/src/content/docs/docs/index.md) | [User docs](https://clamui.com/docs/) |

Put tight Markdown/MDX under dat source tree, use root-relative `/docs/.../` link, + fix
Starlight sidebar in [`website/astro.config.mjs`](website/astro.config.mjs). Keep root
`README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` as GitHub door;
`CHANGELOG.md` + `RELEASE_NOTES.md` stay release food for MDX. No touch made-by-machine
`website/public/` asset or `website/dist/`.

Docs change? Run from `website/`: frozen Bun install, `bun run check`, `bun run build`;
then `python3 ../scripts/check-built-links.py dist`. Website CI do same check again.

### Community Documentation

- [`CONTRIBUTING.md`](CONTRIBUTING.md) = front door for helper: report bug, dev setup, validate, repo rule, PR want.
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) say how tribe behave + secret way to report bad act.
- [`SECURITY.md`](SECURITY.md) say secret way to report hole; never shout security bug in public GitHub issue.

### System Tray Subprocess Architecture

**Location**: [`website/src/content/docs/docs/contributing/architecture.md`](website/src/content/docs/docs/contributing/architecture.md)

ClamUI use subprocess for tray:

- **Main process** (GTK4): `ClamUIApp` + `TrayManager`
- **Subprocess** (GIO D-Bus): `TrayService` use StatusNotifierItem protocol + libdbusmenu
- **IPC**: JSON message over stdin/stdout pipe

Subprocess use pure GIO D-Bus (no GTK) for SNI protocol, with `Dbusmenu` (GLib API) for right-click menu. Doc hold:

- Runtime diagram show process wall + thread model
- Full IPC protocol spec (command, event, message shape)
- Sequence diagram for startup, status update, menu action
- How `app.py`, `tray_manager.py`, `tray_service.py`, `tray_icons.py` hold hands
- Security thought + fix-trouble guide

**When to reference this:**

- Build thing dat poke tray (status, progress, icon)
- Hunt IPC talk bug between main app + tray
- Learn why some op need thread-safe callback
- Touch tray code in `src/ui/tray_*.py`

## Development Commands

### Setup

```bash
# Install system dependencies (Ubuntu/Debian)
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
    libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev clamav

# Build dependencies for Pillow (tray icon support)
sudo apt install libjpeg-dev zlib1g-dev

# Install Python dependencies with uv
uv sync --locked --extra dev

# Install git hooks (REQUIRED)
./scripts/hooks/install-hooks.sh

# Run from source
uv run clamui
```

Want runtime-only local launch dat install distro dep? Use `./scripts/local-run.sh`.
Plain Ubuntu 22.04 / Pop!_OS 22.04 too old for source dep floor:
`PyGObject>=3.56.3` want GLib 2.80+, but those ship GLib 2.72. Use Flatpak there,
or dev where GLib new; UI code still aim GTK 4.6 + libadwaita 1.1.

**Important:** Pre-commit hook is **must** for dev. It block absolute `src.*` import dat break when ClamUI install as Debian package. Look [Import Conventions](#import-conventions-package-compatibility).

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

Important: Always run `uv run ruff format src/ tests/` + `uv run ruff check --fix` before commit so code stay same shape.

## Code Patterns & Conventions

### Import Conventions (Package Compatibility)

**Always use relative import** inside `src/` package so thing work when install as `clamui`:

```python
# CORRECT - relative imports (work in both development and installed)
from ..core.clipboard import copy_to_clipboard
from .view_helpers import create_empty_state

# WRONG - absolute src imports (break when installed)
from src.core.clipboard import copy_to_clipboard
```

Package install as `clamui`, not `src`. Absolute `src.*` import work only in dev, die when install via pip/deb/flatpak.

### Internationalization (i18n)

All string user see must translate with gettext. i18n module live `src/core/i18n.py`.

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

- Logger message (`logger.debug/info/warning/error`)
- Exception message for dev eye
- CSS class name, D-Bus path, settings key, tech name
- Shell command show to user (like `"sudo apt install clamav"`)

**After adding/changing translatable strings:**

Run `./scripts/update-pot.sh` to make POT template again. New tongue? Look
[`website/src/content/docs/docs/contributing/translating.md`](website/src/content/docs/docs/contributing/translating.md).

### Async Operations (GTK Thread Safety)

All slow work run in background thread + use `GLib.idle_add()` for UI poke:

```python
def scan_async(self, path: str, callback: Callable[[ScanResult], None]) -> None:
    def scan_thread():
        result = self.scan_sync(path)
        GLib.idle_add(callback, result)  # Schedule callback on main thread

    thread = threading.Thread(target=scan_thread, daemon=True)
    thread.start()
```

### Scanner Type System

Scanner result use shared type system in `src/core/scanner_types.py`. From other `src/core/`
module, import relative:

```python
from .scanner_types import ScanStatus, ThreatDetail, ScanResult

# ScanStatus enum: CLEAN, INFECTED, ERROR, CANCELLED
# ThreatDetail dataclass for structured threat information
# ScanResult dataclass with computed properties (is_clean, has_threats)
```

### Threat Classification

Threat sort by severity + category with `threat_classifier.py`:

```python
from ..core.threat_classifier import classify_threat_severity, categorize_threat, ThreatSeverity

severity = classify_threat_severity("Trojan.GenericKD")  # Returns ThreatSeverity.HIGH
category = categorize_threat("Trojan.GenericKD")          # Returns "Trojan"
# ThreatSeverity: CRITICAL, HIGH, MEDIUM, LOW
```

### Input Sanitization

Always clean user input before log, else log injection attack:

```python
from ..core.sanitize import sanitize_log_line, sanitize_log_text, sanitize_path_for_logging

# Removes ANSI escape sequences, control characters, Unicode bidirectional overrides
safe_output = sanitize_log_line(clamav_output)            # single line
safe_block = sanitize_log_text(multiline_clamav_output)   # multi-line variant
safe_path = sanitize_path_for_logging(user_provided_path)
```

### Path Validation

Check path before file op, most when user input:

```python
from ..core.path_validation import validate_path, check_symlink_safety

is_valid, error = validate_path(user_path)
is_safe, target = check_symlink_safety(symlink_path)
```

### Dataclasses for Results

Use `@dataclass` for shaped data, with property for computed value:

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

Give back tuple of `(success: bool, error_or_value: Optional[str])`:

```python
def check_clamav_installed() -> Tuple[bool, Optional[str]]:
    # Returns (True, version_string) or (False, error_message)
```

### Flatpak Support

Command dat run on host must wrap. From `src/core/` module:

```python
from .flatpak import wrap_host_command, is_flatpak

cmd = wrap_host_command(["clamscan", "--version"])
# In Flatpak: ['flatpak-spawn', '--host', 'clamscan', '--version']
# Native: ['clamscan', '--version']
```

Flatpak package **not** carry ClamAV. Flatpak build need host `clamscan` + `freshclam`; daemon mode
also need host `clamd`/`clamdscan`. No add `/app/bin` bundled-ClamAV fallback, no sandbox database
guess. Keep ClamAV subprocess + host config touch behind `flatpak-spawn --host`.

More Flatpak tool in `flatpak.py`:

- `which_host_command()` - Find host binary from inside Flatpak
- `read_host_file()` - Read host config file from inside Flatpak
- `format_flatpak_portal_path()` - Shape path from Flatpak portal
- `get_clamav_database_dir()` / `ensure_freshclam_config()` - Old sandbox database/config helper; no use for new Flatpak ClamAV runtime path

### GTK4 Widget Patterns

- Inherit right base class (`Gtk.Box`, `Adw.PreferencesWindow`, etc.)
- Use `gi.require_version()` before import
- Set CSS class with `add_css_class()`

### libadwaita Version Compatibility

Aim **libadwaita 1.1+** (Ubuntu 22.04 / Pop!\_OS 22.04 floor). **No use API born after 1.1.** Runtime fallback for missing API live in `src/ui/compat.py`. `adw-compat` skill hold full API migration reference.

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

Show with `dialog.set_transient_for(parent); dialog.present()` - **not** `dialog.present(parent)` (dat 1.5+).

**Compatibility helpers (`src/ui/preferences/base.py`):**

```python
from .base import create_password_entry_row, create_spin_row

api_key_row = create_password_entry_row("API Key")
row, spin_button = create_spin_row(title="Max File Size (MB)", min_val=0, max_val=4000, step=1)
widgets_dict["MaxFileSize"] = spin_button  # store SpinButton, not row
group.add(row)
```

### Icon Usage (Adwaita Only)

Always use plain Adwaita symbolic icon. Never use:

- App-own icon (like `org.gnome.Nautilus-symbolic`)
- KDE/Breeze icon
- Weird icon name

**Safe Adwaita icons for common use cases:**

- File/folder: `folder-symbolic`, `folder-open-symbolic`
- Info: `dialog-information-symbolic`
- Warning: `dialog-warning-symbolic`
- Error: `dialog-error-symbolic`
- Settings: `preferences-system-symbolic`
- Security: `security-high-symbolic`, `security-medium-symbolic`

Reference: https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/named-icons.html

### Thread Locks

Use `threading.Lock()` for shared state in manager:

```python
class QuarantineManager:
    def __init__(self):
        self._lock = threading.Lock()

    def quarantine_file(self, path: str) -> QuarantineResult:
        with self._lock:
            # Thread-safe operations
```

### Modular Preferences Pattern

Preferences page inherit `PreferencesPageMixin`:

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

Use `FileExportHelper` for file export dialog. From sibling UI module:

```python
from .file_export import FileExportHelper, FileFilter

FileExportHelper.show_export_dialog(
    filters=[FileFilter(name="CSV Files", extension="csv")],
    initial_name="scan_results.csv",
    content_generator=lambda: format_results_as_csv(result),
    on_success=lambda: show_toast("Export successful")
)
```

### Pagination Pattern

Use `PaginatedListController` for big list. From sibling UI module:

```python
from .pagination import PaginatedListController

controller = PaginatedListController(
    list_box=self.list_box,
    initial_limit=50,
    batch_size=50
)
controller.set_items(items, create_row_func)
```

### VirusTotal Integration Pattern

Use `VirusTotalClient` for threat look:

```python
from ..core.virustotal import VirusTotalClient, VTScanStatus

client = VirusTotalClient(api_key)
result = client.scan_file_sync(file_path)  # Handles rate limiting internally
# Async variant: client.scan_file_async(file_path, callback)

if result.status == VTScanStatus.DETECTED:
    print(f"Detections: {result.detections}/{result.total_engines}")
```

### Secure API Key Storage

Use module-level function in `keyring_manager` for safe secret keep (no `KeyringManager` class exist):

```python
from ..core.keyring_manager import get_api_key, set_api_key, delete_api_key

set_api_key(api_key)   # Stores the VirusTotal key in the system keyring
key = get_api_key()    # Returns the stored key or None
delete_api_key()       # Removes the stored key
```

Plaintext `settings.json` keep happen only when keyring dead **and** user
set `allow_plaintext_api_key_fallback` to `true` in `settings.json` by own hand.

## Testing Guidelines

### GTK Mocking (conftest.py)

Test use central GTK mock from `tests/conftest.py`. `src.*` import allowed in test:

```python
def test_navigation_sidebar_can_be_created(mock_gi_modules):
    from src.ui.sidebar import NavigationSidebar

    sidebar = NavigationSidebar()
    assert sidebar is not None
```

### Fixtures

- `tmp_path`: Pytest temp dir (use for file I/O test)
- `eicar_file`: EICAR test file for antivirus test
- `eicar_directory`: Dir with EICAR + clean file
- `mock_scanner`: Ready-made Scanner mock

### Test File Naming

- Test mirror source shape: `src/core/scanner.py` -> `tests/core/test_scanner.py`
- Preferences test: `src/ui/preferences/scanner_page.py` -> `tests/ui/preferences/test_scanner_page.py`
- Put `test_` in front of test method
- Write docstring dat say what happen

### Coverage Requirements

- **Overall minimum**: 50% (fail_under in pyproject.toml)
- **Target coverage**: 80%+ for src/core, 70%+ for src/ui

## Key Modules Reference

### Scanner (`src/core/scanner.py`)

- Hold three backend: `"auto"`, `"daemon"`, `"clamscan"`
- Read ClamAV exit code: 0=clean, 1=infected, 2=error
- Use `scanner_types.py` for result type
- Use `threat_classifier.py` for threat sort
- Save scan log via `LogManager`

### Scanner Types (`src/core/scanner_types.py`)

- `ScanStatus` enum: CLEAN, INFECTED, ERROR, CANCELLED
- `ThreatDetail` dataclass: file_path, threat_name, category, severity
- `ScanResult` dataclass: status, path, infected_files, scanned_files, scanned_dirs, infected_count, threat_details, skipped_files/skipped_count, warning_message, error_message; property `is_clean`, `has_threats`, `has_warnings`

### Threat Classifier (`src/core/threat_classifier.py`)

- `ThreatSeverity` enum: CRITICAL, HIGH, MEDIUM, LOW
- Pattern sort for 70+ threat kind
- Category map (Trojan, Ransomware, Adware, etc.)
- `classify_threat_severity(name) -> ThreatSeverity` + `categorize_threat(name) -> str` function

### VirusTotal Client (`src/core/virustotal.py`)

- `VirusTotalClient(api_key=None)` with API v3; `scan_file_sync(path)` + `scan_file_async(path, callback)`
- SHA256 hash look (`check_file_hash`) for known file
- File upload (`upload_file`) for unknown file; code constant `VT_MAX_FILE_SIZE` = 650 MB (plain `POST /files` stop at 32 MB, bigger go via `/files/upload_url`)
- Rate limit: 4 request/minute **and** 500 request/day (free tier)
- Backoff retry grow big
- `VTScanStatus` enum: CLEAN, DETECTED, ERROR, PENDING, RATE_LIMITED, NOT_FOUND, FILE_TOO_LARGE
- `VTScanResult` dataclass: status, file_path, sha256, `detections`, `total_engines`, detection_details, scan_date, permalink, error_message, duration

### Sanitization (`src/core/sanitize.py`)

- `sanitize_log_line()` - Rip out ANSI, control char, null byte (one line)
- `sanitize_log_text()` - Many-line kind (clean each line)
- `sanitize_path_for_logging()` - Safe path shape for log
- Stop log injection attack
- Rip out Unicode bidi override

### Path Validation (`src/core/path_validation.py`)

- `validate_path()` - Check path exist + permission
- `check_symlink_safety()` - Check where symlink point
- `validate_dropped_files()` - Check file manager drop (give back good path + error)
- `get_path_info()` - Pull file metadata

### ClamAV Detection (`src/core/clamav_detection.py`)

- `check_clamav_installed()` - Check install + version
- `get_clamav_path()` / `get_freshclam_path()` - Find host/native ClamAV binary
- `check_database_available()` - Check host/native virus database there
- `check_clamd_connection()` - Poke daemon

### Keyring Manager (`src/core/keyring_manager.py`)

- Safe keep with system keyring (GNOME Keyring, KWallet)
- Fall to settings.json when keyring gone
- `get_api_key()`, `set_api_key()`, `delete_api_key()`

### Scheduler (`src/core/scheduler.py`)

- Sniff systemd vs cron
- Make systemd user timer or crontab line
- Check path for injection attack
- Use `shlex.quote()` for safe command build

### System Audit (`src/core/system_audit.py` + `src/ui/audit_view.py`)

- Security-posture auditor show by `AuditView` + sidebar "Audit" entry
- Tier 1 `run_audit()`: ClamAV health, firewall, MAC framework, auto-update, intrusion detection, SSH hardening, Portmaster
- Tier 2 `run_deep_audit()`: add Lynis + chkrootkit scan
- Result type: `AuditStatus`, `AuditCategory`, `AuditCheckResult`, `AuditSectionResult`, `AuditReport`
- Maybe-Portmaster (safing.io) probe via `src/core/portmaster_client.py`

### ClamAV Config (`src/core/clamav_config.py`)

- Read/write `clamd.conf` / `freshclam.conf` keep comment + shape
- `ClamAVConfig` (get/set/add/remove value, `to_string`), `parse_config()`, `write_config()`
- `write_config_with_elevation()` / `write_configs_with_elevation()` push change with one `pkexec` call (allowlist guard by `privileged_paths.py`)

### Device Monitor (`src/core/device_monitor.py`)

- `DeviceMonitor` (Gio.VolumeMonitor) drive USB/removable auto-scan
- `DeviceType` (REMOVABLE/EXTERNAL/NETWORK/INTERNAL/UNKNOWN), `MountInfo`

### Statistics Calculator (`src/core/statistics_calculator.py`)

- `StatisticsCalculator` pile up scan history for `StatisticsView`
- `Timeframe` (DAILY/WEEKLY/MONTHLY/ALL), `ProtectionLevel`, `ScanStatistics`, `ProtectionStatus`

### QuarantineManager (`src/core/quarantine/manager.py`)

- Boss `QuarantineDatabase` + `SecureFileHandler`
- Use `ConnectionPool` for fast database touch
- Check file whole with SHA-256 hash
- Hold async op with callback

### ProfileManager (`src/profiles/profile_manager.py`)

- Make default profile on first run (Quick Scan, Full Scan, Home Folder)
- Check name, path, exclusion pattern
- Hold import/export + handle same-name clash

### Application and UI seams

- `ClamUIApp` (`src/app.py`) own life + lazy view; hand life, notification, tray event,
  nav to `AppLifecycleManager`, `NotificationDispatcher`, `TrayIntegration`, `ViewCoordinator`.
- `SettingsManager` = one seam for settings keep + listener; `LoggingConfig` set
  privacy-aware debug log, `LogManager` own scan/update log.
- Keep privileged system-config write behind `core/privileged_helper.py`,
  `write_config_with_elevation()` / `write_configs_with_elevation()`, + installed polkit helper.
- Active scan screen is `src/ui/scan_view.py` (`ScanView`), which `src/app.py` loads. Add
  `src/ui/scan/` components only when wired into that active view; send scan run through
  `ScanController`, tray-drive orchestration through `ScanCoordinator`.

### Preferences System (`src/ui/preferences/`)

- `PreferencesWindow` - Main window boss all page
- `PreferencesPageMixin` - Base class with shared tool
- One page class per settings group:
  - `BehaviorPage` - close behavior, notification, tray
  - `DatabasePage` - freshclam settings
  - `ExclusionsPage` - exclusion pattern
  - `OnAccessPage` - on-access scan
  - `ScannerPage` - clamd config
  - `ScheduledPage` - scheduled scan
  - `VirusTotalPage` - VirusTotal API setup
  - `DebugPage` - diagnostic, log control
  - `DeviceScanPage` - removable-device scan config
  - `SavePage` - save & apply with permission lift

### UI Helpers (`src/ui/view_helpers.py`)

- `StatusLevel` enum for same-look style
- `set_status_class()` for status banner
- `create_empty_state()` for empty list
- Loading spinner helper

### Pagination (`src/ui/pagination.py`)

- `PaginatedListController` class
- Batch size + first limit tunable
- "Show More"/"Show All" control
- Used by logs_view.py + quarantine_view.py

### File Export (`src/ui/file_export.py`)

- `FileExportHelper` class
- `FileFilter` dataclass for file type filter
- Async file pick with cancel
- Error handle + toast notification

## Configuration & Settings

Settings, profile, data sit in XDG place:

- Settings + profile: `$XDG_CONFIG_HOME/clamui/{settings,profiles}.json` (default `~/.config`)
- Quarantine database + file: `$XDG_DATA_HOME/clamui/quarantine{.db,/}` (default `~/.local/share`);
  explicit `quarantine_directory` setting beat file dir.
- Scan/update log: `$XDG_DATA_HOME/clamui/logs/`; debug log: `$XDG_DATA_HOME/clamui/debug/`.

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

UI label for `start_minimized` is **Start in System Tray**. Normal launch start tray subprocess
then hide; launch with scan target stay visible. StatusNotifierWatcher register async,
so doc must tell user to eyeball dat desktop show icon before trust background startup.

VirusTotal opt-in, set via **Preferences → VirusTotal**. API key use system keyring
by default; plaintext settings fall need user say yes loud. Look
[`/docs/reference/configuration/`](https://clamui.com/docs/reference/configuration/) for full `DEFAULT_SETTINGS` reference.

#### Scan Backend Options

`scan_backend` ∈ {`"auto"` (default), `"daemon"`, `"clamscan"`}. Auto like clamd daemon when there
else use `clamscan`; daemon mode need `clamd` + `clamdscan`. Look
[`/docs/reference/scan-backends/`](https://clamui.com/docs/reference/scan-backends/) for setup + fix-trouble.

## CI/CD Workflows

### test.yml

- Run on **ubuntu-24.04 + ubuntu-22.04**, Python 3.11–3.14
- Use xvfb for headless GTK test
- Python 3.12 upload `coverage.xml` (30-day keep); `fail_under` is 50
- Hold libadwaita-1.1 compat test on ubuntu-22.04

### Other workflows

- **lint.yml** - ubuntu-22.04 / py3.12; `ruff check` + `ruff format`; block absolute `src.*` prod import
- **build-appimage.yml** - ubuntu-24.04; build AppImage + `.zsync` (7-day artifact); smoke test; maybe GPG sign on tag
- **build-flatpak.yml** - x86_64 (ubuntu-22.04) + aarch64 (ubuntu-24.04-arm); flathub-infra builder GNOME 51; 7-day artifact
- **build-deb.yml** - ubuntu-22.04; build `clamui_<version>_all.deb` + matching
  `clamui-privileged-helper_<version>_all.deb`, maybe sign both with `dpkg-sig`
- **build-all.yml** - hand-push dat call Debian, Flatpak, AppImage reusable workflow
- **release.yml** - on `v*` tag, call Debian workflow with inherited sign secret, then make
  draft release from `RELEASE_NOTES.md` with both Debian artifact
- **codeql.yml** - push/PR/weekly CodeQL look (Python)
- **i18n.yml** - on `po/**` change, run `check-translations.sh` + `check-potfiles.sh`
- **dependency-review.yml** - dependency review on PR
- **dependency-audit.yml** - push/PR/weekly Python dependency hole audit
- **deploy-website.yml** - use Bun to copy source asset + build `website/`, then push `website/dist` to
  GitHub Pages on `master` push dat matter (`website/`, `screenshots/`, `icons/`), published release, + weekly

## Security Considerations

1. **Input Sanitization**: Use `sanitize_log_line()` before log user/outside input
2. **Path Validation**: Always check path with `validate_path()` before op
3. **Symlink Safety**: Check symlink with `check_symlink_safety()` before follow
4. **Command Injection**: Use `shlex.quote()` for user path in shell command
5. **Scheduler Security**: `_validate_target_paths()` hunt newline/null byte
6. **Quarantine Integrity**: SHA-256 hash check before restore
7. **API Key Storage**: Use `keyring_manager` module function (`get_api_key`/`set_api_key`/`delete_api_key`) for safe secret keep
8. **Secrets**: Never commit `.env` file or credential

## Common Tasks

### Updating Website Screenshots

Root `screenshots/` = truth. `screenshots/ClamUI-Social-Preview-1280x640.png` = the
one true README hero + website social-card source. Fix website asset-copy/metadata when need, but
no hand-edit made-by-machine `website/public/` copy or `website/dist/`.

### Adding a New View

1. Make `src/ui/new_view.py` inherit `Gtk.Box` or like.
2. Add lazy `@property` in `ClamUIApp` (`src/app.py`); no build view in `do_activate()`.
3. Add its `show-<id>` action in `ViewCoordinator.setup_actions()` + `app.py` callback dat set
   lazy view as content + active view.
4. Add matching `("<id>", "<icon>-symbolic", N_("Label"))` sidebar tuple; `MainWindow` fire
   `show-<id>` from dat ID.
5. Write test in `tests/ui/test_new_view.py`.

### Adding a Core Feature

1. Make module in `src/core/`
2. Use dataclass for result, enum for status
3. Give both sync + async method
4. Add thread lock for shared state
5. Use `sanitize_log_line()` for any user/outside input log
6. Write big test pile

### Adding a Preferences Page

1. Make `src/ui/preferences/new_page.py` inherit `PreferencesPageMixin`; copy config-backed
   static `create_page()` or simple-settings instance `create_page()` template.
2. Import it in `src/ui/preferences/window.py`, add its sidebar tuple, + register lazy factory in
   `_page_factories`.
3. Keep load model same: only `BehaviorPage` eager; new page born on first nav.
4. Write test in `tests/ui/preferences/test_new_page.py`.

### Modifying Scan Profiles

1. Default profile live in `ProfileManager.DEFAULT_PROFILES`
2. Check in `_validate_profile()`, `_validate_targets()`, `_validate_exclusions()`
3. Keep in `ProfileStorage` with atomic file write

## Debugging Tips

1. **GTK Issues**: Look `GLib.idle_add()` use for thread safe
2. **Flatpak**: Test with `is_flatpak()` sniff
3. **ClamAV Not Found**: Look `check_clamav_installed()` in `clamav_detection.py`
4. **Daemon Issues**: Check clamd socket with `get_clamd_socket_path()`
5. **Test Failures**: Make sure `mock_gi_modules` fixture used for UI test
6. **VirusTotal Issues**: Check API key with `keyring_manager.get_api_key()`, check rate limit
7. **Sanitization Issues**: Look `sanitize.py` for char filter

## Entry Points (pyproject.toml)

```toml
[project.scripts]
clamui = "src.main:main"
clamui-scheduled-scan = "src.cli.scheduled_scan:main"
```

`src/cli/` package use command router (`router.py`) whose `CLI_SUBCOMMANDS` throw 7 subcommand:
`scan`, `quarantine`, `profile`, `status`, `history`, `help`, `install-privileged-helper`. These map to
matching `*_cmd.py` module (plus `output.py` helper). `clamui-scheduled-scan` on purpose separate
headless entry for systemd timer or cron; it no pass dat router, no start GTK.
`install_helper.py` register `clamui install-privileged-helper`, which install root-own
`/usr/bin/clamui-apply-preferences` wrapper + polkit policy
(`io.github.linx_systems.ClamUI.policy`) so system ClamAV config write can lift via `pkexec`;
privileged wrapper on purpose not Python project entry point.

## Dependencies

`pyproject.toml` = truth for runtime dependency; keep its security floor:
`urllib3>=2.8.0` + `certifi>=2026.7.22`. Python 3.11+, `PyGObject>=3.56.3` want
GLib 2.80+ for source work; packaged UI support still aim GTK 4.6+ + libadwaita 1.1+.

Tray SVG fallback uses the native GdkPixbuf librsvg loader lazily, then Pillow stacks its badge.
Do not add CairoSVG. Package that loader: Debian needs `gir1.2-gdkpixbuf-2.0` +
`librsvg2-common`; AppImage carries `libpixbufloader-svg.so` + `librsvg-2.so.2`; Flatpak builds
install checked-in [`icons/io.github.linx_systems.ClamUI.png`](icons/io.github.linx_systems.ClamUI.png).
When its SVG changes, regenerate that PNG once and commit both; see the [Development guide](https://clamui.com/docs/contributing/development/).

**Build dependencies for Pillow (Ubuntu/Debian):**
```bash
sudo apt install libjpeg-dev zlib1g-dev
```

## Flatpak Development

### Flatpak Python Dependencies

Python dep born from locked requirement:

- `flathub/requirements-build.txt` → committed `flathub/python3-build-deps.json`
  via `flatpak-pip-generator`.
- `flathub/requirements-runtime.txt` = looked-at floor list; locked export make
  `flathub/requirements-runtime-pinned.txt`, then committed `flathub/python3-runtime-deps.json`
  via `req2flatpak`.

PyGObject + pycairo come from GNOME, so generation leave them out. Keep generated source change
with their input requirement + aim both runtime arch.

### Flatpak-Specific Code

`src/core/flatpak.py` module do Flatpak-only work:

- `is_flatpak()` - Sniff if inside Flatpak sandbox
- `wrap_host_command()` - Wrap command for host run
- `which_host_command()` - Find host binary from inside Flatpak
- `read_host_file()` - Read host ClamAV config file from inside Flatpak

Flatpak ClamUI want ClamAV on host. Manifest must not compile or install ClamAV, `json-c`, or Rust SDK
extension just for ClamAV.

### Regenerating Flatpak Dependencies

Runtime dep change? Fix locked requirement + make both committed JSON file again:

```bash
# Install generators
pipx install flatpak-pip-generator
pipx install req2flatpak

# Ensure GNOME 51 SDK is installed
flatpak install flathub org.gnome.Sdk//51

cd flathub/

# Build dependencies
flatpak_pip_generator \
    --runtime='org.gnome.Sdk//51' \
    --requirements-file='requirements-build.txt' \
    --output='python3-build-deps' \
    --checker-data

# Runtime dependencies for x86_64 and aarch64
req2flatpak \
    -r requirements-runtime-pinned.txt \
    -t 314-x86_64 314-aarch64 \
    -o python3-runtime-deps.json
```

GNOME 51 give Python 3.14.7; use both `314-x86_64` + `314-aarch64`, not host Python
version, so binary wheel + pure-Python dep share one made file.

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

Script do dis:
1. Make Python venv with GTK4/libadwaita
2. Stuff all dep into AppDir shape
3. Grab + use `linuxdeploy` + `linuxdeploy-plugin-gtk` for GTK runtime bundle
4. Spit out `ClamUI-<version>-x86_64.AppImage` (~96 MB)

**Note:** AppImage carry Python + GTK4/libadwaita but want ClamAV on host. ClamAV no can bundle, it need system-level virus database update.

### Testing the AppImage

```bash
# Make executable and run
chmod +x ClamUI-*-x86_64.AppImage
./ClamUI-*-x86_64.AppImage
```

Look `appimage/build-appimage.sh` for deep build config.

---

## Packaging Notes

- Flatpak use `--filesystem=host` (read-write) for full scan + quarantine op, and run host ClamAV tool through `flatpak-spawn --host`.
- Every format need host ClamAV, own no engine, own no virus database: `clamscan` +
  `freshclam` must; daemon mode also need `clamd` + `clamdscan`.
- Debian artifact arch-free: `clamui_<version>_all.deb` + matching
  `clamui-privileged-helper_<version>_all.deb`; install both together.
- `urllib3>=2.7.0` pinned for CVE fix (decompression-bomb bypass on redirect).
- Look [`RELEASE_NOTES.md`](RELEASE_NOTES.md) + [`SECURITY.md`](SECURITY.md) for old security-hardening change + current advisory.