import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";

import {
  closeApplication,
  credits as loadCredits,
  notify,
  onEvent,
  openExternal,
  openPaths,
  request,
  startupState,
  type NativeEvent,
  type Credits,
} from "./api";
import { HelperTrustErrorDialog, isHelperTrustError } from "./HelperTrustErrorDialog";
import { Icon, type IconName } from "./Icon";
import { _, activeCatalog } from "./i18n";
import { Modal } from "./Modal";
import Audit from "./pages/Audit";
import Components from "./pages/Components";
import Database from "./pages/Database";
import Logs from "./pages/Logs";
import Network from "./pages/Network";
import Preferences from "./pages/Preferences";
import Profiles from "./pages/Profiles";
import Quarantine from "./pages/Quarantine";
import Results from "./pages/Results";
import Scan from "./pages/Scan";
import Statistics from "./pages/Statistics";

type PageId =
  | "scan"
  | "database"
  | "logs"
  | "components"
  | "quarantine"
  | "statistics"
  | "audit"
  | "network"
  | "preferences"
  | "profiles"
  | "results";

type NavigationDetail = { page: PageId; args: Record<string, unknown> };
type Toast = { id: number; message: string; type: "success" | "error" | "info" | "warning" };
type StartupInfo = { version: string; trayAvailable: boolean };
type HelperStatus = {
  version: string;
  detail: string | null;
  installed: boolean;
  installable: boolean;
  needsOnboarding: boolean;
};

const pageComponents: Record<Exclude<PageId, "database">, ComponentType> = {
  scan: Scan,
  logs: Logs,
  components: Components,
  quarantine: Quarantine,
  statistics: Statistics,
  audit: Audit,
  network: Network,
  preferences: Preferences,
  profiles: Profiles,
  results: Results,
};

const destinations: Array<{
  id: Exclude<PageId, "preferences" | "profiles" | "results">;
  shortcut: string;
  icon: IconName;
}> = [
  { id: "scan", shortcut: "Ctrl+1", icon: "folder" },
  { id: "database", shortcut: "Ctrl+2", icon: "database" },
  { id: "logs", shortcut: "Ctrl+3", icon: "logs" },
  { id: "components", shortcut: "Ctrl+4", icon: "components" },
  { id: "quarantine", shortcut: "Ctrl+5", icon: "shield" },
  { id: "statistics", shortcut: "Ctrl+6", icon: "statistics" },
  { id: "audit", shortcut: "Ctrl+7", icon: "audit" },
  { id: "network", shortcut: "Ctrl+8", icon: "network" },
];

const PROJECT_URL = "https://github.com/linx-systems/clamui";
const ISSUES_URL = "https://github.com/linx-systems/clamui/issues";

function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "https:" || url.protocol === "http:") &&
      url.hostname &&
      !url.username &&
      !url.password
    ) ? url.toString() : null;
  } catch {
    return null;
  }
}

function contributorCredit(line: string): { name: string; url: string | null } {
  const urlStart = line.lastIndexOf(" ");
  if (urlStart === -1) {
    return { name: line, url: null };
  }
  const url = safeHttpUrl(line.slice(urlStart + 1));
  return url ? { name: line.slice(0, urlStart), url } : { name: line, url: null };
}

function pageLabel(page: PageId): string {
  switch (page) {
    case "scan":
      return _("Scan");
    case "database":
      return _("Database");
    case "logs":
      return _("Logs");
    case "components":
      return _("Components");
    case "quarantine":
      return _("Quarantine");
    case "statistics":
      return _("Statistics");
    case "audit":
      return _("Audit");
    case "network":
      return _("Network");
    case "preferences":
      return _("Preferences");
    case "profiles":
      return _("Profiles");
    case "results":
      return _("Results");
  }
}
function isPageId(value: unknown): value is PageId {
  switch (value) {
    case "scan":
    case "database":
    case "logs":
    case "components":
    case "quarantine":
    case "statistics":
    case "audit":
    case "network":
      return true;
    case "preferences":
    case "profiles":
    case "results":
      return true;
    default:
      return false;
  }
}

function navigationDetail(value: unknown): NavigationDetail | null {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !("page" in value) ||
    !isPageId(value.page)
  ) {
    return null;
  }
  const args: Record<string, unknown> = {};
  if (
    "args" in value &&
    typeof value.args === "object" &&
    value.args !== null &&
    !Array.isArray(value.args)
  ) {
    for (const [key, argument] of Object.entries(value.args)) {
      args[key] = argument;
    }
  }
  return { page: value.page, args };
}

function localEvent(event: string, data: unknown = {}): void {
  window.dispatchEvent(new CustomEvent("clamui-event", { detail: { event, data } }));
}

function toastClass(type: Toast["type"]): string {
  switch (type) {
    case "success":
      return "toast success";
    case "error":
      return "toast error";
    case "warning":
      return "toast warning";
    default:
      return "toast";
  }
}

function helperStatusFrom(value: unknown): HelperStatus | null {
  if (
    typeof value !== "object" ||
    value === null ||
    !("version" in value) ||
    typeof value.version !== "string" ||
    !("installed" in value) ||
    typeof value.installed !== "boolean" ||
    !("installable" in value) ||
    typeof value.installable !== "boolean" ||
    !("needs_onboarding" in value) ||
    typeof value.needs_onboarding !== "boolean"
  ) {
    return null;
  }
  return {
    version: value.version,
    detail: "detail" in value && typeof value.detail === "string" ? value.detail : null,
    installed: value.installed,
    installable: value.installable,
    needsOnboarding: value.needs_onboarding,
  };
}

export default function App(): ReactNode {
  const [activePage, setActivePage] = useState<PageId>("scan");
  const activePageRef = useRef<PageId>("scan");
  const [previousPage, setPreviousPage] = useState<Exclude<PageId, "preferences">>("scan");
  const [mountedPages, setMountedPages] = useState<Set<PageId>>(() => new Set(["scan"]));
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [helperTrustError, setHelperTrustError] = useState<string | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [aboutCredits, setAboutCredits] = useState<Credits | null>(null);
  const [aboutCreditsError, setAboutCreditsError] = useState<string | null>(null);
  const [closeOpen, setCloseOpen] = useState(false);
  const [scanCloseOpen, setScanCloseOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);
  const [scanJobId, setScanJobId] = useState<string | null>(null);
  const scanJobIdRef = useRef<string | null>(null);
  const [openMenu, setOpenMenu] = useState<"application" | "targets" | null>(null);
  const targetMenuRef = useRef<HTMLDivElement>(null);
  const applicationMenuRef = useRef<HTMLDivElement>(null);
  const targetMenuButtonRef = useRef<HTMLButtonElement>(null);
  const applicationMenuButtonRef = useRef<HTMLButtonElement>(null);
  const [startupInfo, setStartupInfo] = useState<StartupInfo>({ version: "", trayAvailable: false });
  const [rememberCloseChoice, setRememberCloseChoice] = useState(false);
  const [closeIntent, setCloseIntent] = useState<"window" | "quit">("window");
  const [updateStartRequest, setUpdateStartRequest] = useState(0);
  const [helperStatus, setHelperStatus] = useState<HelperStatus | null>(null);
  const [helperInstalling, setHelperInstalling] = useState(false);
  const [helperError, setHelperError] = useState<string | null>(null);
  const showToast = useCallback((message: string, type: Toast["type"]): void => {
    if (type === "error" && isHelperTrustError(message)) {
      setHelperTrustError(message);
      return;
    }
    const toast = { id: Date.now() + Math.floor(Math.random() * 1000), message, type };
    setToasts((current) => [...current, toast]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== toast.id));
    }, 6000);
  }, []);

  const openAbout = useCallback((): void => {
    setAboutCredits(null);
    setAboutCreditsError(null);
    setAboutOpen(true);
  }, []);

  const openAboutUrl = useCallback((url: string): void => {
    const isContributorUrl = aboutCredits?.contributors.some(
      (contributor) => contributorCredit(contributor).url === url,
    ) ?? false;
    if (!safeHttpUrl(url) || (!isContributorUrl && url !== PROJECT_URL && url !== ISSUES_URL)) {
      return;
    }
    void openExternal(url).catch(() => notify(_("Could not open link"), "error"));
  }, [aboutCredits]);

  const selectPage = useCallback((page: PageId, args: Record<string, unknown> = {}): void => {
    const currentPage = activePageRef.current;
    if (page === "preferences" && currentPage !== "preferences") {
      setPreviousPage(currentPage);
    }
    activePageRef.current = page;
    setMountedPages((current) => {
      if (current.has(page)) {
        return current;
      }
      const next = new Set(current);
      next.add(page);
      return next;
    });
    setActivePage(page);
    window.dispatchEvent(new CustomEvent("clamui-page-selected", { detail: { page, args } }));
    if (page === "scan" && args.quickScan === true) {
      window.dispatchEvent(new CustomEvent("clamui-quick-scan"));
    }
  }, []);


  const requestQuit = useCallback(async (): Promise<void> => {
    setCloseIntent("quit");
    if (scanJobId) {
      setScanCloseOpen(true);
      return;
    }
    try {
      await closeApplication("quit");
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), "error");
    }
  }, [scanJobId]);

  const completeClose = useCallback(async (choice: "minimize" | "quit", remember: boolean): Promise<void> => {
    try {
      await closeApplication(choice, remember);
      setCloseOpen(false);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), "error");
    }
  }, []);

  const cancelScanAndClose = useCallback(async (): Promise<void> => {
    try {
      if (scanJobId) {
        await request("scanner.cancel", { id: scanJobId });
      }
      setScanCloseOpen(false);
      await closeApplication(closeIntent === "quit" ? "quit" : undefined);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), "error");
    }
  }, [closeIntent, scanJobId]);
  const startUpdate = useCallback((): void => {
    selectPage("database");
    setUpdateStartRequest((current) => current + 1);
  }, [selectPage]);

  const focusMenuItem = useCallback((menu: "application" | "targets", index: number): void => {
    const root = menu === "targets" ? targetMenuRef.current : applicationMenuRef.current;
    const items = root ? Array.from(root.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')) : [];
    if (items.length > 0) {
      items[(index + items.length) % items.length]?.focus();
    }
  }, []);

  const openMenuWithFocus = useCallback((menu: "application" | "targets", index = 0): void => {
    setOpenMenu(menu);
    window.requestAnimationFrame(() => focusMenuItem(menu, index));
  }, [focusMenuItem]);

  const chooseScanTargets = useCallback(async (directory: boolean): Promise<void> => {
    setOpenMenu(null);
    if (scanJobIdRef.current) {
      notify(
        _(
          // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
          "Scan in progress — wait for it to finish before changing targets",
        ),
        "warning",
      );
      return;
    }
    try {
      const paths = await openPaths({ directory, multiple: true });
      if (paths.length === 0) {
        return;
      }
      if (scanJobIdRef.current) {
        notify(
          _(
            // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
            "Scan in progress — wait for it to finish before changing targets",
          ),
          "warning",
        );
        return;
      }
      selectPage("scan");
      localEvent("open-targets", { paths });
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), "error");
    }
  }, [selectPage]);

  const quickScan = useCallback((): void => {
    if (scanJobIdRef.current) {
      notify(
        _(
          // Translators: The em dash separates the two clauses; use your language's usual dash and spacing.
          "Scan in progress — wait for it to finish before changing targets",
        ),
        "warning",
      );
      return;
    }
    selectPage("scan", { quickScan: true });
  }, [selectPage]);

  const handleMenuKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>, menu: "application" | "targets"): void => {
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'));
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      setOpenMenu(null);
      (menu === "targets" ? targetMenuButtonRef : applicationMenuButtonRef).current?.focus();
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      focusMenuItem(menu, 0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      focusMenuItem(menu, -1);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusMenuItem(menu, currentIndex + (event.key === "ArrowDown" ? 1 : -1));
    }
  }, [focusMenuItem]);

  const installHelper = useCallback(async (): Promise<void> => {
    setHelperInstalling(true);
    setHelperError(null);
    try {
      const result = helperStatusFrom(await request<unknown>("privileged.install"));
      if (!result) {
        throw new Error(_("The privileged-helper installation returned an invalid status."));
      }
      setHelperStatus(result);
      if (result.installed) {
        setOnboardingOpen(false);
        notify(_("The privileged helper was installed successfully."), "success");
      } else {
        setHelperError(result.detail ?? _("The privileged helper is still unavailable. Try again or install it manually."));
      }
    } catch (error) {
      setHelperError(error instanceof Error ? error.message : String(error));
    } finally {
      setHelperInstalling(false);
    }
  }, []);

  const dismissOnboarding = useCallback(async (): Promise<void> => {
    if (helperStatus?.version) {
      try {
        await request("settings.update", { privileged_helper_prompt_skipped_version: helperStatus.version });
      } catch (error) {
        notify(error instanceof Error ? error.message : String(error), "error");
        return;
      }
    }
    setOnboardingOpen(false);
  }, [helperStatus]);

  useEffect(() => {
    if (!aboutOpen) {
      return;
    }
    let disposed = false;
    void loadCredits()
      .then((credits) => {
        if (!disposed) {
          setAboutCredits(credits);
        }
      })
      .catch((error: unknown) => {
        if (!disposed) {
          setAboutCreditsError(error instanceof Error ? error.message : String(error));
        }
      });
    return () => {
      disposed = true;
    };
  }, [aboutOpen]);

  useEffect(() => {
    if (!openMenu) {
      return;
    }
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      if (
        event.target instanceof Node &&
        !targetMenuRef.current?.contains(event.target) &&
        !applicationMenuRef.current?.contains(event.target)
      ) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [openMenu]);

  useEffect(() => {
    const onNavigate = (event: Event): void => {
      if (!(event instanceof CustomEvent)) {
        return;
      }
      const detail = navigationDetail(event.detail);
      if (detail) {
        selectPage(detail.page, detail.args);
      }
    };
    const onToast = (event: Event): void => {
      if (
        !(event instanceof CustomEvent) ||
        typeof event.detail !== "object" ||
        event.detail === null ||
        !("message" in event.detail) ||
        !("type" in event.detail)
      ) {
        return;
      }
      const { message, type } = event.detail;
      if (
        typeof message === "string" &&
        (type === "success" || type === "error" || type === "info" || type === "warning")
      ) {
        showToast(message, type);
      }
    };
    const onScanState = (event: Event): void => {
      if (
        !(event instanceof CustomEvent) ||
        typeof event.detail !== "object" ||
        event.detail === null ||
        !("id" in event.detail) ||
        typeof event.detail.id !== "string"
      ) {
        return;
      }
      const nextScanJobId = "active" in event.detail && event.detail.active === true ? event.detail.id : null;
      scanJobIdRef.current = nextScanJobId;
      setScanJobId(nextScanJobId);
    };

    window.addEventListener("clamui-navigate", onNavigate);
    window.addEventListener("clamui-notify", onToast);
    window.addEventListener("clamui-scan-state", onScanState);
    return () => {
      window.removeEventListener("clamui-navigate", onNavigate);
      window.removeEventListener("clamui-notify", onToast);
      window.removeEventListener("clamui-scan-state", onScanState);
    };
  }, [selectPage, showToast]);

  useEffect(() => {
    let disposed = false;
    let stopEvents: (() => void) | undefined;

    const receiveEvent = (event: NativeEvent): void => {
      window.dispatchEvent(new CustomEvent("clamui-native-event", { detail: event }));
      if (event.event === "open-targets" || event.event === "dropped-targets") {
        selectPage("scan");
        return;
      }
      if (event.event === "select-profile") {
        selectPage("scan");
        return;
      }
      if (event.event === "start-update") {
        startUpdate();
        return;
      }
      if (
        event.event === "notification-activated" &&
        typeof event.data === "object" &&
        event.data !== null &&
        "action" in event.data &&
        typeof event.data.action === "string"
      ) {
        window.dispatchEvent(new CustomEvent("clamui-notification-activated", { detail: event.data }));
        if (event.data.action === "show-scan") {
          selectPage("scan");
        } else if (event.data.action === "show-update") {
          selectPage("database");
        } else if (event.data.action === "show-audit") {
          selectPage("audit");
        }
        return;
      }
      if (
        event.event === "tray-availability" &&
        typeof event.data === "object" &&
        event.data !== null &&
        "available" in event.data &&
        typeof event.data.available === "boolean"
      ) {
        const trayAvailable = event.data.available;
        setStartupInfo((current) => ({ ...current, trayAvailable }));
        return;
      }
      if (event.event === "close-requested") {
        setCloseIntent("window");
        const data = event.data;
        const trayAvailable = (
          typeof data === "object" &&
          data !== null &&
          "tray_available" in data &&
          typeof data.tray_available === "boolean"
        ) ? data.tray_available : false;
        setStartupInfo((current) => ({ ...current, trayAvailable }));
        if (
          typeof data === "object" &&
          data !== null &&
          "scan_active" in data &&
          data.scan_active === true
        ) {
          setScanCloseOpen(true);
        } else if (trayAvailable) {
          setRememberCloseChoice(false);
          setCloseOpen(true);
        } else {
          void closeApplication("quit").catch((error: unknown) => notify(error instanceof Error ? error.message : String(error), "error"));
        }
        return;
      }
      if (
        event.event === "scan-progress" &&
        typeof event.data === "object" &&
        event.data !== null &&
        "id" in event.data &&
        typeof event.data.id === "string"
      ) {
        scanJobIdRef.current = event.data.id;
        setScanJobId(event.data.id);
        return;
      }
      if (
        event.event === "scan-complete" &&
        typeof event.data === "object" &&
        event.data !== null &&
        "id" in event.data &&
        typeof event.data.id === "string"
      ) {
        const completedId = event.data.id;
        setScanJobId((current) => {
          const nextScanJobId = current === completedId ? null : current;
          scanJobIdRef.current = nextScanJobId;
          return nextScanJobId;
        });
        return;
      }
      if (
        event.event === "privacy-activity" &&
        typeof event.data === "object" &&
        event.data !== null &&
        "message" in event.data &&
        typeof event.data.message === "string"
      ) {
        setActivity(event.data.message);
        return;
      }
      if (event.event === "show-onboarding") {
        setOnboardingOpen(true);
      }
    };

    void onEvent(receiveEvent)
      .then((unlisten) => {
        if (disposed) {
          unlisten();
          return;
        }
        stopEvents = unlisten;
      })
      .catch((error: unknown) => notify(error instanceof Error ? error.message : String(error), "error"));

    void (async () => {
      const [startupResult, settingsResult, helperResult] = await Promise.allSettled([
        startupState(),
        request<unknown>("settings.get"),
        request<unknown>("privileged.status"),
      ]);
      if (disposed) {
        return;
      }
      if (startupResult.status === "rejected") {
        notify(startupResult.reason instanceof Error ? startupResult.reason.message : String(startupResult.reason), "error");
        return;
      }

      const state = startupResult.value;
      setStartupInfo({ version: state.version, trayAvailable: state.tray_available });
      let skippedHelperVersion = "";
      if (settingsResult.status === "fulfilled") {
        const settings = settingsResult.value;
        if (
          typeof settings === "object" &&
          settings !== null &&
          "privileged_helper_prompt_skipped_version" in settings &&
          typeof settings.privileged_helper_prompt_skipped_version === "string"
        ) {
          skippedHelperVersion = settings.privileged_helper_prompt_skipped_version;
        }
      } else {
        notify(settingsResult.reason instanceof Error ? settingsResult.reason.message : String(settingsResult.reason), "error");
      }
      if (helperResult.status === "fulfilled") {
        const result = helperStatusFrom(helperResult.value);
        if (!result) {
          notify(_("The privileged-helper status returned an invalid response."), "error");
        } else {
          setHelperStatus(result);
          if (result.needsOnboarding && skippedHelperVersion !== result.version) {
            setOnboardingOpen(true);
          }
        }
      } else {
        notify(helperResult.reason instanceof Error ? helperResult.reason.message : String(helperResult.reason), "error");
      }
      const scanJob = state.active_jobs?.find((job) => job.startsWith("scanner.scan#"));
      if (scanJob) {
        scanJobIdRef.current = scanJob;
        setScanJobId(scanJob);
      }
    })();

    return () => {
      disposed = true;
      stopEvents?.();
    };
  }, [selectPage, startUpdate]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (!event.ctrlKey || event.altKey || event.metaKey) {
        if (event.key === "Escape") {
          if (openMenu) {
            event.preventDefault();
            setOpenMenu(null);
            (openMenu === "targets" ? targetMenuButtonRef : applicationMenuButtonRef).current?.focus();
            return;
          }
          setAboutOpen(false);
          setCloseOpen(false);
          setScanCloseOpen(false);
          if (!helperInstalling) {
            setOnboardingOpen(false);
          }
        }
        return;
      }
      const key = event.key.toLowerCase();

      const destination = destinations.find((item) => item.shortcut === `Ctrl+${key}`);
      if (destination) {
        event.preventDefault();
        selectPage(destination.id);
        return;
      }
      if (key === "s") {
        event.preventDefault();
        selectPage("scan");
        localEvent("start-scan");
        return;
      }
      if (key === "u") {
        event.preventDefault();
        startUpdate();
        return;
      }
      if (key === ",") {
        event.preventDefault();
        selectPage("preferences");
        return;
      }
      if (key === "q") {
        event.preventDefault();
        void requestQuit();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [helperInstalling, openMenu, requestQuit, selectPage, startUpdate]);

  const renderedPages = useMemo(() => {
    return Array.from(mountedPages).map((page) => {
      const selected = page === activePage;
      if (page === "database") {
        return (
          <section className="content-page" key={page} hidden={!selected} aria-hidden={!selected} aria-label={pageLabel(page)}>
            <Database startRequest={updateStartRequest} />
          </section>
        );
      }
      const Page = pageComponents[page];
      return (
        <section className="content-page" key={page} hidden={!selected} aria-hidden={!selected} aria-label={pageLabel(page)}>
          <Page />
        </section>
      );
    });
  }, [activePage, mountedPages, updateStartRequest]);

  const catalog = activeCatalog();
  const translatorCredits = aboutCredits?.translator_credits?.trim();
  const preferencesOpen = activePage === "preferences";

  return (
    <div className={`app-shell${preferencesOpen ? " preferences-shell" : ""}`}>
      <header className="headerbar">
        {preferencesOpen ? (
          <div className="header-title">
            <button className="button back-button" type="button" onClick={() => selectPage(previousPage)}>
              <Icon name="back" />
              {_("Back")}
            </button>
            <h1>{_("Preferences")}</h1>
          </div>
        ) : null}
        {!preferencesOpen ? (
          <div className="header-actions">
            <div className="application-menu" ref={targetMenuRef}>
              <button
                className="button"
                type="button"
                ref={targetMenuButtonRef}
                aria-haspopup="menu"
                aria-expanded={openMenu === "targets"}
                aria-controls="scan-targets-menu"
                onClick={() => openMenu === "targets" ? setOpenMenu(null) : openMenuWithFocus("targets")}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    openMenuWithFocus("targets");
                  }
                }}
                disabled={scanJobId !== null}
              >
                <Icon name="folder" className="header-action-icon" />
                {_("Scan File or Folder")}
              </button>
              {openMenu === "targets" ? (
                <div
                  className="menu-items"
                  id="scan-targets-menu"
                  role="menu"
                  aria-label={_("Choose scan targets")}
                  onKeyDown={(event) => handleMenuKeyDown(event, "targets")}
                  onBlur={(event) => {
                    if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
                      setOpenMenu(null);
                    }
                  }}
                >
                  <button className="menu-item" role="menuitem" type="button" onClick={() => void chooseScanTargets(false)}>
                    <Icon name="file" />
                    {_("Scan Files")}
                  </button>
                  <button className="menu-item" role="menuitem" type="button" onClick={() => void chooseScanTargets(true)}>
                    <Icon name="folder" />
                    {_("Scan Folders")}
                  </button>
                </div>
              ) : null}
            </div>
            <button className="button primary" type="button" onClick={quickScan} disabled={scanJobId !== null}>
              <Icon name="system" className="header-action-icon" />
              {_("Scan System (Quick Scan)")}
            </button>
            <div className="application-menu" ref={applicationMenuRef}>
              <button
                className="button icon-button"
                type="button"
                ref={applicationMenuButtonRef}
                aria-label={_("Menu")}
                title={_("Menu")}
                aria-haspopup="menu"
                aria-expanded={openMenu === "application"}
                aria-controls="application-menu"
                onClick={() => openMenu === "application" ? setOpenMenu(null) : openMenuWithFocus("application")}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    openMenuWithFocus("application");
                  }
                }}
              >
                <Icon name="menu" />
              </button>
              {openMenu === "application" ? (
                <div
                  className="menu-items"
                  id="application-menu"
                  role="menu"
                  aria-label={_("Application menu")}
                  onKeyDown={(event) => handleMenuKeyDown(event, "application")}
                  onBlur={(event) => {
                    if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
                      setOpenMenu(null);
                    }
                  }}
                >
                  <button className="menu-item" role="menuitem" type="button" onClick={() => { setOpenMenu(null); selectPage("preferences"); }}>
                    <Icon name="settings" />
                    {_("Preferences")}
                  </button>
                  <button className="menu-item" role="menuitem" type="button" onClick={() => { setOpenMenu(null); openAbout(); }}>
                    {_("About")}
                  </button>
                  <button className="menu-item" role="menuitem" type="button" onClick={() => { setOpenMenu(null); void requestQuit(); }}>
                    <Icon name="close" />
                    {_("Quit")}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </header>
      {!preferencesOpen ? (
        <aside className="sidebar" aria-label={_("Main navigation")}>
          <nav className="navigation" aria-label={_("Views")}>
            {destinations.map((destination) => (
              <button
                className="navigation-item"
                key={destination.id}
                type="button"
                aria-current={activePage === destination.id ? "page" : undefined}
                aria-keyshortcuts={destination.shortcut.replace("Ctrl", "Control")}
                title={destination.shortcut}
                onClick={() => selectPage(destination.id)}
              >
                <Icon name={destination.icon} />
                <span className="navigation-label">{pageLabel(destination.id)}</span>
              </button>
            ))}
          </nav>
        </aside>
      ) : null}
      <main className="main-content">
        {activity ? <div className="activity-banner notice" role="status"><span>{activity}</span><button className="button" type="button" onClick={() => setActivity(null)}>{_("Dismiss")}</button></div> : null}
        <div className="page-scroll">{renderedPages}</div>
      </main>
      <div className="toast-region" role="status" aria-live="polite">
        {toasts.map((toast) => <div className={toastClass(toast.type)} key={toast.id}>{toast.message}</div>)}
      </div>
      {helperTrustError ? <HelperTrustErrorDialog rawError={helperTrustError} onClose={() => setHelperTrustError(null)} /> : null}
      {aboutOpen ? <Modal className="about-dialog" title={_("About ClamUI")} onClose={() => setAboutOpen(false)}>
        <p>{_("A native desktop interface for ClamAV.")}</p>
        <dl className="about-details">
          <dt>{_("Version")}</dt><dd>{startupInfo.version || "—"}</dd>
          <dt>{_("Language")}</dt><dd>{catalog?.language ?? "—"}</dd>
          <dt>{_("License")}</dt><dd>MIT License</dd>
        </dl>
        <div className="about-links">
          <button className="button" type="button" onClick={() => openAboutUrl(PROJECT_URL)}>{_("Project website")}</button>
          <button className="button" type="button" onClick={() => openAboutUrl(ISSUES_URL)}>{_("Issue tracker")}</button>
        </div>
        {aboutCreditsError ? <p className="notice error" role="alert">{_(
          "Could not load contributor credits: {error}",
          { error: aboutCreditsError },
        )}</p> : aboutCredits ? <>
          <section className="about-section" aria-labelledby="about-contributors">
            <h3 id="about-contributors">{_("Contributors")}</h3>
            <ul className="about-credit-list">
              {aboutCredits.contributors.map((contributor) => {
                const credit = contributorCredit(contributor);
                return <li key={contributor}>{credit.url ? <button className="about-link" type="button" onClick={() => openAboutUrl(credit.url!)}>{credit.name}</button> : credit.name}</li>;
              })}
            </ul>
          </section>
          {translatorCredits && translatorCredits !== "translator-credits" ? <section className="about-section" aria-labelledby="about-translators">
            <h3 id="about-translators">{_("Translator credits")}</h3>
            <p className="about-translator-credits">{translatorCredits}</p>
          </section> : null}
        </> : <p className="muted" role="status">{_("Loading contributor credits…")}</p>}
      </Modal> : null}
      {closeOpen ? <Modal title={_("Close ClamUI?")} onClose={() => setCloseOpen(false)}>
        <p>{_("Choose whether to keep ClamUI available in the system tray or quit it completely.")}</p>
        <label className="check-row"><input type="checkbox" checked={rememberCloseChoice} onChange={(event) => setRememberCloseChoice(event.currentTarget.checked)} />{_("Remember my choice")}</label>
        <div className="dialog-actions"><button className="button" type="button" onClick={() => setCloseOpen(false)}>{_("Cancel")}</button>{startupInfo.trayAvailable ? <button className="button" type="button" onClick={() => void completeClose("minimize", rememberCloseChoice)}>{_("Minimize to tray")}</button> : null}<button className="button danger" type="button" onClick={() => void completeClose("quit", rememberCloseChoice)}>{_("Quit")}</button></div>
      </Modal> : null}
      {scanCloseOpen ? <Modal title={scanJobId ? _("Scan in Progress") : _("Scan Complete")} onClose={() => setScanCloseOpen(false)}>
        {scanJobId ? <p>{_("A scan is still running. Cancelling it may leave partial results.")}</p> : null}
        <div className="dialog-actions"><button className="button" type="button" onClick={() => setScanCloseOpen(false)}>{scanJobId ? _("Keep Scanning") : _("Cancel")}</button><button className={scanJobId ? "button danger" : "button"} type="button" onClick={() => void cancelScanAndClose()}>{scanJobId ? _("Cancel Scan and Close") : _("Close")}</button></div>
      </Modal> : null}
      {onboardingOpen ? <Modal title={_("Install Privileged Helper")} busy={helperInstalling} onClose={() => void dismissOnboarding()}>
        <p>{helperStatus?.detail ?? _("ClamUI needs its matching privileged helper to save system configuration.")}</p>
        {helperInstalling ? <p className="notice" role="status">{_("Installing privileged helper…")}</p> : null}
        {helperError ? <p className="error" role="alert">{helperError}</p> : null}
        <div className="dialog-actions"><button className="button" type="button" disabled={helperInstalling} onClick={() => void dismissOnboarding()}>{_("Not now")}</button>{helperStatus?.installable ? <button className="button primary" type="button" disabled={helperInstalling} onClick={() => void installHelper()}>{helperInstalling ? _("Installing…") : helperError ? _("Try Again") : _("Install Helper")}</button> : <button className="button primary" type="button" onClick={() => { setOnboardingOpen(false); selectPage("preferences"); }}>{_("Open Preferences")}</button>}</div>
      </Modal> : null}
    </div>
  );
}
