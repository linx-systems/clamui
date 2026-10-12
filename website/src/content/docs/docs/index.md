---
title: ClamUI documentation
description: Task-focused help for ClamUI and its host ClamAV installation.
---

ClamUI is a Linux desktop interface for [ClamAV](https://www.clamav.net/). It does not ship ClamAV or its virus database: install host `clamscan` and `freshclam` for every package format. Daemon scans additionally need host `clamd` and `clamdscan`.

## Start here

1. [Install ClamUI](/docs/installation/), then update the ClamAV database.
2. Follow [your first scan](/docs/getting-started/).
3. For recurring work, create [profiles](/docs/guides/profiles/) or [scheduled scans](/docs/guides/scheduling/).

## Common tasks

- [Scan a file, folder, or removable drive](/docs/guides/scanning/)
- [Review or remove quarantined files](/docs/guides/quarantine/)
- [Choose a scan backend](/docs/reference/scan-backends/)
- [Fix an installation, daemon, tray, or scan problem](/docs/troubleshooting/)
- [Configure settings and ClamAV integration](/docs/reference/configuration/)

## Contributors

- [Set up development and packaging](/docs/contributing/development/)
- [Translate ClamUI](/docs/contributing/translating/)
- [Verify or sign release packages](/docs/contributing/signing/)
- [Understand the tray architecture](/docs/contributing/architecture/)

Report bugs and feature requests on [GitHub](https://github.com/linx-systems/clamui/issues). Report vulnerabilities privately through the [security policy](/docs/contributing/security/).