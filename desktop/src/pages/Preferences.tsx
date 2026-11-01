import { useCallback, useEffect, useRef, useState } from "react";

import { notify, onEvent, request, startupState } from "../api";
import { _ } from "../i18n";
import ConfigPreferences from "./ConfigPreferences";
import SettingsPreferences from "./SettingsPreferences";

type Settings = Record<string, unknown>;
type ConfigSection = "database" | "scanner" | "scheduled" | "onaccess" | "save";
type PreferencePage = "behavior" | "exclusions" | "database" | "scanner" | "scheduled" | "device_scan" | "onaccess" | "virustotal" | "debug" | "save";

const NAVIGATION: Array<{ id: PreferencePage; label: () => string; config?: ConfigSection }> = [
  { id: "behavior", label: () => _("Behavior") },
  { id: "exclusions", label: () => _("Exclusions") },
  { id: "database", label: () => _("Database"), config: "database" },
  { id: "scanner", label: () => _("Scanner"), config: "scanner" },
  { id: "scheduled", label: () => _("Scheduled"), config: "scheduled" },
  { id: "device_scan", label: () => _("Device Scan") },
  { id: "onaccess", label: () => _("On-Access"), config: "onaccess" },
  { id: "virustotal", label: () => _("VirusTotal") },
  { id: "debug", label: () => _("Debug") },
  { id: "save", label: () => _("Save"), config: "save" },
];


/** The ten-page preferences host. Config pages stay mounted to retain unsaved drafts. */
export default function Preferences() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const settingsRef = useRef<Settings>({});
  const confirmedSettingsRef = useRef<Settings>({});
  const writes = useRef(new Map<string, number>());
  const writeQueues = useRef(new Map<string, Promise<boolean>>());
  const [selected, setSelected] = useState<PreferencePage>("behavior");
  const [configSection, setConfigSection] = useState<ConfigSection>("database");
  const [trayAvailable, setTrayAvailable] = useState(false);
  const [flatpak, setFlatpak] = useState(false);

  useEffect(() => {
    let active = true;
    void request<Settings>("settings.get")
      .then((loaded) => {
        if (!active) return;
        settingsRef.current = loaded;
        confirmedSettingsRef.current = loaded;
        setSettings(loaded);
      })
      .catch((error: unknown) => notify(_("Unable to load preferences: {error}", { error: String(error) }), "error"));
    void request<Record<string, unknown>>("platform.system_info")
      .then((info) => {
        if (!active) return;
        setFlatpak(info.is_flatpak === true || info.installation_type === "Flatpak");
      })
      .catch(() => undefined);
    void startupState().then((state) => {
      if (active) setTrayAvailable(state.tray_available);
    }).catch(() => undefined);
    let unlisten: (() => void) | undefined;
    void onEvent((event) => {
      if (!active) return;
      if (event.event === "tray-availability" && typeof event.data === "object" && event.data !== null) {
        const data = event.data as { available?: unknown };
        if (typeof data.available === "boolean") setTrayAvailable(data.available);
      }
    }).then((stop) => {
      unlisten = stop;
    });
    return () => {
      active = false;
      unlisten?.();
    };
  }, []);

  const saveSetting = useCallback(async (key: string, value: unknown): Promise<boolean> => {
    const serial = (writes.current.get(key) ?? 0) + 1;
    writes.current.set(key, serial);
    settingsRef.current = { ...settingsRef.current, [key]: value };
    setSettings(settingsRef.current);

    const previousWrite = writeQueues.current.get(key) ?? Promise.resolve(true);
    const persist = previousWrite.then(async () => {
      try {
        const saved = await request<Settings>("settings.update", { [key]: value });
        const durableValue = Object.prototype.hasOwnProperty.call(saved, key) ? saved[key] : value;
        confirmedSettingsRef.current = { ...confirmedSettingsRef.current, [key]: durableValue };
        if (writes.current.get(key) === serial && JSON.stringify(settingsRef.current[key]) === JSON.stringify(value)) {
          settingsRef.current = { ...settingsRef.current, [key]: durableValue };
          setSettings(settingsRef.current);
        }
        return true;
      } catch (error) {
        if (writes.current.get(key) === serial && JSON.stringify(settingsRef.current[key]) === JSON.stringify(value)) {
          const durableValue = confirmedSettingsRef.current[key];
          settingsRef.current = { ...settingsRef.current, [key]: durableValue };
          setSettings(settingsRef.current);
          notify(_("Could not save preference: {error}", { error: String(error) }), "error");
        }
        return false;
      }
    });
    writeQueues.current.set(key, persist);
    const saved = await persist;
    if (writeQueues.current.get(key) === persist) writeQueues.current.delete(key);
    return saved;
  }, []);

  const selectPage = (item: (typeof NAVIGATION)[number]) => {
    setSelected(item.id);
    if (item.config) setConfigSection(item.config);
  };

  if (settings === null) {
    return <main className="preferences-page" aria-busy="true"><p>{_("Loading preferences…")}</p></main>;
  }

  const showsConfig = NAVIGATION.find((item) => item.id === selected)?.config !== undefined;
  return (
    <main className="preferences-page" aria-label={_("Preferences")}>
      <div className="preferences-layout">
        <nav className="preferences-navigation" aria-label={_("Preference categories")}>
          {NAVIGATION.map((item) => (
            <button
              type="button"
              key={item.id}
              className={selected === item.id ? "active" : ""}
              aria-current={selected === item.id ? "page" : undefined}
              onClick={() => selectPage(item)}
            >{item.label()}</button>
          ))}
        </nav>
        <section className="preferences-content">
          <div hidden={showsConfig}>
            <SettingsPreferences
              selectedPage={selected}
              settings={settings}
              saveSetting={saveSetting}
              trayAvailable={trayAvailable}
              isFlatpak={flatpak}
            />
          </div>
          <div hidden={!showsConfig}>
            <ConfigPreferences section={configSection} />
          </div>
        </section>
      </div>
    </main>
  );
}
