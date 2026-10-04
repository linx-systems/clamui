---
title: Run the security audit
description: Review host-security signals and optional authorized deep scans.
---

The **Audit** view is advisory: it reports status and recommendations but does not install packages, edit host configuration, enable services, or remediate findings. Opening it runs the standard audit; **Refresh Audit** runs it again without administrator authentication.

## Standard checks

The audit reviews ClamAV health and definitions, firewall state and selected listening services, AppArmor/SELinux, automatic updates and pending reboot, fail2ban/CrowdSec, selected SSH settings, and optional Portmaster availability. When Portmaster rejects a stored token, ClamUI clears it so authorization can be requested again.

Host permissions and distribution differences can produce **Unknown**. A passing status summarizes only checks ClamUI could perform, not a security guarantee.

## Deep scans

The opt-in deep scans run [Lynis](https://cisofy.com/lynis/) or `chkrootkit` through `pkexec`. Install the selected tool first, expect an administrator prompt and several minutes of run time, and run them only on systems you are authorized to assess. Cancelled authorization reports **Skipped**.

| Status | Meaning |
| --- | --- |
| Pass | Expected condition or no actionable deep-scan finding |
| Warning | Reviewable condition |
| Fail | Condition or finding needing attention |
| Unknown | State could not be determined |
| Skipped | Inapplicable, unavailable, optional, or not authorized |

Review upstream documentation and back up configuration before acting on a recommendation.