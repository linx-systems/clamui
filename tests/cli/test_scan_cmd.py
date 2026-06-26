# ClamUI Scan Command Tests
"""
Tests for the scan CLI command's text output.

Focuses on the security-sensitive path where filesystem-derived strings
(threat file paths, quarantine-failure paths/errors) are printed to the
terminal and must be sanitized to prevent ANSI/control-sequence injection.
"""

import argparse
from unittest.mock import patch

from src.cli.scan_cmd import _print_text_output, run
from src.core.scanner_types import ScanResult, ScanStatus, ThreatDetail


def _infected_result(threats: list[ThreatDetail]) -> ScanResult:
    """Build a minimal INFECTED ScanResult carrying the given threats."""
    return ScanResult(
        status=ScanStatus.INFECTED,
        path="/scan/target",
        stdout="",
        stderr="",
        exit_code=1,
        infected_files=[t.file_path for t in threats],
        scanned_files=1,
        scanned_dirs=0,
        infected_count=len(threats),
        error_message=None,
        threat_details=threats,
    )


class TestPrintTextOutputSanitization:
    """The text output must strip terminal escape sequences from paths."""

    def test_threat_file_path_is_sanitized(self, capsys):
        """A malicious file path with ANSI escapes must not reach the terminal raw."""
        threat = ThreatDetail(
            file_path="\x1b[31mevil\x1b[0m/payload",
            threat_name="Test.Threat",
            category="malware",
            severity="high",
        )
        result = _infected_result([threat])

        _print_text_output([result], duration=0.1, quarantine_info=None)

        captured = capsys.readouterr()
        assert "\x1b" not in captured.out
        assert "evil" in captured.out

    def test_threat_name_is_sanitized(self, capsys):
        """A malicious ClamAV threat name with ANSI escapes must be stripped."""
        threat = ThreatDetail(
            file_path="/clean/path",
            threat_name="Evil\x1b[2Jname",
            category="malware",
            severity="high",
        )
        result = _infected_result([threat])

        _print_text_output([result], duration=0.1, quarantine_info=None)

        captured = capsys.readouterr()
        assert "\x1b" not in captured.out
        assert "Evilname" in captured.out

    def test_quarantine_failure_path_is_sanitized(self, capsys):
        """Quarantine-failure path and error strings must also be sanitized."""
        threat = ThreatDetail(
            file_path="/clean/path",
            threat_name="Test.Threat",
            category="malware",
            severity="high",
        )
        result = _infected_result([threat])
        failures = [("\x1b[31mevil/file", "denied\x1b[2J")]

        _print_text_output([result], duration=0.1, quarantine_info=(0, failures))

        captured = capsys.readouterr()
        assert "\x1b" not in captured.out
        assert "evil/file" in captured.out


def _clean_result(path: str) -> ScanResult:
    """Build a minimal CLEAN ScanResult so run()'s scan path short-circuits."""
    return ScanResult(
        status=ScanStatus.CLEAN,
        path=path,
        stdout="",
        stderr="",
        exit_code=0,
        infected_files=[],
        scanned_files=1,
        scanned_dirs=0,
        infected_count=0,
        error_message=None,
        threat_details=[],
    )


class TestRunWiresSettingsManager:
    """run() must construct a Scanner that honors saved user settings."""

    def test_run_builds_scanner_with_settings_manager(self, tmp_path):
        """Scanner must be built with the SettingsManager so global exclusions
        and the configured scan_backend are honored by CLI scans."""
        target = tmp_path / "scanme"
        target.mkdir()
        args = argparse.Namespace(
            paths=[str(target)],
            profile=None,
            verbose=False,
            no_recursive=False,
            quarantine=False,
            json_output=False,
        )

        with (
            patch("src.cli.scan_cmd.LogManager"),
            patch("src.cli.scan_cmd.SettingsManager") as mock_settings_cls,
            patch("src.cli.scan_cmd.Scanner") as mock_scanner_cls,
        ):
            scanner = mock_scanner_cls.return_value
            scanner.check_available.return_value = (True, "1.0.0")
            scanner.scan_sync.return_value = _clean_result(str(target))

            run(args)

        assert (
            mock_scanner_cls.call_args.kwargs["settings_manager"] is mock_settings_cls.return_value
        )
