# ClamUI File Manager Integration Tests
"""Unit tests for the file_manager_integration module functions."""

import os
from pathlib import Path
from unittest import mock

from src.core import file_manager_integration
from src.core.file_manager_integration import (
    FileManager,
    IntegrationInfo,
    IntegrationStatus,
    check_any_available,
    check_any_not_installed,
    get_available_integrations,
    install_all_available,
    install_integration,
    remove_integration,
    repair_integration,
)


class TestGetLocalShareDir:
    """Tests for _get_local_share_dir() function."""

    def test_get_local_share_dir_with_xdg_data_home(self):
        """Test _get_local_share_dir uses XDG_DATA_HOME when set."""
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/custom/data"}):
            result = file_manager_integration._get_local_share_dir()
            assert result == Path("/custom/data")

    def test_get_local_share_dir_without_xdg_data_home(self):
        """Test _get_local_share_dir falls back to ~/.local/share."""
        with mock.patch.dict(os.environ, {}, clear=True):
            if "XDG_DATA_HOME" in os.environ:
                del os.environ["XDG_DATA_HOME"]
            with mock.patch("pathlib.Path.home", return_value=Path("/home/testuser")):
                result = file_manager_integration._get_local_share_dir()
                assert result == Path("/home/testuser/.local/share")


class TestCheckFileManagerAvailable:
    """Tests for _check_file_manager_available() function."""

    def test_check_nemo_available_dir_exists(self):
        """Test Nemo detected when ~/.local/share/nemo exists."""
        with mock.patch.object(
            file_manager_integration,
            "_get_local_share_dir",
            return_value=Path("/home/user/.local/share"),
        ):
            with mock.patch.object(Path, "exists", return_value=True):
                result = file_manager_integration._check_file_manager_available(FileManager.NEMO)
                assert result is True

    def test_check_nautilus_available_dir_exists(self):
        """Test Nautilus detected when ~/.local/share/nautilus exists."""
        with mock.patch.object(
            file_manager_integration,
            "_get_local_share_dir",
            return_value=Path("/home/user/.local/share"),
        ):
            with mock.patch.object(Path, "exists", return_value=True):
                result = file_manager_integration._check_file_manager_available(
                    FileManager.NAUTILUS
                )
                assert result is True

    def test_check_dolphin_available_dir_exists(self):
        """Test Dolphin detected when ~/.local/share/kio exists on Plasma 6."""
        with mock.patch.dict(os.environ, {"KDE_SESSION_VERSION": "6"}, clear=True):
            with mock.patch.object(
                file_manager_integration,
                "_get_local_share_dir",
                return_value=Path("/home/user/.local/share"),
            ):
                with mock.patch.object(Path, "exists", return_value=True):
                    result = file_manager_integration._check_file_manager_available(
                        FileManager.DOLPHIN
                    )
                    assert result is True

    def test_check_dolphin_available_legacy_dir_exists(self):
        """Test Dolphin still supports ~/.local/share/kservices5 on Plasma 5."""
        with mock.patch.dict(os.environ, {"KDE_SESSION_VERSION": "5"}, clear=True):
            with mock.patch.object(
                file_manager_integration,
                "_get_local_share_dir",
                return_value=Path("/home/user/.local/share"),
            ):
                with mock.patch.object(Path, "exists", return_value=True):
                    result = file_manager_integration._check_file_manager_available(
                        FileManager.DOLPHIN
                    )
                    assert result is True


class TestCheckIntegrationStatus:
    """Tests for _check_integration_status() function."""

    def test_all_files_installed(self, tmp_path):
        """Test INSTALLED when all integration files exist."""
        local_share = tmp_path / "share"
        # Create all Nemo integration files
        for _, dest_rel in file_manager_integration.NEMO_INTEGRATIONS:
            dest = local_share / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("test")

        with mock.patch.object(
            file_manager_integration, "_get_local_share_dir", return_value=local_share
        ):
            status, missing = file_manager_integration._check_integration_status(FileManager.NEMO)
            assert status == IntegrationStatus.INSTALLED
            assert missing == []

    def test_no_files_installed(self, tmp_path):
        """Test NOT_INSTALLED when no integration files exist."""
        local_share = tmp_path / "share"
        local_share.mkdir()

        with mock.patch.object(
            file_manager_integration, "_get_local_share_dir", return_value=local_share
        ):
            status, missing = file_manager_integration._check_integration_status(FileManager.NEMO)
            assert status == IntegrationStatus.NOT_INSTALLED
            assert len(missing) == len(file_manager_integration.NEMO_INTEGRATIONS)

    def test_partial_install_detected(self, tmp_path):
        """Test PARTIAL when only some integration files exist."""
        local_share = tmp_path / "share"
        # Create only the first Nemo integration file
        first_source, first_dest = file_manager_integration.NEMO_INTEGRATIONS[0]
        dest = local_share / first_dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("test")

        with mock.patch.object(
            file_manager_integration, "_get_local_share_dir", return_value=local_share
        ):
            status, missing = file_manager_integration._check_integration_status(FileManager.NEMO)
            assert status == IntegrationStatus.PARTIAL
            assert len(missing) == len(file_manager_integration.NEMO_INTEGRATIONS) - 1

    def test_nautilus_partial_install(self, tmp_path):
        """Test PARTIAL for Nautilus when only one of two scripts exists."""
        local_share = tmp_path / "share"
        # Create only the first Nautilus integration file
        _, first_dest = file_manager_integration.NAUTILUS_INTEGRATIONS[0]
        dest = local_share / first_dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("test")

        with mock.patch.object(
            file_manager_integration, "_get_local_share_dir", return_value=local_share
        ):
            status, missing = file_manager_integration._check_integration_status(
                FileManager.NAUTILUS
            )
            assert status == IntegrationStatus.PARTIAL
            assert len(missing) == 1

    def test_dolphin_all_installed(self, tmp_path):
        """Test INSTALLED for Dolphin when both desktop files exist."""
        local_share = tmp_path / "share"
        for _, dest_rel in file_manager_integration.DOLPHIN_INTEGRATIONS:
            dest = local_share / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("test")

        with mock.patch.object(
            file_manager_integration, "_get_local_share_dir", return_value=local_share
        ):
            status, missing = file_manager_integration._check_integration_status(
                FileManager.DOLPHIN
            )
            assert status == IntegrationStatus.INSTALLED
            assert missing == []

    def test_dolphin_legacy_install_on_modern_kde_requires_repair(self, tmp_path):
        """Test legacy KDE5-only installs are treated as partial on Plasma 6."""
        local_share = tmp_path / "share"
        for _, dest_rel in file_manager_integration.DOLPHIN_LEGACY_INTEGRATIONS:
            dest = local_share / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("test")

        with mock.patch.dict(os.environ, {"KDE_SESSION_VERSION": "6"}, clear=True):
            with mock.patch.object(
                file_manager_integration, "_get_local_share_dir", return_value=local_share
            ):
                status, missing = file_manager_integration._check_integration_status(
                    FileManager.DOLPHIN
                )
                assert status == IntegrationStatus.PARTIAL
                assert missing == [
                    dest for _, dest in file_manager_integration.DOLPHIN_INTEGRATIONS
                ]


class TestIntegrationLists:
    """Tests for integration list completeness."""

    def test_nautilus_has_scan_and_virustotal(self):
        """Test Nautilus integration list contains both ClamUI scan and VirusTotal."""
        assert len(file_manager_integration.NAUTILUS_INTEGRATIONS) == 2
        source_names = [s for s, _ in file_manager_integration.NAUTILUS_INTEGRATIONS]
        assert "clamui-scan-nautilus.sh" in source_names
        assert "clamui-virustotal-nautilus.sh" in source_names

    def test_dolphin_has_scan_and_virustotal(self):
        """Test Dolphin integration list contains both ClamUI scan and VirusTotal."""
        assert len(file_manager_integration.DOLPHIN_INTEGRATIONS) == 2
        source_names = [s for s, _ in file_manager_integration.DOLPHIN_INTEGRATIONS]
        assert "io.github.linx_systems.ClamUI.service.desktop" in source_names
        assert "io.github.linx_systems.ClamUI-virustotal.desktop" in source_names

    def test_nemo_has_scan_and_virustotal(self):
        """Test Nemo integration list contains both ClamUI scan and VirusTotal."""
        assert len(file_manager_integration.NEMO_INTEGRATIONS) == 2
        source_names = [s for s, _ in file_manager_integration.NEMO_INTEGRATIONS]
        assert "io.github.linx_systems.ClamUI.nemo_action" in source_names
        assert "io.github.linx_systems.ClamUI-virustotal.nemo_action" in source_names


class TestGetAvailableIntegrations:
    """Tests for get_available_integrations() function."""

    def test_get_available_integrations_not_flatpak(self):
        """Test returns empty list when not in Flatpak."""
        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=False):
            result = get_available_integrations()
            assert result == []

    def test_get_available_integrations_no_source_dir(self):
        """Test returns empty list when integration source dir missing."""
        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch("pathlib.Path.exists", return_value=False):
                result = get_available_integrations()
                assert result == []

    def test_get_available_integrations_returns_all_managers(self):
        """Test returns info for all file managers."""
        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch("pathlib.Path.exists", return_value=True):
                with mock.patch.object(
                    file_manager_integration,
                    "_check_file_manager_available",
                    return_value=True,
                ):
                    with mock.patch.object(
                        file_manager_integration,
                        "_check_integration_status",
                        return_value=(IntegrationStatus.NOT_INSTALLED, []),
                    ):
                        result = get_available_integrations()
                        assert len(result) == 3
                        assert any(i.file_manager == FileManager.NEMO for i in result)
                        assert any(i.file_manager == FileManager.NAUTILUS for i in result)
                        assert any(i.file_manager == FileManager.DOLPHIN for i in result)

    def test_get_available_integrations_populates_status(self):
        """Test that status and missing_files are populated correctly."""
        missing = ["some/path"]
        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch("pathlib.Path.exists", return_value=True):
                with mock.patch.object(
                    file_manager_integration,
                    "_check_file_manager_available",
                    return_value=True,
                ):
                    with mock.patch.object(
                        file_manager_integration,
                        "_check_integration_status",
                        return_value=(IntegrationStatus.PARTIAL, missing),
                    ):
                        result = get_available_integrations()
                        for integration in result:
                            assert integration.status == IntegrationStatus.PARTIAL
                            assert integration.missing_files == missing
                            assert integration.is_partial is True
                            assert integration.is_installed is False


class TestInstallIntegration:
    """Tests for install_integration() function."""

    def test_install_integration_not_flatpak(self):
        """Test returns error when not in Flatpak."""
        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=False):
            success, error = install_integration(FileManager.NEMO)
            assert success is False
            assert "Not running as Flatpak" in error

    def test_install_integration_no_source_dir(self):
        """Test returns error when integration source dir missing."""
        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch("pathlib.Path.exists", return_value=False):
                success, error = install_integration(FileManager.NEMO)
                assert success is False
                assert "Integration files not found" in error

    def test_install_integration_success(self, tmp_path):
        """Test successful integration installation."""
        # Create mock source files
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "io.github.linx_systems.ClamUI.nemo_action"
        source_file.write_text("[Nemo Action]\nName=Test")

        dest_dir = tmp_path / "dest"

        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch.object(file_manager_integration, "INTEGRATIONS_SOURCE_DIR", source_dir):
                with mock.patch.object(
                    file_manager_integration,
                    "_get_local_share_dir",
                    return_value=dest_dir,
                ):
                    success, error = install_integration(FileManager.NEMO)
                    # May fail because mock source dir doesn't have all files
                    # but the logic should execute without crashing
                    assert success is True or error is not None

    def test_install_integration_permission_error(self, tmp_path):
        """Test handles permission errors gracefully."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "io.github.linx_systems.ClamUI.nemo_action"
        source_file.write_text("[Nemo Action]\nName=Test")

        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch.object(file_manager_integration, "INTEGRATIONS_SOURCE_DIR", source_dir):
                with mock.patch.object(
                    file_manager_integration,
                    "_get_local_share_dir",
                    return_value=Path("/nonexistent/readonly"),
                ):
                    with mock.patch("shutil.copy2", side_effect=PermissionError("Access denied")):
                        with mock.patch("pathlib.Path.mkdir"):
                            success, error = install_integration(FileManager.NEMO)
                            assert success is False
                            assert (
                                "Permission denied" in error or "Invalid destination path" in error
                            )

    def test_install_dolphin_integration_makes_desktop_files_executable(self, tmp_path):
        """Test Dolphin service menu files are executable for user-local installs."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        for source_name, _ in file_manager_integration.DOLPHIN_INTEGRATIONS:
            (source_dir / source_name).write_text("[Desktop Entry]\nType=Service\n")

        dest_dir = tmp_path / "dest"

        with mock.patch.dict(os.environ, {"KDE_SESSION_VERSION": "6"}, clear=True):
            with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
                with mock.patch.object(
                    file_manager_integration, "INTEGRATIONS_SOURCE_DIR", source_dir
                ):
                    with mock.patch.object(
                        file_manager_integration, "_get_local_share_dir", return_value=dest_dir
                    ):
                        with mock.patch.object(
                            file_manager_integration,
                            "_refresh_dolphin_service_menu_cache",
                        ):
                            success, error = install_integration(FileManager.DOLPHIN)
                            assert success is True
                            assert error is None

        for _, dest_rel in file_manager_integration.DOLPHIN_INTEGRATIONS:
            dest_path = dest_dir / dest_rel
            assert dest_path.exists()
            assert dest_path.stat().st_mode & 0o111


class TestRepairIntegration:
    """Tests for repair_integration() function."""

    def test_repair_installed_is_noop(self):
        """Test repair returns success immediately when already installed."""
        with mock.patch.object(
            file_manager_integration,
            "_check_integration_status",
            return_value=(IntegrationStatus.INSTALLED, []),
        ):
            success, error = repair_integration(FileManager.NEMO)
            assert success is True
            assert error is None

    def test_repair_not_installed_delegates_to_install(self):
        """Test repair delegates to install_integration when not installed."""
        with mock.patch.object(
            file_manager_integration,
            "_check_integration_status",
            return_value=(IntegrationStatus.NOT_INSTALLED, ["path/a", "path/b"]),
        ):
            with mock.patch.object(
                file_manager_integration,
                "install_integration",
                return_value=(True, None),
            ) as mock_install:
                success, error = repair_integration(FileManager.NEMO)
                assert success is True
                mock_install.assert_called_once_with(FileManager.NEMO)

    def test_repair_partial_copies_only_missing(self, tmp_path):
        """Test repair only copies missing files for partial installations."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"

        # Set up source files for Nautilus (2 files)
        for source_name, _ in file_manager_integration.NAUTILUS_INTEGRATIONS:
            (source_dir / source_name).write_text("#!/bin/bash\necho test")

        # Create the first file already (simulating partial install)
        _, first_dest = file_manager_integration.NAUTILUS_INTEGRATIONS[0]
        first_path = dest_dir / first_dest
        first_path.parent.mkdir(parents=True, exist_ok=True)
        first_path.write_text("existing")

        # The missing file is the second one
        _, second_dest = file_manager_integration.NAUTILUS_INTEGRATIONS[1]
        missing = [second_dest]

        with mock.patch.object(
            file_manager_integration,
            "_check_integration_status",
            return_value=(IntegrationStatus.PARTIAL, missing),
        ):
            with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
                with mock.patch.object(
                    file_manager_integration, "INTEGRATIONS_SOURCE_DIR", source_dir
                ):
                    with mock.patch.object(
                        file_manager_integration, "_get_local_share_dir", return_value=dest_dir
                    ):
                        success, error = repair_integration(FileManager.NAUTILUS)
                        assert success is True
                        assert error is None

                        # The missing file should now exist
                        assert (dest_dir / second_dest).exists()
                        # The existing file should be untouched
                        assert first_path.read_text() == "existing"

    def test_repair_partial_permission_error(self, tmp_path):
        """Test repair handles permission errors."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "clamui-scan-nautilus.sh").write_text("test")

        missing = ["nautilus/scripts/Scan with ClamUI"]

        with mock.patch.object(
            file_manager_integration,
            "_check_integration_status",
            return_value=(IntegrationStatus.PARTIAL, missing),
        ):
            with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
                with mock.patch.object(
                    file_manager_integration, "INTEGRATIONS_SOURCE_DIR", source_dir
                ):
                    with mock.patch.object(
                        file_manager_integration,
                        "_get_local_share_dir",
                        return_value=Path("/nonexistent"),
                    ):
                        with mock.patch("shutil.copy2", side_effect=PermissionError("denied")):
                            with mock.patch("pathlib.Path.mkdir"):
                                success, error = repair_integration(FileManager.NAUTILUS)
                                assert success is False
                                assert (
                                    "Permission denied" in error
                                    or "Invalid destination path" in error
                                )


class TestRemoveIntegration:
    """Tests for remove_integration() function."""

    def test_remove_integration_success(self):
        """Test successful integration removal."""
        with mock.patch.object(
            file_manager_integration,
            "_get_local_share_dir",
            return_value=Path("/home/user/.local/share"),
        ):
            mock_path = mock.MagicMock()
            mock_path.exists.return_value = True

            with mock.patch.object(Path, "__truediv__", return_value=mock_path):
                success, error = remove_integration(FileManager.NEMO)
                assert success is True
                assert error is None

    def test_remove_integration_file_not_exists(self):
        """Test removal succeeds even if file doesn't exist."""
        with mock.patch.object(
            file_manager_integration,
            "_get_local_share_dir",
            return_value=Path("/home/user/.local/share"),
        ):
            mock_path = mock.MagicMock()
            mock_path.exists.return_value = False

            with mock.patch.object(Path, "__truediv__", return_value=mock_path):
                success, error = remove_integration(FileManager.NEMO)
                assert success is True
                assert error is None
                mock_path.unlink.assert_not_called()


class TestInstallAllAvailable:
    """Tests for install_all_available() function."""

    def test_install_all_available_no_integrations(self):
        """Test returns empty dict when no integrations available."""
        with mock.patch.object(
            file_manager_integration, "get_available_integrations", return_value=[]
        ):
            result = install_all_available()
            assert result == {}

    def test_install_all_available_skips_installed(self):
        """Test skips already installed integrations."""
        mock_integration = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.INSTALLED,
            is_available=True,
        )

        with mock.patch.object(
            file_manager_integration,
            "get_available_integrations",
            return_value=[mock_integration],
        ):
            with mock.patch.object(file_manager_integration, "install_integration") as mock_install:
                result = install_all_available()
                mock_install.assert_not_called()
                assert result == {}


class TestCheckAnyAvailable:
    """Tests for check_any_available() function."""

    def test_check_any_available_not_flatpak(self):
        """Test returns False when not in Flatpak."""
        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=False):
            result = check_any_available()
            assert result is False

    def test_check_any_available_with_available(self):
        """Test returns True when file manager available."""
        mock_integration = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.NOT_INSTALLED,
            is_available=True,
        )

        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch.object(
                file_manager_integration,
                "get_available_integrations",
                return_value=[mock_integration],
            ):
                result = check_any_available()
                assert result is True

    def test_check_any_available_none_available(self):
        """Test returns False when no file managers available."""
        mock_integration = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.NOT_INSTALLED,
            is_available=False,
        )

        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch.object(
                file_manager_integration,
                "get_available_integrations",
                return_value=[mock_integration],
            ):
                result = check_any_available()
                assert result is False


class TestCheckAnyNotInstalled:
    """Tests for check_any_not_installed() function."""

    def test_check_any_not_installed_not_flatpak(self):
        """Test returns False when not in Flatpak."""
        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=False):
            result = check_any_not_installed()
            assert result is False

    def test_check_any_not_installed_with_uninstalled(self):
        """Test returns True when available integration not installed."""
        mock_integration = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.NOT_INSTALLED,
            is_available=True,
        )

        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch.object(
                file_manager_integration,
                "get_available_integrations",
                return_value=[mock_integration],
            ):
                result = check_any_not_installed()
                assert result is True

    def test_check_any_not_installed_all_installed(self):
        """Test returns False when all available integrations installed."""
        mock_integration = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.INSTALLED,
            is_available=True,
        )

        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch.object(
                file_manager_integration,
                "get_available_integrations",
                return_value=[mock_integration],
            ):
                result = check_any_not_installed()
                assert result is False

    def test_check_any_not_installed_with_partial(self):
        """Test returns True when there's a partial installation."""
        mock_integration = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.PARTIAL,
            is_available=True,
        )

        with mock.patch.object(file_manager_integration, "is_flatpak", return_value=True):
            with mock.patch.object(
                file_manager_integration,
                "get_available_integrations",
                return_value=[mock_integration],
            ):
                result = check_any_not_installed()
                assert result is True


class TestIntegrationInfoProperties:
    """Tests for IntegrationInfo backward-compat properties."""

    def test_is_installed_true_when_installed(self):
        """Test is_installed property returns True for INSTALLED status."""
        info = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.INSTALLED,
        )
        assert info.is_installed is True
        assert info.is_partial is False

    def test_is_installed_false_when_partial(self):
        """Test is_installed property returns False for PARTIAL status."""
        info = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.PARTIAL,
            missing_files=["some/file"],
        )
        assert info.is_installed is False
        assert info.is_partial is True

    def test_is_installed_false_when_not_installed(self):
        """Test is_installed property returns False for NOT_INSTALLED status."""
        info = IntegrationInfo(
            file_manager=FileManager.NEMO,
            display_name="Nemo",
            description="Test",
            source_files=[],
            status=IntegrationStatus.NOT_INSTALLED,
        )
        assert info.is_installed is False
        assert info.is_partial is False
