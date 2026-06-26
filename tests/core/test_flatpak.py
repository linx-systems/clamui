# ClamUI Flatpak Tests
"""Unit tests for the flatpak module functions."""

import os
import subprocess
import threading
from pathlib import Path
from unittest import mock

from src.core import flatpak


class TestIsFlatpak:
    """Tests for is_flatpak() function."""

    def test_is_flatpak_when_flatpak_info_exists(self):
        """Test is_flatpak returns True when /.flatpak-info exists."""
        # Reset cache
        flatpak._flatpak_detected = None

        with mock.patch("os.path.exists", return_value=True) as mock_exists:
            result = flatpak.is_flatpak()
            assert result is True
            mock_exists.assert_called_once_with("/.flatpak-info")

    def test_is_flatpak_when_flatpak_info_missing(self):
        """Test is_flatpak returns False when /.flatpak-info does not exist."""
        # Reset cache
        flatpak._flatpak_detected = None

        with mock.patch("os.path.exists", return_value=False) as mock_exists:
            result = flatpak.is_flatpak()
            assert result is False
            mock_exists.assert_called_once_with("/.flatpak-info")

    def test_is_flatpak_caching(self):
        """Test is_flatpak caches the result after first check."""
        # Reset cache
        flatpak._flatpak_detected = None

        with mock.patch("os.path.exists", return_value=True) as mock_exists:
            # First call should check filesystem
            result1 = flatpak.is_flatpak()
            assert result1 is True
            assert mock_exists.call_count == 1

            # Second call should use cached value
            result2 = flatpak.is_flatpak()
            assert result2 is True
            # Still only called once
            assert mock_exists.call_count == 1

    def test_is_flatpak_thread_safety(self):
        """Test is_flatpak is thread-safe."""
        # Reset cache
        flatpak._flatpak_detected = None

        results = []

        def check_flatpak():
            result = flatpak.is_flatpak()
            results.append(result)

        with mock.patch("os.path.exists", return_value=True):
            threads = [threading.Thread(target=check_flatpak) for _ in range(10)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        # All threads should get the same result
        assert len(results) == 10
        assert all(r is True for r in results)


class TestWrapHostCommand:
    """Tests for wrap_host_command() function."""

    def test_wrap_host_command_not_in_flatpak(self):
        """Test wrap_host_command returns original command when not in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            command = ["clamscan", "--version"]
            result = flatpak.wrap_host_command(command)
            assert result == ["clamscan", "--version"]

    def test_wrap_host_command_in_flatpak(self):
        """Test wrap_host_command wraps command when in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            command = ["clamscan", "--version"]
            result = flatpak.wrap_host_command(command)
            assert result == ["flatpak-spawn", "--host", "clamscan", "--version"]

    def test_wrap_host_command_empty_command(self):
        """Test wrap_host_command handles empty command."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            command = []
            result = flatpak.wrap_host_command(command)
            assert result == []

    def test_wrap_host_command_preserves_list(self):
        """Test wrap_host_command returns a new list."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            command = ["clamscan", "--version"]
            result = flatpak.wrap_host_command(command)
            assert result == command
            assert result is not command  # New list object

    def test_wrap_host_command_with_arguments(self):
        """Test wrap_host_command handles commands with many arguments."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            command = [
                "clamscan",
                "-r",
                "/home/user",
                "--verbose",
                "--max-filesize=100M",
            ]
            result = flatpak.wrap_host_command(command)
            assert result == [
                "flatpak-spawn",
                "--host",
                "clamscan",
                "-r",
                "/home/user",
                "--verbose",
                "--max-filesize=100M",
            ]

    def test_wrap_host_command_force_host_uses_host(self):
        """Test wrap_host_command with force_host=True uses host binary."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            # Even if an executable exists at /app/bin/clamdscan,
            # Flatpak ClamAV commands should use flatpak-spawn --host.
            with mock.patch("os.path.isfile", return_value=True):
                with mock.patch("os.access", return_value=True):
                    command = ["clamdscan", "--ping", "3"]
                    result = flatpak.wrap_host_command(command, force_host=True)
                    assert result == [
                        "flatpak-spawn",
                        "--host",
                        "clamdscan",
                        "--ping",
                        "3",
                    ]

    def test_wrap_host_command_force_host_not_in_flatpak(self):
        """Test wrap_host_command with force_host=True returns original when not in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            command = ["clamdscan", "--ping", "3"]
            result = flatpak.wrap_host_command(command, force_host=True)
            # Not in Flatpak, so just return the original command
            assert result == ["clamdscan", "--ping", "3"]

    def test_wrap_host_command_ignores_app_bin_binary(self):
        """Test Flatpak commands use host binaries even when /app/bin has a match."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch("os.path.isfile", return_value=True):
                with mock.patch("os.access", return_value=True):
                    command = ["clamscan", "--version"]
                    result = flatpak.wrap_host_command(command)
                    assert result == ["flatpak-spawn", "--host", "clamscan", "--version"]


class TestWhichHostCommand:
    """Tests for which_host_command() function."""

    def test_which_host_command_not_in_flatpak_found(self):
        """Test which_host_command uses shutil.which when not in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("shutil.which", return_value="/usr/bin/clamscan") as mock_which:
                result = flatpak.which_host_command("clamscan")
                assert result == "/usr/bin/clamscan"
                mock_which.assert_called_once_with("clamscan")

    def test_which_host_command_not_in_flatpak_not_found(self):
        """Test which_host_command returns None when binary not found."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("shutil.which", return_value=None):
                result = flatpak.which_host_command("nonexistent")
                assert result is None

    def test_which_host_command_in_flatpak_found(self):
        """Test which_host_command uses flatpak-spawn when in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            mock_result = mock.Mock()
            mock_result.returncode = 0
            mock_result.stdout = "/usr/bin/clamscan\n"

            with mock.patch("subprocess.run", return_value=mock_result) as mock_run:
                result = flatpak.which_host_command("clamscan")
                assert result == "/usr/bin/clamscan"
                mock_run.assert_called_once_with(
                    ["flatpak-spawn", "--host", "which", "clamscan"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

    def test_which_host_command_in_flatpak_not_found(self):
        """Test which_host_command returns None when binary not found in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            mock_result = mock.Mock()
            mock_result.returncode = 1

            with mock.patch("subprocess.run", return_value=mock_result):
                result = flatpak.which_host_command("nonexistent")
                assert result is None

    def test_which_host_command_in_flatpak_timeout(self):
        """Test which_host_command handles timeout gracefully."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="which", timeout=5),
            ):
                result = flatpak.which_host_command("clamscan")
                assert result is None

    def test_which_host_command_in_flatpak_exception(self):
        """Test which_host_command handles exceptions gracefully."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch("subprocess.run", side_effect=Exception("Unexpected error")):
                result = flatpak.which_host_command("clamscan")
                assert result is None


class TestResolvePortalPathViaXattr:
    """Tests for _resolve_portal_path_via_xattr() function."""

    def test_resolve_portal_path_via_xattr_success(self):
        """Test _resolve_portal_path_via_xattr resolves path via xattr."""
        mock_xattr = mock.MagicMock()
        mock_xattr.getxattr.return_value = b"/home/user/Documents/file.txt\x00"

        with mock.patch.dict("sys.modules", {"xattr": mock_xattr}):
            result = flatpak._resolve_portal_path_via_xattr("/run/user/1000/doc/abc123/file.txt")
            assert result == "/home/user/Documents/file.txt"

    def test_resolve_portal_path_via_xattr_tries_multiple_attrs(self):
        """Test _resolve_portal_path_via_xattr tries multiple attribute names."""
        mock_xattr = mock.MagicMock()
        # First two attrs fail, third succeeds
        mock_xattr.getxattr.side_effect = [
            OSError(),
            KeyError(),
            b"/home/user/file.txt\x00",
        ]

        with mock.patch.dict("sys.modules", {"xattr": mock_xattr}):
            result = flatpak._resolve_portal_path_via_xattr("/run/user/1000/doc/abc123/file.txt")
            assert result == "/home/user/file.txt"

    def test_resolve_portal_path_via_xattr_not_found(self):
        """Test _resolve_portal_path_via_xattr returns None when attrs not found."""
        mock_xattr = mock.MagicMock()
        mock_xattr.getxattr.side_effect = OSError()

        with mock.patch.dict("sys.modules", {"xattr": mock_xattr}):
            result = flatpak._resolve_portal_path_via_xattr("/run/user/1000/doc/abc123/file.txt")
            assert result is None

    def test_resolve_portal_path_via_xattr_no_xattr_module(self):
        """Test _resolve_portal_path_via_xattr returns None when xattr not available."""
        with mock.patch.dict("sys.modules", {"xattr": None}):
            with mock.patch("builtins.__import__", side_effect=ImportError()):
                result = flatpak._resolve_portal_path_via_xattr(
                    "/run/user/1000/doc/abc123/file.txt"
                )
                assert result is None

    def test_resolve_portal_path_via_xattr_generic_exception(self):
        """Test _resolve_portal_path_via_xattr handles generic exceptions."""
        mock_xattr = mock.MagicMock()
        mock_xattr.getxattr.side_effect = Exception("Unexpected error")

        with mock.patch.dict("sys.modules", {"xattr": mock_xattr}):
            result = flatpak._resolve_portal_path_via_xattr("/run/user/1000/doc/abc123/file.txt")
            assert result is None


class TestResolvePortalPathViaGio:
    """Tests for _resolve_portal_path_via_gio() function."""

    def test_resolve_portal_path_via_gio_target_uri(self):
        """Test _resolve_portal_path_via_gio resolves via target-uri."""
        mock_gio = mock.MagicMock()
        mock_gfile = mock.MagicMock()
        mock_info = mock.MagicMock()
        mock_info.get_attribute_string.side_effect = lambda attr: (
            "file:///home/user/Documents/file.txt" if attr == "standard::target-uri" else None
        )

        mock_gio.File.new_for_path.return_value = mock_gfile
        mock_gfile.query_info.return_value = mock_info

        mock_gi_repository = mock.MagicMock()
        mock_gi_repository.Gio = mock_gio
        with mock.patch.dict("sys.modules", {"gi.repository": mock_gi_repository}):
            result = flatpak._resolve_portal_path_via_gio("/run/user/1000/doc/abc123/file.txt")
            assert result == "/home/user/Documents/file.txt"

    def test_resolve_portal_path_via_gio_symlink_target(self):
        """Test _resolve_portal_path_via_gio resolves via symlink-target."""
        mock_gio = mock.MagicMock()
        mock_gfile = mock.MagicMock()
        mock_info = mock.MagicMock()

        def get_attr(attr):
            if attr == "standard::target-uri":
                return None
            elif attr == "standard::symlink-target":
                return "/home/user/Documents/file.txt"
            return None

        mock_info.get_attribute_string.side_effect = get_attr
        mock_gio.File.new_for_path.return_value = mock_gfile
        mock_gfile.query_info.return_value = mock_info

        mock_gi_repository = mock.MagicMock()
        mock_gi_repository.Gio = mock_gio
        with mock.patch.dict("sys.modules", {"gi.repository": mock_gi_repository}):
            result = flatpak._resolve_portal_path_via_gio("/run/user/1000/doc/abc123/file.txt")
            assert result == "/home/user/Documents/file.txt"

    def test_resolve_portal_path_via_gio_skips_run_symlink(self):
        """Test _resolve_portal_path_via_gio skips symlinks starting with /run/."""
        mock_gio = mock.MagicMock()
        mock_gfile = mock.MagicMock()
        mock_info = mock.MagicMock()

        def get_attr(attr):
            if attr == "standard::target-uri":
                return None
            elif attr == "standard::symlink-target":
                return "/run/user/1000/doc/xyz789/file.txt"
            return None

        mock_info.get_attribute_string.side_effect = get_attr
        mock_gio.File.new_for_path.return_value = mock_gfile
        mock_gfile.query_info.return_value = mock_info

        mock_gi_repository = mock.MagicMock()
        mock_gi_repository.Gio = mock_gio
        with mock.patch.dict("sys.modules", {"gi.repository": mock_gi_repository}):
            result = flatpak._resolve_portal_path_via_gio("/run/user/1000/doc/abc123/file.txt")
            assert result is None

    def test_resolve_portal_path_via_gio_exception(self):
        """Test _resolve_portal_path_via_gio handles exceptions gracefully."""
        with mock.patch.dict("sys.modules", {"gi.repository": None}):
            with mock.patch("builtins.__import__", side_effect=ImportError()):
                result = flatpak._resolve_portal_path_via_gio("/run/user/1000/doc/abc123/file.txt")
                assert result is None


class TestResolvePortalPathViaDBus:
    """Tests for _resolve_portal_path_via_dbus() function."""

    def test_resolve_portal_path_via_dbus_success(self):
        """Test _resolve_portal_path_via_dbus resolves path via D-Bus."""
        mock_gio = mock.MagicMock()
        mock_glib = mock.MagicMock()
        mock_bus = mock.MagicMock()
        mock_result = mock.MagicMock()
        mock_result.unpack.return_value = (b"/home/user/Documents/file.txt\x00", {})

        mock_gio.bus_get_sync.return_value = mock_bus
        mock_bus.call_sync.return_value = mock_result

        mock_gi_repository = mock.MagicMock()
        mock_gi_repository.Gio = mock_gio
        mock_gi_repository.GLib = mock_glib
        with mock.patch.dict("sys.modules", {"gi.repository": mock_gi_repository}):
            result = flatpak._resolve_portal_path_via_dbus("/run/user/1000/doc/abc123/file.txt")
            assert result == "/home/user/Documents/file.txt"

    def test_resolve_portal_path_via_dbus_flatpak_doc(self):
        """Test _resolve_portal_path_via_dbus handles /run/flatpak/doc/ paths."""
        mock_gio = mock.MagicMock()
        mock_glib = mock.MagicMock()
        mock_bus = mock.MagicMock()
        mock_result = mock.MagicMock()
        mock_result.unpack.return_value = (b"/home/user/file.txt\x00", {})

        mock_gio.bus_get_sync.return_value = mock_bus
        mock_bus.call_sync.return_value = mock_result

        mock_gi_repository = mock.MagicMock()
        mock_gi_repository.Gio = mock_gio
        mock_gi_repository.GLib = mock_glib
        with mock.patch.dict("sys.modules", {"gi.repository": mock_gi_repository}):
            result = flatpak._resolve_portal_path_via_dbus("/run/flatpak/doc/def456/file.txt")
            assert result == "/home/user/file.txt"

    def test_resolve_portal_path_via_dbus_list_of_bytes(self):
        """Test _resolve_portal_path_via_dbus handles list of byte values."""
        mock_gio = mock.MagicMock()
        mock_glib = mock.MagicMock()
        mock_bus = mock.MagicMock()
        mock_result = mock.MagicMock()
        # Return as list of integers (byte values)
        path_bytes = [ord(c) for c in "/home/user/file.txt\x00"]
        mock_result.unpack.return_value = (path_bytes, {})

        mock_gio.bus_get_sync.return_value = mock_bus
        mock_bus.call_sync.return_value = mock_result

        mock_gi_repository = mock.MagicMock()
        mock_gi_repository.Gio = mock_gio
        mock_gi_repository.GLib = mock_glib
        with mock.patch.dict("sys.modules", {"gi.repository": mock_gi_repository}):
            result = flatpak._resolve_portal_path_via_dbus("/run/user/1000/doc/abc123/file.txt")
            assert result == "/home/user/file.txt"

    def test_resolve_portal_path_via_dbus_invalid_path(self):
        """Test _resolve_portal_path_via_dbus returns None for invalid paths."""
        result = flatpak._resolve_portal_path_via_dbus("/home/user/Documents/file.txt")
        assert result is None

        result = flatpak._resolve_portal_path_via_dbus("/run/user/1000/file.txt")
        assert result is None

    def test_resolve_portal_path_via_dbus_exception(self):
        """Test _resolve_portal_path_via_dbus handles exceptions gracefully."""
        with mock.patch.dict("sys.modules", {"gi.repository": None}):
            with mock.patch("builtins.__import__", side_effect=ImportError()):
                result = flatpak._resolve_portal_path_via_dbus("/run/user/1000/doc/abc123/file.txt")
                assert result is None


class TestFormatFlatpakPortalPath:
    """Tests for format_flatpak_portal_path() function."""

    def test_format_flatpak_portal_path_home_subdir_downloads(self):
        """Test format_flatpak_portal_path formats Downloads path."""
        result = flatpak.format_flatpak_portal_path("/run/user/1000/doc/abc123/Downloads/file.txt")
        assert result == "~/Downloads/file.txt"

    def test_format_flatpak_portal_path_home_subdir_documents(self):
        """Test format_flatpak_portal_path formats Documents path."""
        result = flatpak.format_flatpak_portal_path(
            "/run/user/1000/doc/def456/Documents/report.pdf"
        )
        assert result == "~/Documents/report.pdf"

    def test_format_flatpak_portal_path_home_username(self):
        """Test format_flatpak_portal_path formats home/username paths."""
        result = flatpak.format_flatpak_portal_path("/run/user/1000/doc/abc123/home/john/file.txt")
        assert result == "~/file.txt"

    def test_format_flatpak_portal_path_media(self):
        """Test format_flatpak_portal_path formats /media paths."""
        result = flatpak.format_flatpak_portal_path(
            "/run/user/1000/doc/abc123/media/data/nextcloud/file.txt"
        )
        assert result == "/media/data/nextcloud/file.txt"

    def test_format_flatpak_portal_path_mnt(self):
        """Test format_flatpak_portal_path formats /mnt paths."""
        result = flatpak.format_flatpak_portal_path("/run/flatpak/doc/def456/mnt/storage/file.txt")
        assert result == "/mnt/storage/file.txt"

    def test_format_flatpak_portal_path_flatpak_doc(self):
        """Test format_flatpak_portal_path handles /run/flatpak/doc/ paths."""
        # Patch resolution methods to prevent actual resolution attempts
        with mock.patch.object(flatpak, "_resolve_portal_path_via_xattr", return_value=None):
            with mock.patch.object(flatpak, "_resolve_portal_path_via_gio", return_value=None):
                with mock.patch.object(flatpak, "_resolve_portal_path_via_dbus", return_value=None):
                    result = flatpak.format_flatpak_portal_path(
                        "/run/flatpak/doc/def789/Downloads/file.txt"
                    )
                    assert result == "~/Downloads/file.txt"

    def test_format_flatpak_portal_path_non_portal_path(self):
        """Test format_flatpak_portal_path returns original path for non-portal paths."""
        original = "/home/user/Documents/file.txt"
        result = flatpak.format_flatpak_portal_path(original)
        assert result == original

    def test_format_flatpak_portal_path_with_dbus_resolution(self):
        """Test format_flatpak_portal_path uses D-Bus resolution as fallback."""
        # Mock resolution methods - D-Bus returns resolved path, others return None
        with mock.patch.object(flatpak, "_resolve_portal_path_via_xattr", return_value=None):
            with mock.patch.object(flatpak, "_resolve_portal_path_via_gio", return_value=None):
                with mock.patch.object(
                    flatpak,
                    "_resolve_portal_path_via_dbus",
                    return_value="/home/user/CustomFolder/file.txt",
                ):
                    with mock.patch("src.core.flatpak.Path.home", return_value=Path("/home/user")):
                        result = flatpak.format_flatpak_portal_path(
                            "/run/user/1000/doc/abc123/CustomFolder/file.txt"
                        )
                        assert result == "~/CustomFolder/file.txt"

    def test_format_flatpak_portal_path_fallback_to_portal_indicator(self):
        """Test format_flatpak_portal_path shows [Portal] when resolution fails."""
        with mock.patch.object(flatpak, "_resolve_portal_path_via_xattr", return_value=None):
            with mock.patch.object(flatpak, "_resolve_portal_path_via_gio", return_value=None):
                with mock.patch.object(flatpak, "_resolve_portal_path_via_dbus", return_value=None):
                    result = flatpak.format_flatpak_portal_path(
                        "/run/user/1000/doc/abc123/UnknownFolder/file.txt"
                    )
                    assert result == "[Portal] UnknownFolder/file.txt"

    def test_format_flatpak_portal_path_all_home_subdirs(self):
        """Test format_flatpak_portal_path handles all known home subdirs."""
        home_subdirs = [
            "Downloads",
            "Documents",
            "Desktop",
            "Pictures",
            "Videos",
            "Music",
            ".config",
            ".local",
            ".cache",
        ]

        for subdir in home_subdirs:
            result = flatpak.format_flatpak_portal_path(
                f"/run/user/1000/doc/abc123/{subdir}/file.txt"
            )
            assert result == f"~/{subdir}/file.txt"

    def test_format_flatpak_portal_path_all_abs_indicators(self):
        """Test format_flatpak_portal_path handles all absolute path indicators."""
        abs_indicators = ["media", "mnt", "run", "tmp", "opt", "var", "usr", "srv"]

        for indicator in abs_indicators:
            result = flatpak.format_flatpak_portal_path(
                f"/run/user/1000/doc/abc123/{indicator}/somepath/file.txt"
            )
            assert result == f"/{indicator}/somepath/file.txt"

    def test_format_flatpak_portal_path_resolved_absolute_path(self):
        """Test format_flatpak_portal_path handles resolved absolute paths."""
        with mock.patch.object(flatpak, "_resolve_portal_path_via_xattr", return_value=None):
            with mock.patch.object(flatpak, "_resolve_portal_path_via_gio", return_value=None):
                with mock.patch.object(
                    flatpak,
                    "_resolve_portal_path_via_dbus",
                    return_value="/opt/app/file.txt",
                ):
                    result = flatpak.format_flatpak_portal_path(
                        "/run/user/1000/doc/abc123/CustomFolder/file.txt"
                    )
                    assert result == "/opt/app/file.txt"

    def test_format_flatpak_portal_path_complex_nested_path(self):
        """Test format_flatpak_portal_path handles complex nested paths."""
        result = flatpak.format_flatpak_portal_path(
            "/run/user/1000/doc/abc123/Documents/Work/Projects/2024/report.pdf"
        )
        assert result == "~/Documents/Work/Projects/2024/report.pdf"


class TestGetXdgUserDir:
    """Tests for get_xdg_user_dir() function."""

    def test_get_xdg_user_dir_download(self):
        """Test get_xdg_user_dir returns Download path."""
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = "/home/user/Downloads\n"

        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("subprocess.run", return_value=mock_result) as mock_run:
                result = flatpak.get_xdg_user_dir("DOWNLOAD")
                assert result == "/home/user/Downloads"
                mock_run.assert_called_once_with(
                    ["xdg-user-dir", "DOWNLOAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

    def test_get_xdg_user_dir_documents(self):
        """Test get_xdg_user_dir returns Documents path."""
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = "/home/user/Dokumente\n"  # German locale

        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("subprocess.run", return_value=mock_result):
                result = flatpak.get_xdg_user_dir("DOCUMENTS")
                assert result == "/home/user/Dokumente"

    def test_get_xdg_user_dir_invalid_type(self):
        """Test get_xdg_user_dir returns None for invalid type."""
        result = flatpak.get_xdg_user_dir("INVALID_TYPE")
        assert result is None

    def test_get_xdg_user_dir_command_not_found(self):
        """Test get_xdg_user_dir returns None when command not found."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch(
                "subprocess.run",
                side_effect=FileNotFoundError("xdg-user-dir not found"),
            ):
                result = flatpak.get_xdg_user_dir("DOWNLOAD")
                assert result is None

    def test_get_xdg_user_dir_timeout(self):
        """Test get_xdg_user_dir returns None on timeout."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
                result = flatpak.get_xdg_user_dir("DOWNLOAD")
                assert result is None

    def test_get_xdg_user_dir_command_fails(self):
        """Test get_xdg_user_dir returns None when command fails."""
        mock_result = mock.Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("subprocess.run", return_value=mock_result):
                result = flatpak.get_xdg_user_dir("DOWNLOAD")
                assert result is None

    def test_get_xdg_user_dir_empty_output(self):
        """Test get_xdg_user_dir returns None for empty output."""
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("subprocess.run", return_value=mock_result):
                result = flatpak.get_xdg_user_dir("DOWNLOAD")
                assert result is None

    def test_get_xdg_user_dir_in_flatpak(self):
        """Test get_xdg_user_dir uses flatpak-spawn in Flatpak."""
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = "/home/user/Downloads\n"

        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch("subprocess.run", return_value=mock_result) as mock_run:
                result = flatpak.get_xdg_user_dir("DOWNLOAD")
                assert result == "/home/user/Downloads"
                mock_run.assert_called_once_with(
                    ["flatpak-spawn", "--host", "xdg-user-dir", "DOWNLOAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

    def test_get_xdg_user_dir_all_valid_types(self):
        """Test get_xdg_user_dir accepts all valid XDG types."""
        valid_types = [
            "DOWNLOAD",
            "DOCUMENTS",
            "DESKTOP",
            "MUSIC",
            "PICTURES",
            "VIDEOS",
            "TEMPLATES",
            "PUBLICSHARE",
        ]

        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = "/home/user/test\n"

        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("subprocess.run", return_value=mock_result):
                for dir_type in valid_types:
                    result = flatpak.get_xdg_user_dir(dir_type)
                    assert result == "/home/user/test"

    def test_get_xdg_user_dir_home_fallback_returns_none(self):
        """xdg-user-dir prints $HOME when the dir is unconfigured; treat as a miss.

        Regression: an unconfigured Downloads dir made xdg-user-dir return $HOME,
        which the Quick Scan default then adopted as its target -> scanning the
        entire home directory instead of ~/Downloads.
        """
        home = os.path.expanduser("~")
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = home + "\n"
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            with mock.patch("subprocess.run", return_value=mock_result):
                assert flatpak.get_xdg_user_dir("DOWNLOAD") is None


class TestIsPortalPath:
    """Tests for is_portal_path() function."""

    def test_user_doc_path(self):
        """Test detection of /run/user/<uid>/doc/ portal paths."""
        assert flatpak.is_portal_path("/run/user/1000/doc/751f8b64/scan.conf") is True

    def test_flatpak_doc_path(self):
        """Test detection of /run/flatpak/doc/ portal paths."""
        assert flatpak.is_portal_path("/run/flatpak/doc/abc123/file.conf") is True

    def test_non_portal_path(self):
        """Test that regular paths are not portal paths."""
        assert flatpak.is_portal_path("/etc/clamav/clamd.conf") is False

    def test_home_path(self):
        """Test that home paths are not portal paths."""
        assert flatpak.is_portal_path("/home/user/.config/clamui/settings.json") is False

    def test_partial_match(self):
        """Test that partial matches don't count."""
        assert flatpak.is_portal_path("/run/user/1000/something") is False

    def test_empty_string(self):
        """Test empty string."""
        assert flatpak.is_portal_path("") is False


class TestResolvePortalPath:
    """Tests for resolve_portal_path() function."""

    def test_non_portal_path_returns_none(self):
        """Test that non-portal paths return None immediately."""
        result = flatpak.resolve_portal_path("/etc/clamav/clamd.conf")
        assert result is None

    def test_tries_all_methods(self):
        """Test that all resolution methods are tried in order."""
        portal = "/run/user/1000/doc/abc123/scan.conf"

        with (
            mock.patch.object(flatpak, "_resolve_portal_path_via_xattr", return_value=None) as m1,
            mock.patch.object(flatpak, "_resolve_portal_path_via_gio", return_value=None) as m2,
            mock.patch.object(
                flatpak, "_resolve_portal_path_via_dbus", return_value="/etc/clamd.d/scan.conf"
            ) as m3,
        ):
            result = flatpak.resolve_portal_path(portal)
            assert result == "/etc/clamd.d/scan.conf"
            m1.assert_called_once_with(portal)
            m2.assert_called_once_with(portal)
            m3.assert_called_once_with(portal)

    def test_returns_first_successful_resolution(self):
        """Test that the first successful method wins."""
        portal = "/run/user/1000/doc/abc123/scan.conf"

        with (
            mock.patch.object(
                flatpak, "_resolve_portal_path_via_xattr", return_value="/etc/clamd.d/scan.conf"
            ),
            mock.patch.object(flatpak, "_resolve_portal_path_via_gio") as m2,
            mock.patch.object(flatpak, "_resolve_portal_path_via_dbus") as m3,
        ):
            result = flatpak.resolve_portal_path(portal)
            assert result == "/etc/clamd.d/scan.conf"
            m2.assert_not_called()
            m3.assert_not_called()

    def test_all_methods_fail(self):
        """Test that None is returned when all methods fail."""
        portal = "/run/user/1000/doc/abc123/scan.conf"

        with (
            mock.patch.object(flatpak, "_resolve_portal_path_via_xattr", return_value=None),
            mock.patch.object(flatpak, "_resolve_portal_path_via_gio", return_value=None),
            mock.patch.object(flatpak, "_resolve_portal_path_via_dbus", return_value=None),
        ):
            result = flatpak.resolve_portal_path(portal)
            assert result is None


class TestReadHostFile:
    """Tests for read_host_file() function."""

    def test_native_reads_file_directly(self, tmp_path):
        """Test that native mode reads files with normal I/O."""
        test_file = tmp_path / "test.conf"
        test_file.write_text("DatabaseDirectory /var/lib/clamav\n")

        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            content, error = flatpak.read_host_file(str(test_file))

        assert error is None
        assert content == "DatabaseDirectory /var/lib/clamav\n"

    def test_native_file_not_found(self):
        """Test native mode with non-existent file."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            content, error = flatpak.read_host_file("/nonexistent/file.conf")

        assert content is None
        assert "not found" in error.lower()

    def test_native_permission_denied(self, tmp_path):
        """Test native mode with unreadable file."""
        test_file = tmp_path / "secret.conf"
        test_file.write_text("secret")
        test_file.chmod(0o000)

        try:
            with mock.patch.object(flatpak, "is_flatpak", return_value=False):
                content, error = flatpak.read_host_file(str(test_file))

            assert content is None
            assert "permission" in error.lower()
        finally:
            test_file.chmod(0o644)

    def test_native_latin1_fallback(self, tmp_path):
        """Test that native mode falls back to latin-1 for non-UTF-8 files."""
        test_file = tmp_path / "latin.conf"
        test_file.write_bytes(b"# Comment with \xe9\n")

        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            content, error = flatpak.read_host_file(str(test_file))

        assert error is None
        assert content is not None

    def test_flatpak_uses_spawn(self):
        """Test that Flatpak mode uses flatpak-spawn --host cat."""
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = b"DatabaseDirectory /var/lib/clamav\n"

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            content, error = flatpak.read_host_file("/etc/clamd.d/scan.conf")

        assert error is None
        assert content == "DatabaseDirectory /var/lib/clamav\n"
        mock_run.assert_called_once_with(
            ["flatpak-spawn", "--host", "cat", "/etc/clamd.d/scan.conf"],
            capture_output=True,
            text=False,
            timeout=10,
        )

    def test_flatpak_spawn_failure(self):
        """Test Flatpak mode when flatpak-spawn returns an error."""
        mock_result = mock.Mock()
        mock_result.returncode = 1
        mock_result.stderr = b"cat: /etc/clamd.d/scan.conf: No such file or directory"

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result),
        ):
            content, error = flatpak.read_host_file("/etc/clamd.d/scan.conf")

        assert content is None
        assert "Cannot read" in error

    def test_flatpak_spawn_timeout(self):
        """Test Flatpak mode when flatpak-spawn times out."""
        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch(
                "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="cat", timeout=10)
            ),
        ):
            content, error = flatpak.read_host_file("/etc/clamd.d/scan.conf")

        assert content is None
        assert "timeout" in error.lower()

    def test_flatpak_utf8_decode(self):
        """Test that Flatpak mode decodes UTF-8 output correctly."""
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = "# Комментарий\n".encode()

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result),
        ):
            content, error = flatpak.read_host_file("/etc/clamav/clamd.conf")

        assert error is None
        assert "Комментарий" in content

    def test_flatpak_latin1_fallback(self):
        """Test that Flatpak mode falls back to latin-1 for non-UTF-8 output."""
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = b"# Comment with \xe9\n"

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result),
        ):
            content, error = flatpak.read_host_file("/etc/clamav/clamd.conf")

        assert error is None
        assert content is not None

    def test_custom_timeout(self):
        """Test that custom timeout is passed to subprocess."""
        mock_result = mock.Mock()
        mock_result.returncode = 0
        mock_result.stdout = b"content"

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            flatpak.read_host_file("/etc/test.conf", timeout=30)

        assert mock_run.call_args[1]["timeout"] == 30

    def test_flatpak_spawn_binary_not_found(self):
        """Test Flatpak mode when flatpak-spawn binary is missing from PATH."""
        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch("subprocess.run", side_effect=FileNotFoundError("flatpak-spawn")),
        ):
            content, error = flatpak.read_host_file("/etc/clamd.d/scan.conf")

        assert content is None
        assert "flatpak-spawn not available" in error

    def test_flatpak_spawn_unexpected_error(self):
        """Test Flatpak mode when subprocess raises an unexpected error."""
        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch("subprocess.run", side_effect=OSError("broken pipe")),
        ):
            content, error = flatpak.read_host_file("/etc/clamd.d/scan.conf")

        assert content is None
        assert "Error reading" in error
        assert "broken pipe" in error


class TestGetCleanEnv:
    """Tests for get_clean_env() function."""

    def test_strips_ld_library_path(self):
        """Test that LD_LIBRARY_PATH is removed from the environment."""
        with mock.patch.dict(
            os.environ,
            {"LD_LIBRARY_PATH": "/app/lib:/usr/lib", "HOME": "/home/user"},
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert "LD_LIBRARY_PATH" not in env

    def test_strips_ld_preload(self):
        """Test that LD_PRELOAD is removed from the environment."""
        with mock.patch.dict(
            os.environ,
            {"LD_PRELOAD": "/app/lib/libfoo.so", "HOME": "/home/user"},
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert "LD_PRELOAD" not in env

    def test_strips_appimage_vars(self):
        """Test that APPIMAGE* and APPDIR* variables are removed."""
        with mock.patch.dict(
            os.environ,
            {
                "APPIMAGE": "/path/to/ClamUI.AppImage",
                "APPIMAGE_EXTRACT_AND_RUN": "1",
                "APPDIR": "/tmp/appimage_mount",
                "APPDIR_SOME_OTHER": "/tmp/appdir_other",
                "HOME": "/home/user",
            },
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert "APPIMAGE" not in env
            assert "APPIMAGE_EXTRACT_AND_RUN" not in env
            assert "APPDIR" not in env
            assert "APPDIR_SOME_OTHER" not in env

    def test_preserves_normal_vars(self):
        """Test that normal environment variables like PATH and HOME are preserved."""
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/usr/bin:/usr/local/bin",
                "HOME": "/home/user",
                "LANG": "en_US.UTF-8",
                "XDG_DATA_HOME": "/home/user/.local/share",
            },
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert env["PATH"] == "/usr/bin:/usr/local/bin"
            assert env["HOME"] == "/home/user"
            assert env["LANG"] == "en_US.UTF-8"
            assert env["XDG_DATA_HOME"] == "/home/user/.local/share"

    def test_returns_copy_not_original(self):
        """Test that get_clean_env returns a copy, not the original os.environ."""
        env = flatpak.get_clean_env()
        assert env is not os.environ

    def test_no_appimage_vars_is_noop(self):
        """Test that calling without AppImage vars doesn't remove anything extra."""
        with mock.patch.dict(
            os.environ,
            {"PATH": "/usr/bin", "HOME": "/home/user"},
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert env == {"PATH": "/usr/bin", "HOME": "/home/user"}

    def test_strips_both_ld_vars_and_appimage_vars_together(self):
        """Test that all problematic variables are stripped in one call."""
        with mock.patch.dict(
            os.environ,
            {
                "LD_LIBRARY_PATH": "/app/lib",
                "LD_PRELOAD": "/app/lib/hook.so",
                "APPIMAGE": "/path/to/app.AppImage",
                "APPDIR": "/tmp/mount",
                "PATH": "/usr/bin",
                "HOME": "/home/user",
            },
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert "LD_LIBRARY_PATH" not in env
            assert "LD_PRELOAD" not in env
            assert "APPIMAGE" not in env
            assert "APPDIR" not in env
            assert env["PATH"] == "/usr/bin"
            assert env["HOME"] == "/home/user"

    def test_strips_pythonhome(self):
        """PYTHONHOME must be stripped so host Python scripts (e.g. firewall-cmd)
        bootstrap the host stdlib, not the AppImage's (GitHub issue #155)."""
        with mock.patch.dict(
            os.environ,
            {"PYTHONHOME": "/tmp/mount/usr", "HOME": "/home/user"},
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert "PYTHONHOME" not in env

    def test_strips_pythonpath(self):
        """PYTHONPATH must be stripped so host Python tools use host site-packages."""
        with mock.patch.dict(
            os.environ,
            {
                "PYTHONPATH": "/tmp/mount/usr/lib/python3.12/site-packages",
                "HOME": "/home/user",
            },
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert "PYTHONPATH" not in env

    def test_strips_pythondontwritebytecode(self):
        """PYTHONDONTWRITEBYTECODE is part of the AppImage Python env and is stripped."""
        with mock.patch.dict(
            os.environ,
            {"PYTHONDONTWRITEBYTECODE": "1", "HOME": "/home/user"},
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert "PYTHONDONTWRITEBYTECODE" not in env

    def test_strips_gi_typelib_path(self):
        """GI_TYPELIB_PATH must be stripped so host tools that ``import gi`` load
        host typelibs, not the AppImage's bundled ones (GitHub issue #155)."""
        with mock.patch.dict(
            os.environ,
            {
                "GI_TYPELIB_PATH": "/tmp/mount/usr/lib/girepository-1.0",
                "HOME": "/home/user",
            },
            clear=True,
        ):
            env = flatpak.get_clean_env()
            assert "GI_TYPELIB_PATH" not in env

    def test_strips_full_appimage_python_env(self):
        """Regression for issue #155: the full AppImage AppRun environment is
        sanitized of every var that breaks a host Python helper, while
        host-essential vars survive."""
        with mock.patch.dict(
            os.environ,
            {
                # AppImage-injected (must be stripped)
                "PYTHONHOME": "/tmp/mount/usr",
                "PYTHONPATH": "/tmp/mount/usr/lib/python3.12/site-packages",
                "PYTHONDONTWRITEBYTECODE": "1",
                "GI_TYPELIB_PATH": "/tmp/mount/usr/lib/girepository-1.0",
                "LD_LIBRARY_PATH": "/tmp/mount/usr/lib",
                "APPDIR": "/tmp/mount",
                # Host-essential (must survive)
                "PATH": "/usr/bin:/bin",
                "HOME": "/home/user",
                "LANG": "en_US.UTF-8",
            },
            clear=True,
        ):
            env = flatpak.get_clean_env()
            for stripped in (
                "PYTHONHOME",
                "PYTHONPATH",
                "PYTHONDONTWRITEBYTECODE",
                "GI_TYPELIB_PATH",
                "LD_LIBRARY_PATH",
                "APPDIR",
            ):
                assert stripped not in env, f"{stripped} should be stripped"
            assert env["PATH"] == "/usr/bin:/bin"
            assert env["HOME"] == "/home/user"
            assert env["LANG"] == "en_US.UTF-8"


class TestGetClamavDatabaseDir:
    """Tests for get_clamav_database_dir() function."""

    def setup_method(self):
        """Reset the module-level cache before each test."""
        flatpak._FLATPAK_DATABASE_DIR = None

    def test_returns_none_when_not_in_flatpak(self):
        """Test that None is returned when not running in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            result = flatpak.get_clamav_database_dir()
            assert result is None

    def test_returns_correct_path_with_xdg_data_home(self):
        """Test that the correct path is returned using XDG_DATA_HOME."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": "/home/user/.var/app/io.github.clamui/data"}
            ):
                result = flatpak.get_clamav_database_dir()
                assert result == Path("/home/user/.var/app/io.github.clamui/data/clamav")

    def test_returns_fallback_path_without_xdg_data_home(self):
        """Test fallback to ~/.local/share/clamav when XDG_DATA_HOME is unset."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch.dict(os.environ, {}, clear=False):
                # Ensure XDG_DATA_HOME is not set
                env_copy = os.environ.copy()
                env_copy.pop("XDG_DATA_HOME", None)
                with mock.patch.dict(os.environ, env_copy, clear=True):
                    with mock.patch.object(Path, "home", return_value=Path("/home/testuser")):
                        result = flatpak.get_clamav_database_dir()
                        assert result == Path("/home/testuser/.local/share/clamav")

    def test_caches_result(self):
        """Test that the result is cached after first call."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": "/home/user/.var/app/io.github.clamui/data"}
            ):
                result1 = flatpak.get_clamav_database_dir()
                result2 = flatpak.get_clamav_database_dir()
                assert result1 == result2
                assert result1 is result2  # Same cached object


class TestEnsureClamavDatabaseDir:
    """Tests for ensure_clamav_database_dir() function."""

    def setup_method(self):
        """Reset the module-level cache before each test."""
        flatpak._FLATPAK_DATABASE_DIR = None

    def test_returns_none_when_not_in_flatpak(self):
        """Test that None is returned when not running in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            result = flatpak.ensure_clamav_database_dir()
            assert result is None

    def test_creates_directory_when_missing(self, tmp_path):
        """Test that the database directory is created when it does not exist."""
        db_dir = tmp_path / "clamav"
        assert not db_dir.exists()

        with mock.patch.object(flatpak, "get_clamav_database_dir", return_value=db_dir):
            result = flatpak.ensure_clamav_database_dir()
            assert result == db_dir
            assert db_dir.exists()
            assert db_dir.is_dir()

    def test_returns_existing_directory(self, tmp_path):
        """Test that an existing directory is returned without error."""
        db_dir = tmp_path / "clamav"
        db_dir.mkdir()
        assert db_dir.exists()

        with mock.patch.object(flatpak, "get_clamav_database_dir", return_value=db_dir):
            result = flatpak.ensure_clamav_database_dir()
            assert result == db_dir

    def test_returns_none_on_creation_failure(self):
        """Test that None is returned when directory creation fails."""
        fake_dir = mock.MagicMock(spec=Path)
        fake_dir.mkdir.side_effect = PermissionError("Permission denied")

        with mock.patch.object(flatpak, "get_clamav_database_dir", return_value=fake_dir):
            result = flatpak.ensure_clamav_database_dir()
            assert result is None

    def test_creates_nested_directories(self, tmp_path):
        """Test that nested parent directories are created (parents=True)."""
        db_dir = tmp_path / "deep" / "nested" / "clamav"
        assert not db_dir.exists()

        with mock.patch.object(flatpak, "get_clamav_database_dir", return_value=db_dir):
            result = flatpak.ensure_clamav_database_dir()
            assert result == db_dir
            assert db_dir.exists()


class TestGetFreshclamConfigPath:
    """Tests for get_freshclam_config_path() function."""

    def test_returns_none_when_not_in_flatpak(self):
        """Test that None is returned when not running in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            result = flatpak.get_freshclam_config_path()
            assert result is None

    def test_returns_correct_path_with_xdg_config_home(self):
        """Test that the correct path is returned using XDG_CONFIG_HOME."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": "/home/user/.var/app/io.github.clamui/config"}
            ):
                result = flatpak.get_freshclam_config_path()
                assert result == Path(
                    "/home/user/.var/app/io.github.clamui/config/clamav/freshclam.conf"
                )

    def test_returns_fallback_path_without_xdg_config_home(self):
        """Test fallback to ~/.config/clamav/freshclam.conf when XDG_CONFIG_HOME is unset."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            env_copy = os.environ.copy()
            env_copy.pop("XDG_CONFIG_HOME", None)
            with mock.patch.dict(os.environ, env_copy, clear=True):
                with mock.patch.object(Path, "home", return_value=Path("/home/testuser")):
                    result = flatpak.get_freshclam_config_path()
                    assert result == Path("/home/testuser/.config/clamav/freshclam.conf")

    def test_returns_path_object(self):
        """Test that a Path object is returned, not a string."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=True):
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/config"}):
                result = flatpak.get_freshclam_config_path()
                assert isinstance(result, Path)


class TestEnsureFreshclamConfig:
    """Tests for ensure_freshclam_config() function."""

    def setup_method(self):
        """Reset the module-level cache before each test."""
        flatpak._FLATPAK_DATABASE_DIR = None

    def test_returns_none_when_not_in_flatpak(self):
        """Test that None is returned when not running in Flatpak."""
        with mock.patch.object(flatpak, "is_flatpak", return_value=False):
            result = flatpak.ensure_freshclam_config()
            assert result is None

    def test_creates_config_when_missing(self, tmp_path):
        """Test that a config file is created when it does not exist."""
        config_path = tmp_path / "clamav" / "freshclam.conf"
        db_dir = tmp_path / "data" / "clamav"

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch.object(flatpak, "get_freshclam_config_path", return_value=config_path),
            mock.patch.object(flatpak, "ensure_clamav_database_dir", return_value=db_dir),
        ):
            result = flatpak.ensure_freshclam_config()
            assert result == config_path
            assert config_path.exists()

    def test_config_contains_database_directory(self, tmp_path):
        """Test that the generated config contains the correct DatabaseDirectory."""
        config_path = tmp_path / "clamav" / "freshclam.conf"
        db_dir = tmp_path / "data" / "clamav"

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch.object(flatpak, "get_freshclam_config_path", return_value=config_path),
            mock.patch.object(flatpak, "ensure_clamav_database_dir", return_value=db_dir),
        ):
            flatpak.ensure_freshclam_config()
            content = config_path.read_text()
            assert f"DatabaseDirectory {db_dir}" in content

    def test_config_contains_database_mirror(self, tmp_path):
        """Test that the generated config contains the DatabaseMirror setting."""
        config_path = tmp_path / "clamav" / "freshclam.conf"
        db_dir = tmp_path / "data" / "clamav"

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch.object(flatpak, "get_freshclam_config_path", return_value=config_path),
            mock.patch.object(flatpak, "ensure_clamav_database_dir", return_value=db_dir),
        ):
            flatpak.ensure_freshclam_config()
            content = config_path.read_text()
            assert "DatabaseMirror database.clamav.net" in content

    def test_does_not_overwrite_existing_config(self, tmp_path):
        """Test that an existing config file is not overwritten."""
        config_path = tmp_path / "clamav" / "freshclam.conf"
        config_path.parent.mkdir(parents=True)
        original_content = "# Custom user config\nDatabaseDirectory /custom/path\n"
        config_path.write_text(original_content)

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch.object(flatpak, "get_freshclam_config_path", return_value=config_path),
        ):
            result = flatpak.ensure_freshclam_config()
            assert result == config_path
            # Content should not have been overwritten
            assert config_path.read_text() == original_content

    def test_returns_none_when_db_dir_fails(self):
        """Test that None is returned when ensure_clamav_database_dir fails."""
        config_path = mock.MagicMock(spec=Path)
        config_path.exists.return_value = False

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch.object(flatpak, "get_freshclam_config_path", return_value=config_path),
            mock.patch.object(flatpak, "ensure_clamav_database_dir", return_value=None),
        ):
            result = flatpak.ensure_freshclam_config()
            assert result is None

    def test_returns_none_when_config_path_is_none(self):
        """Test that None is returned when get_freshclam_config_path returns None."""
        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch.object(flatpak, "get_freshclam_config_path", return_value=None),
        ):
            result = flatpak.ensure_freshclam_config()
            assert result is None

    def test_returns_none_on_write_failure(self, tmp_path):
        """Test that None is returned when writing the config file fails."""
        config_path = mock.MagicMock(spec=Path)
        config_path.exists.return_value = False
        config_path.parent = tmp_path
        config_path.write_text.side_effect = PermissionError("Permission denied")

        db_dir = tmp_path / "data" / "clamav"

        with (
            mock.patch.object(flatpak, "is_flatpak", return_value=True),
            mock.patch.object(flatpak, "get_freshclam_config_path", return_value=config_path),
            mock.patch.object(flatpak, "ensure_clamav_database_dir", return_value=db_dir),
        ):
            result = flatpak.ensure_freshclam_config()
            assert result is None
