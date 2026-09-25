# Security Audit

[← Back to User Guide](../USER_GUIDE.md)

ClamUI's **Security Audit** view reviews selected security signals on the host system. It is primarily a source of
status information and recommendations; it does not install software, change host configuration, or remediate findings.
If Portmaster rejects a stored authentication token, ClamUI clears that token so authorization can be requested again.

---

## Standard Audit

The standard audit runs automatically when the Audit view is first opened and can be run again with **Refresh Audit**.
It does not request administrator authentication.

It checks these areas:

- **ClamAV Health** - ClamAV availability, virus database age and availability, daemon status, and the FreshClam
  automatic-update service.
- **Firewall** - UFW, firewalld, or nftables status; detected graphical firewall management; and listening ports
  commonly associated with higher-risk services.
- **Access Control** - AppArmor or SELinux availability and enforcement status.
- **Automatic Updates** - unattended-upgrades or dnf-automatic, plus a pending-reboot indicator where supported.
- **Intrusion Detection** - fail2ban or CrowdSec status.
- **SSH Security** - whether an SSH service is running and selected effective settings, including root login, password
  authentication, and X11 forwarding.
- **Portmaster** - an optional check for the Portmaster network monitor and application firewall. If it is not detected,
  the audit marks that optional section as skipped.

The checks use the host environment, including when ClamUI runs as a Flatpak. Availability and permissions vary by
distribution, so some checks can be inconclusive.

## Deep Scans

The **Deep Scans** section is opt-in. It offers:

- **Lynis Security Audit** for a broader hardening review and its reported hardening index.
- **Rootkit Detection** using chkrootkit.

Install Lynis or chkrootkit before starting its corresponding scan. Deep scans run through `pkexec`, so they require
administrator authorization and can take several minutes. If you cancel the authorization prompt, the corresponding
scan is shown as skipped.

Run deep scans only on systems you are authorized to assess. Review the tool's detailed output and documentation before
making system-wide security changes.

## Understanding Statuses

- **Pass** - the check found the expected condition or a completed deep scan reported no finding requiring attention.
- **Warning** - the audit found a condition worth reviewing, such as a disabled service or an exposed service.
- **Fail** - the audit found a condition it considers a security issue, or a deep scan reported a finding requiring
  attention.
- **Unknown** - ClamUI could not determine the state, for example because a command, file, service, or permission was
  unavailable.
- **Skipped** - an optional check was not applicable, a deep scan was not authorized, or an optional component was not
  detected.

A status summarizes only the checks ClamUI could perform. It is not a security guarantee or a complete assessment of
your system.

## Recommendations and Install Advice

Some results include a recommendation, a link to upstream documentation, or a copyable package-manager command when
ClamUI recognizes a suitable package target for the host distribution. These are suggestions for you to review: the
Audit view does not execute them, install packages, enable services, edit configuration, or remove threats.

Use recommendations as a starting point, consider your system's intended role and network exposure, and back up or
review configuration before applying changes.