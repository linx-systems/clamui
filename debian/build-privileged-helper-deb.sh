#!/usr/bin/env bash
# Build the version-matched native ClamUI privileged-helper Debian package.
# Usage: ./debian/build-privileged-helper-deb.sh [OUTPUT_DIR]

set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR=""

log_info() { printf '[INFO] %s\n' "$1"; }
log_error() { printf '[ERROR] %s\n' "$1" >&2; }

show_help() {
    cat <<'EOF'
Usage: ./debian/build-privileged-helper-deb.sh [OUTPUT_DIR]

Builds clamui-privileged-helper for the native dpkg architecture. OUTPUT_DIR
defaults to the project root.
EOF
}

if [ "$#" -gt 1 ]; then
    log_error "Expected at most one output directory."
    exit 2
fi
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    show_help
    exit 0
fi

RAW_OUTPUT_DIR="${1:-$PROJECT_ROOT}"
mkdir -p "$RAW_OUTPUT_DIR"
OUTPUT_DIR="$(cd "$RAW_OUTPUT_DIR" && pwd)"
ARCHITECTURE="$(dpkg --print-architecture)"

extract_version() {
    local cargo_toml="$PROJECT_ROOT/Cargo.toml"
    if [ ! -f "$cargo_toml" ]; then
        log_error "Cargo.toml not found: $cargo_toml"
        return 1
    fi
    VERSION="$(grep -E '^version[[:space:]]*=' "$cargo_toml" | head -n 1)"
    VERSION="${VERSION#*=}"
    VERSION="${VERSION//[[:space:]]/}"
    VERSION="${VERSION#\"}"
    VERSION="${VERSION%\"}"
    VERSION="${VERSION#\'}"
    VERSION="${VERSION%\'}"
    if [ -z "$VERSION" ]; then
        log_error "Could not extract a workspace version from Cargo.toml"
        return 1
    fi
    DEB_FILENAME="clamui-privileged-helper_${VERSION}_${ARCHITECTURE}.deb"
}

artifact_dir() {
    local target_root
    if [ -n "${CARGO_TARGET_DIR:-}" ]; then
        case "$CARGO_TARGET_DIR" in
            /*) target_root="$CARGO_TARGET_DIR" ;;
            *) target_root="$PROJECT_ROOT/$CARGO_TARGET_DIR" ;;
        esac
    else
        target_root="$PROJECT_ROOT/target"
    fi

    if [ -n "${CARGO_BUILD_TARGET:-}" ]; then
        printf '%s/%s/release' "$target_root" "$CARGO_BUILD_TARGET"
    else
        printf '%s/release' "$target_root"
    fi
}

build_helper() {
    if [ -n "${CLAMUI_ARTIFACT_DIR:-}" ]; then
        ARTIFACT_DIR="$CLAMUI_ARTIFACT_DIR"
    else
        if ! command -v cargo >/dev/null 2>&1; then
            log_error "Required command not found: cargo"
            return 1
        fi
        (
            cd "$PROJECT_ROOT"
            cargo build --manifest-path "$PROJECT_ROOT/Cargo.toml" --release --locked \
                --package clamui-core --bin clamui-apply-preferences
        )
        ARTIFACT_DIR="$(artifact_dir)"
    fi

    if [ ! -x "$ARTIFACT_DIR/clamui-apply-preferences" ]; then
        log_error "Expected compiled helper is missing or not executable: $ARTIFACT_DIR/clamui-apply-preferences"
        return 1
    fi
}

cleanup() {
    if [ -n "$BUILD_DIR" ] && [ -d "$BUILD_DIR" ]; then
        rm -rf "$BUILD_DIR"
    fi
}

stage_required_file() {
    local source="$1"
    local destination="$2"
    local mode="$3"
    if [ ! -f "$source" ]; then
        log_error "Required package asset is missing: $source"
        return 1
    fi
    install -m "$mode" "$source" "$destination"
}

stage_package() {
    BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/clamui-helper-deb.XXXXXX")"
    chmod 0755 "$BUILD_DIR"
    trap cleanup EXIT
    install -d -m 0755 \
        "$BUILD_DIR/DEBIAN" \
        "$BUILD_DIR/usr/bin" \
        "$BUILD_DIR/usr/share/polkit-1/actions"

    # Both files are root-owned by dpkg-deb --root-owner-group. The policy
    # names the same canonical helper path and action ID as the native binary.
    install -m 0755 "$ARTIFACT_DIR/clamui-apply-preferences" \
        "$BUILD_DIR/usr/bin/clamui-apply-preferences"
    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI.policy" \
        "$BUILD_DIR/usr/share/polkit-1/actions/io.github.linx_systems.ClamUI.policy" 0644

    sed -e "s/VERSION/$VERSION/g" -e "s/ARCHITECTURE/$ARCHITECTURE/g" \
        "$SCRIPT_DIR/DEBIAN/control.helper" > "$BUILD_DIR/DEBIAN/control"
    chmod 0644 "$BUILD_DIR/DEBIAN/control"
}

build_package() {
    local output="$OUTPUT_DIR/$DEB_FILENAME"
    rm -f "$output"
    dpkg-deb --root-owner-group --build "$BUILD_DIR" "$output"
    log_info "Built $output"
}

main() {
    if ! command -v dpkg-deb >/dev/null 2>&1; then
        log_error "Required command not found: dpkg-deb"
        exit 1
    fi
    extract_version
    build_helper
    stage_package
    build_package
}

main
