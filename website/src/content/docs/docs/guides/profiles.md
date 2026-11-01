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
3. Save it, select it from **Scan**, then choose **Use this profile**. ClamUI selects its targets and starts the scan.

A target may be an absolute path or use `~`. Use path exclusions for a directory tree and glob patterns such as `*.tmp` for file names. Do not exclude all targets: ClamUI warns but a resulting profile scans nothing.

Global exclusions apply to every scan. Profile exclusions apply only to that profile; prefer them when an exclusion is task-specific.

## Import and export

Export profiles as JSON to back them up or share them. Exports can reveal user names and filesystem layout—review them before sharing. Imported profiles receive a new ID and are always non-default.

Use the CLI for automation:

```bash
clamui profile export "Quick Scan" "$HOME/quick-scan.json"
clamui profile import "$HOME/quick-scan.json"
```

The CLI uses the supplied profile `FILE` path literally: a quoted `~` is not expanded. Let the shell expand `~`, or use `$HOME` as in the examples. This differs from scan targets, where `~` remains supported.

An export wraps a public nine-field profile (`id`, `name`, `targets`, `exclusions`, `created_at`, `updated_at`, `is_default`, `description`, and `options`). Unknown metadata already stored on disk is retained. For older profiles, a non-string description is normalized to text instead of discarding the profile. See the [configuration reference](/docs/reference/configuration/) for the full configuration shape.