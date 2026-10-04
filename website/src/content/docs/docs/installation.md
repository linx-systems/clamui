---
title: Installation
description: Install ClamUI and the host ClamAV tools it uses.
---

## Choose a package

| System | Recommended package |
| --- | --- |
| Any supported Linux distribution | Flatpak from Flathub |
| Ubuntu/Pop!_OS 22.04 | Flatpak (the bundled GUI runtime supports this host) |
| Debian 12+, Ubuntu 24.04+, or another system with Python 3.11+ | Release `.deb` packages |
| Portable installation | AppImage |
| Contributors | Source checkout |

## Required host software

Every format uses host `clamscan` and `freshclam`; it does **not** bundle the ClamAV engine or definitions. Daemon mode also requires `clamd` and `clamdscan`.

### Debian or Ubuntu

```bash
sudo apt install clamav clamav-freshclam clamav-daemon
```

### Fedora

```bash
sudo dnf install clamav clamav-freshclam clamd
```

### Arch Linux

```bash
sudo pacman -S clamav
```

Run `freshclam` (or use ClamUI's Database view) before your first scan. [Select a backend](/docs/reference/scan-backends/) if you want daemon scans.

## Flatpak

Install Flatpak through your distribution package manager first. On Debian or Ubuntu:

```bash
sudo apt install flatpak
```

Then, on any distribution with Flatpak, add Flathub and install ClamUI:

```bash
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub io.github.linx_systems.ClamUI
flatpak run io.github.linx_systems.ClamUI
```

The Flatpak calls host ClamAV through `flatpak-spawn --host`. It needs host ClamAV even though its GUI is sandboxed. Its configuration is under `~/.var/app/io.github.linx_systems.ClamUI/`.

For a directory outside the granted filesystem, grant the narrowest required access:

```bash
flatpak override --user --filesystem=/path/to/directory io.github.linx_systems.ClamUI
```

ClamAV Database, Scanner, and On-Access preferences target host distribution configuration—not sandbox copies—such as Debian's `/etc/clamav`, Fedora's `/etc/freshclam.conf`, and Fedora's `/etc/clamd.d/scan.conf`. On Debian-family systems they require the trusted, version-matched `clamui-privileged-helper_<version>_all.deb` and its polkit policy. A Flatpak cannot install host files with `sudo flatpak run … install-privileged-helper`; without a valid helper, host changes fail closed. No RPM or pacman helper asset is currently supplied.

## Debian or Ubuntu package

The full application package requires Python 3.11+; use it on stock Debian 12+, Ubuntu 24.04+, or a compatible newer distribution. Stock Ubuntu/Pop!_OS 22.04 provides Python 3.10, so use Flatpak there; its modern bundled runtime is independent of the host GTK and Python stack.

Download matching release assets, set their release version, then install both:

```bash
VERSION="x.y.z"
sudo apt install "./clamui_${VERSION}_all.deb" "./clamui-privileged-helper_${VERSION}_all.deb"
clamui
```

The application package is architecture-independent and declares GTK/PyGObject runtime dependencies. The helper owns the `pkexec` entry point and polkit policy for host ClamAV configuration.

## AppImage

Set the release version for the AppImage downloaded from [GitHub Releases](https://github.com/linx-systems/clamui/releases):

```bash
VERSION="x.y.z"
APPIMAGE="ClamUI-${VERSION}-x86_64.AppImage"
chmod +x "$APPIMAGE"
./"$APPIMAGE"
```

The AppImage includes Python and the GUI runtime, but still uses host ClamAV. A `.zsync` file is available for AppImageUpdate.

## Source

Follow the [development prerequisites](/docs/contributing/development/#prerequisites) to install the required system dependencies and `uv`, then create a source environment. Source installation needs Python 3.11+, GTK 4.6+, libadwaita 1.1+, GI bindings, and a GLib version accepted by `PyGObject>=3.56.3` (GLib 2.80+). Ubuntu/Pop!_OS 22.04 ships GLib 2.72, so use Flatpak there or a newer development environment.

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
uv sync --locked --extra dev
uv run clamui
```

See [development](/docs/contributing/development/) for distribution packages and local Flatpak/AppImage builds.

## File-manager and tray integration

The native package can install file-manager actions for Nautilus, Dolphin, and Nemo; the Flatpak exposes its integration from **Preferences → Behavior → Configure Integration**. A system tray requires a StatusNotifierWatcher; GNOME needs [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/) and native/source users need `libdbusmenu` bindings. See [tray use](/docs/guides/tray/) and [troubleshooting](/docs/troubleshooting/).

## Verify downloads

Verify release packages before installation. See [package signing](/docs/contributing/signing/) for AppImage and Debian instructions.