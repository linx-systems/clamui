# ClamUI Scheduled Scan CLI Tests
"""Unit tests for the scheduled scan CLI module functions."""

import os
import subprocess
from unittest.mock import MagicMock, patch


class TestParseArguments:
    """Tests for the parse_arguments function."""

    def test_parse_arguments_default_values(self):
        """Test parse_arguments returns default values when no args provided."""
        from src.cli.scheduled_scan import parse_arguments

        with patch("sys.argv", ["clamui-scheduled-scan"]):
            args = parse_arguments()

        assert args.skip_on_battery is None
        assert args.auto_quarantine is None
        assert args.targets is None
        assert args.dry_run is False
        assert args.verbose is False

    def test_parse_arguments_skip_on_battery(self):
        """Test parse_arguments with --skip-on-battery flag."""
        from src.cli.scheduled_scan import parse_arguments

        with patch("sys.argv", ["clamui-scheduled-scan", "--skip-on-battery"]):
            args = parse_arguments()

        assert args.skip_on_battery is True

    def test_parse_arguments_auto_quarantine(self):
        """Test parse_arguments with --auto-quarantine flag."""
        from src.cli.scheduled_scan import parse_arguments

        with patch("sys.argv", ["clamui-scheduled-scan", "--auto-quarantine"]):
            args = parse_arguments()

        assert args.auto_quarantine is True

    def test_parse_arguments_single_target(self):
        """Test parse_arguments with single --target."""
        from src.cli.scheduled_scan import parse_arguments

        with patch("sys.argv", ["clamui-scheduled-scan", "--target", "/home/user"]):
            args = parse_arguments()

        assert args.targets == ["/home/user"]

    def test_parse_arguments_multiple_targets(self):
        """Test parse_arguments with multiple --target flags."""
        from src.cli.scheduled_scan import parse_arguments

        with patch(
            "sys.argv",
            ["clamui-scheduled-scan", "--target", "/home/user", "--target", "/tmp"],
        ):
            args = parse_arguments()

        assert args.targets == ["/home/user", "/tmp"]

    def test_parse_arguments_dry_run(self):
        """Test parse_arguments with --dry-run flag."""
        from src.cli.scheduled_scan import parse_arguments

        with patch("sys.argv", ["clamui-scheduled-scan", "--dry-run"]):
            args = parse_arguments()

        assert args.dry_run is True

    def test_parse_arguments_verbose(self):
        """Test parse_arguments with --verbose flag."""
        from src.cli.scheduled_scan import parse_arguments

        with patch("sys.argv", ["clamui-scheduled-scan", "--verbose"]):
            args = parse_arguments()

        assert args.verbose is True

    def test_parse_arguments_verbose_short_form(self):
        """Test parse_arguments with -v flag."""
        from src.cli.scheduled_scan import parse_arguments

        with patch("sys.argv", ["clamui-scheduled-scan", "-v"]):
            args = parse_arguments()

        assert args.verbose is True

    def test_parse_arguments_all_options(self):
        """Test parse_arguments with all options combined."""
        from src.cli.scheduled_scan import parse_arguments

        with patch(
            "sys.argv",
            [
                "clamui-scheduled-scan",
                "--skip-on-battery",
                "--auto-quarantine",
                "--target",
                "/home",
                "--target",
                "/tmp",
                "--dry-run",
                "--verbose",
            ],
        ):
            args = parse_arguments()

        assert args.skip_on_battery is True
        assert args.auto_quarantine is True
        assert args.targets == ["/home", "/tmp"]
        assert args.dry_run is True
        assert args.verbose is True


class TestLogMessage:
    """Tests for the log_message function."""

    def test_log_message_basic(self, capsys):
        """Test log_message outputs to stderr."""
        from src.cli.scheduled_scan import log_message

        log_message("Test message", verbose=False)

        captured = capsys.readouterr()
        assert "Test message" in captured.err
        assert captured.out == ""

    def test_log_message_verbose_only_not_shown(self, capsys):
        """Test verbose-only message not shown when verbose=False."""
        from src.cli.scheduled_scan import log_message

        log_message("Verbose message", verbose=False, is_verbose=True)

        captured = capsys.readouterr()
        assert "Verbose message" not in captured.err

    def test_log_message_verbose_only_shown(self, capsys):
        """Test verbose-only message shown when verbose=True."""
        from src.cli.scheduled_scan import log_message

        log_message("Verbose message", verbose=True, is_verbose=True)

        captured = capsys.readouterr()
        assert "Verbose message" in captured.err

    def test_log_message_timestamp_format(self, capsys):
        """Test log_message includes timestamp."""
        from src.cli.scheduled_scan import log_message

        log_message("Test", verbose=False)

        captured = capsys.readouterr()
        # Check for timestamp format: [YYYY-MM-DD HH:MM:SS]
        assert "[20" in captured.err
        assert "]" in captured.err


class TestSendNotification:
    """Tests for the send_notification function."""

    def test_send_notification_success(self):
        """Test send_notification returns True on success."""
        from src.cli.scheduled_scan import send_notification

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = send_notification("Title", "Body")

        assert result is True
        mock_run.assert_called_once()
        # Check that notify-send was called with the right args
        call_args = mock_run.call_args[0][0]
        assert "notify-send" in call_args
        assert "Title" in call_args
        assert "Body" in call_args

    def test_send_notification_with_urgency(self):
        """Test send_notification with different urgency levels."""
        from src.cli.scheduled_scan import send_notification

        mock_result = MagicMock()
        mock_result.returncode = 0

        for urgency in ["low", "normal", "critical"]:
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                result = send_notification("Title", "Body", urgency=urgency)

            assert result is True
            call_args = mock_run.call_args[0][0]
            assert "--urgency" in call_args
            assert urgency in call_args

    def test_send_notification_file_not_found(self):
        """Test send_notification returns False when notify-send not found."""
        from src.cli.scheduled_scan import send_notification

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = send_notification("Title", "Body")

        assert result is False

    def test_send_notification_timeout(self):
        """Test send_notification returns False on timeout."""
        from src.cli.scheduled_scan import send_notification

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            result = send_notification("Title", "Body")

        assert result is False

    def test_send_notification_oserror(self):
        """Test send_notification returns False on OSError."""
        from src.cli.scheduled_scan import send_notification

        with patch("subprocess.run", side_effect=OSError("Some error")):
            result = send_notification("Title", "Body")

        assert result is False

    def test_send_notification_failure_returncode(self):
        """Test send_notification returns False on non-zero return code."""
        from src.cli.scheduled_scan import send_notification

        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = send_notification("Title", "Body")

        assert result is False


class TestRunScheduledScan:
    """Tests for the run_scheduled_scan function."""

    def test_run_scheduled_scan_dry_run(self, tmp_path, capsys):
        """Test run_scheduled_scan in dry run mode."""
        from src.cli.scheduled_scan import run_scheduled_scan

        target = tmp_path / "test_dir"
        target.mkdir()

        result = run_scheduled_scan(
            targets=[str(target)],
            skip_on_battery=True,
            auto_quarantine=True,
            dry_run=True,
            verbose=True,
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "Dry run mode" in captured.err

    def test_run_scheduled_scan_no_targets(self, capsys):
        """Test run_scheduled_scan with no targets returns error."""
        from src.cli.scheduled_scan import run_scheduled_scan

        result = run_scheduled_scan(
            targets=[],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=True,
        )

        assert result == 2
        captured = capsys.readouterr()
        assert "No scan targets" in captured.err

    def test_run_scheduled_scan_invalid_targets(self, capsys):
        """Test run_scheduled_scan with all invalid targets returns error."""
        from src.cli.scheduled_scan import run_scheduled_scan

        result = run_scheduled_scan(
            targets=["/nonexistent/path/1", "/nonexistent/path/2"],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=True,
        )

        assert result == 2
        captured = capsys.readouterr()
        assert "No valid scan targets" in captured.err

    def test_run_scheduled_scan_skip_on_battery(self, tmp_path, capsys):
        """Test run_scheduled_scan skips scan when on battery."""
        from src.cli.scheduled_scan import run_scheduled_scan

        target = tmp_path / "test_dir"
        target.mkdir()

        # Mock BatteryManager to report on battery
        with patch("src.cli.scheduled_scan.BatteryManager") as mock_bm_class:
            mock_bm = MagicMock()
            mock_bm.should_skip_scan.return_value = True
            mock_bm.get_status.return_value = MagicMock(percent=50.0)
            mock_bm_class.return_value = mock_bm

            # Mock LogManager
            with patch("src.cli.scheduled_scan.LogManager") as mock_lm_class:
                mock_lm = MagicMock()
                mock_lm_class.return_value = mock_lm

                result = run_scheduled_scan(
                    targets=[str(target)],
                    skip_on_battery=True,
                    auto_quarantine=False,
                    dry_run=False,
                    verbose=True,
                )

        assert result == 0
        captured = capsys.readouterr()
        assert "Skipping scan" in captured.err
        assert "battery" in captured.err.lower()

    def test_run_scheduled_scan_clamav_not_available(self, tmp_path, capsys):
        """Test run_scheduled_scan when ClamAV not available."""
        from src.cli.scheduled_scan import run_scheduled_scan

        target = tmp_path / "test_dir"
        target.mkdir()

        # Mock Scanner to report ClamAV not available
        with patch("src.cli.scheduled_scan.Scanner") as mock_scanner_class:
            mock_scanner = MagicMock()
            mock_scanner.check_available.return_value = (False, "ClamAV not found")
            mock_scanner_class.return_value = mock_scanner

            # Mock LogManager
            with patch("src.cli.scheduled_scan.LogManager") as mock_lm_class:
                mock_lm = MagicMock()
                mock_lm_class.return_value = mock_lm

                # Mock send_notification
                with patch("src.cli.scheduled_scan.send_notification"):
                    result = run_scheduled_scan(
                        targets=[str(target)],
                        skip_on_battery=False,
                        auto_quarantine=False,
                        dry_run=False,
                        verbose=True,
                    )

        assert result == 2
        captured = capsys.readouterr()
        assert "ClamAV not available" in captured.err


class TestMain:
    """Tests for the main function."""

    def test_main_uses_settings_defaults(self):
        """Test main uses settings when CLI args not provided."""
        from src.cli.scheduled_scan import main

        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default: {
            "schedule_skip_on_battery": True,
            "schedule_auto_quarantine": False,
            "schedule_targets": ["/home/test"],
        }.get(key, default)

        with patch("sys.argv", ["clamui-scheduled-scan", "--dry-run"]):
            with patch("src.cli.scheduled_scan.SettingsManager", return_value=mock_settings):
                with patch("src.cli.scheduled_scan.run_scheduled_scan") as mock_run:
                    mock_run.return_value = 0
                    result = main()

        assert result == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["skip_on_battery"] is True
        assert call_kwargs["auto_quarantine"] is False
        assert call_kwargs["targets"] == ["/home/test"]

    def test_main_cli_overrides_settings(self):
        """Test main CLI args override settings."""
        from src.cli.scheduled_scan import main

        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default: {
            "schedule_skip_on_battery": True,
            "schedule_auto_quarantine": False,
            "schedule_targets": ["/home/test"],
        }.get(key, default)

        with patch(
            "sys.argv",
            [
                "clamui-scheduled-scan",
                "--auto-quarantine",
                "--target",
                "/custom/path",
                "--dry-run",
            ],
        ):
            with patch("src.cli.scheduled_scan.SettingsManager", return_value=mock_settings):
                with patch("src.cli.scheduled_scan.run_scheduled_scan") as mock_run:
                    mock_run.return_value = 0
                    result = main()

        assert result == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_quarantine"] is True
        assert call_kwargs["targets"] == ["/custom/path"]

    def test_main_default_home_directory(self):
        """Test main defaults to home directory when no targets configured."""
        from src.cli.scheduled_scan import main

        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default: {
            "schedule_skip_on_battery": False,
            "schedule_auto_quarantine": False,
            "schedule_targets": [],
        }.get(key, default)

        home_dir = os.path.expanduser("~")

        with patch("sys.argv", ["clamui-scheduled-scan", "--dry-run"]):
            with patch("src.cli.scheduled_scan.SettingsManager", return_value=mock_settings):
                with patch("src.cli.scheduled_scan.run_scheduled_scan") as mock_run:
                    mock_run.return_value = 0
                    result = main()

        assert result == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["targets"] == [home_dir]


class TestExecuteScans:
    """Tests for the _execute_scans function."""

    def test_execute_scans_single_target_clean(self, tmp_path, capsys):
        """Test _execute_scans with single target and clean result."""
        from src.cli.scheduled_scan import ScanContext, _execute_scans
        from src.core.scanner_types import ScanResult, ScanStatus

        target = tmp_path / "test_dir"
        target.mkdir()

        # Create mock scan result
        mock_result = ScanResult(
            status=ScanStatus.CLEAN,
            path=str(target),
            stdout="Scanning...\n",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=10,
            scanned_dirs=2,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )

        mock_scanner = MagicMock()
        mock_scanner.scan_sync.return_value = mock_result

        ctx = ScanContext(
            targets=[str(target)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=True,
            scanner=mock_scanner,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
        )

        agg = _execute_scans(ctx, [str(target)])

        assert agg.total_scanned == 10
        assert agg.total_infected == 0
        assert agg.has_errors is False
        assert len(agg.all_results) == 1
        assert agg.duration > 0

        captured = capsys.readouterr()
        assert "Clean" in captured.err

    def test_execute_scans_multiple_targets(self, tmp_path, capsys):
        """Test _execute_scans with multiple targets."""
        from src.cli.scheduled_scan import ScanContext, _execute_scans
        from src.core.scanner_types import ScanResult, ScanStatus

        target1 = tmp_path / "dir1"
        target2 = tmp_path / "dir2"
        target1.mkdir()
        target2.mkdir()

        mock_result1 = ScanResult(
            status=ScanStatus.CLEAN,
            path=str(target1),
            stdout="",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=5,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )

        mock_result2 = ScanResult(
            status=ScanStatus.CLEAN,
            path=str(target2),
            stdout="",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=8,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )

        mock_scanner = MagicMock()
        mock_scanner.scan_sync.side_effect = [mock_result1, mock_result2]

        ctx = ScanContext(
            targets=[str(target1), str(target2)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=True,
            scanner=mock_scanner,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
        )

        agg = _execute_scans(ctx, [str(target1), str(target2)])

        assert agg.total_scanned == 13
        assert len(agg.all_results) == 2
        assert agg.valid_targets == [str(target1), str(target2)]

    def test_execute_scans_with_infections(self, tmp_path, capsys):
        """Test _execute_scans with infected files found."""
        from src.cli.scheduled_scan import ScanContext, _execute_scans
        from src.core.scanner_types import ScanResult, ScanStatus, ThreatDetail

        target = tmp_path / "infected_dir"
        target.mkdir()
        infected_file = target / "malware.exe"
        infected_file.write_text("fake malware")

        threat = ThreatDetail(
            file_path=str(infected_file),
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        mock_result = ScanResult(
            status=ScanStatus.INFECTED,
            path=str(target),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(infected_file)],
            scanned_files=5,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        mock_scanner = MagicMock()
        mock_scanner.scan_sync.return_value = mock_result

        ctx = ScanContext(
            targets=[str(target)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=True,
            scanner=mock_scanner,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
        )

        agg = _execute_scans(ctx, [str(target)])

        assert agg.total_infected == 1
        assert len(agg.all_infected_files) == 1
        assert str(infected_file) in agg.all_infected_files

        captured = capsys.readouterr()
        assert "1 threat(s)" in captured.err

    def test_execute_scans_with_error(self, tmp_path, capsys):
        """Test _execute_scans handles scan errors."""
        from src.cli.scheduled_scan import ScanContext, _execute_scans
        from src.core.scanner_types import ScanResult, ScanStatus

        target = tmp_path / "error_dir"
        target.mkdir()

        mock_result = ScanResult(
            status=ScanStatus.ERROR,
            path=str(target),
            stdout="",
            stderr="Permission denied",
            exit_code=2,
            infected_files=[],
            scanned_files=0,
            scanned_dirs=0,
            infected_count=0,
            error_message="Permission denied",
            threat_details=[],
        )

        mock_scanner = MagicMock()
        mock_scanner.scan_sync.return_value = mock_result

        ctx = ScanContext(
            targets=[str(target)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=True,
            scanner=mock_scanner,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
        )

        agg = _execute_scans(ctx, [str(target)])

        assert agg.has_errors is True

        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestProcessQuarantine:
    """Tests for the _process_quarantine function."""

    def test_process_quarantine_disabled(self, tmp_path):
        """Test _process_quarantine when auto_quarantine is False."""
        from src.cli.scheduled_scan import (
            ScanAggregateResult,
            ScanContext,
            _process_quarantine,
        )

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=False,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=10,
            total_infected=1,
            all_infected_files=["/path/to/infected"],
        )

        qr = _process_quarantine(ctx, agg)

        assert qr.quarantined_count == 0
        assert len(qr.failed) == 0

    def test_process_quarantine_no_infected_files(self, tmp_path):
        """Test _process_quarantine with no infected files."""
        from src.cli.scheduled_scan import (
            ScanAggregateResult,
            ScanContext,
            _process_quarantine,
        )

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=True,
            dry_run=False,
            verbose=False,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=10,
            total_infected=0,
            all_infected_files=[],
        )

        qr = _process_quarantine(ctx, agg)

        assert qr.quarantined_count == 0

    def test_process_quarantine_success(self, tmp_path, capsys):
        """Test _process_quarantine successfully quarantines files."""
        from src.cli.scheduled_scan import (
            ScanAggregateResult,
            ScanContext,
            _process_quarantine,
        )
        from src.core.quarantine import QuarantineResult, QuarantineStatus
        from src.core.scanner_types import ScanResult, ScanStatus, ThreatDetail

        infected_file = tmp_path / "malware.exe"
        infected_file.write_text("fake malware")

        threat = ThreatDetail(
            file_path=str(infected_file),
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        mock_scan_result = ScanResult(
            status=ScanStatus.INFECTED,
            path=str(tmp_path),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(infected_file)],
            scanned_files=5,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=True,
            dry_run=False,
            verbose=True,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=5,
            total_infected=1,
            all_infected_files=[str(infected_file)],
            all_results=[mock_scan_result],
        )

        # Mock QuarantineManager
        mock_qm = MagicMock()
        mock_qm.quarantine_file.return_value = QuarantineResult(
            status=QuarantineStatus.SUCCESS,
            entry=MagicMock(),
            error_message=None,
        )

        with patch("src.cli.scheduled_scan.QuarantineManager", return_value=mock_qm):
            qr = _process_quarantine(ctx, agg)

        assert qr.quarantined_count == 1
        assert len(qr.failed) == 0

        captured = capsys.readouterr()
        assert "Quarantining" in captured.err
        assert "Successfully quarantined" in captured.err

    def test_process_quarantine_failure(self, tmp_path, capsys):
        """Test _process_quarantine handles quarantine failures."""
        from src.cli.scheduled_scan import (
            ScanAggregateResult,
            ScanContext,
            _process_quarantine,
        )
        from src.core.quarantine import QuarantineResult, QuarantineStatus
        from src.core.scanner_types import ScanResult, ScanStatus, ThreatDetail

        infected_file = tmp_path / "malware.exe"

        threat = ThreatDetail(
            file_path=str(infected_file),
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        mock_scan_result = ScanResult(
            status=ScanStatus.INFECTED,
            path=str(tmp_path),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(infected_file)],
            scanned_files=5,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=True,
            dry_run=False,
            verbose=True,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=5,
            total_infected=1,
            all_infected_files=[str(infected_file)],
            all_results=[mock_scan_result],
        )

        # Mock QuarantineManager to fail
        mock_qm = MagicMock()
        mock_qm.quarantine_file.return_value = QuarantineResult(
            status=QuarantineStatus.FILE_NOT_FOUND,
            entry=None,
            error_message="File not found",
        )

        with patch("src.cli.scheduled_scan.QuarantineManager", return_value=mock_qm):
            qr = _process_quarantine(ctx, agg)

        assert qr.quarantined_count == 0
        assert len(qr.failed) == 1
        assert qr.failed[0][0] == str(infected_file)

        captured = capsys.readouterr()
        assert "Failed to quarantine" in captured.err


class TestBuildSummaryAndStatus:
    """Tests for the _build_summary_and_status function."""

    def test_summary_clean_scan(self):
        """Test summary for clean scan results."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            _build_summary_and_status,
        )

        agg = ScanAggregateResult(
            total_scanned=100,
            total_infected=0,
            has_errors=False,
        )
        qr = QuarantineResult()

        summary, status = _build_summary_and_status(agg, qr, auto_quarantine=False)

        assert status == "clean"
        assert "100 files scanned" in summary
        assert "no threats" in summary

    def test_summary_infected_no_quarantine(self):
        """Test summary for infected scan without quarantine."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            _build_summary_and_status,
        )

        agg = ScanAggregateResult(
            total_scanned=50,
            total_infected=3,
        )
        qr = QuarantineResult()

        summary, status = _build_summary_and_status(agg, qr, auto_quarantine=False)

        assert status == "infected"
        assert "3 threat(s)" in summary

    def test_summary_infected_with_quarantine(self):
        """Test summary for infected scan with successful quarantine."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            _build_summary_and_status,
        )

        agg = ScanAggregateResult(
            total_scanned=50,
            total_infected=3,
        )
        qr = QuarantineResult(quarantined_count=2)

        summary, status = _build_summary_and_status(agg, qr, auto_quarantine=True)

        assert status == "infected"
        assert "3 threat(s)" in summary
        assert "2 quarantined" in summary

    def test_summary_errors(self):
        """Test summary for scan with errors."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            _build_summary_and_status,
        )

        agg = ScanAggregateResult(
            total_scanned=10,
            total_infected=0,
            has_errors=True,
        )
        qr = QuarantineResult()

        summary, status = _build_summary_and_status(agg, qr, auto_quarantine=False)

        assert status == "error"
        assert "errors" in summary.lower()


class TestBuildLogDetails:
    """Tests for the _build_log_details function."""

    def test_log_details_basic(self):
        """Test basic log details generation."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            _build_log_details,
        )

        agg = ScanAggregateResult(
            total_scanned=100,
            total_infected=0,
            duration=5.5,
            valid_targets=["/home/user"],
        )
        qr = QuarantineResult()

        details = _build_log_details(agg, qr, auto_quarantine=False)

        assert "5.5 seconds" in details
        assert "100" in details
        assert "/home/user" in details

    def test_log_details_with_infected_files(self, tmp_path):
        """Test log details with infected file information."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            _build_log_details,
        )
        from src.core.scanner_types import ScanResult, ScanStatus, ThreatDetail

        infected_file = str(tmp_path / "malware.exe")
        threat = ThreatDetail(
            file_path=infected_file,
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        mock_result = ScanResult(
            status=ScanStatus.INFECTED,
            path=str(tmp_path),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[infected_file],
            scanned_files=5,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        agg = ScanAggregateResult(
            total_scanned=5,
            total_infected=1,
            all_infected_files=[infected_file],
            all_results=[mock_result],
            duration=2.0,
            valid_targets=[str(tmp_path)],
        )
        qr = QuarantineResult()

        details = _build_log_details(agg, qr, auto_quarantine=False)

        assert "Infected Files" in details
        assert "Win.Trojan.Test" in details
        assert "Trojan" in details

    def test_log_details_with_quarantine_info(self, tmp_path):
        """Test log details include quarantine information."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            _build_log_details,
        )
        from src.core.scanner_types import ScanResult, ScanStatus, ThreatDetail

        infected_file = str(tmp_path / "malware.exe")
        threat = ThreatDetail(
            file_path=infected_file,
            threat_name="Test.Threat",
            category="Test",
            severity="low",
        )

        mock_result = ScanResult(
            status=ScanStatus.INFECTED,
            path=str(tmp_path),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[infected_file],
            scanned_files=5,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        agg = ScanAggregateResult(
            total_scanned=5,
            total_infected=1,
            all_infected_files=[infected_file],
            all_results=[mock_result],
            duration=2.0,
            valid_targets=[str(tmp_path)],
        )
        qr = QuarantineResult(
            quarantined_count=1,
            failed=[("/other/file", "Permission denied")],
        )

        details = _build_log_details(agg, qr, auto_quarantine=True)

        assert "Quarantined: 1" in details
        assert "Quarantine Failed: 1" in details

    def test_log_details_with_scan_output(self, tmp_path):
        """Test log details include scan stdout/stderr."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            _build_log_details,
        )
        from src.core.scanner_types import ScanResult, ScanStatus

        mock_result = ScanResult(
            status=ScanStatus.CLEAN,
            path=str(tmp_path),
            stdout="ClamAV scan output here",
            stderr="Warning: something",
            exit_code=0,
            infected_files=[],
            scanned_files=10,
            scanned_dirs=2,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )

        agg = ScanAggregateResult(
            total_scanned=10,
            total_infected=0,
            all_results=[mock_result],
            duration=1.0,
            valid_targets=[str(tmp_path)],
        )
        qr = QuarantineResult()

        details = _build_log_details(agg, qr, auto_quarantine=False)

        assert "ClamAV scan output here" in details
        assert "Warning: something" in details


class TestSendScanNotification:
    """Tests for the _send_scan_notification function."""

    def test_notification_disabled(self, tmp_path):
        """Test notification not sent when disabled in settings."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            ScanContext,
            _send_scan_notification,
        )

        mock_settings = MagicMock()
        mock_settings.get.return_value = False  # notifications_enabled = False

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=False,
            settings=mock_settings,
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(total_scanned=10)
        qr = QuarantineResult()

        with patch("src.cli.scheduled_scan.send_notification") as mock_notify:
            _send_scan_notification(ctx, agg, qr)

        mock_notify.assert_not_called()

    def test_notification_clean_scan(self, tmp_path):
        """Test notification for clean scan."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            ScanContext,
            _send_scan_notification,
        )

        mock_settings = MagicMock()
        mock_settings.get.return_value = True  # notifications_enabled = True

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=False,
            settings=mock_settings,
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=50,
            total_infected=0,
            has_errors=False,
        )
        qr = QuarantineResult()

        with patch("src.cli.scheduled_scan.send_notification") as mock_notify:
            _send_scan_notification(ctx, agg, qr)

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert "No threats found" in call_args[0][1]
        assert call_args[1]["urgency"] == "low"

    def test_notification_infected(self, tmp_path):
        """Test notification for infected scan."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            ScanContext,
            _send_scan_notification,
        )

        mock_settings = MagicMock()
        mock_settings.get.return_value = True

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=False,
            settings=mock_settings,
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=50,
            total_infected=3,
        )
        qr = QuarantineResult()

        with patch("src.cli.scheduled_scan.send_notification") as mock_notify:
            _send_scan_notification(ctx, agg, qr)

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert "Threats Detected" in call_args[0][0]
        assert "3 infected" in call_args[0][1]
        assert call_args[1]["urgency"] == "critical"

    def test_notification_infected_with_quarantine(self, tmp_path):
        """Test notification includes quarantine count."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            ScanContext,
            _send_scan_notification,
        )

        mock_settings = MagicMock()
        mock_settings.get.return_value = True

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=True,
            dry_run=False,
            verbose=False,
            settings=mock_settings,
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=50,
            total_infected=3,
        )
        qr = QuarantineResult(quarantined_count=2)

        with patch("src.cli.scheduled_scan.send_notification") as mock_notify:
            _send_scan_notification(ctx, agg, qr)

        call_args = mock_notify.call_args
        assert "2 quarantined" in call_args[0][1]

    def test_notification_errors(self, tmp_path):
        """Test notification for scan with errors."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            ScanContext,
            _send_scan_notification,
        )

        mock_settings = MagicMock()
        mock_settings.get.return_value = True

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=False,
            settings=mock_settings,
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=10,
            total_infected=0,
            has_errors=True,
        )
        qr = QuarantineResult()

        with patch("src.cli.scheduled_scan.send_notification") as mock_notify:
            _send_scan_notification(ctx, agg, qr)

        call_args = mock_notify.call_args
        assert "errors" in call_args[0][1].lower()
        assert call_args[1]["urgency"] == "normal"


class TestDetermineExitCode:
    """Tests for the _determine_exit_code function."""

    def test_exit_code_clean(self):
        """Test exit code 0 for clean scan."""
        from src.cli.scheduled_scan import ScanAggregateResult, _determine_exit_code

        agg = ScanAggregateResult(
            total_scanned=100,
            total_infected=0,
            has_errors=False,
        )

        assert _determine_exit_code(agg) == 0

    def test_exit_code_infected(self):
        """Test exit code 1 for infected scan."""
        from src.cli.scheduled_scan import ScanAggregateResult, _determine_exit_code

        agg = ScanAggregateResult(
            total_scanned=100,
            total_infected=5,
            has_errors=False,
        )

        assert _determine_exit_code(agg) == 1

    def test_exit_code_error(self):
        """Test exit code 2 for scan with errors."""
        from src.cli.scheduled_scan import ScanAggregateResult, _determine_exit_code

        agg = ScanAggregateResult(
            total_scanned=100,
            total_infected=0,
            has_errors=True,
        )

        assert _determine_exit_code(agg) == 2

    def test_exit_code_infected_takes_precedence(self):
        """Test infected status takes precedence over errors for exit code."""
        from src.cli.scheduled_scan import ScanAggregateResult, _determine_exit_code

        agg = ScanAggregateResult(
            total_scanned=100,
            total_infected=1,
            has_errors=True,
        )

        # Infected (exit 1) takes precedence over error (exit 2)
        assert _determine_exit_code(agg) == 1


class TestSaveLogEntry:
    """Tests for the _save_scan_log function."""

    def test_save_scan_log(self, tmp_path):
        """Test _save_scan_log creates log entry correctly."""
        from src.cli.scheduled_scan import (
            QuarantineResult,
            ScanAggregateResult,
            ScanContext,
            _save_scan_log,
        )

        mock_log_manager = MagicMock()

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=False,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=mock_log_manager,
            scanner=MagicMock(),
        )

        agg = ScanAggregateResult(
            total_scanned=100,
            duration=5.0,
            valid_targets=[str(tmp_path)],
        )
        qr = QuarantineResult()

        _save_scan_log(ctx, agg, qr, "Test summary", "clean", "Test details")

        mock_log_manager.save_log.assert_called_once()
        log_entry = mock_log_manager.save_log.call_args[0][0]

        assert log_entry.summary == "Test summary"
        assert log_entry.status == "clean"
        assert log_entry.scheduled is True


class TestCheckClamavAvailability:
    """Tests for the _check_clamav_availability function."""

    def test_clamav_available(self, tmp_path, capsys):
        """Test _check_clamav_availability when ClamAV is available."""
        from src.cli.scheduled_scan import ScanContext, _check_clamav_availability

        mock_scanner = MagicMock()
        mock_scanner.check_available.return_value = (True, "ClamAV 1.0.0")

        ctx = ScanContext(
            targets=[str(tmp_path)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=False,
            verbose=True,
            settings=MagicMock(),
            battery_manager=MagicMock(),
            log_manager=MagicMock(),
            scanner=mock_scanner,
        )

        version, error = _check_clamav_availability(ctx, [str(tmp_path)])

        assert version == "ClamAV 1.0.0"
        assert error is None

        captured = capsys.readouterr()
        assert "ClamAV version" in captured.err


class TestFullWorkflow:
    """Integration tests for the complete scheduled scan workflow."""

    def test_successful_clean_scan(self, tmp_path, capsys):
        """Test complete workflow with clean scan result."""
        from src.cli.scheduled_scan import run_scheduled_scan
        from src.core.scanner_types import ScanResult, ScanStatus

        target = tmp_path / "clean_dir"
        target.mkdir()
        (target / "file.txt").write_text("clean content")

        mock_result = ScanResult(
            status=ScanStatus.CLEAN,
            path=str(target),
            stdout="Scanned files: 1\n",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=1,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )

        with patch("src.cli.scheduled_scan.Scanner") as mock_scanner_class:
            mock_scanner = MagicMock()
            mock_scanner.check_available.return_value = (True, "ClamAV 1.0.0")
            mock_scanner.scan_sync.return_value = mock_result
            mock_scanner_class.return_value = mock_scanner

            with patch("src.cli.scheduled_scan.LogManager"):
                with patch("src.cli.scheduled_scan.send_notification"):
                    with patch("src.cli.scheduled_scan.SettingsManager") as mock_settings:
                        mock_settings.return_value.get.return_value = True
                        result = run_scheduled_scan(
                            targets=[str(target)],
                            skip_on_battery=False,
                            auto_quarantine=False,
                            dry_run=False,
                            verbose=True,
                        )

        assert result == 0
        captured = capsys.readouterr()
        assert "Scan completed" in captured.err

    def test_successful_infected_scan_with_quarantine(self, tmp_path, capsys):
        """Test complete workflow with infected scan and auto-quarantine."""
        from src.cli.scheduled_scan import run_scheduled_scan
        from src.core.quarantine import QuarantineResult, QuarantineStatus
        from src.core.scanner_types import ScanResult, ScanStatus, ThreatDetail

        target = tmp_path / "infected_dir"
        target.mkdir()
        infected_file = target / "malware.exe"
        infected_file.write_text("fake malware")

        threat = ThreatDetail(
            file_path=str(infected_file),
            threat_name="Win.Trojan.Test",
            category="Trojan",
            severity="high",
        )

        mock_result = ScanResult(
            status=ScanStatus.INFECTED,
            path=str(target),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(infected_file)],
            scanned_files=1,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        with patch("src.cli.scheduled_scan.Scanner") as mock_scanner_class:
            mock_scanner = MagicMock()
            mock_scanner.check_available.return_value = (True, "ClamAV 1.0.0")
            mock_scanner.scan_sync.return_value = mock_result
            mock_scanner_class.return_value = mock_scanner

            with patch("src.cli.scheduled_scan.LogManager"):
                with patch("src.cli.scheduled_scan.send_notification"):
                    with patch("src.cli.scheduled_scan.QuarantineManager") as mock_qm_class:
                        mock_qm = MagicMock()
                        mock_qm.quarantine_file.return_value = QuarantineResult(
                            status=QuarantineStatus.SUCCESS,
                            entry=MagicMock(),
                            error_message=None,
                        )
                        mock_qm_class.return_value = mock_qm

                        with patch("src.cli.scheduled_scan.SettingsManager") as mock_settings:
                            mock_settings.return_value.get.return_value = True
                            result = run_scheduled_scan(
                                targets=[str(target)],
                                skip_on_battery=False,
                                auto_quarantine=True,
                                dry_run=False,
                                verbose=True,
                            )

        assert result == 1  # Exit code 1 for infected
        captured = capsys.readouterr()
        assert "1 threat(s)" in captured.err
        assert "Successfully quarantined" in captured.err

    def test_scan_with_mixed_results(self, tmp_path, capsys):
        """Test workflow with multiple targets having different results."""
        from src.cli.scheduled_scan import run_scheduled_scan
        from src.core.scanner_types import ScanResult, ScanStatus, ThreatDetail

        clean_dir = tmp_path / "clean"
        infected_dir = tmp_path / "infected"
        clean_dir.mkdir()
        infected_dir.mkdir()

        infected_file = infected_dir / "virus.exe"
        infected_file.write_text("virus content")

        threat = ThreatDetail(
            file_path=str(infected_file),
            threat_name="Test.Virus",
            category="Test",
            severity="low",
        )

        clean_result = ScanResult(
            status=ScanStatus.CLEAN,
            path=str(clean_dir),
            stdout="",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=5,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )

        infected_result = ScanResult(
            status=ScanStatus.INFECTED,
            path=str(infected_dir),
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=[str(infected_file)],
            scanned_files=3,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[threat],
        )

        with patch("src.cli.scheduled_scan.Scanner") as mock_scanner_class:
            mock_scanner = MagicMock()
            mock_scanner.check_available.return_value = (True, "ClamAV 1.0.0")
            mock_scanner.scan_sync.side_effect = [clean_result, infected_result]
            mock_scanner_class.return_value = mock_scanner

            with patch("src.cli.scheduled_scan.LogManager"):
                with patch("src.cli.scheduled_scan.send_notification"):
                    with patch("src.cli.scheduled_scan.SettingsManager") as mock_settings:
                        mock_settings.return_value.get.return_value = True
                        result = run_scheduled_scan(
                            targets=[str(clean_dir), str(infected_dir)],
                            skip_on_battery=False,
                            auto_quarantine=False,
                            dry_run=False,
                            verbose=True,
                        )

        assert result == 1  # Infected takes precedence
        captured = capsys.readouterr()
        assert "2 target(s)" in captured.err


class TestValidateTargets:
    """Tests for the _validate_targets function."""

    def test_validate_targets_all_valid(self, tmp_path, capsys):
        """Test _validate_targets with all valid paths."""
        from src.cli.scheduled_scan import _validate_targets

        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        valid, error = _validate_targets([str(dir1), str(dir2)], verbose=True)

        assert error is None
        assert len(valid) == 2

    def test_validate_targets_some_invalid(self, tmp_path, capsys):
        """Test _validate_targets with mixed valid/invalid paths."""
        from src.cli.scheduled_scan import _validate_targets

        valid_dir = tmp_path / "valid"
        valid_dir.mkdir()

        valid, error = _validate_targets([str(valid_dir), "/nonexistent/path"], verbose=True)

        assert error is None
        assert len(valid) == 1
        assert str(valid_dir) in valid

        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_validate_targets_expands_home(self, capsys):
        """Test _validate_targets expands ~ to home directory."""
        from src.cli.scheduled_scan import _validate_targets

        valid, error = _validate_targets(["~"], verbose=False)

        assert error is None
        assert len(valid) == 1
        assert "~" not in valid[0]
        assert os.path.expanduser("~") in valid[0]


class TestScanContextScannerWiring:
    """Tests for ScanContext building the Scanner with saved settings."""

    def test_scancontext_builds_scanner_with_settings_manager(self):
        """ScanContext.__post_init__ must wire settings into the auto-built Scanner."""
        from src.cli.scheduled_scan import ScanContext

        mock_settings = MagicMock()
        mock_log_manager = MagicMock()

        with patch("src.cli.scheduled_scan.Scanner") as mock_scanner_cls:
            ScanContext(
                targets=["/home/user"],
                skip_on_battery=False,
                auto_quarantine=False,
                dry_run=False,
                verbose=False,
                settings=mock_settings,
                battery_manager=MagicMock(),
                log_manager=mock_log_manager,
                scanner=None,
            )

        mock_scanner_cls.assert_called_once()
        kwargs = mock_scanner_cls.call_args.kwargs
        assert kwargs["settings_manager"] is mock_settings
        assert kwargs["log_manager"] is mock_log_manager
