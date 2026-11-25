import { invoke } from "@tauri-apps/api/core";

declare global {
  interface Window {
    /** Created by public/boot-diagnostics.js, which runs before this bundle. */
    __clamuiBoot?: { mark(text: string): void };
  }
}

/** Add a line to the boot log that the page shows if the app never mounts. */
export function bootMark(text: string): void {
  window.__clamuiBoot?.mark(text);
}

// This module is imported first by main.tsx, so this marks that the bundle started to run.
bootMark("bundle started");

export type FrontendReportKind = "catalog" | "render" | "ready-failed";

/** Leave a diagnostic line in the native debug log. Never throws. */
export async function reportFrontend(kind: FrontendReportKind, message: string): Promise<void> {
  try {
    await invoke("frontend_report", { kind, message: message.slice(0, 2000) });
  } catch {
    // The report is best effort; the page already shows the failure.
  }
}

/** Tell the native watchdog that React mounted. */
export async function reportFrontendReady(): Promise<void> {
  try {
    await invoke("frontend_ready");
  } catch (error) {
    await reportFrontend("ready-failed", error instanceof Error ? error.message : String(error));
  }
}
