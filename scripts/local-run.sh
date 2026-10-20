#!/usr/bin/env bash
# local-run.sh - Build and run the Rust/Tauri ClamUI application from source.
# This script never installs OS packages or requests root privileges.
#
# Usage:
#   ./scripts/local-run.sh                      # Sync frontend dependencies and start Tauri dev
#   ./scripts/local-run.sh --deps               # Sync locked Bun dependencies only
#   ./scripts/local-run.sh --run                # Run without prerequisite checks
#   ./scripts/local-run.sh --run -- /path/file  # Pass arguments to ClamUI

set -euo pipefail

DEPS_ONLY=false
SKIP_CHECKS=false
APP_ARGS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --deps)
            DEPS_ONLY=true
            ;;
        --run)
            SKIP_CHECKS=true
            ;;
        --)
            shift
            APP_ARGS+=("$@")
            break
            ;;
        --help|-h)
            sed -n '1,10p' "$0"
            exit 0
            ;;
        *)
            APP_ARGS+=("$1")
            ;;
    esac
    shift
done

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

check_prerequisites() {
    local command
    for command in bun cargo; do
        if ! command -v "$command" >/dev/null 2>&1; then
            printf 'Error: required command not found: %s\n' "$command" >&2
            return 1
        fi
    done

    if [ ! -f "$PROJECT_ROOT/Cargo.toml" ]; then
        printf 'Error: Cargo workspace manifest not found: %s/Cargo.toml\n' "$PROJECT_ROOT" >&2
        return 1
    fi
    if [ ! -f "$PROJECT_ROOT/desktop/package.json" ]; then
        printf 'Error: frontend manifest not found: %s/desktop/package.json\n' "$PROJECT_ROOT" >&2
        return 1
    fi
}

if [ "$SKIP_CHECKS" = false ]; then
    check_prerequisites
fi

printf 'Syncing locked Bun dependencies...\n'
bun --cwd "$PROJECT_ROOT/desktop" install --frozen-lockfile

if [ "$DEPS_ONLY" = true ]; then
    exit 0
fi

printf 'Starting ClamUI development runtime...\n'
exec bun run --cwd "$PROJECT_ROOT/desktop" tauri dev -- "${APP_ARGS[@]}"
