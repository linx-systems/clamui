/**
 * Pure planning helpers for the Preferences autosave/batched-apply flow
 * (issue #346).
 *
 * The backend's `config.apply` already collapses every protected
 * (privilege-requiring) file write into exactly one pkexec/polkit prompt per
 * call (see `crates/clamui-core/src/privileged.rs::write_staged_configs`).
 * The remaining problem this module solves is *when* to call it: leaving a
 * settings section must never itself trigger an authorization prompt, so a
 * dirty document can only be included in an immediate ("direct") flush if
 * writing it would not need elevation. Anything that would need elevation
 * stays queued (dirty) until an explicit batched flush: the persistent
 * header Save button, or leaving the Preferences page/closing the window.
 */

import { type ConfigDraftLike, type ConfigValues, isConfigDraftDirty } from "./configDraft";

export type ConfigKind = "freshclam" | "clamd";

export type ConfigDocument = ConfigDraftLike & {
  kind: ConfigKind;
  /** clamd.conf legacy size units (e.g. `MaxFileSize 100M`) pending a one-time rewrite. */
  needsSizeUnitMigration?: boolean;
};

export type ConfigProposal = { kind: ConfigKind; path: string; values: ConfigValues };

/** True if a document has edits that have not yet been durably saved. */
export function isDocumentPending(document: ConfigDocument | null | undefined): boolean {
  if (!document) return false;
  return isConfigDraftDirty(document) || (document.kind === "clamd" && document.needsSizeUnitMigration === true);
}

/** The subset of open documents that have unsaved edits, as apply-ready proposals. */
export function pendingProposals(documents: ReadonlyArray<ConfigDocument | null | undefined>): ConfigProposal[] {
  return documents
    .filter((document): document is ConfigDocument => isDocumentPending(document))
    .map((document) => ({ kind: document.kind, path: document.path, values: document.values }));
}

/**
 * Splits proposals into ones that can be written immediately without an
 * authorization prompt ("direct") and ones that would require one
 * ("deferred"), given a map of path -> needs-elevation reported by the
 * backend's `config.needs_elevation` check.
 */
export function partitionByElevation(
  proposals: readonly ConfigProposal[],
  needsElevation: ReadonlyMap<string, boolean>,
): { direct: ConfigProposal[]; deferred: ConfigProposal[] } {
  const direct: ConfigProposal[] = [];
  const deferred: ConfigProposal[] = [];
  for (const proposal of proposals) {
    if (needsElevation.get(proposal.path) === true) deferred.push(proposal);
    else direct.push(proposal);
  }
  return { direct, deferred };
}
