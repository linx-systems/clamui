#!/usr/bin/env bash
# Run from a trusted checkout. The snapshot contains data files only, not code.
# Usage: bash scripts/refresh-dependabot-sources.sh /path/to/snapshot
# Requires Bun 1.3.14 and the generators required by generate-flatpak-sources.sh.
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: bash scripts/refresh-dependabot-sources.sh SNAPSHOT_DIRECTORY" >&2
    exit 2
fi
root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
snapshot="$(CDPATH= cd -- "$1" && pwd)"
for file in Cargo.lock desktop/package.json desktop/bun.lock; do
    if [ ! -f "$snapshot/$file" ] || [ -L "$snapshot/$file" ]; then
        echo "Missing or unsafe snapshot file: $file" >&2
        exit 1
    fi
done
if [ "$(bun --version)" != 1.3.14 ]; then
    echo "Bun 1.3.14 is required" >&2
    exit 1
fi
cp -- "$snapshot/Cargo.lock" "$root/Cargo.lock"
cp -- "$snapshot/desktop/package.json" "$root/desktop/package.json"
cp -- "$snapshot/desktop/bun.lock" "$root/desktop/bun.lock"
# Do not execute dependency or project lifecycle scripts from the PR data.
(cd "$root/desktop" && bun install --ignore-scripts --yarn)
bash "$root/scripts/generate-flatpak-sources.sh"
