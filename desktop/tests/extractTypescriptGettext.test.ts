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

  test("reports source names for invalid TypeScript instead of silently omitting messages", () => {
    expect(() => extractTypeScriptGettext("const = ;", "broken.tsx")).toThrow("Unable to parse broken.tsx");
  });
});
