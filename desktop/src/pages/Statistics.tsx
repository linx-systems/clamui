import { useCallback, useEffect, useState } from "react";
import { navigate, notify, onEvent, request } from "../api";
import { Icon } from "../Icon";
import { _, ngettext } from "../i18n";
type TrendPoint = { label: string; scans: number; threats: number };
type Protection = { level: string; message: string; lastScanTimestamp?: string; lastScanAgeHours?: number };
type Statistics = {
  totalScans: number;
  filesScanned: number;
  threatsDetected: number;
  cleanScans: number;
  averageDuration: number;
  startDate?: string;
  endDate?: string;
  trends: TrendPoint[];
  protection: Protection;
};

type Timeframe = "day" | "week" | "month" | "all";

function fieldValue(object: object, snake: string, camel: string): unknown {
  if (Object.prototype.hasOwnProperty.call(object, snake)) return Reflect.get(object, snake);
  if (Object.prototype.hasOwnProperty.call(object, camel)) return Reflect.get(object, camel);
  return undefined;
}


function optionalNumber(record: object, snake: string, camel: string): { value: number } | null {
  const value = fieldValue(record, snake, camel);
  return typeof value === "number" && Number.isFinite(value) ? { value } : null;
}

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function readNumber(record: object, snake: string, camel: string): number {
  const value = fieldValue(record, snake, camel);
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function readText(record: object, snake: string, camel: string): string | undefined {
  const value = fieldValue(record, snake, camel);
  return typeof value === "string" ? value : undefined;
}

function parseTrend(value: unknown): TrendPoint[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((point) => {
    if (!point || typeof point !== "object") return [];
    const label = readText(point, "label", "label") ?? readText(point, "date", "date");
    if (!label) return [];
    return [{ label, scans: readNumber(point, "scans", "scanCount"), threats: readNumber(point, "threats", "threatCount") }];
  });
}

function parseStatistics(value: unknown): Statistics | null {
  if (!value || typeof value !== "object") return null;
  const protectionValue = fieldValue(value, "protection_status", "protectionStatus");
  if (!protectionValue || typeof protectionValue !== "object") return null;
  const totalScans = optionalNumber(value, "total_scans", "totalScans");
  const filesScanned = optionalNumber(value, "files_scanned", "filesScanned");
  const threatsDetected = optionalNumber(value, "threats_detected", "threatsDetected");
  const cleanScans = optionalNumber(value, "clean_scans", "cleanScans");
  const averageDuration = optionalNumber(value, "average_duration", "averageDuration");
  const level = readText(protectionValue, "level", "level");
  const message = readText(protectionValue, "message", "message");
  const trends = fieldValue(value, "trends", "trends");
  if (!totalScans || !filesScanned || !threatsDetected || !cleanScans || !averageDuration || !level || !message || !Array.isArray(trends)) return null;
  const startDate = readText(value, "start_date", "startDate");
  const endDate = readText(value, "end_date", "endDate");
  const lastScanTimestamp = readText(protectionValue, "last_scan_timestamp", "lastScanTimestamp");
  const lastScanAgeHours = optionalNumber(protectionValue, "last_scan_age_hours", "lastScanAgeHours");
  return {
    totalScans: totalScans.value,
    filesScanned: filesScanned.value,
    threatsDetected: threatsDetected.value,
    cleanScans: cleanScans.value,
    averageDuration: averageDuration.value,
    ...(startDate ? { startDate } : {}),
    ...(endDate ? { endDate } : {}),
    trends: parseTrend(trends),
    protection: {
      level,
      message,
      ...(lastScanTimestamp ? { lastScanTimestamp } : {}),
      ...(lastScanAgeHours !== null ? { lastScanAgeHours: lastScanAgeHours.value } : {}),
    },
  };
}

function formatDuration(seconds: number): string {
  if (seconds <= 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function normalizedTimestamp(value: string): string {
  return value.replace(/(\.\d{3})\d+(?=(?:Z|[+-]\d{2}:?\d{2})?$)/, "$1");
}

function formatDateTime(value: string): string {
  const date = new Date(normalizedTimestamp(value));
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatDate(value: string): string {
  const dateOnly = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) {
    return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3])).toLocaleDateString();
  }
  const date = new Date(normalizedTimestamp(value));
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}


function formatLastScan(protection: Protection): string {
  if (!protection.lastScanTimestamp) return _("No scans recorded");
  const formatted = formatDateTime(protection.lastScanTimestamp);
  if (protection.lastScanAgeHours === undefined) return formatted;
  if (protection.lastScanAgeHours < 1) return `${formatted} (${_("less than an hour ago")})`;
  if (protection.lastScanAgeHours < 24) {
    const hours = Math.floor(protection.lastScanAgeHours);
    return `${formatted} (${ngettext("{count} hour ago", "{count} hours ago", hours, { count: hours })})`;
  }
  if (protection.lastScanAgeHours < 168) {
    const days = Math.floor(protection.lastScanAgeHours / 24);
    return `${formatted} (${ngettext("{count} day ago", "{count} days ago", days, { count: days })})`;
  }
  const weeks = Math.floor(protection.lastScanAgeHours / 168);
  return `${formatted} (${ngettext("{count} week ago", "{count} weeks ago", weeks, { count: weeks })})`;
}

function protectionLabel(level: string): string {
  if (level === "protected") return _("Protected");
  if (level === "at_risk") return _("At Risk");
  if (level === "unprotected") return _("Unprotected");
  if (level === "no_data") return _("No Data");
  if (level === "error") return _("Error");
  return _("Unknown");
}

function protectionMessage(message: string): string {
  if (message === "No scans performed yet") return _("No scans performed yet");
  if (message === "Last scan was over 30 days ago") return _("Last scan was over 30 days ago");
  if (message === "Last scan was over a week ago") return _("Last scan was over a week ago");
  if (message === "Virus definitions are over 7 days old") return _("Virus definitions are over 7 days old");
  if (message === "Virus definitions are over 1 day old") return _("Virus definitions are over 1 day old");
  if (message === "System is protected") return _("System is protected");
  return message;
}

function TrendChart({ points }: { points: TrendPoint[] }) {
  if (points.length === 0) return <p className="empty-state">{_("No scan activity in this timeframe.")}</p>;
  const maximum = Math.max(1, ...points.map((point) => Math.max(point.scans, point.threats)));
  return <div className="trend-chart" role="img" aria-label={_("Scan activity trend")}>
    {points.map((point) => {
      const scans = ngettext("{count} scan", "{count} scans", point.scans, { count: point.scans });
      const threats = ngettext("{count} threat", "{count} threats", point.threats, { count: point.threats });
      return <div className="trend-column" key={`${point.label}-${point.scans}-${point.threats}`}>
        <div className="trend-bars" aria-label={`${formatDate(point.label)}: ${scans}, ${threats}`}>
          <span className="trend-bar scans" style={{ height: `${(point.scans / maximum) * 100}%` }} title={scans} />
          <span className="trend-bar threats" style={{ height: `${(point.threats / maximum) * 100}%` }} title={threats} />
        </div>
        <span className="trend-label">{formatDate(point.label)}</span>
      </div>;
    })}
    <p className="trend-legend"><span className="legend-swatch scans" />{_("Scans")} <span className="legend-swatch threats" />{_("Threats")}</p>
  </div>;
}

export default function Statistics() {
  const [timeframe, setTimeframe] = useState<Timeframe>("week");
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStatistics = useCallback(async (selectedTimeframe: Timeframe) => {
    setLoading(true);
    setError(null);
    try {
      const result = await request<unknown>("logs.statistics", { timeframe: selectedTimeframe });
      const parsed = parseStatistics(result);
      if (!parsed) throw new Error(_("ClamUI returned invalid statistics data."));
      setStatistics(parsed);
    } catch (loadError) {
      const message = readableError(loadError);
      setError(message);
      notify(_("Failed to load statistics: {error}", { error: message }), "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatistics(timeframe);
  }, [loadStatistics, timeframe]);

  useEffect(() => {
    let dispose: (() => void) | undefined;
    let active = true;
    void onEvent((event) => {
      if (event.event === "scan-complete") void loadStatistics(timeframe);
    }).then((unlisten) => {
      if (active) dispose = unlisten;
      else unlisten();
    }).catch((listenError: unknown) => notify(_("Statistics updates are unavailable: {error}", { error: readableError(listenError) }), "warning"));
    return () => { active = false; dispose?.(); };
  }, [loadStatistics, timeframe]);

  const protection = statistics?.protection ?? { level: "unknown", message: _("Checking protection status") };
  const cards = statistics ? [
    [_("Total Scans"), statistics.totalScans.toLocaleString(), _("Number of scans performed")],
    [_("Files Scanned"), statistics.filesScanned.toLocaleString(), _("Total files checked")],
    [_("Threats Detected"), statistics.threatsDetected.toLocaleString(), _("Malware and suspicious files found")],
    [_("Clean Scans"), statistics.cleanScans.toLocaleString(), _("Scans with no threats found")],
    [_("Average Scan Duration"), formatDuration(statistics.averageDuration), _("Mean time per scan")],
  ] : [];

  return <main className="page statistics-page">
    <header className="page-header">
      <div><h1>{_("Statistics")}</h1><p>{_("Scan history and current protection posture.")}</p></div>
      <button className="button" type="button" onClick={() => void loadStatistics(timeframe)} disabled={loading}><Icon name="refresh" />{_("Refresh")}</button>
    </header>
    {error && <p className="error-banner" role="alert">{_("Unable to load statistics")}: {error}</p>}
    <section aria-labelledby="protection-heading">
      <header className="section-header">
        <div><h2 id="protection-heading">{_("Protection Status")}</h2><p>{_("Current system security posture")}</p></div>
        <span className={`status-badge ${protection.level}`}>{protectionLabel(protection.level)}</span>
      </header>
      <dl className="grouped-list summary-list">
        <div className="group-row"><dt>{_("System Status")}</dt><dd>{protectionMessage(protection.message)}</dd></div>
        <div className="group-row"><dt>{_("Last Scan")}</dt><dd>{formatLastScan(protection)}</dd></div>
      </dl>
    </section>
    <section aria-labelledby="timeframe-heading">
      <header className="section-header"><div><h2 id="timeframe-heading">{_("Timeframe")}</h2></div></header>
      <div className="timeframe-control segmented-control" role="group" aria-label={_("Statistics timeframe")}>{([ ["day", _("Day")], ["week", _("Week")], ["month", _("Month")], ["all", _("All Time")] ] as const).map(([value, label]) => <button type="button" key={value} aria-pressed={timeframe === value} onClick={() => setTimeframe(value)} disabled={loading}>{label}</button>)}</div>
    </section>
    <section aria-labelledby="statistics-heading">
      <header className="section-header"><div><h2 id="statistics-heading">{_("Scan Statistics")}</h2><p>{statistics?.startDate && statistics.endDate ? _(
        // Translators: Preserve the {range} placeholder; it contains a localized start–end date range.
        "Statistics for: {range}",
        { range: `${formatDateTime(statistics.startDate)} – ${formatDateTime(statistics.endDate)}` },
      ) : _("Aggregated metrics for the selected timeframe")}</p></div></header>
      {loading ? <p className="muted">{_("Loading statistics…")}</p> : statistics && statistics.totalScans === 0 ? <p className="empty-state">{_("No scan history yet. Run your first scan to see statistics and protection status.")}</p> : <div className="statistics-grid">{cards.map(([label, value, description]) => <article className={`group-row metric-card ${label === _("Threats Detected") && statistics && statistics.threatsDetected > 0 ? "error threat-detected" : ""}`} key={label}><h3 className="row-title">{label}</h3><strong>{value}</strong><p className="row-description">{description}</p></article>)}</div>}
    </section>
    <section aria-labelledby="activity-heading">
      <header className="section-header"><div><h2 id="activity-heading">{_("Scan Activity")}</h2><p>{_("Scan trends over the selected timeframe")}</p></div></header>
      <div className="grouped-list"><TrendChart points={statistics?.trends ?? []} /></div>
    </section>
    <section aria-labelledby="quick-actions-heading">
      <header className="section-header"><div><h2 id="quick-actions-heading">{_("Quick Actions")}</h2></div></header>
      <div className="quick-actions"><button className="group-row" type="button" onClick={() => navigate("scan", { quickScan: true })}>{_("Quick Scan")}<span>{_("Scan your home directory")}</span></button><button className="group-row" type="button" onClick={() => navigate("logs")}>{_("View Scan Logs")}<span>{_("See detailed scan history")}</span></button></div>
    </section>
  </main>;
}
