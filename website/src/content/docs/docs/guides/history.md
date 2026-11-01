---
title: Review logs and history
description: Inspect scan and update records, daemon output, and exports.
---
Open **Logs** and select **Historical Logs**. Entries are newest first and the initial view loads up to 100 entries with pagination. Each has an operation type, status, target, timestamp, duration, summary, and full output. Timestamps in visible details use the application's localized display format; this does not change the canonical raw timestamp data used by **Copy** or text, CSV, and JSON exports.

The footer beneath the list shows how many loaded records have been revealed. **Load More** reveals the next 20 records; **Show All** reveals the whole currently loaded set, up to 100 records. These controls sit outside the list's own scroll area. Hover an action icon to read its label.

The status icon at the right of each record retains its existing status color. Hover it for the localized status name; assistive technology receives the same label.

## Work with records

Select an entry to copy it or export it as text, CSV, or JSON. **Copy** and all export formats retain the canonical raw timestamp data rather than the localized display date. **Export all** uses the complete historical-log set, not only the visible page. CSV contains timestamp, type, status, path, summary, and duration; JSON also contains IDs and details. `clean`, `infected`, `error`, and update outcomes describe the recorded ClamAV operation; scheduled scans are marked in the stored record.

Use the CLI for scripts:

```bash
clamui history --help
clamui history --json
```

Native logs are JSON files under `~/.local/share/clamui/logs/`; Flatpak logs are under `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/logs/`.

## Daemon output

The **ClamAV Daemon** tab displays live `clamd` log output when it is accessible. Missing or permission-denied logs can mean that the daemon is not running, logs only to journald, or your user cannot read its log group. ClamUI checks common `/var/log/clamav/` locations.

## Retention

**Clear All** permanently removes log history. Export incident evidence or records needed for compliance first. Manually deleting JSON files bypasses the UI confirmation and should be reserved for recovery.