# ClamUI Path Validation
"""
Path validation and formatting utilities.

This module provides functions for:
- Validating filesystem paths for scanning
- Checking symlink safety and detecting path traversal attempts
- Formatting paths for UI display
- Getting path metadata (type, size, permissions)
- Validating dropped files from drag-and-drop operations
"""

import contextlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

from .flatpak import format_flatpak_portal_path

_PROTECTED_SYSTEM_DIRS = (
    Path("/etc"),
    Path("/var"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/lib"),
    Path("/lib64"),
    Path("/boot"),
    Path("/root"),
)
_USER_WRITABLE_DIRS = (Path("/home"), Path("/tmp"), Path("/var/tmp"))
_VAR_HOME_DIR = Path("/var/home")


def _is_path_under(candidate: Path, base: Path) -> bool:
    candidate_parts = candidate.parts
    base_parts = base.parts
    if len(candidate_parts) < len(base_parts):
        return False
    return candidate_parts[: len(base_parts)] == base_parts


def _safe_symlink_result(path: Path, resolved: Path, is_symlink: bool) -> tuple[bool, str | None]:
    if is_symlink:
        return (True, f"Path is a symlink: {path} -> {resolved}")
    return (True, None)


def check_symlink_safety(path: Path) -> tuple[bool, str | None]:
    """
    Check if a path involves symlinks and if they are safe.

    Detects symlinks or user paths that could be used for path traversal
    attacks by checking if the resolved path escapes common protected directories.

    Args:
        path: Path object to check

    Returns:
        Tuple of (is_safe, warning_message):
        - (True, None) if path is safe
        - (True, warning_message) if path is a symlink but safe
        - (False, error_message) if path is potentially dangerous
    """
    try:
        raw_path = path.expanduser()
        if not raw_path.is_absolute():
            raw_path = Path.cwd() / raw_path
        is_in_user_dir = any(
            _is_path_under(raw_path.parent, user_dir) for user_dir in _USER_WRITABLE_DIRS
        )
        is_symlink = path.is_symlink()

        if not is_symlink and not is_in_user_dir:
            return (True, None)

        resolved = path.resolve()
        if is_symlink and not resolved.exists():
            return (False, f"Symlink target does not exist: {path} -> {resolved}")

        if not is_in_user_dir:
            return _safe_symlink_result(path, resolved, is_symlink)

        if _is_path_under(resolved, _VAR_HOME_DIR) or any(
            _is_path_under(resolved, user_dir) for user_dir in _USER_WRITABLE_DIRS
        ):
            return _safe_symlink_result(path, resolved, is_symlink)

        if any(_is_path_under(resolved, protected) for protected in _PROTECTED_SYSTEM_DIRS):
            return (
                False,
                f"Path resolves to protected directory: {path} -> {resolved}",
            )

        return _safe_symlink_result(path, resolved, is_symlink)

    except (OSError, RuntimeError, ValueError) as e:
        return (False, f"Error checking symlink: {e!s}")


def validate_path(path: str) -> tuple[bool, str | None]:
    """
    Validate a path for scanning.

    Checks that the path:
    - Is not empty
    - Exists on the filesystem
    - Is readable by the current user
    - Is not a dangerous symlink

    Args:
        path: The filesystem path to validate

    Returns:
        Tuple of (is_valid, error_message):
        - (True, None) if path is valid for scanning
        - (False, error_message) if path is invalid
    """
    # Check for empty path
    if not path or not path.strip():
        return (False, "No path specified")

    # Convert to Path object for checks
    path_obj = Path(path)

    # Check for dangerous symlinks before resolving
    is_safe, symlink_msg = check_symlink_safety(path_obj)
    if not is_safe:
        return (False, symlink_msg)

    # Normalize and resolve the path
    try:
        resolved_path = path_obj.resolve()
    except (OSError, RuntimeError, ValueError) as e:
        return (False, f"Error resolving path: {e!s}")

    # Check if path exists
    if not resolved_path.exists():
        return (False, f"Path does not exist: {path}")

    # Check if path is readable
    if not os.access(resolved_path, os.R_OK):
        return (False, f"Permission denied: Cannot read {path}")

    # For directories, check if we can list contents
    if resolved_path.is_dir():
        try:
            # Try to list directory contents to verify access
            next(resolved_path.iterdir(), None)
        except PermissionError:
            return (
                False,
                f"Permission denied: Cannot access directory contents of {path}",
            )
        except OSError as e:
            return (False, f"Error accessing directory: {e!s}")

    return (True, None)


def validate_dropped_files(paths: list[str | None]) -> tuple[list[str], list[str]]:
    """
    Validate a batch of paths from dropped files (typically from Gio.File.get_path()).

    Handles:
    - None paths (remote files where Gio.File.get_path() returns None)
    - Non-existent paths
    - Permission errors
    - Empty path lists

    Args:
        paths: List of filesystem paths to validate. May contain None values
               for remote files that cannot be accessed locally.

    Returns:
        Tuple of (valid_paths, errors):
        - valid_paths: List of validated, resolved path strings ready for scanning
        - errors: List of error messages for invalid paths
    """
    valid_paths: list[str] = []
    errors: list[str] = []

    if not paths:
        errors.append("No files were dropped")
        return (valid_paths, errors)

    for path in paths:
        # Handle None paths (remote files)
        if path is None:
            errors.append("Remote files cannot be scanned locally")
            continue

        # Use existing validate_path for individual validation
        is_valid, error = validate_path(path)

        if is_valid:
            # Resolve path for consistent handling
            try:
                resolved = str(Path(path).resolve())
                valid_paths.append(resolved)
            except (OSError, RuntimeError, ValueError) as e:
                errors.append(f"Error resolving path: {e!s}")
        else:
            if error:
                errors.append(error)

    return (valid_paths, errors)


def format_scan_path(path: str) -> str:
    """
    Format a path for display in the UI.

    Shortens long paths for better readability while keeping them identifiable.
    Handles Flatpak document portal paths by converting them to user-friendly format.

    Args:
        path: The filesystem path to format

    Returns:
        A formatted string suitable for UI display
    """
    if not path:
        return "No path selected"

    # First, handle Flatpak document portal paths
    path = format_flatpak_portal_path(path)

    # If already formatted (~ notation or [Portal] indicator), return as-is
    if path.startswith("~/") or path.startswith("[Portal]"):
        return path

    try:
        resolved = Path(path).resolve()

        # For home directory paths, use ~ notation
        try:
            home = Path.home()
            if resolved.is_relative_to(home):
                return "~/" + str(resolved.relative_to(home))
        except (ValueError, RuntimeError):
            return str(resolved)

        return str(resolved)
    except (OSError, RuntimeError, ValueError):
        return path


def get_path_info(path: str) -> dict:
    """
    Get information about a path for scanning.

    Args:
        path: The filesystem path to analyze

    Returns:
        Dictionary with path information:
        - 'type': 'file', 'directory', or 'unknown'
        - 'exists': boolean
        - 'readable': boolean
        - 'size': size in bytes (for files) or None
        - 'display_path': formatted path for display
    """
    info = {
        "type": "unknown",
        "exists": False,
        "readable": False,
        "size": None,
        "display_path": format_scan_path(path),
    }

    if not path:
        return info

    try:
        resolved = Path(path).resolve()
        info["exists"] = resolved.exists()

        if not info["exists"]:
            return info

        if resolved.is_file():
            info["type"] = "file"
            with contextlib.suppress(OSError):
                info["size"] = resolved.stat().st_size
        elif resolved.is_dir():
            info["type"] = "directory"

        info["readable"] = os.access(resolved, os.R_OK)

    except (OSError, RuntimeError, ValueError) as e:
        logger.debug("Failed to get path info for '%s': %s", path, e)

    return info
