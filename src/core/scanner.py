# ClamUI Scanner Module
"""
Scanner module for ClamUI providing ClamAV subprocess execution and async scanning.
"""

import fnmatch
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import GLib

from .clamav_config import parse_config
from .log_manager import LogManager
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
    check_clamav_installed,
    check_clamd_connection,
    get_clamav_path,
    get_clean_env,
    resolve_clamd_conf_path,
    validate_path,
    wrap_host_command,
)

if TYPE_CHECKING:
    from .daemon_scanner import DaemonScanner

logger = logging.getLogger(__name__)


def glob_to_regex(pattern: str) -> str:
    """
    Convert a user-friendly glob pattern to POSIX ERE for ClamAV.

    Uses fnmatch.translate() for conversion and strips Python-specific
    regex suffixes for ClamAV compatibility. Adds anchors (^ and $) to ensure
    the pattern matches the entire string, not just a substring.

    Edge Cases:
    - fnmatch doesn't support '**' recursive wildcards (use '*' for single level)
    - Character classes like [abc] are converted to (a|b|c) regex syntax
    - Special chars (., +, etc.) are automatically escaped by fnmatch
    - Anchors (^ and $) prevent substring matching (e.g., "*.tmp" won't match "file.tmp.bak")

    Args:
        pattern: Glob pattern (e.g., '*.log', 'node_modules', '/tmp/*')

    Returns:
        POSIX Extended Regular Expression string with anchors
    """
    regex = fnmatch.translate(pattern)
    # Strip fnmatch's \Z(?ms) suffix for ClamAV compatibility
    # fnmatch.translate() adds (?s:...) wrapper and \Z anchor
    # We need to remove these for ClamAV's regex engine
    if regex.endswith(r"\Z"):
        regex = regex[:-2]
    # Handle newer Python versions that use (?s:pattern)\Z format
    if regex.startswith("(?s:") and regex.endswith(")"):
        regex = regex[4:-1]
    # Add anchors to ensure full string match (prevents substring matching)
    if not regex.startswith("^"):
        regex = "^" + regex
    if not regex.endswith("$"):
        regex = regex + "$"
    return regex


def validate_pattern(pattern: str) -> bool:
    """
    Validate that a pattern can be converted and compiled as regex.

    Args:
        pattern: Glob pattern to validate

    Returns:
        True if pattern is valid, False otherwise
    """
    if not pattern or not pattern.strip():
        return False
    try:
        re.compile(glob_to_regex(pattern))
        return True
    except re.error:
        return False


# Re-export types for backwards compatibility
__all__ = [
    "ScanProgress",
    "ScanResult",
    "ScanStatus",
    "Scanner",
    "ThreatDetail",
    "glob_to_regex",
    "validate_pattern",
]


class Scanner:
    """
    ClamAV scanner with async execution support.

    Supports multiple scan backends:
    - "auto": Prefer daemon if available, fallback to clamscan
    - "daemon": Use clamd daemon only (error if unavailable)
    - "clamscan": Use standalone clamscan only

    Provides methods for running scans in a background thread
    while safely updating the UI via GLib.idle_add.
    """

    # Cache daemon availability check result (60-second TTL)
    _daemon_cache: tuple[float, bool] | None = None
    _DAEMON_CACHE_TTL = 60.0

    def __init__(
        self,
        log_manager: LogManager | None = None,
        settings_manager: SettingsManager | None = None,
    ):
        """
        Initialize the scanner.

        Args:
            log_manager: Optional LogManager instance for saving scan logs.
                         If not provided, a default instance is created.
            settings_manager: Optional SettingsManager instance for reading
                              exclusion patterns and scan backend settings.
        """
        self._current_process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._log_manager = log_manager if log_manager else LogManager()
        self._settings_manager = settings_manager
        self._daemon_scanner: DaemonScanner | None = None

    def _get_backend(self) -> str:
        """Get the configured scan backend.

        Both native and Flatpak installations can use the daemon backend.
        In Flatpak, daemon commands are executed on the host via
        flatpak-spawn --host, where they can access clamd normally.
        """
        if self._settings_manager:
            return self._settings_manager.get("scan_backend", "auto")
        return "auto"

    def _get_daemon_scanner(self) -> "DaemonScanner":
        """Get or create the daemon scanner instance."""
        if self._daemon_scanner is None:
            from .daemon_scanner import DaemonScanner

            self._daemon_scanner = DaemonScanner(
                log_manager=self._log_manager, settings_manager=self._settings_manager
            )
        return self._daemon_scanner

    def _get_clamd_config_path(self) -> str | None:
        """Resolve clamd.conf when settings contain a path-like value."""
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

    # clamd.conf scan-limit keys mapped to their clamscan command-line flags.
    # Both backends share libclamav, so the clamd.conf values (including "0" for
    # unlimited and "25M"-style size suffixes) are accepted verbatim by clamscan.
    _CLAMSCAN_LIMIT_FLAGS = (
        ("MaxFileSize", "--max-filesize"),
        ("MaxScanSize", "--max-scansize"),
        ("MaxRecursion", "--max-recursion"),
        ("MaxFiles", "--max-files"),
    )

    def _get_clamscan_limit_args(self) -> list[str]:
        """Forward clamd.conf scan limits to the standalone clamscan backend.

        clamd.conf is the single source of truth for MaxFileSize/MaxScanSize/
        MaxRecursion/MaxFiles (edited via the Scanner preferences page). The daemon
        backend reads them directly; standalone clamscan does not, so without this
        the preferences silently have no effect on clamscan scans. Best-effort: if
        clamd.conf is unavailable or unparseable we return no args and clamscan
        falls back to its own defaults (preserving prior behavior).
        """
        config_path = self._get_clamd_config_path()
        if not config_path:
            return []

        config, error = parse_config(config_path)
        if config is None or error:
            return []

        args: list[str] = []
        for conf_key, flag in self._CLAMSCAN_LIMIT_FLAGS:
            if not config.has_key(conf_key):
                continue
            value = config.get_value(conf_key)
            if value is None or not value.strip():
                continue
            args.append(f"{flag}={value.strip()}")
        return args

    def _is_daemon_available_cached(self) -> bool:
        """Check daemon availability with caching (60s TTL)."""
        now = time.monotonic()
        if (
            Scanner._daemon_cache is not None
            and now - Scanner._daemon_cache[0] < Scanner._DAEMON_CACHE_TTL
        ):
            return Scanner._daemon_cache[1]

        is_available, _ = check_clamd_connection(config_path=self._get_clamd_config_path())
        Scanner._daemon_cache = (now, is_available)
        return is_available

    def get_active_backend(self) -> str:
        """
        Get the backend that will actually be used for scanning.

        Returns:
            "daemon" if daemon will be used, "clamscan" otherwise
        """
        backend = self._get_backend()
        if backend == "clamscan":
            return "clamscan"
        elif backend == "daemon":
            is_available, _ = self._get_daemon_scanner().check_available()
            return "daemon" if is_available else "unavailable"
        else:  # auto
            is_available = self._is_daemon_available_cached()
            return "daemon" if is_available else "clamscan"

    def check_available(self) -> tuple[bool, str | None]:
        """
        Check if the configured scan backend is available.

        Auto Backend Fallback Logic:
        1. Check if clamd daemon is accessible via socket connection
        2. If daemon available: return success with "Using clamd daemon"
        3. If daemon unavailable: fall back to checking clamscan binary
        4. If clamscan available: return success (scans will use clamscan)
        5. If neither available: return error from clamscan check

        This ensures seamless fallback without user intervention, preferring
        the faster daemon when available but gracefully using clamscan otherwise.

        Returns:
            Tuple of (is_available, version_or_error)
        """
        backend = self._get_backend()

        if backend == "clamscan":
            return check_clamav_installed()
        elif backend == "daemon":
            return self._get_daemon_scanner().check_available()
        else:  # auto
            # For auto, check if daemon is available, otherwise fallback to clamscan
            is_daemon_available = self._is_daemon_available_cached()
            if is_daemon_available:
                return (True, "Using clamd daemon")
            return check_clamav_installed()

    def scan_sync(
        self,
        path: str,
        recursive: bool = True,
        profile_exclusions: dict | None = None,
        progress_callback: Callable[[ScanProgress], None] | None = None,
        backend_override: str | None = None,
        daemon_force_stream: bool = False,
    ) -> ScanResult:
        """
        Execute a synchronous scan on the given path.

        WARNING: This will block the calling thread. For UI applications,
        use scan_async() instead.

        Progress Callback Threading Behavior:
        - progress_callback is called directly from the background thread running scan_sync()
        - Callback receives ScanProgress updates on the SAME thread (background thread)
        - For GTK UI updates, wrap callback logic with GLib.idle_add() inside the callback
        - Callback is invoked for each file scanned and each infection detected

        Args:
            path: Path to file or directory to scan
            recursive: Whether to scan directories recursively
            profile_exclusions: Optional exclusions from a scan profile.
                               Format: {"paths": ["/path1", ...], "patterns": ["*.ext", ...]}
            progress_callback: Optional callback for real-time progress updates.
                              If provided, verbose mode is used and callback receives
                              ScanProgress updates as files are scanned.
            backend_override: Optional one-shot backend override for this scan.
                              Uses the provided backend without changing saved settings.
            daemon_force_stream: Force the daemon backend to use clamdscan's
                                 --stream mode for this scan.

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

        # Determine which backend to use
        backend = backend_override if backend_override is not None else self._get_backend()

        # For daemon-only mode, delegate entirely to daemon scanner
        if backend == "daemon":
            return self._get_daemon_scanner().scan_sync(
                path,
                recursive,
                profile_exclusions,
                progress_callback=progress_callback,
                force_stream=daemon_force_stream,
            )

        # For auto mode, try daemon first if available
        if backend == "auto":
            is_daemon_available = self._is_daemon_available_cached()
            if is_daemon_available:
                return self._get_daemon_scanner().scan_sync(
                    path,
                    recursive,
                    profile_exclusions,
                    progress_callback=progress_callback,
                    force_stream=daemon_force_stream,
                )

        # Fall through to clamscan for "clamscan" mode or auto fallback
        is_installed, version_or_error = check_clamav_installed()
        if not is_installed:
            result = create_error_result(path, version_or_error or "ClamAV not installed")
            self._save_scan_log(result, time.monotonic() - start_time)
            return result

        # Count files for progress tracking (if callback is provided)
        files_total: int | None = None
        if progress_callback is not None:
            files_total = self._count_files(path, profile_exclusions)
            # Check if cancelled during file counting
            if self._cancel_event.is_set():
                result = create_cancelled_result(path)
                self._save_scan_log(result, time.monotonic() - start_time)
                return result

        # Build clamscan command (use verbose mode if progress callback provided)
        cmd = self._build_command(
            path, recursive, profile_exclusions, verbose=progress_callback is not None
        )

        try:
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
                        self._current_process, progress_callback, files_total
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
                result = create_cancelled_result(
                    path,
                    stdout,
                    stderr,
                    exit_code if exit_code is not None else -1,
                    scanned_files=progress_files_scanned,
                    infected_files=progress_infected_files,
                    infected_count=progress_infected_count,
                )
                self._save_scan_log(result, time.monotonic() - start_time)
                return result

            # Parse the results
            result = self._parse_results(path, stdout, stderr, exit_code)
            self._save_scan_log(result, time.monotonic() - start_time)
            return result

        except FileNotFoundError:
            result = create_error_result(path, "ClamAV executable not found")
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

    def _count_files(self, path: str, profile_exclusions: dict | None = None) -> int | None:
        """
        Pre-count files for progress calculation.

        Uses os.scandir for fast counting, respecting exclusion patterns.

        Args:
            path: Path to scan
            profile_exclusions: Optional exclusions from a scan profile

        Returns:
            Total number of files to scan, or None if counting was skipped
        """
        scan_path = Path(path)

        # Single file scan
        if scan_path.is_file():
            return 1

        # Skip pre-counting for root-level paths (adds 3-30s of overhead)
        # The UI handles files_total=None gracefully (shows count without percentage)
        ROOT_LEVEL_PATHS = {"/", "/home", "/usr", "/var", "/opt", "/etc", "/tmp", "/root"}
        resolved = str(scan_path.resolve())
        if resolved in ROOT_LEVEL_PATHS:
            return None

        # Not a valid path
        if not scan_path.is_dir():
            return None

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
                    if excl_path.startswith("~"):
                        excl_path = str(Path(excl_path).expanduser())
                    exclude_dirs.append(excl_path)

            for pattern in profile_exclusions.get("patterns", []):
                if pattern:
                    exclude_patterns.append(pattern)

        file_count = 0

        try:
            for root, dirs, files in os.walk(path):
                # Check for cancellation during counting
                if self._cancel_event.is_set():
                    logger.info("File counting cancelled by user")
                    return 0

                # Filter out excluded directories (modifies dirs in-place)
                dirs[:] = [
                    d
                    for d in dirs
                    if not self._is_path_excluded(
                        os.path.join(root, d), d, exclude_dirs, is_dir=True
                    )
                ]

                # Count files that aren't excluded
                for f in files:
                    file_path = os.path.join(root, f)
                    if not self._is_path_excluded(file_path, f, exclude_patterns, is_dir=False):
                        file_count += 1
        except (PermissionError, OSError):
            # If we can't access the directory, return 0
            return file_count

        return file_count

    def _is_path_excluded(
        self, full_path: str, name: str, patterns: list[str], is_dir: bool
    ) -> bool:
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

    def _scan_with_progress(
        self,
        process: subprocess.Popen,
        progress_callback: Callable[[ScanProgress], None],
        files_total: int | None,
    ) -> tuple[str, str, bool, int, int, list[str]]:
        """
        Scan with real-time progress updates.

        Streams ClamAV verbose output and parses it to track progress,
        calling the progress_callback for each file scanned.

        Args:
            process: The subprocess running clamscan with -v flag
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

        def on_line(line: str) -> None:
            nonlocal files_scanned, infected_count, infected_files
            nonlocal infected_threats, current_file

            # Parse verbose ClamAV output
            # Format for scanning: "Scanning /path/to/file"
            # Format for infected: "/path/to/file: ThreatName FOUND"
            line = line.strip()

            if line.startswith("Scanning "):
                # Extract file path from "Scanning /path/to/file"
                current_file = line[9:]  # Remove "Scanning " prefix
                files_scanned += 1

                # Create and send progress update
                progress = ScanProgress(
                    current_file=current_file,
                    files_scanned=files_scanned,
                    files_total=files_total,
                    infected_count=infected_count,
                    infected_files=list(infected_files),
                    infected_threats=dict(infected_threats),
                    estimate_exceeded=(files_total is not None and files_scanned > files_total),
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
                    infected_count += 1
                    infected_files.append(file_path)
                    infected_threats[file_path] = threat_name

                    # Send updated progress with new infection
                    progress = ScanProgress(
                        current_file=file_path,
                        files_scanned=files_scanned,
                        files_total=files_total,
                        infected_count=infected_count,
                        infected_files=list(infected_files),
                        infected_threats=dict(infected_threats),
                        estimate_exceeded=(files_total is not None and files_scanned > files_total),
                    )
                    progress_callback(progress)

        stdout, stderr, was_cancelled = stream_process_output(
            process, self._cancel_event.is_set, on_line
        )
        return stdout, stderr, was_cancelled, files_scanned, infected_count, infected_files

    def scan_async(
        self,
        path: str,
        callback: Callable[[ScanResult], None],
        recursive: bool = True,
        profile_exclusions: dict | None = None,
        progress_callback: Callable[[ScanProgress], None] | None = None,
        daemon_force_stream: bool = False,
    ) -> None:
        """
        Execute an asynchronous scan on the given path.

        The scan runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        GLib.idle_add() Pattern for Thread-Safe UI Updates:
        - scan_sync() runs in a background thread (blocks for entire scan duration)
        - Direct GTK widget updates from background threads are UNSAFE and will crash
        - GLib.idle_add() schedules callback on the main GTK event loop thread
        - This ensures all UI updates happen on the main thread where GTK expects them
        - The callback is queued and executed during the next GTK main loop iteration
        - Multiple GLib.idle_add() calls are serialized automatically by GTK

        Why This Matters:
        - GTK is not thread-safe - only the main thread can update widgets
        - Without GLib.idle_add(), you'll get race conditions and segfaults
        - This is the standard pattern for async operations in GTK applications

        Args:
            path: Path to file or directory to scan
            callback: Function to call with ScanResult when scan completes
            recursive: Whether to scan directories recursively
            profile_exclusions: Optional exclusions from a scan profile.
                               Format: {"paths": ["/path1", ...], "patterns": ["*.ext", ...]}
            progress_callback: Optional callback for real-time progress updates.
                              If provided, callback receives ScanProgress updates
                              as files are scanned.
            daemon_force_stream: Force the daemon backend to use clamdscan's
                                 --stream mode for this scan.
        """

        def scan_thread():
            result = self.scan_sync(
                path,
                recursive,
                profile_exclusions,
                progress_callback,
                daemon_force_stream=daemon_force_stream,
            )
            # Schedule callback on main thread
            GLib.idle_add(callback, result)

        thread = threading.Thread(target=scan_thread)
        thread.daemon = True
        thread.start()

    def cancel(self) -> None:
        """
        Cancel the current scan operation with graceful shutdown escalation.

        Cleanup Guarantees:
        1. Sets _cancel_event to signal ongoing operations to stop
        2. Sends SIGTERM to the process for graceful termination
        3. Waits up to 5 seconds for process to exit cleanly
        4. Escalates to SIGKILL if process doesn't respond
        5. Ensures process resources are fully released (file handles, memory)
        6. Resets _current_process to None to prevent double-termination
        7. Also cancels daemon scanner if it was being used

        Thread Safety: Uses _process_lock to prevent race conditions during
        cancellation while scan operations are starting or completing.

        If a scan is in progress, it will be terminated with SIGTERM first,
        then escalated to SIGKILL if the process doesn't respond within
        the grace period. Cancels both clamscan and daemon scanner if active.
        """
        self._cancel_event.set()
        # Acquire lock to safely get process reference
        with self._process_lock:
            process = self._current_process
        # Terminate outside lock to avoid holding it during I/O
        terminate_process_gracefully(process)

        # Also cancel daemon scanner if it exists
        if self._daemon_scanner is not None:
            self._daemon_scanner.cancel()

    def _build_command(
        self,
        path: str,
        recursive: bool,
        profile_exclusions: dict | None = None,
        verbose: bool = False,
    ) -> list[str]:
        """
        Build the clamscan command arguments.

        When running inside a Flatpak sandbox, the command is automatically
        wrapped with 'flatpak-spawn --host' to execute ClamAV on the host system.

        Args:
            path: Path to scan
            recursive: Whether to scan recursively
            profile_exclusions: Optional exclusions from a scan profile.
                               Format: {"paths": ["/path1", ...], "patterns": ["*.ext", ...]}
            verbose: Whether to enable verbose mode for progress tracking.
                    When True, clamscan outputs each file as it's scanned.

        Returns:
            List of command arguments (wrapped with flatpak-spawn if in Flatpak)
        """
        clamscan = get_clamav_path() or "clamscan"
        cmd = [clamscan]

        # -r / --recursive: Scan subdirectories recursively
        # Add recursive flag for directories
        if recursive and Path(path).is_dir():
            cmd.append("-r")

        # -v / --verbose: Output each file as it's scanned (enables progress tracking)
        # -i / --infected: Show only infected files (cleaner output when no progress needed)
        # Verbose mode for progress tracking (outputs each file being scanned)
        if verbose:
            cmd.append("-v")
        else:
            # Show infected files only (reduces output noise)
            cmd.append("-i")

        # Forward clamd.conf scan limits (MaxFileSize/MaxScanSize/etc.) so the
        # standalone clamscan backend honors the same Scanner preferences as the
        # daemon backend instead of silently using clamscan's built-in defaults.
        cmd.extend(self._get_clamscan_limit_args())

        # Inject exclusion patterns from settings
        if self._settings_manager is not None:
            exclusions = self._settings_manager.get("exclusion_patterns", [])
            for exclusion in exclusions:
                if not exclusion.get("enabled", True):
                    continue

                pattern = exclusion.get("pattern", "")
                if not pattern:
                    continue

                regex = glob_to_regex(pattern)
                exclusion_type = exclusion.get("type", "pattern")

                if exclusion_type == "directory":
                    cmd.extend(["--exclude-dir", regex])
                else:  # file or pattern
                    cmd.extend(["--exclude", regex])

        # Apply profile exclusions (paths and patterns)
        if profile_exclusions:
            # Handle path exclusions (directories)
            for excl_path in profile_exclusions.get("paths", []):
                if not excl_path:
                    continue
                # Expand ~ in exclusion paths
                if excl_path.startswith("~"):
                    excl_path = str(Path(excl_path).expanduser())
                # Use the path directly for --exclude-dir (ClamAV accepts paths)
                cmd.extend(["--exclude-dir", excl_path])

            # Handle pattern exclusions (file patterns like *.tmp)
            for pattern in profile_exclusions.get("patterns", []):
                if not pattern:
                    continue
                # Convert glob pattern to regex for ClamAV
                regex = glob_to_regex(pattern)
                cmd.extend(["--exclude", regex])

        # Add the path to scan. Use "--" so a filename starting with "-"
        # is not reinterpreted as a clamscan flag.
        cmd.append("--")
        cmd.append(path)

        # Wrap with flatpak-spawn if running inside Flatpak sandbox
        return wrap_host_command(cmd)

    def _parse_results(self, path: str, stdout: str, stderr: str, exit_code: int) -> ScanResult:
        """
        Parse clamscan output into a ScanResult.

        ClamAV exit codes:
        - 0: No virus found
        - 1: Virus(es) found
        - 2: Some error(s) occurred

        Args:
            path: The scanned path
            stdout: Standard output from clamscan
            stderr: Standard error from clamscan
            exit_code: Process exit code

        Returns:
            Parsed ScanResult
        """
        infected_files = []
        threat_details = []
        skipped_files, nonfatal_warnings, hard_error_lines = collect_clamav_warnings(stdout, stderr)
        scanned_files = 0
        scanned_dirs = 0
        infected_count = 0

        # Parse stdout line by line
        for line in stdout.splitlines():
            line = line.strip()

            # Regex pattern: "/path/to/file: ThreatName FOUND"
            # Uses rsplit to handle colons in file paths (e.g., Windows C:\)
            # Look for infected file lines (format: "/path/to/file: Virus.Name FOUND")
            # Skip verbose "Scanning <path>" lines so a clean file whose name
            # ends in "FOUND" is not misparsed as a detection (mirrors on_line).
            if line.startswith("Scanning "):
                continue

            if line.endswith("FOUND"):
                # Extract file path and threat name
                # Format: "/path/to/file: ThreatName FOUND"
                parts = line.rsplit(":", 1)
                if len(parts) == 2:
                    file_path = parts[0].strip()
                    # Extract threat name (remove " FOUND" suffix)
                    threat_part = parts[1].strip()
                    threat_name = (
                        threat_part.rsplit(" ", 1)[0].strip()
                        if " FOUND" in threat_part
                        else threat_part
                    )

                    infected_files.append(file_path)

                    # Create ThreatDetail with classification
                    threat_detail = ThreatDetail(
                        file_path=file_path,
                        threat_name=threat_name,
                        category=categorize_threat(threat_name),
                        severity=classify_threat_severity_str(threat_name),
                    )
                    threat_details.append(threat_detail)
                    infected_count += 1

            # Regex pattern for statistics: "Scanned files: 123"
            # Captures numeric value after the label
            # Look for individual summary lines from ClamAV output
            # Format: "Scanned files: 10" or "Scanned directories: 1" or "Infected files: 0"
            elif line.startswith("Scanned files:"):
                match = re.search(r"Scanned files:\s*(\d+)", line)
                if match:
                    scanned_files = int(match.group(1))
            elif line.startswith("Scanned directories:"):
                match = re.search(r"Scanned directories:\s*(\d+)", line)
                if match:
                    scanned_dirs = int(match.group(1))

        # Determine overall status based on exit code
        warning_message = None
        if infected_count > 0:
            # Detections are authoritative: clamscan returns exit code 2 when it
            # both finds a virus and hits an error (e.g. an unreadable file), so
            # never let an error code mask a real threat.
            status = ScanStatus.INFECTED
            if exit_code == 2 and skipped_files:
                warning_message = f"{len(skipped_files)} file(s) could not be accessed"
        elif exit_code == 0:
            status = ScanStatus.CLEAN
        elif exit_code == 1:
            status = ScanStatus.INFECTED
        elif exit_code == 2:
            # Exit code 2 = warnings/errors. clamscan reports 2 even for benign,
            # by-design situations (unreadable files, files exceeding scan limits,
            # truncated archives). Treat as CLEAN only when we positively identified
            # the cause as non-fatal (a skipped file or a limit/truncation warning)
            # and nothing looked like a hard error. Unrecognized stderr stays ERROR.
            if not hard_error_lines and (skipped_files or nonfatal_warnings):
                status = ScanStatus.CLEAN
                if skipped_files:
                    warning_message = f"{len(skipped_files)} file(s) could not be accessed"
            else:
                status = ScanStatus.ERROR
        else:
            status = ScanStatus.ERROR

        error_message = None
        if status == ScanStatus.ERROR:
            error_message = stderr.strip() or (hard_error_lines[0] if hard_error_lines else None)

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

    def _save_scan_log(self, result: ScanResult, duration: float) -> None:
        """Save scan result to log."""
        save_scan_log(self._log_manager, result, duration)
