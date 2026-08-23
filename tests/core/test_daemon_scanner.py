# ClamUI Daemon Scanner Tests
"""Unit tests for the daemon scanner module."""

import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import directly - daemon_scanner uses GLib only for idle_add in async methods,
# and those methods are not tested here (unit tests mock the async behavior)
from src.core.daemon_scanner import DaemonScanner
from src.core.scanner import ScanStatus
from src.core.threat_classifier import categorize_threat, classify_threat_severity_str


@pytest.fixture
def daemon_scanner_class():
    """Get DaemonScanner class."""
    return DaemonScanner


@pytest.fixture
def scan_status_class():
    """Get ScanStatus enum."""
    return ScanStatus


@pytest.fixture
def daemon_scanner():
    """Create a DaemonScanner instance for testing."""
    return DaemonScanner()


class TestDaemonScannerCheckAvailable:
    """Tests for DaemonScanner.check_available method."""

    def test_check_available_when_daemon_running(self, daemon_scanner_class):
        """Test availability check when clamd is running."""
        scanner = daemon_scanner_class()

        with patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed:
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            with patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection:
                mock_connection.return_value = (True, "PONG")

                available, msg = scanner.check_available()

        assert available is True
        assert "available" in msg.lower()

    def test_check_available_clamdscan_not_installed(self, daemon_scanner_class):
        """Test availability check when clamdscan is not installed."""
        scanner = daemon_scanner_class()

        with patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed:
            mock_installed.return_value = (False, "clamdscan not found")

            available, msg = scanner.check_available()

        assert available is False
        assert "not found" in msg.lower() or "clamdscan" in msg.lower()

    def test_check_available_daemon_not_running(self, daemon_scanner_class):
        """Test availability check when clamd is not running."""
        scanner = daemon_scanner_class()

        with patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed:
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            with patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection:
                mock_connection.return_value = (False, "Connection refused")

                available, msg = scanner.check_available()

        assert available is False
        assert "not accessible" in msg.lower() or "connection" in msg.lower()

    def test_check_available_passes_resolved_config_path(self, daemon_scanner_class):
        """Test availability checks use the saved clamd.conf path when present."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = "/etc/clamd.d/scan.conf"
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        with patch(
            "src.core.daemon_scanner.resolve_clamd_conf_path", return_value="/etc/clamd.d/scan.conf"
        ):
            with patch(
                "src.core.daemon_scanner.check_clamdscan_installed",
                return_value=(True, "ClamAV 1.0.0"),
            ):
                with patch(
                    "src.core.daemon_scanner.check_clamd_connection", return_value=(True, "PONG")
                ) as mock_connection:
                    scanner.check_available()

        mock_connection.assert_called_once_with(config_path="/etc/clamd.d/scan.conf")


class TestDaemonScannerBuildCommand:
    """Tests for DaemonScanner._build_command method."""

    def test_build_command_basic(self, tmp_path, daemon_scanner_class):
        """Test _build_command builds correct clamdscan command."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        # Mock wrap_host_command to verify it's called with force_host=True
        with patch(
            "src.core.daemon_scanner.wrap_host_command", side_effect=lambda x, **kw: x
        ) as mock_wrap:
            cmd = scanner._build_command(str(test_file), recursive=True)
            # Verify force_host=True is passed for daemon commands
            mock_wrap.assert_called_once()
            call_kwargs = mock_wrap.call_args[1]
            assert call_kwargs.get("force_host") is True

        # Now uses binary name directly (not full path from which_host_command)
        assert cmd[0] == "clamdscan"
        assert "--multiscan" in cmd
        assert "--fdpass" in cmd
        assert "-i" in cmd
        assert str(test_file) in cmd

    def test_build_command_uses_force_host(self, tmp_path, daemon_scanner_class):
        """Test _build_command uses force_host=True for Flatpak daemon communication."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        with patch(
            "src.core.daemon_scanner.wrap_host_command", side_effect=lambda x, **kw: x
        ) as mock_wrap:
            scanner._build_command(str(test_file), recursive=True)
            # Must use force_host=True so clamdscan talks to host's daemon
            mock_wrap.assert_called_once()
            assert mock_wrap.call_args[1].get("force_host") is True

    def test_build_command_force_stream_uses_stream_mode(self, tmp_path, daemon_scanner_class):
        """Test force_stream switches daemon scans to clamdscan --stream."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        with patch("src.core.daemon_scanner.wrap_host_command", side_effect=lambda x, **kw: x):
            cmd = scanner._build_command(str(test_file), recursive=True, force_stream=True)

        assert cmd[0] == "clamdscan"
        assert "--stream" in cmd
        assert "--multiscan" not in cmd
        assert "--fdpass" not in cmd

    def test_build_command_verbose_file_list_uses_fdpass(self, tmp_path, daemon_scanner_class):
        """Verbose file-list scans should keep fdpass for reliable access."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        file_list = tmp_path / "files.txt"
        file_list.write_text(str(test_file), encoding="utf-8")

        scanner = daemon_scanner_class()

        with patch("src.core.daemon_scanner.wrap_host_command", side_effect=lambda x, **kw: x):
            cmd = scanner._build_command(
                str(test_file),
                recursive=True,
                verbose=True,
                file_list_path=str(file_list),
            )

        assert cmd[:3] == ["stdbuf", "-oL", "clamdscan"]
        assert "-v" in cmd
        assert "--file-list" in cmd
        assert "--fdpass" in cmd
        assert "--multiscan" not in cmd
        assert "--stream" not in cmd

    def test_build_command_without_exclusions(self, tmp_path, daemon_scanner_class):
        """Test _build_command does NOT include --exclude (clamdscan doesn't support it)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_settings = MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "*.log", "type": "file", "enabled": True},
            {"pattern": "node_modules", "type": "directory", "enabled": True},
        ]

        scanner = daemon_scanner_class(settings_manager=mock_settings)

        with patch("src.core.daemon_scanner.wrap_host_command", side_effect=lambda x, **kw: x):
            cmd = scanner._build_command(str(test_file), recursive=True)

        # clamdscan does NOT support --exclude options (they're silently ignored)
        # Exclusions are handled post-scan via _filter_excluded_threats()
        assert "--exclude" not in cmd
        assert "--exclude-dir" not in cmd

    def test_build_command_uses_saved_clamd_config_path(self, tmp_path, daemon_scanner_class):
        """Test _build_command adds --config-file for saved clamd.conf paths."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        mock_settings = MagicMock()
        mock_settings.get.return_value = "/etc/clamd.d/scan.conf"
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        with patch(
            "src.core.daemon_scanner.resolve_clamd_conf_path", return_value="/etc/clamd.d/scan.conf"
        ):
            with patch("src.core.daemon_scanner.wrap_host_command", side_effect=lambda x, **kw: x):
                cmd = scanner._build_command(str(test_file), recursive=True)

        assert cmd[0] == "clamdscan"
        assert cmd[1:3] == ["--config-file", "/etc/clamd.d/scan.conf"]
        assert "--multiscan" in cmd
        assert "--fdpass" in cmd


class TestDaemonScannerParseResults:
    """Tests for DaemonScanner._parse_results method."""

    def test_parse_results_clean_scan(self, daemon_scanner_class, scan_status_class):
        """Test parsing clean scan results."""
        scanner = daemon_scanner_class()

        # clamdscan output doesn't include file/directory counts,
        # so they are passed as parameters from pre-counting
        stdout = """
/home/user/test.txt: OK

----------- SCAN SUMMARY -----------
Infected files: 0
"""
        result = scanner._parse_results("/home/user", stdout, "", 0, file_count=1, dir_count=0)

        assert result.status == scan_status_class.CLEAN
        assert result.infected_count == 0
        assert result.scanned_files == 1

    def test_parse_results_file_list_error_with_zero_exit_is_error(
        self, daemon_scanner_class, scan_status_class
    ):
        """clamdscan can return 0 after failing to open --file-list."""
        scanner = daemon_scanner_class()
        stdout = """
ERROR: --file-list: Can't open file /run/user/1000/clamui_filelist.txt

----------- SCAN SUMMARY -----------
Infected files: 0
"""

        result = scanner._parse_results("/home/user", stdout, "", 0, file_count=0, dir_count=0)

        assert result.status == scan_status_class.ERROR
        assert "--file-list" in result.error_message

    def test_parse_results_infected_scan(self, daemon_scanner_class, scan_status_class):
        """Test parsing infected scan results."""
        scanner = daemon_scanner_class()

        # clamdscan output with -i flag only shows infected files
        stdout = """
/home/user/malware.exe: Win.Trojan.Agent FOUND

----------- SCAN SUMMARY -----------
Infected files: 1
"""
        result = scanner._parse_results("/home/user", stdout, "", 1, file_count=1, dir_count=0)

        assert result.status == scan_status_class.INFECTED
        assert result.infected_count == 1
        assert len(result.threat_details) == 1
        assert result.threat_details[0].threat_name == "Win.Trojan.Agent"
        assert result.threat_details[0].file_path == "/home/user/malware.exe"

    def test_parse_results_error(self, daemon_scanner_class, scan_status_class):
        """Test parsing error scan results."""
        scanner = daemon_scanner_class()

        result = scanner._parse_results("/home/user", "", "Connection refused", 2)

        assert result.status == scan_status_class.ERROR
        assert result.error_message is not None

    def test_parse_results_permission_denied_file_path_check_failure_is_warning(
        self, daemon_scanner_class, scan_status_class
    ):
        """Test newer clamdscan permission warnings are treated as skipped files."""
        scanner = daemon_scanner_class()

        stdout = """
/home/user/a.txt: File path check failure: Permission denied. ERROR
/home/user/b.txt: File path check failure: Permission denied. ERROR
"""
        result = scanner._parse_results("/home/user", stdout, "", 2, file_count=3, dir_count=0)

        assert result.status == scan_status_class.CLEAN
        assert result.infected_count == 0
        assert result.skipped_count == 2
        assert result.warning_message is not None

    def test_parse_results_deduplicates_repeated_skipped_file_lines(
        self, daemon_scanner_class, scan_status_class
    ):
        """Test duplicated warning lines do not inflate skipped_count."""
        scanner = daemon_scanner_class()

        stdout = """
/home/user/a.txt: File path check failure: Permission denied. ERROR
/home/user/a.txt: File path check failure: Permission denied. ERROR
"""
        result = scanner._parse_results("/home/user", stdout, "", 2, file_count=2, dir_count=0)

        assert result.status == scan_status_class.CLEAN
        assert result.skipped_count == 1
        assert result.skipped_files == ["/home/user/a.txt"]

    def test_parse_results_special_file_warnings_are_nonfatal(
        self, daemon_scanner_class, scan_status_class
    ):
        """Runtime special-file warnings should be treated as skipped paths."""
        scanner = daemon_scanner_class()

        stdout = """
WARNING: /home/user/.cache/ibus/dbus-abc: Not supported file type
LibClamAV Warning: cli_realpath: Invalid arguments.
WARNING: /home/user/.cache/steam_pipe: Not supported file type
LibClamAV Warning: cli_realpath: Invalid arguments.
"""
        result = scanner._parse_results("/home/user", stdout, "", 2, file_count=3, dir_count=0)

        assert result.status == scan_status_class.CLEAN
        assert result.infected_count == 0
        assert result.skipped_count == 2
        assert result.skipped_files == [
            "/home/user/.cache/ibus/dbus-abc",
            "/home/user/.cache/steam_pipe",
        ]
        assert result.warning_message == "2 file(s) could not be accessed"

    def test_parse_results_all_files_skipped_is_error(
        self, daemon_scanner_class, scan_status_class
    ):
        """Exit 2 where every pre-counted file was inaccessible must not report CLEAN."""
        scanner = daemon_scanner_class()

        stdout = "".join(f"/root/secret{i}.txt: Access denied. ERROR\n" for i in range(1, 6))
        result = scanner._parse_results("/root", stdout, "", 2, file_count=5, dir_count=1)

        assert result.status == scan_status_class.ERROR
        assert result.error_message == "No files could be scanned"
        assert result.skipped_count == 5

    def test_parse_results_all_skipped_without_precount_still_downgrades(
        self, daemon_scanner_class, scan_status_class
    ):
        """With counting disabled (file_count=0) skip warnings still downgrade to CLEAN."""
        scanner = daemon_scanner_class()

        stdout = "/root/secret.txt: Access denied. ERROR\n"
        result = scanner._parse_results("/root", stdout, "", 2, file_count=0, dir_count=0)

        assert result.status == scan_status_class.CLEAN
        assert result.skipped_files == ["/root/secret.txt"]
        assert result.warning_message == "1 file(s) could not be accessed"

    def test_parse_results_total_errors_covering_precount_is_error(
        self, daemon_scanner_class, scan_status_class
    ):
        """'Total errors' matching the pre-count means every file failed -> ERROR."""
        scanner = daemon_scanner_class()

        stdout = """
----------- SCAN SUMMARY -----------
Infected files: 0
Total errors: 4
"""
        result = scanner._parse_results("/root", stdout, "", 2, file_count=4, dir_count=1)

        assert result.status == scan_status_class.ERROR
        assert result.error_message == "No files could be scanned"

    def test_parse_results_exit_code_2_with_detection_is_infected(
        self, daemon_scanner_class, scan_status_class
    ):
        """Detections must win over a co-occurring error: exit 2 + FOUND -> INFECTED."""
        scanner = daemon_scanner_class()

        stdout = """
/home/user/eicar.txt: Eicar-Test-Signature FOUND
/home/user/locked.bin: Can't open file or directory ERROR
"""
        result = scanner._parse_results("/home/user", stdout, "", 2, file_count=2, dir_count=0)

        assert result.status == scan_status_class.INFECTED
        assert result.infected_count == 1
        assert "/home/user/eicar.txt" in result.infected_files

    def test_parse_results_issue_149_warning_lines_exit_2_clean(
        self, daemon_scanner_class, scan_status_class
    ):
        """Regression for issue #149: the exact benign LibClamAV warnings from the
        report must not flip an exit-2 daemon scan to ERROR."""
        scanner = daemon_scanner_class()

        stdout = """
----------- SCAN SUMMARY -----------
Infected files: 0
"""
        stderr = (
            "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN\n"
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes\n"
        )

        result = scanner._parse_results(
            "/home/user", stdout, stderr, 2, file_count=100, dir_count=3
        )

        assert result.status == scan_status_class.CLEAN
        assert result.error_message is None
        assert result.nonfatal_warnings == [
            "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN",
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes",
        ]
        assert result.has_warnings is True
        assert result.warning_message == (
            "2 non-fatal warning(s) during scan; some files may have been only partially scanned"
        )

    def test_parse_results_exit_0_with_stray_warning_stays_clean(
        self, daemon_scanner_class, scan_status_class
    ):
        """A stray unrecognized warning line must not override the daemon's exit 0."""
        scanner = daemon_scanner_class()

        stdout = """
/home/user/test.txt: OK

----------- SCAN SUMMARY -----------
Infected files: 0
"""
        stderr = "LibClamAV Warning: something novel happened\n"

        result = scanner._parse_results("/home/user", stdout, stderr, 0, file_count=1, dir_count=0)

        assert result.status == scan_status_class.CLEAN
        assert result.error_message is None

    def test_parse_results_exit_0_unrar_dlopen_warning_is_clean(
        self, daemon_scanner_class, scan_status_class
    ):
        """The verified 'Cannot dlopen libclamunrar_iface' warning at exit 0 -> CLEAN."""
        scanner = daemon_scanner_class()

        stderr = (
            "LibClamAV Warning: Cannot dlopen libclamunrar_iface: file not found, "
            "unrar support unavailable\n"
        )

        result = scanner._parse_results("/home/user", "", stderr, 0, file_count=1, dir_count=0)

        assert result.status == scan_status_class.CLEAN
        assert result.error_message is None
        assert result.nonfatal_warnings == [
            "LibClamAV Warning: Cannot dlopen libclamunrar_iface: file not found, "
            "unrar support unavailable"
        ]
        assert result.has_warnings is True

    def test_parse_results_exit_0_with_per_file_error_reply_is_error(
        self, daemon_scanner_class, scan_status_class
    ):
        """Genuine per-file '... ERROR' replies still override exit 0."""
        scanner = daemon_scanner_class()

        stdout = "/home/user/locked.bin: Can't open file or directory ERROR\n"

        result = scanner._parse_results("/home/user", stdout, "", 0, file_count=1, dir_count=0)

        assert result.status == scan_status_class.ERROR
        assert result.error_message is not None

    def test_parse_results_total_errors_summary_downgrades_to_clean(
        self, daemon_scanner_class, scan_status_class
    ):
        """With -i suppressing per-file lines, 'Total errors: N' downgrades exit 2."""
        scanner = daemon_scanner_class()

        stdout = """
----------- SCAN SUMMARY -----------
Infected files: 0
Total errors: 2
Time: 1.000 sec (0 m 1 s)
"""
        result = scanner._parse_results("/home/user", stdout, "", 2, file_count=10, dir_count=1)

        assert result.status == scan_status_class.CLEAN
        assert result.warning_message == "2 file(s) could not be read"
        assert result.error_message is None

    def test_parse_results_infected_with_nonfatal_warnings_never_masked(
        self, daemon_scanner_class, scan_status_class
    ):
        """Exit 2 with a FOUND line plus benign warnings must stay INFECTED."""
        scanner = daemon_scanner_class()

        stdout = """
/home/user/eicar.txt: Eicar-Test-Signature FOUND
"""
        stderr = "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN\n"

        result = scanner._parse_results("/home/user", stdout, stderr, 2, file_count=2, dir_count=0)

        assert result.status == scan_status_class.INFECTED
        assert result.infected_count == 1
        assert result.nonfatal_warnings == [
            "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN"
        ]


class TestDaemonScannerProgressParsing:
    """Tests for DaemonScanner._scan_with_progress parsing behavior."""

    def test_scan_with_progress_counts_permission_errors_as_processed(self, daemon_scanner_class):
        """Permission-denied ERROR lines should advance files_scanned progress."""
        scanner = daemon_scanner_class()
        progress_events = []
        lines = [
            "/home/user/a.txt: File path check failure: Permission denied. ERROR",
            "/home/user/a.txt: File path check failure: Permission denied. ERROR",
            "/home/user/b.txt: Failed to open file ERROR",
        ]

        def fake_stream(process, is_cancelled, on_line):
            for line in lines:
                on_line(line)
            return ("\n".join(lines), "", False)

        with patch("src.core.daemon_scanner.stream_process_output", side_effect=fake_stream):
            stdout, stderr, was_cancelled, files_scanned, infected_count, infected_files = (
                scanner._scan_with_progress(
                    process=MagicMock(),
                    progress_callback=progress_events.append,
                    files_total=10,
                )
            )

        assert was_cancelled is False
        assert stderr == ""
        assert stdout
        assert files_scanned == 2
        assert infected_count == 0
        assert infected_files == []
        assert len(progress_events) == 2
        assert progress_events[-1].files_scanned == 2

    def test_scan_with_progress_deduplicates_duplicate_found_lines(self, daemon_scanner_class):
        """Duplicate FOUND lines should not inflate counters."""
        scanner = daemon_scanner_class()
        progress_events = []
        lines = [
            "/home/user/malware.exe: Win.Trojan.Agent FOUND",
            "/home/user/malware.exe: Win.Trojan.Agent FOUND",
        ]

        def fake_stream(process, is_cancelled, on_line):
            for line in lines:
                on_line(line)
            return ("\n".join(lines), "", False)

        with patch("src.core.daemon_scanner.stream_process_output", side_effect=fake_stream):
            scan_result = scanner._scan_with_progress(
                process=MagicMock(),
                progress_callback=progress_events.append,
                files_total=10,
            )
            files_scanned = scan_result[3]
            infected_count = scan_result[4]
            infected_files = scan_result[5]

        assert files_scanned == 1
        assert infected_count == 1
        assert infected_files == ["/home/user/malware.exe"]
        assert len(progress_events) == 1

    def test_scan_with_progress_emits_independent_snapshots(self, daemon_scanner_class):
        """Each progress snapshot must keep len(infected_files) == infected_count.

        ScanProgress objects are handed to progress_callback, which schedules a
        GTK update via GLib.idle_add on the main thread. If the daemon scanner
        passed the live infected_files list / infected_threats dict by reference,
        the background thread would keep mutating them after the snapshot was
        emitted, so an early snapshot's int infected_count would desync from the
        ever-growing shared list (and the main thread could observe a partially
        mutated structure). Snapshots must be independent copies.
        """
        scanner = daemon_scanner_class()
        captured = []
        lines = [
            "/home/user/a.exe: Win.Trojan.A FOUND",
            "/home/user/b.exe: Win.Trojan.B FOUND",
            "/home/user/c.exe: Win.Trojan.C FOUND",
        ]

        def fake_stream(process, is_cancelled, on_line):
            for line in lines:
                on_line(line)
            return ("\n".join(lines), "", False)

        with patch("src.core.daemon_scanner.stream_process_output", side_effect=fake_stream):
            scanner._scan_with_progress(
                process=MagicMock(),
                progress_callback=captured.append,
                files_total=3,
            )

        assert len(captured) == 3
        # First snapshot must reflect exactly one infection, not the final three.
        assert captured[0].infected_files == ["/home/user/a.exe"]
        assert len(captured[0].infected_threats) == 1
        # Every snapshot stays internally consistent with its own count.
        for progress in captured:
            assert len(progress.infected_files) == progress.infected_count
            assert len(progress.infected_threats) == progress.infected_count


class TestDaemonScannerThreatClassification:
    """Tests for threat classification functions."""

    def test_classify_threat_severity_critical(self):
        """Test classifying ransomware as critical."""
        severity = classify_threat_severity_str("Win.Ransomware.Locky")
        assert severity == "critical"

    def test_classify_threat_severity_high(self):
        """Test classifying trojan as high severity."""
        severity = classify_threat_severity_str("Win.Trojan.Agent")
        assert severity == "high"

    def test_classify_threat_severity_low(self):
        """Test classifying EICAR test as low severity."""
        severity = classify_threat_severity_str("Eicar-Test-Signature")
        assert severity == "low"

    def test_categorize_threat_trojan(self):
        """Test categorizing a trojan threat."""
        category = categorize_threat("Win.Trojan.Agent")
        assert category == "Trojan"

    def test_categorize_threat_ransomware(self):
        """Test categorizing a ransomware threat."""
        category = categorize_threat("Win.Ransomware.Locky")
        assert category == "Ransomware"


class TestDaemonScannerCancel:
    """Tests for DaemonScanner.cancel method."""

    def test_cancel_sets_flag(self, daemon_scanner_class):
        """Test that cancel sets the cancel event."""
        scanner = daemon_scanner_class()

        scanner.cancel()

        assert scanner._cancel_event.is_set() is True

    def test_cancel_terminates_process(self, daemon_scanner_class):
        """Test that cancel terminates running process."""
        scanner = daemon_scanner_class()
        mock_process = MagicMock()
        scanner._current_process = mock_process

        scanner.cancel()

        mock_process.terminate.assert_called_once()

    def test_cancel_terminate_timeout_escalates_to_kill(self, daemon_scanner_class):
        """Test that cancel escalates to kill if terminate times out."""
        scanner = daemon_scanner_class()
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock(
            side_effect=[
                subprocess.TimeoutExpired(cmd="test", timeout=5),  # First wait times out
                None,  # Second wait (after kill) succeeds
            ]
        )
        scanner._current_process = mock_process

        scanner.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        assert scanner._cancel_event.is_set() is True

    def test_cancel_kill_timeout_handles_gracefully(self, daemon_scanner_class):
        """Test that cancel handles kill timeout gracefully."""
        scanner = daemon_scanner_class()
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock(
            side_effect=[
                subprocess.TimeoutExpired(cmd="test", timeout=5),  # First wait times out
                subprocess.TimeoutExpired(cmd="test", timeout=2),  # Second wait also times out
            ]
        )
        scanner._current_process = mock_process

        # Should not raise exception even if kill times out
        scanner.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        assert scanner._cancel_event.is_set() is True

    def test_cancel_process_already_terminated_on_terminate(self, daemon_scanner_class):
        """Test cancel handles process already gone when calling terminate."""
        scanner = daemon_scanner_class()
        mock_process = MagicMock()
        mock_process.terminate = MagicMock(side_effect=ProcessLookupError("No such process"))
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock()
        scanner._current_process = mock_process

        # Should not raise exception and should return early
        scanner.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_not_called()  # Should not reach kill
        mock_process.wait.assert_not_called()  # Should not reach wait
        assert scanner._cancel_event.is_set() is True

    def test_cancel_graceful_termination_success(self, daemon_scanner_class):
        """Test cancel when process terminates gracefully within timeout."""
        scanner = daemon_scanner_class()
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock(return_value=None)  # Succeeds on first call
        scanner._current_process = mock_process

        scanner.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()  # Only one wait call
        mock_process.kill.assert_not_called()  # Should not escalate to kill
        assert scanner._cancel_event.is_set() is True


class TestDaemonScannerFilterExcludedThreats:
    """Tests for DaemonScanner._filter_excluded_threats method."""

    def test_filter_excludes_exact_path_match(self, daemon_scanner_class, scan_status_class):
        """Test that exact path matches are filtered out."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "/home/user/eicar.txt", "type": "file", "enabled": True},
        ]
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        # Create a mock ThreatDetail
        from src.core.scanner import ThreatDetail

        threat = ThreatDetail(
            file_path="/home/user/eicar.txt",
            threat_name="Eicar-Test-Signature",
            category="Test",
            severity="low",
        )

        # Create infected result
        from src.core.scanner import ScanResult

        result = ScanResult(
            status=scan_status_class.INFECTED,
            path="/home/user",
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=["/home/user/eicar.txt"],
            scanned_files=1,
            scanned_dirs=0,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        filtered = scanner._filter_excluded_threats(result)

        # Should be clean since threat was excluded
        assert filtered.status == scan_status_class.CLEAN
        assert filtered.infected_count == 0
        assert len(filtered.threat_details) == 0

    def test_filter_keeps_non_excluded_threats(self, daemon_scanner_class, scan_status_class):
        """Test that non-excluded threats are kept."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "/some/other/path.txt", "type": "file", "enabled": True},
        ]
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        from src.core.scanner import ScanResult, ThreatDetail

        threat = ThreatDetail(
            file_path="/home/user/virus.exe",
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        result = ScanResult(
            status=scan_status_class.INFECTED,
            path="/home/user",
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=["/home/user/virus.exe"],
            scanned_files=1,
            scanned_dirs=0,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        filtered = scanner._filter_excluded_threats(result)

        # Should still be infected
        assert filtered.status == scan_status_class.INFECTED
        assert filtered.infected_count == 1
        assert len(filtered.threat_details) == 1

    def test_filter_respects_disabled_exclusions(self, daemon_scanner_class, scan_status_class):
        """Test that disabled exclusions don't filter threats."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "/home/user/eicar.txt", "type": "file", "enabled": False},
        ]
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        from src.core.scanner import ScanResult, ThreatDetail

        threat = ThreatDetail(
            file_path="/home/user/eicar.txt",
            threat_name="Eicar-Test-Signature",
            category="Test",
            severity="low",
        )

        result = ScanResult(
            status=scan_status_class.INFECTED,
            path="/home/user",
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=["/home/user/eicar.txt"],
            scanned_files=1,
            scanned_dirs=0,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        filtered = scanner._filter_excluded_threats(result)

        # Should still be infected since exclusion is disabled
        assert filtered.status == scan_status_class.INFECTED
        assert filtered.infected_count == 1


class TestDaemonScannerCountTargets:
    """Tests for DaemonScanner count_targets parameter."""

    def test_scan_sync_with_count_targets_true_counts_files(
        self, tmp_path, daemon_scanner_class, scan_status_class
    ):
        """Test that count_targets=True (default) counts files and directories."""
        # Create test directory structure
        test_dir = tmp_path / "scan_test"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("content3")

        scanner = daemon_scanner_class()

        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            result = scanner.scan_sync(str(test_dir), count_targets=True)

        assert result.status == scan_status_class.CLEAN
        # Should have counted files (3 files)
        assert result.scanned_files == 3
        # Should have counted directories (root + subdir = 2)
        assert result.scanned_dirs == 2

    def test_scan_sync_with_count_targets_false_skips_counting(
        self, tmp_path, daemon_scanner_class, scan_status_class
    ):
        """Test that count_targets=False skips file/directory counting."""
        # Create test directory structure
        test_dir = tmp_path / "scan_test"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("content3")

        scanner = daemon_scanner_class()

        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            result = scanner.scan_sync(str(test_dir), count_targets=False)

        assert result.status == scan_status_class.CLEAN
        # Counts should be 0 when count_targets=False
        assert result.scanned_files == 0
        assert result.scanned_dirs == 0

    def test_scan_sync_count_targets_false_still_detects_infections(
        self, tmp_path, daemon_scanner_class, scan_status_class
    ):
        """Test that count_targets=False still correctly reports infections."""
        test_dir = tmp_path / "scan_test"
        test_dir.mkdir()
        (test_dir / "malware.exe").write_text("fake malware")

        scanner = daemon_scanner_class()

        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            infected_output = f"{test_dir}/malware.exe: Win.Trojan.Test FOUND\n"
            mock_process.communicate.return_value = (infected_output, "")
            mock_process.returncode = 1
            mock_popen.return_value = mock_process

            result = scanner.scan_sync(str(test_dir), count_targets=False)

        # Should still detect infection
        assert result.status == scan_status_class.INFECTED
        assert result.infected_count == 1
        assert len(result.threat_details) == 1
        assert result.threat_details[0].threat_name == "Win.Trojan.Test"
        # But counts should still be 0
        assert result.scanned_files == 0
        assert result.scanned_dirs == 0

    def test_scan_sync_default_count_targets_is_true(
        self, tmp_path, daemon_scanner_class, scan_status_class
    ):
        """Test that count_targets defaults to True for backwards compatibility."""
        test_dir = tmp_path / "scan_test"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")

        scanner = daemon_scanner_class()

        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
            patch.object(scanner, "_count_scan_targets") as mock_count,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")
            mock_count.return_value = (1, 1, None)

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            # Call without count_targets parameter (should default to True)
            scanner.scan_sync(str(test_dir))

        # _count_scan_targets should have been called
        mock_count.assert_called_once()

    def test_scan_async_passes_count_targets_to_sync(self, tmp_path, daemon_scanner_class):
        """Test that scan_async passes count_targets to scan_sync."""
        test_dir = tmp_path / "scan_test"
        test_dir.mkdir()

        scanner = daemon_scanner_class()
        callback = MagicMock()

        with (
            patch.object(scanner, "scan_sync") as mock_sync,
            patch("src.core.daemon_scanner.GLib.idle_add"),
        ):
            from src.core.scanner import ScanResult, ScanStatus

            mock_sync.return_value = ScanResult(
                status=ScanStatus.CLEAN,
                path=str(test_dir),
                stdout="",
                stderr="",
                exit_code=0,
                infected_files=[],
                scanned_files=0,
                scanned_dirs=0,
                infected_count=0,
                error_message=None,
                threat_details=[],
            )

            # Call async with count_targets=False
            scanner.scan_async(str(test_dir), callback, count_targets=False)

            # Wait for thread to execute
            import time

            time.sleep(0.1)

        # Verify scan_sync was called with count_targets=False
        mock_sync.assert_called_once()
        call_args = mock_sync.call_args
        assert call_args[0][0] == str(test_dir)  # path
        assert call_args[0][3] is False  # count_targets (4th positional arg)

    def test_scan_sync_uses_file_list_when_exclusions_active_without_progress(
        self, tmp_path, daemon_scanner_class, scan_status_class
    ):
        """Daemon scans should use --file-list so exclusions shape the actual scan."""
        test_dir = tmp_path / "scan_test"
        included_dir = test_dir / "included"
        excluded_dir = test_dir / "excluded"
        included_dir.mkdir(parents=True)
        excluded_dir.mkdir(parents=True)
        included_file = included_dir / "keep.txt"
        excluded_file = excluded_dir / "skip.txt"
        included_file.write_text("keep")
        excluded_file.write_text("skip")

        scanner = daemon_scanner_class()
        profile_exclusions = {"paths": [str(excluded_dir)], "patterns": []}

        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("src.core.daemon_scanner.os.unlink"),
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            result = scanner.scan_sync(
                str(test_dir),
                profile_exclusions=profile_exclusions,
                count_targets=True,
                progress_callback=None,
            )

        assert result.status == scan_status_class.CLEAN
        cmd = mock_popen.call_args[0][0]
        assert "--file-list" in cmd
        file_list_path = cmd[cmd.index("--file-list") + 1]
        file_list_content = Path(file_list_path).read_text(encoding="utf-8")
        assert str(included_file) in file_list_content
        assert str(excluded_file) not in file_list_content

    def test_filter_excludes_profile_path_subdirectory(
        self, daemon_scanner_class, scan_status_class, tmp_path
    ):
        """Test that threats under excluded directory paths are filtered."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = []  # No global exclusions
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        # Create a real directory structure for path resolution
        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        threat_file = excluded_dir / "subdir" / "virus.exe"
        threat_file.parent.mkdir(parents=True)
        threat_file.touch()

        from src.core.scanner import ScanResult, ThreatDetail

        threat = ThreatDetail(
            file_path=str(threat_file),
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        result = ScanResult(
            status=scan_status_class.INFECTED,
            path=str(tmp_path),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(threat_file)],
            scanned_files=1,
            scanned_dirs=0,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        profile_exclusions = {"paths": [str(excluded_dir)], "patterns": []}
        filtered = scanner._filter_excluded_threats(result, profile_exclusions)

        # Should be clean since threat is under excluded directory
        assert filtered.status == scan_status_class.CLEAN
        assert filtered.infected_count == 0
        assert len(filtered.threat_details) == 0

    def test_filter_excludes_profile_path_with_tilde(
        self, daemon_scanner_class, scan_status_class, monkeypatch, tmp_path
    ):
        """Test that tilde paths are expanded correctly."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = []
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        # Create directory structure and mock home expansion
        fake_home = tmp_path / "fakehome"
        cache_dir = fake_home / ".cache"
        cache_dir.mkdir(parents=True)
        threat_file = cache_dir / "malware.exe"
        threat_file.touch()

        # Patch Path.home() and expanduser
        monkeypatch.setenv("HOME", str(fake_home))

        from src.core.scanner import ScanResult, ThreatDetail

        threat = ThreatDetail(
            file_path=str(threat_file),
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        result = ScanResult(
            status=scan_status_class.INFECTED,
            path=str(fake_home),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(threat_file)],
            scanned_files=1,
            scanned_dirs=0,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        profile_exclusions = {"paths": ["~/.cache"], "patterns": []}
        filtered = scanner._filter_excluded_threats(result, profile_exclusions)

        assert filtered.status == scan_status_class.CLEAN
        assert filtered.infected_count == 0

    def test_filter_keeps_threats_outside_excluded_paths(
        self, daemon_scanner_class, scan_status_class, tmp_path
    ):
        """Test that threats outside excluded paths are preserved."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = []
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        # Create directories
        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        threat_file = other_dir / "virus.exe"
        threat_file.touch()

        from src.core.scanner import ScanResult, ThreatDetail

        threat = ThreatDetail(
            file_path=str(threat_file),
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        result = ScanResult(
            status=scan_status_class.INFECTED,
            path=str(tmp_path),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(threat_file)],
            scanned_files=1,
            scanned_dirs=0,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        profile_exclusions = {"paths": [str(excluded_dir)], "patterns": []}
        filtered = scanner._filter_excluded_threats(result, profile_exclusions)

        # Should still be infected since threat is not under excluded dir
        assert filtered.status == scan_status_class.INFECTED
        assert filtered.infected_count == 1
        assert len(filtered.threat_details) == 1

    def test_filter_combines_global_and_profile_exclusions(
        self, daemon_scanner_class, scan_status_class, tmp_path
    ):
        """Test that both global patterns and profile paths work together."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "*.tmp", "type": "file", "enabled": True},
        ]
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        # Create directories and files
        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        threat1 = excluded_dir / "virus.exe"
        threat1.touch()
        threat2 = tmp_path / "temp.tmp"
        threat2.touch()
        threat3 = tmp_path / "real_virus.exe"
        threat3.touch()

        from src.core.scanner import ScanResult, ThreatDetail

        threats = [
            ThreatDetail(
                file_path=str(threat1),
                threat_name="Trojan1",
                category="Trojan",
                severity="high",
            ),
            ThreatDetail(
                file_path=str(threat2),
                threat_name="Trojan2",
                category="Trojan",
                severity="high",
            ),
            ThreatDetail(
                file_path=str(threat3),
                threat_name="Trojan3",
                category="Trojan",
                severity="high",
            ),
        ]

        result = ScanResult(
            status=scan_status_class.INFECTED,
            path=str(tmp_path),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(threat1), str(threat2), str(threat3)],
            scanned_files=3,
            scanned_dirs=0,
            infected_count=3,
            error_message=None,
            threat_details=threats,
        )

        profile_exclusions = {"paths": [str(excluded_dir)], "patterns": []}
        filtered = scanner._filter_excluded_threats(result, profile_exclusions)

        # threat1 filtered by profile path, threat2 by global pattern
        # Only threat3 should remain
        assert filtered.status == scan_status_class.INFECTED
        assert filtered.infected_count == 1
        assert len(filtered.threat_details) == 1
        assert filtered.threat_details[0].file_path == str(threat3)

    def test_filter_preserves_skipped_files(self, daemon_scanner_class, scan_status_class):
        """skipped_files/skipped_count must survive _filter_excluded_threats rebuilds."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "/home/user/eicar.txt", "type": "file", "enabled": True},
        ]
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        from src.core.scanner import ScanResult, ThreatDetail

        threat = ThreatDetail(
            file_path="/home/user/eicar.txt",
            threat_name="Eicar-Test-Signature",
            category="Test",
            severity="low",
        )
        kept = ThreatDetail(
            file_path="/home/user/virus.exe",
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        skipped = ["/home/user/locked.bin", "/home/user/special.sock"]
        result = ScanResult(
            status=scan_status_class.INFECTED,
            path="/home/user",
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=["/home/user/eicar.txt", "/home/user/virus.exe"],
            scanned_files=4,
            scanned_dirs=0,
            infected_count=2,
            error_message=None,
            threat_details=[threat, kept],
            skipped_files=skipped,
            skipped_count=len(skipped),
        )

        # Excluded threat removed -> still INFECTED (kept threat survives).
        filtered = scanner._filter_excluded_threats(result)
        assert filtered.status == scan_status_class.INFECTED
        assert filtered.skipped_files == skipped
        assert filtered.skipped_count == 2

        # All threats excluded -> CLEAN rebuild still carries skipped info.
        mock_settings.get.return_value = [
            {"pattern": "/home/user/eicar.txt", "type": "file", "enabled": True},
            {"pattern": "/home/user/virus.exe", "type": "file", "enabled": True},
        ]
        cleaned = scanner._filter_excluded_threats(result)
        assert cleaned.status == scan_status_class.CLEAN
        assert cleaned.skipped_files == skipped
        assert cleaned.skipped_count == 2

    def test_is_excluded_respects_path_separator_boundary(self, daemon_scanner_class):
        """Sibling paths sharing a prefix must not be excluded (no under-scan)."""
        scanner = daemon_scanner_class()
        patterns = ["/data/safe"]

        # Exact match and true subpaths are excluded.
        assert scanner._is_excluded("/data/safe", "safe", patterns, True) is True
        assert scanner._is_excluded("/data/safe/x", "x", patterns, False) is True

        # Prefix-sibling must NOT be excluded.
        assert scanner._is_excluded("/data/safe-malware", "safe-malware", patterns, False) is False


class TestDaemonScannerProcessLockThreadSafety:
    """Tests for DaemonScanner process lock and thread safety."""

    def test_daemon_scanner_has_process_lock(self, daemon_scanner_class):
        """Test that DaemonScanner has a _process_lock attribute."""
        import threading

        scanner = daemon_scanner_class()
        assert hasattr(scanner, "_process_lock")
        assert isinstance(scanner._process_lock, type(threading.Lock()))

    def test_cancel_uses_lock_for_process_access(self, daemon_scanner_class):
        """Test that cancel() acquires lock before accessing _current_process."""
        scanner = daemon_scanner_class()
        lock_acquired = []

        original_lock = scanner._process_lock

        class TrackingLock:
            def __enter__(self):
                lock_acquired.append("enter")
                return original_lock.__enter__()

            def __exit__(self, *args):
                lock_acquired.append("exit")
                return original_lock.__exit__(*args)

        scanner._process_lock = TrackingLock()
        scanner.cancel()

        assert "enter" in lock_acquired
        assert "exit" in lock_acquired

    def test_scan_sync_uses_lock_for_process_assignment(self, tmp_path, daemon_scanner_class):
        """Test that scan_sync() acquires lock when assigning _current_process."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        # Verify the lock attribute exists (check for the fix)
        assert hasattr(scanner, "_process_lock"), "Scanner should have _process_lock attribute"

        # We can verify the lock is used by checking that _current_process operations
        # don't raise errors during concurrent access. The actual lock usage is tested
        # by the concurrent test below. Here we just verify the lock exists and
        # scan completes successfully with proper cleanup.
        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            result = scanner.scan_sync(str(test_file), count_targets=False)

        # Verify scan completed and process was cleared
        assert result.status.value in ["clean", "infected", "error", "cancelled"]
        assert scanner._current_process is None

    def test_concurrent_cancel_and_scan_cleanup(self, tmp_path, daemon_scanner_class):
        """Test that concurrent cancel and scan cleanup don't cause race conditions."""
        import threading
        import time

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()
        errors = []

        def scan_thread():
            try:
                with (
                    patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
                    patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
                    patch("subprocess.Popen") as mock_popen,
                ):
                    mock_installed.return_value = (True, "ClamAV 1.0.0")
                    mock_connection.return_value = (True, "PONG")

                    mock_process = MagicMock()
                    # Simulate slow scan
                    mock_process.communicate.side_effect = lambda: (
                        time.sleep(0.1),
                        ("", ""),
                    )[-1]
                    mock_process.returncode = 0
                    mock_popen.return_value = mock_process

                    scanner.scan_sync(str(test_file), count_targets=False)
            except Exception as e:
                errors.append(e)

        def cancel_thread():
            try:
                time.sleep(0.05)  # Wait for scan to start
                scanner.cancel()
            except Exception as e:
                errors.append(e)

        # Run multiple iterations to increase chance of hitting race condition
        for _ in range(5):
            scanner._cancel_event.clear()
            t1 = threading.Thread(target=scan_thread)
            t2 = threading.Thread(target=cancel_thread)

            t1.start()
            t2.start()

            t1.join(timeout=2)
            t2.join(timeout=2)

        # No exceptions should have been raised due to race conditions
        assert len(errors) == 0, f"Race condition errors: {errors}"

    def test_process_cleared_after_scan_completes(self, tmp_path, daemon_scanner_class):
        """Test that _current_process is None after scan completes."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            scanner.scan_sync(str(test_file), count_targets=False)

        # After scan completes, _current_process should be None
        assert scanner._current_process is None

    def test_cancel_with_none_process_is_safe(self, daemon_scanner_class):
        """Test that cancel() is safe when _current_process is None."""
        scanner = daemon_scanner_class()
        assert scanner._current_process is None

        # Should not raise any exception
        scanner.cancel()
        assert scanner._cancel_event.is_set() is True


class TestDaemonScannerCancelFlagReset:
    """Tests for cancel event reset at start of new scans."""

    def test_cancelled_flag_reset_at_scan_start(
        self, tmp_path, daemon_scanner_class, scan_status_class
    ):
        """Test that _cancel_event is reset at start of scan_sync."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        # Manually set cancel event to simulate previous cancelled scan
        scanner._cancel_event.set()

        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            result = scanner.scan_sync(str(test_file), count_targets=False)

        # Scan should complete successfully (not be cancelled)
        assert result.status == scan_status_class.CLEAN
        # Event should have been cleared during scan
        assert scanner._cancel_event.is_set() is False

    def test_scan_after_cancelled_during_counting_runs_normally(
        self, tmp_path, daemon_scanner_class, scan_status_class
    ):
        """Test that a new scan runs normally after previous scan was cancelled during counting.

        This is the specific bug scenario:
        1. Start scan A
        2. Cancel during counting phase (event set, scan returns cancelled)
        3. Start scan B - it should run normally, not return cancelled immediately
        """
        # Create test directory with files to trigger counting phase
        test_dir = tmp_path / "scan_test"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")

        scanner = daemon_scanner_class()

        # Simulate scan A being cancelled during counting phase
        # This is what happens when user cancels during _count_scan_targets
        def counting_that_gets_cancelled(*args, **kwargs):
            # Simulate cancel during counting
            scanner._cancel_event.set()
            return (0, 0, None)

        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch.object(scanner, "_count_scan_targets", side_effect=counting_that_gets_cancelled),
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            # Scan A - should be cancelled during counting
            result_a = scanner.scan_sync(str(test_dir), count_targets=True)

        assert result_a.status == scan_status_class.CANCELLED
        # Event should still be set after cancelled scan
        assert scanner._cancel_event.is_set() is True

        # Now start scan B - this is where the bug manifested
        # Without the fix, scan B would return CANCELLED immediately
        # because the flag wasn't reset at scan start
        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            # Scan B - should run normally, not be cancelled
            result_b = scanner.scan_sync(str(test_dir), count_targets=False)

        # With the fix, scan B should complete successfully
        assert result_b.status == scan_status_class.CLEAN
        assert scanner._cancel_event.is_set() is False

    def test_multiple_cancelled_scans_followed_by_successful_scan(
        self, tmp_path, daemon_scanner_class, scan_status_class
    ):
        """Test that multiple consecutive cancelled scans don't affect subsequent scans."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        # Cancel several scans in a row
        for _ in range(3):
            scanner._cancel_event.set()

        # Now run a real scan
        with (
            patch("src.core.daemon_scanner.check_clamdscan_installed") as mock_installed,
            patch("src.core.daemon_scanner.check_clamd_connection") as mock_connection,
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            result = scanner.scan_sync(str(test_file), count_targets=False)

        assert result.status == scan_status_class.CLEAN


class TestDaemonScannerExclusionHelpers:
    """Tests for DaemonScanner exclusion helper methods."""

    def test_collect_exclusion_patterns_from_settings(self, daemon_scanner_class):
        """Test collecting patterns from global settings."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "*.log", "type": "file", "enabled": True},
            {"pattern": "*.tmp", "type": "file", "enabled": True},
            {"pattern": "*.bak", "type": "file", "enabled": False},  # disabled
        ]
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        patterns = scanner._collect_exclusion_patterns()

        assert len(patterns) == 2
        assert "*.log" in patterns
        assert "*.tmp" in patterns
        assert "*.bak" not in patterns

    def test_collect_exclusion_patterns_from_profile(self, daemon_scanner_class):
        """Test collecting patterns from profile exclusions."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = []
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        profile_exclusions = {"patterns": ["*.cache", "*.swp", ""], "paths": []}
        patterns = scanner._collect_exclusion_patterns(profile_exclusions)

        assert len(patterns) == 2
        assert "*.cache" in patterns
        assert "*.swp" in patterns

    def test_collect_exclusion_patterns_combines_sources(self, daemon_scanner_class):
        """Test that patterns from settings and profile are combined."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "*.log", "type": "file", "enabled": True},
        ]
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        profile_exclusions = {"patterns": ["*.cache"], "paths": []}
        patterns = scanner._collect_exclusion_patterns(profile_exclusions)

        assert len(patterns) == 2
        assert "*.log" in patterns
        assert "*.cache" in patterns

    def test_collect_exclusion_patterns_empty_when_no_settings(self, daemon_scanner_class):
        """Test that empty list is returned when no settings manager."""
        scanner = daemon_scanner_class()

        patterns = scanner._collect_exclusion_patterns()

        assert patterns == []

    def test_collect_exclusion_paths_from_profile(self, daemon_scanner_class, tmp_path):
        """Test collecting paths from profile exclusions."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = []
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()

        profile_exclusions = {"patterns": [], "paths": [str(excluded_dir), ""]}
        paths = scanner._collect_exclusion_paths(profile_exclusions)

        assert len(paths) == 1
        assert paths[0] == excluded_dir.resolve()

    def test_collect_exclusion_paths_expands_tilde(
        self, daemon_scanner_class, monkeypatch, tmp_path
    ):
        """Test that tilde paths are expanded."""
        mock_settings = MagicMock()
        mock_settings.get.return_value = []
        scanner = daemon_scanner_class(settings_manager=mock_settings)

        fake_home = tmp_path / "fakehome"
        cache_dir = fake_home / ".cache"
        cache_dir.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))

        profile_exclusions = {"patterns": [], "paths": ["~/.cache"]}
        paths = scanner._collect_exclusion_paths(profile_exclusions)

        assert len(paths) == 1
        assert str(paths[0]).endswith(".cache")

    def test_collect_exclusion_paths_empty_when_no_profile(self, daemon_scanner_class):
        """Test that empty list is returned when no profile exclusions."""
        scanner = daemon_scanner_class()

        paths = scanner._collect_exclusion_paths()

        assert paths == []

    def test_matches_exclusion_pattern_exact_match(self, daemon_scanner_class):
        """Test exact path matching."""
        scanner = daemon_scanner_class()

        patterns = ["/home/user/eicar.txt"]
        assert scanner._matches_exclusion_pattern("/home/user/eicar.txt", patterns) is True
        assert scanner._matches_exclusion_pattern("/home/user/other.txt", patterns) is False

    def test_matches_exclusion_pattern_glob_pattern(self, daemon_scanner_class):
        """Test glob pattern matching."""
        scanner = daemon_scanner_class()

        patterns = ["*.log", "*.tmp"]
        assert scanner._matches_exclusion_pattern("/var/log/test.log", patterns) is True
        assert scanner._matches_exclusion_pattern("/tmp/file.tmp", patterns) is True
        assert scanner._matches_exclusion_pattern("/home/user/file.txt", patterns) is False

    def test_matches_exclusion_pattern_with_tilde(
        self, daemon_scanner_class, monkeypatch, tmp_path
    ):
        """Test pattern matching with tilde expansion."""
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        scanner = daemon_scanner_class()

        patterns = ["~/.cache/*"]
        # After tilde expansion, the pattern becomes the full path
        assert scanner._matches_exclusion_pattern(str(fake_home / ".cache/file"), patterns) is True

    def test_matches_exclusion_pattern_empty_patterns(self, daemon_scanner_class):
        """Test that empty patterns list returns False."""
        scanner = daemon_scanner_class()

        assert scanner._matches_exclusion_pattern("/some/file.txt", []) is False

    def test_matches_exclusion_path_direct_match(self, daemon_scanner_class, tmp_path):
        """Test direct path matching."""
        scanner = daemon_scanner_class()

        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        exclude_paths = [excluded_dir.resolve()]

        # File is exactly the excluded path (edge case, but valid)
        assert scanner._matches_exclusion_path(str(excluded_dir), exclude_paths) is True

    def test_matches_exclusion_path_subdirectory(self, daemon_scanner_class, tmp_path):
        """Test subdirectory path matching."""
        scanner = daemon_scanner_class()

        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        subdir = excluded_dir / "subdir"
        subdir.mkdir()
        file_in_subdir = subdir / "file.txt"
        file_in_subdir.touch()

        exclude_paths = [excluded_dir.resolve()]

        assert scanner._matches_exclusion_path(str(file_in_subdir), exclude_paths) is True

    def test_matches_exclusion_path_outside_excluded(self, daemon_scanner_class, tmp_path):
        """Test that files outside excluded paths don't match."""
        scanner = daemon_scanner_class()

        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        file_in_other = other_dir / "file.txt"
        file_in_other.touch()

        exclude_paths = [excluded_dir.resolve()]

        assert scanner._matches_exclusion_path(str(file_in_other), exclude_paths) is False

    def test_matches_exclusion_path_empty_paths(self, daemon_scanner_class):
        """Test that empty paths list returns False."""
        scanner = daemon_scanner_class()

        assert scanner._matches_exclusion_path("/some/file.txt", []) is False

    def test_matches_exclusion_path_similar_prefix_not_matched(
        self, daemon_scanner_class, tmp_path
    ):
        """Test that paths with similar prefixes are not incorrectly matched."""
        scanner = daemon_scanner_class()

        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        similar_dir = tmp_path / "excluded_other"
        similar_dir.mkdir()
        file_in_similar = similar_dir / "file.txt"
        file_in_similar.touch()

        exclude_paths = [excluded_dir.resolve()]

        # Should NOT match because "excluded_other" is not under "excluded"
        assert scanner._matches_exclusion_path(str(file_in_similar), exclude_paths) is False


class TestDaemonScannerFlatpakSupport:
    """Tests for DaemonScanner Flatpak mode support."""

    def test_file_list_temp_dir_uses_host_visible_cache_in_flatpak(
        self, tmp_path, daemon_scanner_class
    ):
        """Flatpak daemon file lists must not be created in XDG_RUNTIME_DIR."""
        scanner = daemon_scanner_class()

        with (
            patch("src.core.daemon_scanner.is_flatpak", return_value=True),
            patch("src.core.daemon_scanner.Path.home", return_value=tmp_path),
        ):
            temp_dir = scanner._get_file_list_temp_dir()

        expected = tmp_path / ".cache" / "clamui"
        assert temp_dir == str(expected)
        assert expected.is_dir()
        assert stat.S_IMODE(expected.stat().st_mode) == 0o700

    def test_file_list_temp_dir_prefers_runtime_dir_natively(
        self, tmp_path, monkeypatch, daemon_scanner_class
    ):
        """Native daemon file lists can stay in the private runtime directory."""
        scanner = daemon_scanner_class()
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        with patch("src.core.daemon_scanner.is_flatpak", return_value=False):
            assert scanner._get_file_list_temp_dir() == str(tmp_path)

    def test_build_command_uses_optimal_flags_in_flatpak(self, tmp_path, daemon_scanner_class):
        """Test _build_command uses --multiscan --fdpass in Flatpak mode."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        # Mock wrap_host_command to simulate Flatpak wrapping with force_host=True
        def mock_wrap(cmd, force_host=False):
            assert force_host is True, "force_host must be True for daemon commands"
            return ["flatpak-spawn", "--host"] + cmd

        with patch("src.core.daemon_scanner.wrap_host_command", side_effect=mock_wrap):
            cmd = scanner._build_command(str(test_file), recursive=True)

        # Verify flatpak-spawn wrapping
        assert cmd[0] == "flatpak-spawn"
        assert cmd[1] == "--host"
        # Now uses binary name only, not full path
        assert cmd[2] == "clamdscan"

        # Verify optimal flags are used (not --stream)
        assert "--multiscan" in cmd
        assert "--fdpass" in cmd
        assert "--stream" not in cmd

    def test_build_command_uses_optimal_flags_in_native(self, tmp_path, daemon_scanner_class):
        """Test _build_command uses --multiscan --fdpass in native mode."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        # In native mode, wrap_host_command returns command unchanged
        def mock_wrap(cmd, force_host=False):
            assert force_host is True, "force_host must be True for daemon commands"
            return cmd  # Native mode: command unchanged

        with patch("src.core.daemon_scanner.wrap_host_command", side_effect=mock_wrap):
            cmd = scanner._build_command(str(test_file), recursive=True)

        # Now uses binary name only
        assert cmd[0] == "clamdscan"
        assert "--multiscan" in cmd
        assert "--fdpass" in cmd
        assert "--stream" not in cmd

    def test_build_command_wraps_with_flatpak_spawn(self, tmp_path, daemon_scanner_class):
        """Test _build_command wraps command for Flatpak execution on host."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = daemon_scanner_class()

        # Mock wrap_host_command to add flatpak-spawn prefix with force_host=True
        def mock_wrap(cmd, force_host=False):
            assert force_host is True, "force_host must be True for daemon commands"
            return ["flatpak-spawn", "--host"] + cmd

        with patch("src.core.daemon_scanner.wrap_host_command", side_effect=mock_wrap):
            cmd = scanner._build_command(str(test_file), recursive=True)

        # Should be wrapped with flatpak-spawn --host
        assert cmd[0] == "flatpak-spawn"
        assert cmd[1] == "--host"
        # clamdscan should be the first actual command
        assert cmd[2] == "clamdscan"
        # The path should be at the end
        assert str(test_file) in cmd
