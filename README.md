<div align="center">

<img src="https://raw.githubusercontent.com/linx-systems/clamui/master/icons/io.github.linx_systems.ClamUI.svg" alt="ClamUI logo" width="140" height="140">

# ClamUI

A modern Linux desktop interface for ClamAV, built with Rust, Tauri, and a React frontend.

[Website](https://clamui.com) · [Documentation](https://clamui.com/docs/) · [Issues](https://github.com/linx-systems/clamui/issues) · [Security](SECURITY.md)

[![Flathub](https://flathub.org/api/badge?locale=en)](https://flathub.org/en/apps/io.github.linx_systems.ClamUI)

</div>

## Install

```bash
flatpak install flathub io.github.linx_systems.ClamUI
flatpak run io.github.linx_systems.ClamUI
```

Every package format uses **host** ClamAV. Install host `clamscan` and `freshclam`; daemon scans also require host `clamd` and `clamdscan`.

```bash
# Debian or Ubuntu
sudo apt install clamav clamav-freshclam
```

ClamUI's desktop is a Tauri/WebKitGTK application. It has a Rust core, native StatusNotifierItem tray integration, and no Python application runtime or tray subprocess. Protected host ClamAV configuration remains behind the version-matched `clamui-apply-preferences` helper and polkit policy.

- [Installation](https://clamui.com/docs/installation/)
- [First scan](https://clamui.com/docs/getting-started/)
- [User guides and troubleshooting](https://clamui.com/docs/)
- [Development, architecture, and packaging](https://clamui.com/docs/contributing/development/)

## License

MIT. See [LICENSE](LICENSE).