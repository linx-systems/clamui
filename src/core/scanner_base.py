# ClamUI Scanner Base Module
"""
Shared utilities for ClamAV scanner implementations.

This module provides common functionality used by both Scanner (clamscan) and
DaemonScanner (clamdscan) to avoid code duplication:
- Process communication with cancellation support
- Streaming output with progress callbacks
- Process termination with graceful shutdown
- Scan log saving
- Error result creation
"""

import logging
import os
import select
import subprocess
from collections.abc import Callable

from .i18n import _
from .log_manager import LogEntry, LogManager
from .scanner_types import ScanResult, ScanStatus

logger = logging.getLogger(__name__)

# Timeout constants (seconds)
TERMINATE_GRACE_TIMEOUT = 5  # Time to wait after SIGTERM before SIGKILL
KILL_WAIT_TIMEOUT = 2  # Time to wait after SIGKILL
STREAM_POLL_TIMEOUT = 0.1  # select() timeout for checking cancellation between output reads

# Hard cap on accumulated subprocess output to prevent memory exhaustion from
# pathological ClamAV output (crafted archives, verbose debug floods, etc.).
# Per stream (stdout and stderr each). Lines beyond the cap are still delivered
# to on_line callbacks but dropped from the accumulated buffer.
MAX_ACCUMULATED_BYTES = 64 * 1024 * 1024

_NONFATAL_SKIP_MARKERS = (
    ": Failed to open file",
    ": File path check failure:",
    ": Not supported file type",
)
_IGNORABLE_WARNING_LINES = ("LibClamAV Warning: cli_realpath: Invalid arguments.",)

# LibClamAV Error patterns from non-fatal file parsing (CL_EPARSE/CL_EFORMAT).
# These are internal errors where ClamAV abandons one corrupt file and continues
# scanning. They should not cause the entire scan to be treated as a hard error.
_NONFATAL_LIBCLAMAV_PATTERNS = (
    "index_local_file_headers_within_bounds",  # ZIP offset validation (ClamAV 1.5.0+)
    "Invalid offset arguments",  # ZIP parser malformed archive offsets
)


def communicate_with_cancel_check(
    process: subprocess.Popen,
    is_cancelled: Callable[[], bool],
) -> tuple[str, str, bool]:
    """
    Communicate with process while checking for cancellation.

    Polling Loop Strategy:
    - Uses process.communicate(timeout=0.5) instead of blocking wait
    - Checks is_cancelled() before each communicate() attempt
    - If timeout expires, loop continues to check cancellation again
    - If cancelled during wait, terminates process and drains remaining output
    - This provides ~500ms cancellation responsiveness (vs minutes for blocking wait)

    Why Not process.wait():
    - process.wait() blocks until completion with no timeout mechanism
    - Long scans would be uninterruptible without SIGTERM from another thread
    - communicate(timeout) gives us both output collection and cancellation points

    Uses a polling loop with timeout to allow periodic cancellation checks.
    This prevents the scan thread from blocking indefinitely on communicate().

    Args:
        process: The subprocess to communicate with.
        is_cancelled: Callable that returns True if operation was cancelled.

    Returns:
        Tuple of (stdout, stderr, was_cancelled).
    """
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    stdout_total = 0
    stderr_total = 0

    def _append(parts: list[str], total: int, chunk: str, stream_name: str) -> int:
        if not chunk:
            return total
        if total >= MAX_ACCUMULATED_BYTES:
            return total
        remaining = MAX_ACCUMULATED_BYTES - total
        if len(chunk) <= remaining:
            parts.append(chunk)
            return total + len(chunk)
        # Truncation point — keep marker so parsers see the boundary.
        parts.append(chunk[:remaining])
        parts.append(f"\n[{stream_name} truncated at {MAX_ACCUMULATED_BYTES} bytes]\n")
        logger.warning(
            "Subprocess %s exceeded %d bytes; truncating accumulated buffer",
            stream_name,
            MAX_ACCUMULATED_BYTES,
        )
        return MAX_ACCUMULATED_BYTES

    while True:
        if is_cancelled():
            # Terminate process and collect any remaining output
            try:
                process.terminate()
                stdout, stderr = process.communicate(timeout=2.0)
                stdout_total = _append(stdout_parts, stdout_total, stdout or "", "stdout")
                stderr_total = _append(stderr_parts, stderr_total, stderr or "", "stderr")
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return "".join(stdout_parts), "".join(stderr_parts), True

        try:
            stdout, stderr = process.communicate(timeout=0.5)
            stdout_total = _append(stdout_parts, stdout_total, stdout or "", "stdout")
            stderr_total = _append(stderr_parts, stderr_total, stderr or "", "stderr")
            return "".join(stdout_parts), "".join(stderr_parts), False
        except subprocess.TimeoutExpired:
            continue  # Loop again, check cancel flag


def stream_process_output(
    process: subprocess.Popen,
    is_cancelled: Callable[[], bool],
    on_line: Callable[[str], None],
    poll_interval: float = STREAM_POLL_TIMEOUT,
) -> tuple[str, str, bool]:
    """
    Stream stdout line-by-line with cancellation support.

    Why select() + os.read() Instead of readline():
    - readline() blocks until it finds a newline character (could be seconds/minutes)
    - select() with timeout allows checking cancellation every poll_interval (0.1s default)
    - os.read() is truly non-blocking after select() returns readable
    - process.stdout.read() uses TextIOWrapper which loops internally, blocking on pipe
    - This combination provides real-time progress AND fast cancellation response

    Why os.read() Over process.stdout.read():
    - process.stdout is a TextIOWrapper (BufferedReader + encoding)
    - TextIOWrapper.read(n) tries to accumulate exactly n characters
    - It internally loops on the underlying pipe, blocking until it has n chars
    - os.read() is a raw syscall that returns immediately with available data
    - This gives us true non-blocking behavior after select() indicates readability

    Uses select/poll for non-blocking reads to maintain cancellation responsiveness.
    Each line from stdout is passed to the on_line callback in real-time.

    Args:
        process: The subprocess to communicate with (must have stdout=PIPE, stderr=PIPE).
        is_cancelled: Callable that returns True if operation was cancelled.
        on_line: Callback function called with each line from stdout.
        poll_interval: Time to wait for output before checking cancellation (seconds).

    Returns:
        Tuple of (stdout, stderr, was_cancelled).
        Note: stdout contains all accumulated output for final parsing.
    """
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    stdout_total = 0
    stderr_total = 0

    if process.stdout is None or process.stderr is None:
        # Fallback to blocking communicate if pipes not available
        logger.warning("stream_process_output called without stdout/stderr pipes")
        return communicate_with_cancel_check(process, is_cancelled)

    def _append(parts: list[str], total: int, chunk: str, stream_name: str) -> int:
        if not chunk:
            return total
        if total >= MAX_ACCUMULATED_BYTES:
            return total
        remaining = MAX_ACCUMULATED_BYTES - total
        if len(chunk) <= remaining:
            parts.append(chunk)
            return total + len(chunk)
        parts.append(chunk[:remaining])
        parts.append(f"\n[{stream_name} truncated at {MAX_ACCUMULATED_BYTES} bytes]\n")
        logger.warning(
            "Subprocess %s exceeded %d bytes; truncating accumulated buffer",
            stream_name,
            MAX_ACCUMULATED_BYTES,
        )
        return MAX_ACCUMULATED_BYTES

    # Get file descriptors for both streams. We must drain stderr concurrently
    # with stdout to avoid a pipe-buffer deadlock: clamscan/clamdscan write
    # LibClamAV warnings and permission errors to stderr, and a single
    # write(stderr_fd) blocks once the kernel pipe buffer (~64 KiB on Linux)
    # fills. While blocked, the process never advances, process.poll() stays
    # None, and the scan freezes mid-run. See issue #146.
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    stdout_eof = False
    stderr_eof = False
    incomplete_line = ""

    try:
        while True:
            # Check for cancellation first
            if is_cancelled():
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                # Drain remaining output via os.read() to avoid mixing
                # with the TextIOWrapper used by process.communicate()
                for fd, parts, stream_name in [
                    (stdout_fd, stdout_parts, "stdout"),
                    (stderr_fd, stderr_parts, "stderr"),
                ]:
                    local_total = stdout_total if stream_name == "stdout" else stderr_total
                    while True:
                        try:
                            raw = os.read(fd, 4096)
                            if not raw:
                                break
                            local_total = _append(
                                parts,
                                local_total,
                                raw.decode("utf-8", errors="replace"),
                                stream_name,
                            )
                        except OSError:
                            break
                    if stream_name == "stdout":
                        stdout_total = local_total
                    else:
                        stderr_total = local_total
                return "".join(stdout_parts), "".join(stderr_parts), True

            # Check if process has finished
            if process.poll() is not None:
                # Process finished - drain remaining output via os.read()
                remaining_chunks = []
                while True:
                    try:
                        raw = os.read(stdout_fd, 4096)
                        if not raw:
                            break
                        remaining_chunks.append(raw.decode("utf-8", errors="replace"))
                    except OSError:
                        break
                remaining_stdout = "".join(remaining_chunks)

                remaining_stderr_chunks = []
                while True:
                    try:
                        raw = os.read(stderr_fd, 4096)
                        if not raw:
                            break
                        remaining_stderr_chunks.append(raw.decode("utf-8", errors="replace"))
                    except OSError:
                        break
                remaining_stderr = "".join(remaining_stderr_chunks)

                if remaining_stdout:
                    # Process remaining data including incomplete line
                    data = incomplete_line + remaining_stdout
                    lines = data.split("\n")
                    for line in lines:
                        if line:  # Skip empty lines from split
                            on_line(line)
                    stdout_total = _append(stdout_parts, stdout_total, data, "stdout")
                elif incomplete_line:
                    # Process the final incomplete line
                    on_line(incomplete_line)
                    stdout_total = _append(stdout_parts, stdout_total, incomplete_line, "stdout")
                if remaining_stderr:
                    stderr_total = _append(stderr_parts, stderr_total, remaining_stderr, "stderr")
                break

            # Build the active read set. Once a stream reaches EOF we drop it
            # so select() doesn't spin on a closed fd.
            read_fds = []
            if not stdout_eof:
                read_fds.append(stdout_fd)
            if not stderr_eof:
                read_fds.append(stderr_fd)

            if not read_fds:
                # Both streams closed but process still hasn't exited.
                # Give it a moment, then escalate to kill so the next poll()
                # iteration takes the drain-and-exit branch above.
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                continue

            # Use select to wait for data with timeout
            readable = select.select(read_fds, [], [], poll_interval)[0]

            for fd in readable:
                # Use os.read() for truly non-blocking reads.
                # process.stdout.read(n) uses TextIOWrapper which internally
                # loops to accumulate n chars, blocking on the pipe even after
                # select() returns readable.
                raw_bytes = os.read(fd, 4096)
                if not raw_bytes:
                    # EOF on this stream. Mark it closed and stop selecting
                    # on it; the other stream may still have data, and the
                    # process.poll() branch will run the final drain.
                    if fd == stdout_fd:
                        stdout_eof = True
                    else:
                        stderr_eof = True
                    continue

                chunk = raw_bytes.decode("utf-8", errors="replace")

                if fd == stdout_fd:
                    # Accumulate for final parsing (capped to avoid memory exhaustion)
                    stdout_total = _append(stdout_parts, stdout_total, chunk, "stdout")

                    # Incomplete line handling: Buffer partial lines until newline arrives
                    # - incomplete_line holds text from previous read that didn't end with \n
                    # - Prepend it to current chunk to reassemble the full line
                    # - lines[-1] becomes the new incomplete_line (empty string if chunk ended with \n)
                    # - This ensures callbacks always receive complete lines
                    data = incomplete_line + chunk
                    lines = data.split("\n")

                    # The last element might be incomplete (no newline yet)
                    incomplete_line = lines[-1]

                    # Process complete lines
                    for line in lines[:-1]:
                        if line:  # Skip empty lines
                            on_line(line)
                else:
                    # stderr: accumulate only (no line callback). Both parsers
                    # in scanner.py and daemon_scanner.py operate on stdout only,
                    # and routing stderr ERROR-suffixed lines into on_line would
                    # corrupt the progress counter.
                    stderr_total = _append(stderr_parts, stderr_total, chunk, "stderr")

    except OSError as e:
        logger.warning("Error streaming process output: %s", e)
        # Try to get any remaining output
        try:
            remaining_stdout, remaining_stderr = process.communicate(timeout=2.0)
            if remaining_stdout:
                stdout_total = _append(stdout_parts, stdout_total, remaining_stdout, "stdout")
            if remaining_stderr:
                stderr_total = _append(stderr_parts, stderr_total, remaining_stderr, "stderr")
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    return "".join(stdout_parts), "".join(stderr_parts), False


def _extract_skipped_path(line: str) -> str | None:
    """Extract a skipped-file path from a known non-fatal ClamAV warning line."""
    for marker in _NONFATAL_SKIP_MARKERS:
        if marker in line:
            file_path = line.split(marker, 1)[0].strip()
            if file_path.startswith("WARNING:"):
                file_path = file_path[len("WARNING:") :].strip()
            if file_path.startswith("ERROR:"):
                file_path = file_path[len("ERROR:") :].strip()
            return file_path or None
    return None


def collect_clamav_warnings(stdout: str, stderr: str) -> tuple[list[str], list[str]]:
    """Collect non-fatal skipped paths and remaining hard-error lines."""
    skipped_files: list[str] = []
    seen_skipped: set[str] = set()
    hard_error_lines: list[str] = []

    for raw_line in [*stdout.splitlines(), *stderr.splitlines()]:
        line = raw_line.strip()
        if not line:
            continue

        skipped_path = _extract_skipped_path(line)
        if skipped_path is not None:
            if skipped_path not in seen_skipped:
                seen_skipped.add(skipped_path)
                skipped_files.append(skipped_path)
            continue

        if any(ignored in line for ignored in _IGNORABLE_WARNING_LINES):
            continue

        # Non-fatal LibClamAV parse errors (e.g. corrupt ZIP archives) —
        # ClamAV skips the file internally and continues scanning.
        if line.startswith("LibClamAV Error:") and any(
            pattern in line for pattern in _NONFATAL_LIBCLAMAV_PATTERNS
        ):
            continue

        if line.startswith(
            ("WARNING:", "ERROR:", "LibClamAV Error:", "LibClamAV Warning:")
        ) or line.endswith("ERROR"):
            hard_error_lines.append(line)

    return skipped_files, hard_error_lines


def cleanup_process(process: subprocess.Popen | None) -> None:
    """
    Ensure a subprocess is properly terminated and cleaned up.

    Args:
        process: The subprocess to clean up, or None.
    """
    if process is None:
        return

    try:
        if process.poll() is None:  # Only kill if still running
            process.kill()
        process.wait(timeout=KILL_WAIT_TIMEOUT)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        logger.debug("Failed to forcefully terminate subprocess during cleanup", exc_info=True)


def terminate_process_gracefully(process: subprocess.Popen | None) -> None:
    """
    Terminate a process with graceful shutdown escalation.

    First sends SIGTERM, then escalates to SIGKILL if the process
    doesn't respond within the grace period.

    Args:
        process: The subprocess to terminate, or None.
    """
    if process is None:
        return

    # Step 1: SIGTERM (graceful)
    try:
        process.terminate()
    except (OSError, ProcessLookupError):
        # Process already gone
        return

    # Step 2: Wait for graceful termination
    try:
        process.wait(timeout=TERMINATE_GRACE_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Step 3: SIGKILL (forceful)
        logger.warning("Process didn't terminate gracefully, killing")
        try:
            process.kill()
            process.wait(timeout=KILL_WAIT_TIMEOUT)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            logger.debug("Failed to kill subprocess after graceful shutdown timeout", exc_info=True)


def save_scan_log(
    log_manager: LogManager,
    result: ScanResult,
    duration: float,
    suffix: str = "",
    scheduled: bool = False,
) -> None:
    """
    Save scan result to log.

    Args:
        log_manager: The LogManager instance to save to.
        result: The scan result.
        duration: Scan duration in seconds.
        suffix: Optional suffix for summary (e.g., "(daemon)").
        scheduled: Whether this was a scheduled scan.
    """
    # Map ScanStatus to string
    status_map = {
        ScanStatus.CLEAN: "clean",
        ScanStatus.INFECTED: "infected",
        ScanStatus.CANCELLED: "cancelled",
        ScanStatus.ERROR: "error",
    }
    scan_status = status_map.get(result.status, "error")

    # Convert threat details to dicts for the factory method
    threat_dicts = [
        {"file_path": t.file_path, "threat_name": t.threat_name} for t in result.threat_details
    ]

    entry = LogEntry.from_scan_result_data(
        scan_status=scan_status,
        path=result.path,
        duration=duration,
        scanned_files=result.scanned_files,
        scanned_dirs=result.scanned_dirs,
        infected_count=result.infected_count,
        threat_details=threat_dicts,
        error_message=result.error_message,
        stdout=result.stdout,
        suffix=suffix,
        scheduled=scheduled,
    )
    log_manager.save_log(entry)


def create_error_result(
    path: str,
    error_message: str,
    stderr: str = "",
) -> ScanResult:
    """
    Create a ScanResult for an error condition.

    Args:
        path: The path that was being scanned.
        error_message: The error message.
        stderr: Optional stderr content.

    Returns:
        A ScanResult with ERROR status.
    """
    return ScanResult(
        status=ScanStatus.ERROR,
        path=path,
        stdout="",
        stderr=stderr or error_message,
        exit_code=-1,
        infected_files=[],
        scanned_files=0,
        scanned_dirs=0,
        infected_count=0,
        error_message=error_message,
        threat_details=[],
    )


def create_cancelled_result(
    path: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = -1,
    scanned_files: int = 0,
    scanned_dirs: int = 0,
    infected_files: list[str] | None = None,
    infected_count: int = 0,
    threat_details: list | None = None,
) -> ScanResult:
    """
    Create a ScanResult for a cancelled operation.

    Args:
        path: The path that was being scanned.
        stdout: Captured stdout.
        stderr: Captured stderr.
        exit_code: The process exit code.
        scanned_files: Number of files scanned before cancellation.
        scanned_dirs: Number of directories scanned before cancellation.
        infected_files: List of infected file paths found before cancellation.
        infected_count: Number of infected files found before cancellation.
        threat_details: List of ThreatDetail objects found before cancellation.

    Returns:
        A ScanResult with CANCELLED status.
    """
    return ScanResult(
        status=ScanStatus.CANCELLED,
        path=path,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        infected_files=infected_files or [],
        scanned_files=scanned_files,
        scanned_dirs=scanned_dirs,
        infected_count=infected_count,
        error_message=_("Scan cancelled by user"),
        threat_details=threat_details or [],
    )
