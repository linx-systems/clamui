# ClamUI Dependency Consistency Tests
"""
Tests for dependency consistency across packaging formats.

Tests cover:
- Debian control vs pyproject.toml alignment
- Minimum version constraints
- Flatpak pinned versions sync
- GIR (GTK/Adw) dependencies

These tests prevent dependency drift between packaging formats.
"""

import re
from pathlib import Path

import pytest

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestDebianControlVsPyproject:
    """Tests for Debian control vs pyproject.toml dependency alignment."""

    def test_pyproject_dependencies_exist(self):
        """Test pyproject.toml has dependencies section."""
        pyproject = PROJECT_ROOT / "pyproject.toml"
        content = pyproject.read_text()

        assert "dependencies" in content, "pyproject.toml missing dependencies section"

    def test_control_depends_exist(self):
        """Test Debian control has Depends field."""
        control = PROJECT_ROOT / "debian" / "DEBIAN" / "control"
        content = control.read_text()

        assert "Depends:" in content, "Debian control missing Depends field"

    def test_python_version_constraint_aligned(self):
        """Test Python version constraint is aligned."""
        pyproject = PROJECT_ROOT / "pyproject.toml"
        control = PROJECT_ROOT / "debian" / "DEBIAN" / "control"

        pyproject_content = pyproject.read_text()
        control_content = control.read_text()

        # pyproject.toml should have requires-python >= 3.11
        assert ">=3.11" in pyproject_content or ">= 3.11" in pyproject_content, (
            "pyproject.toml should require Python 3.11+"
        )

        # Debian control should have python3 >= 3.11
        assert "python3 (>= 3.11)" in control_content, "Debian control should require Python 3.11+"

    def test_requests_version_aligned(self):
        """Test requests library version is aligned."""
        pyproject = PROJECT_ROOT / "pyproject.toml"
        control = PROJECT_ROOT / "debian" / "DEBIAN" / "control"

        pyproject_content = pyproject.read_text()
        control_content = control.read_text()

        # Both should have requests dependency
        assert "requests" in pyproject_content.lower(), "pyproject.toml missing requests dependency"
        assert "python3-requests" in control_content, (
            "Debian control missing python3-requests dependency"
        )

    def test_keyring_version_aligned(self):
        """Test keyring library version is aligned."""
        pyproject = PROJECT_ROOT / "pyproject.toml"
        control = PROJECT_ROOT / "debian" / "DEBIAN" / "control"

        pyproject_content = pyproject.read_text()
        control_content = control.read_text()

        # Both should have keyring dependency
        assert "keyring" in pyproject_content.lower(), "pyproject.toml missing keyring dependency"
        assert "python3-keyring" in control_content, (
            "Debian control missing python3-keyring dependency"
        )

    def test_gdkpixbuf_svg_loader_dependencies(self):
        """Debian must provide the native SVG loader and its GI binding."""
        control_content = (PROJECT_ROOT / "debian" / "DEBIAN" / "control").read_text()

        assert "gir1.2-gdkpixbuf-2.0" in control_content
        assert "librsvg2-common" in control_content


class TestMinimumVersionConstraints:
    """Tests for minimum version constraints."""

    def test_all_pyproject_deps_have_versions(self):
        """Test all pyproject.toml dependencies have version constraints."""
        pyproject = PROJECT_ROOT / "pyproject.toml"
        content = pyproject.read_text()

        # Find the dependencies section
        dep_match = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.DOTALL)
        if not dep_match:
            pytest.skip("Could not parse dependencies section")

        deps_section = dep_match.group(1)

        # Each dependency line should have a version constraint
        dep_lines = [
            line.strip()
            for line in deps_section.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]

        for line in dep_lines:
            # Skip empty lines and comments
            if not line or line.startswith("]"):
                continue
            # Should have version specifier (>=, ==, ~=, etc.)
            assert ">=" in line or "==" in line or "~=" in line or "<" in line, (
                f"Dependency missing version constraint: {line}"
            )

    def test_urllib3_has_audit_fix_version(self):
        """urllib3 must include the fixes for PYSEC-2026-4175/4176/4177."""
        content = (PROJECT_ROOT / "pyproject.toml").read_text()

        match = re.search(r"urllib3[><=]+([0-9.]+)", content)
        assert match, "pyproject.toml missing urllib3 version constraint"
        assert tuple(map(int, match.group(1).split("."))) >= (2, 8, 0)


class TestFlatpakPinnedVersions:
    """Tests for Flatpak pinned versions sync."""

    def test_pinned_versions_exist(self):
        """Test requirements-runtime-pinned.txt exists."""
        pinned = PROJECT_ROOT / "flathub" / "requirements-runtime-pinned.txt"
        assert pinned.exists(), "requirements-runtime-pinned.txt not found"

    def test_runtime_requirements_exist(self):
        """Test requirements-runtime.txt exists."""
        runtime = PROJECT_ROOT / "flathub" / "requirements-runtime.txt"
        assert runtime.exists(), "requirements-runtime.txt not found"

    def test_pinned_has_version_numbers(self):
        """Test pinned requirements have exact versions."""
        pinned = PROJECT_ROOT / "flathub" / "requirements-runtime-pinned.txt"
        content = pinned.read_text()

        # Each line should have == for exact pinning
        lines = [
            line.strip()
            for line in content.split("\n")
            if line.strip() and not line.startswith("#")
        ]

        for line in lines:
            assert "==" in line, f"Pinned requirement missing exact version: {line}"


class TestGirDependencies:
    """Tests for GIR (GNOME Introspection) dependencies."""

    def test_control_has_gtk4_gir(self):
        """Test Debian control has GTK4 GIR dependency."""
        control = PROJECT_ROOT / "debian" / "DEBIAN" / "control"
        content = control.read_text()

        assert "gir1.2-gtk-4.0" in content, "Debian control missing gir1.2-gtk-4.0 dependency"

    def test_control_has_adwaita_gir(self):
        """Test Debian control has libadwaita GIR dependency."""
        control = PROJECT_ROOT / "debian" / "DEBIAN" / "control"
        content = control.read_text()

        assert "gir1.2-adw-1" in content, "Debian control missing gir1.2-adw-1 dependency"

    def test_control_has_pygobject(self):
        """Test Debian control has PyGObject dependency."""
        control = PROJECT_ROOT / "debian" / "DEBIAN" / "control"
        content = control.read_text()

        assert "python3-gi" in content, "Debian control missing python3-gi dependency"

    def test_control_has_cairo(self):
        """Test Debian control has Cairo dependency."""
        control = PROJECT_ROOT / "debian" / "DEBIAN" / "control"
        content = control.read_text()

        # Should have python3-cairo or python3-gi-cairo
        has_cairo = "python3-cairo" in content or "python3-gi-cairo" in content
        assert has_cairo, "Debian control missing Cairo dependency"


class TestAppImageDependencies:
    """AppImage must let pip resolve the complete runtime dependency graph."""

    def test_installs_direct_dependencies_with_transitives(self):
        content = (PROJECT_ROOT / "appimage" / "build-appimage.sh").read_text()

        assert "--no-deps" not in content
        assert "cairosvg" not in content
        for dependency in ("keyring", "matplotlib", "Pillow", "urllib3"):
            assert dependency in content
        assert "bundle_svg_loader" in content
        assert "libpixbufloader-svg.so" in content
        assert "librsvg-2.so.2" in content
        assert "sys.version_info < (3, 11)" in content
