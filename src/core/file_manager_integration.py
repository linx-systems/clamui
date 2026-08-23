# ClamUI File Manager Integration
"""
File manager integration installer for Flatpak.

This module provides functions to install context menu integration
for various file managers (Nemo, Nautilus, Dolphin) when running
as a Flatpak application.

The integration files are bundled in the Flatpak at /app/share/clamui/integrations/
and are copied to the user's local share directories on first run.
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .flatpak import get_clean_env, is_flatpak, wrap_host_command
from .i18n import N_, _
from .path_validation import validate_path

logger = logging.getLogger(__name__)


class FileManager(Enum):
    """Supported file managers for integration."""

    NEMO = "nemo"
    NAUTILUS = "nautilus"
    DOLPHIN = "dolphin"


class IntegrationStatus(Enum):
    """Status of a file manager integration installation."""

    NOT_INSTALLED = "not_installed"
    PARTIAL = "partial"
    INSTALLED = "installed"


@dataclass
class IntegrationInfo:
    """Information about a file manager integration."""

    file_manager: FileManager
    display_name: str
    description: str
    source_files: list[tuple[str, str]]  # List of (source_filename, dest_path) tuples
    status: IntegrationStatus = IntegrationStatus.NOT_INSTALLED
    is_available: bool = False
    missing_files: list[str] = field(default_factory=list)

    @property
    def is_installed(self) -> bool:
        """Backward-compatible property: True when fully installed."""
        return self.status == IntegrationStatus.INSTALLED

    @property
    def is_partial(self) -> bool:
        """True when some but not all integration files are installed."""
        return self.status == IntegrationStatus.PARTIAL


# Bundled integration files location in Flatpak
INTEGRATIONS_SOURCE_DIR = Path("/app/share/clamui/integrations")

# Integration file mappings: source filename -> destination relative path
NEMO_INTEGRATIONS = [
    (
        "io.github.linx_systems.ClamUI.nemo_action",
        "nemo/actions/io.github.linx_systems.ClamUI.nemo_action",
    ),
    (
        "io.github.linx_systems.ClamUI-virustotal.nemo_action",
        "nemo/actions/io.github.linx_systems.ClamUI-virustotal.nemo_action",
    ),
]

NAUTILUS_INTEGRATIONS = [
    (
        "clamui-scan-nautilus.sh",
        "nautilus/scripts/Scan with ClamUI",
    ),
    (
        "clamui-virustotal-nautilus.sh",
        "nautilus/scripts/Scan with VirusTotal",
    ),
]


def _build_dolphin_integrations(service_menu_dir: str) -> list[tuple[str, str]]:
    """Build Dolphin integration mappings for a specific KDE service menu directory."""
    return [
        (
            "io.github.linx_systems.ClamUI.service.desktop",
            f"{service_menu_dir}/io.github.linx_systems.ClamUI.service.desktop",
        ),
        (
            "io.github.linx_systems.ClamUI-virustotal.desktop",
            f"{service_menu_dir}/io.github.linx_systems.ClamUI-virustotal.desktop",
        ),
    ]


DOLPHIN_INTEGRATIONS = _build_dolphin_integrations("kio/servicemenus")
DOLPHIN_LEGACY_INTEGRATIONS = _build_dolphin_integrations("kservices5/ServiceMenus")


def _get_local_share_dir() -> Path:
    """
    Get the user's local share directory for file manager integrations.

    In Flatpak, we explicitly use ~/.local/share (not XDG_DATA_HOME) because:
    1. XDG_DATA_HOME points to the sandboxed ~/.var/app/<app-id>/data/
    2. File managers (Nemo, Nautilus, Dolphin) look in the real ~/.local/share
    3. The Flatpak manifest grants filesystem permissions to those directories

    Returns:
        Path to ~/.local/share (always the real user directory)
    """
    if is_flatpak():
        # In Flatpak, always use the real ~/.local/share, not the sandbox
        return Path.home() / ".local" / "share"

    # Outside Flatpak, respect XDG_DATA_HOME if set
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home)
    return Path.home() / ".local" / "share"


def _check_file_manager_available(file_manager: FileManager) -> bool:
    """
    Check if a file manager is available on the system.

    Uses directory existence as the primary check since it's more reliable
    and doesn't require executing host commands.

    Args:
        file_manager: The file manager to check.

    Returns:
        True if the file manager appears to be installed/used.
    """
    local_share = _get_local_share_dir()

    if file_manager == FileManager.NEMO:
        # Check if Nemo actions directory exists or can be created
        nemo_dir = local_share / "nemo"
        return nemo_dir.exists() or _can_create_directory(nemo_dir)

    elif file_manager == FileManager.NAUTILUS:
        # Check if Nautilus scripts directory exists or can be created
        nautilus_dir = local_share / "nautilus"
        return nautilus_dir.exists() or _can_create_directory(nautilus_dir)

    elif file_manager == FileManager.DOLPHIN:
        # Check if KDE service menus directory exists or can be created
        kde_dir = local_share / _get_dolphin_service_menu_parent(local_share)
        return kde_dir.exists() or _can_create_directory(kde_dir)

    return False


def _can_create_directory(path: Path) -> bool:
    """
    Check if a directory can be created (parent exists and is writable).

    Args:
        path: The directory path to check.

    Returns:
        True if the directory can be created.
    """
    try:
        parent = path.parent
        return parent.exists() and os.access(parent, os.W_OK)
    except Exception:
        return False


def _check_integration_status(
    file_manager: FileManager,
) -> tuple[IntegrationStatus, list[str]]:
    """
    Check the installation status of integration files for a file manager.

    Checks ALL files (not just the first) to detect partial installations.

    Args:
        file_manager: The file manager to check.

    Returns:
        Tuple of (status, missing_files) where missing_files lists
        destination-relative paths that are not yet installed.
    """
    local_share = _get_local_share_dir()

    if file_manager == FileManager.NEMO:
        files = NEMO_INTEGRATIONS
        return _check_integration_files(local_share, files)
    elif file_manager == FileManager.NAUTILUS:
        files = NAUTILUS_INTEGRATIONS
        return _check_integration_files(local_share, files)
    elif file_manager == FileManager.DOLPHIN:
        preferred_files = _get_dolphin_integrations(local_share)
        status, missing = _check_integration_files(local_share, preferred_files)
        if status != IntegrationStatus.NOT_INSTALLED:
            return status, missing

        legacy_files = _get_dolphin_legacy_integrations(local_share)
        legacy_status = _check_integration_files(local_share, legacy_files)[0]
        if legacy_status != IntegrationStatus.NOT_INSTALLED:
            # Treat legacy-only installs as partial so Apply repairs them into
            # the current service menu path on Plasma 6 systems.
            return (
                IntegrationStatus.PARTIAL,
                [file_entry[1] for file_entry in preferred_files],
            )
        return status, missing
    else:
        return IntegrationStatus.NOT_INSTALLED, []


def _check_integration_files(
    local_share: Path,
    files: list[tuple[str, str]],
) -> tuple[IntegrationStatus, list[str]]:
    """Check whether a specific integration file set is installed."""
    if not files:
        return IntegrationStatus.NOT_INSTALLED, []

    missing = []
    installed_count = 0

    for file_entry in files:
        dest_path = local_share / file_entry[1]
        if dest_path.exists():
            installed_count += 1
        else:
            missing.append(file_entry[1])

    if installed_count == 0:
        return IntegrationStatus.NOT_INSTALLED, missing
    if missing:
        return IntegrationStatus.PARTIAL, missing
    return IntegrationStatus.INSTALLED, []


def _get_dolphin_service_menu_parent(local_share: Path | None = None) -> str:
    """Return the preferred KDE service menu parent directory name."""
    if local_share is None:
        local_share = _get_local_share_dir()

    session_version = os.environ.get("KDE_SESSION_VERSION")
    if session_version == "5":
        return "kservices5"
    if session_version == "6":
        return "kio"

    modern_dir = local_share / "kio"
    legacy_dir = local_share / "kservices5"
    if modern_dir.exists():
        return "kio"
    if legacy_dir.exists():
        return "kservices5"
    return "kio"


def _get_dolphin_integrations(local_share: Path | None = None) -> list[tuple[str, str]]:
    """Return the preferred Dolphin integration mapping for this KDE environment."""
    parent_dir = _get_dolphin_service_menu_parent(local_share)
    if parent_dir == "kservices5":
        return DOLPHIN_LEGACY_INTEGRATIONS
    return DOLPHIN_INTEGRATIONS


def _get_dolphin_legacy_integrations(local_share: Path | None = None) -> list[tuple[str, str]]:
    """Return the non-preferred Dolphin integration mapping for cleanup/repair."""
    parent_dir = _get_dolphin_service_menu_parent(local_share)
    if parent_dir == "kservices5":
        return DOLPHIN_INTEGRATIONS
    return DOLPHIN_LEGACY_INTEGRATIONS


def _set_integration_permissions(
    file_manager: FileManager, source_name: str, dest_path: Path
) -> None:
    """Apply any required executable permissions to installed integration files."""
    if source_name.endswith(".sh") or file_manager == FileManager.DOLPHIN:
        dest_path.chmod(0o755)


def _remove_legacy_dolphin_files(local_share: Path) -> None:
    """Remove Dolphin service menu files from the non-preferred KDE path."""
    for file_entry in _get_dolphin_legacy_integrations(local_share):
        dest_path = local_share / file_entry[1]
        if dest_path.exists():
            dest_path.unlink()
            logger.info("Removed stale Dolphin integration: %s", dest_path)


def _refresh_dolphin_service_menu_cache() -> None:
    """Refresh KDE service menu cache after changing Dolphin integration files."""
    for binary in ("kbuildsycoca6", "kbuildsycoca5"):
        try:
            subprocess.run(
                wrap_host_command([binary, "--noincremental"], force_host=True),
                capture_output=True,
                check=True,
                text=True,
                timeout=10,
                env=get_clean_env(),
            )
            logger.info("Refreshed KDE service menu cache via %s", binary)
            return
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError as e:
            logger.debug("Failed to refresh KDE cache via %s: %s", binary, e.stderr or e)
        except Exception as e:
            logger.debug("Failed to refresh KDE cache via %s: %s", binary, e)


def _check_integration_installed(file_manager: FileManager) -> bool:
    """
    Check if integration files are already installed for a file manager.

    Backward-compatible wrapper around _check_integration_status().

    Args:
        file_manager: The file manager to check.

    Returns:
        True if all integration files are installed.
    """
    status, _ = _check_integration_status(file_manager)
    return status == IntegrationStatus.INSTALLED


def get_available_integrations() -> list[IntegrationInfo]:
    """
    Get list of available file manager integrations.

    Detects which file managers are available and whether integrations
    are already installed.

    Returns:
        List of IntegrationInfo objects for each supported file manager.
    """
    integrations = []

    # Check if we're in Flatpak and have integration files
    if not is_flatpak():
        logger.debug("Not in Flatpak, file manager integrations not applicable")
        return integrations

    if not INTEGRATIONS_SOURCE_DIR.exists():
        logger.warning(f"Integration source directory not found: {INTEGRATIONS_SOURCE_DIR}")
        return integrations

    # Nemo (Linux Mint, Cinnamon)
    nemo_available = _check_file_manager_available(FileManager.NEMO)
    nemo_status, nemo_missing = _check_integration_status(FileManager.NEMO)
    integrations.append(
        IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description=N_("Linux Mint / Cinnamon file manager"),
            source_files=NEMO_INTEGRATIONS,
            status=nemo_status,
            is_available=nemo_available,
            missing_files=nemo_missing,
        )
    )

    # Nautilus (GNOME Files)
    nautilus_available = _check_file_manager_available(FileManager.NAUTILUS)
    nautilus_status, nautilus_missing = _check_integration_status(FileManager.NAUTILUS)
    integrations.append(
        IntegrationInfo(
            file_manager=FileManager.NAUTILUS,
            display_name="Nautilus",
            description=N_("GNOME Files"),
            source_files=NAUTILUS_INTEGRATIONS,
            status=nautilus_status,
            is_available=nautilus_available,
            missing_files=nautilus_missing,
        )
    )

    # Dolphin (KDE)
    dolphin_available = _check_file_manager_available(FileManager.DOLPHIN)
    dolphin_status, dolphin_missing = _check_integration_status(FileManager.DOLPHIN)
    integrations.append(
        IntegrationInfo(
            file_manager=FileManager.DOLPHIN,
            display_name="Dolphin",
            description=N_("KDE file manager"),
            source_files=_get_dolphin_integrations(),
            status=dolphin_status,
            is_available=dolphin_available,
            missing_files=dolphin_missing,
        )
    )

    return integrations


def install_integration(file_manager: FileManager) -> tuple[bool, str | None]:
    """
    Install file manager integration.

    Copies integration files from the Flatpak bundle to the user's
    local share directory.

    Args:
        file_manager: The file manager to install integration for.

    Returns:
        Tuple of (success, error_message).
    """
    if not is_flatpak():
        return False, _("Not running as Flatpak")

    if not INTEGRATIONS_SOURCE_DIR.exists():
        return False, _("Integration files not found")

    local_share = _get_local_share_dir()

    if file_manager == FileManager.NEMO:
        files = NEMO_INTEGRATIONS
    elif file_manager == FileManager.NAUTILUS:
        files = NAUTILUS_INTEGRATIONS
    elif file_manager == FileManager.DOLPHIN:
        files = _get_dolphin_integrations(local_share)
    else:
        return False, _("Unknown file manager: {name}").format(name=file_manager)

    try:
        for source_name, dest_rel in files:
            source_path = INTEGRATIONS_SOURCE_DIR / source_name
            dest_path = local_share / dest_rel

            if not source_path.exists():
                logger.warning(f"Source file not found: {source_path}")
                continue

            # Create destination directory if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            is_valid, error = validate_path(str(dest_path.parent))
            if not is_valid:
                logger.warning(
                    "Invalid destination path for integration file: %s - %s",
                    dest_path,
                    error,
                )
                return False, _("Invalid destination path: {path}").format(path=dest_path)

            if dest_path.parent.is_symlink():
                logger.warning("Destination parent is a symlink, skipping: %s", dest_path)
                return False, _("Invalid destination path: {path}").format(path=dest_path)

            # Copy the file
            shutil.copy2(source_path, dest_path)

            _set_integration_permissions(file_manager, source_name, dest_path)

            logger.info(f"Installed: {dest_path}")

        if file_manager == FileManager.DOLPHIN:
            _remove_legacy_dolphin_files(local_share)
            _refresh_dolphin_service_menu_cache()

        return True, None

    except PermissionError as e:
        error_msg = _("Permission denied: {error}").format(error=e)
        logger.error("Permission denied: %s", e)
        return False, error_msg

    except Exception as e:
        error_msg = _("Failed to install integration: {error}").format(error=e)
        logger.error("Failed to install integration: %s", e)
        return False, error_msg


def repair_integration(file_manager: FileManager) -> tuple[bool, str | None]:
    """
    Repair a partial file manager integration by installing only missing files.

    Args:
        file_manager: The file manager to repair integration for.

    Returns:
        Tuple of (success, error_message).
    """
    status, missing = _check_integration_status(file_manager)

    if status == IntegrationStatus.INSTALLED:
        return True, None  # Nothing to repair

    if status == IntegrationStatus.NOT_INSTALLED:
        return install_integration(file_manager)

    # PARTIAL: install only missing files
    if not is_flatpak():
        return False, _("Not running as Flatpak")

    if not INTEGRATIONS_SOURCE_DIR.exists():
        return False, _("Integration files not found")

    local_share = _get_local_share_dir()

    if file_manager == FileManager.NEMO:
        files = NEMO_INTEGRATIONS
    elif file_manager == FileManager.NAUTILUS:
        files = NAUTILUS_INTEGRATIONS
    elif file_manager == FileManager.DOLPHIN:
        files = _get_dolphin_integrations(local_share)
    else:
        return False, _("Unknown file manager: {name}").format(name=file_manager)

    try:
        for source_name, dest_rel in files:
            if dest_rel not in missing:
                continue

            source_path = INTEGRATIONS_SOURCE_DIR / source_name
            dest_path = local_share / dest_rel

            if not source_path.exists():
                logger.warning("Source file not found: %s", source_path)
                continue

            dest_path.parent.mkdir(parents=True, exist_ok=True)

            is_valid, error = validate_path(str(dest_path.parent))
            if not is_valid:
                logger.warning(
                    "Invalid destination path for integration file: %s - %s",
                    dest_path,
                    error,
                )
                return False, _("Invalid destination path: {path}").format(path=dest_path)

            if dest_path.parent.is_symlink():
                logger.warning("Destination parent is a symlink, skipping: %s", dest_path)
                return False, _("Invalid destination path: {path}").format(path=dest_path)

            shutil.copy2(source_path, dest_path)

            _set_integration_permissions(file_manager, source_name, dest_path)

            logger.info("Repaired: %s", dest_path)

        if file_manager == FileManager.DOLPHIN:
            _remove_legacy_dolphin_files(local_share)
            _refresh_dolphin_service_menu_cache()

        return True, None

    except PermissionError as e:
        error_msg = _("Permission denied: {error}").format(error=e)
        logger.error("Permission denied: %s", e)
        return False, error_msg

    except Exception as e:
        error_msg = _("Failed to repair integration: {error}").format(error=e)
        logger.error("Failed to repair integration: %s", e)
        return False, error_msg


def remove_integration(file_manager: FileManager) -> tuple[bool, str | None]:
    """
    Remove file manager integration.

    Removes integration files from the user's local share directory.

    Args:
        file_manager: The file manager to remove integration for.

    Returns:
        Tuple of (success, error_message).
    """
    local_share = _get_local_share_dir()

    if file_manager == FileManager.NEMO:
        files = NEMO_INTEGRATIONS
    elif file_manager == FileManager.NAUTILUS:
        files = NAUTILUS_INTEGRATIONS
    elif file_manager == FileManager.DOLPHIN:
        files = _get_dolphin_integrations(local_share) + _get_dolphin_legacy_integrations(
            local_share
        )
    else:
        return False, _("Unknown file manager: {name}").format(name=file_manager)

    try:
        for file_entry in files:
            dest_path = local_share / file_entry[1]

            if dest_path.exists():
                dest_path.unlink()
                logger.info(f"Removed: {dest_path}")

        if file_manager == FileManager.DOLPHIN:
            _refresh_dolphin_service_menu_cache()

        return True, None

    except PermissionError as e:
        error_msg = _("Permission denied: {error}").format(error=e)
        logger.error("Permission denied: %s", e)
        return False, error_msg

    except Exception as e:
        error_msg = _("Failed to remove integration: {error}").format(error=e)
        logger.error("Failed to remove integration: %s", e)
        return False, error_msg


def install_all_available() -> dict[FileManager, tuple[bool, str | None]]:
    """
    Install integrations for all available file managers.

    Returns:
        Dictionary mapping file manager to (success, error_message) tuple.
    """
    results = {}

    for integration in get_available_integrations():
        if integration.is_available and not integration.is_installed:
            success, error = install_integration(integration.file_manager)
            results[integration.file_manager] = (success, error)

    return results


def check_any_available() -> bool:
    """
    Check if any file manager integrations are available.

    Returns:
        True if at least one file manager integration can be installed.
    """
    if not is_flatpak():
        return False

    return any(integration.is_available for integration in get_available_integrations())


def check_any_not_installed() -> bool:
    """
    Check if any available integrations are not yet installed.

    Returns:
        True if at least one available integration is not installed.
    """
    if not is_flatpak():
        return False

    return any(
        integration.is_available and not integration.is_installed
        for integration in get_available_integrations()
    )
