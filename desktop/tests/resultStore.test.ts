import { describe, expect, test } from "bun:test";
import { createResultStore, STORED_OUTPUT_LIMIT, trimmedForStorage } from "../src/resultStore";

type ScanLike = { status: string; stdout?: string; scanned_files?: number; per_target_results?: ScanLike[] };
const isScan = (value: unknown): value is ScanLike =>
  value !== null && typeof value === "object" && typeof (value as ScanLike).status === "string";

/** sessionStorage stand-in that enforces a quota like the browser's ~5 MB. */
function quotaStorage(quota: number) {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    removeItem: (key: string) => void data.delete(key),
    setItem(key: string, value: string) {
      if (value.length > quota) throw new DOMException("quota", "QuotaExceededError");
      data.set(key, value);
    },
  };
}

// 556k "file: OK" lines, as reported in a full daemon scan of a desktop.
const hugeScan = (): ScanLike => ({
  status: "clean",
  scanned_files: 556_000,
  stdout: "/home/user/some/file.txt: OK\n".repeat(556_000),
});

describe("result store", () => {
  test("a result too big for sessionStorage still reaches a lazily mounted Results page", () => {
    const storage = quotaStorage(5 * 1024 * 1024);
    const store = createResultStore(() => storage);
    const scan = hugeScan();

    store.remember("scan", scan);

    // Results mounts after the scan finished and the navigate event was missed.
    const recalled = store.recall("scan", isScan);
    expect(recalled).toBe(scan);
    expect(recalled?.scanned_files).toBe(556_000);
  });

  test("falls back to a trimmed copy in sessionStorage that survives a reload", () => {
    const storage = quotaStorage(5 * 1024 * 1024);
    createResultStore(() => storage).remember("scan", hugeScan());

    const afterReload = createResultStore(() => storage).recall("scan", isScan);

    expect(afterReload?.status).toBe("clean");
    expect(afterReload?.scanned_files).toBe(556_000);
    expect(afterReload?.stdout?.length).toBeLessThan(STORED_OUTPUT_LIMIT + 200);
    expect(afterReload?.stdout?.endsWith("file.txt: OK\n")).toBe(true);
  });

  test("small results are stored untrimmed", () => {
    const storage = quotaStorage(5 * 1024 * 1024);
    const scan: ScanLike = { status: "infected", stdout: "a: Eicar FOUND\n" };
    createResultStore(() => storage).remember("scan", scan);
    expect(createResultStore(() => storage).recall("scan", isScan)).toEqual(scan);
  });

  test("keeps working without sessionStorage or when it always throws", () => {
    const scan: ScanLike = { status: "clean" };
    const none = createResultStore(() => null);
    none.remember("scan", scan);
    expect(none.recall("scan", isScan)).toBe(scan);

    const broken = createResultStore(() => quotaStorage(0));
    broken.remember("virustotal", scan);
    expect(broken.recall("virustotal", isScan)).toBe(scan);
    expect(createResultStore(() => null).recall("scan", isScan)).toBeNull();
  });

  test("a newer result replaces the older one and kinds stay separate", () => {
    const store = createResultStore(() => quotaStorage(1024));
    store.remember("scan", { status: "clean" });
    store.remember("scan", { status: "infected" });
    store.remember("virustotal", { status: "detected" });
    expect(store.recall("scan", isScan)?.status).toBe("infected");
    expect(store.recall("virustotal", isScan)?.status).toBe("detected");
  });

  test("ignores corrupt or mismatching stored values", () => {
    const storage = quotaStorage(1024);
    storage.data.set("clamui-last-scan-result", "{not json");
    expect(createResultStore(() => storage).recall("scan", isScan)).toBeNull();
    storage.data.set("clamui-last-scan-result", JSON.stringify({ nope: true }));
    expect(createResultStore(() => storage).recall("scan", isScan)).toBeNull();
  });

  test("trimming covers per-target results and leaves other fields alone", () => {
    const trimmed = trimmedForStorage(
      { status: "clean", stdout: "x".repeat(50), per_target_results: [{ status: "clean", stdout: "y".repeat(50) }] },
      10,
    ) as ScanLike;
    expect(trimmed.stdout?.endsWith("x".repeat(10))).toBe(true);
    expect(trimmed.per_target_results?.[0].stdout?.endsWith("y".repeat(10))).toBe(true);
    expect(trimmed.status).toBe("clean");
  });
});
