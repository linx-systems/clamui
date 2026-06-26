# ClamUI v0.3.0

Privileged ClamAV configuration improvements, Flatpak host-config fixes, CLI scan reliability, and security hardening.

## Highlights

### Configuration & Flatpak

- **Privileged helper installer** — `clamui install-privileged-helper` installs the `clamui-apply-preferences` wrapper and polkit policy needed for elevated ClamAV configuration writes. (#143)
- **Flatpak host configuration persistence** — Flatpak preferences now persist host ClamAV configuration through the privileged helper instead of assuming sandbox-local ClamAV paths. (#136)
- **Less unnecessary elevation** — ClamUI skips elevation prompts when it is already running as root and fixes elevation decision/reporting edge cases.

### Scan & CLI Reliability

- **CLI path handling fixed** — one-shot CLI scans now scan every path provided on the command line instead of only the first path.
- **Saved scan settings honored** — scheduled and one-shot CLI scans now apply saved exclusions and backend settings consistently.
- **Benign ClamAV warnings tolerated** — scans no longer fail solely because ClamAV reports expected size-limit warnings.
- **Database age parsing fixed** — ClamUI now parses CVD/CLD database headers robustly even when compressed database payload bytes immediately follow the header.

### Security Hardening

- Sanitized untrusted profile, scan, quarantine, audit, and terminal output paths to reduce log/terminal injection risk.
- Hardened profile import/name normalization, scheduler quoting, Unicode sanitizer coverage, ClamAV config parsing, quarantine cleanup, and audit verdict handling.
- Improved exclusion matching bounds in scanner and daemon scanner paths and preserved detections on ClamAV error exits.

### VirusTotal, UI & Packaging

- VirusTotal retries now resend the full request body, large uploads are supported, and all engine-result buckets are counted.
- VirusTotal result flow, stuck spinners, tray resynchronization, and deliberate tray shutdown behavior were repaired.
- AppImage execution now strips bundled Python/GI environment variables before launching host tools. (#155)
- Debian packaging accepts `pkexec | policykit-1` for Debian 13 compatibility.
- Python, Flatpak, website, and translation assets were refreshed, and a real-GTK construction smoke test now covers all views, preference pages, and dialogs.

## Install

**Flathub** (recommended):
```bash
flatpak install flathub io.github.linx_systems.ClamUI
```

**AppImage**: Download `ClamUI-0.3.0-x86_64.AppImage` from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.3.0).

**GitHub Release**: Download packages from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.3.0).

**From source**:
```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui && uv sync && uv run clamui
```

## Contributors

Thanks to everyone who contributed code, translations, and bug reports for this release. See the [full commit log](https://github.com/linx-systems/clamui/compare/v0.2.0...v0.3.0) for details.
