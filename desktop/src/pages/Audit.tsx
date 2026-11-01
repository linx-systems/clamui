import { useEffect, useRef, useState, type JSX } from "react";

import { copyText, notify, onEvent, openExternal, request } from "../api";
import { Icon } from "../Icon";
import { _, ngettext } from "../i18n";

type AuditStatus = "pass" | "warning" | "fail" | "unknown" | "skipped" | "checking";
type AuditCategory = "clamav_health" | "firewall" | "mac_framework" | "auto_updates" | "intrusion_detection" | "ssh_hardening" | "portmaster" | "deep_scan_lynis" | "deep_scan_rootkit";

type AuditCheck = {
  name: string;
  status: AuditStatus;
  detail: string;
  recommendation?: string | null;
  install_command?: string | null;
  info_url?: string | null;
  launch_command?: string | null;
  launch_label?: string | null;
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
  "portmaster",
] as const satisfies readonly AuditCategory[];

function categoryTitle(category: (typeof CATEGORY_ORDER)[number]): string {
  switch (category) {
    case "clamav_health": return _("ClamAV Health");
    case "firewall": return _("Firewall");
    case "mac_framework": return _("Access Control");
    case "auto_updates": return _("Automatic Updates");
    case "intrusion_detection": return _("Intrusion Detection");
    case "ssh_hardening": return _("SSH Security");
    case "portmaster": return _("Portmaster");
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
      ("launch_label" in check && check.launch_label !== null && typeof check.launch_label !== "string")
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
  const runSequence = useRef(0);

  const applySection = (section: AuditSection): void => {
    setSections((current) => replaceSection(current, section));
  };


  const runAudit = async (): Promise<void> => {
    if (running || deepRunning) return;
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
  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | undefined;
    void onEvent((event) => {
      if (!active || event.event !== "audit-progress") return;
      const section = parseAuditProgress(event.data);
      if (section) applySection(section);
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
    if (running || deepRunning) return;
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
    }
  };

  const launch = async (command: string): Promise<void> => {
    if (command !== "gufw" && command !== "firewall-config") {
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
    if (authorizationRunning) return;
    setAuthorizationRunning(true);
    setError(null);
    try {
      const response = await request<{ authorized: boolean; cancelled: boolean; message?: string }>("audit.portmaster_authorize");
      if (response.authorized) {
        notify(_("Portmaster authorization granted; refreshing audit."), "success");
        await runAudit();
      } else if (response.cancelled) {
        notify(_("Portmaster authorization was cancelled."), "info");
      } else {
        setError(response.message || _("Portmaster authorization was not granted."));
      }
    } catch (authorizationError) {
      setError(errorText(authorizationError));
    } finally {
      setAuthorizationRunning(false);
    }
  };

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
        <button className="button" disabled={running || deepRunning !== null} onClick={() => void runAudit()} type="button"><Icon name="refresh" />{running ? _("Auditing…") : _("Refresh audit")}</button>
      </header>

      {error && <p className="error-banner" role="alert">{error}</p>}
      {(sections.length > 0 || running) && <div className="status-banner audit-overview" role="status"><span className="audit-overview-result"><Icon name={statusIcon("fail")} /><strong>{ngettext("{count} issue", "{count} issues", summary.fail, { count: summary.fail })}</strong></span><span className="audit-overview-metrics"><span aria-label={`${_("Warning")}: ${summary.warning}`} className="audit-metric warning" title={_("Warning")}><Icon name={statusIcon("warning")} /><span>{summary.warning}</span></span><span aria-label={`${_("Pass")}: ${summary.pass}`} className="audit-metric success" title={_("Pass")}><Icon name={statusIcon("pass")} /><span>{summary.pass}</span></span><span aria-label={`${_("unavailable or skipped")}: ${summary.unknown}`} className="audit-metric" title={_("unavailable or skipped")}><Icon name={statusIcon("unknown")} /><span>{summary.unknown}</span></span></span></div>}

      {running && CATEGORY_ORDER.filter((category) => !sections.some((section) => section.category === category)).map((category) => <section className="audit-category" aria-labelledby={`audit-${category}`} key={category}><header className="section-header"><div><h2 id={`audit-${category}`}>{categoryTitle(category)}</h2></div><AuditStatusIndicator status="checking" /></header><div className="grouped-list"><div className="group-row muted">{_("Checking")}</div></div></section>)}
      {tierSections.map((section) => <SectionView authorizationRunning={authorizationRunning} key={section.category} onAuthorize={authorizePortmaster} onLaunch={launch} section={section} />)}

      <section className="audit-category" aria-labelledby="deep-scans-heading">
        <header className="section-header"><div><h2 id="deep-scans-heading">{_("Deep scans")}</h2><p>{_(
          // Translators: Keep Lynis and chkrootkit unchanged; they are tool names.
          "Lynis and chkrootkit are never run automatically. Each check may request administrator authorization only after you explicitly start that check.",
        )}</p></div></header>
        <div className="actions">
          <button className="button primary" disabled={running || deepRunning !== null} onClick={() => void runDeep("lynis")} type="button">{deepRunning === "lynis" ? _("Running Lynis…") : _("Run Lynis security audit")}</button>
          <button className="button primary" disabled={running || deepRunning !== null} onClick={() => void runDeep("chkrootkit")} type="button">{deepRunning === "chkrootkit" ? _("Running chkrootkit…") : _("Run rootkit detection")}</button>
        </div>
      </section>
      {deepSections.map((section) => <SectionView authorizationRunning={authorizationRunning} key={section.category} onAuthorize={authorizePortmaster} onLaunch={launch} section={section} />)}
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

function SectionView({ section, onLaunch, onAuthorize, authorizationRunning }: { section: AuditSection; onLaunch: (command: string) => Promise<void>; onAuthorize: () => Promise<void>; authorizationRunning: boolean }): JSX.Element {
  const label = section.category === "portmaster" && section.overall_status === "skipped"
    ? _(
      // Translators: Portmaster is a product name. The em dash separates the two clauses; use your language's usual dash and spacing.
      "Portmaster — not detected (optional)",
    )
    : section.category === "portmaster" && section.overall_status === "unknown"
      ? _(
        // Translators: Portmaster is a product name. The em dash separates the two clauses; use your language's usual dash and spacing.
        "Portmaster — could not probe",
      )
      : section.title;
  const headingId = `audit-${section.category}`;
  return <section className="audit-category" aria-labelledby={headingId}>
    <header className="section-header"><div><h2 id={headingId}>{label}</h2></div><AuditStatusIndicator status={section.overall_status} /></header>
    <div className="grouped-list audit-list" role="list">
      {section.checks.length > 0 ? section.checks.map((check, index) => <CheckView authorizationRunning={authorizationRunning} check={check} key={`${check.name}-${index}`} onAuthorize={onAuthorize} onLaunch={onLaunch} />) : <div className="group-row muted" role="listitem">{_("No audit details were returned.")}</div>}
    </div>
  </section>;
}

function CheckView({ check, onLaunch, onAuthorize, authorizationRunning }: { check: AuditCheck; onLaunch: (command: string) => Promise<void>; onAuthorize: () => Promise<void>; authorizationRunning: boolean }): JSX.Element {
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
  const hasDetails = Boolean((check.recommendation && check.status !== "pass") || check.install_command || check.launch_command || check.info_url);
  const overview = <><span className="row-copy"><span className="row-title">{check.name}</span><span className="row-description">{check.detail}</span></span><AuditStatusIndicator status={check.status} /></>;
  const details = <div className="audit-details">
    {check.recommendation && check.status !== "pass" && <p className="notice warning">{check.recommendation}</p>}
    {check.install_command && <div className="row"><code className="monospace path-value">{check.install_command}</code><button className="button" onClick={() => void copy()} type="button"><Icon name="copy" />{_("Copy")}</button></div>}
    {(check.launch_command || check.info_url) && <div className="actions">{check.launch_command === "__portmaster_authorize__" && <button className="button primary" disabled={authorizationRunning} onClick={() => void onAuthorize()} type="button">{authorizationRunning ? _("Authorizing…") : check.launch_label || _("Authorize")}</button>}{check.launch_command && check.launch_command !== "__portmaster_authorize__" && <button className="button" onClick={() => void onLaunch(check.launch_command!)} type="button">{check.launch_label || _("Open")}</button>}{check.info_url && <button className="button audit-external-link" onClick={() => void learn()} title={_("Open in browser")} type="button"><Icon name="external-link" />{_("Learn more")}</button>}</div>}
  </div>;
  if (!hasDetails) return <article className="group-row audit-row" role="listitem">{overview}</article>;
  return <details className="group-row audit-row" open={check.status !== "pass" && check.status !== "checking"} role="listitem"><summary className="audit-summary">{overview}<Icon className="audit-disclosure-icon" name="chevron-down" /></summary>{details}</details>;
}
