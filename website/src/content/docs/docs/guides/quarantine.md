---
title: Manage quarantine
description: Review, restore, or permanently delete detected files.
---

Quarantine moves a detected file to owner-only storage and records its original path, detection, size, date, and SHA-256. Quarantined files are stored with restrictive permissions and cannot run from their original location.

## Decide what to do

- **Uncertain, critical, or high-severity detection:** quarantine it first.
- **Known false positive:** restore only after checking its source and identity. Restoration verifies the stored SHA-256 and refuses to overwrite an existing destination file.
- **Confirmed malware:** delete it permanently.

Deletion and **Clear Old Items** are irreversible. Clear Old Items deletes items older than 30 days; review and export anything you need first.

## Work in the GUI

Open **Quarantine**, search by threat or path, expand an item for metadata, then choose **Restore** or **Delete**. The list paginates large collections. If restoration fails an integrity check, do not manually restore the file.

## Locations and recovery

Default native paths are:

```text
~/.local/share/clamui/quarantine/
~/.local/share/clamui/quarantine.db
```

For Flatpak they are under:

```text
~/.var/app/io.github.linx_systems.ClamUI/data/clamui/quarantine/
~/.var/app/io.github.linx_systems.ClamUI/data/clamui/quarantine.db
```

`quarantine_directory` can move newly quarantined files, but the SQLite metadata database remains in the standard data directory. Changing it does not relocate existing items. Manual changes bypass integrity and database checks; use them only for recovery after backing up the database.

## CLI

```bash
clamui quarantine --help
clamui quarantine list --json
```

The numeric item ID from `list` identifies restores and deletions. See the [FAQ](/docs/guides/faq/) for a false-positive workflow.