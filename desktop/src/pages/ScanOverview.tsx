import { useCallback, useState } from "react";
import { navigate, request } from "../api";
import { Icon } from "../Icon";
import { _, scanStatusLabel } from "../i18n";

import { parseLatestScan, type LatestScan } from "../scanHistory";
import { useActivityRefresh } from "./useActivityRefresh";

export function ScanOverview({ available, databaseAvailable, scanning, result, active = true, onQuickScan }: {
  available?: boolean;
  databaseAvailable?: boolean;
  scanning: boolean;
  result: LatestScan | null;
  active?: boolean;
  onQuickScan: () => void;
}) {
  const [history, setHistory] = useState<LatestScan | null>(null);
  const [historyState, setHistoryState] = useState<"loading" | "ready" | "error">("loading");
  const loadHistory = useCallback(async () => {
    try {
      const entries = await request<unknown>("logs.list", { log_type: "scan", limit: 1 });
      if (!Array.isArray(entries)) throw new Error("Invalid scan history response");
      const latest = parseLatestScan(entries[0]);
      if (entries.length > 0 && !latest) throw new Error("Invalid scan history entry");
      setHistory(latest);
      setHistoryState("ready");
    } catch {
      setHistoryState("error");
    }
  }, []);
  useActivityRefresh(active, loadHistory);

  const latest = result ?? history;
  const ready = available === true && databaseAvailable === true;
  const loading = available === undefined || databaseAvailable === undefined;
  const tone = loading ? "checking" : ready ? "ready" : "attention";
  const threats = latest?.infected_count ?? latest?.threat_details?.length;
  const date = latest?.timestamp ? new Date(latest.timestamp) : null;
  const lastScan = date && Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
    : latest ? scanStatusLabel(latest.status) : historyState === "loading" ? _("Loading…") : historyState === "error" ? _("Unknown") : _("No scans recorded");
  const number = (value: number | undefined) => value === undefined ? _("Unknown") : new Intl.NumberFormat().format(value);

  return <>
    <section className={`status-hero ${tone}`} aria-labelledby="overview-status">
      <span className="overview-status-icon"><Icon name={ready ? "check-circle" : loading ? "info" : "warning"} /></span>
      <div className="status-hero-copy">
        <h2 id="overview-status">{scanning ? _("Scan in Progress") : loading ? _("Loading…") : ready ? _("Scanner available") : _("Scanner unavailable")}</h2>
        <p>{databaseAvailable === false ? _("Update the database before starting a scan.") : _("Scan files and folders with ClamAV.")}</p>
      </div>
      <button className="button primary dashboard-quick-scan" onClick={onQuickScan} disabled={scanning || !ready}><Icon name="bolt" />{_("Quick Scan")}</button>
    </section>
    <dl className="dashboard-metrics">
      <div><dt>{_("Last scanned")}</dt><dd>{lastScan}</dd></div>
      <div><dt>{_("Files scanned")}</dt><dd>{number(latest?.scanned_files)}</dd></div>
      <div className={threats ? "warning" : ""}><dt>{_("Threats found")}</dt><dd>{number(threats)}</dd></div>
    </dl>
    {latest && <section className="grouped-list overview-summary" aria-labelledby="overview-latest">
      <header className="overview-summary-header"><h2 id="overview-latest">{_("Latest scan")}</h2><span className={`status-badge ${latest.status === "clean" ? "success" : "warning"}`}>{scanStatusLabel(latest.status)}</span></header>
      {latest.summary && <p className="overview-summary-copy">{latest.summary}</p>}
      {latest.threat_details?.slice(0, 3).map((threat) => <div className="group-row" key={threat.file_path}><Icon name="warning" /><div className="row-copy"><strong>{threat.threat_name}</strong><code className="path-value" title={threat.file_path}>{threat.file_path}</code></div></div>)}
      <div className="overview-summary-actions"><button className="button" onClick={() => result ? navigate("results", { result }) : navigate("logs")}>{result ? _("View Results") : _("Logs")}</button></div>
    </section>}
  </>;
}
