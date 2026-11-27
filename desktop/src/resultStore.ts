/**
 * Keeps the latest scan and VirusTotal results where the lazily mounted Results
 * page can always find them.
 *
 * A full-system scan reports one "file: OK" line per file, so the result can be
 * far larger than the ~5 MB sessionStorage quota. Persisting it must never be
 * the only place the result lives: the page that finishes the scan hands it
 * over in memory, and sessionStorage only keeps a (trimmed) copy for reloads.
 */
export type ResultKind = "scan" | "virustotal";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const STORAGE_KEYS: Record<ResultKind, string> = {
  scan: "clamui-last-scan-result",
  virustotal: "clamui-last-vt-result",
};

/** Per-field cap for the copy that goes to sessionStorage. */
export const STORED_OUTPUT_LIMIT = 256 * 1024;

const OUTPUT_FIELDS = ["stdout", "stderr"] as const;

function tail(text: string, limit: number): string {
  if (text.length <= limit) return text;
  return `[output truncated, last ${limit} characters kept]\n${text.slice(text.length - limit)}`;
}

/** Copy of a result without the unbounded raw clamdscan/clamscan output. */
export function trimmedForStorage(value: unknown, limit: number = STORED_OUTPUT_LIMIT): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  const trimmed: Record<string, unknown> = { ...(value as Record<string, unknown>) };
  for (const field of OUTPUT_FIELDS) {
    const output = trimmed[field];
    if (typeof output === "string") trimmed[field] = tail(output, limit);
  }
  if (Array.isArray(trimmed.per_target_results)) {
    trimmed.per_target_results = trimmed.per_target_results.map((entry) => trimmedForStorage(entry, limit));
  }
  return trimmed;
}

export function createResultStore(storage: () => StorageLike | null) {
  const memory = new Map<ResultKind, unknown>();

  const persist = (kind: ResultKind, value: unknown): void => {
    const target = storage();
    if (!target) return;
    const key = STORAGE_KEYS[kind];
    for (const candidate of [value, trimmedForStorage(value), trimmedForStorage(value, 0)]) {
      try {
        target.setItem(key, JSON.stringify(candidate));
        return;
      } catch {
        // Quota exceeded: retry with less output. The in-memory copy stays complete.
      }
    }
    try {
      target.removeItem(key);
    } catch {
      // Nothing left to clean up.
    }
  };

  return {
    remember(kind: ResultKind, value: unknown): void {
      memory.set(kind, value);
      persist(kind, value);
    },
    recall<T>(kind: ResultKind, guard: (value: unknown) => value is T): T | null {
      const live = memory.get(kind);
      if (guard(live)) return live;
      try {
        const serialized = storage()?.getItem(STORAGE_KEYS[kind]);
        if (!serialized) return null;
        const parsed: unknown = JSON.parse(serialized);
        return guard(parsed) ? parsed : null;
      } catch {
        return null;
      }
    },
  };
}

export const resultStore = createResultStore(() => {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
});
