import { useEffect, useState, type JSX } from "react";

import { Icon } from "../Icon";
import { _ } from "../i18n";
import { copyText, notify, request } from "../api";

type ComponentId = "clamscan" | "freshclam" | "clamdscan" | "clamd";
type ComponentState = "installed" | "missing" | "not_installed" | "running" | "stopped" | "unknown";

type ComponentStatus = {
  id: ComponentId;
  name: string;
  status: ComponentState;
  detail: string | null;
  version: string | null;
  install_command: string | null;
};

type ComponentsStatus = {
  components: ComponentStatus[];
  database: { available: boolean; detail: string | null; path: string | null };
};

type InstallCommands = {
  distro: "debian" | "fedora" | "fedora_atomic" | "arch" | "unknown";
  commands: Record<string, string>;
};

type Guide = { distro: string; command: string };

type ComponentDefinition = {
  id: ComponentId;
  guides: Guide[];
};

const DEFINITIONS: ComponentDefinition[] = [
  {
    id: "clamscan",
    guides: [
      { distro: "Ubuntu/Debian", command: "sudo apt install clamav" },
      { distro: "Fedora Workstation", command: "sudo dnf install clamav" },
      { distro: "Fedora Atomic", command: "sudo rpm-ostree install clamav\nsudo systemctl reboot" },
      { distro: "Arch Linux", command: "sudo pacman -S clamav" },
    ],
  },
  {
    id: "freshclam",
    guides: [
      { distro: "Ubuntu/Debian", command: "sudo apt install clamav-freshclam" },
      { distro: "Fedora Workstation", command: "sudo dnf install clamav-freshclam" },
      { distro: "Fedora Atomic", command: "sudo rpm-ostree install clamav-freshclam\nsudo systemctl reboot" },
      { distro: "Arch Linux", command: "sudo pacman -S clamav" },
    ],
  },
  {
    id: "clamdscan",
    guides: [
      { distro: "Ubuntu/Debian", command: "sudo apt install clamav-daemon" },
      { distro: "Fedora Workstation", command: "sudo dnf install clamd" },
      { distro: "Fedora Atomic", command: "sudo rpm-ostree install clamd\nsudo systemctl reboot" },
      { distro: "Arch Linux", command: "sudo pacman -S clamav" },
    ],
  },
  {
    id: "clamd",
    guides: [
      { distro: "Ubuntu/Debian", command: "sudo apt install clamav-daemon\nsudo systemctl enable clamav-daemon\nsudo systemctl start clamav-daemon" },
      { distro: "Fedora Workstation", command: "sudo dnf install clamd clamav-freshclam\nsudo freshclam\nsudo systemctl enable clamd@scan\nsudo systemctl start clamd@scan" },
      { distro: "Fedora Atomic", command: "sudo rpm-ostree install clamd clamav-freshclam\nsudo systemctl reboot" },
      { distro: "Arch Linux", command: "sudo pacman -S clamav\nsudo systemctl enable clamav-daemon\nsudo systemctl start clamav-daemon" },
    ],
  },
];

function componentTitle(id: ComponentId): string {
  switch (id) {
    case "clamscan":
      return _("Virus Scanner");
    case "freshclam":
      return _("Database Updater");
    case "clamdscan":
      return _("Daemon Scanner Client");
    case "clamd":
      return _("Scanner Daemon");
  }
}

function componentDescription(id: ComponentId): string {
  switch (id) {
    case "clamscan":
      return _(
        // Translators: Keep clamscan unchanged; it is the scanner command name.
        "clamscan performs on-demand virus scans.",
      );
    case "freshclam":
      return _(
        // Translators: Keep freshclam unchanged; it is the database-updater command name.
        "freshclam downloads current virus definitions.",
      );
    case "clamdscan":
      return _(
        // Translators: Keep clamdscan and clamd unchanged; they are command and service names.
        "clamdscan uses the clamd daemon for faster scanning.",
      );
    case "clamd":
      return _(
        // Translators: Keep clamd unchanged; it is the daemon service name.
        "clamd is the ClamAV daemon for faster scans.",
      );
  }
}

function componentNote(id: ComponentId): string {
  switch (id) {
    case "clamscan":
      return _(
        // Translators: Keep freshclam unchanged; it is the database-updater command name.
        "After installation, update virus definitions with freshclam.",
      );
    case "freshclam":
      return _(
        // Translators: Keep the embedded shell commands and service name unchanged.
        "Enable the service for automatic updates: sudo systemctl enable clamav-freshclam; sudo systemctl start clamav-freshclam",
      );
    case "clamdscan":
      return _(
        // Translators: Keep clamd unchanged; it is the daemon service name.
        "Requires the clamd daemon to be running.",
      );
    case "clamd":
      return _(
        // Translators: Keep the embedded file path, command, and command-line options unchanged.
        "Configuration is auto-detected in Preferences. On Fedora, ClamUI uses /etc/clamd.d/scan.conf. If clamd is running but unavailable, verify socket permissions and run: clamdscan --config-file=/etc/clamd.d/scan.conf --ping 3",
      );
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function statusLabel(status: ComponentState): string {
  if (status === "installed" || status === "running") return status === "running" ? _("Running") : _("Installed");
  if (status === "stopped") return _("Stopped");
  if (status === "missing" || status === "not_installed") return _("Not installed");
  return _("Unknown");
}

function statusClass(status: ComponentState): string {
  if (status === "installed" || status === "running") return "success";
  if (status === "unknown") return "warning";
  return "error";
}

export default function Components(): JSX.Element {
  const [components, setComponents] = useState<ComponentStatus[]>([]);
  const [installCommands, setInstallCommands] = useState<InstallCommands | null>(null);
  const [expanded, setExpanded] = useState<ComponentId | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const refresh = async (): Promise<void> => {
    setChecking(true);
    setError(null);
    try {
      const [status, commands] = await Promise.all([
        request<ComponentsStatus>("components.status"),
        request<InstallCommands>("components.install_commands"),
      ]);
      setComponents(status.components);
      setInstallCommands(commands);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const copyCommand = async (command: string): Promise<void> => {
    try {
      await copyText(command);
      setCopied(command);
      notify(_("Command copied to clipboard"), "success");
      window.setTimeout(() => setCopied((value) => value === command ? null : value), 1500);
    } catch (copyError) {
      notify(_("Could not copy command: {error}", { error: errorText(copyError) }), "error");
    }
  };
  const detectedDistro = installCommands?.distro;

  return (
    <section className="page" aria-labelledby="components-title">
      <header className="page-header">
        <div>
          <h1 id="components-title">{_("ClamAV components")}</h1>
          <p>{_("Check host-side ClamAV tools and copy distribution-specific setup commands.")}</p>
        </div>
        <button className="button" disabled={checking} onClick={() => void refresh()} type="button">
          <Icon name="refresh" />{checking ? _("Checking…") : _("Refresh status")}
        </button>
      </header>

      <p className="notice warning">{_("Setup instructions are copy-only. ClamUI never installs packages or starts services for you.")}</p>
      {error && <p className="notice error" role="alert">{_("Could not check component status: {error}", { error })}</p>}
      {detectedDistro && detectedDistro !== "unknown" && <p className="muted">{_("Detected host family: {distro}.", { distro: detectedDistro.replace("_", " ") })}</p>}

      <section aria-labelledby="components-status-heading">
        <header className="section-header">
          <div>
            <h2 className="section-heading" id="components-status-heading">{_("Components Status")}</h2>
          </div>
        </header>
        <div className="grouped-list components-list" role="list">
          {DEFINITIONS.map((definition) => {
            const component = components.find((item) => item.id === definition.id);
            const state = component?.status || "unknown";
            const open = expanded === definition.id;
            const preferredCommand = component?.install_command || installCommands?.commands[definition.id === "clamscan" ? "clamav" : definition.id];
            const detailId = `${definition.id}-setup`;
            const title = componentTitle(definition.id);
            const description = componentDescription(definition.id);
            const note = componentNote(definition.id);
            const version = component?.version || (checking ? _("Checking…") : _("Version unavailable"));
            const detail = component?.detail;
            const renderedDetail = detail && detail.trim() === version.trim() ? null : detail;
            return (
              <article className="group-row component-row" key={definition.id} role="listitem">
                <div className="component-summary">
                  <div className="row-copy">
                    <h3 className="row-title">{title}</h3>
                    <p className="row-description inline-metadata">
                      <span className="metadata-item monospace">{definition.id}</span>
                      <span className="metadata-item">{version}</span>
                    </p>
                    {renderedDetail && <p className="row-description">{renderedDetail}</p>}
                  </div>
                  <div className="actions">
                    <span className={`status-badge ${statusClass(state)}`}>{statusLabel(state)}</span>
                    <button aria-controls={detailId} aria-expanded={open} className="button" onClick={() => setExpanded(open ? null : definition.id)} type="button">
                      {open ? _("Hide details") : _("Show details")}
                    </button>
                  </div>
                </div>
                <div className="component-details" hidden={!open} id={detailId}>
                  <p>{description}</p>
                  {preferredCommand && <>
                    <p className="muted">{_("Suggested for the detected system:")}</p>
                    <Command command={preferredCommand} copied={copied === preferredCommand} onCopy={copyCommand} />
                  </>}
                  <p className="muted">{_("Commands for supported distributions:")}</p>
                  {definition.guides.map((guide) => (
                    <div className="group-row" key={`${definition.id}-${guide.distro}`}>
                      <p className="row-title">{guide.distro}</p>
                      <Command command={guide.command} copied={copied === guide.command} onCopy={copyCommand} />
                    </div>
                  ))}
                  {note && <p className="row-description">{note}</p>}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </section>
  );
}

function Command({ command, copied, onCopy }: { command: string; copied: boolean; onCopy: (command: string) => Promise<void> }): JSX.Element {
  return <div className="row"><pre className="monospace">{command}</pre><button className="button" onClick={() => void onCopy(command)} type="button"><Icon name="copy" />{copied ? _("Copied") : _("Copy")}</button></div>;
}
