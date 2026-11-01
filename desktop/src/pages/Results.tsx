import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../Icon";
import { Modal } from "../Modal";
import { _, ngettext, scanStatusLabel } from "../i18n";
import { copyText, navigate, onEvent, openExternal, request, saveText } from "../api";
import { formatScanOutput } from "../scanOutput";
import { scanLogChunks } from "../scanLog";
import { ScanLogViewport } from "../ScanLogViewport";

type Threat = { file_path: string; threat_name: string; category?: string; severity?: string };
type ScanResult = { id?: string; status: string; path?: string; stdout?: string; stderr?: string; scanned_files?: number; scanned_dirs?: number; infected_count?: number; threat_details?: Threat[]; skipped_files?: string[]; skipped_count?: number; warning_message?: string; nonfatal_warnings?: string[]; error_message?: string | null; per_target_results?: ScanResult[] };
type VTDetection = { engine_name: string; category: string; result?: string | null };
type VTResult = { status: string; file_path: string; sha256?: string; detections?: number; total_engines?: number; detection_details?: VTDetection[]; scan_date?: string; permalink?: string; error_message?: string; duration?: number };
type Confirmation = { kind: "single"; threat: Threat } | { kind: "all"; threats: Threat[] } | null;

const PAGE_SIZE = 25;
const LARGE_COPY_BYTES = 10 * 1024 * 1024;

function byteSize(text: string): number {
  return new TextEncoder().encode(text).byteLength;
}
function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
function isScanResult(value: unknown): value is ScanResult {
  const record = asRecord(value);
  return record !== null && typeof record.status === "string";
}
function isVTResult(value: unknown): value is VTResult {
  const record = asRecord(value);
  return record !== null && typeof record.status === "string" && typeof record.file_path === "string";
}

function threatLabel(severity?: string, category?: string): string {
  const value = severity || category;
  switch (value) {
    case "critical": return _("Critical");
    case "high": return _("High");
    case "medium": return _("Medium");
    case "low": return _("Low");
    case "Ransomware": return _("Ransomware");
    case "Rootkit": return _("Rootkit");
    case "Trojan": return _("Trojan");
    case "Worm": return _("Worm");
    case "Backdoor": return _("Backdoor");
    case "Exploit": return _("Exploit");
    case "Adware": return _("Adware");
    case "Spyware": return _("Spyware");
    case "Test": return _("Test");
    case "Macro": return _("Macro");
    case "Phishing": return _("Phishing");
    case "Heuristic": return _("Heuristic");
    case "PUA": return _("PUA");
    case "Virus": return _("Virus");
    case "Unknown": return _("Unknown");
    default: return value || _("Threat");
  }
}

function virusTotalStatusLabel(status: string): string {
  switch (status) {
    case "clean": return _("Clean");
    case "detected": return _("Detected");
    case "error": return _("Error");
    case "pending": return _("Pending");
    case "rate_limited": return _("Rate limited");
    case "not_found": return _("Not found");
    case "file_too_large": return _("File too large");
    default: return status || _("Unknown");
  }
}

function virusTotalCategoryLabel(category: string): string {
  if (category === "malicious") return _("Malicious");
  if (category === "suspicious") return _("Suspicious");
  return category || _("Unknown");
}
function completedVT(value: unknown): VTResult | null {
  const record = asRecord(value);
  return record && isVTResult(record.result) ? record.result : null;
}
function storedResult<T>(key: string, guard: (value: unknown) => value is T): T | null {
  const serialized = sessionStorage.getItem(key);
  if (!serialized) return null;
  try {
    const parsed: unknown = JSON.parse(serialized);
    return guard(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function ScanResultPanel({ result }: { result: ScanResult }) {
  const [shown, setShown] = useState(PAGE_SIZE);
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quarantined, setQuarantined] = useState<Set<string>>(() => new Set());
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const outputCache = useRef<{ result: ScanResult; output: string } | null>(null);
  const threats = result.threat_details ?? [];
  const visibleThreats = threats.slice(0, shown);
  const logChunks = useMemo(() => scanLogChunks(result), [result]);
  const status = result.status === "infected" ? "warning" : result.status === "clean" ? "success" : result.status === "error" ? "error" : "";

  const fullOutput = () => {
    const cached = outputCache.current;
    if (cached?.result === result) return cached.output;
    const output = formatScanOutput(result, _("Scan target"));
    outputCache.current = { result, output };
    return output;
  };
  const copyOrExport = async () => {
    const output = fullOutput();
    if (!output) throw new Error(_("No scan output is available"));
    if (output.length > LARGE_COPY_BYTES || byteSize(output) > LARGE_COPY_BYTES) {
      await saveText(output, "clamui_scan_results.txt", [{ name: _("Text Files"), extensions: ["txt"] }]);
    } else {
      await copyText(output);
    }
  };
  const handleCopyOrExport = () => {
    setError(null);
    void copyOrExport().catch((reason: unknown) => setError(String(reason)));
  };

  const exclude = async (threat: Threat) => {
    setBusy(true);
    setError(null);
    try {
      const settings = await request<Record<string, unknown>>("settings.get");
      const existing = Array.isArray(settings.exclusion_patterns) ? settings.exclusion_patterns.filter((entry): entry is Record<string, unknown> => asRecord(entry) !== null) : [];
      const alreadyPresent = existing.some((entry) => entry.pattern === threat.file_path);
      if (!alreadyPresent) await request("settings.update", { exclusion_patterns: [...existing, { pattern: threat.file_path, type: "file", enabled: true }] });
      setQuarantined((current) => new Set(current).add(`excluded:${threat.file_path}`));
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };
  const quarantine = async () => {
    const target = confirmation;
    if (!target) return;
    setBusy(true);
    setError(null);
    const threatsToMove = target.kind === "single" ? [target.threat] : target.threats;
    const failures: string[] = [];
    const completed: string[] = [];
    for (const threat of threatsToMove) {
      try {
        const response = await request<{ status: string; error_message?: string }>("quarantine.quarantine", { path: threat.file_path, threat_name: threat.threat_name });
        if (response.status === "success") completed.push(threat.file_path);
        else failures.push(`${threat.file_path}: ${response.error_message || response.status}`);
      } catch (reason) {
        failures.push(`${threat.file_path}: ${String(reason)}`);
      }
    }
    setQuarantined((current) => {
      const next = new Set(current);
      completed.forEach((path) => next.add(path));
      return next;
    });
    setConfirmation(null);
    setBusy(false);
    if (failures.length) setError(failures.join("\n"));
  };

  return <>
    <section className="results-summary scan-results-summary" aria-labelledby="scan-results-title">
      <div className="scan-result-toolbar">
        <div className="row"><h2 id="scan-results-title" className="row-title">{_("Scan Results")}</h2><span className={`status-badge ${status}`}>{scanStatusLabel(result.status)}</span></div>
        <div className="actions">
          <button className="button" onClick={handleCopyOrExport}><Icon name="copy" />{_("Copy or Export")}</button>
          {logChunks.length > 0 && <button className="button" onClick={() => setFullscreen(true)}><Icon name="expand" />{_("Fullscreen")}</button>}
          {threats.length > 0 && <button className="button primary" disabled={busy || threats.every((threat) => quarantined.has(threat.file_path))} onClick={() => setConfirmation({ kind: "all", threats: threats.filter((threat) => !quarantined.has(threat.file_path)) })}>{_("Quarantine All")}</button>}
        </div>
      </div>
      <dl className="scan-summary-metrics">
        <div><dt>{_("Files scanned")}</dt><dd>{result.scanned_files ?? 0}</dd></div>
        <div><dt>{_("Directories")}</dt><dd>{result.scanned_dirs ?? 0}</dd></div>
        <div><dt>{_("Threats found")}</dt><dd>{result.infected_count ?? threats.length}</dd></div>
        {(result.skipped_count ?? 0) > 0 && <div><dt>{_("Not accessible")}</dt><dd>{result.skipped_count}</dd></div>}
      </dl>
      {result.warning_message && <p className="notice warning">{result.warning_message}</p>}
      {result.nonfatal_warnings?.map((warning, index) => <p className="notice warning" key={`${warning}-${index}`}>{warning}</p>)}
      {result.error_message && <p className="notice error">{result.error_message}</p>}
    </section>
    {error && <pre className="notice error" role="alert">{error}</pre>}

    {threats.length > 0 && <section aria-labelledby="detected-threats-title"><header className="section-header"><div><h2 id="detected-threats-title">{_("Detected Threats")}</h2>{threats.length > PAGE_SIZE && <p className="notice warning">{_("Large result set: displaying threats in batches.")}</p>}</div></header><div className="grouped-list">{visibleThreats.map((threat, index) => {
      const key = `${threat.file_path}-${index}`;
      const moved = quarantined.has(threat.file_path);
      const excluded = quarantined.has(`excluded:${threat.file_path}`);
      return <article className="group-row result-threat-row" key={key}><div className="row-copy"><div className="row"><strong>{threat.threat_name}</strong><span className={`status-badge ${threat.severity === "critical" || threat.severity === "high" ? "error" : "warning"}`}>{threatLabel(threat.severity, threat.category)}</span></div><code className="path-value">{threat.file_path}</code></div><div className="actions"><button className="button primary" onClick={() => setConfirmation({ kind: "single", threat })} disabled={busy || moved}>{moved ? _("Quarantined") : _("Quarantine")}</button><button className="button" onClick={() => void exclude(threat)} disabled={busy || excluded}>{excluded ? _("Excluded") : _("Exclude")}</button><button className="button" onClick={() => void copyText(threat.file_path).catch((reason: unknown) => setError(String(reason)))}><Icon name="copy" />{_("Copy Path")}</button></div></article>;
    })}{shown < threats.length && <button className="button" onClick={() => setShown((current) => current + PAGE_SIZE)}>{_("Show {count} more", { count: Math.min(PAGE_SIZE, threats.length - shown) })}</button>}</div></section>}

    {(result.skipped_files?.length ?? 0) > 0 && <details className="grouped-list"><summary>{_("Files Not Accessible")}</summary>{result.skipped_files!.slice(0, 100).map((path) => <div className="group-row" key={path}><code className="path-value">{path}</code></div>)}{result.skipped_files!.length > 100 && <p className="muted">{_("Additional inaccessible files are omitted from this view.")}</p>}</details>}
    {logChunks.length > 0 && <details className="scan-log-details" onToggle={(event) => setDetailsOpen(event.currentTarget.open)}><summary>{_("Scan details")}</summary>{detailsOpen && <ScanLogViewport chunks={logChunks} label={_("Scan details")} />}</details>}
    {fullscreen && <FullscreenOutput title={_("Scan details")} chunks={logChunks} onCopyOrExport={copyOrExport} onClose={() => setFullscreen(false)} />}
    {confirmation && <Modal title={confirmation.kind === "single" ? _("Quarantine File") : _("Quarantine All Threats")} onClose={() => setConfirmation(null)}><p>{confirmation.kind === "single" ? _(
      // Translators: Preserve the {path} placeholder; it is a file path, not translatable. Use quotation marks appropriate for your language.
      "Move '{path}' to quarantine?",
      { path: confirmation.threat.file_path },
    ) : ngettext("Move {count} detected file to quarantine?", "Move {count} detected files to quarantine?", confirmation.threats.length, { count: confirmation.threats.length })}</p><p className="warning">{_("This removes each original file from its current location.")}</p><div className="dialog-actions"><button className="button danger" onClick={() => void quarantine()} disabled={busy}>{busy ? _("Quarantining…") : _("Quarantine")}</button><button className="button" onClick={() => setConfirmation(null)} disabled={busy}>{_("Cancel")}</button></div></Modal>}
  </>;
}

function VirusTotalPanel({ result }: { result: VTResult }) {
  const [shown, setShown] = useState(PAGE_SIZE);
  const [error, setError] = useState<string | null>(null);
  const details = result.detection_details ?? [];
  const exportData = JSON.stringify(result, null, 2);
  const copyOrExport = async () => {
    try {
      if (byteSize(exportData) > LARGE_COPY_BYTES) await saveText(exportData, "clamui_virustotal_results.json", [{ name: _("JSON Files"), extensions: ["json"] }]);
      else await copyText(exportData);
    } catch (reason) {
      setError(String(reason));
    }
  };

  return <section className="results-summary grouped-list" aria-labelledby="virustotal-results-title">
    <div className="group-row"><div className="row-copy"><div className="row"><h2 id="virustotal-results-title" className="row-title">{_("VirusTotal Results")}</h2><span className={`status-badge ${result.status === "detected" || result.status === "rate_limited" ? "warning" : result.status === "error" || result.status === "file_too_large" ? "error" : "success"}`}>{virusTotalStatusLabel(result.status)}</span></div><dl className="summary-list"><div><dt>{_("File")}</dt><dd><code className="path-value">{result.file_path}</code></dd></div>{result.sha256 && <div><dt>SHA256</dt><dd><code className="path-value">{result.sha256}</code></dd></div>}<div><dt>{_("Detections")}</dt><dd>{result.detections ?? 0}/{result.total_engines ?? 0}</dd></div>{result.scan_date && <div><dt>{_("Last scanned")}</dt><dd>{result.scan_date}</dd></div>}</dl></div><div className="actions"><button className="button" onClick={() => void copyOrExport()}><Icon name="copy" />{byteSize(exportData) > LARGE_COPY_BYTES ? _("Export JSON") : _("Copy JSON")}</button><button className="button" onClick={() => void copyText(result.file_path).catch((reason: unknown) => setError(String(reason)))}><Icon name="copy" />{_("Copy Path")}</button>{result.sha256 && <button className="button" onClick={() => void copyText(result.sha256!).catch((reason: unknown) => setError(String(reason)))}><Icon name="copy" />{_("Copy Hash")}</button>}{result.permalink && <button className="button primary" onClick={() => void openExternal(result.permalink!).catch((reason: unknown) => setError(String(reason)))}>{_("View on VirusTotal")}</button>}</div></div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {result.error_message && <p className="notice error">{result.error_message}</p>}
    {details.length > 0 && <section className="grouped-list" aria-labelledby="detection-details-title"><h3 id="detection-details-title" className="section-heading">{_("Detection Details")}</h3>{details.length > PAGE_SIZE && <p className="notice warning">{_("Large result set: displaying detections in batches.")}</p>}{details.slice(0, shown).map((detail, index) => <div className="group-row" key={`${detail.engine_name}-${index}`}><strong>{detail.engine_name}</strong><span className="row-description">{detail.result || _("No result")}</span><span className={`status-badge ${detail.category === "malicious" ? "error" : detail.category === "suspicious" ? "warning" : ""}`}>{virusTotalCategoryLabel(detail.category)}</span></div>)}{shown < details.length && <button className="button" onClick={() => setShown((current) => current + PAGE_SIZE)}>{_("Show {count} more", { count: Math.min(PAGE_SIZE, details.length - shown) })}</button>}</section>}
  </section>;
}

function FullscreenOutput({ title, chunks, onCopyOrExport, onClose }: { title: string; chunks: readonly string[]; onCopyOrExport: () => Promise<void>; onClose: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const copyOrExport = () => {
    setError(null);
    void onCopyOrExport().catch((reason: unknown) => setError(String(reason)));
  };
  return <Modal title={title} onClose={onClose} className="fullscreen-log"><div className="dialog-actions"><button className="button" onClick={copyOrExport}><Icon name="copy" />{_("Copy or Export")}</button></div>{error && <p className="error" role="alert">{error}</p>}<ScanLogViewport chunks={chunks} label={title} /></Modal>;
}

export default function Results() {
  const [scan, setScan] = useState<ScanResult | null>(() => storedResult("clamui-last-scan-result", isScanResult));
  const [virusTotal, setVirusTotal] = useState<VTResult | null>(() => storedResult("clamui-last-vt-result", isVTResult));

  useEffect(() => {
    const onScan = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail;
      if (isScanResult(detail)) setScan(detail);
    };
    const onVT = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail;
      if (isVTResult(detail)) setVirusTotal(detail);
    };
    const onNavigate = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail;
      const record = asRecord(detail);
      const args = record ? asRecord(record.args) : null;
      if (args && isScanResult(args.result)) setScan(args.result);
      if (args && isVTResult(args.virusTotal)) setVirusTotal(args.virusTotal);
    };
    window.addEventListener("clamui-scan-result", onScan);
    window.addEventListener("clamui-vt-result", onVT);
    window.addEventListener("clamui-navigate", onNavigate);
    return () => {
      window.removeEventListener("clamui-scan-result", onScan);
      window.removeEventListener("clamui-vt-result", onVT);
      window.removeEventListener("clamui-navigate", onNavigate);
    };
  }, []);
  useEffect(() => {
    const unlisten = onEvent((event) => {
      const result = event.event === "virustotal-complete" ? completedVT(event.data) : null;
      if (result) setVirusTotal(result);
    });
    return () => {
      void unlisten.then((dispose) => dispose());
    };
  }, []);

  const hasResults = useMemo(() => scan !== null || virusTotal !== null, [scan, virusTotal]);
  return <section className="page results-page" aria-label={_("Results")}>
    <header className="page-header"><div><h1>{_("Results")}</h1><p>{_("Review scan findings and take action on detected threats.")}</p></div><button className="button" onClick={() => navigate("scan")}>{_("Back to Scan")}</button></header>
    {!hasResults ? <div className="empty-state"><h2>{_("No results yet")}</h2><p>{_("Start a scan to see its results here.")}</p></div> : <>{scan && <ScanResultPanel key={scan.id || `${scan.path}-${scan.status}-${scan.scanned_files}`} result={scan} />}{virusTotal && <VirusTotalPanel key={virusTotal.sha256 || `${virusTotal.file_path}-${virusTotal.status}`} result={virusTotal} />}</>}
  </section>;
}
