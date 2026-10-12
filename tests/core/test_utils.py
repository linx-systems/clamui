# ClamUI Utils Re-export Tests
"""
Tests for the utils.py backwards compatibility re-export module.

This module verifies that all functions can be imported from src.core.utils
for backwards compatibility, and that they are correctly re-exported from
the focused utility modules.
"""

import sys
from unittest import mock

# Store original gi modules to restore later (if they exist)
_original_gi = sys.modules.get("gi")
_original_gi_repository = sys.modules.get("gi.repository")

# Mock gi module before importing src.core to avoid GTK dependencies in tests
sys.modules["gi"] = mock.MagicMock()
sys.modules["gi.repository"] = mock.MagicMock()


class TestBackwardsCompatibilityImports:
    """Test that all functions can be imported from src.core.utils for backwards compatibility."""

    def test_import_flatpak_functions(self):
        """Test that all Flatpak-related functions can be imported from utils."""
        from src.core import utils

        # Verify Flatpak functions are accessible
        assert hasattr(utils, "is_flatpak")
        assert hasattr(utils, "wrap_host_command")
        assert hasattr(utils, "which_host_command")
        assert hasattr(utils, "format_flatpak_portal_path")
        assert hasattr(utils, "_resolve_portal_path_via_xattr")
        assert hasattr(utils, "_resolve_portal_path_via_gio")
        assert hasattr(utils, "_resolve_portal_path_via_dbus")

    def test_import_clamav_detection_functions(self):
        """Test that all ClamAV detection functions can be imported from utils."""
        from src.core import utils

        # Verify ClamAV detection functions are accessible
        assert hasattr(utils, "check_clamav_installed")
        assert hasattr(utils, "check_freshclam_installed")
        assert hasattr(utils, "check_clamdscan_installed")
        assert hasattr(utils, "get_clamd_socket_path")
        assert hasattr(utils, "check_clamd_connection")
        assert hasattr(utils, "get_clamav_path")
        assert hasattr(utils, "get_freshclam_path")

    def test_import_path_validation_functions(self):
        """Test that all path validation functions can be imported from utils."""
        from src.core import utils

        # Verify path validation functions are accessible
        assert hasattr(utils, "check_symlink_safety")
        assert hasattr(utils, "validate_path")
        assert hasattr(utils, "validate_dropped_files")
        assert hasattr(utils, "format_scan_path")
        assert hasattr(utils, "get_path_info")

    def test_import_result_formatter_functions(self):
        """Test that all result formatter functions can be imported from utils."""
        from src.core import utils

        # Verify result formatter functions are accessible
        assert hasattr(utils, "format_results_as_text")
        assert hasattr(utils, "format_results_as_csv")

    def test_import_clipboard_functions(self):
        """Test that clipboard functions can be imported from utils."""
        from src.core import utils

        # Verify clipboard function is accessible
        assert hasattr(utils, "copy_to_clipboard")

    def test_import_using_from_statement(self):
        """Test that functions can be imported using 'from src.core.utils import' syntax."""
        # This is the most common backwards compatibility import pattern
        # If this import fails, backwards compatibility is broken
        from src.core.utils import (  # noqa: F401 - backward compat test
            check_clamav_installed,
            check_clamdscan_installed,
            check_freshclam_installed,
            copy_to_clipboard,
            format_results_as_csv,
            format_results_as_text,
            format_scan_path,
            get_path_info,
            is_flatpak,
            validate_dropped_files,
            validate_path,
            wrap_host_command,
        )


class TestReExportCorrectness:
    """Test that re-exported functions are the same as the original functions from focused modules."""

    def test_flatpak_functions_are_same_objects(self):
        """Test that Flatpak functions from utils are the same as from flatpak module."""
        from src.core import flatpak, utils

        # Verify re-exported functions are the same objects
        assert utils.is_flatpak is flatpak.is_flatpak
        assert utils.wrap_host_command is flatpak.wrap_host_command
        assert utils.which_host_command is flatpak.which_host_command
        assert utils.format_flatpak_portal_path is flatpak.format_flatpak_portal_path
        assert utils._resolve_portal_path_via_xattr is flatpak._resolve_portal_path_via_xattr
        assert utils._resolve_portal_path_via_gio is flatpak._resolve_portal_path_via_gio
        assert utils._resolve_portal_path_via_dbus is flatpak._resolve_portal_path_via_dbus

    def test_clamav_detection_functions_are_same_objects(self):
        """Test that ClamAV detection functions from utils are the same as from clamav_detection module."""
        from src.core import clamav_detection, utils

        # Verify re-exported functions are the same objects
        assert utils.check_clamav_installed is clamav_detection.check_clamav_installed
        assert utils.check_freshclam_installed is clamav_detection.check_freshclam_installed
        assert utils.check_clamdscan_installed is clamav_detection.check_clamdscan_installed
        assert utils.get_clamd_socket_path is clamav_detection.get_clamd_socket_path
        assert utils.check_clamd_connection is clamav_detection.check_clamd_connection
        assert utils.get_clamav_path is clamav_detection.get_clamav_path
        assert utils.get_freshclam_path is clamav_detection.get_freshclam_path

    def test_path_validation_functions_are_same_objects(self):
        """Test that path validation functions from utils are the same as from path_validation module."""
        from src.core import path_validation, utils

        # Verify re-exported functions are the same objects
        assert utils.check_symlink_safety is path_validation.check_symlink_safety
        assert utils.validate_path is path_validation.validate_path
        assert utils.validate_dropped_files is path_validation.validate_dropped_files
        assert utils.format_scan_path is path_validation.format_scan_path
        assert utils.get_path_info is path_validation.get_path_info

    def test_result_formatter_functions_are_same_objects(self):
        """Test that result formatter functions from utils are the same as from result_formatters module."""
        from src.core import result_formatters, utils

        # Verify re-exported functions are the same objects
        assert utils.format_results_as_text is result_formatters.format_results_as_text
        assert utils.format_results_as_csv is result_formatters.format_results_as_csv

    def test_clipboard_functions_are_same_objects(self):
        """Test that clipboard functions from utils are the same as from clipboard module."""
        from src.core import clipboard, utils

        # Verify re-exported function is the same object
        assert utils.copy_to_clipboard is clipboard.copy_to_clipboard


class TestUtilsModuleAPI:
    """Test the utils module's public API (__all__)."""

    def test_all_attribute_exists(self):
        """Test that utils module has __all__ attribute."""
        from src.core import utils

        assert hasattr(utils, "__all__")
        assert isinstance(utils.__all__, list)

    def test_all_contains_expected_functions(self):
        """Test that __all__ contains all expected function names."""
        from src.core import utils

        expected_functions = [
            # Flatpak functions
            "is_flatpak",
            "wrap_host_command",
            "which_host_command",
            "format_flatpak_portal_path",
            "_resolve_portal_path_via_xattr",
            "_resolve_portal_path_via_gio",
            "_resolve_portal_path_via_dbus",
            # ClamAV detection functions
            "check_clamav_installed",
            "check_freshclam_installed",
            "check_clamdscan_installed",
            "get_clamd_socket_path",
            "check_clamd_connection",
            "get_clamav_path",
            "get_freshclam_path",
            # Path validation functions
            "check_symlink_safety",
            "validate_path",
            "validate_dropped_files",
            "format_scan_path",
            "get_path_info",
            # Result formatting functions
            "format_results_as_text",
            "format_results_as_csv",
            # Clipboard functions
            "copy_to_clipboard",
        ]

        for function_name in expected_functions:
            assert function_name in utils.__all__, f"{function_name} not in utils.__all__"

    def test_all_functions_in_all_are_accessible(self):
        """Test that all functions listed in __all__ are actually accessible."""
        from src.core import utils

        for function_name in utils.__all__:
            assert hasattr(utils, function_name), f"{function_name} in __all__ but not accessible"
            attr = getattr(utils, function_name)
            assert callable(attr), f"{function_name} is not callable"

    def test_no_extra_public_functions(self):
        """Test that no unexpected public functions are exported."""
        from src.core import utils

        # Get all public attributes (not starting with _)
        public_attrs = [name for name in dir(utils) if not name.startswith("_")]

        # Filter to only callables (functions)
        public_functions = [name for name in public_attrs if callable(getattr(utils, name))]

        # All public functions should be in __all__
        for function_name in public_functions:
            assert function_name in utils.__all__, f"{function_name} is public but not in __all__"


class TestReExportFunctionality:
    """Basic smoke tests to ensure re-exported functions actually work."""

    def test_validate_path_works_via_utils(self):
        """Test that validate_path function works when called via utils module."""
        from src.core.utils import validate_path

        # Test with empty path (should return error)
        is_valid, error = validate_path("")
        assert is_valid is False
        assert "no path" in error.lower()

    def test_validate_dropped_files_works_via_utils(self):
        """Test that validate_dropped_files function works when called via utils module."""
        from src.core.utils import validate_dropped_files

        # Test with empty list (should return error)
        valid_paths, errors = validate_dropped_files([])
        assert valid_paths == []
        assert len(errors) == 1
        assert "no files" in errors[0].lower()

    def test_format_scan_path_works_via_utils(self):
        """Test that format_scan_path function works when called via utils module."""
        from src.core.utils import format_scan_path

        # Test with empty path
        result = format_scan_path("")
        assert "no path" in result.lower()

    def test_get_path_info_works_via_utils(self):
        """Test that get_path_info function works when called via utils module."""
        from src.core.utils import get_path_info

        # Test with empty path
        info = get_path_info("")
        assert info["type"] == "unknown"
        assert info["exists"] is False

    def test_wrap_host_command_works_via_utils(self):
        """Test that wrap_host_command function works when called via utils module."""
        from src.core.utils import wrap_host_command

        # Mock is_flatpak to return False (non-Flatpak environment)
        with mock.patch("src.core.flatpak.is_flatpak", return_value=False):
            cmd = wrap_host_command(["clamscan", "--version"])
            # Should return the command unchanged in non-Flatpak environment
            assert cmd == ["clamscan", "--version"]

    def test_get_clamav_path_works_via_utils(self):
        """Test that get_clamav_path function works when called via utils module."""
        from src.core.utils import get_clamav_path

        # Mock which_host_command to return a path
        with mock.patch(
            "src.core.clamav_detection.which_host_command",
            return_value="/usr/bin/clamscan",
        ):
            path = get_clamav_path()
            assert path == "/usr/bin/clamscan"

    def test_get_freshclam_path_works_via_utils(self):
        """Test that get_freshclam_path function works when called via utils module."""
        from src.core.utils import get_freshclam_path

        # Mock which_host_command to return None (not found)
        with mock.patch("src.core.clamav_detection.which_host_command", return_value=None):
            path = get_freshclam_path()
            assert path is None


# Restore original gi modules after all tests
def teardown_module():
    """Restore original gi modules after all tests."""
    if _original_gi is not None:
        sys.modules["gi"] = _original_gi
    elif "gi" in sys.modules:
        del sys.modules["gi"]

    if _original_gi_repository is not None:
        sys.modules["gi.repository"] = _original_gi_repository
    elif "gi.repository" in sys.modules:
        del sys.modules["gi.repository"]
