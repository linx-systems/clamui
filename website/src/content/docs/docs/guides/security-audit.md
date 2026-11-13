---
title: Run the security audit
description: Review host-security signals and optional authorized deep scans.
---

The **Audit** view is advisory: it reports status and recommendations but does not install packages, edit host configuration, enable services, or remediate findings. Opening it runs the standard audit; **Refresh Audit** runs it again without administrator authentication.

The compact summary shows the issue total alongside icon-led warning, pass, and unavailable counters. Their labels are available on hover and to assistive technology. Click a disclosure chevron, or press <kbd>Enter</kbd> or <kbd>Space</kbd> while it is focused, to expand or collapse its details. **Learn more** opens approved documentation in your browser.

Select **Hide missing optional items** to hide only optional entries reported as missing or not detected. This changes the view only: installed or inactive components, unknown results, required findings, and overall audit totals remain unchanged. Clear the checkbox to show the hidden entries again.

## Standard checks

The audit reviews ClamAV health and definitions, firewall state and selected listening services, AppArmor/SELinux, automatic updates and pending reboot, fail2ban/CrowdSec, selected SSH settings, and optional application firewalls. The **Application firewalls** section reports Portmaster and OpenSnitch independently; when Portmaster rejects a stored token, ClamUI clears it so authorization can be requested again.

Host permissions and distribution differences can produce **Unknown**. A passing status summarizes only checks ClamUI could perform, not a security guarantee.

Expand **Open Ports** to see a table of TCP listeners and bound UDP sockets with their numeric ports, local bind addresses, binding scopes, and process names and PIDs where host permissions expose them. The summary counts distinct port numbers, so separate addresses, address families, or protocols can produce more table rows than the count. A listening or bound socket does not establish reachability through a firewall or from the Internet. Partial observations retain the available rows and are qualified; unavailable observations are not treated as an empty result. Process information may be unavailable, and the audit does not request additional authorization to obtain it.

## Application firewalls

OpenSnitch's system service and local graphical interface have separate rows. A running service does not establish that traffic is being filtered or that a GUI is connected; an available GUI does not establish a running or connected daemon. A GUI-only installation can manage [remote nodes](https://github.com/evilsocket/opensnitch/wiki/Nodes), and a daemon can be installed without the GUI.

The audit checks both `opensnitch.service`, used by [Debian packaging](https://github.com/evilsocket/opensnitch/blob/v1.8.0/utils/packaging/daemon/deb/debian/opensnitch.service), and `opensnitchd.service`, used by [upstream](https://github.com/evilsocket/opensnitch/blob/v1.8.0/daemon/data/init/opensnitchd.service) and the [NixOS module](https://github.com/NixOS/nixpkgs/blob/c56a87d8e41ce69bd2af57eb35dcc117a9dfca33/nixos/modules/services/security/opensnitch.nix#L159-L176). An installed inactive or failed service is reported as such. If neither service is detected, a manually started daemon may still be running: the audit does not check it. Unavailable or indeterminate service observations are **Unknown**, not proof of absence. On NixOS, `services.opensnitch.enable` enables the daemon service; install the GUI package separately if needed, as described in the [upstream installation guide](https://github.com/evilsocket/opensnitch/wiki/Installation#nixos).

The GUI check uses the host session's `PATH`, including profile paths, to find `opensnitch-ui`; when needed it can use the fixed upstream `opensnitch_ui` desktop entry through `gtk-launch`. An unconfirmed optional GUI is **Skipped**; unavailable detection is **Unknown**. When a launch target is found, **Open OpenSnitch** explicitly requests a host GUI launch. Flatpak uses its existing host-launch permission, without a new permission or administrator prompt. A successful launch request does not prove that a window appeared: OpenSnitch may use a tray or open an existing instance's window instead of starting another one ([upstream GUI startup](https://github.com/evilsocket/opensnitch/blob/v1.8.0/ui/bin/opensnitch-ui#L178-L190)).

Application-firewall observations are independent of the host input-policy evidence below; neither substitutes for the other.

## Firewall inventory

The firewall check inventories supported host components independently: UFW, firewalld, native nftables rules, legacy or compatibility `iptables` rules for IPv4 and IPv6, and the optional Gufw, Firewall Config, and Plasma Firewall interfaces. A package, graphical interface, startup setting, active-exited service, or non-empty ruleset is not by itself evidence that the host accepts or blocks incoming traffic.

[Plasma Firewall](https://github.com/KDE/plasma-firewall) is a KDE settings module that manages UFW or firewalld; it is not a separate firewall. Its presence, like Gufw or Firewall Config, is inventory only and does not make the host protected or require an interface to be installed.

For UFW, the audit reads `ufw status verbose` and accepts only its explicit runtime state. It reports the stated default incoming policy and qualifies any rule exceptions; it does not infer that UFW is active from its configuration file, package, or service state. For firewalld, the audit makes only a non-activating system-bus ownership query. A bus owner establishes that firewalld is present on the bus, not that its runtime is ready or that zones protect this host. It deliberately does not call firewalld methods, `firewall-cmd`, KDE helpers, polkit, or KAuth: upstream firewalld authorization may request interactive authorization. See the [UFW manual](https://manpages.ubuntu.com/manpages/jammy/man8/ufw.8.html), [firewalld authorization implementation](https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/server/decorators.py), and [firewalld command reference](https://firewalld.org/documentation/man-pages/firewall-cmd.html).

Where the host permits access, native kernel rules are examined independently. nftables inspection considers only live, non-dormant filter base chains attached to `input`; `iptables-save` and `ip6tables-save` inspect each family's filter `INPUT` policy. IPv4 and IPv6 remain separate evidence. A restrictive default policy supports only that default-policy finding, and permitted or custom rule exceptions remain qualified. NAT, `FORWARD`, Docker or other non-empty rules, ordinary named chains, and comments do not prove host-input protection; neither does this bounded inspection prove full network reachability. See the [nftables manual](https://netfilter.org/projects/nftables/manpage.html) and [iptables-save manual](https://man7.org/linux/man-pages/man8/iptables-save.8.html).

Missing policy-inspection tools, permission denial, malformed or incomplete output, and timeouts are **Unknown**, not proof that a firewall is disabled. Unconfirmed optional graphical interfaces are **Skipped**. UFW and a firewalld bus owner can indicate a potential concurrent-manager situation, but do not prove a rule conflict. nftables and iptables are overlapping kernel-rule engines rather than competing firewall managers. Standard firewall probes never acquire root access or open an authorization dialog.

If UFW is **Unknown** and a trusted system executable is available, **Check UFW with administrator access** explicitly requests a host `pkexec`/polkit administrator prompt to read the fixed `ufw status verbose` command. The check does not change firewall settings or authorize the other firewall probes. Cancellation or denial leaves the existing findings unchanged. A successful result applies only to the current view; **Refresh Audit** runs the standard unprivileged audit again. Neither standard probes nor this action enable an alternative firewall or change firewall configuration.

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