---
title: Scan files and folders
description: Select targets, interpret results, and test detection safely.
---

## Start a scan

In **Scan**, add files or folders, select a saved profile, or drag local targets into the window. Folders scan recursively. Invalid, missing, inaccessible, or protected targets are rejected before the scan begins.

For one-off integrations, launch with paths:

```bash
clamui /path/to/file /path/to/folder
flatpak run io.github.linx_systems.ClamUI /path/to/file /path/to/folder
```

Headless use is available through `clamui scan`; run `clamui scan --help` for the current options. Its standard ClamAV exit codes are `0` clean, `1` infected, and `2` error. Most ClamUI subcommands accept `--json` for scripts.

## Select the right scan

| Need | Best choice |
| --- | --- |
| New download | Scan the file or use **Quick Scan** |
| Personal files | **Home Folder** profile |
| System-wide review | **Full Scan** when the machine is idle |
| Recurring work | [Scheduled scan](/docs/guides/scheduling/) |
| New removable media | Scan its mount point, or enable device auto-scan |

**Quick Scan** targets `~/Downloads`. **Full Scan** targets `/` and excludes `/proc`, `/sys`, `/dev`, `/run`, `/tmp`, `/var/cache`, and `/var/tmp`. **Home Folder** targets `~` and excludes `~/.cache` and `~/.local/share/Trash`.

## Results and detections

ClamUI displays clean, infected, or error results with a file path and ClamAV detection name. Severity badges are guidance derived from detection names, not proof of actual malware behavior. Treat critical/high detections urgently; for uncertain, low, or heuristic detections, quarantine first and investigate.

**Quarantine** copies the file to owner-only storage, hashes it with SHA-256, and verifies that hash when restoring. It is safer than deleting immediately. See [quarantine](/docs/guides/quarantine/).

## Test with EICAR

Use the built-in **EICAR Test** button after installation. It creates a harmless, standard detection test; delete or quarantine the resulting EICAR item when finished. Do not test with real malware.

## Removable and network storage

Enable **Preferences → Device Scan** to scan `removable`, `external`, and optionally `network` mounts. Set a maximum size (`0` means unlimited), a post-mount delay, notifications, optional auto-quarantine, and battery skipping. Review targets and results before opening files; never disconnect a device during its scan.

## Speed and safety

A daemon keeps signatures in memory and is better for repeated scans. Exclusions can reduce work, but never exclude the whole target, Downloads, or documents just to make a scan finish faster. Archive limits protect against resource-exhaustion archives; configure them in [Configuration](/docs/reference/configuration/).