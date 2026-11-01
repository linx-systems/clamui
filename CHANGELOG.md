# Changelog

## [Unreleased]

## [0.5.0] - 2026-11-01

### Changed

- Updated the release documentation for the v0.5.0 Rust/Tauri package set and its deployment boundaries: GitHub release assets and the separate Flathub store rollout remain distinct.

- Updated `ctutils` to 0.4.4, `rustls-webpki` to 0.103.16, `webpki-roots` to 1.0.10, `zip` to 9.2.1, and Vite to 6.4.5 for identified dependency advisories; removed the unused archive-codec/zstd dependency chain. This does not assert prior application exploitability, ZIP-extraction reachability, or complete audit coverage.

- Added a separate snapshot-only **Network** sidebar for current TCP/UDP listeners and connections, endpoint copying, filtering, and permission-aware process attribution; it neither monitors traffic nor changes the advisory Audit or deep-scan workflows.
- Added explicit browser-only VirusTotal IP-report confirmation with a conservative public-IP policy; private, special-purpose, scoped, and wildcard endpoints stay disabled and no port or process data is shared.
- Expanded the advisory firewall audit with independent UFW, firewalld, nftables, IPv4/IPv6 iptables, and supported management-interface inventory while keeping host inspection read-only and non-interactive.
- Moved Save & Apply proposal validation and persistence into a GTK-free workflow, with click-time snapshots and explicit durable outcomes for partial failures.
- Added **See Configuration** to failed **Save & Apply** reports. It displays the frozen exact native ClamAV configuration attempted for each full target path, with separate copy actions for safe manual recovery; it never applies files or bypasses helper trust, and warns that a helper failure can follow partial writes.
- Added an explicit **Install Helper** offer for a missing privileged helper on supported Debian-family native, source, AppImage, and Flatpak installs; it verifies the matching signed release package before graphical Polkit authorization, preserves safe manual repair for untrusted or unsupported cases, and requires an explicit Save retry after installation.
- Added Fedora helper-only RPM support for explicit native and Flatpak-host recovery: matching signed published RPM and `.asc` assets are required, with DNF handling mutable hosts and guarded `rpm-ostree` handling Atomic desktops.
- Consolidated standalone and daemon scan-result interpretation while retaining backend-specific counting and error semantics.
- Strengthened property-based tests for log redaction, Unicode preservation, filesystem and symlink validation, scheduled-command quoting, and threat-classification precedence.
- Rendered website Mermaid diagrams into accessible light and dark SVGs at build time, removing the Mermaid JavaScript payload from documentation pages.
- Replaced cumulative threat snapshots in standalone and daemon scan progress with ordered detection deltas, avoiding quadratic copying while preserving complete final results.
- Batched live threat rows into bounded UI update turns, retained findings while the scan view is hidden, and throttled only scalar progress updates.
- Cached the selected gettext catalog so building scan-result rows no longer repeats translation-file discovery; language changes still take effect after restarting.
- Restored the nine live gettext locales (`de`, `en`, `es`, `fr`, `hu`, `it`, `nb`, `pt_BR`, and `zh_CN`), retaining bounded localized historical scan-summary recognition without shipping archived catalogs.
- Refreshed Norwegian Bokmål translations from upstream PR #251, including translator-credit labels, for the Rust/Tauri UI.
- Embedded the canonical root `AUTHORS` list in Rust packages so About shows contributors in canonical order offline, alongside genuine per-locale translator credits.
- Localized built-in scan-profile labels and unchanged preset descriptions without rewriting stored names, custom descriptions, or CLI lookup identifiers.
- Enforced exact gettext source/context/plural keys, complete plural forms, English source identity, and interpolation-placeholder preservation in translation validation.
- Applied the current translation-authoring rules to Rust and TypeScript messages and all active catalogs, preserving translator notes in extracted gettext templates.
- Migrated the application from Python/PyGObject to a headless Rust core and Tauri/WebKitGTK React desktop, retaining the native CLI, XDG JSON/SQLite data, host ClamAV boundary, pure-Rust SNI tray, and protocol-v4 protected-host helper.
- Restored a compact GTK-like desktop organization: a single Preferences navigation, grouped controls with visible keyboard and disabled states, header file/folder selection, Quick Scan, an application menu, profile-started scans, expanded scan details with Copy, localized display timestamps, and secondary-button and tab selected, hover, and pressed states in light and dark themes.

- Compacted Audit totals into icon-led issue, warning, pass, and unavailable counters; removed the summary checked timestamp; made disclosure chevrons keyboard-operable; and localized **Learn more** with an external-link arrow.
- Removed decorative middle dots from application metadata and enabled canonical Linux GTK application identity opt-in, preserving the official logo and desktop association.
- Made the normal system-tray icon carry ClamUI's bundled official logo, so SNI hosts do not need a matching icon theme asset; warning, scanning, and threat indicators remain themed status icons.
- Improved the exclusions preferences with left-aligned checkboxes, icon-led actions, and native multiple-file and multiple-folder selection while preserving manual patterns and immediate saving.
- Compacted historical-log and selected-detail actions into accessible icons with distinct CSV and JSON symbols, and clarified local pagination with a visible loaded-record count and separate Load More and Show All actions.

- Replaced historical-log status badges with fixed-size overview icons while preserving status colors, localized tooltips, accessible names, and row selection.

### Verified

- Exercised 125 Rust workspace tests and strict Clippy; exercised host-bridge EICAR scans through the Tauri desktop, AppImage, and Flatpak.
- Exercised prior XDG JSON, SQLite, and keyring compatibility plus the desktop's 1.114 MB copy and 18.55 MB ZIP-export paths. These results do not claim zero regressions or coverage of protected host writes, VirusTotal uploads, physical-device hardware, Wayland, or aarch64 CI.
- Compared the public CLI against an exact legacy Python revision in an isolated HOME/XDG environment, and exercised a native Nemo action plus native Nautilus scripts against the running application. Nautilus and Dolphin GUIs were unavailable.

### Fixed
- Fixed generation of immutable Flatpak release manifests when the checkout source block contains `skip:` entries.
- Fixed pending Clamd size-unit repairs being omitted when normalized values matched the displayed baseline; reads and startup remain non-writing and do not request elevation.
- Restored persisted debug-log size and backup-retention settings on every write, with safe fallbacks for unusable values.
- Fixed locked Bun dependency installation in local source, Debian, and AppImage package builds with Bun 1.3.14; clean Debian CI runners now install the gettext catalog tools required by the package builder.
- Fixed inconsistent button padding and spacing in the debug-log deletion confirmation dialog.
- Fixed daemon scans aborting on filenames containing carriage returns or newlines; these files are scanned separately through open file descriptors while retaining exclusions, original detection paths, progress, and partial results. (#264)
- Fixed uneven spacing between linked and plain-text contributor names in About.

- Consolidated known privileged-helper trust failures into one localized, actionable recovery dialog instead of duplicate raw error notifications.
- Checked Flatpak helper availability at the canonical host path and sanitized privileged-helper diagnostics before presentation while preserving useful paths and redacting secrets.
- Distinguished a missing canonical system helper from an existing untrusted helper and provided actionable supported recovery; blocked protected writes remain unapplied and pending settings drafts can be retried after repair.
- Fixed Flatpak recognition of a trusted, same-version protocol-v4 Debian `all` helper already installed at the canonical path; it no longer treats it as missing or requests a nonexistent architecture-specific release asset.
- Wrapped settings-save diagnostics and toast messages so long errors remain readable without horizontal overflow.

- Prevented delayed Save & Apply completion from replacing a newly selected configuration file with the previous save target.
- Preserved literal backslashes before percent signs in cron scan targets and command arguments instead of letting cron interpret them as an input separator.
- Registered the website's English UI dictionary and added a custom 404 page with documentation and homepage recovery links without duplicate routes.
- Fixed the completed-scan/close-confirmation race so close continues its original exit path rather than restoring a stale scan button after completion.
- Fixed gettext extraction for multiline and static-branch Rust messages so CLI and deep-audit text remains localized.
- Serialized concurrent quarantine startup access to prevent locking conflicts.
- Corrected statistics totals from localized historical scan records so files scanned and detections reflect the completed scans.
- Fixed **Scan Details** keyboard focus wrapping for WebKitGTK Tab events, including reverse navigation, and restored focus to its opener after Escape.
- Added a read-only startup check for notification permission while retaining the existing permission request and native-notification dispatch capabilities.
- Corrected light-theme warning and error emphasis; made Scanner and On-Access labels static gettext messages while preserving stored configuration IDs, values, and the English catalog fallback; separated the **Detected Threats** heading from grouped rows; and aligned quarantine metadata.
- Extracted static TypeScript and TSX gettext calls for the desktop without treating dynamic expressions as translatable message IDs.
- Removed duplicated aggregate/per-target scan text from results, clipboard copies, and exports while preserving per-target diagnostics and aggregate-only fallback output.
- Reported individual-check audit totals, the database build timestamp, and the actual Tauri runtime major version in system information.
- Made enabled unchecked checkbox boundaries readable in both themes while preserving checked, keyboard-focus, disabled, and switch-control states.
- Made locally generated quarantine validation errors and history-detail failure messages statically extractable for gettext while preserving external diagnostics.
- Removed the redundant upper separator from side-by-side quarantine and statistics summaries while retaining vertical list dividers.
- Removed the duplicate application heading below the native titlebar and refined the file/folder and Quick Scan toolbar vector icons while preserving native window controls.
- Compacted scan-result metrics and actions, replaced duplicate per-target output cards with one scrollable Scan Details view, and limited log rendering to 50 rows at a time while retaining all captured output for scrolling, copying, and export.
- Restored compatible CLI flag aliases and bundled forms, attached history arguments, safe handling of very large positive history limits, and invalid or missing quarantine-ID exit semantics.
- Restored native local helper staging with the co-bundled compiled helper and canonical policy, while keeping the real host installation root-gated and the Flatpak signed-package path separate.
- Restored profile export/import compatibility: public JSON remains the nine-field shape, unknown stored metadata survives, legacy non-string descriptions normalize to strings, and CLI profile FILE paths are literal rather than `~`-expanded.
- Fixed scan-profile layouts on small screens with full-width text, expandable untruncated paths, wrapping icon actions, and responsive editing and deletion dialogs.
- Stacked database update progress and result metadata vertically, wrapped long lines, and separated freshclam output into a plain theme-aware terminal surface.
- Replaced scan-target and scan action text buttons with right-aligned accessible icons and localized tooltips while preserving disabled and running states.
- Replaced audit category and check status badges with shared overview icons while preserving severity colors, translated tooltips, accessible names, and native disclosures.
- Restored `--` end-of-options handling in the GUI so literal option-like filenames, including `--virustotal`, are scanned rather than opening the VirusTotal dialog.

## [0.4.1] - 2026-10-12

### Added

- Added a **Start in System Tray** preference for login/autostart workflows while keeping explicit file and folder scans visible. (#221)
- Added Hungarian localization.
- Added an in-app Flatpak flow for installing the matching `clamui-privileged-helper` on supported Debian-family hosts; it validates the release asset before requesting administrator authorization.
- Added regression coverage for privileged configuration read failures, mixed direct/elevated saves, staging cleanup, and direct-write filesystem rejection.

### Changed

- Moved project documentation into the Starlight site at `/docs/`, retaining root release notes as canonical sources.
- Updated Flatpak to GNOME 51/Python 3.14 and replaced the tray's CairoSVG dependency with GdkPixbuf/librsvg rasterization.
- Simplified scanner output handling, daemon target counting, and ClamAV configuration parsing while preserving cancellation, exclusion scope, and explicit read-authorization behavior.
- Simplified preference configuration saving/loading, tray shutdown, scan-output streaming, and symlink safety checks while preserving their existing behavior.
- Clarified privileged-helper release asset validation without changing accepted metadata or security checks.
- Separated modern and legacy About dialog setup and removed redundant GTK setter checks while retaining GTK 4.6/libadwaita 1.1 compatibility and presentation behavior.
- Flattened daemon scan result parsing while preserving detection priority, skipped-file warnings, and error-message precedence.
- Simplified daemon log discovery while preserving common-location priority, configured log fallback, and Flatpak host access.
- Separated file-count exclusion preparation from traversal while preserving cancellation, partial counts, and symlink handling.
- Separated daemon scan-input preparation and temporary file-list ownership from execution while preserving exclusions, progress, cancellation, and cleanup.
- Consolidated scanner preference boolean collection without changing directive order, size units, or missing-widget handling.
- Extracted stateless clamscan result parsing from the scanner lifecycle while preserving summary precedence, threat detection, and warning classification.

### Fixed

- Bundled GLib's desktop-launch helper in the AppImage so audit documentation links open on KDE and other non-Ubuntu host layouts. (#194)
- Prevented large standalone full scans from being reported as failed when capped verbose output hid the final summary and only nonfatal ClamAV warnings remained. (#217)
- Corrected Fedora `freshclam` installation guidance and made the availability probe independent of Fedora's root-only default configuration.
- Preserved raw POSIX filename bytes for `clamscan`, daemon scans, and quarantine restore; reject newline-containing daemon file-list targets.
- Used the installed scheduled-scan module path when generating Debian jobs.
- Used the selected custom `freshclam.conf` for manual database updates.
- Corrected tray-availability, VirusTotal setup, scan selection, and result-scroller behavior.
- Kept Configuration File paths readable by using compact configuration-file actions in Scanner and Database preferences.
- Rendered Mermaid diagrams in the documentation with light/dark theme support and a mobile-friendly tray architecture layout.
- Fixed scanner-test package isolation so later Flatpak configuration tests patch the restored modules rather than stale package references.

### Security

- Hardened trusted helper discovery in system `sbin` directories and atomic configuration writes, with administrator reads and `0600` custom configs.

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

[Unreleased]: https://github.com/linx-systems/clamui/compare/v0.5.0...HEAD

[0.5.0]: https://github.com/linx-systems/clamui/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/linx-systems/clamui/compare/v0.4.0...v0.4.1
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
