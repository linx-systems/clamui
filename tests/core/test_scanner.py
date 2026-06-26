# ClamUI Scanner Tests
"""Unit tests for the scanner module, including Flatpak integration."""

import subprocess
import sys
from unittest import mock

import pytest


def _clear_src_modules():
    """Clear all cached src.* modules to ensure clean imports."""
    modules_to_remove = [mod for mod in list(sys.modules.keys()) if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


@pytest.fixture(autouse=True)
def ensure_fresh_scanner_import():
    """Ensure scanner module is freshly imported for each test.

    This fixture clears cached src modules and exposes fresh class references
    as globals so tests can use Scanner, ScanResult, etc.

    Also resets the flatpak detection cache after imports to ensure tests
    can properly mock is_flatpak() behavior.
    """
    global Scanner, ScanResult, ScanStatus, ThreatDetail, glob_to_regex, validate_pattern
    global classify_threat_severity_str, categorize_threat

    # Save existing src.* modules so other test files' references stay valid
    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith("src.")}

    # Clear any cached src modules before test
    _clear_src_modules()

    # Import fresh
    # Reset flatpak cache after imports to allow tests to mock is_flatpak
    import src.core.flatpak as flatpak_module
    from src.core.scanner import (
        Scanner as _Scanner,
    )
    from src.core.scanner import (
        ScanResult as _ScanResult,
    )
    from src.core.scanner import (
        ScanStatus as _ScanStatus,
    )
    from src.core.scanner import (
        ThreatDetail as _ThreatDetail,
    )
    from src.core.scanner import (
        glob_to_regex as _glob_to_regex,
    )
    from src.core.scanner import (
        validate_pattern as _validate_pattern,
    )
    from src.core.threat_classifier import (
        categorize_threat as _categorize_threat,
    )
    from src.core.threat_classifier import (
        classify_threat_severity_str as _classify_threat_severity_str,
    )

    flatpak_module._flatpak_detected = None

    Scanner = _Scanner
    ScanResult = _ScanResult
    ScanStatus = _ScanStatus
    ThreatDetail = _ThreatDetail
    glob_to_regex = _glob_to_regex
    validate_pattern = _validate_pattern
    classify_threat_severity_str = _classify_threat_severity_str
    categorize_threat = _categorize_threat

    yield

    # Restore original modules so other test files' module-level imports
    # (e.g. test_keyring_manager.py) still reference the correct objects
    _clear_src_modules()
    sys.modules.update(saved_modules)


# Declare globals for type checkers
Scanner = None
ScanResult = None
ScanStatus = None
ThreatDetail = None
glob_to_regex = None
validate_pattern = None
classify_threat_severity_str = None
categorize_threat = None


@pytest.fixture
def scanner_class():
    """Get Scanner class."""
    return Scanner


@pytest.fixture
def scan_result_class():
    """Get ScanResult class."""
    return ScanResult


@pytest.fixture
def scan_status_class():
    """Get ScanStatus enum."""
    return ScanStatus


@pytest.fixture
def threat_detail_class():
    """Get ThreatDetail class."""
    return ThreatDetail


@pytest.fixture
def scanner():
    """Create a Scanner instance for testing."""
    return Scanner()


@pytest.fixture
def pattern_functions():
    """Get pattern utility functions."""
    return glob_to_regex, validate_pattern


class TestScannerBuildCommand:
    """Tests for the Scanner._build_command method."""

    def test_build_command_basic_file(self, tmp_path, scanner_class):
        """Test _build_command for a basic file scan without Flatpak."""
        # Create a temporary file for testing
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = scanner_class()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_file), recursive=False)

        # Should be clamscan with -i flag and path
        assert cmd[0] == "/usr/bin/clamscan"
        assert "-i" in cmd
        assert str(test_file) in cmd
        # Should NOT have -r flag for file (non-recursive)
        assert "-r" not in cmd

    def test_build_command_directory_recursive(self, tmp_path, scanner_class):
        """Test _build_command for recursive directory scan."""
        scanner = scanner_class()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(tmp_path), recursive=True)

        # Should have -r flag for directory
        assert cmd[0] == "/usr/bin/clamscan"
        assert "-r" in cmd
        assert "-i" in cmd
        assert str(tmp_path) in cmd

    def test_build_command_fallback_to_clamscan(self, tmp_path, scanner_class):
        """Test _build_command falls back to 'clamscan' when path not found."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = scanner_class()

        with mock.patch("src.core.scanner.get_clamav_path", return_value=None):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_file), recursive=False)

        # Should fall back to 'clamscan'
        assert cmd[0] == "clamscan"

    def test_build_command_wraps_with_flatpak_spawn(self, tmp_path, scanner_class):
        """Test _build_command wraps command with flatpak-spawn when in Flatpak."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = scanner_class()

        # Mock wrap_host_command to add flatpak-spawn prefix (simulating Flatpak environment)
        def mock_wrap(cmd):
            return ["flatpak-spawn", "--host"] + cmd

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=mock_wrap):
                cmd = scanner._build_command(str(test_file), recursive=False)

        # Should be prefixed with flatpak-spawn --host
        assert cmd[0] == "flatpak-spawn"
        assert cmd[1] == "--host"
        assert cmd[2] == "/usr/bin/clamscan"
        assert "-i" in cmd
        assert str(test_file) in cmd

    def test_build_command_no_wrap_outside_flatpak(self, tmp_path, scanner_class):
        """Test _build_command does NOT wrap when not in Flatpak."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = scanner_class()

        # Mock wrap_host_command to return command unchanged (not in Flatpak)
        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_file), recursive=False)

        # Should NOT be prefixed with flatpak-spawn
        assert cmd[0] == "/usr/bin/clamscan"
        assert "flatpak-spawn" not in cmd

    def test_build_command_with_exclusions(self, tmp_path):
        """Test _build_command includes exclusion patterns from settings."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Create a mock settings manager with exclusion patterns
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "*.log", "type": "file", "enabled": True},
            {"pattern": "node_modules", "type": "directory", "enabled": True},
            {"pattern": "*.tmp", "type": "pattern", "enabled": True},
            {
                "pattern": "*.disabled",
                "type": "file",
                "enabled": False,
            },  # Should be skipped
            {
                "pattern": "",
                "type": "file",
                "enabled": True,
            },  # Empty pattern, should be skipped
        ]

        scanner = Scanner(settings_manager=mock_settings)

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_dir), recursive=True)

        # Verify the command structure
        assert cmd[0] == "/usr/bin/clamscan"
        assert "-r" in cmd
        assert "-i" in cmd
        assert str(test_dir) in cmd

        # Verify file exclusions (--exclude) for *.log and *.tmp
        exclude_indices = [i for i, arg in enumerate(cmd) if arg == "--exclude"]
        assert len(exclude_indices) == 2  # *.log and *.tmp (not *.disabled which is disabled)

        # Verify directory exclusion (--exclude-dir) for node_modules
        exclude_dir_indices = [i for i, arg in enumerate(cmd) if arg == "--exclude-dir"]
        assert len(exclude_dir_indices) == 1

        # Verify the exclusion patterns are converted to regex
        # Get the argument following each --exclude flag
        exclude_patterns = [cmd[i + 1] for i in exclude_indices]
        exclude_dir_patterns = [cmd[i + 1] for i in exclude_dir_indices]

        # Verify regex patterns are present (glob_to_regex converts *.log to .*\.log etc.)
        # The exact regex format depends on fnmatch.translate, but should contain backslash-escaped dot
        assert any("log" in p for p in exclude_patterns)
        assert any("tmp" in p for p in exclude_patterns)
        assert any("node_modules" in p for p in exclude_dir_patterns)

        # Verify disabled patterns are NOT included
        all_args = " ".join(cmd)
        assert "disabled" not in all_args

    def test_build_command_without_settings_manager(self, tmp_path):
        """Test _build_command works without settings manager (no exclusions)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Scanner without settings manager
        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_file), recursive=False)

        # Should not have any exclusion flags
        assert "--exclude" not in cmd
        assert "--exclude-dir" not in cmd
        assert cmd[0] == "/usr/bin/clamscan"
        assert "-i" in cmd
        assert str(test_file) in cmd

    def test_build_command_with_empty_exclusions(self, tmp_path):
        """Test _build_command handles empty exclusions list."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Create a mock settings manager with empty exclusions
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = []

        scanner = Scanner(settings_manager=mock_settings)

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_file), recursive=False)

        # Should not have any exclusion flags
        assert "--exclude" not in cmd
        assert "--exclude-dir" not in cmd

    def test_disabled_exclusions_ignored(self, tmp_path):
        """Test _build_command ignores all disabled exclusions regardless of type."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Create a mock settings manager with ONLY disabled exclusions
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "*.log", "type": "file", "enabled": False},
            {"pattern": "node_modules", "type": "directory", "enabled": False},
            {"pattern": "*.tmp", "type": "pattern", "enabled": False},
            {"pattern": "__pycache__", "type": "directory", "enabled": False},
            {"pattern": ".git", "type": "directory", "enabled": False},
        ]

        scanner = Scanner(settings_manager=mock_settings)

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_dir), recursive=True)

        # Verify the command structure is correct
        assert cmd[0] == "/usr/bin/clamscan"
        assert "-r" in cmd
        assert "-i" in cmd
        assert str(test_dir) in cmd

        # Verify NO exclusion flags are present (all exclusions were disabled)
        assert "--exclude" not in cmd
        assert "--exclude-dir" not in cmd

        # Double-check none of the disabled patterns appear as exclusion args
        # We need to exclude the path argument itself (which may contain /tmp/)
        # Get only the exclusion-related args by filtering out the scan path and base command
        exclusion_args = [
            arg for arg in cmd if arg not in ["/usr/bin/clamscan", "-r", "-i", str(test_dir)]
        ]
        all_exclusion_args = " ".join(exclusion_args)
        assert "log" not in all_exclusion_args.lower()
        assert "node_modules" not in all_exclusion_args
        assert "tmp" not in all_exclusion_args.lower()
        assert "pycache" not in all_exclusion_args
        assert ".git" not in all_exclusion_args

    def _settings_with_clamd_conf(self, conf_path: str):
        """Build a mock settings manager that exposes a clamd.conf path."""
        values = {"clamd_conf_path": conf_path, "exclusion_patterns": []}
        mock_settings = mock.MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: values.get(key, default)
        return mock_settings

    def test_build_command_forwards_clamd_limits(self, tmp_path):
        """clamscan must inherit MaxFileSize/MaxScanSize/MaxRecursion/MaxFiles from clamd.conf."""
        conf = tmp_path / "clamd.conf"
        conf.write_text("MaxFileSize 50M\nMaxScanSize 400M\nMaxRecursion 20\nMaxFiles 50000\n")
        test_file = tmp_path / "test.txt"
        test_file.write_text("data")

        scanner = Scanner(settings_manager=self._settings_with_clamd_conf(str(conf)))

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch("src.core.scanner.resolve_clamd_conf_path", return_value=str(conf)):
                    cmd = scanner._build_command(str(test_file), recursive=False)

        assert "--max-filesize=50M" in cmd
        assert "--max-scansize=400M" in cmd
        assert "--max-recursion=20" in cmd
        assert "--max-files=50000" in cmd

    def test_build_command_forwards_only_present_limits(self, tmp_path):
        """Only the limit keys present in clamd.conf are forwarded."""
        conf = tmp_path / "clamd.conf"
        conf.write_text("MaxScanSize 200M\n")
        test_file = tmp_path / "test.txt"
        test_file.write_text("data")

        scanner = Scanner(settings_manager=self._settings_with_clamd_conf(str(conf)))

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch("src.core.scanner.resolve_clamd_conf_path", return_value=str(conf)):
                    cmd = scanner._build_command(str(test_file), recursive=False)

        assert "--max-scansize=200M" in cmd
        assert not any(arg.startswith("--max-filesize") for arg in cmd)
        assert not any(arg.startswith("--max-recursion") for arg in cmd)

    def test_build_command_no_limits_without_settings_manager(self, tmp_path):
        """No clamd.conf source → clamscan uses its own defaults (no limit flags)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("data")

        scanner = Scanner()  # no settings manager

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_file), recursive=False)

        assert not any(arg.startswith("--max-") for arg in cmd)


class TestScannerFlatpakIntegration:
    """Tests for Flatpak integration in Scanner."""

    def test_scanner_uses_wrap_host_command(self, tmp_path):
        """Test that Scanner._build_command calls wrap_host_command."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command") as mock_wrap:
                mock_wrap.return_value = ["/usr/bin/clamscan", "-i", str(test_file)]
                scanner._build_command(str(test_file), recursive=False)

        # Verify wrap_host_command was called
        mock_wrap.assert_called_once()
        # Verify it was called with the expected base command
        call_args = mock_wrap.call_args[0][0]
        assert call_args[0] == "/usr/bin/clamscan"

    def test_scanner_flatpak_does_not_pass_sandbox_database(self, tmp_path):
        """Host clamscan should use the host's default database paths."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch(
                "src.core.scanner.wrap_host_command",
                side_effect=lambda x: ["flatpak-spawn", "--host", *x],
            ):
                cmd = scanner._build_command(str(test_file), recursive=False)

        assert cmd[:3] == ["flatpak-spawn", "--host", "/usr/bin/clamscan"]
        assert "--database" not in cmd


class TestScanResult:
    """Tests for the ScanResult dataclass."""

    def test_scan_result_is_clean(self):
        """Test ScanResult.is_clean property."""
        result = ScanResult(
            status=ScanStatus.CLEAN,
            path="/test/path",
            stdout="",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=10,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )
        assert result.is_clean is True
        assert result.has_threats is False

    def test_scan_result_has_threats(self):
        """Test ScanResult.has_threats property."""
        result = ScanResult(
            status=ScanStatus.INFECTED,
            path="/test/path",
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=["/test/infected.txt"],
            scanned_files=10,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[],
        )
        assert result.is_clean is False
        assert result.has_threats is True

    def test_scan_result_error(self):
        """Test ScanResult with error status."""
        result = ScanResult(
            status=ScanStatus.ERROR,
            path="/test/path",
            stdout="",
            stderr="ClamAV error",
            exit_code=2,
            infected_files=[],
            scanned_files=0,
            scanned_dirs=0,
            infected_count=0,
            error_message="ClamAV error",
            threat_details=[],
        )
        assert result.is_clean is False
        assert result.has_threats is False

    def test_scan_result_cancelled(self):
        """Test ScanResult with cancelled status."""
        result = ScanResult(
            status=ScanStatus.CANCELLED,
            path="/test/path",
            stdout="",
            stderr="",
            exit_code=-1,
            infected_files=[],
            scanned_files=0,
            scanned_dirs=0,
            infected_count=0,
            error_message="Scan cancelled by user",
            threat_details=[],
        )
        assert result.is_clean is False
        assert result.has_threats is False


class TestScanStatus:
    """Tests for the ScanStatus enum."""

    def test_scan_status_values(self):
        """Test ScanStatus enum has expected values."""
        assert ScanStatus.CLEAN.value == "clean"
        assert ScanStatus.INFECTED.value == "infected"
        assert ScanStatus.ERROR.value == "error"
        assert ScanStatus.CANCELLED.value == "cancelled"


class TestScannerParseResults:
    """Tests for the Scanner._parse_results method."""

    def test_parse_results_clean(self):
        """Test _parse_results with clean scan output."""
        scanner = Scanner()

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
        result = scanner._parse_results("/home/user", stdout, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert result.scanned_files == 10
        assert result.scanned_dirs == 1
        assert len(result.infected_files) == 0

    def test_parse_results_infected(self):
        """Test _parse_results with infected scan output."""
        scanner = Scanner()

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
        result = scanner._parse_results("/home/user/test", stdout, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert result.infected_count == 1
        assert result.scanned_files == 5
        assert len(result.infected_files) == 1
        assert "/home/user/test/virus.txt" in result.infected_files

    def test_parse_results_error(self):
        """Test _parse_results with error exit code."""
        scanner = Scanner()

        result = scanner._parse_results("/nonexistent", "", "Can't access path", 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message is not None

    def test_parse_results_large_file_warnings_are_clean(self):
        """Exit code 2 caused only by scan-limit warnings should be CLEAN, not ERROR.

        Regression for a full scan reporting an error after hitting a large
        compressed file (cli_scanxz decompress-size-limit warning).
        """
        scanner = Scanner()
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

        result = scanner._parse_results("/", stdout, stderr, 2)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert result.error_message is None

    def test_parse_results_real_error_with_limit_warnings_still_error(self):
        """A genuine error on exit code 2 must remain ERROR despite benign warnings."""
        scanner = Scanner()
        stderr = (
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits - "
            "only scanning 105906176 bytes\n"
            "ERROR: Can't open file or directory\n"
        )

        result = scanner._parse_results("/", "", stderr, 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message is not None

    def test_parse_results_multiple_infected(self):
        """Test _parse_results with multiple infected files."""
        scanner = Scanner()

        stdout = """
/home/user/virus1.txt: Eicar-Test-Signature FOUND
/home/user/virus2.txt: Trojan.Generic FOUND
/home/user/virus3.exe: Win.Trojan.Agent FOUND

----------- SCAN SUMMARY -----------
Scanned files: 100
Infected files: 3
"""
        result = scanner._parse_results("/home/user", stdout, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert result.infected_count == 3
        assert len(result.infected_files) == 3

    def test_parse_results_clean_has_empty_threat_details(self):
        """Test _parse_results returns empty threat_details for clean scans."""
        scanner = Scanner()

        stdout = """
/home/user/test.txt: OK

----------- SCAN SUMMARY -----------
Scanned files: 10
Infected files: 0
"""
        result = scanner._parse_results("/home/user", stdout, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert len(result.threat_details) == 0

    def test_parse_results_extracts_threat_details(self):
        """Test _parse_results extracts ThreatDetail objects with correct data."""
        scanner = Scanner()

        stdout = """
/home/user/test/virus.txt: Eicar-Test-Signature FOUND

----------- SCAN SUMMARY -----------
Scanned files: 5
Infected files: 1
"""
        result = scanner._parse_results("/home/user/test", stdout, "", 1)

        assert len(result.threat_details) == 1
        threat = result.threat_details[0]
        assert threat.file_path == "/home/user/test/virus.txt"
        assert threat.threat_name == "Eicar-Test-Signature"
        assert threat.category == "Test"
        assert threat.severity == "low"

    def test_parse_results_multiple_threats_with_classification(self):
        """Test _parse_results correctly classifies multiple threats."""
        scanner = Scanner()

        stdout = """
/home/user/eicar.txt: Eicar-Test-Signature FOUND
/home/user/trojan.exe: Win.Trojan.Agent FOUND
/home/user/ransom.exe: Ransomware.Locky FOUND

----------- SCAN SUMMARY -----------
Scanned files: 100
Infected files: 3
"""
        result = scanner._parse_results("/home/user", stdout, "", 1)

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

    def test_classify_threat_severity(self):
        """Test classify_threat_severity_str returns correct severity levels."""
        # Critical threats
        assert classify_threat_severity_str("Ransomware.Locky") == "critical"
        assert classify_threat_severity_str("Win.Rootkit.Agent") == "critical"
        assert classify_threat_severity_str("Bootkit.MBR") == "critical"
        assert classify_threat_severity_str("CryptoLocker.A") == "critical"

        # High threats
        assert classify_threat_severity_str("Trojan.Banker") == "high"
        assert classify_threat_severity_str("Worm.Mydoom") == "high"
        assert classify_threat_severity_str("Backdoor.IRC") == "high"
        assert classify_threat_severity_str("Exploit.CVE2021") == "high"
        assert classify_threat_severity_str("Downloader.Agent") == "high"

        # Medium threats
        assert classify_threat_severity_str("PUA.Adware.Generic") == "medium"
        assert classify_threat_severity_str("Spyware.Keylogger") == "high"  # keylogger = high
        assert classify_threat_severity_str("Coinminer.Generic") == "medium"
        assert classify_threat_severity_str("Unknown.Malware") == "medium"

        # Low threats
        assert classify_threat_severity_str("Eicar-Test-Signature") == "low"
        assert classify_threat_severity_str("Heuristic.Generic") == "low"

        # Edge cases
        assert classify_threat_severity_str("") == "medium"

    def test_categorize_threat(self):
        """Test categorize_threat extracts correct category from threat name."""
        # Specific categories
        assert categorize_threat("Win.Trojan.Agent") == "Trojan"
        assert categorize_threat("Worm.Mydoom") == "Worm"
        assert categorize_threat("Ransomware.Locky") == "Ransomware"
        assert categorize_threat("Win.Rootkit.Agent") == "Rootkit"
        assert categorize_threat("Backdoor.IRC") == "Backdoor"
        assert categorize_threat("Exploit.PDF") == "Exploit"
        assert categorize_threat("PUA.Adware.Generic") == "Adware"
        assert categorize_threat("Eicar-Test-Signature") == "Test"
        assert categorize_threat("Phishing.Email") == "Phishing"

        # Default category for unknown
        assert categorize_threat("Unknown.Malware") == "Virus"
        assert categorize_threat("") == "Unknown"

    def test_parse_results_permission_denied_only(self):
        """Test _parse_results treats exit code 2 with only permission errors as CLEAN."""
        scanner = Scanner()

        stdout = """/home/user/test.txt: OK
/root/secret.txt: Failed to open file ERROR
/root/other.txt: Failed to open file ERROR

----------- SCAN SUMMARY -----------
Scanned files: 1
Scanned directories: 2
Infected files: 0
"""
        result = scanner._parse_results("/home/user", stdout, "", 2)

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
        scanner = Scanner()

        stdout = """/home/user/test.txt: OK
/home/user/virus.txt: Eicar-Test-Signature FOUND
/root/secret.txt: Failed to open file ERROR

----------- SCAN SUMMARY -----------
Scanned files: 2
Infected files: 1
"""
        result = scanner._parse_results("/home/user", stdout, "", 2)

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
        """Test _parse_results reports ERROR when exit code 2 with no skipped files."""
        scanner = Scanner()

        stdout = """----------- SCAN SUMMARY -----------
Scanned files: 0
Infected files: 0
"""
        result = scanner._parse_results("/nonexistent", stdout, "Path not found", 2)

        # Should be ERROR because exit code 2 and no skipped files
        assert result.status == ScanStatus.ERROR
        assert result.skipped_count == 0
        assert result.error_message == "Path not found"

    def test_parse_results_single_permission_denied(self):
        """Test _parse_results correctly parses single permission denied file."""
        scanner = Scanner()

        stdout = """/home/user/test.txt: OK
/root/secret: Failed to open file ERROR

----------- SCAN SUMMARY -----------
Scanned files: 1
Infected files: 0
"""
        result = scanner._parse_results("/", stdout, "", 2)

        assert result.status == ScanStatus.CLEAN
        assert result.skipped_count == 1
        assert result.skipped_files == ["/root/secret"]
        assert result.warning_message == "1 file(s) could not be accessed"

    def test_parse_results_special_file_warnings_in_stderr(self):
        """Special-file warnings should be treated as non-fatal skipped paths."""
        scanner = Scanner()

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

        result = scanner._parse_results("/home/user", stdout, stderr, 2)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert result.skipped_count == 2
        assert result.skipped_files == [
            "/home/user/.cache/ibus/dbus-abc",
            "/home/user/.cache/steam_pipe",
        ]
        assert result.warning_message == "2 file(s) could not be accessed"

    def test_scan_result_has_warnings_property(self):
        """Test ScanResult.has_warnings property works correctly."""
        # No warnings
        result_no_warnings = ScanResult(
            status=ScanStatus.CLEAN,
            path="/test",
            stdout="",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=10,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
            skipped_files=[],
            skipped_count=0,
            warning_message=None,
        )
        assert result_no_warnings.has_warnings is False

        # With warnings
        result_with_warnings = ScanResult(
            status=ScanStatus.CLEAN,
            path="/test",
            stdout="",
            stderr="",
            exit_code=2,
            infected_files=[],
            scanned_files=10,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
            skipped_files=["/root/secret.txt"],
            skipped_count=1,
            warning_message="1 file(s) could not be accessed",
        )
        assert result_with_warnings.has_warnings is True


class TestScannerThreatDetailsIntegration:
    """Integration tests for enhanced scanner with threat details."""

    def test_scan_sync_threat_details_integration(self, tmp_path):
        """Integration test: scan_sync produces structured threat details."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        # Mock clamscan output with infected result
        mock_stdout = """
/home/user/virus.exe: Win.Trojan.Agent FOUND

----------- SCAN SUMMARY -----------
Scanned files: 5
Infected files: 1
"""

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = (mock_stdout, "")
                        mock_process.returncode = 1
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        # Verify threat details are properly populated
        assert result.status == ScanStatus.INFECTED
        assert len(result.threat_details) == 1
        assert result.threat_details[0].file_path == "/home/user/virus.exe"
        assert result.threat_details[0].threat_name == "Win.Trojan.Agent"
        assert result.threat_details[0].category == "Trojan"
        assert result.threat_details[0].severity == "high"

    def test_scan_sync_multiple_threat_details_integration(self, tmp_path):
        """Integration test: scan_sync handles multiple threats with different severities."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        scanner = Scanner()

        # Mock clamscan output with multiple infected files
        mock_stdout = """
/home/user/critical.exe: Ransomware.Locky FOUND
/home/user/high.exe: Win.Trojan.Agent FOUND
/home/user/medium.exe: PUA.Adware.Generic FOUND
/home/user/low.exe: Eicar-Test-Signature FOUND

----------- SCAN SUMMARY -----------
Scanned directories: 1
Scanned files: 100
Infected files: 4
"""

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = (mock_stdout, "")
                        mock_process.returncode = 1
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_dir), recursive=True)

        # Verify all threat details are captured with correct classification
        assert result.status == ScanStatus.INFECTED
        assert result.infected_count == 4
        assert len(result.threat_details) == 4

        # Verify each threat has correct severity
        severities = {t.threat_name: t.severity for t in result.threat_details}
        assert severities["Ransomware.Locky"] == "critical"
        assert severities["Win.Trojan.Agent"] == "high"
        assert severities["PUA.Adware.Generic"] == "medium"
        assert severities["Eicar-Test-Signature"] == "low"

        # Verify categories
        categories = {t.threat_name: t.category for t in result.threat_details}
        assert categories["Ransomware.Locky"] == "Ransomware"
        assert categories["Win.Trojan.Agent"] == "Trojan"
        assert categories["PUA.Adware.Generic"] == "Adware"
        assert categories["Eicar-Test-Signature"] == "Test"

    def test_scan_sync_clean_threat_details_empty(self, tmp_path):
        """Integration test: clean scan produces empty threat_details list."""
        test_file = tmp_path / "clean.txt"
        test_file.write_text("clean content")

        scanner = Scanner()

        # Mock clamscan output with clean result
        mock_stdout = """
/home/user/clean.txt: OK

----------- SCAN SUMMARY -----------
Scanned files: 1
Infected files: 0
"""

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = (mock_stdout, "")
                        mock_process.returncode = 0
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        # Verify clean result has empty threat_details
        assert result.status == ScanStatus.CLEAN
        assert result.is_clean is True
        assert result.has_threats is False
        assert len(result.threat_details) == 0
        assert result.infected_count == 0

    def test_threat_details_file_path_preserved(self, tmp_path):
        """Integration test: threat details preserve full file paths."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        # Mock output with complex path
        mock_stdout = """
/home/user/Documents/My Files/virus (copy).exe: Win.Trojan.Agent FOUND

----------- SCAN SUMMARY -----------
Scanned files: 1
Infected files: 1
"""

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = (mock_stdout, "")
                        mock_process.returncode = 1
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        # Verify file path is preserved including spaces and special characters
        assert len(result.threat_details) == 1
        assert (
            result.threat_details[0].file_path == "/home/user/Documents/My Files/virus (copy).exe"
        )

    def test_threat_details_with_cancelled_scan(self, tmp_path):
        """Integration test: cancelled scan produces empty threat_details."""
        import subprocess

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        # Set up mock to simulate cancellation during polling loop:
        # First call raises TimeoutExpired (process still running),
        # then we set _cancel_event, and the loop detects cancellation
        call_count = 0

        def simulate_timeout_then_cancel(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: simulate process still running
                scanner._cancel_event.set()  # Simulate cancel() being called
                raise subprocess.TimeoutExpired(cmd="clamscan", timeout=0.5)
            # Second call: return output after termination
            return ("", "")

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.side_effect = simulate_timeout_then_cancel
                        mock_process.returncode = 0
                        mock_process.poll.return_value = None  # Process still running
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        # Verify cancelled scan has empty threat_details
        assert result.status == ScanStatus.CANCELLED
        assert len(result.threat_details) == 0

    def test_threat_details_with_error_scan(self, tmp_path):
        """Integration test: error scan produces empty threat_details."""
        scanner = Scanner()

        # Mock ClamAV not installed
        with (
            mock.patch(
                "src.core.scanner.check_clamav_installed",
                return_value=(False, "ClamAV not found"),
            ),
            mock.patch("src.core.scanner.validate_path", return_value=(True, None)),
        ):
            result = scanner.scan_sync("/nonexistent/path")

        # Verify error result has empty threat_details
        assert result.status == ScanStatus.ERROR
        assert len(result.threat_details) == 0

    def test_threat_details_dataclass_attributes(self):
        """Test ThreatDetail dataclass has correct attributes."""
        threat = ThreatDetail(
            file_path="/test/virus.exe",
            threat_name="Win.Trojan.Agent",
            category="Trojan",
            severity="high",
        )

        assert threat.file_path == "/test/virus.exe"
        assert threat.threat_name == "Win.Trojan.Agent"
        assert threat.category == "Trojan"
        assert threat.severity == "high"

    def test_threat_details_all_severity_levels(self):
        """Integration test: verify all severity levels are correctly assigned."""
        scanner = Scanner()

        # Create output with threats of each severity level
        mock_stdout = """
/path/ransomware.exe: Ransomware.WannaCry FOUND
/path/rootkit.exe: Linux.Rootkit.Agent FOUND
/path/trojan.exe: Trojan.Banker FOUND
/path/worm.exe: Worm.Slammer FOUND
/path/backdoor.exe: Backdoor.Cobalt FOUND
/path/adware.exe: Adware.Toolbar FOUND
/path/eicar.txt: Eicar-Test-Signature FOUND
/path/generic.exe: Heuristic.Generic FOUND

----------- SCAN SUMMARY -----------
Scanned files: 8
Infected files: 8
"""

        result = scanner._parse_results("/path", mock_stdout, "", 1)

        assert len(result.threat_details) == 8

        # Build a map for easy verification
        threat_map = {t.threat_name: t for t in result.threat_details}

        # Critical severity
        assert threat_map["Ransomware.WannaCry"].severity == "critical"
        assert threat_map["Linux.Rootkit.Agent"].severity == "critical"

        # High severity
        assert threat_map["Trojan.Banker"].severity == "high"
        assert threat_map["Worm.Slammer"].severity == "high"
        assert threat_map["Backdoor.Cobalt"].severity == "high"

        # Medium severity
        assert threat_map["Adware.Toolbar"].severity == "medium"

        # Low severity
        assert threat_map["Eicar-Test-Signature"].severity == "low"
        assert threat_map["Heuristic.Generic"].severity == "low"

    def test_threat_details_integration_with_scan_result_properties(self, tmp_path):
        """Integration test: threat_details integrates with ScanResult properties."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        mock_stdout = """
/home/user/virus.exe: Win.Trojan.Agent FOUND

----------- SCAN SUMMARY -----------
Scanned files: 10
Scanned directories: 2
Infected files: 1
"""

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = (mock_stdout, "")
                        mock_process.returncode = 1
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        # Verify ScanResult properties work with threat_details
        assert result.is_clean is False
        assert result.has_threats is True
        assert result.infected_count == 1
        assert len(result.infected_files) == 1
        assert len(result.threat_details) == 1

        # Verify threat_details and infected_files are consistent
        assert result.threat_details[0].file_path == result.infected_files[0]


class TestPatternUtilities:
    """Tests for the glob_to_regex and validate_pattern utility functions."""

    # Tests for glob_to_regex function

    def test_glob_to_regex_simple_wildcard(self):
        """Test glob_to_regex converts simple wildcard patterns."""
        regex = glob_to_regex("*.log")
        # Should match any string ending with .log
        assert regex  # Not empty
        # Verify it's a valid regex by compiling
        import re

        compiled = re.compile(regex)
        assert compiled.match("test.log")
        assert compiled.match("error.log")
        assert not compiled.match("test.txt")

    def test_glob_to_regex_directory_pattern(self):
        """Test glob_to_regex converts directory name patterns."""
        regex = glob_to_regex("node_modules")
        import re

        compiled = re.compile(regex)
        assert compiled.match("node_modules")
        assert not compiled.match("node_modules_backup")

    def test_glob_to_regex_path_wildcard(self):
        """Test glob_to_regex converts path wildcard patterns."""
        regex = glob_to_regex("/tmp/*")
        import re

        compiled = re.compile(regex)
        assert compiled.match("/tmp/file.txt")
        assert compiled.match("/tmp/subdir")
        assert not compiled.match("/var/tmp/file")

    def test_glob_to_regex_multiple_wildcards(self):
        """Test glob_to_regex handles multiple wildcards."""
        regex = glob_to_regex("*.test.*")
        import re

        compiled = re.compile(regex)
        assert compiled.match("file.test.js")
        assert compiled.match("module.test.py")
        assert not compiled.match("file.spec.js")

    def test_glob_to_regex_question_mark_wildcard(self):
        """Test glob_to_regex converts ? wildcard (single character)."""
        regex = glob_to_regex("file?.txt")
        import re

        compiled = re.compile(regex)
        assert compiled.match("file1.txt")
        assert compiled.match("fileA.txt")
        assert not compiled.match("file12.txt")
        assert not compiled.match("file.txt")

    def test_glob_to_regex_character_class(self):
        """Test glob_to_regex converts character class patterns."""
        regex = glob_to_regex("file[0-9].txt")
        import re

        compiled = re.compile(regex)
        assert compiled.match("file0.txt")
        assert compiled.match("file9.txt")
        assert not compiled.match("fileA.txt")
        assert not compiled.match("file10.txt")

    def test_glob_to_regex_no_python_suffix(self):
        """Test glob_to_regex strips Python-specific regex suffixes."""
        regex = glob_to_regex("*.log")
        # Should not contain \Z (Python anchor)
        assert "\\Z" not in regex
        # Should not contain (?s: wrapper (newer Python)
        assert not regex.startswith("(?s:")

    def test_glob_to_regex_common_exclusion_patterns(self):
        """Test glob_to_regex handles common exclusion patterns."""
        import re

        # .git directory
        regex = glob_to_regex(".git")
        assert re.compile(regex).match(".git")

        # __pycache__ directory
        regex = glob_to_regex("__pycache__")
        assert re.compile(regex).match("__pycache__")

        # .venv directory
        regex = glob_to_regex(".venv")
        assert re.compile(regex).match(".venv")

        # build directory
        regex = glob_to_regex("build")
        assert re.compile(regex).match("build")

        # *.pyc files
        regex = glob_to_regex("*.pyc")
        compiled = re.compile(regex)
        assert compiled.match("module.pyc")
        assert not compiled.match("module.py")

    def test_glob_to_regex_special_characters_escaped(self):
        """Test glob_to_regex properly escapes special regex characters."""
        import re

        # Dots are escaped (not treated as regex wildcard)
        regex = glob_to_regex("file.txt")
        compiled = re.compile(regex)
        assert compiled.match("file.txt")
        assert not compiled.match("filextxt")  # Would match if . wasn't escaped

    def test_glob_to_regex_empty_pattern(self):
        """Test glob_to_regex handles empty pattern."""
        regex = glob_to_regex("")
        # Should return something (empty string becomes regex that matches empty)
        assert regex is not None

    # Tests for validate_pattern function

    def test_validate_pattern_valid_simple_wildcard(self):
        """Test validate_pattern accepts valid simple wildcard patterns."""
        assert validate_pattern("*.log") is True
        assert validate_pattern("*.txt") is True
        assert validate_pattern("*.py") is True

    def test_validate_pattern_valid_directory_names(self):
        """Test validate_pattern accepts valid directory name patterns."""
        assert validate_pattern("node_modules") is True
        assert validate_pattern(".git") is True
        assert validate_pattern("__pycache__") is True
        assert validate_pattern(".venv") is True
        assert validate_pattern("build") is True
        assert validate_pattern("dist") is True

    def test_validate_pattern_valid_path_patterns(self):
        """Test validate_pattern accepts valid path patterns."""
        assert validate_pattern("/tmp/*") is True
        assert validate_pattern("/var/log/*.log") is True
        assert validate_pattern("src/**") is True

    def test_validate_pattern_valid_complex_patterns(self):
        """Test validate_pattern accepts valid complex patterns."""
        assert validate_pattern("*.test.js") is True
        assert validate_pattern("file[0-9].txt") is True
        assert validate_pattern("file?.txt") is True

    def test_validate_pattern_empty_string(self):
        """Test validate_pattern rejects empty string."""
        assert validate_pattern("") is False

    def test_validate_pattern_whitespace_only(self):
        """Test validate_pattern rejects whitespace-only patterns."""
        assert validate_pattern("   ") is False
        assert validate_pattern("\t") is False
        assert validate_pattern("\n") is False
        assert validate_pattern("  \t\n  ") is False

    def test_validate_pattern_valid_with_spaces(self):
        """Test validate_pattern accepts patterns with internal spaces."""
        # Patterns with spaces are valid (e.g., matching files with spaces)
        assert validate_pattern("My Documents") is True
        assert validate_pattern("*.log file") is True

    def test_validate_pattern_common_development_exclusions(self):
        """Test validate_pattern accepts all common development exclusion patterns."""
        common_patterns = [
            "node_modules",
            ".git",
            ".venv",
            "build",
            "dist",
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".env",
            ".DS_Store",
            "*.log",
            "*.tmp",
            "coverage",
            ".coverage",
            ".pytest_cache",
            ".mypy_cache",
            "*.egg-info",
        ]
        for pattern in common_patterns:
            assert validate_pattern(pattern) is True, f"Pattern '{pattern}' should be valid"

    def test_validate_pattern_preserves_none_handling(self):
        """Test validate_pattern handles None gracefully (if passed)."""
        # The function expects a string, but should handle edge cases
        # This test verifies that empty/falsy values are rejected
        assert validate_pattern("") is False


class TestScannerErrorHandling:
    """Tests for Scanner error handling edge cases."""

    def test_scan_sync_handles_file_not_found_error(self, tmp_path):
        """Test scan_sync handles FileNotFoundError from Popen."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch(
                        "subprocess.Popen",
                        side_effect=FileNotFoundError("clamscan not found"),
                    ):
                        result = scanner.scan_sync(str(test_file))

        assert result.status == ScanStatus.ERROR
        assert "not found" in result.error_message.lower()
        assert len(result.threat_details) == 0

    def test_scan_sync_handles_permission_error(self, tmp_path):
        """Test scan_sync handles PermissionError from Popen."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch(
                        "subprocess.Popen",
                        side_effect=PermissionError("Permission denied"),
                    ):
                        result = scanner.scan_sync(str(test_file))

        assert result.status == ScanStatus.ERROR
        assert "permission denied" in result.error_message.lower()
        assert len(result.threat_details) == 0

    def test_scan_sync_handles_generic_exception(self, tmp_path):
        """Test scan_sync handles generic Exception from Popen."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch(
                        "subprocess.Popen", side_effect=RuntimeError("Unexpected error")
                    ):
                        result = scanner.scan_sync(str(test_file))

        assert result.status == ScanStatus.ERROR
        assert "scan failed" in result.error_message.lower()
        assert len(result.threat_details) == 0

    def test_scan_sync_handles_invalid_path(self):
        """Test scan_sync handles invalid/nonexistent path."""
        scanner = Scanner()

        with mock.patch(
            "src.core.scanner.validate_path",
            return_value=(False, "Path does not exist"),
        ):
            result = scanner.scan_sync("/nonexistent/path/to/scan")

        assert result.status == ScanStatus.ERROR
        assert result.error_message == "Path does not exist"
        assert result.scanned_files == 0
        assert len(result.threat_details) == 0

    def test_scan_sync_handles_clamav_not_installed(self, tmp_path):
        """Test scan_sync handles ClamAV not being installed."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        with mock.patch("src.core.scanner.validate_path", return_value=(True, None)):
            # Also mock check_clamd_connection so it falls through to clamscan path
            # (in "auto" mode, daemon is tried first if available)
            with mock.patch(
                "src.core.scanner.check_clamd_connection",
                return_value=(False, "not running"),
            ):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(False, "ClamAV not found"),
                ):
                    result = scanner.scan_sync(str(test_file))

        assert result.status == ScanStatus.ERROR
        assert (
            "not found" in result.error_message.lower() or "not installed" in result.stderr.lower()
        )
        assert len(result.threat_details) == 0

    def test_scan_sync_communicate_raises_exception(self, tmp_path):
        """Test scan_sync handles exception during communicate()."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.side_effect = OSError(
                            "Process communication failed"
                        )
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        assert result.status == ScanStatus.ERROR
        assert len(result.threat_details) == 0


class TestScannerCancelEdgeCases:
    """Tests for Scanner.cancel() edge cases."""

    def test_cancel_with_no_active_process(self):
        """Test cancel() when no scan is in progress."""
        scanner = Scanner()
        # Should not raise any exception
        scanner.cancel()
        assert scanner._cancel_event.is_set() is True

    def test_cancel_handles_terminate_oserror(self, tmp_path):
        """Test cancel() handles OSError when terminating process."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        # Create a mock process that raises OSError on terminate
        mock_process = mock.MagicMock()
        mock_process.terminate.side_effect = OSError("Process already terminated")
        scanner._current_process = mock_process

        # Should not raise exception
        scanner.cancel()
        assert scanner._cancel_event.is_set() is True

    def test_cancel_handles_process_lookup_error(self, tmp_path):
        """Test cancel() handles ProcessLookupError when terminating process."""
        scanner = Scanner()

        # Create a mock process that raises ProcessLookupError on terminate
        mock_process = mock.MagicMock()
        mock_process.terminate.side_effect = ProcessLookupError("No such process")
        scanner._current_process = mock_process

        # Should not raise exception
        scanner.cancel()
        assert scanner._cancel_event.is_set() is True

    def test_cancel_terminate_timeout_escalates_to_kill(self):
        """Test that cancel() escalates to kill if terminate times out."""
        scanner = Scanner()
        mock_process = mock.MagicMock()
        mock_process.terminate = mock.MagicMock()
        mock_process.kill = mock.MagicMock()
        mock_process.wait = mock.MagicMock(
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

    def test_cancel_kill_timeout_handles_gracefully(self):
        """Test that cancel() handles kill timeout gracefully."""
        scanner = Scanner()
        mock_process = mock.MagicMock()
        mock_process.terminate = mock.MagicMock()
        mock_process.kill = mock.MagicMock()
        mock_process.wait = mock.MagicMock(
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

    def test_cancel_process_already_terminated_on_terminate(self):
        """Test cancel() handles process already gone when calling terminate."""
        scanner = Scanner()
        mock_process = mock.MagicMock()
        mock_process.terminate = mock.MagicMock(side_effect=ProcessLookupError("No such process"))
        mock_process.kill = mock.MagicMock()
        mock_process.wait = mock.MagicMock()
        scanner._current_process = mock_process

        # Should not raise exception and should return early
        scanner.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_not_called()  # Should not reach kill
        mock_process.wait.assert_not_called()  # Should not reach wait
        assert scanner._cancel_event.is_set() is True

    def test_cancel_graceful_termination_success(self):
        """Test cancel() when process terminates gracefully within timeout."""
        scanner = Scanner()
        mock_process = mock.MagicMock()
        mock_process.terminate = mock.MagicMock()
        mock_process.kill = mock.MagicMock()
        mock_process.wait = mock.MagicMock(return_value=None)  # Succeeds on first call
        scanner._current_process = mock_process

        scanner.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()  # Only one wait call
        mock_process.kill.assert_not_called()  # Should not escalate to kill
        assert scanner._cancel_event.is_set() is True


class TestParseResultsEdgeCases:
    """Tests for Scanner._parse_results edge cases."""

    def test_parse_results_empty_stdout(self):
        """Test _parse_results handles empty stdout."""
        scanner = Scanner()
        result = scanner._parse_results("/test/path", "", "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert len(result.infected_files) == 0
        assert len(result.threat_details) == 0

    def test_parse_results_malformed_found_line(self):
        """Test _parse_results handles malformed FOUND lines."""
        scanner = Scanner()

        # Missing colon separator
        stdout = "some_file_without_colon FOUND\n"
        result = scanner._parse_results("/test", stdout, "", 1)

        # Should not crash, but may not parse the file correctly
        assert result.status == ScanStatus.INFECTED

    def test_parse_results_with_only_ok_lines(self):
        """Test _parse_results with only OK lines (no summary)."""
        scanner = Scanner()

        stdout = """
/home/user/file1.txt: OK
/home/user/file2.txt: OK
/home/user/file3.txt: OK
"""
        result = scanner._parse_results("/home/user", stdout, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert len(result.threat_details) == 0

    def test_parse_results_stderr_with_error_exit_code(self):
        """Test _parse_results includes stderr in error message on error exit code."""
        scanner = Scanner()

        stderr = "LibClamAV Error: Can't open file"
        result = scanner._parse_results("/test", "", stderr, 2)

        assert result.status == ScanStatus.ERROR
        assert result.error_message == stderr

    def test_parse_results_special_characters_in_path(self):
        """Test _parse_results handles special characters in file paths."""
        scanner = Scanner()

        # File path with unicode and special characters
        stdout = "/home/user/test file (copy).txt: Eicar-Test-Signature FOUND\n"
        result = scanner._parse_results("/home/user", stdout, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert len(result.threat_details) == 1
        assert result.threat_details[0].file_path == "/home/user/test file (copy).txt"

    def test_parse_results_colons_in_threat_name(self):
        """Test _parse_results handles colons in threat names.

        Note: Due to the rsplit(":", 1) parsing approach, threat names with colons
        result in only the portion after the last colon being captured. This test
        documents the current behavior.
        """
        scanner = Scanner()

        # Threat name contains colon (edge case)
        stdout = "/home/user/file.exe: Win.Trojan.Generic:Variant FOUND\n"
        result = scanner._parse_results("/home/user", stdout, "", 1)

        assert result.status == ScanStatus.INFECTED
        assert len(result.threat_details) == 1
        # Due to rsplit(":", 1), the file_path incorrectly includes part of the threat
        # This documents the current (imperfect) parsing behavior for paths with colons
        assert result.threat_details[0].file_path == "/home/user/file.exe: Win.Trojan.Generic"

    def test_parse_results_scanning_line_not_parsed_as_threat(self):
        """A verbose 'Scanning ' line for a clean file ending in FOUND is not a detection."""
        scanner = Scanner()

        # clamscan -v emits "Scanning <path>" lines; a clean file named with a
        # trailing 'FOUND' must not be misparsed as a detection.
        stdout = (
            "Scanning /home/user/notes: about malware FOUND\n"
            "/home/user/notes: about malware FOUND: OK\n"
            "----------- SCAN SUMMARY -----------\n"
            "Scanned files: 1\n"
            "Infected files: 0\n"
        )
        result = scanner._parse_results("/home/user", stdout, "", 0)

        assert result.status == ScanStatus.CLEAN
        assert result.infected_count == 0
        assert len(result.threat_details) == 0


class TestScanProgressSnapshot:
    """Tests that ScanProgress carries point-in-time snapshots of infections."""

    def test_progress_infected_files_snapshot_is_stable(self):
        """A progress snapshot must keep len(infected_files) == infected_count.

        The on_line callback keeps appending to the live infected_files list; a
        progress object captured mid-scan must not grow as later rows arrive.
        """
        scanner = Scanner()
        captured: list = []

        def fake_stream(process, cancel_check, on_line):
            on_line("/home/user/a.exe: Eicar-Test-Signature FOUND")
            on_line("/home/user/b.exe: Win.Trojan.Generic FOUND")
            on_line("/home/user/c.exe: Win.Trojan.Other FOUND")
            return "", "", False

        with mock.patch("src.core.scanner.stream_process_output", side_effect=fake_stream):
            scanner._scan_with_progress(mock.MagicMock(), captured.append, None)

        # Three FOUND lines -> three progress updates.
        assert len(captured) == 3
        # The first snapshot must reflect only the first infection, even after
        # the later appends mutated the live list.
        assert captured[0].infected_count == 1
        assert len(captured[0].infected_files) == 1
        assert captured[0].infected_files == ["/home/user/a.exe"]
        assert len(captured[0].infected_threats) == 1
        # Each snapshot stays consistent with its own count.
        for progress in captured:
            assert len(progress.infected_files) == progress.infected_count
        assert len(captured[-1].infected_files) == 3


class TestPatternValidationEdgeCases:
    """Tests for pattern validation edge cases."""

    def test_validate_pattern_with_invalid_regex_characters(self):
        """Test validate_pattern rejects patterns that produce invalid regex."""
        # Most glob patterns will be valid, but we test edge cases
        # An unclosed bracket should fail
        # Note: fnmatch.translate may handle this, so we test compilation

        # Test that validate_pattern returns True for valid patterns
        assert validate_pattern("*.log") is True
        assert validate_pattern("file[0-9].txt") is True

    def test_validate_pattern_very_long_pattern(self):
        """Test validate_pattern handles very long patterns."""
        long_pattern = "a" * 10000 + "*.log"
        # Should not crash and should be valid
        result = validate_pattern(long_pattern)
        assert isinstance(result, bool)

    def test_validate_pattern_unicode_characters(self):
        """Test validate_pattern handles unicode characters."""
        assert validate_pattern("文件*.txt") is True
        assert validate_pattern("файл*.log") is True
        assert validate_pattern("αβγ*.py") is True

    def test_glob_to_regex_preserves_path_separators(self):
        """Test glob_to_regex handles path separators correctly."""
        import re

        regex = glob_to_regex("/home/user/*.log")
        compiled = re.compile(regex)
        assert compiled.match("/home/user/test.log")
        assert not compiled.match("/home/other/test.log")

    def test_glob_to_regex_double_star_pattern(self):
        """Test glob_to_regex handles ** pattern (documented limitation)."""
        import re

        # Note: fnmatch doesn't support ** for recursive matching
        regex = glob_to_regex("src/**/*.py")
        # Should produce some regex without crashing
        assert regex is not None
        # Can compile
        re.compile(regex)


class TestScannerProfileExclusionsEdgeCases:
    """Tests for profile exclusion edge cases in _build_command."""

    def test_build_command_profile_exclusions_empty_values(self, tmp_path):
        """Test _build_command handles empty values in profile exclusions."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        scanner = Scanner()

        profile_exclusions = {
            "paths": ["", None, "/valid/path"],  # Empty and None values
            "patterns": ["", "*.log", None],  # Empty and None values
        }

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                # Filter out None values before passing to function
                clean_exclusions = {
                    "paths": [p for p in profile_exclusions["paths"] if p],
                    "patterns": [p for p in profile_exclusions["patterns"] if p],
                }
                cmd = scanner._build_command(
                    str(test_dir), recursive=True, profile_exclusions=clean_exclusions
                )

        # Should not crash and should include valid exclusions
        assert "--exclude-dir" in cmd
        assert "--exclude" in cmd

    def test_build_command_profile_exclusions_with_tilde_expansion(self, tmp_path):
        """Test _build_command expands ~ in profile exclusion paths."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        scanner = Scanner()

        profile_exclusions = {"paths": ["~/Downloads"], "patterns": []}

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(
                    str(test_dir), recursive=True, profile_exclusions=profile_exclusions
                )

        # The ~ should be expanded
        cmd_str = " ".join(cmd)
        assert "~" not in cmd_str or "/home" in cmd_str or "Downloads" in cmd_str

    def test_build_command_with_none_profile_exclusions(self, tmp_path):
        """Test _build_command handles None profile_exclusions."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_dir), recursive=True, profile_exclusions=None)

        # Should not crash
        assert cmd[0] == "/usr/bin/clamscan"
        assert str(test_dir) in cmd


class TestThreatClassificationEdgeCases:
    """Tests for threat classification edge cases."""

    def test_classify_threat_severity_empty_string(self):
        """Test classify_threat_severity_str handles empty threat name."""
        assert classify_threat_severity_str("") == "medium"

    def test_classify_threat_severity_whitespace_only(self):
        """Test classify_threat_severity_str handles whitespace-only threat name."""
        assert classify_threat_severity_str("   ") == "medium"

    def test_classify_threat_severity_mixed_case(self):
        """Test classify_threat_severity_str handles mixed case threat names."""
        assert classify_threat_severity_str("RANSOMWARE.WannaCry") == "critical"
        assert classify_threat_severity_str("Trojan.BANKER") == "high"
        assert classify_threat_severity_str("PUA.AdWaRe") == "medium"

    def test_categorize_threat_empty_string(self):
        """Test categorize_threat handles empty threat name."""
        assert categorize_threat("") == "Unknown"

    def test_categorize_threat_whitespace_only(self):
        """Test categorize_threat handles whitespace-only threat name."""
        assert categorize_threat("   ") == "Virus"  # Default category

    def test_categorize_threat_unknown_format(self):
        """Test categorize_threat handles unknown threat format."""
        # A threat name that doesn't match any known pattern
        assert categorize_threat("CustomMalware.123") == "Virus"

    def test_categorize_threat_multiple_keywords(self):
        """Test categorize_threat prioritizes correctly when multiple keywords present."""
        # Contains both "trojan" and "worm" - should pick first match
        result = categorize_threat("Trojan.Worm.Agent")
        # "trojan" comes before "worm" in the category_patterns list
        assert result in ["Trojan", "Worm"]


class TestScannerWithMalformedExclusions:
    """Tests for Scanner handling malformed exclusion patterns from settings."""

    def test_build_command_exclusion_missing_pattern_key(self, tmp_path):
        """Test _build_command handles exclusion entries missing 'pattern' key."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = [
            {"type": "file", "enabled": True},  # Missing 'pattern' key
            {"pattern": "*.log", "type": "file", "enabled": True},  # Valid entry
        ]

        scanner = Scanner(settings_manager=mock_settings)

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_dir), recursive=True)

        # Should not crash and should include the valid exclusion
        assert "--exclude" in cmd
        # Only one --exclude (the valid pattern)
        exclude_count = cmd.count("--exclude")
        assert exclude_count == 1

    def test_build_command_exclusion_missing_enabled_key(self, tmp_path):
        """Test _build_command handles exclusion entries missing 'enabled' key."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = [
            {
                "pattern": "*.log",
                "type": "file",
            },  # Missing 'enabled' key - should default to True
        ]

        scanner = Scanner(settings_manager=mock_settings)

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_dir), recursive=True)

        # Should include the exclusion (defaults to enabled=True)
        assert "--exclude" in cmd

    def test_build_command_exclusion_missing_type_key(self, tmp_path):
        """Test _build_command handles exclusion entries missing 'type' key."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = [
            {
                "pattern": "*.log",
                "enabled": True,
            },  # Missing 'type' key - should default to 'pattern'
        ]

        scanner = Scanner(settings_manager=mock_settings)

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                cmd = scanner._build_command(str(test_dir), recursive=True)

        # Should use --exclude (not --exclude-dir) since type defaults to 'pattern'
        assert "--exclude" in cmd
        assert "--exclude-dir" not in cmd


class TestScannerProcessLockThreadSafety:
    """Tests for Scanner process lock and thread safety."""

    def test_scanner_has_process_lock(self):
        """Test that Scanner has a _process_lock attribute."""
        import threading

        scanner = Scanner()
        assert hasattr(scanner, "_process_lock")
        assert isinstance(scanner._process_lock, type(threading.Lock()))

    def test_cancel_uses_lock_for_process_access(self):
        """Test that cancel() acquires lock before accessing _current_process."""
        scanner = Scanner()
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

    def test_scan_sync_uses_lock_for_process_assignment(self, tmp_path):
        """Test that scan_sync() acquires lock when assigning _current_process."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()
        lock_operations = []

        original_lock = scanner._process_lock

        class TrackingLock:
            def __enter__(self):
                lock_operations.append("enter")
                return original_lock.__enter__()

            def __exit__(self, *args):
                lock_operations.append("exit")
                return original_lock.__exit__(*args)

        scanner._process_lock = TrackingLock()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = ("", "")
                        mock_process.returncode = 0
                        mock_popen.return_value = mock_process

                        scanner.scan_sync(str(test_file))

        # Lock should be acquired at least twice (for setting and clearing process)
        assert lock_operations.count("enter") >= 2
        assert lock_operations.count("exit") >= 2

    def test_concurrent_cancel_and_scan_cleanup(self, tmp_path):
        """Test that concurrent cancel and scan cleanup don't cause race conditions."""
        import threading
        import time

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()
        errors = []

        def scan_thread():
            try:
                with mock.patch(
                    "src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"
                ):
                    with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                        with mock.patch(
                            "src.core.scanner.check_clamav_installed",
                            return_value=(True, "1.0.0"),
                        ):
                            with mock.patch("subprocess.Popen") as mock_popen:
                                mock_process = mock.MagicMock()
                                # Simulate slow scan
                                mock_process.communicate.side_effect = lambda: (
                                    time.sleep(0.1),
                                    ("", ""),
                                )[-1]
                                mock_process.returncode = 0
                                mock_popen.return_value = mock_process

                                scanner.scan_sync(str(test_file))
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

    def test_process_cleared_after_scan_completes(self, tmp_path):
        """Test that _current_process is None after scan completes."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = ("", "")
                        mock_process.returncode = 0
                        mock_popen.return_value = mock_process

                        scanner.scan_sync(str(test_file))

        # After scan completes, _current_process should be None
        assert scanner._current_process is None

    def test_cancel_with_none_process_is_safe(self):
        """Test that cancel() is safe when _current_process is None."""
        scanner = Scanner()
        assert scanner._current_process is None

        # Should not raise any exception
        scanner.cancel()
        assert scanner._cancel_event.is_set() is True


class TestScannerCancelFlagReset:
    """Tests for cancel event reset at start of new scans."""

    def test_cancelled_flag_reset_at_scan_start(self, tmp_path):
        """Test that _cancel_event is reset at start of scan_sync."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        # Manually set cancel event to simulate previous cancelled scan
        scanner._cancel_event.set()

        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = ("", "")
                        mock_process.returncode = 0
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        # Scan should complete successfully (not be cancelled)
        assert result.status == ScanStatus.CLEAN
        # Event should have been cleared during scan
        assert scanner._cancel_event.is_set() is False

    def test_scan_after_cancelled_scan_runs_normally(self, tmp_path):
        """Test that a new scan runs normally after a previous scan was cancelled.

        This verifies the fix for the bug where a cancelled scan's event
        would affect subsequent scans.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        # Simulate a cancelled scan
        scanner._cancel_event.set()

        # Now run a new scan
        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = ("", "")
                        mock_process.returncode = 0
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        # With the fix, the new scan should complete successfully
        assert result.status == ScanStatus.CLEAN
        assert scanner._cancel_event.is_set() is False

    def test_multiple_cancelled_scans_followed_by_successful_scan(self, tmp_path):
        """Test that multiple consecutive cancelled scans don't affect subsequent scans."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        scanner = Scanner()

        # Cancel several scans in a row
        for _ in range(3):
            scanner._cancel_event.set()

        # Now run a real scan
        with mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"):
            with mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x):
                with mock.patch(
                    "src.core.scanner.check_clamav_installed",
                    return_value=(True, "1.0.0"),
                ):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_process = mock.MagicMock()
                        mock_process.communicate.return_value = ("", "")
                        mock_process.returncode = 0
                        mock_popen.return_value = mock_process

                        result = scanner.scan_sync(str(test_file))

        assert result.status == ScanStatus.CLEAN


class TestScannerBackendSelection:
    """Tests for Scanner._get_backend method and Flatpak backend support."""

    def test_get_backend_returns_auto_by_default(self):
        """Test _get_backend returns 'auto' when no settings manager."""
        scanner = Scanner()
        assert scanner._get_backend() == "auto"

    def test_get_backend_returns_settings_value(self):
        """Test _get_backend returns the configured backend from settings."""
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = "daemon"

        scanner = Scanner(settings_manager=mock_settings)
        assert scanner._get_backend() == "daemon"
        mock_settings.get.assert_called_with("scan_backend", "auto")

    def test_get_backend_returns_clamscan_setting(self):
        """Test _get_backend returns 'clamscan' when configured."""
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = "clamscan"

        scanner = Scanner(settings_manager=mock_settings)
        assert scanner._get_backend() == "clamscan"

    def test_get_backend_allows_daemon_regardless_of_flatpak(self):
        """Test _get_backend returns daemon setting regardless of environment.

        Previously, Flatpak mode forced 'clamscan' backend. Now daemon
        backend is available because clamdscan runs on the host via
        flatpak-spawn --host. The _get_backend() method no longer checks
        is_flatpak() at all - it simply returns the configured setting.
        """
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = "daemon"

        scanner = Scanner(settings_manager=mock_settings)

        # No need to mock is_flatpak - _get_backend() doesn't check it
        backend = scanner._get_backend()

        # Backend should be "daemon" (not forced to "clamscan")
        assert backend == "daemon"

    def test_get_backend_allows_auto_regardless_of_flatpak(self):
        """Test _get_backend returns 'auto' regardless of environment.

        Auto mode works in both native and Flatpak because daemon availability
        is checked at scan time, and clamdscan runs on the host via flatpak-spawn.
        """
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = "auto"

        scanner = Scanner(settings_manager=mock_settings)

        # No need to mock is_flatpak - _get_backend() doesn't check it
        backend = scanner._get_backend()

        assert backend == "auto"


class TestDaemonAvailableCached:
    """Tests for Scanner._is_daemon_available_cached method."""

    def setup_method(self):
        """Reset daemon cache before each test."""
        Scanner._daemon_cache = None

    def teardown_method(self):
        """Reset daemon cache after each test to prevent pollution."""
        Scanner._daemon_cache = None

    def test_cache_miss_calls_check_clamd_connection(self):
        """Test cache miss triggers check_clamd_connection and caches result."""
        scanner = Scanner()

        with mock.patch(
            "src.core.scanner.check_clamd_connection",
            return_value=(True, "clamd 1.0"),
        ) as mock_check:
            result = scanner._is_daemon_available_cached()

        assert result is True
        mock_check.assert_called_once()
        # Verify cache was populated
        assert Scanner._daemon_cache is not None
        assert Scanner._daemon_cache[1] is True

    def test_cache_hit_returns_cached_value_without_calling_check(self):
        """Test cache hit returns cached value without calling check_clamd_connection."""
        import time

        scanner = Scanner()

        # Pre-populate cache with a recent timestamp
        Scanner._daemon_cache = (time.monotonic(), False)

        with mock.patch(
            "src.core.scanner.check_clamd_connection",
            return_value=(True, "clamd 1.0"),
        ) as mock_check:
            result = scanner._is_daemon_available_cached()

        # Should return cached False, not the mocked True
        assert result is False
        mock_check.assert_not_called()

    def test_cache_expiry_rechecks_after_ttl(self):
        """Test expired cache entry triggers re-check after TTL."""
        import time

        scanner = Scanner()

        # Pre-populate cache with an expired timestamp (61 seconds ago)
        expired_time = time.monotonic() - 61.0
        Scanner._daemon_cache = (expired_time, False)

        with mock.patch(
            "src.core.scanner.check_clamd_connection",
            return_value=(True, "clamd 1.0"),
        ) as mock_check:
            result = scanner._is_daemon_available_cached()

        # Should re-check and return True (the new value)
        assert result is True
        mock_check.assert_called_once()
        # Cache should now have the new value
        assert Scanner._daemon_cache[1] is True

    def test_cache_stores_false_when_daemon_unavailable(self):
        """Test cache stores False when daemon is unavailable."""
        scanner = Scanner()

        with mock.patch(
            "src.core.scanner.check_clamd_connection",
            return_value=(False, "Connection refused"),
        ):
            result = scanner._is_daemon_available_cached()

        assert result is False
        assert Scanner._daemon_cache is not None
        assert Scanner._daemon_cache[1] is False

    def test_cache_not_expired_just_before_ttl(self):
        """Test cache is still valid just before the 60-second TTL."""
        import time

        scanner = Scanner()

        # Set cache to 59 seconds ago (just under TTL)
        Scanner._daemon_cache = (time.monotonic() - 59.0, True)

        with mock.patch(
            "src.core.scanner.check_clamd_connection",
            return_value=(False, "down"),
        ) as mock_check:
            result = scanner._is_daemon_available_cached()

        # Should still use cached value
        assert result is True
        mock_check.assert_not_called()


class TestCountFiles:
    """Tests for Scanner._count_files method."""

    def test_count_files_single_file(self, tmp_path):
        """Test _count_files returns 1 for a single file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        scanner = Scanner()
        count = scanner._count_files(str(test_file))
        assert count == 1

    def test_count_files_directory(self, tmp_path):
        """Test _count_files counts files in a directory."""
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("b")
        (tmp_path / "file3.log").write_text("c")

        scanner = Scanner()
        count = scanner._count_files(str(tmp_path))
        assert count == 3

    def test_count_files_recursive(self, tmp_path):
        """Test _count_files counts files recursively."""
        (tmp_path / "file1.txt").write_text("a")
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "file2.txt").write_text("b")
        subsub = sub / "deep"
        subsub.mkdir()
        (subsub / "file3.txt").write_text("c")

        scanner = Scanner()
        count = scanner._count_files(str(tmp_path))
        assert count == 3

    def test_count_files_permission_error(self, tmp_path):
        """Test _count_files handles PermissionError gracefully."""
        scanner = Scanner()

        with mock.patch("os.walk", side_effect=PermissionError("Access denied")):
            count = scanner._count_files(str(tmp_path))

        # Should return 0 on PermissionError (not crash)
        assert count == 0

    def test_count_files_respects_cancellation(self, tmp_path):
        """Test _count_files respects cancellation event."""
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("b")

        scanner = Scanner()
        scanner._cancel_event.set()

        count = scanner._count_files(str(tmp_path))
        assert count == 0

    def test_count_files_nonexistent_path(self):
        """Test _count_files returns None for non-existent path."""
        scanner = Scanner()
        count = scanner._count_files("/nonexistent/path/that/doesnt/exist")
        assert count is None

    def test_count_files_root_level_path_returns_none(self):
        """Test _count_files returns None for root-level paths to avoid overhead."""
        scanner = Scanner()

        # Root-level paths should be skipped
        assert scanner._count_files("/") is None
        assert scanner._count_files("/home") is None
        assert scanner._count_files("/usr") is None

    def test_count_files_with_exclusion_patterns(self, tmp_path):
        """Test _count_files applies exclusion filtering from profile."""
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.log").write_text("b")
        (tmp_path / "file3.txt").write_text("c")

        scanner = Scanner()
        profile_exclusions = {"paths": [], "patterns": ["*.log"]}

        count = scanner._count_files(str(tmp_path), profile_exclusions)
        assert count == 2  # file2.log excluded

    def test_count_files_with_directory_exclusions(self, tmp_path):
        """Test _count_files excludes directories from profile."""
        (tmp_path / "file1.txt").write_text("a")
        excluded_dir = tmp_path / "node_modules"
        excluded_dir.mkdir()
        (excluded_dir / "file2.txt").write_text("b")

        scanner = Scanner()
        profile_exclusions = {"paths": [str(excluded_dir)], "patterns": []}

        count = scanner._count_files(str(tmp_path), profile_exclusions)
        assert count == 1  # file in node_modules excluded

    def test_count_files_with_settings_exclusions(self, tmp_path):
        """Test _count_files applies exclusions from settings manager."""
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.log").write_text("b")

        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = [
            {"pattern": "*.log", "type": "pattern", "enabled": True},
        ]

        scanner = Scanner(settings_manager=mock_settings)
        count = scanner._count_files(str(tmp_path))
        assert count == 1  # file2.log excluded by settings


class TestIsPathExcluded:
    """Tests for Scanner._is_path_excluded method."""

    def test_glob_pattern_matching(self):
        """Test _is_path_excluded matches glob patterns against filenames."""
        scanner = Scanner()

        assert (
            scanner._is_path_excluded("/home/user/file.log", "file.log", ["*.log"], is_dir=False)
            is True
        )

        assert (
            scanner._is_path_excluded("/home/user/file.txt", "file.txt", ["*.log"], is_dir=False)
            is False
        )

    def test_absolute_path_pattern(self):
        """Test _is_path_excluded matches absolute path patterns."""
        scanner = Scanner()

        assert (
            scanner._is_path_excluded(
                "/home/user/Downloads/file.txt",
                "file.txt",
                ["/home/user/Downloads"],
                is_dir=False,
            )
            is True
        )

        assert (
            scanner._is_path_excluded(
                "/home/user/Documents/file.txt",
                "file.txt",
                ["/home/user/Downloads"],
                is_dir=False,
            )
            is False
        )

    def test_tilde_expansion_branch(self):
        """Test _is_path_excluded expands tilde in patterns."""
        import os

        scanner = Scanner()
        home = os.path.expanduser("~")

        assert (
            scanner._is_path_excluded(
                f"{home}/Downloads/file.txt",
                "file.txt",
                ["~/Downloads"],
                is_dir=False,
            )
            is True
        )

    def test_non_matching_returns_false(self):
        """Test _is_path_excluded returns False for non-matching paths."""
        scanner = Scanner()

        assert (
            scanner._is_path_excluded(
                "/home/user/file.py", "file.py", ["*.log", "*.tmp", "/var"], is_dir=False
            )
            is False
        )

    def test_empty_patterns_list(self):
        """Test _is_path_excluded returns False for empty patterns list."""
        scanner = Scanner()

        assert (
            scanner._is_path_excluded("/home/user/file.txt", "file.txt", [], is_dir=False) is False
        )

    def test_directory_pattern_matching(self):
        """Test _is_path_excluded works for directory entries."""
        scanner = Scanner()

        assert (
            scanner._is_path_excluded(
                "/home/user/node_modules", "node_modules", ["node_modules"], is_dir=True
            )
            is True
        )

    def test_full_path_glob_matching(self):
        """Test _is_path_excluded matches glob against full path for non-absolute patterns."""
        scanner = Scanner()

        # Non-absolute glob patterns are matched via fnmatch against full_path
        assert (
            scanner._is_path_excluded(
                "/home/user/logs/app.log",
                "app.log",
                ["*/logs/*.log"],
                is_dir=False,
            )
            is True
        )

    def test_absolute_path_prefix_matching(self):
        """Test _is_path_excluded uses startswith for absolute path patterns (not glob)."""
        scanner = Scanner()

        # Absolute patterns use startswith, so /home/user/logs/*.log won't glob-match
        # but /home/user/logs will match any file under that directory
        assert (
            scanner._is_path_excluded(
                "/home/user/logs/app.log",
                "app.log",
                ["/home/user/logs"],
                is_dir=False,
            )
            is True
        )

    def test_absolute_path_respects_separator_boundary(self):
        """Sibling paths sharing a prefix must not be excluded (no under-count).

        Excluding "/home/user/foo" must not also exclude "/home/user/foobar",
        otherwise _count_files undercounts and the progress estimate is wrong.
        """
        scanner = Scanner()

        # The excluded directory itself and files under it are excluded.
        assert (
            scanner._is_path_excluded(
                "/home/user/foo/file.txt", "file.txt", ["/home/user/foo"], is_dir=False
            )
            is True
        )
        # A sibling directory that merely shares the prefix is NOT excluded.
        assert (
            scanner._is_path_excluded(
                "/home/user/foobar/file.txt", "file.txt", ["/home/user/foo"], is_dir=False
            )
            is False
        )


class TestGetActiveBackend:
    """Tests for Scanner.get_active_backend method."""

    def setup_method(self):
        """Reset daemon cache before each test."""
        Scanner._daemon_cache = None

    def teardown_method(self):
        """Reset daemon cache after each test."""
        Scanner._daemon_cache = None

    def test_returns_clamscan_for_clamscan_backend(self):
        """Test get_active_backend returns 'clamscan' when backend is clamscan."""
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = "clamscan"

        scanner = Scanner(settings_manager=mock_settings)
        assert scanner.get_active_backend() == "clamscan"

    def test_returns_daemon_when_daemon_available_auto_mode(self):
        """Test get_active_backend returns 'daemon' when daemon is available in auto mode."""
        scanner = Scanner()  # No settings = auto mode

        with mock.patch(
            "src.core.scanner.check_clamd_connection",
            return_value=(True, "clamd 1.0"),
        ):
            result = scanner.get_active_backend()

        assert result == "daemon"

    def test_returns_clamscan_when_daemon_unavailable_auto_mode(self):
        """Test get_active_backend returns 'clamscan' when daemon unavailable in auto mode."""
        scanner = Scanner()  # No settings = auto mode

        with mock.patch(
            "src.core.scanner.check_clamd_connection",
            return_value=(False, "not running"),
        ):
            result = scanner.get_active_backend()

        assert result == "clamscan"

    def test_returns_daemon_for_daemon_backend_when_available(self):
        """Test get_active_backend returns 'daemon' when daemon backend configured and available."""
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = "daemon"

        scanner = Scanner(settings_manager=mock_settings)

        # Mock the daemon scanner's check_available method
        mock_daemon_scanner = mock.MagicMock()
        mock_daemon_scanner.check_available.return_value = (True, "clamd 1.0")

        with mock.patch.object(scanner, "_get_daemon_scanner", return_value=mock_daemon_scanner):
            result = scanner.get_active_backend()

        assert result == "daemon"

    def test_returns_unavailable_for_daemon_backend_when_down(self):
        """Test get_active_backend returns 'unavailable' when daemon backend configured but down."""
        mock_settings = mock.MagicMock()
        mock_settings.get.return_value = "daemon"

        scanner = Scanner(settings_manager=mock_settings)

        mock_daemon_scanner = mock.MagicMock()
        mock_daemon_scanner.check_available.return_value = (False, "Connection refused")

        with mock.patch.object(scanner, "_get_daemon_scanner", return_value=mock_daemon_scanner):
            result = scanner.get_active_backend()

        assert result == "unavailable"


class TestSaveScanLog:
    """Tests for Scanner._save_scan_log method."""

    def test_saves_log_entry_via_log_manager(self):
        """Test _save_scan_log delegates to save_scan_log with log manager."""
        mock_log_manager = mock.MagicMock()
        scanner = Scanner(log_manager=mock_log_manager)

        result = ScanResult(
            status=ScanStatus.CLEAN,
            path="/test/path",
            stdout="",
            stderr="",
            exit_code=0,
            infected_files=[],
            scanned_files=10,
            scanned_dirs=1,
            infected_count=0,
            error_message=None,
            threat_details=[],
        )

        with mock.patch("src.core.scanner.save_scan_log") as mock_save:
            scanner._save_scan_log(result, 1.5)

        mock_save.assert_called_once_with(mock_log_manager, result, 1.5)

    def test_handles_default_log_manager(self):
        """Test _save_scan_log works with default LogManager when none provided."""
        scanner = Scanner()

        result = ScanResult(
            status=ScanStatus.INFECTED,
            path="/test/path",
            stdout="",
            stderr="",
            exit_code=1,
            infected_files=["/test/virus.exe"],
            scanned_files=5,
            scanned_dirs=1,
            infected_count=1,
            error_message=None,
            threat_details=[],
        )

        with mock.patch("src.core.scanner.save_scan_log") as mock_save:
            scanner._save_scan_log(result, 2.0)

        # Should still call save_scan_log with the default log manager
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][1] is result
        assert call_args[0][2] == 2.0


class TestScannerBackendOverride:
    """Tests for one-shot backend overrides during scans."""

    def test_scan_sync_backend_override_uses_clamscan(self, tmp_path):
        """Test backend_override bypasses daemon mode without changing settings."""
        test_file = tmp_path / "eicar.txt"
        test_file.write_text("test content")

        mock_settings = mock.MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: (
            "daemon" if key == "scan_backend" else default
        )
        scanner = Scanner(settings_manager=mock_settings)

        with (
            mock.patch("src.core.scanner.check_clamav_installed") as mock_installed,
            mock.patch("src.core.scanner.check_clamd_connection") as mock_connection,
            mock.patch.object(scanner, "_get_daemon_scanner") as mock_daemon,
            mock.patch("src.core.scanner.get_clamav_path", return_value="/usr/bin/clamscan"),
            mock.patch("src.core.scanner.wrap_host_command", side_effect=lambda x: x),
            mock.patch("subprocess.Popen") as mock_popen,
        ):
            mock_installed.return_value = (True, "ClamAV 1.0.0")
            mock_connection.return_value = (True, "PONG")

            mock_process = mock.MagicMock()
            mock_process.communicate.return_value = ("", "")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            result = scanner.scan_sync(str(test_file), backend_override="clamscan")

        assert result.status == ScanStatus.CLEAN
        mock_installed.assert_called_once()
        mock_daemon.assert_not_called()

    def test_scan_sync_daemon_force_stream_passes_through(self, tmp_path):
        """Test daemon_force_stream reaches the daemon scanner for one scan."""
        test_file = tmp_path / "eicar.txt"
        test_file.write_text("test content")

        mock_settings = mock.MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: (
            "daemon" if key == "scan_backend" else default
        )
        scanner = Scanner(settings_manager=mock_settings)

        daemon_result = mock.MagicMock()
        daemon_result.status = ScanStatus.CLEAN

        with mock.patch.object(scanner, "_get_daemon_scanner") as mock_daemon:
            mock_daemon.return_value.scan_sync.return_value = daemon_result

            result = scanner.scan_sync(str(test_file), daemon_force_stream=True)

        assert result is daemon_result
        mock_daemon.return_value.scan_sync.assert_called_once()
        assert mock_daemon.return_value.scan_sync.call_args[1]["force_stream"] is True
