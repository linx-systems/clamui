import { describe, expect, test } from "bun:test";

import { type ConfigDocument, isConfigDirty, mergeAuthorizedConfig } from "../src/configAuthorize";

function document(overrides: Partial<ConfigDocument> = {}): ConfigDocument {
  return {
    kind: "clamd",
    path: "/etc/clamav/clamd.conf",
    baselinePath: "/etc/clamav/clamd.conf",
    values: { OnAccessIncludePath: ["/home"] },
    baseline: { OnAccessIncludePath: ["/home"] },
    needsSizeUnitMigration: false,
    readable: false,
    ...overrides,
  };
}

describe("isConfigDirty", () => {
  test("is false when the form matches its baseline and path", () => {
    expect(isConfigDirty(document())).toBe(false);
  });

  test("is true when the form has unsaved value edits", () => {
    const dirty = document({ values: { OnAccessIncludePath: ["/home", "/srv"] } });
    expect(isConfigDirty(dirty)).toBe(true);
  });

  test("is true when the selected path has not been saved", () => {
    const dirty = document({ path: "/etc/clamav/clamd.conf", baselinePath: "/etc/clamav/old-clamd.conf" });
    expect(isConfigDirty(dirty)).toBe(true);
  });
});

describe("mergeAuthorizedConfig", () => {
  test("replaces the form with the authoritative values when nothing is dirty", () => {
    const clean = document();
    const next = mergeAuthorizedConfig(clean, { path: clean.path, values: { OnAccessIncludePath: ["/var"] }, readable: true }, clean.baselinePath);
    expect(next.values).toEqual({ OnAccessIncludePath: ["/var"] });
    expect(next.baseline).toEqual({ OnAccessIncludePath: ["/var"] });
  });

  test("keeps unsaved edits and only refreshes the baseline when the form is dirty", () => {
    const dirty = document({ values: { OnAccessIncludePath: ["/home", "/srv"] } });
    const next = mergeAuthorizedConfig(dirty, { path: dirty.path, values: { OnAccessIncludePath: ["/home"] }, readable: true }, dirty.baselinePath);
    expect(next.values).toEqual({ OnAccessIncludePath: ["/home", "/srv"] });
    expect(next.baseline).toEqual({ OnAccessIncludePath: ["/home"] });
  });

  test("does not mutate the original document's values or baseline", () => {
    const dirty = document({ values: { OnAccessIncludePath: ["/home", "/srv"] } });
    const next = mergeAuthorizedConfig(dirty, { path: dirty.path, values: { OnAccessIncludePath: ["/home"] }, readable: true }, dirty.baselinePath);
    next.values.OnAccessIncludePath.push("/mutated");
    next.baseline.OnAccessIncludePath.push("/mutated");
    expect(dirty.values).toEqual({ OnAccessIncludePath: ["/home", "/srv"] });
    expect(dirty.baseline).toEqual({ OnAccessIncludePath: ["/home"] });
  });

  test("carries over readable, error, and migration flags from the authorized read", () => {
    const clean = document();
    const next = mergeAuthorizedConfig(clean, { path: clean.path, values: {}, readable: false, error: "denied", needs_size_unit_migration: true }, clean.baselinePath);
    expect(next.readable).toBe(false);
    expect(next.error).toBe("denied");
    expect(next.needsSizeUnitMigration).toBe(true);
  });

  test("updates the baseline path to the newly persisted path", () => {
    const clean = document();
    const next = mergeAuthorizedConfig(clean, { path: clean.path, values: {}, readable: true }, "/etc/clamav/clamd.conf.new");
    expect(next.baselinePath).toBe("/etc/clamav/clamd.conf.new");
  });
});
