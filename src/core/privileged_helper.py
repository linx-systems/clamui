"""Install the version-matched host privileged helper for Flatpak ClamUI."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import requests

from .. import __version__
from .clamav_config import privileged_writer_available
from .flatpak import is_flatpak, which_host_command, wrap_host_command
from .i18n import _
from .install_commands import DistroFamily, detect_distro_family

_GITHUB_REPOSITORY = "linx-systems/clamui"
_HELPER_PACKAGE = "clamui-privileged-helper"
_HELPER_ARCHITECTURE = "all"
_API_RESPONSE_LIMIT = 256 * 1024
_HELPER_ASSET_LIMIT = 64 * 1024 * 1024
_REQUEST_TIMEOUT = (5, 30)
_PROCESS_TIMEOUT = 300
_INSTALL_LOCK = threading.Lock()
_TRUSTED_SIGNING_KEY = Path("/app/share/clamui/signing-key.asc")
_TRUSTED_SIGNING_FINGERPRINT = "037273A518BE90BA6EA27B3CDEF2A3E473DE1E26"
_AR_MAGIC = b"!<arch>\n"
_AR_HEADER_SIZE = 60
_SIGNED_TAR_MEMBERS = (
    "control.tar.gz",
    "control.tar.xz",
    "control.tar.zst",
    "data.tar.gz",
    "data.tar.xz",
    "data.tar.zst",
    "data.tar.bz2",
    "data.tar.lzma",
)
_SIGNED_FILE_LINE = re.compile(
    r"^[ \t]+([0-9a-f]{32})[ \t]+([0-9a-f]{40})[ \t]+([0-9]+)[ \t]+(\S+)$"
)

# This program runs only after pkexec has crossed to the host.  It deliberately
# does not import ClamUI: every value that crosses the privilege boundary is
# parsed as data, and the downloaded user-owned file is never passed to apt.
_ELEVATED_INSTALL_BOOTSTRAP = r"""
import hashlib
import os
import secrets
import stat
import subprocess
import sys

SOURCE_PATH, EXPECTED_SIZE, EXPECTED_DIGEST, EXPECTED_VERSION = sys.argv[1:]
EXPECTED_PACKAGE = "clamui-privileged-helper"
EXPECTED_ARCHITECTURE = "all"
MAX_SIZE = 64 * 1024 * 1024

try:
    expected_size = int(EXPECTED_SIZE)
    expected_uid = int(os.environ["PKEXEC_UID"])
except (KeyError, ValueError):
    sys.exit(2)
if (
    os.geteuid() != 0
    or expected_size <= 0
    or expected_size > MAX_SIZE
    or len(EXPECTED_DIGEST) != 64
    or any(character not in "0123456789abcdef" for character in EXPECTED_DIGEST)
):
    sys.exit(2)

source_fd = None
destination_fd = None
destination_path = None
try:
    source_fd = os.open(SOURCE_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    source_stat = os.fstat(source_fd)
    if (
        not stat.S_ISREG(source_stat.st_mode)
        or source_stat.st_uid != expected_uid
        or source_stat.st_mode & 0o022
    ):
        sys.exit(3)

    for _ in range(8):
        candidate = "/var/tmp/clamui-helper-" + secrets.token_hex(16) + ".deb"
        try:
            destination_fd = os.open(
                candidate,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
        except FileExistsError:
            continue
        destination_path = candidate
        break
    if destination_fd is None or destination_path is None:
        sys.exit(4)
    os.fchmod(destination_fd, 0o600)
    destination_stat = os.fstat(destination_fd)
    if not stat.S_ISREG(destination_stat.st_mode) or destination_stat.st_uid != 0:
        sys.exit(4)

    digest = hashlib.sha256()
    copied = 0
    while True:
        chunk = os.read(source_fd, 64 * 1024)
        if not chunk:
            break
        copied += len(chunk)
        if copied > expected_size:
            sys.exit(5)
        digest.update(chunk)
        view = memoryview(chunk)
        while view:
            written = os.write(destination_fd, view)
            view = view[written:]
    if copied != expected_size or digest.hexdigest() != EXPECTED_DIGEST:
        sys.exit(5)
    os.fsync(destination_fd)
    os.close(destination_fd)
    destination_fd = None

    package_fields = subprocess.run(
        [
            "/usr/bin/dpkg-deb",
            "--show",
            "--showformat=${Package}\\n${Version}\\n${Architecture}\\n",
            destination_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if package_fields.returncode != 0 or package_fields.stdout.splitlines() != [
        EXPECTED_PACKAGE,
        EXPECTED_VERSION,
        EXPECTED_ARCHITECTURE,
    ]:
        sys.exit(6)

    installation = subprocess.run(
        ["/usr/bin/apt-get", "install", "-y", destination_path],
        capture_output=True,
        text=True,
        check=False,
    )
    sys.exit(installation.returncode)
finally:
    if destination_fd is not None:
        os.close(destination_fd)
    if source_fd is not None:
        os.close(source_fd)
    if destination_path is not None:
        try:
            os.unlink(destination_path)
        except FileNotFoundError:
            pass
"""


class _HostProcessError(Exception):
    """A required host package-management command could not be run."""


class _HostProcessTimeout(_HostProcessError):
    """A required host package-management command exceeded its deadline."""


class PrivilegedHelperState(str, Enum):  # noqa: UP042 - Ubuntu 22.04 CI uses Python 3.10
    """Availability of the host privileged configuration helper."""

    __str__ = str.__str__
    INSTALLED = "installed"
    INSTALLABLE = "installable"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class PrivilegedHelperStatus:
    """The helper state for the running ClamUI version."""

    state: PrivilegedHelperState
    package_name: str
    version: str
    detail: str | None = None

    @property
    def is_installed(self) -> bool:
        """Whether the trusted helper can currently be used."""
        return self.state is PrivilegedHelperState.INSTALLED

    @property
    def can_install(self) -> bool:
        """Whether this Flatpak host supports automatic installation."""
        return self.state is PrivilegedHelperState.INSTALLABLE


@dataclass(frozen=True)
class PrivilegedHelperInstallResult:
    """The outcome of one helper installation attempt."""

    success: bool
    status: PrivilegedHelperStatus
    message: str


def _package_name() -> str:
    return f"{_HELPER_PACKAGE}_{__version__}_{_HELPER_ARCHITECTURE}.deb"


def _status(state: PrivilegedHelperState, detail: str | None = None) -> PrivilegedHelperStatus:
    return PrivilegedHelperStatus(state, _HELPER_PACKAGE, __version__, detail)


def _matching_host_helper_version() -> bool | None:
    """Return whether the canonical host package exactly matches this Flatpak.

    ``None`` means the host query itself is unavailable or unusable, while
    ``False`` means a usable query found a missing or non-matching package.
    """
    if not _has_canonical_host_command("/usr/bin/dpkg-query"):
        return None
    try:
        result = subprocess.run(
            wrap_host_command(
                [
                    "/usr/bin/dpkg-query",
                    "--show",
                    "--showformat=${db:Status-Abbrev}\\n${Version}\\n${Architecture}\\n",
                    _HELPER_PACKAGE,
                ]
            ),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return False
    return result.stdout.splitlines() == ["ii ", __version__, _HELPER_ARCHITECTURE]


def get_privileged_helper_status() -> PrivilegedHelperStatus:
    """Return the trusted helper's status without attempting installation."""
    helper_available = privileged_writer_available()
    running_flatpak = is_flatpak()
    if helper_available:
        if running_flatpak and detect_distro_family() is DistroFamily.DEBIAN:
            matching_version = _matching_host_helper_version()
            if matching_version is True:
                return _status(PrivilegedHelperState.INSTALLED)
            if matching_version is False:
                return _status(PrivilegedHelperState.INSTALLABLE)
            return _status(
                PrivilegedHelperState.UNSUPPORTED,
                _(
                    "The host helper was found, but its installed package version could not be verified."
                ),
            )
        return _status(PrivilegedHelperState.INSTALLED)
    if not running_flatpak:
        return _status(
            PrivilegedHelperState.NOT_APPLICABLE,
            _("The privileged helper is only installed automatically for Flatpak ClamUI."),
        )
    if detect_distro_family() is not DistroFamily.DEBIAN:
        return _status(
            PrivilegedHelperState.UNSUPPORTED,
            _(
                "Automatic privileged-helper installation is currently supported only on Debian-family hosts."
            ),
        )
    return _status(PrivilegedHelperState.INSTALLABLE)


def _release_tag() -> str:
    return f"v{__version__}"


def _release_api_url() -> str:
    return f"https://api.github.com/repos/{_GITHUB_REPOSITORY}/releases/tags/{_release_tag()}"


def _asset_url() -> str:
    return (
        f"https://github.com/{_GITHUB_REPOSITORY}/releases/download/"
        f"{_release_tag()}/{_package_name()}"
    )


def _result(status: PrivilegedHelperStatus, message: str) -> PrivilegedHelperInstallResult:
    return PrivilegedHelperInstallResult(False, status, message)


def _read_bounded_response(response: Any, limit: int) -> bytes:
    """Read a streamed response without accepting an unbounded body."""
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            raise ValueError("response has an invalid size") from None
        if declared_size < 0 or declared_size > limit:
            raise ValueError("response has an invalid size")

    body = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > limit:
            raise ValueError("response is too large")
    return bytes(body)


def _fetch_release_metadata() -> dict[str, Any]:
    """Fetch and validate the release document for exactly this application tag."""
    response = requests.get(
        _release_api_url(),
        headers={"Accept": "application/vnd.github+json"},
        stream=True,
        timeout=_REQUEST_TIMEOUT,
    )
    try:
        response.raise_for_status()
        raw = _read_bounded_response(response, _API_RESPONSE_LIMIT)
    finally:
        response.close()

    try:
        release = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("release metadata is not valid JSON") from error
    if not isinstance(release, dict):
        raise ValueError("release metadata has an invalid structure")
    if (
        release.get("tag_name") != _release_tag()
        or release.get("draft") is not False
        or release.get("prerelease") is not False
        or not isinstance(release.get("published_at"), str)
        or not release["published_at"]
    ):
        raise ValueError("release metadata does not describe a published exact-version release")
    return release


def _expected_asset(release: dict[str, Any]) -> tuple[int, str]:
    """Return the exact verified asset size and SHA-256 digest."""
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("release metadata has no assets")

    matches = [
        asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("name") == _package_name()
    ]
    if len(matches) != 1:
        raise ValueError("release metadata has no unique matching helper asset")
    asset = matches[0]
    size = asset.get("size")
    digest = asset.get("digest")
    if (
        not isinstance(size, int)
        or size <= 0
        or size > _HELPER_ASSET_LIMIT
        or asset.get("state") != "uploaded"
        or asset.get("content_type") != "application/x-debian-package"
        or asset.get("browser_download_url") != _asset_url()
        or not isinstance(digest, str)
    ):
        raise ValueError("matching helper asset metadata is invalid")

    algorithm, separator, checksum = digest.partition(":")
    if (
        algorithm != "sha256"
        or separator != ":"
        or len(checksum) != 64
        or any(character not in "0123456789abcdef" for character in checksum)
    ):
        raise ValueError("matching helper asset has no valid SHA-256 digest")
    return size, checksum


def _cache_directory() -> Path:
    """Create the host-visible, passwd-derived private helper cache directory."""
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    cache_dir = home / ".cache" / "clamui" / "privileged-helper"
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if cache_dir.is_symlink() or not cache_dir.is_dir():
        raise OSError("helper cache is not a directory")
    os.chmod(cache_dir, 0o700)
    return cache_dir


def _safe_regular_file(path: Path) -> bool:
    """Return whether *path* is a non-symlink regular file."""
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except OSError:
        return False


def _read_debian_ar(path: Path) -> dict[str, bytes] | None:
    """Strictly parse the small, fixed member set of a Debian ``ar`` archive."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            source_stat = os.fstat(fd)
            if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size > _HELPER_ASSET_LIMIT:
                return None
            raw = bytearray()
            while len(raw) <= _HELPER_ASSET_LIMIT:
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    break
                raw.extend(chunk)
            if len(raw) > _HELPER_ASSET_LIMIT or not raw.startswith(_AR_MAGIC):
                return None
        finally:
            os.close(fd)
    except OSError:
        return None

    members: dict[str, bytes] = {}
    offset = len(_AR_MAGIC)
    while offset < len(raw):
        if len(raw) - offset < _AR_HEADER_SIZE:
            return None
        header = raw[offset : offset + _AR_HEADER_SIZE]
        if header[58:60] != b"`\n":
            return None
        try:
            raw_name = header[:16].decode("ascii").rstrip()
            raw_size = header[48:58].decode("ascii").strip()
        except UnicodeDecodeError:
            return None
        name = raw_name[:-1] if raw_name.endswith("/") else raw_name
        if (
            not name
            or "/" in name
            or name.startswith("#1/")
            or not raw_size.isascii()
            or not raw_size.isdigit()
        ):
            return None
        size = int(raw_size)
        content_start = offset + _AR_HEADER_SIZE
        content_end = content_start + size
        if content_end > len(raw) or not name or name in members:
            return None
        members[name] = bytes(raw[content_start:content_end])
        offset = content_end
        if size % 2:
            if offset >= len(raw) or raw[offset : offset + 1] != b"\n":
                return None
            offset += 1
    if offset != len(raw):
        return None
    return members


def _trusted_key_is_safe() -> bool:
    """Accept only the bundled, immutable signing key as a regular safe file."""
    try:
        key_stat = _TRUSTED_SIGNING_KEY.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(key_stat.st_mode)
        and not _TRUSTED_SIGNING_KEY.is_symlink()
        and key_stat.st_uid == 0
        and not key_stat.st_mode & 0o022
    )


def _write_private_file(path: Path, content: bytes) -> bool:
    """Create one non-symlink mode-0600 file, writing all bytes and fsyncing."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(content)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        return False
    return True


def _signed_deb_members_are_exact(signature: str, members: dict[str, bytes]) -> bool:
    """Check dpkg-sig v4 builder fields against every expected archive member."""
    lines = signature.splitlines()
    if lines.count("Version: 4") != 1 or lines.count("Role: builder") != 1:
        return False
    try:
        files_index = lines.index("Files:")
    except ValueError:
        return False

    signed: dict[str, tuple[str, str, int]] = {}
    for line in lines[files_index + 1 :]:
        match = _SIGNED_FILE_LINE.fullmatch(line)
        if match is None:
            return False
        md5, sha1, size, name = match.groups()
        if name in signed:
            return False
        signed[name] = (md5, sha1, int(size))

    control_members = [name for name in members if name.startswith("control.tar.")]
    data_members = [name for name in members if name.startswith("data.tar.")]
    if (
        len(control_members) != 1
        or len(data_members) != 1
        or control_members[0] not in _SIGNED_TAR_MEMBERS
        or data_members[0] not in _SIGNED_TAR_MEMBERS
    ):
        return False
    expected_members = {"debian-binary", control_members[0], data_members[0]}
    if set(signed) != expected_members or set(members) != expected_members | {"_gpgbuilder"}:
        return False
    for name in expected_members:
        content = members[name]
        md5, sha1, size = signed[name]
        if (
            size != len(content)
            or md5 != hashlib.md5(content, usedforsecurity=False).hexdigest()
            or sha1 != hashlib.sha1(content, usedforsecurity=False).hexdigest()
        ):
            return False
    return True


def _verify_deb_signature(path: Path) -> bool:
    """Verify the dpkg-sig v4 builder signature and signed Debian members."""
    if (
        not _safe_regular_file(path)
        or not _trusted_key_is_safe()
        or not Path("/usr/bin/gpg").is_file()
    ):
        return False
    members = _read_debian_ar(path)
    if members is None or "_gpgbuilder" not in members:
        return False

    gpg_home: Path | None = None
    try:
        gpg_home = Path(tempfile.mkdtemp(prefix="clamui-gpg-"))
        os.chmod(gpg_home, 0o700)
        signature_path = gpg_home / "builder.asc"
        if not _write_private_file(signature_path, members["_gpgbuilder"]):
            return False
        imported = subprocess.run(
            [
                "/usr/bin/gpg",
                "--batch",
                "--no-options",
                "--homedir",
                str(gpg_home),
                "--import",
                str(_TRUSTED_SIGNING_KEY),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if imported.returncode != 0:
            return False
        verified = subprocess.run(
            [
                "/usr/bin/gpg",
                "--batch",
                "--no-options",
                "--homedir",
                str(gpg_home),
                "--status-fd=2",
                "--decrypt",
                str(signature_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if verified.returncode != 0:
            return False
        valid_signature = any(
            line.split()[2:3] == [_TRUSTED_SIGNING_FINGERPRINT]
            for line in verified.stderr.splitlines()
            if line.startswith("[GNUPG:] VALIDSIG ")
        )
        return valid_signature and _signed_deb_members_are_exact(verified.stdout, members)
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired):
        return False
    finally:
        if gpg_home is not None:
            shutil.rmtree(gpg_home, ignore_errors=True)


def _download_asset(cache_dir: Path, expected_size: int, expected_digest: str) -> Path:
    """Download the verified asset into the private cache and hash it while streaming."""
    response = requests.get(_asset_url(), stream=True, timeout=_REQUEST_TIMEOUT)
    fd: int | None = None
    filename: str | None = None
    try:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                raise ValueError("helper download has an invalid size") from None
            if declared_size != expected_size:
                raise ValueError("helper download has an unexpected size")

        fd, filename = tempfile.mkstemp(prefix="helper-", suffix=".deb", dir=cache_dir)
        os.fchmod(fd, 0o600)
        digest = hashlib.sha256()
        downloaded = 0
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = None
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > _HELPER_ASSET_LIMIT or downloaded > expected_size:
                    raise ValueError("helper download exceeds its verified size")
                stream.write(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())

        path = Path(filename)
        if (
            downloaded != expected_size
            or digest.hexdigest() != expected_digest
            or not _safe_regular_file(path)
        ):
            raise ValueError("helper download did not pass verification")
        return path
    except Exception:
        if filename:
            Path(filename).unlink(missing_ok=True)
        raise
    finally:
        if fd is not None:
            os.close(fd)
        response.close()


def _has_canonical_host_command(path: str) -> bool:
    """Require the host resolver to return exactly the trusted command path."""
    return which_host_command(Path(path).name) == path


def _verify_deb_identity(path: Path) -> bool:
    """Verify the trusted helper package fields using host dpkg-deb."""
    if not _safe_regular_file(path) or not _has_canonical_host_command("/usr/bin/dpkg-deb"):
        return False
    try:
        result = subprocess.run(
            wrap_host_command(
                [
                    "/usr/bin/dpkg-deb",
                    "--show",
                    "--showformat=${Package}\\n${Version}\\n${Architecture}\\n",
                    str(path),
                ]
            ),
            capture_output=True,
            text=True,
            timeout=_PROCESS_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise _HostProcessTimeout from error
    except OSError as error:
        raise _HostProcessError from error
    if result.returncode != 0:
        return False
    fields = result.stdout.splitlines()
    return fields == [_HELPER_PACKAGE, __version__, _HELPER_ARCHITECTURE]


def _run_install(path: Path, expected_size: int, expected_digest: str) -> tuple[bool, bool]:
    """Ask pkexec to verify and install a root-owned copy of the helper.

    The downloaded source remains untrusted after this process has verified it:
    the elevated bootstrap opens and checks the retained descriptor, copies it
    to a root-owned /var/tmp file, rechecks both digest and Debian fields, and
    only then gives that root-owned filename to apt-get.
    """
    if not _safe_regular_file(path):
        return (False, False)
    if not (
        _has_canonical_host_command("/usr/bin/pkexec")
        and _has_canonical_host_command("/usr/bin/python3")
        and _has_canonical_host_command("/usr/bin/apt-get")
    ):
        return (False, False)
    try:
        result = subprocess.run(
            wrap_host_command(
                [
                    "/usr/bin/pkexec",
                    "/usr/bin/python3",
                    "-I",
                    "-c",
                    _ELEVATED_INSTALL_BOOTSTRAP,
                    str(path),
                    str(expected_size),
                    expected_digest,
                    __version__,
                ]
            ),
            capture_output=True,
            text=True,
            timeout=_PROCESS_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise _HostProcessTimeout from error
    except OSError as error:
        raise _HostProcessError from error
    return (result.returncode == 0, result.returncode in {126, 127})


def _install_matching_privileged_helper() -> PrivilegedHelperInstallResult:
    """Install only the release asset matching this Flatpak's exact version."""
    status = get_privileged_helper_status()
    if status.is_installed:
        return PrivilegedHelperInstallResult(
            True, status, _("The privileged helper is already installed.")
        )
    if not status.can_install:
        return _result(
            status,
            status.detail or _("The privileged helper cannot be installed automatically here."),
        )

    staging_dir: Path | None = None
    try:
        release = _fetch_release_metadata()
        expected_size, expected_digest = _expected_asset(release)
    except requests.Timeout:
        return _result(status, _("Timed out while checking the ClamUI release."))
    except requests.RequestException:
        return _result(
            status,
            _(
                "Could not contact GitHub to check the ClamUI release. Check your connection and try again."
            ),
        )
    except (OSError, ValueError):
        return _result(status, _("The matching ClamUI helper release could not be verified."))

    try:
        try:
            cache_dir = _cache_directory()
            staging_dir = Path(tempfile.mkdtemp(prefix="install-", dir=cache_dir))
            os.chmod(staging_dir, 0o700)
            package_path = _download_asset(staging_dir, expected_size, expected_digest)
        except requests.Timeout:
            return _result(
                status, _("Timed out while downloading the privileged helper. Try again.")
            )
        except requests.RequestException:
            return _result(
                status,
                _("Could not download the privileged helper. Check your connection and try again."),
            )
        except (OSError, ValueError):
            return _result(status, _("The downloaded privileged helper could not be verified."))

        try:
            if not _verify_deb_identity(package_path):
                return _result(
                    status,
                    _("The downloaded privileged helper has an unexpected package identity."),
                )
            if not _verify_deb_signature(package_path):
                return _result(
                    status,
                    _("The downloaded privileged helper does not have a valid ClamUI signature."),
                )
            installed, cancelled = _run_install(package_path, expected_size, expected_digest)
            if cancelled:
                return _result(
                    status,
                    _("Authorization was cancelled. The privileged helper was not installed."),
                )
            if not installed:
                return _result(
                    status,
                    _(
                        "The privileged-helper installation failed. Try again or install it manually."
                    ),
                )
            rechecked = get_privileged_helper_status()
            if not rechecked.is_installed:
                return _result(
                    rechecked,
                    _(
                        "The privileged helper was installed but is still unavailable. Restart ClamUI and try again."
                    ),
                )
            return PrivilegedHelperInstallResult(
                True, rechecked, _("The privileged helper was installed successfully.")
            )
        except _HostProcessTimeout:
            return _result(
                status,
                _("Timed out while verifying or installing the privileged helper. Try again."),
            )
        except _HostProcessError:
            return _result(
                status,
                _("Could not run the host package-management tools. Install the helper manually."),
            )
    finally:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)


def install_matching_privileged_helper() -> PrivilegedHelperInstallResult:
    """Install the matching helper once, rejecting concurrent requests."""
    if not _INSTALL_LOCK.acquire(blocking=False):
        status = get_privileged_helper_status()
        return _result(status, _("Privileged-helper installation is already in progress."))
    try:
        return _install_matching_privileged_helper()
    finally:
        _INSTALL_LOCK.release()
