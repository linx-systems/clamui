import { describe, expect, test } from "bun:test";
import { addNewestFirst, moveEntry, parseListDraft } from "../src/pathList";

describe("path list", () => {
  test("parses comma-separated drafts", () => {
    expect(parseListDraft(" /home , ,/srv ")).toEqual(["/home", "/srv"]);
  });

  test("adds new entries at the top in typed order", () => {
    expect(addNewestFirst(["/var"], ["/home", "/srv"])).toEqual(["/home", "/srv", "/var"]);
  });

  test("skips entries that already exist or repeat", () => {
    const values = ["/var"];
    expect(addNewestFirst(values, ["/var"])).toBe(values);
    expect(addNewestFirst(values, ["/home", "/home", "/var"])).toEqual(["/home", "/var"]);
  });

  test("moves entries up and down", () => {
    expect(moveEntry(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moveEntry(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
  });

  test("ignores moves outside the list", () => {
    const values = ["a", "b"];
    expect(moveEntry(values, 0, -1)).toBe(values);
    expect(moveEntry(values, 1, 2)).toBe(values);
    expect(moveEntry(values, 1, 1)).toBe(values);
  });
});
