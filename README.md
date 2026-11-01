<div align="center">

<img src="https://raw.githubusercontent.com/linx-systems/clamui/master/icons/io.github.linx_systems.ClamUI.svg" alt="ClamUI logo" width="140" height="140">

# ClamUI

A modern Linux desktop interface for ClamAV, built with Rust, Tauri, and a React frontend.

[Website](https://clamui.com) · [Documentation](https://clamui.com/docs/) · [Issues](https://github.com/linx-systems/clamui/issues) · [Security](SECURITY.md)

[![Flathub](https://flathub.org/api/badge?locale=en)](https://flathub.org/en/apps/io.github.linx_systems.ClamUI)

</div>

## ClamUI v0.5.1

v0.5.1 is a patch release. After the matching artifacts are attached to [GitHub Releases](https://github.com/linx-systems/clamui/releases), download the native packages, AppImage, or Flatpak bundle there and follow the [package-signing guide](https://clamui.com/docs/contributing/signing/) before installing native artifacts.

Every package format uses **host** ClamAV. Install host `clamscan` and `freshclam`; daemon scans also require host `clamd` and `clamdscan`.

```bash
# Debian or Ubuntu
sudo apt install clamav clamav-freshclam
```

Install the matching Debian application and helper pair for your architecture. Their asset patterns are `clamui_0.5.1_<debarch>.deb` and `clamui-privileged-helper_0.5.1_<debarch>.deb`:

```bash
DEB_ARCH="$(dpkg --print-architecture)"
sudo apt install "./clamui_0.5.1_${DEB_ARCH}.deb" \
  "./clamui-privileged-helper_0.5.1_${DEB_ARCH}.deb"
```

The v0.5.1 helper RPM asset names are `clamui-privileged-helper-0.5.1-1.x86_64.rpm` and `clamui-privileged-helper-0.5.1-1.aarch64.rpm`, each with a matching `.rpm.asc`. The x86_64 AppImage asset name is `ClamUI-0.5.1-x86_64.AppImage` (with `.zsync` metadata). The Flatpak bundle asset names are `clamui-x86_64.flatpak` and `clamui-aarch64.flatpak`.

The Flathub store currently publishes the historical Python 0.4.1 release. It does not yet distribute the Rust/Tauri v0.5.1 release; use the GitHub Flatpak bundles for v0.5.1.

For source development, clone `master`. The Rust/Tauri desktop uses WebKitGTK 4.1, GTK 3, a native StatusNotifierItem tray, and no Python application runtime. Protected host ClamAV configuration remains behind the version-matched `clamui-apply-preferences` helper and Polkit policy.

- [Installation](https://clamui.com/docs/installation/)
- [First scan](https://clamui.com/docs/getting-started/)
- [User guides and troubleshooting](https://clamui.com/docs/)
- [Development, architecture, and packaging](https://clamui.com/docs/contributing/development/)

## License

MIT. See [LICENSE](LICENSE).