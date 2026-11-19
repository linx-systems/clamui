import { describe, expect, test } from "bun:test";
import { INITIAL_MOUNTED_PAGES } from "../src/initialMountedPages";

describe("initial mounted pages", () => {
  test("mounts Scan alongside Dashboard from the start", () => {
    // selectPage() dispatches clamui-page-selected/clamui-quick-scan and
    // open-targets synchronously; Scan must already be mounted so its
    // window listeners exist before the first navigation/quick-scan event.
    expect(INITIAL_MOUNTED_PAGES).toContain("dashboard");
    expect(INITIAL_MOUNTED_PAGES).toContain("scan");
  });
});
