#!/bin/sh
# ClamUI local-install uninstaller. Distribution-managed installations must be
# removed with their package manager so package ownership and the polkit helper
# remain consistent.

set -eu

if [ -t 1 ]; then
    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    NC='\033[0m'
else
    BLUE=''
    GREEN=''
    YELLOW=''
    RED=''
    NC=''
fi

log_info() { printf "${BLUE}[INFO]${NC} %s\n" "$1"; }
log_success() { printf "${GREEN}[OK]${NC} %s\n" "$1"; }
log_warning() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$1" >&2; }

show_help() {
    cat <<'EOF'
ClamUI local-install uninstaller

Usage: ./uninstall.sh [OPTIONS]

Options:
    --system    Remove a manually installed /usr/local ClamUI application
                 (requires root). Do not use for distribution packages.
    --help       Show this help message

This removes only ClamUI executables and desktop/file-manager integration
installed in the selected local prefix. It never removes settings, profiles,
logs, quarantine data, scan history, or other user data.

For Flatpak, run: flatpak uninstall io.github.linx_systems.ClamUI
For a Debian or other distribution package, use that distribution's package
manager. This script deliberately does not remove the system privileged helper.
EOF
}

SYSTEM_INSTALL=0
for arg in "$@"; do
    case "$arg" in
        --system) SYSTEM_INSTALL=1 ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $arg"
            show_help
            exit 1
            ;;
    esac
done

if [ "$SYSTEM_INSTALL" = "1" ]; then
    if [ "$(id -u)" != "0" ]; then
        log_error "System local uninstallation requires root privileges."
        log_info "Run: sudo ./uninstall.sh --system"
        exit 1
    fi
    PREFIX=/usr/local
    SHARE_DIR=/usr/local/share
    NAUTILUS_SCRIPTS_DIR=''
else
    PREFIX="${HOME}/.local"
    SHARE_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}"
    NAUTILUS_SCRIPTS_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/nautilus/scripts"
fi

BIN_DIR="${PREFIX}/bin"
DESKTOP_DIR="${SHARE_DIR}/applications"
ICON_THEME_DIR="${SHARE_DIR}/icons/hicolor"
NEMO_ACTION_DIR="${SHARE_DIR}/nemo/actions"
DOLPHIN_KIO_DIR="${SHARE_DIR}/kio/servicemenus"
DOLPHIN_LEGACY_DIR="${SHARE_DIR}/kservices5/ServiceMenus"
FILES_REMOVED=0

remove_file() {
    if [ -e "$1" ] || [ -L "$1" ]; then
        rm -f -- "$1"
        log_success "Removed: $1"
        FILES_REMOVED=$((FILES_REMOVED + 1))
    fi
}

remove_binaries() {
    log_info "Removing native ClamUI executables from ${BIN_DIR}"
    remove_file "${BIN_DIR}/clamui"
    remove_file "${BIN_DIR}/clamui-cli"
    remove_file "${BIN_DIR}/clamui-scheduled-scan"
}

remove_desktop_integration() {
    log_info "Removing ClamUI desktop and file-manager integration"
    remove_file "${DESKTOP_DIR}/io.github.linx_systems.ClamUI.desktop"
    remove_file "${ICON_THEME_DIR}/scalable/apps/io.github.linx_systems.ClamUI.svg"
    remove_file "${ICON_THEME_DIR}/128x128/apps/io.github.linx_systems.ClamUI.png"
    remove_file "${NEMO_ACTION_DIR}/io.github.linx_systems.ClamUI.nemo_action"
    remove_file "${NEMO_ACTION_DIR}/io.github.linx_systems.ClamUI-virustotal.nemo_action"
    remove_file "${DOLPHIN_KIO_DIR}/io.github.linx_systems.ClamUI.service.desktop"
    remove_file "${DOLPHIN_KIO_DIR}/io.github.linx_systems.ClamUI-virustotal.desktop"
    remove_file "${DOLPHIN_LEGACY_DIR}/io.github.linx_systems.ClamUI.service.desktop"
    remove_file "${DOLPHIN_LEGACY_DIR}/io.github.linx_systems.ClamUI-virustotal.desktop"

    if [ -n "$NAUTILUS_SCRIPTS_DIR" ]; then
        remove_file "${NAUTILUS_SCRIPTS_DIR}/Scan with ClamUI"
        remove_file "${NAUTILUS_SCRIPTS_DIR}/Scan with VirusTotal"
    fi
}

refresh_desktop_caches() {
    if command -v update-desktop-database >/dev/null 2>&1 && [ -d "$DESKTOP_DIR" ]; then
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || log_warning "Could not update the desktop database"
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -d "$ICON_THEME_DIR" ]; then
        gtk-update-icon-cache -f -t "$ICON_THEME_DIR" >/dev/null 2>&1 || log_warning "Could not update the icon cache"
    fi
    if command -v kbuildsycoca6 >/dev/null 2>&1; then
        kbuildsycoca6 --noincremental >/dev/null 2>&1 || log_warning "Could not rebuild the KDE 6 service cache"
    elif command -v kbuildsycoca5 >/dev/null 2>&1; then
        kbuildsycoca5 --noincremental >/dev/null 2>&1 || log_warning "Could not rebuild the KDE 5 service cache"
    fi
}

main() {
    log_info "Removing a local native ClamUI installation"
    remove_binaries
    remove_desktop_integration
    refresh_desktop_caches

    if [ "$FILES_REMOVED" -eq 0 ]; then
        log_info "No ClamUI files were found in the selected local prefix."
    else
        log_success "Removed ${FILES_REMOVED} ClamUI file(s)."
    fi
    log_info "Your ClamUI settings and data were retained."
    log_info "Remove a Flatpak or distribution package with its package manager."
}

main
