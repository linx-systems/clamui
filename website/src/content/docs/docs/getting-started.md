---
title: Getting started
description: Update ClamAV, run a first scan, and handle its result.
---

## 1. Launch ClamUI

Open **ClamUI** from your application menu, or run the command for your package:

```bash
flatpak run io.github.linx_systems.ClamUI
clamui
# Replace VERSION with the downloaded release version.
./ClamUI-VERSION-x86_64.AppImage
```

Pass a file or folder to pre-load it as a scan target:

```bash
flatpak run io.github.linx_systems.ClamUI /path/to/file-or-folder
clamui /path/to/file-or-folder
```

## 2. Update definitions

Open the **Database** view and update definitions before scanning, or use host `freshclam`:

```bash
sudo freshclam
```

## 3. Run the first scan

1. In **Scan**, choose **Quick Scan** (your `~/Downloads`) or add a file/folder. Dropping local files and folders into the window works too.
2. Click **Start Scan**.
3. Review the result. Exit code/result `0` is clean, `1` means a detection, and `2` is an error.

Use the built-in **EICAR Test** once after installation to confirm detection. EICAR is a harmless industry-standard test pattern, not malware.

## 4. If a threat is found

Quarantine an unfamiliar or high-severity file first. It is reversible and ClamUI verifies its SHA-256 hash before restoration. Do **not** restore a file unless you have established that it is safe. See [quarantine](/docs/guides/quarantine/) and the [FAQ](/docs/guides/faq/) for false-positive handling.

## Main views and shortcuts

The sidebar contains Scan, Database, Logs, Components, Quarantine, Statistics, Audit, and Preferences. `Ctrl+1` opens Scan, `Ctrl+2` Database, `Ctrl+3` Logs, `Ctrl+4` Components, `Ctrl+5` Quarantine, `Ctrl+6` Statistics, `Ctrl+7` Audit, and `Ctrl+,` Preferences. Choose scan profiles in the Scan view.

Next: [scan targets and results](/docs/guides/scanning/), [scan profiles](/docs/guides/profiles/), or [scheduled scans](/docs/guides/scheduling/).