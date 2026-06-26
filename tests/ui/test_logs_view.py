# ClamUI LogsView Tests
"""
Unit tests for the LogsView component.

Tests cover:
- Initialization and setup
- Loading state management
- Log entry display and pagination
- Log selection and detail display
- Daemon status and live log updates
- Clear logs functionality
- Copy/export functionality
- CSV formatting
- Export button state management
- Export all to CSV handler
- Export all to JSON handler
- Export single log to JSON handler
"""

import sys
from unittest import mock

import pytest


@pytest.fixture
def mock_log_manager():
    """Create a mock LogManager."""
    manager = mock.MagicMock()
    manager.get_logs_async = mock.MagicMock()
    manager.get_log_by_id = mock.MagicMock()
    manager.clear_logs = mock.MagicMock()
    manager.get_daemon_status = mock.MagicMock(return_value=("RUNNING", "Running"))
    manager.read_daemon_logs = mock.MagicMock(return_value=(True, "daemon log content"))
    return manager


@pytest.fixture
def mock_log_entry():
    """Create a mock LogEntry."""
    entry = mock.MagicMock()
    entry.id = "test-log-id-123"
    entry.type = "scan"
    entry.status = "clean"
    entry.timestamp = "2024-01-15T10:30:00"
    entry.path = "/home/user/documents"
    entry.summary = "Scanned 100 files, 0 threats found"
    entry.duration = 45.5
    entry.details = "Detailed scan output here..."
    return entry


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


@pytest.fixture
def logs_view_class(mock_gi_modules):
    """Get LogsView class with mocked dependencies."""
    # Add additional mock modules that logs_view.py imports
    # Note: src.core.log_manager is NOT mocked - we need the real DaemonStatus enum
    with mock.patch.dict(
        sys.modules,
        {
            "src.core.utils": mock.MagicMock(),
            "src.ui.fullscreen_dialog": mock.MagicMock(),
        },
    ):
        # Clear any cached import of logs_view
        if "src.ui.logs_view" in sys.modules:
            del sys.modules["src.ui.logs_view"]

        from src.ui.logs_view import LogsView

        yield LogsView

    # Critical: Clear all src.* modules after test to prevent pollution
    _clear_src_modules()


@pytest.fixture
def mock_logs_view(logs_view_class, mock_log_manager):
    """Create a mock LogsView instance for testing."""
    # Create instance without calling __init__ (Python 3.13+ compatible)
    view = object.__new__(logs_view_class)

    # Set up required attributes
    view._log_manager = mock_log_manager
    view._selected_log = None
    view._daemon_refresh_id = None
    view._is_loading = False
    view._all_log_entries = []

    # Set up mock pagination controller (used by backward compatibility properties)
    view._pagination = mock.MagicMock()
    view._pagination.displayed_count = 0
    view._pagination.load_more_row = None

    # Mock UI elements
    view._view_stack = mock.MagicMock()
    view._logs_listbox = mock.MagicMock()
    view._logs_spinner = mock.MagicMock()
    view._refresh_button = mock.MagicMock()
    view._clear_button = mock.MagicMock()
    view._detail_text = mock.MagicMock()
    view._detail_group = mock.MagicMock()
    view._copy_detail_button = mock.MagicMock()
    view._export_detail_text_button = mock.MagicMock()
    view._export_detail_csv_button = mock.MagicMock()
    view._export_detail_json_button = mock.MagicMock()
    view._export_all_csv_button = mock.MagicMock()
    view._export_all_json_button = mock.MagicMock()
    view._fullscreen_detail_button = mock.MagicMock()
    view._daemon_text = mock.MagicMock()
    view._daemon_group = mock.MagicMock()
    view._daemon_status_row = mock.MagicMock()
    view._live_toggle = mock.MagicMock()
    view._fullscreen_daemon_button = mock.MagicMock()
    view._export_daemon_button = mock.MagicMock()

    # Mock internal methods
    view._setup_ui = mock.MagicMock()
    view._load_logs_async = mock.MagicMock()
    view._set_loading_state = mock.MagicMock()
    view._display_log_details = mock.MagicMock()
    view._create_log_row = mock.MagicMock()
    view._check_daemon_status = mock.MagicMock()
    view.get_root = mock.MagicMock(return_value=None)

    return view


class TestLogsViewImport:
    """Tests for LogsView import."""

    def test_import_logs_view(self, mock_gi_modules):
        """Test that LogsView can be imported."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.log_manager": mock.MagicMock(),
                "src.core.utils": mock.MagicMock(),
                "src.ui.fullscreen_dialog": mock.MagicMock(),
            },
        ):
            from src.ui.logs_view import LogsView

            assert LogsView is not None

    def test_import_from_ui_package(self, mock_gi_modules):
        """Test that LogsView is exported from src.ui package."""
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
            from src.ui import LogsView

            assert LogsView is not None

    def test_pagination_constants_defined(self, mock_gi_modules):
        """Test that pagination constants are defined."""
        with mock.patch.dict(
            sys.modules,
            {
                "src.core.log_manager": mock.MagicMock(),
                "src.core.utils": mock.MagicMock(),
                "src.ui.fullscreen_dialog": mock.MagicMock(),
            },
        ):
            from src.ui.pagination import PaginatedListController

            assert PaginatedListController.DEFAULT_INITIAL_LIMIT == 25
            assert PaginatedListController.DEFAULT_BATCH_SIZE == 25


class TestLogsViewInitialization:
    """Tests for LogsView initialization."""

    def test_initial_loading_state_is_false(self, mock_logs_view):
        """Test that initial loading state is False."""
        assert mock_logs_view._is_loading is False

    def test_initial_selected_log_is_none(self, mock_logs_view):
        """Test that initial selected log is None."""
        assert mock_logs_view._selected_log is None

    def test_initial_daemon_refresh_id_is_none(self, mock_logs_view):
        """Test that initial daemon refresh ID is None."""
        assert mock_logs_view._daemon_refresh_id is None

    def test_initial_displayed_log_count_is_zero(self, mock_logs_view):
        """Test that initial displayed log count is zero."""
        assert mock_logs_view._displayed_log_count == 0

    def test_initial_all_log_entries_is_empty(self, mock_logs_view):
        """Test that initial all_log_entries is empty."""
        assert mock_logs_view._all_log_entries == []

    def test_initial_load_more_row_is_none(self, mock_logs_view):
        """Test that initial load_more_row is None."""
        assert mock_logs_view._load_more_row is None


class TestLogsViewLoadingState:
    """Tests for loading state management."""

    def test_set_loading_state_true_shows_spinner(self, logs_view_class, mock_log_manager):
        """Test that setting loading True shows spinner."""
        view = object.__new__(logs_view_class)
        view._is_loading = False
        view._logs_spinner = mock.MagicMock()
        view._refresh_button = mock.MagicMock()
        view._clear_button = mock.MagicMock()
        view._logs_listbox = mock.MagicMock()
        view._create_loading_state = mock.MagicMock()

        view._set_loading_state(True)

        assert view._is_loading is True
        view._logs_spinner.set_visible.assert_called_with(True)
        view._logs_spinner.start.assert_called_once()
        view._refresh_button.set_sensitive.assert_called_with(False)
        view._clear_button.set_sensitive.assert_called_with(False)

    def test_set_loading_state_false_hides_spinner(self, logs_view_class, mock_log_manager):
        """Test that setting loading False hides spinner."""
        view = object.__new__(logs_view_class)
        view._is_loading = True
        view._logs_spinner = mock.MagicMock()
        view._refresh_button = mock.MagicMock()
        view._clear_button = mock.MagicMock()
        view._logs_listbox = mock.MagicMock()

        view._set_loading_state(False)

        assert view._is_loading is False
        view._logs_spinner.stop.assert_called_once()
        view._logs_spinner.set_visible.assert_called_with(False)
        view._refresh_button.set_sensitive.assert_called_with(True)

    def test_load_logs_async_prevents_double_load(self, logs_view_class, mock_log_manager):
        """Test that async load prevents loading when already loading."""
        view = object.__new__(logs_view_class)
        view._is_loading = True
        view._set_loading_state = mock.MagicMock()
        view._log_manager = mock_log_manager

        view._load_logs_async()

        view._set_loading_state.assert_not_called()


class TestLogsViewLogSelection:
    """Tests for log selection handling."""

    def test_on_log_selected_with_none_clears_selection(self, logs_view_class):
        """Test that selecting None clears the selection."""
        view = object.__new__(logs_view_class)
        view._selected_log = mock.MagicMock()
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer
        view._copy_detail_button = mock.MagicMock()
        view._export_detail_text_button = mock.MagicMock()
        view._export_detail_csv_button = mock.MagicMock()
        view._export_detail_json_button = mock.MagicMock()

        view._on_log_selected(mock.MagicMock(), None)

        assert view._selected_log is None
        mock_buffer.set_text.assert_called_with("Select a log entry to view details.")
        view._copy_detail_button.set_sensitive.assert_called_with(False)
        view._export_detail_text_button.set_sensitive.assert_called_with(False)
        view._export_detail_csv_button.set_sensitive.assert_called_with(False)
        view._export_detail_json_button.set_sensitive.assert_called_with(False)

    def test_on_log_selected_enables_buttons(
        self, logs_view_class, mock_log_entry, mock_log_manager
    ):
        """Test that selecting a log enables copy/export buttons."""
        view = object.__new__(logs_view_class)
        view._selected_log = None
        view._log_manager = mock_log_manager
        view._log_manager.get_log_by_id.return_value = mock_log_entry
        view._display_log_details = mock.MagicMock()
        view._copy_detail_button = mock.MagicMock()
        view._export_detail_text_button = mock.MagicMock()
        view._export_detail_csv_button = mock.MagicMock()
        view._export_detail_json_button = mock.MagicMock()

        mock_row = mock.MagicMock()
        mock_row.get_name.return_value = "test-log-id-123"

        view._on_log_selected(mock.MagicMock(), mock_row)

        assert view._selected_log == mock_log_entry
        view._copy_detail_button.set_sensitive.assert_called_with(True)
        view._export_detail_text_button.set_sensitive.assert_called_with(True)
        view._export_detail_csv_button.set_sensitive.assert_called_with(True)
        view._export_detail_json_button.set_sensitive.assert_called_with(True)
        view._display_log_details.assert_called_once_with(mock_log_entry)

    def test_on_log_selected_returns_when_entry_not_found(self, logs_view_class, mock_log_manager):
        """Test that selecting a log that doesn't exist returns early."""
        view = object.__new__(logs_view_class)
        view._selected_log = None
        view._log_manager = mock_log_manager
        view._log_manager.get_log_by_id.return_value = None
        view._display_log_details = mock.MagicMock()

        mock_row = mock.MagicMock()
        mock_row.get_name.return_value = "nonexistent-id"

        view._on_log_selected(mock.MagicMock(), mock_row)

        view._display_log_details.assert_not_called()


class TestLogsViewPagination:
    """Tests for log pagination functionality."""

    def test_on_logs_loaded_with_empty_list(self, logs_view_class, mock_log_manager):
        """Test handling empty logs list."""
        view = object.__new__(logs_view_class)
        view._is_loading = True
        view._logs_listbox = mock.MagicMock()
        view._clear_button = mock.MagicMock()
        view._all_log_entries = []
        view._displayed_log_count = 0
        view._load_more_row = None
        view._set_loading_state = mock.MagicMock()

        result = view._on_logs_loaded([])

        assert result is False
        view._clear_button.set_sensitive.assert_called_with(False)
        assert view._all_log_entries == []

    def test_on_logs_loaded_stores_entries(self, logs_view_class, mock_log_entry):
        """Test that loaded logs are stored."""
        view = object.__new__(logs_view_class)
        view._is_loading = True
        view._logs_listbox = mock.MagicMock()
        view._logs_listbox.get_row_at_index.return_value = mock.MagicMock()
        view._clear_button = mock.MagicMock()
        view._all_log_entries = []
        view._displayed_log_count = 0
        view._load_more_row = None
        view._set_loading_state = mock.MagicMock()
        view._display_log_batch = mock.MagicMock()
        view._add_load_more_button = mock.MagicMock()

        logs = [mock_log_entry]
        view._on_logs_loaded(logs)

        assert view._all_log_entries == logs

    def test_display_log_batch_delegates_to_pagination(self, logs_view_class, mock_log_entry):
        """Test that displaying logs delegates to pagination controller."""
        view = object.__new__(logs_view_class)
        view._pagination = mock.MagicMock()

        view._display_log_batch(0, 2)

        view._pagination.display_batch.assert_called_once_with(0, 2)

    def test_on_load_more_logs_clicked_delegates_to_pagination(
        self, logs_view_class, mock_log_entry
    ):
        """Test that clicking load more delegates to pagination controller."""
        view = object.__new__(logs_view_class)
        view._pagination = mock.MagicMock()

        view._on_load_more_logs_clicked(mock.MagicMock())

        view._pagination.load_more.assert_called_once_with(entries_label="logs")

    def test_on_show_all_logs_clicked_delegates_to_pagination(
        self, logs_view_class, mock_log_entry
    ):
        """Test that clicking show all delegates to pagination controller."""
        view = object.__new__(logs_view_class)
        view._pagination = mock.MagicMock()

        view._on_show_all_logs_clicked(mock.MagicMock())

        view._pagination.show_all.assert_called_once()


class TestLogsViewLogRowCreation:
    """Tests for log row creation."""

    def test_create_log_row_sets_scan_icon(self, logs_view_class, mock_log_entry, mock_gi_modules):
        """Test that scan logs get folder icon via add_prefix."""
        view = object.__new__(logs_view_class)
        mock_log_entry.type = "scan"

        # Configure Adw.ActionRow to return our mock_row
        mock_row = mock.MagicMock()
        mock_gi_modules["adw"].ActionRow.side_effect = lambda *args, **kwargs: mock_row

        view._create_log_row(mock_log_entry)

        # Icon is added via add_prefix with a Gtk.Image (modern pattern)
        mock_row.add_prefix.assert_called()

    def test_create_log_row_sets_update_icon(
        self, logs_view_class, mock_log_entry, mock_gi_modules
    ):
        """Test that update logs get update icon via add_prefix."""
        view = object.__new__(logs_view_class)
        mock_log_entry.type = "update"

        mock_row = mock.MagicMock()
        mock_gi_modules["adw"].ActionRow.side_effect = lambda *args, **kwargs: mock_row

        view._create_log_row(mock_log_entry)

        # Icon is added via add_prefix with a Gtk.Image (modern pattern)
        mock_row.add_prefix.assert_called()

    def test_create_log_row_sets_name_to_id(self, logs_view_class, mock_log_entry, mock_gi_modules):
        """Test that row name is set to entry ID."""
        view = object.__new__(logs_view_class)

        mock_row = mock.MagicMock()
        mock_gi_modules["adw"].ActionRow.side_effect = lambda *args, **kwargs: mock_row

        view._create_log_row(mock_log_entry)

        mock_row.set_name.assert_called_with("test-log-id-123")


class TestLogsViewDaemonStatus:
    """Tests for daemon status checking."""

    def test_check_daemon_status_running(self, logs_view_class, mock_log_manager):
        """Test daemon status display when running."""
        # Import real DaemonStatus to match what the implementation uses
        from src.core.log_manager import DaemonStatus

        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._log_manager.get_daemon_status.return_value = (
            DaemonStatus.RUNNING,
            "Running",
        )
        view._daemon_status_row = mock.MagicMock()
        view._daemon_status_icon = mock.MagicMock()
        view._live_toggle = mock.MagicMock()

        result = view._apply_daemon_status(DaemonStatus.RUNNING, "Running")

        assert result is False
        view._daemon_status_row.set_subtitle.assert_called_with("Running")
        view._daemon_status_icon.set_from_icon_name.assert_called_with("object-select-symbolic")
        view._live_toggle.set_sensitive.assert_called_with(True)

    def test_check_daemon_status_stopped(self, logs_view_class, mock_log_manager):
        """Test daemon status display when stopped."""
        from src.core.log_manager import DaemonStatus

        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._log_manager.get_daemon_status.return_value = (
            DaemonStatus.STOPPED,
            "Stopped",
        )
        view._daemon_status_row = mock.MagicMock()
        view._daemon_status_icon = mock.MagicMock()
        view._live_toggle = mock.MagicMock()

        view._apply_daemon_status(DaemonStatus.STOPPED, "Stopped")

        view._daemon_status_row.set_subtitle.assert_called_with("Stopped")
        view._daemon_status_icon.set_from_icon_name.assert_called_with(
            "media-playback-stop-symbolic"
        )
        view._live_toggle.set_sensitive.assert_called_with(True)

    def test_check_daemon_status_not_installed(self, logs_view_class, mock_log_manager):
        """Test daemon status display when not installed."""
        from src.core.log_manager import DaemonStatus

        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._log_manager.get_daemon_status.return_value = (
            DaemonStatus.NOT_INSTALLED,
            "",
        )
        view._daemon_status_row = mock.MagicMock()
        view._live_toggle = mock.MagicMock()
        view._daemon_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._daemon_text.get_buffer.return_value = mock_buffer

        view._apply_daemon_status(DaemonStatus.NOT_INSTALLED, "")

        view._daemon_status_row.set_subtitle.assert_called_with("Not installed")
        view._live_toggle.set_sensitive.assert_called_with(False)


class TestLogsViewLiveToggle:
    """Tests for live log toggle functionality."""

    def test_on_live_toggle_starts_refresh(self, logs_view_class):
        """Test that toggling on starts refresh."""
        view = object.__new__(logs_view_class)
        view._start_daemon_log_refresh = mock.MagicMock()
        view._stop_daemon_log_refresh = mock.MagicMock()

        mock_button = mock.MagicMock()
        mock_button.get_active.return_value = True

        view._on_live_toggle(mock_button)

        mock_button.set_icon_name.assert_called_with("media-playback-pause-symbolic")
        mock_button.set_tooltip_text.assert_called_with("Stop live log updates")
        view._start_daemon_log_refresh.assert_called_once()

    def test_on_live_toggle_stops_refresh(self, logs_view_class):
        """Test that toggling off stops refresh."""
        view = object.__new__(logs_view_class)
        view._start_daemon_log_refresh = mock.MagicMock()
        view._stop_daemon_log_refresh = mock.MagicMock()

        mock_button = mock.MagicMock()
        mock_button.get_active.return_value = False

        view._on_live_toggle(mock_button)

        mock_button.set_icon_name.assert_called_with("media-playback-start-symbolic")
        mock_button.set_tooltip_text.assert_called_with("Start live log updates")
        view._stop_daemon_log_refresh.assert_called_once()

    def test_stop_daemon_log_refresh_removes_timeout(self, logs_view_class):
        """Test that stopping refresh removes the timeout."""
        with mock.patch.dict(sys.modules, {"gi.repository.GLib": mock.MagicMock()}):
            from gi.repository import GLib

            view = object.__new__(logs_view_class)
            view._daemon_refresh_id = 12345

            view._stop_daemon_log_refresh()

            GLib.source_remove.assert_called_once_with(12345)
            assert view._daemon_refresh_id is None

    def test_stop_daemon_log_refresh_with_no_id(self, logs_view_class):
        """Test that stopping refresh with no ID does nothing."""
        with mock.patch.dict(sys.modules, {"gi.repository.GLib": mock.MagicMock()}):
            from gi.repository import GLib

            view = object.__new__(logs_view_class)
            view._daemon_refresh_id = None

            view._stop_daemon_log_refresh()

            GLib.source_remove.assert_not_called()


class TestLogsViewRefreshDaemonLogs:
    """Tests for daemon log refresh."""

    def test_refresh_daemon_logs_success(self, logs_view_class, mock_log_manager):
        """Test successful daemon log refresh."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._log_manager.read_daemon_logs.return_value = (True, "log content here")
        view._daemon_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        mock_buffer.get_end_iter.return_value = mock.MagicMock()
        view._daemon_text.get_buffer.return_value = mock_buffer
        view._daemon_refresh_id = 123

        view._daemon_refresh_in_flight = True
        view._apply_daemon_logs(True, "log content here")

        mock_buffer.set_text.assert_called_with("log content here")
        assert view._daemon_refresh_in_flight is False

    def test_refresh_daemon_logs_failure(self, logs_view_class, mock_log_manager):
        """Test failed daemon log refresh."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._log_manager.read_daemon_logs.return_value = (False, "Permission denied")
        view._daemon_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._daemon_text.get_buffer.return_value = mock_buffer
        view._daemon_refresh_id = None

        view._apply_daemon_logs(False, "Permission denied")

        mock_buffer.set_text.assert_called_with("Error loading daemon logs:\n\nPermission denied")


class TestLogsViewExportDaemonLogs:
    """Tests for daemon logs export functionality."""

    def test_export_daemon_button_exists(self, mock_logs_view):
        """Test that export daemon logs button exists."""
        assert hasattr(mock_logs_view, "_export_daemon_button")
        assert mock_logs_view._export_daemon_button is not None

    def test_export_daemon_logs_skips_placeholder(self, logs_view_class):
        """Test that export skips placeholder text."""
        view = object.__new__(logs_view_class)
        view._daemon_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        mock_buffer.get_start_iter.return_value = mock.MagicMock()
        mock_buffer.get_end_iter.return_value = mock.MagicMock()
        mock_buffer.get_text.return_value = (
            "Daemon logs will appear here.\n\nClick the play button to start live updates."
        )
        view._daemon_text.get_buffer.return_value = mock_buffer
        view.get_root = mock.MagicMock(return_value=None)

        # Should return early without creating FileExportHelper
        with mock.patch("src.ui.logs_view.FileExportHelper") as mock_helper:
            view._on_export_daemon_logs_clicked(mock.MagicMock())
            mock_helper.assert_not_called()

    def test_export_daemon_logs_creates_helper(self, logs_view_class, mock_gi_modules):
        """Test that export daemon logs creates FileExportHelper and shows dialog."""
        view = object.__new__(logs_view_class)
        view._daemon_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        mock_buffer.get_start_iter.return_value = mock.MagicMock()
        mock_buffer.get_end_iter.return_value = mock.MagicMock()
        mock_buffer.get_text.return_value = "Jan 26 10:30:00 clamd[1234]: LibClamAV info"
        view._daemon_text.get_buffer.return_value = mock_buffer
        view.get_root = mock.MagicMock(return_value=mock.MagicMock())

        mock_dialog = mock.MagicMock()
        mock_gi_modules["gtk"].FileDialog.return_value = mock_dialog

        view._on_export_daemon_logs_clicked(mock.MagicMock())

        # FileExportHelper should create dialog via show_save_dialog
        mock_gi_modules["gtk"].FileDialog.assert_called_once()
        mock_dialog.set_title.assert_called_with("Export Daemon Logs")
        # Initial filename should contain clamd_logs and .txt extension
        assert mock_dialog.set_initial_name.called
        initial_name = mock_dialog.set_initial_name.call_args[0][0]
        assert initial_name.startswith("clamd_logs_")
        assert initial_name.endswith(".txt")
        mock_dialog.save.assert_called_once()

    def test_export_button_enabled_on_successful_refresh(self, logs_view_class, mock_log_manager):
        """Test that export button is enabled when logs are successfully loaded."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._log_manager.read_daemon_logs.return_value = (True, "log content here")
        view._daemon_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        mock_buffer.get_end_iter.return_value = mock.MagicMock()
        view._daemon_text.get_buffer.return_value = mock_buffer
        view._daemon_refresh_id = 123
        view._export_daemon_button = mock.MagicMock()

        view._apply_daemon_logs(True, "log content here")

        view._export_daemon_button.set_sensitive.assert_called_with(True)

    def test_export_button_disabled_on_failed_refresh(self, logs_view_class, mock_log_manager):
        """Test that export button is disabled when logs fail to load."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._log_manager.read_daemon_logs.return_value = (False, "Permission denied")
        view._daemon_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._daemon_text.get_buffer.return_value = mock_buffer
        view._daemon_refresh_id = None
        view._export_daemon_button = mock.MagicMock()

        view._apply_daemon_logs(False, "Permission denied")

        view._export_daemon_button.set_sensitive.assert_called_with(False)


class TestLogsViewClearLogs:
    """Tests for clear logs functionality."""

    def test_on_clear_dialog_response_clears_logs(self, logs_view_class, mock_log_manager):
        """Test that clear response clears logs."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._all_log_entries = [mock.MagicMock()]
        view._pagination = mock.MagicMock()
        view._pagination.displayed_count = 10
        view._pagination.load_more_row = mock.MagicMock()
        view._load_logs_async = mock.MagicMock()
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer
        view._selected_log = mock.MagicMock()
        view._copy_detail_button = mock.MagicMock()
        view._export_detail_text_button = mock.MagicMock()
        view._export_detail_csv_button = mock.MagicMock()
        view._export_detail_json_button = mock.MagicMock()

        view._on_clear_dialog_response(mock.MagicMock(), "clear")

        view._log_manager.clear_logs.assert_called_once()
        assert view._all_log_entries == []
        view._pagination.reset_state.assert_called_once()
        view._load_logs_async.assert_called_once()
        assert view._selected_log is None
        view._copy_detail_button.set_sensitive.assert_called_with(False)

    def test_on_clear_dialog_response_cancel_does_nothing(self, logs_view_class, mock_log_manager):
        """Test that cancel response does nothing."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._all_log_entries = [mock.MagicMock()]
        view._load_logs_async = mock.MagicMock()

        view._on_clear_dialog_response(mock.MagicMock(), "cancel")

        view._log_manager.clear_logs.assert_not_called()
        view._load_logs_async.assert_not_called()


class TestLogsViewRefresh:
    """Tests for refresh functionality."""

    def test_on_refresh_clicked_loads_logs(self, logs_view_class):
        """Test that refresh button click triggers load."""
        view = object.__new__(logs_view_class)
        view._load_logs_async = mock.MagicMock()

        view._on_refresh_clicked(mock.MagicMock())

        view._load_logs_async.assert_called_once()

    def test_refresh_logs_public_method(self, logs_view_class):
        """Test that public refresh_logs method works."""
        with mock.patch.dict(sys.modules, {"gi.repository.GLib": mock.MagicMock()}):
            from gi.repository import GLib

            GLib.idle_add = lambda f: f()

            view = object.__new__(logs_view_class)
            view._load_logs_async = mock.MagicMock()

            view.refresh_logs()


class TestLogsViewDisplayLogDetails:
    """Tests for log detail display."""

    def test_display_log_details_scan(self, logs_view_class, mock_log_entry):
        """Test displaying scan log details."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer
        mock_log_entry.type = "scan"

        # Mock the statistics_calculator
        view._statistics_calculator = mock.MagicMock()
        view._statistics_calculator.extract_entry_statistics.return_value = {
            "files_scanned": 0,
            "directories_scanned": 0,
            "duration": 0,
        }

        view._display_log_details(mock_log_entry)

        # Verify buffer.set_text was called with content containing SCAN LOG
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "SCAN LOG" in call_args
        assert mock_log_entry.id in call_args

    def test_display_log_details_update(self, logs_view_class, mock_log_entry):
        """Test displaying update log details."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer
        mock_log_entry.type = "update"

        view._display_log_details(mock_log_entry)

        call_args = mock_buffer.set_text.call_args[0][0]
        assert "UPDATE LOG" in call_args


class TestLogsViewStatisticsSummary:
    """Tests for statistics summary in log detail display."""

    def test_statistics_summary_shown_for_scan_with_data(self, logs_view_class, mock_log_entry):
        """Test that statistics summary appears in scan log detail when data is available."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer

        # Create a mock statistics calculator
        mock_stats_calc = mock.MagicMock()
        mock_stats_calc.extract_entry_statistics.return_value = {
            "files_scanned": 100,
            "directories_scanned": 5,
            "duration": 45.5,
        }
        view._statistics_calculator = mock_stats_calc

        # Set up scan log entry
        mock_log_entry.type = "scan"
        mock_log_entry.duration = 45.5

        view._display_log_details(mock_log_entry)

        # Verify buffer.set_text was called with statistics content
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "Statistics Summary:" in call_args
        assert "Files Scanned: 100" in call_args
        assert "Directories Scanned: 5" in call_args
        assert "Duration:" in call_args
        mock_stats_calc.extract_entry_statistics.assert_called_once_with(mock_log_entry)

    def test_statistics_summary_absent_for_update_log(self, logs_view_class, mock_log_entry):
        """Test that statistics summary does not appear for update logs."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer

        # Create a mock statistics calculator
        mock_stats_calc = mock.MagicMock()
        view._statistics_calculator = mock_stats_calc

        # Set up update log entry
        mock_log_entry.type = "update"
        mock_log_entry.duration = 30.0

        view._display_log_details(mock_log_entry)

        # Verify statistics summary is NOT in the output
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "Statistics Summary:" not in call_args
        assert "Files Scanned:" not in call_args
        assert "Directories Scanned:" not in call_args
        # Statistics calculator should not be called for update logs
        mock_stats_calc.extract_entry_statistics.assert_not_called()

    def test_statistics_summary_absent_when_no_data(self, logs_view_class, mock_log_entry):
        """Test that statistics summary is not shown when all values are zero."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer

        # Create a mock statistics calculator returning all zeros
        mock_stats_calc = mock.MagicMock()
        mock_stats_calc.extract_entry_statistics.return_value = {
            "files_scanned": 0,
            "directories_scanned": 0,
            "duration": 0,
        }
        view._statistics_calculator = mock_stats_calc

        # Set up scan log entry
        mock_log_entry.type = "scan"
        mock_log_entry.duration = 0

        view._display_log_details(mock_log_entry)

        # Verify statistics summary is NOT in the output
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "Statistics Summary:" not in call_args

    def test_statistics_summary_duration_formatting_seconds(self, logs_view_class, mock_log_entry):
        """Test that duration under 60 seconds is formatted correctly."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer

        # Create a mock statistics calculator
        mock_stats_calc = mock.MagicMock()
        mock_stats_calc.extract_entry_statistics.return_value = {
            "files_scanned": 10,
            "directories_scanned": 1,
            "duration": 45.5,
        }
        view._statistics_calculator = mock_stats_calc

        # Set up scan log entry
        mock_log_entry.type = "scan"
        mock_log_entry.duration = 45.5

        view._display_log_details(mock_log_entry)

        # Verify duration is formatted as seconds
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "Duration: 45.50 seconds" in call_args

    def test_statistics_summary_duration_formatting_minutes(self, logs_view_class, mock_log_entry):
        """Test that duration between 60 and 3600 seconds is formatted as minutes."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer

        # Create a mock statistics calculator
        mock_stats_calc = mock.MagicMock()
        mock_stats_calc.extract_entry_statistics.return_value = {
            "files_scanned": 100,
            "directories_scanned": 5,
            "duration": 125.0,  # 2 minutes 5 seconds
        }
        view._statistics_calculator = mock_stats_calc

        # Set up scan log entry
        mock_log_entry.type = "scan"
        mock_log_entry.duration = 125.0

        view._display_log_details(mock_log_entry)

        # Verify duration is formatted as minutes and seconds
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "Duration: 2m 5s" in call_args

    def test_statistics_summary_duration_formatting_hours(self, logs_view_class, mock_log_entry):
        """Test that duration over 3600 seconds is formatted as hours."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer

        # Create a mock statistics calculator
        mock_stats_calc = mock.MagicMock()
        mock_stats_calc.extract_entry_statistics.return_value = {
            "files_scanned": 10000,
            "directories_scanned": 500,
            "duration": 7200.0,  # 2 hours
        }
        view._statistics_calculator = mock_stats_calc

        # Set up scan log entry
        mock_log_entry.type = "scan"
        mock_log_entry.duration = 7200.0

        view._display_log_details(mock_log_entry)

        # Verify duration is formatted as hours and minutes
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "Duration: 2h 0m" in call_args

    def test_statistics_summary_partial_data(self, logs_view_class, mock_log_entry):
        """Test that statistics summary shows only when at least one value is non-zero."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer

        # Create a mock statistics calculator with only files scanned
        mock_stats_calc = mock.MagicMock()
        mock_stats_calc.extract_entry_statistics.return_value = {
            "files_scanned": 50,
            "directories_scanned": 0,
            "duration": 0,
        }
        view._statistics_calculator = mock_stats_calc

        # Set up scan log entry
        mock_log_entry.type = "scan"
        mock_log_entry.duration = 0

        view._display_log_details(mock_log_entry)

        # Verify statistics summary appears with only files scanned
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "Statistics Summary:" in call_args
        assert "Files Scanned: 50" in call_args
        # Directories and duration should not appear (zero values)
        assert "Directories Scanned: 0" not in call_args

    def test_statistics_summary_with_thousands_separator(self, logs_view_class, mock_log_entry):
        """Test that large numbers use thousands separator."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        view._detail_text.get_buffer.return_value = mock_buffer

        # Create a mock statistics calculator with large numbers
        mock_stats_calc = mock.MagicMock()
        mock_stats_calc.extract_entry_statistics.return_value = {
            "files_scanned": 12345,
            "directories_scanned": 678,
            "duration": 120.0,
        }
        view._statistics_calculator = mock_stats_calc

        # Set up scan log entry
        mock_log_entry.type = "scan"
        mock_log_entry.duration = 120.0

        view._display_log_details(mock_log_entry)

        # Verify thousands separator is used
        call_args = mock_buffer.set_text.call_args[0][0]
        assert "Files Scanned: 12,345" in call_args
        assert "Directories Scanned: 678" in call_args


class TestLogsViewCopyExport:
    """Tests for copy and export functionality."""

    def test_on_copy_detail_clicked_with_no_selection(self, logs_view_class):
        """Test that copy does nothing when no log selected."""
        view = object.__new__(logs_view_class)
        view._selected_log = None

        # Should return early without creating ClipboardHelper
        with mock.patch("src.ui.logs_view.ClipboardHelper") as mock_helper:
            view._on_copy_detail_clicked(mock.MagicMock())
            mock_helper.assert_not_called()

    def test_on_copy_detail_clicked_copies_content(self, logs_view_class, mock_log_entry):
        """Test that copy copies content to clipboard via ClipboardHelper."""
        view = object.__new__(logs_view_class)
        view._selected_log = mock_log_entry
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        mock_buffer.get_start_iter.return_value = mock.MagicMock()
        mock_buffer.get_end_iter.return_value = mock.MagicMock()
        mock_buffer.get_text.return_value = "log content"
        view._detail_text.get_buffer.return_value = mock_buffer
        view.get_root = mock.MagicMock(return_value=None)

        # Patch ClipboardHelper to verify it's called with correct content
        with mock.patch("src.ui.logs_view.ClipboardHelper") as mock_helper_class:
            mock_helper = mock.MagicMock()
            mock_helper_class.return_value = mock_helper

            view._on_copy_detail_clicked(mock.MagicMock())

            mock_helper_class.assert_called_once_with(parent_widget=view)
            mock_helper.copy_with_feedback.assert_called_once()
            # Verify the text argument
            call_kwargs = mock_helper.copy_with_feedback.call_args.kwargs
            assert call_kwargs["text"] == "log content"
            assert call_kwargs["success_message"] == "Log details copied to clipboard"

    def test_on_export_detail_text_clicked_with_no_selection(self, logs_view_class):
        """Test that export does nothing when no log selected."""
        view = object.__new__(logs_view_class)
        view._selected_log = None

        # Should return early without creating dialog
        view._on_export_detail_text_clicked(mock.MagicMock())

    def test_on_export_detail_csv_clicked_with_no_selection(self, logs_view_class):
        """Test that CSV export does nothing when no log selected."""
        view = object.__new__(logs_view_class)
        view._selected_log = None

        # Should return early without creating dialog
        view._on_export_detail_csv_clicked(mock.MagicMock())


class TestLogsViewCSVFormatting:
    """Tests for CSV formatting."""

    def test_format_log_entry_as_csv_basic(self, logs_view_class, mock_log_entry):
        """Test basic CSV formatting."""
        view = object.__new__(logs_view_class)

        result = view._format_log_entry_as_csv(mock_log_entry)

        # Verify header row is present
        assert "timestamp,type,status,path,summary,duration" in result
        # Verify data values are present
        assert mock_log_entry.timestamp in result
        assert mock_log_entry.type in result
        assert mock_log_entry.status in result

    def test_format_log_entry_as_csv_escapes_special_chars(self, logs_view_class, mock_log_entry):
        """Test CSV formatting with special characters."""
        view = object.__new__(logs_view_class)
        mock_log_entry.summary = 'Summary with "quotes" and, commas'

        result = view._format_log_entry_as_csv(mock_log_entry)

        # CSV should properly escape quotes
        assert result is not None

    def test_format_log_entry_as_csv_handles_no_path(self, logs_view_class, mock_log_entry):
        """Test CSV formatting when path is None."""
        view = object.__new__(logs_view_class)
        mock_log_entry.path = None

        result = view._format_log_entry_as_csv(mock_log_entry)

        # Should not raise an error
        assert result is not None

    def test_format_log_entry_as_csv_handles_zero_duration(self, logs_view_class, mock_log_entry):
        """Test CSV formatting with zero duration."""
        view = object.__new__(logs_view_class)
        mock_log_entry.duration = 0

        result = view._format_log_entry_as_csv(mock_log_entry)

        # Should output "0" for zero duration
        assert ",0\n" in result or ",0\r\n" in result


class TestLogsViewLogManagerProperty:
    """Tests for log_manager property."""

    def test_log_manager_property_returns_manager(self, mock_logs_view, mock_log_manager):
        """Test that log_manager property returns the internal manager."""
        result = mock_logs_view.log_manager

        assert result is mock_log_manager


class TestLogsViewShowExportToast:
    """Tests for export toast notifications."""

    def test_show_export_toast_success(self, logs_view_class):
        """Test showing success toast."""
        with mock.patch.dict(sys.modules, {"gi.repository.Adw": mock.MagicMock()}):
            from gi.repository import Adw

            view = object.__new__(logs_view_class)
            mock_window = mock.MagicMock()
            mock_window.add_toast = mock.MagicMock()
            view.get_root = mock.MagicMock(return_value=mock_window)

            view._show_export_toast("Export successful")

            Adw.Toast.new.assert_called_with("Export successful")
            mock_window.add_toast.assert_called_once()

    def test_show_export_toast_no_window(self, logs_view_class):
        """Test showing toast when no window available."""
        with mock.patch.dict(sys.modules, {"gi.repository.Adw": mock.MagicMock()}):
            view = object.__new__(logs_view_class)
            view.get_root = mock.MagicMock(return_value=None)

            # Should not raise an error
            view._show_export_toast("Export successful")


class TestLogsViewExportButtonState:
    """Tests for export button state management."""

    def test_export_buttons_disabled_when_no_logs(self, logs_view_class):
        """Test that export all buttons are disabled when no logs exist."""
        view = object.__new__(logs_view_class)
        view._is_loading = True
        view._logs_listbox = mock.MagicMock()
        view._clear_button = mock.MagicMock()
        view._export_all_csv_button = mock.MagicMock()
        view._export_all_json_button = mock.MagicMock()
        view._all_log_entries = []
        view._displayed_log_count = 0
        view._load_more_row = None
        view._set_loading_state = mock.MagicMock()

        view._on_logs_loaded([])

        view._export_all_csv_button.set_sensitive.assert_called_with(False)
        view._export_all_json_button.set_sensitive.assert_called_with(False)

    def test_export_buttons_enabled_when_logs_loaded(self, logs_view_class, mock_log_entry):
        """Test that export all buttons are enabled when logs are loaded."""
        view = object.__new__(logs_view_class)
        view._is_loading = True
        view._logs_listbox = mock.MagicMock()
        view._logs_listbox.get_row_at_index.return_value = mock.MagicMock()
        view._clear_button = mock.MagicMock()
        view._export_all_csv_button = mock.MagicMock()
        view._export_all_json_button = mock.MagicMock()
        view._all_log_entries = []
        view._displayed_log_count = 0
        view._load_more_row = None
        view._set_loading_state = mock.MagicMock()
        view._display_log_batch = mock.MagicMock()
        view._add_load_more_button = mock.MagicMock()

        logs = [mock_log_entry]
        view._on_logs_loaded(logs)

        view._export_all_csv_button.set_sensitive.assert_called_with(True)
        view._export_all_json_button.set_sensitive.assert_called_with(True)

    def test_export_buttons_disabled_during_loading(self, logs_view_class):
        """Test that export all buttons are disabled during loading."""
        view = object.__new__(logs_view_class)
        view._is_loading = False
        view._logs_spinner = mock.MagicMock()
        view._refresh_button = mock.MagicMock()
        view._clear_button = mock.MagicMock()
        view._export_all_csv_button = mock.MagicMock()
        view._export_all_json_button = mock.MagicMock()
        view._logs_listbox = mock.MagicMock()
        view._create_loading_state = mock.MagicMock()

        view._set_loading_state(True)

        view._export_all_csv_button.set_sensitive.assert_called_with(False)
        view._export_all_json_button.set_sensitive.assert_called_with(False)


class TestLogsViewExportAllCSVHandler:
    """Tests for export all to CSV handler."""

    def test_on_export_all_csv_clicked_returns_when_no_logs(self, logs_view_class, mock_gi_modules):
        """Test that export all CSV returns early when no logs."""
        view = object.__new__(logs_view_class)
        view._all_log_entries = []

        # Should return early without creating FileExportHelper
        view._on_export_all_csv_clicked(mock.MagicMock())

        # FileDialog should not be created (FileExportHelper not invoked)
        mock_gi_modules["gtk"].FileDialog.assert_not_called()

    def test_on_export_all_csv_clicked_creates_helper(
        self, logs_view_class, mock_log_entry, mock_gi_modules
    ):
        """Test that export all CSV creates FileExportHelper and shows dialog."""
        view = object.__new__(logs_view_class)
        view._all_log_entries = [mock_log_entry]
        view.get_root = mock.MagicMock(return_value=mock.MagicMock())
        view._format_all_logs_as_csv = mock.MagicMock(return_value="csv content")

        mock_dialog = mock.MagicMock()
        mock_gi_modules["gtk"].FileDialog.return_value = mock_dialog

        view._on_export_all_csv_clicked(mock.MagicMock())

        # FileExportHelper should create dialog via show_save_dialog
        mock_gi_modules["gtk"].FileDialog.assert_called_once()
        mock_dialog.set_title.assert_called_with("Export All Logs to CSV")
        # Initial filename should contain timestamp and csv extension
        assert mock_dialog.set_initial_name.called
        initial_name = mock_dialog.set_initial_name.call_args[0][0]
        assert initial_name.startswith("clamui_logs_")
        assert initial_name.endswith(".csv")
        mock_dialog.save.assert_called_once()


class TestLogsViewExportAllJSONHandler:
    """Tests for export all to JSON handler."""

    def test_on_export_all_json_clicked_returns_when_no_logs(
        self, logs_view_class, mock_gi_modules
    ):
        """Test that export all JSON returns early when no logs."""
        view = object.__new__(logs_view_class)
        view._all_log_entries = []

        view._on_export_all_json_clicked(mock.MagicMock())

        # FileDialog should not be created
        mock_gi_modules["gtk"].FileDialog.assert_not_called()

    def test_on_export_all_json_clicked_creates_helper(
        self, logs_view_class, mock_log_entry, mock_gi_modules
    ):
        """Test that export all JSON creates FileExportHelper and shows dialog."""
        view = object.__new__(logs_view_class)
        view._all_log_entries = [mock_log_entry]
        view.get_root = mock.MagicMock(return_value=mock.MagicMock())
        view._format_all_logs_as_json = mock.MagicMock(return_value="json content")

        mock_dialog = mock.MagicMock()
        mock_gi_modules["gtk"].FileDialog.return_value = mock_dialog

        view._on_export_all_json_clicked(mock.MagicMock())

        # FileExportHelper should create dialog
        mock_gi_modules["gtk"].FileDialog.assert_called_once()
        mock_dialog.set_title.assert_called_with("Export All Logs to JSON")
        # Initial filename should contain timestamp and .json extension
        assert mock_dialog.set_initial_name.called
        initial_name = mock_dialog.set_initial_name.call_args[0][0]
        assert initial_name.startswith("clamui_logs_")
        assert initial_name.endswith(".json")
        mock_dialog.save.assert_called_once()


class TestLogsViewExportDetailJSONHandler:
    """Tests for export single log to JSON handler."""

    def test_on_export_detail_json_clicked_returns_when_no_selection(
        self, logs_view_class, mock_gi_modules
    ):
        """Test that export detail JSON returns early when no log selected."""
        view = object.__new__(logs_view_class)
        view._selected_log = None

        view._on_export_detail_json_clicked(mock.MagicMock())

        # FileDialog should not be created
        mock_gi_modules["gtk"].FileDialog.assert_not_called()

    def test_on_export_detail_json_clicked_creates_helper(
        self, logs_view_class, mock_log_entry, mock_gi_modules
    ):
        """Test that export detail JSON creates FileExportHelper and shows dialog."""
        view = object.__new__(logs_view_class)
        view._selected_log = mock_log_entry
        view.get_root = mock.MagicMock(return_value=mock.MagicMock())
        view._format_log_entry_as_json = mock.MagicMock(return_value="json content")

        mock_dialog = mock.MagicMock()
        mock_gi_modules["gtk"].FileDialog.return_value = mock_dialog

        view._on_export_detail_json_clicked(mock.MagicMock())

        # FileExportHelper should create dialog with correct title
        mock_gi_modules["gtk"].FileDialog.assert_called_once()
        mock_dialog.set_title.assert_called_with("Export Log Details as JSON")
        # Initial filename should contain timestamp
        assert mock_dialog.set_initial_name.called
        initial_name = mock_dialog.set_initial_name.call_args[0][0]
        assert initial_name.startswith("clamui_log_")
        assert initial_name.endswith(".json")
        mock_dialog.save.assert_called_once()


class TestLogsViewContentFormatters:
    """Tests for content formatting helper methods."""

    def test_get_detail_text_content(self, logs_view_class):
        """Test that _get_detail_text_content extracts text from buffer."""
        view = object.__new__(logs_view_class)
        view._detail_text = mock.MagicMock()
        mock_buffer = mock.MagicMock()
        mock_start = mock.MagicMock()
        mock_end = mock.MagicMock()
        mock_buffer.get_start_iter.return_value = mock_start
        mock_buffer.get_end_iter.return_value = mock_end
        mock_buffer.get_text.return_value = "Log content here"
        view._detail_text.get_buffer.return_value = mock_buffer

        result = view._get_detail_text_content()

        assert result == "Log content here"
        mock_buffer.get_text.assert_called_once_with(mock_start, mock_end, False)

    def test_format_log_entry_as_json(self, logs_view_class, mock_log_entry):
        """Test that _format_log_entry_as_json produces valid JSON."""
        import json

        view = object.__new__(logs_view_class)

        result = view._format_log_entry_as_json(mock_log_entry)

        # Should be valid JSON
        data = json.loads(result)
        assert data["id"] == mock_log_entry.id
        assert data["type"] == mock_log_entry.type
        assert data["status"] == mock_log_entry.status
        assert data["timestamp"] == mock_log_entry.timestamp
        assert data["path"] == mock_log_entry.path
        assert data["summary"] == mock_log_entry.summary
        assert data["duration"] == mock_log_entry.duration
        assert data["details"] == mock_log_entry.details

    def test_format_all_logs_as_csv(self, logs_view_class, mock_log_entry):
        """Test that _format_all_logs_as_csv produces valid CSV with header."""
        view = object.__new__(logs_view_class)
        view._all_log_entries = [mock_log_entry, mock_log_entry]

        result = view._format_all_logs_as_csv()

        # Should have header row
        assert "timestamp,type,status,path,summary,duration" in result
        # Should have two data rows (plus header)
        lines = result.strip().split("\n")
        assert len(lines) == 3  # Header + 2 data rows

    def test_format_all_logs_as_csv_empty(self, logs_view_class):
        """Test that _format_all_logs_as_csv handles empty list."""
        view = object.__new__(logs_view_class)
        view._all_log_entries = []

        result = view._format_all_logs_as_csv()

        # Should only have header row
        assert "timestamp,type,status,path,summary,duration" in result
        lines = result.strip().split("\n")
        assert len(lines) == 1

    def test_format_all_logs_as_json(self, logs_view_class, mock_log_entry):
        """Test that _format_all_logs_as_json produces valid JSON array."""
        import json

        view = object.__new__(logs_view_class)
        view._all_log_entries = [mock_log_entry, mock_log_entry]

        result = view._format_all_logs_as_json()

        # Should be valid JSON array
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == mock_log_entry.id
        assert data[1]["id"] == mock_log_entry.id

    def test_format_all_logs_as_json_empty(self, logs_view_class):
        """Test that _format_all_logs_as_json handles empty list."""
        import json

        view = object.__new__(logs_view_class)
        view._all_log_entries = []

        result = view._format_all_logs_as_json()

        # Should be empty JSON array
        data = json.loads(result)
        assert data == []


class TestLogsViewUnmapMap:
    """Tests for widget mapping/unmapping lifecycle."""

    def test_do_unmap_stops_daemon_refresh(self, logs_view_class):
        """Test that unmapping stops daemon log refresh."""
        view = object.__new__(logs_view_class)
        view._stop_daemon_log_refresh = mock.MagicMock()
        view._live_toggle = mock.MagicMock()
        view._live_toggle.get_active.return_value = True

        # Call the method directly - parent class call is a no-op with mocks
        view.do_unmap()

        view._stop_daemon_log_refresh.assert_called_once()
        view._live_toggle.set_active.assert_called_with(False)


# Module-level test function for verification
def test_logs_view_basic(mock_gi_modules):
    """
    Basic test function for pytest verification command.

    This test verifies the core LogsView functionality
    using the centralized mock setup.
    """
    from src.ui.logs_view import LogsView
    from src.ui.pagination import PaginatedListController

    # Test 1: Class can be imported
    assert LogsView is not None

    # Test 2: Pagination constants are correct
    assert PaginatedListController.DEFAULT_INITIAL_LIMIT == 25
    assert PaginatedListController.DEFAULT_BATCH_SIZE == 25

    # Test 3: Create mock instance and test CSV formatting
    view = object.__new__(LogsView)

    # Create mock log entry
    mock_entry = mock.MagicMock()
    mock_entry.id = "test-123"
    mock_entry.timestamp = "2024-01-15T10:30:00"
    mock_entry.type = "scan"
    mock_entry.status = "clean"
    mock_entry.path = "/home/user"
    mock_entry.summary = "Test summary"
    mock_entry.duration = 30.5

    # Test _format_log_entry_as_csv
    csv_result = view._format_log_entry_as_csv(mock_entry)
    assert "timestamp" in csv_result
    assert "type" in csv_result
    assert "status" in csv_result
    assert "2024-01-15T10:30:00" in csv_result

    # All tests passed


class TestLogsViewDaemonOffThread:
    """Daemon status/log reads must run off the GTK main loop, not block it."""

    def test_refresh_daemon_logs_dispatches_to_worker_thread(
        self, logs_view_class, mock_log_manager
    ):
        """_refresh_daemon_logs must defer the blocking read to a worker thread."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._daemon_refresh_id = 123
        view._daemon_refresh_in_flight = False

        with mock.patch("src.ui.logs_view.threading") as mock_threading:
            result = view._refresh_daemon_logs()

        # The blocking read is NOT performed on the calling (main) loop.
        mock_log_manager.read_daemon_logs.assert_not_called()
        mock_threading.Thread.assert_called_once()
        assert mock_threading.Thread.call_args.kwargs["target"] == view._refresh_daemon_logs_worker
        mock_threading.Thread.return_value.start.assert_called_once()
        # Timer keeps firing while live refresh is active; guard is armed.
        assert result is True
        assert view._daemon_refresh_in_flight is True

    def test_refresh_daemon_logs_in_flight_guard_blocks_second_read(
        self, logs_view_class, mock_log_manager
    ):
        """A second tick while a read is in flight must not spawn another worker."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        view._daemon_refresh_id = 123
        view._daemon_refresh_in_flight = True  # a read is already running

        with mock.patch("src.ui.logs_view.threading") as mock_threading:
            result = view._refresh_daemon_logs()

        mock_threading.Thread.assert_not_called()
        assert result is True

    def test_refresh_worker_reads_and_schedules_apply(self, logs_view_class, mock_log_manager):
        """The worker performs the read and marshals the result onto the main loop."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager
        mock_log_manager.read_daemon_logs.return_value = (True, "content")

        with mock.patch("src.ui.logs_view.GLib") as mock_glib:
            view._refresh_daemon_logs_worker()

        mock_log_manager.read_daemon_logs.assert_called_once()
        mock_glib.idle_add.assert_called_once_with(view._apply_daemon_logs, True, "content")

    def test_check_daemon_status_dispatches_to_worker_thread(
        self, logs_view_class, mock_log_manager
    ):
        """_check_daemon_status must defer the blocking status probe to a worker thread."""
        view = object.__new__(logs_view_class)
        view._log_manager = mock_log_manager

        with mock.patch("src.ui.logs_view.threading") as mock_threading:
            result = view._check_daemon_status()

        mock_log_manager.get_daemon_status.assert_not_called()
        mock_threading.Thread.assert_called_once()
        assert mock_threading.Thread.call_args.kwargs["target"] == view._check_daemon_status_worker
        assert result is False
