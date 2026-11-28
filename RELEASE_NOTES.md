# ClamUI v0.6.1 release notes

ClamUI v0.6.1 fixes the blank window in the Flatpak, adds OpenSnitch checks and acknowledgeable warnings to the security audit, adds startup diagnostics, and brings the new dashboard layout.

## Highlights

- **Blank window in the Flatpak fixed:** the Flatpak now forces WebKitGTK's shared-memory rendering instead of disabling the DMA-BUF renderer entirely, which left some WebKit versions without any usable buffer transport and showed an empty window. The Wayland `Error 71` workaround stays in place. If you are on the 0.6.0 Flatpak and see a blank window, the [troubleshooting page](https://clamui.com/docs/troubleshooting/) has a one-line workaround. ([#315](https://github.com/linx-systems/clamui/issues/315), [#282](https://github.com/linx-systems/clamui/issues/282))
- **OpenSnitch in the audit:** the application-firewall check now looks at the OpenSnitch service and its graphical interface separately from Portmaster, and can launch the GUI. ([#241](https://github.com/linx-systems/clamui/issues/241))
- **Acknowledge audit warnings:** warnings you have reviewed can be acknowledged and revoked again, and no longer count as outstanding while the check stays unchanged. The audit also opens with a clear Protected / Action recommended overview, richer Open Ports details, an optional UFW status check, and an option to hide missing optional items. ([#329](https://github.com/linx-systems/clamui/issues/329), [#322](https://github.com/linx-systems/clamui/issues/322))
- **Startup diagnostics:** if the window stays blank, ClamUI now shows the JavaScript or render error in the window and logs where startup stopped after ten seconds. `scripts/inspect-blank-window.py` helps inspect a blank web view. ([#361](https://github.com/linx-systems/clamui/issues/361))
- **Dashboard layout:** a new Dashboard start page, a separate Scan page, a results page that leads with a clear verdict, and the system accent color from the desktop portal. ([#351](https://github.com/linx-systems/clamui/pull/351), [#325](https://github.com/linx-systems/clamui/issues/325))
- **Preferences:** settings save automatically, with a single authorization prompt for protected changes. Path lists show new entries first and can be reordered. ([#346](https://github.com/linx-systems/clamui/issues/346))
- **Scanning fixes:** daemon scans of FUSE-mounted files, including AppImage mounts, no longer fail; "View Results" works after very large scans; daemon scans use clamd's thread pool; Flatpak scan progress estimates count host files. ([#369](https://github.com/linx-systems/clamui/issues/369), [#225](https://github.com/linx-systems/clamui/issues/225), [#304](https://github.com/linx-systems/clamui/issues/304))
- **More distributions:** openSUSE Tumbleweed and Leap are recognized, and SELinux and host tool detection work on systems without `which` or with `getenforce` outside the user PATH. ([#367](https://github.com/linx-systems/clamui/issues/367), [#368](https://github.com/linx-systems/clamui/issues/368))
- **Packaging and dependencies:** the AppImage ships a readable AppDir and current AppStream screenshots, `cookie` and `url` are updated for RUSTSEC-2026-0594 and RUSTSEC-2026-0592, and Rust, desktop, and website dependencies are refreshed.

## Installation and upgrade guidance

All package formats use **host-installed ClamAV**: install `clamscan` and `freshclam`; daemon scans also require `clamd` and `clamdscan`. Flatpak calls the host tools through `flatpak-spawn --host` and does not bundle the ClamAV engine or database. Native builds use GTK 3 and WebKitGTK 4.1; the Flatpak targets GNOME Platform 51.

Download the v0.6.1 package for your architecture from [GitHub Releases](https://github.com/linx-systems/clamui/releases) and verify native packages using the [package-signing guide](https://clamui.com/docs/contributing/signing/). On Debian, install the application and privileged-helper packages matching your architecture and version. Fedora's helper-only RPM does not include the desktop or ClamAV. Protected host settings require a trusted protocol-v4 helper and graphical Polkit authorization.

GitHub Flatpak bundles can be installed directly. Flathub is updated separately, so the version available there can differ from this release for a short time. See the [installation guide](https://clamui.com/docs/installation/) for package names, platform requirements, and upgrade instructions.

For the full list of changes, see the [changelog](https://github.com/linx-systems/clamui/blob/master/CHANGELOG.md).
