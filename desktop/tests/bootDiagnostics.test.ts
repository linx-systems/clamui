import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../public/boot-diagnostics.js", import.meta.url), "utf8");

type Listener = (event: Record<string, unknown>) => void;

function fakePage(options: { mounted: boolean; withTauri?: boolean }) {
  const reports: Array<{ kind: string; message: string }> = [];
  const timers: Array<() => void> = [];
  const listeners: Record<string, Listener[]> = {};
  const status = { textContent: "", hidden: true };
  const detail = { textContent: "", hidden: true };
  const box = {
    hidden: true,
    querySelector: (selector: string) => (selector === "[data-boot-status]" ? status : detail),
  };
  const document = {
    readyState: "loading",
    querySelector: () => (options.mounted ? null : box),
    addEventListener: () => {},
  };
  const window: Record<string, unknown> = {
    addEventListener: (name: string, listener: Listener) => {
      (listeners[name] ??= []).push(listener);
    },
    __TAURI_INTERNALS__: options.withTauri === false ? undefined : {
      invoke: async (command: string, args: { kind: string; message: string }) => {
        expect(command).toBe("frontend_report");
        reports.push(args);
      },
    },
  };
  new Function("window", "document", "location", "setTimeout", source)(
    window,
    document,
    { href: "tauri://localhost/" },
    (callback: () => void) => timers.push(callback),
  );
  return { window, box, status, detail, reports, timers, listeners };
}

describe("boot-diagnostics.js", () => {
  test("shows and reports a script error that happens before React mounted", () => {
    const page = fakePage({ mounted: false });
    page.listeners.error[0]({ message: "Unexpected token", filename: "index.js", lineno: 3, colno: 9 });
    expect(page.box.hidden).toBe(false);
    expect(page.status.textContent).toContain("Unexpected token");
    expect(page.detail.textContent).toContain("index.js:3:9");
    expect(page.reports).toHaveLength(1);
    expect(page.reports[0].kind).toBe("boot-error");
  });

  test("reports a script file that failed to load", () => {
    const page = fakePage({ mounted: false });
    page.listeners.error[0]({ target: { src: "tauri://localhost/assets/index.js" } });
    expect(page.status.textContent).toContain("could not load tauri://localhost/assets/index.js");
  });

  test("stays silent after React mounted", () => {
    const page = fakePage({ mounted: true });
    page.listeners.error[0]({ message: "late error" });
    page.timers[0]();
    expect(page.box.hidden).toBe(true);
    expect(page.reports).toHaveLength(0);
  });

  test("explains a stalled start after the timeout and reports it once", () => {
    const page = fakePage({ mounted: false });
    expect(page.timers).toHaveLength(1);
    page.timers[0]();
    expect(page.status.textContent).toContain("still starting after 8 seconds");
    expect(page.detail.textContent).toContain("tauriInternals=object");
    expect(page.reports.map((report) => report.kind)).toEqual(["boot-stalled"]);
  });

  test("works without the native bridge", () => {
    const page = fakePage({ mounted: false, withTauri: false });
    page.timers[0]();
    expect(page.detail.textContent).toContain("tauriInternals=undefined");
    expect(page.reports).toHaveLength(0);
  });
});
