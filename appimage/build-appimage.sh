#!/bin/bash
# ClamUI AppImage Build Script
# Builds a portable AppImage bundling Python + GTK4/libadwaita + dependencies.
# ClamAV is NOT bundled (relies on system install, like .deb).
#
# Usage: ./appimage/build-appimage.sh [--help]
#
# Prerequisites: wget, Python 3, GTK4/libadwaita system packages (Ubuntu 24.04+)
# Output: ClamUI-VERSION-x86_64.AppImage in the project root

set -e

# Colors for output (only if terminal supports it)
if [ -t 1 ]; then
	RED='\033[0;31m'
	GREEN='\033[0;32m'
	YELLOW='\033[1;33m'
	BLUE='\033[0;34m'
	NC='\033[0m' # No Color
else
	RED=''
	GREEN=''
	YELLOW=''
	BLUE=''
	NC=''
fi

# Logging functions
log_info() {
	printf "${BLUE}[INFO]${NC} %s\n" "$1"
}

log_success() {
	printf "${GREEN}[OK]${NC} %s\n" "$1"
}

log_warning() {
	printf "${YELLOW}[WARN]${NC} %s\n" "$1"
}

log_error() {
	printf "${RED}[ERROR]${NC} %s\n" "$1" >&2
}

# Show usage information
show_help() {
	cat <<'EOF'
ClamUI AppImage Build Script

Usage: ./appimage/build-appimage.sh [--help]

This script builds a portable AppImage for ClamUI.

Prerequisites:
    - wget
    - Python 3.11+
    - GTK4/libadwaita system packages (python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1)
    - pip (python3-pip)
    - FUSE (libfuse2) for running AppImages

The script will:
    1. Extract version from pyproject.toml
    2. Validate imports (block absolute src.* imports)
    3. Download linuxdeploy and GTK plugin
    4. Create AppDir with bundled Python, libraries, and ClamUI source
    5. Run linuxdeploy to resolve shared library dependencies
    6. Output a portable AppImage

Environment variables:
    UPDATE_INFORMATION    Embed update info for delta updates (AppImageUpdate).
                          For GitHub releases:
                          "gh-releases-zsync|owner|repo|latest|Pattern-*.AppImage.zsync"
                          When set, a .zsync file is generated alongside the AppImage.

Output: ClamUI-VERSION-x86_64.AppImage in the project root directory.

Run the generated AppImage with:
    chmod +x ClamUI-*.AppImage
    ./ClamUI-*.AppImage
EOF
}

# Parse command line arguments
for arg in "$@"; do
	case "$arg" in
	--help | -h)
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

#
# Directory and Path Setup
#

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Build directories
TOOLS_DIR="$PROJECT_ROOT/build-appimage-tools"
BUILD_DIR="$PROJECT_ROOT/build-appimage-temp"
APPDIR="$BUILD_DIR/ClamUI.AppDir"

# Application metadata
APP_ID="io.github.linx_systems.ClamUI"

# Package installer (set during prerequisite check)
PIP_CMD=""

# Extra library paths for bundled .libs directories (set during pip install)
EXTRA_LIB_PATHS=""

#
# Version Extraction
#

extract_version() {
	log_info "Extracting version from pyproject.toml..."

	PYPROJECT_FILE="$PROJECT_ROOT/pyproject.toml"

	if [ ! -f "$PYPROJECT_FILE" ]; then
		log_error "pyproject.toml not found at $PYPROJECT_FILE"
		log_info "Please run this script from the project repository."
		return 1
	fi

	VERSION=$(grep -E '^version\s*=' "$PYPROJECT_FILE" | head -n1 | sed -E 's/^version\s*=\s*["\x27]([^"\x27]+)["\x27].*/\1/')

	if [ -z "$VERSION" ]; then
		log_error "Could not extract version from pyproject.toml"
		log_info "Ensure pyproject.toml contains: version = \"X.Y.Z\""
		return 1
	fi

	if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+'; then
		log_warning "Version '$VERSION' may not follow semantic versioning (X.Y.Z)"
	fi

	log_success "Version: $VERSION"

	APPIMAGE_FILENAME="ClamUI-${VERSION}-x86_64.AppImage"
	log_info "AppImage will be: $APPIMAGE_FILENAME"

	return 0
}

#
# Prerequisites Checking
#

check_prerequisites() {
	log_info "=== Checking Prerequisites ==="
	echo

	PREREQS_OK=1

	# Check wget
	log_info "Checking for wget..."
	if command -v wget >/dev/null 2>&1; then
		log_success "wget found"
	else
		log_error "wget not found. Install: sudo apt install wget"
		PREREQS_OK=0
	fi

	# Check Python 3
	log_info "Checking for Python 3..."
	if command -v python3 >/dev/null 2>&1; then
		PYTHON_VERSION=$(python3 --version 2>&1)
		log_success "Python found: $PYTHON_VERSION"
	else
		log_error "Python 3 not found. Install: sudo apt install python3"
		PREREQS_OK=0
	fi

	# Check pip or uv (either works for installing dependencies)
	log_info "Checking for pip or uv..."
	PIP_CMD=""
	if command -v uv >/dev/null 2>&1; then
		PIP_CMD="uv pip"
		log_success "uv found (will use 'uv pip install')"
	elif python3 -m pip --version >/dev/null 2>&1; then
		PIP_CMD="python3 -m pip"
		log_success "pip found"
	elif command -v pip3 >/dev/null 2>&1; then
		PIP_CMD="pip3"
		log_success "pip3 found"
	else
		log_error "Neither uv nor pip found. Install: sudo apt install python3-pip (or install uv)"
		PREREQS_OK=0
	fi

	# Check PyGObject
	log_info "Checking for PyGObject..."
	if python3 -c "import gi" 2>/dev/null; then
		log_success "PyGObject found"
	else
		log_error "PyGObject not found. Install: sudo apt install python3-gi"
		PREREQS_OK=0
	fi

	# Check GTK4 typelib
	log_info "Checking for GTK4 typelib..."
	if python3 -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk" 2>/dev/null; then
		log_success "GTK4 typelib found"
	else
		log_error "GTK4 typelib not found. Install: sudo apt install gir1.2-gtk-4.0"
		PREREQS_OK=0
	fi

	# Check libadwaita typelib
	log_info "Checking for libadwaita typelib..."
	if python3 -c "import gi; gi.require_version('Adw', '1'); from gi.repository import Adw" 2>/dev/null; then
		log_success "libadwaita typelib found"
	else
		log_error "libadwaita typelib not found. Install: sudo apt install gir1.2-adw-1"
		PREREQS_OK=0
	fi

	echo

	if [ "$PREREQS_OK" = "0" ]; then
		log_error "Missing prerequisites. Please install them and try again."
		log_info "Quick install: sudo apt install wget python3 python3-pip python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libfuse2"
		exit 1
	fi

	log_success "All prerequisites satisfied!"
	echo
	return 0
}

#
# Import Validation
#

check_absolute_imports() {
	log_info "=== Checking for Absolute Imports ==="
	echo

	log_info "Scanning src/ for absolute src.* imports..."

	IMPORT_ERRORS=$(grep -rn --include="*.py" -E "^(from|import) src\." "$PROJECT_ROOT/src/" 2>/dev/null || true)

	if [ -n "$IMPORT_ERRORS" ]; then
		log_error "Found absolute src.* imports that will break when packaged!"
		echo
		log_error "The following files have problematic imports:"
		echo "$IMPORT_ERRORS" | while read -r line; do
			log_error "  $line"
		done
		echo
		log_error "REASON: The AppImage installs source as the 'clamui' package."
		log_error "        Absolute 'src.*' imports only work during development."
		echo
		log_info "FIX: Use relative imports instead:"
		log_info "  from ..core.module import X    (parent package)"
		log_info "  from .module import X          (same package)"
		return 1
	fi

	log_success "No absolute src.* imports found"
	echo
	return 0
}

#
# Download Build Tools
#

download_tools() {
	log_info "=== Downloading Build Tools ==="
	echo

	mkdir -p "$TOOLS_DIR"

	# Download linuxdeploy
	LINUXDEPLOY="$TOOLS_DIR/linuxdeploy-x86_64.AppImage"
	if [ ! -f "$LINUXDEPLOY" ]; then
		log_info "Downloading linuxdeploy..."
		wget -q --show-progress -O "$LINUXDEPLOY" \
			"https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
		chmod +x "$LINUXDEPLOY"
		log_success "linuxdeploy downloaded"
	else
		log_success "linuxdeploy already downloaded (cached)"
	fi

	# Download linuxdeploy GTK plugin
	GTK_PLUGIN="$TOOLS_DIR/linuxdeploy-plugin-gtk.sh"
	if [ ! -f "$GTK_PLUGIN" ]; then
		log_info "Downloading linuxdeploy GTK plugin..."
		wget -q --show-progress -O "$GTK_PLUGIN" \
			"https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh"
		chmod +x "$GTK_PLUGIN"
		log_success "GTK plugin downloaded"
	else
		log_success "GTK plugin already downloaded (cached)"
	fi

	# Download appimagetool (for creating AppImage after patching)
	APPIMAGETOOL="$TOOLS_DIR/appimagetool-x86_64.AppImage"
	if [ ! -f "$APPIMAGETOOL" ]; then
		log_info "Downloading appimagetool..."
		wget -q --show-progress -O "$APPIMAGETOOL" \
			"https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
		chmod +x "$APPIMAGETOOL"
		log_success "appimagetool downloaded"
	else
		log_success "appimagetool already downloaded (cached)"
	fi

	echo
	log_success "Build tools ready"
	echo
	return 0
}

#
# Create AppDir Structure
#

create_appdir() {
	log_info "=== Creating AppDir ==="
	echo

	# Clean previous build
	if [ -d "$BUILD_DIR" ]; then
		log_warning "Removing existing build directory..."
		rm -rf "$BUILD_DIR"
	fi

	mkdir -p "$APPDIR/usr/bin"
	mkdir -p "$APPDIR/usr/lib"
	mkdir -p "$APPDIR/usr/share/applications"
	mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"
	mkdir -p "$APPDIR/usr/share/icons/hicolor/128x128/apps"
	mkdir -p "$APPDIR/usr/share/metainfo"

	log_success "AppDir structure created"
	echo
	return 0
}

#
# Bundle Python Interpreter
#

bundle_python() {
	log_info "=== Bundling Python Interpreter ==="
	echo

	PYTHON_BIN=$(python3 -c "import sys; print(sys.executable)")
	PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
	# Use base_prefix to get the real Python install (not the venv, which lacks stdlib)
	PYTHON_PREFIX=$(python3 -c "import sys; print(sys.base_prefix)")

	log_info "Python binary: $PYTHON_BIN"
	log_info "Python version: $PYTHON_VER"
	log_info "Python prefix (base): $PYTHON_PREFIX"

	# Create Python directory structure in AppDir
	APPDIR_PYTHON="$APPDIR/usr"
	mkdir -p "$APPDIR_PYTHON/bin"
	mkdir -p "$APPDIR_PYTHON/lib/python${PYTHON_VER}"

	# Copy Python binary (resolve symlinks to get the real binary)
	log_info "Copying Python binary..."
	REAL_PYTHON_BIN=$(readlink -f "$PYTHON_BIN")
	log_info "Real Python binary: $REAL_PYTHON_BIN"
	cp "$REAL_PYTHON_BIN" "$APPDIR_PYTHON/bin/python3"
	chmod 755 "$APPDIR_PYTHON/bin/python3"

	# Also create python3.X symlink
	ln -sf python3 "$APPDIR_PYTHON/bin/python${PYTHON_VER}"

	# Copy Python stdlib
	log_info "Copying Python standard library..."
	STDLIB_SRC="$PYTHON_PREFIX/lib/python${PYTHON_VER}"
	STDLIB_DEST="$APPDIR_PYTHON/lib/python${PYTHON_VER}"

	if [ -d "$STDLIB_SRC" ]; then
		# Copy stdlib, excluding heavy/unnecessary modules
		rsync -a \
			--exclude='__pycache__' \
			--exclude='*.pyc' \
			--exclude='test/' \
			--exclude='tests/' \
			--exclude='tkinter/' \
			--exclude='idlelib/' \
			--exclude='turtle*' \
			--exclude='turtledemo/' \
			--exclude='ensurepip/' \
			--exclude='distutils/' \
			--exclude='lib2to3/' \
			--exclude='unittest/test/' \
			"$STDLIB_SRC/" "$STDLIB_DEST/"
		log_success "Python stdlib copied (trimmed test/tkinter/idle)"
	else
		log_error "Python stdlib not found at $STDLIB_SRC"
		return 1
	fi

	# Copy Python shared library (libpython3.X.so)
	log_info "Copying Python shared library..."
	LIBPYTHON=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('LDLIBRARY') or '')")
	# LIBDIR from sysconfig may point to venv; check base_prefix first
	LIBDIR=$(python3 -c "import sysconfig, sys; libdir = sysconfig.get_config_var('LIBDIR') or ''; print(libdir.replace(sys.prefix, sys.base_prefix) if libdir.startswith(sys.prefix) else libdir)")

	if [ -n "$LIBPYTHON" ] && [ -n "$LIBDIR" ] && [ -f "$LIBDIR/$LIBPYTHON" ]; then
		mkdir -p "$APPDIR_PYTHON/lib"
		cp "$LIBDIR/$LIBPYTHON" "$APPDIR_PYTHON/lib/"
		# Also copy versioned symlinks
		for f in "$LIBDIR"/libpython${PYTHON_VER}*.so*; do
			if [ -f "$f" ]; then
				cp -P "$f" "$APPDIR_PYTHON/lib/" 2>/dev/null || true
			fi
		done
		log_success "Python shared library copied"
	else
		log_warning "Could not locate Python shared library (statically linked?)"
		log_info "Trying alternative locations..."
		for dir in /usr/lib/x86_64-linux-gnu /usr/lib64 /usr/lib; do
			for f in "$dir"/libpython${PYTHON_VER}*.so*; do
				if [ -f "$f" ]; then
					cp -P "$f" "$APPDIR_PYTHON/lib/" 2>/dev/null || true
					log_success "Found and copied: $f"
				fi
			done
		done
	fi

	# Copy lib-dynload (compiled extension modules)
	DYNLOAD_SRC="$STDLIB_SRC/lib-dynload"
	if [ -d "$DYNLOAD_SRC" ]; then
		log_info "Copying lib-dynload extension modules..."
		cp -r "$DYNLOAD_SRC" "$STDLIB_DEST/"
		log_success "lib-dynload copied"
	fi

	echo
	log_success "Python interpreter bundled"
	echo
	return 0
}

#
# Bundle PyGObject and System Python Packages
#

bundle_system_packages() {
	log_info "=== Bundling System Python Packages ==="
	echo

	PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
	SITE_DEST="$APPDIR/usr/lib/python${PYTHON_VER}/site-packages"
	mkdir -p "$SITE_DEST"

	# Copy PyGObject (gi module) from system dist-packages
	log_info "Copying PyGObject (gi module)..."
	GI_PATH=$(python3 -c "import gi; import os; print(os.path.dirname(gi.__file__))" 2>/dev/null || true)
	if [ -n "$GI_PATH" ] && [ -d "$GI_PATH" ]; then
		cp -r "$GI_PATH" "$SITE_DEST/"
		log_success "PyGObject copied from $GI_PATH"
	else
		log_error "Could not locate PyGObject (gi module)"
		return 1
	fi

	# Copy _gi compiled extension (may be separate from gi/)
	GI_SO=$(python3 -c "import _gi; print(_gi.__file__)" 2>/dev/null || true)
	if [ -n "$GI_SO" ] && [ -f "$GI_SO" ]; then
		cp "$GI_SO" "$SITE_DEST/"
		log_success "Copied _gi extension: $GI_SO"
	fi

	# Copy pycairo (cairo module)
	log_info "Copying pycairo..."
	CAIRO_PATH=$(python3 -c "import cairo; import os; print(os.path.dirname(cairo.__file__))" 2>/dev/null || true)
	if [ -n "$CAIRO_PATH" ] && [ -d "$CAIRO_PATH" ]; then
		cp -r "$CAIRO_PATH" "$SITE_DEST/"
		log_success "pycairo copied from $CAIRO_PATH"
	else
		log_warning "Could not locate pycairo - will try pip install later"
	fi

	echo
	log_success "System Python packages bundled"
	echo
	return 0
}

#
# Install Pure Python Dependencies
#

install_pip_deps() {
	log_info "=== Installing Python Dependencies ==="
	echo

	PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
	SITE_DEST="$APPDIR/usr/lib/python${PYTHON_VER}/site-packages"

	# Install pure Python dependencies
	log_info "Installing Python dependencies via ${PIP_CMD}..."

	# Build pip install args (uv pip doesn't support --quiet the same way)
	PIP_ARGS=(
		install
		--target "$SITE_DEST"
		--no-deps
	)

	# uv pip uses --python to specify interpreter; regular pip uses --ignore-installed
	if [ "$PIP_CMD" = "uv pip" ]; then
		PIP_ARGS+=(--python "$(which python3)")
	else
		PIP_ARGS+=(--ignore-installed --quiet)
	fi

	DEPS=(
		requests
		urllib3
		psutil
		keyring
		matplotlib
		charset-normalizer
		idna
		certifi
		"jaraco.classes"
		"jaraco.functools"
		"jaraco.context"
		more-itertools
		importlib-metadata
		zipp
		SecretStorage
		jeepney
		pyparsing
		packaging
		cycler
		python-dateutil
		six
		kiwisolver
		Pillow
		fonttools
		contourpy
		numpy
	)

	$PIP_CMD "${PIP_ARGS[@]}" "${DEPS[@]}"

	# Patch bundled .libs directories (e.g., pillow.libs/, numpy.libs/)
	# These contain shared libraries with hash-mangled names that cross-reference
	# each other. linuxdeploy can't resolve them, so we add an RPATH pointing
	# each .so to its own directory, and set LD_LIBRARY_PATH during the build.
	log_info "Patching bundled shared library directories..."
	EXTRA_LIB_PATHS=""
	for libdir in "$SITE_DEST"/*.libs; do
		if [ -d "$libdir" ]; then
			LIBDIR_NAME=$(basename "$libdir")
			log_info "  Found $LIBDIR_NAME"
			EXTRA_LIB_PATHS="$libdir:$EXTRA_LIB_PATHS"
		fi
	done

	log_success "Python dependencies installed"
	echo
	return 0
}

#
# Copy ClamUI Source
#

copy_clamui_source() {
	log_info "=== Copying ClamUI Source ==="
	echo

	PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
	CLAMUI_DEST="$APPDIR/usr/lib/python${PYTHON_VER}/site-packages/src"

	log_info "Copying ClamUI source to $CLAMUI_DEST..."

	mkdir -p "$CLAMUI_DEST"

	if command -v rsync >/dev/null 2>&1; then
		rsync -a --exclude='__pycache__' --exclude='*.pyc' "$PROJECT_ROOT/src/" "$CLAMUI_DEST/"
	else
		cp -r "$PROJECT_ROOT/src/"* "$CLAMUI_DEST/"
		find "$CLAMUI_DEST" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
		find "$CLAMUI_DEST" -type f -name '*.pyc' -delete 2>/dev/null || true
	fi

	# Verify copy
	if [ ! -f "$CLAMUI_DEST/main.py" ]; then
		log_error "Failed to copy ClamUI source files"
		return 1
	fi

	log_success "ClamUI source copied"
	echo
	return 0
}

#
# Bundle GI Typelibs
#

bundle_typelibs() {
	log_info "=== Bundling GI Typelibs ==="
	echo

	TYPELIB_DEST="$APPDIR/usr/lib/girepository-1.0"
	mkdir -p "$TYPELIB_DEST"

	# Find system typelib directory
	TYPELIB_SRC=""
	for dir in \
		/usr/lib/x86_64-linux-gnu/girepository-1.0 \
		/usr/lib64/girepository-1.0 \
		/usr/lib/girepository-1.0; do
		if [ -d "$dir" ]; then
			TYPELIB_SRC="$dir"
			break
		fi
	done

	if [ -z "$TYPELIB_SRC" ]; then
		log_error "Could not find GI typelib directory"
		return 1
	fi

	log_info "Typelib source: $TYPELIB_SRC"

	# Required typelibs for GTK4/Adwaita application
	TYPELIBS=(
		"Gtk-4.0"
		"Adw-1"
		"GLib-2.0"
		"GObject-2.0"
		"Gio-2.0"
		"GModule-2.0"
		"Gdk-4.0"
		"GdkPixbuf-2.0"
		"Gsk-4.0"
		"Graphene-1.0"
		"Pango-1.0"
		"PangoCairo-1.0"
		"HarfBuzz-0.0"
		"cairo-1.0"
		"freetype2-2.0"
		"GdkWayland-4.0"
		"GdkX11-4.0"
	)

	for typelib in "${TYPELIBS[@]}"; do
		TYPELIB_FILE="$TYPELIB_SRC/${typelib}.typelib"
		if [ -f "$TYPELIB_FILE" ]; then
			cp "$TYPELIB_FILE" "$TYPELIB_DEST/"
			log_success "  Copied: ${typelib}.typelib"
		else
			log_warning "  Not found: ${typelib}.typelib (may be optional)"
		fi
	done

	echo
	log_success "GI typelibs bundled"
	echo
	return 0
}

#
# Bundle GI-loaded Shared Libraries
#
# linuxdeploy traces dependencies from the python3 binary, which doesn't
# directly link to GTK4 or libadwaita. PyGObject loads these at runtime
# via GObject Introspection, so linuxdeploy never sees them. We must
# explicitly copy them into the AppDir so they're available at runtime.
#

bundle_gi_libraries() {
	log_info "=== Bundling GI-loaded Shared Libraries ==="
	echo

	LIB_DEST="$APPDIR/usr/lib"

	# Libraries loaded dynamically by PyGObject via GI (not linked to python3)
	GI_LIBS=(
		"libadwaita-1.so.0"
		"libgtk-4.so.1"
		"libgdk_pixbuf-2.0.so.0"
		"libgsk-4.so.1"
		"libgraphene-1.0.so.0"
		"libpango-1.0.so.0"
		"libpangocairo-1.0.so.0"
		"libharfbuzz.so.0"
		"libcairo.so.2"
		"libcairo-gobject.so.2"
		"libgio-2.0.so.0"
		"libgobject-2.0.so.0"
		"libglib-2.0.so.0"
	)

	# Search paths for shared libraries
	LIB_SEARCH_DIRS=(
		/usr/lib/x86_64-linux-gnu
		/usr/lib64
		/usr/lib
	)

	local copied=0
	for lib in "${GI_LIBS[@]}"; do
		local found=0
		for dir in "${LIB_SEARCH_DIRS[@]}"; do
			if [ -f "$dir/$lib" ]; then
				# Copy the library and any versioned symlinks
				cp -P "$dir/$lib"* "$LIB_DEST/" 2>/dev/null || true
				log_success "  Copied: $lib (from $dir)"
				found=1
				copied=$((copied + 1))
				break
			fi
		done
		if [ "$found" = "0" ]; then
			log_warning "  Not found: $lib (linuxdeploy may resolve it)"
		fi
	done

	echo
	log_success "Bundled $copied GI-loaded libraries"
	echo
	return 0
}
#
# Bundle GIO Desktop Launcher
#
# GIO spawns this helper to launch desktop applications. It is not linked
# directly by the application, so linuxdeploy does not bundle it.
#

bundle_gio_launch_desktop() {
	log_info "=== Bundling GIO Desktop Launcher ==="
	echo

	local gio_libdir
	local gio_launch_desktop_src=""
	local gio_launch_desktop_dest="$APPDIR/usr/libexec/gio-launch-desktop"
	local -a gio_launch_desktop_candidates=()

	if gio_libdir=$(pkg-config --variable=libdir gio-2.0 2>/dev/null); then
		gio_launch_desktop_candidates+=(
			"$gio_libdir/glib-2.0/gio-launch-desktop"
		)
	fi
	gio_launch_desktop_candidates+=(
		"/usr/lib/x86_64-linux-gnu/glib-2.0/gio-launch-desktop"
		"/usr/lib64/glib-2.0/gio-launch-desktop"
		"/usr/lib/glib-2.0/gio-launch-desktop"
	)

	for candidate in "${gio_launch_desktop_candidates[@]}"; do
		if [ -x "$candidate" ]; then
			gio_launch_desktop_src="$candidate"
			break
		fi
	done

	if [ -z "$gio_launch_desktop_src" ]; then
		log_error "Could not find an executable gio-launch-desktop helper"
		return 1
	fi

	mkdir -p "$(dirname "$gio_launch_desktop_dest")"
	log_info "Copying: $gio_launch_desktop_src -> $gio_launch_desktop_dest"
	cp "$gio_launch_desktop_src" "$gio_launch_desktop_dest"
	chmod 755 "$gio_launch_desktop_dest"

	if [ ! -x "$gio_launch_desktop_dest" ]; then
		log_error "Bundled gio-launch-desktop is not executable: $gio_launch_desktop_dest"
		return 1
	fi

	echo
	log_success "GIO desktop launcher bundled"
	echo
	return 0
}


#
# Bundle Adwaita Icon Theme
#
# GTK4/libadwaita applications need the Adwaita icon theme for proper
# symbolic icon rendering. Without it, many icons may be missing.
#

bundle_adwaita_icons() {
	log_info "=== Bundling Adwaita Icon Theme ==="
	echo

	ICON_DEST="$APPDIR/usr/share/icons/Adwaita"
	mkdir -p "$ICON_DEST"

	# Source directories
	ICON_SRC="/usr/share/icons/Adwaita"

	if [ -d "$ICON_SRC" ]; then
		# Copy scalable symbolic icons (most important for GTK4)
		if [ -d "$ICON_SRC/scalable" ]; then
			cp -r "$ICON_SRC/scalable" "$ICON_DEST/"
			log_success "Copied scalable icons"
		fi

		# Copy index.theme for icon discovery
		if [ -f "$ICON_SRC/index.theme" ]; then
			cp "$ICON_SRC/index.theme" "$ICON_DEST/"
			log_success "Copied index.theme"
		fi

		# Copy cursors (optional, small)
		if [ -d "$ICON_SRC/cursors" ]; then
			cp -r "$ICON_SRC/cursors" "$ICON_DEST/"
			log_success "Copied cursors"
		fi
	else
		log_warning "Adwaita icon theme not found at $ICON_SRC"
	fi

	echo
	return 0
}

#
# Bundle Locale Files (i18n)
#
# Compile .po translation files to .mo and install them into the AppDir
# so the application can be used in different languages.
#

bundle_locales() {
	log_info "=== Bundling Locale Files ==="
	echo

	PO_DIR="$PROJECT_ROOT/po"
	LOCALE_DEST="$APPDIR/usr/share/locale"

	if [ ! -d "$PO_DIR" ]; then
		log_warning "No po/ directory found, skipping locale bundling"
		return 0
	fi

	# Read LINGUAS file for list of languages
	LINGUAS_FILE="$PO_DIR/LINGUAS"
	if [ ! -f "$LINGUAS_FILE" ]; then
		log_warning "No po/LINGUAS file found, skipping locale bundling"
		return 0
	fi

	LANG_COUNT=0
	while IFS= read -r lang || [ -n "$lang" ]; do
		# Skip comments and empty lines
		lang=$(echo "$lang" | sed 's/#.*//' | tr -d '[:space:]')
		[ -z "$lang" ] && continue

		PO_FILE="$PO_DIR/$lang.po"
		if [ ! -f "$PO_FILE" ]; then
			log_warning "Missing translation file: $PO_FILE"
			continue
		fi

		MO_DIR="$LOCALE_DEST/$lang/LC_MESSAGES"
		mkdir -p "$MO_DIR"
		msgfmt -o "$MO_DIR/clamui.mo" "$PO_FILE"
		LANG_COUNT=$((LANG_COUNT + 1))
	done < "$LINGUAS_FILE"

	if [ "$LANG_COUNT" -eq 0 ]; then
		log_info "No translations to bundle (LINGUAS is empty)"
	else
		log_success "Bundled $LANG_COUNT language(s)"
	fi

	echo
	return 0
}

#
# Patch GTK Plugin Hook for libadwaita
#
# The linuxdeploy GTK plugin forces GTK_THEME="Adwaita:dark" which overrides
# the user's system theme. For GTK4/libadwaita apps, we want libadwaita to
# handle its own theming natively. This function patches the generated hook.
#

patch_gtk_plugin_hook() {
	log_info "=== Patching GTK Plugin Hook for libadwaita ==="
	echo

	HOOK_FILE="$APPDIR/apprun-hooks/linuxdeploy-plugin-gtk.sh"

	if [ ! -f "$HOOK_FILE" ]; then
		log_warning "GTK plugin hook not found, skipping patch"
		return 0
	fi

	# Create patched version that works with GTK4/libadwaita:
	# - Don't force GTK_THEME (let libadwaita use its styling)
	# - Keep color-scheme detection for dark/light mode
	# - Append to GSETTINGS_SCHEMA_DIR instead of replacing

	cat >"$HOOK_FILE" <<'PATCHED_HOOK'
#! /usr/bin/env bash

# Patched for GTK4/libadwaita compatibility
# - Removed forced GTK_THEME (libadwaita handles theming)
# - Preserves user's color-scheme preference
# - Appends to system paths instead of replacing

# Detect color scheme via portal or gsettings
COLOR_SCHEME="$(dbus-send --session --dest=org.freedesktop.portal.Desktop --type=method_call --print-reply --reply-timeout=1000 /org/freedesktop/portal/desktop org.freedesktop.portal.Settings.Read 'string:org.freedesktop.appearance' 'string:color-scheme' 2> /dev/null | tail -n1 | cut -b35- | cut -d' ' -f2 || printf '')"
if [ -z "$COLOR_SCHEME" ]; then
    COLOR_SCHEME="$(gsettings get org.gnome.desktop.interface color-scheme 2> /dev/null || printf '')"
fi

# Set ADW_DEBUG_COLOR_SCHEME for libadwaita (respects user preference)
case "$COLOR_SCHEME" in
    "1"|"'prefer-dark'")  export ADW_DEBUG_COLOR_SCHEME=prefer-dark;;
    "2"|"'prefer-light'") export ADW_DEBUG_COLOR_SCHEME=prefer-light;;
esac

export APPDIR="${APPDIR:-"$(dirname "$(realpath "$0")")"}"

# GTK4/libadwaita paths
export GTK_DATA_PREFIX="$APPDIR"
export GTK_EXE_PREFIX="$APPDIR/usr"
export GTK_PATH="$APPDIR/usr/lib/gtk-4.0"
export GDK_PIXBUF_MODULE_FILE="$APPDIR/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"
export GI_TYPELIB_PATH="$APPDIR/usr/lib/girepository-1.0:${GI_TYPELIB_PATH:-}"

# Append to system paths instead of replacing (allows reading user prefs)
export XDG_DATA_DIRS="$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export GSETTINGS_SCHEMA_DIR="$APPDIR/usr/share/glib-2.0/schemas:${GSETTINGS_SCHEMA_DIR:-}"

# Note: GTK_THEME is NOT set - libadwaita handles its own theming
# Note: GDK_BACKEND is NOT forced - let GTK4 auto-detect
PATCHED_HOOK

	log_success "GTK plugin hook patched for libadwaita"
	echo
	return 0
}

#
# Copy Desktop Integration Files
#

copy_desktop_files() {
	log_info "=== Copying Desktop Integration Files ==="
	echo

	# Desktop file
	DESKTOP_FILE="$PROJECT_ROOT/data/$APP_ID.desktop"
	if [ -f "$DESKTOP_FILE" ]; then
		cp "$DESKTOP_FILE" "$APPDIR/usr/share/applications/"
		# Also copy to AppDir root (required by linuxdeploy)
		cp "$DESKTOP_FILE" "$APPDIR/"
		log_success "Desktop entry copied"
	else
		log_error "Desktop file not found: $DESKTOP_FILE"
		return 1
	fi

	# SVG icon
	SVG_ICON="$PROJECT_ROOT/icons/$APP_ID.svg"
	if [ -f "$SVG_ICON" ]; then
		cp "$SVG_ICON" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
		log_success "SVG icon copied"
	else
		log_warning "SVG icon not found: $SVG_ICON"
	fi

	# PNG icon
	PNG_ICON="$PROJECT_ROOT/icons/$APP_ID.png"
	if [ -f "$PNG_ICON" ]; then
		cp "$PNG_ICON" "$APPDIR/usr/share/icons/hicolor/128x128/apps/"
		# Also copy to AppDir root for linuxdeploy
		cp "$PNG_ICON" "$APPDIR/${APP_ID}.png"
		log_success "PNG icon copied"
	else
		log_warning "PNG icon not found: $PNG_ICON"
		# Try SVG as fallback for root icon
		if [ -f "$SVG_ICON" ]; then
			cp "$SVG_ICON" "$APPDIR/${APP_ID}.svg"
		fi
	fi

	# AppStream metainfo
	METAINFO="$PROJECT_ROOT/data/$APP_ID.metainfo.xml"
	if [ -f "$METAINFO" ]; then
		cp "$METAINFO" "$APPDIR/usr/share/metainfo/"
		log_success "AppStream metainfo copied"
	else
		log_warning "Metainfo not found: $METAINFO"
	fi

	echo
	log_success "Desktop integration files copied"
	echo
	return 0
}

#
# Create AppRun Entry Script
#

create_apprun() {
	log_info "=== Creating AppRun Entry Script ==="
	echo

	PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

	cat >"$APPDIR/AppRun" <<APPRUN
#!/bin/bash
# ClamUI AppImage entry point

# Determine the AppImage mount directory
HERE="\$(dirname "\$(readlink -f "\$0")")"
export APPDIR="\$HERE"

# GIO desktop launcher
export GIO_LAUNCH_DESKTOP="\$HERE/usr/libexec/gio-launch-desktop"

# Python environment
export PYTHONHOME="\$HERE/usr"
export PYTHONPATH="\$HERE/usr/lib/python${PYTHON_VER}/site-packages:\$HERE/usr/lib/python${PYTHON_VER}:\$PYTHONPATH"
export PYTHONDONTWRITEBYTECODE=1

# GObject Introspection typelibs
export GI_TYPELIB_PATH="\$HERE/usr/lib/girepository-1.0:\${GI_TYPELIB_PATH:-}"

# Shared libraries
export LD_LIBRARY_PATH="\$HERE/usr/lib:\$HERE/usr/lib/x86_64-linux-gnu:\${LD_LIBRARY_PATH:-}"

# GTK4 settings
export GTK_PATH="\$HERE/usr/lib/gtk-4.0"
export GTK_EXE_PREFIX="\$HERE/usr"
export GTK_DATA_PREFIX="\$HERE/usr"

# GSettings schemas
export GSETTINGS_SCHEMA_DIR="\$HERE/usr/share/glib-2.0/schemas:\${GSETTINGS_SCHEMA_DIR:-}"

# GDK pixbuf loaders
if [ -d "\$HERE/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders" ]; then
	export GDK_PIXBUF_MODULE_FILE="\$HERE/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"
	export GDK_PIXBUF_MODULEDIR="\$HERE/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders"
elif [ -d "\$HERE/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0" ]; then
	export GDK_PIXBUF_MODULE_FILE="\$HERE/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache"
	export GDK_PIXBUF_MODULEDIR="\$HERE/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders"
fi

# XDG data dirs for icons and desktop integration
export XDG_DATA_DIRS="\$HERE/usr/share:\${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

# Launch ClamUI
exec "\$HERE/usr/bin/python3" -c "from src.main import main; main()" "\$@"
APPRUN

	chmod 755 "$APPDIR/AppRun"

	log_success "AppRun entry script created"
	echo
	return 0
}

#
# Run linuxdeploy
#

run_linuxdeploy() {
	log_info "=== Running linuxdeploy ==="
	echo

	LINUXDEPLOY="$TOOLS_DIR/linuxdeploy-x86_64.AppImage"
	GTK_PLUGIN="$TOOLS_DIR/linuxdeploy-plugin-gtk.sh"

	# Add GTK plugin to PATH so linuxdeploy can find it
	export PATH="$TOOLS_DIR:$PATH"

	# Set GTK version for the plugin
	export DEPLOY_GTK_VERSION=4

	log_info "Running linuxdeploy with GTK4 plugin..."
	log_info "This resolves shared library dependencies and prepares the AppDir."
	echo

	# Add bundled .libs directories to LD_LIBRARY_PATH so linuxdeploy can
	# resolve cross-references between hash-mangled shared libraries
	# (e.g., pillow.libs/libharfbuzz-*.so depends on pillow.libs/libfreetype-*.so)
	if [ -n "$EXTRA_LIB_PATHS" ]; then
		export LD_LIBRARY_PATH="${EXTRA_LIB_PATHS}${LD_LIBRARY_PATH:+:}${LD_LIBRARY_PATH:-}"
		log_info "Added bundled lib paths to LD_LIBRARY_PATH"
	fi

	# Run linuxdeploy WITHOUT --output to just prepare the AppDir
	# We'll create the AppImage separately after patching the GTK hook
	"$LINUXDEPLOY" \
		--appimage-extract-and-run \
		--appdir "$APPDIR" \
		--desktop-file "$APPDIR/$APP_ID.desktop" \
		--plugin gtk

	echo
	log_success "AppDir prepared by linuxdeploy"
	return 0
}

#
# Create AppImage
#
# Run appimagetool to create the final AppImage from the prepared AppDir.
# This is done separately from linuxdeploy so we can patch the GTK hook first.
#

create_appimage() {
	log_info "=== Creating AppImage ==="
	echo

	APPIMAGETOOL="$TOOLS_DIR/appimagetool-x86_64.AppImage"
	APPIMAGE_OUTPUT="$PROJECT_ROOT/$APPIMAGE_FILENAME"

	# Remove existing output
	if [ -f "$APPIMAGE_OUTPUT" ]; then
		log_warning "Removing existing AppImage: $APPIMAGE_FILENAME"
		rm -f "$APPIMAGE_OUTPUT"
	fi

	log_info "Running appimagetool..."

	# Build appimagetool arguments
	# --appimage-extract-and-run avoids FUSE requirement during build
	APPIMAGETOOL_ARGS=(
		--appimage-extract-and-run
	)

	# Embed update information for delta updates (AppImageUpdate/zsync2)
	# Set UPDATE_INFORMATION env var to enable. For GitHub releases:
	#   UPDATE_INFORMATION="gh-releases-zsync|owner|repo|latest|Pattern-*-x86_64.AppImage.zsync"
	if [ -n "${UPDATE_INFORMATION:-}" ]; then
		log_info "Embedding update information: $UPDATE_INFORMATION"
		APPIMAGETOOL_ARGS+=(-u "$UPDATE_INFORMATION")
	else
		log_info "No UPDATE_INFORMATION set, skipping delta update support"
	fi

	"$APPIMAGETOOL" \
		"${APPIMAGETOOL_ARGS[@]}" \
		"$APPDIR" \
		"$APPIMAGE_OUTPUT"

	echo

	# Verify output
	if [ ! -f "$APPIMAGE_OUTPUT" ]; then
		log_error "AppImage was not created at expected path: $APPIMAGE_OUTPUT"
		return 1
	fi

	chmod +x "$APPIMAGE_OUTPUT"
	log_success "AppImage created: $APPIMAGE_FILENAME"

	# Check for generated zsync file (created when update info is embedded)
	ZSYNC_FILE="${APPIMAGE_OUTPUT}.zsync"
	if [ -f "$ZSYNC_FILE" ]; then
		log_success "zsync file created: ${APPIMAGE_FILENAME}.zsync"
	elif [ -n "${UPDATE_INFORMATION:-}" ]; then
		log_warning "Update information was set but no .zsync file was generated"
		log_warning "Delta updates will not work without the .zsync file"
	fi

	return 0
}

#
# Cleanup
#

cleanup() {
	log_info "Cleaning up build directories..."

	if [ -d "$BUILD_DIR" ]; then
		rm -rf "$BUILD_DIR"
		log_success "Build directory cleaned up"
	fi

	# Keep tools directory for caching (can be cleaned manually)
	if [ -d "$TOOLS_DIR" ]; then
		log_info "Build tools cached in: $TOOLS_DIR"
		log_info "Remove manually if not needed: rm -rf $TOOLS_DIR"
	fi
}

#
# Summary
#

print_summary() {
	echo
	log_info "========================================"
	log_success "   Build Complete!"
	log_info "========================================"
	echo
	log_info "AppImage created: $APPIMAGE_FILENAME"
	log_info "Location: $PROJECT_ROOT/$APPIMAGE_FILENAME"
	echo

	if [ -f "$PROJECT_ROOT/$APPIMAGE_FILENAME" ]; then
		APPIMAGE_SIZE=$(du -h "$PROJECT_ROOT/$APPIMAGE_FILENAME" | cut -f1)
		log_info "Size: $APPIMAGE_SIZE"
		echo
	fi

	# Report zsync file for delta updates
	ZSYNC_FILE="$PROJECT_ROOT/${APPIMAGE_FILENAME}.zsync"
	if [ -f "$ZSYNC_FILE" ]; then
		ZSYNC_SIZE=$(du -h "$ZSYNC_FILE" | cut -f1)
		log_info "zsync file: ${APPIMAGE_FILENAME}.zsync ($ZSYNC_SIZE)"
		log_info "Delta updates enabled (AppImageUpdate compatible)"
		echo
	fi

	log_info "To run the AppImage:"
	log_info "  ./$APPIMAGE_FILENAME"
	echo
	log_info "Note: ClamAV must be installed on the system for scanning to work."
	echo
}

#
# Main Execution
#

main() {
	echo
	log_info "=== ClamUI AppImage Builder ==="
	echo

	# Check prerequisites
	check_prerequisites

	# Validate imports
	if ! check_absolute_imports; then
		log_error "Import validation failed. Fix the imports before building."
		exit 1
	fi

	# Extract version
	log_info "=== Extracting Package Version ==="
	echo
	if ! extract_version; then
		log_error "Version extraction failed."
		exit 1
	fi
	echo

	# Download build tools
	if ! download_tools; then
		log_error "Failed to download build tools."
		exit 1
	fi

	# Create AppDir structure
	if ! create_appdir; then
		log_error "Failed to create AppDir."
		cleanup
		exit 1
	fi

	# Bundle Python interpreter
	if ! bundle_python; then
		log_error "Failed to bundle Python interpreter."
		cleanup
		exit 1
	fi

	# Bundle system Python packages (PyGObject, pycairo)
	if ! bundle_system_packages; then
		log_error "Failed to bundle system Python packages."
		cleanup
		exit 1
	fi

	# Install pip dependencies
	if ! install_pip_deps; then
		log_error "Failed to install Python dependencies."
		cleanup
		exit 1
	fi

	# Copy ClamUI source
	if ! copy_clamui_source; then
		log_error "Failed to copy ClamUI source."
		cleanup
		exit 1
	fi

	# Bundle GI typelibs
	if ! bundle_typelibs; then
		log_error "Failed to bundle GI typelibs."
		cleanup
		exit 1
	fi

	# Bundle GI-loaded shared libraries (PyGObject loads these dynamically,
	# so linuxdeploy can't discover them by tracing the python3 binary)
	if ! bundle_gi_libraries; then
		log_error "Failed to bundle GI-loaded libraries."
		cleanup
		exit 1
	fi

	# Bundle the GIO helper that Gtk.show_uri() launches out of process
	if ! bundle_gio_launch_desktop; then
		log_error "Failed to bundle GIO desktop launcher."
		cleanup
		exit 1
	fi

	# Bundle Adwaita icon theme for proper symbolic icon rendering
	if ! bundle_adwaita_icons; then
		log_warning "Failed to bundle Adwaita icons (non-fatal)"
	fi

	# Bundle locale files for i18n
	if ! bundle_locales; then
		log_warning "Failed to bundle locale files (non-fatal)"
	fi

	# Copy desktop integration files
	if ! copy_desktop_files; then
		log_error "Failed to copy desktop files."
		cleanup
		exit 1
	fi

	# Create AppRun entry script
	if ! create_apprun; then
		log_error "Failed to create AppRun script."
		cleanup
		exit 1
	fi

	# Run linuxdeploy to resolve shared libs and prepare AppDir
	if ! run_linuxdeploy; then
		log_error "Failed to prepare AppDir with linuxdeploy."
		cleanup
		exit 1
	fi

	# Patch GTK plugin hook for libadwaita compatibility
	# This must run AFTER linuxdeploy (which generates the hook) but BEFORE
	# creating the AppImage
	if ! patch_gtk_plugin_hook; then
		log_warning "Failed to patch GTK plugin hook (non-fatal)"
	fi

	# Create the final AppImage
	if ! create_appimage; then
		log_error "Failed to create AppImage."
		cleanup
		exit 1
	fi

	# Cleanup build directory
	echo
	cleanup

	# Print summary
	print_summary

	log_success "Done!"
}

main "$@"
