#!/bin/bash
# Validate PO translation files before merge.
#
# Checks:
#   1. PO syntax and format string consistency (msgfmt -c)
#   2. LINGUAS <-> .po file consistency
#   3. No compiled .mo files committed
#
# Exits 0 when no .po files exist (graceful no-op).
#
# Usage:
#   ./scripts/check-translations.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

LINGUAS="po/LINGUAS"
ERRORS=0

# Collect .po files (may be empty)
mapfile -t PO_FILES < <(find po/ -maxdepth 1 -name "*.po" -printf '%f\n' | sort)

# Collect language codes from LINGUAS (strip comments and blank lines)
LINGUAS_CODES=()
if [ -f "$LINGUAS" ]; then
    mapfile -t LINGUAS_CODES < <(grep -v '^#' "$LINGUAS" | grep -v '^$' | tr -s ' ' '\n' | sort)
fi

echo "Translation validation"
echo "  PO files found: ${#PO_FILES[@]}"
echo "  LINGUAS entries: ${#LINGUAS_CODES[@]}"
echo

# --- Check 1: No compiled .mo files committed ---
mapfile -t MO_FILES < <(find po/ -name "*.mo" 2>/dev/null || true)
if [ "${#MO_FILES[@]}" -gt 0 ]; then
    for mo in "${MO_FILES[@]}"; do
        echo "::error file=$mo::Compiled .mo file should not be committed: $mo"
        ERRORS=$((ERRORS + 1))
    done
fi

# If no .po files exist, nothing more to check
if [ "${#PO_FILES[@]}" -eq 0 ]; then
    echo "No .po files found - nothing to validate."
    if [ "$ERRORS" -gt 0 ]; then
        echo
        echo "Found $ERRORS error(s)."
        exit 1
    fi
    exit 0
fi

# --- Check 2: PO syntax + format string validation ---
echo "Validating PO files with msgfmt..."
for po in "${PO_FILES[@]}"; do
    po_path="po/$po"
    # -c enables all checks: format strings, header, duplicate msgids
    # --statistics prints translated/fuzzy/untranslated counts
    if msgfmt -c --statistics -o /dev/null "$po_path" 2>&1; then
        echo "  $po: OK"
    else
        echo "::error file=$po_path::msgfmt validation failed for $po"
        ERRORS=$((ERRORS + 1))
    fi
done
echo

# --- Check 3: LINGUAS consistency ---
echo "Checking LINGUAS consistency..."

# Every .po file should have its language code in LINGUAS
for po in "${PO_FILES[@]}"; do
    lang="${po%.po}"
    found=0
    for code in "${LINGUAS_CODES[@]}"; do
        if [ "$code" = "$lang" ]; then
            found=1
            break
        fi
    done
    if [ "$found" -eq 0 ]; then
        echo "::error file=$LINGUAS::Language '$lang' has po/$po but is not listed in $LINGUAS"
        ERRORS=$((ERRORS + 1))
    fi
done

# Every LINGUAS code should have a .po file
for code in "${LINGUAS_CODES[@]}"; do
    if [ ! -f "po/${code}.po" ]; then
        echo "::error file=$LINGUAS::Language '$code' is listed in $LINGUAS but po/${code}.po does not exist"
        ERRORS=$((ERRORS + 1))
    fi
done

echo

if [ "$ERRORS" -gt 0 ]; then
    echo "Found $ERRORS translation error(s)."
    exit 1
fi

echo "All translation checks passed."
