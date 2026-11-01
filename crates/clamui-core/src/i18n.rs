//! Gettext catalog access for the headless core and the TypeScript frontend.
//!
//! Catalogs are generated from the repository's existing PO files by `build.rs`.
//! This keeps the Rust application independent of Python and gettext at runtime.

use chrono::{DateTime, FixedOffset};
use std::collections::BTreeMap;

use serde_json::{json, Value};

use crate::common::Context;
use crate::AppResult;

#[derive(Clone, Copy)]
struct CatalogEntry {
    key: &'static str,
    forms: &'static [&'static str],
}

#[derive(Clone, Copy)]
struct CatalogDefinition {
    code: &'static str,
    name: &'static str,
    plural_rule: &'static str,
    entries: &'static [CatalogEntry],
}

include!(concat!(env!("OUT_DIR"), "/i18n_catalogs.rs"));

/// Dispatch i18n operations. Only `catalog` is publicly routable.
pub fn dispatch(ctx: &Context, action: &str, _args: Value) -> AppResult<Value> {
    match action {
        "catalog" => Ok(catalog(ctx)),
        _ => Err(format!("Unknown i18n action: {action}")),
    }
}

/// Translate one non-plural message for native CLI and tray surfaces.
///
/// Callers retain ownership of interpolation: catalog strings deliberately keep
/// Python-style `{name}` placeholders so existing message IDs and variables are
/// preserved across the migration.
pub fn translate(ctx: &Context, message: &str) -> String {
    translate_key(ctx, message, message)
}

/// Translate a plural message for native CLI and tray surfaces.
///
/// The generated catalogs retain GNU gettext's singular and plural message
/// IDs as one NUL-separated key. Selection deliberately recognizes only the
/// plural rules used by ClamUI's shipped catalogs; it never evaluates catalog
/// expressions at runtime. If the selected localized form is unavailable,
/// the caller's English singular or plural message is returned instead.
pub fn translate_plural(ctx: &Context, singular: &str, plural: &str, count: u64) -> String {
    translate_plural_from_catalog(active_catalog(ctx), singular, plural, count).to_owned()
}

/// Format a precise, offset-aware timestamp using the active ClamUI locale.
///
/// Core messages retain the original offset instead of converting it to local
/// time, so diagnostic timestamps describe the instant reported by their
/// source while avoiding raw English date strings in localized UI and CLI text.
pub(crate) fn format_local_date_time(ctx: &Context, timestamp: DateTime<FixedOffset>) -> String {
    timestamp
        .format(date_time_format(active_catalog(ctx).code))
        .to_string()
}

fn date_time_format(code: &str) -> &'static str {
    match code {
        "de" | "nb" => "%d.%m.%Y, %H:%M %:z",
        "en" => "%Y-%m-%d, %H:%M %:z",
        "es" | "fr" | "it" | "pt_BR" => "%d/%m/%Y, %H:%M %:z",
        "hu" => "%Y.%m.%d. %H:%M %:z",
        "zh_CN" => "%Y/%m/%d %H:%M %:z",
        _ => "%Y-%m-%d, %H:%M %:z",
    }
}

/// Visit active translations of a plural message.
pub(crate) fn visit_plural_translations(
    singular: &str,
    plural: &str,
    mut visitor: impl FnMut(&str),
) {
    visitor(singular);
    visitor(plural);
    for definition in CATALOGS {
        visit_plural_forms(definition.entries, singular, plural, &mut visitor);
    }
}

/// Visit translations needed to recognize historical localized scan summaries.
pub(crate) fn visit_historical_plural_translations(
    singular: &str,
    plural: &str,
    mut visitor: impl FnMut(&str),
) {
    visit_plural_translations(singular, plural, &mut visitor);
    visit_plural_forms(HISTORICAL_SUMMARY_TEMPLATES, singular, plural, &mut visitor);
}

/// Visit active translations of a non-plural message.
pub(crate) fn visit_translations(message: &str, mut visitor: impl FnMut(&str)) {
    visitor(message);
    for definition in CATALOGS {
        visit_message_forms(definition.entries, message, &mut visitor);
    }
}

/// Visit translations needed to recognize historical localized scan summaries.
pub(crate) fn visit_historical_translations(message: &str, mut visitor: impl FnMut(&str)) {
    visit_translations(message, &mut visitor);
    visit_message_forms(HISTORICAL_SUMMARY_TEMPLATES, message, &mut visitor);
}

fn visit_plural_forms(
    entries: &[CatalogEntry],
    singular: &str,
    plural: &str,
    visitor: &mut impl FnMut(&str),
) {
    let Some(entry) = entries.iter().find(|entry| {
        entry
            .key
            .split_once('\0')
            .is_some_and(|(entry_singular, entry_plural)| {
                entry_singular == singular && entry_plural == plural
            })
    }) else {
        return;
    };
    for form in entry.forms {
        if !form.is_empty() {
            visitor(form);
        }
    }
}

fn visit_message_forms(entries: &[CatalogEntry], message: &str, visitor: &mut impl FnMut(&str)) {
    if let Some(entry) = entries.iter().find(|entry| entry.key == message) {
        for form in entry.forms {
            if !form.is_empty() {
                visitor(form);
            }
        }
    }
}

fn localized_plural_form(
    definition: &CatalogDefinition,
    singular: &str,
    plural: &str,
    count: u64,
) -> Option<&'static str> {
    let index = plural_form_index(definition, count);
    definition
        .entries
        .iter()
        .find(|entry| {
            entry
                .key
                .split_once('\0')
                .is_some_and(|(entry_singular, entry_plural)| {
                    entry_singular == singular && entry_plural == plural
                })
        })
        .and_then(|entry| entry.forms.get(index))
        .copied()
        .filter(|form| !form.is_empty())
}

fn translate_plural_from_catalog<'a>(
    definition: &CatalogDefinition,
    singular: &'a str,
    plural: &'a str,
    count: u64,
) -> &'a str {
    if let Some(form) = localized_plural_form(definition, singular, plural, count) {
        form
    } else {
        plural_fallback(singular, plural, count)
    }
}

fn plural_form_index(definition: &CatalogDefinition, count: u64) -> usize {
    if definition.plural_rule.contains("nplurals=1") || definition.plural_rule.contains("plural=0")
    {
        return 0;
    }
    if definition.plural_rule.contains("n > 1") {
        return usize::from(count > 1);
    }

    usize::from(count != 1)
}

fn plural_fallback<'a>(singular: &'a str, plural: &'a str, count: u64) -> &'a str {
    if count == 1 {
        singular
    } else {
        plural
    }
}

/// Translate a gettext context-qualified message without conflating identical
/// message IDs from distinct contexts.
pub fn translate_context(ctx: &Context, context: &str, message: &str) -> String {
    let key = format!("{context}\u{4}{message}");
    translate_key(ctx, &key, message)
}

fn translate_key(ctx: &Context, key: &str, fallback: &str) -> String {
    active_catalog(ctx)
        .entries
        .iter()
        .find(|entry| entry.key == key)
        .and_then(|entry| entry.forms.first())
        .copied()
        .unwrap_or(fallback)
        .to_owned()
}

fn catalog(ctx: &Context) -> Value {
    let definition = active_catalog(ctx);
    let messages = definition
        .entries
        .iter()
        .map(|entry| {
            (
                entry.key.to_owned(),
                Value::Array(
                    entry
                        .forms
                        .iter()
                        .map(|form| Value::String((*form).to_owned()))
                        .collect(),
                ),
            )
        })
        .collect::<BTreeMap<_, _>>();

    json!({
        "language": definition.code,
        "languages": CATALOGS.iter().map(|catalog| json!({
            "code": catalog.code,
            "name": catalog.name,
        })).collect::<Vec<_>>(),
        "messages": messages,
        "plural_rule": definition.plural_rule,
    })
}

fn active_catalog(ctx: &Context) -> &'static CatalogDefinition {
    let configured = ctx.settings().ok().and_then(|settings| {
        settings
            .get("language")
            .and_then(Value::as_str)
            .map(str::to_owned)
    });

    let requested = configured
        .filter(|language| !language.is_empty() && language != "auto")
        .or_else(system_language);

    catalog_for_locale(requested.as_deref())
}

fn system_language() -> Option<String> {
    ["LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"]
        .iter()
        .filter_map(|name| std::env::var(name).ok())
        .find(|value| !value.is_empty())
}

fn catalog_for_locale(locale: Option<&str>) -> &'static CatalogDefinition {
    locale
        .and_then(resolve_catalog_code)
        .and_then(|code| CATALOGS.iter().find(|catalog| catalog.code == code))
        .or_else(|| CATALOGS.iter().find(|catalog| catalog.code == "en"))
        .or_else(|| CATALOGS.first())
        .expect("generated catalogs always include English")
}

fn resolve_catalog_code(locale: &str) -> Option<&'static str> {
    for candidate in locale.split(':') {
        let normalized = candidate
            .split(['.', '@'])
            .next()
            .unwrap_or_default()
            .replace('-', "_");
        if normalized.is_empty()
            || normalized.eq_ignore_ascii_case("C")
            || normalized.eq_ignore_ascii_case("POSIX")
        {
            continue;
        }
        if let Some(catalog) = CATALOGS
            .iter()
            .find(|catalog| catalog.code.eq_ignore_ascii_case(&normalized))
        {
            return Some(catalog.code);
        }

        let language = normalized
            .split_once('_')
            .map_or(normalized.as_str(), |(language, _)| language);
        let alias = if language.eq_ignore_ascii_case("pt") {
            Some("pt_BR")
        } else if language.eq_ignore_ascii_case("zh") || normalized.eq_ignore_ascii_case("zh_Hans")
        {
            Some("zh_CN")
        } else {
            None
        };
        if let Some(alias) = alias {
            if let Some(catalog) = CATALOGS.iter().find(|catalog| catalog.code == alias) {
                return Some(catalog.code);
            }
        }
        if let Some(catalog) = CATALOGS
            .iter()
            .find(|catalog| catalog.code.eq_ignore_ascii_case(language))
        {
            return Some(catalog.code);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::{
        catalog, catalog_for_locale, date_time_format, localized_plural_form, plural_form_index,
        resolve_catalog_code, translate_plural_from_catalog, CatalogDefinition, CatalogEntry,
    };
    use crate::{common::Paths, Context};
    use chrono::DateTime;
    use serde_json::json;
    use tempfile::TempDir;

    const SYNTHETIC_ENTRIES: &[CatalogEntry] = &[
        CatalogEntry {
            key: "synthetic singular\0synthetic plural",
            forms: &["localized singular", "localized plural"],
        },
        CatalogEntry {
            key: "missing singular\0missing plural",
            forms: &["localized singular", ""],
        },
        CatalogEntry {
            key: "unusable singular\0unusable plural",
            forms: &[],
        },
    ];
    const SYNTHETIC_CATALOG: CatalogDefinition = CatalogDefinition {
        code: "en",
        name: "Synthetic",
        plural_rule: "nplurals=2; plural=(n != 1);",
        entries: SYNTHETIC_ENTRIES,
    };

    #[test]
    fn persisted_shipped_language_selects_its_catalog() {
        let temp = TempDir::new().expect("temporary catalog root");
        let root = temp.path();
        let context = Context::with_paths(Paths {
            home: root.join("home"),
            config_dir: root.join("config/clamui"),
            data_dir: root.join("data/clamui"),
        })
        .expect("catalog context");

        context
            .update_settings(json!({"language": "fr"}))
            .expect("persist selected language");
        let response = catalog(&context);

        assert_eq!(response["language"], "fr");
    }

    #[test]
    fn regional_locales_normalize_to_shipped_catalogs_and_unknowns_use_english() {
        assert_eq!(resolve_catalog_code("de_AT.UTF-8"), Some("de"));
        assert_eq!(resolve_catalog_code("fr_CA:de_DE"), Some("fr"));
        assert_eq!(resolve_catalog_code("pt-BR.UTF-8"), Some("pt_BR"));
        assert_eq!(resolve_catalog_code("zh-Hans"), Some("zh_CN"));
        assert_eq!(catalog_for_locale(Some("fr_CA")).code, "fr");
        assert_eq!(catalog_for_locale(Some("unavailable")).code, "en");
    }

    #[test]
    fn shipped_locales_use_numeric_date_formats_without_english_month_names() {
        let timestamp = DateTime::parse_from_rfc3339("2026-10-20T13:04:00+02:00")
            .expect("fixed test timestamp");
        for (locale, expected) in [
            ("de", "20.10.2026, 13:04 +02:00"),
            ("en", "2026-10-20, 13:04 +02:00"),
            ("es", "20/10/2026, 13:04 +02:00"),
            ("fr", "20/10/2026, 13:04 +02:00"),
            ("hu", "2026.10.20. 13:04 +02:00"),
            ("it", "20/10/2026, 13:04 +02:00"),
            ("nb", "20.10.2026, 13:04 +02:00"),
            ("pt_BR", "20/10/2026, 13:04 +02:00"),
            ("zh_CN", "2026/10/20 13:04 +02:00"),
        ] {
            assert_eq!(
                timestamp.format(date_time_format(locale)).to_string(),
                expected
            );
        }
    }

    #[test]
    fn active_plural_rules_select_the_expected_form_for_zero_one_and_many() {
        for (locale, expected) in [
            ("de", [1, 0, 1]),
            ("en", [1, 0, 1]),
            ("es", [1, 0, 1]),
            ("fr", [0, 0, 1]),
            ("hu", [1, 0, 1]),
            ("it", [1, 0, 1]),
            ("nb", [1, 0, 1]),
            ("pt_BR", [0, 0, 1]),
            ("zh_CN", [0, 0, 0]),
        ] {
            let catalog = catalog_for_locale(Some(locale));
            assert_eq!(
                [
                    plural_form_index(catalog, 0),
                    plural_form_index(catalog, 1),
                    plural_form_index(catalog, 2),
                ],
                expected,
                "{locale} must use its catalog's GNU plural rule",
            );
        }
    }

    #[test]
    fn zero_uses_the_plural_form_instead_of_the_singular_catalog_form() {
        assert_eq!(
            localized_plural_form(
                &SYNTHETIC_CATALOG,
                "synthetic singular",
                "synthetic plural",
                0,
            ),
            Some("localized plural"),
        );
        assert_eq!(
            localized_plural_form(
                &SYNTHETIC_CATALOG,
                "synthetic singular",
                "synthetic plural",
                1,
            ),
            Some("localized singular"),
        );
        assert_eq!(
            localized_plural_form(
                &SYNTHETIC_CATALOG,
                "synthetic singular",
                "synthetic plural",
                2,
            ),
            Some("localized plural"),
        );
    }

    #[test]
    fn missing_or_unusable_localized_forms_use_matching_english_grammar() {
        assert_eq!(
            localized_plural_form(&SYNTHETIC_CATALOG, "missing singular", "missing plural", 0),
            None,
        );

        for (count, expected) in [
            (0, "English plural"),
            (1, "English singular"),
            (2, "English plural"),
        ] {
            assert_eq!(
                translate_plural_from_catalog(
                    &SYNTHETIC_CATALOG,
                    "English singular",
                    "English plural",
                    count,
                ),
                expected,
            );
        }
    }
}
