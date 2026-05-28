# ClamUI TrayManager Tests
"""Unit tests for the TrayManager class (subprocess-based tray)."""

import json
import sys
from unittest import mock

import pytest

# Mock gi and GTK before any imports
_mock_gi = mock.MagicMock()
_mock_glib = mock.MagicMock()
_mock_glib.idle_add = mock.MagicMock(side_effect=lambda func, *args: func(*args))

_mock_repo = mock.MagicMock()
_mock_repo.GLib = _mock_glib


@pytest.fixture(autouse=True)
def mock_gtk_modules(monkeypatch):
    """Mock GTK modules for all tests."""
    monkeypatch.setitem(sys.modules, "gi", _mock_gi)
    monkeypatch.setitem(sys.modules, "gi.repository", _mock_repo)
    _mock_gi.require_version = mock.MagicMock()
    yield


class TestTrayManagerModuleFunctions:
    """Tests for module-level functions."""

    def test_is_available_returns_true(self, mock_gtk_modules):
        """Test is_available returns True (subprocess always available)."""
        from src.ui.tray_manager import is_available

        assert is_available() is True

    def test_get_unavailable_reason_returns_none(self, mock_gtk_modules):
        """Test get_unavailable_reason returns None (subprocess handles it)."""
        from src.ui.tray_manager import get_unavailable_reason

        assert get_unavailable_reason() is None


class TestTrayManagerInit:
    """Tests for TrayManager initialization."""

    def test_init_creates_instance(self, mock_gtk_modules):
        """Test TrayManager can be instantiated."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        assert manager is not None

    def test_init_has_no_process(self, mock_gtk_modules):
        """Test TrayManager starts with no process."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        assert manager._process is None

    def test_init_callbacks_are_none(self, mock_gtk_modules):
        """Test TrayManager initializes with no callbacks."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        assert manager._on_quick_scan is None
        assert manager._on_full_scan is None
        assert manager._on_update is None
        assert manager._on_quit is None
        assert manager._on_window_toggle is None
        assert manager._on_profile_select is None

    def test_init_not_running(self, mock_gtk_modules):
        """Test TrayManager starts as not running."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        assert manager._running is False
        assert manager._ready is False


class TestTrayManagerCallbacks:
    """Tests for TrayManager callback methods."""

    def test_set_action_callbacks_stores_callbacks(self, mock_gtk_modules):
        """Test set_action_callbacks stores the callback references."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        quick_scan = mock.Mock()
        full_scan = mock.Mock()
        update = mock.Mock()
        quit_cb = mock.Mock()

        manager.set_action_callbacks(
            on_quick_scan=quick_scan, on_full_scan=full_scan, on_update=update, on_quit=quit_cb
        )

        assert manager._on_quick_scan is quick_scan
        assert manager._on_full_scan is full_scan
        assert manager._on_update is update
        assert manager._on_quit is quit_cb

    def test_set_window_toggle_callback_stores_callback(self, mock_gtk_modules):
        """Test set_window_toggle_callback stores the callback."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        toggle_cb = mock.Mock()
        manager.set_window_toggle_callback(toggle_cb)

        assert manager._on_window_toggle is toggle_cb

    def test_set_profile_select_callback_stores_callback(self, mock_gtk_modules):
        """Test set_profile_select_callback stores the callback."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        profile_cb = mock.Mock()
        manager.set_profile_select_callback(profile_cb)

        assert manager._on_profile_select is profile_cb


class TestTrayManagerHandleMenuAction:
    """Tests for TrayManager._handle_menu_action method."""

    def test_handle_quick_scan_action(self, mock_gtk_modules):
        """Test handling quick_scan action invokes callback."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_quick_scan = callback

        manager._handle_menu_action("quick_scan", {})

        callback.assert_called_once()

    def test_handle_full_scan_action(self, mock_gtk_modules):
        """Test handling full_scan action invokes callback."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_full_scan = callback

        manager._handle_menu_action("full_scan", {})

        callback.assert_called_once()

    def test_handle_update_action(self, mock_gtk_modules):
        """Test handling update action invokes callback."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_update = callback

        manager._handle_menu_action("update", {})

        callback.assert_called_once()

    def test_handle_quit_action(self, mock_gtk_modules):
        """Test handling quit action invokes callback."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_quit = callback

        manager._handle_menu_action("quit", {})

        callback.assert_called_once()

    def test_handle_toggle_window_action(self, mock_gtk_modules):
        """Test handling toggle_window action invokes callback."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_window_toggle = callback

        manager._handle_menu_action("toggle_window", {})

        callback.assert_called_once()

    def test_handle_select_profile_action(self, mock_gtk_modules):
        """Test handling select_profile action invokes callback with profile_id."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_profile_select = callback

        # Simulate message with profile_id
        message = {"action": "select_profile", "profile_id": "test-profile-123"}
        manager._handle_menu_action("select_profile", message)

        callback.assert_called_once_with("test-profile-123")

    def test_handle_select_profile_action_updates_current_profile(self, mock_gtk_modules):
        """Test handling select_profile updates current_profile_id."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_profile_select = callback

        message = {"action": "select_profile", "profile_id": "new-profile-id"}
        manager._handle_menu_action("select_profile", message)

        assert manager._current_profile_id == "new-profile-id"

    def test_handle_select_profile_action_no_profile_id(self, mock_gtk_modules):
        """Test handling select_profile without profile_id doesn't invoke callback."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_profile_select = callback

        # Message without profile_id
        message = {"action": "select_profile"}
        manager._handle_menu_action("select_profile", message)

        callback.assert_not_called()

    def test_handle_unknown_action_does_not_crash(self, mock_gtk_modules):
        """Test handling unknown action doesn't crash."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        # Should not raise
        manager._handle_menu_action("unknown_action", {})


class TestTrayManagerHandleMessage:
    """Tests for TrayManager._handle_message method."""

    def test_handle_ready_message(self, mock_gtk_modules):
        """Test handling ready message sets ready flag."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        assert manager._ready is False

        manager._handle_message({"event": "ready"})

        assert manager._ready is True

    def test_handle_pong_message(self, mock_gtk_modules):
        """Test handling pong message doesn't crash."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        # Should not raise
        manager._handle_message({"event": "pong"})

    def test_handle_error_message(self, mock_gtk_modules):
        """Test handling error message logs error."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        # Should not raise
        manager._handle_message({"event": "error", "message": "test error"})

    def test_handle_menu_action_message(self, mock_gtk_modules):
        """Test handling menu_action message invokes action handler."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        callback = mock.Mock()
        manager._on_quick_scan = callback

        manager._handle_message({"event": "menu_action", "action": "quick_scan"})

        callback.assert_called_once()


class TestTrayManagerSendCommand:
    """Tests for TrayManager._send_command method."""

    def test_send_command_returns_false_without_process(self, mock_gtk_modules):
        """Test _send_command returns False when no process."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        result = manager._send_command({"action": "test"})

        assert result is False

    def test_send_command_writes_to_stdin(self, mock_gtk_modules):
        """Test _send_command writes JSON to process stdin."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_stdin = mock.Mock()
        mock_process = mock.Mock()
        mock_process.stdin = mock_stdin
        manager._process = mock_process

        command = {"action": "update_status", "status": "scanning"}
        result = manager._send_command(command)

        assert result is True
        mock_stdin.write.assert_called_once()
        mock_stdin.flush.assert_called_once()

        # Verify JSON format
        written_data = mock_stdin.write.call_args[0][0]
        assert json.loads(written_data.strip()) == command


class TestTrayManagerUpdateMethods:
    """Tests for TrayManager update methods."""

    def test_update_status_sends_command(self, mock_gtk_modules):
        """Test update_status sends correct command."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with mock.patch.object(manager, "_send_command") as mock_send:
            manager.update_status("scanning")

            mock_send.assert_called_once_with({"action": "update_status", "status": "scanning"})

    def test_update_status_tracks_current_status(self, mock_gtk_modules):
        """Test update_status tracks current status."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with mock.patch.object(manager, "_send_command"):
            manager.update_status("threat")

        assert manager._current_status == "threat"

    def test_update_scan_progress_sends_command(self, mock_gtk_modules):
        """Test update_scan_progress sends correct command."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with mock.patch.object(manager, "_send_command") as mock_send:
            manager.update_scan_progress(75)

            mock_send.assert_called_once_with({"action": "update_progress", "percentage": 75})

    def test_update_window_menu_label_sends_command(self, mock_gtk_modules):
        """Test update_window_menu_label sends correct command."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with mock.patch.object(manager, "_send_command") as mock_send:
            manager.update_window_menu_label(visible=True)

            mock_send.assert_called_once_with({"action": "update_window_visible", "visible": True})

    def test_update_profiles_sends_command(self, mock_gtk_modules):
        """Test update_profiles sends correct command with profiles list."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        profiles = [
            {"id": "profile-1", "name": "Quick Scan", "is_default": True},
            {"id": "profile-2", "name": "Full Scan", "is_default": True},
        ]

        with mock.patch.object(manager, "_send_command") as mock_send:
            manager.update_profiles(profiles, "profile-1")

            mock_send.assert_called_once_with(
                {
                    "action": "update_profiles",
                    "profiles": profiles,
                    "current_profile_id": "profile-1",
                }
            )

    def test_update_profiles_stores_current_profile_id(self, mock_gtk_modules):
        """Test update_profiles stores current_profile_id."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        profiles = [{"id": "test-id", "name": "Test", "is_default": False}]

        with mock.patch.object(manager, "_send_command"):
            manager.update_profiles(profiles, "test-id")

        assert manager._current_profile_id == "test-id"


class TestTrayManagerProperties:
    """Tests for TrayManager properties."""

    def test_is_active_false_when_not_running(self, mock_gtk_modules):
        """Test is_active is False when not running."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        assert manager.is_active is False

    def test_is_active_false_when_not_ready(self, mock_gtk_modules):
        """Test is_active is False when not ready."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._process = mock.Mock()
        manager._ready = False

        assert manager.is_active is False

    def test_is_active_true_when_running_and_ready(self, mock_gtk_modules):
        """Test is_active is True when running and ready."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._process = mock.Mock()
        manager._ready = True

        assert manager.is_active is True

    def test_is_library_available_depends_on_process(self, mock_gtk_modules):
        """Test is_library_available depends on running process."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        assert manager.is_library_available is False

        manager._running = True
        manager._process = mock.Mock()

        assert manager.is_library_available is True

    def test_current_status_returns_status(self, mock_gtk_modules):
        """Test current_status returns current status."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        assert manager.current_status == "protected"

        manager._current_status = "scanning"
        assert manager.current_status == "scanning"


class TestTrayManagerCleanup:
    """Tests for TrayManager cleanup methods."""

    def test_cleanup_clears_callbacks(self, mock_gtk_modules):
        """Test cleanup clears all callbacks."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        manager._on_quick_scan = mock.Mock()
        manager._on_full_scan = mock.Mock()
        manager._on_update = mock.Mock()
        manager._on_quit = mock.Mock()
        manager._on_window_toggle = mock.Mock()
        manager._on_profile_select = mock.Mock()

        manager.cleanup()

        assert manager._on_quick_scan is None
        assert manager._on_full_scan is None
        assert manager._on_update is None
        assert manager._on_quit is None
        assert manager._on_window_toggle is None
        assert manager._on_profile_select is None

    def test_stop_sends_quit_command(self, mock_gtk_modules):
        """Test stop sends quit command to subprocess."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_process = mock.Mock()
        mock_process.wait = mock.Mock()
        manager._process = mock_process
        manager._running = True

        with mock.patch.object(manager, "_send_command") as mock_send:
            manager.stop()

            mock_send.assert_called_with({"action": "quit"})

    def test_stop_sets_running_false(self, mock_gtk_modules):
        """Test stop sets running to False."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        manager.stop()

        assert manager._running is False

    def test_cleanup_can_be_called_multiple_times(self, mock_gtk_modules):
        """Test cleanup can be called multiple times safely."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        # Should not raise
        manager.cleanup()
        manager.cleanup()
        manager.cleanup()


class TestTrayManagerStart:
    """Tests for TrayManager.start method."""

    def test_start_returns_false_without_service_path(self, mock_gtk_modules):
        """Test start returns False if service path not found."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with mock.patch.object(manager, "_get_service_path", return_value=None):
            result = manager.start()

        assert result is False

    def test_start_already_running_returns_true(self, mock_gtk_modules):
        """Test start returns True if already running."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._process = mock.Mock()

        result = manager.start()

        assert result is True


class TestTrayManagerPipeCleanup:
    """Tests for TrayManager pipe cleanup on abnormal termination."""

    def test_close_pipes_closes_all_pipes(self, mock_gtk_modules):
        """Test _close_pipes closes stdin, stdout, and stderr."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_stdin = mock.Mock()
        mock_stdout = mock.Mock()
        mock_stderr = mock.Mock()

        mock_process = mock.Mock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        manager._process = mock_process

        manager._close_pipes()

        mock_stdin.close.assert_called_once()
        mock_stdout.close.assert_called_once()
        mock_stderr.close.assert_called_once()

    def test_close_pipes_handles_none_process(self, mock_gtk_modules):
        """Test _close_pipes handles None process gracefully."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._process = None

        # Should not raise
        manager._close_pipes()

    def test_close_pipes_handles_none_pipes(self, mock_gtk_modules):
        """Test _close_pipes handles None pipes gracefully."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_process = mock.Mock()
        mock_process.stdin = None
        mock_process.stdout = None
        mock_process.stderr = None
        manager._process = mock_process

        # Should not raise
        manager._close_pipes()

    def test_close_pipes_handles_close_exception(self, mock_gtk_modules):
        """Test _close_pipes handles exceptions during close."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_stdin = mock.Mock()
        mock_stdin.close.side_effect = OSError("Pipe broken")
        mock_stdout = mock.Mock()
        mock_stderr = mock.Mock()

        mock_process = mock.Mock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        manager._process = mock_process

        # Should not raise
        manager._close_pipes()

        # Other pipes should still be closed
        mock_stdout.close.assert_called_once()
        mock_stderr.close.assert_called_once()

    def test_close_pipes_can_be_called_multiple_times(self, mock_gtk_modules):
        """Test _close_pipes can be called multiple times safely."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_stdin = mock.Mock()
        mock_stdout = mock.Mock()
        mock_stderr = mock.Mock()

        mock_process = mock.Mock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        manager._process = mock_process

        # First call
        manager._close_pipes()

        # Simulate pipes already closed on second call
        mock_stdin.close.side_effect = OSError("Already closed")
        mock_stdout.close.side_effect = OSError("Already closed")
        mock_stderr.close.side_effect = OSError("Already closed")

        # Should not raise
        manager._close_pipes()

    def test_del_calls_close_pipes(self, mock_gtk_modules):
        """Test __del__ calls _close_pipes for cleanup."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with mock.patch.object(manager, "_close_pipes") as mock_close:
            manager.__del__()
            mock_close.assert_called_once()

    def test_stop_uses_close_pipes(self, mock_gtk_modules):
        """Test stop method uses _close_pipes for cleanup."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_process = mock.Mock()
        mock_process.wait = mock.Mock()
        manager._process = mock_process
        manager._running = True

        with mock.patch.object(manager, "_send_command"):
            with mock.patch.object(manager, "_close_pipes") as mock_close:
                manager.stop()
                mock_close.assert_called_once()

    def test_manager_registered_in_active_managers(self, mock_gtk_modules):
        """Test TrayManager is registered in _active_managers on creation."""
        from src.ui.tray_manager import TrayManager, _active_managers

        manager = TrayManager()

        assert manager in _active_managers

    def test_atexit_handler_registered(self, mock_gtk_modules):
        """Test atexit handler is registered."""
        # The atexit handler should be registered
        # We verify by checking the module's _atexit_registered flag
        from src.ui import tray_manager

        assert tray_manager._atexit_registered is True

    def test_cleanup_all_managers_closes_all_instances(self, mock_gtk_modules):
        """Test _cleanup_all_managers closes all active manager instances."""
        from src.ui.tray_manager import TrayManager, _cleanup_all_managers

        # Create multiple managers
        manager1 = TrayManager()
        manager2 = TrayManager()

        # Set up mock processes
        mock_process1 = mock.Mock()
        mock_process1.stdin = mock.Mock()
        mock_process1.stdout = mock.Mock()
        mock_process1.stderr = mock.Mock()
        manager1._process = mock_process1

        mock_process2 = mock.Mock()
        mock_process2.stdin = mock.Mock()
        mock_process2.stdout = mock.Mock()
        mock_process2.stderr = mock.Mock()
        manager2._process = mock_process2

        # Run atexit cleanup
        _cleanup_all_managers()

        # Verify pipes were closed
        mock_process1.stdin.close.assert_called()
        mock_process2.stdin.close.assert_called()


class TestTrayManagerReadStdout:
    """Tests for TrayManager._read_stdout method (reader thread)."""

    def test_read_stdout_exits_when_process_none(self, mock_gtk_modules):
        """Test _read_stdout exits early when process is None."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._process = None

        # Should return without error
        manager._read_stdout()

    def test_read_stdout_exits_when_stdout_none(self, mock_gtk_modules):
        """Test _read_stdout exits early when stdout is None."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        mock_process = mock.Mock()
        mock_process.stdout = None
        manager._process = mock_process

        # Should return without error
        manager._read_stdout()

    def test_read_stdout_processes_valid_json_messages(self, mock_gtk_modules):
        """Test _read_stdout correctly parses and handles valid JSON messages."""
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        # Mark as shutting down so EOF at end of mock stream doesn't trigger
        # the crash-recovery / respawn path (UI-001 fix).
        manager._shutting_down = True

        # Simulate stdout with JSON messages
        messages = ['{"event": "ready"}\n', '{"event": "pong"}\n']
        mock_stdout = StringIO("".join(messages))

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        manager._process = mock_process

        # Run _read_stdout
        manager._read_stdout()

        # Check that ready event was handled
        assert manager._ready is True

    def test_read_stdout_handles_empty_lines(self, mock_gtk_modules):
        """Test _read_stdout skips empty lines."""
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._shutting_down = True  # Suppress UI-001 respawn path on EOF

        # Simulate stdout with empty lines
        messages = ["\n", "   \n", '{"event": "ready"}\n', "\n"]
        mock_stdout = StringIO("".join(messages))

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        manager._process = mock_process

        # Should not crash
        manager._read_stdout()
        assert manager._ready is True

    def test_read_stdout_handles_invalid_json(self, mock_gtk_modules, caplog):
        """Test _read_stdout handles invalid JSON gracefully."""
        import logging
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._shutting_down = True  # Suppress UI-001 respawn path on EOF

        # Simulate stdout with invalid JSON
        messages = ["not valid json\n", "{invalid}\n", '{"event": "ready"}\n']
        mock_stdout = StringIO("".join(messages))

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        manager._process = mock_process

        with caplog.at_level(logging.ERROR):
            manager._read_stdout()

        # Should log errors for invalid JSON but continue processing
        assert "Invalid JSON from tray service" in caplog.text
        # Valid message should still be processed
        assert manager._ready is True

    def test_read_stdout_rejects_oversized_messages(self, mock_gtk_modules, caplog):
        """Test _read_stdout rejects messages exceeding MAX_MESSAGE_SIZE."""
        import logging
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._shutting_down = True  # Suppress UI-001 respawn path on EOF

        # Create oversized message (> 1MB)
        oversized_data = "x" * (TrayManager.MAX_MESSAGE_SIZE + 1)
        messages = [oversized_data + "\n", '{"event": "ready"}\n']
        mock_stdout = StringIO("".join(messages))

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        manager._process = mock_process

        with caplog.at_level(logging.ERROR):
            manager._read_stdout()

        # Should log error about size limit
        assert "exceeds size limit" in caplog.text
        # Valid message after oversized should still be processed
        assert manager._ready is True

    def test_read_stdout_stops_when_running_false(self, mock_gtk_modules):
        """Test _read_stdout stops when _running becomes False."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        # Create an iterator that sets _running to False after first message
        def message_generator():
            yield '{"event": "pong"}\n'
            manager._running = False
            yield '{"event": "ready"}\n'  # Should not be processed

        mock_stdout = mock.Mock()
        mock_stdout.__iter__ = lambda self: iter(message_generator())

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        manager._process = mock_process

        manager._read_stdout()

        # ready should NOT be set because we stopped before that message
        assert manager._ready is False

    def test_read_stdout_handles_exception_gracefully(self, mock_gtk_modules, caplog):
        """Test _read_stdout handles exceptions without crashing."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        # Simulate stdout that raises an exception
        mock_stdout = mock.Mock()
        mock_stdout.__iter__ = mock.Mock(side_effect=OSError("Pipe broken"))

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        manager._process = mock_process

        with caplog.at_level(logging.ERROR):
            manager._read_stdout()

        assert "Error reading tray service stdout" in caplog.text


class TestTrayManagerValidateMessageStructure:
    """Tests for TrayManager._validate_message_structure method."""

    def test_valid_simple_message(self, mock_gtk_modules):
        """Test validation of simple valid message."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        message = {"event": "ready"}
        assert manager._validate_message_structure(message) is True

    def test_valid_message_with_nested_data(self, mock_gtk_modules):
        """Test validation of message with nested data."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        message = {
            "event": "menu_action",
            "action": "select_profile",
            "profile_id": "test-123",
            "data": {"nested": {"key": "value"}},
        }
        assert manager._validate_message_structure(message) is True

    def test_rejects_message_without_event_field(self, mock_gtk_modules):
        """Test rejection of message without 'event' field."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        message = {"action": "something", "data": "value"}
        assert manager._validate_message_structure(message) is False

    def test_rejects_deeply_nested_message(self, mock_gtk_modules):
        """Test rejection of excessively nested message."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        # Build deeply nested structure
        deep_message = {"event": "test"}
        current = deep_message
        for _ in range(TrayManager.MAX_NESTING_DEPTH + 5):
            current["nested"] = {}
            current = current["nested"]

        assert manager._validate_message_structure(deep_message) is False

    def test_accepts_message_at_max_depth(self, mock_gtk_modules):
        """Test acceptance of message exactly at max nesting depth."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        # Build nested structure at exactly max depth
        deep_message = {"event": "test"}
        current = deep_message
        for _ in range(TrayManager.MAX_NESTING_DEPTH - 1):
            current["nested"] = {}
            current = current["nested"]

        assert manager._validate_message_structure(deep_message) is True

    def test_validates_list_items(self, mock_gtk_modules):
        """Test validation recurses into list items."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        message = {
            "event": "update_profiles",
            "profiles": [
                {"id": "1", "name": "Profile 1"},
                {"id": "2", "name": "Profile 2"},
            ],
        }
        assert manager._validate_message_structure(message) is True

    def test_rejects_deeply_nested_list(self, mock_gtk_modules):
        """Test rejection of deeply nested list structure."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        # Build deeply nested list structure
        deep_list = [[[[[[[[[[[[["too deep"]]]]]]]]]]]]]
        message = {"event": "test", "data": deep_list}

        assert manager._validate_message_structure(message) is False

    def test_accepts_primitive_values(self, mock_gtk_modules):
        """Test validation accepts primitive values."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        message = {
            "event": "test",
            "string": "hello",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
        }
        assert manager._validate_message_structure(message) is True


class TestTrayManagerReadStderr:
    """Tests for TrayManager._read_stderr method."""

    def test_read_stderr_exits_when_process_none(self, mock_gtk_modules):
        """Test _read_stderr exits early when process is None."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._process = None

        # Should return without error
        manager._read_stderr()

    def test_read_stderr_exits_when_stderr_none(self, mock_gtk_modules):
        """Test _read_stderr exits early when stderr is None."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        mock_process = mock.Mock()
        mock_process.stderr = None
        manager._process = mock_process

        # Should return without error
        manager._read_stderr()

    def test_read_stderr_logs_messages(self, mock_gtk_modules, caplog):
        """Test _read_stderr logs messages from subprocess."""
        import logging
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        # Simulate stderr with messages
        stderr_messages = ["Debug message\n", "Another message\n"]
        mock_stderr = StringIO("".join(stderr_messages))

        mock_process = mock.Mock()
        mock_process.stderr = mock_stderr
        manager._process = mock_process

        with caplog.at_level(logging.DEBUG, logger="src.ui.tray_manager"):
            manager._read_stderr()

        assert "[TrayService] Debug message" in caplog.text
        assert "[TrayService] Another message" in caplog.text

    def test_read_stderr_skips_empty_lines(self, mock_gtk_modules, caplog):
        """Test _read_stderr skips empty lines."""
        import logging
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        # Simulate stderr with empty lines
        stderr_messages = ["\n", "   \n", "Actual message\n"]
        mock_stderr = StringIO("".join(stderr_messages))

        mock_process = mock.Mock()
        mock_process.stderr = mock_stderr
        manager._process = mock_process

        with caplog.at_level(logging.DEBUG, logger="src.ui.tray_manager"):
            manager._read_stderr()

        # Should only log the non-empty message
        assert "[TrayService] Actual message" in caplog.text

    def test_read_stderr_stops_when_running_false(self, mock_gtk_modules, caplog):
        """Test _read_stderr stops when _running becomes False."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        # Create an iterator that sets _running to False after first message
        def message_generator():
            yield "First message\n"
            manager._running = False
            yield "Second message\n"  # Should not be logged

        mock_stderr = mock.Mock()
        mock_stderr.__iter__ = lambda self: iter(message_generator())

        mock_process = mock.Mock()
        mock_process.stderr = mock_stderr
        manager._process = mock_process

        with caplog.at_level(logging.DEBUG, logger="src.ui.tray_manager"):
            manager._read_stderr()

        assert "[TrayService] First message" in caplog.text
        assert "Second message" not in caplog.text

    def test_read_stderr_handles_exception_gracefully(self, mock_gtk_modules, caplog):
        """Test _read_stderr handles exceptions without crashing."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        # Simulate stderr that raises an exception
        mock_stderr = mock.Mock()
        mock_stderr.__iter__ = mock.Mock(side_effect=OSError("Pipe broken"))

        mock_process = mock.Mock()
        mock_process.stderr = mock_stderr
        manager._process = mock_process

        with caplog.at_level(logging.ERROR):
            manager._read_stderr()

        assert "Error reading tray service stderr" in caplog.text


class TestTrayManagerHandleMessageEvents:
    """Tests for TrayManager._handle_message with various event types."""

    def test_handle_unknown_event(self, mock_gtk_modules, caplog):
        """Test handling unknown event logs warning."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with caplog.at_level(logging.WARNING):
            manager._handle_message({"event": "unknown_event"})

        assert "Unknown event from tray service: unknown_event" in caplog.text

    def test_handle_error_event_with_message(self, mock_gtk_modules, caplog):
        """Test handling error event logs the error message."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with caplog.at_level(logging.ERROR):
            manager._handle_message({"event": "error", "message": "Test error message"})

        assert "Tray service error: Test error message" in caplog.text

    def test_handle_error_event_without_message(self, mock_gtk_modules, caplog):
        """Test handling error event without message field."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with caplog.at_level(logging.ERROR):
            manager._handle_message({"event": "error"})

        assert "Tray service error: Unknown error" in caplog.text


class TestTrayManagerThreadSafety:
    """Tests for TrayManager thread safety."""

    def test_concurrent_status_updates(self, mock_gtk_modules):
        """Test concurrent status updates are thread-safe."""
        import threading

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        statuses = ["protected", "warning", "scanning", "threat"]
        results = []

        def update_status(status):
            with mock.patch.object(manager, "_send_command"):
                manager.update_status(status)
                results.append(manager._current_status)

        threads = []
        for status in statuses * 10:  # Run multiple times
            t = threading.Thread(target=update_status, args=(status,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All updates should have completed without error
        assert len(results) == 40

    def test_state_lock_protects_ready_flag(self, mock_gtk_modules):
        """Test _state_lock protects _ready flag during concurrent access."""
        import threading

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        def set_ready():
            for _ in range(100):
                manager._handle_message({"event": "ready"})

        def check_ready():
            results = []
            for _ in range(100):
                # This should be thread-safe
                with manager._state_lock:
                    results.append(manager._ready)
            return results

        t1 = threading.Thread(target=set_ready)
        t2 = threading.Thread(target=check_ready)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Final state should be ready
        assert manager._ready is True

    def test_profile_id_update_is_thread_safe(self, mock_gtk_modules):
        """Test _current_profile_id updates are thread-safe."""
        import threading

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._on_profile_select = mock.Mock()

        profile_ids = [f"profile-{i}" for i in range(10)]

        def select_profile(profile_id):
            manager._handle_menu_action(
                "select_profile", {"action": "select_profile", "profile_id": profile_id}
            )

        threads = []
        for profile_id in profile_ids * 5:
            t = threading.Thread(target=select_profile, args=(profile_id,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All updates should have completed without error
        assert manager._on_profile_select.call_count == 50


class TestTrayManagerEdgeCases:
    """Tests for TrayManager edge cases and error recovery."""

    def test_send_command_handles_write_exception(self, mock_gtk_modules, caplog):
        """Test _send_command handles write exceptions gracefully."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_stdin = mock.Mock()
        mock_stdin.write.side_effect = BrokenPipeError("Pipe closed")
        mock_process = mock.Mock()
        mock_process.stdin = mock_stdin
        manager._process = mock_process

        with caplog.at_level(logging.ERROR):
            result = manager._send_command({"action": "test"})

        assert result is False
        assert "Failed to send command to tray service" in caplog.text

    def test_send_command_handles_flush_exception(self, mock_gtk_modules, caplog):
        """Test _send_command handles flush exceptions gracefully."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_stdin = mock.Mock()
        mock_stdin.write = mock.Mock()
        mock_stdin.flush.side_effect = BrokenPipeError("Pipe closed")
        mock_process = mock.Mock()
        mock_process.stdin = mock_stdin
        manager._process = mock_process

        with caplog.at_level(logging.ERROR):
            result = manager._send_command({"action": "test"})

        assert result is False
        assert "Failed to send command to tray service" in caplog.text

    def test_send_command_returns_false_when_stdin_none(self, mock_gtk_modules):
        """Test _send_command returns False when stdin is None."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_process = mock.Mock()
        mock_process.stdin = None
        manager._process = mock_process

        result = manager._send_command({"action": "test"})

        assert result is False

    def test_stop_handles_timeout_expired(self, mock_gtk_modules, caplog):
        """Test stop handles subprocess not stopping gracefully."""
        import logging
        import subprocess

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_process = mock.Mock()
        mock_process.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 2.0),  # First wait (graceful)
            subprocess.TimeoutExpired("cmd", 1.0),  # Second wait (after terminate)
        ]
        mock_process.stdin = mock.Mock()
        mock_process.stdout = mock.Mock()
        mock_process.stderr = mock.Mock()
        manager._process = mock_process
        manager._running = True

        with caplog.at_level(logging.WARNING):
            manager.stop()

        # Should have called terminate and kill
        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        assert "Tray service didn't stop gracefully" in caplog.text
        assert "Tray service didn't terminate" in caplog.text

    def test_stop_handles_exception(self, mock_gtk_modules, caplog):
        """Test stop handles exceptions during shutdown."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        mock_process = mock.Mock()
        mock_process.wait.side_effect = Exception("Unexpected error")
        mock_process.stdin = mock.Mock()
        mock_process.stdout = mock.Mock()
        mock_process.stderr = mock.Mock()
        manager._process = mock_process
        manager._running = True

        with caplog.at_level(logging.ERROR):
            manager.stop()

        assert "Error stopping tray service" in caplog.text
        # Process should be cleared
        assert manager._process is None

    def test_menu_action_without_callback_logs_warning(self, mock_gtk_modules, caplog):
        """Test handling menu action without callback logs warning."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        # No callbacks set

        with caplog.at_level(logging.WARNING):
            manager._handle_menu_action("quick_scan", {})

        assert "No handler for action: quick_scan" in caplog.text

    def test_get_service_path_module_import(self, mock_gtk_modules):
        """Test _get_service_path falls back to module import."""
        from pathlib import Path

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        # Create a proper mock module with __file__ attribute
        mock_module = mock.MagicMock()
        mock_module.__file__ = "/fake/path/to/tray_service.py"

        # Mock Path.exists to return False for first path, True for second
        import src.ui as ui_package

        with mock.patch.object(Path, "exists", side_effect=[False, True]):
            with mock.patch.dict("sys.modules", {"src.ui.tray_service": mock_module}):
                with mock.patch.object(ui_package, "tray_service", mock_module, create=True):
                    # This should try the module import path
                    result = manager._get_service_path()

        # Should return the module path
        assert result == Path("/fake/path/to/tray_service.py")

    def test_start_exception_handling(self, mock_gtk_modules, caplog):
        """Test start handles exceptions during subprocess creation."""
        import logging

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        with mock.patch.object(manager, "_get_service_path", return_value="/fake/path"):
            with mock.patch("subprocess.Popen", side_effect=OSError("Cannot create process")):
                with caplog.at_level(logging.ERROR):
                    result = manager.start()

        assert result is False
        assert "Failed to start tray service" in caplog.text
        assert manager._process is None


class TestTrayManagerSubprocessCrashRecovery:
    """Regression tests for UI-001 — silent tray subprocess crash detection.

    Prior behavior: when the tray subprocess died (segfault, OOM, D-Bus loss)
    the stdout reader exited silently on EOF; ``_ready`` stayed True; ``is_active``
    kept reporting True; ``_send_command`` wrote to a closed pipe and just logged.

    Expected behavior after the fix:
    - on EOF, ``_ready`` is reset to False
    - subprocess exit is observed via ``poll()``
    - ``start()`` is called again to respawn (bounded)
    - after 3 rapid respawns, respawn stops and ``_tray_down`` flag is set
    - no respawn is attempted while ``stop()`` is in progress (``_shutting_down``)
    """

    def test_subprocess_eof_resets_ready_flag(self, mock_gtk_modules):
        """When stdout EOFs (subprocess died), ``_ready`` must be reset to False."""
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._ready = True  # Simulate subprocess that was previously ready

        # Empty stdout simulates immediate EOF (subprocess died)
        mock_stdout = StringIO("")

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        mock_process.poll = mock.Mock(return_value=139)  # SIGSEGV
        manager._process = mock_process

        # Don't actually respawn during this test — patch start() to noop
        with mock.patch.object(manager, "start", return_value=True):
            manager._read_stdout()

        # After EOF the reader must have cleared _ready.
        assert manager._ready is False

    def test_subprocess_crash_triggers_respawn(self, mock_gtk_modules):
        """When subprocess exits with non-zero, ``start()`` should be called again."""
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        mock_stdout = StringIO("")  # EOF immediately
        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        mock_process.poll = mock.Mock(return_value=1)  # Non-zero exit
        manager._process = mock_process

        with mock.patch.object(manager, "start", return_value=True) as mock_start:
            manager._read_stdout()

        # Respawn was attempted.
        mock_start.assert_called()

    def test_respawn_circuit_breaks_after_3_failures(self, mock_gtk_modules):
        """Respawn must stop after 3 failed attempts in a short window."""
        import time
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        # Simulate 3 prior rapid respawns (within the 60s window).
        manager._respawn_count = 3
        manager._last_respawn_time = time.monotonic()

        mock_stdout = StringIO("")  # EOF immediately
        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        mock_process.poll = mock.Mock(return_value=1)
        manager._process = mock_process

        with mock.patch.object(manager, "start", return_value=True) as mock_start:
            manager._read_stdout()

        # Circuit breaker engaged: no further respawn attempts.
        mock_start.assert_not_called()
        # State flag set so callers/UI can observe "tray is down".
        assert manager._tray_down is True

    def test_no_respawn_during_shutdown(self, mock_gtk_modules):
        """When ``_shutting_down`` is True, the EOF path must NOT respawn."""
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._shutting_down = True  # Concurrent stop() in progress

        mock_stdout = StringIO("")  # EOF immediately
        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        mock_process.poll = mock.Mock(return_value=0)  # Clean exit during shutdown
        manager._process = mock_process

        with mock.patch.object(manager, "start", return_value=True) as mock_start:
            manager._read_stdout()

        mock_start.assert_not_called()

    def test_respawn_count_resets_after_60_seconds(self, mock_gtk_modules):
        """Respawn count window is 60s — older respawns shouldn't trip the breaker."""
        import time
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True

        # Simulate 3 prior respawns, but more than 60 seconds ago.
        manager._respawn_count = 3
        manager._last_respawn_time = time.monotonic() - 120.0  # 2 minutes ago

        mock_stdout = StringIO("")
        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        mock_process.poll = mock.Mock(return_value=1)
        manager._process = mock_process

        with mock.patch.object(manager, "start", return_value=True) as mock_start:
            manager._read_stdout()

        # Window expired — respawn should be allowed again.
        mock_start.assert_called()

    def test_init_initializes_respawn_state(self, mock_gtk_modules):
        """``__init__`` must initialize the new respawn / shutdown state fields."""
        from src.ui.tray_manager import TrayManager

        manager = TrayManager()

        assert manager._shutting_down is False
        assert manager._respawn_count == 0
        assert manager._last_respawn_time == 0.0
        assert manager._tray_down is False


class TestTrayManagerReaderThreadIntegration:
    """Integration tests for reader thread behavior."""

    def test_reader_processes_multiple_events_in_sequence(self, mock_gtk_modules):
        """Test reader thread processes multiple events correctly."""
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._shutting_down = True  # Suppress UI-001 respawn path on EOF

        # Set up callbacks to track calls
        quick_scan_called = []
        manager._on_quick_scan = lambda: quick_scan_called.append(True)

        # Simulate a sequence of events
        messages = [
            '{"event": "ready"}\n',
            '{"event": "pong"}\n',
            '{"event": "menu_action", "action": "quick_scan"}\n',
        ]
        mock_stdout = StringIO("".join(messages))

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        manager._process = mock_process

        manager._read_stdout()

        assert manager._ready is True
        assert len(quick_scan_called) == 1

    def test_reader_handles_mixed_valid_and_invalid_messages(self, mock_gtk_modules):
        """Test reader handles mix of valid and invalid messages."""
        from io import StringIO

        from src.ui.tray_manager import TrayManager

        manager = TrayManager()
        manager._running = True
        manager._shutting_down = True  # Suppress UI-001 respawn path on EOF

        messages = [
            "invalid json\n",  # Invalid
            '{"no_event": "field"}\n',  # Invalid structure
            '{"event": "ready"}\n',  # Valid
            '{"incomplete": \n',  # Invalid
            '{"event": "pong"}\n',  # Valid
        ]
        mock_stdout = StringIO("".join(messages))

        mock_process = mock.Mock()
        mock_process.stdout = mock_stdout
        manager._process = mock_process

        # Should not crash
        manager._read_stdout()

        # Valid messages should have been processed
        assert manager._ready is True
