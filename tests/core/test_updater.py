# ClamUI Updater Tests
"""
Comprehensive unit tests for the freshclam updater module.

Tests cover:
- get_pkexec_path() function
- UpdateStatus enum values
- UpdateResult dataclass and properties
- FreshclamUpdater class methods including async operations
- Force update backup/restore methods
"""

import os
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def updater_module():
    """Import updater module and provide mocked GLib for async tests."""
    from src.core.updater import (
        FreshclamUpdater,
        UpdateResult,
        UpdateStatus,
        get_pkexec_path,
    )

    # Create mock GLib for async callback testing
    mock_glib = MagicMock()
    mock_glib.idle_add = MagicMock(side_effect=lambda cb, *args: cb(*args))

    yield {
        "FreshclamUpdater": FreshclamUpdater,
        "UpdateResult": UpdateResult,
        "UpdateStatus": UpdateStatus,
        "get_pkexec_path": get_pkexec_path,
        "glib": mock_glib,
    }


# =============================================================================
# get_pkexec_path() Tests
# =============================================================================


class TestGetPkexecPath:
    """Tests for the get_pkexec_path utility function."""

    def test_returns_path_when_pkexec_available(self, updater_module):
        """Test returns path when pkexec is found."""
        get_pkexec_path = updater_module["get_pkexec_path"]
        with patch("src.core.updater.which_host_command", return_value="/usr/bin/pkexec"):
            result = get_pkexec_path()
            assert result == "/usr/bin/pkexec"

    def test_returns_none_when_pkexec_not_found(self, updater_module):
        """Test returns None when pkexec is not found."""
        get_pkexec_path = updater_module["get_pkexec_path"]
        with patch("src.core.updater.which_host_command", return_value=None):
            result = get_pkexec_path()
            assert result is None


# =============================================================================
# UpdateStatus Enum Tests
# =============================================================================


class TestUpdateStatusEnum:
    """Tests for the UpdateStatus enum."""

    def test_all_status_levels_defined(self, updater_module):
        """Verify all expected status levels are defined."""
        UpdateStatus = updater_module["UpdateStatus"]
        assert hasattr(UpdateStatus, "SUCCESS")
        assert hasattr(UpdateStatus, "UP_TO_DATE")
        assert hasattr(UpdateStatus, "ERROR")
        assert hasattr(UpdateStatus, "CANCELLED")

    def test_status_values(self, updater_module):
        """Verify status string values."""
        UpdateStatus = updater_module["UpdateStatus"]
        assert UpdateStatus.SUCCESS.value == "success"
        assert UpdateStatus.UP_TO_DATE.value == "up_to_date"
        assert UpdateStatus.ERROR.value == "error"
        assert UpdateStatus.CANCELLED.value == "cancelled"

    def test_status_count(self, updater_module):
        """Verify exactly 4 status levels defined."""
        UpdateStatus = updater_module["UpdateStatus"]
        assert len(UpdateStatus) == 4


# =============================================================================
# UpdateResult Dataclass Tests
# =============================================================================


class TestUpdateResultDataclass:
    """Tests for the UpdateResult dataclass."""

    def test_is_success_returns_true_for_success(self, updater_module):
        """Test is_success property returns True for SUCCESS status."""
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        result = UpdateResult(
            status=UpdateStatus.SUCCESS,
            stdout="",
            stderr="",
            exit_code=0,
            databases_updated=1,
            error_message=None,
        )
        assert result.is_success is True

    def test_is_success_returns_true_for_up_to_date(self, updater_module):
        """Test is_success property returns True for UP_TO_DATE status."""
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        result = UpdateResult(
            status=UpdateStatus.UP_TO_DATE,
            stdout="",
            stderr="",
            exit_code=0,
            databases_updated=0,
            error_message=None,
        )
        assert result.is_success is True

    def test_is_success_returns_false_for_error(self, updater_module):
        """Test is_success property returns False for ERROR status."""
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        result = UpdateResult(
            status=UpdateStatus.ERROR,
            stdout="",
            stderr="Error occurred",
            exit_code=1,
            databases_updated=0,
            error_message="Error occurred",
        )
        assert result.is_success is False

    def test_is_success_returns_false_for_cancelled(self, updater_module):
        """Test is_success property returns False for CANCELLED status."""
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        result = UpdateResult(
            status=UpdateStatus.CANCELLED,
            stdout="",
            stderr="",
            exit_code=0,
            databases_updated=0,
            error_message="Cancelled",
        )
        assert result.is_success is False

    def test_has_error_returns_true_only_for_error(self, updater_module):
        """Test has_error property returns True only for ERROR status."""
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]

        error_result = UpdateResult(
            status=UpdateStatus.ERROR,
            stdout="",
            stderr="",
            exit_code=1,
            databases_updated=0,
            error_message="Error",
        )
        assert error_result.has_error is True

        success_result = UpdateResult(
            status=UpdateStatus.SUCCESS,
            stdout="",
            stderr="",
            exit_code=0,
            databases_updated=1,
            error_message=None,
        )
        assert success_result.has_error is False

        cancelled_result = UpdateResult(
            status=UpdateStatus.CANCELLED,
            stdout="",
            stderr="",
            exit_code=0,
            databases_updated=0,
            error_message="Cancelled",
        )
        assert cancelled_result.has_error is False


# =============================================================================
# FreshclamUpdater Initialization Tests
# =============================================================================


class TestFreshclamUpdaterInit:
    """Tests for FreshclamUpdater initialization."""

    def test_init_with_custom_log_manager(self, updater_module):
        """Test initialization with custom LogManager."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()
        updater = FreshclamUpdater(log_manager=mock_log_manager)
        assert updater._log_manager is mock_log_manager

    def test_init_sets_process_to_none(self, updater_module):
        """Test initialization sets _current_process to None."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        assert updater._current_process is None

    def test_init_sets_cancelled_to_false(self, updater_module):
        """Test initialization sets _update_cancelled to False."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        assert updater._update_cancelled is False


# =============================================================================
# FreshclamUpdater.check_available() Tests
# =============================================================================


class TestFreshclamUpdaterCheckAvailable:
    """Tests for FreshclamUpdater.check_available()."""

    def test_returns_true_and_version_when_installed(self, updater_module):
        """Test returns (True, version) when freshclam is installed."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            updater = FreshclamUpdater(log_manager=MagicMock())
            is_available, version = updater.check_available()
            assert is_available is True
            assert version == "1.0.0"

    def test_returns_false_and_error_when_not_installed(self, updater_module):
        """Test returns (False, error) when freshclam is not installed."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch(
            "src.core.updater.check_freshclam_installed",
            return_value=(False, "freshclam not found"),
        ):
            updater = FreshclamUpdater(log_manager=MagicMock())
            is_available, error = updater.check_available()
            assert is_available is False
            assert error == "freshclam not found"


# =============================================================================
# FreshclamUpdater._build_command() Tests
# =============================================================================


class TestFreshclamUpdaterBuildCommand:
    """Tests for FreshclamUpdater._build_command()."""

    def test_build_command_with_pkexec(self, updater_module):
        """Test command includes pkexec when available (non-Flatpak)."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("src.core.updater.get_freshclam_path", return_value="/usr/bin/freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value="/usr/bin/pkexec"):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        updater = FreshclamUpdater(log_manager=MagicMock())
                        cmd = updater._build_command()
                        assert cmd[0] == "/usr/bin/pkexec"
                        assert cmd[1] == "/usr/bin/freshclam"
                        assert "--verbose" in cmd

    def test_build_command_without_pkexec(self, updater_module):
        """Test command uses freshclam directly when pkexec not available (non-Flatpak)."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("src.core.updater.get_freshclam_path", return_value="/usr/bin/freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        updater = FreshclamUpdater(log_manager=MagicMock())
                        cmd = updater._build_command()
                        assert cmd[0] == "/usr/bin/freshclam"
                        assert "--verbose" in cmd

    def test_build_command_uses_wrap_host_command(self, updater_module):
        """Test command is wrapped for Flatpak compatibility."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command") as mock_wrap:
                        mock_wrap.return_value = [
                            "flatpak-spawn",
                            "--host",
                            "freshclam",
                            "--verbose",
                        ]
                        updater = FreshclamUpdater(log_manager=MagicMock())
                        cmd = updater._build_command()
                        mock_wrap.assert_called_once()
                        assert cmd[0] == "flatpak-spawn"

    def test_build_command_flatpak_uses_host_freshclam(self, updater_module):
        """Test Flatpak mode uses host freshclam without generated sandbox config."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch("src.core.updater.get_freshclam_path", return_value="/usr/bin/freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch(
                        "src.core.updater.wrap_host_command",
                        side_effect=lambda x: ["flatpak-spawn", "--host", *x],
                    ):
                        updater = FreshclamUpdater(log_manager=MagicMock())
                        cmd = updater._build_command()
                        assert cmd == [
                            "flatpak-spawn",
                            "--host",
                            "/usr/bin/freshclam",
                            "--verbose",
                        ]
                        assert "--config-file" not in cmd

    def test_build_command_with_force_flag(self, updater_module):
        """Test force command stages downloads and passes freshclam as positional data."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("src.core.updater.get_freshclam_path", return_value="/usr/bin/freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        updater = FreshclamUpdater(log_manager=MagicMock())
                        cmd = updater._build_command(force=True)

        assert cmd[0] == "sh"
        assert cmd[1] == "-c"
        shell_script = cmd[2]
        assert 'staging=$(mktemp -d "$d/.clamui-force-update.XXXXXX")' in shell_script
        assert '--datadir="$staging"' in shell_script
        assert '"$1"' in shell_script
        assert "/usr/bin/freshclam" not in shell_script
        assert cmd[3] == "clamui-force-update"
        assert cmd[4] == "/usr/bin/freshclam"
        assert "--no-dns" not in shell_script

    def test_build_command_without_force_flag(self, updater_module):
        """Test command does not include --no-dns flag when force=False (default)."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("src.core.updater.get_freshclam_path", return_value="/usr/bin/freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        updater = FreshclamUpdater(log_manager=MagicMock())
                        cmd = updater._build_command(force=False)
                        assert cmd[0] == "/usr/bin/freshclam"
                        assert "--verbose" in cmd
                        assert "--no-dns" not in cmd

    def test_build_command_force_with_pkexec_no_shell_injection(self, updater_module):
        """Test force+pkexec path passes freshclam as positional arg, not interpolated."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.get_freshclam_path",
                return_value="/usr/bin/freshclam",
            ):
                with patch(
                    "src.core.updater.get_pkexec_path",
                    return_value="/usr/bin/pkexec",
                ):
                    with patch(
                        "src.core.updater.wrap_host_command",
                        side_effect=lambda x: x,
                    ):
                        updater = FreshclamUpdater(log_manager=MagicMock())
                        cmd = updater._build_command(force=True)
                        # Must use sh -c with a constant shell script
                        assert cmd[0] == "/usr/bin/pkexec"
                        assert cmd[1] == "sh"
                        assert cmd[2] == "-c"
                        # The shell script string (cmd[3]) must NOT contain
                        # the freshclam path -- it should use "$1" instead
                        shell_script = cmd[3]
                        assert "/usr/bin/freshclam" not in shell_script
                        assert '"$1"' in shell_script
                        # freshclam path must be passed as a separate positional arg
                        assert "/usr/bin/freshclam" in cmd[4:]

    def test_build_command_force_with_pkexec_metachar_path(self, updater_module):
        """Test force+pkexec is safe even if freshclam path has shell metacharacters."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        malicious_path = "/usr/bin/freshclam; rm -rf /"
        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.get_freshclam_path",
                return_value=malicious_path,
            ):
                with patch(
                    "src.core.updater.get_pkexec_path",
                    return_value="/usr/bin/pkexec",
                ):
                    with patch(
                        "src.core.updater.wrap_host_command",
                        side_effect=lambda x: x,
                    ):
                        updater = FreshclamUpdater(log_manager=MagicMock())
                        cmd = updater._build_command(force=True)
                        # The shell script must be a constant string
                        shell_script = cmd[3]
                        assert malicious_path not in shell_script
                        # The malicious path is passed as a data argument, not code
                        assert malicious_path in cmd[4:]


# =============================================================================
# FreshclamUpdater._parse_results() Tests
# =============================================================================


class TestFreshclamUpdaterParseResults:
    """Tests for FreshclamUpdater._parse_results()."""

    def test_parse_success_with_updates(self, updater_module):
        """Test parsing successful update with database updates."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        stdout = """
daily.cvd updated (version: 27150, sigs: 2050000, f-level: 90, builder: virusdb)
main.cvd updated (version: 62, sigs: 6500000, f-level: 90, builder: virusdb)
"""
        updater = FreshclamUpdater(log_manager=MagicMock())
        result = updater._parse_results(stdout, "", 0)
        assert result.status == UpdateStatus.SUCCESS
        assert result.databases_updated == 2
        assert result.error_message is None

    def test_parse_up_to_date(self, updater_module):
        """Test parsing when database is already up-to-date."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        stdout = """
daily.cvd database is up-to-date (version: 27150, sigs: 2050000, f-level: 90, builder: virusdb)
main.cvd database is up-to-date (version: 62, sigs: 6500000, f-level: 90, builder: virusdb)
"""
        updater = FreshclamUpdater(log_manager=MagicMock())
        result = updater._parse_results(stdout, "", 0)
        assert result.status == UpdateStatus.UP_TO_DATE
        assert result.databases_updated == 0
        assert result.error_message is None

    def test_parse_error_code(self, updater_module):
        """Test parsing error with non-zero code."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        result = updater._parse_results("", "Error occurred", 1)
        assert result.status == UpdateStatus.ERROR
        assert result.error_message is not None

    def test_parse_mixed_updates_and_up_to_date(self, updater_module):
        """Test parsing when some databases updated, some up-to-date."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        stdout = """
daily.cvd updated (version: 27150, sigs: 2050000, f-level: 90, builder: virusdb)
main.cvd database is up-to-date (version: 62, sigs: 6500000, f-level: 90, builder: virusdb)
"""
        updater = FreshclamUpdater(log_manager=MagicMock())
        result = updater._parse_results(stdout, "", 0)
        assert result.status == UpdateStatus.SUCCESS
        assert result.databases_updated == 1

    def test_parse_partial_progress_with_database_specific_rate_limits(self, updater_module):
        """Test parsing preserves per-database rate limit details."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        stdout = """
daily.cvd updated (version: 27150, sigs: 2050000, f-level: 90, builder: virusdb)
main.cvd database is up-to-date (version: 62, sigs: 6500000, f-level: 90, builder: virusdb)
bytecode.cvd database available for download (remote version: 333, local version: 332)
WARNING: FreshClam received error code 429 from the ClamAV CDN.
WARNING: You are on cool-down until after: 2026-03-06 10:15:00
WARNING: Can't download bytecode.cvd from https://database.clamav.net/bytecode.cvd
WARNING: FreshClam failed to update bytecode.cvd
"""
        updater = FreshclamUpdater(log_manager=MagicMock())
        result = updater._parse_results(stdout, "", 1)

        assert result.status == UpdateStatus.ERROR
        assert result.databases_updated == 1
        assert result.updated_databases == ["daily.cvd"]
        assert result.up_to_date_databases == ["main.cvd"]
        assert result.rate_limited_databases == {"bytecode.cvd": "2026-03-06 10:15:00"}
        assert "partially completed" in result.error_message.lower()
        assert "bytecode.cvd until 2026-03-06 10:15:00" in result.error_message


# =============================================================================
# FreshclamUpdater._extract_error_message() Tests
# =============================================================================


class TestFreshclamUpdaterExtractErrorMessage:
    """Tests for FreshclamUpdater._extract_error_message()."""

    def test_auth_cancelled_code_126(self, updater_module):
        """Test code 126 returns auth cancelled message."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("", "", 126)
        assert "Authentication cancelled" in msg

    def test_auth_failed_code_127_with_pkexec(self, updater_module):
        """Test code 127 with pkexec in output returns auth failed message."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("pkexec error", "", 127)
        assert "Authorization failed" in msg

    def test_not_authorized_in_output(self, updater_module):
        """Test 'not authorized' in output returns auth message."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("", "not authorized to perform this action", 1)
        assert "Authorization failed" in msg

    def test_locked_in_output(self, updater_module):
        """Test 'locked' in output returns lock message."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("Database is locked", "", 1)
        assert "locked" in msg.lower()

    def test_permission_denied_in_output(self, updater_module):
        """Test 'permission denied' in output returns permission message."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("", "permission denied", 1)
        assert "Permission denied" in msg

    def test_connection_error_in_output(self, updater_module):
        """Test connection error patterns return connection message."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("can't connect to server", "", 1)
        assert "Connection error" in msg

    def test_dns_error_in_output(self, updater_module):
        """Test DNS error patterns return DNS message."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("can't resolve hostname", "", 1)
        assert "DNS resolution failed" in msg

    def test_fallback_to_stderr(self, updater_module):
        """Test fallback to stderr content when no pattern matches."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("", "Some unknown error message", 1)
        assert msg == "Some unknown error message"

    def test_fallback_to_unknown_error(self, updater_module):
        """Test fallback to unknown error when stderr empty."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("", "", 1)
        assert "unknown error" in msg.lower()

    def test_rate_limit_error_detected(self, updater_module):
        """Test rate limit error patterns are detected."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())

        # Test various rate limit patterns
        patterns = [
            "rate limit exceeded",
            "rate-limit detected",
            "rate limited by server",
            "HTTP 429",
            "too many requests",
            "temporarily blocked",
            "blocked temporarily",
        ]

        for pattern in patterns:
            msg = updater._extract_error_message(pattern, "", 1)
            assert "rate limited" in msg.lower(), f"Failed for pattern: {pattern}"

    def test_cloudfront_error_detected(self, updater_module):
        """Test CloudFront CDN error is detected."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("CloudFront blocked request", "", 1)
        assert "CDN" in msg or "rate limiting" in msg.lower()

    def test_cloudflare_error_detected(self, updater_module):
        """Test Cloudflare CDN error is detected."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        msg = updater._extract_error_message("cloudflare blocked", "", 1)
        assert "CDN" in msg or "rate limiting" in msg.lower()

    def test_rate_limit_message_includes_per_database_details(self, updater_module):
        """Test rate limit message reports the affected databases and cooldowns."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        stdout = """
daily.cvd updated (version: 27150, sigs: 2050000, f-level: 90, builder: virusdb)
bytecode.cvd database is up-to-date (version: 333, sigs: 95000, f-level: 90, builder: virusdb)
main.cvd database available for download (remote version: 63, local version: 62)
WARNING: FreshClam received error code 429 from the ClamAV CDN.
WARNING: You are on cool-down until after: 2026-03-06 10:30:00
WARNING: Can't download main.cvd from https://database.clamav.net/main.cvd
WARNING: FreshClam failed to update main.cvd
"""

        msg = updater._extract_error_message(stdout, "", 1)

        assert "daily.cvd" in msg
        assert "bytecode.cvd" in msg
        assert "main.cvd until 2026-03-06 10:30:00" in msg

    def test_mirror_unavailable_error_detected(self, updater_module):
        """Test mirror unavailable error is detected."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())

        # Test "mirror down" pattern
        msg = updater._extract_error_message("mirror database.cvd.clamav.net is down", "", 1)
        assert "mirror" in msg.lower() and "unavailable" in msg.lower()

        # Test "mirror unavailable" pattern
        msg = updater._extract_error_message("mirror unavailable", "", 1)
        assert "mirror" in msg.lower() and "unavailable" in msg.lower()

    def test_certificate_error_detected(self, updater_module):
        """Test SSL/TLS certificate error is detected."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())

        # Test various certificate error patterns
        patterns = [
            "certificate verify failed",
            "SSL error: certificate",
            "TLS error: bad certificate",
            "verify failed",
        ]

        for pattern in patterns:
            msg = updater._extract_error_message(pattern, "", 1)
            assert "certificate" in msg.lower() or "SSL/TLS" in msg, (
                f"Failed for pattern: {pattern}"
            )

    def test_timeout_error_detected(self, updater_module):
        """Test timeout error is detected."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())

        # Test "timeout" pattern
        msg = updater._extract_error_message("connection timeout", "", 1)
        assert "timed out" in msg.lower()

        # Test "timed out" pattern
        msg = updater._extract_error_message("request timed out", "", 1)
        assert "timed out" in msg.lower()


# =============================================================================
# FreshclamUpdater.update_sync() Tests
# =============================================================================


class TestFreshclamUpdaterUpdateSync:
    """Tests for FreshclamUpdater.update_sync() with manual method (prefer_service=False)."""

    def test_successful_update(self, updater_module):
        """Test successful database update."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()
        mock_stdout = (
            "daily.cvd updated (version: 27150, sigs: 2050000, f-level: 90, builder: virusdb)"
        )

        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        with patch("subprocess.Popen") as mock_popen:
                            mock_process = MagicMock()
                            mock_process.communicate.return_value = (mock_stdout, "")
                            mock_process.returncode = 0
                            mock_process.kill = MagicMock()
                            mock_process.wait = MagicMock()
                            mock_popen.return_value = mock_process

                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "_check_freshclam_running",
                                return_value=(False, None),
                            ):
                                result = updater.update_sync(prefer_service=False)

                            assert result.status == UpdateStatus.SUCCESS
                            assert result.databases_updated == 1
                            mock_log_manager.save_log.assert_called_once()

    def test_already_up_to_date(self, updater_module):
        """Test when database is already up-to-date."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()
        mock_stdout = "daily.cvd database is up-to-date (version: 27150)"

        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        with patch("subprocess.Popen") as mock_popen:
                            mock_process = MagicMock()
                            mock_process.communicate.return_value = (mock_stdout, "")
                            mock_process.returncode = 0
                            mock_process.kill = MagicMock()
                            mock_process.wait = MagicMock()
                            mock_popen.return_value = mock_process

                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "_check_freshclam_running",
                                return_value=(False, None),
                            ):
                                result = updater.update_sync(prefer_service=False)

                            assert result.status == UpdateStatus.UP_TO_DATE
                            assert result.databases_updated == 0

    def test_error_return_code(self, updater_module):
        """Test error handling for non-zero return code."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        with patch("subprocess.Popen") as mock_popen:
                            mock_process = MagicMock()
                            mock_process.communicate.return_value = (
                                "",
                                "Error occurred",
                            )
                            mock_process.returncode = 1
                            mock_process.kill = MagicMock()
                            mock_process.wait = MagicMock()
                            mock_popen.return_value = mock_process

                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "_check_freshclam_running",
                                return_value=(False, None),
                            ):
                                result = updater.update_sync(prefer_service=False)

                            assert result.status == UpdateStatus.ERROR
                            assert result.has_error is True

    def test_freshclam_not_installed(self, updater_module):
        """Test handling when freshclam is not installed."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch(
            "src.core.updater.check_freshclam_installed",
            return_value=(False, "freshclam not found"),
        ):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            result = updater.update_sync(prefer_service=False)

            assert result.status == UpdateStatus.ERROR
            assert "freshclam" in result.stderr.lower() or "not" in result.stderr.lower()

    def test_file_not_found_error(self, updater_module):
        """Test handling FileNotFoundError."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        with patch("subprocess.Popen") as mock_popen:
                            mock_popen.side_effect = FileNotFoundError("freshclam not found")

                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "_check_freshclam_running",
                                return_value=(False, None),
                            ):
                                result = updater.update_sync(prefer_service=False)

                            assert result.status == UpdateStatus.ERROR
                            assert "not found" in result.error_message.lower()

    def test_permission_error(self, updater_module):
        """Test handling PermissionError."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        with patch("subprocess.Popen") as mock_popen:
                            mock_popen.side_effect = PermissionError("Access denied")

                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "_check_freshclam_running",
                                return_value=(False, None),
                            ):
                                result = updater.update_sync(prefer_service=False)

                            assert result.status == UpdateStatus.ERROR
                            assert "Permission denied" in result.error_message

    def test_generic_runtime_error(self, updater_module):
        """Test handling generic RuntimeError."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        with patch("subprocess.Popen") as mock_popen:
                            mock_popen.side_effect = RuntimeError("Unexpected error")

                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "_check_freshclam_running",
                                return_value=(False, None),
                            ):
                                result = updater.update_sync(prefer_service=False)

                            assert result.status == UpdateStatus.ERROR
                            assert "Update failed" in result.error_message

    def test_cancelled_during_run(self, updater_module):
        """Test cancellation during update run."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        with patch("subprocess.Popen") as mock_popen:
                            mock_process = MagicMock()

                            updater = FreshclamUpdater(log_manager=mock_log_manager)

                            def simulate_cancel(*args, **kwargs):
                                # Simulate cancellation happening during communicate()
                                updater._update_cancelled = True
                                return ("", "")

                            mock_process.communicate.side_effect = simulate_cancel
                            mock_process.returncode = 0
                            mock_process.kill = MagicMock()
                            mock_process.wait = MagicMock()
                            mock_process.poll = MagicMock(return_value=0)  # Process already done
                            mock_popen.return_value = mock_process

                            with patch.object(
                                updater,
                                "_check_freshclam_running",
                                return_value=(False, None),
                            ):
                                result = updater.update_sync(prefer_service=False)

                            assert result.status == UpdateStatus.CANCELLED


# =============================================================================
# FreshclamUpdater.cancel() Tests
# =============================================================================


class TestFreshclamUpdaterCancel:
    """Tests for FreshclamUpdater.cancel()."""

    def test_cancel_sets_cancelled_flag(self, updater_module):
        """Test cancel sets _update_cancelled flag."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        updater._update_cancelled = False
        updater.cancel()
        assert updater._update_cancelled is True

    def test_cancel_terminates_current_process(self, updater_module):
        """Test cancel terminates the current process."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        mock_process = MagicMock()
        updater._current_process = mock_process
        updater.cancel()
        mock_process.terminate.assert_called_once()

    def test_cancel_handles_no_current_process(self, updater_module):
        """Test cancel handles case when no process is running."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        updater._current_process = None
        # Should not raise an error
        updater.cancel()
        assert updater._update_cancelled is True

    def test_cancel_handles_oserror(self, updater_module):
        """Test cancel handles OSError when terminating process."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        mock_process = MagicMock()
        mock_process.terminate.side_effect = OSError("Process already terminated")
        updater._current_process = mock_process
        # Should not raise an error
        updater.cancel()
        assert updater._update_cancelled is True

    def test_cancel_terminate_timeout_escalates_to_kill(self, updater_module):
        """Test that cancel escalates to kill if terminate times out."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock(
            side_effect=[
                subprocess.TimeoutExpired(cmd="test", timeout=5),  # First wait times out
                None,  # Second wait (after kill) succeeds
            ]
        )
        updater._current_process = mock_process

        updater.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        assert updater._update_cancelled is True

    def test_cancel_kill_timeout_handles_gracefully(self, updater_module):
        """Test that cancel handles kill timeout gracefully."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock(
            side_effect=[
                subprocess.TimeoutExpired(cmd="test", timeout=5),  # First wait times out
                subprocess.TimeoutExpired(cmd="test", timeout=2),  # Second wait also times out
            ]
        )
        updater._current_process = mock_process

        # Should not raise exception even if kill times out
        updater.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        assert updater._update_cancelled is True

    def test_cancel_process_already_terminated_on_terminate(self, updater_module):
        """Test cancel handles process already gone when calling terminate."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        mock_process = MagicMock()
        mock_process.terminate = MagicMock(side_effect=ProcessLookupError("No such process"))
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock()
        updater._current_process = mock_process

        # Should not raise exception and should return early
        updater.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_not_called()  # Should not reach kill
        mock_process.wait.assert_not_called()  # Should not reach wait
        assert updater._update_cancelled is True

    def test_cancel_graceful_termination_success(self, updater_module):
        """Test cancel when process terminates gracefully within timeout."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = MagicMock(return_value=None)  # Succeeds on first call
        updater._current_process = mock_process

        updater.cancel()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()  # Only one wait call
        mock_process.kill.assert_not_called()  # Should not escalate to kill
        assert updater._update_cancelled is True


class TestFreshclamUpdaterCommunicateTimeout:
    """Tests for FreshclamUpdater communicate() timeout handling."""

    def test_communicate_timeout_kills_process_and_returns_error(self, updater_module):
        """Test that communicate() timeout kills process and returns ERROR status."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
            with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                with patch("src.core.updater.get_pkexec_path", return_value=None):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        with patch("subprocess.Popen") as mock_popen:
                            mock_process = MagicMock()
                            # Simulate timeout on communicate
                            timeout_exc = subprocess.TimeoutExpired(cmd="freshclam", timeout=600)
                            timeout_exc.stdout = "partial output"
                            timeout_exc.stderr = ""
                            mock_process.communicate = MagicMock(
                                side_effect=[
                                    timeout_exc,  # First call times out
                                    ("", ""),  # Second call after kill
                                ]
                            )
                            mock_process.kill = MagicMock()
                            mock_process.poll = MagicMock(return_value=None)
                            mock_process.wait = MagicMock()
                            mock_popen.return_value = mock_process

                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "_check_freshclam_running",
                                return_value=(False, None),
                            ):
                                result = updater.update_sync(prefer_service=False)

                            # Should have called kill after timeout
                            mock_process.kill.assert_called()
                            # Should return ERROR status with timeout message
                            assert result.status == UpdateStatus.ERROR
                            assert "timed out" in result.error_message.lower()

    @pytest.mark.skipif(
        os.name != "posix" or not Path("/proc").is_dir(),
        reason="requires POSIX process groups and /proc",
    )
    def test_timeout_terminates_descendant_process(
        self,
        tmp_path: Path,
        updater_module,
    ):
        """A timed-out update must terminate descendants of the shell wrapper."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())

        child_script = tmp_path / "blocking-child.sh"
        child_script.write_text(
            """#!/bin/sh
set -eu
trap '' TERM
printf '%s\n' "$$" > "$1"
exec sleep 3600
""",
            encoding="utf-8",
        )

        wrapper_script = tmp_path / "blocking-wrapper.sh"
        wrapper_script.write_text(
            """#!/bin/sh
set -eu
/bin/sh "$1" "$2" &
wait
""",
            encoding="utf-8",
        )
        marker = tmp_path / "child.pid"
        child_pid: int | None = None

        def read_child_pid() -> int | None:
            try:
                value = marker.read_text(encoding="utf-8").strip()
            except (FileNotFoundError, OSError):
                return None
            try:
                pid = int(value)
            except ValueError:
                return None
            return pid if pid > 0 else None

        def pid_exists(pid: int) -> bool:
            proc_entry = Path("/proc") / str(pid)
            if not proc_entry.exists():
                return False
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            return proc_entry.exists()

        try:
            with patch("src.core.updater._UPDATE_COMMUNICATE_TIMEOUT", 0.5):
                _, _, _, timed_out = updater._run_update_process(
                    ["/bin/sh", str(wrapper_script), str(child_script), str(marker)]
                )

            marker_deadline = time.monotonic() + 5.0
            while child_pid is None:
                child_pid = read_child_pid()
                if child_pid is not None:
                    break
                if time.monotonic() >= marker_deadline:
                    raise AssertionError(f"timed out waiting for child PID marker: {marker}")
                time.sleep(0.01)

            assert timed_out is True
            assert child_pid != os.getpid()

            cleanup_deadline = time.monotonic() + 5.0
            while pid_exists(child_pid):
                if time.monotonic() >= cleanup_deadline:
                    break
                time.sleep(0.01)
            assert not pid_exists(child_pid), f"descendant process {child_pid} is still alive"
        finally:
            if child_pid is None:
                cleanup_deadline = time.monotonic() + 1.0
                while child_pid is None and time.monotonic() < cleanup_deadline:
                    child_pid = read_child_pid()
                    if child_pid is None:
                        time.sleep(0.01)
            if child_pid is not None:
                if pid_exists(child_pid):
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                cleanup_deadline = time.monotonic() + 2.0
                while pid_exists(child_pid) and time.monotonic() < cleanup_deadline:
                    time.sleep(0.01)
            updater._cleanup_current_process()

    @pytest.mark.skipif(
        os.name != "posix" or not Path("/proc").is_dir(),
        reason="requires POSIX process groups and /proc",
    )
    def test_force_update_timeout_cleans_staging_directory(
        self,
        tmp_path: Path,
        updater_module,
    ):
        """A timed-out force update must remove staging without changing live data."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        updater = FreshclamUpdater(log_manager=MagicMock())
        from src.core.updater import _build_force_update_script

        database_dir = tmp_path / "clamav"
        database_dir.mkdir()
        live_database = database_dir / "main.cvd"
        original_bytes = b"live-database-before-timeout"
        live_database.write_bytes(original_bytes)

        datadir_marker = tmp_path / "staging.datadir"
        pid_marker = tmp_path / "freshclam.pid"
        fake_freshclam = tmp_path / "fake-freshclam"
        fake_freshclam.write_text(
            """#!/bin/sh
set -eu

datadir=
while [ "$#" -gt 0 ]; do
    arg=$1
    shift
    case "$arg" in
        --datadir=*) datadir=${arg#--datadir=} ;;
        --datadir)
            [ "$#" -gt 0 ]
            datadir=$1
            shift
            ;;
    esac
done
[ -n "$datadir" ]
trap '' TERM
script_dir=$(dirname "$0")
printf '%s\n' "$datadir" > "$script_dir/staging.datadir"
printf '%s\n' "$$" > "$script_dir/freshclam.pid"
exec sleep 3600
""",
            encoding="utf-8",
        )
        fake_freshclam.chmod(0o755)

        def pid_exists(pid: int) -> bool:
            proc_entry = Path("/proc") / str(pid)
            if not proc_entry.exists():
                return False
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            return proc_entry.exists()

        fake_pid: int | None = None
        try:
            script = _build_force_update_script(str(database_dir))
            with patch("src.core.updater._UPDATE_COMMUNICATE_TIMEOUT", 0.5):
                _, _, _, timed_out = updater._run_update_process(
                    ["sh", "-c", script, "clamui-force-update", str(fake_freshclam)]
                )

            staging_dir: Path | None = None
            marker_deadline = time.monotonic() + 5.0
            while staging_dir is None:
                try:
                    marker_value = datadir_marker.read_text(encoding="utf-8").strip()
                except (FileNotFoundError, OSError):
                    marker_value = ""
                if marker_value:
                    staging_dir = Path(marker_value)
                    break
                if time.monotonic() >= marker_deadline:
                    raise AssertionError(f"timed out waiting for staging marker: {datadir_marker}")
                time.sleep(0.01)

            assert timed_out is True
            assert staging_dir != database_dir
            assert not staging_dir.exists()
            assert live_database.read_bytes() == original_bytes
        finally:
            pid_deadline = time.monotonic() + 1.0
            while fake_pid is None and time.monotonic() < pid_deadline:
                try:
                    fake_pid = int(pid_marker.read_text(encoding="utf-8").strip())
                except (FileNotFoundError, OSError, ValueError):
                    fake_pid = None
                if fake_pid is None:
                    time.sleep(0.01)

            if fake_pid is not None and fake_pid > 0 and fake_pid != os.getpid():
                if pid_exists(fake_pid):
                    try:
                        os.kill(fake_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    cleanup_deadline = time.monotonic() + 2.0
                    while pid_exists(fake_pid) and time.monotonic() < cleanup_deadline:
                        time.sleep(0.01)
            updater._cleanup_current_process()

    def test_force_timeout_restores_backup_in_native_mode(self, updater_module):
        """Force-update timeouts should not invoke legacy Python backup helpers."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                with patch.object(updater, "_backup_local_databases") as mock_backup:
                    with patch.object(updater, "_delete_local_databases") as mock_delete:
                        with patch.object(
                            updater,
                            "_check_freshclam_running",
                            return_value=(False, None),
                        ):
                            with patch.object(
                                updater,
                                "_build_command",
                                return_value=[
                                    "sh",
                                    "-c",
                                    "staged force update",
                                    "clamui-force-update",
                                    "freshclam",
                                ],
                            ):
                                with patch.object(
                                    updater,
                                    "_run_update_process",
                                    return_value=("partial output", "", -1, True),
                                ):
                                    with patch.object(
                                        updater, "_restore_databases_from_backup"
                                    ) as mock_restore:
                                        result = updater.update_sync(
                                            force=True,
                                            prefer_service=False,
                                        )

        assert result.status == UpdateStatus.ERROR
        assert "timed out" in result.error_message.lower()
        mock_backup.assert_not_called()
        mock_delete.assert_not_called()
        mock_restore.assert_not_called()

    def test_force_cancel_does_not_touch_sandbox_backup_in_flatpak_mode(self, updater_module):
        """Flatpak force updates operate on the host and skip sandbox DB backup."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch("src.core.updater.check_freshclam_installed", return_value=(True, "1.0.0")):
                updater = FreshclamUpdater(log_manager=mock_log_manager)

                def simulate_cancel(*args, **kwargs):
                    updater._update_cancelled = True
                    return ("", "", 0, False)

                with patch.object(updater, "_backup_local_databases") as mock_backup:
                    with patch.object(
                        updater,
                        "_delete_local_databases",
                    ) as mock_delete:
                        with patch.object(
                            updater, "_check_freshclam_running", return_value=(False, None)
                        ):
                            with patch.object(
                                updater,
                                "_build_command",
                                return_value=["freshclam"],
                            ):
                                with patch.object(
                                    updater,
                                    "_run_update_process",
                                    side_effect=simulate_cancel,
                                ):
                                    with patch.object(
                                        updater,
                                        "_restore_databases_from_backup",
                                        return_value=(True, "Restored"),
                                    ) as mock_restore:
                                        result = updater.update_sync(
                                            force=True,
                                            prefer_service=False,
                                        )

        assert result.status == UpdateStatus.CANCELLED
        mock_backup.assert_not_called()
        mock_delete.assert_not_called()
        mock_restore.assert_not_called()


# =============================================================================
# FreshclamUpdater.update_async() Tests
# =============================================================================


class TestFreshclamUpdaterUpdateAsync:
    """Tests for FreshclamUpdater.update_async()."""

    def test_callback_invoked_on_completion(self, updater_module):
        """Test callback is invoked when update completes."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_glib = updater_module["glib"]
        mock_log_manager = MagicMock()
        mock_callback = MagicMock()

        with patch("src.core.updater.GLib", mock_glib):
            with patch(
                "src.core.updater.check_freshclam_installed",
                return_value=(True, "1.0.0"),
            ):
                with patch("src.core.updater.get_freshclam_path", return_value="freshclam"):
                    with patch("src.core.updater.get_pkexec_path", return_value=None):
                        with patch(
                            "src.core.updater.wrap_host_command",
                            side_effect=lambda x: x,
                        ):
                            with patch("subprocess.Popen") as mock_popen:
                                mock_process = MagicMock()
                                mock_process.communicate.return_value = (
                                    "database is up-to-date",
                                    "",
                                )
                                mock_process.returncode = 0
                                mock_process.kill = MagicMock()
                                mock_process.wait = MagicMock()
                                mock_popen.return_value = mock_process

                                updater = FreshclamUpdater(log_manager=mock_log_manager)
                                with patch.object(
                                    updater,
                                    "_check_freshclam_running",
                                    return_value=(False, None),
                                ):
                                    updater.update_async(mock_callback, prefer_service=False)

                                    # Wait for thread to complete
                                    import time

                                    time.sleep(0.2)

                                # Verify callback was called via GLib.idle_add
                                mock_callback.assert_called_once()


# =============================================================================
# FreshclamUpdater._save_update_log() Tests
# =============================================================================


class TestFreshclamUpdaterSaveUpdateLog:
    """Tests for FreshclamUpdater._save_update_log()."""

    def test_log_entry_created_for_success(self, updater_module):
        """Test log entry created with correct summary for SUCCESS."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()
        updater = FreshclamUpdater(log_manager=mock_log_manager)

        result = UpdateResult(
            status=UpdateStatus.SUCCESS,
            stdout="Updated successfully",
            stderr="",
            exit_code=0,
            databases_updated=2,
            error_message=None,
        )

        updater._save_update_log(result, 5.0)

        mock_log_manager.save_log.assert_called_once()
        call_args = mock_log_manager.save_log.call_args
        log_entry = call_args[0][0]
        assert "2 database(s) updated" in log_entry.summary

    def test_log_entry_created_for_up_to_date(self, updater_module):
        """Test log entry created with correct summary for UP_TO_DATE."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()
        updater = FreshclamUpdater(log_manager=mock_log_manager)

        result = UpdateResult(
            status=UpdateStatus.UP_TO_DATE,
            stdout="Already up to date",
            stderr="",
            exit_code=0,
            databases_updated=0,
            error_message=None,
        )

        updater._save_update_log(result, 3.0)

        mock_log_manager.save_log.assert_called_once()
        call_args = mock_log_manager.save_log.call_args
        log_entry = call_args[0][0]
        assert "up to date" in log_entry.summary.lower()

    def test_log_entry_created_for_cancelled(self, updater_module):
        """Test log entry created with correct summary for CANCELLED."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()
        updater = FreshclamUpdater(log_manager=mock_log_manager)

        result = UpdateResult(
            status=UpdateStatus.CANCELLED,
            stdout="",
            stderr="",
            exit_code=0,
            databases_updated=0,
            error_message="Cancelled by user",
        )

        updater._save_update_log(result, 1.0)

        mock_log_manager.save_log.assert_called_once()
        call_args = mock_log_manager.save_log.call_args
        log_entry = call_args[0][0]
        assert "cancelled" in log_entry.summary.lower()

    def test_log_entry_created_for_error(self, updater_module):
        """Test log entry created with correct summary for ERROR."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()
        updater = FreshclamUpdater(log_manager=mock_log_manager)

        result = UpdateResult(
            status=UpdateStatus.ERROR,
            stdout="",
            stderr="Connection failed",
            exit_code=1,
            databases_updated=0,
            error_message="Connection failed",
        )

        updater._save_update_log(result, 2.0)

        mock_log_manager.save_log.assert_called_once()
        call_args = mock_log_manager.save_log.call_args
        log_entry = call_args[0][0]
        assert "failed" in log_entry.summary.lower()

    def test_log_entry_type_is_update(self, updater_module):
        """Test log entry has type 'update'."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        UpdateResult = updater_module["UpdateResult"]
        UpdateStatus = updater_module["UpdateStatus"]
        mock_log_manager = MagicMock()
        updater = FreshclamUpdater(log_manager=mock_log_manager)

        result = UpdateResult(
            status=UpdateStatus.SUCCESS,
            stdout="",
            stderr="",
            exit_code=0,
            databases_updated=1,
            error_message=None,
        )

        updater._save_update_log(result, 1.0)

        call_args = mock_log_manager.save_log.call_args
        log_entry = call_args[0][0]
        # LogEntry uses 'type' not 'log_type' as the attribute
        assert log_entry.type == "update"


# =============================================================================
# FreshclamUpdater Force Update Backup/Restore Tests
# =============================================================================


class TestFreshclamUpdaterBackupLocalDatabases:
    """Tests for FreshclamUpdater._backup_local_databases()."""

    def test_backup_local_databases_success_flatpak(self, updater_module, tmp_path):
        """Test successful backup of database files in Flatpak mode."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Create mock database directory with files
        db_dir = tmp_path / "clamav"
        db_dir.mkdir()
        (db_dir / "daily.cvd").write_text("daily content")
        (db_dir / "main.cvd").write_text("main content")
        (db_dir / "bytecode.cld").write_text("bytecode content")

        # Use Flatpak mode since it allows us to specify the db path
        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                success, error, files = updater._backup_local_databases()

                # Verify backup was created
                assert success is True
                assert error is None
                assert len(files) == 3
                assert updater._force_update_backup_dir is not None
                assert updater._force_update_backup_dir.exists()

                # Clean up
                updater._cleanup_backup()

    def test_backup_local_databases_no_directory(self, updater_module, tmp_path):
        """Test backup fails when database directory doesn't exist."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Point to non-existent directory
        non_existent = tmp_path / "non_existent"

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=non_existent,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                success, error, files = updater._backup_local_databases()

                assert success is False
                assert "not found" in error.lower()
                assert files == []

    def test_backup_local_databases_no_files(self, updater_module, tmp_path):
        """Test backup fails when no database files found."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Create empty database directory
        db_dir = tmp_path / "clamav"
        db_dir.mkdir()

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                success, error, files = updater._backup_local_databases()

                assert success is False
                assert "no database files" in error.lower()
                assert files == []

    def test_backup_local_databases_permission_error(self, updater_module, tmp_path):
        """Test backup fails on permission error during copy."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        db_dir = tmp_path / "clamav"
        db_dir.mkdir()
        (db_dir / "daily.cvd").write_text("daily content")

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                with patch("shutil.copy2", side_effect=OSError("Permission denied")):
                    success, error, _ = updater._backup_local_databases()

                assert success is False
                assert "permission denied" in error.lower() or "failed" in error.lower()

    def test_backup_local_databases_flatpak_path(self, updater_module, tmp_path):
        """Test backup uses Flatpak database path when in Flatpak."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        flatpak_db_dir = tmp_path / "flatpak_clamav"
        flatpak_db_dir.mkdir()
        (flatpak_db_dir / "daily.cvd").write_text("daily")

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=flatpak_db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                success, _, files = updater._backup_local_databases()

                # Should succeed using Flatpak path
                assert success is True
                assert len(files) == 1

                # Clean up
                updater._cleanup_backup()


class TestFreshclamUpdaterRestoreDatabasesFromBackup:
    """Tests for FreshclamUpdater._restore_databases_from_backup()."""

    def test_restore_databases_from_backup_success(self, updater_module, tmp_path):
        """Test successful restore of database files from backup."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Create backup directory with files
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        (backup_dir / "daily.cvd").write_text("daily content")
        (backup_dir / "main.cvd").write_text("main content")

        # Create target database directory
        db_dir = tmp_path / "clamav"
        db_dir.mkdir()

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                updater._force_update_backup_dir = backup_dir

                success, message = updater._restore_databases_from_backup()

                assert success is True
                assert "restored" in message.lower()
                # Verify files were copied
                assert (db_dir / "daily.cvd").exists()
                assert (db_dir / "main.cvd").exists()

    def test_restore_databases_from_backup_no_backup(self, updater_module):
        """Test restore fails when no backup exists."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=True):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            # No backup directory set

            success, error = updater._restore_databases_from_backup()

            assert success is False
            assert "no backup" in error.lower()

    def test_restore_databases_from_backup_missing_backup_dir(self, updater_module, tmp_path):
        """Test restore fails when backup directory was deleted."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Set backup dir to non-existent path
        non_existent = tmp_path / "deleted_backup"

        with patch("src.core.updater.is_flatpak", return_value=True):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            updater._force_update_backup_dir = non_existent

            success, error = updater._restore_databases_from_backup()

            assert success is False
            assert "no backup" in error.lower()

    def test_restore_databases_from_backup_permission_error(self, updater_module, tmp_path):
        """Test restore fails on permission error."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        (backup_dir / "daily.cvd").write_text("content")

        db_dir = tmp_path / "clamav"
        db_dir.mkdir()

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                updater._force_update_backup_dir = backup_dir

                with patch("shutil.copy2", side_effect=OSError("Permission denied")):
                    success, error = updater._restore_databases_from_backup()

                assert success is False
                assert "failed" in error.lower()

    def test_restore_databases_db_dir_not_found(self, updater_module, tmp_path):
        """Test restore fails when database directory doesn't exist."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        (backup_dir / "daily.cvd").write_text("content")

        non_existent_db = tmp_path / "non_existent_db"

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=non_existent_db,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                updater._force_update_backup_dir = backup_dir

                success, error = updater._restore_databases_from_backup()

                assert success is False
                assert "not found" in error.lower()


class TestFreshclamUpdaterCleanupBackup:
    """Tests for FreshclamUpdater._cleanup_backup()."""

    def test_cleanup_backup_success(self, updater_module, tmp_path):
        """Test successful cleanup of backup directory."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Create backup directory
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        (backup_dir / "daily.cvd").write_text("content")

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            updater._force_update_backup_dir = backup_dir

            updater._cleanup_backup()

            # Verify backup dir is cleaned up
            assert not backup_dir.exists()
            assert updater._force_update_backup_dir is None

    def test_cleanup_backup_no_backup_dir(self, updater_module):
        """Test cleanup handles case when no backup directory exists."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            # No backup directory set

            # Should not raise exception
            updater._cleanup_backup()

    def test_cleanup_backup_already_deleted(self, updater_module, tmp_path):
        """Test cleanup handles case when backup was already deleted."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Set backup dir to non-existent path
        non_existent = tmp_path / "already_deleted"

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            updater._force_update_backup_dir = non_existent

            # Should not raise exception
            updater._cleanup_backup()


class TestFreshclamUpdaterDeleteLocalDatabases:
    """Tests for FreshclamUpdater._delete_local_databases()."""

    def test_delete_local_databases_success(self, updater_module, tmp_path):
        """Test successful deletion of database files."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Create mock database directory with files
        db_dir = tmp_path / "clamav"
        db_dir.mkdir()
        (db_dir / "daily.cvd").write_text("daily")
        (db_dir / "main.cvd").write_text("main")
        (db_dir / "bytecode.cld").write_text("bytecode")

        # Use Flatpak mode for controllable paths
        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                success, error, count = updater._delete_local_databases()

        assert success is True
        assert error is None
        assert count == 3
        # Verify files were deleted
        assert not (db_dir / "daily.cvd").exists()
        assert not (db_dir / "main.cvd").exists()
        assert not (db_dir / "bytecode.cld").exists()

    def test_delete_local_databases_no_directory(self, updater_module, tmp_path):
        """Test delete fails when database directory doesn't exist."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        non_existent = tmp_path / "non_existent"

        # Use Flatpak mode for controllable paths
        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=non_existent,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                success, error, count = updater._delete_local_databases()

        assert success is False
        assert "not found" in error.lower()
        assert count == 0

    def test_delete_local_databases_partial_failure(self, updater_module, tmp_path):
        """Test partial deletion when some files cannot be deleted."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        db_dir = tmp_path / "clamav"
        db_dir.mkdir()
        (db_dir / "daily.cvd").write_text("daily")
        (db_dir / "main.cvd").write_text("main")

        # Make unlink fail for one file
        original_unlink = Path.unlink
        call_count = [0]

        def mock_unlink(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("Permission denied")
            return original_unlink(self, *args, **kwargs)

        # Use Flatpak mode for controllable paths
        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                with patch.object(Path, "unlink", mock_unlink):
                    success, error, count = updater._delete_local_databases()

        # Partial success - some deleted, some failed
        assert success is True  # Still True if any were deleted
        assert count == 1  # Only 1 deleted successfully

    def test_delete_local_databases_all_fail(self, updater_module, tmp_path):
        """Test delete fails when all files cannot be deleted."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        db_dir = tmp_path / "clamav"
        db_dir.mkdir()
        (db_dir / "daily.cvd").write_text("daily")

        # Use Flatpak mode for controllable paths
        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
                    success, error, count = updater._delete_local_databases()

        assert success is False
        assert "could not be deleted" in error.lower()
        assert count == 0

    def test_delete_local_databases_flatpak_path(self, updater_module, tmp_path):
        """Test delete uses Flatpak database path when in Flatpak."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        flatpak_db_dir = tmp_path / "flatpak_clamav"
        flatpak_db_dir.mkdir()
        (flatpak_db_dir / "daily.cvd").write_text("daily")

        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=flatpak_db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                success, error, count = updater._delete_local_databases()

                assert success is True
                assert count == 1
                assert not (flatpak_db_dir / "daily.cvd").exists()

    def test_delete_local_databases_no_files(self, updater_module, tmp_path):
        """Test delete returns 0 count when no database files exist."""
        FreshclamUpdater = updater_module["FreshclamUpdater"]
        mock_log_manager = MagicMock()

        # Create empty database directory
        db_dir = tmp_path / "clamav"
        db_dir.mkdir()

        # Use Flatpak mode for controllable paths
        with patch("src.core.updater.is_flatpak", return_value=True):
            with patch(
                "src.core.updater.get_clamav_database_dir",
                return_value=db_dir,
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                success, error, count = updater._delete_local_databases()

        assert success is True
        assert error is None
        assert count == 0


# =============================================================================
# UpdateMethod Enum Tests
# =============================================================================


class TestUpdateMethod:
    """Tests for the UpdateMethod enum."""

    def test_service_signal_value(self, updater_module):
        """Test UpdateMethod.SERVICE_SIGNAL has correct value."""
        from src.core.updater import UpdateMethod

        assert UpdateMethod.SERVICE_SIGNAL.value == "service_signal"

    def test_manual_value(self, updater_module):
        """Test UpdateMethod.MANUAL has correct value."""
        from src.core.updater import UpdateMethod

        assert UpdateMethod.MANUAL.value == "manual"


# =============================================================================
# FreshclamServiceStatus Enum Tests
# =============================================================================


class TestFreshclamServiceStatus:
    """Tests for the FreshclamServiceStatus enum."""

    def test_running_value(self, updater_module):
        """Test FreshclamServiceStatus.RUNNING has correct value."""
        from src.core.updater import FreshclamServiceStatus

        assert FreshclamServiceStatus.RUNNING.value == "running"

    def test_stopped_value(self, updater_module):
        """Test FreshclamServiceStatus.STOPPED has correct value."""
        from src.core.updater import FreshclamServiceStatus

        assert FreshclamServiceStatus.STOPPED.value == "stopped"

    def test_not_found_value(self, updater_module):
        """Test FreshclamServiceStatus.NOT_FOUND has correct value."""
        from src.core.updater import FreshclamServiceStatus

        assert FreshclamServiceStatus.NOT_FOUND.value == "not_found"

    def test_unknown_value(self, updater_module):
        """Test FreshclamServiceStatus.UNKNOWN has correct value."""
        from src.core.updater import FreshclamServiceStatus

        assert FreshclamServiceStatus.UNKNOWN.value == "unknown"


# =============================================================================
# UpdateResult with update_method Tests
# =============================================================================


class TestUpdateResultMethod:
    """Tests for UpdateResult.update_method field."""

    def test_default_update_method_is_manual(self, updater_module):
        """Test UpdateResult defaults to MANUAL update method."""
        from src.core.updater import UpdateMethod, UpdateResult, UpdateStatus

        result = UpdateResult(
            status=UpdateStatus.SUCCESS,
            stdout="output",
            stderr="",
            exit_code=0,
            databases_updated=1,
            error_message=None,
        )
        assert result.update_method == UpdateMethod.MANUAL

    def test_update_method_can_be_service_signal(self, updater_module):
        """Test UpdateResult can use SERVICE_SIGNAL method."""
        from src.core.updater import UpdateMethod, UpdateResult, UpdateStatus

        result = UpdateResult(
            status=UpdateStatus.SUCCESS,
            stdout="Signal sent",
            stderr="",
            exit_code=0,
            databases_updated=0,
            error_message=None,
            update_method=UpdateMethod.SERVICE_SIGNAL,
        )
        assert result.update_method == UpdateMethod.SERVICE_SIGNAL


# =============================================================================
# check_freshclam_service() Tests
# =============================================================================


class TestCheckFreshclamService:
    """Tests for FreshclamUpdater.check_freshclam_service() method."""

    def test_checks_host_service_in_flatpak(self, updater_module):
        """Test Flatpak service checks are wrapped for host execution."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()
        calls = []

        def mock_run(cmd, *args, **kwargs):
            calls.append(cmd)
            if "show" in cmd:
                # LoadState probe confirming the unit exists
                return MagicMock(returncode=0, stdout="loaded\n")
            return MagicMock(returncode=3, stdout="inactive")

        with (
            patch(
                "src.core.updater.wrap_host_command",
                side_effect=lambda cmd: ["flatpak-spawn", "--host", *cmd],
            ),
            patch(
                "src.core.clamav_detection.wrap_host_command",
                side_effect=lambda cmd: ["flatpak-spawn", "--host", *cmd],
            ),
            patch("subprocess.run", side_effect=mock_run),
        ):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.STOPPED
        assert pid is None
        assert calls[0][:2] == ["flatpak-spawn", "--host"]
        assert calls[0][2:4] == ["systemctl", "is-active"]

    def test_returns_running_when_service_active(self, updater_module):
        """Test returns RUNNING when systemd service is active."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        # Mock systemctl is-active returning active
        mock_systemctl = MagicMock()
        mock_systemctl.returncode = 0
        mock_systemctl.stdout = "active"

        # Mock pidof returning a PID
        mock_pidof = MagicMock()
        mock_pidof.returncode = 0
        mock_pidof.stdout = "12345"

        def mock_run(cmd, *args, **kwargs):
            if "is-active" in cmd:
                return mock_systemctl
            elif "pidof" in cmd:
                return mock_pidof
            return MagicMock(returncode=1, stdout="")

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=mock_run):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.RUNNING
        assert pid == "12345"

    def test_returns_stopped_when_service_inactive(self, updater_module):
        """Test returns STOPPED when systemd service exists but is inactive."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        # Mock systemctl is-active returning inactive for a unit that exists
        def mock_run(cmd, *args, **kwargs):
            if "show" in cmd:
                # LoadState probe confirming the unit exists
                return MagicMock(returncode=0, stdout="loaded\n")
            return MagicMock(returncode=3, stdout="inactive")

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=mock_run):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    with patch(
                        "src.core.clamav_detection.wrap_host_command", side_effect=lambda x: x
                    ):
                        updater = FreshclamUpdater(log_manager=mock_log_manager)
                        status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.STOPPED
        assert pid is None

    def test_returns_not_found_when_unit_unknown_but_reported_inactive(self, updater_module):
        """systemd prints 'inactive' for units it has never heard of; that
        must not be classified as installed-but-stopped, or the second
        candidate unit name (openSUSE's freshclam.service) is never probed."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        def mock_run(cmd, *args, **kwargs):
            if "show" in cmd:
                # LoadState probe: unit is unknown to systemd
                return MagicMock(returncode=0, stdout="not-found\n")
            return MagicMock(returncode=3, stdout="inactive")

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=mock_run):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    with patch(
                        "src.core.clamav_detection.wrap_host_command", side_effect=lambda x: x
                    ):
                        updater = FreshclamUpdater(log_manager=mock_log_manager)
                        status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.NOT_FOUND
        assert pid is None

    def test_returns_not_found_when_no_service_exists(self, updater_module):
        """Test returns NOT_FOUND when no systemd service exists."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        # Mock systemctl returning error (service not found)
        mock_result = MagicMock()
        mock_result.returncode = 4  # systemctl unit not found
        mock_result.stdout = ""

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", return_value=mock_result):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.NOT_FOUND
        assert pid is None

    def test_checks_both_service_names(self, updater_module):
        """Test checks both clamav-freshclam.service and freshclam.service."""
        from src.core.updater import FreshclamUpdater

        mock_log_manager = MagicMock()
        checked_services = []

        def mock_run(cmd, *args, **kwargs):
            if "is-active" in cmd:
                checked_services.append(cmd[-1])  # Last arg is service name
            mock_result = MagicMock()
            mock_result.returncode = 4
            mock_result.stdout = ""
            return mock_result

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=mock_run):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    updater.check_freshclam_service()

        assert "clamav-freshclam.service" in checked_services
        assert "freshclam.service" in checked_services


# =============================================================================
# trigger_service_update() Tests
# =============================================================================


class TestTriggerServiceUpdate:
    """Tests for FreshclamUpdater.trigger_service_update() method."""

    def test_returns_error_when_service_not_running(self, updater_module):
        """Test returns error when freshclam service is not running."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.NOT_FOUND, None),
            ):
                success, message = updater.trigger_service_update()

        assert success is False
        assert "not running" in message.lower()

    def test_sends_sigusr1_when_service_running(self, updater_module):
        """Test sends SIGUSR1 signal to freshclam process."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        # Mock kill command succeeding
        mock_kill = MagicMock()
        mock_kill.returncode = 0
        mock_kill.stderr = ""

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, "12345"),
            ):
                with patch("subprocess.run", return_value=mock_kill) as mock_run:
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        success, message = updater.trigger_service_update()

        assert success is True
        assert "12345" in message
        # Verify kill was called with SIGUSR1
        call_args = mock_run.call_args[0][0]
        assert "kill" in call_args
        assert "SIGUSR1" in call_args

    def test_returns_error_when_signal_fails(self, updater_module):
        """Test returns error when kill command fails."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        # Mock kill command failing
        mock_kill = MagicMock()
        mock_kill.returncode = 1
        mock_kill.stderr = "Operation not permitted"

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, "12345"),
            ):
                with patch("subprocess.run", return_value=mock_kill):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        success, message = updater.trigger_service_update()

        assert success is False
        assert "failed" in message.lower()


# =============================================================================
# update_sync() with prefer_service Tests
# =============================================================================


class TestUpdateSyncPreferService:
    """Tests for update_sync() with prefer_service parameter."""

    def test_uses_service_when_available_and_preferred(self, updater_module):
        """Test uses service method when service is running and prefer_service=True."""
        from src.core.updater import (
            FreshclamServiceStatus,
            FreshclamUpdater,
            UpdateMethod,
            UpdateStatus,
        )

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                with patch.object(
                    updater,
                    "check_freshclam_service",
                    return_value=(FreshclamServiceStatus.RUNNING, "12345"),
                ):
                    with patch.object(
                        updater,
                        "trigger_service_update",
                        return_value=(True, "Signal sent to PID 12345"),
                    ):
                        result = updater.update_sync(force=False, prefer_service=True)

        assert result.status == UpdateStatus.SUCCESS
        assert result.update_method == UpdateMethod.SERVICE_SIGNAL
        assert "12345" in result.stdout

    def test_falls_back_to_manual_when_service_not_running(self, updater_module):
        """Test falls back to manual method when service is not running."""
        from src.core.updater import (
            FreshclamServiceStatus,
            FreshclamUpdater,
            UpdateMethod,
            UpdateStatus,
        )

        mock_log_manager = MagicMock()

        # Mock successful manual update
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("daily.cvd updated (version: 26929", "")
        mock_process.returncode = 0
        mock_process.poll.return_value = 0

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
            ):
                with patch("shutil.which", return_value="/usr/bin/pkexec"):
                    with patch("subprocess.Popen", return_value=mock_process):
                        with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "check_freshclam_service",
                                return_value=(FreshclamServiceStatus.NOT_FOUND, None),
                            ):
                                with patch.object(
                                    updater,
                                    "_check_freshclam_running",
                                    return_value=(False, None),
                                ):
                                    result = updater.update_sync(force=False, prefer_service=True)

        assert result.status == UpdateStatus.SUCCESS
        assert result.update_method == UpdateMethod.MANUAL

    def test_uses_manual_for_force_update(self, updater_module):
        """Test always uses manual method for force updates."""
        from src.core.updater import (
            FreshclamServiceStatus,
            FreshclamUpdater,
            UpdateMethod,
        )

        mock_log_manager = MagicMock()

        # Mock successful manual update
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("daily.cvd updated (version: 26929", "")
        mock_process.returncode = 0
        mock_process.poll.return_value = 0

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
            ):
                with patch("shutil.which", return_value="/usr/bin/pkexec"):
                    with patch("subprocess.Popen", return_value=mock_process):
                        with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            # Service is running but force=True should skip it
                            with patch.object(
                                updater,
                                "check_freshclam_service",
                                return_value=(FreshclamServiceStatus.RUNNING, "12345"),
                            ) as mock_check:
                                with patch.object(
                                    updater,
                                    "_check_freshclam_running",
                                    return_value=(False, None),
                                ):
                                    result = updater.update_sync(force=True, prefer_service=True)

        # check_freshclam_service should NOT be called for force updates
        mock_check.assert_not_called()
        assert result.update_method == UpdateMethod.MANUAL

    def test_uses_manual_when_prefer_service_false(self, updater_module):
        """Test uses manual method when prefer_service=False."""
        from src.core.updater import (
            FreshclamUpdater,
            UpdateMethod,
        )

        mock_log_manager = MagicMock()

        # Mock successful manual update
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("daily.cvd updated (version: 26929", "")
        mock_process.returncode = 0
        mock_process.poll.return_value = 0

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
            ):
                with patch("shutil.which", return_value="/usr/bin/pkexec"):
                    with patch("subprocess.Popen", return_value=mock_process):
                        with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                            updater = FreshclamUpdater(log_manager=mock_log_manager)
                            with patch.object(
                                updater,
                                "check_freshclam_service",
                            ) as mock_check:
                                with patch.object(
                                    updater,
                                    "_check_freshclam_running",
                                    return_value=(False, None),
                                ):
                                    result = updater.update_sync(force=False, prefer_service=False)

        # check_freshclam_service should NOT be called when prefer_service=False
        mock_check.assert_not_called()
        assert result.update_method == UpdateMethod.MANUAL

    def test_returns_error_when_service_trigger_fails(self, updater_module):
        """Test returns error when service trigger fails (no fallback to manual).

        When the service is running but signal delivery fails, we must NOT
        fall back to manual freshclam — the service holds all locks and the
        manual method would fail with a confusing lock contention error.
        """
        from src.core.updater import (
            FreshclamServiceStatus,
            FreshclamUpdater,
            UpdateStatus,
        )

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                with patch.object(
                    updater,
                    "check_freshclam_service",
                    return_value=(FreshclamServiceStatus.RUNNING, "12345"),
                ):
                    with patch.object(
                        updater,
                        "trigger_service_update",
                        return_value=(False, "Permission denied"),
                    ):
                        result = updater.update_sync(force=False, prefer_service=True)

        # Should return error, not fall back to manual
        assert result.status == UpdateStatus.ERROR
        assert result.error_message is not None


# =============================================================================
# Additional check_freshclam_service() Tests
# =============================================================================


class TestCheckFreshclamServiceAdditional:
    """Additional tests for check_freshclam_service() edge cases."""

    def test_handles_systemctl_timeout(self, updater_module):
        """Test handles timeout when checking systemctl."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=5)
            ):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    status, pid = updater.check_freshclam_service()

        # Should return NOT_FOUND after all services timeout
        assert status == FreshclamServiceStatus.NOT_FOUND
        assert pid is None

    def test_handles_oserror_during_check(self, updater_module):
        """Test handles OSError when checking systemctl."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=OSError("Command not found")):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.NOT_FOUND
        assert pid is None

    def test_returns_running_without_pid_when_pidof_fails(self, updater_module):
        """Test returns RUNNING with None PID when pidof fails."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        def mock_run(cmd, *args, **kwargs):
            if "is-active" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "active"
                return result
            elif "pidof" in cmd:
                raise subprocess.TimeoutExpired(cmd="pidof", timeout=5)
            return MagicMock(returncode=1, stdout="")

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=mock_run):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.RUNNING
        assert pid is None

    def test_takes_first_pid_when_multiple_returned(self, updater_module):
        """Test takes first PID when pidof returns multiple PIDs."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        def mock_run(cmd, *args, **kwargs):
            if "is-active" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "active"
                return result
            elif "pidof" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "12345 67890 11111"  # Multiple PIDs
                return result
            return MagicMock(returncode=1, stdout="")

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=mock_run):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.RUNNING
        assert pid == "12345"  # First PID

    def test_detects_opensuse_service_name(self, updater_module):
        """Test detects freshclam.service (openSUSE naming)."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        def mock_run(cmd, *args, **kwargs):
            if "is-active" in cmd:
                service_name = cmd[-1]
                result = MagicMock()
                if service_name == "clamav-freshclam.service":
                    result.returncode = 4  # Not found
                    result.stdout = ""
                elif service_name == "freshclam.service":
                    result.returncode = 0
                    result.stdout = "active"
                return result
            elif "pidof" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "99999"
                return result
            return MagicMock(returncode=1, stdout="")

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=mock_run):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.RUNNING
        assert pid == "99999"

    def test_pidof_oserror_returns_running_without_pid(self, updater_module):
        """Test returns RUNNING without PID when pidof raises OSError."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        def mock_run(cmd, *args, **kwargs):
            if "is-active" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "active"
                return result
            elif "pidof" in cmd:
                raise OSError("pidof not found")
            return MagicMock(returncode=1, stdout="")

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch("subprocess.run", side_effect=mock_run):
                with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.RUNNING
        assert pid is None


# =============================================================================
# Additional trigger_service_update() Tests
# =============================================================================


class TestTriggerServiceUpdateAdditional:
    """Additional tests for trigger_service_update() edge cases."""

    def test_fetches_pid_when_not_provided_by_check(self, updater_module):
        """Test fetches PID when check_freshclam_service returns None PID."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        # Mock pidof and kill
        def mock_run(cmd, *args, **kwargs):
            if "pidof" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = "54321"
                return result
            elif "kill" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stderr = ""
                return result
            return MagicMock(returncode=1, stdout="")

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, None),  # No PID
            ):
                with patch("subprocess.run", side_effect=mock_run):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        success, message = updater.trigger_service_update()

        assert success is True
        assert "54321" in message

    def test_fails_when_pid_cannot_be_determined(self, updater_module):
        """Test fails when PID cannot be determined."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        # Mock pidof failing
        mock_pidof = MagicMock()
        mock_pidof.returncode = 1
        mock_pidof.stdout = ""

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, None),
            ):
                with patch("subprocess.run", return_value=mock_pidof):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        success, message = updater.trigger_service_update()

        assert success is False
        assert "could not determine" in message.lower()

    def test_handles_kill_timeout(self, updater_module):
        """Test handles timeout when kill command times out."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, "12345"),
            ):
                with patch(
                    "subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd="kill", timeout=5),
                ):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        success, message = updater.trigger_service_update()

        assert success is False
        assert "timeout" in message.lower()

    def test_handles_kill_oserror(self, updater_module):
        """Test handles OSError when kill command fails."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, "12345"),
            ):
                with patch("subprocess.run", side_effect=OSError("No such process")):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        success, message = updater.trigger_service_update()

        assert success is False
        assert "error" in message.lower()

    def test_handles_pidof_timeout_during_trigger(self, updater_module):
        """Test handles pidof timeout when fetching PID during trigger."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, None),
            ):
                with patch(
                    "subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd="pidof", timeout=5),
                ):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        success, message = updater.trigger_service_update()

        assert success is False
        assert "failed to get" in message.lower()

    def test_handles_pidof_oserror_during_trigger(self, updater_module):
        """Test handles pidof OSError when fetching PID during trigger."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, None),
            ):
                with patch("subprocess.run", side_effect=OSError("pidof not found")):
                    with patch("src.core.updater.wrap_host_command", side_effect=lambda x: x):
                        success, message = updater.trigger_service_update()

        assert success is False
        assert "failed to get" in message.lower()

    def test_returns_error_for_stopped_service(self, updater_module):
        """Test returns error when service is stopped."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.STOPPED, None),
            ):
                success, message = updater.trigger_service_update()

        assert success is False
        assert "not running" in message.lower()
        assert "stopped" in message.lower()

    def test_returns_error_for_unknown_status(self, updater_module):
        """Test returns error when service status is unknown."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.UNKNOWN, None),
            ):
                success, message = updater.trigger_service_update()

        assert success is False
        assert "not running" in message.lower()


# =============================================================================
# Clean-Env Wiring Tests (issue #155 residuals)
# =============================================================================


class TestProbeSubprocessCleanEnv:
    """Host-state probes (systemctl is-active, pidof) must receive the
    sanitized environment so leaked AppImage vars don't break them."""

    def test_check_freshclam_service_passes_clean_env(self, updater_module):
        """systemctl is-active and pidof both receive env=get_clean_env()."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/home/user"}
        env_by_cmd = {}

        def mock_run(cmd, *args, **kwargs):
            env_by_cmd[cmd[0]] = kwargs.get("env")
            if "is-active" in cmd:
                return MagicMock(returncode=0, stdout="active")
            if "pidof" in cmd:
                return MagicMock(returncode=0, stdout="12345")
            return MagicMock(returncode=1, stdout="")

        with (
            patch("src.core.updater.get_clean_env", return_value=clean_env),
            patch("src.core.updater.wrap_host_command", side_effect=lambda x: x),
            patch("subprocess.run", side_effect=mock_run),
        ):
            updater = FreshclamUpdater(log_manager=MagicMock())
            status, pid = updater.check_freshclam_service()

        assert status == FreshclamServiceStatus.RUNNING
        assert pid == "12345"
        assert env_by_cmd["systemctl"] is clean_env
        assert env_by_cmd["pidof"] is clean_env

    def test_trigger_service_update_pid_probe_passes_clean_env(self, updater_module):
        """The pidof retry inside trigger_service_update() gets the clean env."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/home/user"}
        env_by_cmd = {}

        def mock_run(cmd, *args, **kwargs):
            env_by_cmd[cmd[0]] = kwargs.get("env")
            if "pidof" in cmd:
                return MagicMock(returncode=0, stdout="54321")
            if "kill" in cmd:
                return MagicMock(returncode=0, stderr="")
            return MagicMock(returncode=1, stdout="")

        updater = FreshclamUpdater(log_manager=MagicMock())
        with (
            patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, None),
            ),
            patch("src.core.updater.get_clean_env", return_value=clean_env),
            patch("src.core.updater.wrap_host_command", side_effect=lambda x: x),
            patch("subprocess.run", side_effect=mock_run),
        ):
            success, _message = updater.trigger_service_update()

        assert success is True
        assert env_by_cmd["pidof"] is clean_env

    def test_check_freshclam_running_passes_clean_env(self, updater_module):
        """_check_freshclam_running's pidof probe gets the clean env."""
        from src.core.updater import FreshclamUpdater

        clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/home/user"}

        with (
            patch("src.core.updater.get_clean_env", return_value=clean_env),
            patch("src.core.updater.wrap_host_command", side_effect=lambda x: x),
            patch(
                "subprocess.run",
                return_value=MagicMock(returncode=0, stdout="777"),
            ) as mock_run,
        ):
            updater = FreshclamUpdater(log_manager=MagicMock())
            is_running, pid = updater._check_freshclam_running()

        assert is_running is True
        assert pid == "777"
        assert mock_run.call_args.kwargs["env"] is clean_env

    def test_trigger_service_update_kill_passes_clean_env(self, updater_module):
        """Both the kill and pkexec-kill signal commands get the clean env."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater

        clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/home/user"}
        env_by_cmd = {}

        def mock_run(cmd, *args, **kwargs):
            env_by_cmd[cmd[0]] = kwargs.get("env")
            if cmd[0] == "kill":
                # Regular kill fails so the pkexec fallback runs too
                return MagicMock(returncode=1, stderr="Operation not permitted")
            if cmd[0] == "/usr/bin/pkexec":
                return MagicMock(returncode=0, stderr="")
            return MagicMock(returncode=1, stdout="")

        updater = FreshclamUpdater(log_manager=MagicMock())
        with (
            patch.object(
                updater,
                "check_freshclam_service",
                return_value=(FreshclamServiceStatus.RUNNING, "123"),
            ),
            patch("src.core.updater.get_pkexec_path", return_value="/usr/bin/pkexec"),
            patch("src.core.updater.get_clean_env", return_value=clean_env),
            patch("src.core.updater.wrap_host_command", side_effect=lambda x: x),
            patch("subprocess.run", side_effect=mock_run),
        ):
            success, _message = updater.trigger_service_update()

        assert success is True
        assert env_by_cmd["kill"] is clean_env
        assert env_by_cmd["/usr/bin/pkexec"] is clean_env


# =============================================================================
# Additional UpdateResult Tests
# =============================================================================


class TestUpdateResultAdditional:
    """Additional tests for UpdateResult with update_method."""

    def test_is_success_works_with_service_method(self, updater_module):
        """Test is_success property works correctly with SERVICE_SIGNAL method."""
        from src.core.updater import UpdateMethod, UpdateResult, UpdateStatus

        result = UpdateResult(
            status=UpdateStatus.SUCCESS,
            stdout="Signal sent",
            stderr="",
            exit_code=0,
            databases_updated=0,
            error_message=None,
            update_method=UpdateMethod.SERVICE_SIGNAL,
        )
        assert result.is_success is True
        assert result.has_error is False

    def test_has_error_works_with_service_method(self, updater_module):
        """Test has_error property works correctly with SERVICE_SIGNAL method."""
        from src.core.updater import UpdateMethod, UpdateResult, UpdateStatus

        result = UpdateResult(
            status=UpdateStatus.ERROR,
            stdout="",
            stderr="Signal failed",
            exit_code=1,
            databases_updated=0,
            error_message="Failed to send signal",
            update_method=UpdateMethod.SERVICE_SIGNAL,
        )
        assert result.is_success is False
        assert result.has_error is True

    def test_up_to_date_with_manual_method(self, updater_module):
        """Test UP_TO_DATE status with MANUAL method."""
        from src.core.updater import UpdateMethod, UpdateResult, UpdateStatus

        result = UpdateResult(
            status=UpdateStatus.UP_TO_DATE,
            stdout="Database is up to date",
            stderr="",
            exit_code=0,
            databases_updated=0,
            error_message=None,
            update_method=UpdateMethod.MANUAL,
        )
        assert result.is_success is True
        assert result.has_error is False
        assert result.update_method == UpdateMethod.MANUAL


# =============================================================================
# Additional update_sync() Service Tests
# =============================================================================


class TestUpdateSyncServiceAdditional:
    """Additional tests for update_sync() with service integration."""

    def test_service_update_saves_log(self, updater_module):
        """Test service update saves log entry."""
        from src.core.updater import FreshclamServiceStatus, FreshclamUpdater, UpdateMethod

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                with patch.object(
                    updater,
                    "check_freshclam_service",
                    return_value=(FreshclamServiceStatus.RUNNING, "12345"),
                ):
                    with patch.object(
                        updater,
                        "trigger_service_update",
                        return_value=(True, "Signal sent to PID 12345"),
                    ):
                        result = updater.update_sync(force=False, prefer_service=True)

        # Verify log was saved
        mock_log_manager.save_log.assert_called_once()
        assert result.update_method == UpdateMethod.SERVICE_SIGNAL

    def test_service_update_result_has_correct_fields(self, updater_module):
        """Test service update result has correct fields populated."""
        from src.core.updater import (
            FreshclamServiceStatus,
            FreshclamUpdater,
            UpdateMethod,
            UpdateStatus,
        )

        mock_log_manager = MagicMock()

        with patch("src.core.updater.is_flatpak", return_value=False):
            with patch(
                "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
            ):
                updater = FreshclamUpdater(log_manager=mock_log_manager)
                with patch.object(
                    updater,
                    "check_freshclam_service",
                    return_value=(FreshclamServiceStatus.RUNNING, "12345"),
                ):
                    with patch.object(
                        updater,
                        "trigger_service_update",
                        return_value=(True, "Signal sent to PID 12345"),
                    ):
                        result = updater.update_sync(force=False, prefer_service=True)

        assert result.status == UpdateStatus.SUCCESS
        assert result.update_method == UpdateMethod.SERVICE_SIGNAL
        assert result.exit_code == 0
        assert result.databases_updated == 0  # Unknown for service updates
        assert result.error_message is None
        assert "12345" in result.stdout

    def test_freshclam_not_installed_skips_service_check(self, updater_module):
        """Test that freshclam not installed returns error without checking service."""
        from src.core.updater import FreshclamUpdater, UpdateMethod, UpdateStatus

        mock_log_manager = MagicMock()

        with patch(
            "src.core.updater.check_freshclam_installed",
            return_value=(False, "freshclam not found"),
        ):
            updater = FreshclamUpdater(log_manager=mock_log_manager)
            with patch.object(updater, "check_freshclam_service") as mock_check:
                result = updater.update_sync(force=False, prefer_service=True)

        # Service check should not be called when freshclam not installed
        mock_check.assert_not_called()
        assert result.status == UpdateStatus.ERROR
        assert result.update_method == UpdateMethod.MANUAL


# =============================================================================
# update_async() with Service Tests
# =============================================================================


class TestUpdateAsyncService:
    """Tests for update_async() with service integration."""

    def test_async_uses_service_when_available(self, updater_module):
        """Test async update uses service when available."""
        from src.core.updater import (
            FreshclamServiceStatus,
            FreshclamUpdater,
            UpdateMethod,
            UpdateStatus,
        )

        mock_log_manager = MagicMock()
        mock_callback = MagicMock()
        mock_glib = updater_module["glib"]

        with patch("src.core.updater.GLib", mock_glib):
            with patch("src.core.updater.is_flatpak", return_value=False):
                with patch(
                    "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
                ):
                    updater = FreshclamUpdater(log_manager=mock_log_manager)
                    with patch.object(
                        updater,
                        "check_freshclam_service",
                        return_value=(FreshclamServiceStatus.RUNNING, "12345"),
                    ):
                        with patch.object(
                            updater,
                            "trigger_service_update",
                            return_value=(True, "Signal sent"),
                        ):
                            updater.update_async(mock_callback, prefer_service=True)

                            # Wait for thread
                            import time

                            time.sleep(0.2)

        # Verify callback was called with service result
        mock_callback.assert_called_once()
        result = mock_callback.call_args[0][0]
        assert result.status == UpdateStatus.SUCCESS
        assert result.update_method == UpdateMethod.SERVICE_SIGNAL

    def test_async_falls_back_to_manual(self, updater_module):
        """Test async update falls back to manual when service unavailable."""
        from src.core.updater import (
            FreshclamServiceStatus,
            FreshclamUpdater,
            UpdateMethod,
            UpdateStatus,
        )

        mock_log_manager = MagicMock()
        mock_callback = MagicMock()
        mock_glib = updater_module["glib"]

        mock_process = MagicMock()
        mock_process.communicate.return_value = ("daily.cvd updated (version: 26929", "")
        mock_process.returncode = 0
        mock_process.poll.return_value = 0

        with patch("src.core.updater.GLib", mock_glib):
            with patch("src.core.updater.is_flatpak", return_value=False):
                with patch(
                    "src.core.updater.check_freshclam_installed", return_value=(True, "0.103.8")
                ):
                    with patch("shutil.which", return_value="/usr/bin/pkexec"):
                        with patch("subprocess.Popen", return_value=mock_process):
                            with patch(
                                "src.core.updater.wrap_host_command", side_effect=lambda x: x
                            ):
                                updater = FreshclamUpdater(log_manager=mock_log_manager)
                                with patch.object(
                                    updater,
                                    "check_freshclam_service",
                                    return_value=(FreshclamServiceStatus.NOT_FOUND, None),
                                ):
                                    with patch.object(
                                        updater,
                                        "_check_freshclam_running",
                                        return_value=(False, None),
                                    ):
                                        updater.update_async(mock_callback, prefer_service=True)

                                        import time

                                        time.sleep(0.2)

        mock_callback.assert_called_once()
        result = mock_callback.call_args[0][0]
        assert result.status == UpdateStatus.SUCCESS
        assert result.update_method == UpdateMethod.MANUAL


# =============================================================================
# FreshclamServiceStatus Enum Completeness Tests
# =============================================================================


class TestFreshclamServiceStatusCompleteness:
    """Tests for FreshclamServiceStatus enum completeness."""

    def test_all_status_values_exist(self, updater_module):
        """Test all expected status values exist."""
        from src.core.updater import FreshclamServiceStatus

        assert hasattr(FreshclamServiceStatus, "RUNNING")
        assert hasattr(FreshclamServiceStatus, "STOPPED")
        assert hasattr(FreshclamServiceStatus, "NOT_FOUND")
        assert hasattr(FreshclamServiceStatus, "UNKNOWN")

    def test_status_count(self, updater_module):
        """Test correct number of status values."""
        from src.core.updater import FreshclamServiceStatus

        assert len(FreshclamServiceStatus) == 4


# =============================================================================
# UpdateMethod Enum Completeness Tests
# =============================================================================


class TestUpdateMethodCompleteness:
    """Tests for UpdateMethod enum completeness."""

    def test_all_method_values_exist(self, updater_module):
        """Test all expected method values exist."""
        from src.core.updater import UpdateMethod

        assert hasattr(UpdateMethod, "SERVICE_SIGNAL")
        assert hasattr(UpdateMethod, "MANUAL")

    def test_method_count(self, updater_module):
        """Test correct number of method values."""
        from src.core.updater import UpdateMethod

        assert len(UpdateMethod) == 2


# =============================================================================
# Force-update staging race regression tests
# =============================================================================


@pytest.fixture
def force_update_script_builder():
    """Return the force-update shell-script builder under test."""
    from src.core.updater import _build_force_update_script

    return _build_force_update_script


def _write_blocking_fake_freshclam(tmp_path: Path, *, outcome: str) -> Path:
    """Create a fake freshclam that blocks before completing its download."""
    script_path = tmp_path / f"fake-freshclam-{outcome}"
    script_path.write_text(
        """#!/bin/sh
set -eu

datadir=
while [ "$#" -gt 0 ]; do
    arg=$1
    shift
    case "$arg" in
        --datadir=*) datadir=${arg#--datadir=} ;;
        --datadir)
            [ "$#" -gt 0 ]
            datadir=$1
            shift
            ;;
    esac
done

[ -n "$datadir" ]
printf '%s' "$datadir" > "$FAKE_DATADIR_MARKER"
: > "$FAKE_STARTED_MARKER"
IFS= read -r release_token
if [ "$FAKE_OUTCOME" = success ]; then
    printf '%s' "$FAKE_REPLACEMENT" > "$datadir/main.cvd"
    exit 0
fi
printf '%s' "$FAKE_FAILURE_CANDIDATE" > "$datadir/main.cvd"
exit 1
""",
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path


def _wait_for_marker(marker: Path, process: subprocess.Popen, timeout: float = 5.0) -> None:
    """Wait for a fake freshclam marker without an unbounded race-prone sleep."""
    deadline = time.monotonic() + timeout
    while not marker.exists():
        if process.poll() is not None:
            raise AssertionError(f"freshclam exited before creating marker: {marker}")
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for marker: {marker}")
        time.sleep(0.01)


def _finish_blocked_update(process: subprocess.Popen, *, expected_returncode: int) -> None:
    """Release a blocked fake freshclam and reap the shell process."""
    try:
        stdout, stderr = process.communicate(input=b"release\n", timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == expected_returncode, (
        f"force-update script exited {process.returncode}, stdout={stdout!r}, stderr={stderr!r}"
    )


class TestForceUpdateStaging:
    """Exercise force updates through the generated shell script."""

    def test_success_preserves_live_database_until_staged_download_is_ready(
        self,
        tmp_path: Path,
        force_update_script_builder,
    ):
        database_dir = tmp_path / "clamav"
        database_dir.mkdir()
        live_database = database_dir / "main.cvd"
        original_bytes = b"live-database-before-update"
        live_database.write_bytes(original_bytes)

        started_marker = tmp_path / "success.started"
        datadir_marker = tmp_path / "success.datadir"
        fake_freshclam = _write_blocking_fake_freshclam(
            tmp_path,
            outcome="success",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "FAKE_STARTED_MARKER": str(started_marker),
                "FAKE_DATADIR_MARKER": str(datadir_marker),
                "FAKE_OUTCOME": "success",
                "FAKE_REPLACEMENT": "fresh-staged-database",
                "FAKE_FAILURE_CANDIDATE": "unused-failure-candidate",
            }
        )

        script = force_update_script_builder(str(database_dir))
        process = subprocess.Popen(
            ["sh", "-c", script, "clamui-force-update", str(fake_freshclam)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        try:
            _wait_for_marker(started_marker, process)

            assert live_database.is_file()
            assert live_database.read_bytes() == original_bytes
            staging_dir = Path(datadir_marker.read_text(encoding="utf-8"))
            assert staging_dir != database_dir
            assert process.poll() is None

            _finish_blocked_update(process, expected_returncode=0)
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.communicate()
            raise

        assert live_database.read_bytes() == b"fresh-staged-database"

    def test_failure_leaves_original_live_database_after_staged_download_fails(
        self,
        tmp_path: Path,
        force_update_script_builder,
    ):
        database_dir = tmp_path / "clamav"
        database_dir.mkdir()
        live_database = database_dir / "main.cvd"
        original_bytes = b"live-database-before-failed-update"
        live_database.write_bytes(original_bytes)

        started_marker = tmp_path / "failure.started"
        datadir_marker = tmp_path / "failure.datadir"
        fake_freshclam = _write_blocking_fake_freshclam(
            tmp_path,
            outcome="failure",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "FAKE_STARTED_MARKER": str(started_marker),
                "FAKE_DATADIR_MARKER": str(datadir_marker),
                "FAKE_OUTCOME": "failure",
                "FAKE_REPLACEMENT": "unused-success-candidate",
                "FAKE_FAILURE_CANDIDATE": "partial-staged-database",
            }
        )

        script = force_update_script_builder(str(database_dir))
        process = subprocess.Popen(
            ["sh", "-c", script, "clamui-force-update", str(fake_freshclam)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        try:
            _wait_for_marker(started_marker, process)

            assert live_database.is_file()
            assert live_database.read_bytes() == original_bytes
            staging_dir = Path(datadir_marker.read_text(encoding="utf-8"))
            assert staging_dir != database_dir
            assert process.poll() is None

            _finish_blocked_update(process, expected_returncode=1)
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.communicate()
            raise

        assert live_database.is_file()
        assert live_database.read_bytes() == original_bytes
