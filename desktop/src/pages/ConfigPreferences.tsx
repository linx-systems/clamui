import { useCallback, useEffect, useMemo, useState } from "react";

import { notify, openExternal, openPaths, request } from "../api";
import { _ } from "../i18n";

type ConfigKind = "freshclam" | "clamd";
type ConfigValues = Record<string, string[]>;

type ConfigDocument = {
  kind: ConfigKind;
  path: string;
  baselinePath: string;
  values: ConfigValues;
  baseline: ConfigValues;
  needsSizeUnitMigration: boolean;
  readable: boolean;
  error?: string;
};

type LoadResult = {
  kind?: ConfigKind;
  path?: string;
  values?: ConfigValues;
  needs_size_unit_migration?: boolean;
  readable?: boolean;
  error?: string;
};

type DetectResult = {
  path?: string;
  exists?: boolean;
  readable?: boolean;
  error?: string;
};

type ScannerStatus = {
  available: boolean;
  backend: "daemon" | "clamscan" | "unavailable";
  configured_backend: "auto" | "daemon" | "clamscan";
  daemon_status: {
    available: boolean;
    connected: boolean;
    clamdscan_available: boolean;
    message?: string;
  };
};

type Schedule = {
  scheduled_scans_enabled: boolean;
  schedule_frequency: "hourly" | "daily" | "weekly" | "monthly";
  schedule_time: string;
  schedule_targets: string[];
  schedule_skip_on_battery: boolean;
  schedule_auto_quarantine: boolean;
  schedule_day_of_week: number;
  schedule_day_of_month: number;
};

type ApplyResult = {
  status: "applied" | "partially_applied" | "failed" | "no_changes";
  durable_groups?: string[];
  failures?: Array<{ group: string; message: string; path?: string }>;
  configs?: Array<{ kind: ConfigKind; path: string; changed: boolean; written: boolean; error?: string }>;
  schedule?: { success?: boolean; written?: boolean; error?: string };
  config_paths?: { changed: boolean; durable: boolean; durable_keys: string[] };
};

type ReportTone = "success" | "warning" | "error" | "info";
type SaveReport = { tone: ReportTone; text: string } | null;

const EMPTY_VALUES: ConfigValues = {};
const DAY_LABELS = [
  () => _("Monday"),
  () => _("Tuesday"),
  () => _("Wednesday"),
  () => _("Thursday"),
  () => _("Friday"),
  () => _("Saturday"),
  () => _("Sunday"),
] as const;
const FREQUENCY_LABELS: Record<Schedule["schedule_frequency"], () => string> = {
  hourly: () => _("Hourly"),
  daily: () => _("Daily"),
  weekly: () => _("Weekly"),
  monthly: () => _("Monthly"),
};
const FREQUENCIES: Schedule["schedule_frequency"][] = ["hourly", "daily", "weekly", "monthly"];
const FILE_TYPE_FIELDS = ["ScanPE", "ScanELF", "ScanOLE2", "ScanPDF", "ScanHTML", "ScanArchive"] as const;
const SCANNER_BOOLEAN_FIELDS = ["LogVerbose", "LogSyslog"] as const;
const ONACCESS_BOOLEAN_FIELDS = [
  "OnAccessPrevention",
  "OnAccessExtraScanning",
  "OnAccessDenyOnError",
  "OnAccessDisableDDD",
  "OnAccessExcludeRootUID",
] as const;

const SUGGESTED_SIGNATURE_URLS = [
  "https://urlhaus.abuse.ch/downloads/urlhaus.ndb",
  "http://sigs.interserver.net/interserver256.hdb",
  "http://sigs.interserver.net/interservertopline.db",
  "http://sigs.interserver.net/shell.ldb",
] as const;

const defaultSchedule = (): Schedule => ({
  scheduled_scans_enabled: false,
  schedule_frequency: "weekly",
  schedule_time: "02:00",
  schedule_targets: [],
  schedule_skip_on_battery: true,
  schedule_auto_quarantine: false,
  schedule_day_of_week: 0,
  schedule_day_of_month: 1,
});

function cloneValues(values: ConfigValues): ConfigValues {
  return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, [...value]]));
}

function valuesEqual(left: ConfigValues, right: ConfigValues): boolean {
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  return leftKeys.length === rightKeys.length && leftKeys.every((key, index) =>
    key === rightKeys[index] && left[key].length === right[key].length && left[key].every((value, valueIndex) => value === right[key][valueIndex]),
  );
}

function schedulesEqual(left: Schedule, right: Schedule): boolean {
  return left.scheduled_scans_enabled === right.scheduled_scans_enabled
    && left.schedule_frequency === right.schedule_frequency
    && left.schedule_time === right.schedule_time
    && left.schedule_skip_on_battery === right.schedule_skip_on_battery
    && left.schedule_auto_quarantine === right.schedule_auto_quarantine
    && left.schedule_day_of_week === right.schedule_day_of_week
    && left.schedule_day_of_month === right.schedule_day_of_month
    && left.schedule_targets.length === right.schedule_targets.length
    && left.schedule_targets.every((target, index) => target === right.schedule_targets[index]);
}

function value(values: ConfigValues, key: string, fallback = ""): string {
  return values[key]?.[0] ?? fallback;
}

function enabled(values: ConfigValues, key: string, fallback = false): boolean {
  const configured = value(values, key);
  if (!configured) return fallback;
  return configured.toLowerCase() === "yes" || configured.toLowerCase() === "true" || configured === "1";
}

function valuesForSingle(values: ConfigValues, key: string, next: string): ConfigValues {
  const copied = cloneValues(values);
  if (next.trim()) copied[key] = [next];
  else delete copied[key];
  return copied;
}

function valuesForMany(values: ConfigValues, key: string, next: string[]): ConfigValues {
  const copied = cloneValues(values);
  if (next.length) copied[key] = next;
  else delete copied[key];
  return copied;
}

function numberValue(values: ConfigValues, key: string, fallback: number): number {
  const parsed = Number.parseInt(value(values, key), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function sizeMbValue(values: ConfigValues, key: string): number {
  const raw = value(values, key).trim();
  if (!raw) return 0;
  if (/^\d+$/.test(raw)) return Number(raw);
  const match = /^(\d+)\s*([KMG])$/i.exec(raw);
  if (!match) return 0;
  const multiplier = match[2].toUpperCase() === "G" ? 1024 : match[2].toUpperCase() === "M" ? 1 : 1 / 1024;
  return Math.ceil(Number(match[1]) * multiplier);
}

function fieldId(key: string): string {
  return `config-${key.replaceAll(/[^a-zA-Z0-9]+/g, "-").toLowerCase()}`;
}

function ConfigLocation({
  label,
  kind,
  document,
  onDetect,
  onBrowse,
  onAuthorize,
}: {
  label: string;
  kind: ConfigKind;
  document: ConfigDocument | null;
  onDetect: (kind: ConfigKind) => Promise<void>;
  onBrowse: (kind: ConfigKind) => Promise<void>;
  onAuthorize: (kind: ConfigKind) => Promise<void>;
}) {
  const description = document?.path || _("No configuration file selected");
  return <section className="preference-section form-section config-path-row">
    <div className="setting-row">
      <div className="row-copy">
        <h3 className="section-heading">{label}</h3>
        <p className="muted monospace">{description}</p>
        {document?.error && <p className="warning">{document.error}</p>}
        {document && !document.readable && !document.error && <p className="warning">{_("The file is not currently readable.")}</p>}
      </div>
      <div className="toolbar actions">
        <button className="button" type="button" onClick={() => void onDetect(kind)}>{_("Detect")}</button>
        <button className="button" type="button" onClick={() => void onBrowse(kind)}>{_("Browse")}</button>
        {document?.path && <button className="button" type="button" onClick={() => void onAuthorize(kind)}>{_("Authorize read")}</button>}
      </div>
    </div>
    <p className="muted">{_(
      // Translators: Save & Apply and Authorize read are button labels; use their translations.
      "Selecting a file keeps the path in this pending proposal. Save & Apply persists it only after the complete proposal is valid. Authorization is requested only when you explicitly choose Authorize read.",
    )}</p>
  </section>;
}

function TextField({ label, field, value: currentValue, onChange, type = "text", placeholder }: {
  label: string;
  field: string;
  value: string;
  onChange: (next: string) => void;
  type?: "text" | "password" | "url" | "time";
  placeholder?: string;
}) {
  const id = fieldId(field);
  return <label className="field field-control" htmlFor={id}>
    <span>{label}</span>
    <input id={id} type={type} value={currentValue} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
  </label>;
}

function NumberField({ label, field, value: currentValue, min, max, onChange, note }: {
  label: string;
  field: string;
  value: number;
  min: number;
  max: number;
  onChange: (next: number) => void;
  note?: string;
}) {
  const id = fieldId(field);
  return <label className="field field-control" htmlFor={id}>
    <span>{label}</span>
    <input id={id} type="number" min={min} max={max} step="1" value={currentValue} onChange={(event) => onChange(Number(event.target.value))} />
    {note && <small className="muted">{note}</small>}
  </label>;
}

function BooleanField({ label, field, checked, onChange, note }: {
  label: string;
  field: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  note?: string;
}) {
  const id = fieldId(field);
  return <label className="preference-row setting-row switch-control" htmlFor={id}>
    <span className="row-copy"><strong>{label}</strong>{note && <small className="muted">{note}</small>}</span>
    <input id={id} type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
  </label>;
}


function StringListField({ label, field, values, onChange, placeholder }: {
  label: string;
  field: string;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");
  const id = fieldId(field);
  const add = () => {
    const candidates = draft.split(",").map((candidate) => candidate.trim()).filter(Boolean);
    if (candidates.length === 0) return;
    onChange([...values, ...candidates.filter((candidate) => !values.includes(candidate))]);
    setDraft("");
  };
  return <div className="form-grid">
    <label className="field field-control" htmlFor={id}>{label}</label>
    <div className="inline-form">
      <input id={id} value={draft} placeholder={placeholder} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          add();
        }
      }} />
      <button className="button" type="button" onClick={add}>{_("Add")}</button>
    </div>
    {values.length > 0 && <ul className="table">
      {values.map((item) => <li className="row setting-row" key={item}>
        <code className="monospace">{item}</code>
        <button className="button danger" type="button" onClick={() => onChange(values.filter((valueItem) => valueItem !== item))}>{_("Remove")}</button>
      </li>)}
    </ul>}
  </div>;
}

function parseCustomUrls(raw: string): string[] {
  const allowedSchemes = ["http://", "https://", "ftp://", "ftps://", "file://"];
  const parsed: string[] = [];
  for (const line of raw.split("\n")) {
    let candidate = line.trim();
    if (!candidate || candidate.startsWith("#")) continue;
    if (candidate.toLowerCase().startsWith("databasecustomurl")) {
      candidate = candidate.slice("DatabaseCustomURL".length).trim();
    }
    if (allowedSchemes.some((scheme) => candidate.toLowerCase().startsWith(scheme))) {
      parsed.push(candidate);
    }
  }
  return parsed;
}

function CustomUrlListField({ values, onChange }: { values: string[]; onChange: (next: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const candidates = parseCustomUrls(draft);
    if (candidates.length === 0) {
      notify(
        _(
          // Translators: Keep the URI schemes unchanged.
          "Enter an http, https, ftp, ftps, or file URL.",
        ),
        "warning",
      );
      return;
    }
    onChange([...values, ...candidates.filter((candidate) => !values.includes(candidate))]);
    setDraft("");
  };
  return <div className="form-grid">
    <label className="field field-control" htmlFor="config-databasecustomurl">{_("Add URLs")}</label>
    <textarea id="config-databasecustomurl" value={draft} rows={3} placeholder={"DatabaseCustomURL https://example.invalid/signatures.ndb"} onChange={(event) => setDraft(event.target.value)} />
    <div className="toolbar actions"><button className="button" type="button" onClick={add}>{_("Add")}</button></div>
    {values.length > 0 && <ul className="table">
      {values.map((item) => <li className="row setting-row" key={item}>
        <code className="monospace">{item}</code>
        <button className="button danger" type="button" onClick={() => onChange(values.filter((valueItem) => valueItem !== item))}>{_("Remove")}</button>
      </li>)}
    </ul>}
  </div>;
}

export default function ConfigPreferences({ section }: { section: string }) {
  const [freshclam, setFreshclam] = useState<ConfigDocument | null>(null);
  const [clamd, setClamd] = useState<ConfigDocument | null>(null);
  const [scanner, setScanner] = useState<ScannerStatus | null>(null);
  const [backend, setBackend] = useState<ScannerStatus["configured_backend"]>("auto");
  const [schedule, setSchedule] = useState<Schedule>(defaultSchedule);
  const [scheduleBaseline, setScheduleBaseline] = useState<Schedule>(defaultSchedule);
  const [report, setReport] = useState<SaveReport>(null);
  const [busy, setBusy] = useState(false);

  const loadConfig = useCallback(async (kind: ConfigKind, path?: string, baselinePath?: string) => {
    const loaded = await request<LoadResult>("config.load", path ? { kind, path } : { kind });
    const next: ConfigDocument = {
      kind,
      path: loaded.path ?? path ?? "",
      baselinePath: baselinePath ?? loaded.path ?? path ?? "",
      values: cloneValues(loaded.values ?? EMPTY_VALUES),
      baseline: cloneValues(loaded.values ?? EMPTY_VALUES),
      needsSizeUnitMigration: loaded.needs_size_unit_migration === true,
      readable: loaded.readable ?? false,
      error: loaded.error,
    };
    if (kind === "freshclam") setFreshclam(next);
    else setClamd(next);
    return next;
  }, []);

  const refreshScanner = useCallback(async () => {
    try {
      const status = await request<ScannerStatus>("scanner.status");
      setScanner(status);
      setBackend(status.configured_backend);
    } catch (error) {
      notify(String(error), "error");
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([loadConfig("freshclam"), loadConfig("clamd"), refreshScanner()]);
        const settings = await request<Record<string, unknown>>("settings.get");
        const next = {
          scheduled_scans_enabled: settings.scheduled_scans_enabled === true,
          schedule_frequency: FREQUENCIES.includes(settings.schedule_frequency as Schedule["schedule_frequency"])
            ? settings.schedule_frequency as Schedule["schedule_frequency"] : "weekly",
          schedule_time: typeof settings.schedule_time === "string" ? settings.schedule_time : "02:00",
          schedule_targets: Array.isArray(settings.schedule_targets) ? settings.schedule_targets.filter((item): item is string => typeof item === "string") : [],
          schedule_skip_on_battery: settings.schedule_skip_on_battery !== false,
          schedule_auto_quarantine: settings.schedule_auto_quarantine === true,
          schedule_day_of_week: typeof settings.schedule_day_of_week === "number" ? settings.schedule_day_of_week : 0,
          schedule_day_of_month: typeof settings.schedule_day_of_month === "number" ? settings.schedule_day_of_month : 1,
        } satisfies Schedule;
        setSchedule(next);
        setScheduleBaseline(next);
      } catch (error) {
        notify(String(error), "error");
      }
    })();
  }, [loadConfig, refreshScanner]);

  const selectConfig = useCallback(async (kind: ConfigKind, path: string) => {
    const existing = kind === "freshclam" ? freshclam : clamd;
    await loadConfig(kind, path, existing?.baselinePath ?? "");
    notify(
      _(
        // Translators: Save & Apply is a button label; use its translation.
        "Configuration file selection is pending Save & Apply.",
      ),
      "info",
    );
  }, [clamd, freshclam, loadConfig]);

  const detectConfig = useCallback(async (kind: ConfigKind) => {
    try {
      const detected = await request<DetectResult>("config.detect", { kind });
      if (!detected.path || !detected.exists) {
        notify(detected.error || _("No configuration file was found."), "warning");
        return;
      }
      await selectConfig(kind, detected.path);
    } catch (error) {
      notify(String(error), "error");
    }
  }, [selectConfig]);

  const browseConfig = useCallback(async (kind: ConfigKind) => {
    try {
      const [path] = await openPaths({ multiple: false });
      if (!path) return;
      if (!path.endsWith(".conf")) {
        notify(_("Select a .conf configuration file."), "warning");
        return;
      }
      await selectConfig(kind, path);
    } catch (error) {
      notify(String(error), "error");
    }
  }, [selectConfig]);

  const authorizeRead = useCallback(async (kind: ConfigKind) => {
    const document = kind === "freshclam" ? freshclam : clamd;
    if (!document?.path) return;
    try {
      const loaded = await request<LoadResult>("config.read_authorized", { path: document.path });
      const next: ConfigDocument = {
        kind,
        path: loaded.path ?? document.path,
        baselinePath: document.baselinePath,
        values: cloneValues(loaded.values ?? EMPTY_VALUES),
        baseline: cloneValues(loaded.values ?? EMPTY_VALUES),
        needsSizeUnitMigration: loaded.needs_size_unit_migration === true,
        readable: loaded.readable ?? true,
        error: loaded.error,
      };
      if (kind === "freshclam") setFreshclam(next);
      else setClamd(next);
      notify(_("Configuration loaded with administrator authorization."), "success");
    } catch (error) {
      notify(String(error), "error");
    }
  }, [clamd, freshclam]);

  const updateConfig = useCallback((kind: ConfigKind, updater: (values: ConfigValues) => ConfigValues) => {
    const setDocument = kind === "freshclam" ? setFreshclam : setClamd;
    setDocument((current) => current ? { ...current, values: updater(current.values) } : current);
  }, []);

  const addSuggestedUrls = () => {
    updateConfig("freshclam", (values) => valuesForMany(
      values,
      "DatabaseCustomURL",
      [...(values.DatabaseCustomURL ?? []), ...SUGGESTED_SIGNATURE_URLS.filter((url) => !values.DatabaseCustomURL?.includes(url))],
    ));
  };

  const openReference = async (url: string) => {
    try {
      await openExternal(url);
    } catch (error) {
      notify(`${_("Could not open link")}: ${String(error)}`, "error");
    }
  };

  const saveBackend = useCallback(async (next: ScannerStatus["configured_backend"]) => {
    const previous = backend;
    setBackend(next);
    try {
      await request("settings.update", { scan_backend: next });
      await refreshScanner();
      notify(_("Scan backend saved."), "success");
    } catch (error) {
      setBackend(previous);
      notify(String(error), "error");
    }
  }, [backend, refreshScanner]);

  const saveAndApply = useCallback(async () => {
    const freshclamSnapshot = freshclam && {
      ...freshclam,
      values: cloneValues(freshclam.values),
      baseline: cloneValues(freshclam.baseline),
    };
    const clamdSnapshot = clamd && {
      ...clamd,
      values: cloneValues(clamd.values),
      baseline: cloneValues(clamd.baseline),
    };
    const scheduleSnapshot = { ...schedule, schedule_targets: [...schedule.schedule_targets] };
    const configs = [freshclamSnapshot, clamdSnapshot].filter((document): document is ConfigDocument => Boolean(document && (
      !valuesEqual(document.values, document.baseline)
      || document.path !== document.baselinePath
      || (document.kind === "clamd" && document.needsSizeUnitMigration)
    )));
    const unselected = configs.find((document) => !document.path);
    if (unselected) {
      const message = _("Choose a configuration file before applying its changes.");
      setReport({ tone: "error", text: message });
      notify(message, "error");
      return;
    }
    const onAccessIncluded = (clamdSnapshot?.values.OnAccessIncludePath?.length ?? 0) > 0;
    const hasLoopPrevention = Boolean(
      value(clamdSnapshot?.values ?? EMPTY_VALUES, "OnAccessExcludeUname").trim()
      || value(clamdSnapshot?.values ?? EMPTY_VALUES, "OnAccessExcludeUID").trim()
      || enabled(clamdSnapshot?.values ?? EMPTY_VALUES, "OnAccessExcludeRootUID"),
    );
    if (onAccessIncluded && !hasLoopPrevention) {
      const message = _("On-Access scanning requires an excluded username, UID, or root user to prevent scan loops.");
      setReport({ tone: "error", text: message });
      notify(message, "error");
      return;
    }
    const changedConfigs = configs.map((document) => ({ kind: document.kind, path: document.path, values: document.values }));
    const scheduleChanged = !schedulesEqual(scheduleSnapshot, scheduleBaseline);
    if (changedConfigs.length === 0 && !scheduleChanged) {
      const message = _("No changes to apply.");
      setReport({ tone: "info", text: message });
      notify(message, "info");
      return;
    }

    setBusy(true);
    try {
      for (const config of changedConfigs) {
        const validation = await request<{ valid: boolean; errors: string[] }>("config.validate", { kind: config.kind, values: config.values });
        if (!validation.valid) {
          const message = validation.errors.join("\n") || _("Configuration validation failed.");
          setReport({ tone: "error", text: message });
          notify(message, "error");
          return;
        }
      }

      const result = await request<ApplyResult>("config.apply", {
        configs: changedConfigs,
        ...(scheduleChanged ? { schedule: scheduleSnapshot } : {}),
      });
      const written = new Set((result.configs ?? []).filter((config) => config.written).map((config) => config.kind));
      const persisted = new Set((result.configs ?? [])
        .filter((config) => config.changed && config.written)
        .map((config) => config.kind));
      const durablePathKeys = new Set(result.config_paths?.durable_keys ?? []);
      const freshclamPathDurable = durablePathKeys.has("freshclam_conf_path");
      const clamdPathDurable = durablePathKeys.has("clamd_conf_path");
      if (freshclamSnapshot && (written.has("freshclam") || freshclamPathDurable)) {
        setFreshclam((current) => {
          if (!current) return current;
          const wroteCurrentDocument = written.has("freshclam") && current.path === freshclamSnapshot.path;
          return {
            ...current,
            baselinePath: freshclamPathDurable ? freshclamSnapshot.path : current.baselinePath,
            baseline: wroteCurrentDocument ? cloneValues(freshclamSnapshot.values) : current.baseline,
          };
        });
      }
      if (clamdSnapshot && (written.has("clamd") || clamdPathDurable)) {
        setClamd((current) => {
          if (!current) return current;
          const wroteCurrentDocument = written.has("clamd") && current.path === clamdSnapshot.path;
          const persistedCurrentDocument = persisted.has("clamd") && current.path === clamdSnapshot.path;
          return {
            ...current,
            baselinePath: clamdPathDurable ? clamdSnapshot.path : current.baselinePath,
            baseline: wroteCurrentDocument ? cloneValues(clamdSnapshot.values) : current.baseline,
            needsSizeUnitMigration: persistedCurrentDocument ? false : current.needsSizeUnitMigration,
          };
        });
      }
      const scheduleWritten = result.schedule?.written === true || result.schedule?.success === true
        || (result.durable_groups ?? []).some((group) => group === "scheduled_preferences" || group === "schedule");
      if (scheduleChanged && scheduleWritten) setScheduleBaseline(scheduleSnapshot);

      const durable = (result.durable_groups ?? []).join(", ");
      const explicitFailures = (result.failures ?? []).map((failure) => `${failure.group}: ${failure.message}`);
      const configFailures = (result.configs ?? [])
        .filter((config) => Boolean(config.error))
        .map((config) => `${config.path}: ${config.error}`);
      const failures = [...explicitFailures, ...configFailures, ...(result.schedule?.error ? [`schedule: ${result.schedule.error}`] : [])]
        .filter((failure, index, allFailures) => allFailures.indexOf(failure) === index)
        .join("\n");
      const text = [
        result.status === "applied" ? _("Configuration saved and applied.") : result.status === "no_changes" ? _("No changes to apply.") : _("Some changes could not be applied."),
        durable && `${_("Saved groups")}: ${durable}`,
        failures,
      ].filter(Boolean).join("\n");
      const tone: ReportTone = result.status === "applied" ? "success" : result.status === "no_changes" ? "info" : result.status === "partially_applied" ? "warning" : "error";
      setReport({ tone, text });
      notify(text, tone === "warning" ? "warning" : tone === "error" ? "error" : tone === "success" ? "success" : "info");
    } catch (error) {
      const message = String(error);
      setReport({ tone: "error", text: message });
      notify(message, "error");
    } finally {
      setBusy(false);
    }
  }, [clamd, freshclam, schedule, scheduleBaseline]);

  const scannerSummary = useMemo(() => {
    if (!scanner) return _("Checking scanner status…");
    return scanner.daemon_status.connected
      ? _("Daemon connected")
      : scanner.daemon_status.message || (scanner.available ? _("Scanner available") : _("Scanner unavailable"));
  }, [scanner]);

  const freshclamValues = freshclam?.values ?? EMPTY_VALUES;
  const clamdValues = clamd?.values ?? EMPTY_VALUES;
  const setFreshclamField = (key: string, next: string) => updateConfig("freshclam", (values) => valuesForSingle(values, key, next));
  const setClamdField = (key: string, next: string) => updateConfig("clamd", (values) => valuesForSingle(values, key, next));
  const setClamdMany = (key: string, next: string[]) => updateConfig("clamd", (values) => valuesForMany(values, key, next));

  const fileTypeLabels: Record<(typeof FILE_TYPE_FIELDS)[number], string> = {
    ScanPE: _("Scan PE Files"),
    ScanELF: _("Scan ELF Files"),
    ScanOLE2: _("Scan OLE2 Files"),
    ScanPDF: _("Scan PDF Files"),
    ScanHTML: _("Scan HTML Files"),
    ScanArchive: _("Scan Archive Files"),
  };


  return <div className="settings-preferences">
    {section === "database" && <>
      <h2 className="section-heading">{_("Database Updates")}</h2>
      <ConfigLocation label={_(
        // Translators: Keep freshclam.conf unchanged; it is a configuration file name.
        "freshclam.conf",
      )} kind="freshclam" document={freshclam} onDetect={detectConfig} onBrowse={browseConfig} onAuthorize={authorizeRead} />
      <section className="preference-section form-section"><h3 className="section-heading">{_("Paths")}</h3>
        <TextField label={_("Database Directory")} field="DatabaseDirectory" value={value(freshclamValues, "DatabaseDirectory")} onChange={(next) => setFreshclamField("DatabaseDirectory", next)} />
        <TextField label={_("Update Log File")} field="UpdateLogFile" value={value(freshclamValues, "UpdateLogFile")} onChange={(next) => setFreshclamField("UpdateLogFile", next)} />
        <TextField label={_("PID File")} field="PidFile" value={value(freshclamValues, "PidFile")} onChange={(next) => setFreshclamField("PidFile", next)} />
        <TextField label={_("Notify ClamD Config")} field="NotifyClamd" value={value(freshclamValues, "NotifyClamd")} onChange={(next) => setFreshclamField("NotifyClamd", next)} />
        <BooleanField label={_("Log timestamps")} field="LogTime" checked={enabled(freshclamValues, "LogTime")} onChange={(next) => setFreshclamField("LogTime", next ? "yes" : "no")} />
        <BooleanField label={_("Verbose logging")} field="freshclam-LogVerbose" checked={enabled(freshclamValues, "LogVerbose")} onChange={(next) => setFreshclamField("LogVerbose", next ? "yes" : "no")} />
        <BooleanField label={_("Syslog logging")} field="freshclam-LogSyslog" checked={enabled(freshclamValues, "LogSyslog")} onChange={(next) => setFreshclamField("LogSyslog", next ? "yes" : "no")} />
      </section>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Update Behavior")}</h3>
        <NumberField label={_("Checks per day")} field="Checks" value={numberValue(freshclamValues, "Checks", 0)} min={0} max={50} note={_("0 disables automatic checks.")} onChange={(next) => setFreshclamField("Checks", String(next))} />
        <TextField label={_("Database Mirror")} field="DatabaseMirror" value={value(freshclamValues, "DatabaseMirror")} onChange={(next) => setFreshclamField("DatabaseMirror", next)} />
      </section>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Custom Signature Databases")}</h3>
        <CustomUrlListField values={freshclamValues.DatabaseCustomURL ?? []} onChange={(next) => updateConfig("freshclam", (values) => valuesForMany(values, "DatabaseCustomURL", next))} />
        <div className="toolbar actions"><button className="button" type="button" onClick={addSuggestedUrls}>{_("Suggested")}</button></div>
        <p className="muted">{_(
          // Translators: Suggested and Save & Apply are button labels; use their translations. Keep URLhaus and InterServer unchanged.
          "Suggested adds URLhaus and three InterServer databases to this draft. Save & Apply is still required.",
        )}</p>
        <p className="muted">{_(
          // Translators: Keep the URI schemes unchanged.
          "Supported URL schemes: http, https, ftp, ftps, and file. Paste each provider URL as a separate entry.",
        )}</p>
      </section>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Signature Providers")}</h3>
        <div className="setting-row"><span className="row-copy"><strong>URLhaus</strong><small className="muted">{_("Free malware URL blocklist; no registration required.")}</small></span><button className="button" type="button" onClick={() => void openReference("https://urlhaus.abuse.ch/api/")}>{_("Open provider")}</button></div>
        <div className="setting-row"><span className="row-copy"><strong>SecuriteInfo</strong><small className="muted">{_("Registration is required; URLs include your personal API key.")}</small></span><button className="button" type="button" onClick={() => void openReference("https://www.securiteinfo.com/")}>{_("Open provider")}</button></div>
        <div className="setting-row"><span className="row-copy"><strong>SaneSecurity</strong><small className="muted">{_(
          // Translators: Keep fangfrisch and clamav-unofficial-sigs unchanged; they are tool names.
          "Use fangfrisch or clamav-unofficial-sigs; it is not a direct custom URL provider.",
        )}</small></span><button className="button" type="button" onClick={() => void openReference("https://sanesecurity.com/")}>{_("Open provider")}</button></div>
        <div className="setting-row"><span className="row-copy"><strong>InterServer</strong><small className="muted">{_("Community hash, web-shell, and general malware signature databases.")}</small></span><button className="button" type="button" onClick={() => void openReference("http://sigs.interserver.net/")}>{_("Open provider")}</button></div>
      </section>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Proxy Settings")}</h3>
        <TextField label={_("Proxy Server")} field="HTTPProxyServer" value={value(freshclamValues, "HTTPProxyServer")} onChange={(next) => setFreshclamField("HTTPProxyServer", next)} />
        <NumberField label={_("Proxy Port")} field="HTTPProxyPort" value={numberValue(freshclamValues, "HTTPProxyPort", 0)} min={0} max={65535} note={_("0 disables the proxy port.")} onChange={(next) => setFreshclamField("HTTPProxyPort", String(next))} />
        <TextField label={_("Proxy Username")} field="HTTPProxyUsername" value={value(freshclamValues, "HTTPProxyUsername")} onChange={(next) => setFreshclamField("HTTPProxyUsername", next)} />
        <TextField label={_("Proxy Password")} field="HTTPProxyPassword" type="password" value={value(freshclamValues, "HTTPProxyPassword")} onChange={(next) => setFreshclamField("HTTPProxyPassword", next)} />
      </section>
    </>}

    {section === "scanner" && <>
      <h2 className="section-heading">{_("Scanner Settings")}</h2>
      <section className="preference-section form-section">
        <label className="field field-control" htmlFor="config-scan-backend"><span>{_("Scan Backend")}</span><select id="config-scan-backend" value={backend} onChange={(event) => void saveBackend(event.target.value as ScannerStatus["configured_backend"])}><option value="auto">{_("Auto (prefer daemon)")}</option><option value="daemon">{_(
          // Translators: Keep clamd unchanged; it is the daemon command and service name.
          "ClamAV Daemon (clamd)",
        )}</option><option value="clamscan">{_(
          // Translators: Keep clamscan unchanged; it is the scanner command name.
          "Standalone Scanner (clamscan)",
        )}</option></select></label>
        <div className="setting-row"><span className="row-copy"><strong>{_("Daemon Status")}</strong><small className="muted">{scannerSummary}</small></span><button className="button" type="button" onClick={() => void refreshScanner()}>{_("Refresh Status")}</button></div>
        <button className="button" type="button" onClick={() => void openReference("https://clamui.com/docs/reference/scan-backends/")}>{_("Documentation")}</button>
      </section>
      <ConfigLocation label={_(
        // Translators: Keep clamd.conf unchanged; it is a configuration file name.
        "clamd.conf",
      )} kind="clamd" document={clamd} onDetect={detectConfig} onBrowse={browseConfig} onAuthorize={authorizeRead} />
      <section className="preference-section form-section"><h3 className="section-heading">{_("File Type Scanning")}</h3>
        {FILE_TYPE_FIELDS.map((key) => <BooleanField key={key} label={fileTypeLabels[key]} field={key} checked={enabled(clamdValues, key, true)} onChange={(next) => setClamdField(key, next ? "yes" : "no")} />)}
      </section>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Performance and Limits")}</h3>
        <NumberField label={_("Max File Size (MB)")} field="MaxFileSize" value={sizeMbValue(clamdValues, "MaxFileSize")} min={0} max={4000} note={_("0 means unlimited.")} onChange={(next) => setClamdField("MaxFileSize", next === 0 ? "0" : `${next}M`)} />
        <NumberField label={_("Max Scan Size (MB)")} field="MaxScanSize" value={sizeMbValue(clamdValues, "MaxScanSize")} min={0} max={4000} note={_("0 means unlimited.")} onChange={(next) => setClamdField("MaxScanSize", next === 0 ? "0" : `${next}M`)} />
        <NumberField label={_("Max Archive Recursion")} field="MaxRecursion" value={numberValue(clamdValues, "MaxRecursion", 17)} min={1} max={100} onChange={(next) => setClamdField("MaxRecursion", String(next))} />
        <NumberField label={_("Max Files in Archive")} field="MaxFiles" value={numberValue(clamdValues, "MaxFiles", 0)} min={0} max={1000000} note={_("0 means unlimited.")} onChange={(next) => setClamdField("MaxFiles", String(next))} />
      </section>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Logging")}</h3>
        <TextField label={_("Log File Path")} field="clamd-LogFile" value={value(clamdValues, "LogFile")} onChange={(next) => setClamdField("LogFile", next)} />
        {SCANNER_BOOLEAN_FIELDS.map((key) => <BooleanField key={key} label={key === "LogVerbose" ? _("Verbose Logging") : _("Syslog Logging")} field={`clamd-${key}`} checked={enabled(clamdValues, key)} onChange={(next) => setClamdField(key, next ? "yes" : "no")} />)}
      </section>
    </>}

    {section === "onaccess" && <>
      <h2 className="section-heading">{_("On-Access Scanning")}</h2>
      <ConfigLocation label={_(
        // Translators: Keep clamd.conf unchanged; it is a configuration file name.
        "clamd.conf",
      )} kind="clamd" document={clamd} onDetect={detectConfig} onBrowse={browseConfig} onAuthorize={authorizeRead} />
      <section className="preference-section form-section"><h3 className="section-heading">{_("Monitored Paths")}</h3>
        <StringListField label={_("Include Paths")} field="OnAccessIncludePath" values={clamdValues.OnAccessIncludePath ?? []} placeholder="/home" onChange={(next) => setClamdMany("OnAccessIncludePath", next)} />
        <StringListField label={_("Exclude Paths")} field="OnAccessExcludePath" values={clamdValues.OnAccessExcludePath ?? []} placeholder="/proc" onChange={(next) => setClamdMany("OnAccessExcludePath", next)} />
      </section>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Behavior Settings")}</h3>
        {ONACCESS_BOOLEAN_FIELDS.slice(0, 4).map((key) => <BooleanField key={key} label={key === "OnAccessPrevention" ? _("Prevention Mode") : key === "OnAccessExtraScanning" ? _("Extra Scanning") : key === "OnAccessDenyOnError" ? _("Deny on Error") : _("Disable DDD")} field={key} checked={enabled(clamdValues, key)} onChange={(next) => setClamdField(key, next ? "yes" : "no")} />)}
      </section>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Performance Settings")}</h3>
        <NumberField label={_("Max Threads")} field="OnAccessMaxThreads" value={numberValue(clamdValues, "OnAccessMaxThreads", 1)} min={1} max={64} onChange={(next) => setClamdField("OnAccessMaxThreads", String(next))} />
        <NumberField label={_("Max File Size (MB)")} field="OnAccessMaxFileSize" value={numberValue(clamdValues, "OnAccessMaxFileSize", 0)} min={0} max={4000} note={_("0 means unlimited.")} onChange={(next) => setClamdField("OnAccessMaxFileSize", String(next))} />
        <NumberField label={_("Curl Timeout (seconds)")} field="OnAccessCurlTimeout" value={numberValue(clamdValues, "OnAccessCurlTimeout", 0)} min={0} max={3600} note={_("0 disables the timeout.")} onChange={(next) => setClamdField("OnAccessCurlTimeout", String(next))} />
        <NumberField label={_("Retry Attempts")} field="OnAccessRetryAttempts" value={numberValue(clamdValues, "OnAccessRetryAttempts", 0)} min={0} max={10} onChange={(next) => setClamdField("OnAccessRetryAttempts", String(next))} />
      </section>
      <section className="preference-section form-section warning"><h3 className="section-heading">{_("Scan Loop Prevention")}</h3>
        <p>{_("At least one loop-prevention exclusion is required. Exclude the clamav service account, its UID, or root to prevent recursive scans.")}</p>
        <TextField label={_("Exclude Username")} field="OnAccessExcludeUname" value={value(clamdValues, "OnAccessExcludeUname")} onChange={(next) => setClamdField("OnAccessExcludeUname", next)} />
        <NumberField label={_("Exclude User ID")} field="OnAccessExcludeUID" value={numberValue(clamdValues, "OnAccessExcludeUID", 0)} min={0} max={65534} onChange={(next) => setClamdField("OnAccessExcludeUID", String(next))} />
        <BooleanField label={_("Exclude Root User")} field="OnAccessExcludeRootUID" checked={enabled(clamdValues, "OnAccessExcludeRootUID")} onChange={(next) => setClamdField("OnAccessExcludeRootUID", next ? "yes" : "no")} />
      </section>
    </>}

    {section === "scheduled" && <>
      <h2 className="section-heading">{_("Scheduled Scans")}</h2>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Schedule")}</h3>
        <BooleanField label={_("Enable Scheduled Scans")} field="scheduled_scans_enabled" checked={schedule.scheduled_scans_enabled} onChange={(next) => setSchedule((current) => ({ ...current, scheduled_scans_enabled: next }))} />
        <label className="field field-control" htmlFor="config-schedule-frequency"><span>{_("Scan Frequency")}</span><select id="config-schedule-frequency" value={schedule.schedule_frequency} onChange={(event) => setSchedule((current) => ({ ...current, schedule_frequency: event.target.value as Schedule["schedule_frequency"] }))}>{FREQUENCIES.map((frequency) => <option key={frequency} value={frequency}>{FREQUENCY_LABELS[frequency]()}</option>)}</select></label>
        <TextField label={_("Scan Time (24-hour)")} field="schedule_time" type="time" value={schedule.schedule_time} onChange={(next) => setSchedule((current) => ({ ...current, schedule_time: next }))} />
        <label className="field field-control" htmlFor="config-schedule-day-of-week"><span>{_("Day of Week")}</span><select id="config-schedule-day-of-week" value={schedule.schedule_day_of_week} onChange={(event) => setSchedule((current) => ({ ...current, schedule_day_of_week: Number(event.target.value) }))}>{DAY_LABELS.map((label, index) => <option key={index} value={index}>{label()}</option>)}</select><small className="muted">{_("Used for weekly scans.")}</small></label>
        <NumberField label={_("Day of Month")} field="schedule_day_of_month" value={schedule.schedule_day_of_month} min={1} max={28} note={_("Used for monthly scans.")} onChange={(next) => setSchedule((current) => ({ ...current, schedule_day_of_month: next }))} />
        <StringListField label={_("Scan Targets")} field="schedule_targets" values={schedule.schedule_targets} placeholder="/home/user" onChange={(next) => setSchedule((current) => ({ ...current, schedule_targets: next }))} />
        {schedule.schedule_targets.length === 0 && <p className="muted">{_("No targets are configured. The scheduled scan will use your home directory without saving it as an explicit target.")}</p>}
        <BooleanField label={_("Skip on Battery")} field="schedule_skip_on_battery" checked={schedule.schedule_skip_on_battery} note={_("Do not start scheduled scans while on battery power.")} onChange={(next) => setSchedule((current) => ({ ...current, schedule_skip_on_battery: next }))} />
        <BooleanField label={_("Auto-Quarantine")} field="schedule_auto_quarantine" checked={schedule.schedule_auto_quarantine} note={_("Automatically quarantine threats found by scheduled scans.")} onChange={(next) => setSchedule((current) => ({ ...current, schedule_auto_quarantine: next }))} />
      </section>
    </>}

    {section === "save" && <>
      <h2 className="section-heading">{_("Save & Apply")}</h2>
      <section className="preference-section form-section"><h3 className="section-heading">{_("Apply Configuration")}</h3>
        <p>{_(
          // Translators: Save & Apply is a button label; use its translation.
          "All edited forms are captured at the moment you click Save & Apply. Every configured file is validated before any write or authorization request.",
        )}</p>
        <p className="muted">{_(
          // Translators: Keep clamd.conf unchanged; it is a configuration file name.
          "Scanner and On-Access changes share one clamd.conf proposal; neither form can overwrite the other's detached changes.",
        )}</p>
        <button className="button primary" type="button" disabled={busy} onClick={() => void saveAndApply()}>{busy ? _("Saving…") : _("Save & Apply")}</button>
      </section>
      {report && <section className={`notice ${report.tone}`} aria-live="polite"><pre>{report.text}</pre></section>}
    </>}
  </div>;
}
