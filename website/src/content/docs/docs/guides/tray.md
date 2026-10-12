---
title: Use the system tray
description: Run ClamUI in the background when the desktop supports SNI.
---

ClamUI's tray is optional. It uses a separate GIO D-Bus StatusNotifierItem process and DBusMenu, not an AppIndicator library. KDE Plasma, Cinnamon, MATE, and Budgie generally provide an SNI watcher; GNOME requires [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/). Native/source installations also need `libdbusmenu` bindings.

## Configure behavior

In **Preferences → Behavior**:

- **When closing window:** choose minimize to tray, quit, or ask. Without a tray, closing quits.
- **Start in System Tray:** hides ordinary launches after the tray service starts. Launches with a scan target stay visible.
- `minimize_to_tray` is a JSON-only setting for the window-manager minimize button.

Verify that your desktop actually shows the icon before relying on background startup. A tray failure does not prevent normal GUI use.

## Tray actions

Right-click the icon to show/hide the window, run Quick Scan or Full Scan, select a saved profile, update definitions, or quit. Scans continue when the window is hidden; quitting cancels them. Tray status reflects normal, scanning, error, and attention states.

## Autostart

Enable **Start in System Tray**, then create a user autostart entry if you want launch-on-login. Keep path scans separate: passing a file/folder deliberately opens the window.

For design, IPC, lifecycle, and security limits, see [tray subprocess architecture](/docs/contributing/architecture/).