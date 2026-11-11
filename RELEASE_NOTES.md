# ClamUI v0.6.0 release notes

ClamUI v0.6.0 adds Vietnamese, improves responsiveness on large histories and scans, and fixes scan-evidence and Flatpak integration issues.

## Highlights

- **Vietnamese translation:** Vietnamese (`vi`) joins the active desktop and CLI catalogs.
- **Faster history, quarantine, and progress:** history loads requested entries through a recoverable metadata index, and statistics reuse parsed timestamps. Quarantine browsing uses bounded pages and Unicode-aware search. Hidden history, quarantine, and statistics views defer refreshes until shown, while desktop scan-progress updates are coalesced without dropping threat changes or terminal events. Standalone scans count files without retaining an unused list of paths.
- **Complete large-scan results:** findings, skipped files, warnings, and summary counts are retained after the 64 MiB displayed-output limit for both ClamAV backends. History and final results preserve the evidence and exact filename identities, and infected CLI scans are not reported as clean. Daemon paths of 1,023 bytes or more use the protected stdin transport instead of being split, retaining exclusions, progress, and cancellation. ([#285](https://github.com/linx-systems/clamui/issues/285), [#286](https://github.com/linx-systems/clamui/issues/286))
- **Host integration:** trusted installed native helpers remain recognized when automatic installation or package metadata is unavailable, and conventional numeric-leading Debian revisions are accepted after the exact upstream version. Flatpak checks virus databases on the host and accepts trusted host-tool symlinks only after validating their resolved targets. Flatpak Wayland startup defaults to disabling WebKitGTK's DMA-BUF renderer while respecting explicit overrides. ([#278](https://github.com/linx-systems/clamui/issues/278), [#279](https://github.com/linx-systems/clamui/issues/279), [#280](https://github.com/linx-systems/clamui/issues/280), [#282](https://github.com/linx-systems/clamui/issues/282))
- **VirusTotal:** uploads are rejected if the original pathname is substituted after lookup, alongside the existing no-follow descriptor identity checks.
- **Tooling and packaging:** Rust dependencies include `glib` 0.22.10, bundled `rusqlite` 0.41.1, `rfd` 0.17.2, and locked `tauri` 2.12.5. Desktop tooling includes TypeScript 7.0.2, Vite 8.3.5, React plugin 6.2.1, and Babel parser 8.1.0; gettext extraction uses the locked Babel parser. Bun, Yarn, and Flatpak dependency sources were refreshed, and ordinary AppImage builds no longer pass empty update metadata to `linuxdeploy`.

## Installation and upgrade guidance

All package formats use **host-installed ClamAV**: install `clamscan` and `freshclam`; daemon scans also require `clamd` and `clamdscan`. Flatpak calls the host tools through `flatpak-spawn --host` and does not bundle the ClamAV engine or database. Native builds use GTK 3 and WebKitGTK 4.1; the Flatpak targets GNOME Platform 51.

After the matching v0.6.0 artifacts are attached to [GitHub Releases](https://github.com/linx-systems/clamui/releases), choose the correct architecture and verify native packages with the [package-signing guide](https://clamui.com/docs/contributing/signing/). For Debian, install the matching application and privileged-helper pair. Fedora's helper-only RPM does not include the desktop or ClamAV. Protected host settings require a trusted protocol-v4 helper and graphical Polkit authorization; where installation is offered, use the matching verified signed helper package and explicitly retry Save & Apply. A trusted already-installed compatible helper need not be replaced solely for a source build.

GitHub Flatpak bundles and a separate Flathub submission or rollout are distinct; attaching bundles does not update the store. See the [installation guide](https://clamui.com/docs/installation/) for package names, platform requirements, and upgrade instructions.

For the full list of changes, see the [changelog](https://github.com/linx-systems/clamui/blob/master/CHANGELOG.md).
