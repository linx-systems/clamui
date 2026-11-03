#!/usr/bin/env bash
# Build the x86_64 ClamUI AppImage from the Rust/Tauri workspace.
# ClamAV and its signature database remain host-owned integrations.
set -euo pipefail

readonly APP_ID="io.github.linx_systems.ClamUI"
readonly SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
readonly PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
readonly BUILD_DIR="$PROJECT_ROOT/build-appimage-temp"
readonly APPDIR="$BUILD_DIR/ClamUI.AppDir"
readonly TAURI_CONFIG="$PROJECT_ROOT/desktop/src-tauri/tauri.conf.json"
readonly RELEASE_DIR="$PROJECT_ROOT/target/release"

log() {
    printf '[appimage] %s\n' "$*"
}

die() {
    printf '[appimage] error: %s\n' "$*" >&2
    exit 1
}

show_help() {
    cat <<'EOF'
Usage: ./appimage/build-appimage.sh [--help]

Builds the x86_64 ClamUI AppImage with the Tauri bundler. Build on the oldest
supported Linux baseline (Ubuntu 22.04-compatible) so bundled WebKitGTK/GTK
libraries retain that compatibility floor.

Required host tools: cargo, bun, appimagetool and pkg-config.

UPDATE_INFORMATION may contain AppImageUpdate metadata, for example:
  gh-releases-zsync|linx-systems|clamui|latest|ClamUI-*-x86_64.AppImage.zsync

Output: ClamUI-VERSION-x86_64.AppImage (and a .zsync sidecar when update
information is supplied). The release workflow signs those artifacts after
this script returns; this script never handles private keys.
EOF
}

case "${1:-}" in
    "") ;;
    --help|-h) show_help; exit 0 ;;
    *) die "unknown option: $1" ;;
esac

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_file() {
    [ -f "$1" ] || die "required file not found: $1"
}

workspace_version() {
    local version
    version="$(awk -F '"' '/^[[:space:]]*version[[:space:]]*=[[:space:]]*"[0-9]/{print $2; exit}' "$PROJECT_ROOT/Cargo.toml")"
    [ -n "$version" ] || die "could not read a package version from Cargo.toml"
    printf '%s\n' "$version"
}

check_prerequisites() {
    [ "$(uname -m)" = "x86_64" ] || die "this builder produces x86_64 AppImages and must run on x86_64"
    require_file "$PROJECT_ROOT/Cargo.toml"
    require_file "$PROJECT_ROOT/Cargo.lock"
    require_file "$PROJECT_ROOT/desktop/package.json"
    require_file "$PROJECT_ROOT/desktop/bun.lock"
    require_file "$TAURI_CONFIG"
    require_command cargo
    require_command bun
    require_command pkg-config

    if ! pkg-config --exists webkit2gtk-4.1 && ! pkg-config --exists webkit2gtk-4.0; then
        die "WebKitGTK development files are required (webkit2gtk-4.1 or webkit2gtk-4.0)"
    fi
    pkg-config --exists gtk+-3.0 || die "GTK3 development files are required by Tauri on Linux"
}

appimagetool_path() {
    local tool="${APPIMAGETOOL:-appimagetool}"
    if [ -x "$tool" ]; then
        printf '%s\n' "$tool"
        return
    fi
    command -v "$tool" >/dev/null 2>&1 || die "appimagetool is required (set APPIMAGETOOL to an explicit executable if needed)"
    command -v "$tool"
}

clean_build_environment() {
    # An activated Python/AppImage/GTK environment must not affect Cargo, Bun,
    # Tauri's dependency collection, or the eventual packaged launcher.
    unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE
    unset VIRTUAL_ENV CONDA_PREFIX CONDA_DEFAULT_ENV
    unset GTK_PATH GTK_DATA_PREFIX GTK_EXE_PREFIX GTK_THEME GI_TYPELIB_PATH
    unset GDK_PIXBUF_MODULE_FILE GDK_PIXBUF_MODULEDIR GSETTINGS_SCHEMA_DIR
    unset LD_LIBRARY_PATH LD_PRELOAD
}

build_tauri_bundle() {
    clean_build_environment
    rm -rf "$BUILD_DIR"
    # These are first-class Rust command binaries, not Tauri sidecars.
    (cd "$PROJECT_ROOT" && \
        cargo build --locked --release -p clamui-core \
            --bin clamui-scheduled-scan --bin clamui-apply-preferences)
    # Install the locked frontend toolchain so this builder works from a clean
    # checkout and `bun run tauri` resolves the project-local CLI.
    log "Installing locked Bun dependencies"
    (cd "$PROJECT_ROOT/desktop" && bun install --frozen-lockfile)
    # The Bun-locked Tauri CLI runs the frontend command from tauri.conf and
    # bundles the native Tauri/WebKitGTK application. No Python app is copied.
    (cd "$PROJECT_ROOT/desktop" && \
        bun run tauri build --config "$TAURI_CONFIG" --bundles appimage)
    [ -x "$RELEASE_DIR/clamui" ] || die "Tauri did not produce target/release/clamui"
    [ -x "$RELEASE_DIR/clamui-scheduled-scan" ] || die "scheduled scan helper was not built"
    [ -x "$RELEASE_DIR/clamui-apply-preferences" ] || die "privileged helper was not built"
}

find_tauri_appimage() {
    local -a images
    shopt -s nullglob
    images=("$RELEASE_DIR"/bundle/appimage/*.AppImage)
    shopt -u nullglob
    [ "${#images[@]}" -eq 1 ] || die "expected exactly one Tauri AppImage under target/release/bundle/appimage"
    printf '%s\n' "${images[0]}"
}

extract_tauri_appdir() {
    local image="$1"
    mkdir -p "$BUILD_DIR"
    (
        cd "$BUILD_DIR"
        "$image" --appimage-extract >/dev/null
        mv squashfs-root "$(basename "$APPDIR")"
    )
    [ -x "$APPDIR/usr/bin/clamui" ] || die "Tauri AppImage lacks /usr/bin/clamui"
}

install_packaging_assets() {
    local assets="$PROJECT_ROOT/crates/clamui-core/assets/integrations"
    local destination="$APPDIR/usr/share/clamui/integrations"

    [ -d "$assets" ] || die "integration assets missing: $assets"
    # First-class helpers are explicitly staged rather than Tauri externalBin
    # sidecars, preserving their canonical command names and trust boundary.
    install -Dm755 "$RELEASE_DIR/clamui-scheduled-scan" "$APPDIR/usr/bin/clamui-scheduled-scan"
    install -Dm755 "$RELEASE_DIR/clamui-apply-preferences" "$APPDIR/usr/bin/clamui-apply-preferences"

    mkdir -p "$destination"
    cp -a "$assets/." "$destination/"
    # Tauri's product-name desktop files use the temporary bundle identity.
    # Replace only those generated copies with the canonical legacy ID in
    # both locations expected by AppImage desktop integration.
    rm -f "$APPDIR/ClamUI.desktop" "$APPDIR/usr/share/applications/ClamUI.desktop"
    install -Dm644 "$PROJECT_ROOT/data/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
    install -Dm644 "$PROJECT_ROOT/data/$APP_ID.desktop" "$APPDIR/usr/share/applications/$APP_ID.desktop"
    # appimagetool associates root desktop files with an .appdata.xml file;
    # the same canonical AppStream metadata is installed system-wide below.
    install -Dm644 "$PROJECT_ROOT/data/$APP_ID.metainfo.xml" "$APPDIR/$APP_ID.appdata.xml"
    install -Dm644 "$PROJECT_ROOT/data/$APP_ID.metainfo.xml" "$APPDIR/usr/share/metainfo/$APP_ID.metainfo.xml"
    # Replace only root Tauri icon artifacts that belonged to its temporary
    # desktop identity; appimagetool resolves the canonical desktop Icon from
    # the AppDir root and uses .DirIcon for file-manager integration.
    rm -f "$APPDIR/.DirIcon" "$APPDIR/ClamUI.png" "$APPDIR/clamui.png"
    install -Dm644 "$PROJECT_ROOT/icons/$APP_ID.png" "$APPDIR/$APP_ID.png"
    ln -s "$APP_ID.png" "$APPDIR/.DirIcon"
    install -Dm644 "$PROJECT_ROOT/icons/$APP_ID.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
    install -Dm644 "$PROJECT_ROOT/icons/$APP_ID.png" "$APPDIR/usr/share/icons/hicolor/128x128/apps/$APP_ID.png"
}

verify_bundled_gui_runtime() {
    # The bundle must carry its GTK/WebKitGTK runtime instead of binding to a
    # potentially newer host library after a baseline-compatible build.
    if ! find "$APPDIR/usr/lib" -type f \( -name 'libwebkit2gtk-*.so*' -o -name 'libgtk-3.so*' \) -print -quit | grep -q .; then
        die "Tauri AppImage did not bundle WebKitGTK/GTK runtime libraries"
    fi
}

write_clean_apprun() {
    # Preserve linuxdeploy's AppRun, which configures the bundled GTK/WebKit
    # runtime before it starts AppRun.wrapped. Cleaning the environment alone
    # would otherwise make the AppImage depend on host runtime paths.
    mv "$APPDIR/AppRun" "$APPDIR/AppRun.tauri"
    cat >"$APPDIR/AppRun" <<'EOF'
#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE
unset VIRTUAL_ENV CONDA_PREFIX CONDA_DEFAULT_ENV
unset GTK_PATH GTK_DATA_PREFIX GTK_EXE_PREFIX GTK_THEME GI_TYPELIB_PATH
unset GDK_PIXBUF_MODULE_FILE GDK_PIXBUF_MODULEDIR GSETTINGS_SCHEMA_DIR
unset LD_LIBRARY_PATH LD_PRELOAD
exec "$HERE/AppRun.tauri" "$@"
EOF
    chmod 0755 "$APPDIR/AppRun"
}

create_appimage() {
    local version="$1"
    local appimagetool="$2"
    local output="$PROJECT_ROOT/ClamUI-${version}-x86_64.AppImage"
    local -a args=(--appimage-extract-and-run)

    rm -f "$output" "$output.zsync"
    if [ -n "${UPDATE_INFORMATION:-}" ]; then
        args+=(-u "$UPDATE_INFORMATION")
    fi
    "$appimagetool" "${args[@]}" "$APPDIR" "$output"
    [ -f "$output" ] || die "appimagetool did not produce $output"
    chmod 0755 "$output"
    if [ -n "${UPDATE_INFORMATION:-}" ] && [ ! -f "$output.zsync" ]; then
        die "UPDATE_INFORMATION was supplied but no zsync sidecar was generated"
    fi
    log "created $(basename "$output")"
}

main() {
    local version appimagetool tauri_image
    check_prerequisites
    version="$(workspace_version)"
    build_tauri_bundle
    tauri_image="$(find_tauri_appimage)"
    extract_tauri_appdir "$tauri_image"
    install_packaging_assets
    verify_bundled_gui_runtime
    write_clean_apprun
    appimagetool="$(appimagetool_path)"
    create_appimage "$version" "$appimagetool"
    rm -rf "$BUILD_DIR"
}

main
