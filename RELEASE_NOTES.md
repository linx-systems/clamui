# ClamUI v0.5.0 release notes

ClamUI v0.5.0 is the first Rust/Tauri desktop release. It retains ClamUI's public identity, host-ClamAV integration, and established user data and command-line workflows.

## Highlights

### A rebuilt desktop, with familiar workflows retained

- ClamUI now uses a headless Rust core with a Tauri 2/WebKitGTK and React desktop instead of the Python/PyGObject application runtime.
- The public desktop identity, headless CLI, host-ClamAV boundary, and existing XDG JSON and SQLite data layouts are retained, together with scanning, history, quarantine, profiles, exports, clipboard actions, tray controls, and file-manager integration.
- The desktop and Preferences are more compact and consistent, with clearer scan details, accessible keyboard and state feedback, native tray integration, and improved light and dark themes.

### New read-only network and security insight

- A new **Network** view provides a snapshot of current TCP/UDP listeners and connections, with filtering, copying, and permission-aware process attribution. It does not capture or monitor network traffic.
- VirusTotal IP reports open only in the browser after explicit confirmation for conservatively accepted public IP addresses. ClamUI does not send port or process information, and this is separate from file-upload features.
- The advisory firewall audit now inventories UFW, firewalld, nftables, IPv4/IPv6 iptables, and supported management interfaces. It remains read-only and non-interactive: ClamUI does not change firewall rules.

### Safer protected-configuration recovery

- **Save & Apply** records the proposals selected at click time and reports durable outcomes, including partial failures.
- Failed or unconfirmed configuration writes can expose **See Configuration**, which shows the exact native ClamAV configuration attempted for each full target path and offers separate copy actions for manual recovery. It never applies files or bypasses helper trust; because a failure can follow partial writes, inspect the current file before replacing it manually.
- Missing helpers are distinguished from untrusted helpers. On supported hosts, ClamUI can offer an explicit, Polkit-confirmed installation of a verified matching signed helper package; retry Save & Apply after installation. Unsupported or untrusted cases keep manual repair as the safe path.

### Packaging and host integration

- The v0.5.0 GitHub release package set uses matching native Debian application and helper packages, an x86_64 AppImage with `.zsync` metadata, and Flatpak bundles for `x86_64` and `aarch64`.
- Helper-only Fedora RPM support covers `x86_64` and `aarch64`. Protected-preference recovery requires the matching signed RPM and detached `.rpm.asc` asset for the host architecture.
- After the v0.5.0 GitHub assets are attached, use its Flatpak bundles; the separate Flathub store listing remains the Python 0.4.1 release until a later Flathub submission and rollout.

### Security dependency maintenance

- Updated `ctutils`, `rustls-webpki`, `webpki-roots`, `zip`, and the Vite build tool to versions addressing identified dependency advisories, and removed the unused archive-codec/zstd dependency chain. This maintenance does not by itself establish application exploitability, ZIP-extraction reachability, or a complete audit result.

## Reliability and usability improvements

- Daemon scans now handle filenames containing carriage returns or newlines without losing exclusions, original detection paths, progress, or partial results.
- Scan detection and progress reporting are more consistent across standalone and daemon backends; Clamd size-unit repair, debug-log retention, and scheduled scan quoting are more reliable.
- Addressed configuration-save races, scan close/focus behavior, quarantine startup contention, history totals, scan-detail navigation, responsive profile layouts, and retained CLI/profile compatibility—including literal profile paths and supported flag forms.
- The rewritten interface restores nine active locales: German, English, Spanish, French, Hungarian, Italian, Norwegian Bokmål, Brazilian Portuguese, and Simplified Chinese. Norwegian Bokmål updates, plural and placeholder handling, and contributor and translator credits are included.

## Before upgrading

- ClamUI continues to use the host ClamAV engine and databases. Install host `clamscan` and `freshclam`; daemon scanning also requires host `clamd` and `clamdscan`.
- Native builds require system GTK3 and WebKitGTK 4.1. Flatpak supplies the desktop runtime but still uses host ClamAV.
- Protected host settings still require a trusted, compatible helper and Polkit authorization. Use the matching signed helper package when installation or repair is needed; a matching version string alone does not prove compatibility. Do not bypass signature checks or change permissions on unknown executables.
- Existing user data, the public app ID, and CLI compatibility are preserved; no data deletion or reinstallation is required.