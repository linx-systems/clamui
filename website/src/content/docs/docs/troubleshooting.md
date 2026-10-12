---
title: Troubleshooting
description: Resolve ClamAV, Flatpak, daemon, integration, and scan issues.
---

## ClamAV is missing or definitions are old

Install host ClamAV for every ClamUI package format, then update definitions:

```bash
clamscan --version
freshclam --version
sudo freshclam
```

Use the distribution commands in [installation](/docs/installation/). In Flatpak, these commands must succeed on the host; ClamUI calls them with `flatpak-spawn --host`.

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

Database updates use host `freshclam`, which may need the host service's usual permissions. ClamUI cannot modify host `/etc/clamav` without a valid version-matched privileged helper; it fails without changing host configuration.

## File-manager action or tray icon is absent

For Flatpak context-menu actions, re-run **Preferences → Behavior → Configure Integration**, then restart the file manager or sign out/in. For a native Debian package, copy Nautilus scripts once:

```bash
mkdir -p ~/.local/share/nautilus/scripts
cp /usr/share/clamui/integrations/clamui-*.sh ~/.local/share/nautilus/scripts/
chmod +x ~/.local/share/nautilus/scripts/clamui-*.sh
```

Restart Nautilus after copying. Check that `clamui` is executable for native integrations.

The tray needs an SNI watcher. GNOME requires [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/); native/source installations also need `libdbusmenu` bindings. The GUI remains usable when a tray is unavailable.

## Scans are slow, fail, or find a false positive

- Use **Auto** or a running daemon for frequent scans; `clamscan` reloads the database each time.
- Confirm the account can read targets and do not unplug removable media during a scan.
- If `clamscan` reports unavailable or unreadable definition files, repair the host ClamAV setup or use a reachable daemon backend; ClamUI distinguishes missing definitions from definitions it cannot read.
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