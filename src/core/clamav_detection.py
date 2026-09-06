# ClamUI ClamAV Detection
"""
ClamAV installation detection and daemon connectivity utilities.

This module provides functions for:
- Checking if ClamAV binaries (clamscan, freshclam, clamdscan) are installed
- Getting paths to ClamAV executables
- Detecting clamd socket locations
- Testing clamd daemon connectivity
"""

import logging
import os
import subprocess
from pathlib import Path

from .flatpak import (
    get_clean_env,
    is_flatpak,
    which_host_command,
    wrap_host_command,
)
from .i18n import _
from .install_commands import InstallTarget, recommend_install_command

logger = logging.getLogger(__name__)

# Database file extensions that ClamAV uses
_DATABASE_EXTENSIONS = {".cvd", ".cld", ".cud"}
_DEFAULT_DATABASE_DIRS = ("/var/lib/clamav", "/usr/local/share/clamav")


def systemd_unit_exists(unit_name: str) -> bool:
    """
    Check whether a systemd unit is actually known to systemd.

    `systemctl is-active` prints "inactive" for units systemd has never
    heard of, so callers probing multiple candidate unit names cannot use
    its output alone to distinguish "installed but stopped" from
    "not installed". LoadState is "loaded" only for real units.

    Args:
        unit_name: Full unit name (e.g. "clamav-freshclam.service")

    Returns:
        True if systemd reports the unit as loaded, False otherwise
    """
    try:
        result = subprocess.run(
            wrap_host_command(["systemctl", "show", "-p", "LoadState", "--value", unit_name]),
            capture_output=True,
            text=True,
            timeout=5,
            env=get_clean_env(),
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        logger.debug("systemctl show failed for %s", unit_name, exc_info=True)
        return False
    return result.returncode == 0 and result.stdout.strip() == "loaded"


def _clamav_not_installed_message() -> str:
    """Build the missing-clamscan message for the detected distribution."""
    command = recommend_install_command(InstallTarget.CLAMAV)
    if command is None:
        return _("ClamAV is not installed. Install the ClamAV package for your distribution.")
    return _("ClamAV is not installed. Please install it with: {command}").format(command=command)


def _freshclam_not_installed_message() -> str:
    """Build the missing-freshclam message for the detected distribution."""
    command = recommend_install_command(InstallTarget.FRESHCLAM)
    if command is None:
        return _(
            "freshclam is not installed. Install the ClamAV database updater package "
            "for your distribution."
        )
    return _("freshclam is not installed. Please install it with: {command}").format(
        command=command
    )


def _clamdscan_not_installed_message() -> str:
    """Build the missing-clamdscan message for the detected distribution."""
    command = recommend_install_command(InstallTarget.CLAMD)
    if command is None:
        return _(
            "clamdscan is not installed. Install the ClamAV daemon package for your distribution."
        )
    return _("clamdscan is not installed. Please install it with: {command}").format(
        command=command
    )


def check_clamav_installed() -> tuple[bool, str | None]:
    """
    Check if ClamAV (clamscan) is installed and accessible.

    Returns:
        Tuple of (is_installed, version_or_error):
        - (True, version_string) if ClamAV is installed
        - (False, error_message) if ClamAV is not found or inaccessible
    """
    # First check if clamscan exists in PATH (checking host if in Flatpak)
    clamscan_path = which_host_command("clamscan")

    if clamscan_path is None:
        return (False, _clamav_not_installed_message())

    # Try to get version to verify it's working
    try:
        result = subprocess.run(
            wrap_host_command(["clamscan", "--version"]),
            capture_output=True,
            text=True,
            timeout=10,
            env=get_clean_env(),
        )

        if result.returncode == 0:
            version = result.stdout.strip()
            return (True, version)
        else:
            return (
                False,
                _("ClamAV found but returned error: {error}").format(error=result.stderr.strip()),
            )

    except subprocess.TimeoutExpired:
        return (False, _("ClamAV check timed out"))
    except FileNotFoundError:
        return (False, _("ClamAV executable not found"))
    except PermissionError:
        return (False, _("Permission denied when accessing ClamAV"))
    except Exception as e:
        return (False, _("Error checking ClamAV: {error}").format(error=str(e)))


def check_freshclam_installed() -> tuple[bool, str | None]:
    """
    Check if freshclam (ClamAV database updater) is installed and accessible.

    Returns:
        Tuple of (is_installed, version_or_error):
        - (True, version_string) if freshclam is installed
        - (False, error_message) if freshclam is not found or inaccessible
    """
    # First check if freshclam exists in PATH (checking host if in Flatpak)
    freshclam_path = which_host_command("freshclam")

    if freshclam_path is None:
        return (False, _freshclam_not_installed_message())

    cmd = ["freshclam", "--version"]

    # Try to get version to verify it's working
    try:
        result = subprocess.run(
            wrap_host_command(cmd),
            capture_output=True,
            text=True,
            timeout=10,
            env=get_clean_env(),
        )

        if result.returncode == 0:
            version = result.stdout.strip()
            return (True, version)
        else:
            return (
                False,
                _("freshclam found but returned error: {error}").format(
                    error=result.stderr.strip()
                ),
            )

    except subprocess.TimeoutExpired:
        return (False, _("freshclam check timed out"))
    except FileNotFoundError:
        return (False, _("freshclam executable not found"))
    except PermissionError:
        return (False, _("Permission denied when accessing freshclam"))
    except Exception as e:
        return (False, _("Error checking freshclam: {error}").format(error=str(e)))


def check_clamdscan_installed() -> tuple[bool, str | None]:
    """
    Check if clamdscan (ClamAV daemon scanner) is installed and accessible.

    Returns:
        Tuple of (is_installed, version_or_error):
        - (True, version_string) if clamdscan is installed
        - (False, error_message) if clamdscan is not found or inaccessible
    """
    # First check if clamdscan exists in PATH (checking host if in Flatpak)
    clamdscan_path = which_host_command("clamdscan")

    if clamdscan_path is None:
        return (False, _clamdscan_not_installed_message())

    # Try to get version to verify it's working
    # Use force_host=True because clamdscan must communicate with the host clamd daemon.
    try:
        result = subprocess.run(
            wrap_host_command(["clamdscan", "--version"], force_host=True),
            capture_output=True,
            text=True,
            timeout=10,
            env=get_clean_env(),
        )

        if result.returncode == 0:
            version = result.stdout.strip()
            return (True, version)
        else:
            error = result.stderr.strip() or result.stdout.strip()
            return (
                False,
                _("clamdscan returned error: {error}").format(error=error),
            )

    except subprocess.TimeoutExpired:
        return (False, _("clamdscan check timed out"))
    except FileNotFoundError:
        return (False, _clamdscan_not_installed_message())
    except PermissionError:
        return (False, _("Permission denied when accessing clamdscan"))
    except Exception as e:
        return (False, _("Error checking clamdscan: {error}").format(error=str(e)))


def _get_configured_clamd_socket_path(config_path: str | None) -> str | None:
    """Read LocalSocket from clamd.conf when an explicit config path is known."""
    if not config_path:
        return None

    try:
        from .clamav_config import parse_config

        config, error = parse_config(config_path)
        if config is None:
            if error:
                logger.debug("Failed to parse clamd config %s: %s", config_path, error)
            return None

        socket_path = config.get_value("LocalSocket")
        if socket_path:
            return socket_path.strip()
    except Exception as e:
        logger.debug("Failed to read LocalSocket from %s: %s", config_path, e)

    return None


def get_clamd_socket_path(config_path: str | None = None) -> str | None:
    """
    Get the clamd socket path by checking common locations.

    Checks the following paths in order:
    - LocalSocket from the provided clamd.conf, if available
    - /var/run/clamav/clamd.ctl (Ubuntu/Debian default)
    - /run/clamav/clamd.ctl (alternative location)
    - /run/clamd.scan/clamd.sock (Fedora/RHEL)
    - /var/run/clamd.scan/clamd.sock (Fedora)

    Returns:
        Socket path if found, None otherwise
    """
    configured_socket = _get_configured_clamd_socket_path(config_path)
    if configured_socket and os.path.exists(configured_socket):
        return configured_socket

    socket_paths = [
        "/var/run/clamav/clamd.ctl",
        "/run/clamav/clamd.ctl",
        "/run/clamd.scan/clamd.sock",
        "/var/run/clamd.scan/clamd.sock",
    ]

    for path in socket_paths:
        if os.path.exists(path):
            return path

    return None


def check_clamd_connection(
    socket_path: str | None = None,
    config_path: str | None = None,
) -> tuple[bool, str | None]:
    """
    Check if clamd is accessible and responding.

    Uses 'clamdscan --ping' to test the connection to the daemon.

    Args:
        socket_path: Optional socket path. If not provided, uses auto-detection.
        config_path: Optional clamd.conf path. When provided, clamdscan is pointed
            at this config so it uses the same LocalSocket or TCPSocket as the daemon.

    Returns:
        Tuple of (is_connected, message):
        - (True, "PONG") if daemon is responding
        - (False, error_message) if daemon is not accessible
    """
    # First check if clamdscan is installed
    is_installed, error = check_clamdscan_installed()
    if not is_installed:
        return (False, error)

    detected_socket = socket_path

    # Check socket exists (if not in Flatpak)
    if not is_flatpak():
        detected_socket = socket_path or get_clamd_socket_path(config_path)
        if detected_socket is None:
            return (False, _("Could not find clamd socket. Is clamav-daemon installed?"))

    resolved_config_path = config_path
    if resolved_config_path is None and detected_socket in {
        "/run/clamd.scan/clamd.sock",
        "/var/run/clamd.scan/clamd.sock",
    }:
        resolved_config_path = detect_clamd_conf_path()

    # Try to ping the daemon (--ping requires a timeout argument in seconds)
    # Use force_host=True because the clamd daemon runs on the host, not in the
    # Flatpak sandbox.
    try:
        cmd = ["clamdscan"]
        if resolved_config_path:
            cmd.extend(["--config-file", resolved_config_path])
        cmd.extend(["--ping", "3"])
        cmd = wrap_host_command(cmd, force_host=True)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, env=get_clean_env()
        )

        if result.returncode == 0 and "PONG" in result.stdout:
            return (True, "PONG")
        else:
            # Check stderr and stdout for error messages
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            if "permission denied" in error_msg.lower():
                if resolved_config_path:
                    return (
                        False,
                        _(
                            "Daemon socket permission denied. Check LocalSocketMode or LocalSocketGroup in {path}: {error}"
                        ).format(path=resolved_config_path, error=error_msg),
                    )
                return (
                    False,
                    _("Daemon socket permission denied: {error}").format(error=error_msg),
                )
            return (False, _("Daemon not responding: {error}").format(error=error_msg))

    except subprocess.TimeoutExpired:
        return (False, _("Connection to clamd timed out"))
    except FileNotFoundError:
        return (False, _("clamdscan executable not found"))
    except Exception as e:
        return (False, _("Error connecting to clamd: {error}").format(error=str(e)))


def get_clamav_path() -> str | None:
    """
    Get the full path to the clamscan executable.

    Returns:
        The full path to clamscan if found, None otherwise
    """
    return which_host_command("clamscan")


def get_freshclam_path() -> str | None:
    """
    Get the full path to the freshclam executable.

    Returns:
        The full path to freshclam if found, None otherwise
    """
    return which_host_command("freshclam")


def _path_contains_database_file(db_dir: Path) -> tuple[bool, str | None]:
    """Check a directly accessible database directory for ClamAV database files."""
    if not db_dir.exists():
        return (False, _("Database directory does not exist: {path}").format(path=db_dir))

    try:
        for file in db_dir.iterdir():
            if file.suffix.lower() in _DATABASE_EXTENSIONS:
                return (True, None)
    except PermissionError:
        return (False, _("Permission denied accessing: {path}").format(path=db_dir))
    except OSError as e:
        return (False, _("Error accessing database: {error}").format(error=e))

    return (False, _("No virus database files found. Please download the database first."))


def _host_path_contains_database_file(db_dir: str) -> tuple[bool, str | None]:
    """Check a host database directory from inside Flatpak."""
    try:
        result = subprocess.run(
            [
                "flatpak-spawn",
                "--host",
                "find",
                db_dir,
                "-maxdepth",
                "1",
                "-type",
                "f",
                "(",
                "-iname",
                "*.cvd",
                "-o",
                "-iname",
                "*.cld",
                "-o",
                "-iname",
                "*.cud",
                ")",
                "-print",
                "-quit",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return (False, _("Timed out checking host database directory: {path}").format(path=db_dir))
    except FileNotFoundError:
        return (False, _("flatpak-spawn not available"))
    except OSError as e:
        return (False, _("Error checking host database directory: {error}").format(error=e))

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        return (
            False,
            _("Error accessing host database directory {path}: {error}").format(
                path=db_dir, error=error
            ),
        )

    if result.stdout.strip():
        return (True, None)

    return (False, _("No virus database files found in host directory: {path}").format(path=db_dir))


def _detect_database_dirs_from_host_freshclam_config() -> list[str]:
    """Read DatabaseDirectory values from the host freshclam config when available."""
    config_path = resolve_freshclam_conf_path()
    if not config_path:
        return []

    try:
        from .clamav_config import parse_config

        config, error = parse_config(config_path)
        if config is None:
            if error:
                logger.debug("Failed to parse freshclam config %s: %s", config_path, error)
            return []

        database_dir = config.get_value("DatabaseDirectory")
        if database_dir:
            return [database_dir.strip()]
    except Exception as e:
        logger.debug("Failed to read DatabaseDirectory from %s: %s", config_path, e)

    return []


def _host_database_dirs_to_check() -> list[str]:
    """Return host ClamAV database directories in priority order."""
    dirs: list[str] = []
    for db_dir in [*_detect_database_dirs_from_host_freshclam_config(), *_DEFAULT_DATABASE_DIRS]:
        if db_dir and db_dir not in dirs:
            dirs.append(db_dir)
    return dirs


def check_database_available() -> tuple[bool, str | None]:
    """
    Check if ClamAV virus database files are available.

    The database files have extensions .cvd (compressed), .cld (incremental),
    or .cud (diff). At least one of these must exist for ClamAV to scan.

    Returns:
        Tuple of (is_available, error_message):
        - (True, None) if database files exist
        - (False, error_message) if no database files found
    """
    if is_flatpak():
        errors = []
        for db_dir in _host_database_dirs_to_check():
            available, error = _host_path_contains_database_file(db_dir)
            if available:
                return (True, None)
            if error:
                errors.append(error)
        detail = "; ".join(errors) if errors else _("No host database directories were found")
        return (
            False,
            _(
                "No host ClamAV virus database files found. Update the host database with freshclam. Details: {detail}"
            ).format(detail=detail),
        )

    return _path_contains_database_file(Path("/var/lib/clamav"))


# --- Config file path detection ---

_CLAMD_CONF_PATHS = [
    "/etc/clamav/clamd.conf",  # Debian/Ubuntu
    "/etc/clamd.d/scan.conf",  # Fedora/RHEL/CentOS/AlmaLinux/Rocky
    "/etc/clamd.conf",  # Generic/older
]

# Older Flatpak releases persisted this sandbox-local path. It must not be
# treated as a host configuration path when resolving settings in Flatpak.
_LEGACY_FLATPAK_CLAMD_CONF_PATH = os.path.expanduser("~/.config/clamav/clamd.conf")


_FRESHCLAM_CONF_PATHS = [
    "/etc/clamav/freshclam.conf",  # Debian/Ubuntu
    "/etc/freshclam.conf",  # Fedora/RHEL
]


def config_file_exists(path: str) -> bool:
    """
    Check if a config file exists on the host filesystem.

    In Flatpak, uses flatpak-spawn to check the host filesystem.
    Natively, uses os.path.isfile().

    Args:
        path: Absolute path to the config file

    Returns:
        True if the file exists, False otherwise
    """
    if is_flatpak():
        try:
            result = subprocess.run(
                ["flatpak-spawn", "--host", "test", "-f", path],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug("Failed to check host file %s: %s", path, e)
            return False
    return os.path.isfile(path)


def detect_clamd_conf_path() -> str | None:
    """
    Detect the clamd configuration file by probing known paths.

    Checks common distribution-specific locations in priority order:
    1. /etc/clamav/clamd.conf (Debian/Ubuntu)
    2. /etc/clamd.d/scan.conf (Fedora/RHEL/CentOS)
    3. /etc/clamd.conf (Generic/older)

    Returns:
        Path to the first existing config file, or None if not found
    """
    for path in _CLAMD_CONF_PATHS:
        if config_file_exists(path):
            logger.info("Detected clamd config at: %s", path)
            return path
    logger.info("No clamd config file found in known locations")
    return None


def detect_freshclam_conf_path() -> str | None:
    """
    Detect the freshclam configuration file by probing known paths.

    Checks common distribution-specific locations in priority order:
    1. /etc/clamav/freshclam.conf (Debian/Ubuntu)
    2. /etc/freshclam.conf (Fedora/RHEL)

    Returns:
        Path to the first existing config file, or None if not found
    """
    for path in _FRESHCLAM_CONF_PATHS:
        if config_file_exists(path):
            logger.info("Detected freshclam config at: %s", path)
            return path
    logger.info("No freshclam config file found in known locations")
    return None


def resolve_clamd_conf_path(settings_manager=None) -> str | None:
    """
    Resolve the clamd config path: check saved setting, then auto-detect.

    Resolution order:
    1. Saved path from settings (if non-empty and file exists; excluding the
       legacy Flatpak sandbox-local path)
    2. Auto-detect by probing known host paths
    3. None if nothing found

    Persists newly detected paths to settings for future use.

    Args:
        settings_manager: Optional SettingsManager for reading/persisting paths

    Returns:
        Path to clamd.conf, or None if not found
    """
    if settings_manager:
        saved = settings_manager.get("clamd_conf_path", "")
        is_legacy_flatpak_path = is_flatpak() and saved == _LEGACY_FLATPAK_CLAMD_CONF_PATH
        if saved and not is_legacy_flatpak_path and config_file_exists(saved):
            return saved
        if saved:
            if is_legacy_flatpak_path:
                logger.info("Ignoring legacy Flatpak clamd config path (%s)", saved)
            else:
                logger.info("Saved clamd config path invalid (%s), re-detecting", saved)
            settings_manager.set("clamd_conf_path", "")

    detected = detect_clamd_conf_path()
    if detected and settings_manager:
        settings_manager.set("clamd_conf_path", detected)
    return detected


def resolve_freshclam_conf_path(settings_manager=None) -> str | None:
    """
    Resolve the freshclam config path: check saved setting, then auto-detect.

    Resolution order:
    1. Saved path from settings (if non-empty and file exists)
    2. Auto-detect by probing known paths
    3. None if nothing found

    Persists newly detected paths to settings for future use.

    Args:
        settings_manager: Optional SettingsManager for reading/persisting paths

    Returns:
        Path to freshclam.conf, or None if not found
    """
    if settings_manager:
        saved = settings_manager.get("freshclam_conf_path", "")
        if saved and config_file_exists(saved):
            return saved
        if saved:
            logger.info("Saved freshclam config path invalid (%s), re-detecting", saved)
            settings_manager.set("freshclam_conf_path", "")

    detected = detect_freshclam_conf_path()
    if detected and settings_manager:
        settings_manager.set("freshclam_conf_path", detected)
    return detected
