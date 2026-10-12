"""Unit tests for stateless clamscan result parsing."""

from src.core.clamscan_parser import parse_clamscan_result
from src.core.scanner_types import ScanStatus


class TestClamscanResultParser:
    """Tests for parse_clamscan_result."""

    def test_parse_results_clean(self):
        """Parse clean scan output."""

        stdout = """
/home/user/test.txt: OK

----------- SCAN SUMMARY -----------
Known viruses: 8000000
Engine version: 1.2.3
Scanned directories: 1
Scanned files: 10
Infected files: 0
Data scanned: 0.50 MB
Data read: 0.50 MB
Time: 0.500 sec (0 m 0 s)
"""
        result = parse_clamscan_result("/home/user", stdout, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert result.scanned_files == 10
        assert result.scanned_dirs == 1
        assert len(result.infected_files) == 0

    def test_parse_results_infected(self):
        """Parse infected scan output."""

        stdout = """
/home/user/test/virus.txt: Eicar-Test-Signature FOUND

----------- SCAN SUMMARY -----------
Known viruses: 8000000
Engine version: 1.2.3
Scanned directories: 1
Scanned files: 5
Infected files: 1
Data scanned: 0.01 MB
Data read: 0.01 MB
Time: 0.100 sec (0 m 0 s)
"""
        result = parse_clamscan_result("/home/user/test", stdout, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert result.infected_count == 1
        assert result.scanned_files == 5
        assert len(result.infected_files) == 1
        assert "/home/user/test/virus.txt" in result.infected_files

    def test_parse_results_error(self):
        """Return an error result for exit code 2."""

        result = parse_clamscan_result("/nonexistent", "", "Can't access path", 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message is not None

    def test_parse_results_large_file_warnings_are_clean(self):
        """Exit code 2 caused only by scan-limit warnings should be CLEAN, not ERROR.

        Regression for a full scan reporting an error after hitting a large
        compressed file (cli_scanxz decompress-size-limit warning).
        """
        stdout = """
----------- SCAN SUMMARY -----------
Scanned files: 50000
Infected files: 0
"""
        stderr = (
            "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN\n"
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes\n"
        )

        result = parse_clamscan_result("/", stdout, stderr, 2)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert result.error_message is None

    def test_parse_results_real_error_with_limit_warnings_still_error(self):
        """A genuine error on exit code 2 must remain ERROR despite benign warnings."""
        stderr = (
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes\n"
            "ERROR: Can't open file or directory\n"
        )

        result = parse_clamscan_result("/", "", stderr, 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message is not None

    def test_parse_results_multiple_infected(self):
        """Parse multiple infected files."""

        stdout = """
/home/user/virus1.txt: Eicar-Test-Signature FOUND
/home/user/virus2.txt: Trojan.Generic FOUND
/home/user/virus3.exe: Win.Trojan.Agent FOUND

----------- SCAN SUMMARY -----------
Scanned files: 100
Infected files: 3
"""
        result = parse_clamscan_result("/home/user", stdout, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert result.infected_count == 3
        assert len(result.infected_files) == 3

    def test_parse_results_clean_has_empty_threat_details(self):
        """Return no threat details for a clean scan."""

        stdout = """
/home/user/test.txt: OK

----------- SCAN SUMMARY -----------
Scanned files: 10
Infected files: 0
"""
        result = parse_clamscan_result("/home/user", stdout, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert len(result.threat_details) == 0

    def test_parse_results_extracts_threat_details(self):
        """Extract correctly classified threat details."""

        stdout = """
/home/user/test/virus.txt: Eicar-Test-Signature FOUND

----------- SCAN SUMMARY -----------
Scanned files: 5
Infected files: 1
"""
        result = parse_clamscan_result("/home/user/test", stdout, "", 1)

        assert len(result.threat_details) == 1
        threat = result.threat_details[0]
        assert threat.file_path == "/home/user/test/virus.txt"
        assert threat.threat_name == "Eicar-Test-Signature"
        assert threat.category == "Test"
        assert threat.severity == "low"

    def test_parse_results_multiple_threats_with_classification(self):
        """Classify multiple parsed threats."""

        stdout = """
/home/user/eicar.txt: Eicar-Test-Signature FOUND
/home/user/trojan.exe: Win.Trojan.Agent FOUND
/home/user/ransom.exe: Ransomware.Locky FOUND

----------- SCAN SUMMARY -----------
Scanned files: 100
Infected files: 3
"""
        result = parse_clamscan_result("/home/user", stdout, "", 1)

        assert len(result.threat_details) == 3

        # EICAR - Test category, low severity
        assert result.threat_details[0].threat_name == "Eicar-Test-Signature"
        assert result.threat_details[0].category == "Test"
        assert result.threat_details[0].severity == "low"

        # Trojan - Trojan category, high severity
        assert result.threat_details[1].threat_name == "Win.Trojan.Agent"
        assert result.threat_details[1].category == "Trojan"
        assert result.threat_details[1].severity == "high"

        # Ransomware - Ransomware category, critical severity
        assert result.threat_details[2].threat_name == "Ransomware.Locky"
        assert result.threat_details[2].category == "Ransomware"
        assert result.threat_details[2].severity == "critical"

    def test_parse_results_permission_denied_only(self):
        """Treat permission errors on exit code 2 as CLEAN."""

        stdout = """/home/user/test.txt: OK
/root/secret.txt: Failed to open file ERROR
/root/other.txt: Failed to open file ERROR

----------- SCAN SUMMARY -----------
Scanned files: 1
Scanned directories: 2
Infected files: 0
"""
        result = parse_clamscan_result("/home/user", stdout, "", 2)

        # Should be CLEAN because only permission errors, no infections
        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert result.skipped_count == 2
        assert len(result.skipped_files) == 2
        assert "/root/secret.txt" in result.skipped_files
        assert "/root/other.txt" in result.skipped_files
        assert result.has_warnings is True
        assert result.warning_message == "2 file(s) could not be accessed"

    def test_parse_results_permission_denied_with_infection(self):
        """Exit code 2 with both an infection and an unreadable file must stay INFECTED.

        clamscan returns exit code 2 when it detects a virus AND hits an error
        (e.g. an unreadable file). A real detection must not be masked by ERROR.
        """

        stdout = """/home/user/test.txt: OK
/home/user/virus.txt: Eicar-Test-Signature FOUND
/root/secret.txt: Failed to open file ERROR

----------- SCAN SUMMARY -----------
Scanned files: 2
Infected files: 1
"""
        result = parse_clamscan_result("/home/user", stdout, "", 2)

        # Detections are authoritative even on exit code 2.
        assert result.status == ScanStatus.INFECTED
        assert result.infected_count == 1
        # Threat details must survive being forced to INFECTED.
        assert len(result.threat_details) == 1
        assert result.threat_details[0].threat_name == "Eicar-Test-Signature"
        assert "/home/user/virus.txt" in result.infected_files
        assert result.skipped_count == 1
        assert "/root/secret.txt" in result.skipped_files
        assert result.has_warnings is True

    def test_parse_results_exit_code_2_with_no_skipped_files(self):
        """Report ERROR for exit code 2 with no skipped files."""

        stdout = """----------- SCAN SUMMARY -----------
Scanned files: 0
Infected files: 0
"""
        result = parse_clamscan_result("/nonexistent", stdout, "Path not found", 2)

        # Should be ERROR because exit code 2 and no skipped files
        assert result.status == ScanStatus.ERROR
        assert result.skipped_count == 0
        assert result.error_message == "Path not found"

    def test_parse_results_single_permission_denied(self):
        """Parse a single permission-denied file."""

        stdout = """/home/user/test.txt: OK
/root/secret: Failed to open file ERROR

----------- SCAN SUMMARY -----------
Scanned files: 1
Infected files: 0
"""
        result = parse_clamscan_result("/", stdout, "", 2)

        assert result.status == ScanStatus.CLEAN
        assert result.skipped_count == 1
        assert result.skipped_files == ["/root/secret"]
        assert result.warning_message == "1 file(s) could not be accessed"

    def test_parse_results_special_file_warnings_in_stderr(self):
        """Special-file warnings should be treated as non-fatal skipped paths."""

        stdout = """----------- SCAN SUMMARY -----------
Scanned files: 10
Scanned directories: 3
Infected files: 0
"""
        stderr = """WARNING: /home/user/.cache/ibus/dbus-abc: Not supported file type
LibClamAV Warning: cli_realpath: Invalid arguments.
WARNING: /home/user/.cache/steam_pipe: Not supported file type
LibClamAV Warning: cli_realpath: Invalid arguments.
"""

        result = parse_clamscan_result("/home/user", stdout, stderr, 2)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert result.skipped_count == 2
        assert result.skipped_files == [
            "/home/user/.cache/ibus/dbus-abc",
            "/home/user/.cache/steam_pipe",
        ]
        assert result.warning_message == "2 file(s) could not be accessed"

    def test_parse_results_nonfatal_plus_unknown_warning_stays_error(self):
        """A recognized non-fatal warning must not excuse an unrecognized one (veto)."""
        stderr = (
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes\n"
            "LibClamAV Warning: something novel happened\n"
        )

        result = parse_clamscan_result("/", "", stderr, 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message is not None

    def test_parse_results_exit_code_2_empty_output_is_error(self):
        """Exit code 2 with no output at all has no positive signal and stays ERROR."""

        result = parse_clamscan_result("/home/user", "", "", 2)

        assert result.status == ScanStatus.ERROR
        assert result.skipped_count == 0
        assert result.nonfatal_warnings == []
        assert result.error_message is None

    def test_parse_results_total_errors_summary_downgrades_to_clean(self):
        """Regression for the -i mode hole: 'clamui scan' and scheduled scans run
        clamscan with -i, which suppresses per-file 'Access denied' lines, so exit 2
        arrives with only the summary's 'Total errors: N' as a positive signal.
        """
        stdout = """
----------- SCAN SUMMARY -----------
Known viruses: 8000000
Engine version: 1.2.3
Scanned directories: 12
Scanned files: 340
Infected files: 0
Total errors: 3
Data scanned: 120.00 MB
Time: 10.000 sec (0 m 10 s)
"""
        result = parse_clamscan_result("/home/user", stdout, "", 2)

        assert result.status == ScanStatus.CLEAN
        assert result.warning_message == "3 file(s) could not be read"
        assert result.error_message is None
        assert result.scanned_files == 340

    def test_parse_results_verbose_access_denied_line_is_skipped(self):
        """In -v mode the plain '<path>: Access denied' line marks a skipped file."""
        stdout = """/home/user/test.txt: OK
/root/secret.txt: Access denied

----------- SCAN SUMMARY -----------
Scanned files: 1
Infected files: 0
Total errors: 1
"""
        result = parse_clamscan_result("/home/user", stdout, "", 2)

        assert result.status == ScanStatus.CLEAN
        assert result.skipped_files == ["/root/secret.txt"]
        assert result.warning_message == "1 file(s) could not be accessed"

    def test_parse_results_cant_access_file_warning_is_skipped(self):
        """'WARNING: <path>: Can't access file' (file deleted mid-scan) is a skip."""
        stdout = """----------- SCAN SUMMARY -----------
Scanned files: 1
Infected files: 0
"""
        stderr = "WARNING: /home/user/tmp/ephemeral.dat: Can't access file\n"

        result = parse_clamscan_result("/home/user", stdout, stderr, 2)

        assert result.status == ScanStatus.CLEAN
        assert result.skipped_files == ["/home/user/tmp/ephemeral.dat"]

    def test_parse_results_time_limit_reached_is_nonfatal(self):
        """Per-file 'Time limit reached ERROR' lines are partial scans, not skipped files."""
        stdout = """/home/user/huge.tar: Time limit reached ERROR

----------- SCAN SUMMARY -----------
Scanned files: 10
Infected files: 0
"""
        result = parse_clamscan_result("/home/user", stdout, "", 2)

        assert result.status == ScanStatus.CLEAN
        assert result.skipped_files == []
        assert result.nonfatal_warnings == ["/home/user/huge.tar: Time limit reached ERROR"]
        assert result.warning_message == (
            "1 non-fatal warning(s) during scan; some files may have been only partially scanned"
        )

    def test_parse_results_total_errors_with_zero_scanned_is_error(self):
        """Exit 2 where every file failed ('Scanned files: 0') must not report CLEAN."""
        stdout = """----------- SCAN SUMMARY -----------
Scanned directories: 1
Scanned files: 0
Infected files: 0
Total errors: 3
"""
        result = parse_clamscan_result("/root", stdout, "", 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message == "No files could be scanned"

    def test_parse_results_skipped_files_with_zero_scanned_is_error(self):
        """Exit 2 with only skip warnings and no scanned files is an all-failed ERROR."""
        stdout = """----------- SCAN SUMMARY -----------
Scanned files: 0
Infected files: 0
"""
        stderr = "WARNING: /gone: Can't access file\n"

        result = parse_clamscan_result("/gone", stdout, stderr, 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message == "No files could be scanned"

    def test_parse_results_nonfatal_only_downgrade_sets_warning_fields(self):
        """A nonfatal-only downgrade must surface the warnings to the caller."""
        stdout = """
----------- SCAN SUMMARY -----------
Scanned files: 50000
Infected files: 0
"""
        stderr = (
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes\n"
        )

        result = parse_clamscan_result("/", stdout, stderr, 2)

        assert result.status == ScanStatus.CLEAN
        assert result.nonfatal_warnings == [
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes"
        ]
        assert result.has_warnings is True
        assert result.warning_message == (
            "1 non-fatal warning(s) during scan; some files may have been only partially scanned"
        )

    def test_parse_results_infected_with_warnings_never_masked(self):
        """Detections stay INFECTED on exit 1 and 2 despite non-fatal warnings."""
        stdout = """/home/user/virus.txt: Eicar-Test-Signature FOUND

----------- SCAN SUMMARY -----------
Scanned files: 5
Infected files: 1
"""
        stderr = "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN\n"

        for exit_code in (1, 2):
            result = parse_clamscan_result("/home/user", stdout, stderr, exit_code)

            assert result.status == ScanStatus.INFECTED
            assert result.infected_count == 1
            assert "/home/user/virus.txt" in result.infected_files
            assert result.nonfatal_warnings == [
                "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN"
            ]


class TestClamscanResultParserEdgeCases:
    """Edge-case tests for parse_clamscan_result."""

    def test_parse_results_empty_stdout(self):
        """Handle empty stdout."""
        result = parse_clamscan_result("/test/path", "", "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert len(result.infected_files) == 0
        assert len(result.threat_details) == 0

    def test_parse_results_malformed_found_line(self):
        """Handle malformed FOUND lines."""

        # Missing colon separator
        stdout = "some_file_without_colon FOUND\n"
        result = parse_clamscan_result("/test", stdout, "", 1)

        # Should not crash, but may not parse the file correctly
        assert result.status == ScanStatus.INFECTED

    def test_parse_results_with_only_ok_lines(self):
        """Handle only OK lines without a summary."""

        stdout = """
/home/user/file1.txt: OK
/home/user/file2.txt: OK
/home/user/file3.txt: OK
"""
        result = parse_clamscan_result("/home/user", stdout, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert len(result.threat_details) == 0

    def test_parse_results_stderr_with_error_exit_code(self):
        """Include stderr in an error result."""

        stderr = "LibClamAV Error: Can't open file"
        result = parse_clamscan_result("/test", "", stderr, 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message == stderr

    def test_parse_results_special_characters_in_path(self):
        """Handle special characters in paths."""

        # File path with unicode and special characters
        stdout = "/home/user/test file (copy).txt: Eicar-Test-Signature FOUND\n"
        result = parse_clamscan_result("/home/user", stdout, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert len(result.threat_details) == 1
        assert result.threat_details[0].file_path == "/home/user/test file (copy).txt"

    def test_parse_results_colons_in_threat_name(self):
        """Handle colons in threat names.

        With rsplit(":", 1), the filename retains text before the final colon.
        """

        # Threat name contains colon (edge case)
        stdout = "/home/user/file.exe: Win.Trojan.Generic:Variant FOUND\n"
        result = parse_clamscan_result("/home/user", stdout, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert len(result.threat_details) == 1
        # Due to rsplit(":", 1), the file_path incorrectly includes part of the threat
        # This documents the current (imperfect) parsing behavior for paths with colons
        assert result.threat_details[0].file_path == "/home/user/file.exe: Win.Trojan.Generic"

    def test_parse_results_scanning_line_not_parsed_as_threat(self):
        """A verbose 'Scanning ' line for a clean file ending in FOUND is not a detection."""

        # clamscan -v emits "Scanning <path>" lines; a clean file named with a
        # trailing 'FOUND' must not be misparsed as a detection.
        stdout = (
            "Scanning /home/user/notes: about malware FOUND\n"
            "/home/user/notes: about malware FOUND: OK\n"
            "----------- SCAN SUMMARY -----------\n"
            "Scanned files: 1\n"
            "Infected files: 0\n"
        )
        result = parse_clamscan_result("/home/user", stdout, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert len(result.threat_details) == 0
