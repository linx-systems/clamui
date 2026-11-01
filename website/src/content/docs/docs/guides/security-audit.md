---
title: Run the security audit
description: Review host-security signals and optional authorized deep scans.
---

The **Audit** view is advisory: it reports status and recommendations but does not install packages, edit host configuration, enable services, or remediate findings. Opening it runs the standard audit; **Refresh Audit** runs it again without administrator authentication.

The compact summary shows the issue total alongside icon-led warning, pass, and unavailable counters. Their labels are available on hover and to assistive technology. Click a disclosure chevron, or press <kbd>Enter</kbd> or <kbd>Space</kbd> while it is focused, to expand or collapse its details. **Learn more** opens approved documentation in your browser.

## Standard checks

The audit reviews ClamAV health and definitions, firewall state and selected listening services, AppArmor/SELinux, automatic updates and pending reboot, fail2ban/CrowdSec, selected SSH settings, and optional Portmaster availability. When Portmaster rejects a stored token, ClamUI clears it so authorization can be requested again.

Host permissions and distribution differences can produce **Unknown**. A passing status summarizes only checks ClamUI could perform, not a security guarantee.

## Firewall inventory

The firewall check inventories supported host components independently: UFW, firewalld, native nftables rules, legacy or compatibility `iptables` rules for IPv4 and IPv6, and the optional Gufw, Firewall Config, and Plasma Firewall interfaces. A package, graphical interface, startup setting, active-exited service, or non-empty ruleset is not by itself evidence that the host accepts or blocks incoming traffic.

[Plasma Firewall](https://github.com/KDE/plasma-firewall) is a KDE settings module that manages UFW or firewalld; it is not a separate firewall. Its presence, like Gufw or Firewall Config, is inventory only and does not make the host protected or require an interface to be installed.

For UFW, the audit reads `ufw status verbose` and accepts only its explicit runtime state. It reports the stated default incoming policy and qualifies any rule exceptions; it does not infer that UFW is active from its configuration file, package, or service state. For firewalld, the audit makes only a non-activating system-bus ownership query. A bus owner establishes that firewalld is present on the bus, not that its runtime is ready or that zones protect this host. It deliberately does not call firewalld methods, `firewall-cmd`, KDE helpers, polkit, or KAuth: upstream firewalld authorization may request interactive authorization. See the [UFW manual](https://manpages.ubuntu.com/manpages/jammy/man8/ufw.8.html), [firewalld authorization implementation](https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/server/decorators.py), and [firewalld command reference](https://firewalld.org/documentation/man-pages/firewall-cmd.html).

Where the host permits access, native kernel rules are examined independently. nftables inspection considers only live, non-dormant filter base chains attached to `input`; `iptables-save` and `ip6tables-save` inspect each family's filter `INPUT` policy. IPv4 and IPv6 remain separate evidence. A restrictive default policy supports only that default-policy finding, and permitted or custom rule exceptions remain qualified. NAT, `FORWARD`, Docker or other non-empty rules, ordinary named chains, and comments do not prove host-input protection; neither does this bounded inspection prove full network reachability. See the [nftables manual](https://netfilter.org/projects/nftables/manpage.html) and [iptables-save manual](https://man7.org/linux/man-pages/man8/iptables-save.8.html).

Missing policy-inspection tools, permission denial, malformed or incomplete output, and timeouts are **Unknown**, not proof that a firewall is disabled. Unconfirmed optional graphical interfaces are **Skipped**. UFW and a firewalld bus owner can indicate a potential concurrent-manager situation, but do not prove a rule conflict. nftables and iptables are overlapping kernel-rule engines rather than competing firewall managers. These firewall probes never enable an alternative firewall, acquire root access, open an authorization dialog, or change firewall configuration.

## Network connections

**Network** is a separate sidebar view, not an Audit check. It takes a current snapshot when opened and when you choose **Refresh**; it does not change the Audit summary or the opt-in deep-scan behavior. The snapshot lists listening or bound TCP and UDP sockets and observed connections with protocol, state, local endpoint, remote endpoint when there is one, and the available process name and PID. Search matches ports, numeric addresses, process names, and PIDs; **All**, **Listening and bound**, and **Connections** narrow the current snapshot.

Each endpoint has its own copy control. Copies retain the port, use brackets around IPv6 addresses, and retain a valid interface qualifier where the host reports one. A remote endpoint is explicitly unavailable for an unconnected or wildcard socket; it is never guessed. Process attribution can be unavailable because host permissions do not expose it, or because the process exited while the snapshot was taken. It is not evidence that no process owned the socket.

The labels **Local address** and **Remote address** describe socket ends only. A snapshot cannot reliably establish who initiated a connection; a listening or bound port does not establish reachability through a firewall; and it cannot show NAT/WAN mappings, traffic, packet captures, persistent monitoring, or the destinations of UDP `sendto` calls. It also does not perform remediation, persist snapshots, prompt for root access, or inspect command lines, environments, or executable paths.

The view uses the host [`ss` socket inventory](https://manpages.ubuntu.com/manpages/jammy/man8/ss.8.html) supplied by `iproute2` through the existing host wrapper, including Flatpak's host route. Missing tools or permission, invalid or incomplete output, timeouts, and output limits are shown honestly as partial or unavailable rather than as an empty or complete result. A partial snapshot preserves valid rows and says when its socket limit was reached.

For an eligible public, unscoped IP address, the VirusTotal icon opens that IP's report in the browser only after a confirmation names the exact address and explains the external disclosure; cancellation opens nothing. The browser request shares that IP with VirusTotal/browser services; it sends no port, process data, or API key and is never automatic. Private, special-purpose, scoped, or wildcard addresses retain a disabled VirusTotal icon whose reason is available in its tooltip rather than inline prose. Do not use the report for sensitive addresses: [VirusTotal's IP documentation](https://docs.virustotal.com/reference/ip-info) warns that queried indicators enter its dataset. The conservative eligibility rules exclude special-purpose space documented by the [IANA IPv4](https://www.iana.org/assignments/iana-ipv4-special-registry/iana-ipv4-special-registry.xhtml) and [IPv6](https://www.iana.org/assignments/iana-ipv6-special-registry/iana-ipv6-special-registry.xhtml) registries. A report is contextual information, not a safety, reputation, reachability, or security guarantee.


## Deep scans

The opt-in deep scans run [Lynis](https://cisofy.com/lynis/) or `chkrootkit` only after you explicitly select the requested tool. Install the selected tool first, expect an administrator prompt where the host requires one and several minutes of run time, and run them only on systems you are authorized to assess. Cancelled authorization reports **Skipped**.

| Status | Meaning |
| --- | --- |
| Pass | Expected condition or no actionable deep-scan finding |
| Warning | Reviewable condition |
| Fail | Condition or finding needing attention |
| Unknown | State could not be determined |
| Skipped | Inapplicable, unavailable, optional, or not authorized |

Review upstream documentation and back up configuration before acting on a recommendation.