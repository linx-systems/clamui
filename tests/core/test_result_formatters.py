# ClamUI Result Formatters Tests
"""Unit tests for the result_formatters module functions."""

from src.core.result_formatters import (
    clean_scan_status_message,
    compose_scan_warning,
    format_results_as_csv,
    format_results_as_text,
)
from src.core.scanner import ScanResult, ScanStatus, ThreatDetail


class TestFormatResultsAsText:
    """Tests for the format_results_as_text function."""

    def _create_scan_result(
        self,
        status: ScanStatus = ScanStatus.CLEAN,
        path: str = "/home/user/test",
        scanned_files: int = 100,
        scanned_dirs: int = 10,
        infected_count: int = 0,
        threat_details: list = None,
        error_message: str = None,
    ) -> ScanResult:
        """Helper method to create a ScanResult for testing."""
        return ScanResult(
            status=status,
            path=path,
            stdout="",
            stderr="",
            exit_code=0 if status == ScanStatus.CLEAN else 1,
            infected_files=[t.file_path for t in (threat_details or [])],
            scanned_files=scanned_files,
            scanned_dirs=scanned_dirs,
            infected_count=infected_count,
            error_message=error_message,
            threat_details=threat_details or [],
        )

    def test_format_results_as_text_clean_scan(self):
        """Test formatting a clean scan result."""
        result = self._create_scan_result(
            status=ScanStatus.CLEAN,
            path="/home/user/Documents",
            scanned_files=150,
            scanned_dirs=25,
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "ClamUI Scan Report" in text
        assert "2024-01-15 14:30:45" in text
        assert "/home/user/Documents" in text
        assert "Status: CLEAN" in text
        assert "Files Scanned: 150" in text
        assert "Directories Scanned: 25" in text
        assert "Threats Found: 0" in text
        assert "No Threats Detected" in text
        assert "All scanned files are clean" in text

    def test_format_results_as_text_with_threats(self):
        """Test formatting a scan result with detected threats."""
        threat_details = [
            ThreatDetail(
                file_path="/home/user/Downloads/malware.exe",
                threat_name="Win.Ransomware.Locky",
                category="Ransomware",
                severity="critical",
            ),
            ThreatDetail(
                file_path="/home/user/Downloads/suspicious.doc",
                threat_name="Win.Trojan.Agent",
                category="Trojan",
                severity="high",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            path="/home/user/Downloads",
            scanned_files=200,
            scanned_dirs=30,
            infected_count=2,
            threat_details=threat_details,
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "ClamUI Scan Report" in text
        assert "Status: INFECTED" in text
        assert "Threats Found: 2" in text
        assert "Detected Threats" in text
        assert "[1] CRITICAL - Ransomware" in text
        assert "File: /home/user/Downloads/malware.exe" in text
        assert "Threat: Win.Ransomware.Locky" in text
        assert "[2] HIGH - Trojan" in text
        assert "File: /home/user/Downloads/suspicious.doc" in text
        assert "Threat: Win.Trojan.Agent" in text

    def test_format_results_as_text_error_status(self):
        """Test formatting an error scan result."""
        result = self._create_scan_result(
            status=ScanStatus.ERROR,
            path="/home/user/restricted",
            scanned_files=0,
            scanned_dirs=0,
            error_message="Permission denied: Cannot access directory",
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "ClamUI Scan Report" in text
        assert "Status: ERROR" in text
        assert "Scan Error" in text
        assert "Error: Permission denied: Cannot access directory" in text

    def test_format_results_as_text_cancelled_status(self):
        """Test formatting a cancelled scan result."""
        result = self._create_scan_result(
            status=ScanStatus.CANCELLED,
            path="/home/user/large_directory",
            scanned_files=50,
            scanned_dirs=5,
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "ClamUI Scan Report" in text
        assert "Status: CANCELLED" in text
        assert "Scan Cancelled" in text
        assert "scan was cancelled before completion" in text

    def test_format_results_as_text_auto_timestamp(self):
        """Test that timestamp is auto-generated when not provided."""
        result = self._create_scan_result()

        text = format_results_as_text(result)

        assert "ClamUI Scan Report" in text
        assert "Scan Date:" in text
        # Should contain a date-like string
        assert "20" in text  # Year starting with 20xx

    def test_format_results_as_text_header_and_footer(self):
        """Test that the output has proper header and footer lines."""
        result = self._create_scan_result()

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        lines = text.split("\n")
        # First line should be the header border
        assert lines[0].startswith("═")
        # Last line should be the footer border
        assert lines[-1].startswith("═")

    def test_format_results_as_text_multiple_threats_numbered(self):
        """Test that multiple threats are numbered correctly."""
        threat_details = [
            ThreatDetail(
                file_path=f"/path/to/file{i}.exe",
                threat_name=f"Win.Trojan.Agent{i}",
                category="Trojan",
                severity="high",
            )
            for i in range(1, 6)
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=5,
            threat_details=threat_details,
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "[1] HIGH - Trojan" in text
        assert "[2] HIGH - Trojan" in text
        assert "[3] HIGH - Trojan" in text
        assert "[4] HIGH - Trojan" in text
        assert "[5] HIGH - Trojan" in text

    def test_format_results_as_text_severity_levels(self):
        """Test that all severity levels are formatted correctly."""
        threat_details = [
            ThreatDetail(
                file_path="/path/critical.exe",
                threat_name="Win.Ransomware.Test",
                category="Ransomware",
                severity="critical",
            ),
            ThreatDetail(
                file_path="/path/high.exe",
                threat_name="Win.Trojan.Test",
                category="Trojan",
                severity="high",
            ),
            ThreatDetail(
                file_path="/path/medium.exe",
                threat_name="PUA.Adware.Test",
                category="Adware",
                severity="medium",
            ),
            ThreatDetail(
                file_path="/path/low.exe",
                threat_name="Eicar-Test",
                category="Test",
                severity="low",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=4,
            threat_details=threat_details,
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "CRITICAL - Ransomware" in text
        assert "HIGH - Trojan" in text
        assert "MEDIUM - Adware" in text
        assert "LOW - Test" in text

    def test_format_results_as_text_special_characters_in_path(self):
        """Test that special characters in paths are handled correctly."""
        result = self._create_scan_result(
            status=ScanStatus.CLEAN,
            path="/home/user/My Documents (2024)/test folder",
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "/home/user/My Documents (2024)/test folder" in text

    def test_format_results_as_text_empty_threat_details_infected(self):
        """Test infected status with empty threat_details (edge case)."""
        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=1,
            threat_details=[],  # Empty but infected_count > 0
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "Status: INFECTED" in text
        assert "Threats Found: 1" in text
        # Should not have "Detected Threats" section since threat_details is empty
        assert "Detected Threats" not in text

    def test_format_results_as_text_long_threat_name(self):
        """Test that long threat names are handled correctly."""
        long_threat_name = "Win.Trojan.VeryLongThreatNameThatExceedsNormalLength-123456789-0"
        threat_details = [
            ThreatDetail(
                file_path="/path/to/file.exe",
                threat_name=long_threat_name,
                category="Trojan",
                severity="high",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=1,
            threat_details=threat_details,
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert long_threat_name in text

    def test_format_results_as_text_unicode_in_path(self):
        """Test that unicode characters in paths are handled correctly."""
        result = self._create_scan_result(
            status=ScanStatus.CLEAN,
            path="/home/user/文档/テスト/résumé.pdf",
        )

        text = format_results_as_text(result, timestamp="2024-01-15 14:30:45")

        assert "/home/user/文档/テスト/résumé.pdf" in text


class TestFormatResultsAsCsv:
    """Tests for the format_results_as_csv function."""

    def _create_scan_result(
        self,
        status: ScanStatus = ScanStatus.CLEAN,
        path: str = "/home/user/test",
        scanned_files: int = 100,
        scanned_dirs: int = 10,
        infected_count: int = 0,
        threat_details: list = None,
        error_message: str = None,
    ) -> ScanResult:
        """Helper method to create a ScanResult for testing."""
        return ScanResult(
            status=status,
            path=path,
            stdout="",
            stderr="",
            exit_code=0 if status == ScanStatus.CLEAN else 1,
            infected_files=[t.file_path for t in (threat_details or [])],
            scanned_files=scanned_files,
            scanned_dirs=scanned_dirs,
            infected_count=infected_count,
            error_message=error_message,
            threat_details=threat_details or [],
        )

    def test_format_results_as_csv_header_row(self):
        """Test that CSV output contains proper header row."""
        result = self._create_scan_result()

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")
        lines = csv_output.strip().split("\n")

        assert lines[0] == "File Path,Threat Name,Category,Severity,Timestamp"

    def test_format_results_as_csv_clean_scan(self):
        """Test formatting a clean scan result - only header row."""
        result = self._create_scan_result(
            status=ScanStatus.CLEAN,
            path="/home/user/Documents",
            scanned_files=150,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")
        lines = csv_output.strip().split("\n")

        # Should only have header row for clean scan
        assert len(lines) == 1
        assert "File Path,Threat Name,Category,Severity,Timestamp" in lines[0]

    def test_format_results_as_csv_with_threats(self):
        """Test formatting a scan result with detected threats."""
        threat_details = [
            ThreatDetail(
                file_path="/home/user/Downloads/malware.exe",
                threat_name="Win.Ransomware.Locky",
                category="Ransomware",
                severity="critical",
            ),
            ThreatDetail(
                file_path="/home/user/Downloads/suspicious.doc",
                threat_name="Win.Trojan.Agent",
                category="Trojan",
                severity="high",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=2,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")
        lines = csv_output.strip().split("\n")

        # Header + 2 threat rows
        assert len(lines) == 3
        assert "File Path,Threat Name,Category,Severity,Timestamp" in lines[0]
        assert "/home/user/Downloads/malware.exe" in lines[1]
        assert "Win.Ransomware.Locky" in lines[1]
        assert "Ransomware" in lines[1]
        assert "critical" in lines[1]
        assert "2024-01-15 14:30:45" in lines[1]
        assert "/home/user/Downloads/suspicious.doc" in lines[2]
        assert "Win.Trojan.Agent" in lines[2]

    def test_format_results_as_csv_auto_timestamp(self):
        """Test that timestamp is auto-generated when not provided."""
        threat_details = [
            ThreatDetail(
                file_path="/path/to/file.exe",
                threat_name="Test.Threat",
                category="Test",
                severity="low",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=1,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result)  # No timestamp provided
        lines = csv_output.strip().split("\n")

        # Should have a timestamp containing current year
        assert len(lines) == 2
        # Should contain a date-like string (20xx)
        assert "20" in lines[1]

    def test_format_results_as_csv_special_characters_in_path(self):
        """Test that special characters in paths are properly escaped."""
        threat_details = [
            ThreatDetail(
                file_path='/home/user/My Documents, Files/test "file".exe',
                threat_name="Win.Trojan.Agent",
                category="Trojan",
                severity="high",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=1,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")

        # Parse using csv module to verify proper escaping
        import csv
        import io

        reader = csv.reader(io.StringIO(csv_output))
        rows = list(reader)

        assert len(rows) == 2
        # CSV module should properly handle commas and quotes
        assert rows[1][0] == '/home/user/My Documents, Files/test "file".exe'
        assert rows[1][1] == "Win.Trojan.Agent"

    def test_format_results_as_csv_unicode_in_path(self):
        """Test that unicode characters in paths are handled correctly."""
        threat_details = [
            ThreatDetail(
                file_path="/home/user/文档/テスト/résumé.exe",
                threat_name="Win.Virus.Unicode",
                category="Virus",
                severity="medium",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=1,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")

        # Parse and verify unicode is preserved
        import csv
        import io

        reader = csv.reader(io.StringIO(csv_output))
        rows = list(reader)

        assert len(rows) == 2
        assert rows[1][0] == "/home/user/文档/テスト/résumé.exe"

    def test_format_results_as_csv_multiple_threats(self):
        """Test formatting with many threats."""
        threat_details = [
            ThreatDetail(
                file_path=f"/path/to/file{i}.exe",
                threat_name=f"Win.Trojan.Agent{i}",
                category="Trojan",
                severity="high",
            )
            for i in range(1, 6)
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=5,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")
        lines = csv_output.strip().split("\n")

        # Header + 5 threat rows
        assert len(lines) == 6

    def test_format_results_as_csv_all_severity_levels(self):
        """Test that all severity levels are included correctly."""
        threat_details = [
            ThreatDetail(
                file_path="/path/critical.exe",
                threat_name="Win.Ransomware.Test",
                category="Ransomware",
                severity="critical",
            ),
            ThreatDetail(
                file_path="/path/high.exe",
                threat_name="Win.Trojan.Test",
                category="Trojan",
                severity="high",
            ),
            ThreatDetail(
                file_path="/path/medium.exe",
                threat_name="PUA.Adware.Test",
                category="Adware",
                severity="medium",
            ),
            ThreatDetail(
                file_path="/path/low.exe",
                threat_name="Eicar-Test",
                category="Test",
                severity="low",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=4,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")

        assert "critical" in csv_output
        assert "high" in csv_output
        assert "medium" in csv_output
        assert "low" in csv_output

    def test_format_results_as_csv_valid_csv_format(self):
        """Test that output is valid CSV parseable by csv module."""
        threat_details = [
            ThreatDetail(
                file_path="/home/user/file.exe",
                threat_name="Win.Trojan.Agent",
                category="Trojan",
                severity="high",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=1,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")

        # Verify it can be parsed back with csv module
        import csv
        import io

        reader = csv.reader(io.StringIO(csv_output))
        rows = list(reader)

        # Should have header and one data row
        assert len(rows) == 2
        # Header should have 5 columns
        assert len(rows[0]) == 5
        assert rows[0] == ["File Path", "Threat Name", "Category", "Severity", "Timestamp"]
        # Data row should have 5 columns
        assert len(rows[1]) == 5

    def test_format_results_as_csv_error_status(self):
        """Test formatting an error scan result - only header row."""
        result = self._create_scan_result(
            status=ScanStatus.ERROR,
            path="/home/user/restricted",
            error_message="Permission denied",
            threat_details=[],
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")
        lines = csv_output.strip().split("\n")

        # Should only have header row for error scan (no threats)
        assert len(lines) == 1

    def test_format_results_as_csv_cancelled_status(self):
        """Test formatting a cancelled scan result - only header row."""
        result = self._create_scan_result(
            status=ScanStatus.CANCELLED,
            path="/home/user/large_directory",
            threat_details=[],
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")
        lines = csv_output.strip().split("\n")

        # Should only have header row for cancelled scan (no threats)
        assert len(lines) == 1

    def test_format_results_as_csv_long_threat_name(self):
        """Test that long threat names are handled correctly."""
        long_threat_name = "Win.Trojan.VeryLongThreatNameThatExceedsNormalLength-123456789-0"
        threat_details = [
            ThreatDetail(
                file_path="/path/to/file.exe",
                threat_name=long_threat_name,
                category="Trojan",
                severity="high",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=1,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")

        # Parse to verify long name is preserved
        import csv
        import io

        reader = csv.reader(io.StringIO(csv_output))
        rows = list(reader)

        assert rows[1][1] == long_threat_name

    def test_format_results_as_csv_newline_in_path(self):
        """Test that newline characters in paths are properly escaped."""
        threat_details = [
            ThreatDetail(
                file_path="/home/user/line1\nline2/file.exe",
                threat_name="Win.Trojan.Agent",
                category="Trojan",
                severity="high",
            ),
        ]

        result = self._create_scan_result(
            status=ScanStatus.INFECTED,
            infected_count=1,
            threat_details=threat_details,
        )

        csv_output = format_results_as_csv(result, timestamp="2024-01-15 14:30:45")

        # Parse to verify newline is properly escaped in CSV
        import csv
        import io

        reader = csv.reader(io.StringIO(csv_output))
        rows = list(reader)

        assert len(rows) == 2
        # The newline should be preserved in the parsed value
        assert "\n" in rows[1][0]


class TestComposeScanWarning:
    """Tests for the compose_scan_warning aggregation helper."""

    def test_skipped_count_takes_precedence(self):
        warning = compose_scan_warning(3, ["some warning"])
        assert warning == "3 file(s) could not be accessed"

    def test_warning_messages_joined_without_skips(self):
        warning = compose_scan_warning(0, ["limit warning A", "limit warning B"])
        assert warning == "limit warning A; limit warning B"

    def test_no_warnings_returns_none(self):
        assert compose_scan_warning(0, []) is None


class TestCleanScanStatusMessage:
    """Tests for the clean_scan_status_message banner helper."""

    def _create_clean_result(self, skipped_count=0, warning_message=None) -> ScanResult:
        return ScanResult(
            status=ScanStatus.CLEAN,
            path="/home/user/test",
            stdout="",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=10,
            scanned_dirs=2,
            infected_count=0,
            error_message=None,
            threat_details=[],
            skipped_count=skipped_count,
            warning_message=warning_message,
        )

    def test_plain_message_without_warnings(self):
        result = self._create_clean_result()
        assert clean_scan_status_message(result) == "Scan complete - No threats found"

    def test_skipped_files_render_count(self):
        result = self._create_clean_result(
            skipped_count=3, warning_message="3 file(s) could not be accessed"
        )
        message = clean_scan_status_message(result)
        assert message == "Scan complete - No threats found (3 file(s) not accessible)"

    def test_nonfatal_warning_never_renders_zero_files(self):
        """Regression: skipped_count == 0 with a warning must surface the
        warning message instead of a bare '0 file(s)' phrase."""
        result = self._create_clean_result(
            warning_message="LibClamAV Warning: bytecode execution failed"
        )
        message = clean_scan_status_message(result)
        assert "0 file(s)" not in message
        assert message == (
            "Scan complete - No threats found (LibClamAV Warning: bytecode execution failed)"
        )
