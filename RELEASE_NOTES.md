# ClamUI v0.5.1 release notes

ClamUI v0.5.1 is a patch release for Flatpak privileged-helper installation and error reporting.

## Fixes

- Uses authoritative host passwd lookups for helper downloads and configuration staging.
- Selects and executes trusted host checksum and GnuPG tools while retaining pinned-signature and archive-member checks.
- Keeps complete installation errors readable and selectable, including long paths.

## Validation and packaging

- The existing pinned-signature and archive-member validation remains in place.
- Manual Flatpak helper installation has been confirmed.
- Post-tag CI and packaging work remain release-maintenance steps; these notes do not imply publication status.
