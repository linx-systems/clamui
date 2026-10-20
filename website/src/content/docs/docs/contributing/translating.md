---
title: Translate ClamUI
description: Maintain ClamUI's gettext catalogs for the Rust core and Tauri frontend.
---

ClamUI keeps GNU gettext catalogs in `po/`. `po/clamui.pot` is the source template, `po/LINGUAS` is the authoritative list of active catalogs, and each supported translation is `po/<LANG>.po`. The application ships **German (`de`)**, **English (`en`)**, **Spanish (`es`)**, **French (`fr`)**, **Hungarian (`hu`)**, **Italian (`it`)**, **Norwegian Bokmål (`nb`)**, **Brazilian Portuguese (`pt_BR`)**, and **Simplified Chinese (`zh_CN`)**. Rust build tooling and packaging export every catalog listed in `LINGUAS` for the headless core and React UI; generated runtime files are not committed.

Localized historical scan-summary recognition is retained as bounded embedded Rust data, not as inactive full catalogs. It does not make a locale selectable, packaged, or synchronized to the current template. Catalog extraction, loading, and packaging have no Python runtime dependency.

## Add a supported language
Install gettext, then initialize a catalog:

```bash
# Debian/Ubuntu
sudo apt install gettext

# Fedora
sudo dnf install gettext

# Arch Linux
sudo pacman -S gettext

msginit --input=po/clamui.pot --output-file=po/<LANG>.po --locale=<LANG>
```

Add `<LANG>` to `po/LINGUAS` only after explicitly deciding to ship and select the language, updating the runtime catalog policy, and translating every current entry including plural forms. Adding it to `LINGUAS` makes it a packaged application locale. Submit the complete `po/<LANG>.po` and `po/LINGUAS`; do **not** commit generated `.mo` files or build output.

## Update a supported translation
After user-visible source strings change, install GNU gettext and the locked desktop extraction dependencies before regenerating the migration-aware template:

```bash
# Debian/Ubuntu
sudo apt install gettext

# Fedora
sudo dnf install gettext

# Arch Linux
sudo pacman -S gettext

bun --cwd desktop install --frozen-lockfile
./scripts/update-pot.sh
./scripts/update-pot.sh --check
```

Then merge and complete **every active catalog**, then run the canonical freshness and catalog checks:

```bash
for language in de en es fr hu it nb pt_BR zh_CN; do
  msgmerge --update "po/${language}.po" po/clamui.pot
done
./scripts/update-pot.sh --check
./scripts/check-translations.sh
```

The check requires GNU gettext and Bun to compare compiled active catalogs against a source-identity template. It rejects fuzzy entries, missing or extra source keys (including context and plural identities), empty translation forms, and changed named brace placeholders. Review plural forms and message IDs changed in the core or frontend. Historical summary templates are not catalogs to synchronize. Start the Tauri desktop with the development workflow in [Development](/docs/contributing/development/) when checking a translation.

## Translation rules

Translate visible labels, dialogs, errors, tooltips, descriptions, notifications, tray labels, and CLI text. Preserve placeholders such as `{count}`, `{name}`, `%s`, whitespace, newlines, and every plural `msgstr[N]`. Do not translate logger/developer errors, CSS names, D-Bus paths, settings keys, commands, or **ClamUI**.

Render-time Rust and frontend gettext calls must use static literal message IDs, including static template literals in TypeScript, so extraction can find them. Interpolate runtime values only after lookup by passing values to `_` or the existing `ngettext` helper; never construct a message ID from dynamic values. Use the plural API for new singular/plural pairs rather than choosing a translated branch yourself.

## Plural-form headers

Each catalog's `Plural-Forms` header is runtime data and must match its language. `de`, `en`, `es`, `hu`, `it`, and `nb` use two forms with `n != 1`. `fr` and `pt_BR` use two forms with `n > 1`, so both `0` and `1` select the singular form. `zh_CN` has one form and always selects form `0`. Preserve the header and every required `msgstr[N]` when translating.

## About and translator credits

The root [`AUTHORS`](https://github.com/linx-systems/clamui/blob/master/AUTHORS) file is canonical: one contributor per line, in the order shown there. The Rust build embeds that file, so every package can show the About contributor list offline and in that exact order.

For the About view's translator credits, translate `translator-credits` only to genuine contributor names. Leave it empty when no names can be credited; do not leave the literal `translator-credits` as the translation. The literal is suppressed rather than displayed as a person's credit.

## Known pitfalls

Read each entry's `#.` translator note: it identifies the special handling required for that message.

- **Dashes and ellipses:** source uses an em dash (`—`) to separate clauses and an ellipsis (`…`) where one is intended. Use the punctuation and spacing customary in the target language rather than replacing prose punctuation with ASCII ` - ` or `--`.
- **Ranges:** an en dash (`–`) denotes a range, such as `1–28`. Translate the range with the target language's normal typography, spacing, dash, or wording.
- **Quotation marks:** source may use ASCII `'…'` or `"…"`. Use the target language's quotation marks. A quoted UI label must use exactly the translation of that label elsewhere in the interface; a quoted command, key, package name, or file name stays unchanged. The external file-manager entry **Scan with ClamUI** remains English.
- **Markup:** keep every markup tag and entity, including `<b>`, `<big>`, `<small>`, and `&amp;`, intact. Broken markup can hide text.
- **Historical pseudo-plurals:** older entries such as `file(s)` are translated naturally. New source messages must use real plural forms through the existing plural API.

When adding a source message that needs this context, put a `// Translators:` comment immediately above the string literal argument, not above a standalone call or macro opener. State the expected translation treatment precisely. The Rust and TypeScript extraction path projects static literals to gettext; recognized `Translators:` comments are emitted beside the entry as `#.` catalog notes.

The **Preferences → Behavior → Language** override stores `language` as `auto` or an active catalog code. The core applies the active catalog to headless CLI and tray strings; the frontend receives the catalog and plural-rule data from the same i18n domain. Regional system-locale aliases normalize to the supported catalog, including Brazilian Portuguese (`pt_BR`) and Simplified Chinese (`zh_CN`). Restart ClamUI after changing the language to ensure every native and frontend string reloads.