# ClamUI v0.5.1 release notes

ClamUI v0.5.1 is a patch release for Flatpak privileged-helper installation and error reporting.

## Fixes

- Uses authoritative host passwd lookups for helper downloads and configuration staging.
- Selects and executes trusted host checksum and GnuPG tools while retaining pinned-signature and archive-member checks.
- Keeps complete installation errors readable and selectable, including long paths.

## Validation and packaging

- The existing pinned-signature and archive-member validation remains in place.
- Manual Flatpak helper installation has been confirmed.
- Signed Debian packages, privileged-helper RPMs, and the x86_64 AppImage were verified from the v0.5.1 tag builds.
- GitHub Flatpak bundles passed source, metadata, and integrity checks for x86_64 and aarch64.
- Flathub test builds and manifest checks passed for x86_64 and aarch64.
- Clean-file and EICAR scans passed through host ClamAV; quarantine, guarded restore, and deletion were verified using disposable files.
