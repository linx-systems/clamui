# core/ — Business Logic Layer

30 modules. No UI dependencies. All scanning, configuration, security, and system integration.

Parent: [`../../AGENTS.md`](../../AGENTS.md) | Sub: [`quarantine/AGENTS.md`](quarantine/AGENTS.md)

## Structure

```
core/
├── scanner.py / scanner_base.py / daemon_scanner.py  # Scan orchestration
├── clamav_detection.py   # ClamAV/freshclam/clamdscan detection + socket probe
├── scanner_types.py      # ScanStatus, ScanResult, ThreatDetail dataclasses
├── threat_classifier.py  # Severity/category classification (70+ patterns)
├── log_manager.py        # Scan history persistence
├── updater.py            # freshclam database updates
├── scheduler.py          # systemd/cron scheduled scans
├── system_audit.py       # Security-posture auditor (Tier-1/Tier-2)
├── clamav_config.py      # clamd.conf/freshclam.conf parse + write
├── privileged_paths.py   # pkexec allowlist validators (apply-prefs)
├── portmaster_client.py  # Optional Portmaster audit client
├── settings_manager.py   # JSON settings (XDG_CONFIG_HOME)
├── notification_manager.py / battery_manager.py / device_monitor.py
├── virustotal.py         # VirusTotal API v3 + rate limiting
├── statistics_calculator.py  # Scan statistics + protection status
├── result_formatters.py  # Format scan results as text/CSV
├── file_manager_integration.py  # Nemo/Nautilus/Dolphin context menus
├── keyring_manager.py    # System keyring with fallback
├── flatpak.py            # Flatpak detection + host command wrapping
├── sanitize.py           # Log injection prevention
├── path_validation.py    # Symlink safety + path traversal prevention
├── app_context.py        # Service locator with lazy init
├── i18n.py / utils.py / logging_config.py / clipboard.py
└── quarantine/           # SQLite quarantine subsystem → quarantine/AGENTS.md
```

## Key Patterns

### Sync/Async Pair (MANDATORY for long-running ops)
Every operation exposes `operation_sync()` (blocks) and `operation_async()` (spawns daemon thread + `GLib.idle_add(callback)`). Used in Scanner, Updater, QuarantineManager, VirusTotalClient, LogManager.

### Cancellation
`threading.Event()` — call `.set()` to cancel, `.clear()` at start of new operation. Use `communicate_with_cancel_check()` from `scanner_base.py` instead of `process.wait()`.

### Error Returns
`(success: bool, error_message: Optional[str])` tuples — no custom exceptions. Operations return dataclass results with `status` enum + `error_message` field.

### Type System
- `@dataclass` with `@property` for computed values (e.g., `ScanResult.is_clean`)
- Enum statuses: `ScanStatus`, `UpdateStatus`, `QuarantineStatus` (string values, lowercase)
- `TYPE_CHECKING` + lazy imports to break circular dependencies

### Security Audit & ClamAV Config (v0.2.0 subsystems)
- `system_audit.py`: security-posture auditor. `run_audit()` (Tier 1: ClamAV health, firewall, MAC framework, auto-updates, intrusion detection, SSH hardening, Portmaster) and `run_deep_audit()` (Tier 2: Lynis, chkrootkit). Returns `AuditReport` (`AuditSectionResult`/`AuditCheckResult`, `AuditStatus`, `AuditCategory`); surfaced by `ui/audit_view.py`.
- `clamav_config.py`: comment-preserving parser/writer for `clamd.conf`/`freshclam.conf` (`ClamAVConfig`, `parse_config`/`write_config`). System-path writes go through `write_config_with_elevation()` / `write_configs_with_elevation()` (pkexec). `privileged_paths.py` holds the pkexec allowlist validators (`PROTOCOL_VERSION=2`, `validate_destination`).

## Where to Look

| Task | Module | Notes |
|------|--------|-------|
| Add scan backend | `scanner.py`, `scanner_base.py` | Follow daemon_scanner.py pattern |
| Parse ClamAV output | `scanner_types.py`, `threat_classifier.py` | Dataclass + pattern-based classification |
| Add scheduled task | `scheduler.py` | Supports systemd + cron, validates injection |
| Store credentials | `keyring_manager.py` | System keyring with JSON fallback |
| Add settings | `settings_manager.py` | Add to `DEFAULT_SETTINGS` dict |
| Subprocess commands | `flatpak.py` | `wrap_host_command()` + `shlex.quote()` |
| Edit ClamAV config | `clamav_config.py` | `write_config_with_elevation()` (single pkexec) |
| Add audit check | `system_audit.py` | `run_audit()` Tier-1 / `run_deep_audit()` Tier-2 |

## Anti-Patterns (core-specific)

- **Blocking main thread**: Never call `scan_sync()` from UI — use `scan_async()`
- **`process.wait()`**: Use `communicate_with_cancel_check()` — supports cancellation
- **Forgetting cancel reset**: Always `self._cancel_event.clear()` at start of sync methods
- **Flatpak ClamAV ownership**: Flatpak uses host ClamAV via `flatpak-spawn --host`; do not add bundled `/app/bin` ClamAV or sandbox database assumptions
- **Unsanitized logging**: All user/external input through `sanitize_log_line()` or `sanitize_log_text()`
- **Missing Flatpak wrap**: All subprocess calls need `wrap_host_command()` in Flatpak

## Common Imports

```python
from .scanner_types import ScanResult, ScanStatus, ThreatDetail
from .sanitize import sanitize_log_line, sanitize_log_text
from .path_validation import validate_path, check_symlink_safety
from .flatpak import is_flatpak, wrap_host_command
from .i18n import _, ngettext
```
