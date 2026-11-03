---
name: clamui-gettext
description: Maintain ClamUI gettext messages, catalogs, plural forms, translator notes, or extraction across Rust/Tauri and TypeScript.
---

## Scope

Use this skill when changing user-visible gettext source messages, `po/` catalogs, plural behavior, translator comments, or an extraction failure. Production extraction covers Rust in `crates/` and `desktop/src-tauri/`, plus TypeScript/TSX in `desktop/src/`; it has no Python runtime or build dependency. Extend this existing gettext path rather than adding a translation framework.

Read the repository-root `website/src/content/docs/docs/contributing/translating.md` for catalog-editing guidance. Treat `po/LINGUAS` as the active-locale authority: `de`, `en`, `es`, `fr`, `hu`, `it`, `nb`, `pt_BR`, and `zh_CN`.

## Source-message rules

1. Give every gettext helper a direct static string literal (a static no-substitution TypeScript template literal is also supported). Keep the existing message ID, context, placeholders, and singular/plural pair unless the requested wording changes them.
2. Put each conditional branch around its own translated literal—for example, `condition ? _("literal A") : _("literal B")`—rather than selecting a message ID first. Never pass a variable or `if`/`match` expression as a gettext message ID. Interpolate runtime values only after lookup or plural selection with the existing formatting helper or values argument.
3. Use the existing plural API for a new count-dependent message: Rust `i18n::translate_plural`/the local `trn` or `trnf` wrapper, or frontend `ngettext`. Keep every plural form meaningful; do not introduce a pseudo-plural or select a translated branch manually.
4. Place a `// Translators:` comment immediately above the relevant literal argument when a dash, range, quotes, markup, or protected package, command, file, or UI literal needs handling guidance. Say exactly whether a protected literal remains unchanged or a quoted UI label must match its translation elsewhere. Keep source Unicode `—`, `–`, and `…` unchanged unless the translator note specifies target-language treatment.
5. Preserve unknown catalog data and unrelated entries. Do not casually churn existing msgids, plural semantics, headers, or generated output.

The extractor recognizes the Rust helpers in `scripts/update-pot.sh` and the frontend `_`/`ngettext` calls in `scripts/extract-typescript-gettext.ts`; model a new call on the nearest existing callsite. `desktop/src/i18n.ts` defines the frontend formatting and plural contract.

## Workflow

1. Change the source literal(s) and any precise translator note first. If this is a catalog-only translation, preserve placeholders, markup, whitespace, and all required `msgstr[N]` entries.
2. For source-message changes, use GNU gettext and the frozen desktop dependencies: `(cd desktop && bun install --frozen-lockfile)`, then run `./scripts/update-pot.sh`. Merge the resulting template into every active catalog, translate the affected entries, and keep `po/LINGUAS` aligned with its nine catalogs.
3. Run only the repository contracts appropriate to the change: `./scripts/update-pot.sh --check` checks template freshness; `./scripts/check-potfiles.sh` checks Rust/Tauri and TypeScript discovery; `./scripts/check-translations.sh` validates the active catalogs and compiled source identities. Do not invoke the internal catalog checker directly; its flags are owned by `check-translations.sh`.

### CLI help branch

Apply this only when changing `crates/clamui-core/src/cli.rs` root help or command summaries. Preserve the seven command-name contracts—`scan`, `quarantine`, `profile`, `status`, `history`, `install-privileged-helper`, and `help`—and leave command names, flags, command syntax, package names, and paths literal where the existing translator notes require it. The human-readable summaries remain translatable.

## Completion

- Every changed source call has extractable literal IDs, correct post-lookup interpolation, and real plural handling where required.
- Translator notes sit directly above only the literal they explain; protected literals and Unicode punctuation follow the specified treatment.
- If the template or a catalog changed, `po/clamui.pot`, all nine active catalogs, and `po/LINGUAS` retain consistent msgids, contexts, plural forms, and placeholders; no generated `.mo` or build output is added.
- The applicable repository scripts above succeed after the change.

## Source pointers

- `website/src/content/docs/docs/contributing/translating.md` — public translator workflow and language-specific rules.
- `scripts/update-pot.sh` and `scripts/extract-typescript-gettext.ts` — supported extraction shapes and `--check` behavior.
- `scripts/check-translations.sh`, `scripts/check-potfiles.sh`, and `.github/workflows/i18n.yml` — validation and CI contracts.
- `crates/clamui-core/src/i18n.rs`, `desktop/src/i18n.ts`, and `crates/clamui-core/src/cli.rs` — runtime, plural, and CLI-help implementations.
