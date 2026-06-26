# ClamUI User Guide

>Welcome to ClamUI! If you're new to the application, start with the **[Getting Started Guide](user-guide/getting-started.md)** for a quick introduction to installation, first use, and next steps.
>
> This guide will help you get the most out of your antivirus protection on Linux.

## What is ClamUI?

ClamUI is a user-friendly desktop application that brings the powerful ClamAV antivirus engine to your Linux desktop with an intuitive graphical interface. No command-line knowledge required!

Whether you're downloading files, managing USB drives, or just want peace of mind about your system's security, ClamUI makes virus scanning simple and accessible.

Beyond on-demand scanning, ClamUI includes a **Security Audit** view that reviews your system's overall security posture — ClamAV health, firewall, mandatory access control, automatic updates, intrusion detection, SSH hardening, and Portmaster — with optional deeper checks via Lynis and chkrootkit. It can also **automatically scan USB and removable drives** the moment they are connected.

## Who is this guide for?

This guide is written for Linux desktop users who want straightforward antivirus protection without dealing with terminal commands. If you've installed ClamUI via Flatpak, a .deb package, an AppImage, or any other method, you're in the right place!

You don't need to be a Linux expert or understand how ClamAV works under the hood. This guide focuses on **what you can do** with ClamUI, not how the code works.

---

## User Guide Topics

The user guide is organized into focused topics for easy navigation. Choose the section most relevant to what you're trying to accomplish:

### 🚀 [Getting Started](user-guide/getting-started.md)

**New to ClamUI?** Start here to learn how to launch the application, complete first-time setup, understand the main window, navigate between views, and run your first scan. Includes step-by-step guidance on selecting files, understanding scan progress, and interpreting results.

### 🔍 [Scanning for Viruses](user-guide/scanning.md)

Learn all the ways to scan files and folders for threats: browse for files, drag-and-drop from your file manager, test with EICAR, understand scan progress indicators, read detailed scan results, and interpret threat severity levels. Essential reading for effective threat detection.

### 📋 [Scan Profiles](user-guide/profiles.md)

Master scan profiles to save time and standardize your scanning workflow. Learn about the three default profiles (Quick Scan, Full Scan, Home Folder), create custom profiles tailored to your needs, edit existing profiles, manage exclusions, and import/export profiles for backup or sharing.

### 🛡️ [Quarantine Management](user-guide/quarantine.md)

Understand how ClamUI safely isolates threats. Learn what quarantine is and how it works, view quarantined files with detailed metadata, restore files if they're false positives, permanently delete confirmed threats, clear old items, and understand the secure storage system.

### 📜 [Scan History](user-guide/history.md)

Access and analyze your complete scanning history. View past scan results with filtering and pagination, understand log entries and their status indicators, export scan logs to CSV for record-keeping, review daemon logs for advanced troubleshooting, and follow best practices for log management.

### ⏰ [Scheduled Scans](user-guide/scheduling.md)

Set up automated, hands-free protection with scheduled scans. Learn why scheduled scans matter, enable automatic scanning, choose the right scan frequency (hourly, daily, weekly, monthly), set optimal scan times, configure scan targets and profiles, enable battery-aware scanning on laptops, configure auto-quarantine for hands-off protection, and manage your schedules with systemd or cron.

### 📊 [Statistics Dashboard](user-guide/statistics.md)

Monitor your protection status at a glance. Understand the protection status overview, view comprehensive scan statistics, filter by timeframe (Day, Week, Month, All Time), interpret scan activity charts and trends, and use quick actions to export or update virus definitions.

### ⚙️ [Settings and Preferences](user-guide/settings.md)

Customize ClamUI to match your needs and system configuration. Access the preferences window, navigate the multi-page settings interface, configure application behavior (minimize to tray, notifications, close behavior), choose scan backends (auto, daemon, clamscan), manage database update settings with freshclam, configure scanner options (max file size, recursive scanning), set up on-access scanning for real-time protection, configure automatic scanning of USB and removable drives, manage global exclusion patterns, integrate VirusTotal for enhanced threat intelligence, enable debug logging, configure notification behavior, and understand settings storage and best practices.

### 🔔 [System Tray and Background Features](user-guide/tray.md)

Keep ClamUI accessible with system tray integration. Enable the system tray icon, configure minimize to tray behavior, use start minimized for background operation, access quick actions from the tray menu (scan, update, quarantine, quit), and understand how background scanning works with tray status indicators.

### 🔧 [Troubleshooting](user-guide/troubleshooting.md)

Solve common issues quickly with this reference guide. Fix "ClamAV not found" errors with installation verification, resolve daemon connection issues, diagnose scan errors and permission problems, troubleshoot quarantine issues (restore failures, database corruption), debug scheduled scans that won't run, and address performance issues (slow scans, high memory usage).

### 🖥️ Command-Line Interface

Use ClamUI without a graphical interface for scripting, automation, and headless servers. Available subcommands: `scan` (one-shot scanning with profile and quarantine support), `quarantine` (list, restore, delete quarantined files), `profile` (list, show, export, import scan profiles), `status` (ClamAV version, backend, daemon info), `history` (scan log viewer with type filtering), `help` (command overview and per-topic help), and `install-privileged-helper` (installs the privileged helper and polkit policy so ClamUI can write system ClamAV configuration; requires `sudo`). Most commands support `--json` output for integration with other tools. Run `clamui help` for full usage.


### ❓ [Frequently Asked Questions](user-guide/faq.md)

Get quick answers to common questions about ClamUI and antivirus scanning on Linux. Topics include: ClamUI vs ClamAV, how often to scan, what to do when threats are found, handling false positives, system performance impact, quarantine data safety, virus definition updates, and scanning external drives and USB devices.

---

## Quick Reference

### Keyboard Shortcuts

ClamUI supports keyboard shortcuts for faster navigation:

| Shortcut | Action                    |
|----------|---------------------------|
| `Ctrl+1` | Switch to Scan View       |
| `Ctrl+2` | Switch to Update View     |
| `Ctrl+3` | Switch to Logs View       |
| `Ctrl+4` | Switch to Components View |
| `Ctrl+5` | Switch to Quarantine View |
| `Ctrl+6` | Switch to Statistics View |
| `Ctrl+7` | Switch to Audit View      |
| `Ctrl+S` | Start Scan                |
| `Ctrl+U` | Start Database Update     |
| `Ctrl+Q` | Quit ClamUI              |
| `Ctrl+,` | Open Preferences          |

Shortcuts work from any view and automatically switch to the relevant view.

### Configuration Files

- **Settings**: `~/.config/clamui/settings.json`
- **Profiles**: `~/.config/clamui/profiles.json`
- **Quarantine Database**: `~/.local/share/clamui/quarantine.db`
- **Quarantine Files**: `~/.local/share/clamui/quarantine/`
- **Scan Logs**: `~/.local/share/clamui/logs/`

---

## Need More Help?

If you're experiencing issues not covered in this guide:

- **Report bugs**: Visit the [GitHub Issues](https://github.com/linx-systems/clamui/issues) page
- **Technical documentation**: See [DEVELOPMENT.md](./DEVELOPMENT.md) for developer information
- **Installation help**: Check the [Installation Guide](./INSTALL.md)
- **Configuration reference**: See [CONFIGURATION.md](./CONFIGURATION.md) for detailed configuration options

---
