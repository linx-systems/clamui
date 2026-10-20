use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

#[path = "src/historical_summary.rs"]
mod historical_summary;

#[derive(Default)]
struct Entry {
    context: String,
    id: String,
    plural: Option<String>,
    translations: BTreeMap<usize, String>,
    fuzzy: bool,
}

#[derive(Clone, Copy)]
enum Field {
    Context,
    Id,
    Plural,
    Translation(usize),
}

fn main() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("manifest directory"));
    let po_dir = manifest_dir.join("../../po");
    let linguas = po_dir.join("LINGUAS");
    println!("cargo:rerun-if-changed={}", linguas.display());
    println!("cargo:rerun-if-changed=src/historical_summary.rs");

    let codes = fs::read_to_string(&linguas)
        .expect("read po/LINGUAS")
        .lines()
        .map(|line| line.split('#').next().unwrap_or_default().trim())
        .filter(|code| !code.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();

    let mut generated = String::from("static HISTORICAL_SUMMARY_TEMPLATES: &[CatalogEntry] = &[\n");
    for (key, forms) in historical_summary::TEMPLATES {
        generated.push_str("    CatalogEntry { key: ");
        generated.push_str(&rust_string(key));
        generated.push_str(", forms: &[");
        for form in *forms {
            generated.push_str(&rust_string(form));
            generated.push(',');
        }
        generated.push_str("] },\n");
    }
    generated.push_str("];\n\nstatic CATALOGS: &[CatalogDefinition] = &[\n");
    for code in codes {
        let path = po_dir.join(format!("{code}.po"));
        println!("cargo:rerun-if-changed={}", path.display());
        let entries = parse_po(&path);
        let header = entries
            .iter()
            .find(|entry| entry.id.is_empty())
            .and_then(|entry| entry.translations.get(&0))
            .cloned()
            .unwrap_or_default();
        let plural_rule = header_value(&header, "Plural-Forms").unwrap_or_default();
        let plural_count = plural_count(&plural_rule);

        generated.push_str("    CatalogDefinition { code: ");
        generated.push_str(&rust_string(&code));
        generated.push_str(", name: ");
        generated.push_str(&rust_string(language_name(&code)));
        generated.push_str(", plural_rule: ");
        generated.push_str(&rust_string(&plural_rule));
        generated.push_str(", entries: &[\n");

        for entry in entries.into_iter().filter(|entry| !entry.id.is_empty()) {
            let key = match &entry.plural {
                Some(plural) => format!("{}\0{}", entry.id, plural),
                None => entry.id.clone(),
            };
            let forms = translation_forms(&entry, plural_count);
            generated.push_str("        CatalogEntry { key: ");
            generated.push_str(&rust_string(&context_key(&entry.context, &key)));
            generated.push_str(", forms: &[");
            for form in forms {
                generated.push_str(&rust_string(&form));
                generated.push(',');
            }
            generated.push_str("] },\n");
        }
        generated.push_str("    ] },\n");
    }
    generated.push_str("];\n");

    let output =
        PathBuf::from(env::var("OUT_DIR").expect("output directory")).join("i18n_catalogs.rs");
    fs::write(output, generated).expect("write generated i18n catalogs");
}

fn parse_po(path: &Path) -> Vec<Entry> {
    let input =
        fs::read_to_string(path).unwrap_or_else(|error| panic!("read {}: {error}", path.display()));
    parse_po_text(path, &input)
}

fn parse_po_text(path: &Path, input: &str) -> Vec<Entry> {
    let mut entries = Vec::new();
    let mut entry = Entry::default();
    let mut field = None;

    let flush = |entries: &mut Vec<Entry>, entry: &mut Entry, field: &mut Option<Field>| {
        if !entry.id.is_empty() || !entry.translations.is_empty() {
            entries.push(std::mem::take(entry));
        }
        *field = None;
    };

    for raw_line in input.lines() {
        let line = raw_line.trim();
        if line.is_empty() {
            flush(&mut entries, &mut entry, &mut field);
            continue;
        }
        if let Some(flags) = line.strip_prefix("#,") {
            if flags.split(',').any(|flag| flag.trim() == "fuzzy") {
                entry.fuzzy = true;
            }
            continue;
        }
        if line.starts_with('#') {
            continue;
        }

        if let Some(value) = directive_value(line, "msgctxt") {
            entry.context = value;
            field = Some(Field::Context);
        } else if let Some(value) = directive_value(line, "msgid_plural") {
            entry.plural = Some(value);
            field = Some(Field::Plural);
        } else if let Some(value) = directive_value(line, "msgid") {
            entry.id = value;
            field = Some(Field::Id);
        } else if let Some((index, value)) = plural_translation_value(line) {
            entry.translations.insert(index, value);
            field = Some(Field::Translation(index));
        } else if let Some(value) = directive_value(line, "msgstr") {
            entry.translations.insert(0, value);
            field = Some(Field::Translation(0));
        } else if line.starts_with('"') {
            let value = po_string(line);
            match field {
                Some(Field::Context) => entry.context.push_str(&value),
                Some(Field::Id) => entry.id.push_str(&value),
                Some(Field::Plural) => entry
                    .plural
                    .get_or_insert_with(String::new)
                    .push_str(&value),
                Some(Field::Translation(index)) => entry
                    .translations
                    .entry(index)
                    .or_default()
                    .push_str(&value),
                None => panic!(
                    "continuation without directive in {}: {line}",
                    path.display()
                ),
            }
        } else {
            panic!("unsupported PO line in {}: {line}", path.display());
        }
    }
    flush(&mut entries, &mut entry, &mut field);
    entries
}

fn directive_value(line: &str, directive: &str) -> Option<String> {
    let rest = line.strip_prefix(directive)?;
    if rest.chars().next().map(char::is_whitespace) != Some(true) {
        return None;
    }
    Some(po_string(rest.trim_start()))
}

fn plural_translation_value(line: &str) -> Option<(usize, String)> {
    let rest = line.strip_prefix("msgstr[")?;
    let (index, value) = rest.split_once("]")?;
    let index = index.parse().ok()?;
    Some((index, po_string(value.trim_start())))
}

fn po_string(input: &str) -> String {
    let quoted = input
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or_else(|| panic!("invalid PO string: {input}"));
    let mut output = String::new();
    let mut chars = quoted.chars();
    while let Some(character) = chars.next() {
        if character != '\\' {
            output.push(character);
            continue;
        }
        match chars.next().expect("unterminated PO escape") {
            'n' => output.push('\n'),
            'r' => output.push('\r'),
            't' => output.push('\t'),
            '"' => output.push('"'),
            '\\' => output.push('\\'),
            first @ '0'..='7' => {
                let mut octal = String::from(first);
                for _ in 0..2 {
                    match chars.clone().next() {
                        Some(next @ '0'..='7') => {
                            chars.next();
                            octal.push(next);
                        }
                        _ => break,
                    }
                }
                let byte = u8::from_str_radix(&octal, 8).expect("valid octal escape");
                output.push(char::from(byte));
            }
            escaped => output.push(escaped),
        }
    }
    output
}

fn header_value(header: &str, name: &str) -> Option<String> {
    header.lines().find_map(|line| {
        let value = line.strip_prefix(name)?.strip_prefix(':')?.trim();
        Some(value.to_owned())
    })
}

fn plural_count(rule: &str) -> usize {
    rule.split(';')
        .find_map(|part| part.trim().strip_prefix("nplurals=")?.trim().parse().ok())
        .filter(|count: &usize| *count > 0)
        .unwrap_or(2)
}

fn translation_forms(entry: &Entry, plural_count: usize) -> Vec<String> {
    match &entry.plural {
        Some(plural) => (0..plural_count)
            .map(|index| {
                let fallback = if index == 0 { &entry.id } else { plural };
                if entry.fuzzy {
                    fallback.clone()
                } else {
                    entry
                        .translations
                        .get(&index)
                        .filter(|translation| !translation.is_empty())
                        .cloned()
                        .unwrap_or_else(|| fallback.clone())
                }
            })
            .collect(),
        None => vec![if entry.fuzzy {
            entry.id.clone()
        } else {
            entry
                .translations
                .get(&0)
                .filter(|translation| !translation.is_empty())
                .cloned()
                .unwrap_or_else(|| entry.id.clone())
        }],
    }
}

fn context_key(context: &str, key: &str) -> String {
    if context.is_empty() {
        key.to_owned()
    } else {
        format!("{context}\u{4}{key}")
    }
}

fn rust_string(value: &str) -> String {
    format!("{value:?}")
}

fn language_name(code: &str) -> &'static str {
    match code {
        "de" => "Deutsch",
        "en" => "English",
        "es" => "Español",
        "fr" => "Français",
        "hu" => "Magyar",
        "it" => "Italiano",
        "nb" => "Norsk bokmål",
        "pt_BR" => "Português (Brasil)",
        "zh_CN" => "简体中文",
        _ => panic!("unsupported catalog language in po/LINGUAS: {code}"),
    }
}
