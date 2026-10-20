#!/bin/bash
# Validate gettext catalogs before merge.
#
# Checks:
#   1. POT and catalog syntax plus gettext format-string consistency.
#   2. Every active catalog has exact compiled coverage, complete plural forms,
#      and preserved named brace placeholders.
#   3. LINGUAS names exactly the shipped catalog set.
#   4. Generated MO files are not committed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

LINGUAS="po/LINGUAS"
POT="po/clamui.pot"
EXPECTED_ACTIVE_CODES=(de en es fr hu it nb pt_BR zh_CN)
ERRORS=0
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mapfile -t PO_FILES < <(find po/ -maxdepth 1 -type f -name "*.po" -printf '%f\n' | sort)
LINGUAS_CODES=()
if [ -f "$LINGUAS" ]; then
    mapfile -t LINGUAS_CODES < <(grep -v '^#' "$LINGUAS" | grep -v '^$' | tr -s ' ' '\n' | sort)
else
    echo "::error file=$LINGUAS::Missing active locale manifest"
    ERRORS=$((ERRORS + 1))
fi


echo "Translation validation"
echo "  Active PO files found: ${#PO_FILES[@]}"
echo "  Active LINGUAS entries: ${#LINGUAS_CODES[@]}"
echo

mapfile -t MO_FILES < <(find po/ -name "*.mo" -print | sort)
if [ "${#MO_FILES[@]}" -gt 0 ]; then
    for mo in "${MO_FILES[@]}"; do
        echo "::error file=$mo::Compiled .mo file should not be committed: $mo"
        ERRORS=$((ERRORS + 1))
    done
fi

if [ ! -f "$POT" ]; then
    echo "::error file=$POT::Missing canonical gettext template"
    ERRORS=$((ERRORS + 1))
elif ! msgfmt -c --check-format -o /dev/null "$POT"; then
    echo "::error file=$POT::msgfmt validation failed for the gettext template"
    ERRORS=$((ERRORS + 1))
fi

echo "Checking active locale manifest..."
if [ "${#LINGUAS_CODES[@]}" -ne "${#EXPECTED_ACTIVE_CODES[@]}" ]; then
    echo "::error file=$LINGUAS::Expected supported locales: ${EXPECTED_ACTIVE_CODES[*]}"
    ERRORS=$((ERRORS + 1))
fi
for language in "${EXPECTED_ACTIVE_CODES[@]}"; do
    if [[ " ${LINGUAS_CODES[*]} " != *" $language "* ]]; then
        echo "::error file=$LINGUAS::Missing supported locale '$language'"
        ERRORS=$((ERRORS + 1))
    fi
done

for po in "${PO_FILES[@]}"; do
    language="${po%.po}"
    if [[ " ${LINGUAS_CODES[*]} " != *" $language "* ]]; then
        echo "::error file=$LINGUAS::Active catalog '$po' is not listed in LINGUAS"
        ERRORS=$((ERRORS + 1))
    fi
done

for language in "${LINGUAS_CODES[@]}"; do
    if [ ! -f "po/${language}.po" ]; then
        echo "::error file=$LINGUAS::Language '$language' is listed in LINGUAS but po/${language}.po does not exist"
        ERRORS=$((ERRORS + 1))
    fi
done

if ! command -v bun >/dev/null 2>&1; then
    echo "::error::Bun is required to validate compiled active catalogs"
    ERRORS=$((ERRORS + 1))
    BUN_AVAILABLE=false
else
    BUN_AVAILABLE=true
fi

echo "Validating active catalogs..."
COMPILED_CATALOGS=()
for po in "${PO_FILES[@]}"; do
    language="${po%.po}"
    po_path="po/$po"
    compiled_catalog="$TMP_DIR/$language.mo"
    if ! msgfmt -c --check-format --statistics --output-file="$compiled_catalog" "$po_path" 2>&1; then
        echo "::error file=$po_path::msgfmt validation failed for active catalog"
        ERRORS=$((ERRORS + 1))
        continue
    fi

    if [ -f "$POT" ] && ! msgcmp "$po_path" "$POT" >/dev/null; then
        echo "::error file=$po_path::Active catalog is incompatible with $POT"
        ERRORS=$((ERRORS + 1))
    fi

    COMPILED_CATALOGS+=("$language=$compiled_catalog")
done

if [ -f "$POT" ] && [ "${#COMPILED_CATALOGS[@]}" -eq "${#PO_FILES[@]}" ]; then
    template_po="$TMP_DIR/template.po"
    template_mo="$TMP_DIR/template.mo"
    if ! msgen --output-file="$template_po" "$POT"; then
        echo "::error file=$POT::Unable to generate the source-identity catalog"
        ERRORS=$((ERRORS + 1))
    elif ! msgfmt -c --check-format --output-file="$template_mo" "$template_po"; then
        echo "::error file=$POT::Unable to compile the source-identity catalog"
        ERRORS=$((ERRORS + 1))
    elif [ "$BUN_AVAILABLE" = true ] && ! bun "$SCRIPT_DIR/check-compiled-catalogs.ts" "$template_mo" "${COMPILED_CATALOGS[@]}"; then
        echo "::error file=$POT::Compiled active catalog validation failed"
        ERRORS=$((ERRORS + 1))
    fi
fi


if [ "$ERRORS" -gt 0 ]; then
    echo "Found $ERRORS translation error(s)."
    exit 1
fi

echo "All translation checks passed."
