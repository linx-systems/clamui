export type HelperTrustFailure = "missing" | "untrusted";

const HELPER_FAILURES: Record<string, HelperTrustFailure> = {
  "the canonical privileged helper is missing": "missing",
  "the canonical host privileged helper is unavailable": "missing",
  "the canonical privileged helper is not a root-owned immutable executable": "untrusted",
  "legacy privileged helper libraries are not root-owned and immutable": "untrusted",
};

function normalizedTrustFailure(message: string): string {
  let normalized = message.trim();
  while (normalized.startsWith("Error:")) {
    normalized = normalized.slice("Error:".length).trimStart();
  }
  return normalized.trim();
}

/** Classifies exact native helper failures without broad text matching. */
export function helperTrustFailure(message: string): HelperTrustFailure | null {
  const normalized = normalizedTrustFailure(message);
  return Object.hasOwn(HELPER_FAILURES, normalized) ? HELPER_FAILURES[normalized] : null;
}

/** Recognizes exact native helper failures without changing their fail-closed behavior. */
export function isHelperTrustError(message: string): boolean {
  return helperTrustFailure(message) !== null;
}
