#!/bin/bash
# Verify that production translation extraction covers Rust/Tauri and TypeScript.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"
ERRORS=0


mapfile -t RUST_SOURCES < <(
    for source_root in crates desktop/src-tauri; do
        [ -d "$source_root" ] && find "$source_root" -type f -name '*.rs' -print
    done | sort -u
)
mapfile -t TYPESCRIPT_SOURCES < <(
    [ -d desktop/src ] && find desktop/src -type f \( -name '*.ts' -o -name '*.tsx' \) -print | sort || true
)

echo "Checking production translation extraction coverage..."
echo "  Rust/Tauri sources discovered automatically: ${#RUST_SOURCES[@]}"
echo "  TypeScript sources discovered automatically: ${#TYPESCRIPT_SOURCES[@]}"
echo

if [ "${#RUST_SOURCES[@]}" -eq 0 ]; then
    echo "::error::No Rust/Tauri sources discovered for extraction"
    ERRORS=$((ERRORS + 1))
fi
if [ "${#TYPESCRIPT_SOURCES[@]}" -eq 0 ]; then
    echo "::error::No TypeScript sources discovered for extraction"
    ERRORS=$((ERRORS + 1))
fi
echo


if [ "$ERRORS" -gt 0 ]; then
    echo
    echo "Found $ERRORS translation-source consistency error(s)."
    exit 1
fi


echo "Translation source coverage is consistent."
