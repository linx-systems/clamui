---
title: Configuration reference
description: XDG data, settings, profiles, and the protected host ClamAV boundary.
---

ClamUI preserves its existing settings, profile, log, quarantine, and debug data across the Rust/Tauri migration. Most application preferences save immediately. **Scheduled Scans** and host ClamAV configuration use **Save & Apply** because they can change both local settings and host state. Direct JSON edits take effect after restart; ensure the file remains a JSON object before restarting.

## Locations

| Data | Native default | Flatpak default |
| --- | --- | --- |
| Settings | `~/.config/clamui/settings.json` | `~/.var/app/io.github.linx_systems.ClamUI/config/clamui/settings.json` |
| Profiles | `~/.config/clamui/profiles.json` | `~/.var/app/io.github.linx_systems.ClamUI/config/clamui/profiles.json` |
| Logs | `~/.local/share/clamui/logs/` | `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/logs/` |
| Quarantine database and payloads | `~/.local/share/clamui/quarantine.db`, `quarantine/` | `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/` |
| Debug logs | `~/.local/share/clamui/debug/` | `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/debug/` |

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` change native base paths. In Flatpak they apply inside the sandbox. Back up both locations, not only `settings.json`:

```bash
tar -C "${XDG_CONFIG_HOME:-$HOME/.config}" -czf clamui-config-backup.tar.gz clamui
tar -C "${XDG_DATA_HOME:-$HOME/.local/share}" -czf clamui-data-backup.tar.gz clamui
```

## Application settings

The settings file is an object. ClamUI merges missing defaults, preserves unknown keys, normalizes old exclusion forms, and writes updates atomically. Important keys include:

| Key | Default | Meaning |
| --- | --- | --- |
| `language` | `"auto"` | Automatic system locale, or one of `de`, `en`, `es`, `fr`, `hu`, `it`, `nb`, `pt_BR`, or `zh_CN`; unsupported saved or system locales use English |
| `notifications_enabled` | `true` | Global application notifications |
| `minimize_to_tray` / `start_minimized` | `false` | Optional tray behavior |
| `close_behavior` | `null` | `unset`, `minimize`, `quit`, or `ask` |
| `scan_backend` | `"auto"` | `auto`, `clamd`, or `clamscan` |
| `daemon_socket_path` | `""` | Optional daemon socket override |
| `show_live_progress` | `true` | Detailed scan progress |
| `quarantine_directory` | `""` | Optional payload directory override |
| `debug_log_level` | `"WARNING"` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `debug_log_max_size_mb` | `5` | Positive whole MiB per active debug log; zero, missing, invalid, or overflowing values use 5 MiB |
| `debug_log_max_files` | `3` | Positive whole numbered-backup count; zero, missing, or invalid values use 3 |
| `virustotal_api_key` | `null` | Compatibility field; the system keyring is preferred |
| `allow_plaintext_api_key_fallback` | `false` | Explicitly permits less-private fallback storage |

VirusTotal API keys are not returned to the frontend in settings data. Do not submit private files or hashes that you are not authorized to share.

When a valid size is reached, the active debug log rotates and retains the configured number of numbered backups. Existing persisted retention settings are applied on every debug-log write.

## Scheduled scans and exclusions

| Key | Default | Behavior |
| --- | --- | --- |
| `scheduled_scans_enabled` | `false` | Enable the user schedule |
| `schedule_frequency` | `"weekly"` | `hourly`, `daily`, `weekly`, or `monthly` |
| `schedule_time` | `"02:00"` | 24-hour time; hourly uses minute zero |
| `schedule_targets` | `[]` | Saved scan targets |
| `schedule_skip_on_battery` | `true` | Skip on battery power |
| `schedule_auto_quarantine` | `false` | Quarantine detections automatically |
| `schedule_day_of_week` | `0` | Monday is 0 |
| `schedule_day_of_month` | `1` | Valid range 1–28 |

`exclusion_patterns` starts with enabled directory records for `node_modules`, `.git`, `.venv`, `build`, `dist`, and `__pycache__`. Exclusions apply to manual and scheduled scans. Use narrow exclusions; do not exclude all targets or documents merely to speed a scan.

## Scan backend and mounted devices

`auto` selects a reachable daemon and otherwise `clamscan`; `clamd` is daemon-only and `clamscan` never attempts the daemon. ClamUI checks a configured `LocalSocket` and common host socket locations. See [scan backends](/docs/reference/scan-backends/) for setup and troubleshooting.

Mounted-device settings are `device_auto_scan_enabled`, `device_auto_scan_types`, `device_auto_scan_notify`, `device_auto_scan_max_size_gb`, `device_auto_scan_delay_seconds`, `device_auto_scan_auto_quarantine`, and `device_auto_scan_skip_on_battery`. The defaults scan removable and external mounts only when the feature is enabled; the default size limit is 32 GiB and the default delay is three seconds.

## Profiles file format

`profiles.json` is normally an object with a version and a `profiles` array. The loader also accepts the previous bare array format. A profile records an `id` UUID, unique `name`, `created_at`, `updated_at`, `targets`, `exclusions`, `is_default`, optional `description`, and optional engine `options`.

```json
{
  "version": 1,
  "profiles": [
    {
      "id": "6e8bb20e-4a0a-4be9-94a0-0d24c4f960f2",
      "name": "Downloads",
      "targets": ["~/Downloads"],
      "exclusions": {"paths": [], "patterns": ["*.tmp"]},
      "is_default": false,
      "description": "New downloads",
      "options": {},
      "created_at": "2026-01-01T12:00:00+00:00",
      "updated_at": "2026-01-01T12:00:00+00:00"
    }
  ]
}
```

Built-in defaults are Quick Scan, Full Scan, and Home Folder. Their IDs are generated and persisted, not fixed constants. Imported profiles get a new ID and cannot become defaults.

## Host ClamAV settings

**Database**, **Scanner**, and **On-Access** Preferences target host `freshclam.conf` and `clamd.conf`, including from Flatpak. They never write sandbox copies. The native `/usr/bin/clamui-apply-preferences` helper and `io.github.linx_systems.ClamUI.policy` authorize only allowlisted host configurations through the compatible protocol-v4 boundary. On supported Debian-family and Fedora hosts, the local missing-helper diagnosis may show the explicit in-app offer without downloading release metadata. Automatic installation can complete only when matching signed published artifacts exist; before graphical Polkit authorization it verifies their signature, identity, version, size, digest, and compatible architecture, otherwise failing safely. Debian can use its signed same-version architecture-independent fallback only when no exact-architecture helper exists; Fedora requires the exact RPM. Untrusted existing helpers and unsupported hosts remain blocked, and missing trust, invalid input, or denied authorization fails closed without changing host configuration. See [installation](/docs/installation/#fedora-helper-rpm) for Fedora DNF and Atomic behavior.

**Save & Apply** validates the snapshot captured when you click it. Configuration files, schedule settings, and timer/cron changes are not one atomic operation: later failures can leave earlier groups durable. Review each reported durable group and failure before retrying.

### Recovering a failed configuration attempt

When a failed configuration **Save & Apply** has valid native file proposals, its report offers **See Configuration**. This read-only view shows each full `clamd.conf` or `freshclam.conf` destination and the exact content prepared for that failed attempt. Copy the path and configuration separately, then use an administrative editor with the permissions appropriate to that destination, such as `sudoedit /full/path/to/clamd.conf`.

The displayed content is a frozen failed-attempt snapshot, not a rendering of later preference edits. A helper failure may occur after writing one or more target files, so inspect each target before manually replacing it. Opening or copying from this view never applies a configuration, bypasses helper trust, or exposes application-settings JSON or VirusTotal data.

When ClamUI reads legacy Clamd size-unit values, it normalizes them in memory and marks the raw configuration for pending repair. Reading or startup never writes the host configuration or requests elevation. **Save & Apply** carries that repair even if the displayed values match the baseline; only a successful repair clears it, while a failed apply or a new-path draft remains safe to review and retry.

Database options include `DatabaseDirectory`, `UpdateLogFile`, `NotifyClamd`, `LogVerbose`, `LogSyslog`, `Checks`, `DatabaseMirror`, repeatable `DatabaseCustomURL`, and HTTP proxy fields. Scanner options include `ScanPE`, `ScanELF`, `ScanOLE2`, `ScanPDF`, `ScanHTML`, `ScanArchive`, `MaxFileSize`, `MaxScanSize`, `MaxRecursion`, `MaxFiles`, `LogFile`, `LogVerbose`, and `LogSyslog`. On-access options retain the existing include, exclude, prevention, extra-scanning, thread, size, timeout, retry, and UID directives.

New custom configuration files are owner-only. Avoid unbounded archive/file limits on untrusted data, and set on-access exclusions for the scanner account before enabling monitoring. For task guidance, see [scan backends](/docs/reference/scan-backends/) and [settings](/docs/guides/settings/).