import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { copyText, notify, openExternal, openPath, openPaths, request, saveBinary } from "../api";
import { _, activeCatalog, ngettext } from "../i18n";
import { Icon } from "../Icon";
import { Modal } from "../Modal";
type Settings = Record<string, unknown>;
type SaveSetting = (key: string, value: unknown) => Promise<boolean>;
type Integration = {
  file_manager: "nemo" | "nautilus" | "dolphin";
  display_name: string;
  description: string;
  status: "installed" | "partial" | "not_installed";
  is_available: boolean;
  missing_files: string[];
};
type KeyStatus = {
  present: boolean;
  backend: "keyring" | "plaintext_fallback" | "none";
  status: "configured" | "not_configured" | "locked" | "unavailable";
  masked?: string;
  message?: string;
};
type DebugInfo = { log_dir: string; total_bytes: number; file_count: number; files: string[]; level: string };
type Exclusion = { pattern: string; type: "directory" | "file" | "pattern"; enabled: boolean };
type SystemInfo = {
  installation_type: string;
  distribution: string;
  desktop_environment: string;
  platform: string;
  architecture: string;
  is_flatpak: boolean;
  app_version: string;
  rust_runtime: string;
  tauri_runtime?: string;
};

type SettingsPreferencesProps = {
  selectedPage?: string;
  settings?: Settings;
  saveSetting?: SaveSetting;
  trayAvailable?: boolean;
  isFlatpak?: boolean;
};

const PRESETS: Array<{ pattern: string; description: () => string }> = [
  { pattern: "node_modules", description: () => _("Node.js dependencies") },
  { pattern: ".git", description: () => _("Git repository data") },
  { pattern: ".venv", description: () => _("Python virtual environment") },
  { pattern: "build", description: () => _("Build output directory") },
  { pattern: "dist", description: () => _("Distribution output directory") },
  { pattern: "__pycache__", description: () => _("Python bytecode cache") },
];
const PRESET_PATTERNS: Record<string, true> = Object.fromEntries(PRESETS.map(({ pattern }) => [pattern, true]));
const LANGUAGE_FALLBACK = [
  { code: "de", name: "Deutsch" },
  { code: "en", name: "English" },
  { code: "es", name: "Español" },
  { code: "fr", name: "Français" },
  { code: "hu", name: "Magyar" },
  { code: "it", name: "Italiano" },
  { code: "nb", name: "Norsk bokmål" },
  { code: "pt_BR", name: "Português (Brasil)" },
  { code: "zh_CN", name: "简体中文" },
];
const CLOSE_BEHAVIOR = ["minimize", "quit", "ask"] as const;
const DEVICE_TYPES = [
  { id: "removable", label: () => _("Removable Devices"), detail: () => _("USB flash drives, SD cards, and removable media") },
  { id: "external", label: () => _("External Drives"), detail: () => _("Ejectable external HDDs and SSDs") },
  { id: "network", label: () => _("Network Mounts"), detail: () => _("NFS, SMB/CIFS, and SSHFS mounts") },
  { id: "internal", label: () => _("Internal Volumes"), detail: () => _("Non-removable local storage") },
];

function valueString(settings: Settings, key: string, fallback: string): string {
  return typeof settings[key] === "string" ? settings[key] as string : fallback;
}

function valueBoolean(settings: Settings, key: string, fallback: boolean): boolean {
  return typeof settings[key] === "boolean" ? settings[key] as boolean : fallback;
}

function valueNumber(settings: Settings, key: string, fallback: number): number {
  return typeof settings[key] === "number" && Number.isFinite(settings[key]) ? settings[key] as number : fallback;
}

function formatBytes(value: number): string {
  if (value < 1024) return ngettext("{count} byte", "{count} bytes", value);
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function normalizedExclusions(value: unknown): Exclusion[] {
  const normalized: Exclusion[] = [];
  const known: Record<string, true> = {};
  if (Array.isArray(value)) {
    for (const item of value) {
      const raw = typeof item === "string" ? { pattern: item } : item;
      if (typeof raw !== "object" || raw === null) continue;
      const candidate = raw as { pattern?: unknown; type?: unknown; enabled?: unknown };
      if (typeof candidate.pattern !== "string" || candidate.pattern.length === 0 || known[candidate.pattern]) continue;
      const type = candidate.type === "directory" || candidate.type === "file" || candidate.type === "pattern"
        ? candidate.type
        : candidate.pattern.startsWith("/") ? "file" : "pattern";
      normalized.push({ pattern: candidate.pattern, type, enabled: candidate.enabled !== false });
      known[candidate.pattern] = true;
    }
  }
  for (const preset of PRESETS) {
    if (!known[preset.pattern]) normalized.push({ pattern: preset.pattern, type: "directory", enabled: true });
  }
  return normalized;
}

function addPickedExclusions(current: Exclusion[], paths: string[], type: "directory" | "file"): Exclusion[] {
  const known = new Set(current.map((entry) => entry.pattern));
  const additions: Exclusion[] = [];
  for (const pattern of paths) {
    if (!pattern || known.has(pattern)) continue;
    known.add(pattern);
    additions.push({ pattern, type, enabled: true });
  }
  return additions.length === 0 ? current : [...current, ...additions];
}

function Field({ label, children, detail }: { label: string; children: ReactNode; detail?: string }) {
  return <label className="preference-row setting-row"><span className="row-copy"><strong>{label}</strong>{detail && <small>{detail}</small>}</span><span className="field-control">{children}</span></label>;
}

function Section({ title, children, description }: { title: string; children?: ReactNode; description?: string }) {
  return <section className="preference-section form-section"><h2 className="section-heading">{title}</h2>{description && <p>{description}</p>}{children}</section>;
}

/** Auto-saved preference pages. Optional props allow the component to be mounted independently. */
export default function SettingsPreferences({
  selectedPage = "behavior",
  settings: suppliedSettings,
  saveSetting: suppliedSave,
  trayAvailable = false,
  isFlatpak = false,
}: SettingsPreferencesProps) {
  const [ownedSettings, setOwnedSettings] = useState<Settings>({});
  const settings = suppliedSettings ?? ownedSettings;

  useEffect(() => {
    if (suppliedSettings) return;
    void request<Settings>("settings.get").then(setOwnedSettings).catch((error: unknown) => notify(_("Unable to load preferences: {error}", { error: String(error) }), "error"));
  }, [suppliedSettings]);

  const saveSetting = useCallback<SaveSetting>(async (key, value) => {
    if (suppliedSave) return suppliedSave(key, value);
    const before = ownedSettings[key];
    const optimistic = { ...ownedSettings, [key]: value };
    setOwnedSettings(optimistic);
    try {
      const saved = await request<Settings>("settings.update", { [key]: value });
      setOwnedSettings(saved);
      return true;
    } catch (error) {
      setOwnedSettings({ ...optimistic, [key]: before });
      notify(_("Could not save preference: {error}", { error: String(error) }), "error");
      return false;
    }
  }, [ownedSettings, suppliedSave]);

  if (selectedPage === "exclusions") return <ExclusionsPage settings={settings} saveSetting={saveSetting} />;
  if (selectedPage === "device_scan") return <DeviceScanPage settings={settings} saveSetting={saveSetting} />;
  if (selectedPage === "virustotal") return <VirusTotalPage settings={settings} saveSetting={saveSetting} />;
  if (selectedPage === "debug") return <DebugPage settings={settings} saveSetting={saveSetting} />;
  return <BehaviorPage settings={settings} saveSetting={saveSetting} trayAvailable={trayAvailable} isFlatpak={isFlatpak} />;
}

function BehaviorPage({ settings, saveSetting, trayAvailable, isFlatpak }: { settings: Settings; saveSetting: SaveSetting; trayAvailable: boolean; isFlatpak: boolean }) {
  const [languages, setLanguages] = useState(LANGUAGE_FALLBACK);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [busyManager, setBusyManager] = useState<string | null>(null);

  useEffect(() => {
    void request<{ languages?: Array<{ code: string; name: string }> }>("i18n.catalog")
      .then((catalog) => {
        if (catalog.languages?.length) setLanguages(catalog.languages);
      })
      .catch(() => undefined);
  }, []);

  const refreshIntegrations = useCallback(async () => {
    try {
      const result = await request<{ integrations: Integration[] }>("platform.integrations_status");
      setIntegrations(result.integrations);
    } catch (error) {
      notify(_("Unable to read file manager integrations: {error}", { error: String(error) }), "error");
    }
  }, []);

  useEffect(() => {
    if (dialogOpen) void refreshIntegrations();
  }, [dialogOpen, refreshIntegrations]);

  const changeIntegration = async (integration: Integration, action: "install" | "repair" | "remove") => {
    setBusyManager(integration.file_manager);
    try {
      if (action === "remove") {
        await request("platform.integrations_remove", { file_manager: integration.file_manager });
      } else {
        await request("platform.integrations_install", { file_manager: integration.file_manager, repair: action === "repair" });
      }
      notify(action === "remove"
        ? _("{name} integration removed", { name: integration.display_name })
        : action === "repair"
          ? _("{name} integration repaired", { name: integration.display_name })
          : _("{name} integration installed", { name: integration.display_name }), "success");
      await refreshIntegrations();
    } catch (error) {
      notify(_("Integration {action} failed: {error}", { action, error: String(error) }), "error");
    } finally {
      setBusyManager(null);
    }
  };

  const configuredLanguage = valueString(settings, "language", "auto") || "auto";
  const selectedLanguage = configuredLanguage === "auto" || languages.some((language) => language.code === configuredLanguage)
    ? configuredLanguage
    : activeCatalog()?.language ?? "en";

  return <div className="settings-preferences">
    <Section title={_("Language")} description={_("Override the application language. Restart ClamUI to apply a language change.")}>
      <Field label={_("Language")}><select value={selectedLanguage} onChange={async (event) => {
        if (await saveSetting("language", event.target.value)) notify(_("Restart ClamUI to apply the new language"), "info");
      }}><option value="auto">{_("Automatic (System)")}</option>{languages.map((language) => <option key={language.code} value={language.code}>{language.name}</option>)}</select></Field>
    </Section>
    {trayAvailable ? <Section title={_("Window Behavior")} description={_("Configure what happens when closing the main window.")}>
      <Field label={_("When closing window")}><select value={valueString(settings, "close_behavior", "ask")} onChange={(event) => void saveSetting("close_behavior", event.target.value)}>{CLOSE_BEHAVIOR.map((value) => <option key={value} value={value}>{_(value === "minimize" ? "Minimize to tray" : value === "quit" ? "Quit completely" : "Always ask")}</option>)}</select></Field>
      <Field label={_("Start in System Tray")} detail={_("Launch in the background and show only the tray icon.")}><input type="checkbox" checked={valueBoolean(settings, "start_minimized", false)} onChange={(event) => void saveSetting("start_minimized", event.target.checked)} /></Field>
    </Section> : <Section title={_("Window Behavior")} description={_("System tray is not available. Window behavior settings require an active system tray.")} />}
    <Section title={_("Scan Behavior")}>
      <Field label={_("Show Live Scan Progress")} detail={_("Display files being scanned in real time.")}><input type="checkbox" checked={valueBoolean(settings, "show_live_progress", true)} onChange={(event) => void saveSetting("show_live_progress", event.target.checked)} /></Field>
      <Field label={_("Desktop Notifications")} detail={_("Allow scan, update, device, and VirusTotal notifications.")}><input type="checkbox" checked={valueBoolean(settings, "notifications_enabled", true)} onChange={(event) => void saveSetting("notifications_enabled", event.target.checked)} /></Field>
    </Section>
    {isFlatpak && <Section title={_("File Manager Integration")} description={_("Add context menu actions for supported file managers.")}><button type="button" onClick={() => setDialogOpen(true)}>{_("Configure Integration")}</button></Section>}
    {dialogOpen && <Modal title={_("File Manager Integration")} onClose={() => setDialogOpen(false)}>
      <p>{_(
        // Translators: 'Scan with ClamUI' is the installed file-manager menu label; keep it in English.
        "Install, repair, or remove 'Scan with ClamUI' context menu actions.",
      )}</p>
      {integrations.map((integration) => {
        const status = integration.status === "installed"
          ? _("Installed")
          : integration.status === "not_installed"
            ? _("Not installed")
            : _("Partially installed");
        return <article key={integration.file_manager} className="integration-row">
          <div><strong>{integration.display_name}</strong><p>{integration.description}</p><small>{integration.is_available ? status : _("Not available")}{integration.missing_files.length > 0 ? ` — ${_("missing")} ${integration.missing_files.join(", ")}` : ""}</small></div>
          <div>{integration.status === "installed" ? <><button type="button" disabled={busyManager === integration.file_manager} onClick={() => void changeIntegration(integration, "repair")}>{_("Repair")}</button><button type="button" disabled={busyManager === integration.file_manager} onClick={() => void changeIntegration(integration, "remove")}>{_("Remove")}</button></> : <button type="button" disabled={!integration.is_available || busyManager === integration.file_manager} onClick={() => void changeIntegration(integration, integration.status === "partial" ? "repair" : "install")}>{_(integration.status === "partial" ? "Repair" : "Install")}</button>}</div>
        </article>;
      })}
      <footer><button type="button" onClick={() => setDialogOpen(false)}>{_("Close")}</button></footer>
    </Modal>}
  </div>;
}

function ExclusionsPage({ settings, saveSetting }: { settings: Settings; saveSetting: SaveSetting }) {
  const exclusions = useMemo(() => normalizedExclusions(settings.exclusion_patterns), [settings.exclusion_patterns]);
  const [newPattern, setNewPattern] = useState("");
  const [pickerPending, setPickerPending] = useState(false);
  const pendingExclusions = useRef(exclusions);
  const pickerPendingRef = useRef(false);
  useEffect(() => {
    pendingExclusions.current = exclusions;
  }, [exclusions]);

  const update = (change: (current: Exclusion[]) => Exclusion[]) => {
    const next = change(pendingExclusions.current);
    pendingExclusions.current = next;
    return saveSetting("exclusion_patterns", next);
  };
  const addCustomExclusion = async () => {
    const pattern = newPattern.trim();
    if (!pattern) return;
    if (pendingExclusions.current.some((entry) => entry.pattern === pattern)) {
      notify(_("This exclusion already exists"), "warning");
      return;
    }
    if (await update((current) => [...current, { pattern, type: pattern.startsWith("/") ? "file" : "pattern", enabled: true }])) {
      setNewPattern("");
    }
  };
  const chooseExclusions = async (directory: boolean) => {
    if (pickerPendingRef.current) return;
    pickerPendingRef.current = true;
    setPickerPending(true);
    try {
      const paths = await openPaths({ directory, multiple: true });
      const next = addPickedExclusions(pendingExclusions.current, paths, directory ? "directory" : "file");
      if (next !== pendingExclusions.current) void update(() => next);
    } catch (error) {
      notify(_("Unable to choose exclusions: {error}", { error: String(error) }), "error");
    } finally {
      pickerPendingRef.current = false;
      setPickerPending(false);
    }
  };
  const custom = exclusions.filter((entry) => !PRESET_PATTERNS[entry.pattern]);
  const toggle = (pattern: string, enabled: boolean) => void update((current) => current.map((item) => item.pattern === pattern ? { ...item, enabled } : item));
  return <div className="settings-preferences exclusions-preferences">
    <Section title={_("Preset Exclusions")} description={_("Common directories to exclude from scanning. Changes save immediately.")}>
      <div className="exclusion-list">{PRESETS.map((preset) => {
        const entry = exclusions.find((item) => item.pattern === preset.pattern) ?? { pattern: preset.pattern, type: "directory" as const, enabled: true };
        return <div className="exclusion-row" key={preset.pattern}>
          <label className="exclusion-toggle">
            <input type="checkbox" checked={entry.enabled} onChange={(event) => toggle(preset.pattern, event.target.checked)} />
            <span className="exclusion-copy"><strong>{preset.description()}</strong><small>{preset.pattern}</small></span>
          </label>
        </div>;
      })}</div>
    </Section>
    <Section title={_("Custom Exclusions")} description={_("Select files or folders, or enter an absolute file path or pattern. Changes save immediately.")}>
      <div className="actions exclusion-picker-actions">
        <button className="button" type="button" disabled={pickerPending} onClick={() => void chooseExclusions(false)}><Icon name="file" />{_("Add Files")}</button>
        <button className="button" type="button" disabled={pickerPending} onClick={() => void chooseExclusions(true)}><Icon name="folder" />{_("Add Folders")}</button>
      </div>
      <div className="inline-form">
        <input value={newPattern} placeholder={_("/path/to/exclude or *.tmp")} onChange={(event) => setNewPattern(event.target.value)} />
        <button className="button" type="button" onClick={() => void addCustomExclusion()}><Icon name="plus" />{_("Add")}</button>
      </div>
      <div className="exclusion-list">{custom.map((entry) => <div className="exclusion-row" key={entry.pattern}>
        <label className="exclusion-toggle">
          <input type="checkbox" checked={entry.enabled} onChange={(event) => toggle(entry.pattern, event.target.checked)} />
          <span className="exclusion-copy"><code className="path-value">{entry.pattern}</code><small>{entry.type}</small></span>
        </label>
        <button className="button danger icon-button exclusion-remove" type="button" aria-label={_("Remove {pattern}", { pattern: entry.pattern })} title={_("Remove {pattern}", { pattern: entry.pattern })} onClick={() => void update((current) => current.filter((item) => item.pattern !== entry.pattern))}><Icon name="trash" /></button>
      </div>)}</div>
    </Section>
  </div>;
}

function DeviceScanPage({ settings, saveSetting }: { settings: Settings; saveSetting: SaveSetting }) {
  const selectedTypes = Array.isArray(settings.device_auto_scan_types) ? settings.device_auto_scan_types.filter((type): type is string => typeof type === "string") : ["removable", "external"];
  const saveNumber = (key: string, raw: string, lower: number, upper: number) => {
    const parsed = Number.parseInt(raw, 10);
    void saveSetting(key, Number.isFinite(parsed) ? Math.max(lower, Math.min(upper, parsed)) : lower);
  };
  return <div className="settings-preferences"><Section title={_("General")} description={_("Automatically scan storage devices when they are connected.")}><Field label={_("Enable Device Auto-Scan")}><input type="checkbox" checked={valueBoolean(settings, "device_auto_scan_enabled", false)} onChange={(event) => void saveSetting("device_auto_scan_enabled", event.target.checked)} /></Field></Section><Section title={_("Device Types")} description={_("Select which kinds of mounted devices may be scanned.")}>{DEVICE_TYPES.map((type) => <Field key={type.id} label={type.label()} detail={type.detail()}><input type="checkbox" checked={selectedTypes.includes(type.id)} onChange={(event) => { const types = event.target.checked ? [...selectedTypes, type.id] : selectedTypes.filter((entry) => entry !== type.id); void saveSetting("device_auto_scan_types", types); }} /></Field>)}</Section><Section title={_("Options")}><Field label={_("Max Device Size (GB)")} detail={_("0 means no size limit; devices larger than 10,000 GB are not accepted.")}><input type="number" min="0" max="10000" step="1" value={valueNumber(settings, "device_auto_scan_max_size_gb", 32)} onChange={(event) => saveNumber("device_auto_scan_max_size_gb", event.target.value, 0, 10000)} /></Field><Field label={_("Scan Delay (seconds)")} detail={_(
    // Translators: The en dash marks the inclusive 0–60-second delay range; use your language's usual range typography.
    "Wait after mounting before scanning (0–60 seconds).",
  )}><input type="number" min="0" max="60" step="1" value={valueNumber(settings, "device_auto_scan_delay_seconds", 3)} onChange={(event) => saveNumber("device_auto_scan_delay_seconds", event.target.value, 0, 60)} /></Field><Field label={_("Auto-Quarantine Threats")}><input type="checkbox" checked={valueBoolean(settings, "device_auto_scan_auto_quarantine", false)} onChange={(event) => void saveSetting("device_auto_scan_auto_quarantine", event.target.checked)} /></Field><Field label={_("Notifications")} detail={_("Show desktop notifications for device scan events.")}><input type="checkbox" disabled={!valueBoolean(settings, "notifications_enabled", true)} checked={valueBoolean(settings, "device_auto_scan_notify", true)} onChange={(event) => void saveSetting("device_auto_scan_notify", event.target.checked)} /></Field>{!valueBoolean(settings, "notifications_enabled", true) && <p className="muted">{_("Desktop notifications are globally disabled in Behavior.")}</p>}<Field label={_("Skip on Battery")}><input type="checkbox" checked={valueBoolean(settings, "device_auto_scan_skip_on_battery", true)} onChange={(event) => void saveSetting("device_auto_scan_skip_on_battery", event.target.checked)} /></Field></Section></div>;
}

function VirusTotalPage({ settings, saveSetting }: { settings: Settings; saveSetting: SaveSetting }) {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [key, setKey] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const refresh = useCallback(async () => {
    try { setStatus(await request<KeyStatus>("virustotal.key_status")); } catch { setStatus({ present: false, backend: "none", status: "unavailable" }); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const saveKey = async () => {
    if (!/^[a-fA-F0-9]{64}$/.test(key)) { notify(_("VirusTotal API keys must be exactly 64 hexadecimal characters"), "error"); return; }
    setSaving(true);
    try { const saved = await request<KeyStatus>("virustotal.key_save", { key }); setStatus(saved); setKey(""); notify(saved.message ?? _("API key saved"), "success"); } catch { notify(_("Unable to save the API key"), "error"); } finally { setSaving(false); }
  };
  const deleteKey = async () => {
    setSaving(true);
    try { const deleted = await request<KeyStatus>("virustotal.key_delete"); setStatus(deleted); setDeleteOpen(false); notify(deleted.message ?? _("API key deleted"), "success"); } catch { notify(_("Unable to delete the API key"), "error"); } finally { setSaving(false); }
  };
  const noKeyAction = valueString(settings, "virustotal_remember_no_key_action", "none");
  return <div className="settings-preferences"><Section title={_("API Key")} description={_("Keys are stored in the operating system keyring or the explicitly enabled compatibility fallback; they are never returned to the interface.")}><Field label={_("Status")} detail={status?.present ? _("Configured ({masked}) using {backend}", { masked: status.masked ?? _("masked"), backend: status.backend.replaceAll("_", " ") }) : status?.status === "locked" ? _("Keyring is locked") : status?.status === "unavailable" ? _("Keyring unavailable") : _("Not configured")}><button type="button" onClick={() => void refresh()}>{_("Refresh")}</button></Field><Field label={_("API Key")} detail={_("Exactly 64 hexadecimal characters.")}><input type="password" autoComplete="off" value={key} onChange={(event) => setKey(event.target.value)} /></Field><div className="button-row"><button type="button" disabled={saving || !/^[a-fA-F0-9]{64}$/.test(key)} onClick={() => void saveKey()}>{_("Save Key")}</button><button type="button" onClick={() => void openExternal("https://www.virustotal.com/gui/my-apikey")}>{_("Get a free API key")}</button><button type="button" className="destructive" disabled={saving || !status?.present} onClick={() => setDeleteOpen(true)}>{_("Delete Key")}</button></div></Section><Section title={_("Behavior")}><Field label={_("When API key is missing")}><select value={noKeyAction} onChange={(event) => void saveSetting("virustotal_remember_no_key_action", event.target.value)}><option value="none">{_("Always ask")}</option><option value="open_website">{_("Open VirusTotal website")}</option><option value="prompt">{_("Show notification only")}</option></select></Field></Section><Section title={_("Information")}><p>{_("Free tier: 4 requests per minute, 500 per day. Files up to 650 MB can be scanned.")}</p></Section>{deleteOpen && <Modal title={_("Delete VirusTotal API key")} onClose={() => setDeleteOpen(false)}><p>{_("This removes the key from secure storage. You will need to enter it again to use VirusTotal scanning.")}</p><footer><button type="button" onClick={() => setDeleteOpen(false)}>{_("Cancel")}</button><button type="button" className="destructive" disabled={saving} onClick={() => void deleteKey()}>{_("Delete")}</button></footer></Modal>}</div>;
}

function DebugPage({ settings, saveSetting }: { settings: Settings; saveSetting: SaveSetting }) {
  const [debug, setDebug] = useState<DebugInfo | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const logFileSummary = debug
    ? ngettext("{count} file", "{count} files", debug.file_count, { count: debug.file_count })
    : "";

  const refresh = useCallback(async () => {
    try {
      setDebug(await request<DebugInfo>("logs.debug_info"));
    } catch (error) {
      notify(_("Unable to read debug logs: {error}", { error: String(error) }), "error");
    }
  }, []);

  useEffect(() => {
    void refresh();
    void request<SystemInfo>("platform.system_info")
      .then(setSystem)
      .catch((error: unknown) => notify(_("Unable to read system information: {error}", { error: String(error) }), "error"));
  }, [refresh]);

  const exportLogs = async () => {
    try {
      const archive = await request<{ content_base64: string; filename: string }>("logs.debug_export");
      const saved = await saveBinary(archive.content_base64, archive.filename, [
        { name: _("ZIP archives"), extensions: ["zip"] },
        { name: _("All files"), extensions: ["*"] },
      ]);
      if (saved) notify(_("Logs exported successfully"), "success");
    } catch (error) {
      notify(_("Unable to export logs: {error}", { error: String(error) }), "error");
    }
  };

  const clearLogs = async () => {
    try {
      const result = await request<{ cleared: number; message: string; success: boolean }>("logs.debug_clear");
      if (!result.success) {
        notify(result.message, "error");
        return;
      }
      setClearOpen(false);
      notify(result.message || ngettext("{count} log file cleared", "{count} log files cleared", result.cleared, { count: result.cleared }), "success");
      await refresh();
    } catch (error) {
      notify(_("Unable to clear logs: {error}", { error: String(error) }), "error");
    }
  };

  const copySystem = async () => {
    if (!system) return;
    const lines = [
      _("ClamUI System Information"),
      "=".repeat(40),
      _("Installation Type: {value}", { value: system.installation_type }),
      _("Distribution: {value}", { value: system.distribution }),
      _("Desktop Environment: {value}", { value: system.desktop_environment }),
      _("Rust Runtime: {value}", { value: system.rust_runtime }),
      _("Tauri Runtime: {value}", { value: system.tauri_runtime ?? _("Unknown") }),
      _("Platform: {value}", { value: system.platform }),
      _("Architecture: {value}", { value: system.architecture }),
      _("Version: {value}", { value: system.app_version }),
    ];
    try {
      await copyText(lines.join("\n"));
      notify(_("System information copied to clipboard"), "success");
    } catch (error) {
      notify(_("Unable to copy system information: {error}", { error: String(error) }), "error");
    }
  };

  return <div className="settings-preferences">
    <Section title={_("Logging Settings")} description={_("Higher levels produce more detailed logs and apply immediately.")}>
      <Field label={_("Log Level")}><select value={valueString(settings, "debug_log_level", "WARNING")} onChange={(event) => void saveSetting("debug_log_level", event.target.value)}>{["DEBUG", "INFO", "WARNING", "ERROR"].map((level) => <option key={level} value={level}>{level}</option>)}</select></Field>
      <Field label={_("Log File Location")} detail={debug?.log_dir ?? _("Loading…")}>{debug?.log_dir && <button type="button" onClick={() => void openPath(debug.log_dir)}>{_("Open")}</button>}</Field>
    </Section>
    <Section title={_("Log Management")} description={_("Export a ZIP archive for support or permanently clear the application logs.")}>
      <Field label={_("Current Log Size")} detail={debug ? `${formatBytes(debug.total_bytes)} (${logFileSummary})` : _("Loading…")}><button type="button" onClick={() => void refresh()}>{_("Refresh")}</button></Field>
      <Field label={_("Export Logs")} detail={_("Save all sanitized debug logs to a ZIP archive.")}><button type="button" disabled={!debug || debug.file_count === 0} onClick={() => void exportLogs()}>{_("Export")}</button></Field>
      <Field label={_("Clear Logs")} detail={_("This permanently deletes all debug log files.")}><button type="button" className="destructive" disabled={!debug || debug.file_count === 0} onClick={() => setClearOpen(true)}>{_("Clear")}</button></Field>
    </Section>
    <Section title={_("System Information")} description={_("Useful for troubleshooting and bug reports.")}>
      {system ? <><Field label={_("Installation Type")} detail={system.installation_type}><span /></Field><Field label={_("Distribution")} detail={system.distribution}><span /></Field><Field label={_("Desktop Environment")} detail={system.desktop_environment}><span /></Field><Field label={_("Rust Runtime")} detail={system.rust_runtime}><span /></Field><Field label={_("Tauri Runtime")} detail={system.tauri_runtime ?? _("Unknown")}><span /></Field><Field label={_("Platform")} detail={`${system.platform} (${system.architecture})`}><span /></Field><Field label={_("Copy System Info")} detail={_("Copy all system information to the clipboard.")}><button type="button" onClick={() => void copySystem()}>{_("Copy")}</button></Field></> : <p>{_("Loading system information…")}</p>}
    </Section>
    {clearOpen && <Modal title={_("Clear logs")} onClose={() => setClearOpen(false)}><p>{ngettext("This permanently deletes {count} log file totaling {size}. This action cannot be undone.", "This permanently deletes {count} log files totaling {size}. This action cannot be undone.", debug?.file_count ?? 0, { size: debug ? formatBytes(debug.total_bytes) : formatBytes(0) })}</p><div className="button-row"><button type="button" className="button" onClick={() => setClearOpen(false)}>{_("Cancel")}</button><button type="button" className="button destructive" onClick={() => void clearLogs()}>{_("Delete Logs")}</button></div></Modal>}
  </div>;
}
