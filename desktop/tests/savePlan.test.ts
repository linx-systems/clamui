import { describe, expect, test } from "bun:test";
import { type ConfigDocument, isDocumentPending, partitionByElevation, pendingProposals } from "../src/savePlan";

function document(overrides: Partial<ConfigDocument> = {}): ConfigDocument {
  return {
    kind: "freshclam",
    values: { DatabaseMirror: ["database.clamav.net"] },
    baseline: { DatabaseMirror: ["database.clamav.net"] },
    path: "/etc/freshclam.conf",
    baselinePath: "/etc/freshclam.conf",
    ...overrides,
  };
}

describe("isDocumentPending", () => {
  test("a document with unedited values is not pending", () => {
    expect(isDocumentPending(document())).toBe(false);
  });

  test("an edited document is pending", () => {
    expect(isDocumentPending(document({ values: { DatabaseMirror: ["db.local"] } }))).toBe(true);
  });

  test("a clamd document awaiting a size-unit migration is pending even with unedited values", () => {
    expect(isDocumentPending(document({ kind: "clamd", needsSizeUnitMigration: true }))).toBe(true);
  });

  test("null or undefined documents are never pending", () => {
    expect(isDocumentPending(null)).toBe(false);
    expect(isDocumentPending(undefined)).toBe(false);
  });
});

describe("pendingProposals", () => {
  test("keeps only dirty documents, projected down to kind/path/values", () => {
    const clean = document();
    const dirty = document({ path: "/etc/clamd.d/scan.conf", kind: "clamd", values: { LogVerbose: ["yes"] }, baseline: { LogVerbose: ["no"] } });
    expect(pendingProposals([clean, dirty, null, undefined])).toEqual([
      { kind: "clamd", path: "/etc/clamd.d/scan.conf", values: { LogVerbose: ["yes"] } },
    ]);
  });

  test("returns an empty list when nothing is dirty", () => {
    expect(pendingProposals([document(), document()])).toEqual([]);
  });
});

describe("partitionByElevation", () => {
  test("splits proposals by the backend's reported elevation requirement", () => {
    const proposals = [
      { kind: "freshclam" as const, path: "/etc/freshclam.conf", values: {} },
      { kind: "clamd" as const, path: "/etc/clamd.d/scan.conf", values: {} },
    ];
    const needsElevation = new Map([
      ["/etc/freshclam.conf", false],
      ["/etc/clamd.d/scan.conf", true],
    ]);
    expect(partitionByElevation(proposals, needsElevation)).toEqual({
      direct: [proposals[0]],
      deferred: [proposals[1]],
    });
  });

  test("treats an unknown path as not requiring elevation", () => {
    const proposals = [{ kind: "freshclam" as const, path: "/home/user/custom.conf", values: {} }];
    expect(partitionByElevation(proposals, new Map())).toEqual({ direct: proposals, deferred: [] });
  });

  test("returns empty partitions for an empty proposal list", () => {
    expect(partitionByElevation([], new Map())).toEqual({ direct: [], deferred: [] });
  });
});
