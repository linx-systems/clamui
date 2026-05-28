# ClamUI v0.2.0

Portmaster privacy-filter audit integration, quarantine restore hardening, and scanner reliability fixes.

## Highlights

### Security Audit

- **Portmaster privacy-filter check** — a new optional section in the system security audit probes the local Portmaster API (`127.0.0.1:817`) to report whether Portmaster is running, installed-but-stopped, or not installed, and shows per-module health when an API token is available. It uses Portmaster's own in-app authorization flow (no manual token paste), stores tokens in the system keyring, and only ever produces `SKIPPED` — never `FAIL`/`WARNING` — so it never pollutes the audit summary on systems without Portmaster.

### Security Hardening

- **Quarantine restore hardening** (GHSA-xhhj-qvvr-vhwq) — reworked quarantine file handling to close path- and metadata-handling vulnerabilities in the restore flow.

### Reliability & UX

- **Scanner hang fixed** — full scans could freeze mid-run (reported around ~72%) when ClamAV filled its stderr pipe buffer with permission warnings and LibClamAV notices, blocking the child process. The scanner now drains stderr concurrently with stdout, with regression tests covering the deadlock. (Fixes #146)
- **Tray reliability under Flatpak** — StatusNotifierItem registration reworked for stricter tray hosts (Plasma 6, Ayatana indicator, xapp-sn-watcher) and Flatpak's D-Bus proxy: registers the SNI object path instead of owning a well-known bus name, exposes ARGB32 icon-pixmap fallbacks, and mirrors the attention-icon so the correct icon renders.

### Documentation

- **INSTALL.md** now documents installation via AppMan / AM.

### Maintenance

- Website migrated to **Astro 6 + Tailwind 4** (Node ≥22.12), with the toolchain switched to a bun lockfile.
- Refreshed Python and Flatpak runtime dependencies — cryptography 48, urllib3 2.7.0, certifi, packaging 26.2, idna 3.15, numpy, fonttools, PyGObject 3.56.3, and more (pins + wheel hashes regenerated).

## Install

**Flathub** (recommended):
```bash
flatpak install flathub io.github.linx_systems.ClamUI
```

**AppImage**: Download `ClamUI-0.2.0-x86_64.AppImage` from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.2.0). Existing AppImages can delta-update via zsync.

**GitHub Release**: Download from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.2.0)

**From source**:
```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui && uv sync && uv run clamui
```

## Contributors

Thanks to everyone who contributed code, translations, and bug reports for this release. See the [full commit log](https://github.com/linx-systems/clamui/compare/v0.1.8...v0.2.0) for details.
