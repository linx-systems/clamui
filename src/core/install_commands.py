"""Distribution-aware package installation recommendations."""

from __future__ import annotations

import re
import shlex
from enum import Enum
from types import MappingProxyType

from .flatpak import read_host_file


class DistroFamily(Enum):
    """Linux distribution families with verified package mappings."""

    DEBIAN = "debian"
    FEDORA = "fedora"
    ARCH = "arch"


class InstallTarget(Enum):
    """Software that ClamUI may recommend installing."""

    CLAMAV = "clamav"
    FRESHCLAM = "freshclam"
    CLAMD = "clamd"
    FIREWALL = "firewall"
    FIREWALL_GUI = "firewall_gui"
    AUTOMATIC_UPDATES = "automatic_updates"
    INTRUSION_PREVENTION = "intrusion_prevention"
    LYNIS = "lynis"
    CHKROOTKIT = "chkrootkit"


_DISTRO_IDS = MappingProxyType(
    {
        "debian": DistroFamily.DEBIAN,
        "ubuntu": DistroFamily.DEBIAN,
        "linuxmint": DistroFamily.DEBIAN,
        "pop": DistroFamily.DEBIAN,
        "fedora": DistroFamily.FEDORA,
        "arch": DistroFamily.ARCH,
        "manjaro": DistroFamily.ARCH,
    }
)

_COMMANDS = MappingProxyType(
    {
        DistroFamily.DEBIAN: MappingProxyType(
            {
                InstallTarget.CLAMAV: "sudo apt install clamav clamav-daemon",
                InstallTarget.FRESHCLAM: "sudo apt install clamav-freshclam",
                InstallTarget.CLAMD: "sudo apt install clamav-daemon",
                InstallTarget.FIREWALL: "sudo apt install ufw && sudo ufw enable",
                InstallTarget.FIREWALL_GUI: "sudo apt install gufw",
                InstallTarget.AUTOMATIC_UPDATES: "sudo apt install unattended-upgrades",
                InstallTarget.INTRUSION_PREVENTION: "sudo apt install fail2ban",
                InstallTarget.LYNIS: "sudo apt install lynis",
                InstallTarget.CHKROOTKIT: "sudo apt install chkrootkit",
            }
        ),
        DistroFamily.FEDORA: MappingProxyType(
            {
                InstallTarget.CLAMAV: "sudo dnf install clamav clamd",
                InstallTarget.FRESHCLAM: "sudo dnf install clamav-update",
                InstallTarget.CLAMD: "sudo dnf install clamd",
                InstallTarget.FIREWALL: (
                    "sudo dnf install firewalld && sudo systemctl enable --now firewalld"
                ),
                InstallTarget.FIREWALL_GUI: "sudo dnf install firewall-config",
                InstallTarget.AUTOMATIC_UPDATES: "sudo dnf install dnf-automatic",
                InstallTarget.INTRUSION_PREVENTION: "sudo dnf install fail2ban",
                InstallTarget.LYNIS: "sudo dnf install lynis",
                InstallTarget.CHKROOTKIT: "sudo dnf install chkrootkit",
            }
        ),
        DistroFamily.ARCH: MappingProxyType(
            {
                InstallTarget.CLAMAV: "sudo pacman -S clamav",
                InstallTarget.FRESHCLAM: "sudo pacman -S clamav",
                InstallTarget.CLAMD: "sudo pacman -S clamav",
                InstallTarget.FIREWALL: (
                    "sudo pacman -S firewalld && sudo systemctl enable --now firewalld"
                ),
                InstallTarget.FIREWALL_GUI: "sudo pacman -S firewall-config",
                InstallTarget.INTRUSION_PREVENTION: "sudo pacman -S fail2ban",
                InstallTarget.LYNIS: "sudo pacman -S lynis",
            }
        ),
    }
)

_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _parse_value(value: str) -> str | None:
    """Parse one os-release value, rejecting malformed or compound values."""
    try:
        parts = shlex.split(value, comments=True, posix=True)
    except ValueError:
        return None
    if len(parts) != 1:
        return None
    return parts[0].strip().lower() or None


def parse_distro_family(os_release_text: str) -> DistroFamily | None:
    """Resolve a verified distro family from an os-release document.

    Only the exact ``ID`` is authoritative. ``ID_LIKE`` is deliberately not
    used because derivative distributions can share a package manager while
    using different package names.
    """
    distro_id: str | None = None
    for raw_line in os_release_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY_PATTERN.fullmatch(key):
            continue
        if key == "ID":
            distro_id = _parse_value(value.strip())
            if distro_id is None:
                return None

    if distro_id is None:
        return None
    return _DISTRO_IDS.get(distro_id)


def detect_distro_family() -> DistroFamily | None:
    """Detect the host distribution family from ``/etc/os-release``."""
    content, error = read_host_file("/etc/os-release")
    if error is not None or not content:
        return None
    return parse_distro_family(content)


def get_install_command(target: InstallTarget, family: DistroFamily | None) -> str | None:
    """Return the verified install command for a target and distro family."""
    if family is None:
        return None
    return _COMMANDS[family].get(target)


def recommend_install_command(target: InstallTarget) -> str | None:
    """Return the host distribution's verified command for a target."""
    return get_install_command(target, detect_distro_family())
