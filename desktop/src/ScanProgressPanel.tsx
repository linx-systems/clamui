import { _, ngettext } from "./i18n";

export type Threat = { file_path: string; threat_name: string; category?: string; severity?: string };
export type ScanProgress = { path?: string; target_index?: number; target_count?: number; files_scanned_total?: number; total_estimate?: number | null; estimate_approximate?: boolean; percentage?: number | null; current_file?: string; files_scanned?: number; scanned_files?: number; files_total?: number | null; total_files?: number | null; infected_count?: number; new_threats?: Threat[]; bytes_scanned?: number; estimate_exceeded?: boolean };

export function ScanProgressPanel({ progress, liveThreats, showLiveProgress, multipleTargets, onCancel }: {
  progress: ScanProgress;
  liveThreats: Threat[];
  showLiveProgress: boolean;
  multipleTargets: boolean;
  onCancel: () => void;
}) {
  const filesScanned = progress.files_scanned ?? progress.scanned_files ?? 0;
  const filesTotal = progress.files_total ?? progress.total_files;
  const estimateIndeterminate = progress.estimate_approximate || progress.estimate_exceeded || !filesTotal || filesScanned > filesTotal || progress.percentage === null;
  const scanPercent = estimateIndeterminate ? null : progress.percentage ?? (filesScanned / filesTotal!) * 100;
  const targetLabel = progress.path && progress.target_index && progress.target_count
    ? _("Target {index}/{count}: {path}", { index: progress.target_index, count: progress.target_count, path: progress.path })
    : progress.path ? `${_("Scan target")}: ${progress.path}` : null;

  return <section className="scan-progress grouped-list" aria-labelledby="scan-progress-title"><div className="group-row"><div className="row-copy">
    <h2 id="scan-progress-title" className="row-title">{_("Scanning")}</h2>
    {targetLabel && <p id="scan-progress-target" className="row-description path-value">{targetLabel}</p>}
    {progress.files_scanned_total !== undefined && <p className="muted">{ngettext("{count} file scanned overall", "{count} files scanned overall", progress.files_scanned_total, { count: progress.files_scanned_total })}</p>}
    {showLiveProgress ? <>
      <p className="row-description path-value">{progress.current_file || _("Waiting for scan data…")}</p>
      {scanPercent === null ? <progress className="progress" aria-label={targetLabel ?? _("Scan progress")} /> : <progress className="progress" value={scanPercent} max="100" aria-label={targetLabel ?? _("Scan progress")}>{scanPercent}</progress>}
      <p className="muted inline-metadata"><span className="metadata-item">{ngettext("{count} file scanned", "{count} files scanned", filesScanned, { count: filesScanned })}</span><span className="metadata-item">{ngettext("{count} threat", "{count} threats", progress.infected_count ?? liveThreats.length, { count: progress.infected_count ?? liveThreats.length })}</span></p>
      {estimateIndeterminate && <p className="muted">{_("File estimate is approximate; progress is indeterminate.")}</p>}
      {liveThreats.length > 0 && <ul className="summary-list">{liveThreats.slice(-10).map((threat, index) => <li key={`${threat.file_path}-${index}`}><strong>{threat.threat_name}</strong><span className="path-value">{threat.file_path}</span></li>)}</ul>}
    </> : <p className="row-description">{_("Live progress is disabled. The completed scan result will remain available.")}</p>}
  </div><button className="button danger" onClick={onCancel}>{multipleTargets ? _("Cancel All") : _("Cancel")}</button></div></section>;
}
