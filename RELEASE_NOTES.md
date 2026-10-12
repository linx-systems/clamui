# ClamUI v0.4.1

Hungarian localization, easier Flatpak host-helper setup, tray startup, and reliability fixes for scanning, host integration, and packaged builds.

## Highlights

### Flatpak host configuration

- **Install the matching helper from ClamUI** - On supported Debian-family hosts, Flatpak users can now install the version-matched `clamui-privileged-helper` from Preferences. The flow obtains the exact release asset, checks its release metadata, package identity, and signature, then requests administrator authorization to install it.
- **Clearer host-configuration boundary** - Database, Scanner, and On-Access preferences continue to target the host ClamAV configuration, not sandbox copies. Protected system-configuration writes fail without making changes when the trusted helper is unavailable.
- **Better compatibility** - The privileged-helper import path is compatible with Python 3.10, so the Flatpak remains suitable for Ubuntu/Pop!_OS 22.04 hosts.

### Everyday use

- **Hungarian is now available** in the application language list.
- **Start in System Tray** is a new Behavior preference for login/autostart workflows. Explicit file and folder scans remain visible, and ClamUI keeps the window visible if tray integration is unavailable.
- **More reliable scan results** - Large `clamscan` scans are no longer reported as failed merely because bounded verbose output omitted the final summary while only nonfatal ClamAV warnings remained.
- **Improved tray integration** - Generated tray icons are supplied as pixmaps for desktop hosts that do not reliably resolve sandbox-local themed icons; tray registration and VirusTotal setup handling were also corrected.

### Host integration and packages

- **Fedora setup uses the right update package** - ClamUI now recommends `clamav-freshclam`, and its availability check avoids Fedora's root-only default configuration.
- **AppImage links work on more desktops** - The AppImage bundles GLib's desktop-launch helper so documentation links can open on KDE and other non-Ubuntu host layouts.
- **Flatpak packaging is more self-contained** - Hatchling's build dependency sources are included, and the Flatpak runtime now uses GNOME 51 with Python 3.14.
- **Documentation has moved to the ClamUI website**, including task-focused installation, configuration, and troubleshooting guidance.

### Safety and correctness

- Preserve raw POSIX filename bytes through `clamscan`, daemon scans, and quarantine restore. Daemon scans reject targets containing a newline rather than submitting an ambiguous file list.
- Manual database updates use the selected custom `freshclam.conf`.
- Hardened trusted helper discovery and atomic configuration writes; newly created custom configurations use owner-only permissions.

## Before you install or upgrade

- **Install ClamAV on the host for every package format.** ClamUI does not bundle the ClamAV engine or definitions: install host `clamscan` and `freshclam`, then update definitions. Daemon scans also require host `clamd` and `clamdscan`.
- **Flatpak users:** ClamUI calls host tools through `flatpak-spawn --host`. On Debian-family hosts, install the version-matched `clamui-privileged-helper_0.4.1_all.deb` when you need to change protected system ClamAV settings; the new in-app flow can do this on supported hosts. Do not use `sudo flatpak run … install-privileged-helper`: a Flatpak cannot install files on the host. No RPM or pacman helper asset is supplied.
- **Ubuntu/Pop!_OS 22.04:** use Flatpak. The full Debian package requires Python 3.11+, while stock 22.04 provides Python 3.10.

## Install

**Flathub** (recommended):
```bash
flatpak install flathub io.github.linx_systems.ClamUI
```

**AppImage**: Download `ClamUI-0.4.1-x86_64.AppImage` from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.4.1).

**GitHub Release**: Download `clamui_0.4.1_all.deb` or the `clamui-x86_64.flatpak` / `clamui-aarch64.flatpak` bundle from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.4.1). On Debian/Ubuntu, install the matching `clamui-privileged-helper_0.4.1_all.deb` when changing protected host ClamAV configuration.

**From source**:
```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui && uv sync && uv run clamui
```

See the [full commit log](https://github.com/linx-systems/clamui/compare/v0.4.0...v0.4.1) for all changes.
