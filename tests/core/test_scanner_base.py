# ClamUI Scanner Base Tests
"""Unit tests for the scanner_base module."""

import subprocess
from unittest.mock import MagicMock, patch

from src.core.scanner_base import (
    KILL_WAIT_TIMEOUT,
    STREAM_POLL_TIMEOUT,
    TERMINATE_GRACE_TIMEOUT,
    cleanup_process,
    collect_clamav_warnings,
    communicate_with_cancel_check,
    create_cancelled_result,
    create_error_result,
    stream_process_output,
    terminate_process_gracefully,
)
from src.core.scanner_types import ScanStatus


class TestCommunicateWithCancelCheck:
    """Tests for communicate_with_cancel_check function."""

    def test_communicate_without_cancellation(self):
        """Test communication completes normally without cancellation."""
        # Create a mock process
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("stdout output", "stderr output")

        stdout, stderr, cancelled = communicate_with_cancel_check(mock_process, lambda: False)

        assert stdout == "stdout output"
        assert stderr == "stderr output"
        assert cancelled is False

    def test_communicate_with_cancellation(self):
        """Test communication stops when cancelled."""
        mock_process = MagicMock()
        # Simulate the first communicate timing out, then cancel flag set
        mock_process.communicate.side_effect = [
            subprocess.TimeoutExpired("cmd", 0.5),
            ("remaining", ""),
        ]

        cancel_flag = False

        def is_cancelled():
            return cancel_flag

        # Start in a thread, then set cancel flag
        result = []

        def run_communicate():
            nonlocal cancel_flag
            # After first timeout, set cancel flag
            cancel_flag = True
            stdout, stderr, was_cancelled = communicate_with_cancel_check(
                mock_process, is_cancelled
            )
            result.extend([stdout, stderr, was_cancelled])

        run_communicate()

        assert result[2] is True  # was_cancelled
        mock_process.terminate.assert_called()

    def test_communicate_handles_timeout_expired_on_terminate(self):
        """Test handling when terminate doesn't stop process quickly."""
        mock_process = MagicMock()
        mock_process.communicate.side_effect = [
            subprocess.TimeoutExpired("cmd", 2.0),
        ]
        mock_process.wait.return_value = None

        stdout, stderr, cancelled = communicate_with_cancel_check(
            mock_process,
            lambda: True,  # Always cancelled
        )

        assert cancelled is True
        mock_process.terminate.assert_called()
        mock_process.kill.assert_called()


class TestStreamProcessOutput:
    """Tests for stream_process_output function."""

    def test_stream_output_basic(self):
        """Test basic streaming of process output."""
        mock_process = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        # Simulate process finishing immediately
        mock_process.poll.side_effect = [None, 0]  # First check running, second done
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_stdout.fileno.return_value = 1
        mock_stderr.fileno.return_value = 2

        lines_received = []

        def on_line(line):
            lines_received.append(line)

        # os.read returns bytes; first call in select loop, then drain on poll==0
        with (
            patch("src.core.scanner_base.select.select", return_value=([1], [], [])),
            patch(
                "src.core.scanner_base.os.read",
                side_effect=[
                    b"line1\nline2\n",  # streaming read
                    b"",  # drain stdout after poll
                    b"",  # drain stderr after poll
                ],
            ),
        ):
            _stdout, _stderr, cancelled = stream_process_output(
                mock_process, lambda: False, on_line
            )

        assert cancelled is False
        assert "line1" in lines_received
        assert "line2" in lines_received

    def test_stream_output_cancellation(self):
        """Test streaming stops on cancellation."""
        mock_process = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_process.poll.return_value = None  # Process still running
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_stdout.fileno.return_value = 1
        mock_process.communicate.return_value = ("remaining", "")

        lines_received = []
        cancel_flag = True  # Start cancelled

        with patch("src.core.scanner_base.select.select", return_value=([], [], [])):
            _stdout, _stderr, cancelled = stream_process_output(
                mock_process, lambda: cancel_flag, lambda ln: lines_received.append(ln)
            )

        assert cancelled is True
        mock_process.terminate.assert_called()

    def test_stream_output_without_pipes_fallback(self):
        """Test fallback when stdout/stderr pipes not available."""
        mock_process = MagicMock()
        mock_process.stdout = None
        mock_process.stderr = None
        # communicate_with_cancel_check calls process.communicate(timeout=0.5)
        mock_process.communicate.return_value = ("output", "error")

        stdout, stderr, cancelled = stream_process_output(
            mock_process, lambda: False, lambda line: None
        )

        # Should have fallen back to communicate_with_cancel_check,
        # which calls process.communicate()
        mock_process.communicate.assert_called()
        assert stdout == "output"
        assert stderr == "error"
        assert cancelled is False

    def test_stream_output_handles_os_error(self):
        """Test graceful handling of OSError during streaming."""
        mock_process = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_process.poll.return_value = None
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_stdout.fileno.return_value = 1
        mock_process.communicate.return_value = ("final", "")

        with patch(
            "src.core.scanner_base.select.select",
            side_effect=OSError("IO Error"),
        ):
            _stdout, _stderr, cancelled = stream_process_output(
                mock_process, lambda: False, lambda _: None
            )

        # Should recover gracefully
        assert cancelled is False
        assert _stdout == "final"

    def test_stream_output_line_callback_called_for_each_line(self):
        """Test that on_line callback is called for each complete line."""
        mock_process = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_process.poll.side_effect = [None, None, 0]
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_stdout.fileno.return_value = 1
        mock_stderr.fileno.return_value = 2

        lines = []

        def on_line(line):
            lines.append(line)

        # os.read returns bytes; two streaming chunks then drain on poll==0
        with (
            patch("src.core.scanner_base.select.select", return_value=([1], [], [])),
            patch(
                "src.core.scanner_base.os.read",
                side_effect=[
                    b"/path/file1.txt: OK\n/path/file2.txt: OK\n",  # chunk 1
                    b"/path/file3.txt: FOUND\n",  # chunk 2
                    b"",  # drain stdout after poll
                    b"",  # drain stderr after poll
                ],
            ),
        ):
            _stdout, _stderr, _cancelled = stream_process_output(
                mock_process, lambda: False, on_line
            )

        assert "/path/file1.txt: OK" in lines
        assert "/path/file2.txt: OK" in lines
        assert "/path/file3.txt: FOUND" in lines

    def test_stream_output_does_not_deadlock_on_large_stderr(self):
        """Regression test for issue #146: full scan hanging at ~72%.

        When clamscan emits more than the kernel pipe buffer (~64 KiB on Linux)
        to stderr without anyone reading it, its write() blocks and the entire
        scan freezes. stream_process_output() must drain stderr concurrently
        with stdout to prevent this deadlock.
        """
        import sys
        import time as _time

        # Spawn a real subprocess that fills stderr beyond any reasonable pipe
        # buffer (1 MiB >> 64 KiB) and prints one line to stdout at the end.
        # If stderr isn't drained concurrently, the child blocks on write()
        # and this test hangs until pytest times out.
        child = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                (
                    "import sys\n"
                    "sys.stderr.write('x' * (1024 * 1024))\n"
                    "sys.stderr.flush()\n"
                    "sys.stdout.write('done\\n')\n"
                    "sys.stdout.flush()\n"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )

        lines_received: list[str] = []
        start = _time.monotonic()

        try:
            stdout, stderr, cancelled = stream_process_output(
                child,
                lambda: False,
                lambda line: lines_received.append(line),
                poll_interval=0.05,
            )
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            if child.stdout is not None:
                child.stdout.close()
            if child.stderr is not None:
                child.stderr.close()

        elapsed = _time.monotonic() - start

        # Without the fix this hangs forever; with it the child completes
        # almost instantly. Allow generous slack for CI.
        assert elapsed < 10.0, f"stream_process_output hung for {elapsed:.1f}s"
        assert cancelled is False
        assert lines_received == ["done"]
        # stderr should contain the bulk of what the child wrote (subject to
        # MAX_ACCUMULATED_BYTES truncation, which doesn't kick in at 1 MiB).
        assert len(stderr) >= 1024 * 1024
        assert "x" in stderr
        # Process must have exited cleanly, not been killed by the test.
        assert child.returncode == 0

    def test_stream_output_handles_stderr_eof_before_stdout(self):
        """stderr closing first must not prevent stdout from being read.

        Subprocesses can close their streams in any order. The select loop
        must keep selecting on the live fd after one side hits EOF.
        """
        import sys

        child = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                (
                    "import sys, os\n"
                    "os.close(2)\n"  # Close stderr immediately
                    "sys.stdout.write('line1\\nline2\\n')\n"
                    "sys.stdout.flush()\n"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )

        lines_received: list[str] = []
        try:
            _stdout, _stderr, cancelled = stream_process_output(
                child,
                lambda: False,
                lambda line: lines_received.append(line),
                poll_interval=0.05,
            )
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            if child.stdout is not None:
                child.stdout.close()
            if child.stderr is not None:
                child.stderr.close()

        assert cancelled is False
        assert "line1" in lines_received
        assert "line2" in lines_received


class TestCleanupProcess:
    """Tests for cleanup_process function."""

    def test_cleanup_none_process(self):
        """Test cleanup_process handles None gracefully."""
        # Should not raise
        cleanup_process(None)

    def test_cleanup_already_finished_process(self):
        """Test cleanup of already finished process."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Already finished

        cleanup_process(mock_process)

        mock_process.kill.assert_not_called()

    def test_cleanup_running_process(self):
        """Test cleanup kills running process."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Still running
        mock_process.wait.return_value = None

        cleanup_process(mock_process)

        mock_process.kill.assert_called_once()
        mock_process.wait.assert_called_once()

    def test_cleanup_handles_os_error(self):
        """Test cleanup handles OSError gracefully."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.kill.side_effect = OSError("No such process")

        # Should not raise
        cleanup_process(mock_process)

    def test_cleanup_handles_process_lookup_error(self):
        """Test cleanup handles ProcessLookupError gracefully."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.kill.side_effect = ProcessLookupError("No such process")

        # Should not raise
        cleanup_process(mock_process)


class TestTerminateProcessGracefully:
    """Tests for terminate_process_gracefully function."""

    def test_terminate_none_process(self):
        """Test terminate handles None gracefully."""
        # Should not raise
        terminate_process_gracefully(None)

    def test_terminate_graceful_success(self):
        """Test process terminates gracefully with SIGTERM."""
        mock_process = MagicMock()
        mock_process.wait.return_value = None  # Terminates within timeout

        terminate_process_gracefully(mock_process)

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_not_called()

    def test_terminate_escalates_to_kill(self):
        """Test process escalates to SIGKILL when SIGTERM times out."""
        mock_process = MagicMock()
        mock_process.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", TERMINATE_GRACE_TIMEOUT),
            None,
        ]

        terminate_process_gracefully(mock_process)

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()

    def test_terminate_handles_already_gone_on_terminate(self):
        """Test handling when process exits before SIGTERM."""
        mock_process = MagicMock()
        mock_process.terminate.side_effect = ProcessLookupError("No such process")

        # Should not raise
        terminate_process_gracefully(mock_process)

    def test_terminate_handles_os_error_on_kill(self):
        """Test handling OSError during SIGKILL."""
        mock_process = MagicMock()
        mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        mock_process.kill.side_effect = OSError("Error")

        # Should not raise
        terminate_process_gracefully(mock_process)


class TestCreateErrorResult:
    """Tests for create_error_result function."""

    def test_create_error_result_basic(self):
        """Test creating a basic error result."""
        result = create_error_result("/path/to/scan", "ClamAV not found")

        assert result.status == ScanStatus.ERROR
        assert result.path == "/path/to/scan"
        assert result.error_message == "ClamAV not found"
        assert result.exit_code == -1
        assert result.infected_files == []
        assert result.threat_details == []

    def test_create_error_result_with_stderr(self):
        """Test error result includes stderr."""
        result = create_error_result("/path/to/scan", "Command failed", stderr="Permission denied")

        assert result.stderr == "Permission denied"

    def test_create_error_result_stderr_defaults_to_error_message(self):
        """Test stderr defaults to error message when not provided."""
        result = create_error_result("/path/to/scan", "Some error")

        assert result.stderr == "Some error"


class TestCreateCancelledResult:
    """Tests for create_cancelled_result function."""

    def test_create_cancelled_result_basic(self):
        """Test creating a basic cancelled result."""
        result = create_cancelled_result("/path/to/scan")

        assert result.status == ScanStatus.CANCELLED
        assert result.path == "/path/to/scan"
        assert result.error_message == "Scan cancelled by user"
        assert result.infected_files == []
        assert result.infected_count == 0
        assert result.threat_details == []

    def test_create_cancelled_result_with_partial_progress(self):
        """Test cancelled result preserves partial scan progress."""
        result = create_cancelled_result(
            "/path/to/scan",
            stdout="Partial output",
            stderr="",
            exit_code=-15,
            scanned_files=50,
            scanned_dirs=10,
            infected_files=["/path/to/infected1", "/path/to/infected2"],
            infected_count=2,
        )

        assert result.stdout == "Partial output"
        assert result.exit_code == -15
        assert result.scanned_files == 50
        assert result.scanned_dirs == 10
        assert result.infected_files == ["/path/to/infected1", "/path/to/infected2"]
        assert result.infected_count == 2

    def test_create_cancelled_result_with_threat_details(self):
        """Test cancelled result preserves threat details found before cancellation."""
        mock_threat = MagicMock()
        result = create_cancelled_result(
            "/path/to/scan",
            infected_files=["/path/to/malware"],
            infected_count=1,
            threat_details=[mock_threat],
        )

        assert result.infected_files == ["/path/to/malware"]
        assert result.infected_count == 1
        assert result.threat_details == [mock_threat]


class TestConstants:
    """Tests for module constants."""

    def test_timeout_constants_are_reasonable(self):
        """Test timeout constants have reasonable values."""
        assert TERMINATE_GRACE_TIMEOUT > 0
        assert TERMINATE_GRACE_TIMEOUT <= 10  # Not too long

        assert KILL_WAIT_TIMEOUT > 0
        assert KILL_WAIT_TIMEOUT <= 5  # Not too long

        assert STREAM_POLL_TIMEOUT > 0
        assert STREAM_POLL_TIMEOUT <= 1  # Should be responsive


class TestCollectClamavWarnings:
    """Tests for collect_clamav_warnings classification of ClamAV output."""

    def test_nonfatal_libclamav_zip_offset_error_not_hard_error(self):
        """LibClamAV Error about ZIP offset validation should not be a hard error."""
        stderr = (
            "LibClamAV Error: index_local_file_headers_within_bounds: "
            "Invalid offset arguments: start_offset=123, end_offset=456, fsize=100\n"
        )
        skipped, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []
        assert skipped == []

    def test_nonfatal_invalid_offset_pattern_not_hard_error(self):
        """LibClamAV Error with 'Invalid offset arguments' should not be a hard error."""
        stderr = (
            "LibClamAV Error: Invalid offset arguments: start_offset=0, end_offset=0, fsize=50\n"
        )
        skipped, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []

    def test_genuine_libclamav_error_still_hard_error(self):
        """Other LibClamAV Error lines should still be classified as hard errors."""
        stderr = "LibClamAV Error: Can't open database directory\n"
        skipped, hard_errors = collect_clamav_warnings("", stderr)
        assert len(hard_errors) == 1
        assert "Can't open database" in hard_errors[0]

    def test_ignorable_cli_realpath_warning(self):
        """The known-ignorable cli_realpath warning should be silently dropped."""
        stderr = "LibClamAV Warning: cli_realpath: Invalid arguments.\n"
        skipped, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []

    def test_nonfatal_skip_markers_classified_as_skipped(self):
        """Files that couldn't be opened should go into skipped_files, not hard errors."""
        stdout = "/some/file: Failed to open file ERROR\n"
        skipped, hard_errors = collect_clamav_warnings(stdout, "")
        assert len(skipped) == 1
        assert "/some/file" in skipped[0]
        assert hard_errors == []

    def test_mixed_nonfatal_and_hard_errors(self):
        """Non-fatal ZIP parse errors should be filtered while real errors remain."""
        stderr = (
            "LibClamAV Error: index_local_file_headers_within_bounds: "
            "Invalid offset arguments: start_offset=0, end_offset=0, fsize=50\n"
            "ERROR: Can't open file or directory\n"
        )
        skipped, hard_errors = collect_clamav_warnings("", stderr)
        assert len(hard_errors) == 1
        assert "Can't open file" in hard_errors[0]
