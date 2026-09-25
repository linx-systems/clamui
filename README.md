<div align="center">

<img src="https://raw.githubusercontent.com/linx-systems/clamui/master/icons/io.github.linx_systems.ClamUI.svg" alt="ClamUI Logo" width="140" height="140">

# ClamUI

<p align="center">
  <strong>A modern Linux desktop application for ClamAV antivirus</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="#"><img src="https://img.shields.io/badge/platform-Linux-lightgrey.svg" alt="Platform"></a>
  <a href="https://flathub.org/en/apps/io.github.linx_systems.ClamUI"><img src="https://flathub.org/api/badge?locale=en" alt="Get ClamUI on Flathub"></a>
</p>

<p align="center">
  Built with <strong>PyGObject</strong>, <strong>GTK4</strong>, and <strong>Adwaita</strong> for a native GNOME appearance
</p>

<p align="center">
  <a href="https://clamui.com">Website</a> •
  <a href="#features">Features</a> •
  <a href="#screenshots">Screenshots</a> •
  <a href="#quick-start">Installation</a> •
  <a href="#documentation">Documentation</a>
</p>

<br>

<img src="./screenshots/ClamUI-Social-Preview-1280x640.png" alt="ClamUI logo and scan results view, highlighting open source, zero telemetry, GTK4 and libadwaita, and system security audit" width="800">

</div>

<br>

---

## Features

ClamUI provides a comprehensive set of features designed to make antivirus protection on Linux both powerful and user-friendly.

<table>
<tr>
<td width="50%" valign="top">

### Scanning & Protection

- **Easy File Scanning** - Native GTK4 file dialogs for intuitive file selection
- **Async Scanning** - Background processing keeps the UI responsive during scans
- **Quarantine Management** - Safely isolate and manage detected threats
- **Scan Profiles** - Create custom configurations for different use cases
- **On-Access Scanning** - Configure real-time file monitoring via clamonacc
- **Automatic Device Scanning** - Scan USB drives and external storage on mount

</td>
<td width="50%" valign="top">

### Security & Monitoring

- **System Security Audit** - Dashboard checking firewall, AppArmor/SELinux, SSH hardening, intrusion detection, and more
- **Deep Security Scans** - Optional Lynis and chkrootkit scans with privilege elevation
- **Scan History** - Track and review all past scan results
- **Statistics Dashboard** - Monitor scanning activity and threat detections
- **VirusTotal Integration** - Opt-in enhanced threat analysis via API

</td>
</tr>
<tr>
<td width="50%" valign="top">

### User Experience

- **Modern UI** - Native Adwaita styling with proper GNOME integration
- **System Tray** - Quick access, real-time scan progress, and optional **Start in System Tray** background startup
- **Desktop Notifications** - Stay informed of scan results and updates
- **Language Selection** - Override the UI language without changing system locale
- **File Manager Integration** - Right-click "Scan with ClamUI" in Nautilus, Dolphin, and Nemo

</td>
<td width="50%" valign="top">

### Flexibility

- **Multiple Scan Backends** - Choose between daemon (clamd) or direct (clamscan)
- **Scheduled Scans** - Configure automatic scanning with systemd or cron
- **ClamAV Config Editor** - Edit clamd.conf and freshclam.conf directly from the GUI
- **CLI Subcommands** - Full headless management: scan, quarantine, profiles, status, history
- **Debug & Diagnostics** - Configurable log verbosity, log export, and privacy-hardened logging
- **Multi-Distro Support** - Auto-detects ClamAV config paths across Debian, Fedora, and more

</td>
</tr>
</table>

---

## Screenshots

<div align="center">

|                         Scan Results                          |                 Quarantine Management                 |
| :-----------------------------------------------------------: | :---------------------------------------------------: |
| ![Scan Results](./screenshots/main_view_with_scan_result.png) | ![Quarantine View](./screenshots/quarantine_view.png) |

|               ClamAV Components Status                |                  Scan History                   |
| :---------------------------------------------------: | :---------------------------------------------: |
| ![Components View](./screenshots/components_view.png) | ![History View](./screenshots/history_view.png) |

|                        Scan Profiles                        |                   Settings                    |
| :---------------------------------------------------------: | :-------------------------------------------: |
| ![Profile Management](./screenshots/profile_management.png) | ![Config View](./screenshots/config_view.png) |

</div>

---

## Quick Start

### Flatpak (Recommended)

```bash
flatpak install flathub io.github.linx_systems.ClamUI
flatpak run io.github.linx_systems.ClamUI
```

### From Source

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
./scripts/local-run.sh
```

Stock Ubuntu/Pop!_OS 22.04 does not satisfy the current source dependency floor: `PyGObject>=3.56.3`
requires GLib 2.80+, while those releases ship GLib 2.72. Use the Flatpak there, or develop in an environment with newer GLib.

> **Host ClamAV required:** Every installation format (Flatpak, AppImage, Debian package, and source) uses host
> ClamAV and does not bundle its engine or database. Install host `clamscan` and `freshclam`; daemon mode also
> requires host `clamd` and `clamdscan`.


> **More Installation Options:** See the [Installation Guide](./docs/INSTALL.md) for .deb packages and system-wide installation

> **New users:** Start with the [Getting Started Guide](./docs/user-guide/getting-started.md) for a step-by-step introduction

---

## Usage

### GUI Application

1. Launch ClamUI from your application menu or terminal
2. Select a file or folder to scan
3. Click "Scan" to start the antivirus scan
4. View results and take action on any threats detected

### Command Line

ClamUI includes a full CLI for headless use. Run `clamui` without arguments to launch the GUI, or use subcommands:

```bash
# Launch the graphical interface
clamui

# Scan files or directories
clamui scan /path/to/file
clamui scan /home/user/Downloads --profile "Quick Scan" --quarantine --json

# Manage quarantined files
clamui quarantine list
clamui quarantine restore 42
clamui quarantine delete 42

# Manage scan profiles
clamui profile list
clamui profile show "Full Scan"
clamui profile export "Quick Scan" backup.json
clamui profile import backup.json

# View ClamAV and ClamUI status
clamui status
clamui status --json

# View scan history
clamui history
clamui history --limit 50 --type scan --json

# Install the privileged helper and polkit policy (native host only)
sudo clamui install-privileged-helper

# Get help
clamui help
clamui help scan
```

All subcommands support `--json` for scripting. Exit codes: 0 = clean/success, 1 = threats found, 2 = error.

> **Detailed Instructions:** See the [User Guide](./docs/USER_GUIDE.md)

---

## Configuration

ClamUI stores user preferences and can be configured through the Preferences dialog or by editing the configuration file directly.

**Configuration Location:** `~/.config/clamui/settings.json`

### Key Configuration Options

<table>
<tr>
<th width="25%">Category</th>
<th width="75%">Description</th>
</tr>
<tr>
<td><strong>Scan Backend</strong></td>
<td>Choose between automatic detection, daemon (clamd), or direct clamscan</td>
</tr>
<tr>
<td><strong>ClamAV Configuration</strong></td>
<td>Edit clamd.conf and freshclam.conf directly, with validation and automatic service restart</td>
</tr>
<tr>
<td><strong>On-Access Scanning</strong></td>
<td>Configure real-time file monitoring via clamonacc with path, thread, and size limits</td>
</tr>
<tr>
<td><strong>Notifications</strong></td>
<td>Control desktop notifications for scan results and updates</td>
</tr>
<tr>
<td><strong>Auto-Quarantine</strong></td>
<td>Automatically quarantine detected threats</td>
</tr>
<tr>
<td><strong>Scheduled Scans</strong></td>
<td>Configure automatic scanning with systemd or cron</td>
</tr>
<tr>
<td><strong>System Tray</strong></td>
<td>Optionally start normal launches in the tray; closing behavior is configured separately</td>
</tr>
<tr>
<td><strong>Scan Profiles</strong></td>
<td>Create custom scan configurations with exclusion patterns</td>
</tr>
<tr>
<td><strong>Device Scanning</strong></td>
<td>Automatically scan USB drives and external storage when connected</td>
</tr>
<tr>
<td><strong>Debug &amp; Logging</strong></td>
<td>Configure log verbosity, export logs, and manage log storage</td>
</tr>
</table>

<br>

> **For complete configuration reference:** See the [Configuration Reference](./docs/CONFIGURATION.md) for all settings and examples

---

## Documentation

Comprehensive guides to help you get the most out of ClamUI:

<table>
<tr>
<th width="30%">Document</th>
<th width="70%">Description</th>
</tr>
<tr>
<td><a href="https://clamui.com"><strong>ClamUI Website</strong></a></td>
<td>Public website with feature highlights, screenshots, install options, and latest release links</td>
</tr>
<tr>
<td><a href="./docs/user-guide/getting-started.md"><strong>Getting Started</strong></a></td>
<td><em>New!</em> Quick start guide for installation, first use, and next steps</td>
</tr>
<tr>
<td><a href="./docs/USER_GUIDE.md"><strong>User Guide</strong></a></td>
<td>Complete guide to using ClamUI features</td>
</tr>
<tr>
<td><a href="./docs/INSTALL.md"><strong>Installation Guide</strong></a></td>
<td>Flatpak, .deb, context menu, and tray setup</td>
</tr>
<tr>
<td><a href="./docs/TROUBLESHOOTING.md"><strong>Troubleshooting Guide</strong></a></td>
<td>Common issues and solutions</td>
</tr>
<tr>
<td><a href="./docs/DEVELOPMENT.md"><strong>Development Guide</strong></a></td>
<td>Dev environment, testing, and contributing</td>
</tr>
<tr>
<td><a href="./docs/SCAN_BACKENDS.md"><strong>Scan Backend Guide</strong></a></td>
<td>Backend options, performance comparison, and selection guide</td>
</tr>
<tr>
<td><a href="./SECURITY.md"><strong>Security Policy</strong></a></td>
<td>Security contact and reporting</td>
</tr>
</table>

---

## Requirements

ClamUI requires the following components to be installed on your system:

<table>
<tr>
<th width="30%">Component</th>
<th width="70%">Description</th>
</tr>
<tr>
<td><strong>ClamAV</strong></td>
<td>All installation formats use host <code>clamscan</code> and <code>freshclam</code>; ClamUI does not bundle the engine or virus database. Daemon mode also requires host <code>clamd</code> and <code>clamdscan</code>.</td>
</tr>
<tr>
<td><strong>GTK 4.6+ + libadwaita 1.1+</strong></td>
<td>For the graphical interface</td>
</tr>
<tr>
<td><strong>Python 3.11+</strong></td>
<td>With PyGObject bindings</td>
</tr>
</table>

<br>

> **Platform-specific installation:** See the [Installation Guide](./docs/INSTALL.md) for dependency installation instructions

---

## Contributing

Contributions are welcome! Check out the [Development Guide](./docs/DEVELOPMENT.md) for:

- Setting up the development environment
- Running tests with coverage
- Code style guidelines
- Submitting pull requests

---

## License

This project is open source. See [LICENSE](LICENSE) file for details.

---

<div align="center">

**Made with care for the Linux community**

[Website](https://clamui.com) • [Star on GitHub](https://github.com/linx-systems/clamui) • [Report Bug](https://github.com/linx-systems/clamui/issues) • [Request Feature](https://github.com/linx-systems/clamui/issues)

</div>
