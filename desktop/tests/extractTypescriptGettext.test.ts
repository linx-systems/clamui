import { describe, expect, test } from "bun:test";

import { extractTypeScriptGettext } from "../../scripts/extract-typescript-gettext";

describe("TypeScript gettext extraction", () => {
  test("extracts static TSX messages, plurals, contexts, templates, and adjacent translator notes", () => {
    const source = `
const component = <section>
  {_("Escaped café\\nmessage")}
  {_(\`Static template\`)}
  {ngettext("one file", "many files", count)}
  {pgettext("menu", "Open")}
  {_(
    // Translators: Visible when a scan finishes.
    "Scan complete"
  )}
  {_(prefix + suffix)}
</section>;
`;

    expect(extractTypeScriptGettext(source, "fixture.tsx")).toEqual([
      { name: "_", messages: ["Escaped café\nmessage"], line: 3, comments: [] },
      { name: "_", messages: ["Static template"], line: 4, comments: [] },
      { name: "ngettext", messages: ["one file", "many files"], line: 5, comments: [] },
      { name: "pgettext", messages: ["menu", "Open"], line: 6, comments: [] },
      {
        name: "_",
        messages: ["Scan complete"],
        line: 7,
        comments: ["Translators: Visible when a scan finishes."],
      },
    ]);
  });

  test("uses TypeScript grammar for angle assertions in .ts files", () => {
    const source = `const value = <number>1;
const label = _("Label");`;

    expect(extractTypeScriptGettext(source, "fixture.ts")).toEqual([
      { name: "_", messages: ["Label"], line: 2, comments: [] },
    ]);
  });

  test("extracts optional-call helpers", () => {
    const source = `const label = _?.("Optional label");
const files = ngettext?.("one item", "many items", count);`;

    expect(extractTypeScriptGettext(source, "fixture.ts")).toEqual([
      { name: "_", messages: ["Optional label"], line: 1, comments: [] },
      { name: "ngettext", messages: ["one item", "many items"], line: 2, comments: [] },
    ]);
  });

  test("reports source names for invalid TypeScript instead of silently omitting messages", () => {
    expect(() => extractTypeScriptGettext("const = ;", "broken.tsx")).toThrow("Unable to parse broken.tsx");
  });
});
