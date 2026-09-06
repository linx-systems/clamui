# ClamUI ClamAV Detection Tests
"""Unit tests for the clamav_detection module functions."""

import re
import subprocess
from unittest import mock

from src.core import clamav_detection


class TestCheckClamavInstalled:
    """Tests for check_clamav_installed() function."""

    def test_check_clamav_installed_found_and_working(self):
        """Test check_clamav_installed returns (True, version) when installed."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="ClamAV 1.2.3/27421/Mon Dec 30 09:00:00 2024\n",
                    stderr="",
                )
                installed, version = clamav_detection.check_clamav_installed()
                assert installed is True
                assert "ClamAV" in version

    def test_check_clamav_not_installed(self):
        """Test check_clamav_installed returns (False, message) when not installed."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            installed, message = clamav_detection.check_clamav_installed()
            assert installed is False
            assert "not installed" in message.lower()

    def test_check_clamav_timeout(self):
        """Test check_clamav_installed handles timeout gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired(cmd="clamscan", timeout=10)
                installed, message = clamav_detection.check_clamav_installed()
                assert installed is False
                assert "timed out" in message.lower()

    def test_check_clamav_permission_denied(self):
        """Test check_clamav_installed handles permission errors gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = PermissionError("Permission denied")
                installed, message = clamav_detection.check_clamav_installed()
                assert installed is False
                assert "permission denied" in message.lower()

    def test_check_clamav_file_not_found(self):
        """Test check_clamav_installed handles FileNotFoundError gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError("File not found")
                installed, message = clamav_detection.check_clamav_installed()
                assert installed is False
                assert "not found" in message.lower()

    def test_check_clamav_returns_error(self):
        """Test check_clamav_installed when command returns non-zero exit code."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=1,
                    stdout="",
                    stderr="Some error occurred",
                )
                installed, message = clamav_detection.check_clamav_installed()
                assert installed is False
                assert "error" in message.lower()

    def test_check_clamav_generic_exception(self):
        """Test check_clamav_installed handles generic exceptions gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = Exception("Unexpected error")
                installed, message = clamav_detection.check_clamav_installed()
                assert installed is False
                assert "error" in message.lower()

    def test_check_clamav_uses_wrap_host_command(self):
        """Test check_clamav_installed uses wrap_host_command for Flatpak support."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ):
            with mock.patch.object(
                clamav_detection,
                "wrap_host_command",
                return_value=["clamscan", "--version"],
            ) as mock_wrap:
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=0,
                        stdout="ClamAV 1.2.3\n",
                        stderr="",
                    )
                    clamav_detection.check_clamav_installed()
                    mock_wrap.assert_called_once_with(["clamscan", "--version"])


class TestCheckFreshclamInstalled:
    """Tests for check_freshclam_installed() function."""

    def test_check_freshclam_installed_found_and_working(self):
        """Test check_freshclam_installed returns (True, version) when installed."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="ClamAV 1.2.3/27421/Mon Dec 30 09:00:00 2024\n",
                    stderr="",
                )
                installed, version = clamav_detection.check_freshclam_installed()
                assert installed is True
                assert "ClamAV" in version

    def test_check_freshclam_not_installed(self):
        """Test check_freshclam_installed returns (False, message) when not installed."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            installed, message = clamav_detection.check_freshclam_installed()
            assert installed is False
            assert "not installed" in message.lower()

    def test_check_freshclam_timeout(self):
        """Test check_freshclam_installed handles timeout gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired(cmd="freshclam", timeout=10)
                installed, message = clamav_detection.check_freshclam_installed()
                assert installed is False
                assert "timed out" in message.lower()

    def test_check_freshclam_permission_denied(self):
        """Test check_freshclam_installed handles permission errors gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = PermissionError("Permission denied")
                installed, message = clamav_detection.check_freshclam_installed()
                assert installed is False
                assert "permission denied" in message.lower()

    def test_check_freshclam_file_not_found(self):
        """Test check_freshclam_installed handles FileNotFoundError gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError("File not found")
                installed, message = clamav_detection.check_freshclam_installed()
                assert installed is False
                assert "not found" in message.lower()

    def test_check_freshclam_returns_error(self):
        """Test check_freshclam_installed when command returns non-zero exit code."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=1,
                    stdout="",
                    stderr="Some error occurred",
                )
                installed, message = clamav_detection.check_freshclam_installed()
                assert installed is False
                assert "error" in message.lower()

    def test_check_freshclam_generic_exception(self):
        """Test check_freshclam_installed handles generic exceptions gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = Exception("Unexpected error")
                installed, message = clamav_detection.check_freshclam_installed()
                assert installed is False
                assert "error" in message.lower()

    def test_check_freshclam_uses_config_neutral_host_command(self):
        """The version probe must not read Fedora's root-only freshclam.conf."""
        native_command = ["/usr/bin/freshclam", "--version", "--config-file=/dev/null"]
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ):
            with mock.patch.object(
                clamav_detection,
                "wrap_host_command",
                return_value=native_command,
            ) as mock_wrap:
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=0,
                        stdout="ClamAV 1.2.3\n",
                        stderr="",
                    )
                    clamav_detection.check_freshclam_installed()

        mock_wrap.assert_called_once_with(native_command)

    def test_check_freshclam_flatpak_uses_config_neutral_host_probe_for_fedora(self):
        """Fedora's root-only config must not make the Flatpak host probe fail."""
        native_command = ["/usr/bin/freshclam", "--version", "--config-file=/dev/null"]
        host_command = ["flatpak-spawn", "--host", *native_command]
        clean_env = {"PATH": "/usr/bin"}
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ):
            with mock.patch("src.core.flatpak.is_flatpak", return_value=True):
                with mock.patch.object(
                    clamav_detection,
                    "wrap_host_command",
                    wraps=clamav_detection.wrap_host_command,
                ) as mock_wrap:
                    with mock.patch.object(
                        clamav_detection, "get_clean_env", return_value=clean_env
                    ):
                        with mock.patch("subprocess.run") as mock_run:
                            mock_run.return_value = mock.Mock(
                                returncode=0,
                                stdout="ClamAV 1.2.3\n",
                                stderr="",
                            )
                            installed, version = clamav_detection.check_freshclam_installed()

        assert installed is True
        assert version == "ClamAV 1.2.3"
        mock_wrap.assert_called_once_with(native_command)
        mock_run.assert_called_once_with(
            host_command,
            capture_output=True,
            text=True,
            timeout=10,
            env=clean_env,
        )


class TestCheckClamdscanInstalled:
    """Tests for check_clamdscan_installed() function."""

    def test_check_clamdscan_installed_found_via_which(self):
        """Test check_clamdscan_installed returns (True, version) when found via which."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamdscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="ClamAV 1.2.3/27421/Mon Dec 30 09:00:00 2024\n",
                    stderr="",
                )
                installed, version = clamav_detection.check_clamdscan_installed()
                assert installed is True
                assert "ClamAV" in version

    def test_check_clamdscan_not_installed_which_fails(self):
        """Test check_clamdscan_installed when which returns None and fallback fails."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            with mock.patch("subprocess.run") as mock_run:
                # All fallback paths fail
                mock_run.side_effect = FileNotFoundError("not found")
                installed, message = clamav_detection.check_clamdscan_installed()
                assert installed is False
                assert "not installed" in message.lower()

    def test_check_clamdscan_timeout(self):
        """Test check_clamdscan_installed handles timeout gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamdscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired(cmd="clamdscan", timeout=10)
                installed, message = clamav_detection.check_clamdscan_installed()
                assert installed is False
                assert "timed out" in message.lower()

    def test_check_clamdscan_permission_denied(self):
        """Test check_clamdscan_installed handles permission errors gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamdscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = PermissionError("Permission denied")
                installed, message = clamav_detection.check_clamdscan_installed()
                assert installed is False
                assert "permission denied" in message.lower()

    def test_check_clamdscan_file_not_found_after_which(self):
        """Test check_clamdscan_installed handles FileNotFoundError after which succeeds."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamdscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError("File not found")
                installed, message = clamav_detection.check_clamdscan_installed()
                assert installed is False
                assert "not installed" in message.lower()

    def test_check_clamdscan_returns_error(self):
        """Test check_clamdscan_installed when command returns non-zero exit code."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamdscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=1,
                    stdout="",
                    stderr="Some error occurred",
                )
                installed, message = clamav_detection.check_clamdscan_installed()
                assert installed is False
                assert "error" in message.lower()

    def test_check_clamdscan_generic_exception(self):
        """Test check_clamdscan_installed handles generic exceptions gracefully."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamdscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = Exception("Unexpected error")
                installed, message = clamav_detection.check_clamdscan_installed()
                assert installed is False
                assert "error" in message.lower()

    def test_check_clamdscan_returns_not_installed_when_which_fails(self):
        """Test check_clamdscan_installed returns not installed when which returns None."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            installed, message = clamav_detection.check_clamdscan_installed()
            assert installed is False
            assert "not installed" in message.lower()

    def test_check_clamdscan_uses_wrap_host_command_with_force_host(self):
        """Test check_clamdscan_installed uses wrap_host_command with force_host=True."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamdscan"
        ):
            with mock.patch.object(
                clamav_detection,
                "wrap_host_command",
                return_value=["clamdscan", "--version"],
            ) as mock_wrap:
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=0,
                        stdout="ClamAV 1.2.3\n",
                        stderr="",
                    )
                    clamav_detection.check_clamdscan_installed()
                    # Uses force_host=True because clamdscan must talk to HOST's daemon
                    mock_wrap.assert_called_once_with(["clamdscan", "--version"], force_host=True)


class TestGetClamdSocketPath:
    """Tests for get_clamd_socket_path() function."""

    def test_get_clamd_socket_path_ubuntu_default(self):
        """Test get_clamd_socket_path returns Ubuntu/Debian default path."""
        with mock.patch("os.path.exists") as mock_exists:

            def exists_check(path):
                return path == "/var/run/clamav/clamd.ctl"

            mock_exists.side_effect = exists_check
            socket_path = clamav_detection.get_clamd_socket_path()
            assert socket_path == "/var/run/clamav/clamd.ctl"

    def test_get_clamd_socket_path_alternative_location(self):
        """Test get_clamd_socket_path returns alternative location."""
        with mock.patch("os.path.exists") as mock_exists:

            def exists_check(path):
                return path == "/run/clamav/clamd.ctl"

            mock_exists.side_effect = exists_check
            socket_path = clamav_detection.get_clamd_socket_path()
            assert socket_path == "/run/clamav/clamd.ctl"

    def test_get_clamd_socket_path_fedora_location(self):
        """Test get_clamd_socket_path returns Fedora location."""
        with mock.patch("os.path.exists") as mock_exists:

            def exists_check(path):
                return path == "/var/run/clamd.scan/clamd.sock"

            mock_exists.side_effect = exists_check
            socket_path = clamav_detection.get_clamd_socket_path()
            assert socket_path == "/var/run/clamd.scan/clamd.sock"

    def test_get_clamd_socket_path_fedora_run_location(self):
        """Test get_clamd_socket_path returns Fedora /run location."""
        with mock.patch("os.path.exists") as mock_exists:

            def exists_check(path):
                return path == "/run/clamd.scan/clamd.sock"

            mock_exists.side_effect = exists_check
            socket_path = clamav_detection.get_clamd_socket_path()
            assert socket_path == "/run/clamd.scan/clamd.sock"

    def test_get_clamd_socket_path_prefers_configured_local_socket(self):
        """Test get_clamd_socket_path reads LocalSocket from the provided config."""
        with mock.patch.object(
            clamav_detection,
            "_get_configured_clamd_socket_path",
            return_value="/custom/clamd.sock",
        ):
            with mock.patch(
                "os.path.exists", side_effect=lambda path: path == "/custom/clamd.sock"
            ):
                socket_path = clamav_detection.get_clamd_socket_path("/etc/clamd.d/scan.conf")
                assert socket_path == "/custom/clamd.sock"

    def test_get_clamd_socket_path_not_found(self):
        """Test get_clamd_socket_path returns None when socket not found."""
        with mock.patch("os.path.exists", return_value=False):
            socket_path = clamav_detection.get_clamd_socket_path()
            assert socket_path is None

    def test_get_clamd_socket_path_priority_order(self):
        """Test get_clamd_socket_path returns first found socket in priority order."""
        with mock.patch("os.path.exists") as mock_exists:
            # All sockets exist, should return first one
            mock_exists.return_value = True
            socket_path = clamav_detection.get_clamd_socket_path()
            # Should return the first one in the list
            assert socket_path == "/var/run/clamav/clamd.ctl"


class TestCheckClamdConnection:
    """Tests for check_clamd_connection() function."""

    def test_check_clamd_connection_clamdscan_not_installed(self):
        """Test check_clamd_connection fails when clamdscan not installed."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(False, "Not installed"),
        ):
            is_connected, message = clamav_detection.check_clamd_connection()
            assert is_connected is False
            assert "not installed" in message.lower()

    def test_check_clamd_connection_socket_not_found_not_flatpak(self):
        """Test check_clamd_connection fails when socket not found (not in Flatpak)."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection, "get_clamd_socket_path", return_value=None
                ):
                    is_connected, message = clamav_detection.check_clamd_connection()
                    assert is_connected is False
                    assert "socket" in message.lower()

    def test_check_clamd_connection_socket_provided(self):
        """Test check_clamd_connection uses provided socket path."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection,
                    "wrap_host_command",
                    return_value=["clamdscan", "--ping", "3"],
                ):
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = mock.Mock(
                            returncode=0,
                            stdout="PONG\n",
                            stderr="",
                        )
                        is_connected, message = clamav_detection.check_clamd_connection(
                            socket_path="/custom/socket.sock"
                        )
                        assert is_connected is True
                        assert message == "PONG"

    def test_check_clamd_connection_successful_pong(self):
        """Test check_clamd_connection returns (True, 'PONG') when daemon responds."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection,
                    "get_clamd_socket_path",
                    return_value="/var/run/clamav/clamd.ctl",
                ):
                    with mock.patch.object(
                        clamav_detection,
                        "wrap_host_command",
                        return_value=["clamdscan", "--ping", "3"],
                    ):
                        with mock.patch("subprocess.run") as mock_run:
                            mock_run.return_value = mock.Mock(
                                returncode=0,
                                stdout="PONG\n",
                                stderr="",
                            )
                            is_connected, message = clamav_detection.check_clamd_connection()
                            assert is_connected is True
                            assert message == "PONG"

    def test_check_clamd_connection_daemon_not_responding(self):
        """Test check_clamd_connection when daemon is not responding."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection,
                    "get_clamd_socket_path",
                    return_value="/var/run/clamav/clamd.ctl",
                ):
                    with mock.patch.object(
                        clamav_detection,
                        "wrap_host_command",
                        return_value=["clamdscan", "--ping", "3"],
                    ):
                        with mock.patch("subprocess.run") as mock_run:
                            mock_run.return_value = mock.Mock(
                                returncode=1,
                                stdout="",
                                stderr="Can't connect to clamd",
                            )
                            is_connected, message = clamav_detection.check_clamd_connection()
                            assert is_connected is False
                            assert "not responding" in message.lower()

    def test_check_clamd_connection_timeout(self):
        """Test check_clamd_connection handles timeout."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection,
                    "get_clamd_socket_path",
                    return_value="/var/run/clamav/clamd.ctl",
                ):
                    with mock.patch.object(
                        clamav_detection,
                        "wrap_host_command",
                        return_value=["clamdscan", "--ping", "3"],
                    ):
                        with mock.patch("subprocess.run") as mock_run:
                            mock_run.side_effect = subprocess.TimeoutExpired(
                                cmd="clamdscan", timeout=10
                            )
                            is_connected, message = clamav_detection.check_clamd_connection()
                            assert is_connected is False
                            assert "timed out" in message.lower()

    def test_check_clamd_connection_file_not_found(self):
        """Test check_clamd_connection handles FileNotFoundError."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection,
                    "get_clamd_socket_path",
                    return_value="/var/run/clamav/clamd.ctl",
                ):
                    with mock.patch.object(
                        clamav_detection,
                        "wrap_host_command",
                        return_value=["clamdscan", "--ping", "3"],
                    ):
                        with mock.patch("subprocess.run") as mock_run:
                            mock_run.side_effect = FileNotFoundError("File not found")
                            is_connected, message = clamav_detection.check_clamd_connection()
                            assert is_connected is False
                            assert "not found" in message.lower()

    def test_check_clamd_connection_generic_exception(self):
        """Test check_clamd_connection handles generic exceptions."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection,
                    "get_clamd_socket_path",
                    return_value="/var/run/clamav/clamd.ctl",
                ):
                    with mock.patch.object(
                        clamav_detection,
                        "wrap_host_command",
                        return_value=["clamdscan", "--ping", "3"],
                    ):
                        with mock.patch("subprocess.run") as mock_run:
                            mock_run.side_effect = Exception("Unexpected error")
                            is_connected, message = clamav_detection.check_clamd_connection()
                            assert is_connected is False
                            assert "error" in message.lower()

    def test_check_clamd_connection_in_flatpak(self):
        """Test check_clamd_connection skips socket check in Flatpak."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
                with mock.patch.object(
                    clamav_detection,
                    "wrap_host_command",
                    return_value=["clamdscan", "--ping", "3"],
                ):
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = mock.Mock(
                            returncode=0,
                            stdout="PONG\n",
                            stderr="",
                        )
                        is_connected, message = clamav_detection.check_clamd_connection()
                        assert is_connected is True
                        assert message == "PONG"

    def test_check_clamd_connection_uses_fedora_config_file_when_socket_matches(self):
        """Test Fedora socket probes use the detected scan.conf."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection,
                    "get_clamd_socket_path",
                    return_value="/run/clamd.scan/clamd.sock",
                ):
                    with mock.patch.object(
                        clamav_detection,
                        "detect_clamd_conf_path",
                        return_value="/etc/clamd.d/scan.conf",
                    ):
                        with mock.patch.object(
                            clamav_detection,
                            "wrap_host_command",
                            return_value=[
                                "clamdscan",
                                "--config-file",
                                "/etc/clamd.d/scan.conf",
                                "--ping",
                                "3",
                            ],
                        ) as mock_wrap:
                            with mock.patch("subprocess.run") as mock_run:
                                mock_run.return_value = mock.Mock(
                                    returncode=0,
                                    stdout="PONG\n",
                                    stderr="",
                                )
                                is_connected, message = clamav_detection.check_clamd_connection()
                                assert is_connected is True
                                assert message == "PONG"
                                mock_wrap.assert_called_once_with(
                                    [
                                        "clamdscan",
                                        "--config-file",
                                        "/etc/clamd.d/scan.conf",
                                        "--ping",
                                        "3",
                                    ],
                                    force_host=True,
                                )

    def test_check_clamd_connection_permission_denied_mentions_socket_permissions(self):
        """Test permission errors mention LocalSocket permissions when config is known."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
                with mock.patch.object(
                    clamav_detection,
                    "wrap_host_command",
                    return_value=[
                        "clamdscan",
                        "--config-file",
                        "/etc/clamd.d/scan.conf",
                        "--ping",
                        "3",
                    ],
                ):
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = mock.Mock(
                            returncode=2,
                            stdout="",
                            stderr="/run/clamd.scan/clamd.sock: Permission denied",
                        )
                        is_connected, message = clamav_detection.check_clamd_connection(
                            config_path="/etc/clamd.d/scan.conf",
                            socket_path="/run/clamd.scan/clamd.sock",
                        )
                        assert is_connected is False
                        assert "localsocketgroup" in message.lower()
                        assert "/etc/clamd.d/scan.conf" in message

    def test_check_clamd_connection_uses_wrap_host_command_with_force_host(self):
        """Test check_clamd_connection uses wrap_host_command with force_host=True."""
        with mock.patch.object(
            clamav_detection,
            "check_clamdscan_installed",
            return_value=(True, "ClamAV 1.2.3"),
        ):
            with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
                with mock.patch.object(
                    clamav_detection,
                    "wrap_host_command",
                    return_value=["clamdscan", "--ping", "3"],
                ) as mock_wrap:
                    with mock.patch("subprocess.run") as mock_run:
                        mock_run.return_value = mock.Mock(
                            returncode=0,
                            stdout="PONG\n",
                            stderr="",
                        )
                        clamav_detection.check_clamd_connection()
                        # Uses force_host=True because daemon runs on HOST
                        mock_wrap.assert_called_once_with(
                            ["clamdscan", "--ping", "3"], force_host=True
                        )


class TestGetClamavPath:
    """Tests for get_clamav_path() function."""

    def test_get_clamav_path_found(self):
        """Test get_clamav_path returns path when clamscan is found."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ) as mock_which:
            path = clamav_detection.get_clamav_path()
            assert path == "/usr/bin/clamscan"
            mock_which.assert_called_once_with("clamscan")

    def test_get_clamav_path_not_found(self):
        """Test get_clamav_path returns None when clamscan is not found."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            path = clamav_detection.get_clamav_path()
            assert path is None

    def test_get_clamav_path_uses_which_host_command(self):
        """Test get_clamav_path uses which_host_command for Flatpak support."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamscan"
        ) as mock_which:
            clamav_detection.get_clamav_path()
            mock_which.assert_called_once_with("clamscan")


class TestGetFreshclamPath:
    """Tests for get_freshclam_path() function."""

    def test_get_freshclam_path_found(self):
        """Test get_freshclam_path returns path when freshclam is found."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ) as mock_which:
            path = clamav_detection.get_freshclam_path()
            assert path == "/usr/bin/freshclam"
            mock_which.assert_called_once_with("freshclam")

    def test_get_freshclam_path_not_found(self):
        """Test get_freshclam_path returns None when freshclam is not found."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            path = clamav_detection.get_freshclam_path()
            assert path is None

    def test_get_freshclam_path_uses_which_host_command(self):
        """Test get_freshclam_path uses which_host_command for Flatpak support."""
        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/freshclam"
        ) as mock_which:
            clamav_detection.get_freshclam_path()
            mock_which.assert_called_once_with("freshclam")


class TestCheckDatabaseAvailable:
    """Tests for check_database_available() function."""

    def test_check_database_available_with_cvd_file(self, tmp_path):
        """Test check_database_available returns True when .cvd file exists."""
        # Create a mock database file
        db_file = tmp_path / "main.cvd"
        db_file.write_text("mock database content")

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=tmp_path) as mock_path:
                # Make Path("/var/lib/clamav") return tmp_path
                mock_path.return_value = tmp_path
                is_available, error = clamav_detection.check_database_available()
                assert is_available is True
                assert error is None

    def test_check_database_available_with_cld_file(self, tmp_path):
        """Test check_database_available returns True when .cld file exists."""
        db_file = tmp_path / "daily.cld"
        db_file.write_text("mock database content")

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=tmp_path):
                is_available, error = clamav_detection.check_database_available()
                assert is_available is True
                assert error is None

    def test_check_database_available_with_cud_file(self, tmp_path):
        """Test check_database_available returns True when .cud file exists."""
        db_file = tmp_path / "bytecode.cud"
        db_file.write_text("mock database content")

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=tmp_path):
                is_available, error = clamav_detection.check_database_available()
                assert is_available is True
                assert error is None

    def test_check_database_available_empty_directory(self, tmp_path):
        """Test check_database_available returns False when directory is empty."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=tmp_path):
                is_available, error = clamav_detection.check_database_available()
                assert is_available is False
                assert "No virus database files found" in error

    def test_check_database_available_no_database_files(self, tmp_path):
        """Test check_database_available returns False when no .cvd/.cld/.cud files exist."""
        # Create some non-database files
        (tmp_path / "readme.txt").write_text("readme")
        (tmp_path / "config.conf").write_text("config")

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=tmp_path):
                is_available, error = clamav_detection.check_database_available()
                assert is_available is False
                assert "No virus database files found" in error

    def test_check_database_available_directory_not_exists(self, tmp_path):
        """Test check_database_available returns False when directory doesn't exist."""
        non_existent = tmp_path / "non_existent"

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=non_existent):
                is_available, error = clamav_detection.check_database_available()
                assert is_available is False
                assert "does not exist" in error

    def test_check_database_available_permission_error(self, tmp_path):
        """Test check_database_available handles permission errors."""
        # Create a mock Path object that raises PermissionError on iterdir()
        mock_path = mock.MagicMock()
        mock_path.exists.return_value = True
        mock_path.iterdir.side_effect = PermissionError("Access denied")

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=mock_path):
                is_available, error = clamav_detection.check_database_available()
                assert is_available is False
                assert "Permission denied" in error

    def test_check_database_available_oserror(self, tmp_path):
        """Test check_database_available handles OS errors."""
        # Create a mock Path object that raises OSError on iterdir()
        mock_path = mock.MagicMock()
        mock_path.exists.return_value = True
        mock_path.iterdir.side_effect = OSError("Disk error")

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=mock_path):
                is_available, error = clamav_detection.check_database_available()
                assert is_available is False
                assert "Error accessing database" in error

    def test_check_database_available_flatpak_with_host_database(self):
        """Test check_database_available in Flatpak checks host database dirs."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
            with mock.patch.object(
                clamav_detection, "_host_database_dirs_to_check", return_value=["/var/lib/clamav"]
            ):
                with mock.patch.object(
                    clamav_detection,
                    "_host_path_contains_database_file",
                    return_value=(True, None),
                ):
                    is_available, error = clamav_detection.check_database_available()
                    assert is_available is True
                    assert error is None

    def test_check_database_available_flatpak_no_host_database(self):
        """Test check_database_available in Flatpak when host databases are missing."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
            with mock.patch.object(
                clamav_detection, "_host_database_dirs_to_check", return_value=["/var/lib/clamav"]
            ):
                with mock.patch.object(
                    clamav_detection,
                    "_host_path_contains_database_file",
                    return_value=(False, "No virus database files found"),
                ):
                    is_available, error = clamav_detection.check_database_available()
                    assert is_available is False
                    assert "host ClamAV virus database" in error

    def test_check_database_available_case_insensitive_extension(self, tmp_path):
        """Test check_database_available handles uppercase extensions."""
        db_file = tmp_path / "main.CVD"
        db_file.write_text("mock database content")

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("src.core.clamav_detection.Path", return_value=tmp_path):
                is_available, error = clamav_detection.check_database_available()
                assert is_available is True
                assert error is None


class TestConfigFileExists:
    """Tests for config_file_exists() function."""

    def test_native_file_exists(self):
        """Test native mode checks os.path.isfile."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("os.path.isfile", return_value=True) as mock_isfile:
                assert clamav_detection.config_file_exists("/etc/clamav/clamd.conf") is True
                mock_isfile.assert_called_once_with("/etc/clamav/clamd.conf")

    def test_native_file_not_exists(self):
        """Test native mode returns False for missing files."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=False):
            with mock.patch("os.path.isfile", return_value=False):
                assert clamav_detection.config_file_exists("/etc/clamav/clamd.conf") is False

    def test_flatpak_file_exists(self):
        """Test Flatpak mode uses flatpak-spawn to check host."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0)
                assert clamav_detection.config_file_exists("/etc/clamav/clamd.conf") is True
                mock_run.assert_called_once_with(
                    ["flatpak-spawn", "--host", "test", "-f", "/etc/clamav/clamd.conf"],
                    capture_output=True,
                    timeout=5,
                )

    def test_flatpak_file_not_exists(self):
        """Test Flatpak mode returns False when host file missing."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=1)
                assert clamav_detection.config_file_exists("/etc/clamav/clamd.conf") is False

    def test_flatpak_subprocess_error(self):
        """Test Flatpak mode returns False on subprocess error."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
            with mock.patch("subprocess.run", side_effect=OSError("no such command")):
                assert clamav_detection.config_file_exists("/etc/clamav/clamd.conf") is False

    def test_flatpak_checks_fedora_path_on_host(self):
        """Test Flatpak mode checks Fedora path /etc/clamd.d/scan.conf via host."""
        with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0)
                assert clamav_detection.config_file_exists("/etc/clamd.d/scan.conf") is True
                mock_run.assert_called_once_with(
                    ["flatpak-spawn", "--host", "test", "-f", "/etc/clamd.d/scan.conf"],
                    capture_output=True,
                    timeout=5,
                )

    def test_flatpak_timeout_returns_false(self):
        """Test Flatpak mode returns False when flatpak-spawn times out."""
        import subprocess as _subprocess

        with mock.patch.object(clamav_detection, "is_flatpak", return_value=True):
            with mock.patch("subprocess.run", side_effect=_subprocess.TimeoutExpired("test", 5)):
                assert clamav_detection.config_file_exists("/etc/clamd.d/scan.conf") is False


class TestFlatpakConfigDetection:
    """Tests verifying Flatpak host-aware config detection for distro-specific paths.

    Regression tests for the bug where config_file_exists() correctly found
    clamd.conf on the host via flatpak-spawn, but the availability check in
    PreferencesWindow used Path.exists() which checked the sandbox filesystem.
    Fix: window.py now uses config_file_exists() for the availability check.
    """

    def test_detect_clamd_fedora_path_in_flatpak(self):
        """Test detect_clamd_conf_path finds Fedora config via flatpak-spawn."""

        def host_exists(p):
            # Simulate Fedora host: only /etc/clamd.d/scan.conf exists
            return p == "/etc/clamd.d/scan.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", side_effect=host_exists):
            result = clamav_detection.detect_clamd_conf_path()
            assert result == "/etc/clamd.d/scan.conf"

    def test_resolve_clamd_fedora_path_in_flatpak(self):
        """Test resolve_clamd_conf_path returns Fedora path in Flatpak."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = ""

        def host_exists(p):
            return p == "/etc/clamd.d/scan.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", side_effect=host_exists):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)
            assert result == "/etc/clamd.d/scan.conf"
            mock_sm.set.assert_called_with("clamd_conf_path", "/etc/clamd.d/scan.conf")

    def test_resolve_uses_config_file_exists_not_path_exists(self):
        """Test resolve checks existence via config_file_exists, not Path.exists.

        This is the core regression test: config_file_exists uses flatpak-spawn
        to check the HOST filesystem, while Path.exists checks the SANDBOX.
        """
        mock_sm = mock.Mock()
        mock_sm.get.return_value = "/etc/clamd.d/scan.conf"

        with mock.patch.object(
            clamav_detection, "config_file_exists", return_value=True
        ) as mock_check:
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)
            assert result == "/etc/clamd.d/scan.conf"
            # Verify config_file_exists was called (host-aware check)
            mock_check.assert_called_with("/etc/clamd.d/scan.conf")


class TestDetectClamdConfPath:
    """Tests for detect_clamd_conf_path() function."""

    def test_finds_debian_path(self):
        """Test detects Debian/Ubuntu path first."""
        with mock.patch.object(
            clamav_detection,
            "config_file_exists",
            side_effect=lambda p: p == "/etc/clamav/clamd.conf",
        ):
            assert clamav_detection.detect_clamd_conf_path() == "/etc/clamav/clamd.conf"

    def test_finds_fedora_path(self):
        """Test detects Fedora/RHEL path when Debian path missing."""

        def exists(p):
            return p == "/etc/clamd.d/scan.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", side_effect=exists):
            assert clamav_detection.detect_clamd_conf_path() == "/etc/clamd.d/scan.conf"

    def test_finds_generic_path(self):
        """Test detects generic /etc/clamd.conf when others missing."""

        def exists(p):
            return p == "/etc/clamd.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", side_effect=exists):
            assert clamav_detection.detect_clamd_conf_path() == "/etc/clamd.conf"

    def test_returns_none_when_not_found(self):
        """Test returns None when no config file found."""
        with mock.patch.object(clamav_detection, "config_file_exists", return_value=False):
            assert clamav_detection.detect_clamd_conf_path() is None

    def test_priority_order(self):
        """Test Debian path is preferred over Fedora when both exist."""
        with mock.patch.object(clamav_detection, "config_file_exists", return_value=True):
            assert clamav_detection.detect_clamd_conf_path() == "/etc/clamav/clamd.conf"


class TestDetectFreshclamConfPath:
    """Tests for detect_freshclam_conf_path() function."""

    def test_finds_debian_path(self):
        """Test detects Debian/Ubuntu path."""
        with mock.patch.object(
            clamav_detection,
            "config_file_exists",
            side_effect=lambda p: p == "/etc/clamav/freshclam.conf",
        ):
            assert clamav_detection.detect_freshclam_conf_path() == "/etc/clamav/freshclam.conf"

    def test_finds_fedora_path(self):
        """Test detects Fedora/RHEL path when Debian path missing."""

        def exists(p):
            return p == "/etc/freshclam.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", side_effect=exists):
            assert clamav_detection.detect_freshclam_conf_path() == "/etc/freshclam.conf"

    def test_returns_none_when_not_found(self):
        """Test returns None when no config file found."""
        with mock.patch.object(clamav_detection, "config_file_exists", return_value=False):
            assert clamav_detection.detect_freshclam_conf_path() is None


class TestResolveClamdConfPath:
    """Tests for resolve_clamd_conf_path() function."""

    def test_uses_saved_setting(self):
        """Test returns saved path when it exists on disk."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = "/custom/clamd.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", return_value=True):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)
            assert result == "/custom/clamd.conf"
            mock_sm.get.assert_called_once_with("clamd_conf_path", "")

    def test_clears_invalid_saved_path(self):
        """Test clears saved path that no longer exists and re-detects."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = "/gone/clamd.conf"

        def exists(p):
            return p != "/gone/clamd.conf" and p == "/etc/clamav/clamd.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", side_effect=exists):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)
            assert result == "/etc/clamav/clamd.conf"
            # Should have cleared the invalid path
            mock_sm.set.assert_any_call("clamd_conf_path", "")
            # Should have persisted the detected path
            mock_sm.set.assert_any_call("clamd_conf_path", "/etc/clamav/clamd.conf")

    def test_flatpak_migrates_legacy_sandbox_path_to_detected_host_path(self):
        """Test Flatpak replaces the old sandbox-local path with a host path."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = clamav_detection._LEGACY_FLATPAK_CLAMD_CONF_PATH

        with (
            mock.patch.object(clamav_detection, "is_flatpak", return_value=True),
            mock.patch.object(
                clamav_detection,
                "detect_clamd_conf_path",
                return_value="/etc/clamd.d/scan.conf",
            ) as detect,
            mock.patch.object(clamav_detection, "config_file_exists") as exists,
        ):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)

        assert result == "/etc/clamd.d/scan.conf"
        exists.assert_not_called()
        detect.assert_called_once_with()
        assert mock_sm.set.call_args_list == [
            mock.call("clamd_conf_path", ""),
            mock.call("clamd_conf_path", "/etc/clamd.d/scan.conf"),
        ]

    def test_flatpak_clears_legacy_sandbox_path_when_host_config_is_unknown(self):
        """Test Flatpak never returns the legacy path when host detection fails."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = clamav_detection._LEGACY_FLATPAK_CLAMD_CONF_PATH

        with (
            mock.patch.object(clamav_detection, "is_flatpak", return_value=True),
            mock.patch.object(clamav_detection, "detect_clamd_conf_path", return_value=None),
            mock.patch.object(clamav_detection, "config_file_exists") as exists,
        ):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)

        assert result is None
        exists.assert_not_called()
        mock_sm.set.assert_called_once_with("clamd_conf_path", "")

    def test_flatpak_uses_valid_custom_host_path(self):
        """Test Flatpak still honors an existing explicit custom host path."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = "/opt/clamav/custom-clamd.conf"

        with (
            mock.patch.object(clamav_detection, "is_flatpak", return_value=True),
            mock.patch.object(clamav_detection, "config_file_exists", return_value=True) as exists,
        ):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)

        assert result == "/opt/clamav/custom-clamd.conf"
        exists.assert_called_once_with("/opt/clamav/custom-clamd.conf")
        mock_sm.set.assert_not_called()

    def test_native_uses_existing_legacy_path(self):
        """Test the legacy path remains valid when it is a native user config."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = clamav_detection._LEGACY_FLATPAK_CLAMD_CONF_PATH

        with (
            mock.patch.object(clamav_detection, "is_flatpak", return_value=False),
            mock.patch.object(clamav_detection, "config_file_exists", return_value=True) as exists,
        ):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)

        assert result == clamav_detection._LEGACY_FLATPAK_CLAMD_CONF_PATH
        exists.assert_called_once_with(clamav_detection._LEGACY_FLATPAK_CLAMD_CONF_PATH)
        mock_sm.set.assert_not_called()

    def test_persists_detected_path(self):
        """Test newly detected path is persisted to settings."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = ""

        with mock.patch.object(
            clamav_detection, "detect_clamd_conf_path", return_value="/etc/clamav/clamd.conf"
        ):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)
            assert result == "/etc/clamav/clamd.conf"
            mock_sm.set.assert_called_once_with("clamd_conf_path", "/etc/clamav/clamd.conf")

    def test_works_without_settings_manager(self):
        """Test works when no settings_manager provided."""
        with mock.patch.object(
            clamav_detection, "detect_clamd_conf_path", return_value="/etc/clamd.d/scan.conf"
        ):
            result = clamav_detection.resolve_clamd_conf_path(None)
            assert result == "/etc/clamd.d/scan.conf"

    def test_returns_none_when_nothing_found(self):
        """Test returns None when no config found anywhere."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = ""

        with mock.patch.object(clamav_detection, "detect_clamd_conf_path", return_value=None):
            result = clamav_detection.resolve_clamd_conf_path(mock_sm)
            assert result is None


class TestResolveFreshclamConfPath:
    """Tests for resolve_freshclam_conf_path() function."""

    def test_uses_saved_setting(self):
        """Test returns saved path when it exists on disk."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = "/custom/freshclam.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", return_value=True):
            result = clamav_detection.resolve_freshclam_conf_path(mock_sm)
            assert result == "/custom/freshclam.conf"

    def test_clears_invalid_saved_path(self):
        """Test clears saved path that no longer exists."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = "/gone/freshclam.conf"

        def exists(p):
            return p != "/gone/freshclam.conf" and p == "/etc/clamav/freshclam.conf"

        with mock.patch.object(clamav_detection, "config_file_exists", side_effect=exists):
            result = clamav_detection.resolve_freshclam_conf_path(mock_sm)
            assert result == "/etc/clamav/freshclam.conf"
            mock_sm.set.assert_any_call("freshclam_conf_path", "")

    def test_persists_detected_path(self):
        """Test newly detected path is persisted to settings."""
        mock_sm = mock.Mock()
        mock_sm.get.return_value = ""

        with mock.patch.object(
            clamav_detection,
            "detect_freshclam_conf_path",
            return_value="/etc/freshclam.conf",
        ):
            result = clamav_detection.resolve_freshclam_conf_path(mock_sm)
            assert result == "/etc/freshclam.conf"
            mock_sm.set.assert_called_once_with("freshclam_conf_path", "/etc/freshclam.conf")

    def test_returns_none_when_nothing_found(self):
        """Test returns None when no config found."""
        with mock.patch.object(clamav_detection, "detect_freshclam_conf_path", return_value=None):
            result = clamav_detection.resolve_freshclam_conf_path(None)
            assert result is None


_PACKAGE_MANAGER_PATTERN = re.compile(r"\b(?:apt|apt-get|dnf|yum|pacman|zypper)\b")


def _assert_no_package_manager_command(message):
    """Fail when a user-facing message advertises any package manager command."""
    match = _PACKAGE_MANAGER_PATTERN.search(message.lower())
    assert match is None, f"unexpected package manager hint {match.group(0)!r} in: {message}"


def _assert_only_install_command(message, command):
    """Fail unless the message quotes exactly `command` and no other package manager."""
    assert command in message, f"expected {command!r} in: {message}"
    _assert_no_package_manager_command(message.replace(command, ""))


def _recommended_targets(mock_recommend):
    """Return the install targets the detection code asked the resolver about."""
    targets = []
    for call_args, call_kwargs in mock_recommend.call_args_list:
        targets.append(call_args[0] if call_args else call_kwargs["target"])
    return targets


class TestMissingToolInstallGuidance:
    """Regression tests for distro-aware install hints (issue #184).

    Missing-tool messages must quote the command that
    recommend_install_command() produced for the detected distro instead of
    hardcoding Debian's apt, and must stay useful - while naming no package
    manager at all - when the distro cannot be identified.

    The resolver is patched on clamav_detection itself, so the module is
    expected to import recommend_install_command (and InstallTarget) from
    src.core.install_commands.
    """

    def test_missing_clamscan_quotes_detected_arch_command(self):
        """Missing clamscan on Arch should suggest pacman, never apt."""
        from src.core.install_commands import InstallTarget

        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            with mock.patch.object(
                clamav_detection,
                "recommend_install_command",
                return_value="sudo pacman -S clamav",
            ) as mock_recommend:
                installed, message = clamav_detection.check_clamav_installed()

        assert installed is False
        assert "not installed" in message.lower()
        _assert_only_install_command(message, "sudo pacman -S clamav")
        assert _recommended_targets(mock_recommend) == [InstallTarget.CLAMAV]

    def test_missing_clamscan_unknown_distro_omits_install_command(self):
        """Unknown distros keep a useful clamscan message with no install command."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            with mock.patch.object(
                clamav_detection, "recommend_install_command", return_value=None
            ):
                installed, message = clamav_detection.check_clamav_installed()

        assert installed is False
        assert "clamav" in message.lower()
        assert "not installed" in message.lower()
        _assert_no_package_manager_command(message)

    def test_missing_freshclam_quotes_detected_arch_command(self):
        """Missing freshclam on Arch should suggest pacman, never apt."""
        from src.core.install_commands import InstallTarget

        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            with mock.patch.object(
                clamav_detection,
                "recommend_install_command",
                return_value="sudo pacman -S clamav",
            ) as mock_recommend:
                installed, message = clamav_detection.check_freshclam_installed()

        assert installed is False
        assert "not installed" in message.lower()
        _assert_only_install_command(message, "sudo pacman -S clamav")
        assert _recommended_targets(mock_recommend) == [InstallTarget.FRESHCLAM]

    def test_missing_freshclam_unknown_distro_omits_install_command(self):
        """Unknown distros keep a useful freshclam message with no install command."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            with mock.patch.object(
                clamav_detection, "recommend_install_command", return_value=None
            ):
                installed, message = clamav_detection.check_freshclam_installed()

        assert installed is False
        assert "freshclam" in message.lower()
        assert "not installed" in message.lower()
        _assert_no_package_manager_command(message)

    def test_missing_clamdscan_quotes_detected_arch_command(self):
        """Missing clamdscan on Arch should suggest pacman, never apt."""
        from src.core.install_commands import InstallTarget

        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            with mock.patch.object(
                clamav_detection,
                "recommend_install_command",
                return_value="sudo pacman -S clamav",
            ) as mock_recommend:
                installed, message = clamav_detection.check_clamdscan_installed()

        assert installed is False
        assert "not installed" in message.lower()
        _assert_only_install_command(message, "sudo pacman -S clamav")
        assert _recommended_targets(mock_recommend) == [InstallTarget.CLAMD]

    def test_missing_clamdscan_after_which_quotes_detected_arch_command(self):
        """The clamdscan FileNotFoundError fallback is distro aware too."""
        from src.core.install_commands import InstallTarget

        with mock.patch.object(
            clamav_detection, "which_host_command", return_value="/usr/bin/clamdscan"
        ):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError("File not found")
                with mock.patch.object(
                    clamav_detection,
                    "recommend_install_command",
                    return_value="sudo pacman -S clamav",
                ) as mock_recommend:
                    installed, message = clamav_detection.check_clamdscan_installed()

        assert installed is False
        assert "not installed" in message.lower()
        _assert_only_install_command(message, "sudo pacman -S clamav")
        assert _recommended_targets(mock_recommend) == [InstallTarget.CLAMD]

    def test_missing_clamdscan_unknown_distro_omits_install_command(self):
        """Unknown distros keep a useful clamdscan message with no install command."""
        with mock.patch.object(clamav_detection, "which_host_command", return_value=None):
            with mock.patch.object(
                clamav_detection, "recommend_install_command", return_value=None
            ):
                installed, message = clamav_detection.check_clamdscan_installed()

        assert installed is False
        assert "clamdscan" in message.lower()
        assert "not installed" in message.lower()
        _assert_no_package_manager_command(message)
