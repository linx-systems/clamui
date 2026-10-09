"""Behavioral tests for the version-matched Flatpak privileged-helper installer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import privileged_helper
from src.core.install_commands import DistroFamily


class _Response:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self.body = body
        self.headers = headers or {"Content-Length": str(len(body))}
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size: int):
        return iter(
            self.body[index : index + chunk_size] for index in range(0, len(self.body), chunk_size)
        )

    def close(self):
        self.closed = True


def _asset(*, size: int = 3, digest: str | None = None, **overrides):
    values = {
        "name": privileged_helper._package_name(),
        "size": size,
        "digest": digest or f"sha256:{'a' * 64}",
        "content_type": "application/x-debian-package",
        "state": "uploaded",
        "browser_download_url": privileged_helper._asset_url(),
    }
    values.update(overrides)
    return values


def _release(asset: dict | None = None):
    return {
        "tag_name": privileged_helper._release_tag(),
        "draft": False,
        "prerelease": False,
        "published_at": "2026-09-10T12:00:00Z",
        "assets": [asset or _asset()],
    }


def _installable_status():
    return privileged_helper.PrivilegedHelperStatus(
        privileged_helper.PrivilegedHelperState.INSTALLABLE,
        privileged_helper._HELPER_PACKAGE,
        privileged_helper.__version__,
    )


def test_installed_status_is_authoritative_before_platform_applicability(monkeypatch):
    monkeypatch.setattr(privileged_helper, "privileged_writer_available", lambda: True)
    monkeypatch.setattr(privileged_helper, "is_flatpak", lambda: False)

    status = privileged_helper.get_privileged_helper_status()

    assert status.state is privileged_helper.PrivilegedHelperState.INSTALLED
    assert status.is_installed is True
    assert status.can_install is False


@pytest.mark.parametrize(
    ("flatpak", "family", "expected"),
    [
        (True, DistroFamily.DEBIAN, privileged_helper.PrivilegedHelperState.INSTALLABLE),
        (True, DistroFamily.FEDORA, privileged_helper.PrivilegedHelperState.UNSUPPORTED),
        (False, DistroFamily.DEBIAN, privileged_helper.PrivilegedHelperState.NOT_APPLICABLE),
    ],
)
def test_status_only_auto_installs_on_debian_flatpak(monkeypatch, flatpak, family, expected):
    monkeypatch.setattr(privileged_helper, "privileged_writer_available", lambda: False)
    monkeypatch.setattr(privileged_helper, "is_flatpak", lambda: flatpak)
    monkeypatch.setattr(privileged_helper, "detect_distro_family", lambda: family)

    status = privileged_helper.get_privileged_helper_status()

    assert status.state is expected
    assert status.can_install is (expected is privileged_helper.PrivilegedHelperState.INSTALLABLE)


def test_release_metadata_uses_exact_tag_url_and_validates_exact_asset(monkeypatch):
    response = _Response(json.dumps(_release()).encode())
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(privileged_helper.requests, "get", get)

    release = privileged_helper._fetch_release_metadata()
    size, digest = privileged_helper._expected_asset(release)

    assert calls == [
        (
            f"https://api.github.com/repos/linx-systems/clamui/releases/tags/v{privileged_helper.__version__}",
            {
                "headers": {"Accept": "application/vnd.github+json"},
                "stream": True,
                "timeout": privileged_helper._REQUEST_TIMEOUT,
            },
        )
    ]
    assert response.closed is True
    assert (size, digest) == (3, "a" * 64)


@pytest.mark.parametrize(
    "asset",
    [
        _asset(browser_download_url="https://example.invalid/helper.deb"),
        _asset(digest="sha256:not-a-digest"),
        _asset(content_type="application/octet-stream"),
        _asset(size=0),
        _asset(size=privileged_helper._HELPER_ASSET_LIMIT + 1),
        {**_asset(), "digest": None},
    ],
)
def test_release_asset_rejects_non_exact_metadata(asset):
    with pytest.raises(ValueError):
        privileged_helper._expected_asset(_release(asset))


def test_download_rejects_size_overrun_and_removes_partial_file(monkeypatch, tmp_path):
    body = b"larger-than-the-declared-asset"
    response = _Response(body, {"Content-Length": str(len(body))})
    monkeypatch.setattr(privileged_helper.requests, "get", lambda *_args, **_kwargs: response)

    with pytest.raises(ValueError):
        privileged_helper._download_asset(tmp_path, 3, hashlib.sha256(b"abc").hexdigest())

    assert list(tmp_path.iterdir()) == []
    assert response.closed is True


def test_download_verifies_digest_and_keeps_only_regular_file(monkeypatch, tmp_path):
    body = b"verified-deb"
    response = _Response(body)
    monkeypatch.setattr(privileged_helper.requests, "get", lambda *_args, **_kwargs: response)

    package = privileged_helper._download_asset(
        tmp_path, len(body), hashlib.sha256(body).hexdigest()
    )

    assert package.read_bytes() == body
    assert package.is_symlink() is False
    assert privileged_helper._safe_regular_file(package) is True


def test_deb_identity_rejects_wrong_package_metadata(monkeypatch, tmp_path):
    package = tmp_path / "helper.deb"
    package.write_bytes(b"not parsed by the mocked dpkg-deb")
    monkeypatch.setattr(privileged_helper, "_has_canonical_host_command", lambda _path: True)
    monkeypatch.setattr(
        privileged_helper.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"wrong-package\n{privileged_helper.__version__}\nall\n",
        ),
    )

    assert privileged_helper._verify_deb_identity(package) is False


def test_deb_identity_uses_machine_readable_host_query(monkeypatch, tmp_path):
    package = tmp_path / "helper.deb"
    package.write_bytes(b"not parsed by the mocked dpkg-deb")
    calls = []
    monkeypatch.setattr(privileged_helper, "_has_canonical_host_command", lambda _path: True)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                f"{privileged_helper._HELPER_PACKAGE}\n"
                f"{privileged_helper.__version__}\n"
                f"{privileged_helper._HELPER_ARCHITECTURE}\n"
            ),
        )

    monkeypatch.setattr(privileged_helper.subprocess, "run", run)

    assert privileged_helper._verify_deb_identity(package) is True
    assert calls[0][0][-5:] == [
        "/usr/bin/dpkg-deb",
        "--show",
        "--showformat=${Package}\\n${Version}\\n${Architecture}\\n",
        str(package),
    ]


def test_install_does_not_run_pkexec_before_deb_verification(monkeypatch, tmp_path):
    status = _installable_status()
    package = tmp_path / "helper.deb"
    package.write_bytes(b"downloaded")
    install_calls = []
    monkeypatch.setattr(privileged_helper, "get_privileged_helper_status", lambda: status)
    monkeypatch.setattr(privileged_helper, "_fetch_release_metadata", lambda: _release())
    monkeypatch.setattr(privileged_helper, "_expected_asset", lambda _release: (10, "a" * 64))
    monkeypatch.setattr(privileged_helper, "_cache_directory", lambda: tmp_path)
    monkeypatch.setattr(privileged_helper, "_download_asset", lambda *_args: package)
    monkeypatch.setattr(privileged_helper, "_verify_deb_identity", lambda _path: False)
    monkeypatch.setattr(
        privileged_helper, "_run_install", lambda *_args: install_calls.append(_args)
    )

    result = privileged_helper.install_matching_privileged_helper()

    assert result.success is False
    assert install_calls == []


def test_download_failure_cleans_staging(monkeypatch, tmp_path):
    status = _installable_status()

    def fail_download(*_args):
        raise ValueError("digest mismatch")

    monkeypatch.setattr(privileged_helper, "get_privileged_helper_status", lambda: status)
    monkeypatch.setattr(privileged_helper, "_fetch_release_metadata", lambda: _release())
    monkeypatch.setattr(privileged_helper, "_expected_asset", lambda _release: (10, "a" * 64))
    monkeypatch.setattr(privileged_helper, "_cache_directory", lambda: tmp_path)
    monkeypatch.setattr(privileged_helper, "_download_asset", fail_download)

    result = privileged_helper.install_matching_privileged_helper()

    assert result.success is False
    assert list(tmp_path.iterdir()) == []


def test_install_maps_authorization_cancel_and_cleans_staging(monkeypatch, tmp_path):
    status = _installable_status()
    install_calls = []

    def download(staging, *_args):
        package = staging / "helper.deb"
        package.write_bytes(b"downloaded")
        return package

    def run_install(path, size, digest):
        install_calls.append((path, size, digest))
        return (False, True)

    monkeypatch.setattr(privileged_helper, "get_privileged_helper_status", lambda: status)
    monkeypatch.setattr(privileged_helper, "_fetch_release_metadata", lambda: _release())
    monkeypatch.setattr(privileged_helper, "_expected_asset", lambda _release: (10, "a" * 64))
    monkeypatch.setattr(privileged_helper, "_cache_directory", lambda: tmp_path)
    monkeypatch.setattr(privileged_helper, "_download_asset", download)
    monkeypatch.setattr(privileged_helper, "_verify_deb_identity", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "_verify_deb_signature", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "_run_install", run_install)

    result = privileged_helper.install_matching_privileged_helper()

    assert result.success is False
    assert "cancelled" in result.message.lower()
    assert install_calls[0][1:] == (10, "a" * 64)
    assert list(tmp_path.iterdir()) == []


def test_install_rechecks_after_verified_success(monkeypatch, tmp_path):
    installable = _installable_status()
    installed = privileged_helper.PrivilegedHelperStatus(
        privileged_helper.PrivilegedHelperState.INSTALLED,
        privileged_helper._HELPER_PACKAGE,
        privileged_helper.__version__,
    )
    install_calls = []

    def download(staging, *_args):
        package = staging / "helper.deb"
        package.write_bytes(b"downloaded")
        return package

    def run_install(path, size, digest):
        install_calls.append((path, size, digest))
        return (True, False)

    statuses = iter((installable, installed))
    monkeypatch.setattr(privileged_helper, "get_privileged_helper_status", lambda: next(statuses))
    monkeypatch.setattr(privileged_helper, "_fetch_release_metadata", lambda: _release())
    monkeypatch.setattr(privileged_helper, "_expected_asset", lambda _release: (10, "a" * 64))
    monkeypatch.setattr(privileged_helper, "_cache_directory", lambda: tmp_path)
    monkeypatch.setattr(privileged_helper, "_download_asset", download)
    monkeypatch.setattr(privileged_helper, "_verify_deb_identity", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "_verify_deb_signature", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "_run_install", run_install)

    result = privileged_helper.install_matching_privileged_helper()

    assert result.success is True
    assert result.status is installed
    assert install_calls[0][1:] == (10, "a" * 64)
    assert list(tmp_path.iterdir()) == []


def test_debian_flatpak_helper_requires_exact_host_package_query(monkeypatch):
    calls = []
    monkeypatch.setattr(privileged_helper, "privileged_writer_available", lambda: True)
    monkeypatch.setattr(privileged_helper, "is_flatpak", lambda: True)
    monkeypatch.setattr(privileged_helper, "detect_distro_family", lambda: DistroFamily.DEBIAN)
    monkeypatch.setattr(privileged_helper, "_has_canonical_host_command", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "wrap_host_command", lambda command: command)

    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=f"ii \n{privileged_helper.__version__}\nall\n",
        )

    monkeypatch.setattr(privileged_helper.subprocess, "run", run)

    status = privileged_helper.get_privileged_helper_status()

    assert status.state is privileged_helper.PrivilegedHelperState.INSTALLED
    assert calls == [
        [
            "/usr/bin/dpkg-query",
            "--show",
            "--showformat=${db:Status-Abbrev}\\n${Version}\\n${Architecture}\\n",
            "clamui-privileged-helper",
        ]
    ]


def test_debian_flatpak_old_helper_is_installable(monkeypatch):
    monkeypatch.setattr(privileged_helper, "privileged_writer_available", lambda: True)
    monkeypatch.setattr(privileged_helper, "is_flatpak", lambda: True)
    monkeypatch.setattr(privileged_helper, "detect_distro_family", lambda: DistroFamily.DEBIAN)
    monkeypatch.setattr(privileged_helper, "_matching_host_helper_version", lambda: False)

    status = privileged_helper.get_privileged_helper_status()

    assert status.state is privileged_helper.PrivilegedHelperState.INSTALLABLE


def test_debian_flatpak_unqueryable_helper_is_not_claimed_installed(monkeypatch):
    monkeypatch.setattr(privileged_helper, "privileged_writer_available", lambda: True)
    monkeypatch.setattr(privileged_helper, "is_flatpak", lambda: True)
    monkeypatch.setattr(privileged_helper, "detect_distro_family", lambda: DistroFamily.DEBIAN)
    monkeypatch.setattr(privileged_helper, "_matching_host_helper_version", lambda: None)

    status = privileged_helper.get_privileged_helper_status()

    assert status.state is privileged_helper.PrivilegedHelperState.UNSUPPORTED
    assert status.is_installed is False


def test_elevated_install_launches_fixed_bootstrap_with_verified_asset_data(monkeypatch, tmp_path):
    source = tmp_path / "helper.deb"
    source.write_bytes(b"untrusted source")
    captured = []
    monkeypatch.setattr(privileged_helper, "_has_canonical_host_command", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "wrap_host_command", lambda command: command)
    monkeypatch.setattr(
        privileged_helper.subprocess,
        "run",
        lambda command, **_kwargs: (
            captured.append(command) or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )

    success, cancelled = privileged_helper._run_install(source, 16, "a" * 64)

    assert (success, cancelled) == (True, False)
    command = captured[0]
    assert command[:5] == [
        "/usr/bin/pkexec",
        "/usr/bin/python3",
        "-I",
        "-c",
        privileged_helper._ELEVATED_INSTALL_BOOTSTRAP,
    ]
    assert command[5:] == [str(source), "16", "a" * 64, privileged_helper.__version__]


def test_concurrent_install_returns_in_progress_without_launching(monkeypatch):
    status = _installable_status()
    monkeypatch.setattr(privileged_helper, "get_privileged_helper_status", lambda: status)
    monkeypatch.setattr(
        privileged_helper,
        "_install_matching_privileged_helper",
        lambda: pytest.fail("a second installer must not start"),
    )

    assert privileged_helper._INSTALL_LOCK.acquire(blocking=False)
    try:
        result = privileged_helper.install_matching_privileged_helper()
    finally:
        privileged_helper._INSTALL_LOCK.release()
    assert result.success is False
    assert "already in progress" in result.message.lower()


def _signed_members():
    return {
        "debian-binary": b"2.0\n",
        "control.tar.xz": b"control",
        "data.tar.xz": b"data",
        "_gpgbuilder": b"-----BEGIN PGP SIGNED MESSAGE-----\n",
    }


def _signed_fields(members):
    lines = ["Version: 4", "Role: builder", "Files:"]
    for name in ("debian-binary", "control.tar.xz", "data.tar.xz"):
        content = members[name]
        lines.append(
            f"\t{hashlib.md5(content, usedforsecurity=False).hexdigest()} "
            f"{hashlib.sha1(content, usedforsecurity=False).hexdigest()} "
            f"{len(content)} {name}"
        )
    return "\n".join(lines)


def test_dpkg_sig_v4_signed_members_match_exact_archive_content():
    members = _signed_members()

    assert privileged_helper._signed_deb_members_are_exact(_signed_fields(members), members) is True


def test_dpkg_sig_v4_rejects_tampered_archive_member():
    members = _signed_members()
    signed_fields = _signed_fields(members)
    members["data.tar.xz"] = b"tampered"

    assert privileged_helper._signed_deb_members_are_exact(signed_fields, members) is False


def test_signature_verification_requires_exact_validsig_fingerprint(monkeypatch):
    members = _signed_members()
    monkeypatch.setattr(privileged_helper, "_safe_regular_file", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "_trusted_key_is_safe", lambda: True)
    monkeypatch.setattr(privileged_helper, "_read_debian_ar", lambda _path: members)
    monkeypatch.setattr(privileged_helper.Path, "is_file", lambda _path: True)
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(
                returncode=0,
                stdout=_signed_fields(members),
                stderr=(
                    "[GNUPG:] VALIDSIG "
                    f"{privileged_helper._TRUSTED_SIGNING_FINGERPRINT} 2026-09-10 0 4 0 1 10 00"
                ),
            ),
        )
    )
    monkeypatch.setattr(
        privileged_helper.subprocess, "run", lambda *_args, **_kwargs: next(responses)
    )

    assert privileged_helper._verify_deb_signature(Path("/untrusted/helper.deb")) is True


def test_signature_verification_rejects_wrong_validsig_fingerprint(monkeypatch):
    members = _signed_members()
    monkeypatch.setattr(privileged_helper, "_safe_regular_file", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "_trusted_key_is_safe", lambda: True)
    monkeypatch.setattr(privileged_helper, "_read_debian_ar", lambda _path: members)
    monkeypatch.setattr(privileged_helper.Path, "is_file", lambda _path: True)
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(
                returncode=0,
                stdout=_signed_fields(members),
                stderr="[GNUPG:] VALIDSIG DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF",
            ),
        )
    )
    monkeypatch.setattr(
        privileged_helper.subprocess, "run", lambda *_args, **_kwargs: next(responses)
    )

    assert privileged_helper._verify_deb_signature(Path("/untrusted/helper.deb")) is False


def test_signature_verification_rejects_archive_without_builder_signature(monkeypatch):
    members = _signed_members()
    del members["_gpgbuilder"]
    monkeypatch.setattr(privileged_helper, "_safe_regular_file", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "_trusted_key_is_safe", lambda: True)
    monkeypatch.setattr(privileged_helper, "_read_debian_ar", lambda _path: members)
    monkeypatch.setattr(privileged_helper.Path, "is_file", lambda _path: True)

    assert privileged_helper._verify_deb_signature(Path("/untrusted/helper.deb")) is False


def test_invalid_signature_never_reaches_elevated_installer(monkeypatch, tmp_path):
    status = _installable_status()
    install_calls = []

    def download(staging, *_args):
        package = staging / "helper.deb"
        package.write_bytes(b"downloaded")
        return package

    monkeypatch.setattr(privileged_helper, "get_privileged_helper_status", lambda: status)
    monkeypatch.setattr(privileged_helper, "_fetch_release_metadata", lambda: _release())
    monkeypatch.setattr(privileged_helper, "_expected_asset", lambda _release: (10, "a" * 64))
    monkeypatch.setattr(privileged_helper, "_cache_directory", lambda: tmp_path)
    monkeypatch.setattr(privileged_helper, "_download_asset", download)
    monkeypatch.setattr(privileged_helper, "_verify_deb_identity", lambda _path: True)
    monkeypatch.setattr(privileged_helper, "_verify_deb_signature", lambda _path: False)
    monkeypatch.setattr(
        privileged_helper, "_run_install", lambda *_args: install_calls.append(_args)
    )

    result = privileged_helper.install_matching_privileged_helper()

    assert result.success is False
    assert "signature" in result.message.lower()
    assert install_calls == []
