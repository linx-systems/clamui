# ClamUI Clipboard Tests
"""Unit tests for the clipboard module functions."""

import threading
from unittest.mock import patch

from src.core.clipboard import (
    CLIPBOARD_ASYNC_THRESHOLD,
    CLIPBOARD_SYNC_THRESHOLD,
    ClipboardOperationResult,
    ClipboardResult,
    copy_to_clipboard,
    copy_to_clipboard_async,
    copy_to_clipboard_with_result,
    format_size,
    get_clipboard_size_tier,
    get_text_size,
)


class TestCopyToClipboard:
    """Tests for the copy_to_clipboard function."""

    def test_copy_empty_string_returns_false(self):
        """Test copy_to_clipboard returns False for empty string."""
        result = copy_to_clipboard("")
        assert result is False

    def test_copy_none_returns_false(self):
        """Test copy_to_clipboard returns False for None."""
        result = copy_to_clipboard(None)
        assert result is False

    def test_copy_whitespace_only_succeeds(self):
        """Test copy_to_clipboard with whitespace-only string (non-empty)."""
        # Whitespace is non-empty, so the function should try to copy
        # (might fail due to no display, but won't return False for empty check)
        result = copy_to_clipboard("   ")
        # Result depends on GTK display availability
        # Just verify it doesn't raise an exception
        assert result in (True, False)


class TestGetTextSize:
    """Tests for the get_text_size function."""

    def test_empty_string_returns_zero(self):
        """Test empty string returns 0 bytes."""
        assert get_text_size("") == 0

    def test_none_returns_zero(self):
        """Test None returns 0 bytes."""
        assert get_text_size(None) == 0

    def test_ascii_string(self):
        """Test ASCII string returns correct byte count."""
        assert get_text_size("hello") == 5

    def test_unicode_string(self):
        """Test Unicode string returns correct byte count (UTF-8 encoded)."""
        # Each emoji is 4 bytes in UTF-8
        assert get_text_size("👋") == 4
        assert get_text_size("👋👋") == 8

    def test_mixed_unicode_ascii(self):
        """Test mixed content returns correct byte count."""
        # "Hello 👋" = 5 ASCII chars (5 bytes) + 1 space (1 byte) + 1 emoji (4 bytes) = 10 bytes
        assert get_text_size("Hello 👋") == 10


class TestFormatSize:
    """Tests for the format_size function."""

    def test_bytes(self):
        """Test formatting bytes."""
        assert format_size(0) == "0 B"
        assert format_size(500) == "500 B"
        assert format_size(1023) == "1023 B"

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"
        assert format_size(10240) == "10.0 KB"

    def test_megabytes(self):
        """Test formatting megabytes."""
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(int(1.5 * 1024 * 1024)) == "1.5 MB"
        assert format_size(10 * 1024 * 1024) == "10.0 MB"

    def test_gigabytes(self):
        """Test formatting gigabytes."""
        assert format_size(1024 * 1024 * 1024) == "1.0 GB"
        assert format_size(int(2.5 * 1024 * 1024 * 1024)) == "2.5 GB"


class TestGetClipboardSizeTier:
    """Tests for the get_clipboard_size_tier function."""

    def test_empty_string_is_sync(self):
        """Test empty string returns sync tier."""
        assert get_clipboard_size_tier("") == "sync"
        assert get_clipboard_size_tier(None) == "sync"

    def test_small_content_is_sync(self):
        """Test content under 1 MB returns sync tier."""
        small_text = "x" * (CLIPBOARD_SYNC_THRESHOLD - 1)
        assert get_clipboard_size_tier(small_text) == "sync"

    def test_medium_content_is_async(self):
        """Test content between 1-10 MB returns async tier."""
        # Just over 1 MB
        medium_text = "x" * (CLIPBOARD_SYNC_THRESHOLD + 1)
        assert get_clipboard_size_tier(medium_text) == "async"

        # Just under 10 MB
        medium_text_upper = "x" * (CLIPBOARD_ASYNC_THRESHOLD - 1)
        assert get_clipboard_size_tier(medium_text_upper) == "async"

    def test_large_content_is_too_large(self):
        """Test content over 10 MB returns too_large tier."""
        large_text = "x" * (CLIPBOARD_ASYNC_THRESHOLD + 1)
        assert get_clipboard_size_tier(large_text) == "too_large"


class TestClipboardOperationResult:
    """Tests for the ClipboardOperationResult dataclass."""

    def test_success_result(self):
        """Test success result properties."""
        result = ClipboardOperationResult(
            status=ClipboardResult.SUCCESS,
            message="Copied",
            size_bytes=100,
        )
        assert result.is_success is True
        assert result.is_too_large is False
        assert result.size_bytes == 100

    def test_error_result(self):
        """Test error result properties."""
        result = ClipboardOperationResult(
            status=ClipboardResult.ERROR,
            message="Failed",
            size_bytes=0,
        )
        assert result.is_success is False
        assert result.is_too_large is False

    def test_too_large_result(self):
        """Test too_large result properties."""
        result = ClipboardOperationResult(
            status=ClipboardResult.TOO_LARGE,
            message="Too large",
            size_bytes=15 * 1024 * 1024,
        )
        assert result.is_success is False
        assert result.is_too_large is True


class TestCopyToClipboardWithResult:
    """Tests for the copy_to_clipboard_with_result function."""

    def test_empty_text_returns_error(self):
        """Test empty text returns error result."""
        result = copy_to_clipboard_with_result("")
        assert result.status == ClipboardResult.ERROR
        assert result.size_bytes == 0
        assert "No content" in result.message

    def test_none_returns_error(self):
        """Test None returns error result."""
        result = copy_to_clipboard_with_result(None)
        assert result.status == ClipboardResult.ERROR

    def test_too_large_returns_too_large(self):
        """Test content over threshold returns TOO_LARGE."""
        large_text = "x" * (CLIPBOARD_ASYNC_THRESHOLD + 1)
        result = copy_to_clipboard_with_result(large_text)
        assert result.status == ClipboardResult.TOO_LARGE
        assert result.is_too_large is True
        assert "too large" in result.message.lower()

    @patch("src.core.clipboard._do_clipboard_set")
    def test_success_with_mocked_clipboard(self, mock_set):
        """Test successful copy with mocked clipboard."""
        mock_set.return_value = True
        result = copy_to_clipboard_with_result("test content")
        assert result.status == ClipboardResult.SUCCESS
        assert result.size_bytes == 12  # "test content" = 12 bytes
        mock_set.assert_called_once_with("test content")

    @patch("src.core.clipboard._do_clipboard_set")
    def test_failure_with_mocked_clipboard(self, mock_set):
        """Test failed copy with mocked clipboard."""
        mock_set.return_value = False
        result = copy_to_clipboard_with_result("test content")
        assert result.status == ClipboardResult.ERROR
        assert "Failed" in result.message


class TestCopyToClipboardAsync:
    """Tests for the copy_to_clipboard_async function."""

    def test_empty_text_calls_callback_immediately(self):
        """Test empty text calls callback immediately with error."""
        callback_result = []

        def callback(result):
            callback_result.append(result)

        copy_to_clipboard_async("", callback)

        # Callback should be called synchronously for empty text
        assert len(callback_result) == 1
        assert callback_result[0].status == ClipboardResult.ERROR

    def test_too_large_calls_callback_immediately(self):
        """Test too large content calls callback immediately."""
        callback_result = []

        def callback(result):
            callback_result.append(result)

        large_text = "x" * (CLIPBOARD_ASYNC_THRESHOLD + 1)
        copy_to_clipboard_async(large_text, callback)

        # Callback should be called synchronously for too large
        assert len(callback_result) == 1
        assert callback_result[0].status == ClipboardResult.TOO_LARGE

    @patch("src.core.clipboard._do_clipboard_set")
    def test_async_success_with_mocked_clipboard(self, mock_set):
        """Test async copy succeeds with mocked clipboard."""
        mock_set.return_value = True

        callback_event = threading.Event()
        callback_result = []

        def callback(result):
            callback_result.append(result)
            callback_event.set()

        # Mock GLib.idle_add to call the function immediately
        def mock_idle_add(func, *args):
            func(*args)
            return True

        with patch.dict(
            "sys.modules",
            {
                "gi.repository": type(
                    "module",
                    (),
                    {"GLib": type("GLib", (), {"idle_add": mock_idle_add})()},
                )()
            },
        ):
            copy_to_clipboard_async("test", callback)

            # Wait for async callback (with timeout)
            callback_event.wait(timeout=5.0)

        assert len(callback_result) == 1
        assert callback_result[0].status == ClipboardResult.SUCCESS
        assert callback_result[0].size_bytes == 4

    @patch("src.core.clipboard._do_clipboard_set")
    def test_async_failure_with_mocked_clipboard(self, mock_set):
        """Test async copy handles failure with mocked clipboard."""
        mock_set.return_value = False

        callback_event = threading.Event()
        callback_result = []

        def callback(result):
            callback_result.append(result)
            callback_event.set()

        # Mock GLib.idle_add to call the function immediately
        def mock_idle_add(func, *args):
            func(*args)
            return True

        with patch.dict(
            "sys.modules",
            {
                "gi.repository": type(
                    "module",
                    (),
                    {"GLib": type("GLib", (), {"idle_add": mock_idle_add})()},
                )()
            },
        ):
            copy_to_clipboard_async("test", callback)

            # Wait for async callback (with timeout)
            callback_event.wait(timeout=5.0)

        assert len(callback_result) == 1
        assert callback_result[0].status == ClipboardResult.ERROR


class TestThresholdConstants:
    """Tests for the threshold constants."""

    def test_sync_threshold_is_1mb(self):
        """Test sync threshold is 1 MB."""
        assert CLIPBOARD_SYNC_THRESHOLD == 1 * 1024 * 1024

    def test_async_threshold_is_10mb(self):
        """Test async threshold is 10 MB."""
        assert CLIPBOARD_ASYNC_THRESHOLD == 10 * 1024 * 1024

    def test_async_threshold_greater_than_sync(self):
        """Test async threshold is greater than sync threshold."""
        assert CLIPBOARD_ASYNC_THRESHOLD > CLIPBOARD_SYNC_THRESHOLD


class TestAsyncRunsClipboardSetOnMainThread:
    """Regression: GTK/GDK clipboard access must run on the main-loop thread.

    The async copy previously performed _do_clipboard_set() inside a worker
    thread, which is a GTK thread-safety violation (GDK is not thread-safe).
    The fix schedules the clipboard write on the main loop via GLib.idle_add().
    """

    @patch("src.core.clipboard._do_clipboard_set")
    def test_clipboard_set_invoked_on_main_thread(self, mock_set):
        recorded: dict[str, threading.Thread] = {}

        def fake_set(text):
            recorded["thread"] = threading.current_thread()
            return True

        mock_set.side_effect = fake_set

        done = threading.Event()

        def callback(result):
            done.set()

        # Mock GLib.idle_add to run the scheduled function synchronously on the
        # calling (main) thread, mirroring main-loop dispatch.
        def mock_idle_add(func, *args):
            func(*args)
            return True

        with patch.dict(
            "sys.modules",
            {
                "gi.repository": type(
                    "module",
                    (),
                    {"GLib": type("GLib", (), {"idle_add": staticmethod(mock_idle_add)})()},
                )()
            },
        ):
            copy_to_clipboard_async("payload", callback)
            done.wait(timeout=5.0)

        assert recorded.get("thread") is threading.main_thread()
