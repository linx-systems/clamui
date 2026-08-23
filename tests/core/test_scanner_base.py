# ClamUI Scanner Base Tests
"""Unit tests for the scanner_base module."""

import subprocess
from unittest.mock import MagicMock, patch

from src.core.scanner_base import (
    KILL_WAIT_TIMEOUT,
    STREAM_POLL_TIMEOUT,
    TERMINATE_GRACE_TIMEOUT,
    _extract_skipped_path,
    cleanup_process,
    collect_clamav_warnings,
    communicate_with_cancel_check,
    create_cancelled_result,
    create_error_result,
    parse_total_errors,
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

    def test_stream_output_partial_line_not_duplicated_in_stdout(self):
        """A trailing partial line must appear exactly once in accumulated stdout.

        The streaming loop appends every raw chunk to the stdout buffer as it
        arrives, while separately tracking the trailing partial line for the
        line callback. The exit-drain path used to re-append that partial
        line, corrupting the final output (e.g. 'Scanned files: 1' +
        'Scanned files: 123') and breaking result parsing.
        """
        mock_process = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        # First iteration: process running, chunk ends mid-line.
        # Second iteration: process exited, drain returns the rest.
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_stdout.fileno.return_value = 1
        mock_stderr.fileno.return_value = 2

        lines = []

        with (
            patch("src.core.scanner_base.select.select", return_value=([1], [], [])),
            patch(
                "src.core.scanner_base.os.read",
                side_effect=[
                    b"Infected files: 0\nScanned files: 1",  # streaming read (partial line)
                    b"23\n",  # drain stdout after poll
                    b"",  # stdout EOF
                    b"",  # stderr EOF
                ],
            ),
        ):
            stdout, _stderr, cancelled = stream_process_output(
                mock_process, lambda: False, lines.append
            )

        assert cancelled is False
        assert stdout == "Infected files: 0\nScanned files: 123\n"
        assert lines == ["Infected files: 0", "Scanned files: 123"]

    def test_stream_output_final_incomplete_line_flushed_once(self):
        """A final line without trailing newline reaches the callback once and
        is not duplicated in the accumulated stdout buffer."""
        mock_process = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_stdout.fileno.return_value = 1
        mock_stderr.fileno.return_value = 2

        lines = []

        with (
            patch("src.core.scanner_base.select.select", return_value=([1], [], [])),
            patch(
                "src.core.scanner_base.os.read",
                side_effect=[
                    b"line1\nno newline at end",  # streaming read
                    b"",  # drain stdout after poll (EOF, nothing new)
                    b"",  # stderr EOF
                ],
            ),
        ):
            stdout, _stderr, _cancelled = stream_process_output(
                mock_process, lambda: False, lines.append
            )

        assert stdout == "line1\nno newline at end"
        assert lines == ["line1", "no newline at end"]

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
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []
        assert skipped == []

    def test_nonfatal_invalid_offset_pattern_not_hard_error(self):
        """LibClamAV Error with 'Invalid offset arguments' should not be a hard error."""
        stderr = (
            "LibClamAV Error: Invalid offset arguments: start_offset=0, end_offset=0, fsize=50\n"
        )
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []

    def test_genuine_libclamav_error_still_hard_error(self):
        """Other LibClamAV Error lines should still be classified as hard errors."""
        stderr = "LibClamAV Error: Can't open database directory\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert len(hard_errors) == 1
        assert "Can't open database" in hard_errors[0]

    def test_ignorable_cli_realpath_warning(self):
        """The known-ignorable cli_realpath warning should be silently dropped."""
        stderr = "LibClamAV Warning: cli_realpath: Invalid arguments.\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []

    def test_nonfatal_skip_markers_classified_as_skipped(self):
        """Files that couldn't be opened should go into skipped_files, not hard errors."""
        stdout = "/some/file: Failed to open file ERROR\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings(stdout, "")
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
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert len(hard_errors) == 1
        assert "Can't open file" in hard_errors[0]

    def test_scanxz_size_limit_warning_not_hard_error(self):
        """Decompress-size-limit warnings (large .xz files) must not be hard errors."""
        stderr = (
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes\n"
        )
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []
        assert skipped == []
        assert len(nonfatal) == 1
        assert "exceeds limits" in nonfatal[0]

    def test_tnef_file_truncated_warning_not_hard_error(self):
        """Truncated-container warnings must not be hard errors."""
        stderr = "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []
        assert skipped == []
        assert len(nonfatal) == 1

    def test_recursion_limit_warning_not_hard_error(self):
        """Archive recursion-limit warnings must not be hard errors."""
        stderr = "LibClamAV Warning: cli_magic_scan: Max recursion level reached.\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert hard_errors == []
        assert len(nonfatal) == 1

    def test_size_limit_warnings_mixed_with_real_error(self):
        """A genuine error alongside benign limit warnings must still be reported."""
        stderr = (
            "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN\n"
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes\n"
            "LibClamAV Error: Can't allocate memory\n"
        )
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert len(hard_errors) == 1
        assert "Can't allocate memory" in hard_errors[0]

    def test_cant_access_file_warning_classified_as_skipped(self):
        """clamscan lstat() failure (e.g. file deleted mid-scan) is a skipped file."""
        stderr = "WARNING: /home/user/tmp/ephemeral.dat: Can't access file\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert skipped == ["/home/user/tmp/ephemeral.dat"]
        assert nonfatal == []
        assert hard_errors == []

    def test_cant_open_file_warning_classified_as_skipped(self):
        """clamscan open() failure names the path AFTER the marker."""
        stderr = "WARNING: Can't open file /home/user/locked.bin: Permission denied\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert skipped == ["/home/user/locked.bin"]
        assert nonfatal == []
        assert hard_errors == []

    def test_unrar_dlopen_warning_is_nonfatal(self):
        """Missing optional unrar module is informational, not an error."""
        stderr = (
            "LibClamAV Warning: Cannot dlopen libclamunrar_iface: file not found, "
            "unrar support unavailable\n"
        )
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert skipped == []
        assert len(nonfatal) == 1
        assert "libclamunrar_iface" in nonfatal[0]
        assert hard_errors == []

    def test_bytecode_timeout_warning_is_nonfatal(self):
        """Bytecode signature timeouts are by-design protections, not errors."""
        stderr = "LibClamAV Warning: Bytecode run timed out, timeout flag set\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert skipped == []
        assert len(nonfatal) == 1
        assert hard_errors == []

    def test_per_file_time_limit_reached_classified_as_nonfatal(self):
        """Per-file CL_ETIMEOUT lines are partial scans: nonfatal, not skipped files."""
        stdout = "/home/user/huge.tar: Time limit reached ERROR\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings(stdout, "")
        assert skipped == []
        assert nonfatal == ["/home/user/huge.tar: Time limit reached ERROR"]
        assert hard_errors == []

    def test_marker_first_cant_access_file_extracts_trailing_path(self):
        """clamdscan's 'ERROR: Can't access file <path>' names the path AFTER the marker."""
        assert _extract_skipped_path("ERROR: Can't access file /root/gone.bin") == "/root/gone.bin"

    def test_marker_first_cant_access_file_lines_yield_distinct_paths(self):
        """Two marker-first access errors must produce two distinct skipped paths."""
        stdout = (
            "ERROR: Can't access file /root/gone.bin\nERROR: Can't access file /root/gone2.bin\n"
        )
        skipped, nonfatal, hard_errors = collect_clamav_warnings(stdout, "")
        assert skipped == ["/root/gone.bin", "/root/gone2.bin"]
        assert hard_errors == []

    def test_novel_marker_first_line_does_not_yield_garbage_path(self):
        """Unknown marker-first wordings must stay hard errors, not become path 'ERROR'."""
        stdout = "ERROR: Access denied\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings(stdout, "")
        assert skipped == []
        assert hard_errors == ["ERROR: Access denied"]

    def test_per_file_access_denied_classified_as_skipped(self):
        """Plain 'Access denied' lines from clamscan -v are skipped files."""
        stdout = "/root/secret.txt: Access denied\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings(stdout, "")
        assert skipped == ["/root/secret.txt"]
        assert hard_errors == []

    def test_clamdscan_access_denied_error_line_classified_as_skipped(self):
        """clamdscan's 'Access denied. ERROR' replies are skipped files."""
        stdout = "/root/secret.txt: Access denied. ERROR\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings(stdout, "")
        assert skipped == ["/root/secret.txt"]
        assert hard_errors == []

    def test_unknown_libclamav_warning_stays_hard_error(self):
        """Unrecognized LibClamAV warnings must keep vetoing the benign downgrade."""
        stderr = "LibClamAV Warning: something novel happened\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings("", stderr)
        assert skipped == []
        assert nonfatal == []
        assert hard_errors == ["LibClamAV Warning: something novel happened"]

    def test_unknown_per_file_error_line_stays_hard_error(self):
        """Unknown per-file '... ERROR' replies must stay hard errors."""
        stdout = "/home/user/file.bin: SomeThing ERROR\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings(stdout, "")
        assert skipped == []
        assert hard_errors == ["/home/user/file.bin: SomeThing ERROR"]

    def test_file_list_cant_open_error_stays_hard_error(self):
        """clamdscan's own 'ERROR: ... Can't open file' must not be swallowed."""
        stdout = "ERROR: --file-list: Can't open file /run/user/1000/clamui_filelist.txt\n"
        skipped, nonfatal, hard_errors = collect_clamav_warnings(stdout, "")
        assert skipped == []
        assert len(hard_errors) == 1


class TestParseTotalErrors:
    """Tests for parse_total_errors summary parsing."""

    def test_parses_total_errors_from_summary(self):
        """The 'Total errors: N' summary line yields its numeric count."""
        stdout = (
            "----------- SCAN SUMMARY -----------\n"
            "Scanned files: 340\n"
            "Infected files: 0\n"
            "Total errors: 3\n"
            "Time: 10.000 sec (0 m 10 s)\n"
        )
        assert parse_total_errors(stdout) == 3

    def test_returns_zero_when_summary_line_absent(self):
        """A summary without a 'Total errors' line parses as zero errors."""
        stdout = "----------- SCAN SUMMARY -----------\nScanned files: 5\n"
        assert parse_total_errors(stdout) == 0

    def test_returns_zero_for_empty_output(self):
        """Empty scanner output parses as zero errors."""
        assert parse_total_errors("") == 0
