---
title: Configuration reference
description: Settings files, JSON keys, scan profiles, and host ClamAV boundaries.
---

ClamUI creates settings on first launch. Most Preferences pages save application settings immediately; **Scheduled Scans** needs **Save & Apply** to persist settings and provision its timer or cron job. Direct JSON changes take effect after restart. Validate direct edits before restarting:

```bash
python3 -m json.tool ~/.config/clamui/settings.json
```

## Locations

| Data | Native default | Flatpak default |
| --- | --- | --- |
| Settings | `~/.config/clamui/settings.json` | `~/.var/app/io.github.linx_systems.ClamUI/config/clamui/settings.json` |
| Profiles | `~/.config/clamui/profiles.json` | `~/.var/app/io.github.linx_systems.ClamUI/config/clamui/profiles.json` |
| Quarantine database | `~/.local/share/clamui/quarantine.db` | `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/quarantine.db` |
| Quarantine files | `~/.local/share/clamui/quarantine/` | `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/quarantine/` |
| Logs | `~/.local/share/clamui/logs/` | `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/logs/` |

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` change native base paths. In Flatpak they apply inside the sandbox. Back up both directories, not only `settings.json`:

```bash
tar -czf clamui-backup.tar.gz "${XDG_CONFIG_HOME:-$HOME/.config}/clamui" "${XDG_DATA_HOME:-$HOME/.local/share}/clamui"
```

## Application settings

| Key | Default | Meaning |
| --- | --- | --- |
| `privileged_helper_prompt_skipped_version` | `""` | Internal record of the helper-version prompt; do not hand-edit. |
| `language` | `"auto"` | `auto` uses system locale; otherwise an ISO code such as `de` or `zh_CN`; restart required. |
| `close_behavior` | `null` | `null` (first-run choice), `minimize`, `quit`, or `ask`. |
| `show_live_progress` | `true` | File-by-file progress during scans. |
| `start_minimized` | `false` | Start ordinary launches in a working system tray; target-path launches stay visible. |
| `minimize_to_tray` | `false` | Make the window-manager minimize action hide to tray. |
| `notifications_enabled` | `true` | Desktop notifications for scans and updates. |
| `quarantine_directory` | `""` | Absolute storage directory for *new* quarantined files; empty uses the default. |
| `virustotal_api_key` | `null` | API key stored here only when the user explicitly permits plaintext fallback. |
| `allow_plaintext_api_key_fallback` | `false` | Permit the plaintext `virustotal_api_key` fallback when the system keyring is unavailable. |
| `virustotal_remember_no_key_action` | `"none"` | Missing-key behavior: `none`, `open_website`, or `prompt`. |

VirusTotal API keys use the system keyring when available. Plaintext fallback requires explicit consent; it is less private than the keyring. With no key, users can do nothing, open the API-key website, or be prompted according to `virustotal_remember_no_key_action`. Do not submit private files or hashes you are not authorized to share.

A custom quarantine directory must be writable. Files use randomized names and restrictive permissions; existing items do not move when it changes.

## Scheduled scans and exclusions

| Key | Default | Valid values / behavior |
| --- | --- | --- |
| `scheduled_scans_enabled` | `false` | Master switch for user systemd timer or cron. |
| `schedule_frequency` | `"weekly"` | `hourly`, `daily`, `weekly`, or `monthly`. |
| `schedule_time` | `"02:00"` | Local 24-hour `HH:MM`; hourly scans run at minute zero and ignore this value. |
| `schedule_targets` | `[]` | Absolute target directories; empty means no scan. |
| `schedule_skip_on_battery` | `true` | Skip when on battery. |
| `schedule_auto_quarantine` | `false` | Isolate detections automatically; review this risk. |
| `schedule_day_of_week` | `0` | Weekly only: `0` Monday through `6` Sunday. |
| `schedule_day_of_month` | `1` | Monthly only: `1` through `28`. |
| `exclusion_patterns` | common development directories | Enabled records with `pattern`, `type` (`directory`, `file`, or `pattern`), and `enabled`. |

The shipped exclusions cover `node_modules`, `.git`, `.venv`, `build`, `dist`, and `__pycache__`. Exclusions apply to manual and scheduled scans. Do not exclude all targets, Downloads, or documents without a security reason.

## Scan backend and diagnostics

| Key | Default | Valid values / behavior |
| --- | --- | --- |
| `scan_backend` | `"auto"` | `auto` prefers a reachable daemon and falls back to `clamscan`; `daemon` requires it; `clamscan` is standalone. |
| `daemon_socket_path` | `""` | Empty auto-detects; otherwise an absolute socket path. |
| `clamd_conf_path` | `""` | Empty auto-detects; otherwise a custom `clamd.conf`. |
| `freshclam_conf_path` | `""` | Empty auto-detects; otherwise a custom `freshclam.conf`. |
| `debug_log_level` | `"WARNING"` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `debug_log_max_size_mb` | `5` | Debug log rotation size in MB. |
| `debug_log_max_files` | `3` | Number of rotated debug files to retain. |

Auto-detection reads configured `LocalSocket` then tries `/var/run/clamav/clamd.ctl`, `/run/clamav/clamd.ctl`, `/run/clamd.scan/clamd.sock`, and `/var/run/clamd.scan/clamd.sock`.

## Mounted-device scans

| Key | Default | Valid values / behavior |
| --- | --- | --- |
| `device_auto_scan_enabled` | `false` | Monitor mount events and scan selected devices. |
| `device_auto_scan_types` | `["removable", "external"]` | Any of `removable`, `external`, `network`. |
| `device_auto_scan_notify` | `true` | Notify about device scans. |
| `device_auto_scan_max_size_gb` | `32` | Maximum device size; `0` is unlimited. |
| `device_auto_scan_delay_seconds` | `3` | Delay after mount; `0`–`60`. |
| `device_auto_scan_auto_quarantine` | `false` | Quarantine a device-scan detection automatically. |
| `device_auto_scan_skip_on_battery` | `true` | Skip device scans on battery. |

## Profiles file format

`profiles.json` is an array of profiles. Each profile needs an `id` UUID, unique 1–50-character `name`, non-empty `targets` array, `created_at` and `updated_at` ISO 8601 timestamps, and `is_default`. Optional `description` defaults to empty text, `exclusions` to `{}`, and `options` to `{}`.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Documents",
  "targets": ["~/Documents"],
  "exclusions": {
    "paths": ["~/.cache"],
    "patterns": ["*.tmp"]
  },
  "created_at": "2026-10-04T12:00:00+00:00",
  "updated_at": "2026-10-04T12:00:00+00:00",
  "is_default": false,
  "description": "Personal documents",
  "options": {}
}
```

Path exclusions match a resolved directory tree; pattern exclusions use filename globs. Built-in defaults are Quick Scan, Full Scan, and Home Folder. Default profiles cannot be deleted and are recreated when missing.

## Host ClamAV settings

**Database**, **Scanner**, and **On-Access** Preferences write host `freshclam.conf` and `clamd.conf`—including from the Flatpak. They never write sandbox copies. Saving requires the trusted matching `clamui-apply-preferences` helper and polkit policy; unavailable validation or installation fails closed without changing host configuration.

For an allowlisted root-only host config, select the **lock icon** on its **Configuration File** row in Preferences to request administrator access. It uses the installed trusted helper and polkit; it never changes ownership or permissions and shows helper-install guidance when unavailable.

New custom configuration files are created with mode `0600`. If you directly launch a ClamAV service as a non-root account, that account must own or have read access to its selected configuration file.

Database options are `DatabaseDirectory`, `UpdateLogFile`, `NotifyClamd`, `LogVerbose`, `LogSyslog`, `Checks` (0–50/day), `DatabaseMirror`, repeatable `DatabaseCustomURL`, and `HTTPProxyServer`, `HTTPProxyPort` (0–65535), `HTTPProxyUsername`, and `HTTPProxyPassword`. Proxy passwords are plaintext in `freshclam.conf`; use a dedicated least-privilege account.

The legacy Flatpak sandbox `freshclam.conf` is ignored. Database discovery and manual updates use the selected host configuration; a selected custom config is passed to the manual update with `--config-file` and does not claim to represent a running service's configuration.

Scanner options are `ScanPE`, `ScanELF`, `ScanOLE2`, `ScanPDF`, `ScanHTML`, `ScanArchive`, `MaxFileSize` and `MaxScanSize` (0–4000 MB), `MaxRecursion` (1–100), `MaxFiles` (0–1,000,000), `LogFile`, `LogVerbose`, and `LogSyslog`. Do not set unbounded archive/file limits on untrusted data: archive bombs can exhaust resources.

On-access options are `OnAccessIncludePath`, `OnAccessExcludePath`, `OnAccessPrevention`, `OnAccessExtraScanning`, `OnAccessDenyOnError`, `OnAccessDisableDDD`, `OnAccessMaxThreads` (1–64), `OnAccessMaxFileSize` (0–4000 MB), `OnAccessCurlTimeout` (0–3600 seconds), `OnAccessRetryAttempts` (0–10), `OnAccessExcludeUname`, `OnAccessExcludeUID` (0–65534), and `OnAccessExcludeRootUID`. Set exclusions for the scanner account before enabling monitoring to avoid scan loops. Large recursive trees may exceed the host inotify watch limit; start with a small path such as `~/Downloads` and consult the [ClamAV On-Access manual](https://docs.clamav.net/manual/OnAccess.html).

For task guidance, see [scan backends](/docs/reference/scan-backends/) and [settings](/docs/guides/settings/).