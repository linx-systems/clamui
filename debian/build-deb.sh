#!/usr/bin/env bash
# Build the native ClamUI Debian packages.
# Usage: ./debian/build-deb.sh [OUTPUT_DIR]

set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGE_NAME="clamui"
BUILD_DIR=""

log_info() { printf '[INFO] %s\n' "$1"; }
log_error() { printf '[ERROR] %s\n' "$1" >&2; }

show_help() {
    cat <<'EOF'
Usage: ./debian/build-deb.sh [OUTPUT_DIR]

Builds matching architecture-specific ClamUI and privileged-helper Debian
packages. OUTPUT_DIR defaults to the project root.

Set CLAMUI_ARTIFACT_DIR to an existing release-artifact directory containing
clamui, clamui-scheduled-scan, and clamui-apply-preferences to package
prebuilt native binaries without invoking Bun or Cargo.
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

    DEB_FILENAME="${PACKAGE_NAME}_${VERSION}_${ARCHITECTURE}.deb"
}

check_prerequisites() {
    local command
    for command in dpkg-deb msgfmt; do
        if ! command -v "$command" >/dev/null 2>&1; then
            log_error "Required command not found: $command"
            return 1
        fi
    done

    if [ -z "${CLAMUI_ARTIFACT_DIR:-}" ]; then
        for command in bun cargo; do
            if ! command -v "$command" >/dev/null 2>&1; then
                log_error "Required command not found: $command"
                return 1
            fi
        done
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

verify_artifacts() {
    local artifact
    for artifact in clamui clamui-scheduled-scan clamui-apply-preferences; do
        if [ ! -x "$ARTIFACT_DIR/$artifact" ]; then
            log_error "Expected compiled artifact is missing or not executable: $ARTIFACT_DIR/$artifact"
            return 1
        fi
    done
}

build_artifacts() {
    if [ -n "${CLAMUI_ARTIFACT_DIR:-}" ]; then
        ARTIFACT_DIR="${CLAMUI_ARTIFACT_DIR%/}"
        log_info "Using prebuilt native artifacts from $ARTIFACT_DIR"
        verify_artifacts
        return
    fi

    if [ ! -f "$PROJECT_ROOT/desktop/package.json" ]; then
        log_error "Tauri frontend manifest not found: desktop/package.json"
        return 1
    fi

    log_info "Installing locked Bun dependencies and building the frontend"
    bun --cwd "$PROJECT_ROOT/desktop" install --frozen-lockfile
    ( cd "$PROJECT_ROOT/desktop" && bun run build )

    log_info "Building release Rust binaries"
    (
        cd "$PROJECT_ROOT"
        cargo build --manifest-path "$PROJECT_ROOT/Cargo.toml" --release --locked \
            --package clamui --bin clamui
        cargo build --manifest-path "$PROJECT_ROOT/Cargo.toml" --release --locked \
            --package clamui-core --bin clamui-scheduled-scan --bin clamui-apply-preferences
    )

    ARTIFACT_DIR="$(artifact_dir)"
    verify_artifacts
}

create_package_structure() {
    BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/clamui-deb.XXXXXX")"
    chmod 0755 "$BUILD_DIR"
    trap cleanup EXIT
    install -d -m 0755 \
        "$BUILD_DIR/DEBIAN" \
        "$BUILD_DIR/usr/bin" \
        "$BUILD_DIR/usr/share/applications" \
        "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps" \
        "$BUILD_DIR/usr/share/icons/hicolor/128x128/apps" \
        "$BUILD_DIR/usr/share/metainfo" \
        "$BUILD_DIR/usr/share/nemo/actions" \
        "$BUILD_DIR/usr/share/clamui/integrations" \
        "$BUILD_DIR/usr/share/clamui" \
        "$BUILD_DIR/usr/share/kio/servicemenus" \
        "$BUILD_DIR/usr/share/kservices5/ServiceMenus"
}

cleanup() {
    if [ -n "$BUILD_DIR" ] && [ -d "$BUILD_DIR" ]; then
        rm -rf "$BUILD_DIR"
    fi
}

stage_native_binaries() {
    install -m 0755 "$ARTIFACT_DIR/clamui" "$BUILD_DIR/usr/bin/clamui"
    install -m 0755 "$ARTIFACT_DIR/clamui-scheduled-scan" \
        "$BUILD_DIR/usr/bin/clamui-scheduled-scan"
}

stage_locales() {
    local language source destination
    local po_dir="$PROJECT_ROOT/po"
    local linguas="$po_dir/LINGUAS"

    if [ ! -f "$linguas" ]; then
        log_error "Locale manifest not found: $linguas"
        return 1
    fi

    while IFS= read -r language || [ -n "$language" ]; do
        language="${language%%#*}"
        language="${language//[[:space:]]/}"
        [ -z "$language" ] && continue
        source="$po_dir/$language.po"
        destination="$BUILD_DIR/usr/share/locale/$language/LC_MESSAGES"
        if [ ! -f "$source" ]; then
            log_error "Locale listed in LINGUAS is missing: $source"
            return 1
        fi
        install -d -m 0755 "$destination"
        msgfmt --output-file="$destination/clamui.mo" "$source"
        chmod 0644 "$destination/clamui.mo"
    done < "$linguas"
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

stage_desktop_assets() {
    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI.desktop" \
        "$BUILD_DIR/usr/share/applications/io.github.linx_systems.ClamUI.desktop" 0644
    stage_required_file "$PROJECT_ROOT/icons/io.github.linx_systems.ClamUI.svg" \
        "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps/io.github.linx_systems.ClamUI.svg" 0644
    stage_required_file "$PROJECT_ROOT/icons/io.github.linx_systems.ClamUI.png" \
        "$BUILD_DIR/usr/share/icons/hicolor/128x128/apps/io.github.linx_systems.ClamUI.png" 0644
    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI.metainfo.xml" \
        "$BUILD_DIR/usr/share/metainfo/io.github.linx_systems.ClamUI.metainfo.xml" 0644

    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI.nemo_action" \
        "$BUILD_DIR/usr/share/nemo/actions/io.github.linx_systems.ClamUI.nemo_action" 0644
    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI-virustotal.nemo_action" \
        "$BUILD_DIR/usr/share/nemo/actions/io.github.linx_systems.ClamUI-virustotal.nemo_action" 0644
    stage_required_file "$PROJECT_ROOT/scripts/clamui-scan-nautilus.sh" \
        "$BUILD_DIR/usr/share/clamui/integrations/clamui-scan-nautilus.sh" 0755
    stage_required_file "$PROJECT_ROOT/scripts/clamui-virustotal-nautilus.sh" \
        "$BUILD_DIR/usr/share/clamui/integrations/clamui-virustotal-nautilus.sh" 0755

    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI.service.desktop" \
        "$BUILD_DIR/usr/share/kio/servicemenus/io.github.linx_systems.ClamUI.service.desktop" 0644
    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI.service.desktop" \
        "$BUILD_DIR/usr/share/kservices5/ServiceMenus/io.github.linx_systems.ClamUI.service.desktop" 0644
    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI-virustotal.desktop" \
        "$BUILD_DIR/usr/share/kio/servicemenus/io.github.linx_systems.ClamUI-virustotal.desktop" 0644
    stage_required_file "$PROJECT_ROOT/data/io.github.linx_systems.ClamUI-virustotal.desktop" \
        "$BUILD_DIR/usr/share/kservices5/ServiceMenus/io.github.linx_systems.ClamUI-virustotal.desktop" 0644
    stage_required_file "$PROJECT_ROOT/signing-key.asc" \
        "$BUILD_DIR/usr/share/clamui/signing-key.asc" 0644
}

stage_control_files() {
    sed -e "s/VERSION/$VERSION/g" -e "s/ARCHITECTURE/$ARCHITECTURE/g" \
        "$SCRIPT_DIR/DEBIAN/control" > "$BUILD_DIR/DEBIAN/control"
    chmod 0644 "$BUILD_DIR/DEBIAN/control"

    local script
    for script in postinst prerm postrm; do
        if [ -f "$SCRIPT_DIR/DEBIAN/$script" ]; then
            install -m 0755 "$SCRIPT_DIR/DEBIAN/$script" "$BUILD_DIR/DEBIAN/$script"
        fi
    done
}

build_package() {
    local output="$OUTPUT_DIR/$DEB_FILENAME"
    rm -f "$output"
    dpkg-deb --root-owner-group --build "$BUILD_DIR" "$output"
    log_info "Built $output"
}

main() {
    extract_version
    check_prerequisites
    build_artifacts
    create_package_structure
    stage_native_binaries
    stage_locales
    stage_desktop_assets
    stage_control_files
    build_package

    log_info "Building matching privileged helper package"
    CLAMUI_ARTIFACT_DIR="$ARTIFACT_DIR" "$SCRIPT_DIR/build-privileged-helper-deb.sh" "$OUTPUT_DIR"
}

main
