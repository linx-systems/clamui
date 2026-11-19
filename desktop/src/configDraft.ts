/**
 * Shared dirty-state helpers for Preferences config documents (freshclam.conf,
 * clamd.conf, the scheduled-scan draft).
 *
 * This is the shared "is this document dirty" contract used by:
 *  - the autosave/batched-apply flow in `pages/ConfigPreferences.tsx` and
 *    `pages/Preferences.tsx` (issue #346: autosave + persistent Save button),
 *  - any future guard that must avoid discarding unsaved edits before a
 *    destructive reload, such as "Authorize read" overwriting an in-progress
 *    draft on the On-Access page (issue #343).
 *
 * `ConfigPreferences.tsx` calls `authorizeRead`, `selectConfig`, and
 * `detectConfig`/`browseConfig` to replace a document's `values` *and*
 * `baseline` with freshly loaded content. A fix for #343 should check
 * `isConfigDraftDirty(document)` on the document being replaced *before*
 * doing that swap, and confirm with the user (or merge/preserve the pending
 * edits) instead of silently clobbering `values`. Reusing these helpers keeps
 * both features' notion of "dirty" identical, so a document can't be
 * considered saved by one feature while still shown as having pending edits
 * by the other.
 */

export type ConfigValues = Record<string, string[]>;

export type ConfigDraftLike = {
  values: ConfigValues;
  baseline: ConfigValues;
  path: string;
  baselinePath: string;
};

/** True if two config-file value maps contain exactly the same keys and ordered values. */
export function valuesEqual(left: ConfigValues, right: ConfigValues): boolean {
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  return leftKeys.length === rightKeys.length && leftKeys.every((key, index) =>
    key === rightKeys[index] && left[key].length === right[key].length && left[key].every((value, valueIndex) => value === right[key][valueIndex]),
  );
}

/**
 * True if a config document (freshclam.conf or clamd.conf draft) has edits
 * that have not yet been persisted: its values differ from the last
 * confirmed-saved baseline, or the user switched to a different file path.
 */
export function isConfigDraftDirty(document: Pick<ConfigDraftLike, "values" | "baseline" | "path" | "baselinePath"> | null): boolean {
  if (!document) return false;
  return !valuesEqual(document.values, document.baseline) || document.path !== document.baselinePath;
}
