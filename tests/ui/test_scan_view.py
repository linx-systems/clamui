# ClamUI ScanView Tests
"""
Unit tests for the ScanView component's multi-path selection functionality.

Tests cover:
- Single path addition and management
- Multiple path addition and ordering
- Path removal operations
- Clearing all paths
- Duplicate path detection
- Drag-and-drop with multiple files
- Profile loading with all targets
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


@pytest.fixture
def scan_view_class(mock_gi_modules):
    """Get ScanView class with mocked dependencies."""
    # Mock core dependencies
    mock_scanner = mock.MagicMock()
    mock_scanner_module = mock.MagicMock()
    mock_scanner_module.Scanner = mock_scanner
    mock_scanner_module.ScanResult = mock.MagicMock()
    mock_scanner_module.ScanStatus = mock.MagicMock()

    mock_quarantine = mock.MagicMock()
    mock_utils = mock.MagicMock()
    mock_utils.format_scan_path = lambda x: x  # Pass through
    mock_utils.is_flatpak = lambda: False
    mock_utils.validate_dropped_files = lambda paths: (
        [p for p in paths if p],
        [],
    )

    with mock.patch.dict(
        sys.modules,
        {
            "src.core.scanner": mock_scanner_module,
            "src.core.quarantine": mock_quarantine,
            "src.core.utils": mock_utils,
            "src.ui.profile_dialogs": mock.MagicMock(),
            "src.ui.scan_results_dialog": mock.MagicMock(),
            "src.ui.utils": mock.MagicMock(),
            "src.ui.view_helpers": mock.MagicMock(),
        },
    ):
        # Clear any cached import
        if "src.ui.scan_view" in sys.modules:
            del sys.modules["src.ui.scan_view"]

        from src.ui.scan_view import ScanView

        yield ScanView

    # Critical: Clear all src.* modules after test to prevent pollution
    _clear_src_modules()


@pytest.fixture
def mock_scan_view(scan_view_class):
    """Create a mock ScanView instance for testing."""
    # Create instance without calling __init__
    view = object.__new__(scan_view_class)

    # Set up required attributes for multi-path functionality
    view._selected_paths = []
    view._normalized_paths = set()
    view._is_scanning = False
    view._cancel_all_requested = False
    view._progress_session_id = 0
    view._current_target_idx = 1
    view._total_target_count = 1
    view._cumulative_files_scanned = 0
    view._scan_backend_override = None
    view._scan_daemon_force_stream = False

    # Mock UI elements
    view._path_label = mock.MagicMock()
    view._path_row = mock.MagicMock()
    view._status_banner = mock.MagicMock()
    view._scan_button = mock.MagicMock()
    view._cancel_button = mock.MagicMock()
    view._eicar_button = mock.MagicMock()
    view._progress_section = mock.MagicMock()
    view._progress_bar = mock.MagicMock()
    view._progress_label = mock.MagicMock()
    view._status_detail_group = mock.MagicMock()
    view._status_detail_text = mock.MagicMock()
    view._status_detail_text.get_buffer.return_value = mock.MagicMock()
    view._status_detail_copy_button = mock.MagicMock()
    view._status_detail_fullscreen_button = mock.MagicMock()
    view._status_detail_content = ""
    view._status_detail_title_text = ""

    # Live progress Adwaita widgets (used by _stop_progress_pulse, _update_live_progress)
    view._progress_group = mock.MagicMock()
    view._current_file_row = mock.MagicMock()
    view._file_spinner = mock.MagicMock()
    view._stats_row = mock.MagicMock()
    view._threat_group = mock.MagicMock()
    view._live_threat_list = mock.MagicMock()
    # Return None so the while-loop in _stop_progress_pulse exits immediately
    view._live_threat_list.get_row_at_index.return_value = None
    view._live_threat_count = 0

    view._view_results_section = mock.MagicMock()
    view._view_results_button = mock.MagicMock()
    view._profile_dropdown = mock.MagicMock()
    view._profile_list = []
    view._selected_profile = None
    view._backend_label = mock.MagicMock()

    # Mock scanner
    view._scanner = mock.MagicMock()
    view._scanner.get_active_backend.return_value = "clamscan"

    # Mock quarantine manager
    view._quarantine_manager = mock.MagicMock()

    # Mock settings manager
    view._settings_manager = mock.MagicMock()

    # Mock internal methods that interact with GTK
    view.get_root = mock.MagicMock(return_value=None)
    view.add_css_class = mock.MagicMock()
    view.remove_css_class = mock.MagicMock()

    return view


class TestScanViewImport:
    """Tests for ScanView import."""

    def test_import_scan_view(self, mock_gi_modules):
        """Test that ScanView can be imported."""
        mock_scanner_module = mock.MagicMock()
        mock_scanner_module.Scanner = mock.MagicMock()
        mock_scanner_module.ScanResult = mock.MagicMock()
        mock_scanner_module.ScanStatus = mock.MagicMock()

        with mock.patch.dict(
            sys.modules,
            {
                "src.core.scanner": mock_scanner_module,
                "src.core.quarantine": mock.MagicMock(),
                "src.core.utils": mock.MagicMock(),
                "src.ui.profile_dialogs": mock.MagicMock(),
                "src.ui.scan_results_dialog": mock.MagicMock(),
                "src.ui.utils": mock.MagicMock(),
                "src.ui.view_helpers": mock.MagicMock(),
            },
        ):
            from src.ui.scan_view import ScanView

            assert ScanView is not None


class TestAddSinglePath:
    """Tests for adding a single path to the selection."""

    def test_add_single_path_adds_to_list(self, mock_scan_view):
        """Test that adding a single path adds it to the selected paths list."""
        # Mock the UI elements that _add_path interacts with
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()

        result = mock_scan_view._add_path("/home/user/documents")

        assert result is True
        assert "/home/user/documents" in mock_scan_view._selected_paths
        assert len(mock_scan_view._selected_paths) == 1

    def test_add_single_path_updates_ui(self, mock_scan_view):
        """Test that adding a path updates the UI elements."""
        # Mock the UI elements that _add_path interacts with
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()

        mock_scan_view._add_path("/home/user/documents")

        mock_scan_view._paths_placeholder.set_visible.assert_called_once_with(False)
        mock_scan_view._update_selection_header.assert_called_once()

    def test_add_single_path_preserves_original_path(self, mock_scan_view):
        """Test that the original path string is preserved."""
        # Mock the UI elements that _add_path interacts with
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        original_path = "/home/user/documents"

        mock_scan_view._add_path(original_path)

        assert mock_scan_view._selected_paths[0] == original_path


class TestAddMultiplePaths:
    """Tests for adding multiple paths to the selection."""

    def test_add_multiple_paths_maintains_order(self, mock_scan_view):
        """Test that adding multiple paths maintains insertion order."""
        # Mock the UI elements that _add_path interacts with
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()

        mock_scan_view._add_path("/home/user/documents")
        mock_scan_view._add_path("/home/user/downloads")
        mock_scan_view._add_path("/home/user/pictures")

        assert mock_scan_view._selected_paths == [
            "/home/user/documents",
            "/home/user/downloads",
            "/home/user/pictures",
        ]

    def test_add_multiple_paths_count(self, mock_scan_view):
        """Test that multiple paths are all added."""
        # Mock the UI elements that _add_path interacts with
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()

        mock_scan_view._add_path("/path1")
        mock_scan_view._add_path("/path2")
        mock_scan_view._add_path("/path3")
        mock_scan_view._add_path("/path4")

        assert len(mock_scan_view._selected_paths) == 4

    def test_add_multiple_paths_updates_ui_each_time(self, mock_scan_view):
        """Test that UI update is called for each path addition."""
        # Mock the UI elements that _add_path interacts with
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()

        mock_scan_view._add_path("/path1")
        mock_scan_view._add_path("/path2")
        mock_scan_view._add_path("/path3")

        assert mock_scan_view._update_selection_header.call_count == 3


class TestRemovePath:
    """Tests for removing paths from the selection."""

    def _setup_remove_path_mocks(self, mock_scan_view):
        """Helper to set up common mocks for remove path tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._update_selection_header = mock.MagicMock()

    def test_remove_path_removes_from_list(self, mock_scan_view):
        """Test that removing a path removes it from the list."""
        self._setup_remove_path_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]
        mock_scan_view._normalized_paths = {"/path1", "/path2", "/path3"}

        result = mock_scan_view._remove_path("/path2")

        assert result is True
        assert "/path2" not in mock_scan_view._selected_paths
        assert len(mock_scan_view._selected_paths) == 2

    def test_remove_path_preserves_other_paths(self, mock_scan_view):
        """Test that removing a path preserves other paths."""
        self._setup_remove_path_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]
        mock_scan_view._normalized_paths = {"/path1", "/path2", "/path3"}

        mock_scan_view._remove_path("/path2")

        assert mock_scan_view._selected_paths == ["/path1", "/path3"]

    def test_remove_nonexistent_path_returns_false(self, mock_scan_view):
        """Test that removing a non-existent path returns False."""
        self._setup_remove_path_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/path1", "/path2"]
        mock_scan_view._normalized_paths = {"/path1", "/path2"}

        result = mock_scan_view._remove_path("/nonexistent")

        assert result is False
        assert len(mock_scan_view._selected_paths) == 2

    def test_remove_path_updates_ui(self, mock_scan_view):
        """Test that removing a path updates the UI."""
        self._setup_remove_path_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/path1", "/path2"]
        mock_scan_view._normalized_paths = {"/path1", "/path2"}

        mock_scan_view._remove_path("/path1")

        mock_scan_view._update_selection_header.assert_called()

    def test_remove_path_handles_normalized_paths(self, mock_scan_view):
        """Test that path removal handles path normalization."""
        self._setup_remove_path_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/home/user/./documents"]
        # The set stores normalized paths
        mock_scan_view._normalized_paths = {os.path.normpath("/home/user/./documents")}

        # Normalized version should still match
        result = mock_scan_view._remove_path("/home/user/documents")

        assert result is True
        assert len(mock_scan_view._selected_paths) == 0


class TestClearPaths:
    """Tests for clearing all paths from the selection."""

    def _setup_clear_paths_mocks(self, mock_scan_view):
        """Helper to set up common mocks for clear paths tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._update_selection_header = mock.MagicMock()

    def test_clear_paths_empties_list(self, mock_scan_view):
        """Test that clearing paths empties the entire list."""
        self._setup_clear_paths_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]
        mock_scan_view._normalized_paths = {"/path1", "/path2", "/path3"}

        mock_scan_view._clear_paths()

        assert mock_scan_view._selected_paths == []
        assert len(mock_scan_view._selected_paths) == 0

    def test_clear_paths_updates_ui(self, mock_scan_view):
        """Test that clearing paths updates the UI."""
        self._setup_clear_paths_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/path1", "/path2"]
        mock_scan_view._normalized_paths = {"/path1", "/path2"}

        mock_scan_view._clear_paths()

        mock_scan_view._update_selection_header.assert_called_once()
        mock_scan_view._paths_placeholder.set_visible.assert_called_with(True)

    def test_clear_paths_on_empty_list(self, mock_scan_view):
        """Test that clearing an empty list works without error."""
        self._setup_clear_paths_mocks(mock_scan_view)
        mock_scan_view._selected_paths = []

        mock_scan_view._clear_paths()

        assert mock_scan_view._selected_paths == []


class TestDuplicateDetection:
    """Tests for duplicate path detection."""

    def _setup_add_path_mocks(self, mock_scan_view):
        """Helper to set up common mocks for add path tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()

    def test_duplicate_exact_path_rejected(self, mock_scan_view):
        """Test that adding the exact same path twice is rejected."""
        self._setup_add_path_mocks(mock_scan_view)

        result1 = mock_scan_view._add_path("/home/user/documents")
        result2 = mock_scan_view._add_path("/home/user/documents")

        assert result1 is True
        assert result2 is False
        assert len(mock_scan_view._selected_paths) == 1

    def test_duplicate_normalized_path_rejected(self, mock_scan_view):
        """Test that normalized duplicate paths are rejected."""
        self._setup_add_path_mocks(mock_scan_view)

        mock_scan_view._add_path("/home/user/documents")
        result = mock_scan_view._add_path("/home/user/./documents")

        assert result is False
        assert len(mock_scan_view._selected_paths) == 1

    def test_different_paths_accepted(self, mock_scan_view):
        """Test that different paths are accepted."""
        self._setup_add_path_mocks(mock_scan_view)

        result1 = mock_scan_view._add_path("/home/user/documents")
        result2 = mock_scan_view._add_path("/home/user/downloads")

        assert result1 is True
        assert result2 is True
        assert len(mock_scan_view._selected_paths) == 2

    def test_case_sensitive_paths(self, mock_scan_view):
        """Test that paths are case-sensitive (on case-sensitive filesystems)."""
        self._setup_add_path_mocks(mock_scan_view)

        result1 = mock_scan_view._add_path("/home/user/Documents")
        result2 = mock_scan_view._add_path("/home/user/documents")

        # On Linux, these are different paths
        assert result1 is True
        assert result2 is True
        assert len(mock_scan_view._selected_paths) == 2


class TestFileChooserCompatibility:
    """Tests for file chooser compatibility wrappers."""

    def test_select_file_clicked_uses_open_paths_dialog(self, mock_scan_view):
        """Test file selection delegates to the compatibility helper."""
        window_type = type("Window", (), {})
        window = window_type()
        mock_scan_view.get_root.return_value = window
        mock_scan_view._get_initial_selection_folder = mock.MagicMock(return_value=None)

        with mock.patch("src.ui.scan_view.Gtk.Window", window_type):
            with mock.patch("src.ui.scan_view.open_paths_dialog") as mock_open_paths_dialog:
                mock_scan_view._on_select_file_clicked(mock.MagicMock())

        mock_open_paths_dialog.assert_called_once()
        call_kwargs = mock_open_paths_dialog.call_args.kwargs
        assert call_kwargs["multiple"] is True
        assert call_kwargs["select_folders"] is False

    def test_select_folder_clicked_uses_open_paths_dialog(self, mock_scan_view):
        """Test folder selection delegates to the compatibility helper."""
        window_type = type("Window", (), {})
        window = window_type()
        mock_scan_view.get_root.return_value = window
        mock_scan_view._get_initial_selection_folder = mock.MagicMock(return_value=None)

        with mock.patch("src.ui.scan_view.Gtk.Window", window_type):
            with mock.patch("src.ui.scan_view.open_paths_dialog") as mock_open_paths_dialog:
                mock_scan_view._on_select_folder_clicked(mock.MagicMock())

        mock_open_paths_dialog.assert_called_once()
        call_kwargs = mock_open_paths_dialog.call_args.kwargs
        assert call_kwargs["multiple"] is True
        assert call_kwargs["select_folders"] is True


class TestDragDropMultiple:
    """Tests for drag-and-drop with multiple files."""

    def _setup_drop_mocks(self, mock_scan_view):
        """Helper to set up common mocks for drop tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()

    def test_drop_multiple_files_adds_all(self, mock_scan_view):
        """Test that dropping multiple files adds all valid paths."""
        self._setup_drop_mocks(mock_scan_view)
        mock_scan_view._show_drop_error = mock.MagicMock()

        # Mock Gdk.FileList with multiple files
        mock_file1 = mock.MagicMock()
        mock_file1.get_path.return_value = "/home/user/file1.txt"

        mock_file2 = mock.MagicMock()
        mock_file2.get_path.return_value = "/home/user/file2.txt"

        mock_file3 = mock.MagicMock()
        mock_file3.get_path.return_value = "/home/user/file3.txt"

        mock_file_list = mock.MagicMock()
        mock_file_list.get_files.return_value = [mock_file1, mock_file2, mock_file3]

        # Mock validate_dropped_files to return all paths as valid
        with mock.patch("src.ui.scan_view.validate_dropped_files") as mock_validate:
            mock_validate.return_value = (
                [
                    "/home/user/file1.txt",
                    "/home/user/file2.txt",
                    "/home/user/file3.txt",
                ],
                [],
            )

            result = mock_scan_view._on_drop(None, mock_file_list, 0, 0)

        assert result is True
        assert len(mock_scan_view._selected_paths) == 3

    def test_drop_during_scan_rejected(self, mock_scan_view):
        """Test that dropping files during a scan is rejected."""
        mock_scan_view._is_scanning = True
        mock_scan_view._show_drop_error = mock.MagicMock()

        mock_file_list = mock.MagicMock()
        mock_file_list.get_files.return_value = [mock.MagicMock()]

        result = mock_scan_view._on_drop(None, mock_file_list, 0, 0)

        assert result is False
        mock_scan_view._show_drop_error.assert_called()

    def test_drop_removes_css_class(self, mock_scan_view):
        """Test that drop removes the visual feedback CSS class."""
        self._setup_drop_mocks(mock_scan_view)

        mock_file = mock.MagicMock()
        mock_file.get_path.return_value = "/home/user/file.txt"

        mock_file_list = mock.MagicMock()
        mock_file_list.get_files.return_value = [mock_file]

        with mock.patch("src.ui.scan_view.validate_dropped_files") as mock_validate:
            mock_validate.return_value = (["/home/user/file.txt"], [])

            mock_scan_view._on_drop(None, mock_file_list, 0, 0)

        mock_scan_view.remove_css_class.assert_called_with("drop-active")

    def test_drop_empty_file_list_rejected(self, mock_scan_view):
        """Test that dropping an empty file list is rejected."""
        mock_scan_view._show_drop_error = mock.MagicMock()

        mock_file_list = mock.MagicMock()
        mock_file_list.get_files.return_value = []

        result = mock_scan_view._on_drop(None, mock_file_list, 0, 0)

        assert result is False
        mock_scan_view._show_drop_error.assert_called_with("No files were dropped")


class TestProfileLoadsAllTargets:
    """Tests for profile loading all targets."""

    def _setup_profile_mocks(self, mock_scan_view):
        """Helper to set up common mocks for profile tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()

    def test_profile_selection_loads_all_targets(self, mock_scan_view, tmp_path):
        """Test that selecting a profile loads all its targets."""
        self._setup_profile_mocks(mock_scan_view)
        mock_scan_view._show_toast = mock.MagicMock()

        # Create actual directories for testing
        dir1 = tmp_path / "documents"
        dir2 = tmp_path / "downloads"
        dir3 = tmp_path / "pictures"
        dir1.mkdir()
        dir2.mkdir()
        dir3.mkdir()

        # Create mock profile with multiple targets
        mock_profile = mock.MagicMock()
        mock_profile.name = "Test Profile"
        mock_profile.targets = [str(dir1), str(dir2), str(dir3)]

        mock_scan_view._profile_list = [mock_profile]
        mock_scan_view._selected_profile = None

        # Mock dropdown to return index 1 (first profile after "No Profile")
        mock_dropdown = mock.MagicMock()
        mock_dropdown.get_selected.return_value = 1

        mock_scan_view._on_profile_selected(mock_dropdown, None)

        # All three paths should be added
        assert len(mock_scan_view._selected_paths) == 3
        assert str(dir1) in mock_scan_view._selected_paths
        assert str(dir2) in mock_scan_view._selected_paths
        assert str(dir3) in mock_scan_view._selected_paths

    def test_profile_selection_clears_previous_paths(self, mock_scan_view, tmp_path):
        """Test that selecting a profile clears previously selected paths."""
        self._setup_profile_mocks(mock_scan_view)
        mock_scan_view._show_toast = mock.MagicMock()

        # Pre-populate with some paths
        mock_scan_view._selected_paths = ["/some/old/path"]

        # Create directory for profile target
        profile_dir = tmp_path / "profile_target"
        profile_dir.mkdir()

        # Create mock profile
        mock_profile = mock.MagicMock()
        mock_profile.name = "Test Profile"
        mock_profile.targets = [str(profile_dir)]

        mock_scan_view._profile_list = [mock_profile]

        mock_dropdown = mock.MagicMock()
        mock_dropdown.get_selected.return_value = 1

        mock_scan_view._on_profile_selected(mock_dropdown, None)

        # Should only have the profile target, not the old path
        assert len(mock_scan_view._selected_paths) == 1
        assert "/some/old/path" not in mock_scan_view._selected_paths

    def test_profile_selection_handles_tilde_paths(self, mock_scan_view, tmp_path):
        """Test that selecting a profile expands tilde (~) in paths."""
        self._setup_profile_mocks(mock_scan_view)
        mock_scan_view._show_toast = mock.MagicMock()

        # Create mock profile with tilde path
        mock_profile = mock.MagicMock()
        mock_profile.name = "Test Profile"
        mock_profile.targets = ["~"]  # Home directory always exists

        mock_scan_view._profile_list = [mock_profile]

        mock_dropdown = mock.MagicMock()
        mock_dropdown.get_selected.return_value = 1

        mock_scan_view._on_profile_selected(mock_dropdown, None)

        # Should have expanded path, not literal ~
        assert len(mock_scan_view._selected_paths) == 1
        assert "~" not in mock_scan_view._selected_paths[0]
        assert mock_scan_view._selected_paths[0] == os.path.expanduser("~")

    def test_profile_with_no_valid_targets_shows_toast(self, mock_scan_view):
        """Test that profile with no valid targets shows a warning toast."""
        self._setup_profile_mocks(mock_scan_view)
        mock_scan_view._show_toast = mock.MagicMock()

        # Create mock profile with non-existent targets
        mock_profile = mock.MagicMock()
        mock_profile.name = "Empty Profile"
        mock_profile.targets = ["/nonexistent/path1", "/nonexistent/path2"]

        mock_scan_view._profile_list = [mock_profile]

        mock_dropdown = mock.MagicMock()
        mock_dropdown.get_selected.return_value = 1

        mock_scan_view._on_profile_selected(mock_dropdown, None)

        # Toast should be shown for no valid targets
        mock_scan_view._show_toast.assert_called()
        call_args = mock_scan_view._show_toast.call_args[0][0]
        assert "Empty Profile" in call_args
        assert "no valid targets" in call_args

    def test_no_profile_selection_clears_profile(self, mock_scan_view):
        """Test that selecting 'No Profile' clears the selected profile."""
        self._setup_profile_mocks(mock_scan_view)

        # Set up a selected profile
        mock_scan_view._selected_profile = mock.MagicMock()

        mock_dropdown = mock.MagicMock()
        mock_dropdown.get_selected.return_value = 0  # "No Profile" option

        mock_scan_view._on_profile_selected(mock_dropdown, None)

        assert mock_scan_view._selected_profile is None

    def test_profile_selection_clears_normalized_paths(self, mock_scan_view, tmp_path):
        """Test that selecting a profile clears both _selected_paths and _normalized_paths.

        Regression test for bug where _normalized_paths was not cleared in _clear_paths(),
        causing profile switching to fail when returning to a previously selected profile.
        """
        self._setup_profile_mocks(mock_scan_view)
        mock_scan_view._show_toast = mock.MagicMock()

        # Pre-populate both data structures
        mock_scan_view._selected_paths = ["/some/old/path"]
        mock_scan_view._normalized_paths = {os.path.normpath("/some/old/path")}

        # Create directory for profile target
        profile_dir = tmp_path / "profile_target"
        profile_dir.mkdir()

        # Create mock profile
        mock_profile = mock.MagicMock()
        mock_profile.name = "Test Profile"
        mock_profile.targets = [str(profile_dir)]

        mock_scan_view._profile_list = [mock_profile]

        mock_dropdown = mock.MagicMock()
        mock_dropdown.get_selected.return_value = 1

        # Select profile - should clear both data structures
        mock_scan_view._on_profile_selected(mock_dropdown, None)

        # Verify both structures are cleared and updated
        assert len(mock_scan_view._selected_paths) == 1
        assert "/some/old/path" not in mock_scan_view._selected_paths
        assert os.path.normpath("/some/old/path") not in mock_scan_view._normalized_paths
        assert os.path.normpath(str(profile_dir)) in mock_scan_view._normalized_paths

    def test_profile_switch_allows_reselection(self, mock_scan_view, tmp_path):
        """Test that switching between profiles allows re-selecting the same profile.

        Regression test for the scenario: Full Scan → Quick Scan → Full Scan
        where the second Full Scan selection failed due to stale _normalized_paths.
        """
        self._setup_profile_mocks(mock_scan_view)
        mock_scan_view._show_toast = mock.MagicMock()

        # Create directories for two profiles
        full_scan_dir = tmp_path / "full_scan"
        quick_scan_dir = tmp_path / "quick_scan"
        full_scan_dir.mkdir()
        quick_scan_dir.mkdir()

        # Create two profiles
        full_profile = mock.MagicMock()
        full_profile.name = "Full Scan"
        full_profile.targets = [str(full_scan_dir)]

        quick_profile = mock.MagicMock()
        quick_profile.name = "Quick Scan"
        quick_profile.targets = [str(quick_scan_dir)]

        mock_scan_view._profile_list = [full_profile, quick_profile]

        # Step 1: Select Full Scan
        mock_dropdown = mock.MagicMock()
        mock_dropdown.get_selected.return_value = 1  # First profile (Full Scan)
        mock_scan_view._on_profile_selected(mock_dropdown, None)

        assert len(mock_scan_view._selected_paths) == 1
        assert str(full_scan_dir) in mock_scan_view._selected_paths
        assert os.path.normpath(str(full_scan_dir)) in mock_scan_view._normalized_paths

        # Step 2: Switch to Quick Scan
        mock_dropdown.get_selected.return_value = 2  # Second profile (Quick Scan)
        mock_scan_view._on_profile_selected(mock_dropdown, None)

        assert len(mock_scan_view._selected_paths) == 1
        assert str(quick_scan_dir) in mock_scan_view._selected_paths
        assert os.path.normpath(str(quick_scan_dir)) in mock_scan_view._normalized_paths
        assert os.path.normpath(str(full_scan_dir)) not in mock_scan_view._normalized_paths

        # Step 3: Switch back to Full Scan - this would fail before the fix
        mock_dropdown.get_selected.return_value = 1  # First profile (Full Scan) again
        mock_scan_view._on_profile_selected(mock_dropdown, None)

        # Should successfully re-add Full Scan paths
        assert len(mock_scan_view._selected_paths) == 1
        assert str(full_scan_dir) in mock_scan_view._selected_paths
        assert os.path.normpath(str(full_scan_dir)) in mock_scan_view._normalized_paths


class TestGetSelectedPaths:
    """Tests for the get_selected_paths method."""

    def test_get_selected_paths_returns_copy(self, mock_scan_view):
        """Test that get_selected_paths returns a copy of the list."""
        mock_scan_view._selected_paths = ["/path1", "/path2"]

        result = mock_scan_view.get_selected_paths()

        # Should be equal but not the same object
        assert result == mock_scan_view._selected_paths
        assert result is not mock_scan_view._selected_paths

    def test_get_selected_paths_modification_safe(self, mock_scan_view):
        """Test that modifying returned list doesn't affect original."""
        mock_scan_view._selected_paths = ["/path1", "/path2"]

        result = mock_scan_view.get_selected_paths()
        result.append("/path3")

        assert len(mock_scan_view._selected_paths) == 2
        assert "/path3" not in mock_scan_view._selected_paths


class TestSetSelectedPath:
    """Tests for the _set_selected_path convenience method."""

    def test_set_selected_path_clears_and_adds(self, mock_scan_view):
        """Test that _set_selected_path clears existing and adds new path."""
        # Mock the UI elements that _add_path/_clear_paths interacts with
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        mock_scan_view._selected_paths = ["/old/path1", "/old/path2"]

        mock_scan_view._set_selected_path("/new/path")

        assert mock_scan_view._selected_paths == ["/new/path"]
        assert len(mock_scan_view._selected_paths) == 1


# Basic verification test
def test_scan_view_multi_path_basic(mock_gi_modules):
    """
    Basic test function for pytest verification command.

    This test verifies the core multi-path functionality
    using a minimal mock setup.
    """
    mock_scanner_module = mock.MagicMock()
    mock_scanner_module.Scanner = mock.MagicMock()
    mock_scanner_module.ScanResult = mock.MagicMock()
    mock_scanner_module.ScanStatus = mock.MagicMock()

    mock_utils = mock.MagicMock()
    mock_utils.format_scan_path = lambda x: x  # Pass through as string

    with mock.patch.dict(
        sys.modules,
        {
            "src.core.scanner": mock_scanner_module,
            "src.core.quarantine": mock.MagicMock(),
            "src.core.utils": mock_utils,
            "src.ui.profile_dialogs": mock.MagicMock(),
            "src.ui.scan_results_dialog": mock.MagicMock(),
            "src.ui.utils": mock.MagicMock(),
            "src.ui.view_helpers": mock.MagicMock(),
        },
    ):
        from src.ui.scan_view import ScanView

        # Test 1: Class can be imported
        assert ScanView is not None

        # Test 2: Create mock instance and test basic path methods
        view = object.__new__(ScanView)
        view._selected_paths = []
        view._normalized_paths = set()
        # Mock UI elements used by _add_path and _remove_path
        view._paths_placeholder = mock.MagicMock()
        view._paths_listbox = mock.MagicMock()
        view._paths_listbox.get_first_child.return_value = None
        view._create_path_row = mock.MagicMock()
        view._update_selection_header = mock.MagicMock()

        # Test _add_path
        result = view._add_path("/test/path1")
        assert result is True
        assert len(view._selected_paths) == 1

        # Test duplicate detection
        result = view._add_path("/test/path1")
        assert result is False
        assert len(view._selected_paths) == 1

        # Test _add_path with second path
        result = view._add_path("/test/path2")
        assert result is True
        assert len(view._selected_paths) == 2

        # Test _remove_path
        result = view._remove_path("/test/path1")
        assert result is True
        assert len(view._selected_paths) == 1
        assert view._selected_paths == ["/test/path2"]

        # Test _clear_paths
        view._add_path("/test/path3")
        view._clear_paths()
        assert view._selected_paths == []
        # Note: _normalized_paths is NOT cleared by _clear_paths as per implementation

        # Test get_selected_paths returns copy
        view._selected_paths = ["/a", "/b"]
        view._normalized_paths = {"/a", "/b"}
        paths_copy = view.get_selected_paths()
        assert paths_copy == ["/a", "/b"]
        assert paths_copy is not view._selected_paths

        # All tests passed


# =============================================================================
# Scan Worker Tests
# =============================================================================


class TestScanWorker:
    """Tests for the _scan_worker method that performs actual scanning."""

    def _setup_scan_mocks(self, mock_scan_view):
        """Helper to set up common mocks for scan worker tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._eicar_temp_path = ""
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._current_result = None

    def test_scan_worker_single_file_clean(self, mock_scan_view):
        """Test scan worker with a single clean file."""
        self._setup_scan_mocks(mock_scan_view)

        # Create mock ScanResult and ScanStatus
        from unittest.mock import MagicMock

        mock_status = MagicMock()
        mock_status.CLEAN = "clean"
        mock_status.INFECTED = "infected"
        mock_status.ERROR = "error"
        mock_status.CANCELLED = "cancelled"

        mock_result = MagicMock()
        mock_result.status = mock_status.CLEAN
        mock_result.scanned_files = 10
        mock_result.scanned_dirs = 1
        mock_result.infected_count = 0
        mock_result.infected_files = []
        mock_result.threat_details = []
        mock_result.stdout = "Scanned 10 files"
        mock_result.stderr = ""
        mock_result.error_message = None

        mock_scan_view._scanner.scan_sync.return_value = mock_result
        mock_scan_view._selected_paths = ["/home/user/test.txt"]

        # Mock GLib.idle_add to call the callback directly
        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            captured_callbacks = []

            def capture_idle_add(callback, *args):
                captured_callbacks.append((callback, args))
                return True

            mock_glib.idle_add.side_effect = capture_idle_add

            # Import the module fresh
            mock_scan_view._scan_worker()

            # Verify scanner was called with the correct path
            mock_scan_view._scanner.scan_sync.assert_called_once()
            call_args = mock_scan_view._scanner.scan_sync.call_args
            assert call_args[0][0] == "/home/user/test.txt"
            assert call_args[1]["recursive"] is True
            assert call_args[1]["backend_override"] is None
            assert call_args[1]["daemon_force_stream"] is False

            # Verify _on_scan_complete was scheduled
            assert len(captured_callbacks) >= 1

    def test_scan_worker_uses_backend_override(self, mock_scan_view):
        """Test scan worker passes one-shot backend overrides to the scanner."""
        self._setup_scan_mocks(mock_scan_view)

        mock_status = mock.MagicMock()
        mock_status.CLEAN = "clean"
        mock_status.INFECTED = "infected"
        mock_status.ERROR = "error"
        mock_status.CANCELLED = "cancelled"

        mock_result = mock.MagicMock()
        mock_result.status = mock_status.CLEAN
        mock_result.scanned_files = 1
        mock_result.scanned_dirs = 0
        mock_result.infected_count = 0
        mock_result.infected_files = []
        mock_result.threat_details = []
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.error_message = None

        mock_scan_view._scanner.scan_sync.return_value = mock_result
        mock_scan_view._selected_paths = ["/home/user/eicar.txt"]
        mock_scan_view._scan_backend_override = "clamscan"

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_glib.idle_add.side_effect = lambda callback, *args: True

            mock_scan_view._scan_worker()

        mock_scan_view._scanner.scan_sync.assert_called_once()
        call_args = mock_scan_view._scanner.scan_sync.call_args
        assert call_args[1]["backend_override"] == "clamscan"
        assert call_args[1]["daemon_force_stream"] is False

    def test_scan_worker_no_paths_returns_error(self, mock_scan_view):
        """Test scan worker with no paths returns an error result."""
        self._setup_scan_mocks(mock_scan_view)
        mock_scan_view._selected_paths = []

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            with mock.patch("src.ui.scan_view.ScanResult") as mock_scan_result:
                with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
                    mock_scan_status.ERROR = "error"

                    captured_results = []

                    def capture_idle_add(callback, *args):
                        if args:
                            captured_results.append(args[0])
                        return True

                    mock_glib.idle_add.side_effect = capture_idle_add

                    mock_scan_view._scan_worker()

                    # Scanner should not be called
                    mock_scan_view._scanner.scan_sync.assert_not_called()

                    # ScanResult should be constructed with error message
                    mock_scan_result.assert_called_once()
                    call_kwargs = mock_scan_result.call_args[1]
                    assert call_kwargs["error_message"] == "No paths selected for scanning"

    def test_scan_worker_exception_calls_error_handler(self, mock_scan_view):
        """Test scan worker handles exceptions properly."""
        self._setup_scan_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/home/user/test.txt"]
        mock_scan_view._scanner.scan_sync.side_effect = RuntimeError("Scan failed")

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            captured_errors = []

            def capture_idle_add(callback, *args):
                if args and isinstance(args[0], str):
                    captured_errors.append(args[0])
                return True

            mock_glib.idle_add.side_effect = capture_idle_add

            mock_scan_view._scan_worker()

            # Error handler should be called
            assert len(captured_errors) == 1
            assert "Scan failed" in captured_errors[0]


class TestMultiTargetScanning:
    """Tests for multi-target scanning functionality."""

    def _setup_multi_scan_mocks(self, mock_scan_view):
        """Helper to set up mocks for multi-target scan tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._eicar_temp_path = ""
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._current_result = None

    def test_multi_target_scan_iterates_all_paths(self, mock_scan_view):
        """Test that multi-target scan processes all paths."""
        self._setup_multi_scan_mocks(mock_scan_view)

        # Create mock results
        mock_result = mock.MagicMock()
        mock_result.status = mock.MagicMock()
        mock_result.status.value = "clean"
        mock_result.scanned_files = 5
        mock_result.scanned_dirs = 1
        mock_result.infected_count = 0
        mock_result.infected_files = []
        mock_result.threat_details = []
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.error_message = None

        # Make status comparisons work (return False so status != CANCELLED)
        mock_result.status.__eq__ = mock.MagicMock(return_value=False)

        mock_scan_view._scanner.scan_sync.return_value = mock_result
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]
        mock_scan_view._cancel_all_requested = False

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_glib.idle_add.side_effect = lambda callback, *args: True

            # Need to import and patch ScanStatus
            with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
                mock_scan_status.CLEAN = "clean"
                mock_scan_status.INFECTED = "infected"
                mock_scan_status.ERROR = "error"
                mock_scan_status.CANCELLED = "cancelled"

                mock_scan_view._scan_worker()

            # Scanner should be called for each path
            assert mock_scan_view._scanner.scan_sync.call_count == 3
            calls = mock_scan_view._scanner.scan_sync.call_args_list
            assert calls[0][0][0] == "/path1"
            assert calls[1][0][0] == "/path2"
            assert calls[2][0][0] == "/path3"

    def test_multi_target_scan_aggregates_results(self, mock_scan_view):
        """Test that multi-target scan aggregates results correctly."""
        self._setup_multi_scan_mocks(mock_scan_view)

        # Create results with different stats
        def create_result(files, infected):
            result = mock.MagicMock()
            result.status = mock.MagicMock()
            result.scanned_files = files
            result.scanned_dirs = 1
            result.infected_count = infected
            result.infected_files = [f"infected_{i}" for i in range(infected)]
            result.threat_details = []
            result.stdout = f"scanned {files}"
            result.stderr = ""
            result.error_message = None
            return result

        results = [create_result(10, 0), create_result(20, 1), create_result(5, 0)]

        mock_scan_view._scanner.scan_sync.side_effect = results
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]
        mock_scan_view._cancel_all_requested = False

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            with mock.patch("src.ui.scan_view.ScanResult") as mock_scan_result_class:

                def capture_idle_add(callback, *args):
                    return True

                mock_glib.idle_add.side_effect = capture_idle_add

                with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
                    mock_scan_status.CLEAN = "clean"
                    mock_scan_status.INFECTED = "infected"
                    mock_scan_status.ERROR = "error"
                    mock_scan_status.CANCELLED = "cancelled"

                    mock_scan_view._scan_worker()

                # Check aggregated result was constructed correctly
                mock_scan_result_class.assert_called_once()
                call_kwargs = mock_scan_result_class.call_args[1]
                assert call_kwargs["scanned_files"] == 35  # 10 + 20 + 5
                assert call_kwargs["infected_count"] == 1


class TestCancelScan:
    """Tests for scan cancellation functionality."""

    def _setup_cancel_mocks(self, mock_scan_view):
        """Helper to set up mocks for cancel tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._eicar_temp_path = ""
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._current_result = None

    def test_cancel_click_sets_cancel_flag(self, mock_scan_view):
        """Test that cancel button click sets the cancel flag."""
        self._setup_cancel_mocks(mock_scan_view)

        mock_scan_view._cancel_all_requested = False

        mock_scan_view._on_cancel_clicked(mock.MagicMock())

        assert mock_scan_view._cancel_all_requested is True
        mock_scan_view._scanner.cancel.assert_called_once()

    def test_cancel_all_stops_multi_target_scan(self, mock_scan_view):
        """Test that cancel all stops processing remaining targets."""
        self._setup_cancel_mocks(mock_scan_view)

        mock_result = mock.MagicMock()
        mock_result.status = mock.MagicMock()
        mock_result.scanned_files = 5
        mock_result.scanned_dirs = 1
        mock_result.infected_count = 0
        mock_result.infected_files = []
        mock_result.threat_details = []
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.error_message = None

        mock_scan_view._scanner.scan_sync.return_value = mock_result
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]
        mock_scan_view._cancel_all_requested = True  # Already cancelled

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_glib.idle_add.side_effect = lambda callback, *args: True

            with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
                mock_scan_status.CLEAN = "clean"
                mock_scan_status.INFECTED = "infected"
                mock_scan_status.ERROR = "error"
                mock_scan_status.CANCELLED = "cancelled"

                mock_scan_view._scan_worker()

            # Scanner should not be called at all (cancel was set before first scan)
            mock_scan_view._scanner.scan_sync.assert_not_called()

    def test_cancel_during_scan_stops_at_current_target(self, mock_scan_view):
        """Test that cancelling during scan stops after current target and aggregates partial results."""
        self._setup_cancel_mocks(mock_scan_view)

        # Mock ScanStatus
        mock_cancelled_status = mock.MagicMock()

        def create_result_and_cancel(path, **kwargs):
            """Create result and set cancel flag after first scan."""
            mock_scan_view._cancel_all_requested = True
            result = mock.MagicMock()
            result.status = mock_cancelled_status
            result.scanned_files = 5
            result.scanned_dirs = 1
            result.infected_count = 2
            result.infected_files = ["/path1/virus1", "/path1/virus2"]
            result.threat_details = [mock.MagicMock(), mock.MagicMock()]
            result.stdout = ""
            result.stderr = ""
            result.error_message = None
            return result

        mock_scan_view._scanner.scan_sync.side_effect = create_result_and_cancel
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]
        mock_scan_view._cancel_all_requested = False

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_glib.idle_add.side_effect = lambda callback, *args: True

            with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
                mock_scan_status.CLEAN = "clean"
                mock_scan_status.INFECTED = "infected"
                mock_scan_status.ERROR = "error"
                mock_scan_status.CANCELLED = mock_cancelled_status

                with mock.patch("src.ui.scan_view.ScanResult") as mock_scan_result:
                    mock_scan_view._scan_worker()

            # Should only scan first target before cancel takes effect
            assert mock_scan_view._scanner.scan_sync.call_count == 1

            # Verify partial results were aggregated via ScanResult constructor
            mock_scan_result.assert_called_once()
            call_kwargs = mock_scan_result.call_args[1]
            assert call_kwargs["scanned_files"] == 5
            assert call_kwargs["infected_count"] == 2
            assert call_kwargs["infected_files"] == ["/path1/virus1", "/path1/virus2"]
            assert call_kwargs["status"] == mock_cancelled_status


class TestScanComplete:
    """Tests for scan completion handling."""

    def _setup_complete_mocks(self, mock_scan_view):
        """Helper to set up mocks for scan complete tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._eicar_temp_path = ""
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._current_result = None
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._stop_progress_pulse = mock.MagicMock()
        mock_scan_view._show_view_results = mock.MagicMock()
        mock_scan_view._hide_view_results = mock.MagicMock()

    def test_on_scan_complete_clean_result(self, mock_scan_view):
        """Test scan complete handler with clean result."""
        self._setup_complete_mocks(mock_scan_view)

        # Create a clean result enum-like object
        clean_status = mock.MagicMock()
        clean_status.value = "clean"

        result = mock.MagicMock()
        result.status = clean_status
        result.infected_count = 0
        result.error_message = None
        result.stderr = ""

        # Make status comparison work for CLEAN
        with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
            mock_scan_status.CLEAN = clean_status
            mock_scan_status.INFECTED = mock.MagicMock()
            mock_scan_status.ERROR = mock.MagicMock()
            mock_scan_status.CANCELLED = mock.MagicMock()

            mock_scan_view._on_scan_complete(result)

        # Verify UI state updates
        assert mock_scan_view._is_scanning is False
        mock_scan_view._scan_button.set_sensitive.assert_called_with(True)
        mock_scan_view._eicar_button.set_sensitive.assert_called_with(True)
        mock_scan_view._selection_group.set_sensitive.assert_called_with(True)
        mock_scan_view._cancel_button.set_visible.assert_called_with(False)
        mock_scan_view._stop_progress_pulse.assert_called_once()
        mock_scan_view._show_view_results.assert_called_once_with(0)

    def test_on_scan_complete_infected_result(self, mock_scan_view):
        """Test scan complete handler with infected result."""
        self._setup_complete_mocks(mock_scan_view)

        infected_status = mock.MagicMock()
        infected_status.value = "infected"

        result = mock.MagicMock()
        result.status = infected_status
        result.infected_count = 3
        result.error_message = None

        with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
            mock_scan_status.CLEAN = mock.MagicMock()
            mock_scan_status.INFECTED = infected_status
            mock_scan_status.ERROR = mock.MagicMock()

            mock_scan_view._on_scan_complete(result)

        mock_scan_view._show_view_results.assert_called_once_with(3)
        # Status banner should show warning about threats
        mock_scan_view._status_banner.set_title.assert_called()
        call_arg = mock_scan_view._status_banner.set_title.call_args[0][0]
        assert "3 threat" in call_arg

    def test_on_scan_complete_error_result(self, mock_scan_view):
        """Test scan complete handler with error result."""
        self._setup_complete_mocks(mock_scan_view)
        mock_scan_view._show_status_details = mock.MagicMock()
        mock_scan_view._hide_status_details = mock.MagicMock()

        error_status = mock.MagicMock()
        error_status.value = "error"

        result = mock.MagicMock()
        result.status = error_status
        result.infected_count = 0
        result.error_message = "ClamAV not found"
        result.stderr = (
            "LibClamAV Error: Something went wrong while scanning\n"
            "Bytecode run timed out in interpreter"
        )
        result.stdout = ""

        with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
            mock_scan_status.CLEAN = mock.MagicMock()
            mock_scan_status.INFECTED = mock.MagicMock()
            mock_scan_status.ERROR = error_status

            mock_scan_view._on_scan_complete(result)

        # Status banner should show error
        mock_scan_view._status_banner.set_title.assert_called()
        call_arg = mock_scan_view._status_banner.set_title.call_args[0][0]
        assert "error" in call_arg.lower()
        assert "ClamAV not found" in call_arg
        assert "Bytecode run timed out" not in call_arg
        mock_scan_view._show_status_details.assert_called_once()

    def test_on_scan_complete_cleans_eicar_file(self, mock_scan_view, tmp_path):
        """Test that scan complete cleans up EICAR temp file."""
        self._setup_complete_mocks(mock_scan_view)

        # Create actual temp file
        eicar_file = tmp_path / "eicar_test.txt"
        eicar_file.write_text("test content")
        mock_scan_view._eicar_temp_path = str(eicar_file)

        clean_status = mock.MagicMock()
        result = mock.MagicMock()
        result.status = clean_status
        result.infected_count = 0
        result.error_message = None
        result.stderr = ""

        with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
            mock_scan_status.CLEAN = clean_status
            mock_scan_status.INFECTED = mock.MagicMock()
            mock_scan_status.ERROR = mock.MagicMock()

            mock_scan_view._on_scan_complete(result)

        # EICAR file should be deleted
        assert not eicar_file.exists()
        assert mock_scan_view._eicar_temp_path == ""

    def test_on_scan_complete_notifies_state_change_callback(self, mock_scan_view):
        """Test that scan complete notifies external state change callback."""
        self._setup_complete_mocks(mock_scan_view)

        callback = mock.MagicMock()
        mock_scan_view._on_scan_state_changed = callback
        mock_scan_view._is_scanning = True

        clean_status = mock.MagicMock()
        result = mock.MagicMock()
        result.status = clean_status
        result.infected_count = 0
        result.error_message = None
        result.stderr = ""

        with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
            mock_scan_status.CLEAN = clean_status
            mock_scan_status.INFECTED = mock.MagicMock()
            mock_scan_status.ERROR = mock.MagicMock()

            mock_scan_view._on_scan_complete(result)

        callback.assert_called_once_with(False, result)


class TestScanError:
    """Tests for scan error handling."""

    def _setup_error_mocks(self, mock_scan_view):
        """Helper to set up mocks for error tests."""
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._eicar_temp_path = ""
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._stop_progress_pulse = mock.MagicMock()

    def test_on_scan_error_updates_ui_state(self, mock_scan_view):
        """Test that scan error handler updates UI state correctly."""
        self._setup_error_mocks(mock_scan_view)
        mock_scan_view._is_scanning = True

        with mock.patch("src.ui.scan_view.set_status_class"):
            mock_scan_view._on_scan_error("Test error message")

        assert mock_scan_view._is_scanning is False
        mock_scan_view._scan_button.set_sensitive.assert_called_with(True)
        mock_scan_view._eicar_button.set_sensitive.assert_called_with(True)
        mock_scan_view._selection_group.set_sensitive.assert_called_with(True)
        mock_scan_view._cancel_button.set_visible.assert_called_with(False)
        mock_scan_view._stop_progress_pulse.assert_called_once()

    def test_on_scan_error_shows_error_message(self, mock_scan_view):
        """Test that scan error displays error message in status banner."""
        self._setup_error_mocks(mock_scan_view)
        mock_scan_view._show_status_details = mock.MagicMock()
        mock_scan_view._hide_status_details = mock.MagicMock()

        with mock.patch("src.ui.scan_view.set_status_class"):
            mock_scan_view._on_scan_error("ClamAV process crashed\nTraceback line 2")

        mock_scan_view._status_banner.set_title.assert_called()
        call_arg = mock_scan_view._status_banner.set_title.call_args[0][0]
        assert "ClamAV process crashed" in call_arg
        assert "Traceback line 2" not in call_arg
        mock_scan_view._show_status_details.assert_called_once()

    def test_on_scan_error_cleans_eicar_file(self, mock_scan_view, tmp_path):
        """Test that scan error cleans up EICAR temp file."""
        self._setup_error_mocks(mock_scan_view)

        eicar_file = tmp_path / "eicar_error_test.txt"
        eicar_file.write_text("test")
        mock_scan_view._eicar_temp_path = str(eicar_file)

        with mock.patch("src.ui.scan_view.set_status_class"):
            mock_scan_view._on_scan_error("Error")

        assert not eicar_file.exists()
        assert mock_scan_view._eicar_temp_path == ""


class TestStatusDetails:
    """Tests for the scan status detail panel actions."""

    def test_copy_status_details_uses_clipboard_helper(self, mock_scan_view):
        """Copy action should delegate to ClipboardHelper with the stored detail text."""
        mock_scan_view._status_detail_content = "Detailed scan output"

        with mock.patch("src.ui.scan_view.ClipboardHelper") as mock_helper_class:
            helper = mock_helper_class.return_value

            mock_scan_view._on_copy_status_details_clicked(mock.MagicMock())

        mock_helper_class.assert_called_once_with(parent_widget=mock_scan_view)
        helper.copy_with_feedback.assert_called_once()
        assert helper.copy_with_feedback.call_args.kwargs["text"] == "Detailed scan output"

    def test_fullscreen_status_details_opens_dialog(self, mock_scan_view):
        """Fullscreen action should open the fullscreen dialog with the stored detail text."""
        mock_scan_view._status_detail_content = "Detailed scan output"
        mock_scan_view._status_detail_title_text = "Detailed scan error output"
        mock_root = mock.MagicMock()
        mock_scan_view.get_root.return_value = mock_root

        with mock.patch("src.ui.scan_view.FullscreenLogDialog") as mock_dialog_class:
            dialog = mock_dialog_class.return_value

            mock_scan_view._on_fullscreen_status_details_clicked(mock.MagicMock())

        mock_dialog_class.assert_called_once_with(
            title="Detailed scan error output",
            content="Detailed scan output",
        )
        dialog.set_transient_for.assert_called_once_with(mock_root)
        dialog.present.assert_called_once_with()


class TestProgressUpdates:
    """Tests for progress bar and label updates."""

    def _setup_progress_mocks(self, mock_scan_view):
        """Helper to set up mocks for progress tests."""
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._is_scanning = True

    def _make_progress(
        self,
        files_scanned: int = 1,
        files_total: int | None = None,
        infected_count: int = 0,
        current_file: str = "/tmp/file.txt",
        percentage: float | None = None,
    ):
        """Create a lightweight progress object for UI update tests."""
        progress = mock.MagicMock()
        progress.files_scanned = files_scanned
        progress.files_total = files_total
        progress.infected_count = infected_count
        progress.infected_files = []
        progress.infected_threats = {}
        progress.current_file = current_file
        progress.percentage = percentage
        progress.estimate_exceeded = False
        return progress

    def test_start_progress_pulse_creates_timeout(self, mock_scan_view):
        """Test that starting progress pulse creates a GLib timeout."""
        self._setup_progress_mocks(mock_scan_view)

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_glib.timeout_add.return_value = 123

            mock_scan_view._start_progress_pulse()

            mock_glib.timeout_add.assert_called_once()
            assert mock_scan_view._pulse_timeout_id == 123

    def test_start_progress_pulse_no_double_start(self, mock_scan_view):
        """Test that starting progress pulse when already pulsing does nothing."""
        self._setup_progress_mocks(mock_scan_view)
        mock_scan_view._pulse_timeout_id = 456  # Already pulsing

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_scan_view._start_progress_pulse()

            mock_glib.timeout_add.assert_not_called()
            assert mock_scan_view._pulse_timeout_id == 456

    def test_stop_progress_pulse_removes_timeout(self, mock_scan_view):
        """Test that stopping progress pulse removes the timeout."""
        self._setup_progress_mocks(mock_scan_view)
        mock_scan_view._pulse_timeout_id = 789

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_scan_view._stop_progress_pulse()

            mock_glib.source_remove.assert_called_once_with(789)
            assert mock_scan_view._pulse_timeout_id is None

    def test_stop_progress_pulse_hides_section(self, mock_scan_view):
        """Test that stopping progress pulse hides the progress section."""
        self._setup_progress_mocks(mock_scan_view)
        mock_scan_view._pulse_timeout_id = None

        with mock.patch("src.ui.scan_view.GLib"):
            mock_scan_view._stop_progress_pulse()

            mock_scan_view._progress_section.set_visible.assert_called_with(False)

    def test_update_scan_progress_single_target(self, mock_scan_view):
        """Test progress update for single target scan."""
        self._setup_progress_mocks(mock_scan_view)

        with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
            mock_scan_view._update_scan_progress(1, 1, "/test/path")

        mock_scan_view._progress_label.set_label.assert_called_once()
        label = mock_scan_view._progress_label.set_label.call_args[0][0]
        assert "Scanning" in label

    def test_update_scan_progress_multi_target(self, mock_scan_view):
        """Test progress update for multi-target scan."""
        self._setup_progress_mocks(mock_scan_view)

        with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
            mock_scan_view._update_scan_progress(2, 5, "/test/path")

        label = mock_scan_view._progress_label.set_label.call_args[0][0]
        assert "2 of 5" in label

    def test_update_scan_progress_truncates_long_path(self, mock_scan_view):
        """Test that progress update truncates very long paths."""
        self._setup_progress_mocks(mock_scan_view)

        long_path = "/very/long/path/that/exceeds/forty/characters/limit/completely"
        with mock.patch("src.ui.scan_view.format_scan_path", return_value=long_path):
            mock_scan_view._update_scan_progress(1, 1, long_path)

        label = mock_scan_view._progress_label.set_label.call_args[0][0]
        # Label should be truncated (contains "...")
        assert "..." in label or len(label) < len(long_path) + 20

    def test_update_scan_progress_sets_cumulative_baseline(self, mock_scan_view):
        """Test that target progress update stores completed-file baseline."""
        self._setup_progress_mocks(mock_scan_view)
        mock_scan_view._progress_session_id = 7

        with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
            mock_scan_view._update_scan_progress(
                2,
                3,
                "/test/path",
                scan_session_id=7,
                completed_files_before_target=42,
            )

        assert mock_scan_view._cumulative_files_scanned == 42
        assert mock_scan_view._last_progress_update == 0.0

    def test_update_live_progress_ignores_stale_session(self, mock_scan_view):
        """Test stale session callbacks do not mutate UI."""
        self._setup_progress_mocks(mock_scan_view)
        mock_scan_view._updates_paused = False
        mock_scan_view._progress_session_id = 5
        mock_scan_view._apply_progress_updates = mock.MagicMock()

        progress = self._make_progress(files_scanned=2)
        result = mock_scan_view._update_live_progress(
            progress, scan_session_id=4, target_idx=1, completed_files_before_target=0
        )

        assert result is False
        mock_scan_view._apply_progress_updates.assert_not_called()

    def test_update_live_progress_ignores_stale_target(self, mock_scan_view):
        """Test stale target callbacks do not mutate UI."""
        self._setup_progress_mocks(mock_scan_view)
        mock_scan_view._updates_paused = False
        mock_scan_view._progress_session_id = 6
        mock_scan_view._current_target_idx = 2
        mock_scan_view._apply_progress_updates = mock.MagicMock()

        progress = self._make_progress(files_scanned=2)
        result = mock_scan_view._update_live_progress(
            progress, scan_session_id=6, target_idx=1, completed_files_before_target=0
        )

        assert result is False
        mock_scan_view._apply_progress_updates.assert_not_called()

    def test_apply_progress_updates_uses_target_baseline(self, mock_scan_view):
        """Test cumulative stat uses passed baseline for the current target."""
        self._setup_progress_mocks(mock_scan_view)
        mock_scan_view._total_target_count = 2
        mock_scan_view._current_target_idx = 2

        progress = self._make_progress(files_scanned=3, files_total=10)
        with mock.patch.object(mock_scan_view, "_format_path_for_display", return_value="file.txt"):
            mock_scan_view._apply_progress_updates(progress, completed_files_before_target=7)

        title_text = mock_scan_view._stats_row.set_title.call_args[0][0]
        subtitle_text = mock_scan_view._stats_row.set_subtitle.call_args[0][0]
        assert "3" in title_text
        assert "10" in title_text
        assert "10" in subtitle_text  # 7 completed + 3 current target

    def test_progress_callback_throttle_is_target_scoped(self, mock_scan_view):
        """Test callback throttling still preserves first and delayed updates."""
        self._setup_progress_mocks(mock_scan_view)

        callback = mock_scan_view._create_progress_callback(
            scan_session_id=9,
            target_idx=3,
            completed_files_before_target=11,
        )
        progress = self._make_progress(files_scanned=1, infected_count=0)

        with (
            mock.patch("src.ui.scan_view.time.monotonic", side_effect=[1.0, 1.05, 1.20]),
            mock.patch("src.ui.scan_view.GLib") as mock_glib,
        ):
            callback(progress)  # allowed (first update)
            callback(progress)  # throttled
            callback(progress)  # allowed

        assert mock_glib.idle_add.call_count == 2
        first_call = mock_glib.idle_add.call_args_list[0][0]
        assert first_call[0] == mock_scan_view._update_live_progress
        assert first_call[2] == 9
        assert first_call[3] == 3
        assert first_call[4] == 11

    def test_progress_callback_bypasses_throttle_on_new_threat(self, mock_scan_view):
        """Test threat updates bypass throttle so threat list stays live."""
        self._setup_progress_mocks(mock_scan_view)

        callback = mock_scan_view._create_progress_callback(
            scan_session_id=2,
            target_idx=1,
            completed_files_before_target=0,
        )
        normal = self._make_progress(files_scanned=1, infected_count=0)
        threat = self._make_progress(files_scanned=2, infected_count=1)

        with (
            mock.patch("src.ui.scan_view.time.monotonic", side_effect=[1.0, 1.05]),
            mock.patch("src.ui.scan_view.GLib") as mock_glib,
        ):
            callback(normal)  # first update
            callback(threat)  # new threat, should bypass throttle

        assert mock_glib.idle_add.call_count == 2


class TestStartScanning:
    """Tests for the _start_scanning method that initiates scans."""

    def _setup_start_mocks(self, mock_scan_view):
        """Helper to set up mocks for start scanning tests."""
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._hide_view_results = mock.MagicMock()
        mock_scan_view._start_progress_pulse = mock.MagicMock()

    def test_start_scanning_sets_scanning_state(self, mock_scan_view):
        """Test that start scanning sets the is_scanning flag."""
        self._setup_start_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
                mock_scan_view._start_scanning()

        assert mock_scan_view._is_scanning is True
        assert mock_scan_view._cancel_all_requested is False

    def test_start_scanning_disables_buttons(self, mock_scan_view):
        """Test that start scanning disables scan and EICAR buttons."""
        self._setup_start_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
                mock_scan_view._start_scanning()

        mock_scan_view._scan_button.set_sensitive.assert_called_with(False)
        mock_scan_view._eicar_button.set_sensitive.assert_called_with(False)
        mock_scan_view._selection_group.set_sensitive.assert_called_with(False)

    def test_start_scanning_shows_cancel_button(self, mock_scan_view):
        """Test that start scanning shows the cancel button."""
        self._setup_start_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
                mock_scan_view._start_scanning()

        mock_scan_view._cancel_button.set_visible.assert_called_with(True)

    def test_start_scanning_multi_target_sets_cancel_all_label(self, mock_scan_view):
        """Test that multi-target scan shows 'Cancel All' button label."""
        self._setup_start_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/path"):
                mock_scan_view._start_scanning()

        mock_scan_view._cancel_button.set_label.assert_called_with("Cancel All")

    def test_start_scanning_single_target_sets_cancel_label(self, mock_scan_view):
        """Test that single target scan shows 'Cancel' button label."""
        self._setup_start_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/single/path"]

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/single/path"):
                mock_scan_view._start_scanning()

        mock_scan_view._cancel_button.set_label.assert_called_with("Cancel")

    def test_start_scanning_hides_previous_results(self, mock_scan_view):
        """Test that start scanning hides any previous results."""
        self._setup_start_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
                mock_scan_view._start_scanning()

        mock_scan_view._hide_view_results.assert_called_once()

    def test_start_scanning_notifies_state_callback(self, mock_scan_view):
        """Test that start scanning notifies external state callback."""
        self._setup_start_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]
        callback = mock.MagicMock()
        mock_scan_view._on_scan_state_changed = callback

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
                mock_scan_view._start_scanning()

        callback.assert_called_once_with(True)

    def test_start_scanning_shows_progress_section(self, mock_scan_view):
        """Test that start scanning shows the progress section."""
        self._setup_start_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
                mock_scan_view._start_scanning()

        mock_scan_view._progress_section.set_visible.assert_called_with(True)
        mock_scan_view._start_progress_pulse.assert_called_once()


class TestOnScanClicked:
    """Tests for the _on_scan_clicked handler."""

    def _setup_click_mocks(self, mock_scan_view):
        """Helper to set up mocks for scan click tests."""
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._hide_view_results = mock.MagicMock()
        mock_scan_view._start_progress_pulse = mock.MagicMock()
        mock_scan_view._check_database_and_prompt = mock.MagicMock(return_value=True)

    def test_scan_click_with_no_paths_shows_warning(self, mock_scan_view):
        """Test that clicking scan with no paths shows a warning."""
        self._setup_click_mocks(mock_scan_view)
        mock_scan_view._selected_paths = []

        with mock.patch("src.ui.scan_view.set_status_class"):
            mock_scan_view._on_scan_clicked(mock.MagicMock())

        mock_scan_view._status_banner.set_title.assert_called()
        call_arg = mock_scan_view._status_banner.set_title.call_args[0][0]
        assert "select" in call_arg.lower()
        mock_scan_view._status_banner.set_revealed.assert_called_with(True)

    def test_scan_click_with_paths_starts_scan(self, mock_scan_view):
        """Test that clicking scan with paths starts scanning."""
        self._setup_click_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
                mock_scan_view._on_scan_clicked(mock.MagicMock())

        assert mock_scan_view._is_scanning is True


class TestViewResults:
    """Tests for view results functionality."""

    def test_show_view_results_no_threats(self, mock_scan_view):
        """Test showing view results button with no threats."""
        mock_scan_view._show_view_results(0)

        mock_scan_view._view_results_button.set_label.assert_called()
        label = mock_scan_view._view_results_button.set_label.call_args[0][0]
        assert "Results" in label
        mock_scan_view._view_results_section.set_visible.assert_called_with(True)

    def test_show_view_results_with_threats(self, mock_scan_view):
        """Test showing view results button with threats."""
        mock_scan_view._show_view_results(5)

        label = mock_scan_view._view_results_button.set_label.call_args[0][0]
        assert "5" in label
        assert "Threat" in label

    def test_hide_view_results(self, mock_scan_view):
        """Test hiding view results section."""
        mock_scan_view._hide_view_results()

        mock_scan_view._view_results_section.set_visible.assert_called_with(False)

    def test_on_view_results_clicked_no_result(self, mock_scan_view):
        """Test view results click with no current result."""
        mock_scan_view._current_result = None

        # Should return without error
        mock_scan_view._on_view_results_clicked(mock.MagicMock())
        # No crash is the success condition

    def test_on_view_results_clicked_no_root(self, mock_scan_view):
        """Test view results click with no root window."""
        mock_scan_view._current_result = mock.MagicMock()
        mock_scan_view.get_root.return_value = None

        # Should return without error
        mock_scan_view._on_view_results_clicked(mock.MagicMock())


class TestEicarTest:
    """Tests for EICAR test functionality."""

    def _setup_eicar_mocks(self, mock_scan_view):
        """Helper to set up mocks for EICAR tests."""
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._hide_view_results = mock.MagicMock()
        mock_scan_view._start_progress_pulse = mock.MagicMock()
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._paths_listbox.get_first_child.return_value = None
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        mock_scan_view._check_database_and_prompt = mock.MagicMock(return_value=True)

    def test_eicar_test_creates_temp_file(self, mock_scan_view, tmp_path):
        """Test that EICAR test creates a temporary test file."""
        self._setup_eicar_mocks(mock_scan_view)

        eicar_path = str(tmp_path / "eicar_test.txt")
        with mock.patch(
            "src.ui.scan_view.create_eicar_temp", return_value=eicar_path
        ) as mock_create:
            with mock.patch("src.ui.scan_view.register_eicar_atexit_cleanup"):
                with mock.patch("src.ui.scan_view.is_flatpak", return_value=False):
                    with mock.patch("src.ui.scan_view.GLib"):
                        with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test"):
                            mock_scan_view._on_eicar_test_clicked(mock.MagicMock())

            # Verify temp file was created
            mock_create.assert_called_once()
            # Non-Flatpak: parent_dir should be None (system default)
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("parent_dir") is None

    def test_eicar_test_uses_cache_dir_in_flatpak(self, mock_scan_view, tmp_path):
        """Test that EICAR test uses ~/.cache/clamui directory in Flatpak.

        In Flatpak, /tmp is sandboxed and not accessible to host commands.
        We use ~/.cache/clamui/ which is accessible via --filesystem=host.
        """
        self._setup_eicar_mocks(mock_scan_view)

        eicar_path = "/home/test/.cache/clamui/eicar_test.txt"
        with mock.patch(
            "src.ui.scan_view.create_eicar_temp", return_value=eicar_path
        ) as mock_create:
            with mock.patch("src.ui.scan_view.register_eicar_atexit_cleanup"):
                with mock.patch("src.ui.scan_view.is_flatpak", return_value=True):
                    with mock.patch("src.ui.scan_view.Path") as mock_path:
                        mock_home = mock.MagicMock()
                        mock_cache_dir = mock.MagicMock()
                        mock_cache_dir.__str__ = mock.MagicMock(
                            return_value="/home/test/.cache/clamui"
                        )
                        mock_home.__truediv__ = mock.MagicMock(return_value=mock_cache_dir)
                        mock_cache_dir.__truediv__ = mock.MagicMock(return_value=mock_cache_dir)
                        mock_path.home.return_value = mock_home
                        with mock.patch("src.ui.scan_view.GLib"):
                            with mock.patch(
                                "src.ui.scan_view.format_scan_path", return_value="/test"
                            ):
                                mock_scan_view._on_eicar_test_clicked(mock.MagicMock())

            # Verify cache dir was used (not /tmp)
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["parent_dir"] == "/home/test/.cache/clamui"

    def test_eicar_test_handles_oserror(self, mock_scan_view):
        """Test that EICAR test handles OSError gracefully."""
        self._setup_eicar_mocks(mock_scan_view)

        with mock.patch(
            "src.ui.scan_view.create_eicar_temp",
            side_effect=OSError("Permission denied"),
        ):
            with mock.patch("src.ui.scan_view.register_eicar_atexit_cleanup"):
                with mock.patch("src.ui.scan_view.is_flatpak", return_value=False):
                    with mock.patch("src.ui.scan_view.set_status_class"):
                        mock_scan_view._on_eicar_test_clicked(mock.MagicMock())

            # Should show error in status banner
            mock_scan_view._status_banner.set_title.assert_called()
            call_arg = mock_scan_view._status_banner.set_title.call_args[0][0]
            assert "Failed" in call_arg or "error" in call_arg.lower()

    def test_eicar_test_forces_daemon_stream_when_daemon_active(self, mock_scan_view, tmp_path):
        """EICAR self-test should keep clamdscan but force --stream."""
        self._setup_eicar_mocks(mock_scan_view)
        mock_scan_view._scanner.get_active_backend.return_value = "daemon"
        mock_scan_view._set_selected_path = mock.MagicMock()
        mock_scan_view._start_scanning = mock.MagicMock()

        eicar_path = str(tmp_path / "eicar_test.txt")
        with mock.patch("src.ui.scan_view.create_eicar_temp", return_value=eicar_path):
            with mock.patch("src.ui.scan_view.register_eicar_atexit_cleanup"):
                with mock.patch("src.ui.scan_view.is_flatpak", return_value=False):
                    mock_scan_view._on_eicar_test_clicked(mock.MagicMock())

        assert mock_scan_view._scan_backend_override == "daemon"
        assert mock_scan_view._scan_daemon_force_stream is True
        mock_scan_view._set_selected_path.assert_called_once_with(eicar_path)
        mock_scan_view._start_scanning.assert_called_once()

    def test_eicar_test_registers_atexit_cleanup_on_create(self, mock_scan_view, tmp_path):
        """Click handler must register atexit cleanup so a force-quit/crash
        does not leave the EICAR file lying around (UI-010)."""
        self._setup_eicar_mocks(mock_scan_view)
        mock_scan_view._set_selected_path = mock.MagicMock()
        mock_scan_view._start_scanning = mock.MagicMock()

        eicar_path = str(tmp_path / "eicar_test.txt")
        with mock.patch("src.ui.scan_view.create_eicar_temp", return_value=eicar_path):
            with mock.patch("src.ui.scan_view.register_eicar_atexit_cleanup") as mock_register:
                mock_register.return_value = lambda: None
                with mock.patch("src.ui.scan_view.is_flatpak", return_value=False):
                    mock_scan_view._on_eicar_test_clicked(mock.MagicMock())

                mock_register.assert_called_once_with(eicar_path)


class TestBackendIndicator:
    """Tests for backend indicator functionality."""

    def test_init_subscribes_to_scan_backend_changes(self, scan_view_class):
        """Test ScanView listens for scan backend setting updates."""
        settings_manager = mock.MagicMock()

        scan_view_class(
            settings_manager=settings_manager,
            quarantine_manager=mock.MagicMock(),
        )

        settings_manager.add_listener.assert_called_once()
        key, callback = settings_manager.add_listener.call_args[0]
        assert key == "scan_backend"
        assert callback.__name__ == "_on_scan_backend_setting_changed"

    def test_update_backend_label_daemon(self, mock_scan_view):
        """Test backend label shows daemon name."""
        mock_scan_view._scanner.get_active_backend.return_value = "daemon"

        mock_scan_view._update_backend_label()

        mock_scan_view._backend_label.set_label.assert_called()
        label = mock_scan_view._backend_label.set_label.call_args[0][0]
        assert "daemon" in label.lower() or "clamd" in label.lower()

    def test_update_backend_label_clamscan(self, mock_scan_view):
        """Test backend label shows clamscan name."""
        mock_scan_view._scanner.get_active_backend.return_value = "clamscan"

        mock_scan_view._update_backend_label()

        label = mock_scan_view._backend_label.set_label.call_args[0][0]
        assert "clamscan" in label.lower()

    def test_update_backend_label_daemon_sets_eicar_tooltip(self, mock_scan_view):
        """Test daemon backend tooltip describes EICAR self-test."""
        mock_scan_view._scanner.get_active_backend.return_value = "daemon"

        mock_scan_view._update_backend_label()

        tooltip = mock_scan_view._eicar_button.set_tooltip_text.call_args[0][0]
        assert "eicar test file" in tooltip.lower()

    def test_update_backend_label_clamscan_sets_base_eicar_tooltip(self, mock_scan_view):
        """Test clamscan backend keeps the base EICAR tooltip text."""
        mock_scan_view._scanner.get_active_backend.return_value = "clamscan"

        mock_scan_view._update_backend_label()

        tooltip = mock_scan_view._eicar_button.set_tooltip_text.call_args[0][0]
        assert "eicar test file" in tooltip.lower()
        assert "cleaned up" not in tooltip.lower()

    def test_backend_setting_change_schedules_refresh(self, mock_scan_view):
        """Test backend setting updates schedule a UI refresh on the GTK loop."""
        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_scan_view._on_scan_backend_setting_changed("daemon")

        mock_glib.idle_add.assert_called_once_with(mock_scan_view._refresh_backend_indicator)

    def test_refresh_backend_indicator_updates_label(self, mock_scan_view):
        """Test backend indicator refresh calls the shared label updater."""
        mock_scan_view._update_backend_label = mock.MagicMock()

        result = mock_scan_view._refresh_backend_indicator()

        mock_scan_view._update_backend_label.assert_called_once_with()
        assert result is False


class TestScanStateCallbacks:
    """Tests for scan state change callback functionality."""

    def test_set_on_scan_state_changed(self, mock_scan_view):
        """Test setting scan state change callback."""
        callback = mock.MagicMock()

        mock_scan_view.set_on_scan_state_changed(callback)

        assert mock_scan_view._on_scan_state_changed == callback

    def test_set_scan_state_changed_callback_alias(self, mock_scan_view):
        """Test the backwards compatibility alias."""
        callback = mock.MagicMock()

        mock_scan_view.set_scan_state_changed_callback(callback)

        assert mock_scan_view._on_scan_state_changed == callback


class TestSelectedProfile:
    """Tests for profile selection getters and setters."""

    def test_get_selected_profile(self, mock_scan_view):
        """Test getting selected profile."""
        mock_profile = mock.MagicMock()
        mock_scan_view._selected_profile = mock_profile

        result = mock_scan_view.get_selected_profile()

        assert result == mock_profile

    def test_get_selected_profile_none(self, mock_scan_view):
        """Test getting selected profile when none selected."""
        mock_scan_view._selected_profile = None

        result = mock_scan_view.get_selected_profile()

        assert result is None

    def test_set_selected_profile_found(self, mock_scan_view):
        """Test setting selected profile by ID when found."""
        mock_profile = mock.MagicMock()
        mock_profile.id = "test-profile-id"
        mock_scan_view._profile_list = [mock_profile]

        result = mock_scan_view.set_selected_profile("test-profile-id")

        assert result is True
        assert mock_scan_view._selected_profile == mock_profile
        mock_scan_view._profile_dropdown.set_selected.assert_called_with(1)

    def test_set_selected_profile_not_found(self, mock_scan_view):
        """Test setting selected profile by ID when not found."""
        mock_profile = mock.MagicMock()
        mock_profile.id = "other-id"
        mock_scan_view._profile_list = [mock_profile]

        result = mock_scan_view.set_selected_profile("nonexistent-id")

        assert result is False

    def test_set_selected_profile_no_dropdown(self, mock_scan_view):
        """Test setting profile with no dropdown returns False."""
        mock_scan_view._profile_dropdown = None

        result = mock_scan_view.set_selected_profile("any-id")

        assert result is False

    def test_set_selected_profile_empty_list(self, mock_scan_view):
        """Test setting profile with empty list returns False."""
        mock_scan_view._profile_list = []

        result = mock_scan_view.set_selected_profile("any-id")

        assert result is False


class TestDragDropVisualFeedback:
    """Tests for drag-and-drop visual feedback."""

    def test_on_drag_enter_adds_css_class(self, mock_scan_view):
        """Test that drag enter adds visual feedback CSS class."""
        mock_scan_view._on_drag_enter(None, 0, 0)

        mock_scan_view.add_css_class.assert_called_with("drop-active")

    def test_on_drag_leave_removes_css_class(self, mock_scan_view):
        """Test that drag leave removes visual feedback CSS class."""
        mock_scan_view._on_drag_leave(None)

        mock_scan_view.remove_css_class.assert_called_with("drop-active")


class TestStatusBanner:
    """Tests for status banner functionality."""

    def test_on_status_banner_dismissed(self, mock_scan_view):
        """Test that dismissing status banner hides it."""
        mock_banner = mock.MagicMock()

        mock_scan_view._on_status_banner_dismissed(mock_banner)

        mock_banner.set_revealed.assert_called_once_with(False)


class TestShowToast:
    """Tests for toast notification functionality."""

    def test_show_toast_no_root(self, mock_scan_view):
        """Test show toast when no root window."""
        mock_scan_view.get_root.return_value = None

        # Should not raise
        mock_scan_view._show_toast("Test message")

    def test_show_toast_with_root_no_add_toast(self, mock_scan_view):
        """Test show toast when root has no add_toast method."""
        mock_root = mock.MagicMock(spec=[])  # No add_toast method
        mock_scan_view.get_root.return_value = mock_root

        # Should not raise
        mock_scan_view._show_toast("Test message")

    def test_show_toast_with_add_toast(self, mock_scan_view):
        """Test show toast when root has add_toast method."""
        mock_root = mock.MagicMock()
        mock_scan_view.get_root.return_value = mock_root

        with mock.patch("src.ui.scan_view.Adw") as mock_adw:
            mock_toast = mock.MagicMock()
            mock_adw.Toast.new.return_value = mock_toast

            mock_scan_view._show_toast("Test message")

            mock_adw.Toast.new.assert_called_once_with("Test message")
            mock_root.add_toast.assert_called_once_with(mock_toast)


class TestStartScan:
    """Tests for the _start_scan method."""

    def _setup_start_scan_mocks(self, mock_scan_view):
        """Helper to set up mocks for start scan tests."""
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._hide_view_results = mock.MagicMock()
        mock_scan_view._start_progress_pulse = mock.MagicMock()
        mock_scan_view._check_database_and_prompt = mock.MagicMock(return_value=True)

    def test_start_scan_calls_on_scan_clicked(self, mock_scan_view):
        """Test that _start_scan calls _on_scan_clicked."""
        self._setup_start_scan_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]

        # Track if _on_scan_clicked was called via the is_scanning flag
        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test/path"):
                mock_scan_view._start_scan()

        # Verify scanning was started
        assert mock_scan_view._is_scanning is True


class TestUpdateSelectionHeader:
    """Tests for the _update_selection_header method."""

    def _setup_header_mocks(self, mock_scan_view):
        """Helper to set up mocks for header tests."""
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._clear_all_button = mock.MagicMock()

    def test_update_header_zero_paths(self, mock_scan_view):
        """Test header update with no paths selected."""
        self._setup_header_mocks(mock_scan_view)
        mock_scan_view._selected_paths = []

        mock_scan_view._update_selection_header()

        mock_scan_view._selection_group.set_title.assert_called()
        title = mock_scan_view._selection_group.set_title.call_args[0][0]
        assert "Target" in title
        mock_scan_view._clear_all_button.set_visible.assert_called_with(False)

    def test_update_header_one_path(self, mock_scan_view):
        """Test header update with one path selected."""
        self._setup_header_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/test/path"]

        mock_scan_view._update_selection_header()

        title = mock_scan_view._selection_group.set_title.call_args[0][0]
        assert "1" in title
        mock_scan_view._clear_all_button.set_visible.assert_called_with(False)

    def test_update_header_multiple_paths(self, mock_scan_view):
        """Test header update with multiple paths selected."""
        self._setup_header_mocks(mock_scan_view)
        mock_scan_view._selected_paths = ["/path1", "/path2", "/path3"]

        mock_scan_view._update_selection_header()

        title = mock_scan_view._selection_group.set_title.call_args[0][0]
        assert "3" in title
        mock_scan_view._clear_all_button.set_visible.assert_called_with(True)


class TestShowDropError:
    """Tests for the _show_drop_error method."""

    def test_show_drop_error_sets_banner(self, mock_scan_view):
        """Test that drop error sets status banner."""
        mock_scan_view._show_toast = mock.MagicMock()

        with mock.patch("src.ui.scan_view.set_status_class"):
            mock_scan_view._show_drop_error("Test error message")

        mock_scan_view._status_banner.set_title.assert_called_with("Test error message")
        mock_scan_view._status_banner.set_revealed.assert_called_with(True)

    def test_show_drop_error_shows_toast(self, mock_scan_view):
        """Test that drop error shows toast notification."""
        mock_scan_view._show_toast = mock.MagicMock()

        with mock.patch("src.ui.scan_view.set_status_class"):
            mock_scan_view._show_drop_error("Error message")

        mock_scan_view._show_toast.assert_called_with("Error message")


class TestRefreshProfiles:
    """Tests for the refresh_profiles method."""

    def _setup_profile_refresh_mocks(self, mock_scan_view):
        """Helper to set up mocks for profile refresh tests."""
        mock_scan_view._profile_string_list = mock.MagicMock()
        mock_scan_view._profile_string_list.get_n_items.return_value = 2

    def test_refresh_profiles_no_manager(self, mock_scan_view):
        """Test refresh profiles when no profile manager available."""
        self._setup_profile_refresh_mocks(mock_scan_view)
        mock_scan_view._get_profile_manager = mock.MagicMock(return_value=None)

        # Should not raise
        mock_scan_view.refresh_profiles()

    def test_refresh_profiles_clears_and_rebuilds_list(self, mock_scan_view):
        """Test that refresh profiles clears and rebuilds the dropdown."""
        self._setup_profile_refresh_mocks(mock_scan_view)
        # Make get_n_items return a proper int (not MagicMock)
        mock_scan_view._profile_string_list.get_n_items.return_value = 2
        # Make get_selected return an int (not MagicMock)
        mock_scan_view._profile_dropdown.get_selected.return_value = 0

        mock_profile_manager = mock.MagicMock()
        mock_profile1 = mock.MagicMock()
        mock_profile1.name = "Quick Scan"
        mock_profile1.id = "quick"
        mock_profile2 = mock.MagicMock()
        mock_profile2.name = "Full Scan"
        mock_profile2.id = "full"
        mock_profile_manager.list_profiles.return_value = [mock_profile1, mock_profile2]

        mock_scan_view._get_profile_manager = mock.MagicMock(return_value=mock_profile_manager)

        mock_scan_view.refresh_profiles()

        # Should remove old items (called for items in the list)
        assert mock_scan_view._profile_string_list.remove.called
        # Should append "No Profile" + 2 profiles
        assert mock_scan_view._profile_string_list.append.called

    def test_refresh_profiles_restores_selection(self, mock_scan_view):
        """Test that refresh profiles tries to restore previous selection."""
        self._setup_profile_refresh_mocks(mock_scan_view)

        mock_profile = mock.MagicMock()
        mock_profile.name = "Test Profile"
        mock_profile.id = "test-id"

        mock_profile_manager = mock.MagicMock()
        mock_profile_manager.list_profiles.return_value = [mock_profile]

        mock_scan_view._get_profile_manager = mock.MagicMock(return_value=mock_profile_manager)
        mock_scan_view._profile_list = [mock_profile]

        # Set current selection to the test profile
        mock_scan_view._profile_dropdown.get_selected.return_value = 1

        mock_scan_view.refresh_profiles()

        # Should try to restore the profile selection
        mock_scan_view._profile_dropdown.set_selected.assert_called()


class TestGetProfileManager:
    """Tests for the _get_profile_manager method."""

    def test_get_profile_manager_no_root(self, mock_scan_view):
        """Test getting profile manager with no root window."""
        mock_scan_view.get_root.return_value = None

        result = mock_scan_view._get_profile_manager()

        assert result is None

    def test_get_profile_manager_root_no_app(self, mock_scan_view):
        """Test getting profile manager with root but no application."""
        mock_root = mock.MagicMock()
        mock_root.get_application.return_value = None
        mock_scan_view.get_root.return_value = mock_root

        result = mock_scan_view._get_profile_manager()

        assert result is None

    def test_get_profile_manager_app_no_profile_manager(self, mock_scan_view):
        """Test getting profile manager when app has no profile_manager."""
        mock_root = mock.MagicMock()
        mock_app = mock.MagicMock(spec=[])  # No profile_manager attribute
        mock_root.get_application.return_value = mock_app
        mock_scan_view.get_root.return_value = mock_root

        result = mock_scan_view._get_profile_manager()

        assert result is None

    def test_get_profile_manager_success(self, mock_scan_view):
        """Test getting profile manager successfully."""
        mock_root = mock.MagicMock()
        mock_app = mock.MagicMock()
        mock_profile_manager = mock.MagicMock()
        mock_app.profile_manager = mock_profile_manager
        mock_root.get_application.return_value = mock_app
        mock_scan_view.get_root.return_value = mock_root

        result = mock_scan_view._get_profile_manager()

        assert result == mock_profile_manager


class TestOnManageProfilesClicked:
    """Tests for the _on_manage_profiles_clicked handler."""

    def test_manage_profiles_no_root(self, mock_scan_view):
        """Test manage profiles button with no root window."""
        mock_scan_view.get_root.return_value = None

        # Should not raise
        mock_scan_view._on_manage_profiles_clicked(mock.MagicMock())

    def test_manage_profiles_root_not_window(self, mock_scan_view):
        """Test manage profiles button when root is not a Gtk.Window."""
        mock_root = mock.MagicMock()
        mock_scan_view.get_root.return_value = mock_root

        with mock.patch("src.ui.scan_view.Gtk") as mock_gtk:
            mock_gtk.Window = type("Window", (), {})  # Different class
            # Should not raise
            mock_scan_view._on_manage_profiles_clicked(mock.MagicMock())


class TestOnProfilesDialogClosed:
    """Tests for the _on_profiles_dialog_closed handler."""

    def test_profiles_dialog_closed_refreshes(self, mock_scan_view):
        """Test that closing profiles dialog refreshes the dropdown."""
        mock_scan_view.refresh_profiles = mock.MagicMock()

        mock_scan_view._on_profiles_dialog_closed(mock.MagicMock())

        mock_scan_view.refresh_profiles.assert_called_once()


class TestOnProfileRunFromDialog:
    """Tests for the _on_profile_run_from_dialog handler."""

    def _setup_run_mocks(self, mock_scan_view):
        """Helper to set up mocks for profile run tests."""
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._hide_view_results = mock.MagicMock()
        mock_scan_view._start_progress_pulse = mock.MagicMock()

    def test_profile_run_from_dialog(self, mock_scan_view):
        """Test running a profile from the dialog."""
        self._setup_run_mocks(mock_scan_view)
        mock_scan_view.refresh_profiles = mock.MagicMock()
        mock_scan_view.set_selected_profile = mock.MagicMock(return_value=True)
        mock_scan_view._selected_paths = ["/test/path"]

        mock_profile = mock.MagicMock()
        mock_profile.id = "test-profile"

        with mock.patch("src.ui.scan_view.GLib"):
            with mock.patch("src.ui.scan_view.format_scan_path", return_value="/test"):
                mock_scan_view._on_profile_run_from_dialog(mock_profile)

        mock_scan_view.refresh_profiles.assert_called_once()
        mock_scan_view.set_selected_profile.assert_called_once_with("test-profile")


class TestOnRealizeLoadProfiles:
    """Tests for the _on_realize_load_profiles handler."""

    def test_realize_loads_profiles(self, mock_scan_view):
        """Test that realizing the widget loads profiles."""
        mock_scan_view.refresh_profiles = mock.MagicMock()

        mock_scan_view._on_realize_load_profiles(mock.MagicMock())

        mock_scan_view.refresh_profiles.assert_called_once()


class TestRunScanAsync:
    """Tests for the _run_scan_async method."""

    def test_run_scan_async_starts_thread(self, mock_scan_view):
        """Test that run_scan_async starts a background thread."""
        mock_scan_view._scan_worker = mock.MagicMock()

        import threading

        with mock.patch.object(threading, "Thread") as mock_thread_class:
            mock_thread = mock.MagicMock()
            mock_thread_class.return_value = mock_thread

            result = mock_scan_view._run_scan_async()

            mock_thread_class.assert_called_once()
            mock_thread.start.assert_called_once()
            assert result is False  # Should return False to not repeat


class TestDropWithValidationErrors:
    """Tests for drop handling with validation errors."""

    def _setup_drop_mocks(self, mock_scan_view):
        """Helper to set up mocks for drop tests."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        mock_scan_view._show_drop_error = mock.MagicMock()

    def test_drop_with_validation_errors_shows_first_error(self, mock_scan_view):
        """Test that drop with validation errors shows the first error."""
        self._setup_drop_mocks(mock_scan_view)

        mock_file = mock.MagicMock()
        mock_file.get_path.return_value = "/remote/file"

        mock_file_list = mock.MagicMock()
        mock_file_list.get_files.return_value = [mock_file]

        with mock.patch("src.ui.scan_view.validate_dropped_files") as mock_validate:
            mock_validate.return_value = ([], ["File not accessible", "Path error"])

            result = mock_scan_view._on_drop(None, mock_file_list, 0, 0)

        assert result is False
        mock_scan_view._show_drop_error.assert_called_with("File not accessible")

    def test_drop_no_valid_paths_no_errors(self, mock_scan_view):
        """Test drop with no valid paths and no specific errors."""
        self._setup_drop_mocks(mock_scan_view)

        mock_file = mock.MagicMock()
        mock_file.get_path.return_value = None

        mock_file_list = mock.MagicMock()
        mock_file_list.get_files.return_value = [mock_file]

        with mock.patch("src.ui.scan_view.validate_dropped_files") as mock_validate:
            mock_validate.return_value = ([], [])

            result = mock_scan_view._on_drop(None, mock_file_list, 0, 0)

        assert result is False
        mock_scan_view._show_drop_error.assert_called_with("Unable to accept dropped files")


class TestProgressLabelNone:
    """Tests for handling None progress label."""

    def test_update_scan_progress_no_label(self, mock_scan_view):
        """Test progress update when label is None."""
        mock_scan_view._progress_label = None

        # Should not raise
        mock_scan_view._update_scan_progress(1, 1, "/test/path")


class TestShowViewResultsNone:
    """Tests for show_view_results when components are None."""

    def test_show_view_results_button_none(self, mock_scan_view):
        """Test show view results when button is None."""
        mock_scan_view._view_results_button = None
        mock_scan_view._view_results_section = mock.MagicMock()

        # Should return early without error
        mock_scan_view._show_view_results(0)

    def test_show_view_results_section_none(self, mock_scan_view):
        """Test show view results when section is None."""
        mock_scan_view._view_results_button = mock.MagicMock()
        mock_scan_view._view_results_section = None

        # Should return early without error
        mock_scan_view._show_view_results(0)


class TestHideViewResultsNone:
    """Tests for hide_view_results when section is None."""

    def test_hide_view_results_section_none(self, mock_scan_view):
        """Test hide view results when section is None."""
        mock_scan_view._view_results_section = None

        # Should not raise
        mock_scan_view._hide_view_results()


class TestStopProgressPulseNoId:
    """Tests for stop_progress_pulse when no timeout is set."""

    def test_stop_progress_pulse_no_timeout_id(self, mock_scan_view):
        """Test stopping progress pulse when no timeout ID exists."""
        mock_scan_view._pulse_timeout_id = None

        with mock.patch("src.ui.scan_view.GLib") as mock_glib:
            mock_scan_view._stop_progress_pulse()

            # source_remove should not be called
            mock_glib.source_remove.assert_not_called()

    def test_stop_progress_pulse_section_none(self, mock_scan_view):
        """Test stopping progress pulse when section is None."""
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._progress_section = None

        with mock.patch("src.ui.scan_view.GLib"):
            # Should not raise
            mock_scan_view._stop_progress_pulse()


class TestOnRemovePathClicked:
    """Tests for the _on_remove_path_clicked handler."""

    def test_remove_path_clicked_calls_remove_path(self, mock_scan_view):
        """Test that clicking remove calls _remove_path."""
        mock_scan_view._remove_path = mock.MagicMock()
        mock_row = mock.MagicMock()

        mock_scan_view._on_remove_path_clicked("/test/path", mock_row)

        mock_scan_view._remove_path.assert_called_once_with("/test/path")


class TestOnClearAllClicked:
    """Tests for the _on_clear_all_clicked handler."""

    def test_clear_all_clicked_calls_clear_paths(self, mock_scan_view):
        """Test that clicking clear all calls _clear_paths."""
        mock_scan_view._clear_paths = mock.MagicMock()

        mock_scan_view._on_clear_all_clicked(mock.MagicMock())

        mock_scan_view._clear_paths.assert_called_once()


class TestScanCompleteOtherStatus:
    """Tests for scan complete with unexpected status."""

    def _setup_complete_mocks(self, mock_scan_view):
        """Helper to set up mocks."""
        mock_scan_view._paths_placeholder = mock.MagicMock()
        mock_scan_view._paths_listbox = mock.MagicMock()
        mock_scan_view._create_path_row = mock.MagicMock()
        mock_scan_view._update_selection_header = mock.MagicMock()
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._eicar_temp_path = ""
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._current_result = None
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._stop_progress_pulse = mock.MagicMock()
        mock_scan_view._show_view_results = mock.MagicMock()

    def test_on_scan_complete_cancelled_status(self, mock_scan_view):
        """Test scan complete with CANCELLED status shows partial results."""
        self._setup_complete_mocks(mock_scan_view)

        cancelled_status = mock.MagicMock()
        cancelled_status.value = "cancelled"

        result = mock.MagicMock()
        result.status = cancelled_status
        result.infected_count = 3
        result.error_message = None
        result.stderr = ""

        with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
            mock_scan_status.CLEAN = mock.MagicMock()
            mock_scan_status.INFECTED = mock.MagicMock()
            mock_scan_status.ERROR = mock.MagicMock()
            mock_scan_status.CANCELLED = cancelled_status

            with mock.patch("src.ui.scan_view.set_status_class") as mock_set_status:
                mock_scan_view._on_scan_complete(result)

                # Should use WARNING status class
                mock_set_status.assert_called()

        # Should show view results with actual threat count
        mock_scan_view._show_view_results.assert_called_with(3)
        # Should set banner title to "Scan cancelled"
        mock_scan_view._status_banner.set_title.assert_called()
        call_arg = mock_scan_view._status_banner.set_title.call_args[0][0]
        assert "cancelled" in call_arg.lower()


class TestScanCompleteEicarCleanupError:
    """Tests for EICAR file cleanup errors during scan complete."""

    def _setup_complete_mocks(self, mock_scan_view):
        """Helper to set up mocks."""
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._current_result = None
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._stop_progress_pulse = mock.MagicMock()
        mock_scan_view._show_view_results = mock.MagicMock()

    def test_on_scan_complete_eicar_cleanup_oserror(self, mock_scan_view, tmp_path):
        """Test scan complete handles OSError during EICAR cleanup."""
        self._setup_complete_mocks(mock_scan_view)

        # Create a path that we'll make fail on deletion
        fake_path = str(tmp_path / "nonexistent_eicar.txt")
        mock_scan_view._eicar_temp_path = fake_path
        mock_scan_view._scan_backend_override = "clamscan"
        mock_scan_view._scan_daemon_force_stream = True

        clean_status = mock.MagicMock()
        result = mock.MagicMock()
        result.status = clean_status
        result.infected_count = 0
        result.error_message = None
        result.stderr = ""

        with mock.patch("src.ui.scan_view.ScanStatus") as mock_scan_status:
            mock_scan_status.CLEAN = clean_status
            mock_scan_status.INFECTED = mock.MagicMock()
            mock_scan_status.ERROR = mock.MagicMock()

            with mock.patch("os.path.exists", return_value=True):
                with mock.patch("os.remove", side_effect=OSError("Permission denied")):
                    # Should not raise, just log warning
                    mock_scan_view._on_scan_complete(result)

        # EICAR path should still be cleared
        assert mock_scan_view._eicar_temp_path == ""
        assert mock_scan_view._scan_backend_override is None
        assert mock_scan_view._scan_daemon_force_stream is False


class TestScanErrorEicarCleanup:
    """Tests for EICAR cleanup errors during scan error."""

    def _setup_error_mocks(self, mock_scan_view):
        """Helper to set up mocks."""
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._on_scan_state_changed = None
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._stop_progress_pulse = mock.MagicMock()

    def test_on_scan_error_eicar_cleanup_oserror(self, mock_scan_view, tmp_path):
        """Test scan error handles OSError during EICAR cleanup."""
        self._setup_error_mocks(mock_scan_view)

        fake_path = str(tmp_path / "nonexistent_eicar.txt")
        mock_scan_view._eicar_temp_path = fake_path
        mock_scan_view._scan_backend_override = "clamscan"
        mock_scan_view._scan_daemon_force_stream = True

        with mock.patch("src.ui.scan_view.set_status_class"):
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch("os.remove", side_effect=OSError("Permission denied")):
                    # Should not raise
                    mock_scan_view._on_scan_error("Test error")

        # EICAR path should still be cleared
        assert mock_scan_view._eicar_temp_path == ""
        assert mock_scan_view._scan_backend_override is None
        assert mock_scan_view._scan_daemon_force_stream is False


class TestScanErrorNotifiesCallback:
    """Tests for scan error notification callback."""

    def _setup_error_mocks(self, mock_scan_view):
        """Helper to set up mocks."""
        mock_scan_view._pulse_timeout_id = None
        mock_scan_view._eicar_temp_path = ""
        mock_scan_view._selection_group = mock.MagicMock()
        mock_scan_view._stop_progress_pulse = mock.MagicMock()

    def test_on_scan_error_notifies_callback(self, mock_scan_view):
        """Test that scan error notifies external callback."""
        self._setup_error_mocks(mock_scan_view)

        callback = mock.MagicMock()
        mock_scan_view._on_scan_state_changed = callback
        mock_scan_view._is_scanning = True

        with mock.patch("src.ui.scan_view.set_status_class"):
            mock_scan_view._on_scan_error("Error")

        callback.assert_called_once_with(False, None)


class TestScanViewSharedQuarantineManager:
    """Tests for shared QuarantineManager injection in ScanView."""

    def test_scan_view_uses_provided_quarantine_manager(self, scan_view_class):
        """When quarantine_manager is passed, ScanView should use it instead of creating one."""
        sv_module = sys.modules["src.ui.scan_view"]

        original_qm = getattr(sv_module, "QuarantineManager", mock.MagicMock)
        mock_qm_class = mock.MagicMock()
        sv_module.QuarantineManager = mock_qm_class

        try:
            external_manager = mock.MagicMock(name="shared_qm")
            view = scan_view_class(
                settings_manager=mock.MagicMock(),
                quarantine_manager=external_manager,
            )
            # The external manager should be used
            assert view._quarantine_manager is external_manager
            # QuarantineManager() should NOT have been called
            mock_qm_class.assert_not_called()
        finally:
            sv_module.QuarantineManager = original_qm

    def test_scan_view_creates_own_manager_when_not_provided(self, scan_view_class):
        """When quarantine_manager is not passed, ScanView should create its own."""
        sv_module = sys.modules["src.ui.scan_view"]

        mock_qm_instance = mock.MagicMock(name="auto_created_qm")
        mock_qm_class = mock.MagicMock(return_value=mock_qm_instance)
        original_qm = getattr(sv_module, "QuarantineManager", mock.MagicMock)
        sv_module.QuarantineManager = mock_qm_class

        try:
            view = scan_view_class(settings_manager=mock.MagicMock())
            # QuarantineManager() should have been called once
            mock_qm_class.assert_called_once()
            assert view._quarantine_manager is mock_qm_instance
        finally:
            sv_module.QuarantineManager = original_qm
