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

ClamUI reports an explicit **system helper is not installed** diagnosis when the canonical helper path is missing. On supported Debian-family and Fedora hosts, native packages, AppImages, source builds, and Flatpak may show **Install Helper** for this local missing-helper case without downloading release metadata. It does nothing until you click it. Automatic installation can complete only when the matching signed published package is available; it verifies that package's signature, identity, version, size, digest, and compatible architecture before graphical Polkit authorization, and fails safely before authorization if no eligible asset exists. Debian alone may use a signed same-version architecture-independent helper as the published fallback when no exact-architecture asset exists. The UI never runs as root or collects an administrator password.

The public 0.4.1 release predates the current Rust/Tauri development source, so its helper assets are not proof of a matching source-build repair, even if a version string happens to match. A repair package must be signed and published for the exact application release and host architecture; the Debian fallback above is the only architecture-independent exception. An already-installed, trusted, same-version protocol-v4 Debian `all` helper remains valid: if an older ClamUI build reports it missing, update ClamUI and retry—do not reinstall the root-owned helper. This installed-helper recognition correction does not expand fresh-host installation: automatic installation still requires a matching signed published asset. Do not disable verification or use an unsigned legacy download.

On Fedora Workstation or Server, the offer presents the persistent system RPM-key trust notice before its DNF transaction. On Fedora Atomic desktops, it can install live only a missing helper with no unrelated pending deployment; after a successful live install, it refreshes the active Polkit service and verifies the ClamUI action is available. It does not import a host RPM key or reboot, and does not automatically replace an existing, outdated, or corrupt Atomic package.

If a helper exists but is untrusted, ClamUI keeps it blocked unless it is a regular executable file, owned by root, not a symbolic link, executable by its owner, and not writable by its group or other users. The error does not identify which individual trust check failed. ClamUI does not execute an untrusted helper or offer an automatic replacement for it.

If authorization is cancelled or the installation fails, the settings draft stays available: retry the offer or use the manual repair route below. After a successful installation, explicitly retry **Save & Apply**; protected changes are never applied automatically.

Use the manual repair route when the helper is untrusted, the host is unsupported, or a source/development release has no eligible published package:

- **Official Debian packages:** Reinstall the official application and `clamui-privileged-helper` packages as the same release version and architecture. A signed architecture-independent helper is acceptable only when it is the published same-version fallback. Follow [installation](/docs/installation/#debian-packages) and verify the packages with [package signing](/docs/contributing/signing/#debian-packages) before installing them.
- **Fedora Workstation or Server:** Download only a matching published `clamui-privileged-helper-<VERSION>-1.<ARCH>.rpm` and its adjacent `.rpm.asc` for the host architecture. Complete [Fedora RPM package signing](/docs/contributing/signing/#fedora-rpm-packages), then continue in the same shell so its fingerprint-pinned `$pinned_key` and `$RPM` variables remain available:

  ```bash
  sudo rpm --import "$pinned_key"
  sudo dnf --setopt=localpkg_gpgcheck=1 install -y "./$RPM"
  ```

- **Fedora Atomic (Silverblue, Kinoite, and similar):** After completing the [Fedora RPM verification](/docs/contributing/signing/#fedora-rpm-packages), continue in that same verified shell to layer the matching package and reboot into the new deployment. Use this repair path for upgrades, pending deployments, or an existing/corrupt helper; do not use the source installer against immutable `/usr`.

  ```bash
  sudo rpm-ostree install "./$RPM"
  systemctl reboot
  ```

- **Source build or unavailable/unpublished development release on a mutable host:** Start from the current Rust/Tauri checkout on `migration/rust-tauri`, not the default `master` branch, and install the Rust/Cargo prerequisites from [Development](/docs/contributing/development/#prerequisites). Then build only the core binaries so the local `clamui-cli` and co-bundled helper are together:

  ```bash
  cargo build --locked -p clamui-core --bins
  sudo ./target/debug/clamui-cli install-privileged-helper
  ```

  This is a local source-built helper installation, not a signed published-package installer. Do not use it from Flatpak or to modify an immutable Fedora Atomic deployment.

- **Flatpak:** On an eligible Debian-family or Fedora host, use the in-app offer for a missing helper. If the host is unsupported or automatic installation cannot complete because no eligible published asset exists, keep protected writes blocked and repair only through the verified package or mutable-host source route for the same release. Do not use `sudo flatpak`, the native host installer command, or a staging prefix as a Flatpak repair; see [installation](/docs/installation/#flatpak).

Do not change an unknown executable's ownership or permissions to bypass this check. After a successful manual repair, restart ClamUI and repeat the requested operation. If it still fails, open the dialog's **Technical details** panel and include the exact error, package format, version, and architecture in a [GitHub issue](https://github.com/linx-systems/clamui/issues).

When a protected write is blocked, that protected write remains unapplied; settings already saved before it may still have succeeded. After completing the supported repair for your package format, retry the pending settings draft.

## Recover a failed Save & Apply

If a configuration **Save & Apply** attempt fails after ClamUI has prepared native ClamAV files, select **See Configuration** in the failure report. The read-only recovery view lists every full target path and the exact `clamd.conf` or `freshclam.conf` content from that failed attempt. Use **Copy Path** and **Copy Configuration** separately, then open the target with an administrative editor appropriate for that path—for example, `sudoedit /full/path/to/clamd.conf`.

The view is a frozen record of the failed attempt, not later edits in the Preferences page. A helper error can happen after it has written some files, so inspect each existing target before replacing anything manually. **See Configuration** does not write or apply files, bypass helper trust checks, or expose application settings, VirusTotal data, or a general JSON dump.

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