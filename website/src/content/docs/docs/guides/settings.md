---
title: Set preferences
description: Choose app behavior, host ClamAV options, device scans, and diagnostics.
---

Open **Preferences** with `Ctrl+,`. Most app preferences and exclusions save immediately. **Scheduled Scans** need **Save & Apply** to persist their settings and provision the scheduler; changes to host `freshclam.conf` or `clamd.conf` also need **Save & Apply** and elevated host access.

## Choose the right page

| Task | Page |
| --- | --- |
| Language, close behavior, tray startup, live progress | Behavior |
| Select ClamAV mode and socket | Scanner |
| Schedule recurring scans | Scheduled Scans |
| Definition update settings | Database |
| Global exclusion records | Exclusions |
| Mounted-device scanning | Device Scan |
| On-access ClamAV monitoring | On-Access |
| VirusTotal API key | VirusTotal |
| Debug logging | Debugging |

For every raw key, default, location, and host boundary see [Configuration](/docs/reference/configuration/).

## Host configuration warning

Database, Scanner, and On-Access settings change host `/etc/clamav`, not Flatpak files. They need a trusted version-matched privileged helper and polkit approval. If the helper is unavailable, saving fails without modifying host configuration. Exclusions and normal application settings remain local to ClamUI.

## Safe defaults

Use **Auto** backend unless you know you need daemon-only behavior; leave notifications on for scheduled scans; prefer narrow exclusions; and preserve finite archive limits. On-access scanning requires `clamd`, careful include paths, and exclusions for the scanner account to prevent loops. Start with a small path such as `~/Downloads`.

VirusTotal keys use the system keyring when available, not `settings.json`; plaintext fallback requires explicit consent. Do not submit private files or hashes you are not authorized to share.