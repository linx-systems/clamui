import { useEffect, useRef, useState, type JSX } from "react";

import { copyText, notify, onEvent, openExternal, request, type NetworkSnapshot } from "../api";
import { Icon } from "../Icon";
import { _, ngettext } from "../i18n";

type AuditStatus = "pass" | "warning" | "fail" | "unknown" | "skipped" | "checking";
type AuditCategory = "clamav_health" | "firewall" | "mac_framework" | "auto_updates" | "intrusion_detection" | "ssh_hardening" | "application_firewalls" | "deep_scan_lynis" | "deep_scan_rootkit";

type AuditCheck = {
  name: string;
  status: AuditStatus;
  detail: string;
  recommendation?: string | null;
  install_command?: string | null;
  info_url?: string | null;
  launch_command?: string | null;
  launch_label?: string | null;
  optional_missing?: boolean;
  listening_ports?: NetworkSnapshot | null;
};

type AuditSection = {
  category: AuditCategory;
  title: string;
  icon_name: string;
  checks: AuditCheck[];
  overall_status: AuditStatus;
};

type AuditReport = { sections: AuditSection[]; timestamp: number };

const CATEGORY_ORDER = [
  "clamav_health",
  "firewall",
  "mac_framework",
  "auto_updates",
  "intrusion_detection",
  "ssh_hardening",
  "application_firewalls",
] as const satisfies readonly AuditCategory[];

function categoryTitle(category: (typeof CATEGORY_ORDER)[number]): string {
  switch (category) {
    case "clamav_health": return _("ClamAV Health");
    case "firewall": return _("Firewall");
    case "mac_framework": return _("Access Control");
    case "auto_updates": return _("Automatic Updates");
    case "intrusion_detection": return _("Intrusion Detection");
    case "ssh_hardening": return _("SSH Security");
    case "application_firewalls": return _("Application firewalls");
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}


function statusLabel(status: AuditStatus): string {
  if (status === "checking") return _("Checking");
  if (status === "pass") return _("Pass");
  if (status === "warning") return _("Warning");
  if (status === "fail") return _("Fail");
  if (status === "skipped") return _("Skipped");
  return _("Unknown");
}

function statusIcon(status: AuditStatus): "check-circle" | "warning" | "audit" | "minus-circle" | "refresh" {
  if (status === "pass") return "check-circle";
  if (status === "warning") return "warning";
  if (status === "fail") return "audit";
  if (status === "checking") return "refresh";
  return "minus-circle";
}

function AuditStatusIndicator({ status }: { status: AuditStatus }): JSX.Element {
  const label = statusLabel(status);
  return <span aria-label={label} className={`status-badge ${status} audit-status-icon`} role="img" title={label}><Icon name={statusIcon(status)} /></span>;
}

function replaceSection(sections: AuditSection[], next: AuditSection): AuditSection[] {
  const current = sections.filter((section) => section.category !== next.category);
  current.push(next);
  return current.sort((left, right) => categoryIndex(left.category) - categoryIndex(right.category));
}

function categoryIndex(category: AuditCategory): number {
  const tierIndex = (CATEGORY_ORDER as readonly AuditCategory[]).indexOf(category);
  if (tierIndex >= 0) return tierIndex;
  return category === "deep_scan_lynis" ? 100 : 101;
}

// Validate the network fields used here at both the progressive and final-response boundaries.
function listeningSnapshot(value: unknown): value is NetworkSnapshot {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const snapshot = value as Record<string, unknown>;
  if (
    !["available", "partial", "unavailable"].includes(snapshot.status as string) ||
    typeof snapshot.captured_at !== "string" ||
    !Array.isArray(snapshot.sockets) ||
    typeof snapshot.unparsed_lines !== "number" ||
    !Number.isSafeInteger(snapshot.unparsed_lines) ||
    snapshot.unparsed_lines < 0 ||
    typeof snapshot.limited !== "boolean" ||
    (snapshot.message !== null && typeof snapshot.message !== "string")
  ) return false;
  const validEndpoint = (endpoint: unknown): boolean => {
    if (typeof endpoint !== "object" || endpoint === null || Array.isArray(endpoint)) return false;
    const item = endpoint as Record<string, unknown>;
    return typeof item.address === "string" &&
      (item.port === null || (typeof item.port === "number" && Number.isSafeInteger(item.port) && item.port >= 0 && item.port <= 65535)) &&
      (item.virustotal_url === null || typeof item.virustotal_url === "string");
  };
  return snapshot.sockets.every((value: unknown) => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const socket = value as Record<string, unknown>;
    return (socket.protocol === "tcp" || socket.protocol === "udp") &&
      (socket.kind === "listener" || socket.kind === "connection") &&
      typeof socket.state === "string" &&
      validEndpoint(socket.local) &&
      (socket.remote === null || validEndpoint(socket.remote)) &&
      Array.isArray(socket.processes) &&
      socket.processes.every((value: unknown) => {
        if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
        const process = value as Record<string, unknown>;
        return typeof process.name === "string" && typeof process.pid === "number" &&
          Number.isSafeInteger(process.pid) && process.pid > 0;
      });
  });
}

function ipv4Parts(address: string): number[] | null {
  const parts = address.split(".");
  if (parts.length !== 4 || !parts.every((part) => /^\d{1,3}$/.test(part) && Number(part) <= 255)) return null;
  return parts.map(Number);
}

function ipv6Parts(address: string): number[] | null {
  let input = address;
  if (input.includes(".")) {
    const lastColon = input.lastIndexOf(":");
    const ipv4 = ipv4Parts(input.slice(lastColon + 1));
    if (lastColon < 0 || !ipv4) return null;
    input = `${input.slice(0, lastColon + 1)}${((ipv4[0] << 8) | ipv4[1]).toString(16)}:${((ipv4[2] << 8) | ipv4[3]).toString(16)}`;
  }
  const halves = input.split("::");
  if (halves.length > 2) return null;
  const left = halves[0] ? halves[0].split(":") : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const parts = [...left, ...right];
  if (!parts.every((part) => /^[0-9a-f]{1,4}$/i.test(part))) return null;
  if (halves.length === 1 ? parts.length !== 8 : parts.length >= 8) return null;
  return [...left, ...Array(8 - parts.length).fill("0"), ...right].map((part) => Number.parseInt(part, 16));
}

function bindingLabel(address: string): string {
  const scopeIndex = address.indexOf("%");
  const host = scopeIndex < 0 ? address : address.slice(0, scopeIndex);
  const ipv4 = ipv4Parts(host);
  const ipv6 = host.includes(":") ? ipv6Parts(host) : null;
  if (ipv4?.[0] === 127 || (ipv6 &&
    ((ipv6.slice(0, 7).every((part) => part === 0) && ipv6[7] === 1) ||
      (ipv6.slice(0, 5).every((part) => part === 0) && ipv6[5] === 0xffff && (ipv6[6] >> 8) === 127)))) return _("Local only");
  if (scopeIndex < 0 && (host === "*" || (ipv4 && ipv4.every((part) => part === 0)) ||
    (ipv6 && ipv6.every((part) => part === 0)))) return _("All interfaces");
  return _("Specific address or interface");
}

function parseAuditProgress(value: unknown): AuditSection | null {
  if (
    typeof value !== "object" ||
    value === null ||
    !("section" in value) ||
    typeof value.section !== "object" ||
    value.section === null
  ) return null;
  const section = value.section;
  if (
    !("category" in section) ||
    !("title" in section) ||
    !("icon_name" in section) ||
    !("checks" in section) ||
    !("overall_status" in section) ||
    typeof section.category !== "string" ||
    typeof section.title !== "string" ||
    typeof section.icon_name !== "string" ||
    !Array.isArray(section.checks) ||
    typeof section.overall_status !== "string" ||
    (
      !(CATEGORY_ORDER as readonly AuditCategory[]).includes(section.category as AuditCategory) &&
      section.category !== "deep_scan_lynis" &&
      section.category !== "deep_scan_rootkit"
    ) ||
    !["pass", "warning", "fail", "unknown", "skipped", "checking"].includes(section.overall_status)
  ) return null;
  for (const check of section.checks) {
    if (
      typeof check !== "object" ||
      check === null ||
      !("name" in check) ||
      !("status" in check) ||
      !("detail" in check) ||
      typeof check.name !== "string" ||
      typeof check.status !== "string" ||
      !["pass", "warning", "fail", "unknown", "skipped", "checking"].includes(check.status) ||
      typeof check.detail !== "string" ||
      ("recommendation" in check && check.recommendation !== null && typeof check.recommendation !== "string") ||
      ("install_command" in check && check.install_command !== null && typeof check.install_command !== "string") ||
      ("info_url" in check && check.info_url !== null && typeof check.info_url !== "string") ||
      ("launch_command" in check && check.launch_command !== null && typeof check.launch_command !== "string") ||
      ("launch_label" in check && check.launch_label !== null && typeof check.launch_label !== "string") ||
      ("optional_missing" in check && typeof check.optional_missing !== "boolean") ||
      ("listening_ports" in check && check.listening_ports !== null && !listeningSnapshot(check.listening_ports))
    ) return null;
  }
  return section as AuditSection;
}

export default function Audit(): JSX.Element {
  const [sections, setSections] = useState<AuditSection[]>([]);
  const [running, setRunning] = useState(false);
  const [deepRunning, setDeepRunning] = useState<"lynis" | "chkrootkit" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authorizationRunning, setAuthorizationRunning] = useState(false);
  const [ufwChecking, setUfwChecking] = useState(false);
  const [hideMissingOptional, setHideMissingOptional] = useState(false);
  const runSequence = useRef(0);
  const activeOperation = useRef<"audit" | "deep" | "portmaster" | "ufw" | null>(null);

  const applySection = (section: AuditSection): void => {
    setSections((current) => replaceSection(current, section));
  };


  const performAudit = async (): Promise<void> => {
    const sequence = ++runSequence.current;
    setRunning(true);
    setError(null);
    setSections([]);
    try {
      const report = await request<AuditReport>("audit.run");
      if (runSequence.current !== sequence) return;
      setSections(report.sections.sort((left, right) => categoryIndex(left.category) - categoryIndex(right.category)));
      const summary = countSummary(report.sections);
      if (summary.fail > 0) notify(ngettext("{count} security issue needs attention", "{count} security issues need attention", summary.fail, { count: summary.fail }), "warning");
      else if (summary.warning > 0) notify(ngettext("{count} audit check needs review", "{count} audit checks need review", summary.warning, { count: summary.warning }), "warning");
      else notify(_("Security audit completed"), "success");
    } catch (requestError) {
      if (runSequence.current === sequence) setError(errorText(requestError));
    } finally {
      if (runSequence.current === sequence) setRunning(false);
    }
  };

  const runAudit = async (): Promise<void> => {
    if (activeOperation.current) return;
    activeOperation.current = "audit";
    try {
      await performAudit();
    } finally {
      activeOperation.current = null;
    }
  };
  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | undefined;
    void onEvent((event) => {
      if (!active || event.event !== "audit-progress") return;
      const section = parseAuditProgress(event.data);
      if (section && !(activeOperation.current === "ufw" && section.category === "firewall")) applySection(section);
    }).then((cleanup) => {
      if (active) {
        unlisten = cleanup;
        void runAudit();
      } else {
        cleanup();
      }
    }).catch((eventError) => {
      if (active) {
        setError(_("Could not receive progressive audit results: {error}", { error: errorText(eventError) }));
        void runAudit();
      }
    });
    return () => {
      active = false;
      unlisten?.();
    };
  }, []);

  

  const runDeep = async (tool: "lynis" | "chkrootkit"): Promise<void> => {
    if (activeOperation.current) return;
    activeOperation.current = "deep";
    setDeepRunning(tool);
    setError(null);
    try {
      const section = await request<AuditSection>("audit.deep", { tool });
      applySection(section);
      notify(_("{tool} check completed", { tool: tool === "lynis" ? "Lynis" : "chkrootkit" }), section.overall_status === "fail" ? "warning" : "info");
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setDeepRunning(null);
      activeOperation.current = null;
    }
  };

  const launch = async (command: string): Promise<void> => {
    if (command !== "gufw" && command !== "firewall-config" && command !== "opensnitch-ui") {
      setError(_("The audit supplied an unsupported GUI launch action."));
      return;
    }
    try {
      const response = await request<{ launched: boolean; error?: string }>("audit.launch", { command });
      if (!response.launched) throw new Error(response.error || _("The selected application did not start"));
    } catch (launchError) {
      setError(errorText(launchError));
    }
  };

  const authorizePortmaster = async (): Promise<void> => {
    if (activeOperation.current) return;
    activeOperation.current = "portmaster";
    setAuthorizationRunning(true);
    setError(null);
    try {
      const response = await request<{ authorized: boolean; cancelled: boolean; message?: string }>("audit.portmaster_authorize");
      if (response.authorized) {
        notify(_("Portmaster authorization granted; refreshing audit."), "success");
        await performAudit();
      } else if (response.cancelled) {
        notify(_("Portmaster authorization was cancelled."), "info");
      } else {
        setError(response.message || _("Portmaster authorization was not granted."));
      }
    } catch (authorizationError) {
      setError(errorText(authorizationError));
    } finally {
      setAuthorizationRunning(false);
      activeOperation.current = null;
    }
  };

  const checkUfw = async (): Promise<void> => {
    if (activeOperation.current) return;
    activeOperation.current = "ufw";
    const sequence = runSequence.current;
    setUfwChecking(true);
    setError(null);
    try {
      const response = await request<{ cancelled: boolean; section?: AuditSection }>("audit.ufw_status");
      if (runSequence.current !== sequence) return;
      if (response.cancelled) {
        notify(_(
          // Translators: Keep UFW unchanged; it is a tool name.
          "UFW status authorization was cancelled.",
        ), "info");
        return;
      }
      const section = parseAuditProgress(response);
      if (!section || section.category !== "firewall") {
        setError(_(
          // Translators: Keep UFW unchanged; it is a tool name.
          "The UFW status check did not return a firewall result.",
        ));
        return;
      }
      applySection(section);
      notify(_(
        // Translators: Keep UFW unchanged; it is a tool name.
        "UFW status check completed",
      ), "success");
    } catch (requestError) {
      if (runSequence.current === sequence) setError(errorText(requestError));
    } finally {
      activeOperation.current = null;
      setUfwChecking(false);
    }
  };

  const actionsDisabled = running || deepRunning !== null || authorizationRunning || ufwChecking;

  const summary = countSummary(sections);
  const tierSections = CATEGORY_ORDER.map((category) => sections.find((section) => section.category === category)).filter((section): section is AuditSection => section !== undefined);
  const deepSections = sections.filter((section) => section.category === "deep_scan_lynis" || section.category === "deep_scan_rootkit");

  return (
    <main className="page audit-page" aria-labelledby="audit-title">
      <header className="page-header">
        <div>
          <h1 id="audit-title">{_("System security audit")}</h1>
          <p>{_("Inspect your security posture and copy recommendations. Audit checks never change system configuration.")}</p>
        </div>
        <button className="button" disabled={actionsDisabled} onClick={() => void runAudit()} type="button"><Icon name="refresh" />{running ? _("Auditing…") : _("Refresh audit")}</button>
      </header>

      {error && <p className="error-banner" role="alert">{error}</p>}
      {(sections.length > 0 || running) && <div className="status-banner audit-overview" role="status"><span className="audit-overview-result"><Icon name={statusIcon("fail")} /><strong>{ngettext("{count} issue", "{count} issues", summary.fail, { count: summary.fail })}</strong></span><span className="audit-overview-metrics"><span aria-label={`${_("Warning")}: ${summary.warning}`} className="audit-metric warning" title={_("Warning")}><Icon name={statusIcon("warning")} /><span>{summary.warning}</span></span><span aria-label={`${_("Pass")}: ${summary.pass}`} className="audit-metric success" title={_("Pass")}><Icon name={statusIcon("pass")} /><span>{summary.pass}</span></span><span aria-label={`${_("unavailable or skipped")}: ${summary.unknown}`} className="audit-metric" title={_("unavailable or skipped")}><Icon name={statusIcon("unknown")} /><span>{summary.unknown}</span></span></span></div>}

      <label className="check-row"><input type="checkbox" checked={hideMissingOptional} onChange={(event) => setHideMissingOptional(event.target.checked)} /> {_("Hide missing optional items")}</label>

      {running && CATEGORY_ORDER.filter((category) => !sections.some((section) => section.category === category)).map((category) => <section className="audit-category" aria-labelledby={`audit-${category}`} key={category}><header className="section-header"><div><h2 id={`audit-${category}`}>{categoryTitle(category)}</h2></div><AuditStatusIndicator status="checking" /></header><div className="grouped-list"><div className="group-row muted">{_("Checking")}</div></div></section>)}
      {tierSections.map((section) => <SectionView actionsDisabled={actionsDisabled} authorizationRunning={authorizationRunning} hideMissingOptional={hideMissingOptional} key={section.category} onAuthorize={authorizePortmaster} onCheckUfw={checkUfw} onLaunch={launch} section={section} ufwChecking={ufwChecking} />)}

      <section className="audit-category" aria-labelledby="deep-scans-heading">
        <header className="section-header"><div><h2 id="deep-scans-heading">{_("Deep scans")}</h2><p>{_(
          // Translators: Keep Lynis and chkrootkit unchanged; they are tool names.
          "Lynis and chkrootkit are never run automatically. Each check may request administrator authorization only after you explicitly start that check.",
        )}</p></div></header>
        <div className="actions">
          <button className="button primary" disabled={actionsDisabled} onClick={() => void runDeep("lynis")} type="button">{deepRunning === "lynis" ? _("Running Lynis…") : _("Run Lynis security audit")}</button>
          <button className="button primary" disabled={actionsDisabled} onClick={() => void runDeep("chkrootkit")} type="button">{deepRunning === "chkrootkit" ? _("Running chkrootkit…") : _("Run rootkit detection")}</button>
        </div>
      </section>
      {deepSections.map((section) => <SectionView actionsDisabled={actionsDisabled} authorizationRunning={authorizationRunning} hideMissingOptional={hideMissingOptional} key={section.category} onAuthorize={authorizePortmaster} onCheckUfw={checkUfw} onLaunch={launch} section={section} ufwChecking={ufwChecking} />)}
    </main>
  );
}

function countSummary(sections: AuditSection[]): Record<"pass" | "warning" | "fail" | "unknown", number> {
  const summary = { pass: 0, warning: 0, fail: 0, unknown: 0 };
  for (const section of sections) {
    for (const check of section.checks) {
      if (check.status === "pass") summary.pass += 1;
      else if (check.status === "warning") summary.warning += 1;
      else if (check.status === "fail") summary.fail += 1;
      else summary.unknown += 1;
    }
  }
  return summary;
}

function SectionView({ section, onLaunch, onAuthorize, onCheckUfw, actionsDisabled, authorizationRunning, ufwChecking, hideMissingOptional }: { section: AuditSection; onLaunch: (command: string) => Promise<void>; onAuthorize: () => Promise<void>; onCheckUfw: () => Promise<void>; actionsDisabled: boolean; authorizationRunning: boolean; ufwChecking: boolean; hideMissingOptional: boolean }): JSX.Element | null {
  const label = section.title;
  const headingId = `audit-${section.category}`;
  if (hideMissingOptional && section.checks.length > 0 && section.checks.every((check) => check.optional_missing === true)) return null;
  return <section className="audit-category" aria-labelledby={headingId}>
    <header className="section-header"><div><h2 id={headingId}>{label}</h2></div><AuditStatusIndicator status={section.overall_status} /></header>
    <div className="grouped-list audit-list" role="list">
      {section.checks.length > 0 ? section.checks.map((check, index) => hideMissingOptional && check.optional_missing === true ? null : <CheckView actionsDisabled={actionsDisabled} authorizationRunning={authorizationRunning} check={check} key={`${check.name}-${index}`} onAuthorize={onAuthorize} onCheckUfw={onCheckUfw} onLaunch={onLaunch} ufwChecking={ufwChecking} />) : <div className="group-row muted" role="listitem">{_("No audit details were returned.")}</div>}
    </div>
  </section>;
}

function ListeningPorts({ value, label }: { value: unknown; label: string }): JSX.Element {
  if (!listeningSnapshot(value)) return <p className="notice warning">{_("Unavailable")}</p>;
  const sockets = value.sockets.filter((socket) => socket.kind === "listener");
  return <>
    {value.status === "unavailable" ? <p className="notice warning">{value.message || _("Network information is unavailable. Check that the system socket tool is installed and try again.")}</p> :
      value.status === "partial" || value.limited || value.unparsed_lines > 0 ? <p className="notice warning">{value.message && <>{value.message} </>}{value.limited ? _("The socket list was limited. This snapshot may be incomplete.") : _("Some socket records could not be read. This snapshot may be incomplete.")}</p> : null}
    <p>{_("Listening sockets do not prove that a port is reachable through the firewall.")}</p>
    {sockets.length > 0 && <div className="audit-table-scroll"><table aria-label={label} className="table audit-ports-table">
      <thead><tr><th scope="col">{_("Protocol")}</th><th scope="col">{_("Port")}</th><th scope="col">{_("Local address")}</th><th scope="col">{_("Binding")}</th><th scope="col">{_("Process")}</th></tr></thead>
      <tbody>{sockets.map((socket, index) => <tr key={`${socket.protocol}-${socket.local.address}-${socket.local.port}-${index}`}>
        <td>{socket.protocol.toUpperCase()}</td>
        <td>{socket.local.port ?? _("Unavailable")}</td>
        <td className="monospace">{socket.local.address}</td>
        <td>{bindingLabel(socket.local.address)}</td>
        <td>{socket.processes.length > 0 ? <ul className="audit-process-list">{socket.processes.map((process, processIndex) => <li key={`${process.pid}-${processIndex}`}>{process.name} {_(
          // Translators: Preserve the {pid} placeholder. It is a numeric process ID.
          "PID {pid}",
          { pid: process.pid },
        )}</li>)}</ul> : _("Process information unavailable")}</td>
      </tr>)}</tbody>
    </table></div>}
  </>;
}

function CheckView({ check, onLaunch, onAuthorize, onCheckUfw, actionsDisabled, authorizationRunning, ufwChecking }: { check: AuditCheck; onLaunch: (command: string) => Promise<void>; onAuthorize: () => Promise<void>; onCheckUfw: () => Promise<void>; actionsDisabled: boolean; authorizationRunning: boolean; ufwChecking: boolean }): JSX.Element {
  const copy = async (): Promise<void> => {
    try {
      await copyText(check.install_command!);
      notify(_("Command copied to clipboard"), "success");
    } catch (copyError) {
      notify(_("Could not copy command: {error}", { error: errorText(copyError) }), "error");
    }
  };
  const learn = async (): Promise<void> => {
    try {
      await openExternal(check.info_url!);
    } catch (openError) {
      notify(_("Could not open documentation: {error}", { error: errorText(openError) }), "error");
    }
  };
  const hasDetails = Boolean((check.recommendation && check.status !== "pass") || check.install_command || check.launch_command || check.info_url || check.listening_ports != null);
  const overview = <><span className="row-copy"><span className="row-title">{check.name}</span><span className="row-description">{check.detail}</span></span><AuditStatusIndicator status={check.status} /></>;
  const details = <div className="audit-details">
    {check.recommendation && check.status !== "pass" && <p className="notice warning">{check.recommendation}</p>}
    {check.listening_ports != null && <ListeningPorts label={check.name} value={check.listening_ports} />}
    {check.install_command && <div className="row"><code className="monospace path-value">{check.install_command}</code><button className="button" onClick={() => void copy()} type="button"><Icon name="copy" />{_("Copy")}</button></div>}
    {(check.launch_command || check.info_url) && <div className="actions">
      {check.launch_command === "__portmaster_authorize__" && <button className="button primary" disabled={actionsDisabled} onClick={() => void onAuthorize()} type="button">{authorizationRunning ? _("Authorizing…") : check.launch_label || _("Authorize")}</button>}
      {check.launch_command === "__ufw_status__" && <button className="button primary" disabled={actionsDisabled} onClick={() => void onCheckUfw()} type="button">{ufwChecking ? _(
        // Translators: Keep UFW unchanged; it is a tool name. Use an ellipsis appropriate for the target language.
        "Checking UFW…",
      ) : check.launch_label}</button>}
      {check.launch_command && check.launch_command !== "__portmaster_authorize__" && check.launch_command !== "__ufw_status__" && <button className="button" onClick={() => void onLaunch(check.launch_command!)} type="button">{check.launch_label || _("Open")}</button>}
      {check.info_url && <button className="button audit-external-link" onClick={() => void learn()} title={_("Open in browser")} type="button"><Icon name="external-link" />{_("Learn more")}</button>}
    </div>}
  </div>;
  if (!hasDetails) return <article className="group-row audit-row" role="listitem">{overview}</article>;
  return <details className="group-row audit-row" open={check.status !== "pass" && check.status !== "checking"} role="listitem"><summary className="audit-summary">{overview}<Icon className="audit-disclosure-icon" name="chevron-down" /></summary>{details}</details>;
}
