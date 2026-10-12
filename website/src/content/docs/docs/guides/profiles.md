---
title: Use scan profiles
description: Reuse targets and exclusions safely.
---

Profiles are saved target and exclusion sets in `profiles.json`. Choose one in **Scan**, or manage them from the profile control.

## Built-in profiles

- **Quick Scan:** `~/Downloads`
- **Full Scan:** `/`, excluding virtual, temporary, and cache paths
- **Home Folder:** `~`, excluding `~/.cache` and `~/.local/share/Trash`

Built-in profiles can be edited but not deleted. **Restore default profiles** resets only those three; custom profiles remain.

## Create a profile

1. Open profile management and choose **Add**.
2. Give it a unique 1–50-character name, add files or directories, and add only necessary exclusions.
3. Save, select it from **Scan**, and start the scan.

A target may be an absolute path or use `~`. Use path exclusions for a directory tree and glob patterns such as `*.tmp` for file names. Do not exclude all targets: ClamUI warns but a resulting profile scans nothing.

Global exclusions apply to every scan. Profile exclusions apply only to that profile; prefer them when an exclusion is task-specific.

## Import and export

Export profiles as JSON to back them up or share them. Exports can reveal user names and filesystem layout—review them before sharing. Imported profiles receive a new ID and are always non-default.

Use the CLI for automation:

```bash
clamui profile --help
clamui profile list --json
```

The profile object contains an ID, unique name, target array, optional `exclusions.paths` and `exclusions.patterns`, timestamps, `is_default`, description, and optional engine `options`. See the [configuration reference](/docs/reference/configuration/) for its full shape.