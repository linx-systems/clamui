---
title: Troubleshooting
description: Resolve ClamAV, Tauri/WebKitGTK, daemon, integration, tray, and scan issues.
---

## ClamAV is missing or definitions are old

Install host ClamAV for every ClamUI package format, then update definitions:

```bash
clamscan --version
freshclam --version
sudo freshclam
```

Use the distribution commands in [installation](/docs/installation/). In Flatpak, these commands must succeed on the host; ClamUI invokes them through `flatpak-spawn --host`.

## The desktop does not start

The native desktop uses Tauri with WebKitGTK 4.1 and GTK 3. On a Debian-family development host, confirm the required runtime is installed:

```bash
dpkg -l libwebkit2gtk-4.1-0 libgtk-3-0
```

For a source build, install the development packages in [Development](/docs/contributing/development/#prerequisites). A build or launch on a newer host does not prove compatibility with the Ubuntu 22.04 baseline; use the project baseline build for release compatibility evidence.

## Daemon backend unavailable

The daemon backend needs `clamd` and `clamdscan` running. Check its service, then choose **Auto** or **Clamscan** if you do not need a persistent daemon:

```bash
sudo systemctl status clamav-daemon
sudo systemctl enable --now clamav-daemon
clamdscan --version
```

Fedora commonly uses `clamd@scan` and `/etc/clamd.d/scan.conf`:

```bash
sudo systemctl enable --now clamd@scan
```

Check `LocalSocketMode` and `LocalSocketGroup` when a running Fedora daemon is inaccessible. [Backend reference](/docs/reference/scan-backends/) lists socket paths and alternatives.

`clamdscan` receives targets through a newline-delimited file list. A pathname containing a newline cannot be represented there, so ClamUI rejects that daemon scan rather than scanning the wrong target. Use the **Clamscan** backend for that file after confirming the pathname.

## Flatpak cannot scan a location or update ClamAV

Grant only the directory you need:

```bash
flatpak override --user --filesystem=/path/to/directory io.github.linx_systems.ClamUI
```

Database updates use host `freshclam`, which may need the host service's usual permissions. ClamUI cannot modify host configuration without the trusted version-matched native helper and polkit policy; failure leaves protected files unchanged.


## Privileged helper is not trusted

ClamUI blocks operations that need the system helper when it cannot verify that helper safely. The helper must be a regular executable file, owned by root, not a symbolic link, executable by its owner, and not writable by its group or other users. The error does not identify which individual check failed. ClamUI does not execute the helper when this check fails.

Use the repair route that matches how you installed ClamUI:

- **Official native packages:** Reinstall the official application and `clamui-privileged-helper` packages as the same release version and architecture. Follow [installation](/docs/installation/#debian-packages) and verify the packages with [package signing](/docs/contributing/signing/#debian-packages) before installing them.
- **Source build:** From the repository root, build the matching application and bundled helper, then install that helper:

  ```bash
  cargo build --workspace --locked
  sudo ./target/debug/clamui install-privileged-helper
  ```

- **Flatpak:** Use ClamUI's supported in-app signed-package helper installer for the matching published helper package. Do not use `sudo flatpak`, the native host installer command, or a staging prefix as a repair from Flatpak; see [installation](/docs/installation/#flatpak).

Do not change an unknown executable's ownership or permissions to bypass this check. After a successful repair, restart ClamUI and repeat the requested operation. If it still fails, open the dialog's **Technical details** panel and include the exact error, package format, version, and architecture in a [GitHub issue](https://github.com/linx-systems/clamui/issues).

## File-manager action or tray icon is absent

For Flatpak context-menu actions, rerun **Preferences → Behavior → Configure Integration**, then restart the file manager or sign out/in. Native packages install the same Nautilus, Dolphin, and Nemo integration assets; use the integration status/repair action instead of copying old Python scripts by hand.

The tray needs an SNI watcher. GNOME requires [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/). ClamUI's tray is pure Rust SNI/DBusMenu and does not need a Python service or `libdbusmenu` binding. The GUI remains usable when no tray is available.

## Scans are slow, fail, or find a false positive

- Use **Auto** or a running daemon for frequent scans; `clamscan` reloads the database each time.
- Confirm the account can read targets and do not unplug removable media during a scan.
- If `clamscan` reports unavailable or unreadable definitions, repair the host ClamAV setup or use a reachable daemon backend.
- Keep ClamAV definitions current. For a suspected false positive, quarantine first, inspect provenance and hashes, and use multiple engines only if the file is safe to disclose. Do not upload sensitive files to third parties.
- Avoid unlimited archive limits: malicious archives can consume resources.

## Quarantine, schedules, and logs

A restore refusal can mean the destination already exists or integrity verification failed; do not bypass the latter. Export important logs before using **Clear All**—clearing is permanent. Scheduled scans require either a user systemd timer or cron and a powered-on machine at run time. Test configuration without changing data:

```bash
clamui-scheduled-scan --dry-run
systemctl --user list-timers
crontab -l
```

## Still stuck?

Collect the relevant Log entry, ClamAV version, package format, desktop environment, and exact error, then search or open a [GitHub issue](https://github.com/linx-systems/clamui/issues). Report vulnerabilities through the [private security policy](/docs/contributing/security/), not a public issue.