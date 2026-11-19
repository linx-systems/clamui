export type ConfigValues = Record<string, string[]>;

export type ConfigDocument = {
  kind: "freshclam" | "clamd";
  path: string;
  baselinePath: string;
  values: ConfigValues;
  baseline: ConfigValues;
  needsSizeUnitMigration: boolean;
  readable: boolean;
  error?: string;
};

export type AuthorizedConfigLoad = {
  path?: string;
  values?: ConfigValues;
  needs_size_unit_migration?: boolean;
  readable?: boolean;
  error?: string;
};

const EMPTY_VALUES: ConfigValues = {};

export function cloneValues(values: ConfigValues): ConfigValues {
  return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, [...value]]));
}

export function valuesEqual(left: ConfigValues, right: ConfigValues): boolean {
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  return leftKeys.length === rightKeys.length && leftKeys.every((key, index) =>
    key === rightKeys[index] && left[key].length === right[key].length && left[key].every((value, valueIndex) => value === right[key][valueIndex]),
  );
}

/** True when the form holds edits (values or path) not yet reflected in the loaded baseline. */
export function isConfigDirty(document: ConfigDocument): boolean {
  return !valuesEqual(document.values, document.baseline) || document.path !== document.baselinePath;
}

/**
 * Applies a freshly authorized read of a config file. When the form has no pending edits,
 * the authoritative values replace both the form and the baseline, same as an ordinary load.
 * When the form is dirty, the authoritative values become the new baseline but the user's
 * pending edits are kept in the form, so authorizing a read never discards unsaved changes.
 */
export function mergeAuthorizedConfig(document: ConfigDocument, loaded: AuthorizedConfigLoad, baselinePath: string): ConfigDocument {
  const loadedValues = cloneValues(loaded.values ?? EMPTY_VALUES);
  const dirty = isConfigDirty(document);
  return {
    kind: document.kind,
    path: loaded.path ?? document.path,
    baselinePath,
    values: dirty ? cloneValues(document.values) : cloneValues(loadedValues),
    baseline: cloneValues(loadedValues),
    needsSizeUnitMigration: loaded.needs_size_unit_migration === true,
    readable: loaded.readable ?? true,
    error: loaded.error,
  };
}
