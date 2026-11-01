import { useCallback, useEffect, useRef, useState } from "react";
import { copyText, notify, onEvent, request, saveText } from "../api";
import { Icon } from "../Icon";
import { _, ngettext, scanStatusLabel } from "../i18n";
import { Modal } from "../Modal";

type LogEntry = {
  id: string;
  timestamp: string;
  type: string;
  status: string;
  summary: string;
  details?: string;
  path?: string | null;
  duration?: number;
  scheduled?: boolean;
};

type DaemonResult = { content?: string; error?: string; success?: boolean } | string;
type DaemonState = "running" | "stopped" | "not_installed" | "unknown";
type ComponentsStatus = {
  components: Array<{ id: string; status: "installed" | "missing" | "not_installed" | "running" | "stopped" | "unknown"; detail: string | null }>;
};

const PAGE_SIZE = 20;
const COPY_EXPORT_BYTES = 10 * 1024 * 1024;

function parseLogEntry(value: unknown): LogEntry | null {
  if (!value || typeof value !== "object") return null;
  const id = Reflect.get(value, "id");
  const timestamp = Reflect.get(value, "timestamp");
  const type = Reflect.get(value, "type");
  const status = Reflect.get(value, "status");
  const summary = Reflect.get(value, "summary");
  const details = Reflect.get(value, "details");
  const path = Reflect.get(value, "path");
  const duration = Reflect.get(value, "duration");
  const scheduled = Reflect.get(value, "scheduled");
  if (typeof id !== "string" || typeof timestamp !== "string" || typeof type !== "string" || typeof status !== "string" || typeof summary !== "string") return null;
  return {
    id,
    timestamp,
    type,
    status,
    summary,
    ...(typeof details === "string" ? { details } : {}),
    ...(typeof path === "string" || path === null ? { path } : {}),
    ...(typeof duration === "number" ? { duration } : {}),
    ...(typeof scheduled === "boolean" ? { scheduled } : {}),
  };
}

function asEntries(value: unknown): LogEntry[] {
  const entries = Array.isArray(value)
    ? value
    : value && typeof value === "object" && "entries" in value && Array.isArray(value.entries)
      ? value.entries
      : [];
  return entries.flatMap((entry) => {
    const parsed = parseLogEntry(entry);
    return parsed ? [parsed] : [];
  });
}

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatDuration(seconds: number | undefined): string | null {
  if (!seconds || seconds <= 0) return null;
  if (seconds < 60) return ngettext("{seconds} second", "{seconds} seconds", seconds, { seconds: seconds.toFixed(2) });
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function formatDetail(entry: LogEntry, timestamp: string): string {
  const heading = entry.type === "scan" ? _("SCAN LOG") : _("UPDATE LOG");
  const metadata = [
    `${_("ID")}: ${entry.id}`,
    `${_("Timestamp")}: ${timestamp}`,
    `${_("Type")}: ${entry.type}`,
    `${_("Status")}: ${entry.status}`,
    entry.path ? `${_("Path")}: ${entry.path}` : null,
    formatDuration(entry.duration) ? `${_("Duration")}: ${formatDuration(entry.duration)}` : null,
  ].filter((line): line is string => line !== null);
  const output = entry.details ? `\n--------------------------------------------------\n${_("Full Output")}:\n--------------------------------------------------\n${entry.details}` : "";
  return `${heading}\n==================================================\n\n${metadata.join("\n")}\n\n${_("Summary")}:\n  ${entry.summary}${output}`;
}
function daemonStatusLabel(status: DaemonState): string {
  switch (status) {
    case "running":
      return _("Running");
    case "stopped":
      return _("Stopped");
    case "not_installed":
      return _("Not installed");
    default:
      return _("Unknown");
  }
}

function StatusBadge({ status, label = scanStatusLabel(status) }: { status: string; label?: string }) {
  const kind = ["clean", "success", "up_to_date"].includes(status)
    ? "success"
    : ["infected", "error"].includes(status)
      ? "error"
      : "info";
  return <span className={`status-badge ${kind}`}>{label}</span>;
}

function historyStatusLabel(status: string): string {
  if (status === "success") return _("Success");
  if (status === "up_to_date") return _("Up to date");
  if (status === "skipped") return _("Skipped");
  if (status === "unknown") return _("Unknown");
  return scanStatusLabel(status);
}

function HistoryLogStatusIndicator({ status }: { status: string }) {
  const kind = ["clean", "success", "up_to_date"].includes(status)
    ? "success"
    : ["infected", "error"].includes(status)
      ? "error"
      : "info";
  const icon = kind === "success" ? "check-circle" : kind === "error" ? "audit" : "minus-circle";
  const label = historyStatusLabel(status);
  return <span aria-label={label} className={`status-badge ${kind} log-status-icon`} role="img" title={label}><Icon name={icon} /></span>;
}


export default function Logs() {
  const [tab, setTab] = useState<"history" | "daemon">("history");
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [selected, setSelected] = useState<LogEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [showAll, setShowAll] = useState(false);
  const [clearConfirming, setClearConfirming] = useState(false);
  const [daemonContent, setDaemonContent] = useState("");
  const [daemonError, setDaemonError] = useState<string | null>(null);
  const [daemonLoading, setDaemonLoading] = useState(false);
  const [daemonReadSucceeded, setDaemonReadSucceeded] = useState(false);
  const [daemonState, setDaemonState] = useState<DaemonState>("unknown");
  const [daemonDetail, setDaemonDetail] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [fullscreen, setFullscreen] = useState<{ title: string; content: string; kind: "detail" | "daemon" } | null>(null);
  const daemonInFlight = useRef(false);

  const loadEntries = useCallback(async () => {
    setLoading(true);
    try {
      const result = await request<unknown>("logs.list", { limit: 100 });
      setEntries(asEntries(result));
      setPage(1);
      setShowAll(false);
    } catch (error) {
      notify(_("Failed to load historical logs: {error}", { error: readableError(error) }), "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  useEffect(() => {
    let active = true;
    let dispose: (() => void) | undefined;
    void onEvent((event) => {
      if (event.event === "scan-complete" || event.event === "update-complete") void loadEntries();
    }).then((unlisten) => {
      if (active) dispose = unlisten;
      else unlisten();
    }).catch((listenError: unknown) => notify(_("Log updates are unavailable: {error}", { error: readableError(listenError) }), "warning"));
    return () => {
      active = false;
      dispose?.();
    };
  }, [loadEntries]);

  const loadDaemonStatus = useCallback(async () => {
    try {
      const result = await request<ComponentsStatus>("components.status");
      const daemon = result.components.find((component) => component.id === "clamd");
      if (!daemon) {
        setDaemonState("unknown");
        setDaemonDetail(_("Unable to determine ClamAV daemon status."));
        setLive(false);
        return;
      }
      if (daemon.status === "running") {
        setDaemonState("running");
        setDaemonDetail(daemon.detail);
      } else if (daemon.status === "stopped") {
        setDaemonState("stopped");
        setDaemonDetail(daemon.detail ?? _("ClamAV daemon is not running."));
      } else if (daemon.status === "missing" || daemon.status === "not_installed") {
        setDaemonState("not_installed");
        setDaemonDetail(daemon.detail ?? _("ClamAV daemon is not installed."));
        setLive(false);
      } else {
        setDaemonState("unknown");
        setDaemonDetail(daemon.detail ?? _("Unable to determine ClamAV daemon status."));
        setLive(false);
      }
    } catch (error) {
      setDaemonState("unknown");
      setDaemonDetail(readableError(error));
      setLive(false);
    }
  }, []);

  useEffect(() => {
    const stopLiveUpdatesElsewhere = (event: Event): void => {
      if (!(event instanceof CustomEvent) || !event.detail || typeof event.detail !== "object" || !("page" in event.detail)) return;
      if (event.detail.page !== "logs") setLive(false);
    };
    window.addEventListener("clamui-page-selected", stopLiveUpdatesElsewhere);
    return () => window.removeEventListener("clamui-page-selected", stopLiveUpdatesElsewhere);
  }, []);

  const refreshDaemon = useCallback(async () => {
    if (daemonInFlight.current) return;
    daemonInFlight.current = true;
    setDaemonLoading(true);
    try {
      const result = await request<DaemonResult>("logs.daemon", { lines: 100 });
      const normalized = typeof result === "string" ? { content: result, success: true } : result;
      if (normalized.success === false || normalized.error) {
        setDaemonError(normalized.error ?? _("Unable to load daemon logs."));
        setDaemonContent("");
        setDaemonReadSucceeded(false);
      } else {
        setDaemonContent(normalized.content ?? "");
        setDaemonError(null);
        setDaemonReadSucceeded(true);
      }
    } catch (error) {
      setDaemonContent("");
      setDaemonError(readableError(error));
      setDaemonReadSucceeded(false);
    } finally {
      daemonInFlight.current = false;
      setDaemonLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab !== "daemon") {
      setLive(false);
      return;
    }
    void loadDaemonStatus();
  }, [loadDaemonStatus, tab]);

  useEffect(() => {
    if (tab !== "daemon" || !live || (daemonState !== "running" && daemonState !== "stopped")) return;
    void refreshDaemon();
    const timer = window.setInterval(() => void refreshDaemon(), 3000);
    return () => window.clearInterval(timer);
  }, [daemonState, live, refreshDaemon, tab]);

  const selectEntry = async (entry: LogEntry) => {
    setSelected(entry);
    try {
      const result = await request<unknown>("logs.get", { id: entry.id });
      const complete = parseLogEntry(result);
      if (!complete) throw new Error(_("The log entry returned by ClamUI was incomplete."));
      setSelected((current) => current?.id === entry.id ? complete : current);
    } catch (error) {
      notify(_("Failed to load log details: {error}", { error: readableError(error) }), "error");
    }
  };

  const exportLogs = async (format: "csv" | "json" | "text", ids?: string[]) => {
    try {
      const content = await request<string>("logs.export", { schema: "ui", format, ...(ids ? { ids } : {}) });
      const extension = format === "text" ? "txt" : format;
      const saved = await saveText(content, ids ? `clamui-log-${ids[0]}.${extension}` : `clamui-logs.${extension}`, [{ name: format === "text" ? _("Text") : format.toUpperCase(), extensions: [extension] }]);
      if (saved) notify(ids ? _("Exported selected log.") : _("Exported all logs."), "success");
    } catch (error) {
      notify(`${_("Failed to export logs")}: ${readableError(error)}`, "error");
    }
  };

  const exportSelectedText = async () => {
    if (!selected) return;
    try {
      const saved = await saveText(formatDetail(selected, selected.timestamp), `clamui-log-${selected.id}.txt`, [{ name: _("Text"), extensions: ["txt"] }]);
      if (saved) notify(_("Exported selected log."), "success");
    } catch (error) {
      notify(`${_("Failed to export log")}: ${readableError(error)}`, "error");
    }
  };

  const copySelectedDetail = async () => {
    if (!selected) return;
    const content = formatDetail(selected, selected.timestamp);
    if (new TextEncoder().encode(content).byteLength > COPY_EXPORT_BYTES) {
      notify(_("Log details are too large for the clipboard. Choose an export destination instead."), "info");
      await exportSelectedText();
      return;
    }
    try {
      await copyText(content);
      notify(_("Log details copied to clipboard"), "success");
    } catch (error) {
      notify(`${_("Failed to copy log details")}: ${readableError(error)}`, "error");
    }
  };

  const copyFullscreen = async () => {
    if (!fullscreen) return;
    if (fullscreen.kind === "detail") {
      await copySelectedDetail();
      return;
    }
    try {
      await copyText(fullscreen.content);
      notify(_("Daemon logs copied to clipboard"), "success");
    } catch (error) {
      notify(`${_("Failed to copy daemon logs")}: ${readableError(error)}`, "error");
    }
  };

  const clearLogs = async () => {
    try {
      const result = await request<unknown>("logs.clear");
      const failures = result && typeof result === "object" && "failures" in result && Array.isArray(result.failures) ? result.failures.length : 0;
      setSelected(null);
      setClearConfirming(false);
      if (failures > 0) {
        notify(ngettext(
          "Historical logs were cleared with {count} cleanup failure.",
          "Historical logs were cleared with {count} cleanup failures.",
          failures,
          { count: failures },
        ), "warning");
      } else notify(_("Historical logs cleared."), "success");
      await loadEntries();
    } catch (error) {
      notify(_("Failed to clear logs: {error}", { error: readableError(error) }), "error");
    }
  };

  const displayed = showAll ? entries : entries.slice(0, page * PAGE_SIZE);
  const detail = selected ? formatDetail(selected, formatDate(selected.timestamp)) : _("Select a log entry to view details.");
  const daemonDisplay = daemonError ? `${_("Error loading daemon logs")}: \n\n${daemonError}` : daemonContent;
  const daemonLiveAvailable = daemonState === "running" || daemonState === "stopped";
  const daemonExportAvailable = daemonReadSucceeded && daemonContent.length > 0;

  return (
    <main className="page logs-page">
      <header className="page-header"><div><h1>{_("Logs")}</h1><p>{_("Review previous scan and update operations.")}</p></div></header>
      <div className="tab-list" role="tablist" aria-label={_("Log source")}>
        <button className="button" id="history-tab" type="button" role="tab" aria-controls="history-panel" aria-selected={tab === "history"} onClick={() => setTab("history")}>{_("Historical Logs")}</button>
        <button className="button" id="daemon-tab" type="button" role="tab" aria-controls="daemon-panel" aria-selected={tab === "daemon"} onClick={() => setTab("daemon")}>{_("ClamAV Daemon")}</button>
      </div>

      {tab === "history" ? <div id="history-panel" role="tabpanel" aria-labelledby="history-tab">
        <section aria-labelledby="history-heading">
          <header className="section-header"><div><h2 className="section-heading" id="history-heading">{_("Historical Logs")}</h2><p>{_("Previous scan and update operations")}</p></div><div className="actions logs-history-actions">
            <button className="button icon-button" type="button" title={_("Refresh")} aria-label={_("Refresh")} onClick={() => void loadEntries()} disabled={loading}><Icon name="refresh" /></button>
            <button className="button icon-button" type="button" title={_("Export CSV")} aria-label={_("Export CSV")} onClick={() => void exportLogs("csv")} disabled={!entries.length}><Icon name="file-csv" /></button>
            <button className="button icon-button" type="button" title={_("Export JSON")} aria-label={_("Export JSON")} onClick={() => void exportLogs("json")} disabled={!entries.length}><Icon name="file-json" /></button>
            <button className="button destructive icon-button" type="button" title={_("Clear All")} aria-label={_("Clear All")} onClick={() => setClearConfirming(true)} disabled={!entries.length}><Icon name="trash" /></button>
          </div></header>
          <div className="grouped-list">
            {loading ? <p className="muted">{_("Loading logs…")}</p> : entries.length === 0 ? <p className="empty-state">{_("No historical logs yet.")}</p> : <>
              <div className="log-list" role="list">
                {displayed.map((entry) => <button type="button" role="listitem" className={`group-row log-row ${selected?.id === entry.id ? "selected" : ""}`} key={entry.id} onClick={() => void selectEntry(entry)}>
                  <span className="log-row-copy"><strong className="row-title">{entry.summary}</strong><span className="row-description inline-metadata"><span className="metadata-item">{formatDate(entry.timestamp)}</span><span className="metadata-item">{scanStatusLabel(entry.status)}</span>{entry.path && <span className="metadata-item">{entry.path}</span>}</span></span><HistoryLogStatusIndicator status={entry.status} />
                </button>)}
              </div>
              <div className="logs-pagination">
                <p className="logs-pagination-summary" role="status" aria-live="polite">{ngettext("{shown} of {total} loaded log shown", "{shown} of {total} loaded logs shown", entries.length, { shown: displayed.length, total: entries.length })}</p>
                {!showAll && displayed.length < entries.length && <div className="logs-pagination-actions"><button className="button primary" type="button" onClick={() => setPage((current) => current + 1)}><Icon name="chevron-down" />{_("Load More")}</button><button className="button" type="button" onClick={() => setShowAll(true)}><Icon name="logs" />{_("Show All ({count})", { count: entries.length })}</button></div>}
              </div>
            </>}
          </div>
        </section>
        <section aria-labelledby="details-heading">
          <header className="section-header"><div><h2 className="section-heading" id="details-heading">{_("Log Details")}</h2></div><div className="actions logs-detail-actions">
            <button className="button icon-button" type="button" title={_("Copy")} aria-label={_("Copy")} onClick={() => void copySelectedDetail()} disabled={!selected}><Icon name="copy" /></button>
            <button className="button icon-button" type="button" title={_("Export Text")} aria-label={_("Export Text")} onClick={() => void exportSelectedText()} disabled={!selected}><Icon name="file" /></button>
            <button className="button icon-button" type="button" title={_("Export CSV")} aria-label={_("Export CSV")} onClick={() => selected && void exportLogs("csv", [selected.id])} disabled={!selected}><Icon name="file-csv" /></button>
            <button className="button icon-button" type="button" title={_("Export JSON")} aria-label={_("Export JSON")} onClick={() => selected && void exportLogs("json", [selected.id])} disabled={!selected}><Icon name="file-json" /></button>
            <button className="button icon-button" type="button" title={_("Fullscreen")} aria-label={_("Fullscreen")} onClick={() => setFullscreen({ title: _("Log Details"), content: detail, kind: "detail" })} disabled={!selected}><Icon name="expand" /></button>
          </div></header>
          <div className="grouped-list log-details"><pre className="log-output">{detail}</pre></div>
        </section>
      </div> : <div id="daemon-panel" role="tabpanel" aria-labelledby="daemon-tab">
        <section aria-labelledby="daemon-heading">
          <header className="section-header"><div><h2 className="section-heading" id="daemon-heading">{_("ClamAV Daemon")}</h2><p>{_("Live host daemon log output.")}</p></div><div className="actions">
            <button className="button" type="button" onClick={() => setLive((enabled) => !enabled)} aria-pressed={live} disabled={!daemonLiveAvailable}>{live ? _("Stop Live Updates") : _("Start Live Updates")}</button>
            <button className="button" type="button" onClick={() => void Promise.all([loadDaemonStatus(), refreshDaemon()])} disabled={daemonLoading}><Icon name="refresh" />{_("Refresh")}</button>
            <button className="button" type="button" onClick={() => void saveText(daemonContent, "clamd-logs.txt", [{ name: _("Text"), extensions: ["txt"] }]).then((saved) => saved && notify(_("Exported daemon logs."), "success")).catch((error: unknown) => notify(`${_("Failed to export daemon logs")}: ${readableError(error)}`, "error"))} disabled={!daemonExportAvailable}>{_("Export Text")}</button>
            <button className="button" type="button" onClick={() => setFullscreen({ title: _("Daemon Logs"), content: daemonDisplay, kind: "daemon" })} disabled={!daemonContent && !daemonError}><Icon name="expand" />{_("Fullscreen")}</button>
          </div></header>
          <div className="grouped-list">
            <div className="group-row"><p className={`daemon-status ${daemonState}`}><StatusBadge status={daemonState} label={daemonStatusLabel(daemonState)} /> {daemonDetail ?? _("Checking daemon status…")}</p></div>
            {live && <p className="notice">{_("Live refresh is active every 3 seconds.")}</p>}
            {daemonContent || daemonError ? <pre className={`log-output ${daemonError ? "error-output" : ""}`}>{daemonDisplay}</pre> : <p className="empty-state">{_("Daemon logs will appear here after a successful read.")}</p>}
          </div>
        </section>
      </div>}

      {clearConfirming && <Modal title={_("Clear All Logs?")} onClose={() => setClearConfirming(false)}><p>{_("This will permanently delete all historical logs. This action cannot be undone.")}</p><div className="button-row"><button className="button" type="button" onClick={() => setClearConfirming(false)}>{_("Cancel")}</button><button type="button" className="button destructive" onClick={() => void clearLogs()}>{_("Clear All")}</button></div></Modal>}
      {fullscreen && <Modal title={fullscreen.title} onClose={() => setFullscreen(null)} className="fullscreen-log"><pre className="log-output">{fullscreen.content}</pre><div className="button-row"><button className="button" type="button" onClick={() => void copyFullscreen()}><Icon name="copy" />{_("Copy")}</button></div></Modal>}
    </main>
  );
}
