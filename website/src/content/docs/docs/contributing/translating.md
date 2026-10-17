---
title: Translate ClamUI
description: Add or update a gettext translation.
---

ClamUI uses GNU gettext. `po/clamui.pot` is the generated template, `po/LINGUAS` is the authoritative language list, and each translation is `po/<LANG>.po`.

## Add a language

```bash
# Debian/Ubuntu
sudo apt install gettext

# Fedora
sudo dnf install gettext

# Arch Linux
sudo pacman -S gettext

msginit --input=po/clamui.pot --output-file=po/<LANG>.po --locale=<LANG>
```

Add `<LANG>` as one line in `po/LINGUAS`, translate every `msgstr`, then test locally:

```bash
msgfmt po/<LANG>.po -o po/<LANG>.mo
mkdir -p locale/<LANG>/LC_MESSAGES
cp po/<LANG>.mo locale/<LANG>/LC_MESSAGES/clamui.mo
LANGUAGE=<LANG> uv run clamui
```

Submit `po/<LANG>.po` and `po/LINGUAS`; do **not** commit generated `.mo` files.

## Update a translation

After source strings change, regenerate the template and merge your language:

```bash
./scripts/update-pot.sh
msgmerge --update po/<LANG>.po po/clamui.pot
./scripts/check-potfiles.sh
./scripts/check-translations.sh
```

Review `#, fuzzy` entries, empty `msgstr` values, and obsolete `#~` entries.

## Translation rules

Translate visible labels, dialogs, errors, tooltips, and descriptions. Preserve placeholders such as `{count}`, `{name}`, and `%(prog)s`, whitespace, newlines, and every plural `msgstr[N]`. Do not translate logger/developer errors, CSS names, D-Bus paths, settings keys, commands, or the name **ClamUI**.

## Known pitfalls

Read the `#.` comments above an entry; they explain these cases where they occur.

- **Dashes:** an em dash (`—`) separates two parts of a message. Use the dash and spacing your language normally uses, such as a spaced en dash in many European languages.
- **Ranges:** an en dash (`–`) marks a range, as in `{start_date} – {end_date}` or `1–28`. Write ranges the way your language does: spacing, dash, or a word like "bis" or "til".
- **Quotation marks:** source strings use ASCII `'…'` and `"…"`. Use your language's quotation marks, such as `“…”`, `„…“` or `«…»`. Some quoted text is not prose:
  - **Commands, package names, file names and config keys:** keep the text inside the quotes unchanged.
  - **Labels of other buttons or menu items:** use the same translation as that label. The file manager entry `'Scan with ClamUI'` is not translated, so keep it in English.
- **Markup:** keep tags such as `<b>`, `<big>` and `<small>`, and entities such as `&amp;`, exactly as they are. Broken markup makes the text disappear.
- **Pseudo-plurals:** some older strings still use forms like `file(s)`. Translate them naturally. New strings use `ngettext` and real plural forms.

When adding source strings, put the `# Translators:` comment on the line directly above the string literal; above a `_(` on its own line, `xgettext` drops it.

The in-app **Preferences → Behavior → Language** override writes `language` as `auto` or an ISO code and requires restart. The tray subprocess has its own gettext bootstrap to remain GTK-independent.

When adding source strings, follow the i18n conventions in [AGENTS.md](https://github.com/linx-systems/clamui/blob/master/AGENTS.md): `_()`, `N_()`, `ngettext()`, deferred constants, and no f-strings inside `_()`.