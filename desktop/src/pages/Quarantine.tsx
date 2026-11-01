import { useCallback, useEffect, useRef, useState } from "react";
import { notify, onEvent, request } from "../api";
import { Icon } from "../Icon";
import { _, ngettext } from "../i18n";
import { Modal } from "../Modal";
type QuarantineEntry = {
  id: number;
  originalPath: string;
  quarantinePath: string;
  threatName: string;
  detectionDate: string;
  fileSize: number;
  fileHash: string;
  originalPermissions: number;
};

type QuarantineList = { entries: QuarantineEntry[]; totalSize: number; entryCount: number };
type QuarantineResult = { status: string; errorMessage?: string };

const PAGE_SIZE = 20;

function fieldValue(object: object, snake: string, camel: string): unknown {
  if (Object.prototype.hasOwnProperty.call(object, snake)) return Reflect.get(object, snake);
  if (Object.prototype.hasOwnProperty.call(object, camel)) return Reflect.get(object, camel);
  return undefined;
}

function parseEntry(value: unknown): QuarantineEntry | null {
  if (!value || typeof value !== "object") return null;
  const id = fieldValue(value, "id", "id");
  const originalPath = fieldValue(value, "original_path", "originalPath");
  const quarantinePath = fieldValue(value, "quarantine_path", "quarantinePath");
  const threatName = fieldValue(value, "threat_name", "threatName");
  const detectionDate = fieldValue(value, "detection_date", "detectionDate");
  const fileSize = fieldValue(value, "file_size", "fileSize");
  const fileHash = fieldValue(value, "file_hash", "fileHash");
  const originalPermissions = fieldValue(value, "original_permissions", "originalPermissions");
  if (typeof id !== "number" || typeof originalPath !== "string" || typeof quarantinePath !== "string" || typeof threatName !== "string" || typeof detectionDate !== "string" || typeof fileSize !== "number" || typeof fileHash !== "string" || typeof originalPermissions !== "number") return null;
  return { id, originalPath, quarantinePath, threatName, detectionDate, fileSize, fileHash, originalPermissions };
}

function parseList(value: unknown): QuarantineList | null {
  if (!value || typeof value !== "object") return null;
  const rawEntries = fieldValue(value, "entries", "entries");
  const totalSize = fieldValue(value, "total_size", "totalSize");
  const entryCount = fieldValue(value, "entry_count", "entryCount");
  if (!Array.isArray(rawEntries) || typeof totalSize !== "number" || typeof entryCount !== "number") return null;
  const entries = rawEntries.flatMap((entry) => {
    const parsed = parseEntry(entry);
    return parsed ? [parsed] : [];
  });
  if (entries.length !== rawEntries.length) return null;
  return { entries, totalSize, entryCount };
}

function parseResult(value: unknown): QuarantineResult | null {
  if (!value || typeof value !== "object") return null;
  const status = fieldValue(value, "status", "status");
  const errorMessage = fieldValue(value, "error_message", "errorMessage");
  if (typeof status !== "string") return null;
  return { status, ...(typeof errorMessage === "string" ? { errorMessage } : {}) };
}

function readableError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
function formatDate(value: string): string {
  const date = new Date(value.replace(/(\.\d{3})\d+(?=(?:Z|[+-]\d{2}:?\d{2})?$)/, "$1"));
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}


export default function Quarantine() {
  const [data, setData] = useState<QuarantineList | null>(null);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [showAll, setShowAll] = useState(false);
  const [banner, setBanner] = useState<{ message: string; type: "success" | "warning" | "error" } | null>(null);
  const [confirmation, setConfirmation] = useState<{ action: "restore" | "delete"; entry: QuarantineEntry } | null>(null);
  const lastRefresh = useRef(0);

  const loadEntries = useCallback(async (enforceDebounce = false) => {
    if (enforceDebounce && Date.now() - lastRefresh.current < 1000) return;
    setLoading(true);
    try {
      const result = await request<unknown>("quarantine.list");
      const parsed = parseList(result);
      if (!parsed) throw new Error(_("ClamUI returned invalid quarantine data."));
      setData(parsed);
      lastRefresh.current = Date.now();
      setPage(1);
      setShowAll(false);
    } catch (error) {
      const message = readableError(error);
      const failure = _("Failed to load quarantine: {error}", { error: message });
      setBanner({ message: failure, type: "error" });
      notify(failure, "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadEntries(); }, [loadEntries]);

  useEffect(() => {
    let active = true;
    let dispose: (() => void) | undefined;
    void onEvent((event) => {
      if (event.event === "scan-complete") void loadEntries();
    }).then((unlisten) => {
      if (active) dispose = unlisten;
      else unlisten();
    }).catch((listenError: unknown) => notify(_("Quarantine updates are unavailable: {error}", { error: readableError(listenError) }), "warning"));
    return () => {
      active = false;
      dispose?.();
    };
  }, [loadEntries]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAppliedSearch(search.trim().toLocaleLowerCase());
      setPage(1);
      setShowAll(false);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const filtered = data?.entries.filter((entry) => !appliedSearch || entry.threatName.toLocaleLowerCase().includes(appliedSearch) || entry.originalPath.toLocaleLowerCase().includes(appliedSearch)) ?? [];
  const displayed = showAll ? filtered : filtered.slice(0, page * PAGE_SIZE);

  const cleanupOld = async () => {
    try {
      const result = await request<unknown>("quarantine.cleanup", { days: 30 });
      if (!result || typeof result !== "object" || typeof fieldValue(result, "removed", "removed") !== "number") throw new Error(_("ClamUI returned an invalid cleanup result."));
      const removed = fieldValue(result, "removed", "removed");
      if (typeof removed !== "number") return;
      setBanner({
        message: removed > 0
          ? ngettext(
              "Removed {count} old quarantine entry.",
              "Removed {count} old quarantine entries.",
              removed,
              { count: removed },
            )
          : _("No old entries found to remove."),
        type: removed > 0 ? "success" : "warning",
      });
      if (removed > 0) await loadEntries();
    } catch (error) {
      const message = readableError(error);
      setBanner({ message: _("Failed to clear old items: {error}", { error: message }), type: "error" });
      notify(_("Failed to clear old quarantine items: {error}", { error: message }), "error");
    }
  };

  const actOnEntry = async () => {
    if (!confirmation) return;
    const { action, entry } = confirmation;
    try {
      const response = await request<unknown>(`quarantine.${action}`, { id: entry.id });
      const result = parseResult(response);
      if (!result) throw new Error(_("ClamUI returned an invalid quarantine result."));
      setConfirmation(null);
      if (result.status === "success") {
        setBanner({ message: action === "restore" ? _("File restored successfully.") : _("File deleted successfully."), type: "success" });
        await loadEntries();
        return;
      }
      if (result.status === "database_error") {
        setBanner({ message: result.errorMessage ?? (action === "restore" ? _("File restored, but the database entry could not be removed.") : _("File deleted, but the database entry could not be removed.")), type: "warning" });
        await loadEntries();
        return;
      }
      setBanner({ message: result.errorMessage ?? (action === "restore" ? _("Failed to restore quarantined file ({status}).", { status: result.status }) : _("Failed to delete quarantined file ({status}).", { status: result.status })), type: "error" });
    } catch (error) {
      const message = readableError(error);
      const failure = action === "restore"
        ? _("Failed to restore quarantined file: {error}", { error: message })
        : _("Failed to delete quarantined file: {error}", { error: message });
      setConfirmation(null);
      setBanner({ message: failure, type: "error" });
      notify(failure, "error");
    }
  };

  return <main className="page quarantine-page">
    <header className="page-header">
      <div>
        <h1>{_("Quarantine")}</h1>
        <p>{_("Secure storage for isolated threats.")}</p>
      </div>
    </header>
    {banner && <div className={`status-banner ${banner.type}`} role="status"><span>{banner.message}</span><button className="icon-button" type="button" aria-label={_("Dismiss")} title={_("Dismiss")} onClick={() => setBanner(null)}><Icon name="close" /></button></div>}
    <section aria-labelledby="storage-heading">
      <header className="section-header"><div><h2 id="storage-heading">{_("Quarantine Storage")}</h2></div></header>
      <dl className="grouped-list summary-list">
        <div className="group-row"><dt>{_("Total Size")}</dt><dd>{data ? formatFileSize(data.totalSize) : _("Calculating…")}</dd></div>
        <div className="group-row"><dt>{_("Items")}</dt><dd>{appliedSearch
          ? ngettext("{filtered} of {total} item", "{filtered} of {total} items", data?.entryCount ?? 0, { filtered: filtered.length, total: data?.entryCount ?? 0 })
          : ngettext("{count} item", "{count} items", data?.entryCount ?? 0, { count: data?.entryCount ?? 0 })}</dd></div>
      </dl>
    </section>
    <section aria-labelledby="files-heading">
      <header className="section-header">
        <div><h2 id="files-heading">{_("Quarantined Files")}</h2><p>{_("Detected threats isolated from your system.")}</p></div>
        <div className="actions">
          <button className="button" type="button" onClick={() => void loadEntries(true)} disabled={loading}><Icon name="refresh" />{_("Refresh")}</button>
          <button className="button" type="button" onClick={() => void cleanupOld()} disabled={!data?.entryCount}>{_("Clear Old Items")}</button>
        </div>
      </header>
      <label className="search-field">{_("Search by threat name or path")}<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={_("Search by threat name or path…")} /></label>
      {loading ? <p className="muted">{_("Loading quarantine entries…")}</p> : !data?.entries.length ? <p className="empty-state">{_("No Quarantined Files. Detected threats will be isolated here for review.")}</p> : filtered.length === 0 ? <p className="empty-state">{_("No matching entries. Try a different search term.")}</p> : <div className="grouped-list quarantine-list" role="list">{displayed.map((entry) => <article className="group-row quarantine-entry" role="listitem" key={entry.id}>
        <div className="quarantine-entry-content row-copy">
          <header><h3 className="row-title">{entry.threatName || _("Unknown Threat")}</h3><span className="status-badge warning">{_("Quarantined")}</span></header>
          <p className="path-value">{_("Path")}: {entry.originalPath}</p>
          <dl className="metadata"><div><dt>{_("Quarantined")}</dt><dd>{formatDate(entry.detectionDate)}</dd></div><div><dt>{_("Size")}</dt><dd>{formatFileSize(entry.fileSize)}</dd></div></dl>
        </div>
        <div className="actions"><button className="button" type="button" onClick={() => setConfirmation({ action: "restore", entry })}>{_("Restore")}</button><button type="button" className="button destructive" onClick={() => setConfirmation({ action: "delete", entry })}>{_("Delete")}</button></div>
      </article>)}</div>}
      {!showAll && displayed.length < filtered.length && <div className="pagination-actions"><button className="button" type="button" onClick={() => setPage((current) => current + 1)}>{_("Load More")}</button><button className="button" type="button" onClick={() => setShowAll(true)}>{_("Show All ({count})", { count: filtered.length })}</button></div>}
    </section>
    {confirmation && <Modal title={confirmation.action === "restore" ? _("Restore Quarantined File?") : _("Permanently Delete File?")} onClose={() => setConfirmation(null)}><p>{confirmation.action === "restore" ? _(
      // Translators: Preserve the {threat} and {path} placeholders; they are runtime threat and file-path values. Use quotation marks appropriate for your language.
      "This file was detected as '{threat}'. It will be restored to {path}.",
      { threat: confirmation.entry.threatName || _("Unknown Threat"), path: confirmation.entry.originalPath },
    ) : _(
      // Translators: Preserve the {path} and {threat} placeholders; they are runtime file-path and threat values. Use quotation marks appropriate for your language.
      "The quarantined file from {path} ('{threat}') will be permanently deleted. This action cannot be undone.",
      { path: confirmation.entry.originalPath, threat: confirmation.entry.threatName || _("Unknown Threat") },
    )}</p><div className="button-row"><button type="button" onClick={() => setConfirmation(null)}>{_("Cancel")}</button><button type="button" className="destructive" onClick={() => void actOnEntry()}>{confirmation.action === "restore" ? _("Restore Anyway") : _("Delete")}</button></div></Modal>}
  </main>;
}
