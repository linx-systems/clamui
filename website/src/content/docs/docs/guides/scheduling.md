---
title: Schedule scans
description: Automate recurring scans without losing control of detections.
---

Configure **Preferences → Scheduled Scans**, choose targets and a frequency, then use **Save & Apply**. ClamUI creates a user systemd timer where available, otherwise a cron job. It cannot run while the computer is off.

## Recommended setup

For most desktops, scan Downloads daily during an idle, plugged-in period and leave auto-quarantine off until you have reviewed your normal detections.

| Setting | Values |
| --- | --- |
| Frequency | `hourly`, `daily`, `weekly`, `monthly` |
| Time | 24-hour `HH:MM`; default `02:00`, ignored by hourly scans (which run at minute zero) |
| Weekly day | `0` Monday through `6` Sunday |
| Monthly day | `1` through `28` |
| Targets | absolute directories; empty means no scan |
| Skip on battery | default on |
| Auto-quarantine | default off; review its risk before enabling |

Scheduled scans are recursive. On laptops, battery skipping avoids unexpected power use. Auto-quarantine isolates a detection but can interrupt legitimate work; inspect Quarantine and Logs regularly when it is enabled.

## Check or test a schedule

```bash
clamui-scheduled-scan --dry-run
systemctl --user list-timers
crontab -l
```

A missing systemd user instance and missing cron leave no available scheduler. Use Logs to confirm scan results and update notifications. The scheduler is per-user and does not need administrator access.

On Debian package installations, ClamUI invokes `/usr/bin/clamui-scheduled-scan`; re-save a schedule after upgrading rather than manually repairing generated timer or cron commands.

For exact JSON keys and examples, see [Configuration](/docs/reference/configuration/).