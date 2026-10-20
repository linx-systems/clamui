import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { _ } from "./i18n";


export type NotificationType = "success" | "error" | "info" | "warning";
export type FileFilter = { name: string; extensions: string[] };
export type NativeEvent = { event: string; data: unknown };
export type Credits = {
  contributors: string[];
  translator_credits: string | null;
};

type SaveResult = { saved: boolean; path?: string };
type PathsResult = { paths: string[] };

const MEBIBYTE = 1024 * 1024;
const LARGE_EXPORT_BYTES = 10 * MEBIBYTE;

function assertText(value: string, name: string): void {
  if (typeof value !== "string") {
    throw new TypeError(`${name} must be text`);
  }
}

function bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function isNativeEvent(value: unknown): value is NativeEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    "event" in value &&
    typeof value.event === "string" &&
    "data" in value
  );
}

async function deferLargeOperation<T>(size: number, operation: () => Promise<T>): Promise<T> {
  if (size >= LARGE_EXPORT_BYTES) {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  }
  return operation();
}

/** Invoke an allowlisted operation provided by the native runtime. */
export async function request<T = unknown>(
  operation: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  try {
    return await invoke<T>("request", { action: operation, args });
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : String(error));
  }
}

function isCredits(value: unknown): value is Credits {
  return (
    typeof value === "object" &&
    value !== null &&
    "contributors" in value &&
    Array.isArray(value.contributors) &&
    value.contributors.every((contributor) => typeof contributor === "string") &&
    "translator_credits" in value &&
    (typeof value.translator_credits === "string" || value.translator_credits === null)
  );
}

/** Load embedded contributor and locale translator credits through the core request path. */
export async function credits(): Promise<Credits> {
  const result = await request<unknown>("app.credits", {});
  if (!isCredits(result)) {
    throw new Error(_("The contributor credits response was invalid."));
  }
  return result;
}

/** Subscribe to the sole native event channel. Call the returned function on cleanup. */
export async function onEvent(
  handler: (event: NativeEvent) => void,
): Promise<() => void> {
  const localListener = (event: Event) => {
    if (event instanceof CustomEvent && isNativeEvent(event.detail)) {
      handler(event.detail);
    }
  };
  window.addEventListener("clamui-event", localListener);

  try {
    const unlistenNative = await listen<unknown>("clamui-event", ({ payload }) => {
      if (isNativeEvent(payload)) {
        handler(payload);
      }
    });
    return () => {
      unlistenNative();
      window.removeEventListener("clamui-event", localListener);
    };
  } catch (error) {
    window.removeEventListener("clamui-event", localListener);
    throw error;
  }
}

/** Show an in-app notification. Native OS delivery applies its own preferences. */
export function notify(message: string, type: NotificationType = "info"): void {
  if (!message.trim()) {
    return;
  }
  window.dispatchEvent(new CustomEvent("clamui-notify", { detail: { message, type } }));
}


/** Ask the shell to switch pages without coupling pages to App. */
export function navigate(page: string, args: Record<string, unknown> = {}): void {
  window.dispatchEvent(new CustomEvent("clamui-navigate", { detail: { page, args } }));
}

export async function openPaths(
  options: { directory?: boolean; multiple?: boolean } = {},
): Promise<string[]> {
  const result = await invoke<PathsResult>("choose_paths", { options });
  return Array.isArray(result.paths) ? result.paths.filter((path): path is string => typeof path === "string") : [];
}

export async function saveText(
  content: string,
  defaultName: string,
  filters?: FileFilter[],
): Promise<boolean> {
  assertText(content, "content");
  return deferLargeOperation(bytes(content), async () => {
    const result = await invoke<SaveResult>("save_export", {
      content,
      defaultName,
      filters,
      encoding: "utf8",
    });
    return result.saved === true;
  });
}

export async function saveBinary(
  contentBase64: string,
  defaultName: string,
  filters?: FileFilter[],
): Promise<boolean> {
  assertText(contentBase64, "contentBase64");
  // Base64 is 4/3 the original payload; schedule very large native writes after paint.
  const estimatedBytes = Math.floor((contentBase64.length * 3) / 4);
  return deferLargeOperation(estimatedBytes, async () => {
    const result = await invoke<SaveResult>("save_export", {
      content: contentBase64,
      defaultName,
      filters,
      encoding: "base64",
    });
    return result.saved === true;
  });
}

export async function copyText(text: string): Promise<void> {
  assertText(text, "text");
  // Tauri invocation is async; explicitly yield before IPC for clipboard payloads over 1 MiB.
  if (bytes(text) > MEBIBYTE) {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  }
  await invoke<void>("copy_text", { text });
}

export async function openExternal(url: string): Promise<void> {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(_("Enter a valid HTTP(S) address"));
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error(_("Only HTTP(S) addresses may be opened externally"));
  }
  await invoke<void>("open_external", { url: parsed.toString() });
}

/** Open a user-selected existing local file or folder in its native handler. */
export async function openPath(path: string): Promise<void> {
  assertText(path, "path");
  if (!path.trim()) {
    throw new Error(_("Choose a file or folder first"));
  }
  await invoke<void>("open_path", { path });
}

export async function closeApplication(
  choice?: "minimize" | "quit" | "cancel",
  remember?: boolean,
): Promise<{ action: "hide" | "quit" | "prompt" }> {
  return invoke<{ action: "hide" | "quit" | "prompt" }>("app_close", { choice, remember });
}

export type StartupState = {
  paths: string[];
  virustotal: boolean;
  tray_available: boolean;
  version: string;
  active_jobs?: string[];
};

export function startupState(): Promise<StartupState> {
  return invoke<StartupState>("startup_state");
}

export type NetworkEndpoint = {
  address: string;
  port: number | null;
  virustotal_url: string | null;
};

export type NetworkProcess = {
  name: string;
  pid: number;
};

export type NetworkSocket = {
  protocol: "tcp" | "udp";
  state: string;
  kind: "listener" | "connection";
  local: NetworkEndpoint;
  remote: NetworkEndpoint | null;
  processes: NetworkProcess[];
};

export type NetworkSnapshot = {
  status: "available" | "partial" | "unavailable";
  captured_at: string;
  sockets: NetworkSocket[];
  unparsed_lines: number;
  limited: boolean;
  message: string | null;
};

/** Request one current local socket snapshot with no filters or process arguments. */
export function networkSnapshot(): Promise<unknown> {
  return request("network.snapshot", {});
}
