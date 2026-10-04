---
title: Scan backends
description: Choose auto, daemon, or standalone ClamAV scanning.
---

Set the backend in **Preferences → Scanner Settings** or `scan_backend` in `settings.json`.

| Backend | Startup | Idle memory | Use it when |
| --- | --- | --- | --- |
| Auto (default) | daemon if reachable; otherwise `clamscan` | about 50 MB without daemon | Most desktops |
| Daemon | immediate | 500 MB–1 GB for `clamd` | Frequent, scheduled, or performance-sensitive scans |
| Clamscan | loads definitions each scan (about 3–10 seconds) | about 50 MB | Occasional scans, minimal setup, or daemon diagnosis |

Auto checks `clamdscan --ping` and caches availability for 60 seconds. Daemon mode uses `--multiscan` and `--fdpass`; scans fail when the daemon is down. `clamscan` has no background service and forwards relevant `clamd.conf` limits (`MaxFileSize`, `MaxScanSize`, `MaxRecursion`, and `MaxFiles`) as CLI limits so both modes remain consistent.

## Install a daemon

```bash
# Debian/Ubuntu
sudo apt install clamav-daemon
sudo systemctl enable --now clamav-daemon
clamdscan --version

# Fedora
sudo dnf install clamd clamav-freshclam
sudo freshclam
sudo systemctl enable --now clamd@scan

# Arch Linux
sudo pacman -S clamav
sudo systemctl enable --now clamav-daemon
```

Fedora uses `/etc/clamd.d/scan.conf`; ClamUI invokes `clamdscan --config-file=/etc/clamd.d/scan.conf`. If a running Fedora daemon is unavailable, check its `LocalSocketMode` and `LocalSocketGroup`.

Flatpak users install all ClamAV tools on the **host**. ClamUI invokes them through `flatpak-spawn --host` and auto-detects the host daemon.

## Sockets and exit codes

ClamUI probes `/var/run/clamav/clamd.ctl`, `/run/clamav/clamd.ctl`, `/run/clamd.scan/clamd.sock`, and `/var/run/clamd.scan/clamd.sock`, after checking configured `LocalSocket`. Override with `daemon_socket_path` when necessary.

```bash
grep "LocalSocket" /etc/clamav/clamd.conf
grep "LocalSocket" /etc/clamd.d/scan.conf
```

Both modes use standard ClamAV codes: `0` clean, `1` detection, and `2` error. See [Configuration](/docs/reference/configuration/) for overrides and [Troubleshooting](/docs/troubleshooting/) for failures.