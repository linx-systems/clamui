import { describe, expect, mock, test } from "bun:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

mock.module("../src/api", () => ({ request: async () => ({}) }));
mock.module("@tauri-apps/api/core", () => ({ invoke: async () => undefined }));
Object.assign(globalThis, { window: {} });

const { StartupFailure, describeFailure } = await import("../src/StartupBoundary");

describe("startup failure display", () => {
  test("describes an Error with its name, message and component stack", () => {
    const text = describeFailure(new TypeError("x is undefined"), "\n    at App");
    expect(text).toContain("TypeError: x is undefined");
    expect(text).toContain("Component stack:\n    at App");
  });

  test("describes a thrown non-Error value", () => {
    expect(describeFailure("boom")).toBe("boom");
  });

  test("renders the details as text, never as markup", () => {
    const markup = renderToStaticMarkup(
      createElement(StartupFailure, { details: "<img src=x onerror=alert(1)>" }),
    );
    expect(markup).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(markup).not.toContain("<img");
    expect(markup).toContain('class="startup-error-details"');
  });
});
