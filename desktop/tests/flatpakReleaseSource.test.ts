import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const renderer = fileURLToPath(
  new URL("../../scripts/flatpak-release-source.awk", import.meta.url),
);
const checkoutManifest = fileURLToPath(
  new URL("../../flathub/io.github.linx_systems.ClamUI.yml", import.meta.url),
);
const releaseUrl = "https://github.com/linx-systems/clamui.git";
const releaseCommit = "0123456789abcdef0123456789abcdef01234567";

type ClamuiModule = {
  name: string;
  sources: Array<string | Record<string, unknown>>;
  buildsystem?: string;
};

type Manifest = {
  modules: ClamuiModule[];
};

function render(manifest: string, commit = releaseCommit) {
  const result = Bun.spawnSync({
    cmd: [
      "awk",
      "-v",
      `url=${releaseUrl}`,
      "-v",
      `commit=${commit}`,
      "-f",
      renderer,
    ],
    stdin: new TextEncoder().encode(manifest),
  });

  return {
    exitCode: result.exitCode,
    stderr: new TextDecoder().decode(result.stderr),
    stdout: new TextDecoder().decode(result.stdout),
  };
}

function clamuiModule(manifest: string) {
  const parsed = Bun.YAML.parse(manifest) as Manifest;
  const clamui = parsed.modules.find((module) => module.name === "clamui");
  expect(clamui).toBeDefined();
  return clamui!;
}

describe("flatpak release source renderer", () => {
  test("converts the canonical skip-containing checkout source", () => {
    const original = readFileSync(checkoutManifest, "utf8");
    const result = render(original);

    expect(result.exitCode).toBe(0);

    const clamui = clamuiModule(result.stdout);
    expect(clamui.sources[0]).toEqual({
      type: "git",
      url: releaseUrl,
      commit: releaseCommit,
    });
    expect(clamui.sources).toContain("cargo-sources.json");
    expect(clamui.sources).toContain("bun-sources.json");
  });

  test("emits all-numeric release commits as YAML strings", () => {
    const commit = "1234567890123456789012345678901234567890";
    const result = render(`modules:
  - name: clamui
    sources:
      - type: dir
        path: ..
`, commit);

    expect(result.exitCode).toBe(0);
    expect(clamuiModule(result.stdout).sources[0]).toEqual({
      type: "git",
      url: releaseUrl,
      commit,
    });
  });

  test("recognizes reordered local source keys and preserves unrelated sources", () => {
    const manifest = `modules:
  - name: clamui
    buildsystem: simple
    sources:
      - path: ..
        skip:
          - target
          - desktop/node_modules
        type: dir
      # This local source is not the application checkout.
      - type: dir
        path: vendor
        skip:
          - cache
      - type: archive
        url: https://example.invalid/dependency.tar.gz
      - cargo-sources.json
      - bun-sources.json
`;
    const result = render(manifest);
    expect(result.exitCode).toBe(0);
    const clamui = clamuiModule(result.stdout);
    expect(clamui.buildsystem).toBe("simple");
    expect(clamui.sources).toEqual([
      { type: "git", url: releaseUrl, commit: releaseCommit },
      { type: "dir", path: "vendor", skip: ["cache"] },
      { type: "archive", url: "https://example.invalid/dependency.tar.gz" },
      "cargo-sources.json",
      "bun-sources.json",
    ]);
  });

  test.each([
    [
      "absent checkout source",
      `modules:
  - name: clamui
    sources:
      - type: dir
        path: vendor
`,
      "found none",
    ],
    [
      "ambiguous checkout sources",
      `modules:
  - name: clamui
    sources:
      - type: dir
        path: ..
      - path: ..
        type: dir
`,
      "found 2",
    ],
  ])("refuses %s instead of producing a release manifest", (_name, manifest, message) => {
    const result = render(manifest);

    expect(result.exitCode).toBe(1);
    expect(result.stdout).toBe("");
    expect(result.stderr).toContain(message);
  });
});
