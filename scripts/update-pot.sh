#!/bin/bash
# Generate/update the POT (Portable Object Template) file for ClamUI translations.
#
# Usage:
#   ./scripts/update-pot.sh
#   ./scripts/update-pot.sh --check
#
# Prerequisites:
#   sudo apt install gettext
#   bun --cwd desktop install --frozen-lockfile
#
# Bun and the desktop's locked development dependencies provide the TypeScript
# compiler used only for frontend message extraction.
#
# The production catalog is extracted only from the Rust/Tauri runtime and
# TypeScript frontend after the Python/GTK runtime cutover.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

OUTPUT="po/clamui.pot"
MODE="${1:-}"

case "$MODE" in
    ""|--check) ;;
    *)
        echo "Usage: $0 [--check]" >&2
        exit 2
        ;;
esac


TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

VERSION=""
IN_WORKSPACE_PACKAGE=0
while IFS= read -r line; do
    case "$line" in
        "[workspace.package]") IN_WORKSPACE_PACKAGE=1 ;;
        "["*"]") IN_WORKSPACE_PACKAGE=0 ;;
        'version = "'*)
            if [ "$IN_WORKSPACE_PACKAGE" -eq 1 ]; then
                VERSION="${line#version = \"}"
                VERSION="${VERSION%\"}"
                break
            fi
            ;;
    esac
done < Cargo.toml

if [ -z "$VERSION" ]; then
    echo "Error: unable to read workspace.package version from Cargo.toml." >&2
    exit 1
fi


RUST_FILES="$TMPDIR/rust-files"
: > "$RUST_FILES"
for source_root in crates desktop/src-tauri; do
    if [ -d "$source_root" ]; then
        find "$source_root" -type f -name '*.rs' -print >> "$RUST_FILES"
    fi
done
sort -u -o "$RUST_FILES" "$RUST_FILES"

# Ubuntu 22.04's gettext has no Rust parser. Preserve source locations while
# projecting recognized Rust i18n calls into tiny C-compatible snippets for the
# universally available C parser. Rust call sites use qualified or imported
# `translate`, `translate_plural`, and `translate_context`, `tr!`, `trn!`, or
# local `tr`/`trf`/`trn`/`trnf` wrappers; no application code is executed.
RUST_COMPAT_FILES="$TMPDIR/rust-compat-files"
: > "$RUST_COMPAT_FILES"
CONTROL_FLOW_MESSAGE_ARGUMENT=',[[:space:]]*(if|match)([[:space:]]|\()'
RUST_QUALIFIED_OR_MACRO_CALL='(^|[^[:alnum:]_])(i18n::translate_plural|i18n::translate|i18n::translate_context|tr!|trn!|trf|trn|trnf)\('
rust_index=0

# Keep source comments out of the reconstructed call while preserving URL
# literals such as https://... . The Rust source convention is a standalone
# `// Translators:` line directly above a literal argument.
strip_rust_line_comment() {
    local input="$1"
    local output=""
    local in_string=0
    local escaped=0
    local character
    local next
    local index
    for ((index = 0; index < ${#input}; index++)); do
        character="${input:index:1}"
        next="${input:index+1:1}"
        if [ "$in_string" -eq 1 ]; then
            output+="$character"
            if [ "$escaped" -eq 1 ]; then
                escaped=0
            elif [ "$character" = '\' ]; then
                escaped=1
            elif [ "$character" = '"' ]; then
                in_string=0
            fi
        elif [ "$character" = '"' ]; then
            output+="$character"
            in_string=1
        elif [ "$character" = '/' ] && [ "$next" = '/' ]; then
            break
        else
            output+="$character"
        fi
    done
    printf '%s' "$output"
}

# The C projection keeps Rust escape sequences verbatim, but must find a
# closing quote after an escaped quote rather than treating the escape as the
# end of the literal.
RUST_STRING_LITERALS=()
collect_rust_string_literals() {
    local input="$1"
    local literal=""
    local in_string=0
    local escaped=0
    local character
    local index
    RUST_STRING_LITERALS=()
    for ((index = 0; index < ${#input}; index++)); do
        character="${input:index:1}"
        if [ "$in_string" -eq 1 ]; then
            if [ "$escaped" -eq 1 ]; then
                literal+="$character"
                escaped=0
            elif [ "$character" = '\' ]; then
                literal+="$character"
                escaped=1
            elif [ "$character" = '"' ]; then
                RUST_STRING_LITERALS+=("$literal")
                in_string=0
            else
                literal+="$character"
            fi
        elif [ "$character" = '"' ]; then
            literal=""
            in_string=1
        fi
    done
}

leading_whitespace() {
    local input="$1"
    printf '%s' "${input#"${input%%[![:space:]]*}"}"
}

while IFS= read -r source; do
    rust_index=$((rust_index + 1))
    compatible="$TMPDIR/rust-$rust_index.c"
    : > "$compatible"
    collecting=0
    start_line=0
    body=""
    depth=0
    line_number=0
    pending_translator_comments=""
    translator_comments=""
    pending_translator_comment_lines=0
    translator_comment_lines=0
    raw_line=""
    raw_trimmed=""
    trimmed_line=""
    line_without_comment=""
    was_collecting=0

    while IFS= read -r line || [ -n "$line" ]; do
        line_number=$((line_number + 1))
        raw_line="$line"
        raw_trimmed="$(leading_whitespace "$raw_line")"
        line_without_comment="$(strip_rust_line_comment "$raw_line")"
        line="$line_without_comment"
        was_collecting="$collecting"
        if [ "$collecting" -eq 0 ]; then
            pending_translator_comments=""
            translator_comments=""
            pending_translator_comment_lines=0
            translator_comment_lines=0
            # Rust uses context-taking `tr`, `trf`, `trn`, `trnf`, and `text`
            # wrappers around i18n::translate. `tr` and `text` may put their
            # context argument on the next line, so only their identifier
            # boundary is recognized; names merely ending in either helper are
            # excluded below.
            case "$line" in
                *i18n::translate_plural\(*|*i18n::translate\(*|*i18n::translate_context\(*|*tr!\(*|*trn!\(*|*trf\(*|*trn\(*|*trnf\(*)
                    # Do not mistake suffixes such as include_str! for tr!.
                    [[ "$line" =~ $RUST_QUALIFIED_OR_MACRO_CALL ]] || continue
                    collecting=1
                    start_line="$line_number"
                    body="$line"
                    ;;
                *translate_context\(*)
                    prefix="${line%%translate_context\(*}"
                    case "$prefix" in
                        *[[:alnum:]_]) continue ;;
                        *)
                            collecting=1
                            start_line="$line_number"
                            body="$line"
                            ;;
                    esac
                    ;;
                *translate_plural\(*)
                    prefix="${line%%translate_plural\(*}"
                    case "$prefix" in
                        *[[:alnum:]_]) continue ;;
                        *)
                            collecting=1
                            start_line="$line_number"
                            body="$line"
                            ;;
                    esac
                    ;;
                *translate\(*)
                    prefix="${line%%translate\(*}"
                    case "$prefix" in
                        *[[:alnum:]_]) continue ;;
                        *)
                            collecting=1
                            start_line="$line_number"
                            body="$line"
                            ;;
                    esac
                    ;;
                *tr\(*)
                    prefix="${line%%tr\(*}"
                    case "$prefix" in
                        *[[:alnum:]_]) continue ;;
                        *)
                            collecting=1
                            start_line="$line_number"
                            body="$line"
                            ;;
                    esac
                    ;;
                *text\(*)
                    prefix="${line%%text\(*}"
                    case "$prefix" in
                        *[[:alnum:]_]) continue ;;
                        *)
                            collecting=1
                            start_line="$line_number"
                            body="$line"
                            ;;
                    esac
                    ;;
                *) continue ;;
            esac
        fi

        if [ "$was_collecting" -eq 1 ]; then
            if [[ "$raw_trimmed" == "// Translators:"* ]]; then
                pending_translator_comments+="$raw_trimmed"$'\n'
                pending_translator_comment_lines=$((pending_translator_comment_lines + 1))
            elif [[ "$raw_trimmed" == "//"* ]] || [ -z "$raw_trimmed" ]; then
                pending_translator_comments=""
                pending_translator_comment_lines=0
            elif [ -n "$pending_translator_comments" ]; then
                trimmed_line="$(leading_whitespace "$line")"
                case "$trimmed_line" in
                    \"*|N_\(\"*)
                        translator_comments+="$pending_translator_comments"
                        translator_comment_lines=$((translator_comment_lines + pending_translator_comment_lines))
                        ;;
                esac
                pending_translator_comments=""
                pending_translator_comment_lines=0
            fi
        fi

        if [ "$was_collecting" -eq 1 ]; then
            body="$body $line"
        fi
        for ((character = 0; character < ${#line}; character++)); do
            case "${line:character:1}" in
                '(') depth=$((depth + 1)) ;;
                ')') depth=$((depth - 1)) ;;
            esac
        done
        if [ "$collecting" -eq 1 ] && [ "$depth" -le 0 ]; then
            case "$body" in
                *i18n::translate_context\(*) body="translate_context(${body#*i18n::translate_context(}" ;;
                *i18n::translate_plural\(*) body="ngettext(${body#*i18n::translate_plural(}" ;;
                *i18n::translate\(*) body="translate(${body#*i18n::translate(}" ;;
                *translate_context\(*) body="translate_context(${body#*translate_context(}" ;;
                *translate_plural\(*) body="ngettext(${body#*translate_plural(}" ;;
                *translate\(*) body="translate(${body#*translate(}" ;;
                *trn!\(*) body="ngettext(${body#*trn!(}" ;;
                *trnf\(*) body="trn(${body#*trnf(}" ;;
                *trn\(*) body="trn(${body#*trn(}" ;;
                *tr!\(*) body="translate(NULL, ${body#*tr!(}" ;;
                *trf\(*) body="trf(${body#*trf(}" ;;
                *tr\(*) body="tr(${body#*tr(}" ;;
                *text\(*) body="text(${body#*text(}" ;;
            esac
            # A gettext message argument must be a direct literal or an existing
            # N_ deferred literal. A conditional chooser belongs outside the
            # wrapper: its branch literals are not independently extractable.
            # Reject the control-flow expression before considering its strings.
            if [[ "$body" == *\"* ]]; then
                before_literal="${body%%\"*}"
                if [[ "$before_literal" =~ $CONTROL_FLOW_MESSAGE_ARGUMENT ]]; then
                    collecting=0
                    depth=0
                    body=""
                    continue
                fi
            fi

            # Project only the static literal arguments into C-shaped calls.
            # This avoids feeding xgettext Rust replacement arrays, chaining,
            # or parentheses embedded in a translated message.
            collect_rust_string_literals "$body"
            if [ "${#RUST_STRING_LITERALS[@]}" -gt 0 ]; then
                first="${RUST_STRING_LITERALS[0]}"
                projected=1
                case "$body" in
                    translate_context\(*)
                        if [ "${#RUST_STRING_LITERALS[@]}" -lt 2 ]; then
                            projected=0
                        else
                            second="${RUST_STRING_LITERALS[1]}"
                            body="translate_context(NULL, \"$first\", \"$second\")"
                        fi
                        ;;
                    ngettext\(*|trn\(*)
                        if [ "${#RUST_STRING_LITERALS[@]}" -lt 2 ]; then
                            projected=0
                        else
                            second="${RUST_STRING_LITERALS[1]}"
                            body="ngettext(\"$first\", \"$second\")"
                        fi
                        ;;
                    *) body="translate(NULL, \"$first\")" ;;
                esac
                if [ "$projected" -eq 1 ]; then
                    if [ -n "$translator_comments" ]; then
                        # Place notes immediately before the call. Account for
                        # their generated lines so its original source ref stays
                        # unchanged.
                        comment_start_line=$((start_line - translator_comment_lines))
                        printf '#line %s "%s"\n%s%s;\n' \
                            "$comment_start_line" "$source" "$translator_comments" \
                            "$body" >> "$compatible"
                    else
                        printf '#line %s "%s"\n%s;\n' "$start_line" "$source" "$body" >> "$compatible"
                    fi
                fi
            fi
            collecting=0
            depth=0
            body=""
        fi
    done < "$source"
    if [ -s "$compatible" ]; then
        printf '%s\n' "$compatible" >> "$RUST_COMPAT_FILES"
    fi
done < "$RUST_FILES"

TYPESCRIPT_FILES="$TMPDIR/typescript-files"
if [ -d desktop/src ]; then
    find desktop/src -type f \( -name '*.ts' -o -name '*.tsx' \) -print | sort -u > "$TYPESCRIPT_FILES"
else
    : > "$TYPESCRIPT_FILES"
fi

# xgettext's JavaScript parser does not recognize translation calls in TSX JSX
# expressions. Project recognized static calls through the TypeScript compiler
# API before using the portable C parser.
TYPESCRIPT_COMPAT_FILES="$TMPDIR/typescript-compat-files"
: > "$TYPESCRIPT_COMPAT_FILES"
if [ -s "$TYPESCRIPT_FILES" ]; then
    if ! command -v bun >/dev/null 2>&1; then
        echo "Error: Bun is required to extract TypeScript translations. Run bun install --frozen-lockfile in desktop first." >&2
        exit 1
    fi
    if [ ! -f desktop/node_modules/typescript/lib/typescript.js ]; then
        echo "Error: desktop TypeScript dependencies are missing. Run bun install --frozen-lockfile in desktop first." >&2
        exit 1
    fi
    TYPESCRIPT_COMPAT_DIR="$TMPDIR/typescript-compat"
    mkdir -p "$TYPESCRIPT_COMPAT_DIR"
    bun "$SCRIPT_DIR/extract-typescript-gettext.ts" \
        "$TYPESCRIPT_FILES" \
        "$TYPESCRIPT_COMPAT_FILES" \
        "$TYPESCRIPT_COMPAT_DIR"
fi

extract() {
    local language="$1"
    local files="$2"
    local output="$3"
    shift 3

    [ -s "$files" ] || return 0
    xgettext \
        --files-from="$files" \
        --output="$output" \
        --language="$language" \
        --from-code=UTF-8 \
        --add-comments=Translators: \
        --package-name=ClamUI \
        --package-version="$VERSION" \
        --copyright-holder="ClamUI Contributors" \
        --msgid-bugs-address="https://github.com/linx-systems/clamui/issues" \
        "$@"
}

echo "Extracting translatable strings from Rust/Tauri and TypeScript..."
# GNU gettext installations in supported CI do not consistently ship a Rust
# parser. The compatible snippets above use the universally available C parser
# instead, keeping Rust extraction portable on Ubuntu 22.04.
extract C "$RUST_COMPAT_FILES" "$TMPDIR/rust.pot" \
    --keyword=tr:2 \
    --keyword=trf:2 \
    --keyword=trn:2,3 \
    --keyword=text:2 \
    --keyword=translate:2 \
    --keyword=translate_context:2c,3 \
    --keyword=ngettext:1,2 \
    --keyword=pgettext:1c,2
extract C "$TYPESCRIPT_COMPAT_FILES" "$TMPDIR/typescript.pot" \
    --keyword=_:1 \
    --keyword=ngettext:1,2 \
    --keyword=pgettext:1c,2

POT_INPUTS=()
[ -f "$TMPDIR/rust.pot" ] && POT_INPUTS+=("$TMPDIR/rust.pot")
[ -f "$TMPDIR/typescript.pot" ] && POT_INPUTS+=("$TMPDIR/typescript.pot")
msgcat --use-first --output="$TMPDIR/clamui.pot" "${POT_INPUTS[@]}"

# xgettext's template placeholder is not valid once the POT contains plural
# entries. ClamUI's source language is English, so publish its closed rule.
CANONICAL_POT="$TMPDIR/clamui-canonical.pot"
while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
        '"Plural-Forms: nplurals=INTEGER; plural=EXPRESSION;\n"')
            printf '%s\n' '"Plural-Forms: nplurals=2; plural=(n != 1);\n"' >> "$CANONICAL_POT"
            ;;
        *) printf '%s\n' "$line" >> "$CANONICAL_POT" ;;
    esac
done < "$TMPDIR/clamui.pot"
mv "$CANONICAL_POT" "$TMPDIR/clamui.pot"

if [ "$MODE" = "--check" ]; then
    # xgettext refreshes this timestamp on every invocation. It does not change
    # translator-visible source strings, so exclude it from freshness comparison.
    grep -v '^"POT-Creation-Date:' "$TMPDIR/clamui.pot" > "$TMPDIR/generated-normalized.pot"
    grep -v '^"POT-Creation-Date:' "$OUTPUT" > "$TMPDIR/current-normalized.pot"
    if ! cmp -s "$TMPDIR/generated-normalized.pot" "$TMPDIR/current-normalized.pot"; then
        echo "::error file=$OUTPUT::Translation template is stale; run ./scripts/update-pot.sh" >&2
        exit 1
    fi
    echo "$OUTPUT is current."
    exit 0
fi

mv "$TMPDIR/clamui.pot" "$OUTPUT"

COUNT=$(grep -c '^msgid ' "$OUTPUT" 2>/dev/null || echo 0)
COUNT=$((COUNT - 1))
echo "Generated $OUTPUT with $COUNT translatable strings."
