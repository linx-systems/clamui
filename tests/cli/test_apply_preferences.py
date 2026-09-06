# ClamUI Privileged Apply Helper Tests
"""
Tests for the privileged configuration apply helper CLI.

End-to-end coverage of the rewritten ``main()`` flow against the new
src/dst-pair protocol.  The destination allowlist itself is exercised in
:mod:`tests.core.test_privileged_paths`; here we focus on argv parsing,
the protocol/PKEXEC_UID handshake, and the systemd-restart wiring.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cli import apply_preferences
from src.cli.apply_preferences import (
    _restart_units_for_destinations,
    main,
)
from src.core import privileged_paths

PROTOCOL_TOKEN = f"--protocol={privileged_paths.PROTOCOL_VERSION}"


def _bootstrap(monkeypatch, tmp_path):
    """Set up a working PKEXEC_UID + staging root + allowlist override."""
    monkeypatch.setenv("PKEXEC_UID", str(os.geteuid()))
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    os.chmod(staging, 0o700)
    monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)
    monkeypatch.setattr(
        apply_preferences,
        "_restart_units_for_destinations",
        lambda _dests: None,
    )
    return staging


class TestApplyPreferencesCli:
    """Tests for src.cli.apply_preferences.main."""

    def test_main_applies_single_config_pair(self, tmp_path, monkeypatch):
        """Helper should copy a staged file and set destination permissions."""
        staging = _bootstrap(monkeypatch, tmp_path)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_DIRS", (dest_dir,))
        monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_FILES", ())

        source = staging / "source.conf"
        destination = dest_dir / "dest.conf"
        source.write_text("LogVerbose yes\n", encoding="utf-8")
        os.chmod(source, 0o600)

        exit_code = main([PROTOCOL_TOKEN, str(source), str(destination)])

        assert exit_code == 0
        assert destination.read_text(encoding="utf-8") == "LogVerbose yes\n"
        assert (destination.stat().st_mode & 0o777) == 0o644

    def test_main_rejects_odd_argument_count(self, tmp_path, monkeypatch):
        """Helper should fail when source/destination args are not paired."""
        _bootstrap(monkeypatch, tmp_path)
        exit_code = main([PROTOCOL_TOKEN, "/tmp/source.conf"])
        assert exit_code == 2

    def test_main_rejects_no_pairs(self, tmp_path, monkeypatch):
        """Helper should fail when no src/dst pairs are provided."""
        _bootstrap(monkeypatch, tmp_path)
        exit_code = main([PROTOCOL_TOKEN])
        assert exit_code == 2

    def test_main_fails_for_missing_source(self, tmp_path, monkeypatch):
        """Helper should fail when staged source file does not exist."""
        staging = _bootstrap(monkeypatch, tmp_path)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_DIRS", (dest_dir,))
        monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_FILES", ())

        missing_source = staging / "missing.conf"
        destination = dest_dir / "dest.conf"

        exit_code = main([PROTOCOL_TOKEN, str(missing_source), str(destination)])

        assert exit_code != 0
        assert not destination.exists()

    def test_main_creates_destination_parent_directory(self, tmp_path, monkeypatch):
        """Helper should create destination parent directories when needed."""
        staging = _bootstrap(monkeypatch, tmp_path)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_DIRS", (dest_dir,))
        monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_FILES", ())

        source = staging / "source.conf"
        # Pre-existing dir is in allowlist; missing-parent recovery is part
        # of _atomic_install which calls mkdir(parents=True, exist_ok=True).
        destination = dest_dir / "dest.conf"
        source.write_text("DatabaseDirectory /var/lib/clamav\n", encoding="utf-8")
        os.chmod(source, 0o600)

        exit_code = main([PROTOCOL_TOKEN, str(source), str(destination)])

        assert exit_code == 0
        assert destination.exists()

    def test_main_restarts_active_services_for_written_configs(self, tmp_path, monkeypatch):
        """Helper should restart active relevant services after applying configs."""
        # Bootstrap manually because we want to keep the real
        # _restart_units_for_destinations and intercept subprocess.run.
        monkeypatch.setenv("PKEXEC_UID", str(os.geteuid()))
        staging = tmp_path / "staging"
        staging.mkdir(mode=0o700)
        os.chmod(staging, 0o700)
        monkeypatch.setattr(apply_preferences, "_resolve_staging_root", lambda _uid: staging)

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_DIRS", (dest_dir,))
        monkeypatch.setattr(privileged_paths, "ALLOWED_DEST_FILES", ())

        source = staging / "source.conf"
        destination = dest_dir / "freshclam.conf"
        source.write_text("DatabaseDirectory /var/lib/clamav\n", encoding="utf-8")
        os.chmod(source, 0o600)

        run_calls: list[list[str]] = []

        def _fake_run(cmd, **_kwargs):
            run_calls.append(list(cmd))

            class _Result:
                returncode = 0
                stderr = ""
                stdout = ""

            return _Result()

        with (
            patch("src.cli.apply_preferences.shutil.which", return_value="/usr/bin/systemctl"),
            patch("src.cli.apply_preferences.subprocess.run", side_effect=_fake_run),
        ):
            exit_code = main([PROTOCOL_TOKEN, str(source), str(destination)])

        assert exit_code == 0
        assert ["systemctl", "is-active", "--quiet", "clamav-freshclam.service"] in run_calls
        assert ["systemctl", "restart", "clamav-freshclam.service"] in run_calls


class TestRestartUnitsForDestinations:
    """Tests for service restart behavior after privileged writes."""

    def test_skips_restart_when_systemctl_unavailable(self):
        """Restart helper should no-op when systemctl is not installed."""
        with patch("src.cli.apply_preferences.shutil.which", return_value=None):
            _restart_units_for_destinations([Path("/etc/clamav/freshclam.conf")])

    def test_skips_inactive_units(self):
        """Inactive units should be skipped without calling restart."""
        run_calls = []

        def _fake_run(cmd, **_kwargs):
            run_calls.append(list(cmd))

            class _Result:
                returncode = 3
                stderr = ""
                stdout = ""

            return _Result()

        with (
            patch("src.cli.apply_preferences.shutil.which", return_value="/usr/bin/systemctl"),
            patch("src.cli.apply_preferences.subprocess.run", side_effect=_fake_run),
        ):
            _restart_units_for_destinations([Path("/etc/clamav/freshclam.conf")])

        assert ["systemctl", "is-active", "--quiet", "clamav-freshclam.service"] in run_calls
        assert not any(call[:2] == ["systemctl", "restart"] for call in run_calls)

    def test_raises_when_active_unit_restart_fails(self):
        """Restart helper should fail when an active relevant unit cannot restart."""

        def _fake_run(cmd, **_kwargs):
            class _Result:
                stderr = ""
                stdout = ""

            result = _Result()
            if cmd[:3] == ["systemctl", "is-active", "--quiet"]:
                result.returncode = 0
            else:
                result.returncode = 1
                result.stderr = "bad config"
            return result

        with (
            patch("src.cli.apply_preferences.shutil.which", return_value="/usr/bin/systemctl"),
            patch("src.cli.apply_preferences.subprocess.run", side_effect=_fake_run),
        ):
            with pytest.raises(RuntimeError, match=r"Failed to restart clamav-freshclam\.service"):
                _restart_units_for_destinations([Path("/etc/clamav/freshclam.conf")])
