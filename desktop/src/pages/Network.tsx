import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from "react";

import { copyText, networkSnapshot, notify, openExternal, type NetworkEndpoint, type NetworkSnapshot, type NetworkSocket } from "../api";
import { Icon } from "../Icon";
import { _, ngettext } from "../i18n";
import { Modal } from "../Modal";

type SocketFilter = "all" | "listener" | "connection";
type VirusTotalConfirmation = { address: string; url: string };

const PAGE_SIZE = 50;
const VIRUSTOTAL_PREFIX = "https://www.virustotal.com/gui/ip-address/";
const VIRUSTOTAL_SUFFIX = "/detection";
const DECIMAL = /^\d+$/;
const HEX_HEXTET = /^[0-9a-fA-F]{1,4}$/;

function isCanonicalIpAddress(address: string): boolean {
  if (!address || address.includes("%") || address.includes("[") || address.includes("]")) {
    return false;
  }
  const ipv4 = address.split(".");
  if (ipv4.length === 4) {
    return ipv4.every((part) => DECIMAL.test(part) && Number(part) <= 255 && String(Number(part)) === part);
  }
  if (address.includes(".") || !address.includes(":")) {
    return false;
  }
  const halves = address.split("::");
  if (halves.length > 2) {
    return false;
  }
  const hextets = halves.flatMap((half) => half ? half.split(":") : []);
  if (!hextets.every((hextet) => HEX_HEXTET.test(hextet))) {
    return false;
  }
  return halves.length === 2 ? hextets.length < 8 : hextets.length === 8;
}
function isVirusTotalIpAddress(address: string): boolean {
  if (!isCanonicalIpAddress(address)) {
    return false;
  }
  const ipv4 = address.split(".");
  if (ipv4.length === 4) {
    const [first, second, third] = ipv4.map(Number);
    return first !== 0 &&
      first !== 10 &&
      first !== 127 &&
      first < 224 &&
      !(first === 100 && second >= 64 && second <= 127) &&
      !(first === 169 && second === 254) &&
      !(first === 172 && second >= 16 && second <= 31) &&
      !(first === 192 && ((second === 0 && (third === 0 || third === 2)) || (second === 88 && third === 99) || second === 168)) &&
      !(first === 198 && ((second === 18 || second === 19) || (second === 51 && third === 100))) &&
      !(first === 203 && second === 0 && third === 113);
  }
  const halves = address.split("::");
  const left = halves[0] ? halves[0].split(":") : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const hextets = [...left, ...Array(8 - left.length - right.length).fill("0"), ...right].map((hextet) => Number.parseInt(hextet, 16));
  const [first, second] = hextets;
  return first >= 0x2000 &&
    first < 0x4000 &&
    !(first === 0x2001 && second <= 0x01ff) &&
    !(first === 0x2001 && second === 0x0db8) &&
    first !== 0x2002 &&
    first !== 0x3ffe &&
    !(first === 0x3fff && second <= 0x0fff);
}



function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function endpointFrom(value: unknown): NetworkEndpoint | null {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !("address" in value) ||
    !("port" in value) ||
    !("virustotal_url" in value) ||
    typeof value.address !== "string" ||
    (value.port !== null && (typeof value.port !== "number" || !Number.isSafeInteger(value.port) || value.port < 0 || value.port > 65535)) ||
    (value.virustotal_url !== null && typeof value.virustotal_url !== "string")
  ) {
    return null;
  }
  return { address: value.address, port: value.port, virustotal_url: value.virustotal_url };
}

function socketFrom(value: unknown): NetworkSocket | null {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !("protocol" in value) ||
    !("kind" in value) ||
    !("state" in value) ||
    !("local" in value) ||
    !("remote" in value) ||
    !("processes" in value) ||
    (value.protocol !== "tcp" && value.protocol !== "udp") ||
    (value.kind !== "listener" && value.kind !== "connection") ||
    typeof value.state !== "string" ||
    !Array.isArray(value.processes)
  ) {
    return null;
  }
  const local = endpointFrom(value.local);
  const remote = value.remote === null ? null : endpointFrom(value.remote);
  if (!local || (value.remote !== null && !remote)) {
    return null;
  }
  const processes = [];
  for (const process of value.processes) {
    if (
      typeof process !== "object" ||
      process === null ||
      Array.isArray(process) ||
      !("name" in process) ||
      !("pid" in process) ||
      typeof process.name !== "string" ||
      typeof process.pid !== "number" ||
      !Number.isSafeInteger(process.pid) ||
      process.pid <= 0
    ) {
      return null;
    }
    processes.push({ name: process.name, pid: process.pid });
  }
  return { protocol: value.protocol, state: value.state, kind: value.kind, local, remote, processes };
}

function snapshotFrom(value: unknown): NetworkSnapshot | null {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !("status" in value) ||
    !("captured_at" in value) ||
    !("sockets" in value) ||
    !("unparsed_lines" in value) ||
    !("limited" in value) ||
    !("message" in value) ||
    (value.status !== "available" && value.status !== "partial" && value.status !== "unavailable") ||
    typeof value.captured_at !== "string" ||
    !Array.isArray(value.sockets) ||
    typeof value.unparsed_lines !== "number" ||
    !Number.isSafeInteger(value.unparsed_lines) ||
    value.unparsed_lines < 0 ||
    typeof value.limited !== "boolean" ||
    (value.message !== null && typeof value.message !== "string")
  ) {
    return null;
  }
  const sockets = [];
  for (const socket of value.sockets) {
    const parsed = socketFrom(socket);
    if (!parsed) {
      return null;
    }
    sockets.push(parsed);
  }
  return {
    status: value.status,
    captured_at: value.captured_at,
    sockets,
    unparsed_lines: value.unparsed_lines,
    limited: value.limited,
    message: value.message,
  };
}

function formatEndpoint(endpoint: NetworkEndpoint): string {
  if (endpoint.port === null) {
    return endpoint.address;
  }
  return endpoint.address.includes(":") ? `[${endpoint.address}]:${endpoint.port}` : `${endpoint.address}:${endpoint.port}`;
}

function virustotalUrl(endpoint: NetworkEndpoint): string | null {
  if (!endpoint.virustotal_url || !isVirusTotalIpAddress(endpoint.address)) {
    return null;
  }
  const expected = `${VIRUSTOTAL_PREFIX}${endpoint.address}${VIRUSTOTAL_SUFFIX}`;
  if (endpoint.virustotal_url !== expected) {
    return null;
  }
  try {
    const parsed = new URL(endpoint.virustotal_url);
    return parsed.protocol === "https:" &&
      parsed.hostname === "www.virustotal.com" &&
      parsed.port === "" &&
      parsed.username === "" &&
      parsed.password === "" &&
      parsed.search === "" &&
      parsed.hash === "" &&
      parsed.pathname === `/gui/ip-address/${endpoint.address}/detection`
      ? expected
      : null;
  } catch {
    return null;
  }
}

function socketMatches(socket: NetworkSocket, query: string): boolean {
  if (!query) {
    return true;
  }
  const details = [
    socket.protocol,
    socket.kind,
    socket.state,
    formatEndpoint(socket.local),
    socket.remote ? formatEndpoint(socket.remote) : "",
    ...socket.processes.flatMap((process) => [process.name, String(process.pid)]),
  ].join(" ").toLocaleLowerCase();
  return details.includes(query);
}

function kindLabel(kind: NetworkSocket["kind"]): string {
  return kind === "listener" ? _("Listening and bound") : _("Connection");
}

function Endpoint({ endpoint, label, onVirusTotal }: { endpoint: NetworkEndpoint | null; label: string; onVirusTotal: (endpoint: NetworkEndpoint) => void }): JSX.Element {
  const formatted = endpoint ? formatEndpoint(endpoint) : "";
  const reportUrl = endpoint ? virustotalUrl(endpoint) : null;
  const copyLabel = _(
    // Translators: Preserve the {label} placeholder. It is the translated endpoint label, such as “Local address”.
    "Copy {label}",
    { label },
  );
  const virusTotalUnavailableReason = _("VirusTotal reports are unavailable for private, special, scoped, or wildcard addresses.");
  const copy = async (): Promise<void> => {
    if (!endpoint) {
      return;
    }
    try {
      await copyText(formatted);
      notify(_("Address copied to clipboard"), "success");
    } catch (error) {
      notify(_(
        // Translators: Preserve the {error} placeholder. It is a technical clipboard error.
        "Could not copy address: {error}",
        { error: errorText(error) },
      ), "error");
    }
  };

  return <div className="network-endpoint">
    <span className="network-endpoint-label">{label}</span>
    {endpoint ? <div className="network-endpoint-value">
      <code className="monospace network-address">{formatted}</code>
      <div className="network-endpoint-actions">
        <button className="button icon-button network-icon-action" onClick={() => void copy()} type="button" title={copyLabel} aria-label={copyLabel}>
          <Icon name="copy" />
        </button>
        {reportUrl ? <button className="button icon-button network-icon-action" onClick={() => onVirusTotal(endpoint)} type="button" title={_("Open VirusTotal IP report")} aria-label={_("Open VirusTotal IP report")} data-network-vt-open="true">
          <Icon name="external-link" />
        </button> : <span className="network-tooltip-wrapper" title={virusTotalUnavailableReason}><button className="button icon-button network-icon-action" disabled type="button" aria-label={virusTotalUnavailableReason}><Icon name="external-link" /></button></span>}
      </div>
    </div> : <div className="network-endpoint-value">
      <span className="muted">{_("No remote address observed")}</span>
      <button className="button icon-button network-icon-action" disabled type="button" title={_("No remote address is available to copy.")} aria-label={_("No remote address is available to copy.")}>
        <Icon name="copy" />
      </button>
    </div>}
  </div>;
}

function SocketRow({ socket, onVirusTotal }: { socket: NetworkSocket; onVirusTotal: (endpoint: NetworkEndpoint) => void }): JSX.Element {
  return <article className="network-row" role="listitem">
    <div className="network-socket-summary">
      <div className="network-badges">
        <span className="badge">{socket.protocol.toUpperCase()}</span>
        <span className="badge">{kindLabel(socket.kind)}</span>
        <span className="badge">{socket.state}</span>
      </div>
      <div className="network-endpoints">
        <Endpoint endpoint={socket.local} label={_("Local address")} onVirusTotal={onVirusTotal} />
        <Endpoint endpoint={socket.remote} label={_("Remote address")} onVirusTotal={onVirusTotal} />
      </div>
    </div>
    <div className="network-processes">
      <span className="network-endpoint-label">{_("Process")}</span>
      {socket.processes.length > 0 ? <ul className="network-process-list">
        {socket.processes.map((process) => <li key={`${process.pid}-${process.name}`}><span className="network-process-name">{process.name}</span><span className="network-pid">{_(
          // Translators: Preserve the {pid} placeholder. It is a numeric process ID.
          "PID {pid}",
          { pid: process.pid },
        )}</span></li>)}
      </ul> : <span className="muted">{_("Process information unavailable")}</span>}
    </div>
  </article>;
}

export default function Network(): JSX.Element {
  const [snapshot, setSnapshot] = useState<NetworkSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<SocketFilter>("all");
  const [search, setSearch] = useState("");
  const [shown, setShown] = useState(PAGE_SIZE);
  const [confirmation, setConfirmation] = useState<VirusTotalConfirmation | null>(null);
  const [openingReport, setOpeningReport] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const requestSequence = useRef(0);

  const refresh = useCallback(async (): Promise<void> => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    try {
      const response = snapshotFrom(await networkSnapshot());
      if (requestSequence.current !== sequence) {
        return;
      }
      if (!response) {
        throw new Error("invalid network snapshot");
      }
      setSnapshot(response);
      setShown(PAGE_SIZE);
    } catch {
      if (requestSequence.current === sequence) {
        setSnapshot(null);
        setError(_("Could not load network connections. Try again."));
      }
    } finally {
      if (requestSequence.current === sequence) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => {
      requestSequence.current += 1;
    };
  }, [refresh]);

  const normalizedSearch = search.trim().toLocaleLowerCase();
  const sockets = useMemo(() => snapshot?.sockets.filter((socket) => (
    (filter === "all" || socket.kind === filter) && socketMatches(socket, normalizedSearch)
  )) ?? [], [filter, normalizedSearch, snapshot]);
  const visibleSockets = sockets.slice(0, shown);
  const isUnavailable = snapshot?.status === "unavailable";

  const selectVirusTotal = (endpoint: NetworkEndpoint): void => {
    const url = virustotalUrl(endpoint);
    if (!url) {
      return;
    }
    setReportError(null);
    setConfirmation({ address: endpoint.address, url });
  };

  const openVirusTotal = async (): Promise<void> => {
    if (!confirmation) {
      return;
    }
    const expected = `${VIRUSTOTAL_PREFIX}${confirmation.address}${VIRUSTOTAL_SUFFIX}`;
    if (confirmation.url !== expected || virustotalUrl({ address: confirmation.address, port: null, virustotal_url: confirmation.url }) !== expected) {
      setReportError(_("The VirusTotal report address was invalid."));
      return;
    }
    setOpeningReport(true);
    setReportError(null);
    try {
      await openExternal(expected);
      setConfirmation(null);
    } catch (openError) {
      setReportError(_(
        // Translators: Preserve the {error} placeholder. It is a technical browser-opening error.
        "Could not open VirusTotal: {error}",
        { error: errorText(openError) },
      ));
    } finally {
      setOpeningReport(false);
    }
  };

  const resetFilters = (nextFilter: SocketFilter): void => {
    setFilter(nextFilter);
    setShown(PAGE_SIZE);
  };

  return <main className="page network-page" aria-labelledby="network-title">
    <header className="page-header">
      <div>
        <h1 id="network-title">{_("Network Connections")}</h1>
        <p>{_("View the current listening ports and socket peers from one local snapshot.")}</p>
      </div>
      <button className="button" disabled={loading} onClick={() => void refresh()} type="button" data-network-refresh="true">
        <Icon name="refresh" />{loading ? (snapshot ? _("Refreshing…") : _("Loading…")) : _("Refresh")}
      </button>
    </header>

    {loading && !snapshot ? <div className="status-banner" role="status">{_("Loading network connections…")}</div> : null}
    {error ? <section className="network-state error-banner" role="alert"><span>{error}</span><button className="button" onClick={() => void refresh()} type="button">{_("Retry")}</button></section> : null}
    {isUnavailable ? <section className="network-state notice warning" role="status"><span>{_("Network information is unavailable. Check that the system socket tool is installed and try again.")}</span><button className="button" disabled={loading} onClick={() => void refresh()} type="button">{_("Retry")}</button></section> : null}

    {snapshot && !isUnavailable ? <>
      {(snapshot.status === "partial" || snapshot.limited) ? <p className="notice warning" role="status">{snapshot.limited ? _("The socket list was limited. This snapshot may be incomplete.") : _("Some socket records could not be read. This snapshot may be incomplete.")}</p> : null}
      <p className="network-capture-time muted">{_(
        // Translators: Preserve the {time} placeholder. It is the native UTC/ISO snapshot timestamp.
        "Captured at {time}",
        { time: snapshot.captured_at },
      )}</p>
      <div className="network-toolbar">
        <div className="segmented-control" aria-label={_("Network socket filter")}>
          <button aria-pressed={filter === "all"} onClick={() => resetFilters("all")} type="button" data-network-filter="all">{_("All")}</button>
          <button aria-pressed={filter === "listener"} onClick={() => resetFilters("listener")} type="button" data-network-filter="listener">{_("Listening and bound")}</button>
          <button aria-pressed={filter === "connection"} onClick={() => resetFilters("connection")} type="button" data-network-filter="connection">{_("Connections")}</button>
        </div>
        <label className="search-field network-search"><span className="sr-only">{_("Search sockets")}</span><input value={search} onChange={(event) => { setSearch(event.currentTarget.value); setShown(PAGE_SIZE); }} placeholder={_("Search address, port, process, or PID")} type="search" /></label>
      </div>
      <p className="network-permissions-notice notice">{_("Process ownership depends on system permissions. Unavailable process information does not mean that no process owns the socket.")}</p>
      {snapshot.sockets.length === 0 ? <div className="grouped-list empty-state">{snapshot.status === "partial" || snapshot.unparsed_lines > 0 ? _("No socket records could be read from this snapshot.") : _("No network sockets were found in this snapshot.")}</div> : sockets.length === 0 ? <div className="grouped-list empty-state">{_("No sockets match the current filters.")}</div> : <section className="grouped-list network-list" aria-label={_("Network sockets")} role="list">
        {visibleSockets.map((socket, index) => <SocketRow key={`${socket.protocol}-${socket.kind}-${socket.state}-${formatEndpoint(socket.local)}-${socket.remote ? formatEndpoint(socket.remote) : "none"}-${index}`} socket={socket} onVirusTotal={selectVirusTotal} />)}
      </section>}
      {sockets.length > 0 ? <div className="network-pagination"><p>{ngettext(
        // Translators: Preserve the {shown} and {count} placeholders. Both are socket counts.
        "Showing {shown} of {count} matching socket",
        "Showing {shown} of {count} matching sockets",
        sockets.length,
        { shown: visibleSockets.length, count: sockets.length },
      )}</p>{shown < sockets.length ? <button className="button" onClick={() => setShown((current) => Math.min(current + PAGE_SIZE, sockets.length))} type="button" data-network-load-more="true">{_("Load More")}</button> : null}</div> : null}
    </> : null}

    {confirmation ? <Modal title={_("Open VirusTotal IP report")} onClose={() => { if (!openingReport) setConfirmation(null); }} busy={openingReport}>
      <p>{_(
        // Translators: Preserve the {address} placeholder; it is an IP address that will be disclosed to VirusTotal through the browser.
        "Opening this report sends the IP address {address} to VirusTotal through your browser. Do not check sensitive IP addresses.",
        { address: confirmation.address },
      )}</p>
      <p>{_("No port, process information, or API key is sent by ClamUI.")}</p>
      {reportError ? <p className="error" role="alert">{reportError}</p> : null}
      <div className="dialog-actions"><button className="button" disabled={openingReport} onClick={() => setConfirmation(null)} type="button" data-network-vt-cancel="true">{_("Cancel")}</button><button className="button primary" disabled={openingReport} onClick={() => void openVirusTotal()} type="button" data-network-vt-confirm="true"><Icon name="external-link" />{openingReport ? _("Opening…") : _("Open in browser")}</button></div>
    </Modal> : null}
  </main>;
}
