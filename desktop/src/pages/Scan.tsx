import { DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../Icon";
import { Modal } from "../Modal";
import { _, ngettext, scanStatusLabel } from "../i18n";
import { copyText, navigate, notify, onEvent, openExternal, openPaths, request, startupState } from "../api";
import { formatScanOutput } from "../scanOutput";
import { scanLogChunks } from "../scanLog";
import { ScanLogViewport } from "../ScanLogViewport";
import { profileDescription, profileLabel } from "../profilePresentation";


type Profile = { id: string; name: string; targets: string[]; exclusions: { paths?: string[]; patterns?: string[] }; is_default: boolean; description: string; options: Record<string, unknown> };
type Threat = { file_path: string; threat_name: string; category?: string; severity?: string };
type ScanProgress = { current_file?: string; files_scanned?: number; scanned_files?: number; files_total?: number | null; total_files?: number | null; infected_count?: number; new_threats?: Threat[]; bytes_scanned?: number; estimate_exceeded?: boolean };
type ScanResult = { status: string; path?: string; stdout?: string; stderr?: string; exit_code?: number; scanned_files?: number; scanned_dirs?: number; infected_count?: number; infected_files?: string[]; threat_details?: Threat[]; skipped_files?: string[]; skipped_count?: number; warning_message?: string; nonfatal_warnings?: string[]; error_message?: string | null; per_target_results?: ScanResult[] };
type ScannerStatus = { available?: boolean; backend?: string; active_backend?: string; database_available?: boolean; database_error?: string; error?: string };
type StatusNotice = { kind: "success" | "warning" | "error" | "info"; message: string; detail?: string };
type EventRecord = Record<string, unknown>;
type ProgressEvent = ScanProgress & { id: string };
type PendingProfile = { id?: string; name?: string; start: boolean };

function eventRecord(value: unknown): EventRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as EventRecord : null;
}

function threatList(value: unknown): Threat[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.flatMap((item) => {
    const record = eventRecord(item);
    return record && typeof record.file_path === "string" && typeof record.threat_name === "string"
      ? [{ file_path: record.file_path, threat_name: record.threat_name, category: typeof record.category === "string" ? record.category : undefined, severity: typeof record.severity === "string" ? record.severity : undefined }]
      : [];
  });
}

function progressEvent(value: unknown): ProgressEvent | null {
  const record = eventRecord(value);
  if (!record || typeof record.id !== "string") return null;
  return {
    id: record.id,
    current_file: typeof record.current_file === "string" ? record.current_file : undefined,
    files_scanned: typeof record.files_scanned === "number" ? record.files_scanned : undefined,
    scanned_files: typeof record.scanned_files === "number" ? record.scanned_files : undefined,
    files_total: typeof record.files_total === "number" ? record.files_total : null,
    total_files: typeof record.total_files === "number" ? record.total_files : null,
    infected_count: typeof record.infected_count === "number" ? record.infected_count : undefined,
    new_threats: threatList(record.new_threats),
    bytes_scanned: typeof record.bytes_scanned === "number" ? record.bytes_scanned : undefined,
    estimate_exceeded: record.estimate_exceeded === true,
  };
}

function scanResultEvent(value: unknown): ScanResult | null {
  const record = eventRecord(value);
  return record && typeof record.status === "string" ? record as ScanResult : null;
}


const VT_UPLOAD_URL = "https://www.virustotal.com/gui/home/upload";

function uniquePaths(paths: string[]): string[] {
  const seen = new Set<string>();
  return paths.filter((raw) => {
    const path = raw.trim();
    if (!path || path.includes("\0")) return false;
    const normalized = path.replace(/\/+$/, "") || "/";
    if (seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

function localPath(value: string): string | null {
  if (!value) return null;
  if (!value.startsWith("file:")) return value.startsWith("/") ? value : null;
  try {
    const url = new URL(value);
    return url.protocol === "file:" && (!url.hostname || url.hostname === "localhost") ? decodeURIComponent(url.pathname) : null;
  } catch {
    return null;
  }
}

function resultNotice(result: ScanResult): StatusNotice {
  const count = result.infected_count ?? result.threat_details?.length ?? 0;
  if (result.status === "clean") return {
    kind: "success",
    message: result.warning_message
      ? _("Scan complete with warnings")
      : _(
        // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
        "Scan complete — no threats found",
      ),
    detail: result.warning_message,
  };
  if (result.status === "infected") return {
    kind: "warning",
    message: ngettext(
      // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
      "Scan complete — {count} threat detected",
      "Scan complete — {count} threats detected",
      count,
      { count },
    ),
  };
  if (result.status === "cancelled") return {
    kind: "warning",
    message: _(
      // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
      "Scan cancelled — partial results are available",
    ),
  };
  return { kind: "error", message: _("Scan error"), detail: result.error_message || result.stderr || result.stdout || _("Unknown error") };
}

function VirusTotalDialog({ path, onClose }: { path: string; onClose: () => void }) {
  const [keyStatus, setKeyStatus] = useState<{ present?: boolean; masked?: string } | null>(null);
  const [key, setKey] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void request<{ present?: boolean; masked?: string }>("virustotal.key_status").then(setKeyStatus).catch((reason: unknown) => setError(String(reason)));
  }, []);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await request<Record<string, unknown>>("virustotal.scan", { id: `vt-${crypto.randomUUID()}`, path });
      try {
        sessionStorage.setItem("clamui-last-vt-result", JSON.stringify(result));
      } catch {
        // Result remains available through navigation.
      }
      window.dispatchEvent(new CustomEvent("clamui-vt-result", { detail: result }));
      onClose();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const saveAndStart = async () => {
    if (!/^[a-fA-F0-9]{64}$/.test(key)) {
      setError(_("API key must contain exactly 64 hexadecimal characters"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await request("virustotal.key_save", { key });
      await start();
    } catch (reason) {
      setError(String(reason));
      setBusy(false);
    }
  };

  const openManualUpload = async () => {
    setBusy(true);
    setError(null);
    try {
      if (remember) await request("settings.update", { virustotal_remember_no_key_action: "open_website" });
      await openExternal(VT_UPLOAD_URL);
      onClose();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  return <Modal title={_("VirusTotal Scan")} onClose={onClose}>
    <p>{_("VirusTotal uploads one file at a time. Only send files you are authorized to share.")}</p>
    <p className="monospace">{path}</p>
    {error && <p className="error" role="alert">{error}</p>}
    {keyStatus?.present ? <>
      <p className="muted">{_("API key available")}{keyStatus.masked ? ` (${keyStatus.masked})` : ""}</p>
      <button className="button primary" onClick={() => void start()} disabled={busy}>{busy ? _("Scanning…") : _("Scan with VirusTotal")}</button>
    </> : <>
      <label className="field">{_("API Key")}<input type="password" autoComplete="off" spellCheck={false} value={key} onChange={(event) => setKey(event.target.value.trim())} /></label>
      <button className="button primary" onClick={() => void saveAndStart()} disabled={busy || !key}>{busy ? _("Saving…") : _("Save & Scan")}</button>
      <label className="check-row"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> {_("Remember my choice")}</label>
      <button className="button" onClick={() => void openManualUpload()} disabled={busy}>{_("Upload file manually")}</button>
    </>}
  </Modal>;
}

export default function Scan() {
  const [paths, setPaths] = useState<string[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [scanner, setScanner] = useState<ScannerStatus | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const startAfterTargets = useRef(false);
  const [progress, setProgress] = useState<ScanProgress>({});
  const [liveThreats, setLiveThreats] = useState<Threat[]>([]);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [notice, setNotice] = useState<StatusNotice | null>(null);
  const [missingDatabase, setMissingDatabase] = useState(false);
  const [vtPath, setVtPath] = useState<string | null>(null);
  const [fullscreenDetails, setFullscreenDetails] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const scanning = activeId !== null;

  useEffect(() => {
    if (!result) setDetailsOpen(false);
  }, [result]);

  const loadProfiles = useCallback(async () => {
    try {
      setProfiles((await request<{ profiles: Profile[] }>("profiles.list")).profiles);
    } catch (reason) {
      setNotice({ kind: "error", message: _("Unable to load scan profiles"), detail: String(reason) });
    }
  }, []);
  const refreshStatus = useCallback(async () => {
    try {
      setScanner(await request<ScannerStatus>("scanner.status"));
    } catch (reason) {
      setNotice({ kind: "error", message: _("Unable to check scanner status"), detail: String(reason) });
    }
  }, []);
  const replacePaths = useCallback((incoming: string[]) => setPaths(uniquePaths(incoming)), []);
  const addPaths = useCallback((incoming: string[]) => setPaths((current) => uniquePaths([...current, ...incoming])), []);
  const finish = useCallback((scanResult: ScanResult) => {
    const completedId = activeIdRef.current;
    setResult(scanResult);
    setNotice(resultNotice(scanResult));
    setActiveId(null);
    activeIdRef.current = null;
    setProgress({});
    try {
      sessionStorage.setItem("clamui-last-scan-result", JSON.stringify(scanResult));
    } catch {
      // Result remains available in the mounted page.
    }
    if (completedId) window.dispatchEvent(new CustomEvent("clamui-scan-state", { detail: { id: completedId, active: false } }));
    window.dispatchEvent(new CustomEvent("clamui-scan-result", { detail: scanResult }));
  }, []);

  const [showLiveProgress, setShowLiveProgress] = useState(true);
  const selectedProfile = useMemo(() => profiles.find((profile) => profile.id === profileId) ?? null, [profileId, profiles]);
  const refreshLiveProgress = useCallback(async (id: string) => {
    try {
      const settings = await request<Record<string, unknown>>("settings.get");
      if (activeIdRef.current === id && typeof settings.show_live_progress === "boolean") setShowLiveProgress(settings.show_live_progress);
    } catch {
      // Scans remain available if the preference cannot be refreshed.
    }
  }, []);
  const startScan = useCallback(async () => {
    if (activeIdRef.current) return;
    if (paths.length === 0) {
      setNotice({ kind: "warning", message: _("Please select a file or folder to scan") });
      return;
    }
    if (scanner?.database_available === false) {
      setMissingDatabase(true);
      return;
    }
    const id = `scan-${crypto.randomUUID()}`;
    activeIdRef.current = id;
    setActiveId(id);
    window.dispatchEvent(new CustomEvent("clamui-scan-state", { detail: { id, active: true } }));
    setProgress({});
    setLiveThreats([]);
    setResult(null);
    setNotice({ kind: "info", message: _("Starting scan…") });
    await refreshLiveProgress(id);
    if (activeIdRef.current !== id) return;
    try {
      const response = await request<ScanResult>("scanner.scan", {
        id,
        paths,
        recursive: true,
        profile_id: selectedProfile?.id,
        profile_name: selectedProfile?.name,
        exclusions: selectedProfile?.exclusions,
      });
      if (activeIdRef.current === id) finish(response);
    } catch (reason) {
      if (activeIdRef.current === id) finish({ status: "error", error_message: String(reason), threat_details: [] });
    }
  }, [finish, paths, refreshLiveProgress, scanner?.database_available, selectedProfile]);

  const startScanRef = useRef(startScan);
  const startupConsumedRef = useRef(false);
  const profilesRef = useRef<Profile[]>([]);
  const pendingProfileRef = useRef<PendingProfile | null>(null);

  useEffect(() => {
    startScanRef.current = startScan;
  }, [startScan]);
  useEffect(() => {
    profilesRef.current = profiles;
  }, [profiles]);
  useEffect(() => {
    void request<Record<string, unknown>>("settings.get").then((settings) => {
      if (typeof settings.show_live_progress === "boolean") setShowLiveProgress(settings.show_live_progress);
    }).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (startAfterTargets.current && paths.length > 0) {
      startAfterTargets.current = false;
      void startScan();
    }
  }, [paths, startScan]);
  useEffect(() => {
    void loadProfiles();
    void refreshStatus();
  }, [loadProfiles, refreshStatus]);

  const applyProfile = useCallback((pending: PendingProfile, reload = true) => {
    if (activeIdRef.current) {
      setNotice({
        kind: "warning",
        message: _(
          // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
          "Scan in progress — wait for it to finish before changing targets",
        ),
      });
      return;
    }
    const profile = profilesRef.current.find((candidate) => pending.id ? candidate.id === pending.id : candidate.name === pending.name);
    if (!profile) {
      pendingProfileRef.current = pending;
      if (reload) void loadProfiles();
      return;
    }
    pendingProfileRef.current = null;
    setProfileId(profile.id);
    replacePaths(profile.targets);
    if (pending.start) {
      if (profile.targets.length > 0) startAfterTargets.current = true;
      else setNotice({ kind: "warning", message: profile.name === "Quick Scan" ? _("Quick Scan profile has no valid targets") : _("Please select a file or folder to scan") });
    }
  }, [loadProfiles, replacePaths]);

  useEffect(() => {
    const pending = pendingProfileRef.current;
    if (pending) applyProfile(pending, false);
  }, [applyProfile, profiles]);

  useEffect(() => {
    let stopped = false;
    const rejectTargetChange = () => {
      setNotice({
        kind: "warning",
        message: _(
          // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
          "Scan in progress — wait for it to finish before adding targets",
        ),
      });
    };
    const openTargets = (data: unknown, startRequested = false) => {
      if (activeIdRef.current) {
        rejectTargetChange();
        return;
      }
      const payload = eventRecord(data);
      const requested = Array.isArray(payload?.paths)
        ? payload.paths.filter((path): path is string => typeof path === "string").map(localPath).filter((path): path is string => path !== null)
        : [];
      if (requested.length === 0) return;
      if (typeof payload?.profile_id === "string") setProfileId(payload.profile_id);
      replacePaths(requested);
      if (payload?.virustotal === true) {
        setVtPath(requested[0]);
        if (requested.length > 1) notify(ngettext("VirusTotal scans one file at a time; {count} selection was ignored.", "VirusTotal scans one file at a time; {count} selections were ignored.", requested.length - 1, { count: requested.length - 1 }), "warning");
      } else if (payload?.start === true || startRequested) {
        startAfterTargets.current = true;
      }
    };
    const droppedTargets = (data: unknown) => {
      if (activeIdRef.current) {
        rejectTargetChange();
        return;
      }
      const payload = eventRecord(data);
      const requested = Array.isArray(payload?.paths)
        ? payload.paths.filter((path): path is string => typeof path === "string").map(localPath).filter((path): path is string => path !== null)
        : [];
      if (requested.length === 0) {
        setNotice({ kind: "error", message: _("Only local files and folders can be scanned") });
        return;
      }
      addPaths(requested);
    };
    const pageSelected = (event: Event) => {
      const detail = event instanceof CustomEvent ? eventRecord(event.detail) : null;
      if (detail?.page !== "scan") return;
      const args = eventRecord(detail.args);
      if (typeof args?.profile_id === "string") applyProfile({ id: args.profile_id, start: args.start === true });
      else if (args?.quickScan === true) applyProfile({ name: "Quick Scan", start: true });
    };

    if (!startupConsumedRef.current) {
      startupConsumedRef.current = true;
      void startupState().then((state) => {
        if (!stopped) openTargets(state, true);
      }).catch(() => undefined);
    }
    window.addEventListener("clamui-page-selected", pageSelected);
    const unlisten = onEvent((event) => {
      if (event.event === "scan-progress") {
        const data = progressEvent(event.data);
        if (data?.id === activeIdRef.current) {
          setProgress(data);
          if (data.new_threats?.length) setLiveThreats((current) => [...current, ...data.new_threats!]);
        }
      } else if (event.event === "scan-complete") {
        const data = eventRecord(event.data);
        const completed = scanResultEvent(data?.result);
        if (data?.id === activeIdRef.current && completed) finish(completed);
      } else if (event.event === "open-targets") {
        openTargets(event.data);
      } else if (event.event === "dropped-targets") {
        droppedTargets(event.data);
      } else if (event.event === "select-profile") {
        const payload = eventRecord(event.data);
        if (typeof payload?.profile_id === "string") applyProfile({ id: payload.profile_id, start: false });
      } else if (event.event === "start-scan" || (event.event === "shortcut" && eventRecord(event.data)?.action === "start-scan")) {
        void startScanRef.current();
      }
    });
    return () => {
      stopped = true;
      window.removeEventListener("clamui-page-selected", pageSelected);
      void unlisten.then((dispose) => dispose());
    };
  }, [addPaths, applyProfile, finish, replacePaths]);

  useEffect(() => {
    const reloadProfiles = () => {
      void loadProfiles();
    };
    const quickScan = () => applyProfile({ name: "Quick Scan", start: true });
    window.addEventListener("clamui-profiles-updated", reloadProfiles);
    window.addEventListener("clamui-quick-scan", quickScan);
    return () => {
      window.removeEventListener("clamui-profiles-updated", reloadProfiles);
      window.removeEventListener("clamui-quick-scan", quickScan);
    };
  }, [applyProfile, loadProfiles]);

  const choosePaths = async (directory: boolean) => {
    try {
      const selected = await openPaths({ directory, multiple: true });
      if (activeIdRef.current) {
        setNotice({
          kind: "warning",
          message: _(
            // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
            "Scan in progress — wait for it to finish before adding targets",
          ),
        });
        return;
      }
      addPaths(selected);
    } catch (reason) {
      setNotice({ kind: "error", message: _("Unable to choose scan targets"), detail: String(reason) });
    }
  };
  const cancel = async () => {
    if (!activeIdRef.current) return;
    try {
      await request("scanner.cancel", { id: activeIdRef.current });
      setNotice({ kind: "warning", message: _("Cancelling scan…") });
    } catch (reason) {
      setNotice({ kind: "error", message: _("Unable to cancel scan"), detail: String(reason) });
    }
  };
  const runEicar = async () => {
    if (activeIdRef.current) return;
    if (scanner?.database_available === false) {
      setMissingDatabase(true);
      return;
    }
    const id = `eicar-${crypto.randomUUID()}`;
    activeIdRef.current = id;
    setActiveId(id);
    window.dispatchEvent(new CustomEvent("clamui-scan-state", { detail: { id, active: true } }));
    setProgress({});
    setLiveThreats([]);
    setResult(null);
    setNotice({ kind: "info", message: _("Running EICAR test…") });
    await refreshLiveProgress(id);
    if (activeIdRef.current !== id) return;
    try {
      const response = await request<ScanResult>("scanner.eicar", scanner?.backend === "daemon" || scanner?.active_backend === "daemon"
        ? { id, backend_override: "daemon", force_stream: true }
        : { id });
      if (activeIdRef.current === id) finish(response);
    } catch (reason) {
      if (activeIdRef.current === id) finish({ status: "error", error_message: String(reason), threat_details: [] });
    }
  };
  const drop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    if (activeIdRef.current) {
      setNotice({
        kind: "warning",
        message: _(
          // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
          "Scan in progress — wait for it to finish before adding targets",
        ),
      });
      return;
    }
    const values = event.dataTransfer.getData("text/uri-list").split(/\r?\n/).filter((line) => line && !line.startsWith("#"));
    const dropped = values.map(localPath).filter((path): path is string => path !== null);
    if (dropped.length === 0) setNotice({ kind: "error", message: _("Only local files and folders can be scanned") });
    else addPaths(dropped);
  };
  const copyDetails = async (scanResult: ScanResult) => {
    try {
      await copyText(formatScanOutput(scanResult, _("Scan target")));
    } catch (reason) {
      setNotice({ kind: "error", message: _("Scan error"), detail: String(reason) });
    }
  };

  const filesScanned = progress.files_scanned ?? progress.scanned_files ?? 0;
  const filesTotal = progress.files_total ?? progress.total_files;
  const scanPercent = filesTotal && filesTotal > 0 ? Math.min(100, Math.max(0, (filesScanned / filesTotal) * 100)) : null;
  const detailChunks = useMemo<readonly string[]>(() => result ? scanLogChunks(result) : [], [result]);
  const resultStatus = result?.status === "infected" ? "warning" : result?.status === "error" ? "error" : result?.status === "clean" ? "success" : "";

  return <section className="page scan-page" onDragOver={(event) => event.preventDefault()} onDrop={drop} aria-label={_("Scan")}>
    <header className="page-header">
      <div><h1>{_("Scan")}</h1><p className="muted">{scanner?.active_backend || scanner?.backend ? `${_("Backend")}: ${scanner.active_backend ?? scanner.backend}` : ""}</p></div>
      <div className="actions"><button className="button" onClick={() => void refreshStatus()} disabled={scanning}>{_("Refresh status")}</button><button className="button" onClick={() => navigate("profiles")}>{_("Manage Profiles")}</button></div>
    </header>
    {notice && <div className={`notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}><strong>{notice.message}</strong>{notice.detail && <details><summary>{_("Details")}</summary><pre className="monospace">{notice.detail}</pre></details>}</div>}

    <section aria-labelledby="scan-profile-title">
      <h2 id="scan-profile-title" className="section-heading">{_("Scan Profile")}</h2>
      <div className="grouped-list scan-profile"><div className="group-row scan-profile-row"><label className="field">{_("Profile")}<select value={profileId} onChange={(event) => {
        if (activeIdRef.current) return;
        const id = event.target.value;
        setProfileId(id);
        const profile = profiles.find((candidate) => candidate.id === id);
        if (profile?.targets.length) replacePaths(profile.targets);
      }} disabled={scanning}><option value="">{_("No Profile (Manual)")}</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile)}</option>)}</select></label><div className="row-copy">{selectedProfile?.description && <p className="row-description">{profileDescription(selectedProfile)}</p>}</div></div></div>
    </section>

    <section aria-labelledby="scan-targets-title">
      <header className="section-header"><div><h2 id="scan-targets-title">{_("Scan Targets")}</h2><p>{_("Drop local files or folders here, or add them below.")}</p></div><div className="actions scan-target-actions"><button className="button icon-button" title={_("Add Files")} aria-label={_("Add Files")} onClick={() => void choosePaths(false)} disabled={scanning}><Icon name="file" /></button><button className="button icon-button" title={_("Add Folders")} aria-label={_("Add Folders")} onClick={() => void choosePaths(true)} disabled={scanning}><Icon name="folder" /></button>{paths.length > 0 && <button className="button danger icon-button" title={_("Clear All")} aria-label={_("Clear All")} onClick={() => setPaths([])} disabled={scanning}><Icon name="trash" /></button>}</div></header>
      <div className="grouped-list scan-targets target-list">{paths.length === 0 ? <p className="empty-state">{_("No targets added")}</p> : paths.map((path) => <div className="group-row target-row" key={path}><code className="path-value">{path}</code><button className="button danger icon-button" title={_("Remove")} aria-label={_("Remove")} onClick={() => setPaths((current) => current.filter((candidate) => candidate !== path))} disabled={scanning}><Icon name="trash" /></button></div>)}</div>
    </section>

    {scanning && <section className="scan-progress grouped-list" aria-labelledby="scan-progress-title"><div className="group-row"><div className="row-copy"><h2 id="scan-progress-title" className="row-title">{_("Scanning")}</h2>{showLiveProgress ? <><p className="row-description path-value">{progress.current_file || _("Waiting for scan data…")}</p>{scanPercent === null ? <progress className="progress" aria-label={_("Scan progress")} /> : <progress className="progress" value={scanPercent} max="100" aria-label={_("Scan progress")}>{scanPercent}</progress>}<p className="muted inline-metadata"><span className="metadata-item">{ngettext("{count} file scanned", "{count} files scanned", filesScanned, { count: filesScanned })}</span><span className="metadata-item">{ngettext("{count} threat", "{count} threats", progress.infected_count ?? liveThreats.length, { count: progress.infected_count ?? liveThreats.length })}</span></p>{progress.estimate_exceeded && <p className="warning">{_("Estimated file count exceeded")}</p>}{liveThreats.length > 0 && <ul className="summary-list">{liveThreats.slice(-10).map((threat, index) => <li key={`${threat.file_path}-${index}`}><strong>{threat.threat_name}</strong><span className="path-value">{threat.file_path}</span></li>)}</ul>}</> : <p className="row-description">{_("Live progress is disabled. The completed scan result will remain available.")}</p>}</div><button className="button danger" onClick={() => void cancel()}>{paths.length > 1 ? _("Cancel All") : _("Cancel")}</button></div></section>}

    <div className="actions scan-actions"><button className="button primary icon-button" title={scanning ? _("Scanning…") : _("Start Scan")} aria-label={scanning ? _("Scanning…") : _("Start Scan")} onClick={() => void startScan()} disabled={scanning || paths.length === 0}><Icon name="play" /></button><button className="button icon-button" title={_("Run EICAR Test")} aria-label={_("Run EICAR Test")} onClick={() => void runEicar()} disabled={scanning}><Icon name="shield" /></button><button className="button icon-button" title={_("Scan with VirusTotal")} aria-label={_("Scan with VirusTotal")} onClick={() => { if (paths[0]) setVtPath(paths[0]); else setNotice({ kind: "warning", message: _("Select one file before using VirusTotal") }); }} disabled={scanning || paths.length === 0}><Icon name="upload" /></button></div>

    {result && <><section className="scan-result-summary grouped-list" aria-labelledby="latest-scan-title"><div className="group-row"><div className="row-copy"><div className="row"><strong id="latest-scan-title">{_("Latest scan")}</strong><span className={`status-badge ${resultStatus}`}>{scanStatusLabel(result.status)}</span></div><p className="row-description inline-metadata"><span className="metadata-item">{ngettext("{count} file scanned", "{count} files scanned", result.scanned_files ?? 0, { count: result.scanned_files ?? 0 })}</span><span className="metadata-item">{ngettext("{count} threat", "{count} threats", result.infected_count ?? result.threat_details?.length ?? 0, { count: result.infected_count ?? result.threat_details?.length ?? 0 })}</span></p></div><div className="actions"><button className="button" onClick={() => navigate("results", { result })}>{_("View Results")}</button></div></div></section>{detailChunks.length > 0 && <details className="scan-details" onToggle={(event) => setDetailsOpen(event.currentTarget.open)}><summary>{_("Details")}</summary>{detailsOpen && <><div className="actions"><button className="button" onClick={() => void copyDetails(result)}><Icon name="copy" />{_("Copy")}</button><button className="button" onClick={() => setFullscreenDetails(true)}><Icon name="expand" />{_("Fullscreen")}</button></div><ScanLogViewport chunks={detailChunks} label={_("Scan details")} /></>}</details>}</>}

    {missingDatabase && <Modal title={_("Virus database is not available")} onClose={() => setMissingDatabase(false)}><p>{scanner?.database_error || scanner?.error || _("Update the database before starting a scan.")}</p><div className="dialog-actions"><button className="button primary" onClick={() => { setMissingDatabase(false); navigate("database"); }}>{_("Open Database Updates")}</button><button className="button" onClick={() => setMissingDatabase(false)}>{_("Cancel")}</button></div></Modal>}
    {vtPath && <VirusTotalDialog path={vtPath} onClose={() => setVtPath(null)} />}
    {fullscreenDetails && result && detailChunks.length > 0 && <Modal title={_("Scan details")} onClose={() => setFullscreenDetails(false)} className="fullscreen-log"><div className="dialog-actions"><button className="button" onClick={() => void copyDetails(result)}><Icon name="copy" />{_("Copy")}</button></div><ScanLogViewport chunks={detailChunks} label={_("Scan details")} /></Modal>}
  </section>;
}
