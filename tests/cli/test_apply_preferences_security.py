# ClamUI Privileged Apply Helper Security Tests
"""
Security tests for the rewritten privileged apply helper.

These tests cover the attack-surface contract the helper must hold up
against.  They monkey-patch :data:`src.core.privileged_paths.ALLOWED_DEST_DIRS`
and :data:`ALLOWED_DEST_FILES` to point under ``tmp_path`` so that the helper
can be exercised end-to-end without needing root.

Coverage focus:

- ``PKEXEC_UID`` env var must be present and parse to a valid UID.
- The first positional argument must be ``--protocol=3``; anything else
  is rejected so an outdated caller cannot silently invoke a hardened helper
  with the old src/dst-only positional layout.
- A staged source outside the per-invocation staging root is rejected
  *before* any destination is written.
- A staged source that is a symlink (e.g. to ``/etc/shadow``) is refused
  by the ``O_NOFOLLOW`` open in the helper.
- On the happy path the destination has mode 0o644 and matches the
  staged content byte-for-byte.
- Atomicity: if pair #2 fails validation, pair #1's destination must
  not be left in an inconsistent or half-written state.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.cli import apply_preferences
from src.core import privileged_paths

PROTOCOL_TOKEN = f"--protocol={privileged_paths.PROTOCOL_VERSION}"


def _make_staging(tmp_path: Path) -> Path:
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    os.chmod(staging, 0o700)
    return staging


def _make_allowed_dest_dir(tmp_path: Path, name: str) -> Path:
    dest_dir = tmp_path / name
    dest_dir.mkdir()
    return dest_dir


def _patch_allowlist_to_tmp(monkeypatch, dest_dir: Path) -> None:
    """Redirect the allowlist so tests can exercise the full main() flow."""
    monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_DIRS", (dest_dir,))
    monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_FILES", ())


def _set_pkexec_env(monkeypatch) -> None:
    monkeypatch.setenv("PKEXEC_UID", str(os.geteuid()))


def _stage_file(staging: Path, name: str, content: str) -> Path:
    path = staging / name
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


class TestPkexecUidEnv:
    """The helper requires PKEXEC_UID to be set by the policykit invocation."""

    def test_missing_pkexec_uid_returns_three(self, monkeypatch):
        monkeypatch.delenv("PKEXEC_UID", raising=False)
        assert apply_preferences.main([PROTOCOL_TOKEN]) == 3

    def test_zero_pkexec_uid_returns_three(self, monkeypatch):
        monkeypatch.setenv("PKEXEC_UID", "0")
        assert apply_preferences.main([PROTOCOL_TOKEN]) == 3

    def test_non_numeric_pkexec_uid_returns_three(self, monkeypatch):
        monkeypatch.setenv("PKEXEC_UID", "not-a-number")
        assert apply_preferences.main([PROTOCOL_TOKEN]) == 3


class TestProtocolHandshake:
    """Old callers paired with the hardened helper must fail closed."""

    def test_missing_protocol_flag_returns_four(self, monkeypatch, tmp_path):
        _set_pkexec_env(monkeypatch)
        staging = _make_staging(tmp_path)
        src = _stage_file(staging, "a.conf", "x")
        dest_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        _patch_allowlist_to_tmp(monkeypatch, dest_dir)
        monkeypatch.setattr(
            apply_preferences,
            "_resolve_staging_root",
            lambda _uid: staging,
        )

        assert apply_preferences.main([str(src), str(dest_dir / "a.conf")]) == 4

    def test_protocol_two_returns_four(self, monkeypatch):
        _set_pkexec_env(monkeypatch)
        assert apply_preferences.main(["--protocol=2", "/dev/null", "/etc/clamav/a.conf"]) == 4


class TestSourceMustBeUnderStagingRoot:
    """A source path outside the staging root must be rejected."""

    def test_source_outside_staging_rejected(self, monkeypatch, tmp_path):
        _set_pkexec_env(monkeypatch)
        staging = _make_staging(tmp_path)
        # Source is outside staging
        outside = tmp_path / "outside"
        outside.mkdir()
        src = _stage_file(outside, "evil.conf", "owned")
        dest_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        dest = dest_dir / "evil.conf"

        _patch_allowlist_to_tmp(monkeypatch, dest_dir)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
        # No service restarts in tests
        monkeypatch.setattr(
            apply_preferences,
            "_restart_units_for_destinations",
            lambda _dests: None,
        )

        exit_code = apply_preferences.main([PROTOCOL_TOKEN, str(src), str(dest)])

        assert exit_code != 0
        assert not dest.exists()


class TestSourceMustNotBeSymlink:
    """O_NOFOLLOW must refuse to read content through a symlink."""

    def test_symlink_source_rejected(self, monkeypatch, tmp_path):
        _set_pkexec_env(monkeypatch)
        staging = _make_staging(tmp_path)
        # Real "secret" file outside staging
        secret = tmp_path / "shadow_like"
        secret.write_text("root:$6$...:0:0:::", encoding="utf-8")
        os.chmod(secret, 0o600)
        # Symlink inside staging pointing at the secret
        link = staging / "evil.conf"
        link.symlink_to(secret)
        dest_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        dest = dest_dir / "evil.conf"

        _patch_allowlist_to_tmp(monkeypatch, dest_dir)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
        monkeypatch.setattr(
            apply_preferences,
            "_restart_units_for_destinations",
            lambda _dests: None,
        )

        exit_code = apply_preferences.main([PROTOCOL_TOKEN, str(link), str(dest)])

        assert exit_code != 0
        assert not dest.exists()


class TestHappyPath:
    """A valid src/dst pair installs the destination with mode 0o644."""

    def test_single_pair_installed_with_mode_0o644(self, monkeypatch, tmp_path):
        _set_pkexec_env(monkeypatch)
        staging = _make_staging(tmp_path)
        src = _stage_file(staging, "clamd.conf", "LogVerbose yes\n")
        dest_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        dest = dest_dir / "clamd.conf"

        _patch_allowlist_to_tmp(monkeypatch, dest_dir)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
        monkeypatch.setattr(
            apply_preferences,
            "_restart_units_for_destinations",
            lambda _dests: None,
        )

        exit_code = apply_preferences.main([PROTOCOL_TOKEN, str(src), str(dest)])

        assert exit_code == 0
        assert dest.read_text(encoding="utf-8") == "LogVerbose yes\n"
        assert dest.stat().st_mode & 0o777 == 0o644

    def test_parent_symlink_swap_uses_preflighted_canonical_destination(
        self, monkeypatch, tmp_path
    ):
        _set_pkexec_env(monkeypatch)
        staging = _make_staging(tmp_path)
        source = _stage_file(staging, "clamd.conf", "LogVerbose yes\n")
        allowed_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        argv_parent = tmp_path / "clamav-link"
        argv_parent.symlink_to(allowed_dir, target_is_directory=True)
        canonical_destination = allowed_dir / "clamd.conf"
        outside_destination = outside_dir / "clamd.conf"

        _patch_allowlist_to_tmp(monkeypatch, allowed_dir)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
        monkeypatch.setattr(
            apply_preferences,
            "_restart_units_for_destinations",
            lambda _dests: None,
        )
        open_and_validate_source = apply_preferences._open_and_validate_source

        def _swap_parent_after_source_preflight(source, expected_uid, staging_root):
            source_fd = open_and_validate_source(source, expected_uid, staging_root)
            argv_parent.unlink()
            argv_parent.symlink_to(outside_dir, target_is_directory=True)
            return source_fd

        monkeypatch.setattr(
            apply_preferences,
            "_open_and_validate_source",
            _swap_parent_after_source_preflight,
        )

        exit_code = apply_preferences.main(
            [PROTOCOL_TOKEN, str(source), str(argv_parent / "clamd.conf")]
        )

        assert exit_code == 0
        assert canonical_destination.read_text(encoding="utf-8") == "LogVerbose yes\n"
        assert not outside_destination.exists()


class TestAtomicityAcrossPairs:
    """If a later pair is invalid, an earlier pair must not leak."""

    def test_second_pair_invalid_destination_rejects_whole_invocation(self, monkeypatch, tmp_path):
        _set_pkexec_env(monkeypatch)
        staging = _make_staging(tmp_path)
        src_a = _stage_file(staging, "a.conf", "a-content\n")
        src_b = _stage_file(staging, "b.conf", "b-content\n")
        dest_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        dest_a = dest_dir / "a.conf"
        # dest_b is outside the allowlist directory: validate_destination must reject it
        dest_b = tmp_path / "outside" / "b.conf"

        _patch_allowlist_to_tmp(monkeypatch, dest_dir)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
        monkeypatch.setattr(
            apply_preferences,
            "_restart_units_for_destinations",
            lambda _dests: None,
        )

        exit_code = apply_preferences.main(
            [
                PROTOCOL_TOKEN,
                str(src_a),
                str(dest_a),
                str(src_b),
                str(dest_b),
            ]
        )

        # Whole invocation must fail; neither destination should exist.
        assert exit_code != 0
        assert not dest_a.exists()
        assert not dest_b.exists()

    def test_second_pair_missing_source_is_rejected_before_first_write(
        self, monkeypatch, tmp_path, capsys
    ):
        _set_pkexec_env(monkeypatch)
        staging = _make_staging(tmp_path)
        src_a = _stage_file(staging, "a.conf", "a-content\n")
        missing_src = staging / "missing.conf"
        dest_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        dest_a = dest_dir / "a.conf"
        dest_b = dest_dir / "b.conf"

        _patch_allowlist_to_tmp(monkeypatch, dest_dir)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
        monkeypatch.setattr(
            apply_preferences,
            "_restart_units_for_destinations",
            lambda _dests: None,
        )

        exit_code = apply_preferences.main(
            [
                PROTOCOL_TOKEN,
                str(src_a),
                str(dest_a),
                str(missing_src),
                str(dest_b),
            ]
        )

        assert exit_code != 0
        assert str(missing_src) in capsys.readouterr().err
        assert not dest_a.exists()
        assert not dest_b.exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to chown source to a different uid")
class TestSourceUidMismatchRejected:
    """A source owned by a UID other than PKEXEC_UID must be rejected.

    This test only runs when the suite is executed as root (e.g. in a
    container or VM); under a normal developer account we cannot ``chown``
    a file to a foreign UID.  Marked skip in that case rather than mocking
    so the security guarantee is exercised against the real ``os.fstat``.
    """

    def test_foreign_uid_source_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PKEXEC_UID", "1000")
        staging = _make_staging(tmp_path)
        # chown the staging root and source to uid 1000 (not root)
        os.chown(staging, 1000, 1000)
        src = _stage_file(staging, "a.conf", "x")
        os.chown(src, 65534, 65534)  # nobody/nogroup
        dest_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        dest = dest_dir / "a.conf"

        _patch_allowlist_to_tmp(monkeypatch, dest_dir)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
        monkeypatch.setattr(
            apply_preferences,
            "_restart_units_for_destinations",
            lambda _dests: None,
        )

        exit_code = apply_preferences.main([PROTOCOL_TOKEN, str(src), str(dest)])

        assert exit_code != 0
        assert not dest.exists()


class TestStagingRootValidation:
    """A loose-permission staging root must abort the helper."""

    def test_world_readable_staging_rejected(self, monkeypatch, tmp_path):
        _set_pkexec_env(monkeypatch)
        staging = tmp_path / "staging"
        staging.mkdir(mode=0o755)
        os.chmod(staging, 0o755)  # group/other readable -- not allowed
        src = _stage_file(staging, "a.conf", "x")
        dest_dir = _make_allowed_dest_dir(tmp_path, "etc_clamav")
        dest = dest_dir / "a.conf"

        _patch_allowlist_to_tmp(monkeypatch, dest_dir)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
        monkeypatch.setattr(
            apply_preferences,
            "_restart_units_for_destinations",
            lambda _dests: None,
        )

        exit_code = apply_preferences.main([PROTOCOL_TOKEN, str(src), str(dest)])

        assert exit_code != 0
        assert not dest.exists()
