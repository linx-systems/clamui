import { describe, expect, test } from "bun:test";
import { parseLatestScan } from "../src/scanHistory";

describe("dashboard scan history", () => {
  test("keeps unavailable legacy counts unknown rather than presenting a clean scan", () => {
    expect(parseLatestScan({ status: "infected", summary: "Old scan" })).toEqual({
      status: "infected", summary: "Old scan", timestamp: undefined,
      scanned_files: undefined, infected_count: undefined,
    });
  });

  test("retains zero counts and rejects invalid counts from history", () => {
    expect(parseLatestScan({ status: "clean", scanned_files: 0, infected_count: 0 })?.infected_count).toBe(0);
    for (const value of [-1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, "12", null]) {
      const parsed = parseLatestScan({ status: "infected", scanned_files: value, infected_count: value });
      expect(parsed?.scanned_files).toBeUndefined();
      expect(parsed?.infected_count).toBeUndefined();
    }
  });

  test("does not treat a malformed history entry as a scan result", () => {
    for (const value of [undefined, null, [], "clean", {}, { status: 1 }]) {
      expect(parseLatestScan(value)).toBeNull();
    }
  });
});
