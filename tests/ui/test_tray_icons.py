"""Behavior tests for GTK-free tray icon generation."""

import builtins
import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

TRAY_ICONS_PATH = Path(__file__).parents[2] / "src" / "ui" / "tray_icons.py"


@pytest.fixture
def tray_icons():
    """Load the tray module directly, as the tray subprocess does."""
    module_name = "_clamui_test_tray_icons"
    spec = importlib.util.spec_from_file_location(module_name, TRAY_ICONS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop(module_name, None)


@pytest.fixture
def png_icon(tmp_path):
    path = tmp_path / "base.png"
    Image.new("RGBA", (128, 128), (12, 34, 56, 255)).save(path)
    return path


def install_gdk_pixbuf(monkeypatch):
    pixbuf = mock.MagicMock()
    pixbuf_class = mock.MagicMock()
    pixbuf_class.new_from_file_at_scale.return_value = pixbuf
    repository = types.ModuleType("gi.repository")
    repository.GdkPixbuf = types.SimpleNamespace(Pixbuf=pixbuf_class)
    gi = types.ModuleType("gi")
    gi.require_version = mock.MagicMock()
    gi.repository = repository
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)
    return pixbuf_class, pixbuf


@pytest.mark.parametrize(
    ("status", "color"),
    [
        ("protected", (76, 175, 80, 255)),
        ("scanning", (33, 150, 243, 255)),
        ("warning", (255, 193, 7, 255)),
        ("threat", (244, 67, 54, 255)),
    ],
)
def test_png_generation_preserves_status_badges(
    tray_icons, png_icon, tmp_path, monkeypatch, status, color
):
    """PNG inputs stay GTK-free and produce the expected 22px status badge."""
    original_import = builtins.__import__

    def reject_gi(name, *args, **kwargs):
        if name == "gi" or name.startswith("gi."):
            raise AssertionError("PNG tray generation must not import GI")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_gi)
    output = Path(
        tray_icons.TrayIconGenerator(str(png_icon), str(tmp_path / "cache")).get_icon_path(status)
    )

    with Image.open(output) as image:
        assert image.mode == "RGBA"
        assert image.size == (22, 22)
        assert image.getpixel((16, 12)) == color


def test_unknown_status_uses_protected_icon(tray_icons, png_icon, tmp_path):
    generator = tray_icons.TrayIconGenerator(str(png_icon), str(tmp_path / "cache"))

    assert Path(generator.get_icon_path("unknown")).name == "clamui-tray-protected.png"


def test_svg_conversion_uses_gdk_pixbuf_at_128px(tray_icons, tmp_path, monkeypatch):
    pixbuf_class, pixbuf = install_gdk_pixbuf(monkeypatch)
    svg_icon = tmp_path / "base.svg"
    svg_icon.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    cache_dir = tmp_path / "cache"

    generator = tray_icons.TrayIconGenerator(str(svg_icon), str(cache_dir))

    sys.modules["gi"].require_version.assert_called_once_with("GdkPixbuf", "2.0")

    pixbuf_class.new_from_file_at_scale.assert_called_once_with(str(svg_icon), 128, 128, True)
    pixbuf.savev.assert_called_once_with(
        str(cache_dir / "clamui-base-converted.png"), "png", [], []
    )
    assert generator._get_base_icon_path() == cache_dir / "clamui-base-converted.png"


def test_svg_conversion_reuses_fresh_cache_without_loading_gi(tray_icons, tmp_path, monkeypatch):
    pixbuf_class, _ = install_gdk_pixbuf(monkeypatch)
    svg_icon = tmp_path / "base.svg"
    svg_icon.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cached_png = cache_dir / "clamui-base-converted.png"
    cached_png.write_bytes(b"cached")
    os.utime(svg_icon, (1, 1))
    os.utime(cached_png, (2, 2))

    generator = tray_icons.TrayIconGenerator(str(svg_icon), str(cache_dir))

    pixbuf_class.new_from_file_at_scale.assert_not_called()
    assert generator._get_base_icon_path() == cached_png


def test_malformed_svg_keeps_runtime_error(tray_icons, tmp_path, monkeypatch):
    pixbuf_class, _ = install_gdk_pixbuf(monkeypatch)
    pixbuf_class.new_from_file_at_scale.side_effect = ValueError("SVG parse error")
    svg_icon = tmp_path / "broken.svg"
    svg_icon.write_text("not svg")

    with pytest.raises(RuntimeError, match="Failed to convert SVG to PNG: SVG parse error"):
        tray_icons.TrayIconGenerator(str(svg_icon), str(tmp_path / "cache"))


def test_svg_availability_requires_native_svg_loader(tray_icons, monkeypatch):
    pixbuf_class, _ = install_gdk_pixbuf(monkeypatch)
    icon_format = mock.MagicMock()
    pixbuf_class.get_formats.return_value = [icon_format]
    monkeypatch.setattr(tray_icons, "find_clamui_base_icon", lambda: "/icons/base.svg")

    icon_format.get_extensions.return_value = []
    assert tray_icons.is_available() is False

    icon_format.get_extensions.return_value = ["svg"]
    assert tray_icons.is_available() is True
    assert sys.modules["gi"].require_version.call_args_list == [
        mock.call("GdkPixbuf", "2.0"),
        mock.call("GdkPixbuf", "2.0"),
    ]
