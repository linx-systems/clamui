import { describe, expect, test } from "bun:test";

import { applyAccentColor } from "../src/accentColor";

function fakeRoot() {
  const values = new Map<string, string>();
  return {
    values,
    style: {
      setProperty: (name: string, value: string | null) => {
        values.set(name, value ?? "");
      },
      removeProperty: (name: string) => {
        const previous = values.get(name) ?? "";
        values.delete(name);
        return previous;
      },
    },
  };
}

describe("applyAccentColor", () => {
  test("sets accent, darker hover, and focus ring from a system color", () => {
    const root = fakeRoot();
    applyAccentColor("#9141ac", root);
    expect(Object.fromEntries(root.values)).toEqual({
      "--accent": "#9141ac",
      "--accent-hover": "#7d3894",
      "--accent-fg": "#ffffff",
      "--accent-hover-fg": "#ffffff",
      "--focus": "#9141ac",
    });
  });

  test("keeps black and white within channel bounds", () => {
    const root = fakeRoot();
    applyAccentColor("#FFFFFF", root);
    expect(root.values.get("--accent-hover")).toBe("#dbdbdb");
    expect(root.values.get("--accent-fg")).toBe("#000000");
    expect(root.values.get("--accent-hover-fg")).toBe("#000000");
    applyAccentColor("#000000", root);
    expect(root.values.get("--accent-hover")).toBe("#000000");
    expect(root.values.get("--accent-fg")).toBe("#ffffff");
  });

  test("ignores malformed values and keeps the current accent", () => {
    const root = fakeRoot();
    applyAccentColor("#e66100", root);
    for (const invalid of ["", "e66100", "#e661", "#e66100ff", "#gggggg", "red", "#e66100;color:red"]) {
      applyAccentColor(invalid, root);
    }
    expect(root.values.get("--accent")).toBe("#e66100");
  });

  test("keeps button text readable when hover crosses the luminance threshold", () => {
    const root = fakeRoot();
    applyAccentColor("#777777", root);
    expect(root.values.get("--accent-fg")).toBe("#000000");
    expect(root.values.get("--accent-hover-fg")).toBe("#ffffff");
  });

  test("restores stylesheet defaults when the system accent is unset", () => {
    const root = fakeRoot();
    applyAccentColor("#e66100", root);
    applyAccentColor(null, root);
    expect(root.values.size).toBe(0);
  });
});
