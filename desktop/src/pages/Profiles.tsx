import { useCallback, useEffect, useState } from "react";
import { Icon } from "../Icon";
import { Modal } from "../Modal";
import { _, ngettext } from "../i18n";
import { navigate, notify, onEvent, openPaths, request, saveText } from "../api";
import { profileDescription, profileLabel } from "../profilePresentation";


type Exclusions = { paths?: string[]; patterns?: string[] };
type Profile = { id: string; name: string; targets: string[]; exclusions: Exclusions; created_at: string; updated_at: string; is_default: boolean; description: string; options: Record<string, unknown> };
type Draft = { name: string; description: string; targets: string[]; exclusionPaths: string[]; exclusionPatterns: string[]; optionsText: string };

const EMPTY_DRAFT: Draft = { name: "", description: "", targets: [], exclusionPaths: [], exclusionPatterns: [], optionsText: "{}" };

function draftFrom(profile?: Profile): Draft {
  if (!profile) return { ...EMPTY_DRAFT };
  return {
    name: profile.name,
    description: profile.description,
    targets: [...profile.targets],
    exclusionPaths: [...(profile.exclusions.paths ?? [])],
    exclusionPatterns: [...(profile.exclusions.patterns ?? [])],
    optionsText: JSON.stringify(profile.options ?? {}, null, 2),
  };
}

function uniqueValues(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const item = value.trim();
    if (!item || seen.has(item)) return false;
    seen.add(item);
    return true;
  });
}

function ProfileEditor({ profile, onClose, onSaved }: { profile: Profile | null; onClose: () => void; onSaved: (saved: Profile) => void }) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(profile ?? undefined));
  const [pattern, setPattern] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const defaultProfile = Boolean(profile?.is_default);
  const validName = draft.name.trim().length > 0 && draft.name.trim().length <= 50;

  const choose = async (kind: "target" | "exclusion", directory: boolean) => {
    try {
      const selected = await openPaths({ directory, multiple: true });
      setDraft((current) => kind === "target"
        ? { ...current, targets: uniqueValues([...current.targets, ...selected]) }
        : { ...current, exclusionPaths: uniqueValues([...current.exclusionPaths, ...selected]) });
    } catch (reason) {
      setError(String(reason));
    }
  };
  const save = async () => {
    if (!validName) {
      setError(draft.name.trim() ? _("Name must be 50 characters or less") : _("Profile name is required"));
      return;
    }
    let options: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(draft.optionsText || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(_("Options must be a JSON object"));
      options = parsed as Record<string, unknown>;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return;
    }
    setBusy(true);
    setError(null);
    const exclusions: Exclusions = {};
    if (draft.exclusionPaths.length) exclusions.paths = draft.exclusionPaths;
    if (draft.exclusionPatterns.length) exclusions.patterns = draft.exclusionPatterns;
    try {
      const args = { targets: draft.targets, exclusions, description: draft.description.trim(), options };
      const saved = profile
        ? await request<Profile>("profiles.update", { id: profile.id, ...args, ...(profile.is_default ? {} : { name: draft.name.trim() }) })
        : await request<Profile>("profiles.create", { name: draft.name.trim(), ...args });
      onSaved(saved);
      onClose();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  return <Modal title={profile ? _("Edit Profile") : _("New Profile")} onClose={onClose}>
    <div className="profile-editor">
      {error && <p className="error" role="alert">{error}</p>}
      <label className="field">{_("Name")}<input value={defaultProfile && profile ? profileLabel(profile) : draft.name} maxLength={50} disabled={defaultProfile || busy} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />{defaultProfile && <span className="muted">{_("Default profile names are protected")}</span>}</label>
      <label className="field">{_("Description")}<textarea value={draft.description} disabled={busy} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} /></label>

      <section className="grouped-list" aria-labelledby="profile-targets-title">
        <header className="section-header"><h3 id="profile-targets-title">{_("Scan Targets")}</h3><div className="actions"><button className="button" onClick={() => void choose("target", false)} disabled={busy}><Icon name="file" />{_("Add Files")}</button><button className="button" onClick={() => void choose("target", true)} disabled={busy}><Icon name="folder" />{_("Add Folders")}</button></div></header>
        {draft.targets.length === 0 ? <p className="empty-state">{_("No targets added")}</p> : draft.targets.map((path) => <div className="group-row target-row" key={path}><code className="path-value">{path}</code><button className="button danger" aria-label={_("Remove")} title={_("Remove")} disabled={busy} onClick={() => setDraft((current) => ({ ...current, targets: current.targets.filter((candidate) => candidate !== path) }))}><Icon name="trash" /></button></div>)}
      </section>

      <section className="grouped-list" aria-labelledby="profile-exclusions-title">
        <header className="section-header"><h3 id="profile-exclusions-title">{_("Exclusions")}</h3><button className="button" onClick={() => void choose("exclusion", true)} disabled={busy}><Icon name="folder" />{_("Add Path")}</button></header>
        <div className="inline-form"><label className="field"><span>{_("Pattern")}</span><input value={pattern} disabled={busy} onChange={(event) => setPattern(event.target.value)} /></label><button className="button" disabled={busy || !pattern.trim()} onClick={() => { setDraft((current) => ({ ...current, exclusionPatterns: uniqueValues([...current.exclusionPatterns, pattern]) })); setPattern(""); }}><Icon name="plus" />{_("Add Pattern")}</button></div>
        {draft.exclusionPaths.length + draft.exclusionPatterns.length === 0 ? <p className="empty-state">{_("No exclusions added")}</p> : <>
          {draft.exclusionPaths.map((path) => <div className="group-row" key={`path-${path}`}><span>{_("Path")}: <code className="path-value">{path}</code></span><button className="button danger" aria-label={_("Remove")} title={_("Remove")} disabled={busy} onClick={() => setDraft((current) => ({ ...current, exclusionPaths: current.exclusionPaths.filter((candidate) => candidate !== path) }))}><Icon name="trash" /></button></div>)}
          {draft.exclusionPatterns.map((value) => <div className="group-row" key={`pattern-${value}`}><span>{_("Pattern")}: <code className="path-value">{value}</code></span><button className="button danger" aria-label={_("Remove")} title={_("Remove")} disabled={busy} onClick={() => setDraft((current) => ({ ...current, exclusionPatterns: current.exclusionPatterns.filter((candidate) => candidate !== value) }))}><Icon name="trash" /></button></div>)}
        </>}
      </section>

      <label className="field">{_("Scan Options (JSON)")}<textarea className="monospace" value={draft.optionsText} disabled={busy} onChange={(event) => setDraft((current) => ({ ...current, optionsText: event.target.value }))} /></label>
      <div className="dialog-actions"><button className="button primary" onClick={() => void save()} disabled={busy || !validName}><Icon name="save" />{busy ? _("Saving…") : _("Save Profile")}</button></div>
    </div>
  </Modal>;
}

export default function Profiles() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Profile | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Profile | null>(null);
  const [confirmRestore, setConfirmRestore] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setProfiles((await request<{ profiles: Profile[] }>("profiles.list")).profiles);
      setError(null);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const unlisten = onEvent((event) => {
      if (event.event === "profiles-changed") void load();
    });
    return () => {
      void unlisten.then((dispose) => dispose());
    };
  }, [load]);

  const saved = (profile: Profile) => {
    setProfiles((current) => {
      const exists = current.some((candidate) => candidate.id === profile.id);
      return exists ? current.map((candidate) => candidate.id === profile.id ? profile : candidate) : [...current, profile];
    });
    window.dispatchEvent(new CustomEvent("clamui-profiles-updated"));
    notify(_("Profile saved"), "success");
  };
  const duplicate = async (profile: Profile) => {
    setBusyId(profile.id);
    setError(null);
    try {
      const copy = await request<Profile>("profiles.duplicate", { id: profile.id });
      setProfiles((current) => [...current, copy]);
      window.dispatchEvent(new CustomEvent("clamui-profiles-updated"));
      notify(_("Profile duplicated"), "success");
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusyId(null);
    }
  };
  const remove = async () => {
    if (!deleting) return;
    setBusyId(deleting.id);
    setError(null);
    try {
      await request("profiles.delete", { id: deleting.id });
      setProfiles((current) => current.filter((profile) => profile.id !== deleting.id));
      setDeleting(null);
      window.dispatchEvent(new CustomEvent("clamui-profiles-updated"));
      notify(_("Profile deleted"), "success");
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusyId(null);
    }
  };
  const importProfile = async () => {
    try {
      const paths = await openPaths({ multiple: false });
      if (!paths[0]) return;
      const profile = await request<Profile>("profiles.import", { path: paths[0] });
      setProfiles((current) => [...current.filter((candidate) => candidate.id !== profile.id), profile]);
      window.dispatchEvent(new CustomEvent("clamui-profiles-updated"));
      notify(_("Profile imported"), "success");
    } catch (reason) {
      setError(String(reason));
    }
  };
  const exportProfile = async (profile: Profile) => {
    setBusyId(profile.id);
    setError(null);
    try {
      const response = await request<{ id: string; content?: string }>("profiles.export", { id: profile.id });
      if (typeof response.content !== "string") throw new Error(_("Profile export did not return data"));
      const safeName = profile.name.replace(/[^a-z0-9_-]+/gi, "_") || "profile";
      if (await saveText(response.content, `${safeName}.json`, [{ name: _("JSON Files"), extensions: ["json"] }])) notify(_("Profile exported"), "success");
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusyId(null);
    }
  };
  const restoreDefaults = async () => {
    setBusyId("restore");
    setError(null);
    try {
      const response = await request<{ profiles: Profile[] }>("profiles.restore_defaults");
      setProfiles(response.profiles);
      window.dispatchEvent(new CustomEvent("clamui-profiles-updated"));
      notify(_("Default profiles restored"), "success");
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusyId(null);
    }
  };

  return <section className="page profile-layout" aria-label={_("Scan Profiles")}>
    <header className="page-header"><div><h1>{_("Scan Profiles")}</h1><p>{_("Save targets, exclusions, and scan options for reuse.")}</p></div><div className="actions profile-toolbar"><button className="button" onClick={() => void importProfile()} disabled={busyId !== null}><Icon name="upload" />{_("Import")}</button><button className="button" onClick={() => setConfirmRestore(true)} disabled={busyId !== null}><Icon name="refresh" />{_("Restore Defaults")}</button><button className="button primary" onClick={() => setEditing(null)} disabled={busyId !== null}><Icon name="plus" />{_("New Profile")}</button></div></header>
    {error && <p className="notice error" role="alert">{error}</p>}
    {loading ? <p className="empty-state">{_("Loading profiles…")}</p> : profiles.length === 0 ? <div className="empty-state"><p>{_("No profiles available")}</p></div> : <div className="profile-list grouped-list">{profiles.map((profile) => {
      const profileNameId = `profile-name-${profile.id}`;
      const targetCount = ngettext("{count} target", "{count} targets", profile.targets.length, { count: profile.targets.length });
      return <article className="profile-card" key={profile.id} aria-labelledby={profileNameId}>
        <div className="profile-copy">
          <div className="profile-heading"><h2 className="row-title profile-name" id={profileNameId}>{profileLabel(profile)}</h2>{profile.is_default && <span className="status-badge">{_("Default")}</span>}</div>
          {(profile.description || profile.targets.length === 0) && <p className="row-description profile-description">{profile.description ? profileDescription(profile) : targetCount}</p>}
          {profile.targets.length > 0 && <details className="profile-targets"><summary className="profile-targets-summary"><Icon name="chevron-down" className="profile-targets-chevron" /><span>{targetCount}</span></summary><ul className="profile-target-list">{profile.targets.map((path, index) => <li key={`${path}-${index}`}><code className="path-value">{path}</code></li>)}</ul></details>}
        </div>
        <div className="actions profile-actions"><button className="button primary profile-action-primary" onClick={() => navigate("scan", { profile_id: profile.id, start: true })} disabled={busyId === profile.id}><Icon name="play" />{_("Use this profile")}</button><button className="button profile-action-secondary" aria-label={_("Edit")} title={_("Edit")} onClick={() => setEditing(profile)} disabled={busyId === profile.id}><Icon name="edit" /><span className="profile-action-label">{_("Edit")}</span></button><button className="button profile-action-secondary" aria-label={_("Duplicate")} title={_("Duplicate")} onClick={() => void duplicate(profile)} disabled={busyId === profile.id}><Icon name="copy" /><span className="profile-action-label">{_("Duplicate")}</span></button><button className="button profile-action-secondary" aria-label={_("Export")} title={_("Export")} onClick={() => void exportProfile(profile)} disabled={busyId === profile.id}><Icon name="download" /><span className="profile-action-label">{_("Export")}</span></button><button className="button danger profile-action-secondary" aria-label={_("Delete")} title={_("Delete")} onClick={() => setDeleting(profile)} disabled={profile.is_default || busyId === profile.id}><Icon name="trash" /><span className="profile-action-label">{_("Delete")}</span></button></div>
      </article>;
    })}</div>}
    {editing !== undefined && <ProfileEditor profile={editing} onClose={() => setEditing(undefined)} onSaved={saved} />}
    {deleting && <Modal title={_("Delete Profile")} onClose={() => setDeleting(null)}><p className="profile-delete-confirmation">{_(
      // Translators: Preserve the {name} placeholder; it is a user-provided profile name. Use quotation marks appropriate for your language.
      "Delete profile '{name}'? This cannot be undone.",
      { name: profileLabel(deleting) },
    )}</p><div className="dialog-actions"><button className="button danger" onClick={() => void remove()} disabled={busyId === deleting.id}><Icon name="trash" />{busyId === deleting.id ? _("Deleting…") : _("Delete")}</button><button className="button" onClick={() => setDeleting(null)} disabled={busyId === deleting.id}><Icon name="close" />{_("Cancel")}</button></div></Modal>}
    {confirmRestore && <Modal title={_("Restore Default Profiles")} onClose={() => setConfirmRestore(false)}><p>{_("Restore the built-in default profiles? Any customizations to default profiles will be reset; custom profiles are preserved.")}</p><div className="dialog-actions"><button className="button danger" onClick={() => { setConfirmRestore(false); void restoreDefaults(); }} disabled={busyId === "restore"}><Icon name="refresh" />{busyId === "restore" ? _("Restoring…") : _("Restore Defaults")}</button><button className="button" onClick={() => setConfirmRestore(false)} disabled={busyId === "restore"}><Icon name="close" />{_("Cancel")}</button></div></Modal>}
  </section>;
}
