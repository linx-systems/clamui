# ClamUI Flatpak Manifest Tests
"""
Tests for Flatpak manifest and configuration.

Tests cover:
- Manifest YAML validity
- App ID consistency
- Runtime and SDK versions
- Required permissions
- Build commands and sources
- Generated dependency files

These tests prevent Flatpak build failures.
"""

import json
from pathlib import Path

import pytest

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture
def yaml_parser():
    """Get YAML parser if available."""
    try:
        import yaml

        return yaml
    except ImportError:
        pytest.skip("PyYAML not installed")


class TestManifestValidity:
    """Tests for manifest YAML validity."""

    def test_manifest_exists(self):
        """Test that Flatpak manifest exists."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        assert manifest.exists(), "Flatpak manifest not found"

    def test_manifest_is_valid_yaml(self, yaml_parser):
        """Test manifest is valid YAML."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        content = manifest.read_text()

        # Should parse without error
        try:
            data = yaml_parser.safe_load(content)
            assert data is not None, "Manifest parsed to None"
        except yaml_parser.YAMLError as e:
            pytest.fail(f"Invalid YAML: {e}")

    def test_manifest_has_app_id(self, yaml_parser):
        """Test manifest has app-id field."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        assert "app-id" in data, "Missing app-id field"
        assert data["app-id"] == "io.github.linx_systems.ClamUI"


class TestAppIdConsistency:
    """Tests for App ID consistency across files."""

    def test_manifest_and_desktop_file_match(self, yaml_parser):
        """Test app-id matches desktop file name."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        desktop = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.desktop"

        data = yaml_parser.safe_load(manifest.read_text())
        app_id = data.get("app-id", "")

        assert desktop.exists(), "Desktop file not found in flathub/"
        assert app_id in desktop.name, "App ID doesn't match desktop file name"

    def test_desktop_file_exec_line(self):
        """Test desktop file Exec line is correct."""
        desktop = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.desktop"
        content = desktop.read_text()

        assert "Exec=clamui" in content, "Desktop Exec should be 'clamui'"


class TestRuntimeConfiguration:
    """Tests for runtime and SDK configuration."""

    def test_runtime_specified(self, yaml_parser):
        """Test runtime is specified."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        assert "runtime" in data, "Missing runtime field"
        assert "org.gnome." in data["runtime"], "Should use GNOME runtime"

    def test_runtime_version_specified(self, yaml_parser):
        """Test runtime-version is specified."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        assert "runtime-version" in data, "Missing runtime-version field"

    def test_sdk_specified(self, yaml_parser):
        """Test SDK is specified."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        assert "sdk" in data, "Missing sdk field"
        assert "org.gnome.Sdk" in data["sdk"], "Should use GNOME SDK"

    @pytest.mark.parametrize(
        "manifest_name",
        [
            "io.github.linx_systems.ClamUI.yml",
            "io.github.linx_systems.ClamUI.local.yml",
        ],
    )
    def test_manifests_use_current_gnome_runtime(self, yaml_parser, manifest_name):
        """Both production and local builds must use the same supported runtime."""
        manifest = PROJECT_ROOT / "flathub" / manifest_name
        data = yaml_parser.safe_load(manifest.read_text())

        assert data["runtime-version"] == "51"


class TestRequiredPermissions:
    """Tests for required Flatpak permissions."""

    def test_has_finish_args(self, yaml_parser):
        """Test manifest has finish-args section."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        assert "finish-args" in data, "Missing finish-args section"

    def test_has_filesystem_permission(self, yaml_parser):
        """Test has filesystem permission (required for scanning)."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        finish_args = data.get("finish-args", [])
        filesystem_args = [arg for arg in finish_args if "--filesystem" in arg]

        assert len(filesystem_args) > 0, "Missing filesystem permission"

    def test_has_talk_permissions(self, yaml_parser):
        """Test has D-Bus talk permissions for tray."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        finish_args = data.get("finish-args", [])
        talk_args = [arg for arg in finish_args if "--talk-name" in arg or "--own-name" in arg]

        # Should have some D-Bus permissions for tray
        assert len(talk_args) > 0, "Missing D-Bus talk permissions"

    # Verify both the release manifest and the local development manifest rely
    # on Flatpak's accessibility bus proxy instead of requesting org.a11y.Bus.
    @pytest.mark.parametrize(
        "manifest_name",
        [
            "io.github.linx_systems.ClamUI.yml",
            "io.github.linx_systems.ClamUI.local.yml",
        ],
    )
    def test_does_not_request_explicit_a11y_bus_access(self, yaml_parser, manifest_name):
        """Test manifests rely on Flatpak's accessibility bus proxy."""
        manifest = PROJECT_ROOT / "flathub" / manifest_name
        data = yaml_parser.safe_load(manifest.read_text())

        finish_args = data.get("finish-args", [])

        assert "--talk-name=org.a11y.Bus" not in finish_args, (
            "Manifest should not request explicit org.a11y.Bus access"
        )

    @pytest.mark.parametrize(
        "manifest_name",
        [
            "io.github.linx_systems.ClamUI.yml",
            "io.github.linx_systems.ClamUI.local.yml",
        ],
    )
    def test_does_not_request_redundant_app_id_own_name(self, yaml_parser, manifest_name):
        """Test manifests do not request Flatpak's default app-id own-name permission."""
        manifest = PROJECT_ROOT / "flathub" / manifest_name
        data = yaml_parser.safe_load(manifest.read_text())

        finish_args = data.get("finish-args", [])

        assert "--own-name=io.github.linx_systems.ClamUI.tray" not in finish_args, (
            "Manifest should not request app-id scoped own-name access explicitly"
        )


class TestModulesSection:
    """Tests for modules section."""

    def test_has_modules(self, yaml_parser):
        """Test manifest has modules section."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        assert "modules" in data, "Missing modules section"
        assert len(data["modules"]) > 0, "No modules defined"

    def test_has_clamui_module(self, yaml_parser):
        """Test has clamui module in modules."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        data = yaml_parser.safe_load(manifest.read_text())

        modules = data.get("modules", [])
        module_names = [m.get("name", "") for m in modules if isinstance(m, dict)]

        # Should have clamui or main application module
        has_clamui = any("clamui" in name.lower() for name in module_names)
        assert has_clamui, "Missing clamui module"

    @pytest.mark.parametrize(
        "manifest_name",
        [
            "io.github.linx_systems.ClamUI.yml",
            "io.github.linx_systems.ClamUI.local.yml",
        ],
    )
    def test_manifest_does_not_bundle_clamav(self, yaml_parser, manifest_name):
        """Flatpak manifests should require host ClamAV instead of building it."""
        manifest = PROJECT_ROOT / "flathub" / manifest_name
        data = yaml_parser.safe_load(manifest.read_text())

        modules = data.get("modules", [])
        module_names = [m.get("name", "") for m in modules if isinstance(m, dict)]
        content = manifest.read_text()

        assert "clamav" not in module_names
        assert "clamav.net/downloads/production" not in content
        assert "org.freedesktop.Sdk.Extension.rust-stable" not in content


class TestIntegrationAssets:
    """Tests for bundled file manager integration assets."""

    def test_manifest_bundles_dolphin_service_menu(self):
        """Test manifest installs the Dolphin scan service menu into integration assets."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.yml"
        content = manifest.read_text()

        assert "io.github.linx_systems.ClamUI.service.desktop" in content

    def test_local_manifest_bundles_scan_and_virustotal_integrations(self):
        """Test local Flatpak manifest includes both scan and VirusTotal assets."""
        manifest = PROJECT_ROOT / "flathub" / "io.github.linx_systems.ClamUI.local.yml"
        content = manifest.read_text()

        assert "clamui-scan-nautilus.sh" in content
        assert "io.github.linx_systems.ClamUI.service.desktop" in content
        assert "io.github.linx_systems.ClamUI-virustotal.desktop" in content


class TestGeneratedDependencies:
    """Tests for generated dependency files."""

    def test_runtime_deps_json_exists(self):
        """Test runtime dependencies JSON exists."""
        deps_file = PROJECT_ROOT / "flathub" / "python3-runtime-deps.json"
        assert deps_file.exists(), "python3-runtime-deps.json not found"

    def test_runtime_deps_json_valid(self):
        """Test runtime dependencies JSON is valid."""
        deps_file = PROJECT_ROOT / "flathub" / "python3-runtime-deps.json"
        content = deps_file.read_text()

        try:
            data = json.loads(content)
            assert isinstance(data, (list, dict)), "Dependencies should be list or dict"
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON: {e}")

    def test_runtime_deps_target_sdk_python_and_both_architectures(self):
        """Generated binary wheels must match GNOME 51's Python 3.14 runtime."""
        data = json.loads((PROJECT_ROOT / "flathub" / "python3-runtime-deps.json").read_text())
        wheel_sources = [source for source in data["sources"] if "only-arches" in source]

        assert {arch for source in wheel_sources for arch in source["only-arches"]} == {
            "aarch64",
            "x86_64",
        }
        assert {
            arch
            for source in wheel_sources
            if "cp314" in source["url"]
            for arch in source["only-arches"]
        } == {"aarch64", "x86_64"}
        assert "cairosvg" not in data["build-commands"][0]

    def test_build_deps_json_exists(self):
        """Test build dependencies JSON exists."""
        deps_file = PROJECT_ROOT / "flathub" / "python3-build-deps.json"
        assert deps_file.exists(), "python3-build-deps.json not found"

    def test_build_deps_json_valid(self):
        """Test build dependencies JSON is valid."""
        deps_file = PROJECT_ROOT / "flathub" / "python3-build-deps.json"
        content = deps_file.read_text()

        try:
            data = json.loads(content)
            assert isinstance(data, (list, dict)), "Dependencies should be list or dict"
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON: {e}")

    def test_requirements_files_exist(self):
        """Test requirements files exist for dependency generation."""
        flathub_dir = PROJECT_ROOT / "flathub"

        required_files = [
            "requirements-build.txt",
            "requirements-runtime.txt",
            "requirements-runtime-pinned.txt",
        ]

        for filename in required_files:
            assert (flathub_dir / filename).exists(), f"{filename} not found in flathub/"
