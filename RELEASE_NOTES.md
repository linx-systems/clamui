# ClamUI v0.4.0

Safer configuration writes, scan-result reliability, GTK baseline compatibility, and host-integration hardening.

## Highlights

### Configuration, Compatibility & Installation

- **Safer preferences** — preference saves now enforce ClamAV recursion limits, report configuration-load failures clearly, and retain standalone scanner settings when a Flatpak host helper is unavailable.
- **GTK 4.6 / libadwaita 1.1 support restored** — ClamUI no longer relies on newer GTK APIs, preserving compatibility with the supported baseline.
- **Flatpak and Python compatibility** — the release includes a version-matched `clamui-privileged-helper_0.4.0_all.deb` host companion for applying system ClamAV preferences from Flatpak; helper builds support Python 3.10 and glob conversion supports Python 3.14. (#170)
- **Distro-aware install advice** — security-audit install commands now use `/etc/os-release` to select Debian-, Fedora-, or Arch-family commands, and safely omit a command for unknown distributions.

### Scan, Update & Quarantine Reliability

- **More trustworthy scan results** — multi-target scans are safe under concurrent invocation, accumulated output no longer duplicates trailing partial lines, all-failed scans report errors, and recognized nonfatal ClamAV warnings are presented consistently.
- **Safer database updates** — forced database updates are staged before they replace the active database.
- **Safer quarantine actions** — restore and permanent-delete actions require confirmation; dialogs close with Escape; and quarantine copies reject short writes to protect file integrity.

### Security & Host Integration

- **Canonical privileged writes** — elevated configuration writes fail closed unless the trusted helper and destination resolve to canonical paths.
- **Token-safe scheduled commands** — scheduled scan commands are built from tokens rather than re-splitting shell strings.
- **Sanitized AppImage host helpers** — all host helpers launched by AppImage builds run with a cleaned environment.

### Translations & Dependencies

- Refreshed French and Simplified Chinese translations, added translatable UI strings, and updated Python, Flatpak, CI, and runtime dependencies including cryptography 50.0.0.

## Install

**Flathub** (recommended):
```bash
flatpak install flathub io.github.linx_systems.ClamUI
```

**AppImage**: Download `ClamUI-0.4.0-x86_64.AppImage` from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.4.0).

**GitHub Release**: Download `clamui_0.4.0_all.deb` or the `clamui-x86_64.flatpak` / `clamui-aarch64.flatpak` bundle from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.4.0). Flatpak users who need to apply system-wide ClamAV preferences can install the matching `clamui-privileged-helper_0.4.0_all.deb` host companion.

**From source**:
```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui && uv sync && uv run clamui
```

## Contributors

Thanks to everyone who contributed code, translations, and bug reports for this release. See the [full commit log](https://github.com/linx-systems/clamui/compare/v0.3.0...v0.4.0) for details.
