# ClamUI Installation Guide

This document provides comprehensive installation instructions for ClamUI on Linux systems.

## Table of Contents

1. [Quick Start](#quick-start)
2. [ClamAV Requirement](#clamav-requirement)
3. [Flatpak Installation](#flatpak-installation)
4. [AppImage Installation](#appimage-installation)
5. [Debian Package Installation](#debian-package-installation)
6. [File Manager Context Menu](#file-manager-context-menu)
7. [System Tray Integration](#system-tray-integration)
8. [Verification](#verification)
9. [Verifying Package Signatures](#verifying-package-signatures)
10. [Icon Troubleshooting](#icon-troubleshooting)
11. [Uninstallation](#uninstallation)

---

## Quick Start

The recommended installation method depends on your Linux distribution:

| Distribution               | Recommended Method                           |
|----------------------------|----------------------------------------------|
| Any (universal)            | [Flatpak](#flatpak-installation)             |
| Debian, Ubuntu, Linux Mint | [.deb package](#debian-package-installation) |
| Fedora, Arch, others       | [Flatpak](#flatpak-installation) or [AppImage](#appimage-installation) |

There are three distribution formats: a Debian `.deb` package, a portable AppImage, and a Flatpak.
ClamUI is a GTK4/libadwaita GUI front-end for ClamAV; it requires Python 3.11 or newer (bundled in the
Flatpak and AppImage) and **a host installation of ClamAV** regardless of which format you choose
(see [ClamAV Requirement](#clamav-requirement)).

---

## ClamAV Requirement

ClamUI drives the ClamAV command-line tools; **none of the distribution formats bundle ClamAV or its virus
database**. You must install ClamAV on the host for every installation method (Debian `.deb`, AppImage, and
Flatpak). The Flatpak and AppImage invoke the host's ClamAV (the Flatpak via `flatpak-spawn --host`).

At minimum ClamUI needs `clamscan` and `freshclam` (the virus-database updater). Daemon mode additionally
requires the ClamAV daemon (`clamd`) and `clamdscan` — see
[SCAN_BACKENDS.md](./SCAN_BACKENDS.md) for daemon setup and the backend selection.

```bash
# Ubuntu/Debian (clamscan + freshclam; clamav-daemon for daemon mode)
sudo apt install clamav clamav-freshclam
sudo apt install clamav-daemon          # optional: daemon (clamd/clamdscan) backend

# Fedora (clamav-update provides freshclam; clamd/clamav-update for daemon mode)
sudo dnf install clamav clamav-update
sudo dnf install clamd                   # optional: daemon backend

# Arch Linux (the clamav package provides clamscan, freshclam, clamd, and clamdscan)
sudo pacman -S clamav
```

After installing ClamAV, download the virus database with `freshclam` (or run a database update from inside
ClamUI) before your first scan.

---

## Flatpak Installation

Flatpak is the recommended installation method as it works on any Linux distribution and includes automatic updates.

### Prerequisites

Ensure Flatpak is installed on your system:

```bash
# Ubuntu/Debian
sudo apt install flatpak

# Fedora (pre-installed)
# flatpak is included by default

# Arch Linux
sudo pacman -S flatpak
```

Add the Flathub repository if not already configured:

```bash
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

### Install ClamUI

```bash
flatpak install flathub io.github.linx_systems.ClamUI
```

> **Note:** The Flatpak does not bundle ClamAV; install ClamAV on the host first (it is invoked via
> `flatpak-spawn --host`). See [ClamAV Requirement](#clamav-requirement).

### Update Virus Definitions

After installation, launch ClamUI and run a database update from the application, or run host `freshclam`, to download
the latest virus definitions.

### Run ClamUI

```bash
flatpak run io.github.linx_systems.ClamUI
```

Or find "ClamUI" in your application menu.

### Saving System Settings (Privileged Helper)

ClamUI writes `freshclam.conf` and `clamd.conf` through a `pkexec`-elevated helper that must live at
`/usr/bin/clamui-apply-preferences` on the **host**, alongside its polkit policy. The sandbox cannot install files
there, so `sudo flatpak run ... install-privileged-helper` is **not supported** — the sandbox `/usr` is not the
host `/usr`. The `clamui install-privileged-helper` command is native-host-only.

To enable saving system ClamAV settings from the Flatpak, download the matching
`clamui-privileged-helper_<version>_all.deb` from the
[releases page](https://github.com/linx-systems/clamui/releases) (use the **same version** as your Flatpak) and
install it on the host:

```bash
sudo apt install ./clamui-privileged-helper_<version>_all.deb
```

This installs only the helper, its Python modules, and the polkit policy — not the full native app.

> **Troubleshooting**: If you encounter issues with the Flatpak installation,
> see [Flatpak-Specific Issues](./TROUBLESHOOTING.md#flatpak-specific-issues) in the troubleshooting guide.

### Building from Source

If you want to build the Flatpak locally instead of installing from Flathub:

#### Prerequisites

Install `flatpak-builder` and the required GNOME SDK/runtime:

```bash
# Install flatpak-builder
sudo apt install flatpak-builder    # Ubuntu/Debian
sudo dnf install flatpak-builder    # Fedora
sudo pacman -S flatpak-builder      # Arch Linux

# Install the GNOME 49 SDK and runtime
flatpak install flathub org.gnome.Sdk//49 org.gnome.Platform//49
```

#### Build

Clone the repository and build with `flatpak-builder`:

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
flatpak-builder --force-clean build-dir flathub/io.github.linx_systems.ClamUI.yml
```

> **Note:** The Flatpak build uses host ClamAV at runtime and does not compile ClamAV into `/app`.

#### Test Without Installing

Run the built application directly without installing:

```bash
flatpak-builder --run build-dir flathub/io.github.linx_systems.ClamUI.yml clamui
```

#### Install Locally

Install the locally-built Flatpak for the current user:

```bash
flatpak-builder --user --install --force-clean build-dir flathub/io.github.linx_systems.ClamUI.yml
```

Then run it the same way as the Flathub version:

```bash
flatpak run io.github.linx_systems.ClamUI
```

#### Building with Local Changes

A separate manifest is provided for local development builds. It sources ClamUI from your working tree instead of fetching from GitHub:

```bash
flatpak-builder --force-clean build-dir flathub/io.github.linx_systems.ClamUI.local.yml
```

Use `--run` or `--user --install` the same way as above. This is useful for testing local changes before committing.

### Flatpak Permissions

ClamUI requests the following permissions:

| Permission | Purpose |
|---|---|
| `--filesystem=host` | Full filesystem access for scanning and quarantine |
| `--share=network` | Virus database updates |
| `--share=ipc`, `--device=dri` | Shared memory and GPU for rendering |
| `--socket=wayland`, `--socket=fallback-x11` | Display support |
| `--talk-name=org.freedesktop.Flatpak` | Host ClamAV tools, systemctl, and config helpers via `flatpak-spawn --host` |
| `--talk-name=org.freedesktop.Notifications` | Desktop notifications |
| `--talk-name=org.freedesktop.secrets` | Secure API key storage (keyring) |
| `--talk-name=org.kde.StatusNotifierWatcher` etc. | System tray (SNI protocol) |
| `--filesystem=xdg-run/gvfsd` | File browser integration |

### Managing Permissions

View current permissions:

```bash
flatpak info --show-permissions io.github.linx_systems.ClamUI
```

Override permissions if needed:

```bash
# Grant access to additional directories
flatpak override --user --filesystem=/path/to/directory io.github.linx_systems.ClamUI
```

---

## AppImage Installation

ClamUI is also distributed as a portable AppImage that bundles Python, GTK4, and libadwaita. It runs on
most modern Linux distributions without installation. **ClamAV is not bundled** — it must be installed on the
host (see [ClamAV Requirement](#clamav-requirement)).

### Download and Run

Download `ClamUI-<version>-x86_64.AppImage` from the
[releases page](https://github.com/linx-systems/clamui/releases), make it executable, and run it:

```bash
chmod +x ClamUI-*-x86_64.AppImage
./ClamUI-*-x86_64.AppImage
```

Releases that embed update information also ship a `ClamUI-<version>-x86_64.AppImage.zsync` file, which lets
[AppImageUpdate](https://github.com/AppImage/AppImageUpdate) perform delta updates.

### Install via AppMan / AM (optional)

The AppImage can be managed by [AppMan](https://github.com/ivan-hc/AppMan) (rootless) or
[AM](https://github.com/ivan-hc/AM):

```bash
appman -i clamui   # rootless, per-user
am -i clamui       # system-wide
```

### Building the AppImage

To build the AppImage locally (requires `wget`, Python 3, and the GTK4/libadwaita system packages, Ubuntu
24.04+ recommended):

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
./appimage/build-appimage.sh
```

The resulting `ClamUI-<version>-x86_64.AppImage` is written to the project root.

---

## Debian Package Installation

For Debian, Ubuntu, and derivative distributions, ClamUI is available as a `.deb` package.

### Prerequisites

Install the required system dependencies:

```bash
# GTK4, Adwaita, and Python bindings
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1

# Build dependencies (required for pycairo/PyGObject compilation)
sudo apt install python3-dev libcairo2-dev libgirepository-2.0-dev pkg-config

# Build dependencies for Pillow (tray icon support)
sudo apt install libjpeg-dev zlib1g-dev

# ClamAV antivirus (clamscan + freshclam; see ClamAV Requirement above)
sudo apt install clamav clamav-freshclam
```

> **Note:** The build dependencies (`python3-dev`, `libcairo2-dev`, `libgirepository-2.0-dev`, `pkg-config`,
`libjpeg-dev`, `zlib1g-dev`) are only required when running from source with `uv run clamui`. The `.deb`
> package is architecture-independent (`all`) — it installs the Python sources to
`/usr/lib/python3/dist-packages/clamui/` and declares its runtime dependencies (`python3-gi`,
`python3-gi-cairo`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, …), which `apt` pulls in automatically, so no
> compilation is needed. ClamUI requires Python 3.11 or newer. On older Ubuntu versions (22.04), use
`libgirepository1.0-dev` instead of `libgirepository-2.0-dev`.

**Quick Start (from source):** The `local-run.sh` script in the `scripts/` directory automatically installs all dependencies
and runs ClamUI:

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
./scripts/local-run.sh
```

On Ubuntu/Pop!_OS 22.04, `local-run.sh` automatically installs `PyGObject<3.50`. Newer
PyGObject releases require GLib 2.80+, while 22.04 ships GLib 2.72 and
`libgirepository1.0-dev`.

### Download and Install

The `clamui` package now depends on the matching `clamui-privileged-helper`
package, which owns the `pkexec` helper and polkit policy used to save system
ClamAV configuration. Download **both** release assets for your version
(`clamui_<version>_all.deb` and `clamui-privileged-helper_<version>_all.deb`)
and install them together so `apt` resolves the dependency and configures the
helper:

```bash
sudo apt install ./clamui_<version>_all.deb \
  ./clamui-privileged-helper_<version>_all.deb
```

This installs ClamUI and its polkit helper in one step. The privileged helper
is packaged separately so Flatpak users can install it on the host without the
full native app — see "Saving System Settings (Privileged Helper)" under
Flatpak Installation above.

### What Gets Installed

| Path                                                                       | Description                               |
|----------------------------------------------------------------------------|-------------------------------------------|
| `/usr/bin/clamui`                                                          | Launcher script                          |
| `/usr/lib/python3/dist-packages/clamui/`                                   | Python application modules              |
| `/usr/share/applications/io.github.linx_systems.ClamUI.desktop`            | Desktop entry file                       |
| `/usr/share/icons/hicolor/scalable/apps/io.github.linx_systems.ClamUI.svg` | Application icon                        |
| `/usr/bin/clamui-apply-preferences`                                       | Privileged config helper |
| `/usr/lib/clamui/clamui_apply_preferences.py`                             | Helper library           |
| `/usr/lib/clamui/clamui_privileged_paths.py`                              | Helper library           |
| `/usr/share/polkit-1/actions/io.github.linx_systems.ClamUI.policy`         | polkit policy            |

The last four paths are owned by the separate `clamui-privileged-helper`
package, which the `clamui` package declares as a dependency (`Depends:
clamui-privileged-helper (= VERSION)`); the main `clamui` package itself does
not install those files.

### Building the Package

To build the `.deb` from source (requires `dpkg-deb` and `fakeroot`):

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
./debian/build-deb.sh
```

This produces `clamui_<version>_all.deb` in the project root.

### Run ClamUI

```bash
clamui
```

Or find "ClamUI" in your application menu.

> **Troubleshooting**: If you encounter issues with missing dependencies or ClamAV installation,
> see [ClamAV Installation Issues](./TROUBLESHOOTING.md#clamav-installation-issues) in the troubleshooting guide.

---

## File Manager Context Menu

ClamUI integrates with file managers to provide a "Scan with ClamUI" right-click option.

### Supported File Managers

| File Manager | Desktop  | Integration Type     |
|--------------|----------|----------------------|
| Nautilus     | GNOME    | Nautilus script      |
| Dolphin      | KDE      | Dolphin service menu |
| Nemo         | Cinnamon | Native Nemo action   |

### Flatpak Users

If you installed ClamUI via Flatpak, ClamUI bundles the integration files and can install them into your
user profile from Preferences. The Flatpak manifest includes the necessary filesystem permissions to access
files for scanning.

### Native Installation

For native (non-Flatpak) installations, set up context menu integration manually:

#### GNOME (Nautilus)

1. **Create the Nautilus scripts directory**:

   ```bash
   mkdir -p ~/.local/share/nautilus/scripts
   ```

2. **Copy the Nautilus script**:

   ```bash
   cp scripts/clamui-scan-nautilus.sh ~/.local/share/nautilus/scripts/Scan\ with\ ClamUI
   chmod +x ~/.local/share/nautilus/scripts/Scan\ with\ ClamUI
   ```

3. **Restart Nautilus**:

   ```bash
   nautilus -q
   ```

#### KDE (Dolphin)

1. **Create the Dolphin service menu directory**:

   ```bash
   mkdir -p ~/.local/share/kio/servicemenus
   ```

   On older KDE Plasma 5 systems, use `~/.local/share/kservices5/ServiceMenus` instead.

2. **Copy the Dolphin service menu files**:

   ```bash
   cp data/io.github.linx_systems.ClamUI.service.desktop ~/.local/share/kio/servicemenus/
   cp data/io.github.linx_systems.ClamUI-virustotal.desktop ~/.local/share/kio/servicemenus/
   chmod +x ~/.local/share/kio/servicemenus/io.github.linx_systems.ClamUI.service.desktop
   chmod +x ~/.local/share/kio/servicemenus/io.github.linx_systems.ClamUI-virustotal.desktop
   ```

3. **Refresh Dolphin's service menu cache**:

   ```bash
   kbuildsycoca6 --noincremental || kbuildsycoca5 --noincremental
   ```

#### Cinnamon (Nemo)

Nemo uses its own action format for context menu extensions:

1. **Create the Nemo actions directory**:

   ```bash
   mkdir -p ~/.local/share/nemo/actions
   ```

2. **Copy the Nemo action file**:

   ```bash
   cp io.github.linx_systems.ClamUI.nemo_action ~/.local/share/nemo/actions/
   ```

3. **Restart Nemo**:
   ```bash
   nemo -q
   ```

### Using the Context Menu

| Action                 | Description                                                      |
|------------------------|------------------------------------------------------------------|
| **Single file**        | Right-click a file and select "Scan with ClamUI"                 |
| **Folder**             | Right-click a folder to recursively scan all contents            |
| **Multiple selection** | Select multiple files/folders, right-click, and scan all at once |

### Verifying Context Menu Installation

Check that the integration files are installed:

```bash
# Nautilus script
ls ~/.local/share/nautilus/scripts/Scan\ with\ ClamUI

# Dolphin service menu
ls ~/.local/share/kio/servicemenus/io.github.linx_systems.ClamUI.service.desktop

# Nemo action (if using Nemo)
ls ~/.local/share/nemo/actions/io.github.linx_systems.ClamUI.nemo_action
```

If the context menu doesn't appear:

1. Log out and log back in
2. Manually refresh your file manager integration:
   ```bash
   nautilus -q
   kbuildsycoca6 --noincremental || kbuildsycoca5 --noincremental
   nemo -q
   ```

> **Troubleshooting**: For more detailed troubleshooting of context menu issues,
> see [File Manager Context Menu Issues](./TROUBLESHOOTING.md#file-manager-context-menu-issues) in the troubleshooting
> guide.

---

## System Tray Integration

ClamUI provides an optional system tray icon for quick access to scanning functions.

### Features

| Feature              | Description                                                              |
|----------------------|--------------------------------------------------------------------------|
| **Status Indicator** | Tray icon shows protection status (protected, warning, scanning, threat) |
| **Quick Actions**    | Right-click menu for Quick Scan, Full Scan, and Update Definitions       |
| **Scan Progress**    | Shows scan progress percentage during active scans                       |
| **Window Toggle**    | Click the tray icon to show/hide the main window                         |
| **Minimize to Tray** | Option to hide to tray instead of taskbar when minimizing                |

### Requirements

ClamUI uses the StatusNotifierItem (SNI) D-Bus protocol for system tray integration. For context menus, `libdbusmenu` is needed:

```bash
# Ubuntu/Debian
sudo apt install gir1.2-dbusmenu-0.4

# Fedora
sudo dnf install libdbusmenu

# Arch Linux
sudo pacman -S libdbusmenu-glib
```

### GNOME Shell Users

GNOME Shell requires an extension for tray icon support:

1. Install the [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/) extension
2. Enable the extension in GNOME Extensions app

### Graceful Degradation

If libdbusmenu is not installed, the tray icon still appears but without a context menu. If the desktop environment does not support SNI, ClamUI runs normally without the tray icon.

> **Troubleshooting**: If the system tray icon is not appearing or not working correctly,
> see [System Tray Icon Issues](./TROUBLESHOOTING.md#system-tray-icon-issues) in the troubleshooting guide.

---

## Verification

After installation, verify that ClamUI is working correctly.

### Check Installation

```bash
# For native installation
which clamui
clamui help               # prints CLI usage (confirms install)

# For Flatpak
flatpak info io.github.linx_systems.ClamUI

# For AppImage
./ClamUI-*-x86_64.AppImage help
```

### Check ClamAV

```bash
# Verify ClamAV is installed
clamscan --version

# Check virus database is up to date
freshclam --version
```

### Test a Scan

Launch ClamUI and perform a test scan on a small directory to verify everything is working.

> **Troubleshooting**: If ClamAV is not detected or scanning fails,
> see [ClamAV Installation Issues](./TROUBLESHOOTING.md#clamav-installation-issues) in the troubleshooting guide.

---

## Verifying Package Signatures

ClamUI releases are signed to verify their authenticity. This section provides quick verification commands - for full
details, see [SIGNING.md](./SIGNING.md).

### AppImage

```bash
# Display signature info
./ClamUI-*.AppImage --appimage-signature
```

- Install via [AppMan](https://github.com/ivan-hc/AppMan) (rootless)
  ```bash
  appman -i clamui
  ```
- Install via [AM](https://github.com/ivan-hc/AM)
  ```bash
  am -i clamui
  ```

### Debian Package

```bash
# Import ClamUI's public key
curl -fsSL https://raw.githubusercontent.com/linx-systems/clamui/master/signing-key.asc | gpg --import

# Verify the package
dpkg-sig --verify clamui_*.deb clamui-privileged-helper_*.deb
# Expected output: GOODSIG _gpgbuilder ...
```

> **Security Note:** Before importing keys, verify you're downloading from the official repository. You can also
> download `signing-key.asc` directly
> from [the repository](https://github.com/linx-systems/clamui/blob/master/signing-key.asc) and import it manually with
`gpg --import signing-key.asc`.

### Flatpak (via Flathub)

Flathub signatures are verified automatically during installation.

---

## Icon Troubleshooting

If the ClamUI icon doesn't appear in your application menu or system tray after installation, try these solutions.

### Desktop Icon Not Appearing (Debian Package)

After installing the `.deb` package, the desktop icon may not appear immediately in some desktop environments. This is
because running sessions cache icon databases.

**Solutions (try in order):**

1. **Wait a moment** - Some desktop environments refresh automatically within 30-60 seconds

2. **Force refresh the desktop database:**
   ```bash
   sudo update-desktop-database /usr/share/applications
   sudo gtk-update-icon-cache -f -t /usr/share/icons/hicolor
   xdg-desktop-menu forceupdate --mode system
   ```

3. **Log out and log back in** - This refreshes all desktop environment caches

4. **Reboot** - As a last resort, this ensures all caches are rebuilt

### Tray Icon Not Appearing (Running from Source)

When running ClamUI from source with `uv run clamui`, the tray icon requires additional Python dependencies:

```bash
# Verify Pillow is available
uv run python -c "from PIL import Image; print('Pillow OK')"

# Verify cairosvg is available (for SVG icon support)
uv run python -c "import cairosvg; print('cairosvg OK')"
```

If either import fails, ensure the build dependencies are installed:

```bash
# Ubuntu/Debian
sudo apt install libjpeg-dev zlib1g-dev

# Then reinstall Python dependencies
uv sync
```

### Cinnamon Specific

Cinnamon caches menu icons separately and may not respond to standard refresh commands. If the icon shows as a
default/generic icon:

```bash
# Force Cinnamon to reload its theme (includes icons)
dbus-send --session --dest=org.Cinnamon --type=method_call \
    /org/Cinnamon org.Cinnamon.ReloadTheme

# Alternative: restart Cinnamon (will briefly flash the screen)
cinnamon --replace &
```

If the icon still doesn't appear, logging out and back in is the most reliable solution for Cinnamon.

### KDE Plasma Specific

KDE Plasma uses its own icon cache system. If icons don't appear:

```bash
# Rebuild KDE cache (Plasma 5)
kbuildsycoca5 --noincremental

# Rebuild KDE cache (Plasma 6)
kbuildsycoca6 --noincremental
```

---

## Uninstallation

### Flatpak

```bash
flatpak uninstall io.github.linx_systems.ClamUI
```

### Debian Package

```bash
# Remove (keeps configuration files)
sudo dpkg -r clamui

# Purge (removes everything including config)
sudo dpkg -P clamui
```

### Context Menu Cleanup

If you manually installed context menu integration:

```bash
# Remove desktop entry
rm ~/.local/share/applications/io.github.linx_systems.ClamUI.desktop

# Remove Nemo action
rm ~/.local/share/nemo/actions/io.github.linx_systems.ClamUI.nemo_action

# Refresh desktop database
update-desktop-database ~/.local/share/applications
```

---

## See Also

- [README.md](../README.md) - Project overview and quick start
- [CONFIGURATION.md](./CONFIGURATION.md) - Configuration reference and settings guide
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Troubleshooting common issues
- [DEVELOPMENT.md](./DEVELOPMENT.md) - Development setup and contributing
