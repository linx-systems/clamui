import { describe, expect, test } from "bun:test";
import { createScanLogIndex, scanLogChunks } from "../src/scanLog";

describe("scanLogChunks", () => {
  test("prefers target streams over aggregate output and preserves diagnostic order", () => {
    const chunks = scanLogChunks({
      error_message: "aggregate failure",
      stdout: "aggregate stdout",
      stderr: "aggregate stderr",
      warning_message: "aggregate warning",
      nonfatal_warnings: ["aggregate diagnostic"],
      per_target_results: [
        {
          path: "/one",
          error_message: "aggregate failure",
          stdout: "target one stdout",
          stderr: "target one stderr",
          warning_message: "target one warning",
          nonfatal_warnings: ["target one diagnostic"],
        },
        {
          path: "/two",
          error_message: "target two failure",
          stdout: "target two stdout",
          nonfatal_warnings: ["target two diagnostic"],
        },
      ],
    });

    expect(chunks).toEqual([
      "aggregate failure",
      "target one stdout",
      "target one stderr",
      "target one warning",
      "target one diagnostic",
      "target two failure",
      "target two stdout",
      "target two diagnostic",
    ]);
  });

  test("uses aggregate streams only when there are no targets", () => {
    expect(scanLogChunks({
      error_message: "failure",
      stdout: "stdout",
      stderr: "stderr",
      warning_message: "warning",
      nonfatal_warnings: ["diagnostic", ""],
      per_target_results: [],
    })).toEqual(["failure", "stdout", "stderr", "warning", "diagnostic"]);
  });

  test("includes an aggregate error once when targets repeat it", () => {
    const chunks = scanLogChunks({
      error_message: "single aggregate error",
      per_target_results: [
        { error_message: "single aggregate error", stdout: "first" },
        { error_message: "single aggregate error", stdout: "second" },
      ],
    });

    expect(chunks).toEqual(["single aggregate error", "first", "second"]);
  });
});

describe("createScanLogIndex", () => {
  test("keeps blank lines, CRLF boundaries, Unicode, and distinct source segments", () => {
    const index = createScanLogIndex([
      "first\r\nsecond\n\n雪",
      "emoji🙂\r\n",
      "\nlast",
    ]);

    expect(index.lineCount).toBe(8);
    expect(Array.from({ length: index.lineCount }, (_, line) => index.lineAt(line))).toEqual([
      "first",
      "second",
      "",
      "雪",
      "emoji🙂",
      "",
      "",
      "last",
    ]);
    expect(index.lineAt(-1)).toBe("");
    expect(index.lineAt(index.lineCount)).toBe("");
  });

  test("reaches every position in a 200000-line log without materializing line copies", () => {
    const lineCount = 200_000;
    const chunkSize = lineCount / 2;
    const firstChunk = Array.from({ length: chunkSize }, (_, line) => `line ${line}`).join("\n");
    const secondChunk = Array.from({ length: chunkSize }, (_, line) => `line ${line + chunkSize}`).join("\n");
    const index = createScanLogIndex([firstChunk, secondChunk]);

    expect(index.lineCount).toBe(lineCount);
    expect(index.lineAt(0)).toBe("line 0");
    expect(index.lineAt(chunkSize - 1)).toBe("line 99999");
    expect(index.lineAt(chunkSize)).toBe("line 100000");
    expect(index.lineAt(123_456)).toBe("line 123456");
    expect(index.lineAt(lineCount - 1)).toBe("line 199999");
  });
});
