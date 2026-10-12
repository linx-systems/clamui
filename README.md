<div align="center">

<img src="https://raw.githubusercontent.com/linx-systems/clamui/master/icons/io.github.linx_systems.ClamUI.svg" alt="ClamUI logo" width="140" height="140">

# ClamUI

A modern Linux desktop interface for ClamAV antivirus, built with PyGObject, GTK4, and libadwaita.

[Website](https://clamui.com) · [Documentation](https://clamui.com/docs/) · [Issues](https://github.com/linx-systems/clamui/issues) · [Security](SECURITY.md)

[![Flathub](https://flathub.org/api/badge?locale=en)](https://flathub.org/en/apps/io.github.linx_systems.ClamUI)

</div>

## Install

```bash
flatpak install flathub io.github.linx_systems.ClamUI
flatpak run io.github.linx_systems.ClamUI
```

Every package format uses host ClamAV; install host `clamscan` and `freshclam`. Daemon scans also require host `clamd` and `clamdscan`.

- [Installation](https://clamui.com/docs/installation/)
- [First scan](https://clamui.com/docs/getting-started/)
- [User guides and troubleshooting](https://clamui.com/docs/)
- [Development and packaging](https://clamui.com/docs/contributing/development/)

## License

MIT. See [LICENSE](LICENSE).