import { describe, expect, test } from "bun:test";
import { isConfigDraftDirty, valuesEqual } from "../src/configDraft";

describe("valuesEqual", () => {
  test("treats identical key/value maps as equal regardless of key order", () => {
    expect(valuesEqual({ a: ["1"], b: ["2", "3"] }, { b: ["2", "3"], a: ["1"] })).toBe(true);
  });

  test("detects a changed value", () => {
    expect(valuesEqual({ a: ["1"] }, { a: ["2"] })).toBe(false);
  });

  test("detects a changed list order", () => {
    expect(valuesEqual({ a: ["1", "2"] }, { a: ["2", "1"] })).toBe(false);
  });

  test("detects an added or removed key", () => {
    expect(valuesEqual({ a: ["1"] }, { a: ["1"], b: ["2"] })).toBe(false);
    expect(valuesEqual({ a: ["1"], b: ["2"] }, { a: ["1"] })).toBe(false);
  });

  test("treats two empty maps as equal", () => {
    expect(valuesEqual({}, {})).toBe(true);
  });
});

describe("isConfigDraftDirty", () => {
  const baseline = { LogVerbose: ["yes"] };

  test("is not dirty when values match the baseline and the path is unchanged", () => {
    expect(
      isConfigDraftDirty({
        values: { LogVerbose: ["yes"] },
        baseline,
        path: "/etc/clamd.d/scan.conf",
        baselinePath: "/etc/clamd.d/scan.conf",
      }),
    ).toBe(false);
  });

  test("is dirty when a value was edited", () => {
    expect(
      isConfigDraftDirty({
        values: { LogVerbose: ["no"] },
        baseline,
        path: "/etc/clamd.d/scan.conf",
        baselinePath: "/etc/clamd.d/scan.conf",
      }),
    ).toBe(true);
  });

  test("is dirty when the user switched to a different file, even with unchanged values", () => {
    expect(
      isConfigDraftDirty({
        values: baseline,
        baseline,
        path: "/etc/clamd.d/alternate.conf",
        baselinePath: "/etc/clamd.d/scan.conf",
      }),
    ).toBe(true);
  });

  test("a null document is never dirty", () => {
    expect(isConfigDraftDirty(null)).toBe(false);
  });
});
