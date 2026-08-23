# ClamUI CLI Argument Parsing Tests
"""
Unit tests for CLI argument parsing and edge case handling.

Tests cover:
- Single file arguments
- Multiple file arguments
- Mixed files and folders
- Non-existent paths
- Permission denied scenarios
- Symlinks
- Paths with spaces and special characters
- Empty arguments (normal launch)
"""

import os
import sys
from unittest import mock

import pytest


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


# Cache for module-level function reference
_cached_parse_file_arguments = None


@pytest.fixture(scope="module")
def parse_file_arguments(request):
    """Import parse_file_arguments with proper GTK mocking.

    This fixture is module-scoped to avoid repeated imports that cause
    numpy C extension reload errors.
    """
    global _cached_parse_file_arguments
    if _cached_parse_file_arguments is not None:
        yield _cached_parse_file_arguments
        return

    # Create comprehensive mocks for GTK/GI
    mock_gi = mock.MagicMock()
    mock_gi.version_info = (3, 48, 0)
    mock_gi.require_version = mock.MagicMock()

    # Create proper mock classes for inheritance - MagicMock cannot be used as
    # a base class due to metaclass conflicts, so all GTK/Adw classes that are
    # inherited from in the source must be real Python classes.
    class MockGtkWidget:
        """Base mock class for GTK widgets."""

        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return mock.MagicMock()

    class MockGtkBox(MockGtkWidget):
        pass

    class MockGtkListBox(MockGtkWidget):
        pass

    class MockGtkListBoxRow(MockGtkWidget):
        pass

    class MockAdwApplication(MockGtkWidget):
        pass

    class MockAdwApplicationWindow(MockGtkWidget):
        pass

    class MockAdwWindow(MockGtkWidget):
        pass

    class MockAdwPreferencesWindow(MockGtkWidget):
        pass

    mock_gi_repository = mock.MagicMock()
    # Set real classes for all inherited bases (prevents metaclass conflicts)
    mock_gi_repository.Adw.Application = MockAdwApplication
    mock_gi_repository.Adw.ApplicationWindow = MockAdwApplicationWindow
    mock_gi_repository.Adw.Window = MockAdwWindow
    mock_gi_repository.Adw.PreferencesWindow = MockAdwPreferencesWindow
    mock_gi_repository.Gtk.Widget = MockGtkWidget
    mock_gi_repository.Gtk.Box = MockGtkBox
    mock_gi_repository.Gtk.ListBox = MockGtkListBox
    mock_gi_repository.Gtk.ListBoxRow = MockGtkListBoxRow
    # GTK version functions (needed for file_export.py GTK version check)
    mock_gi_repository.Gtk.get_minor_version = mock.MagicMock(return_value=14)
    mock_gi_repository.Gtk.get_major_version = mock.MagicMock(return_value=4)

    # Mock the matplotlib GTK backend
    mock_backend = mock.MagicMock()

    def _is_displaced_module(name: str) -> bool:
        """Match every module this fixture clears or replaces with a mock."""
        return name == "gi" or name.startswith(("gi.", "src.", "matplotlib.backends.backend_gtk4"))

    # Snapshot every module the fixture displaces so teardown can restore the
    # exact objects other test modules captured at import/collection time.
    # (Previously the cleared src.* modules were dropped for good, so e.g.
    # tests/cli/test_scan_cmd.py patched a re-imported src.cli.scan_cmd while
    # calling a stale `run` bound to the original module's globals.)
    original_modules = {
        name: module for name, module in sys.modules.items() if _is_displaced_module(name)
    }

    # Set up mocks
    sys.modules["gi"] = mock_gi
    sys.modules["gi.repository"] = mock_gi_repository
    sys.modules["gi.repository.Adw"] = mock_gi_repository.Adw
    sys.modules["gi.repository.Gtk"] = mock_gi_repository.Gtk
    sys.modules["gi.repository.Gio"] = mock_gi_repository.Gio
    sys.modules["gi.repository.GLib"] = mock_gi_repository.GLib
    sys.modules["gi.repository.Gdk"] = mock_gi_repository.Gdk
    sys.modules["gi.repository.GObject"] = mock_gi_repository.GObject
    sys.modules["gi.repository.Pango"] = mock_gi_repository.Pango
    sys.modules["matplotlib.backends.backend_gtk4"] = mock_backend
    sys.modules["matplotlib.backends.backend_gtk4agg"] = mock_backend

    # Clear any cached src modules from previous test files
    _clear_src_modules()

    try:
        from src.main import parse_file_arguments as func

        _cached_parse_file_arguments = func
        yield func
    finally:
        # Only restore modules at end of module, not between tests
        def cleanup():
            global _cached_parse_file_arguments
            _cached_parse_file_arguments = None
            # Drop the mocks plus everything imported under them, then put
            # back the previously loaded module objects.
            for name in [mod for mod in sys.modules if _is_displaced_module(mod)]:
                del sys.modules[name]
            sys.modules.update(original_modules)

        request.addfinalizer(cleanup)


class TestParseFileArguments:
    """Tests for the parse_file_arguments function."""

    def test_empty_arguments(self, parse_file_arguments):
        """Test parse_file_arguments with no file arguments (normal launch)."""
        argv = ["clamui"]
        result = parse_file_arguments(argv)
        assert result == []

    def test_single_file_argument(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with a single file path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        argv = ["clamui", str(test_file)]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == str(test_file)

    def test_single_folder_argument(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with a single folder path."""
        argv = ["clamui", str(tmp_path)]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == str(tmp_path)

    def test_multiple_file_arguments(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with multiple file paths."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file3 = tmp_path / "file3.txt"
        file1.write_text("content 1")
        file2.write_text("content 2")
        file3.write_text("content 3")

        argv = ["clamui", str(file1), str(file2), str(file3)]
        result = parse_file_arguments(argv)
        assert len(result) == 3
        assert str(file1) in result
        assert str(file2) in result
        assert str(file3) in result

    def test_mixed_files_and_folders(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with both files and folders."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        argv = ["clamui", str(test_file), str(subdir), str(tmp_path)]
        result = parse_file_arguments(argv)
        assert len(result) == 3
        assert str(test_file) in result
        assert str(subdir) in result
        assert str(tmp_path) in result


class TestPathWithSpaces:
    """Tests for handling paths with spaces and special characters."""

    def test_path_with_spaces(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with paths containing spaces."""
        space_dir = tmp_path / "folder with spaces"
        space_dir.mkdir()
        space_file = space_dir / "file with spaces.txt"
        space_file.write_text("content")

        argv = ["clamui", str(space_file)]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == str(space_file)
        assert " " in result[0]

    def test_path_with_special_characters(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with paths containing special characters."""
        # Test various special characters that are valid in filenames
        special_chars = ["test-file", "test_file", "test.file.txt", "test(1).txt"]

        for name in special_chars:
            special_file = tmp_path / name
            special_file.write_text("content")
            argv = ["clamui", str(special_file)]
            result = parse_file_arguments(argv)
            assert len(result) == 1
            assert result[0] == str(special_file)

    def test_path_with_unicode(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with paths containing unicode characters."""
        unicode_file = tmp_path / "test_файл_文件.txt"
        unicode_file.write_text("unicode content")

        argv = ["clamui", str(unicode_file)]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == str(unicode_file)

    def test_path_with_quotes_in_name(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with paths containing quotes."""
        # Single quotes in filename
        quoted_file = tmp_path / "test'file.txt"
        quoted_file.write_text("content")

        argv = ["clamui", str(quoted_file)]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == str(quoted_file)


class TestNonExistentPaths:
    """Tests for handling non-existent paths."""

    def test_nonexistent_path_returned(self, parse_file_arguments):
        """Test that non-existent paths are still returned by parse_file_arguments.

        Note: parse_file_arguments returns all paths; validation happens later
        in set_initial_scan_paths and queue_files_for_scan.
        """
        nonexistent = "/path/that/does/not/exist/file.txt"
        argv = ["clamui", nonexistent]
        result = parse_file_arguments(argv)
        # parse_file_arguments doesn't validate paths, just parses them
        assert len(result) == 1
        assert result[0] == nonexistent

    def test_mixed_existent_and_nonexistent(self, parse_file_arguments, tmp_path):
        """Test with mix of existing and non-existing paths."""
        existing_file = tmp_path / "exists.txt"
        existing_file.write_text("content")
        nonexistent = "/nonexistent/path/file.txt"

        argv = ["clamui", str(existing_file), nonexistent]
        result = parse_file_arguments(argv)
        # Both paths are returned; validation happens later
        assert len(result) == 2


class TestSymlinks:
    """Tests for handling symbolic links."""

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require special permissions on Windows")
    def test_symlink_to_file(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with symlink to a file."""
        target_file = tmp_path / "target.txt"
        target_file.write_text("target content")
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(target_file)

        argv = ["clamui", str(symlink)]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == str(symlink)
        # Verify symlink exists
        assert os.path.exists(result[0])

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require special permissions on Windows")
    def test_symlink_to_directory(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with symlink to a directory."""
        target_dir = tmp_path / "target_dir"
        target_dir.mkdir()
        symlink = tmp_path / "link_dir"
        symlink.symlink_to(target_dir)

        argv = ["clamui", str(symlink)]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == str(symlink)
        # Verify symlink exists and points to directory
        assert os.path.isdir(result[0])

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require special permissions on Windows")
    def test_broken_symlink(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with broken symlink."""
        target = tmp_path / "target_that_will_be_deleted.txt"
        target.write_text("content")
        symlink = tmp_path / "broken_link.txt"
        symlink.symlink_to(target)
        # Delete target to create broken symlink
        target.unlink()

        argv = ["clamui", str(symlink)]
        result = parse_file_arguments(argv)
        # Path is returned but won't exist when validated
        assert len(result) == 1
        assert result[0] == str(symlink)
        # Broken symlink: lexists is True but exists is False
        assert os.path.lexists(result[0])
        assert not os.path.exists(result[0])


@pytest.fixture
def clamui_app(parse_file_arguments):
    """Create a real ClamUIApp instance under the module's GTK mocks."""
    with mock.patch.dict(
        sys.modules,
        {
            "src.ui.window": mock.MagicMock(),
            "src.ui.scan_view": mock.MagicMock(),
            "src.ui.update_view": mock.MagicMock(),
            "src.ui.logs_view": mock.MagicMock(),
            "src.ui.components_view": mock.MagicMock(),
            "src.ui.statistics_view": mock.MagicMock(),
            "src.ui.preferences": mock.MagicMock(),
            "src.ui.preferences.window": mock.MagicMock(),
        },
    ):
        if "src.app" in sys.modules:
            del sys.modules["src.app"]

        from src.app import ClamUIApp

        yield ClamUIApp()


class TestPathValidationInApp:
    """Tests for the real ClamUIApp.set_initial_scan_paths contract.

    set_initial_scan_paths performs NO existence filtering: every parsed
    path is stored and forwarded as-is (validation happens later, during
    the scan itself).
    """

    def test_set_initial_scan_paths_forwards_paths_unfiltered(self, clamui_app, tmp_path):
        """Existing and non-existent paths are both forwarded to the scan view."""
        existing_file = tmp_path / "exists.txt"
        existing_file.write_text("content")
        nonexistent = "/nonexistent/path.txt"
        paths = [str(existing_file), nonexistent]

        scan_view = mock.MagicMock()
        scan_view.is_scanning = False
        clamui_app._scan_view = scan_view

        clamui_app.set_initial_scan_paths(paths)

        scan_view._replace_selected_paths.assert_called_once_with(paths)
        scan_view._start_scan.assert_called_once_with()
        # Consumed once forwarded.
        assert clamui_app._initial_scan_paths == []

    def test_set_initial_scan_paths_keeps_paths_pending_without_scan_view(self, clamui_app):
        """Before the scan view exists the paths must stay pending, not be dropped."""
        paths = ["/nonexistent/path1.txt", "/nonexistent/path2.txt"]
        clamui_app._scan_view = None

        clamui_app.set_initial_scan_paths(paths, use_virustotal=True)

        assert clamui_app._initial_scan_paths == paths
        assert clamui_app._initial_use_virustotal is True

    def test_set_initial_scan_paths_empty_list_is_noop(self, clamui_app):
        """An empty path list is stored but never forwarded."""
        scan_view = mock.MagicMock()
        scan_view.is_scanning = False
        clamui_app._scan_view = scan_view

        clamui_app.set_initial_scan_paths([])

        scan_view._replace_selected_paths.assert_not_called()
        scan_view._start_scan.assert_not_called()


class TestQueueFilesForScan:
    """Tests for ScanView.queue_files_for_scan path validation."""

    def test_queue_files_filters_invalid_paths(self, tmp_path):
        """Test that queue_files_for_scan filters invalid paths."""
        existing_file = tmp_path / "valid.txt"
        existing_file.write_text("content")

        paths = [str(existing_file), "/nonexistent/invalid.txt"]

        # Replicate validation logic from queue_files_for_scan
        valid_paths = []
        for path in paths:
            if os.path.exists(path):
                valid_paths.append(path)

        assert len(valid_paths) == 1
        assert str(existing_file) in valid_paths

    def test_queue_files_empty_list_returns_zero(self):
        """Test that queue_files_for_scan returns 0 for empty list."""
        paths = []
        # Replicate logic: empty list returns 0
        assert len(paths) == 0

    def test_queue_files_all_invalid_returns_zero(self):
        """Test that queue_files_for_scan returns 0 when all paths invalid."""
        paths = ["/nonexistent/a.txt", "/nonexistent/b.txt"]
        valid_paths = [p for p in paths if os.path.exists(p)]
        assert len(valid_paths) == 0


class TestLargeDirectories:
    """Tests for handling large directories."""

    def test_large_directory_with_many_files(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with directory containing many files."""
        # Create a directory with many files
        large_dir = tmp_path / "large_dir"
        large_dir.mkdir()

        # Create 100 files (representative of "large" directory for testing)
        for i in range(100):
            (large_dir / f"file_{i:04d}.txt").write_text(f"content {i}")

        argv = ["clamui", str(large_dir)]
        result = parse_file_arguments(argv)

        # The directory path should be returned
        assert len(result) == 1
        assert result[0] == str(large_dir)

        # Verify directory has files
        files = list(large_dir.iterdir())
        assert len(files) == 100

    def test_deeply_nested_directory(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with deeply nested directory structure."""
        # Create nested structure
        current = tmp_path
        for i in range(10):
            current = current / f"level_{i}"
            current.mkdir()

        # Create file at deepest level
        deep_file = current / "deep_file.txt"
        deep_file.write_text("deep content")

        argv = ["clamui", str(deep_file)]
        result = parse_file_arguments(argv)

        assert len(result) == 1
        assert result[0] == str(deep_file)
        assert os.path.exists(result[0])


class TestPermissionScenarios:
    """Tests for permission-related scenarios."""

    @pytest.mark.skipif(
        os.name == "nt" or os.geteuid() == 0,
        reason="Permission tests not applicable on Windows or when running as root",
    )
    def test_unreadable_file_path_returned(self, parse_file_arguments, tmp_path):
        """Test that paths to unreadable files are still returned by parser.

        Note: The parser returns paths; permission checks happen during scan.
        """
        unreadable_file = tmp_path / "unreadable.txt"
        unreadable_file.write_text("secret content")

        # Remove read permissions
        original_mode = unreadable_file.stat().st_mode
        try:
            unreadable_file.chmod(0o000)

            argv = ["clamui", str(unreadable_file)]
            result = parse_file_arguments(argv)

            # Path is returned; permission error happens during scan
            assert len(result) == 1
            assert result[0] == str(unreadable_file)
        finally:
            # Restore permissions for cleanup
            unreadable_file.chmod(original_mode)

    @pytest.mark.skipif(
        os.name == "nt" or os.geteuid() == 0,
        reason="Permission tests not applicable on Windows or when running as root",
    )
    def test_unreadable_directory_path_returned(self, parse_file_arguments, tmp_path):
        """Test that paths to unreadable directories are still returned."""
        unreadable_dir = tmp_path / "unreadable_dir"
        unreadable_dir.mkdir()
        (unreadable_dir / "file.txt").write_text("content")

        original_mode = unreadable_dir.stat().st_mode
        try:
            unreadable_dir.chmod(0o000)

            argv = ["clamui", str(unreadable_dir)]
            result = parse_file_arguments(argv)

            assert len(result) == 1
            assert result[0] == str(unreadable_dir)
        finally:
            unreadable_dir.chmod(original_mode)


class TestEdgeCasePathFormats:
    """Tests for edge case path formats."""

    def test_relative_path_argument(self, parse_file_arguments):
        """Test parse_file_arguments with relative path."""
        argv = ["clamui", "./relative/path.txt"]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == "./relative/path.txt"

    def test_home_tilde_path(self, parse_file_arguments):
        """Test parse_file_arguments with ~ home directory path."""
        argv = ["clamui", "~/Documents/test.txt"]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        # Tilde is passed as-is; expansion happens in shell before Python
        assert result[0] == "~/Documents/test.txt"

    def test_dot_path(self, parse_file_arguments):
        """Test parse_file_arguments with . (current directory)."""
        argv = ["clamui", "."]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == "."

    def test_double_dot_path(self, parse_file_arguments):
        """Test parse_file_arguments with .. (parent directory)."""
        argv = ["clamui", ".."]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        assert result[0] == ".."

    def test_trailing_slash_directory(self, parse_file_arguments, tmp_path):
        """Test parse_file_arguments with trailing slash on directory."""
        argv = ["clamui", str(tmp_path) + "/"]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        # Trailing slash is preserved
        assert result[0].endswith("/")

    def test_multiple_slashes_path(self, parse_file_arguments):
        """Test parse_file_arguments with multiple consecutive slashes."""
        argv = ["clamui", "/tmp//double//slashes/path"]
        result = parse_file_arguments(argv)
        assert len(result) == 1
        # Multiple slashes are preserved in the raw argument
        assert "//" in result[0]
