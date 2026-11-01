---
title: Use the system tray
description: Run ClamUI in the background when the desktop supports SNI.
---

ClamUI's tray is optional. It uses an in-process, pure-Rust StatusNotifierItem and DBusMenu implementation. It does not run the retired Python tray subprocess and does not require a GTK or `libdbusmenu` tray binding. KDE Plasma, Cinnamon, MATE, and Budgie generally provide an SNI watcher; GNOME requires [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/) or another compatible watcher.

## Configure behavior

In **Preferences → Behavior**:

- **When closing window:** choose minimize to tray, quit, or ask. Without a tray, closing quits.
- **Start in System Tray:** hides ordinary launches after the native SNI item is accepted. Launches with a scan target stay visible.
- `minimize_to_tray` is a JSON-only setting for the window-manager minimize button.

Verify that your desktop actually shows the icon before relying on background startup. A tray failure does not prevent normal GUI use.

## Tray actions

Right-click the icon to show/hide the window, run Quick Scan or Full Scan, select a saved profile, update definitions, or quit. The normal protected state uses ClamUI's bundled official logo, so source, AppImage, Flatpak, and Debian installs do not depend on a host icon-theme asset. Temporary warning, scanning, and threat states retain their desktop status indicators. Scans continue when the window is hidden; quitting cancels them.

## Autostart

Enable **Start in System Tray**, then create a user autostart entry if you want launch-on-login. Keep path scans separate: passing a file or folder deliberately opens the window.

For design, native event handling, lifecycle, and security limits, see [Rust/Tauri desktop and tray architecture](/docs/contributing/architecture/).