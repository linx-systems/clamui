# ClamUI Scan Flow E2E Tests
"""End-to-end tests for scan configuration, execution, parsing, and logging."""

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest  # type: ignore[reportMissingImports]

# Store original gi modules to restore later (if they exist)
_original_gi = sys.modules.get("gi")
_original_gi_repository = sys.modules.get("gi.repository")

# Mock gi module before importing to avoid GTK dependencies in tests
sys.modules["gi"] = mock.MagicMock()
sys.modules["gi.repository"] = mock.MagicMock()

from src.core.log_manager import LogEntry, LogManager
from src.core.scanner import Scanner, glob_to_regex, validate_pattern
from src.core.scanner_types import ScanProgress, ScanResult, ScanStatus, ThreatDetail
from src.core.settings_manager import SettingsManager
from src.core.threat_classifier import categorize_threat, classify_threat_severity_str

# Restore original gi modules after imports are done
if _original_gi is not None:
    sys.modules["gi"] = _original_gi
else:
    del sys.modules["gi"]
if _original_gi_repository is not None:
    sys.modules["gi.repository"] = _original_gi_repository
else:
    del sys.modules["gi.repository"]


CLEAN_SCAN_OUTPUT = """Scanning /tmp/scan_target/file1.txt
Scanning /tmp/scan_target/file2.txt

----------- SCAN SUMMARY -----------
Known viruses: 8700000
Engine version: 1.0.0
Scanned directories: 1
Scanned files: 2
Infected files: 0
Data scanned: 0.01 MB
Data read: 0.01 MB
Time: 1.234 sec (0 m 1 s)
"""

INFECTED_SCAN_OUTPUT = """/tmp/scan_target/malware.exe: Win.Trojan.Agent-12345 FOUND
/tmp/scan_target/virus.doc: Doc.Exploit.CVE_2017_0199 FOUND

----------- SCAN SUMMARY -----------
Known viruses: 8700000
Engine version: 1.0.0
Scanned directories: 1
Scanned files: 5
Infected files: 2
Data scanned: 0.05 MB
Data read: 0.05 MB
Time: 2.345 sec (0 m 2 s)
"""

ERROR_SCAN_STDERR = "LibClamAV Error: Database file not found"


@pytest.fixture(autouse=True)
def _reset_scanner_cache():
    """Reset Scanner class-level daemon cache between tests.

    Scanner._daemon_cache is a class variable with 60s TTL. Without this reset,
    test_e2e_auto_backend_prefers_daemon_when_available sets it to (timestamp, True),
    causing subsequent tests to bypass check_clamd_connection mocks and take the
    daemon path unexpectedly.
    """
    Scanner._daemon_cache = None
    yield
    Scanner._daemon_cache = None


@pytest.fixture
def e2e_env():
    """Shared temporary E2E environment."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        config_dir = base / "config"
        log_dir = base / "logs"
        scan_dir = base / "scan_target"

        config_dir.mkdir(parents=True)
        log_dir.mkdir(parents=True)
        scan_dir.mkdir(parents=True)

        (scan_dir / "file1.txt").write_text("clean content 1", encoding="utf-8")
        (scan_dir / "file2.txt").write_text("clean content 2", encoding="utf-8")
        (scan_dir / "cache.tmp").write_text("temporary data", encoding="utf-8")

        settings = SettingsManager(config_dir=config_dir)
        log_manager = LogManager(log_dir=str(log_dir))

        yield {
            "base": base,
            "config_dir": config_dir,
            "log_dir": log_dir,
            "scan_dir": scan_dir,
            "settings": settings,
            "log_manager": log_manager,
        }


def _make_process(stdout: str, stderr: str, returncode: int) -> mock.MagicMock:
    process = mock.MagicMock()
    process.communicate.return_value = (stdout, stderr)
    process.returncode = returncode
    return process


class TestE2EGlobToRegex:
    """E2E tests for pattern conversion pipeline."""

    def test_e2e_common_glob_patterns_and_anchors(self, e2e_env):
        """
        E2E Test: Convert common glob patterns into anchored regex.

        Steps:
        1. Convert common glob patterns used by scan exclusions.
        2. Verify output regex contains start/end anchors.
        3. Verify converted regex preserves expected pattern semantics.
        """
        _ = e2e_env["scan_dir"]
        converted = {
            "*.log": glob_to_regex("*.log"),
            "*.tmp": glob_to_regex("*.tmp"),
            "node_modules": glob_to_regex("node_modules"),
            "/tmp/*": glob_to_regex("/tmp/*"),
        }

        for regex in converted.values():
            assert regex.startswith("^")
            assert regex.endswith("$")

        assert "log" in converted["*.log"]
        assert "tmp" in converted["*.tmp"]
        assert "node_modules" in converted["node_modules"]
        assert "/tmp" in converted["/tmp/*"]

    def test_e2e_special_character_patterns_convert_to_regex(self, e2e_env):
        """
        E2E Test: Convert special-character glob patterns safely.

        Steps:
        1. Convert patterns with brackets, spaces, and punctuation.
        2. Compile generated regex to ensure syntactic correctness.
        3. Verify all generated regexes remain anchored.
        """
        _ = e2e_env["scan_dir"]
        patterns = ["file[0-9].txt", "test (copy).log", "backup+old?.tmp"]
        regexes = [glob_to_regex(pattern) for pattern in patterns]

        for regex in regexes:
            assert regex.startswith("^")
            assert regex.endswith("$")
            assert validate_pattern(regex.replace("^", "").replace("$", "") or "*")

    def test_e2e_validate_pattern_accepts_and_rejects_inputs(self, e2e_env):
        """
        E2E Test: Validate acceptable and invalid exclusion patterns.

        Steps:
        1. Validate common valid patterns.
        2. Validate empty/whitespace patterns are rejected.
        3. Verify path-style and wildcard patterns are accepted.
        """
        _ = e2e_env["scan_dir"]
        assert validate_pattern("*.log") is True
        assert validate_pattern("/tmp/*") is True
        assert validate_pattern("node_modules") is True
        assert validate_pattern("") is False
        assert validate_pattern("   ") is False


class TestE2EScanBackendSelection:
    """E2E tests for backend selection logic."""

    def test_e2e_auto_backend_prefers_daemon_when_available(self, e2e_env):
        """
        E2E Test: Auto backend selects daemon when available.

        Steps:
        1. Configure scanner for auto backend.
        2. Mock daemon as available.
        3. Verify scan delegates to daemon backend implementation.
        """
        settings = e2e_env["settings"]
        settings.set("scan_backend", "auto")

        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=settings)
        expected_result = ScanResult(
            status=ScanStatus.CLEAN,
            path=str(e2e_env["scan_dir"]),
            stdout="daemon ok",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=2,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )

        daemon_scanner = mock.MagicMock()
        daemon_scanner.scan_sync.return_value = expected_result

        with mock.patch(
            "src.core.scanner.check_clamd_connection", return_value=(True, "available")
        ):
            with mock.patch.object(scanner, "_get_daemon_scanner", return_value=daemon_scanner):
                with mock.patch("src.core.scanner.validate_path", return_value=(True, None)):
                    result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert result.status == ScanStatus.CLEAN
        daemon_scanner.scan_sync.assert_called_once()

    def test_e2e_auto_backend_falls_back_to_clamscan_when_daemon_unavailable(self, e2e_env):
        """
        E2E Test: Auto backend falls back to clamscan when daemon is unavailable.

        Steps:
        1. Configure scanner for auto backend.
        2. Mock daemon unavailable and clamscan available.
        3. Verify scan executes through clamscan subprocess path.
        """
        settings = e2e_env["settings"]
        settings.set("scan_backend", "auto")
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=settings)

        process = _make_process(CLEAN_SCAN_OUTPUT, "", 0)

        with mock.patch("src.core.scanner.check_clamd_connection", return_value=(False, "down")):
            with mock.patch(
                "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process) as popen:
                                    result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert result.status == ScanStatus.CLEAN
        popen.assert_called_once()

    def test_e2e_explicit_clamscan_ignores_daemon(self, e2e_env):
        """
        E2E Test: Explicit clamscan backend bypasses daemon checks.

        Steps:
        1. Configure scanner backend to clamscan.
        2. Force daemon check to raise if called.
        3. Verify active backend and scan path stay on clamscan.
        """
        settings = e2e_env["settings"]
        settings.set("scan_backend", "clamscan")
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=settings)

        process = _make_process(CLEAN_SCAN_OUTPUT, "", 0)

        with mock.patch("src.core.scanner.check_clamd_connection", side_effect=AssertionError):
            with mock.patch(
                "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process):
                                    result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert scanner.get_active_backend() == "clamscan"
        assert result.status == ScanStatus.CLEAN

    def test_e2e_explicit_daemon_reports_unavailable_when_down(self, e2e_env):
        """
        E2E Test: Explicit daemon backend reports unavailable when daemon is down.

        Steps:
        1. Configure scanner backend to daemon.
        2. Mock daemon availability check failure.
        3. Verify availability response and active backend indicator.
        """
        settings = e2e_env["settings"]
        settings.set("scan_backend", "daemon")
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=settings)

        daemon_scanner = mock.MagicMock()
        daemon_scanner.check_available.return_value = (False, "not available")

        with mock.patch.object(scanner, "_get_daemon_scanner", return_value=daemon_scanner):
            available, message = scanner.check_available()
            active = scanner.get_active_backend()

        assert available is False
        assert message == "not available"
        assert active == "unavailable"


class TestE2EScanExecution:
    """E2E tests for scan execution with mocked subprocess."""

    def test_e2e_clean_scan_returns_clean_result(self, e2e_env):
        """
        E2E Test: Clean scan execution via mocked clamscan subprocess.

        Steps:
        1. Prepare scanner with clamscan backend dependencies mocked.
        2. Mock subprocess output for a clean scan and exit code 0.
        3. Verify ScanResult status, counts, and threat details.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        process = _make_process(CLEAN_SCAN_OUTPUT, "", 0)

        with mock.patch(
            "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
        ):
            with mock.patch(
                "src.core.scanner.check_clamd_connection", return_value=(False, "not available")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process):
                                    result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert result.scanned_files == 2
        assert result.scanned_dirs == 1
        assert result.threat_details == []

    def test_e2e_infected_scan_extracts_threat_details(self, e2e_env):
        """
        E2E Test: Infected scan execution parses FOUND lines into threats.

        Steps:
        1. Prepare scanner with mocked clamscan dependencies.
        2. Mock subprocess output with multiple FOUND entries and exit code 1.
        3. Verify infected files, threat details, categories, and severities.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        process = _make_process(INFECTED_SCAN_OUTPUT, "", 1)

        with mock.patch(
            "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
        ):
            with mock.patch(
                "src.core.scanner.check_clamd_connection", return_value=(False, "not available")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process):
                                    result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert result.status == ScanStatus.INFECTED
        assert result.infected_count == 2
        assert len(result.infected_files) == 2
        assert len(result.threat_details) == 2
        assert isinstance(result.threat_details[0], ThreatDetail)

    def test_e2e_error_scan_exit_code_2_returns_error(self, e2e_env):
        """
        E2E Test: Error scan execution for clamscan exit code 2.

        Steps:
        1. Prepare scanner with mocked clamscan dependencies.
        2. Mock subprocess returning exit code 2 and stderr error text.
        3. Verify ScanResult has ERROR status and error message.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        process = _make_process("", ERROR_SCAN_STDERR, 2)

        with mock.patch(
            "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
        ):
            with mock.patch(
                "src.core.scanner.check_clamd_connection", return_value=(False, "not available")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process):
                                    result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert result.status == ScanStatus.ERROR
        assert result.error_message == ERROR_SCAN_STDERR
        assert result.exit_code == 2

    def test_e2e_scan_with_file_count_precounting_and_progress(self, e2e_env):
        """
        E2E Test: Progress scan pre-counts files and emits ScanProgress updates.

        Steps:
        1. Run scan with progress callback enabled.
        2. Mock streamed output lines for file scanning events.
        3. Verify progress callback receives ScanProgress with files_total.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        process = _make_process("", "", 0)
        updates: list[ScanProgress] = []

        def progress_callback(progress: ScanProgress) -> None:
            updates.append(progress)

        def stream_side_effect(process_obj, is_cancelled, on_line):
            on_line(f"Scanning {e2e_env['scan_dir'] / 'file1.txt'}")
            on_line(f"Scanning {e2e_env['scan_dir'] / 'file2.txt'}")
            return CLEAN_SCAN_OUTPUT, "", False

        with mock.patch(
            "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
        ):
            with mock.patch(
                "src.core.scanner.check_clamd_connection", return_value=(False, "not available")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process):
                                    with mock.patch(
                                        "src.core.scanner.stream_process_output",
                                        side_effect=stream_side_effect,
                                    ):
                                        result = scanner.scan_sync(
                                            str(e2e_env["scan_dir"]),
                                            progress_callback=progress_callback,
                                        )

        assert result.status == ScanStatus.CLEAN
        assert len(updates) >= 2
        assert all(isinstance(update, ScanProgress) for update in updates)
        assert updates[0].files_total == 3

    def test_e2e_scan_with_settings_and_profile_exclusions(self, e2e_env):
        """
        E2E Test: Scan command includes settings exclusions and profile exclusions.

        Steps:
        1. Configure global exclusion patterns in settings.
        2. Provide profile exclusions with paths and glob patterns.
        3. Verify built subprocess command includes all expected exclusion args.
        """
        settings = e2e_env["settings"]
        settings.set(
            "exclusion_patterns",
            [
                {"pattern": "*.tmp", "type": "pattern", "enabled": True},
                {"pattern": "node_modules", "type": "directory", "enabled": True},
            ],
        )
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=settings)
        process = _make_process(CLEAN_SCAN_OUTPUT, "", 0)

        profile_exclusions = {
            "paths": [str(e2e_env["scan_dir"] / "exclude_this")],
            "patterns": ["*.log"],
        }

        with mock.patch(
            "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
        ):
            with mock.patch(
                "src.core.scanner.check_clamd_connection", return_value=(False, "not available")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process) as popen:
                                    result = scanner.scan_sync(
                                        str(e2e_env["scan_dir"]),
                                        profile_exclusions=profile_exclusions,
                                    )

        cmd = popen.call_args[0][0]
        assert result.status == ScanStatus.CLEAN
        assert "--exclude" in cmd
        assert "--exclude-dir" in cmd
        assert glob_to_regex("*.tmp") in cmd
        assert glob_to_regex("*.log") in cmd
        assert str(e2e_env["scan_dir"] / "exclude_this") in cmd

    def test_e2e_cancelled_scan_returns_cancelled_result(self, e2e_env):
        """
        E2E Test: Cancelled scan returns CANCELLED status and cancellation message.

        Steps:
        1. Start scan with mocked process and cancellation-aware communication.
        2. Set scanner cancel event during communicate phase.
        3. Verify ScanResult is CANCELLED with cancellation error message.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        process = _make_process("partial output", "", -15)

        def communicate_side_effect(_process, _is_cancelled):
            scanner._cancel_event.set()
            return "partial output", "", True

        with mock.patch(
            "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
        ):
            with mock.patch(
                "src.core.scanner.check_clamd_connection", return_value=(False, "not available")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process):
                                    with mock.patch(
                                        "src.core.scanner.communicate_with_cancel_check",
                                        side_effect=communicate_side_effect,
                                    ):
                                        result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert result.status == ScanStatus.CANCELLED
        assert "cancelled" in (result.error_message or "").lower()


class TestE2EScanResultParsing:
    """E2E tests for parsing realistic clamscan output."""

    def test_e2e_parse_clean_output_with_summary_stats(self, e2e_env):
        """
        E2E Test: Parse clean clamscan output with summary statistics.

        Steps:
        1. Feed realistic clean scan stdout to parser.
        2. Parse with exit code 0.
        3. Verify clean status and scanned file/directory counts.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        result = scanner._parse_results(str(e2e_env["scan_dir"]), CLEAN_SCAN_OUTPUT, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.scanned_files == 2
        assert result.scanned_dirs == 1
        assert result.infected_count == 0

    def test_e2e_parse_infected_output_with_multiple_threats(self, e2e_env):
        """
        E2E Test: Parse infected output with multiple threats and classification.

        Steps:
        1. Feed realistic infected stdout to parser.
        2. Parse with exit code 1.
        3. Verify threat details match classifier integration outputs.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        result = scanner._parse_results(str(e2e_env["scan_dir"]), INFECTED_SCAN_OUTPUT, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert result.infected_count == 2
        assert len(result.threat_details) == 2

        for threat in result.threat_details:
            assert threat.category == categorize_threat(threat.threat_name)
            assert threat.severity == classify_threat_severity_str(threat.threat_name)

    def test_e2e_parse_failed_to_open_warnings_treated_as_clean(self, e2e_env):
        """
        E2E Test: Parse permission warnings and treat exit code 2 as clean when appropriate.

        Steps:
        1. Feed stdout containing failed-to-open warnings, no infections, and
           at least one successfully scanned file.
        2. Parse with exit code 2.
        3. Verify CLEAN status with skipped file warnings populated.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        warning_output = """/root/secret1: Failed to open file ERROR
/root/secret2: Failed to open file ERROR

----------- SCAN SUMMARY -----------
Scanned directories: 1
Scanned files: 1
Infected files: 0
"""

        result = scanner._parse_results(str(e2e_env["scan_dir"]), warning_output, "", 2)

        assert result.status == ScanStatus.CLEAN
        assert result.skipped_count == 2
        assert len(result.skipped_files or []) == 2
        assert "could not be accessed" in (result.warning_message or "")

    def test_e2e_parse_all_files_failed_is_error(self, e2e_env):
        """
        E2E Test: Exit code 2 with zero scanned files is an error, not a clean scan.

        Steps:
        1. Feed stdout where every file failed to open (Scanned files: 0).
        2. Parse with exit code 2.
        3. Verify ERROR status with a specific message instead of a green result.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        warning_output = """/root/secret1: Failed to open file ERROR
/root/secret2: Failed to open file ERROR

----------- SCAN SUMMARY -----------
Scanned directories: 1
Scanned files: 0
Infected files: 0
"""

        result = scanner._parse_results(str(e2e_env["scan_dir"]), warning_output, "", 2)

        assert result.status == ScanStatus.ERROR
        assert "No files could be scanned" in (result.error_message or "")


class TestE2EScanLogging:
    """E2E tests for scan to log integration."""

    def test_e2e_scan_creates_logs_and_supports_retrieval_filter_and_export(self, e2e_env):
        """
        E2E Test: Scan stores log entry and supports retrieval/filter/export.

        Steps:
        1. Execute clean scan through Scanner with LogManager attached.
        2. Retrieve scan logs through log manager filtering.
        3. Export logs to CSV and JSON and verify key output fields.
        """
        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=e2e_env["settings"])
        process = _make_process(CLEAN_SCAN_OUTPUT, "", 0)

        with mock.patch(
            "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
        ):
            with mock.patch(
                "src.core.scanner.check_clamd_connection", return_value=(False, "not available")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process):
                                    result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert result.status == ScanStatus.CLEAN

        scan_logs = e2e_env["log_manager"].get_logs(log_type="scan")
        assert len(scan_logs) >= 1
        assert scan_logs[0].type == "scan"

        csv_output = e2e_env["log_manager"].export_logs_to_csv(scan_logs)
        json_output = e2e_env["log_manager"].export_logs_to_json(scan_logs)
        parsed_json = json.loads(json_output)

        assert "id,timestamp,type,status,path,summary,duration,scheduled" in csv_output
        assert parsed_json["count"] == len(scan_logs)
        assert parsed_json["entries"][0]["type"] == "scan"

    def test_e2e_logentry_from_scan_result_data_clean_and_infected(self, e2e_env):
        """
        E2E Test: Build clean and infected LogEntry objects from scan result data.

        Steps:
        1. Create clean and infected entries via from_scan_result_data factory.
        2. Persist both entries and retrieve them through LogManager.
        3. Verify threat details and scheduled flag are preserved in log details.
        """
        clean_entry = LogEntry.from_scan_result_data(
            scan_status="clean",
            path=str(e2e_env["scan_dir"]),
            duration=1.2,
            scanned_files=2,
            scanned_dirs=1,
            infected_count=0,
            threat_details=[],
            stdout=CLEAN_SCAN_OUTPUT,
        )
        infected_entry = LogEntry.from_scan_result_data(
            scan_status="infected",
            path=str(e2e_env["scan_dir"]),
            duration=2.4,
            scanned_files=5,
            scanned_dirs=1,
            infected_count=2,
            threat_details=[
                {
                    "file_path": str(e2e_env["scan_dir"] / "malware.exe"),
                    "threat_name": "Win.Trojan.Agent-12345",
                }
            ],
            stdout=INFECTED_SCAN_OUTPUT,
            scheduled=True,
        )

        assert clean_entry.status == "clean"
        assert infected_entry.status == "infected"
        assert infected_entry.scheduled is True

        e2e_env["log_manager"].save_log(clean_entry)
        e2e_env["log_manager"].save_log(infected_entry)

        logs = e2e_env["log_manager"].get_logs(log_type="scan")
        assert len(logs) >= 2

        infected_logs = [entry for entry in logs if entry.status == "infected"]
        assert infected_logs
        assert "Threats found" in infected_logs[0].details
        assert "Win.Trojan.Agent-12345" in infected_logs[0].details


class TestE2EFullScanWorkflow:
    """E2E tests for full configuration to scan to logging workflow."""

    def test_e2e_full_scan_configuration_execution_results_and_logging(self, e2e_env):
        """
        E2E Test: Complete scan workflow from settings to execution to logs.

        Steps:
        1. Configure backend and exclusions in settings manager.
        2. Execute scan over real temp files with mocked subprocess only.
        3. Verify scan result, stored logs, and scheduled flag log entry path.
        """
        settings = e2e_env["settings"]
        settings.set("scan_backend", "clamscan")
        settings.set(
            "exclusion_patterns",
            [{"pattern": "*.tmp", "type": "pattern", "enabled": True}],
        )

        scanner = Scanner(log_manager=e2e_env["log_manager"], settings_manager=settings)
        process = _make_process(CLEAN_SCAN_OUTPUT, "", 0)

        with mock.patch(
            "src.core.scanner.check_clamav_installed", return_value=(True, "ClamAV 1.0.0")
        ):
            with mock.patch(
                "src.core.scanner.check_clamd_connection", return_value=(False, "not available")
            ):
                with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda cmd: cmd):
                    with mock.patch(
                        "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                    ):
                        with mock.patch(
                            "src.core.scanner.validate_path", return_value=(True, None)
                        ):
                            with mock.patch("src.core.scanner.get_clean_env", return_value={}):
                                with mock.patch("subprocess.Popen", return_value=process) as popen:
                                    result = scanner.scan_sync(str(e2e_env["scan_dir"]))

        assert result.status == ScanStatus.CLEAN
        assert result.path == str(e2e_env["scan_dir"])

        cmd = popen.call_args[0][0]
        assert glob_to_regex("*.tmp") in cmd

        logs = e2e_env["log_manager"].get_logs(log_type="scan")
        assert logs
        assert logs[0].status in {"clean", "infected", "error", "cancelled"}

        scheduled_entry = LogEntry.from_scan_result_data(
            scan_status=result.status.value,
            path=result.path,
            duration=1.0,
            scanned_files=result.scanned_files,
            scanned_dirs=result.scanned_dirs,
            infected_count=result.infected_count,
            threat_details=[
                {"file_path": threat.file_path, "threat_name": threat.threat_name}
                for threat in result.threat_details
            ],
            stdout=result.stdout,
            scheduled=True,
        )
        e2e_env["log_manager"].save_log(scheduled_entry)

        refreshed_logs = e2e_env["log_manager"].get_logs(log_type="scan")
        assert any(entry.scheduled for entry in refreshed_logs)
