#!/usr/bin/env bash
# Generate the locked, checksummed dependency sources consumed by the Flatpak
# recipes. This command intentionally runs outside flatpak-builder: the build
# itself stays network-free and refuses to resolve either Cargo or frontend
# dependencies.
set -euo pipefail

readonly SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
readonly PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
readonly FLATHUB_DIR="$PROJECT_ROOT/flathub"
readonly CARGO_LOCK="$PROJECT_ROOT/Cargo.lock"
readonly BUN_LOCK="$PROJECT_ROOT/desktop/bun.lock"
readonly YARN_LOCK="$PROJECT_ROOT/desktop/yarn.lock"
readonly CHECKOUT_MANIFEST="$FLATHUB_DIR/io.github.linx_systems.ClamUI.yml"

release_url=""
release_commit=""
release_output="$FLATHUB_DIR/io.github.linx_systems.ClamUI.release.yml"

usage() {
    cat <<'EOF'
Usage: scripts/generate-flatpak-sources.sh [options]

Generate flathub/cargo-sources.json from Cargo.lock and flathub/bun-sources.json
from the Yarn export produced by `bun install --yarn`. bun.lock remains the
product lockfile; Yarn is used only because flatpak-node-generator can prefetch
its complete source archive set for a network-free Flatpak build.

Options:
  --release-url URL       Generate a concrete release manifest from this public
                          Git URL. Requires --release-commit.
  --release-commit SHA    Exact published 40-hex Git commit for --release-url.
  --release-output PATH   Destination for the generated release manifest.
  --help                  Show this help.

Prerequisites (run outside the Flatpak build):
  - Cargo.lock generated from the settled workspace manifest.
  - desktop/bun.lock and desktop/yarn.lock generated together by Bun.
  - flatpak-cargo-generator.py from flatpak-builder-tools/cargo.
  - flatpak-node-generator from flatpak-builder-tools/node, with Python 3.11+.

Environment overrides:
  FLATPAK_CARGO_GENERATOR, FLATPAK_NODE_GENERATOR
EOF
}

die() {
    printf 'generate-flatpak-sources: %s\n' "$*" >&2
    exit 1
}

require_file() {
    [ -f "$1" ] || die "missing required input: $1"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required generator not found: $1"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --release-url)
            [ "$#" -ge 2 ] || die "--release-url requires a value"
            release_url="$2"
            shift 2
            ;;
        --release-commit)
            [ "$#" -ge 2 ] || die "--release-commit requires a value"
            release_commit="$2"
            shift 2
            ;;
        --release-output)
            [ "$#" -ge 2 ] || die "--release-output requires a value"
            release_output="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

if [ -n "$release_url" ] || [ -n "$release_commit" ]; then
    [ -n "$release_url" ] && [ -n "$release_commit" ] || die "release URL and exact commit are required together"
    case "$release_url" in
        https://*|ssh://*|git@*) ;;
        *) die "release URL must identify a public HTTPS or SSH Git remote" ;;
    esac
    [[ "$release_commit" =~ ^[0-9a-fA-F]{40}$ ]] || die "release commit must be a full 40-hex Git commit"
fi

require_file "$CARGO_LOCK"
require_file "$BUN_LOCK"
require_file "$YARN_LOCK"
require_file "$CHECKOUT_MANIFEST"

cargo_generator="${FLATPAK_CARGO_GENERATOR:-flatpak-cargo-generator.py}"
node_generator="${FLATPAK_NODE_GENERATOR:-flatpak-node-generator}"
require_command "$cargo_generator"
require_command "$node_generator"

work_dir="$(mktemp -d "$FLATHUB_DIR/.flatpak-sources.XXXXXX")"
cleanup() {
    rm -rf "$work_dir"
}
trap cleanup EXIT HUP INT TERM

"$cargo_generator" "$CARGO_LOCK" -o "$work_dir/cargo-sources.json"
"$node_generator" --no-requests-cache -o "$work_dir/bun-sources.json" yarn "$YARN_LOCK"

[ -s "$work_dir/cargo-sources.json" ] || die "cargo generator produced no source records"
[ -s "$work_dir/bun-sources.json" ] || die "Bun/Yarn generator produced no source records"

# Vite transitively selects architecture-specific esbuild/Rollup binaries. The
# generated source set must include both Flathub target architectures, rather
# than succeeding on x86_64 and failing later on aarch64.
# Yarn v1 resolves `resolved` URLs through this exact mirror when configured
# by the recipes; without it, an apparently complete source manifest falls
# back to the registry under `--offline`.
grep -Fq '"dest": "flatpak-node/yarn-mirror"' "$work_dir/bun-sources.json" || die "Bun source set lacks a Yarn offline mirror"

grep -qi 'linux-x64' "$work_dir/bun-sources.json" || die "Bun source set lacks x86_64 optional native packages"
grep -qi 'linux-arm64' "$work_dir/bun-sources.json" || die "Bun source set lacks aarch64 optional native packages"

mv "$work_dir/cargo-sources.json" "$FLATHUB_DIR/cargo-sources.json"
mv "$work_dir/bun-sources.json" "$FLATHUB_DIR/bun-sources.json"

if [ -n "$release_url" ]; then
    release_tmp="$work_dir/release-manifest.yml"
    awk -v url="$release_url" -v commit="$release_commit" \
        -f "$SCRIPT_DIR/flatpak-release-source.awk" \
        < "$CHECKOUT_MANIFEST" > "$release_tmp"
    mkdir -p "$(dirname -- "$release_output")"
    mv "$release_tmp" "$release_output"
    printf 'generated release manifest: %s\n' "$release_output"
fi

printf 'generated: %s and %s\n' \
    "$FLATHUB_DIR/cargo-sources.json" "$FLATHUB_DIR/bun-sources.json"
