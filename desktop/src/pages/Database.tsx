import { useCallback, useEffect, useRef, useState, type JSX } from "react";

import { _, ngettext } from "../i18n";
import { notify, onEvent, request } from "../api";
import { Icon } from "../Icon";
import { Modal } from "../Modal";

type FreshclamStatus = {
  installed: boolean;
  version_or_error?: string | null;
  path?: string | null;
};

type ServiceStatus = {
  status: "running" | "stopped" | "not_found" | "unknown";
  pid?: string | null;
};

type DatabaseStatus = {
  available: boolean;
  detail?: string | null;
  path?: string | null;
  age_days?: number | null;
  updated_at?: string | null;
};

type UpdaterStatus = {
  freshclam: FreshclamStatus;
  service: ServiceStatus;
  database?: DatabaseStatus;
};

type UpdateResult = {
  status: "success" | "up_to_date" | "error" | "cancelled";
  stdout: string;
  stderr: string;
  exit_code: number;
  databases_updated: number;
  error_message: string | null;
  update_method: "service_signal" | "manual";
  updated_databases: string[];
  up_to_date_databases: string[];
  rate_limited_databases: Record<string, string | null>;
};

type DatabaseProps = {
  startRequest?: number;
};


function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function serviceDescription(service: ServiceStatus): string {
  switch (service.status) {
    case "running":
      return service.pid ? _("Active (PID {pid})", { pid: service.pid }) : _("Active");
    case "stopped":
      return _("Installed but stopped");
    case "not_found":
      return _("No freshclam service detected; updates run manually");
    default:
      return _("Service state could not be determined");
  }
}

function databaseDescription(database: DatabaseStatus | undefined): JSX.Element {
  if (!database) return <span className="metadata-item">{_("Database freshness information is unavailable")}</span>;
  if (!database.available) return <span className="metadata-item">{database.detail || _("No readable virus database was found")}</span>;
  const freshness = typeof database.age_days === "number"
    ? ngettext("{count} day old", "{count} days old", database.age_days, { count: database.age_days })
    : database.updated_at
      ? _("last updated {timestamp}", { timestamp: database.updated_at })
      : _("freshness could not be determined");
  return <span className="inline-metadata"><span className="metadata-item">{database.detail || _("Virus database available")}</span><span className="metadata-item">{freshness}</span></span>;
}

function formatResultSummary(result: UpdateResult): string {
  const lines = [
    _("Status: {status}", { status: result.status }),
    _("Method: {method}", { method: result.update_method === "service_signal" ? _("freshclam service signal accepted") : _("manual freshclam") }),
    _("Exit code: {code}", { code: result.exit_code }),
  ];
  if (result.databases_updated > 0) lines.push(ngettext("Database updated: {count}", "Databases updated: {count}", result.databases_updated, { count: result.databases_updated }));
  if (result.updated_databases.length) lines.push(_("Updated: {databases}", { databases: result.updated_databases.join(", ") }));
  if (result.up_to_date_databases.length) lines.push(_("Already current: {databases}", { databases: result.up_to_date_databases.join(", ") }));
  for (const [database, cooldown] of Object.entries(result.rate_limited_databases)) {
    lines.push(_("Rate limited: {database}{cooldown}", { database, cooldown: cooldown ? ` ${_("until")} ${cooldown}` : "" }));
  }
  if (result.update_method === "service_signal" && result.status === "success") {
    lines.push(_("The service accepted the signal; it performs the update asynchronously. Check its logs for completion."));
  }
  if (result.error_message) lines.push(_("Error: {error}", { error: result.error_message }));
  return lines.join("\n");
}

function formatFreshclamOutput(result: UpdateResult): string {
  const lines: string[] = [];
  if (result.stdout) lines.push(_("freshclam output:"), result.stdout);
  if (result.stderr) {
    if (lines.length) lines.push("");
    lines.push(_("Error output:"), result.stderr);
  }
  return lines.join("\n");
}

export default function Database({ startRequest }: DatabaseProps): JSX.Element {
  const [status, setStatus] = useState<UpdaterStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [progress, setProgress] = useState<string[]>([]);
  const [result, setResult] = useState<UpdateResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [eventsReady, setEventsReady] = useState(false);
  const [forceConfirmation, setForceConfirmation] = useState(false);
  const sequence = useRef(0);
  const currentOperationId = useRef<string | null>(null);
  const consumedStartRequest = useRef<number | null>(null);

  const refreshStatus = useCallback(async (): Promise<void> => {
    setLoadingStatus(true);
    setStatusError(null);
    try {
      setStatus(await request<UpdaterStatus>("updater.status"));
    } catch (error) {
      setStatusError(errorText(error));
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | undefined;
    void onEvent((event) => {
      if (!active) return;
      if (event.event === "update-progress") {
        const data = event.data;
        const updateId = typeof data === "object" && data !== null && "id" in data && typeof data.id === "string"
          ? data.id
          : null;
        const line = typeof data === "object" && data !== null && "line" in data && typeof data.line === "string"
          ? data.line
          : null;
        if (updateId !== currentOperationId.current || line === null) return;
        setProgress((lines) => [...lines, line]);
      }
      if (event.event === "update-complete") {
        const data = event.data;
        if (
          typeof data !== "object" ||
          data === null ||
          !("id" in data) ||
          !("result" in data) ||
          typeof data.id !== "string" ||
          data.id !== currentOperationId.current ||
          typeof data.result !== "object" ||
          data.result === null ||
          !("status" in data.result) ||
          !("stdout" in data.result) ||
          !("stderr" in data.result) ||
          !("exit_code" in data.result) ||
          !("databases_updated" in data.result) ||
          !("update_method" in data.result) ||
          !("error_message" in data.result) ||
          !("updated_databases" in data.result) ||
          !("up_to_date_databases" in data.result) ||
          !("rate_limited_databases" in data.result) ||
          typeof data.result.status !== "string" ||
          typeof data.result.stdout !== "string" ||
          typeof data.result.stderr !== "string" ||
          typeof data.result.exit_code !== "number" ||
          typeof data.result.databases_updated !== "number" ||
          typeof data.result.update_method !== "string" ||
          (data.result.error_message !== null && typeof data.result.error_message !== "string") ||
          !Array.isArray(data.result.updated_databases) ||
          !Array.isArray(data.result.up_to_date_databases) ||
          !data.result.updated_databases.every((database) => typeof database === "string") ||
          !data.result.up_to_date_databases.every((database) => typeof database === "string") ||
          typeof data.result.rate_limited_databases !== "object" ||
          data.result.rate_limited_databases === null ||
          Array.isArray(data.result.rate_limited_databases) ||
          !Object.values(data.result.rate_limited_databases).every((cooldown) => cooldown === null || typeof cooldown === "string")
        ) return;
        setResult(data.result as UpdateResult);
      }
    }).then((cleanup) => {
      if (active) {
        unlisten = cleanup;
        setEventsReady(true);
      } else cleanup();
    }).catch((error) => {
      if (active) setActionError(_("Could not listen for update progress: {error}", { error: errorText(error) }));
    });
    return () => {
      active = false;
      unlisten?.();
    };
  }, []);

  const runUpdate = useCallback(async (force: boolean): Promise<void> => {
    if (currentOperationId.current !== null) return;
    const id = crypto.randomUUID();
    const run = ++sequence.current;
    currentOperationId.current = id;
    setRunningId(id);
    setProgress([force ? _("Force update requested: preserving existing databases until replacement succeeds.") : _("Update requested.")]);
    setResult(null);
    setActionError(null);
    try {
      const update = await request<UpdateResult>("updater.update", { id, force, prefer_service: !force });
      if (sequence.current !== run) return;
      setResult(update);
      if (update.status === "error") notify(update.error_message || _("Database update failed"), "error");
      else if (update.status === "cancelled") notify(_("Database update cancelled"), "warning");
      else if (update.update_method === "service_signal") notify(_("Update signal accepted by the freshclam service"), "info");
      else notify(update.status === "success" ? _("Database update completed") : _("Database is already up to date"), "success");
      await refreshStatus();
    } catch (error) {
      if (sequence.current === run) setActionError(errorText(error));
    } finally {
      if (sequence.current === run) {
        currentOperationId.current = null;
        setRunningId(null);
      }
    }
  }, [refreshStatus]);

  useEffect(() => {
    if (
      typeof startRequest !== "number" ||
      !Number.isFinite(startRequest) ||
      startRequest <= 0 ||
      consumedStartRequest.current === startRequest
    ) return;
    consumedStartRequest.current = startRequest;
    if (currentOperationId.current === null) void runUpdate(false);
  }, [runUpdate, startRequest]);

  const cancelUpdate = async (): Promise<void> => {
    if (!runningId) return;
    try {
      const response = await request<{ cancelled: boolean }>("updater.cancel", { id: runningId });
      if (!response.cancelled) setActionError(_("No matching update operation could be cancelled."));
      else notify(_("Cancellation requested; waiting for freshclam to stop."), "warning");
    } catch (error) {
      setActionError(errorText(error));
    }
  };

  const freshclamReady = status?.freshclam.installed === true;

  return (
    <section className="page" aria-labelledby="database-title">
      <header className="page-header">
        <div>
          <h1 id="database-title">{_("Database")}</h1>
          <p>{_("Update ClamAV virus definitions and inspect their current state.")}</p>
        </div>
        <button className="button" disabled={loadingStatus} onClick={() => void refreshStatus()} type="button">
          <Icon name="refresh" />{loadingStatus ? _("Checking…") : _("Refresh status")}
        </button>
      </header>

      {statusError && <p className="notice error" role="alert">{_("Could not read updater status: {error}", { error: statusError })}</p>}
      {actionError && <p className="notice error" role="alert">{actionError}</p>}

      <section aria-labelledby="definition-status-heading">
        <header className="section-header">
          <div><h2 className="section-heading" id="definition-status-heading">{_("Virus definitions")}</h2></div>
        </header>
        <div className="grouped-list">
          <div className="group-row">
            <div className="row-copy">
              <strong className="row-title">freshclam</strong>
              <p className="row-description">{status?.freshclam.version_or_error || (loadingStatus ? _("Checking freshclam…") : _("No freshclam status returned"))}</p>
              {status?.freshclam.path && <p className="row-description monospace">{status.freshclam.path}</p>}
            </div>
            <span className={`status-badge ${freshclamReady ? "success" : "error"}`}>{freshclamReady ? _("Available") : _("Unavailable")}</span>
          </div>
          <div className="group-row">
            <div className="row-copy"><strong className="row-title">{_("Update service")}</strong></div>
            <span className={`status-badge ${status?.service.status === "running" ? "success" : "warning"}`}>{status ? serviceDescription(status.service) : _("Checking…")}</span>
          </div>
          <div className="group-row">
            <div className="row-copy">
              <strong className="row-title">{_("Database freshness")}</strong>
              {status?.database?.path && <p className="row-description monospace">{status.database.path}</p>}
            </div>
            <span className={`status-badge ${status?.database?.available ? "success" : "warning"}`}>{databaseDescription(status?.database)}</span>
          </div>
        </div>
      </section>

      <section aria-labelledby="update-database-heading">
        <header className="section-header">
          <div>
            <h2 className="section-heading" id="update-database-heading">{_("Update database")}</h2>
            <p>{_("A normal update asks an active freshclam service to update when possible. A force update bypasses the service and stages replacements before promoting them, restoring prior databases if that replacement fails.")}</p>
          </div>
        </header>
        <div className="grouped-list">
          <div className="group-row">
            <div className="actions">
              <button className="button primary" disabled={!freshclamReady || !eventsReady || !!runningId} onClick={() => void runUpdate(false)} type="button">{runningId ? _("Updating…") : _("Update database")}</button>
              <button className="button" disabled={!freshclamReady || !eventsReady || !!runningId} onClick={() => setForceConfirmation(true)} type="button">{_("Force update")}</button>
              {runningId && <button className="button danger" onClick={() => void cancelUpdate()} type="button">{_("Cancel")}</button>}
            </div>
          </div>
          {!freshclamReady && !loadingStatus && <p className="notice warning">{_("Install freshclam before requesting database updates.")}</p>}
          {!eventsReady && !loadingStatus && <p className="notice warning">{_("Preparing the update progress listener…")}</p>}
        </div>
      </section>

      <section aria-labelledby="update-log-heading">
        <header className="section-header">
          <div><h2 className="section-heading" id="update-log-heading">{_("Update log")}</h2></div>
        </header>
        <div className="grouped-list">
          <div className="database-update-log">
            {progress.length > 0 && <pre className={`monospace database-update-text${result ? "" : " database-update-terminal"}`}>{progress.join("\n")}</pre>}
            {result ? <>
              <pre className="monospace database-update-text">{formatResultSummary(result)}</pre>
              {(result.stdout || result.stderr) && <pre className="monospace database-update-text database-update-terminal">{formatFreshclamOutput(result)}</pre>}
            </> : !runningId && progress.length === 0 && <p className="muted">{_("No update has been requested in this session.")}</p>}
          </div>
        </div>
      </section>

      {forceConfirmation && <Modal onClose={() => setForceConfirmation(false)} title={_("Force database update?")}>
        <p>{_("This bypasses the freshclam service and stages replacement databases. Existing definitions remain available until a replacement succeeds; they are restored if promotion fails.")}</p>
        <div className="button-row">
          <button className="button" onClick={() => setForceConfirmation(false)} type="button">{_("Cancel")}</button>
          <button className="button danger" onClick={() => { setForceConfirmation(false); void runUpdate(true); }} type="button">{_("Force update")}</button>
        </div>
      </Modal>}
    </section>
  );
}
