import type { ScanOutputResult, ScanOutputTarget } from "./scanOutput";

type IndexedSegment = {
  readonly text: string;
  readonly firstLine: number;
  readonly lineOffsets: Uint32Array;
};

function appendNonempty(chunks: string[], value: string | null | undefined): void {
  if (typeof value === "string" && value.length > 0) chunks.push(value);
}

function appendTargetOutput(chunks: string[], target: ScanOutputTarget, aggregateError?: string | null): void {
  if (target.error_message !== aggregateError) appendNonempty(chunks, target.error_message);
  appendNonempty(chunks, target.stdout);
  appendNonempty(chunks, target.stderr);
  appendNonempty(chunks, target.warning_message);
  for (const warning of target.nonfatal_warnings ?? []) appendNonempty(chunks, warning);
}

/**
 * Selects the raw scan-output strings to show without materializing formatting
 * headers or a combined copy of potentially large output.
 */
export function scanLogChunks(result: ScanOutputResult): readonly string[] {
  const chunks: string[] = [];
  const targets = result.per_target_results ?? [];

  if (targets.length > 0) {
    appendNonempty(chunks, result.error_message);
    for (const target of targets) appendTargetOutput(chunks, target, result.error_message);
    return chunks;
  }

  appendNonempty(chunks, result.error_message);
  appendNonempty(chunks, result.stdout);
  appendNonempty(chunks, result.stderr);
  appendNonempty(chunks, result.warning_message);
  for (const warning of result.nonfatal_warnings ?? []) appendNonempty(chunks, warning);
  return chunks;
}

function lineOffsets(text: string): Uint32Array {
  let lineCount = 1;
  for (let index = 0; index < text.length; index += 1) {
    if (text.charCodeAt(index) === 10) lineCount += 1;
  }

  const offsets = new Uint32Array(lineCount);
  let line = 1;
  for (let index = 0; index < text.length; index += 1) {
    if (text.charCodeAt(index) === 10) {
      offsets[line] = index + 1;
      line += 1;
    }
  }
  return offsets;
}

/**
 * Indexes lines in their original segments. The index stores only compact
 * offsets; individual line strings are sliced only when a consumer asks for
 * them.
 */
export function createScanLogIndex(chunks: readonly string[]): { readonly lineCount: number; lineAt(index: number): string } {
  const segments: IndexedSegment[] = [];
  let lineCount = 0;

  for (const text of chunks) {
    if (text.length === 0) continue;
    const offsets = lineOffsets(text);
    segments.push({ text, firstLine: lineCount, lineOffsets: offsets });
    lineCount += offsets.length;
  }

  const lineAt = (index: number): string => {
    if (!Number.isInteger(index) || index < 0 || index >= lineCount) return "";

    let lower = 0;
    let upper = segments.length - 1;
    while (lower <= upper) {
      const middle = (lower + upper) >>> 1;
      const segment = segments[middle];
      if (index < segment.firstLine) {
        upper = middle - 1;
      } else if (index >= segment.firstLine + segment.lineOffsets.length) {
        lower = middle + 1;
      } else {
        const localIndex = index - segment.firstLine;
        const start = segment.lineOffsets[localIndex];
        let end = localIndex + 1 < segment.lineOffsets.length ? segment.lineOffsets[localIndex + 1] - 1 : segment.text.length;
        if (end > start && segment.text.charCodeAt(end - 1) === 13) end -= 1;
        return segment.text.slice(start, end);
      }
    }

    return "";
  };

  return { lineCount, lineAt };
}
