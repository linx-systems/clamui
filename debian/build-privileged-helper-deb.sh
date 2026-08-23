#!/bin/bash
# ClamUI Privileged Helper Debian Package Build Script
#
# Builds ``clamui-privileged-helper_<version>_all.deb``: a root-owned,
# Architecture-all package whose only payload is the canonical pkexec
# wrapper ``/usr/bin/clamui-apply-preferences``, the two self-contained,
# rewrite-isolated helper modules under ``/usr/lib/clamui`` (loaded by the
# system ``/usr/bin/python3``), and the polkit policy under
# ``/usr/share/polkit-1/actions``.
#
# The on-disk layout is produced by reusing
# ``src.cli.install_helper.install_privileged_helper(prefix=staging)``, so the
# staged tree can never drift from the runtime layout.  The wrapper always
# references the canonical ``/usr/lib/clamui`` (not the staging root), since at
# runtime the files live at their real ``/usr`` locations.
#
# The helper package coexists with the full ``clamui`` package: it declares
# ``Depends: python3, pkexec | policykit-1`` and
# ``Replaces: clamui (<= VERSION)``.  Replaces lets dpkg transfer ownership of
# the helper, library, and polkit-policy paths from an older clamui of the same
# version during upgrade; it does not force removal, so no Conflicts/Breaks are
# declared and the two packages remain co-installable.
#
# Usage: ./debian/build-privileged-helper-deb.sh [OUTPUT_DIR]
#
#   OUTPUT_DIR  Optional positional directory to write the .deb into.
#               Defaults to the repository root.
#
# Prerequisites: dpkg-deb, python3
# Output: clamui-privileged-helper_VERSION_all.deb in OUTPUT_DIR

set -euo pipefail

if [ "$#" -gt 1 ]; then
	echo "Usage: $0 [OUTPUT_DIR]" >&2
	exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTROL_HELPER="$SCRIPT_DIR/DEBIAN/control.helper"

# Optional positional OUTPUT_DIR; defaults to the repository root.  Resolve to
# an absolute path after creating it so a relative directory stays reliable
# even though the staging step re-enters the project root in a subshell.
RAW_OUTPUT_DIR="${1:-$PROJECT_ROOT}"
if [ ! -d "$RAW_OUTPUT_DIR" ]; then
	mkdir -p "$RAW_OUTPUT_DIR"
fi
OUTPUT_DIR="$(cd "$RAW_OUTPUT_DIR" && pwd)"
export OUTPUT_DIR

# Colors for output (only if terminal supports it)
if [ -t 1 ]; then
	BLUE='\033[0;34m'
	GREEN='\033[0;32m'
	RED='\033[0;31m'
	NC='\033[0m'
else
	BLUE=''
	GREEN=''
	RED=''
	NC=''
fi

log_info()  { printf "${BLUE}[INFO]${NC} %s\n" "$1"; }
log_success() { printf "${GREEN}[OK]${NC} %s\n" "$1"; }
log_error()  { printf "${RED}[ERROR]${NC} %s\n" "$1" >&2; }


#
# Version Extraction
#

extract_version() {
	PYPROJECT_FILE="$PROJECT_ROOT/pyproject.toml"
	if [ ! -f "$PYPROJECT_FILE" ]; then
		log_error "pyproject.toml not found at $PYPROJECT_FILE"
		return 1
	fi
	VERSION=$(grep -E '^version\s*=' "$PYPROJECT_FILE" | head -n1 | sed -E 's/^version\s*=\s*["\x27]([^"\x27]+)["\x27].*/\1/')
	if [ -z "$VERSION" ]; then
		log_error "Could not extract version from pyproject.toml"
		return 1
	fi
	log_success "Version: $VERSION"
	DEB_FILENAME="clamui-privileged-helper_${VERSION}_all.deb"
	return 0
}

#
# Stage the canonical payload by reusing the privileged-helper installer.
#

stage_payload() {
	# install_privileged_helper will create, under $1, the four canonical
	# files: usr/bin/clamui-apply-preferences, usr/lib/clamui/*.py (two), and
	# usr/share/polkit-1/actions/<policy>.  Importing src.cli.install_helper
	# pulls only the stdlib-based i18n module (no GTK), so this is headless-safe.
	if ! ( cd "$PROJECT_ROOT" && python3 - "$1" <<'PY'
import sys
from src.cli.install_helper import install_privileged_helper
prefix = sys.argv[1]
ok, msg = install_privileged_helper(prefix=prefix)
if not ok:
    sys.stderr.write(str(msg) + "\n")
    sys.exit(1)
PY
	); then
		log_error "install_privileged_helper failed to stage the payload"
		return 1
	fi
	return 0
}

#
# Build the .deb from a staging tree.
#

build_package() {
	if [ ! -f "$CONTROL_HELPER" ]; then
		log_error "Helper control template not found: $CONTROL_HELPER"
		return 1
	fi

	STAGING="$(mktemp -d "${TMPDIR:-/tmp}/clamui-helper-deb.XXXXXX")"
	trap 'rm -rf "$STAGING"' EXIT

	if ! stage_payload "$STAGING"; then
		return 1
	fi

	install -d -m 0755 "$STAGING/DEBIAN"
	# Global substitution: every "VERSION" token in the template (the
	# Version and Replaces fields) resolves to the project version.
	sed "s/VERSION/$VERSION/g" "$CONTROL_HELPER" >"$STAGING/DEBIAN/control"
	chmod 0644 "$STAGING/DEBIAN/control"

	if [ ! -d "$OUTPUT_DIR" ]; then
		mkdir -p "$OUTPUT_DIR"
	fi

	OUTPUT="$OUTPUT_DIR/$DEB_FILENAME"
	rm -f "$OUTPUT"

	log_info "Building $DEB_FILENAME"
	# --root-owner-group makes every entry root-owned without fakeroot, matching
	# the helper's root-owned security model.
	if ! dpkg-deb --root-owner-group --build "$STAGING" "$OUTPUT"; then
		log_error "Failed to build $DEB_FILENAME"
		return 1
	fi

	if [ ! -f "$OUTPUT" ]; then
		log_error "Package file not found after build: $OUTPUT"
		return 1
	fi

	DEB_SIZE=$(du -h "$OUTPUT" | cut -f1)
	log_success "Package: $DEB_FILENAME ($DEB_SIZE)"
	log_info "Location: $OUTPUT"
	return 0
}

main() {
	log_info "=== ClamUI Privileged Helper Debian Builder ==="
	if ! extract_version; then
		exit 1
	fi
	if ! build_package; then
		exit 1
	fi
	log_success "Done!"
}

main "$@"