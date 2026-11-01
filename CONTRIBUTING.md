# Contributing to ClamUI

Thanks for contributing. Report bugs and feature requests in [GitHub Issues](https://github.com/linx-systems/clamui/issues); report vulnerabilities privately through [SECURITY.md](SECURITY.md), never a public issue.

Read the canonical contributor guides before starting:

- [Development and packaging](https://clamui.com/docs/contributing/development/)
- [Rust/Tauri architecture and tray design](https://clamui.com/docs/contributing/architecture/)
- [Translation](https://clamui.com/docs/contributing/translating/)
- [Package signing](https://clamui.com/docs/contributing/signing/)
- [Security policy](https://clamui.com/docs/contributing/security/)
- [Code of conduct](CODE_OF_CONDUCT.md)

Keep pull requests focused and include the tests and documentation needed for the change. The application is Rust core code plus the Tauri/React desktop; do not add a Python application or tray-runtime dependency. Preserve host ClamAV and the authenticated privileged-helper boundary.

Install the repository hooks before contributing:

```bash
./scripts/hooks/install-hooks.sh
```

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).