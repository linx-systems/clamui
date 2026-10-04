---
title: Frequently asked questions
description: Practical answers for scanning, detections, performance, and external drives.
---

## Is ClamUI the antivirus engine?

No. ClamUI is the desktop interface; [ClamAV](https://www.clamav.net/) performs detection. All package formats require host `clamscan` and `freshclam`; daemon mode adds `clamd` and `clamdscan`.

## Can I use Ubuntu or Pop!_OS 22.04?

Use the [Flatpak](/docs/installation/#flatpak). The full `.deb` application requires Python 3.11+, while stock 22.04 has Python 3.10. Flatpak supplies its own current Python and GUI runtime, but still uses the host ClamAV tools.

## How often should I scan?

A practical default is daily Downloads scans and a weekly Home Folder scan. Use a Full Scan after a high-risk event or periodically when the computer is idle. Keep definitions updated more often than you scan.

## What should I do when a scan detects something?

Do not execute it. Quarantine unknown, critical, or high-severity files first; inspect source, hash, and intended use; then delete confirmed malware or restore only a confirmed false positive. Severity is a name-based clue, not a verdict. Do not upload confidential files to VirusTotal or another third party.

## Are false positives possible?

Yes, especially for heuristic, packed, administrative, and potentially unwanted tools. Update definitions, research the exact detection, check provenance and hashes, and compare independent engines only when disclosure is acceptable. Keep a suspicious file quarantined while deciding. Report confirmed ClamAV false positives at [ClamAV](https://www.clamav.net/reports/fp).

## Will scans slow down my system?

They can be CPU- and disk-intensive. A running daemon avoids reloading definitions and is best for recurring scans. Prefer targeted schedules and narrow, justified exclusions; do not reduce protection or set unlimited archive limits merely for speed.

## Is quarantine safe?

It is reversible isolation with owner-only storage and SHA-256 verification on restore. It is not a backup: deletion and clearing old items are permanent, and manual file changes bypass metadata and integrity protections.

## Can I scan USB, external, or network drives?

Yes. Scan a mounted path manually or enable Device Scan for removable, external, and optionally network mounts. Review results before opening files, scan unfamiliar media before use, and do not disconnect it while scanning.