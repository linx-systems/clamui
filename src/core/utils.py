# ClamUI Utility Functions
"""
Backwards compatibility module for ClamUI utilities.

This module re-exports all utility functions from focused modules to maintain
backwards compatibility with existing imports like:
    from clamui.core.utils import check_clamav_installed

The original utils.py has been split into focused modules:
- flatpak.py: Flatpak detection and portal path resolution
- clamav_detection.py: ClamAV installation detection and daemon connectivity
- path_validation.py: Path validation and formatting
- result_formatters.py: Scan result formatting (text/CSV)
- clipboard.py: Clipboard operations

All functions are re-exported here to ensure existing code continues to work.
New code should import directly from the focused modules.
"""

# Re-export all public functions from focused modules
from .clamav_detection import (
    check_clamav_installed,
    check_clamd_connection,
    check_clamdscan_installed,
    check_freshclam_installed,
    detect_clamd_conf_path,
    detect_freshclam_conf_path,
    get_clamav_path,
    get_clamd_socket_path,
    get_freshclam_path,
    resolve_clamd_conf_path,
    resolve_freshclam_conf_path,
    systemd_unit_exists,
)
from .clipboard import copy_to_clipboard
from .flatpak import (
    _resolve_portal_path_via_dbus,
    _resolve_portal_path_via_gio,
    _resolve_portal_path_via_xattr,
    ensure_clamav_database_dir,
    ensure_freshclam_config,
    format_flatpak_portal_path,
    get_clamav_database_dir,
    get_clean_env,
    get_freshclam_config_path,
    is_flatpak,
    which_host_command,
    wrap_host_command,
)
from .path_validation import (
    check_symlink_safety,
    format_scan_path,
    get_path_info,
    validate_dropped_files,
    validate_path,
)
from .result_formatters import format_results_as_csv, format_results_as_text

# Define public API for backwards compatibility
__all__ = [
    "_resolve_portal_path_via_dbus",
    "_resolve_portal_path_via_gio",
    "_resolve_portal_path_via_xattr",
    # ClamAV detection functions
    "check_clamav_installed",
    "check_clamd_connection",
    "check_clamdscan_installed",
    "check_freshclam_installed",
    # Path validation functions
    "check_symlink_safety",
    # Clipboard functions
    "copy_to_clipboard",
    "detect_clamd_conf_path",
    "detect_freshclam_conf_path",
    "ensure_clamav_database_dir",
    "ensure_freshclam_config",
    "format_flatpak_portal_path",
    "format_results_as_csv",
    # Result formatting functions
    "format_results_as_text",
    "format_scan_path",
    "get_clamav_database_dir",
    "get_clamav_path",
    "get_clamd_socket_path",
    # Flatpak/packaging functions
    "get_clean_env",
    "get_freshclam_config_path",
    "get_freshclam_path",
    "get_path_info",
    "is_flatpak",
    "resolve_clamd_conf_path",
    "resolve_freshclam_conf_path",
    "systemd_unit_exists",
    "validate_dropped_files",
    "validate_path",
    "which_host_command",
    "wrap_host_command",
]
