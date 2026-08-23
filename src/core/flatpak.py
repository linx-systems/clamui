# ClamUI Flatpak Integration
"""
Flatpak detection and portal path resolution utilities.

This module provides functions for:
- Detecting if ClamUI is running inside a Flatpak sandbox
- Wrapping host commands to bridge the sandbox boundary
- Resolving Flatpak document portal paths to user-friendly display paths
- Finding host binaries when running in Flatpak
"""

import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Legacy sandbox database directory used by older Flatpak builds.
_FLATPAK_DATABASE_DIR: Path | None = None

# Flatpak detection cache (None = not checked, True/False = result)
_flatpak_detected: bool | None = None
_flatpak_lock = threading.Lock()


def is_flatpak() -> bool:
    """
    Detect if running inside a Flatpak sandbox.

    Uses the presence of /.flatpak-info file as the detection method,
    which is the standard way to detect Flatpak environment.

    The result is cached after the first check for performance.
    Thread-safe via lock.

    Returns:
        True if running inside Flatpak sandbox, False otherwise
    """
    global _flatpak_detected

    with _flatpak_lock:
        if _flatpak_detected is None:
            _flatpak_detected = os.path.exists("/.flatpak-info")
        return _flatpak_detected


def get_clean_env() -> dict[str, str]:
    """Return a clean environment for subprocess calls to host system binaries.

    AppImage's AppRun injects bundled-runtime variables so ClamUI's own bundled
    interpreter and libraries are used. Those must NOT leak into the host helpers
    we spawn (clamscan, freshclam, systemctl, and host Python scripts such as
    Fedora's ``firewall-cmd``), or they break:

    - ``LD_LIBRARY_PATH``/``LD_PRELOAD``: force bundled shared libs, causing
      ABI/version conflicts against host binaries.
    - ``PYTHONHOME``/``PYTHONPATH``: point the interpreter at the AppImage tree,
      so a host Python script's interpreter cannot bootstrap the host stdlib
      ("No module named 'encodings'") or import host site-packages -> non-zero
      exit. This made the Security Audit misreport firewalld as "not running"
      (GitHub issue #155).
    - ``GI_TYPELIB_PATH``: the GObject-introspection analog of LD_LIBRARY_PATH;
      a host tool that ``import gi`` (firewall-cmd does) would otherwise load the
      bundled typelibs against host GLib -> version mismatch.
    - ``GTK_PATH``/``GTK_EXE_PREFIX``/``GTK_DATA_PREFIX``/``GSETTINGS_SCHEMA_DIR``/
      ``GDK_PIXBUF_MODULE_FILE``/``GDK_PIXBUF_MODULEDIR``: point host GTK apps
      (gufw, firewall-config) at the AppImage's bundled GTK modules, compiled
      GSettings schemas, and pixbuf loaders -> module ABI mismatches or
      missing-schema aborts.

    ``XDG_DATA_DIRS`` is intentionally NOT stripped: AppRun only prepends the
    bundled share dir and host tools still need the host entries it contains.

    Every caller spawns native HOST binaries, never ClamUI's bundled Python, so
    stripping these is always safe. Popping an unset var is a no-op.
    """
    env = os.environ.copy()
    # Strip AppImage-injected runtime overrides that break host helpers: library
    # paths (ABI conflicts), Python home/path (host script bootstrap), the
    # introspection typelib path (gi version mismatch), and GTK module/schema/
    # pixbuf overrides (host GTK apps). See GitHub issue #155.
    for var in (
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "GI_TYPELIB_PATH",
        "GTK_PATH",
        "GTK_EXE_PREFIX",
        "GTK_DATA_PREFIX",
        "GSETTINGS_SCHEMA_DIR",
        "GDK_PIXBUF_MODULE_FILE",
        "GDK_PIXBUF_MODULEDIR",
    ):
        env.pop(var, None)
    # Remove AppImage-specific variables that may affect library resolution
    for var in list(env.keys()):
        if var.startswith(("APPIMAGE", "APPDIR")):
            env.pop(var, None)
    return env


def get_clamav_database_dir() -> Path | None:
    """
    Get the legacy sandbox ClamAV database directory for Flatpak installations.

    Current Flatpak runtime paths use host ClamAV and host virus databases.
    This helper remains for compatibility with older sandbox-database helpers.

    Returns:
        Legacy sandbox database path in Flatpak, None for native installations
    """
    global _FLATPAK_DATABASE_DIR

    if not is_flatpak():
        return None

    if _FLATPAK_DATABASE_DIR is not None:
        return _FLATPAK_DATABASE_DIR

    # Use XDG_DATA_HOME which maps to ~/.var/app/<app-id>/data/ in Flatpak
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        _FLATPAK_DATABASE_DIR = Path(data_home) / "clamav"
    else:
        # Fallback to standard location
        _FLATPAK_DATABASE_DIR = Path.home() / ".local" / "share" / "clamav"

    return _FLATPAK_DATABASE_DIR


def ensure_clamav_database_dir() -> Path | None:
    """
    Ensure the legacy sandbox ClamAV database directory exists.

    Current Flatpak builds do not use this path for scanning or updates.

    Returns:
        Path to the created/existing legacy directory, None for native installations
    """
    db_dir = get_clamav_database_dir()
    if db_dir is None:
        return None

    try:
        db_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("ClamAV database directory ensured: %s", db_dir)
        return db_dir
    except Exception as e:
        logger.error("Failed to create ClamAV database directory: %s", e)
        return None


def get_freshclam_config_path() -> Path | None:
    """
    Get the legacy sandbox freshclam.conf path for Flatpak installations.

    Current Flatpak builds use host freshclam and host configuration. This
    path is kept for compatibility with older sandbox database helpers.

    Returns:
        Path to the config file in Flatpak, None for native installations
    """
    if not is_flatpak():
        return None

    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "clamav" / "freshclam.conf"
    else:
        return Path.home() / ".config" / "clamav" / "freshclam.conf"


def ensure_freshclam_config() -> Path | None:
    """
    Ensure the legacy sandbox freshclam.conf exists for Flatpak.

    Current Flatpak runtime paths should prefer host freshclam configuration.
    This helper is retained for compatibility with older sandbox database data.

    Returns:
        Path to the config file, None for native installations or on error
    """
    if not is_flatpak():
        logger.debug("Not in Flatpak, skipping freshclam config generation")
        return None

    config_path = get_freshclam_config_path()
    if config_path is None:
        logger.error("Failed to get freshclam config path")
        return None

    # If config file already exists, don't regenerate it (preserve user settings)
    if config_path.exists():
        logger.debug("Freshclam config already exists at: %s, skipping generation", config_path)
        return config_path

    logger.info("Generating freshclam config at: %s", config_path)

    # Ensure database directory exists first
    db_dir = ensure_clamav_database_dir()
    if db_dir is None:
        logger.error("Failed to ensure database directory")
        return None

    logger.info("Using database directory: %s", db_dir)

    # Ensure config directory exists
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Config directory created: %s", config_path.parent)
    except Exception as e:
        logger.error("Failed to create ClamAV config directory %s: %s", config_path.parent, e)
        return None

    # Generate the config file with the correct database directory
    config_content = f"""# ClamUI Flatpak freshclam configuration
# Auto-generated - do not edit manually

# Database directory (user-writable location in Flatpak)
DatabaseDirectory {db_dir}

# Database mirror - official ClamAV database server
DatabaseMirror database.clamav.net

# Number of database checks per day
Checks 12

# Connect timeout in seconds
ConnectTimeout 30

# Receive timeout in seconds
ReceiveTimeout 60

# Disable test databases
TestDatabases no

# Log verbosely
LogVerbose yes

# Run in foreground (for Flatpak)
Foreground yes
"""

    try:
        config_path.write_text(config_content)
        logger.info("Successfully generated freshclam config at: %s", config_path)
        # Verify file exists
        if config_path.exists():
            logger.debug("Config file verified to exist")
            return config_path
        else:
            logger.error("Config file does not exist after write!")
            return None
    except Exception as e:
        logger.error("Failed to write freshclam config to %s: %s", config_path, e)
        return None


def wrap_host_command(command: list[str], force_host: bool = False) -> list[str]:
    """
    Wrap a command with flatpak-spawn --host if needed in Flatpak.

    This helper is for commands that must run on the host. ClamAV is not
    bundled in the Flatpak, so clamscan, clamdscan, freshclam, systemctl, and
    similar tools always cross the sandbox boundary.

    Args:
        command: The command to wrap as a list of strings
                 (e.g., ['clamscan', '--version'])
        force_host: Kept for backwards-compatible call sites. Host execution is
                    already the only Flatpak behavior.

    Returns:
        The command, wrapped for host execution if running in Flatpak

    Example:
        >>> wrap_host_command(['clamscan', '--version'])
        ['clamscan', '--version']  # When not in Flatpak

        >>> wrap_host_command(['clamscan', '--version'])
        ['flatpak-spawn', '--host', 'clamscan', '--version']  # Host binary in Flatpak

        >>> wrap_host_command(['clamdscan', '--ping'], force_host=True)
        ['flatpak-spawn', '--host', 'clamdscan', '--ping']  # Forced host execution
    """
    if not command:
        return command

    if is_flatpak():
        if command[:2] == ["flatpak-spawn", "--host"]:
            return list(command)
        return ["flatpak-spawn", "--host"] + list(command)

    return list(command)


def get_xdg_user_dir(dir_type: str) -> str | None:
    """
    Get the XDG user directory path for a given type.

    Uses xdg-user-dir command to get localized paths (e.g., "Dokumente"
    for Documents in German locale).

    Args:
        dir_type: XDG directory type (DOWNLOAD, DOCUMENTS, DESKTOP,
                  MUSIC, PICTURES, VIDEOS, TEMPLATES, PUBLICSHARE)

    Returns:
        Absolute path to the directory, or None if lookup fails

    Example:
        >>> get_xdg_user_dir("DOWNLOAD")
        '/home/user/Downloads'  # or '/home/user/Téléchargements' in French
    """
    valid_types = {
        "DOWNLOAD",
        "DOCUMENTS",
        "DESKTOP",
        "MUSIC",
        "PICTURES",
        "VIDEOS",
        "TEMPLATES",
        "PUBLICSHARE",
    }

    if dir_type not in valid_types:
        return None

    try:
        cmd = wrap_host_command(["xdg-user-dir", dir_type])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            env=get_clean_env(),
        )
        resolved = result.stdout.strip()
        if result.returncode == 0 and resolved:
            # xdg-user-dir prints $HOME when the requested user dir is not
            # configured. $HOME is never a valid user *subdirectory* (Downloads,
            # Documents, etc. are always nested under home), so treat a bare
            # $HOME result as a lookup miss. This stops callers such as the
            # Quick Scan default from targeting the entire home directory.
            home = os.path.expanduser("~")
            if os.path.normpath(resolved) != os.path.normpath(home):
                return resolved
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        logger.debug("Failed to resolve XDG user directory for %s", dir_type, exc_info=True)

    return None


def which_host_command(binary: str) -> str | None:
    """
    Find a binary path on the host system.

    When running inside a Flatpak sandbox, this uses
    ``flatpak-spawn --host which``. ClamAV tools are intentionally required on
    the host and are not resolved from /app/bin.

    Args:
        binary: The name of the binary to find (e.g., 'clamscan')

    Returns:
        The full path to the binary if found, None otherwise
    """
    if is_flatpak():
        try:
            result = subprocess.run(
                ["flatpak-spawn", "--host", "which", binary],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            logger.debug("Failed to find binary '%s' on host: %s", binary, e)
            return None
    return shutil.which(binary)


def _resolve_portal_path_via_xattr(portal_path: str) -> str | None:
    """
    Try to resolve a Flatpak portal path using extended attributes.

    The document portal FUSE filesystem may expose the original path
    through extended attributes.

    Args:
        portal_path: A Flatpak document portal path

    Returns:
        The real filesystem path if resolution succeeds, None otherwise.
    """
    try:
        import xattr

        # The document portal might store the real path in an xattr
        attrs_to_try = [
            "user.document-portal.path",
            "user.xdg.origin.path",
            "trusted.overlay.origin",
        ]
        for attr_name in attrs_to_try:
            try:
                value = xattr.getxattr(portal_path, attr_name)
                if value:
                    return value.decode("utf-8").rstrip("\x00")
            except (OSError, KeyError):
                continue
    except ImportError:
        logger.debug("xattr module not available for portal path resolution")
    except Exception as e:
        logger.debug("Failed to resolve portal path via xattr: %s", e)

    return None


def _resolve_portal_path_via_gio(portal_path: str) -> str | None:
    """
    Try to resolve a Flatpak portal path using GIO file attributes.

    The document portal may expose the original path through GIO attributes.

    Args:
        portal_path: A Flatpak document portal path

    Returns:
        The real filesystem path if resolution succeeds, None otherwise.
    """
    try:
        from gi.repository import Gio

        gfile = Gio.File.new_for_path(portal_path)

        # Try to get the target URI which might point to the real location
        try:
            info = gfile.query_info(
                "standard::target-uri,standard::symlink-target,xattr::*",
                Gio.FileQueryInfoFlags.NONE,
                None,
            )
            target_uri = info.get_attribute_string("standard::target-uri")
            if target_uri and target_uri.startswith("file://"):
                return target_uri[7:]  # Strip file:// prefix

            symlink_target = info.get_attribute_string("standard::symlink-target")
            if symlink_target and not symlink_target.startswith("/run/"):
                return symlink_target

            # Try custom xattr via GIO
            xattr_path = info.get_attribute_string("xattr::document-portal-path")
            if xattr_path:
                return xattr_path
        except Exception as e:
            logger.debug("GIO file info query failed: %s", e)

    except Exception as e:
        logger.debug("Failed to resolve portal path via GIO: %s", e)

    return None


def _resolve_portal_path_via_dbus(portal_path: str) -> str | None:
    """
    Try to resolve a Flatpak portal path to its real location via D-Bus.

    Queries the document portal's Info() method to get the original host path.
    This is a best-effort resolution - it may not always succeed.

    Args:
        portal_path: A Flatpak document portal path like:
            - /run/user/1000/doc/<hash>/...
            - /run/flatpak/doc/<hash>/...

    Returns:
        The real filesystem path if resolution succeeds, None otherwise.
    """
    # Match both /run/user/<uid>/doc/ and /run/flatpak/doc/ patterns
    match = re.match(r"/run/(?:user/\d+|flatpak)/doc/([a-f0-9]+)/(.+)", portal_path)
    if not match:
        return None

    doc_id = match.group(1)

    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # Info method returns: (path ay, apps a{sas})
        # path is a byte array containing the host filesystem path
        result = bus.call_sync(
            "org.freedesktop.portal.Documents",
            "/org/freedesktop/portal/documents",
            "org.freedesktop.portal.Documents",
            "Info",
            GLib.Variant("(s)", (doc_id,)),
            GLib.VariantType("(aya{sas})"),
            Gio.DBusCallFlags.NONE,
            1000,  # 1 second timeout
            None,
        )
        unpacked = result.unpack()
        # First element is the path as byte array
        path_bytes = unpacked[0]
        if path_bytes:
            # Convert byte array to string, strip null terminator
            if isinstance(path_bytes, bytes):
                host_path = path_bytes.rstrip(b"\x00").decode("utf-8")
            else:
                # It's a list of integers (byte values)
                host_path = bytes(path_bytes).rstrip(b"\x00").decode("utf-8")

            if host_path:
                return host_path
    except Exception as e:
        logger.debug("D-Bus portal path resolution failed: %s", e)

    return None


def format_flatpak_portal_path(path: str) -> str:
    """
    Convert Flatpak document portal paths to user-friendly display paths.

    In Flatpak, files selected via the file picker are exposed through the
    document portal at paths like:
        - /run/user/1000/doc/<hash>/<path>
        - /run/flatpak/doc/<hash>/<path>
    This function converts them to readable paths.

    Examples:
        /run/user/1000/doc/bceb31dc/Downloads/file.txt -> ~/Downloads/file.txt
        /run/flatpak/doc/abc123/home/user/Docs/f.txt -> ~/Docs/f.txt
        /run/flatpak/doc/abc123/media/data/nextcloud -> /media/data/nextcloud

    Args:
        path: The filesystem path to check and potentially convert

    Returns:
        A user-friendly path if it's a portal path, otherwise the original path
    """
    # Match both /run/user/<uid>/doc/ and /run/flatpak/doc/ patterns
    match = re.match(r"/run/(?:user/\d+|flatpak)/doc/[a-f0-9]+/(.+)", path)
    if match:
        relative_path = match.group(1)

        # If it starts with home/username, strip that part and use ~/
        home_match = re.match(r"home/[^/]+/(.+)", relative_path)
        if home_match:
            return f"~/{home_match.group(1)}"

        # Get the first path component
        first_component = relative_path.split("/")[0]

        # Known home subdirectories - prefix with ~/
        home_subdirs = (
            "Downloads",
            "Documents",
            "Desktop",
            "Pictures",
            "Videos",
            "Music",
            ".config",
            ".local",
            ".cache",
        )
        if first_component in home_subdirs:
            return f"~/{relative_path}"

        # Absolute path indicators - prefix with /
        abs_indicators = ("media", "mnt", "run", "tmp", "opt", "var", "usr", "srv")
        if first_component in abs_indicators:
            return f"/{relative_path}"

        # Unknown location - try multiple resolution methods

        # Method 1: Try extended attributes (might work from inside sandbox)
        resolved = _resolve_portal_path_via_xattr(path)

        # Method 2: Try GIO file attributes
        if not resolved:
            resolved = _resolve_portal_path_via_gio(path)

        # Method 3: Try D-Bus resolution
        if not resolved:
            resolved = _resolve_portal_path_via_dbus(path)

        if resolved:
            # Format the resolved path with ~ for home directory
            try:
                home = str(Path.home())
                if resolved.startswith(home):
                    return "~" + resolved[len(home) :]
            except Exception as e:
                logger.debug("Failed to get home directory for path formatting: %s", e)
            return resolved

        # All resolution methods failed - show just the name with indicator
        # This is friendlier than the raw portal path
        return f"[Portal] {relative_path}"

    return path


def is_portal_path(path: str) -> bool:
    """
    Check if a path is a Flatpak document portal path.

    Portal paths are created by the Flatpak document portal when files are
    selected through a file picker inside the sandbox.

    Args:
        path: Filesystem path to check

    Returns:
        True if the path is a document portal path, False otherwise.
    """
    return bool(re.match(r"/run/(?:user/\d+|flatpak)/doc/", path))


def resolve_portal_path(portal_path: str) -> str | None:
    """
    Resolve a Flatpak document portal path to its real host filesystem path.

    Tries multiple resolution methods in order:
    1. Extended attributes (xattr)
    2. GIO file attributes
    3. D-Bus document portal query

    Args:
        portal_path: A Flatpak document portal path

    Returns:
        The resolved host path, or None if resolution fails.
    """
    if not is_portal_path(portal_path):
        return None

    resolved = _resolve_portal_path_via_xattr(portal_path)
    if not resolved:
        resolved = _resolve_portal_path_via_gio(portal_path)
    if not resolved:
        resolved = _resolve_portal_path_via_dbus(portal_path)

    return resolved


def read_host_file(file_path: str, timeout: int = 10) -> tuple[str | None, str | None]:
    """
    Read a file, using flatpak-spawn to cross the sandbox boundary when needed.

    In Flatpak, system paths (e.g. /etc/clamd.d/scan.conf) are not accessible
    inside the sandbox. This function uses `flatpak-spawn --host cat` to read
    such files from the host filesystem.

    Outside Flatpak, falls back to direct file I/O.

    Args:
        file_path: Path to the file to read
        timeout: Timeout in seconds for the subprocess call

    Returns:
        Tuple of (content, error):
        - (content_string, None) on success
        - (None, error_message) on failure
    """
    if is_flatpak():
        try:
            result = subprocess.run(
                ["flatpak-spawn", "--host", "cat", file_path],
                capture_output=True,
                text=False,
                timeout=timeout,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                return (None, f"Cannot read {file_path}: {stderr}")

            # Decode with UTF-8, fall back to latin-1
            try:
                content = result.stdout.decode("utf-8")
            except UnicodeDecodeError:
                content = result.stdout.decode("latin-1")

            return (content, None)
        except subprocess.TimeoutExpired:
            return (None, f"Timeout reading {file_path}")
        except FileNotFoundError:
            return (None, "flatpak-spawn not available")
        except Exception as e:
            return (None, f"Error reading {file_path}: {e!s}")
    else:
        # Native: direct file I/O
        try:
            with open(file_path, encoding="utf-8") as f:
                return (f.read(), None)
        except UnicodeDecodeError:
            try:
                with open(file_path, encoding="latin-1") as f:
                    return (f.read(), None)
            except Exception as e:
                return (None, f"Error reading {file_path}: {e!s}")
        except PermissionError:
            return (None, f"Permission denied: Cannot read {file_path}")
        except FileNotFoundError:
            return (None, f"File not found: {file_path}")
        except OSError as e:
            return (None, f"Error reading {file_path}: {e!s}")
