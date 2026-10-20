import { describe, expect, mock, test } from "bun:test";

let response: unknown;
mock.module("../src/api", () => ({ request: async () => response }));

// The mock must be registered before loading the module under test.
const { loadCatalog, ngettext } = await import("../src/i18n");
const documentElement = { lang: "" };
Object.assign(globalThis, { document: { documentElement } });

async function loadPluralCatalog(plural_rule: string, forms: string[]): Promise<void> {
  response = {
    language: "test",
    languages: [],
    messages: { "file\u0000files": forms },
    plural_rule,
  };
  await loadCatalog();
}

describe("ngettext", () => {
  test("uses n != 1 catalog forms", async () => {
    await loadPluralCatalog("nplurals=2; plural=(n != 1);", ["one {count} file", "{count} many files"]);
    expect(ngettext("file", "files", 0)).toBe("0 many files");
    expect(ngettext("file", "files", 1)).toBe("one 1 file");
    expect(ngettext("file", "files", 2)).toBe("2 many files");
  });

  test("uses n > 1 catalog forms", async () => {
    await loadPluralCatalog("nplurals=2; plural=(n > 1);", ["singular {count} file", "plural {count} files"]);
    expect(ngettext("file", "files", 0)).toBe("singular 0 file");
    expect(ngettext("file", "files", 1)).toBe("singular 1 file");
    expect(ngettext("file", "files", 2)).toBe("plural 2 files");
  });

  test("uses the only form in one-form catalogs", async () => {
    await loadPluralCatalog("nplurals=1; plural=0;", ["{count} file count"]);
    expect(ngettext("file", "files", 0)).toBe("0 file count");
    expect(ngettext("file", "files", 1)).toBe("1 file count");
    expect(ngettext("file", "files", 2)).toBe("2 file count");
  });
});
