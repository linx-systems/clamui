# ClamUI System Audit Tests
"""Unit tests for the system audit module."""

import subprocess
from unittest.mock import MagicMock, patch

from src.core.portmaster_client import (
    PortmasterModuleRow,
    PortmasterProbeResult,
    PortmasterStatus,
)
from src.core.system_audit import (
    TIER1_CHECKS,
    AuditCategory,
    AuditCheckResult,
    AuditReport,
    AuditSectionResult,
    AuditStatus,
    _check_systemd_service,
    _check_ufw_enabled,
    _parse_cvd_age,
    check_auto_updates,
    check_clamav_health,
    check_firewall,
    check_intrusion_detection,
    check_mac_framework,
    check_portmaster,
    check_ssh_hardening,
    run_lynis_audit,
    run_rootkit_check,
)

# =============================================================================
# Dataclass Tests
# =============================================================================


class TestAuditCheckResult:
    """Tests for AuditCheckResult dataclass."""

    def test_basic_creation(self):
        result = AuditCheckResult(
            name="Test Check",
            status=AuditStatus.PASS,
            detail="All good",
        )
        assert result.name == "Test Check"
        assert result.status == AuditStatus.PASS
        assert result.recommendation is None
        assert result.install_command is None

    def test_with_recommendation(self):
        result = AuditCheckResult(
            name="Test",
            status=AuditStatus.FAIL,
            detail="Bad",
            recommendation="Fix it",
            install_command="sudo fix-it",
        )
        assert result.recommendation == "Fix it"
        assert result.install_command == "sudo fix-it"


class TestAuditSectionResult:
    """Tests for AuditSectionResult.overall_status property."""

    def test_empty_section_is_unknown(self):
        section = AuditSectionResult(
            category=AuditCategory.FIREWALL,
            title="Test",
            icon_name="test",
        )
        assert section.overall_status == AuditStatus.UNKNOWN

    def test_all_pass(self):
        section = AuditSectionResult(
            category=AuditCategory.FIREWALL,
            title="Test",
            icon_name="test",
            checks=[
                AuditCheckResult("A", AuditStatus.PASS, "ok"),
                AuditCheckResult("B", AuditStatus.PASS, "ok"),
            ],
        )
        assert section.overall_status == AuditStatus.PASS

    def test_fail_wins_over_pass(self):
        section = AuditSectionResult(
            category=AuditCategory.FIREWALL,
            title="Test",
            icon_name="test",
            checks=[
                AuditCheckResult("A", AuditStatus.PASS, "ok"),
                AuditCheckResult("B", AuditStatus.FAIL, "bad"),
            ],
        )
        assert section.overall_status == AuditStatus.FAIL

    def test_warning_wins_over_pass(self):
        section = AuditSectionResult(
            category=AuditCategory.FIREWALL,
            title="Test",
            icon_name="test",
            checks=[
                AuditCheckResult("A", AuditStatus.PASS, "ok"),
                AuditCheckResult("B", AuditStatus.WARNING, "meh"),
            ],
        )
        assert section.overall_status == AuditStatus.WARNING

    def test_fail_wins_over_warning(self):
        section = AuditSectionResult(
            category=AuditCategory.FIREWALL,
            title="Test",
            icon_name="test",
            checks=[
                AuditCheckResult("A", AuditStatus.WARNING, "meh"),
                AuditCheckResult("B", AuditStatus.FAIL, "bad"),
            ],
        )
        assert section.overall_status == AuditStatus.FAIL


class TestAuditReport:
    """Tests for AuditReport.summary property."""

    def test_empty_report(self):
        report = AuditReport()
        assert report.summary == {}

    def test_summary_counts(self):
        report = AuditReport(
            sections=[
                AuditSectionResult(
                    AuditCategory.FIREWALL,
                    "FW",
                    "x",
                    [AuditCheckResult("A", AuditStatus.PASS, "ok")],
                ),
                AuditSectionResult(
                    AuditCategory.SSH_HARDENING,
                    "SSH",
                    "x",
                    [AuditCheckResult("B", AuditStatus.FAIL, "bad")],
                ),
                AuditSectionResult(
                    AuditCategory.MAC_FRAMEWORK,
                    "MAC",
                    "x",
                    [AuditCheckResult("C", AuditStatus.PASS, "ok")],
                ),
            ]
        )
        summary = report.summary
        assert summary[AuditStatus.PASS] == 2
        assert summary[AuditStatus.FAIL] == 1


# =============================================================================
# Helper Tests
# =============================================================================


class TestCheckSystemdService:
    """Tests for _check_systemd_service helper."""

    @patch("src.core.system_audit.subprocess.run")
    def test_active_service(self, mock_run):
        mock_run.return_value = MagicMock(stdout="active\n", returncode=0)
        is_active, status = _check_systemd_service("test-service")
        assert is_active is True
        assert status == "active"

    @patch("src.core.system_audit.subprocess.run")
    def test_inactive_service(self, mock_run):
        mock_run.return_value = MagicMock(stdout="inactive\n", returncode=3)
        is_active, status = _check_systemd_service("test-service")
        assert is_active is False
        assert status == "inactive"

    @patch("src.core.system_audit.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)
        is_active, status = _check_systemd_service("test-service")
        assert is_active is False
        assert status == "timeout"

    @patch("src.core.system_audit.subprocess.run")
    def test_command_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        is_active, status = _check_systemd_service("test-service")
        assert is_active is False
        assert status == "systemctl not found"


class TestParseCvdAge:
    """Tests for _parse_cvd_age helper."""

    def test_valid_cvd_header(self, tmp_path):
        """Test parsing a valid CVD header."""
        import time

        # Build timestamp 2 days ago
        build_ts = int(time.time()) - (2 * 86400)
        header = f"ClamAV-VDB:02 Apr 2026:100:1000000:77:md5:dsig:builder:{build_ts}"
        header_bytes = header.encode("ascii")
        # Pad with null bytes to 512 bytes (real CVD format)
        header_bytes += b"\x00" * (512 - len(header_bytes))

        cvd_file = tmp_path / "daily.cvd"
        cvd_file.write_bytes(header_bytes)

        days_old, date_str = _parse_cvd_age(str(cvd_file))
        assert days_old is not None
        assert days_old >= 1  # At least 1 day old (rounding)
        assert date_str == "02 Apr 2026"

    def test_missing_file(self):
        days_old, error = _parse_cvd_age("/nonexistent/path/daily.cvd")
        assert days_old is None
        assert error is not None

    def test_invalid_format(self, tmp_path):
        cvd_file = tmp_path / "bad.cvd"
        cvd_file.write_text("not a valid cvd file")

        days_old, error = _parse_cvd_age(str(cvd_file))
        assert days_old is None
        assert error is not None


# =============================================================================
# Check Function Tests
# =============================================================================


class TestCheckClamavHealth:
    """Tests for check_clamav_health function."""

    @patch("src.core.system_audit.check_clamav_installed")
    def test_clamav_not_installed(self, mock_installed):
        mock_installed.return_value = (False, "not installed")
        result = check_clamav_health()
        assert result.category == AuditCategory.CLAMAV_HEALTH
        assert any(c.status == AuditStatus.FAIL for c in result.checks)
        # Should return early with just the installation check
        assert len(result.checks) == 1

    @patch("src.core.system_audit._check_systemd_service")
    @patch("src.core.system_audit.check_clamd_connection")
    @patch("src.core.system_audit._find_daily_cvd_path")
    @patch("src.core.system_audit.check_clamav_installed")
    def test_clamav_healthy(self, mock_installed, mock_cvd_path, mock_clamd, mock_systemd):
        mock_installed.return_value = (True, "ClamAV 1.0.0")
        mock_cvd_path.return_value = None
        mock_clamd.return_value = (True, "PONG")
        # Simulate: clamav-daemon active on first call,
        # clamav-freshclam active on fourth call
        mock_systemd.side_effect = [
            (True, "active"),  # clamav-daemon
            (True, "active"),  # clamav-freshclam
        ]

        with patch("src.core.system_audit.check_database_available") as mock_db:
            mock_db.return_value = (True, None)
            result = check_clamav_health()

        assert result.category == AuditCategory.CLAMAV_HEALTH
        assert len(result.checks) >= 3


class TestCheckFirewall:
    """Tests for check_firewall function."""

    @patch("src.core.system_audit._run_command")
    def test_ufw_enabled_uses_status_command(self, mock_run_cmd):
        """UFW enabled detection should use the host CLI status when available."""
        mock_run_cmd.return_value = (0, "Status: active", "")

        assert _check_ufw_enabled() is True
        mock_run_cmd.assert_called_once_with(["ufw", "status"])

    @patch("src.core.system_audit.is_flatpak", return_value=True)
    @patch("src.core.system_audit._run_command")
    def test_ufw_enabled_falls_back_to_config(self, mock_run_cmd, mock_is_flatpak):
        """If ufw status cannot be queried, fall back to host config parsing."""
        mock_run_cmd.side_effect = [
            (-1, "", "command not found"),
            (0, "# comment\nENABLED=yes\n", ""),
        ]

        assert _check_ufw_enabled() is True
        assert mock_run_cmd.call_args_list[0].args[0] == ["ufw", "status"]
        assert mock_run_cmd.call_args_list[1].args[0] == ["cat", "/etc/ufw/ufw.conf"]
        mock_is_flatpak.assert_called_once()

    @patch("src.core.system_audit._check_firewall_gui")
    @patch("src.core.system_audit._check_open_ports")
    @patch("src.core.system_audit._run_command")
    @patch("src.core.system_audit._check_systemd_service")
    def test_ufw_active(self, mock_systemd, mock_run_cmd, mock_ports, mock_gui):
        mock_systemd.return_value = (True, "active")
        mock_ports.return_value = None
        mock_gui.return_value = None

        with patch("src.core.system_audit._check_ufw_enabled", return_value=True):
            result = check_firewall()

        assert result.category == AuditCategory.FIREWALL
        assert any(c.status == AuditStatus.PASS and "UFW" in c.name for c in result.checks)

    @patch("src.core.system_audit._check_firewall_gui")
    @patch("src.core.system_audit._check_open_ports")
    @patch("src.core.system_audit._run_command")
    @patch("src.core.system_audit._check_systemd_service")
    def test_no_firewall(self, mock_systemd, mock_run_cmd, mock_ports, mock_gui):
        # No firewall found
        mock_systemd.return_value = (False, "inactive")
        mock_run_cmd.return_value = (-1, "", "command not found")
        mock_ports.return_value = None
        mock_gui.return_value = None

        result = check_firewall()
        assert any(c.status == AuditStatus.FAIL for c in result.checks)


class TestCheckMacFramework:
    """Tests for check_mac_framework function."""

    @patch("src.core.system_audit._check_selinux")
    @patch("src.core.system_audit._check_apparmor")
    def test_apparmor_enabled(self, mock_apparmor, mock_selinux):
        mock_apparmor.return_value = AuditCheckResult("AppArmor", AuditStatus.PASS, "enabled")
        mock_selinux.return_value = None
        result = check_mac_framework()
        assert any(c.status == AuditStatus.PASS for c in result.checks)

    @patch("src.core.system_audit._check_selinux")
    @patch("src.core.system_audit._check_apparmor")
    def test_neither_found(self, mock_apparmor, mock_selinux):
        mock_apparmor.return_value = None
        mock_selinux.return_value = None
        result = check_mac_framework()
        assert any(c.status == AuditStatus.UNKNOWN for c in result.checks)


class TestCheckSshHardening:
    """Tests for check_ssh_hardening function."""

    @patch("src.core.system_audit._check_systemd_service")
    def test_sshd_not_running(self, mock_systemd):
        mock_systemd.return_value = (False, "inactive")
        result = check_ssh_hardening()
        # If sshd not running, that's a pass (no attack surface)
        assert result.checks[0].status == AuditStatus.PASS

    @patch("src.core.system_audit._parse_sshd_config")
    @patch("src.core.system_audit._check_systemd_service")
    def test_sshd_running_good_config(self, mock_systemd, mock_config):
        mock_systemd.side_effect = [
            (True, "active"),  # sshd is running
        ]
        mock_config.return_value = {
            "permitrootlogin": "no",
            "passwordauthentication": "no",
            "x11forwarding": "no",
        }
        result = check_ssh_hardening()
        # All SSH checks should pass
        assert all(c.status == AuditStatus.PASS for c in result.checks)

    @patch("src.core.system_audit._parse_sshd_config")
    @patch("src.core.system_audit._check_systemd_service")
    def test_sshd_running_weak_config(self, mock_systemd, mock_config):
        mock_systemd.side_effect = [
            (True, "active"),
        ]
        mock_config.return_value = {
            "permitrootlogin": "yes",
            "passwordauthentication": "yes",
            "x11forwarding": "yes",
        }
        result = check_ssh_hardening()
        # Should have at least one fail (root login) and warnings
        statuses = [c.status for c in result.checks]
        assert AuditStatus.FAIL in statuses
        assert AuditStatus.WARNING in statuses


class TestCheckIntrustionDetection:
    """Tests for check_intrusion_detection function."""

    @patch("src.core.system_audit._check_systemd_service")
    def test_fail2ban_active(self, mock_systemd):
        mock_systemd.side_effect = [
            (True, "active"),  # fail2ban
            (False, "inactive"),  # crowdsec
        ]
        result = check_intrusion_detection()
        assert any(c.status == AuditStatus.PASS and "fail2ban" in c.name for c in result.checks)

    @patch("src.core.system_audit.is_binary_installed")
    @patch("src.core.system_audit._check_systemd_service")
    def test_nothing_installed(self, mock_systemd, mock_binary):
        mock_systemd.return_value = (False, "inactive")
        mock_binary.return_value = False  # No binaries found
        result = check_intrusion_detection()
        assert any(c.status == AuditStatus.UNKNOWN for c in result.checks)

    @patch("src.core.system_audit.is_binary_installed")
    @patch("src.core.system_audit._check_systemd_service")
    def test_inactive_but_not_installed_is_not_warning(self, mock_systemd, mock_binary):
        """systemctl returns 'inactive' for non-installed services too.
        We should NOT show 'installed but not running' if the binary doesn't exist."""
        mock_systemd.return_value = (False, "inactive")
        mock_binary.return_value = False
        result = check_intrusion_detection()
        # Should NOT have any WARNING about "installed but not running"
        assert not any(c.status == AuditStatus.WARNING for c in result.checks)


class TestCheckAutoUpdates:
    """Tests for check_auto_updates function."""

    @patch("src.core.system_audit._check_pending_reboot")
    @patch("src.core.system_audit._check_systemd_service")
    @patch("src.core.system_audit._run_command")
    def test_unattended_upgrades_enabled(self, mock_cmd, mock_systemd, mock_reboot):
        mock_cmd.return_value = (
            0,
            'APT::Periodic::Unattended-Upgrade "1";',
            "",
        )
        mock_reboot.return_value = None
        result = check_auto_updates()
        assert any(c.status == AuditStatus.PASS for c in result.checks)


# =============================================================================
# Deep Scan Tests
# =============================================================================


class TestRunLynisAudit:
    """Tests for run_lynis_audit function."""

    @patch("src.core.system_audit._run_command")
    def test_lynis_not_installed(self, mock_cmd):
        mock_cmd.return_value = (-1, "", "command not found")
        result = run_lynis_audit()
        assert result.category == AuditCategory.DEEP_SCAN_LYNIS
        assert result.checks[0].status == AuditStatus.UNKNOWN

    @patch("src.core.system_audit._parse_lynis_report")
    @patch("src.core.system_audit.subprocess.run")
    @patch("src.core.system_audit._run_command")
    def test_lynis_pkexec_cancelled(self, mock_cmd, mock_run, mock_report):
        mock_cmd.return_value = (0, "/usr/bin/lynis", "")
        mock_run.return_value = MagicMock(returncode=126, stdout="", stderr="")
        result = run_lynis_audit()
        assert result.checks[0].status == AuditStatus.SKIPPED


class TestRunRootkitCheck:
    """Tests for run_rootkit_check function."""

    @patch("src.core.system_audit._run_command")
    def test_chkrootkit_not_installed(self, mock_cmd):
        mock_cmd.return_value = (-1, "", "command not found")
        result = run_rootkit_check()
        assert result.category == AuditCategory.DEEP_SCAN_ROOTKIT
        assert result.checks[0].status == AuditStatus.UNKNOWN

    @patch("src.core.system_audit.subprocess.run")
    @patch("src.core.system_audit._run_command")
    def test_chkrootkit_clean(self, mock_cmd, mock_run):
        mock_cmd.return_value = (0, "/usr/sbin/chkrootkit", "")
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Checking `amd'... not found\nChecking `basename'... not infected\n",
            stderr="",
        )
        result = run_rootkit_check()
        assert any(c.status == AuditStatus.PASS for c in result.checks)

    @patch("src.core.system_audit.subprocess.run")
    @patch("src.core.system_audit._run_command")
    def test_chkrootkit_infected(self, mock_cmd, mock_run):
        mock_cmd.return_value = (0, "/usr/sbin/chkrootkit", "")
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Checking `bindshell'... INFECTED\n",
            stderr="",
        )
        result = run_rootkit_check()
        assert any(c.status == AuditStatus.FAIL for c in result.checks)


# =============================================================================
# TIER1_CHECKS List
# =============================================================================


class TestTier1ChecksList:
    """Verify TIER1_CHECKS contains all expected functions."""

    def test_contains_all_checks(self):
        assert len(TIER1_CHECKS) == 7
        func_names = [f.__name__ for f in TIER1_CHECKS]
        assert "check_clamav_health" in func_names
        assert "check_firewall" in func_names
        assert "check_mac_framework" in func_names
        assert "check_auto_updates" in func_names
        assert "check_intrusion_detection" in func_names
        assert "check_ssh_hardening" in func_names
        assert "check_portmaster" in func_names


class TestCheckPortmaster:
    """Tests for check_portmaster — must NEVER produce FAIL or WARNING when
    Portmaster is simply not present (this is the contract enforced by the
    user requirement 'if not detected or found it should not raise any flags').
    """

    @patch("src.core.system_audit.get_portmaster_token", return_value=None)
    @patch("src.core.system_audit.probe_portmaster")
    def test_not_installed_is_skipped_only(self, mock_probe, mock_token):
        mock_probe.return_value = PortmasterProbeResult(status=PortmasterStatus.NOT_INSTALLED)
        section = check_portmaster()
        assert section.category == AuditCategory.PORTMASTER
        assert section.overall_status == AuditStatus.SKIPPED
        # Critical invariant: never FAIL or WARNING when absent.
        assert not any(c.status in (AuditStatus.FAIL, AuditStatus.WARNING) for c in section.checks)

    @patch("src.core.system_audit.get_portmaster_token", return_value=None)
    @patch("src.core.system_audit.probe_portmaster")
    def test_installed_not_running_is_warning(self, mock_probe, mock_token):
        mock_probe.return_value = PortmasterProbeResult(
            status=PortmasterStatus.INSTALLED_NOT_RUNNING
        )
        section = check_portmaster()
        assert section.overall_status == AuditStatus.WARNING
        assert any(c.install_command == "sudo systemctl start portmaster" for c in section.checks)

    @patch("src.core.system_audit.get_portmaster_token", return_value=None)
    @patch("src.core.system_audit.probe_portmaster")
    def test_running_without_token_offers_authorize(self, mock_probe, mock_token):
        mock_probe.return_value = PortmasterProbeResult(status=PortmasterStatus.RUNNING)
        section = check_portmaster()
        assert section.overall_status == AuditStatus.PASS
        # Without a token we should offer the Authorize sentinel.
        assert any(c.launch_command == "__portmaster_authorize__" for c in section.checks)

    @patch("src.core.system_audit.get_portmaster_token", return_value="cached-token")
    @patch("src.core.system_audit.probe_portmaster")
    def test_running_with_modules_renders_module_rows(self, mock_probe, mock_token):
        mock_probe.return_value = PortmasterProbeResult(
            status=PortmasterStatus.RUNNING,
            module_status={"core": {"Status": "online"}},
            module_rows=[
                PortmasterModuleRow(name="core", status="online"),
                PortmasterModuleRow(name="filter", status="error", failure_msg="boom"),
            ],
        )
        section = check_portmaster()
        names = [c.name for c in section.checks]
        assert "core" in names
        assert "filter" in names
        assert any(c.status == AuditStatus.FAIL and c.name == "filter" for c in section.checks)

    @patch("src.core.system_audit.delete_portmaster_token")
    @patch("src.core.system_audit.get_portmaster_token", return_value="stale-token")
    @patch("src.core.system_audit.probe_portmaster")
    def test_stale_token_is_cleared(self, mock_probe, mock_token, mock_delete):
        mock_probe.return_value = PortmasterProbeResult(
            status=PortmasterStatus.RUNNING,
            modules_unauthorized=True,
        )
        check_portmaster()
        mock_delete.assert_called_once()

    @patch("src.core.system_audit.get_portmaster_token", return_value=None)
    @patch("src.core.system_audit.probe_portmaster")
    def test_error_is_unknown_not_fail(self, mock_probe, mock_token):
        mock_probe.return_value = PortmasterProbeResult(
            status=PortmasterStatus.ERROR, error="connection reset"
        )
        section = check_portmaster()
        assert section.overall_status == AuditStatus.UNKNOWN
        assert not any(c.status == AuditStatus.FAIL for c in section.checks)
