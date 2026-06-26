# ClamUI Daemon Scanner Module
"""
Daemon scanner module for ClamUI using clamdscan for clamd communication.
Provides faster scanning by leveraging the ClamAV daemon's in-memory database.
"""

import contextlib
import fnmatch
import logging
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from gi.repository import GLib

from .flatpak import is_flatpak, wrap_host_command
from .log_manager import LogManager
from .sanitize import sanitize_surrogate_path
from .scanner_base import (
    cleanup_process,
    collect_clamav_warnings,
    communicate_with_cancel_check,
    create_cancelled_result,
    create_error_result,
    save_scan_log,
    stream_process_output,
    terminate_process_gracefully,
)
from .scanner_types import ScanProgress, ScanResult, ScanStatus, ThreatDetail
from .settings_manager import SettingsManager
from .threat_classifier import (
    categorize_threat,
    classify_threat_severity_str,
)
from .utils import (
    check_clamd_connection,
    check_clamdscan_installed,
    get_clean_env,
    resolve_clamd_conf_path,
    validate_path,
)

logger = logging.getLogger(__name__)


class DaemonScanner:
    """
    ClamAV daemon scanner using clamdscan.

    Provides faster scanning by communicating with the clamd daemon,
    which keeps the virus database loaded in memory.
    """

    def __init__(
        self,
        log_manager: LogManager | None = None,
        settings_manager: SettingsManager | None = None,
    ):
        """
        Initialize the daemon scanner.

        Args:
            log_manager: Optional LogManager instance for saving scan logs.
            settings_manager: Optional SettingsManager instance for reading
                              exclusion patterns and daemon settings.
        """
        self._current_process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._log_manager = log_manager if log_manager else LogManager()
        self._settings_manager = settings_manager

    def _get_clamd_config_path(self) -> str | None:
        """Resolve the configured clamd.conf path when settings are available."""
        if self._settings_manager is None:
            return None

        try:
            saved_path = self._settings_manager.get("clamd_conf_path", "")
        except Exception:
            logger.debug("Failed to read clamd_conf_path from settings", exc_info=True)
            return None

        if not isinstance(saved_path, str):
            return None
        if saved_path and not os.path.isabs(saved_path):
            return None

        try:
            return resolve_clamd_conf_path(self._settings_manager)
        except Exception:
            logger.debug("Failed to resolve clamd config path", exc_info=True)
            return None

    def check_available(self) -> tuple[bool, str | None]:
        """
        Check if daemon scanning is available.

        Verifies both clamdscan is installed and clamd is responding.

        Returns:
            Tuple of (is_available, version_or_error)
        """
        # Check clamdscan is installed
        is_installed, error = check_clamdscan_installed()
        if not is_installed:
            return (False, error)

        # Check clamd is running and responding
        is_connected, message = check_clamd_connection(config_path=self._get_clamd_config_path())
        if not is_connected:
            return (False, f"clamd not accessible: {message}")

        return (True, "clamd is available")

    def scan_sync(
        self,
        path: str,
        recursive: bool = True,
        profile_exclusions: dict | None = None,
        count_targets: bool = True,
        progress_callback: Callable[[ScanProgress], None] | None = None,
        force_stream: bool = False,
    ) -> ScanResult:
        """
        Execute a synchronous scan using clamdscan.

        WARNING: This will block the calling thread. For UI applications,
        use scan_async() instead.

        Args:
            path: Path to file or directory to scan
            recursive: Ignored - clamdscan always scans directories recursively
            profile_exclusions: Optional exclusions from a scan profile.
            count_targets: Whether to pre-count files/directories before scanning.
                If False, scanned_files and scanned_dirs will be 0 in the result,
                but scanning will be faster for large directories by avoiding
                a separate tree walk. Default is True for backwards compatibility.
            progress_callback: Optional callback for real-time progress updates.
                              If provided, verbose mode is used and callback receives
                              ScanProgress updates as files are scanned.
            force_stream: Force clamdscan to use the INSTREAM protocol for this
                          scan instead of the faster fdpass/multiscan path.

        Returns:
            ScanResult with scan details
        """
        start_time = time.monotonic()

        # Reset cancel event at the start of every scan
        # This ensures a previous cancelled scan doesn't affect new scans
        self._cancel_event.clear()

        # Validate the path first
        is_valid, error = validate_path(path)
        if not is_valid:
            result = create_error_result(path, error or "Invalid path")
            self._save_scan_log(result, time.monotonic() - start_time)
            return result

        # Check daemon is available
        is_available, error_msg = self.check_available()
        if not is_available:
            result = create_error_result(path, error_msg or "Daemon not available")
            self._save_scan_log(result, time.monotonic() - start_time)
            return result

        # Count files/directories before scanning (clamdscan doesn't report these).
        # Also collect file paths whenever live progress is enabled or exclusions
        # are active, because clamdscan only respects exclusions when ClamUI feeds
        # an explicit file list instead of a directory root.
        use_file_list = progress_callback is not None or self._has_active_exclusions(
            profile_exclusions
        )
        should_count = count_targets or use_file_list
        file_list_path: str | None = None
        file_paths: list[str] | None = None

        if should_count:
            file_count, dir_count, file_paths = self._count_scan_targets(
                path, profile_exclusions, collect_paths=use_file_list
            )
        else:
            file_count, dir_count = 0, 0

        # Check if cancelled during counting phase
        if self._cancel_event.is_set():
            result = create_cancelled_result(path)
            self._save_scan_log(result, time.monotonic() - start_time)
            return result

        try:
            if use_file_list and not file_paths:
                result = ScanResult(
                    status=ScanStatus.CLEAN,
                    path=path,
                    stdout="",
                    stderr="",
                    exit_code=0,
                    infected_files=[],
                    scanned_files=file_count,
                    scanned_dirs=dir_count,
                    infected_count=0,
                    error_message=None,
                    threat_details=[],
                )
                self._save_scan_log(result, time.monotonic() - start_time)
                return result

            # Write file list to temp file for progress mode
            # clamdscan only emits per-file output with --file-list, not when
            # scanning a directory (which produces a single summary line)
            if use_file_list and file_paths:
                fd, file_list_path = tempfile.mkstemp(
                    prefix="clamui_filelist_",
                    suffix=".txt",
                    dir=self._get_file_list_temp_dir(),
                )
                os.fchmod(fd, 0o600)
                try:
                    f = os.fdopen(fd, "w")
                except Exception:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                    raise

                with f:
                    f.write("\n".join(sanitize_surrogate_path(p) for p in file_paths))

            # Build clamdscan command (use verbose mode if progress callback provided)
            cmd = self._build_command(
                path,
                recursive,
                profile_exclusions,
                verbose=progress_callback is not None,
                file_list_path=file_list_path,
                force_stream=force_stream,
            )

            with self._process_lock:
                self._current_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding="utf-8",
                    errors="replace",
                    env=get_clean_env(),
                )

            progress_files_scanned = 0
            progress_infected_count = 0
            progress_infected_files: list[str] = []

            try:
                if progress_callback is not None:
                    # Use streaming mode for real-time progress
                    (
                        stdout,
                        stderr,
                        was_cancelled,
                        progress_files_scanned,
                        progress_infected_count,
                        progress_infected_files,
                    ) = self._scan_with_progress(
                        self._current_process, progress_callback, file_count
                    )
                else:
                    # Use standard blocking communication
                    stdout, stderr, was_cancelled = communicate_with_cancel_check(
                        self._current_process, self._cancel_event.is_set
                    )
                exit_code = self._current_process.returncode
            finally:
                # Ensure process is cleaned up even if communicate() raises
                # Acquire lock to safely clear process reference and get it for cleanup
                with self._process_lock:
                    process = self._current_process
                    self._current_process = None
                # Perform cleanup outside lock to avoid holding it during I/O
                cleanup_process(process)

            # Check if cancelled during execution
            if was_cancelled:
                # Use progress counters if available, fall back to pre-counted values
                scanned = progress_files_scanned if progress_files_scanned > 0 else file_count
                result = create_cancelled_result(
                    path,
                    stdout,
                    stderr,
                    exit_code if exit_code is not None else -1,
                    scanned_files=scanned,
                    scanned_dirs=dir_count,
                    infected_files=progress_infected_files,
                    infected_count=progress_infected_count,
                )
                self._save_scan_log(result, time.monotonic() - start_time)
                return result

            # Parse the results
            result = self._parse_results(path, stdout, stderr, exit_code, file_count, dir_count)

            # Apply exclusion filtering (clamdscan doesn't support --exclude)
            result = self._filter_excluded_threats(result, profile_exclusions)

            self._save_scan_log(result, time.monotonic() - start_time)
            return result

        except FileNotFoundError:
            result = create_error_result(path, "clamdscan executable not found")
            self._save_scan_log(result, time.monotonic() - start_time)
            return result
        except PermissionError as e:
            result = create_error_result(path, f"Permission denied: {e}", str(e))
            self._save_scan_log(result, time.monotonic() - start_time)
            return result
        except Exception as e:
            result = create_error_result(path, f"Scan failed: {e}", str(e))
            self._save_scan_log(result, time.monotonic() - start_time)
            return result
        finally:
            # Clean up temp file list
            if file_list_path is not None:
                try:
                    os.unlink(file_list_path)
                except OSError:
                    logger.debug(
                        "Failed to remove temporary clamd file list %s",
                        file_list_path,
                        exc_info=True,
                    )

    def scan_async(
        self,
        path: str,
        callback: Callable[[ScanResult], None],
        recursive: bool = True,
        profile_exclusions: dict | None = None,
        count_targets: bool = True,
        progress_callback: Callable[[ScanProgress], None] | None = None,
    ) -> None:
        """
        Execute an asynchronous scan using clamdscan.

        The scan runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        Args:
            path: Path to file or directory to scan
            callback: Function to call with ScanResult when scan completes
            recursive: Whether to scan directories recursively
            profile_exclusions: Optional exclusions from a scan profile.
            count_targets: Whether to pre-count files/directories before scanning.
                If False, scanned_files and scanned_dirs will be 0 in the result,
                but scanning will be faster for large directories by avoiding
                a separate tree walk. Default is True for backwards compatibility.
            progress_callback: Optional callback for real-time progress updates.
                              If provided, callback receives ScanProgress updates
                              as files are scanned.
        """

        def scan_thread():
            result = self.scan_sync(
                path, recursive, profile_exclusions, count_targets, progress_callback
            )
            GLib.idle_add(callback, result)

        thread = threading.Thread(target=scan_thread)
        thread.daemon = True
        thread.start()

    def cancel(self) -> None:
        """
        Cancel the current scan operation with graceful shutdown escalation.

        If a scan is in progress, it will be terminated with SIGTERM first,
        then escalated to SIGKILL if the process doesn't respond within
        the grace period.
        """
        self._cancel_event.set()
        # Acquire lock to safely get process reference
        with self._process_lock:
            process = self._current_process
        # Terminate outside lock to avoid holding it during I/O
        terminate_process_gracefully(process)

    def _build_command(
        self,
        path: str,
        recursive: bool,
        profile_exclusions: dict | None = None,
        verbose: bool = False,
        file_list_path: str | None = None,
        force_stream: bool = False,
    ) -> list[str]:
        """
        Build the clamdscan command arguments.

        Uses --multiscan for parallel scanning and --fdpass for file
        descriptor passing during regular daemon scans. In verbose mode,
        prepends stdbuf -oL and uses --file-list so clamdscan emits
        per-file results on stdout (scanning a directory only produces
        one summary line). File-list scans still use --fdpass by default,
        because bare "-v --file-list" may fall back to daemon-side path
        checks that fail with permission errors. When force_stream is set,
        uses clamdscan's --stream mode for this scan instead of fdpass.

        Args:
            path: Path to scan (used as target when file_list_path is None)
            recursive: Whether to scan recursively (clamdscan is always recursive)
            profile_exclusions: Optional exclusions from a scan profile.
            verbose: Whether to enable verbose mode for progress tracking.
                    When True, clamdscan outputs each file as it's scanned.
            file_list_path: Path to temp file containing one file path per line.
                    Used in verbose mode for per-file progress output.
            force_stream: Whether to force client-side streaming for this scan.

        Returns:
            List of command arguments (wrapped with flatpak-spawn if in Flatpak)
        """
        # Use binary name only so Flatpak wraps it for host execution through
        # flatpak-spawn instead of resolving a sandbox path.
        #
        # In verbose mode, prepend stdbuf -oL to force line-buffered stdout.
        # Without this, clamdscan's C runtime uses full buffering (~4KB blocks)
        # when stdout is a pipe, causing all output to arrive in a single burst
        # at process exit instead of line-by-line during the scan.
        if verbose:
            cmd = ["stdbuf", "-oL", "clamdscan"]
        else:
            cmd = ["clamdscan"]

        config_path = self._get_clamd_config_path()
        if config_path:
            cmd.extend(["--config-file", config_path])

        # For file-list scans, keep --fdpass enabled so clamdscan uses passed
        # descriptors instead of daemon-side path checks. This preserves the
        # per-file verbose output needed for progress updates while avoiding
        # permission-denied results on otherwise readable files.
        if force_stream:
            cmd.append("--stream")
        elif file_list_path is not None:
            cmd.append("--fdpass")
        elif not verbose:
            cmd.append("--multiscan")
            cmd.append("--fdpass")

        if verbose:
            cmd.append("-v")
        else:
            # Show infected files only
            cmd.append("-i")

        # NOTE: clamdscan does NOT support --exclude or --exclude-dir options
        # (it silently ignores them with a warning). Exclusion filtering is
        # performed post-scan in _filter_excluded_threats() instead.

        # In verbose mode with file list, use --file-list for per-file output.
        # clamdscan only emits per-file ": OK"/": FOUND" lines when given
        # individual files (via --file-list), not when scanning a directory.
        if file_list_path is not None:
            cmd.extend(["--file-list", file_list_path])
        else:
            # Use "--" so a path starting with "-" isn't reinterpreted as a flag.
            cmd.append("--")
            cmd.append(path)

        return wrap_host_command(cmd, force_host=True)

    def _get_file_list_temp_dir(self) -> str | None:
        """
        Return a temp directory that the clamdscan process can read.

        In Flatpak, clamdscan runs on the host through flatpak-spawn. Files
        created in the sandbox runtime directory (for example /run/user/$UID)
        are not necessarily visible to that host process, so daemon file lists
        must live in a host-visible app cache directory.
        """
        if is_flatpak():
            cache_dir = Path.home() / ".cache" / "clamui"
            cache_dir.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(cache_dir, 0o700)
            return str(cache_dir)

        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir and os.path.isdir(runtime_dir):
            return runtime_dir
        return None

    def _scan_with_progress(
        self,
        process: subprocess.Popen,
        progress_callback: Callable[[ScanProgress], None],
        files_total: int | None,
    ) -> tuple[str, str, bool, int, int, list[str]]:
        """
        Scan with real-time progress updates.

        Streams clamdscan verbose output and parses it to track progress,
        calling the progress_callback for each file scanned.

        Return Tuple Structure:
        [0] stdout (str): Complete accumulated output for final parsing
        [1] stderr (str): Complete error output
        [2] was_cancelled (bool): True if scan was cancelled by user
        [3] files_scanned (int): Number of files processed before completion/cancellation
        [4] infected_count (int): Number of infected files detected
        [5] infected_files (list[str]): Paths of infected files found

        Args:
            process: The subprocess running clamdscan with -v flag
            progress_callback: Callback to receive ScanProgress updates
            files_total: Total number of files to scan (for percentage)

        Returns:
            Tuple of (stdout, stderr, was_cancelled, files_scanned,
            infected_count, infected_files)
        """
        files_scanned = 0
        infected_count = 0
        infected_files: list[str] = []
        infected_threats: dict[str, str] = {}
        current_file = ""
        processed_paths: set[str] = set()

        def on_line(line: str) -> None:
            nonlocal files_scanned, infected_count, infected_files
            nonlocal infected_threats, current_file, processed_paths

            # Parse verbose clamdscan output
            # Format for scanning: "/path/to/file: OK" or "/path/to/file: ThreatName FOUND"
            line = line.strip()

            if ": OK" in line:
                # Clean file - extract path
                current_file = line.rsplit(": OK", 1)[0].strip()
                if current_file in processed_paths:
                    return
                processed_paths.add(current_file)
                files_scanned += 1

                # Create and send progress update
                progress = ScanProgress(
                    current_file=current_file,
                    files_scanned=files_scanned,
                    files_total=files_total,
                    infected_count=infected_count,
                    infected_files=list(infected_files),
                    infected_threats=dict(infected_threats),
                )
                progress_callback(progress)

            elif line.endswith("FOUND"):
                # Infected file detected
                # Format: "/path/to/file: ThreatName FOUND"
                parts = line.rsplit(":", 1)
                if len(parts) == 2:
                    file_path = parts[0].strip()
                    threat_name = parts[1].strip()
                    # Remove trailing " FOUND" from threat name
                    if threat_name.endswith(" FOUND"):
                        threat_name = threat_name[:-6].strip()
                    is_new_file = file_path not in processed_paths
                    if is_new_file:
                        processed_paths.add(file_path)
                        files_scanned += 1
                    is_new_infection = file_path not in infected_threats
                    previous_threat = infected_threats.get(file_path)
                    if is_new_infection:
                        infected_count += 1
                        infected_files.append(file_path)
                    infected_threats[file_path] = threat_name
                    if not is_new_file and not is_new_infection and previous_threat == threat_name:
                        return

                    # Send updated progress with new infection
                    progress = ScanProgress(
                        current_file=file_path,
                        files_scanned=files_scanned,
                        files_total=files_total,
                        infected_count=infected_count,
                        infected_files=list(infected_files),
                        infected_threats=dict(infected_threats),
                    )
                    progress_callback(progress)

            elif line.endswith("ERROR"):
                # Access/path failures still represent processed file-list entries.
                skip_markers = (
                    ": Failed to open file",
                    ": File path check failure:",
                )
                for marker in skip_markers:
                    if marker in line:
                        file_path = line.split(marker, 1)[0].strip()
                        if not file_path or file_path in processed_paths:
                            return
                        processed_paths.add(file_path)
                        current_file = file_path
                        files_scanned += 1

                        progress = ScanProgress(
                            current_file=file_path,
                            files_scanned=files_scanned,
                            files_total=files_total,
                            infected_count=infected_count,
                            infected_files=list(infected_files),
                            infected_threats=dict(infected_threats),
                        )
                        progress_callback(progress)
                        break

        stdout, stderr, was_cancelled = stream_process_output(
            process, self._cancel_event.is_set, on_line
        )
        return stdout, stderr, was_cancelled, files_scanned, infected_count, infected_files

    def _count_scan_targets(
        self,
        path: str,
        profile_exclusions: dict | None = None,
        collect_paths: bool = False,
    ) -> tuple[int, int, list[str] | None]:
        """
        Count files and directories that will be scanned.

        Since clamdscan doesn't report file/directory counts in its output,
        we count them ourselves before scanning.

        When collect_paths=True, also collects all file paths during the walk.
        This is used for --file-list mode which gives per-file progress output
        from clamdscan (scanning a directory only produces one result line).

        Performance Note for Large Directories:
        - Uses os.scandir() (via os.walk) which is 2-3x faster than os.listdir()
        - Depth-first traversal with cancellation checks at each directory level
        - Modifies dirs[:] in-place to skip excluded directories (avoids unnecessary descent)
        - For ~100K files: typically takes 1-2 seconds
        - This is a trade-off: accurate progress bars vs slightly longer total scan time

        Args:
            path: Path to scan
            profile_exclusions: Optional exclusions from a scan profile.
            collect_paths: If True, collect and return all file paths.

        Returns:
            Tuple of (file_count, dir_count, file_paths).
            file_paths is None when collect_paths=False.
        """
        scan_path = Path(path)

        # Single file scan
        if scan_path.is_file():
            paths = [str(scan_path)] if collect_paths else None
            return (1, 0, paths)

        # Not a valid path
        if not scan_path.is_dir():
            return (0, 0, None)

        # Collect exclusion patterns
        exclude_patterns: list[str] = []
        exclude_dirs: list[str] = []

        # Global exclusions from settings
        if self._settings_manager is not None:
            exclusions = self._settings_manager.get("exclusion_patterns", [])
            for exclusion in exclusions:
                if not exclusion.get("enabled", True):
                    continue
                pattern = exclusion.get("pattern", "")
                if not pattern:
                    continue
                exclusion_type = exclusion.get("type", "pattern")
                if exclusion_type == "directory":
                    exclude_dirs.append(pattern)
                else:
                    exclude_patterns.append(pattern)

        # Profile exclusions
        if profile_exclusions:
            for excl_path in profile_exclusions.get("paths", []):
                if excl_path:
                    # Expand ~ in paths
                    if excl_path.startswith("~"):
                        excl_path = str(Path(excl_path).expanduser())
                    exclude_dirs.append(excl_path)

            for pattern in profile_exclusions.get("patterns", []):
                if pattern:
                    exclude_patterns.append(pattern)

        file_count = 0
        dir_count = 0
        file_paths: list[str] = []

        try:
            for root, dirs, files in os.walk(path):
                # Check for cancellation during counting
                if self._cancel_event.is_set():
                    logger.info("File counting cancelled by user")
                    return (0, 0, None)

                # Filter out excluded directories (modifies dirs in-place)
                dirs[:] = [
                    d
                    for d in dirs
                    if not self._is_excluded(os.path.join(root, d), d, exclude_dirs, is_dir=True)
                ]

                # Count directories (excluding the root)
                dir_count += len(dirs)

                # Count files that aren't excluded
                for f in files:
                    fp = os.path.join(root, f)
                    if not self._is_excluded(fp, f, exclude_patterns, is_dir=False):
                        file_count += 1
                        if collect_paths:
                            file_paths.append(fp)
        except (PermissionError, OSError):
            # If we can't access the directory, return 0 counts
            logger.debug("Failed to count files in scan target %s", path, exc_info=True)

        # Count the root directory itself
        if dir_count > 0 or file_count > 0:
            dir_count += 1

        return (file_count, dir_count, file_paths if collect_paths else None)

    def _has_active_exclusions(self, profile_exclusions: dict | None = None) -> bool:
        """Return True when any enabled exclusion requires file-list filtering."""
        if self._settings_manager is not None:
            exclusions = self._settings_manager.get("exclusion_patterns", [])
            for exclusion in exclusions:
                if exclusion.get("enabled", True) and exclusion.get("pattern", ""):
                    return True

        if profile_exclusions:
            if any(path for path in profile_exclusions.get("paths", [])):
                return True
            if any(pattern for pattern in profile_exclusions.get("patterns", [])):
                return True

        return False

    def _is_excluded(self, full_path: str, name: str, patterns: list[str], is_dir: bool) -> bool:
        """
        Check if a path matches any exclusion pattern.

        Args:
            full_path: Full path to check
            name: Base name of the file/directory
            patterns: List of exclusion patterns (glob or path)
            is_dir: Whether this is a directory

        Returns:
            True if the path should be excluded
        """
        for pattern in patterns:
            # Check if pattern is an absolute path
            if pattern.startswith("/") or pattern.startswith("~"):
                expanded = str(Path(pattern).expanduser()) if pattern.startswith("~") else pattern
                norm = expanded.rstrip("/")
                if full_path == norm or full_path.startswith(norm + os.sep):
                    return True
            # Check glob pattern against filename
            elif fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(full_path, pattern):
                return True
        return False

    def _parse_results(
        self,
        path: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        file_count: int = 0,
        dir_count: int = 0,
    ) -> ScanResult:
        """
        Parse clamdscan output into a ScanResult.

        clamdscan output format is similar to clamscan but doesn't include
        file/directory counts in the summary. These are provided separately
        via the file_count and dir_count parameters.

        Exit codes: 0=clean, 1=infected, 2=error

        Args:
            path: The scanned path
            stdout: Standard output from clamdscan
            stderr: Standard error from clamdscan
            exit_code: Process exit code
            file_count: Pre-counted number of files scanned
            dir_count: Pre-counted number of directories scanned

        Returns:
            Parsed ScanResult
        """
        infected_files = []
        threat_details = []
        skipped_files, nonfatal_warnings, hard_error_lines = collect_clamav_warnings(stdout, stderr)
        scanned_files = file_count
        scanned_dirs = dir_count
        infected_count = 0

        # Regex pattern: "/path/to/file: ThreatName FOUND"
        # Uses rsplit(":") to handle colons in Windows paths (C:\)
        # Also extracts threat name by removing " FOUND" suffix
        for line in stdout.splitlines():
            line = line.strip()

            if line.endswith("FOUND"):
                parts = line.rsplit(":", 1)
                if len(parts) == 2:
                    file_path = parts[0].strip()
                    threat_part = parts[1].strip()
                    threat_name = (
                        threat_part.rsplit(" ", 1)[0].strip()
                        if " FOUND" in threat_part
                        else threat_part
                    )

                    infected_files.append(file_path)

                    threat_detail = ThreatDetail(
                        file_path=file_path,
                        threat_name=threat_name,
                        category=categorize_threat(threat_name),
                        severity=classify_threat_severity_str(threat_name),
                    )
                    threat_details.append(threat_detail)
                    infected_count += 1

        # Determine overall status based on exit code
        warning_message = None
        if infected_count > 0:
            # Detections are authoritative: clamdscan returns exit code 2 when it
            # both finds a virus and hits an error (e.g. an unreadable file), so
            # never let an error code mask a real threat.
            status = ScanStatus.INFECTED
            if exit_code == 2 and skipped_files:
                warning_message = f"{len(skipped_files)} file(s) could not be accessed"
        elif exit_code == 0:
            status = ScanStatus.ERROR if hard_error_lines else ScanStatus.CLEAN
        elif exit_code == 1:
            status = ScanStatus.INFECTED
        elif exit_code == 2:
            # Exit code 2 = warnings/errors. clamscan/clamdscan report 2 even for
            # benign, by-design situations (unreadable files, files exceeding scan
            # limits, truncated archives). Treat as CLEAN only when we positively
            # identified the cause as non-fatal (a skipped file or a limit/truncation
            # warning) and nothing looked like a hard error. Unrecognized stderr
            # stays ERROR.
            if not hard_error_lines and (skipped_files or nonfatal_warnings):
                status = ScanStatus.CLEAN
                if skipped_files:
                    warning_message = f"{len(skipped_files)} file(s) could not be accessed"
            else:
                status = ScanStatus.ERROR
        else:
            status = ScanStatus.ERROR

        # Prefer stderr for hard errors, but fall back to a concise stdout line when stderr is empty.
        error_message: str | None = None
        if status == ScanStatus.ERROR:
            error_message = stderr.strip() or None
            if error_message is None:
                if hard_error_lines:
                    error_message = hard_error_lines[0]
                else:
                    for out_line in stdout.splitlines():
                        candidate = out_line.strip()
                        if candidate and "SCAN SUMMARY" not in candidate:
                            error_message = candidate
                            break

        return ScanResult(
            status=status,
            path=path,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            infected_files=infected_files,
            scanned_files=scanned_files,
            scanned_dirs=scanned_dirs,
            infected_count=infected_count,
            error_message=error_message,
            threat_details=threat_details,
            skipped_files=skipped_files,
            skipped_count=len(skipped_files),
            warning_message=warning_message,
        )

    def _collect_exclusion_patterns(self, profile_exclusions: dict | None = None) -> list[str]:
        """
        Collect all exclusion patterns from settings and profile.

        Args:
            profile_exclusions: Optional exclusions from a scan profile

        Returns:
            List of exclusion patterns (glob patterns or exact paths)
        """
        patterns: list[str] = []

        # Global exclusions from settings
        if self._settings_manager is not None:
            exclusions = self._settings_manager.get("exclusion_patterns", [])
            for exclusion in exclusions:
                if not exclusion.get("enabled", True):
                    continue
                pattern = exclusion.get("pattern", "")
                if pattern:
                    patterns.append(pattern)

        # Profile exclusions - patterns
        if profile_exclusions:
            for pattern in profile_exclusions.get("patterns", []):
                if pattern:
                    patterns.append(pattern)

        return patterns

    def _collect_exclusion_paths(self, profile_exclusions: dict | None = None) -> list[Path]:
        """
        Collect all exclusion directory paths from profile.

        Args:
            profile_exclusions: Optional exclusions from a scan profile

        Returns:
            List of resolved Path objects for excluded directories
        """
        paths: list[Path] = []

        if profile_exclusions:
            for path_str in profile_exclusions.get("paths", []):
                if path_str:
                    path = Path(path_str).expanduser().resolve()
                    paths.append(path)

        return paths

    def _matches_exclusion_pattern(self, file_path: str, patterns: list[str]) -> bool:
        """
        Check if a file path matches any exclusion pattern.

        Args:
            file_path: The file path to check
            patterns: List of exclusion patterns (glob or exact path)

        Returns:
            True if the file matches any pattern
        """
        for pattern in patterns:
            # Expand ~ in patterns
            if pattern.startswith("~"):
                pattern = str(Path(pattern).expanduser())

            # Check for exact path match or fnmatch pattern match
            if file_path == pattern or fnmatch.fnmatch(file_path, pattern):
                return True

        return False

    def _matches_exclusion_path(self, file_path: str, exclude_paths: list[Path]) -> bool:
        """
        Check if a file path is under any excluded directory.

        Args:
            file_path: The file path to check
            exclude_paths: List of resolved excluded directory paths

        Returns:
            True if the file is under any excluded directory
        """
        if not exclude_paths:
            return False

        resolved_file = Path(file_path).resolve()
        resolved_file_str = str(resolved_file)

        for excl_path in exclude_paths:
            excl_path_str = str(excl_path)
            # Match if file is the excluded path or under it
            if resolved_file == excl_path or resolved_file_str.startswith(excl_path_str + "/"):
                return True

        return False

    def _filter_excluded_threats(
        self, result: ScanResult, profile_exclusions: dict | None = None
    ) -> ScanResult:
        """
        Filter out threats that match exclusion patterns.

        Since clamdscan doesn't support --exclude options, we filter the
        results post-scan to remove any threats matching exclusion patterns.

        Args:
            result: The parsed ScanResult
            profile_exclusions: Optional exclusions from a scan profile

        Returns:
            A new ScanResult with excluded threats filtered out
        """
        if result.status != ScanStatus.INFECTED or not result.threat_details:
            return result

        # Collect exclusion patterns and paths using helper methods
        exclude_patterns = self._collect_exclusion_patterns(profile_exclusions)
        exclude_paths = self._collect_exclusion_paths(profile_exclusions)

        if not exclude_patterns and not exclude_paths:
            return result

        # Filter threats using helper methods
        filtered_threats = []
        filtered_files = []

        for threat in result.threat_details:
            file_path = threat.file_path

            # Check pattern exclusions, then path exclusions
            if self._matches_exclusion_pattern(file_path, exclude_patterns):
                continue
            if self._matches_exclusion_path(file_path, exclude_paths):
                continue

            filtered_threats.append(threat)
            filtered_files.append(file_path)

        # Build result based on remaining threats
        if not filtered_threats:
            return ScanResult(
                status=ScanStatus.CLEAN,
                path=result.path,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                infected_files=[],
                scanned_files=result.scanned_files,
                scanned_dirs=result.scanned_dirs,
                infected_count=0,
                error_message=None,
                threat_details=[],
                skipped_files=result.skipped_files,
                skipped_count=result.skipped_count,
            )

        return ScanResult(
            status=ScanStatus.INFECTED,
            path=result.path,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            infected_files=filtered_files,
            scanned_files=result.scanned_files,
            scanned_dirs=result.scanned_dirs,
            infected_count=len(filtered_threats),
            error_message=None,
            threat_details=filtered_threats,
            skipped_files=result.skipped_files,
            skipped_count=result.skipped_count,
        )

    def _save_scan_log(self, result: ScanResult, duration: float) -> None:
        """Save scan result to log."""
        save_scan_log(self._log_manager, result, duration, suffix="(daemon)")
