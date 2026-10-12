---
title: Review logs and history
description: Inspect scan and update records, daemon output, and exports.
---

Open **Logs** and select **Historical Logs**. Entries are newest first and initially paginate in groups of 25. Each has an operation type, status, target, timestamp, duration, summary, and full output.

## Work with records

Select an entry to copy it or export it as text, CSV, or JSON. **Export all** writes only the currently loaded entries, so choose **Show All** before an archive export. `clean`, `infected`, `error`, and update outcomes describe the recorded ClamAV operation; scheduled scans can be inferred from their regular timestamps.

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