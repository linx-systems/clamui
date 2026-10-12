---
title: Security policy
description: Report vulnerabilities privately and use ClamUI securely.
---

## Report a vulnerability

**Do not open a public issue.** Use [GitHub Security Advisories](https://github.com/linx-systems/clamui/security/advisories/new) for private disclosure and discussion, or email [clamui@rooki.xyz](mailto:clamui@rooki.xyz). Include a description, impact, reproduction steps or proof of concept, affected version, and any suggested mitigation.

ClamUI aims to acknowledge reports within 48 hours. Security updates currently target the latest minor release.

## Relevant reports

Report issues such as command injection, path handling, privilege escalation, arbitrary file access, authentication/credential exposure, denial of service, or unsafe ClamAV command execution. Do not report ClamAV detection quality to ClamUI; report it to the ClamAV project. Product feature requests belong in public issues.

Areas of particular interest include ClamAV command execution, path validation and filesystem operations, quarantine storage and restoration, privileged configuration helpers, scheduled tasks, API/keyring handling, Flatpak host-command boundaries, and tray IPC. Include the smallest safe proof of concept and avoid accessing data or services beyond what demonstrates the issue.

## Security practices

ClamUI sanitizes untrusted log text, validates paths before file operations, uses an owner-only quarantine directory with integrity verification, stores VirusTotal keys in the system keyring where available, and keeps privileged host configuration behind polkit. These controls reduce risk; they do not replace review of untrusted files, current ClamAV definitions, or supported system hardening.

## Disclosure and safe use

The project investigates, develops, tests, releases, and coordinates disclosure of validated reports. Do not disclose details before a fix and coordinated announcement. Keep ClamUI and ClamAV definitions current, inspect unexpected detections before restoring them, and verify release artifacts before installation.

`SECURITY.md` is the short GitHub reporting pointer; this page is the complete project security policy.