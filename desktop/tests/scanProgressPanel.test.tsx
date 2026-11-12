import { describe, expect, test } from "bun:test";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ScanProgressPanel } from "../src/ScanProgressPanel";

type Progress = ComponentProps<typeof ScanProgressPanel>["progress"];

function renderProgress(progress: Progress, showLiveProgress = true): string {
  return renderToStaticMarkup(createElement(ScanProgressPanel, {
    progress,
    liveThreats: [],
    showLiveProgress,
    multipleTargets: true,
    onCancel: () => {},
  }));
}

function progressTag(markup: string): string {
  const tag = markup.match(/<progress\b[^>]*>/)?.[0];
  expect(tag).toBeDefined();
  return tag ?? "";
}

describe("ScanProgressPanel", () => {
  test("shows target context and core overall count separately from the current target", () => {
    const markup = renderProgress({
      path: "/home/example/Documents",
      target_index: 2,
      target_count: 3,
      files_scanned: 4,
      files_scanned_total: 17,
      files_total: 10,
      percentage: 40,
    });

    expect(markup).toContain("Target 2/3: /home/example/Documents");
    expect(markup).toContain("17 files scanned overall");
    expect(markup).toContain("4 files scanned");
    expect(progressTag(markup)).toContain('value="40"');
    expect(markup).not.toContain("File estimate is approximate; progress is indeterminate.");
  });

  test("uses indeterminate progress and a neutral explanation for approximate, missing, or exceeded estimates", () => {
    const cases: Progress[] = [
      { files_scanned: 4, files_total: 10, percentage: 40, estimate_approximate: true },
      { files_scanned: 4, files_total: null, percentage: null },
      { files_scanned: 11, files_total: 10, estimate_exceeded: true },
      { files_scanned: 11, files_total: 10 },
      { files_scanned: 4, files_total: 10, percentage: null },
    ];
    for (const progress of cases) {
      const markup = renderProgress(progress);
      expect(progressTag(markup)).not.toContain("value=");
      expect(markup).toContain("File estimate is approximate; progress is indeterminate.");
      expect(markup).not.toContain("Estimated file count exceeded");
    }
  });

  test("supports older events without a percentage or overall count", () => {
    const markup = renderProgress({ path: "/legacy", scanned_files: 2, total_files: 8 });
    expect(markup).toContain("Scan target: /legacy");
    expect(markup).toContain("2 files scanned");
    expect(markup).not.toContain("scanned overall");
    expect(progressTag(markup)).toContain('value="25"');
  });

  test("keeps target and overall counts visible when live progress is disabled", () => {
    const markup = renderProgress({
      path: "/second", target_index: 2, target_count: 3, files_scanned_total: 17,
      current_file: "/second/private-file", files_scanned: 4, files_total: 10,
    }, false);
    expect(markup).toContain("Target 2/3: /second");
    expect(markup).toContain("17 files scanned overall");
    expect(markup).not.toContain("/second/private-file");
    expect(markup).not.toContain("<progress");
  });
});
