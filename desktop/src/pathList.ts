/** Splits a comma-separated draft into trimmed, non-empty entries. */
export function parseListDraft(draft: string): string[] {
  return draft.split(",").map((candidate) => candidate.trim()).filter(Boolean);
}

/** Puts new entries at the top, in the order they were typed, and skips duplicates. */
export function addNewestFirst(values: string[], candidates: string[]): string[] {
  const fresh: string[] = [];
  for (const candidate of candidates) {
    if (!values.includes(candidate) && !fresh.includes(candidate)) fresh.push(candidate);
  }
  return fresh.length === 0 ? values : [...fresh, ...values];
}

/** Moves the entry at `from` to position `to`; out-of-range moves leave the list unchanged. */
export function moveEntry<T>(values: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || from >= values.length || to < 0 || to >= values.length) return values;
  const next = values.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}
