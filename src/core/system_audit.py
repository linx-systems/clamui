# ClamUI System Audit Module
"""
System security posture auditing for ClamUI.

This module checks multiple aspects of system security and returns
structured results with status indicators and actionable recommendations.

Tier 1 checks (no root required, run automatically):
- ClamAV health: database age, daemon status, freshclam timer
- Firewall: auto-detect ufw/firewalld/nftables, open ports
- MAC framework: AppArmor or SELinux status
- Automatic updates: unattended-upgrades or dnf-automatic
- Intrusion detection: fail2ban or CrowdSec status
- SSH hardening: sshd_config key settings

Tier 2 deep scans (root via pkexec, opt-in):
- Lynis: comprehensive security audit with hardening score
- chkrootkit: rootkit detection scan
"""

import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .clamav_detection import (
    check_clamav_installed,
    check_clamd_connection,
    check_database_available,
)
from .flatpak import get_clean_env, is_flatpak, wrap_host_command
from .i18n import _
from .keyring_manager import delete_portmaster_token, get_portmaster_token
from .portmaster_client import PortmasterStatus, probe_portmaster
from .sanitize import sanitize_log_line

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class AuditStatus(Enum):
    """Status of a security audit check."""

    PASS = "pass"  # noqa: S105 - not a password
    WARNING = "warning"
    FAIL = "fail"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"
    CHECKING = "checking"


class AuditCategory(Enum):
    """Categories of security audit checks."""

    CLAMAV_HEALTH = "clamav_health"
    FIREWALL = "firewall"
    MAC_FRAMEWORK = "mac_framework"
    AUTO_UPDATES = "auto_updates"
    INTRUSION_DETECTION = "intrusion_detection"
    SSH_HARDENING = "ssh_hardening"
    PORTMASTER = "portmaster"
    DEEP_SCAN_LYNIS = "deep_scan_lynis"
    DEEP_SCAN_ROOTKIT = "deep_scan_rootkit"


# Reference URLs for security audit checks — official docs and guides
_URLS = {
    "clamav": "https://docs.clamav.net/",
    "clamav_freshclam": "https://docs.clamav.net/manual/Usage/SignatureManagement.html",
    "clamav_clamd": "https://docs.clamav.net/manual/Usage/Scanning.html#clamd",
    "ufw": "https://wiki.archlinux.org/title/Uncomplicated_Firewall",
    "firewalld": "https://firewalld.org/documentation/",
    "nftables": "https://wiki.archlinux.org/title/Nftables",
    "apparmor": "https://wiki.archlinux.org/title/AppArmor",
    "selinux": "https://wiki.archlinux.org/title/SELinux",
    "unattended_upgrades": "https://wiki.debian.org/UnattendedUpgrades",
    "dnf_automatic": "https://dnf.readthedocs.io/en/latest/automatic.html",
    "fail2ban": "https://github.com/fail2ban/fail2ban/wiki",
    "crowdsec": "https://docs.crowdsec.net/",
    "ssh_hardening": "https://wiki.archlinux.org/title/OpenSSH#Protection",
    "ssh_root_login": "https://man7.org/linux/man-pages/man5/sshd_config.5.html",
    "lynis": "https://cisofy.com/lynis/",
    "chkrootkit": "https://www.chkrootkit.org/",
    "open_ports": "https://wiki.archlinux.org/title/Security#Network",
    "portmaster": "https://safing.io/portmaster/",
    "portmaster_install": "https://docs.safing.io/portmaster/install/linux",
    "portmaster_api": "https://docs.safing.io/portmaster/api",
}

# Status priority for overall_status computation (worst wins)
_STATUS_PRIORITY = [
    AuditStatus.FAIL,
    AuditStatus.WARNING,
    AuditStatus.UNKNOWN,
    AuditStatus.PASS,
    AuditStatus.SKIPPED,
    AuditStatus.CHECKING,
]


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass
class AuditCheckResult:
    """Result of a single security check within a section."""

    name: str
    status: AuditStatus
    detail: str
    recommendation: str | None = None
    install_command: str | None = None
    info_url: str | None = None
    launch_command: str | None = None
    launch_label: str | None = None


@dataclass
class AuditSectionResult:
    """Result of a section containing multiple related checks."""

    category: AuditCategory
    title: str
    icon_name: str
    checks: list[AuditCheckResult] = field(default_factory=list)

    @property
    def overall_status(self) -> AuditStatus:
        """Return the worst status among all checks in this section."""
        if not self.checks:
            return AuditStatus.UNKNOWN
        for status in _STATUS_PRIORITY:
            if any(c.status == status for c in self.checks):
                return status
        return AuditStatus.UNKNOWN


@dataclass
class AuditReport:
    """Full audit report containing all section results."""

    sections: list[AuditSectionResult] = field(default_factory=list)
    timestamp: float = 0.0

    @property
    def summary(self) -> dict[AuditStatus, int]:
        """Count of sections by their overall status."""
        counts: dict[AuditStatus, int] = {}
        for section in self.sections:
            s = section.overall_status
            counts[s] = counts.get(s, 0) + 1
        return counts


# =============================================================================
# Helpers
# =============================================================================

_SUBPROCESS_TIMEOUT = 10


def _check_systemd_service(service_name: str) -> tuple[bool, str]:
    """Check if a systemd service is active.

    Returns:
        (is_active, status_text) where status_text is the raw output
        like "active", "inactive", "failed", or an error message.
    """
    try:
        result = subprocess.run(
            wrap_host_command(["systemctl", "is-active", service_name]),
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            env=get_clean_env(),
        )
        status = sanitize_log_line(result.stdout.strip())
        return (status == "active", status)
    except subprocess.TimeoutExpired:
        return (False, "timeout")
    except FileNotFoundError:
        return (False, "systemctl not found")
    except OSError as e:
        logger.debug("systemctl check failed for %s: %s", service_name, e)
        return (False, str(e))


def is_binary_installed(binary_name: str) -> bool:
    """Check if a binary is available on the system (or host if Flatpak)."""
    rc, _stdout, _stderr = _run_command(["which", binary_name])
    return rc == 0


def _is_service_installed(service_name: str) -> bool:
    """Check if a systemd service unit file exists (not just active).

    systemctl is-active returns 'inactive' for BOTH 'installed but stopped'
    and 'not installed at all'. This function uses 'systemctl cat' to
    distinguish — it returns 0 only if the unit file actually exists.
    """
    rc, _stdout, _stderr = _run_command(["systemctl", "cat", service_name])
    return rc == 0


def _run_command(args: list[str], timeout: int = _SUBPROCESS_TIMEOUT) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr).

    All output is sanitized. Returns (-1, "", error) on failure.
    """
    try:
        result = subprocess.run(
            wrap_host_command(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=get_clean_env(),
        )
        return (
            result.returncode,
            sanitize_log_line(result.stdout.strip()),
            sanitize_log_line(result.stderr.strip()),
        )
    except subprocess.TimeoutExpired:
        return (-1, "", "command timed out")
    except FileNotFoundError:
        return (-1, "", "command not found")
    except OSError as e:
        return (-1, "", str(e))


def _parse_cvd_age(cvd_path: str) -> tuple[int | None, str | None]:
    """Parse a ClamAV .cvd/.cld file header to determine database age.

    The CVD header is in the first 512 bytes, colon-delimited:
    ClamAV-VDB:build_time:version:sigs:flevel:md5:dsig:builder:stime

    Returns:
        (days_old, build_date_string) or (None, error_message).
    """
    try:
        with open(cvd_path, "rb") as f:
            header = f.read(512).decode("ascii", errors="ignore")
    except FileNotFoundError:
        return (None, _("Database file not found"))
    except PermissionError:
        return (None, _("Permission denied reading database"))
    except OSError as e:
        return (None, str(e))

    fields = header.split(":")
    if len(fields) < 9 or not fields[0].startswith("ClamAV-VDB"):
        return (None, _("Invalid database file format"))

    try:
        # Strip null bytes from padded header
        stime = fields[8].strip().strip("\x00")
        build_timestamp = int(stime)
        age_seconds = time.time() - build_timestamp
        days_old = int(age_seconds / 86400)
        return (days_old, fields[1])
    except (ValueError, IndexError):
        return (None, _("Could not parse database timestamp"))


def _find_daily_cvd_path() -> str | None:
    """Find the path to the daily.cvd or daily.cld database file."""
    if is_flatpak():
        return None

    db_dir = Path("/var/lib/clamav")

    for ext in (".cvd", ".cld"):
        path = db_dir / f"daily{ext}"
        if path.exists():
            return str(path)
    return None


# =============================================================================
# Tier 1 Check Functions
# =============================================================================


def check_clamav_health() -> AuditSectionResult:
    """Check ClamAV installation, database age, and daemon status."""
    section = AuditSectionResult(
        category=AuditCategory.CLAMAV_HEALTH,
        title=_("ClamAV Health"),
        icon_name="security-high-symbolic",
    )

    # Check 1: ClamAV installed
    installed, version_or_error = check_clamav_installed()
    if installed:
        section.checks.append(
            AuditCheckResult(
                name=_("ClamAV Installation"),
                status=AuditStatus.PASS,
                detail=_("Installed: {version}").format(version=version_or_error),
                info_url=_URLS["clamav"],
            )
        )
    else:
        section.checks.append(
            AuditCheckResult(
                name=_("ClamAV Installation"),
                status=AuditStatus.FAIL,
                detail=_("ClamAV is not installed"),
                recommendation=_("Install ClamAV to enable virus scanning"),
                install_command="sudo apt install clamav clamav-daemon",
                info_url=_URLS["clamav"],
            )
        )
        return section  # No point checking further

    # Check 2: Database age
    daily_path = _find_daily_cvd_path()
    if daily_path:
        days_old, date_str = _parse_cvd_age(daily_path)
        if days_old is not None:
            if days_old <= 3:
                section.checks.append(
                    AuditCheckResult(
                        name=_("Virus Database"),
                        status=AuditStatus.PASS,
                        detail=_("Up to date ({days} days old, built {date})").format(
                            days=days_old, date=date_str
                        ),
                        info_url=_URLS["clamav_freshclam"],
                    )
                )
            elif days_old <= 7:
                section.checks.append(
                    AuditCheckResult(
                        name=_("Virus Database"),
                        status=AuditStatus.WARNING,
                        detail=_("Database is {days} days old (built {date})").format(
                            days=days_old, date=date_str
                        ),
                        recommendation=_("Update virus database to ensure protection"),
                        install_command="sudo freshclam",
                        info_url=_URLS["clamav_freshclam"],
                    )
                )
            else:
                section.checks.append(
                    AuditCheckResult(
                        name=_("Virus Database"),
                        status=AuditStatus.FAIL,
                        detail=_("Database is {days} days old (built {date})").format(
                            days=days_old, date=date_str
                        ),
                        recommendation=_("Database is critically outdated. Update immediately."),
                        install_command="sudo freshclam",
                        info_url=_URLS["clamav_freshclam"],
                    )
                )
        else:
            section.checks.append(
                AuditCheckResult(
                    name=_("Virus Database"),
                    status=AuditStatus.UNKNOWN,
                    detail=_("Could not determine database age: {error}").format(error=date_str),
                    info_url=_URLS["clamav_freshclam"],
                )
            )
    else:
        db_available, db_error = check_database_available()
        if not db_available:
            section.checks.append(
                AuditCheckResult(
                    name=_("Virus Database"),
                    status=AuditStatus.FAIL,
                    detail=_("No virus database found"),
                    recommendation=_("Download virus database"),
                    install_command="sudo freshclam",
                    info_url=_URLS["clamav_freshclam"],
                )
            )
        else:
            section.checks.append(
                AuditCheckResult(
                    name=_("Virus Database"),
                    status=AuditStatus.UNKNOWN,
                    detail=_("Database files exist but age could not be determined"),
                    info_url=_URLS["clamav_freshclam"],
                )
            )

    # Check 3: clamd daemon
    for service_name in ("clamav-daemon", "clamd@scan", "clamd"):
        is_active, status = _check_systemd_service(service_name)
        if is_active:
            section.checks.append(
                AuditCheckResult(
                    name=_("ClamAV Daemon"),
                    status=AuditStatus.PASS,
                    detail=_("Service {name} is running").format(name=service_name),
                    info_url=_URLS["clamav_clamd"],
                )
            )
            break
    else:
        # Also try direct ping as fallback
        ping_ok, _ping_msg = check_clamd_connection()
        if ping_ok:
            section.checks.append(
                AuditCheckResult(
                    name=_("ClamAV Daemon"),
                    status=AuditStatus.PASS,
                    detail=_("Daemon is responding"),
                    info_url=_URLS["clamav_clamd"],
                )
            )
        else:
            section.checks.append(
                AuditCheckResult(
                    name=_("ClamAV Daemon"),
                    status=AuditStatus.WARNING,
                    detail=_("ClamAV daemon is not running"),
                    recommendation=_("Start the daemon for faster scanning"),
                    install_command="sudo systemctl start clamav-daemon",
                    info_url=_URLS["clamav_clamd"],
                )
            )

    # Check 4: freshclam timer
    for service_name in ("clamav-freshclam", "clamav-freshclam.timer"):
        is_active, status = _check_systemd_service(service_name)
        if is_active:
            section.checks.append(
                AuditCheckResult(
                    name=_("Automatic Updates"),
                    status=AuditStatus.PASS,
                    detail=_("Freshclam service is active"),
                    info_url=_URLS["clamav_freshclam"],
                )
            )
            break
    else:
        section.checks.append(
            AuditCheckResult(
                name=_("Automatic Updates"),
                status=AuditStatus.WARNING,
                detail=_("Freshclam automatic update service is not running"),
                recommendation=_("Enable automatic database updates"),
                install_command="sudo systemctl enable --now clamav-freshclam",
                info_url=_URLS["clamav_freshclam"],
            )
        )

    return section


def check_firewall() -> AuditSectionResult:
    """Check firewall status, auto-detecting ufw/firewalld/nftables."""
    section = AuditSectionResult(
        category=AuditCategory.FIREWALL,
        title=_("Firewall"),
        icon_name="security-medium-symbolic",
    )

    firewall_found = False

    # Try ufw first (Ubuntu/Debian)
    is_active, status = _check_systemd_service("ufw")
    if status != "systemctl not found":
        if is_active:
            # Parse /etc/ufw/ufw.conf for ENABLED state
            ufw_enabled = _check_ufw_enabled()
            if ufw_enabled:
                section.checks.append(
                    AuditCheckResult(
                        name=_("UFW Firewall"),
                        status=AuditStatus.PASS,
                        detail=_("UFW is active and enabled"),
                        info_url=_URLS["ufw"],
                    )
                )
                firewall_found = True
            else:
                section.checks.append(
                    AuditCheckResult(
                        name=_("UFW Firewall"),
                        status=AuditStatus.WARNING,
                        detail=_("UFW service is running but firewall may be disabled"),
                        recommendation=_("Enable the firewall"),
                        install_command="sudo ufw enable",
                        info_url=_URLS["ufw"],
                    )
                )
                firewall_found = True

    # Try firewalld (Fedora/RHEL)
    if not firewall_found:
        rc, stdout, _stderr = _run_command(["firewall-cmd", "--state"])
        if rc == 0 and "running" in stdout:
            section.checks.append(
                AuditCheckResult(
                    name=_("Firewalld"),
                    status=AuditStatus.PASS,
                    detail=_("Firewalld is running"),
                    info_url=_URLS["firewalld"],
                )
            )
            firewall_found = True
        elif rc != -1:  # Command exists but not running
            section.checks.append(
                AuditCheckResult(
                    name=_("Firewalld"),
                    status=AuditStatus.WARNING,
                    detail=_("Firewalld is installed but not running"),
                    recommendation=_("Start the firewall"),
                    install_command="sudo systemctl start firewalld",
                    info_url=_URLS["firewalld"],
                )
            )
            firewall_found = True

    # Try nftables
    if not firewall_found:
        is_active, status = _check_systemd_service("nftables")
        if is_active:
            section.checks.append(
                AuditCheckResult(
                    name=_("nftables"),
                    status=AuditStatus.PASS,
                    detail=_("nftables service is active"),
                    info_url=_URLS["nftables"],
                )
            )
            firewall_found = True

    if not firewall_found:
        section.checks.append(
            AuditCheckResult(
                name=_("Firewall"),
                status=AuditStatus.FAIL,
                detail=_("No active firewall detected"),
                recommendation=_("Install and enable a firewall for network protection"),
                install_command="sudo apt install ufw && sudo ufw enable",
                info_url=_URLS["ufw"],
            )
        )

    # Check open ports
    _check_open_ports(section)

    # Detect firewall GUI tools
    _check_firewall_gui(section)

    return section


# Firewall GUI tools: (binary, display_name, desktop_file_or_command)
_FIREWALL_GUIS = [
    ("gufw", "Gufw", "gufw"),
    ("firewall-config", "Firewall Config", "firewall-config"),
]


def _check_firewall_gui(section: AuditSectionResult) -> None:
    """Detect installed firewall GUI tools and add a launch entry."""
    for binary, display_name, command in _FIREWALL_GUIS:
        if is_binary_installed(binary):
            section.checks.append(
                AuditCheckResult(
                    name=_("Firewall Manager"),
                    status=AuditStatus.PASS,
                    detail=_("{name} is available").format(name=display_name),
                    launch_command=command,
                    launch_label=_("Open {name}").format(name=display_name),
                )
            )
            return

    # No GUI found — informational only, not a warning
    section.checks.append(
        AuditCheckResult(
            name=_("Firewall Manager"),
            status=AuditStatus.UNKNOWN,
            detail=_("No graphical firewall manager detected"),
            recommendation=_("Install a GUI for easier firewall management"),
            install_command="sudo apt install gufw",
            info_url=_URLS["ufw"],
        )
    )


def _check_ufw_status_enabled() -> bool | None:
    """Check UFW state using the ufw CLI, which reflects host firewall state."""
    rc, stdout, _stderr = _run_command(["ufw", "status"])
    if rc != 0 or not stdout:
        return None

    for line in stdout.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("status:"):
            status = stripped.split(":", 1)[1].strip()
            if status.startswith("active"):
                return True
            if status.startswith("inactive"):
                return False

    return None


def _check_ufw_enabled() -> bool:
    """Check if UFW is enabled, preferring host CLI status over config parsing."""
    status_enabled = _check_ufw_status_enabled()
    if status_enabled is not None:
        return status_enabled

    try:
        if is_flatpak():
            rc, stdout, _stderr = _run_command(["cat", "/etc/ufw/ufw.conf"])
            if rc != 0:
                return False
            content = stdout
        else:
            content = Path("/etc/ufw/ufw.conf").read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("ENABLED="):
                return stripped.split("=", 1)[1].strip().lower() == "yes"
    except (OSError, PermissionError):
        pass
    return False


# Ports commonly associated with security risks
_RISKY_PORTS = {
    23: "Telnet",
    3389: "RDP",
    445: "SMB",
    135: "RPC",
    139: "NetBIOS",
    5900: "VNC",
}


def _check_open_ports(section: AuditSectionResult) -> None:
    """Check for open listening ports and flag risky ones."""
    rc, stdout, _stderr = _run_command(["ss", "-tulnH"])
    if rc != 0:
        return

    listening_ports: list[int] = []
    risky_found: list[str] = []

    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        # Local address is field 4 (0-indexed), format: addr:port or [addr]:port
        local_addr = parts[4]
        try:
            port = int(local_addr.rsplit(":", 1)[-1])
            listening_ports.append(port)
            if port in _RISKY_PORTS:
                risky_found.append(f"{port} ({_RISKY_PORTS[port]})")
        except (ValueError, IndexError):
            continue

    port_count = len(set(listening_ports))

    if risky_found:
        section.checks.append(
            AuditCheckResult(
                name=_("Open Ports"),
                status=AuditStatus.FAIL,
                detail=_("{count} ports listening, risky ports: {ports}").format(
                    count=port_count, ports=", ".join(risky_found)
                ),
                recommendation=_("Review if these services need to be exposed"),
                info_url=_URLS["open_ports"],
            )
        )
    elif port_count > 0:
        section.checks.append(
            AuditCheckResult(
                name=_("Open Ports"),
                status=AuditStatus.WARNING,
                detail=_("{count} ports listening").format(count=port_count),
                recommendation=_("Review open ports and close unnecessary services"),
                info_url=_URLS["open_ports"],
            )
        )
    else:
        section.checks.append(
            AuditCheckResult(
                name=_("Open Ports"),
                status=AuditStatus.PASS,
                detail=_("No open ports detected"),
                info_url=_URLS["open_ports"],
            )
        )


def check_mac_framework() -> AuditSectionResult:
    """Check Mandatory Access Control framework (AppArmor or SELinux)."""
    section = AuditSectionResult(
        category=AuditCategory.MAC_FRAMEWORK,
        title=_("Access Control"),
        icon_name="system-lock-screen-symbolic",
    )

    mac_found = False

    # Check AppArmor (Ubuntu/Debian)
    apparmor_status = _check_apparmor()
    if apparmor_status is not None:
        section.checks.append(apparmor_status)
        mac_found = True

    # Check SELinux (Fedora/RHEL)
    selinux_status = _check_selinux()
    if selinux_status is not None:
        section.checks.append(selinux_status)
        mac_found = True

    if not mac_found:
        section.checks.append(
            AuditCheckResult(
                name=_("MAC Framework"),
                status=AuditStatus.UNKNOWN,
                detail=_("No mandatory access control framework detected"),
                recommendation=_("Consider enabling AppArmor or SELinux"),
            )
        )

    return section


def _check_apparmor() -> AuditCheckResult | None:
    """Check AppArmor status via /sys filesystem."""
    apparmor_path = "/sys/module/apparmor/parameters/enabled"
    try:
        if is_flatpak():
            rc, stdout, _stderr = _run_command(["cat", apparmor_path])
            if rc != 0:
                return None
            enabled = stdout.strip()
        else:
            try:
                enabled = Path(apparmor_path).read_text().strip()
            except (FileNotFoundError, PermissionError):
                return None

        if enabled == "Y":
            return AuditCheckResult(
                name=_("AppArmor"),
                status=AuditStatus.PASS,
                detail=_("AppArmor is enabled"),
                info_url=_URLS["apparmor"],
            )
        else:
            return AuditCheckResult(
                name=_("AppArmor"),
                status=AuditStatus.WARNING,
                detail=_("AppArmor module is loaded but not enabled"),
                recommendation=_("Enable AppArmor for application sandboxing"),
                info_url=_URLS["apparmor"],
            )
    except OSError:
        return None


def _check_selinux() -> AuditCheckResult | None:
    """Check SELinux status via getenforce."""
    rc, stdout, _stderr = _run_command(["getenforce"])
    if rc == -1:
        return None

    mode = stdout.strip().lower()
    if mode == "enforcing":
        return AuditCheckResult(
            name=_("SELinux"),
            status=AuditStatus.PASS,
            detail=_("SELinux is enforcing"),
            info_url=_URLS["selinux"],
        )
    elif mode == "permissive":
        return AuditCheckResult(
            name=_("SELinux"),
            status=AuditStatus.WARNING,
            detail=_("SELinux is in permissive mode"),
            recommendation=_("Consider switching to enforcing mode for stronger protection"),
            info_url=_URLS["selinux"],
        )
    elif mode == "disabled":
        return AuditCheckResult(
            name=_("SELinux"),
            status=AuditStatus.FAIL,
            detail=_("SELinux is disabled"),
            recommendation=_("Enable SELinux for mandatory access control"),
            info_url=_URLS["selinux"],
        )
    return None


def check_auto_updates() -> AuditSectionResult:
    """Check if automatic security updates are configured."""
    section = AuditSectionResult(
        category=AuditCategory.AUTO_UPDATES,
        title=_("Automatic Updates"),
        icon_name="software-update-available-symbolic",
    )

    updates_found = False

    # Check Debian/Ubuntu unattended-upgrades
    rc, stdout, _stderr = _run_command(["apt-config", "dump", "APT::Periodic::Unattended-Upgrade"])
    if rc == 0 and stdout:
        # Output like: APT::Periodic::Unattended-Upgrade "1";
        if '"1"' in stdout or '"true"' in stdout.lower():
            section.checks.append(
                AuditCheckResult(
                    name=_("Unattended Upgrades"),
                    status=AuditStatus.PASS,
                    detail=_("Automatic security updates are enabled"),
                    info_url=_URLS["unattended_upgrades"],
                )
            )
            updates_found = True
        elif '"0"' in stdout:
            section.checks.append(
                AuditCheckResult(
                    name=_("Unattended Upgrades"),
                    status=AuditStatus.WARNING,
                    detail=_("Unattended upgrades is installed but disabled"),
                    recommendation=_("Enable automatic security updates"),
                    install_command="sudo dpkg-reconfigure unattended-upgrades",
                    info_url=_URLS["unattended_upgrades"],
                )
            )
            updates_found = True

    # Check Fedora/RHEL dnf-automatic — only if dnf is present (Fedora/RHEL system)
    if not updates_found and is_binary_installed("dnf"):
        is_active, status = _check_systemd_service("dnf-automatic.timer")
        if is_active:
            section.checks.append(
                AuditCheckResult(
                    name=_("DNF Automatic"),
                    status=AuditStatus.PASS,
                    detail=_("DNF automatic updates are enabled"),
                    info_url=_URLS["dnf_automatic"],
                )
            )
            updates_found = True
        elif _is_service_installed("dnf-automatic.timer"):
            # Unit file exists but timer is not running
            section.checks.append(
                AuditCheckResult(
                    name=_("DNF Automatic"),
                    status=AuditStatus.WARNING,
                    detail=_("DNF automatic is installed but timer is not active"),
                    recommendation=_("Enable automatic updates"),
                    install_command="sudo systemctl enable --now dnf-automatic.timer",
                    info_url=_URLS["dnf_automatic"],
                )
            )
            updates_found = True

    if not updates_found:
        # Suggest the right package manager command
        if is_binary_installed("apt"):
            install_cmd = "sudo apt install unattended-upgrades"
        elif is_binary_installed("dnf"):
            install_cmd = "sudo dnf install dnf-automatic"
        else:
            install_cmd = None
        section.checks.append(
            AuditCheckResult(
                name=_("Automatic Updates"),
                status=AuditStatus.UNKNOWN,
                detail=_("Could not determine automatic update status"),
                recommendation=_("Configure automatic security updates"),
                install_command=install_cmd,
            )
        )

    # Check for pending reboot
    _check_pending_reboot(section)

    return section


def _check_pending_reboot(section: AuditSectionResult) -> None:
    """Check if a system reboot is required after updates."""
    reboot_required = False
    if is_flatpak():
        rc, _stdout, _stderr = _run_command(["test", "-f", "/var/run/reboot-required"])
        reboot_required = rc == 0
    else:
        reboot_required = Path("/var/run/reboot-required").exists()

    if reboot_required:
        section.checks.append(
            AuditCheckResult(
                name=_("Pending Reboot"),
                status=AuditStatus.WARNING,
                detail=_("System reboot required to apply updates"),
                recommendation=_("Reboot the system to apply pending security updates"),
            )
        )


def check_intrusion_detection() -> AuditSectionResult:
    """Check intrusion detection/prevention systems (fail2ban, CrowdSec)."""
    section = AuditSectionResult(
        category=AuditCategory.INTRUSION_DETECTION,
        title=_("Intrusion Detection"),
        icon_name="dialog-warning-symbolic",
    )

    ids_found = False

    # Check fail2ban — verify binary exists before claiming "installed"
    is_active, status = _check_systemd_service("fail2ban")
    if is_active:
        section.checks.append(
            AuditCheckResult(
                name=_("fail2ban"),
                status=AuditStatus.PASS,
                detail=_("fail2ban is active and protecting services"),
                info_url=_URLS["fail2ban"],
            )
        )
        ids_found = True
    elif is_binary_installed("fail2ban-client"):
        # Binary exists, so it's truly installed but not running
        section.checks.append(
            AuditCheckResult(
                name=_("fail2ban"),
                status=AuditStatus.WARNING,
                detail=_("fail2ban is installed but not running"),
                recommendation=_("Start fail2ban to protect against brute force attacks"),
                install_command="sudo systemctl start fail2ban",
                info_url=_URLS["fail2ban"],
            )
        )
        ids_found = True

    # Check CrowdSec — verify binary exists before claiming "installed"
    is_active, status = _check_systemd_service("crowdsec")
    if is_active:
        section.checks.append(
            AuditCheckResult(
                name=_("CrowdSec"),
                status=AuditStatus.PASS,
                detail=_("CrowdSec is active with community threat intelligence"),
                info_url=_URLS["crowdsec"],
            )
        )
        ids_found = True
    elif is_binary_installed("cscli"):
        # Binary exists, so it's truly installed but not running
        section.checks.append(
            AuditCheckResult(
                name=_("CrowdSec"),
                status=AuditStatus.WARNING,
                detail=_("CrowdSec is installed but not running"),
                recommendation=_("Start CrowdSec for collaborative intrusion prevention"),
                install_command="sudo systemctl start crowdsec",
                info_url=_URLS["crowdsec"],
            )
        )
        ids_found = True

    if not ids_found:
        if is_binary_installed("apt"):
            install_cmd = "sudo apt install fail2ban"
        elif is_binary_installed("dnf"):
            install_cmd = "sudo dnf install fail2ban"
        else:
            install_cmd = None
        section.checks.append(
            AuditCheckResult(
                name=_("Intrusion Prevention"),
                status=AuditStatus.UNKNOWN,
                detail=_("No intrusion detection system found"),
                recommendation=_("Install fail2ban or CrowdSec to protect against attacks"),
                install_command=install_cmd,
                info_url=_URLS["fail2ban"],
            )
        )

    return section


def check_ssh_hardening() -> AuditSectionResult:
    """Check SSH server hardening configuration."""
    section = AuditSectionResult(
        category=AuditCategory.SSH_HARDENING,
        title=_("SSH Security"),
        icon_name="network-server-symbolic",
    )

    # Check if sshd is running
    sshd_running = False
    for service_name in ("sshd", "ssh"):
        is_active, _status = _check_systemd_service(service_name)
        if is_active:
            sshd_running = True
            break

    if not sshd_running:
        section.checks.append(
            AuditCheckResult(
                name=_("SSH Server"),
                status=AuditStatus.PASS,
                detail=_("SSH server is not running (no remote attack surface)"),
                info_url=_URLS["ssh_hardening"],
            )
        )
        return section

    section.checks.append(
        AuditCheckResult(
            name=_("SSH Server"),
            status=AuditStatus.PASS,
            detail=_("SSH server is running"),
            info_url=_URLS["ssh_hardening"],
        )
    )

    # Parse sshd_config
    config = _parse_sshd_config()
    if config is None:
        section.checks.append(
            AuditCheckResult(
                name=_("SSH Configuration"),
                status=AuditStatus.UNKNOWN,
                detail=_("Could not read SSH configuration"),
                info_url=_URLS["ssh_hardening"],
            )
        )
        return section

    # Check PermitRootLogin
    root_login = config.get("permitrootlogin", "prohibit-password")
    if root_login in ("no", "prohibit-password", "without-password", "forced-commands-only"):
        section.checks.append(
            AuditCheckResult(
                name=_("Root Login"),
                status=AuditStatus.PASS,
                detail=_("Root login: {value}").format(value=root_login),
                info_url=_URLS["ssh_root_login"],
            )
        )
    else:
        section.checks.append(
            AuditCheckResult(
                name=_("Root Login"),
                status=AuditStatus.FAIL,
                detail=_("Root login is allowed ({value})").format(value=root_login),
                recommendation=_("Disable root SSH login for security"),
                info_url=_URLS["ssh_root_login"],
            )
        )

    # Check PasswordAuthentication
    password_auth = config.get("passwordauthentication", "yes")
    if password_auth == "no":  # noqa: S105 - not a password
        section.checks.append(
            AuditCheckResult(
                name=_("Password Auth"),
                status=AuditStatus.PASS,
                detail=_("Password authentication is disabled (key-only)"),
                info_url=_URLS["ssh_root_login"],
            )
        )
    else:
        section.checks.append(
            AuditCheckResult(
                name=_("Password Auth"),
                status=AuditStatus.WARNING,
                detail=_("Password authentication is enabled"),
                recommendation=_("Consider disabling password auth in favor of SSH keys"),
                info_url=_URLS["ssh_root_login"],
            )
        )

    # Check X11Forwarding
    x11 = config.get("x11forwarding", "no")
    if x11 == "no":
        section.checks.append(
            AuditCheckResult(
                name=_("X11 Forwarding"),
                status=AuditStatus.PASS,
                detail=_("X11 forwarding is disabled"),
                info_url=_URLS["ssh_root_login"],
            )
        )
    else:
        section.checks.append(
            AuditCheckResult(
                name=_("X11 Forwarding"),
                status=AuditStatus.WARNING,
                detail=_("X11 forwarding is enabled"),
                recommendation=_("Disable X11 forwarding to reduce attack surface"),
                info_url=_URLS["ssh_root_login"],
            )
        )

    return section


def _parse_sshd_config() -> dict[str, str] | None:
    """Parse /etc/ssh/sshd_config for key settings.

    Returns a dict of lowercase setting name -> value, or None on error.
    """
    config_path = "/etc/ssh/sshd_config"
    try:
        if is_flatpak():
            rc, stdout, _stderr = _run_command(["cat", config_path])
            if rc != 0:
                return None
            content = stdout
        else:
            try:
                content = Path(config_path).read_text()
            except (FileNotFoundError, PermissionError):
                return None
    except OSError:
        return None

    settings: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            settings[parts[0].lower()] = parts[1].strip()

    return settings


# =============================================================================
# Tier 2 Deep Scan Functions
# =============================================================================

_DEEP_SCAN_TIMEOUT = 300  # 5 minutes


def run_lynis_audit() -> AuditSectionResult:
    """Run a Lynis security audit (requires root via pkexec).

    Returns an AuditSectionResult with the hardening index and key findings.
    """
    section = AuditSectionResult(
        category=AuditCategory.DEEP_SCAN_LYNIS,
        title=_("Lynis Security Audit"),
        icon_name="system-run-symbolic",
    )

    # Check if lynis is installed
    rc, stdout, _stderr = _run_command(["which", "lynis"])
    if rc != 0:
        section.checks.append(
            AuditCheckResult(
                name=_("Lynis"),
                status=AuditStatus.UNKNOWN,
                detail=_("Lynis is not installed"),
                recommendation=_("Install Lynis for comprehensive security auditing"),
                install_command="sudo apt install lynis",
                info_url=_URLS["lynis"],
            )
        )
        return section

    # Run lynis audit with pkexec
    try:
        result = subprocess.run(
            wrap_host_command(
                [
                    "pkexec",
                    "lynis",
                    "audit",
                    "system",
                    "--cronjob",
                    "--quiet",
                ]
            ),
            capture_output=True,
            text=True,
            timeout=_DEEP_SCAN_TIMEOUT,
            env=get_clean_env(),
        )
    except subprocess.TimeoutExpired:
        section.checks.append(
            AuditCheckResult(
                name=_("Lynis Audit"),
                status=AuditStatus.FAIL,
                detail=_("Lynis audit timed out after 5 minutes"),
                info_url=_URLS["lynis"],
            )
        )
        return section
    except OSError as e:
        section.checks.append(
            AuditCheckResult(
                name=_("Lynis Audit"),
                status=AuditStatus.UNKNOWN,
                detail=_("Failed to run Lynis: {error}").format(error=str(e)),
                info_url=_URLS["lynis"],
            )
        )
        return section

    # pkexec cancelled by user
    if result.returncode in (126, 127):
        section.checks.append(
            AuditCheckResult(
                name=_("Lynis Audit"),
                status=AuditStatus.SKIPPED,
                detail=_("Authentication was cancelled"),
                info_url=_URLS["lynis"],
            )
        )
        return section

    # Parse lynis-report.dat for hardening index
    hardening_index = _parse_lynis_report()
    if hardening_index is not None:
        if hardening_index >= 70:
            status = AuditStatus.PASS
        elif hardening_index >= 50:
            status = AuditStatus.WARNING
        else:
            status = AuditStatus.FAIL

        section.checks.append(
            AuditCheckResult(
                name=_("Hardening Index"),
                status=status,
                detail=_("Score: {score}/100").format(score=hardening_index),
                recommendation=_("Run 'sudo lynis audit system' for detailed recommendations")
                if status != AuditStatus.PASS
                else None,
                info_url=_URLS["lynis"],
            )
        )
    else:
        section.checks.append(
            AuditCheckResult(
                name=_("Lynis Audit"),
                status=AuditStatus.PASS if result.returncode == 0 else AuditStatus.WARNING,
                detail=_("Audit completed (exit code {code})").format(code=result.returncode),
                info_url=_URLS["lynis"],
            )
        )

    return section


def _parse_lynis_report() -> int | None:
    """Parse hardening_index from /var/log/lynis-report.dat."""
    report_path = "/var/log/lynis-report.dat"
    try:
        if is_flatpak():
            rc, stdout, _stderr = _run_command(["cat", report_path])
            if rc != 0:
                return None
            content = stdout
        else:
            try:
                content = Path(report_path).read_text()
            except (FileNotFoundError, PermissionError):
                return None
    except OSError:
        return None

    for line in content.splitlines():
        if line.startswith("hardening_index="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def run_rootkit_check() -> AuditSectionResult:
    """Run chkrootkit scan (requires root via pkexec).

    Returns an AuditSectionResult with scan results.
    """
    section = AuditSectionResult(
        category=AuditCategory.DEEP_SCAN_ROOTKIT,
        title=_("Rootkit Detection"),
        icon_name="system-run-symbolic",
    )

    # Check if chkrootkit is installed
    rc, _stdout, _stderr = _run_command(["which", "chkrootkit"])
    if rc != 0:
        section.checks.append(
            AuditCheckResult(
                name=_("chkrootkit"),
                status=AuditStatus.UNKNOWN,
                detail=_("chkrootkit is not installed"),
                recommendation=_("Install chkrootkit for rootkit detection"),
                install_command="sudo apt install chkrootkit",
                info_url=_URLS["chkrootkit"],
            )
        )
        return section

    # Run chkrootkit with pkexec in quiet mode
    try:
        result = subprocess.run(
            wrap_host_command(["pkexec", "chkrootkit", "-q"]),
            capture_output=True,
            text=True,
            timeout=_DEEP_SCAN_TIMEOUT,
            env=get_clean_env(),
        )
    except subprocess.TimeoutExpired:
        section.checks.append(
            AuditCheckResult(
                name=_("Rootkit Scan"),
                status=AuditStatus.FAIL,
                detail=_("Rootkit scan timed out after 5 minutes"),
                info_url=_URLS["chkrootkit"],
            )
        )
        return section
    except OSError as e:
        section.checks.append(
            AuditCheckResult(
                name=_("Rootkit Scan"),
                status=AuditStatus.UNKNOWN,
                detail=_("Failed to run chkrootkit: {error}").format(error=str(e)),
                info_url=_URLS["chkrootkit"],
            )
        )
        return section

    # pkexec cancelled by user
    if result.returncode in (126, 127):
        section.checks.append(
            AuditCheckResult(
                name=_("Rootkit Scan"),
                status=AuditStatus.SKIPPED,
                detail=_("Authentication was cancelled"),
                info_url=_URLS["chkrootkit"],
            )
        )
        return section

    # Parse output for INFECTED lines
    output = sanitize_log_line(result.stdout)
    infected_lines = [line.strip() for line in output.splitlines() if "INFECTED" in line]

    if infected_lines:
        section.checks.append(
            AuditCheckResult(
                name=_("Rootkit Scan"),
                status=AuditStatus.FAIL,
                detail=_("{count} potential rootkit(s) detected").format(count=len(infected_lines)),
                recommendation=_("Investigate the detected threats immediately"),
                info_url=_URLS["chkrootkit"],
            )
        )
        # Add individual findings
        for finding in infected_lines[:5]:  # Limit to 5
            section.checks.append(
                AuditCheckResult(
                    name=_("Finding"),
                    status=AuditStatus.FAIL,
                    detail=finding,
                    info_url=_URLS["chkrootkit"],
                )
            )
    else:
        section.checks.append(
            AuditCheckResult(
                name=_("Rootkit Scan"),
                status=AuditStatus.PASS,
                detail=_("No rootkits detected"),
                info_url=_URLS["chkrootkit"],
            )
        )

    return section


# =============================================================================
# Portmaster (optional)
# =============================================================================
#
# Portmaster is an optional Safing.io privacy filter. If it is not installed
# and not running, this check returns a single SKIPPED row — SKIPPED has the
# lowest priority in _STATUS_PRIORITY, so the section contributes zero to the
# FAIL/WARNING counts in the audit summary. The UI renders this section inside
# a collapsed Gtk.Expander when nothing was detected.


def _portmaster_module_status_to_audit(status: str) -> AuditStatus:
    """Map Portmaster module status strings to AuditStatus."""
    normalized = status.lower()
    if normalized in ("online", "ready", "active", "ok"):
        return AuditStatus.PASS
    if normalized in ("error", "failed", "failure"):
        return AuditStatus.FAIL
    if normalized in ("warning", "degraded"):
        return AuditStatus.WARNING
    return AuditStatus.UNKNOWN


def check_portmaster() -> AuditSectionResult:
    """Check Portmaster privacy filter status (optional — silent if not installed)."""
    section = AuditSectionResult(
        category=AuditCategory.PORTMASTER,
        title=_("Portmaster"),
        icon_name="network-vpn-symbolic",
    )

    token = get_portmaster_token()
    result = probe_portmaster(token=token)

    if result.modules_unauthorized:
        # Stale token — drop it so the user gets a fresh prompt next time.
        try:
            delete_portmaster_token()
        except Exception as e:
            logger.debug("Could not delete stale Portmaster token: %s", e)

    if result.status == PortmasterStatus.RUNNING:
        section.checks.append(
            AuditCheckResult(
                name=_("Portmaster"),
                status=AuditStatus.PASS,
                detail=_("Portmaster is running and protecting connections"),
                info_url=_URLS["portmaster"],
            )
        )
        if result.module_rows:
            for module in result.module_rows[:8]:  # cap to avoid runaway lists
                module_status = _portmaster_module_status_to_audit(module.status)
                detail = module.failure_msg or module.status
                section.checks.append(
                    AuditCheckResult(
                        name=module.name,
                        status=module_status,
                        detail=detail,
                        info_url=_URLS["portmaster_api"],
                    )
                )
        elif token is None or result.modules_unauthorized:
            # The launch_command sentinel is intercepted by audit_view's
            # button handler and triggers request_app_token() instead of
            # spawning a subprocess.
            section.checks.append(
                AuditCheckResult(
                    name=_("Module Status"),
                    status=AuditStatus.SKIPPED,
                    detail=_("Authorize ClamUI in Portmaster for per-module health"),
                    launch_command="__portmaster_authorize__",
                    launch_label=_("Authorize"),
                    info_url=_URLS["portmaster_api"],
                )
            )
    elif result.status == PortmasterStatus.INSTALLED_NOT_RUNNING:
        section.checks.append(
            AuditCheckResult(
                name=_("Portmaster"),
                status=AuditStatus.WARNING,
                detail=_("Portmaster is installed but not running"),
                recommendation=_("Start the Portmaster service to enable network protection"),
                install_command="sudo systemctl start portmaster",
                info_url=_URLS["portmaster"],
            )
        )
    elif result.status == PortmasterStatus.NOT_INSTALLED:
        section.checks.append(
            AuditCheckResult(
                name=_("Portmaster"),
                status=AuditStatus.SKIPPED,
                detail=_("Not detected — optional network monitor and application firewall"),
                info_url=_URLS["portmaster_install"],
            )
        )
    else:  # PortmasterStatus.ERROR
        section.checks.append(
            AuditCheckResult(
                name=_("Portmaster"),
                status=AuditStatus.UNKNOWN,
                detail=_("Could not probe Portmaster: {error}").format(error=result.error or ""),
                info_url=_URLS["portmaster_api"],
            )
        )

    return section


# =============================================================================
# Audit Runner
# =============================================================================

# All Tier 1 checks in display order
TIER1_CHECKS = [
    check_clamav_health,
    check_firewall,
    check_mac_framework,
    check_auto_updates,
    check_intrusion_detection,
    check_ssh_hardening,
    check_portmaster,
]
