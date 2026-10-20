type Catalog = Map<string, string[]>;

const [templatePath, ...catalogArguments] = Bun.argv.slice(2);

if (!templatePath || catalogArguments.length === 0) {
  throw new Error("Usage: bun scripts/check-compiled-catalogs.ts TEMPLATE_MO LANGUAGE=CATALOG_MO [...]");
}

function checkedRange(bytes: Uint8Array, offset: number, length: number, label: string): void {
  if (offset > bytes.byteLength || length > bytes.byteLength - offset) {
    throw new Error(`${label} is outside the MO file`);
  }
}

function parseCatalog(bytes: Uint8Array): Catalog {
  if (bytes.byteLength < 28) throw new Error("MO file is too short");

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const magic = view.getUint32(0, true);
  const littleEndian = magic === 0x950412de
    ? true
    : magic === 0xde120495
      ? false
      : undefined;
  if (littleEndian === undefined) throw new Error("invalid MO magic");

  const count = view.getUint32(8, littleEndian);
  const originalsOffset = view.getUint32(12, littleEndian);
  const translationsOffset = view.getUint32(16, littleEndian);
  checkedRange(bytes, originalsOffset, count * 8, "MO source table");
  checkedRange(bytes, translationsOffset, count * 8, "MO translation table");

  const decoder = new TextDecoder("utf-8", { fatal: true });
  const catalog = new Map<string, string[]>();
  for (let index = 0; index < count; index += 1) {
    const originalLength = view.getUint32(originalsOffset + index * 8, littleEndian);
    const originalOffset = view.getUint32(originalsOffset + index * 8 + 4, littleEndian);
    const translationLength = view.getUint32(translationsOffset + index * 8, littleEndian);
    const translationOffset = view.getUint32(translationsOffset + index * 8 + 4, littleEndian);
    checkedRange(bytes, originalOffset, originalLength, "MO source string");
    checkedRange(bytes, translationOffset, translationLength, "MO translation string");

    const original = decoder.decode(bytes.subarray(originalOffset, originalOffset + originalLength));
    const translation = decoder.decode(bytes.subarray(translationOffset, translationOffset + translationLength));
    if (catalog.has(original)) throw new Error("MO file contains a duplicate source key");
    catalog.set(original, translation.split("\0"));
  }
  return catalog;
}

function pluralFormCount(catalog: Catalog): number {
  const header = catalog.get("")?.[0] ?? "";
  const match = header.match(/^Plural-Forms:\s*nplurals=(\d+);/m);
  const count = match ? Number.parseInt(match[1], 10) : 2;
  return Number.isSafeInteger(count) && count > 0 ? count : 2;
}

function namedBracePlaceholders(value: string): string[] {
  const placeholders: string[] = [];
  const pattern = /^\{([A-Za-z_][A-Za-z0-9_]*)(:[^{}]*)?\}/;
  for (let index = 0; index < value.length;) {
    if (value[index] === "{" && value[index + 1] === "{") {
      index += 2;
      continue;
    }
    const match = value.slice(index).match(pattern);
    if (match) {
      placeholders.push(match[0]);
      index += match[0].length;
    } else {
      index += 1;
    }
  }
  return placeholders.sort();
}

function displayKey(key: string): string {
  return key.replace(/\0/g, "\\0").replace(/\u0004/g, "\\u0004");
}

let failures = 0;
function fail(path: string, message: string): void {
  failures += 1;
  console.error(`::error file=${path}::${message}`);
}

async function readCatalog(path: string): Promise<Catalog | undefined> {
  try {
    return parseCatalog(new Uint8Array(await Bun.file(path).arrayBuffer()));
  } catch (error) {
    fail(path, `Unable to read compiled catalog: ${error instanceof Error ? error.message : String(error)}`);
    return undefined;
  }
}

const template = await readCatalog(templatePath);
if (template) {
  const expectedEntries = [...template.entries()].filter(([key]) => key !== "");
  const expectedKeys = expectedEntries.map(([key]) => key).sort();

  for (const argument of catalogArguments) {
    const separator = argument.indexOf("=");
    if (separator <= 0 || separator === argument.length - 1) {
      fail(argument, "Expected LANGUAGE=CATALOG_MO");
      continue;
    }

    const language = argument.slice(0, separator);
    const path = argument.slice(separator + 1);
    const catalog = await readCatalog(path);
    if (!catalog) continue;

    const actualKeys = [...catalog.keys()].filter((key) => key !== "").sort();
    if (actualKeys.length !== expectedKeys.length
      || actualKeys.some((key, index) => key !== expectedKeys[index])) {
      const missing = expectedKeys.filter((key) => !catalog.has(key));
      const unexpected = actualKeys.filter((key) => !template.has(key));
      fail(path, `Compiled source keys differ from the template (missing ${missing.length}, unexpected ${unexpected.length})`);
    }

    for (const [key, sourceForms] of expectedEntries) {
      const forms = catalog.get(key);
      const expectedFormCount = key.includes("\0") ? pluralFormCount(catalog) : 1;
      if (!forms || forms.length !== expectedFormCount || forms.some((form) => form.length === 0)) {
        fail(path, `Translation for '${displayKey(key)}' has ${forms?.length ?? 0} form(s); expected ${expectedFormCount} nonempty form(s)`);
        continue;
      }

      for (const [index, translatedForm] of forms.entries()) {
        const sourceForm = sourceForms[index] ?? sourceForms[0];
        const sourcePlaceholders = namedBracePlaceholders(sourceForm);
        const translatedPlaceholders = namedBracePlaceholders(translatedForm);
        if (sourcePlaceholders.length !== translatedPlaceholders.length
          || sourcePlaceholders.some((placeholder, placeholderIndex) => placeholder !== translatedPlaceholders[placeholderIndex])) {
          fail(path, `Translation for '${displayKey(key)}' form ${index} changes named brace placeholders`);
        }
        if (language === "en" && translatedForm !== sourceForm) {
          fail(path, `English translation for '${displayKey(key)}' form ${index} is not source-identical`);
        }
      }
    }
  }
}

if (!template || failures > 0) process.exitCode = 1;
