---
title: Read statistics
description: Use protection status, trends, and quick actions without over-reading them.
---

Open **Statistics** to see scan activity, detections, totals, duration, and a chart for Day, Week, Month, or All Time. Use **Refresh** after scans, updates, or quarantine actions; the view does not continuously refresh itself.

## Protection status

Protection status is based on scan recency, not real-time antivirus coverage:

- **Protected:** a recent scan (within seven days).
- **At risk:** the last scan is more than seven days ago but no more than 30 days ago.
- **Unprotected:** no recorded scan, or the last scan is more than 30 days ago.
- **Unknown:** ClamUI cannot determine status or ClamAV is unavailable.

Keeping definitions current matters, but a definition update alone does not change this scan-recency status. ClamAV is not a complete real-time endpoint-protection guarantee.

## Interpret trends

A rise in files scanned normally reflects larger targets. A rise in detections deserves investigation, but a count does not distinguish severity; open Logs for the affected paths and detection names. Gaps in blue scan bars may indicate skipped scheduled scans. Individual scan details live in [Logs](/docs/guides/history/).

Quick actions navigate to the relevant view (quick scan, logs, database update); they do not make a hidden change in the dashboard.