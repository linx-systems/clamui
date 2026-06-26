# ClamUI Scan Backend Options

ClamUI supports three scan backends, configured in **Preferences > Scanner Settings > Scan Backend** or via `"scan_backend"` in `settings.json`.

## Backend Comparison

| Aspect | Auto (default) | Daemon | Clamscan |
|--------|---------------|--------|----------|
| **Scan startup** | Depends on daemon availability | Instant (<1 sec) | 3-10 sec (loads database) |
| **Memory (idle)** | ~50 MB | 500 MB-1 GB | ~50 MB |
| **Memory (scanning)** | 500 MB-1 GB | 500 MB-1 GB | 500 MB-1 GB |
| **Parallel scanning** | When daemon available | Yes (`--multiscan`) | No |
| **Setup required** | None | Install & run clamd | None |
| **Reliability** | High (auto-fallback) | Requires running daemon | High |

## Auto Mode (Recommended)

Checks daemon availability before each scan (with 60-second cache) and uses the daemon if reachable, otherwise falls back to clamscan. Best for most users.

**Detection process:**
1. Checks if `clamdscan` is installed
2. Pings clamd socket via `clamdscan --ping`
3. If daemon responds: uses daemon backend
4. If unavailable: falls back to clamscan

The availability check result is cached for 60 seconds to avoid repeated socket probes on consecutive scans.

## Daemon Backend

Uses the clamd background service exclusively. Database stays in memory for instant scan startup. Supports `--multiscan` (parallel) and `--fdpass` (file descriptor passing). Scans fail if clamd is not running.

**Best for:** Frequent/scheduled scans, servers, performance-critical environments.

## Clamscan Backend

Uses the standalone `clamscan` command. Loads the database from disk for each scan (3-10 sec overhead). No background service needed. ClamUI forwards the relevant `clamd.conf` limits (`MaxFileSize`, `MaxScanSize`, `MaxRecursion`, `MaxFiles`) as `--max-filesize`/`--max-scansize`/`--max-recursion`/`--max-files` so scan limits stay consistent with the daemon backend.

**Best for:** Occasional scans, minimal installations, troubleshooting.

## Daemon Setup

### Ubuntu/Debian

```bash
sudo apt install clamav-daemon
sudo systemctl enable clamav-daemon
sudo systemctl start clamav-daemon
clamdscan --version  # Verify
```

### Fedora

```bash
sudo dnf install clamd clamav-update
sudo freshclam
sudo systemctl enable clamd@scan
sudo systemctl start clamd@scan
```

ClamUI targets Fedora's `scan.conf` layout automatically and talks to `clamd` with `clamdscan --config-file=/etc/clamd.d/scan.conf ...`.
If the service is running but the daemon still shows unavailable, check the socket permissions configured by `LocalSocketMode` and `LocalSocketGroup` in `/etc/clamd.d/scan.conf`.

### Arch Linux

```bash
sudo pacman -S clamav
sudo systemctl enable clamav-daemon
sudo systemctl start clamav-daemon
```

### Flatpak Users

The ClamUI Flatpak does not bundle ClamAV. Install `clamscan` and `freshclam` on the **host system**; ClamUI runs them through `flatpak-spawn --host`. To use the daemon backend, install and start host `clamd`/`clamdscan`. ClamUI auto-detects the host daemon.

## Exit Codes

Both backends return standard ClamAV exit codes: `0` = clean, `1` = infected, `2` = error.

## Socket Locations

ClamUI auto-detects the clamd socket by checking:

- `/var/run/clamav/clamd.ctl` (Ubuntu/Debian)
- `/run/clamav/clamd.ctl` (alternative)
- `/run/clamd.scan/clamd.sock` (Fedora/RHEL)
- `/var/run/clamd.scan/clamd.sock` (legacy Fedora path)

Override with `"daemon_socket_path"` in settings.json, or check `grep "LocalSocket" /etc/clamav/clamd.conf` on Debian/Ubuntu and `grep "LocalSocket" /etc/clamd.d/scan.conf` on Fedora/RHEL.

## See Also

- [CONFIGURATION.md](CONFIGURATION.md) - Full settings reference
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues and solutions
- [ClamAV Documentation](https://docs.clamav.net/)
