---
title: Installation
description: Install ClamUI, its native desktop runtime, and host ClamAV.
---

## Choose a package

| System | Recommended package |
| --- | --- |
| Most Linux desktops | Flathub Flatpak |
| Debian-family host with matching release assets | The matching architecture-specific Debian application and helper pair |
| Portable x86_64 use | AppImage |
| Development | Rust, Bun, and the [source workflow](/docs/contributing/development/) |

ClamUI is a Rust core with a Tauri desktop application and React frontend. Native desktop packages use the system WebKitGTK 4.1 and GTK 3 runtime; the Flatpak supplies its GNOME Platform 51 runtime. It is not a Python/PyGObject application.

## Required host software

Every format uses **host** `clamscan` and `freshclam`; ClamUI does not bundle the ClamAV engine or its definitions. Daemon scanning also needs host `clamd` and `clamdscan`.

```bash
# Debian or Ubuntu
sudo apt install clamav clamav-freshclam

# Fedora
sudo dnf install clamav clamav-freshclam

# Arch Linux
sudo pacman -S clamav
```

Update definitions before the first scan:

```bash
sudo freshclam
```

You can also update them from ClamUI's **Database** view. See [scan backends](/docs/reference/scan-backends/) for daemon setup.

## Flatpak

Install Flatpak through your distribution package manager first. On Debian or Ubuntu:

```bash
sudo apt install flatpak
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub io.github.linx_systems.ClamUI
flatpak run io.github.linx_systems.ClamUI
```

The Flatpak uses GNOME Platform 51 and calls host ClamAV through `flatpak-spawn --host`; the sandboxed UI does not replace the host engine. Its ClamUI data is under `~/.var/app/io.github.linx_systems.ClamUI/`.

For a directory outside the granted filesystem, grant only that directory:

```bash
flatpak override --user --filesystem=/path/to/directory io.github.linx_systems.ClamUI
```
Database, Scanner, and On-Access preferences target host ClamAV configuration, not sandbox copies. They require the trusted, version-matched host helper and polkit policy. Live helper onboarding reports a ready helper only after it validates matching newly published, signed Rust release assets; neither a source build nor an older helper is treated as authorization. A Flatpak cannot install host files with `sudo flatpak run … install-privileged-helper`; without a valid helper, protected changes fail closed.

## Debian packages

When a release publishes Debian assets, install the **matching version and architecture** application and privileged-helper packages together. The application package provides `/usr/bin/clamui` and `/usr/bin/clamui-scheduled-scan`; the companion package provides `/usr/bin/clamui-apply-preferences` and its polkit policy.

```bash
sudo apt install ./clamui_<VERSION>_<ARCH>.deb ./clamui-privileged-helper_<VERSION>_<ARCH>.deb
```

Both packages are architecture-specific. Do not mix versions or architectures. The canonical helper keeps the protected-host protocol and data rules intact.

A native Tauri build needs WebKitGTK 4.1 and GTK 3. Build release artifacts on the Ubuntu 22.04-compatible baseline used by CI to preserve the glibc floor; a successful build on a newer host is not evidence of old-distribution compatibility.

## AppImage

Download the current x86_64 AppImage from [GitHub Releases](https://github.com/linx-systems/clamui/releases), make it executable, then run it:

```bash
chmod +x ClamUI-*-x86_64.AppImage
./ClamUI-*-x86_64.AppImage
```

The AppImage packages ClamUI but still uses host ClamAV. A `.zsync` file may be available with a published release.

## Source

Follow the [development prerequisites](/docs/contributing/development/#prerequisites), then run the desktop application from the repository root:

```bash
( cd desktop && bun install --frozen-lockfile )
bun run --cwd desktop tauri dev
```

The headless CLI does not initialize the desktop runtime:

```bash
cargo run -p clamui-core --bin clamui-cli -- help
```

See [development](/docs/contributing/development/) for package builds and local Flatpak/AppImage workflows.

## File-manager and tray integration

ClamUI can install file-manager actions for Nautilus, Dolphin, and Nemo. In Flatpak, use **Preferences → Behavior → Configure Integration**. The system tray is optional and requires a StatusNotifierItem watcher; GNOME needs [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/). See [tray use](/docs/guides/tray/) and [troubleshooting](/docs/troubleshooting/).

## Verify downloads

Verify published release packages before installation. See [package signing](/docs/contributing/signing/) for Debian and AppImage instructions.