# ClamUI FileExportHelper Tests
"""
Unit tests for the FileExportHelper reusable component.

Tests cover:
- FileFilter dataclass
- FileExportHelper initialization
- Save dialog creation and configuration
- File selection callback handling
- Error handling (permission errors, OS errors)
- Toast notifications
- Pre-defined filters (TEXT_FILTER, CSV_FILTER, JSON_FILTER)
"""

import contextlib
import sys
from unittest import mock

import pytest


@contextlib.contextmanager
def _sync_thread_and_idle():
    """Run the worker thread synchronously and dispatch GLib.idle_add inline.

    `src/ui/file_export.py` offloads the blocking file write to a
    ``threading.Thread`` and marshals the resulting toast back via
    ``GLib.idle_add``. In tests both are no-ops (the mocked GLib never runs the
    callback and a real daemon thread races the assertions), so this context
    manager makes the flow deterministic: the patched ``Thread.start`` runs the
    target inline, and the patched ``GLib.idle_add`` invokes its callback
    immediately. This is the project's established pattern for threaded GTK
    code (see tests/ui/test_scan_view.py and tests/integration/test_tray_integration.py).
    """
    import src.ui.file_export as fe

    class _SyncThread:
        def __init__(self, target, args=(), kwargs=None, daemon=False):
            self._t, self._a, self._k = target, args, kwargs or {}

        def start(self):
            self._t(*self._a, **self._k)

        def join(self):
            pass

    idle = mock.MagicMock(side_effect=lambda fn, *a: fn(*a))
    with (
        mock.patch.object(fe.threading, "Thread", _SyncThread),
        mock.patch.object(fe.GLib, "idle_add", idle),
    ):
        yield


@pytest.fixture
def file_export_class(mock_gi_modules):
    """Get FileExportHelper class with mocked dependencies."""
    # Clear any cached import of file_export
    if "src.ui.file_export" in sys.modules:
        del sys.modules["src.ui.file_export"]

    from src.ui.file_export import (
        CSV_FILTER,
        JSON_FILTER,
        TEXT_FILTER,
        FileExportHelper,
        FileFilter,
    )

    return {
        "FileExportHelper": FileExportHelper,
        "FileFilter": FileFilter,
        "TEXT_FILTER": TEXT_FILTER,
        "CSV_FILTER": CSV_FILTER,
        "JSON_FILTER": JSON_FILTER,
    }


class TestFileFilter:
    """Tests for FileFilter dataclass."""

    def test_file_filter_basic_creation(self, file_export_class):
        """Test creating a basic FileFilter."""
        FileFilter = file_export_class["FileFilter"]

        filter = FileFilter(name="Test Files", extension="test")

        assert filter.name == "Test Files"
        assert filter.extension == "test"
        assert filter.mime_type is None

    def test_file_filter_with_mime_type(self, file_export_class):
        """Test creating FileFilter with mime type."""
        FileFilter = file_export_class["FileFilter"]

        filter = FileFilter(name="CSV Files", extension="csv", mime_type="text/csv")

        assert filter.name == "CSV Files"
        assert filter.extension == "csv"
        assert filter.mime_type == "text/csv"


class TestPreDefinedFilters:
    """Tests for pre-defined filter constants."""

    def test_text_filter(self, file_export_class):
        """Test TEXT_FILTER constant."""
        TEXT_FILTER = file_export_class["TEXT_FILTER"]

        assert TEXT_FILTER.name == "Text Files"
        assert TEXT_FILTER.extension == "txt"
        assert TEXT_FILTER.mime_type == "text/plain"

    def test_csv_filter(self, file_export_class):
        """Test CSV_FILTER constant."""
        CSV_FILTER = file_export_class["CSV_FILTER"]

        assert CSV_FILTER.name == "CSV Files"
        assert CSV_FILTER.extension == "csv"
        assert CSV_FILTER.mime_type == "text/csv"

    def test_json_filter(self, file_export_class):
        """Test JSON_FILTER constant."""
        JSON_FILTER = file_export_class["JSON_FILTER"]

        assert JSON_FILTER.name == "JSON Files"
        assert JSON_FILTER.extension == "json"
        assert JSON_FILTER.mime_type == "application/json"


class TestFileExportHelperImport:
    """Tests for FileExportHelper import."""

    def test_import_from_file_export_module(self, mock_gi_modules):
        """Test that FileExportHelper can be imported from file_export module."""
        from src.ui.file_export import FileExportHelper

        assert FileExportHelper is not None

    def test_import_from_ui_package(self, mock_gi_modules):
        """Test that FileExportHelper is exported from src.ui package."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.log_manager": mock.MagicMock(),
                "src.core.utils": mock.MagicMock(),
                "src.ui.fullscreen_dialog": mock.MagicMock(),
                "src.ui.update_view": mock.MagicMock(),
                "src.ui.components_view": mock.MagicMock(),
                "src.ui.preferences_dialog": mock.MagicMock(),
                "src.ui.quarantine_view": mock.MagicMock(),
            },
        ):
            from src.ui import FileExportHelper, FileFilter

            assert FileExportHelper is not None
            assert FileFilter is not None


class TestFileExportHelperInitialization:
    """Tests for FileExportHelper initialization."""

    def test_initialization_stores_parameters(self, file_export_class, mock_gi_modules):
        """Test that initialization stores all parameters."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_generator = mock.MagicMock(return_value="content")
        filter = FileFilter(name="Test", extension="txt")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Test Export",
            filename_prefix="test_file",
            file_filter=filter,
            content_generator=mock_generator,
        )

        assert helper._parent_widget is mock_parent
        assert helper._dialog_title == "Test Export"
        assert helper._filename_prefix == "test_file"
        assert helper._file_filter is filter
        assert helper._content_generator is mock_generator
        assert helper._success_message is None
        assert helper._toast_manager is None

    def test_initialization_with_optional_parameters(self, file_export_class, mock_gi_modules):
        """Test initialization with custom success message and toast manager."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_toast_manager = mock.MagicMock()
        filter = FileFilter(name="Test", extension="txt")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Test Export",
            filename_prefix="test_file",
            file_filter=filter,
            content_generator=lambda: "content",
            success_message="Custom success!",
            toast_manager=mock_toast_manager,
        )

        assert helper._success_message == "Custom success!"
        assert helper._toast_manager is mock_toast_manager


class TestFileExportHelperShowSaveDialog:
    """Tests for show_save_dialog method."""

    def test_show_save_dialog_creates_dialog(self, file_export_class, mock_gi_modules):
        """Test that show_save_dialog creates a FileDialog."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="Test", extension="txt")

        mock_dialog = mock.MagicMock()
        mock_gi_modules["gtk"].FileDialog.return_value = mock_dialog

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export Test",
            filename_prefix="export",
            file_filter=filter,
            content_generator=lambda: "content",
        )

        helper.show_save_dialog()

        mock_gi_modules["gtk"].FileDialog.assert_called_once()
        mock_dialog.set_title.assert_called_with("Export Test")
        mock_dialog.save.assert_called_once()

    def test_show_save_dialog_sets_initial_name_with_timestamp(
        self, file_export_class, mock_gi_modules
    ):
        """Test that initial filename includes timestamp and extension."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="CSV Files", extension="csv")

        mock_dialog = mock.MagicMock()
        mock_gi_modules["gtk"].FileDialog.return_value = mock_dialog

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="mydata",
            file_filter=filter,
            content_generator=lambda: "content",
        )

        helper.show_save_dialog()

        # Check initial name was set
        assert mock_dialog.set_initial_name.called
        initial_name = mock_dialog.set_initial_name.call_args[0][0]
        assert initial_name.startswith("mydata_")
        assert initial_name.endswith(".csv")
        # Verify timestamp format (YYYYMMDD_HHMMSS)
        assert len(initial_name) == len("mydata_20240115_103000.csv")

    def test_show_save_dialog_configures_filter(self, file_export_class, mock_gi_modules):
        """Test that file filter is configured correctly."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="CSV Files", extension="csv", mime_type="text/csv")

        mock_dialog = mock.MagicMock()
        mock_gi_modules["gtk"].FileDialog.return_value = mock_dialog

        mock_gtk_filter = mock.MagicMock()
        mock_gi_modules["gtk"].FileFilter.return_value = mock_gtk_filter

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="data",
            file_filter=filter,
            content_generator=lambda: "content",
        )

        helper.show_save_dialog()

        # Verify filter was created and configured
        mock_gtk_filter.set_name.assert_called_with("CSV Files")
        mock_gtk_filter.add_mime_type.assert_called_with("text/csv")
        mock_gtk_filter.add_pattern.assert_called_with("*.csv")


class TestFileExportHelperFileSelected:
    """Tests for _on_file_selected callback."""

    def test_file_selected_writes_content(self, file_export_class, mock_gi_modules, tmp_path):
        """Test that selecting a file writes content."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        test_file = tmp_path / "test.txt"

        mock_file = mock.MagicMock()
        mock_file.get_path.return_value = str(test_file)

        mock_dialog = mock.MagicMock()
        mock_dialog.save_finish.return_value = mock_file

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "Test content here",
        )

        with _sync_thread_and_idle():
            helper._write_to_file(str(test_file))

        assert test_file.exists()
        assert test_file.read_text() == "Test content here"

    def test_file_selected_adds_extension_if_missing(
        self, file_export_class, mock_gi_modules, tmp_path
    ):
        """Test that extension is added if missing from selected path."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="CSV", extension="csv")

        test_file = tmp_path / "test"  # No extension

        mock_file = mock.MagicMock()
        mock_file.get_path.return_value = str(test_file)

        mock_dialog = mock.MagicMock()
        mock_dialog.save_finish.return_value = mock_file

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "CSV content",
        )

        with _sync_thread_and_idle():
            helper._write_to_file(str(test_file))

        # File should be created with .csv extension
        expected_file = tmp_path / "test.csv"
        assert expected_file.exists()
        assert expected_file.read_text() == "CSV content"

    def test_file_selected_returns_on_cancel(self, file_export_class, mock_gi_modules):
        """Test that cancelling the dialog (returning None from save_finish) does nothing."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        mock_dialog = mock.MagicMock()
        mock_dialog.save_finish.return_value = None  # User cancelled

        content_generator = mock.MagicMock()

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=content_generator,
        )

        # Test that _on_file_dialog_selected handles None result (cancel)
        helper._on_file_dialog_selected(mock_dialog, mock.MagicMock())

        # Content generator should not be called since dialog was cancelled
        content_generator.assert_not_called()

    def test_file_selected_handles_invalid_path(self, file_export_class, mock_gi_modules):
        """Test handling of invalid file path (None)."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
        )
        helper._show_toast = mock.MagicMock()

        # Call _write_to_file with None to simulate invalid path
        helper._write_to_file(None)

        helper._show_toast.assert_called_once()
        assert "Invalid file path" in helper._show_toast.call_args[0][0]

    def test_file_selected_shows_success_toast(self, file_export_class, mock_gi_modules, tmp_path):
        """Test that success toast is shown after writing."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        test_file = tmp_path / "test.txt"

        mock_file = mock.MagicMock()
        mock_file.get_path.return_value = str(test_file)

        mock_dialog = mock.MagicMock()
        mock_dialog.save_finish.return_value = mock_file

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
        )
        helper._show_toast = mock.MagicMock()

        with _sync_thread_and_idle():
            helper._write_to_file(str(test_file))

        helper._show_toast.assert_called_once()
        assert "test.txt" in helper._show_toast.call_args[0][0]

    def test_file_selected_uses_custom_success_message(
        self, file_export_class, mock_gi_modules, tmp_path
    ):
        """Test that custom success message is used when provided."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        test_file = tmp_path / "test.txt"

        mock_file = mock.MagicMock()
        mock_file.get_path.return_value = str(test_file)

        mock_dialog = mock.MagicMock()
        mock_dialog.save_finish.return_value = mock_file

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
            success_message="Exported 5 items successfully!",
        )
        helper._show_toast = mock.MagicMock()

        with _sync_thread_and_idle():
            helper._write_to_file(str(test_file))

        helper._show_toast.assert_called_once_with("Exported 5 items successfully!")


class TestFileExportHelperErrorHandling:
    """Tests for error handling in file export."""

    def test_permission_error_shows_toast(self, file_export_class, mock_gi_modules):
        """Test that permission error shows appropriate toast."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
        )
        helper._show_toast = mock.MagicMock()

        with _sync_thread_and_idle(), mock.patch("builtins.open", side_effect=PermissionError()):
            helper._write_to_file("/root/protected.txt")

        helper._show_toast.assert_called_once()
        toast_msg = helper._show_toast.call_args[0][0]
        assert "Permission denied" in toast_msg

    def test_os_error_shows_toast(self, file_export_class, mock_gi_modules):
        """Test that OS error shows appropriate toast."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
        )
        helper._show_toast = mock.MagicMock()

        # Mock open to raise OSError
        with _sync_thread_and_idle(), mock.patch("builtins.open", side_effect=OSError("Disk full")):
            helper._write_to_file("/some/path.txt")

        helper._show_toast.assert_called_once()
        toast_msg = helper._show_toast.call_args[0][0]
        assert "Error writing file" in toast_msg
        assert "Disk full" in toast_msg

    def test_content_generator_exception_shows_error_toast(
        self, file_export_class, mock_gi_modules, tmp_path
    ):
        """A failing content_generator must surface an error toast, not propagate.

        Regression: content generation (CSV/JSON formatting) runs inside the
        async file-dialog callback. Before the fix only PermissionError/OSError
        were caught, so any other exception escaped the GTK callback with no
        user feedback (silent failure).
        """
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock.MagicMock()
        filter = FileFilter(name="JSON", extension="json")

        def boom():
            raise ValueError("not JSON serializable")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=boom,
        )
        helper._show_toast = mock.MagicMock()

        test_file = tmp_path / "out.json"
        # Must not raise even though content_generator raises a non-OSError.
        helper._write_to_file(str(test_file))

        # No file should be written, and the user must get an error toast.
        assert not test_file.exists()
        helper._show_toast.assert_called_once()
        toast_msg = helper._show_toast.call_args[0][0]
        assert "Error exporting file" in toast_msg

    def test_glib_error_handled_silently(self, file_export_class, mock_gi_modules):
        """Test that GLib.Error (dialog dismiss) is handled silently."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        mock_dialog = mock.MagicMock()
        # GLib.Error is raised when dialog is dismissed
        mock_gi_modules["glib"].Error = Exception
        mock_dialog.save_finish.side_effect = mock_gi_modules["glib"].Error("Dismissed")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
        )
        helper._show_toast = mock.MagicMock()

        # Should not raise - GLib.Error is caught in _on_file_dialog_selected
        helper._on_file_dialog_selected(mock_dialog, mock.MagicMock())

        # Toast should not be shown for GLib.Error (user cancelled)
        helper._show_toast.assert_not_called()


class TestFileExportHelperShowToast:
    """Tests for _show_toast method."""

    def test_show_toast_uses_explicit_toast_manager(self, file_export_class, mock_gi_modules):
        """Test that explicit toast_manager is used when provided."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_toast_manager = mock.MagicMock()
        filter = FileFilter(name="Text", extension="txt")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
            toast_manager=mock_toast_manager,
        )

        helper._show_toast("Test message")

        mock_toast_manager.add_toast.assert_called_once()

    def test_show_toast_falls_back_to_window(self, file_export_class, mock_gi_modules):
        """Test that toast falls back to window's add_toast."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_window = mock.MagicMock()
        mock_window.add_toast = mock.MagicMock()

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = mock_window
        filter = FileFilter(name="Text", extension="txt")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
        )

        helper._show_toast("Test message")

        mock_window.add_toast.assert_called_once()

    def test_show_toast_handles_no_toast_target(self, file_export_class, mock_gi_modules):
        """Test that showing toast with no available target does not error."""
        FileExportHelper = file_export_class["FileExportHelper"]
        FileFilter = file_export_class["FileFilter"]

        mock_parent = mock.MagicMock()
        mock_parent.get_root.return_value = None
        filter = FileFilter(name="Text", extension="txt")

        helper = FileExportHelper(
            parent_widget=mock_parent,
            dialog_title="Export",
            filename_prefix="test",
            file_filter=filter,
            content_generator=lambda: "content",
        )

        # Should not raise
        helper._show_toast("Test message")
