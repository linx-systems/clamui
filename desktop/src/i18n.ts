import { request } from "./api";

export type Catalog = {
  language: string;
  languages: Array<{ code: string; name: string }>;
  messages: Record<string, string[]>;
  plural_rule?: string;
};

type FormatValues = Record<string, string | number>;

let catalog: Catalog | null = null;

function format(message: string, values?: FormatValues, count?: number): string {
  if (!values && count === undefined) {
    return message;
  }
  return message.replace(/\{([A-Za-z0-9_]+)\}/g, (placeholder, key: string) => {
    const value = key === "count" && count !== undefined ? count : values?.[key];
    return value === undefined ? placeholder : String(value);
  });
}

function pluralIndex(activeCatalog: Catalog, count: number): number {
  const safeIndex = count === 1 ? 0 : 1;
  const rule = activeCatalog.plural_rule ?? "";
  if (rule.includes("nplurals=1") || rule.includes("plural=0")) {
    return 0;
  }
  if (rule.includes("n > 1")) {
    return count > 1 ? 1 : 0;
  }
  return safeIndex;
}

function translations(): Record<string, string[]> {
  return catalog?.messages ?? {};
}

/** Load the native-generated gettext catalog before React mounts. */
export async function loadCatalog(): Promise<Catalog> {
  const result = await request<unknown>("i18n.catalog");
  if (!result || typeof result !== "object" || !("language" in result) || !("messages" in result)) {
    throw new Error("The translation catalog returned an invalid response");
  }

  const language = result.language;
  const messages = result.messages;
  if (typeof language !== "string" || !messages || typeof messages !== "object") {
    throw new Error("The translation catalog is incomplete");
  }

  const rawLanguages = "languages" in result ? result.languages : [];
  const languages = Array.isArray(rawLanguages)
    ? rawLanguages.filter(
        (entry): entry is { code: string; name: string } =>
          typeof entry === "object" &&
          entry !== null &&
          "code" in entry &&
          "name" in entry &&
          typeof entry.code === "string" &&
          typeof entry.name === "string",
      )
    : [];
  const normalizedMessages: Record<string, string[]> = {};
  for (const [key, forms] of Object.entries(messages)) {
    if (Array.isArray(forms) && forms.every((form) => typeof form === "string")) {
      normalizedMessages[key] = forms;
    }
  }

  catalog = {
    language,
    languages,
    messages: normalizedMessages,
    plural_rule: "plural_rule" in result && typeof result.plural_rule === "string" ? result.plural_rule : undefined,
  };
  document.documentElement.lang = language.replace("_", "-");
  return catalog;
}

export function activeCatalog(): Catalog | null {
  return catalog;
}

export function _(message: string, values?: FormatValues): string {
  const translated = translations()[message]?.[0] ?? message;
  return format(translated, values);
}

export function scanStatusLabel(status: string): string {
  if (status === "clean") return _("Clean");
  if (status === "infected") return _("Infected");
  if (status === "error") return _("Error");
  if (status === "cancelled") return _("Cancelled");
  return status || _("Unknown");
}

export function ngettext(
  single: string,
  plural: string,
  count: number,
  values?: FormatValues,
): string {
  const activeCatalog = catalog;
  const fallback = count === 1 ? single : plural;
  if (!activeCatalog) {
    return format(fallback, values, count);
  }

  const forms = activeCatalog.messages[`${single}\u0000${plural}`];
  const index = pluralIndex(activeCatalog, count);
  const translated = forms?.[index] ?? fallback;
  return format(translated, values, count);
}
