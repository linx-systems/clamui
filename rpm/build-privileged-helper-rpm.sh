#!/usr/bin/env bash
# Build the version-matched native ClamUI privileged-helper RPM package.
# Usage: ./rpm/build-privileged-helper-rpm.sh [OUTPUT_DIR]

set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RPMBUILD_TOPDIR=""
SOURCES_DIR=""

log_info() { printf '[INFO] %s\n' "$1"; }
log_error() { printf '[ERROR] %s\n' "$1" >&2; }

show_help() {
    cat <<'EOF'
Usage: ./rpm/build-privileged-helper-rpm.sh [OUTPUT_DIR]

Builds an x86_64 or aarch64 clamui-privileged-helper RPM. OUTPUT_DIR defaults
to the project root. Set CLAMUI_ARTIFACT_DIR to an existing directory containing
clamui-apply-preferences to package a prebuilt native helper. Otherwise the
script runs the locked clamui-core helper-only Cargo build.

CARGO_TARGET_DIR and CARGO_BUILD_TARGET select the normal Cargo artifact
location. CLAMUI_RPM_ARCH may be set to x86_64 or aarch64 to assert the
architecture of the helper ELF before it is packaged.
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

cleanup() {
    if [ -n "$RPMBUILD_TOPDIR" ] && [ -d "$RPMBUILD_TOPDIR" ]; then
        rm -rf "$RPMBUILD_TOPDIR"
    fi
}

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
        ARTIFACT_DIR="${CLAMUI_ARTIFACT_DIR%/}"
        log_info "Using prebuilt native helper from $ARTIFACT_DIR"
    else
        if ! command -v cargo >/dev/null 2>&1; then
            log_error "Required command not found: cargo"
            return 1
        fi
        (
            cd "$PROJECT_ROOT"
            cargo build --locked --release -p clamui-core --bin clamui-apply-preferences
        )
        ARTIFACT_DIR="$(artifact_dir)"
    fi

    HELPER="$ARTIFACT_DIR/clamui-apply-preferences"
    if [ ! -x "$HELPER" ]; then
        log_error "Expected compiled helper is missing or not executable: $HELPER"
        return 1
    fi
}

verify_helper_architecture() {
    local elf_header
    if ! elf_header="$(LC_ALL=C readelf -h "$HELPER")"; then
        log_error "Helper is not a readable ELF binary: $HELPER"
        return 1
    fi

    case "$elf_header" in
        *"Class:"*"ELF64"*) ;;
        *)
            log_error "Helper must be a 64-bit ELF binary: $HELPER"
            return 1
            ;;
    esac

    case "$elf_header" in
        *"Machine:"*"Advanced Micro Devices X86-64"*) RPM_ARCH="x86_64" ;;
        *"Machine:"*"AArch64"*) RPM_ARCH="aarch64" ;;
        *)
            log_error "Helper ELF architecture is unsupported; expected x86_64 or aarch64."
            return 1
            ;;
    esac

    if [ -n "${CLAMUI_RPM_ARCH:-}" ] && [ "$CLAMUI_RPM_ARCH" != "$RPM_ARCH" ]; then
        log_error "CLAMUI_RPM_ARCH=$CLAMUI_RPM_ARCH does not match helper ELF architecture $RPM_ARCH"
        return 1
    fi

    case "$RPM_ARCH" in
        x86_64|aarch64) ;;
        *)
            log_error "Unsupported RPM architecture: $RPM_ARCH"
            return 1
            ;;
    esac
}

check_prerequisites() {
    local command
    for command in install readelf rpm rpmbuild; do
        if ! command -v "$command" >/dev/null 2>&1; then
            log_error "Required command not found: $command"
            return 1
        fi
    done
}

stage_sources() {
    RPMBUILD_TOPDIR="$(mktemp -d "${TMPDIR:-/tmp}/clamui-helper-rpm.XXXXXX")"
    SOURCES_DIR="$RPMBUILD_TOPDIR/SOURCES"
    trap cleanup EXIT
    install -d -m 0755 "$SOURCES_DIR"
    install -m 0755 "$HELPER" "$SOURCES_DIR/clamui-apply-preferences"

    local policy="$PROJECT_ROOT/data/io.github.linx_systems.ClamUI.policy"
    if [ ! -f "$policy" ]; then
        log_error "Required package asset is missing: $policy"
        return 1
    fi
    install -m 0644 "$policy" "$SOURCES_DIR/io.github.linx_systems.ClamUI.policy"
}

verify_package_metadata() {
    local package="$1"
    local -a metadata
    mapfile -t metadata < <(rpm --query --package --queryformat '%{NAME}\n%{VERSION}\n%{RELEASE}\n%{EPOCH}\n%{ARCH}\n' "$package")
    if [ "${#metadata[@]}" -ne 5 ] \
        || [ "${metadata[0]}" != "clamui-privileged-helper" ] \
        || [ "${metadata[1]}" != "$VERSION" ] \
        || [ "${metadata[2]}" != "1" ] \
        || [ "${metadata[3]}" != "0" ] \
        || [ "${metadata[4]}" != "$RPM_ARCH" ]; then
        log_error "Built RPM metadata does not match the helper package contract."
        return 1
    fi
}

build_package() {
    local expected_name="clamui-privileged-helper-${VERSION}-1.${RPM_ARCH}.rpm"
    local package="$RPMBUILD_TOPDIR/RPMS/$RPM_ARCH/$expected_name"
    local output="$OUTPUT_DIR/$expected_name"

    rpmbuild --target "$RPM_ARCH" \
        --define "_topdir $RPMBUILD_TOPDIR" \
        --define "clamui_version $VERSION" \
        --define "_build_id_links none" \
        -bb "$SCRIPT_DIR/clamui-privileged-helper.spec"

    if [ ! -f "$package" ]; then
        log_error "rpmbuild did not produce the expected package: $package"
        return 1
    fi
    verify_package_metadata "$package"
    rm -f "$output"
    install -m 0644 "$package" "$output"
    log_info "Built $output"
}

main() {
    extract_version
    check_prerequisites
    build_helper
    verify_helper_architecture
    stage_sources
    build_package
}

main
