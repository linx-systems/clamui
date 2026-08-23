# ClamUI install-privileged-helper tests
"""Unit tests for the privileged-helper installer (issue #143, Part 4)."""

import argparse
import os
import stat
import sys
from importlib.resources import files
from pathlib import Path

import pytest

from src.cli import install_helper


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class TestInstallPrivilegedHelper:
    """Tests for install_helper.install_privileged_helper()."""

    def test_creates_all_artifacts_with_modes(self, tmp_path):
        success, message = install_helper.install_privileged_helper(prefix=str(tmp_path))

        assert success is True
        assert "Installed privileged helper" in message

        bin_path = tmp_path / "usr/bin/clamui-apply-preferences"
        lib_dir = tmp_path / "usr/lib/clamui"
        priv = lib_dir / "clamui_privileged_paths.py"
        apply = lib_dir / "clamui_apply_preferences.py"
        policy = tmp_path / "usr/share/polkit-1/actions" / install_helper.POLICY_NAME

        assert bin_path.is_file()
        assert priv.is_file()
        assert apply.is_file()
        assert policy.is_file()

        assert _mode(bin_path) == 0o755
        assert _mode(priv) == 0o644
        assert _mode(apply) == 0o644
        assert _mode(policy) == 0o644

    def test_created_directory_chain_has_safe_modes_with_permissive_umask(self, tmp_path):
        old_umask = os.umask(0)
        try:
            success, _message = install_helper.install_privileged_helper(prefix=str(tmp_path))
        finally:
            os.umask(old_umask)

        assert success is True
        for relative in (
            "usr",
            "usr/bin",
            "usr/lib",
            "usr/lib/clamui",
            "usr/share",
            "usr/share/polkit-1",
            "usr/share/polkit-1/actions",
        ):
            assert _mode(tmp_path / relative) == 0o755

    def test_apply_helper_import_is_rewritten(self, tmp_path):
        install_helper.install_privileged_helper(prefix=str(tmp_path))
        apply = tmp_path / "usr/lib/clamui/clamui_apply_preferences.py"
        content = apply.read_text(encoding="utf-8")

        assert "from clamui_privileged_paths import" in content
        # No relative imports may remain, or the system-python wrapper can't load it.
        assert "from ..core" not in content
        assert "\nfrom ." not in content

    def test_privileged_paths_copied_verbatim(self, tmp_path):
        install_helper.install_privileged_helper(prefix=str(tmp_path))
        copied = (tmp_path / "usr/lib/clamui/clamui_privileged_paths.py").read_text("utf-8")
        original = (
            Path(install_helper.__file__).resolve().parent.parent / "core" / "privileged_paths.py"
        ).read_text("utf-8")
        assert copied == original

    def test_wrapper_uses_system_python_and_runtime_lib(self, tmp_path):
        install_helper.install_privileged_helper(prefix=str(tmp_path))
        wrapper = (tmp_path / "usr/bin/clamui-apply-preferences").read_text("utf-8")

        assert wrapper.startswith("#!/usr/bin/python3")
        # References the canonical runtime path, never the staging prefix.
        assert install_helper.RUNTIME_LIB_DIR in wrapper
        assert str(tmp_path) not in wrapper
        assert "from clamui_apply_preferences import main" in wrapper

    def test_policy_copied_unchanged(self, tmp_path):
        install_helper.install_privileged_helper(prefix=str(tmp_path))
        copied = (tmp_path / "usr/share/polkit-1/actions" / install_helper.POLICY_NAME).read_text(
            "utf-8"
        )
        original = (files("src.cli.resources") / install_helper.POLICY_NAME).read_text(
            encoding="utf-8"
        )
        assert copied == original
        # The polkit exec.path must match where the wrapper is installed.
        assert "/usr/bin/clamui-apply-preferences" in copied

    def test_installed_helper_is_importable_standalone(self, tmp_path):
        """The copied, import-rewritten helper must load with a plain interpreter
        (no clamui package on the path) -- this is what pkexec relies on."""
        install_helper.install_privileged_helper(prefix=str(tmp_path))
        lib_dir = str(tmp_path / "usr/lib/clamui")

        saved_path = list(sys.path)
        saved_modules = {
            name: sys.modules.pop(name)
            for name in ("clamui_apply_preferences", "clamui_privileged_paths")
            if name in sys.modules
        }
        sys.path.insert(0, lib_dir)
        try:
            import clamui_apply_preferences

            assert callable(clamui_apply_preferences.main)
        finally:
            sys.path[:] = saved_path
            for name in ("clamui_apply_preferences", "clamui_privileged_paths"):
                sys.modules.pop(name, None)
            sys.modules.update(saved_modules)

    def test_missing_source_reports_error(self, tmp_path, monkeypatch):
        missing = tmp_path / "nope.py"
        monkeypatch.setattr(install_helper, "_source_paths", lambda: (missing, missing, missing))
        success, message = install_helper.install_privileged_helper(prefix=str(tmp_path))
        assert success is False
        assert "not found" in message.lower()

    def test_replaces_final_symlink_at_canonical_bin_without_following_it(self, tmp_path):
        """A pre-existing symlink at the canonical bin destination must be
        *replaced* by a fresh regular file, never written through.  If the
        installer followed the symlink, an attacker who pre-creates one at the
        install path would redirect the root-owned wrapper write into an
        arbitrary victim file -- a symlink-following privilege escalation."""
        victim = tmp_path / "victim"
        sentinel = b"untouched-victim-bytes\n"
        victim.write_bytes(sentinel)

        bin_path = tmp_path / "usr/bin/clamui-apply-preferences"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.symlink_to(victim)

        success, _message = install_helper.install_privileged_helper(prefix=str(tmp_path))

        assert success is True
        # The destination is now a regular file, not a symlink that still redirects.
        assert not bin_path.is_symlink()
        assert bin_path.is_file()
        # The pre-existing symlink target must be byte-for-byte untouched.
        assert victim.read_bytes() == sentinel
        # The installed file is the real executable wrapper, not the victim file.
        assert _mode(bin_path) == 0o755
        assert bin_path.read_text(encoding="utf-8").startswith("#!/usr/bin/python3")


class TestRunCommand:
    """Tests for the install_helper.run() CLI entry point."""

    def test_real_install_requires_root(self, monkeypatch, capsys):
        monkeypatch.setattr(install_helper.os, "geteuid", lambda: 1000)
        rc = install_helper.run(argparse.Namespace(prefix="/"))
        assert rc == 1
        assert "root" in capsys.readouterr().err.lower()

    def test_prefixed_install_does_not_require_root(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(install_helper.os, "geteuid", lambda: 1000)
        rc = install_helper.run(argparse.Namespace(prefix=str(tmp_path)))
        assert rc == 0
        assert "Installed privileged helper" in capsys.readouterr().out
        assert (tmp_path / "usr/bin/clamui-apply-preferences").is_file()


class TestRouterRegistration:
    """The subcommand must be discoverable by the CLI router."""

    def test_subcommand_registered(self):
        from src.cli.router import CLI_SUBCOMMANDS

        assert "install-privileged-helper" in CLI_SUBCOMMANDS


class TestFlatpakBoundary:
    """Flatpak must delegate real helper installation to the host."""

    @pytest.mark.parametrize("effective_uid", [1000, 0])
    def test_real_install_in_flatpak_aborts_without_sudo_or_install(
        self, effective_uid, monkeypatch, capsys
    ):
        monkeypatch.setattr(install_helper.os, "geteuid", lambda: effective_uid)
        monkeypatch.setattr(install_helper, "is_flatpak", lambda: True)

        installer_calls = 0

        def _must_not_run(prefix="/"):
            nonlocal installer_calls
            installer_calls += 1
            return True, "unreachable"

        monkeypatch.setattr(install_helper, "install_privileged_helper", _must_not_run)

        rc = install_helper.run(argparse.Namespace(prefix="/"))
        err = capsys.readouterr().err.lower()

        assert rc != 0
        assert installer_calls == 0
        assert "flatpak" in err
        assert "host" in err
        assert "sudo" not in err
