# ClamUI Distro Install Command Tests
"""Unit tests for the install_commands module (issue #184).

ClamUI hardcoded ``sudo apt install ...`` in its recommendations, or picked a
package manager by probing for an ``apt`` / ``dnf`` binary. Both are wrong: a
probe cannot distinguish Arch at all, and under Flatpak the sandbox has no host
binaries to probe. These tests pin the replacement contract: resolve the distro
*identity* from the host ``/etc/os-release`` and map that identity onto a
per-family command table.

The module under test is imported inside each test so collection still succeeds
before ``src/core/install_commands.py`` exists; a missing module then surfaces
as a failing test that names the behaviour which is absent, not as a collection
error that hides the whole file.
"""

import contextlib
import re
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Contract tables
# ---------------------------------------------------------------------------

EXPECTED_FAMILIES = ("DEBIAN", "FEDORA", "ARCH")

EXPECTED_TARGETS = (
    "CLAMAV",
    "FRESHCLAM",
    "CLAMD",
    "FIREWALL",
    "FIREWALL_GUI",
    "AUTOMATIC_UPDATES",
    "INTRUSION_PREVENTION",
    "LYNIS",
    "CHKROOTKIT",
)

# (target, family, expected command or None)
COMMAND_MATRIX: list[tuple[str, str, str | None]] = [
    # -- Debian family -----------------------------------------------------
    ("CLAMAV", "DEBIAN", "sudo apt install clamav clamav-daemon"),
    ("FRESHCLAM", "DEBIAN", "sudo apt install clamav-freshclam"),
    ("CLAMD", "DEBIAN", "sudo apt install clamav-daemon"),
    ("FIREWALL", "DEBIAN", "sudo apt install ufw && sudo ufw enable"),
    ("FIREWALL_GUI", "DEBIAN", "sudo apt install gufw"),
    ("AUTOMATIC_UPDATES", "DEBIAN", "sudo apt install unattended-upgrades"),
    ("INTRUSION_PREVENTION", "DEBIAN", "sudo apt install fail2ban"),
    ("LYNIS", "DEBIAN", "sudo apt install lynis"),
    ("CHKROOTKIT", "DEBIAN", "sudo apt install chkrootkit"),
    # -- Fedora family -----------------------------------------------------
    ("CLAMAV", "FEDORA", "sudo dnf install clamav clamd"),
    ("FRESHCLAM", "FEDORA", "sudo dnf install clamav-update"),
    ("CLAMD", "FEDORA", "sudo dnf install clamd"),
    ("FIREWALL", "FEDORA", "sudo dnf install firewalld && sudo systemctl enable --now firewalld"),
    ("FIREWALL_GUI", "FEDORA", "sudo dnf install firewall-config"),
    ("AUTOMATIC_UPDATES", "FEDORA", "sudo dnf install dnf-automatic"),
    ("INTRUSION_PREVENTION", "FEDORA", "sudo dnf install fail2ban"),
    ("LYNIS", "FEDORA", "sudo dnf install lynis"),
    ("CHKROOTKIT", "FEDORA", "sudo dnf install chkrootkit"),
    # -- Arch family -------------------------------------------------------
    ("CLAMAV", "ARCH", "sudo pacman -S clamav"),
    ("FRESHCLAM", "ARCH", "sudo pacman -S clamav"),
    ("CLAMD", "ARCH", "sudo pacman -S clamav"),
    ("FIREWALL", "ARCH", "sudo pacman -S firewalld && sudo systemctl enable --now firewalld"),
    ("FIREWALL_GUI", "ARCH", "sudo pacman -S firewall-config"),
    # Arch ships no unattended-upgrades equivalent and no chkrootkit in the
    # official repos: no command is better than a command that cannot work.
    ("AUTOMATIC_UPDATES", "ARCH", None),
    ("INTRUSION_PREVENTION", "ARCH", "sudo pacman -S fail2ban"),
    ("LYNIS", "ARCH", "sudo pacman -S lynis"),
    ("CHKROOTKIT", "ARCH", None),
]

# Every family owns exactly one package manager; any other manager appearing in
# one of its commands is the issue #184 bug.
FAMILY_PREFIX = {
    "DEBIAN": "sudo apt install ",
    "FEDORA": "sudo dnf install ",
    "ARCH": "sudo pacman -S ",
}

FOREIGN_MANAGERS = {
    "DEBIAN": ("dnf", "pacman"),
    "FEDORA": ("apt", "pacman"),
    "ARCH": ("apt", "dnf"),
}

# ---------------------------------------------------------------------------
# os-release fixtures (verbatim shapes seen on real systems)
# ---------------------------------------------------------------------------

UBUNTU_OS_RELEASE = """\
PRETTY_NAME="Ubuntu 24.04.1 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.1 LTS (Noble Numbat)"
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
"""

FEDORA_OS_RELEASE = """\
NAME="Fedora Linux"
VERSION="41 (Workstation Edition)"
ID=fedora
VERSION_ID=41
PLATFORM_ID="platform:f41"
PRETTY_NAME="Fedora Linux 41 (Workstation Edition)"
"""

ARCH_OS_RELEASE = """\
NAME="Arch Linux"
PRETTY_NAME="Arch Linux"
ID=arch
BUILD_ID=rolling
HOME_URL="https://archlinux.org/"
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _module():
    """Import the module under test lazily (see the module docstring)."""
    from src.core import install_commands

    return install_commands


def _family(name):
    """Resolve a family name to its enum member, or None for 'no family'."""
    return None if name is None else _module().DistroFamily[name]


def _target(name):
    """Resolve a target name to its enum member."""
    return _module().InstallTarget[name]


@contextlib.contextmanager
def _host_os_release(content, error=None):
    """Patch the host ``/etc/os-release`` read behind detect_distro_family().

    Both the source function and any name the module imported from it are
    patched, so the test does not care whether the implementation calls
    ``flatpak.read_host_file(...)`` or a module-level imported alias.
    """
    module = _module()
    targets = [mock.patch("src.core.flatpak.read_host_file", return_value=(content, error))]
    if hasattr(module, "read_host_file"):
        targets.append(mock.patch.object(module, "read_host_file", return_value=(content, error)))

    with contextlib.ExitStack() as stack:
        yield [stack.enter_context(patch) for patch in targets]


def _assert_read_os_release(mocks):
    """Assert the host file reader was asked for /etc/os-release."""
    calls = [call for reader in mocks for call in reader.call_args_list]
    assert calls, "distro detection must read the host /etc/os-release"
    paths = [call.args[0] if call.args else call.kwargs.get("file_path") for call in calls]
    assert "/etc/os-release" in paths, f"expected /etc/os-release read, got {paths}"


# ---------------------------------------------------------------------------
# parse_distro_family()
# ---------------------------------------------------------------------------


class TestParseDistroFamilyExactIds:
    """Exact ``ID=`` values map straight onto a family."""

    @pytest.mark.parametrize(
        ("distro_id", "expected_family"),
        [
            ("debian", "DEBIAN"),
            ("ubuntu", "DEBIAN"),
            ("linuxmint", "DEBIAN"),
            ("pop", "DEBIAN"),
            ("fedora", "FEDORA"),
            ("arch", "ARCH"),
            ("manjaro", "ARCH"),
        ],
    )
    def test_supported_exact_id(self, distro_id, expected_family):
        """Each supported ID resolves to its family."""
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family(f"ID={distro_id}\n") is _family(expected_family)

    @pytest.mark.parametrize(
        ("os_release", "expected_family"),
        [
            (UBUNTU_OS_RELEASE, "DEBIAN"),
            (FEDORA_OS_RELEASE, "FEDORA"),
            (ARCH_OS_RELEASE, "ARCH"),
        ],
    )
    def test_full_real_world_file(self, os_release, expected_family):
        """Complete os-release files parse without help from other keys."""
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family(os_release) is _family(expected_family)

    @pytest.mark.parametrize(
        "line",
        [
            'ID="fedora"',
            "ID='fedora'",
            "ID=fedora   ",
            "   ID=fedora",
            '\tID="fedora"\t',
        ],
    )
    def test_quotes_and_surrounding_whitespace_are_stripped(self, line):
        """Quoting and padding are formatting, not identity."""
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family(f"NAME=Whatever\n{line}\n") is _family("FEDORA")

    def test_comments_and_blank_lines_are_ignored(self):
        """os-release permits comments and empty lines."""
        parse_distro_family = _module().parse_distro_family
        text = "# vendor comment\n\n   \n# ID=debian (commented out)\nID=arch\n\n"

        assert parse_distro_family(text) is _family("ARCH")


class TestParseDistroFamilyIgnoresIdLike:
    """``ID_LIKE`` never grants a family to an unrecognised distro.

    Sharing a package manager does not mean sharing package names: a
    Debian-like distro may have no ``gufw``, an Arch-like one no
    ``firewall-config``. Inheriting a command through ``ID_LIKE`` would hand
    the user a confidently wrong package to install, which is worse than
    saying nothing. Only IDs verified one by one are supported.
    """

    @pytest.mark.parametrize(
        "id_like_line",
        [
            "ID_LIKE=debian",
            'ID_LIKE="debian"',
            "ID_LIKE='debian'",
            'ID_LIKE="ubuntu debian"',
            'ID_LIKE="  ubuntu   debian  "',
            "ID_LIKE=fedora",
            'ID_LIKE="rhel centos fedora"',
            "ID_LIKE=arch",
            "ID_LIKE='arch'",
            'ID_LIKE="archlinux arch"',
        ],
    )
    def test_unknown_id_is_not_rescued_by_id_like(self, id_like_line):
        """An unrecognised ID stays unrecognised, whatever it claims kinship to."""
        parse_distro_family = _module().parse_distro_family
        text = f"ID=someunknownderivative\n{id_like_line}\n"

        assert parse_distro_family(text) is None

    @pytest.mark.parametrize(
        ("label", "text"),
        [
            ("nobara", "ID=nobara\nID_LIKE=fedora\n"),
            ("kali", 'ID=kali\nID_LIKE="debian"\n'),
            ("endeavouros", 'ID=endeavouros\nID_LIKE="arch"\n'),
            ("elementary", "ID=elementary\nID_LIKE=ubuntu\n"),
        ],
    )
    def test_real_derivatives_are_unsupported(self, label, text):
        """Real derivatives need an explicit entry before they get commands."""
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family(text) is None, f"{label} must not inherit via ID_LIKE"

    def test_id_like_alone_is_never_an_identity(self):
        """ID_LIKE without any ID is not an identity either."""
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family('ID_LIKE="debian"\nNAME="Some Distro"\n') is None


class TestParseDistroFamilyPrecedence:
    """A supported ``ID`` decides the family; ``ID_LIKE`` cannot override it."""

    @pytest.mark.parametrize(
        ("text", "expected_family"),
        [
            ("ID=fedora\nID_LIKE=debian\n", "FEDORA"),
            ("ID=ubuntu\nID_LIKE=fedora\n", "DEBIAN"),
            ('ID=manjaro\nID_LIKE="debian fedora"\n', "ARCH"),
            ("ID=debian\nID_LIKE=arch\n", "DEBIAN"),
        ],
    )
    def test_exact_id_beats_id_like(self, text, expected_family):
        """Identity comes from ID alone; a kinship claim cannot redirect it."""
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family(text) is _family(expected_family)

    def test_id_line_order_does_not_matter(self):
        """ID_LIKE appearing before ID must not shadow the exact ID."""
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family("ID_LIKE=debian\nID=fedora\n") is _family("FEDORA")


class TestParseDistroFamilyUnknown:
    """Anything unrecognised fails safe to None rather than guessing apt."""

    @pytest.mark.parametrize(
        ("label", "text"),
        [
            ("empty", ""),
            ("whitespace only", "   \n\n\t\n"),
            ("comments only", "# nothing here\n# ID=debian\n"),
            ("no key/value pairs", "just some text\nnot an os release file\n"),
            ("empty ID value", "ID=\nNAME=Mystery\n"),
            ("empty quoted ID value", 'ID=""\nID_LIKE=""\n'),
            ("missing ID key", 'NAME="Debian GNU/Linux"\nPRETTY_NAME="Debian GNU/Linux 12"\n'),
            ("unsupported distro", "ID=gentoo\n"),
            ("unsupported family", 'ID=opensuse-tumbleweed\nID_LIKE="suse opensuse"\n'),
            ("ID substring only", "ID=notdebian\n"),
            ("lookalike keys", 'XID=fedora\nMY_ID_LIKE="debian"\nPLATFORM_ID="platform:f41"\n'),
        ],
    )
    def test_returns_none(self, label, text):
        """Unknown input yields no family, so callers can stay generic."""
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family(text) is None, f"expected None for {label}"

    @pytest.mark.parametrize(
        ("label", "text"),
        [
            ("unterminated double quote", 'ID="fedora\n'),
            ("unterminated single quote", "ID='arch\n"),
            ("mismatched quotes", "ID=\"debian'\n"),
            ("stray trailing quote", 'ID=ubuntu"\n'),
            ("bare quote as value", 'ID="\n'),
        ],
    )
    def test_malformed_quoting_returns_none(self, label, text):
        """A corrupt identity line is not an identity.

        Naively stripping quote characters would turn ``ID="fedora`` into a
        confident 'run dnf' recommendation from a file we could not parse.
        Quotes must be balanced or the value is discarded.
        """
        parse_distro_family = _module().parse_distro_family

        assert parse_distro_family(text) is None, f"expected None for {label}"

    def test_pretty_name_is_never_used_as_identity(self):
        """Marketing strings must not drive package manager selection."""
        parse_distro_family = _module().parse_distro_family
        text = 'ID=arch\nPRETTY_NAME="Arch Linux (debian and fedora compatible)"\n'

        assert parse_distro_family(text) is _family("ARCH")


# ---------------------------------------------------------------------------
# get_install_command()
# ---------------------------------------------------------------------------


class TestInstallCommandMatrix:
    """The full (target, family) -> command contract."""

    def test_enums_expose_exactly_the_contracted_members(self):
        """New families/targets must be added to this table deliberately."""
        module = _module()

        assert {member.name for member in module.DistroFamily} == set(EXPECTED_FAMILIES)
        assert {member.name for member in module.InstallTarget} == set(EXPECTED_TARGETS)

    def test_matrix_covers_every_combination(self):
        """Guard the table itself against silent gaps."""
        covered = {(target, family) for target, family, _ in COMMAND_MATRIX}

        assert covered == {(t, f) for t in EXPECTED_TARGETS for f in EXPECTED_FAMILIES}

    @pytest.mark.parametrize(("target", "family", "expected"), COMMAND_MATRIX)
    def test_command_for_target_and_family(self, target, family, expected):
        """Each cell of the matrix returns exactly the contracted command."""
        get_install_command = _module().get_install_command

        assert get_install_command(_target(target), _family(family)) == expected

    @pytest.mark.parametrize(("target", "family", "expected"), COMMAND_MATRIX)
    def test_command_uses_only_that_family_package_manager(self, target, family, expected):
        """Regression for #184: no family may be handed a foreign manager."""
        if expected is None:
            pytest.skip(f"{target} has no packaged equivalent on {family}")

        command = _module().get_install_command(_target(target), _family(family))

        assert command.startswith(FAMILY_PREFIX[family])
        for manager in FOREIGN_MANAGERS[family]:
            assert not re.search(rf"\b{manager}\b", command), (
                f"{family}/{target} suggests '{manager}': {command}"
            )

    @pytest.mark.parametrize("target", EXPECTED_TARGETS)
    def test_unknown_family_yields_no_command(self, target):
        """Without an identified distro there is no safe command to print."""
        get_install_command = _module().get_install_command

        assert get_install_command(_target(target), None) is None


# ---------------------------------------------------------------------------
# detect_distro_family()
# ---------------------------------------------------------------------------


class TestDetectDistroFamily:
    """Detection reads the host os-release through the Flatpak-aware helper."""

    @pytest.mark.parametrize(
        ("os_release", "expected_family"),
        [
            (UBUNTU_OS_RELEASE, "DEBIAN"),
            (FEDORA_OS_RELEASE, "FEDORA"),
            (ARCH_OS_RELEASE, "ARCH"),
        ],
    )
    def test_detects_family_from_host_file(self, os_release, expected_family):
        """The host file, not the sandbox filesystem, decides the family."""
        detect_distro_family = _module().detect_distro_family

        with _host_os_release(os_release) as readers:
            result = detect_distro_family()

        assert result is _family(expected_family)
        _assert_read_os_release(readers)

    @pytest.mark.parametrize(
        ("content", "error"),
        [
            (None, "Permission denied: Cannot read /etc/os-release"),
            (None, "File not found: /etc/os-release"),
            (None, "flatpak-spawn not available"),
            (None, None),
            ("", None),
            ("ID=gentoo\n", None),
        ],
    )
    def test_unreadable_or_unknown_host_file_returns_none(self, content, error):
        """A failed read degrades to 'unknown distro', never to a default."""
        detect_distro_family = _module().detect_distro_family

        with _host_os_release(content, error):
            assert detect_distro_family() is None

    def test_detection_never_probes_for_package_manager_binaries(self):
        """Issue #184: identity is read, not guessed from installed binaries."""
        detect_distro_family = _module().detect_distro_family

        with (
            _host_os_release(FEDORA_OS_RELEASE),
            mock.patch("shutil.which") as mock_which,
            mock.patch("subprocess.run") as mock_run,
        ):
            result = detect_distro_family()

        assert result is _family("FEDORA")
        mock_which.assert_not_called()
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# recommend_install_command()
# ---------------------------------------------------------------------------


class TestRecommendInstallCommand:
    """The one call sites use: detect, then map."""

    @pytest.mark.parametrize(
        ("os_release", "target", "expected"),
        [
            (UBUNTU_OS_RELEASE, "CLAMAV", "sudo apt install clamav clamav-daemon"),
            (FEDORA_OS_RELEASE, "CLAMAV", "sudo dnf install clamav clamd"),
            (ARCH_OS_RELEASE, "CLAMAV", "sudo pacman -S clamav"),
            (FEDORA_OS_RELEASE, "LYNIS", "sudo dnf install lynis"),
            (ARCH_OS_RELEASE, "LYNIS", "sudo pacman -S lynis"),
            (ARCH_OS_RELEASE, "CHKROOTKIT", None),
            (ARCH_OS_RELEASE, "AUTOMATIC_UPDATES", None),
        ],
    )
    def test_end_to_end_from_host_file(self, os_release, target, expected):
        """Host identity flows through to the recommended command."""
        recommend_install_command = _module().recommend_install_command

        with _host_os_release(os_release):
            assert recommend_install_command(_target(target)) == expected

    @pytest.mark.parametrize("target", EXPECTED_TARGETS)
    def test_undetectable_distro_yields_no_command(self, target):
        """Unknown host => None, so the UI can stay distro-neutral."""
        module = _module()

        with mock.patch.object(module, "detect_distro_family", return_value=None):
            assert module.recommend_install_command(_target(target)) is None

    @pytest.mark.parametrize(("target", "family", "expected"), COMMAND_MATRIX)
    def test_delegates_to_the_detected_family(self, target, family, expected):
        """recommend_* is get_install_command(detect_distro_family())."""
        module = _module()

        with mock.patch.object(
            module, "detect_distro_family", return_value=_family(family)
        ) as mock_detect:
            result = module.recommend_install_command(_target(target))

        assert result == expected
        mock_detect.assert_called_once_with()

    def test_recommendation_never_probes_for_package_manager_binaries(self):
        """Issue #184: an Arch host must never be told to run apt."""
        module = _module()

        with (
            _host_os_release(ARCH_OS_RELEASE),
            mock.patch("shutil.which") as mock_which,
            mock.patch("subprocess.run") as mock_run,
        ):
            command = module.recommend_install_command(_target("CLAMAV"))

        assert command == "sudo pacman -S clamav"
        assert "apt" not in command
        mock_which.assert_not_called()
        mock_run.assert_not_called()
