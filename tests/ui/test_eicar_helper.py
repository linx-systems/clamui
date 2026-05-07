# EICAR Helper Tests
"""Unit tests for the GTK-free EICAR helper module.

Covers UI-010: EICAR temp files must be cleaned up on normal completion,
on cancel/error, and via atexit registration to survive a crash or
force-quit mid-scan.
"""

import atexit
from pathlib import Path
from unittest import mock

from src.ui.eicar_helper import (
    EICAR_TEST_STRING,
    cleanup_eicar_path,
    create_eicar_temp,
    register_eicar_atexit_cleanup,
)


class TestEicarTestString:
    """Sanity check the test string constant."""

    def test_contains_signature(self):
        assert "EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in EICAR_TEST_STRING


class TestCreateEicarTemp:
    """Tests for create_eicar_temp."""

    def test_creates_file_with_eicar_content(self, tmp_path):
        path = create_eicar_temp(parent_dir=str(tmp_path))
        try:
            assert Path(path).exists()
            assert Path(path).read_text() == EICAR_TEST_STRING
        finally:
            cleanup_eicar_path(path)

    def test_uses_provided_parent_dir(self, tmp_path):
        path = create_eicar_temp(parent_dir=str(tmp_path))
        try:
            assert Path(path).parent == tmp_path
        finally:
            cleanup_eicar_path(path)

    def test_default_dir_when_none(self):
        # Should fall through to tempfile's default location
        path = create_eicar_temp(parent_dir=None)
        try:
            assert Path(path).exists()
        finally:
            cleanup_eicar_path(path)


class TestCleanupEicarPath:
    """Tests for cleanup_eicar_path."""

    def test_removes_existing_file(self, tmp_path):
        path = tmp_path / "eicar.txt"
        path.write_text(EICAR_TEST_STRING)
        assert path.exists()

        cleanup_eicar_path(str(path))

        assert not path.exists()

    def test_handles_missing_file(self, tmp_path):
        # Should not raise even though file does not exist
        cleanup_eicar_path(str(tmp_path / "does_not_exist.txt"))

    def test_handles_empty_string(self):
        # Should be a no-op
        cleanup_eicar_path("")

    def test_handles_none(self):
        # Should be a no-op
        cleanup_eicar_path(None)

    def test_swallows_oserror(self, tmp_path):
        path = tmp_path / "eicar.txt"
        path.write_text(EICAR_TEST_STRING)

        with mock.patch("src.ui.eicar_helper.Path.unlink", side_effect=OSError("permission")):
            # Must not propagate
            cleanup_eicar_path(str(path))


class TestRegisterEicarAtexitCleanup:
    """Tests for register_eicar_atexit_cleanup."""

    def test_registers_atexit_handler(self, tmp_path):
        path = str(tmp_path / "eicar.txt")
        with mock.patch.object(atexit, "register") as mock_register:
            register_eicar_atexit_cleanup(path)
            mock_register.assert_called_once()
            registered_fn, registered_path = (
                mock_register.call_args.args[0],
                mock_register.call_args.args[1],
            )
            assert registered_fn is cleanup_eicar_path
            assert registered_path == path

    def test_register_returns_unregister_handle(self, tmp_path):
        # The returned handle should be callable to unregister early
        # (so it doesn't fire after a successful in-process cleanup).
        path = str(tmp_path / "eicar.txt")
        unregister = register_eicar_atexit_cleanup(path)
        try:
            assert callable(unregister)
        finally:
            unregister()

    def test_atexit_cleanup_runs_for_real_path(self, tmp_path):
        # Integration: register then immediately invoke atexit handler-style
        path = tmp_path / "eicar.txt"
        path.write_text(EICAR_TEST_STRING)
        unregister = register_eicar_atexit_cleanup(str(path))
        try:
            # Simulate atexit firing by calling cleanup directly
            cleanup_eicar_path(str(path))
            assert not path.exists()
        finally:
            unregister()


class TestRegisterEmptyPath:
    """register_eicar_atexit_cleanup with bad input must be safe."""

    def test_empty_string_does_not_register(self):
        with mock.patch.object(atexit, "register") as mock_register:
            register_eicar_atexit_cleanup("")
            mock_register.assert_not_called()

    def test_none_does_not_register(self):
        with mock.patch.object(atexit, "register") as mock_register:
            register_eicar_atexit_cleanup(None)
            mock_register.assert_not_called()


# Sanity check: ensure pytest collects this module correctly under tests/ui
def test_module_importable():
    import src.ui.eicar_helper  # noqa: F401
