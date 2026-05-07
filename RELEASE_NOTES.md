# ClamUI v0.1.8

Security hardening, Flatpak host-ClamAV fixes, tray reliability, and Spanish translation support.

## Highlights

### Security Hardening

- Closed two privileged config-save escalation bugs by routing native and Flatpak config writes through one validated helper path
- Added UID-checked staging directories, `O_NOFOLLOW` source validation, destination allowlisting, and atomic config installs for `clamui-apply-preferences`
- Prevented ClamAV scan path arguments from being interpreted as command-line flags by inserting `--` before user-selected paths
- Masked stored quarantine permissions to regular mode bits so restore cannot reapply setuid, setgid, or sticky bits
- Refused symlink restore destinations and added no-follow restore fallback handling for cross-filesystem quarantine restores
- Hardened scheduled-scan crontab updates so unrelated user crontab entries are not removed by marker-like text

### Flatpak & Packaging

- Flatpak now requires host ClamAV tools instead of bundling ClamAV, keeping virus database ownership on the host system
- Fixed Flatpak daemon file-list scans so `clamdscan` receives host-visible paths correctly
- Improved host ClamAV detection, config access, updater behavior, and audit checks from inside the Flatpak sandbox
- Refreshed Python dependency locks and Flatpak runtime pins, including `cryptography 48.0.0`, `packaging 26.2`, and `more-itertools 11.0.2`
- Added a draft GitHub release workflow for tag-triggered release artifacts

### Reliability & UX

- Fixed an updater gettext regression that could break force-update error handling
- Stopped live scanner output parsing from spinning at 100% CPU after stdout EOF
- Restored tray profile menu updates and added crash detection with bounded tray subprocess respawns
- Tracked delayed removable-device scan requeues so shutdown and removal can cancel pending scan starts
- Cleaned up temporary EICAR self-test files on normal completion, errors, and process exit
- Parsed timezone-aware scan timestamps consistently for statistics timeframes
- Stored VirusTotal scan timestamps in UTC instead of local-naive time
- Added visible ClamUI website links to the README and refreshed release workflow dependencies

### Internationalization

- Added Spanish translation support, including `po/es.po` and `po/LINGUAS` registration

## Install

**Flathub** (recommended):
```bash
flatpak install flathub io.github.linx_systems.ClamUI
```

**AppImage**: Download the `ClamUI-0.1.8-x86_64.AppImage` from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.1.8). Existing AppImages can delta-update via zsync.

**GitHub Release**: Download from the [Releases page](https://github.com/linx-systems/clamui/releases/tag/v0.1.8)

**From source**:
```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui && uv sync && uv run clamui
```

## Contributors

Thanks to everyone who contributed code, translations, and bug reports for this release. See the [full commit log](https://github.com/linx-systems/clamui/compare/v0.1.7...v0.1.8) for details.
