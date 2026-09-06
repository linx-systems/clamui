# Changelog

## [0.4.0] - 2026-08-23

### Added

- Added distro-aware security-audit install advice for Debian, Fedora, and Arch families; unknown distributions show no guessed command. (#184)
- Added French and Simplified Chinese translation updates and additional translatable UI strings.

### Changed

- Restored the GTK 4.6 / libadwaita 1.1 compatibility baseline.
- Made preference saves safer, retained standalone Flatpak scanner settings without a host helper, shipped the version-matched Flatpak host-helper companion package, and added Python 3.10 / 3.14 compatibility. (#170)
- Refreshed Python, Flatpak, CI, and runtime dependencies, including cryptography 50.0.0.

### Fixed

- Improved scan result handling for concurrent multi-target scans, partial output, nonfatal warnings, and all-failed scans.
- Staged forced database updates before activation.
- Added quarantine restore/delete confirmations, Escape-to-close dialogs, and short-write detection for quarantine copies.

### Security

- Hardened privileged configuration writes with canonical helper and destination validation that fails closed.
- Built scheduled scan commands from tokens and sanitized AppImage environments for every host helper.

[0.4.0]: https://github.com/linx-systems/clamui/compare/v0.3.0...v0.4.0

## [0.3.0] - 2026-06-26

### Added

- Added `clamui install-privileged-helper` for installing the privileged ClamAV configuration helper and polkit policy. (#143)
- Added a real-GTK construction smoke test covering all views, preference pages, and dialogs.

### Changed

- Flatpak ClamAV configuration preferences now persist through the host helper. (#136)
- CLI and scheduled scans now honor saved backend/exclusion settings consistently.
- Python, Flatpak, website, and translation assets were refreshed.

### Fixed

- Fixed one-shot CLI scans so every CLI-provided path is scanned.
- Fixed benign ClamAV size-limit warnings causing scan failures.
- Fixed CVD/CLD database age parsing when binary compressed payload bytes follow the text header.
- Fixed VirusTotal retry, large-upload, and engine-result counting behavior.
- Fixed VirusTotal UI result flow, stuck spinners, tray resynchronization, and deliberate tray shutdown behavior.
- Fixed AppImage host-tool execution by stripping bundled Python/GI environment variables. (#155)
- Fixed Debian package dependency compatibility with Debian 13 by accepting `pkexec | policykit-1`.

### Security

- Hardened terminal/log output sanitization, scheduler quoting, profile import handling, ClamAV config parsing, quarantine cleanup, exclusion matching, and audit verdict handling.

[0.3.0]: https://github.com/linx-systems/clamui/compare/v0.2.0...v0.3.0
