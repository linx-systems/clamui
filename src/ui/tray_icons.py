# ClamUI Tray Icon Generator Module
"""
Generates composite tray icons with status overlay badges.

Uses PIL (Pillow) to composite the ClamUI logo with small status indicator
badges for different protection states (protected, scanning, warning, threat).

Generated icons are cached in XDG_CACHE_HOME/clamui/tray-icons/ for efficiency.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# PIL import with graceful fallback
PIL_AVAILABLE = False
CAIROSVG_AVAILABLE = False

try:
    from PIL import Image, ImageDraw

    PIL_AVAILABLE = True
except ImportError:
    logger.warning("PIL/Pillow not available, custom tray icons disabled")

# Try to import cairosvg for SVG support
try:
    import cairosvg

    CAIROSVG_AVAILABLE = True
except ImportError:
    logger.debug("cairosvg not available, SVG icons will need PNG fallback")


def find_clamui_base_icon() -> str | None:
    """
    Find the ClamUI icon (PNG preferred, SVG fallback) for use as base.

    Searches in order:
    1. Development: <module_dir>/../../icons/
    2. Flatpak: /app/share/icons/hicolor/{128x128,scalable}/apps/
    3. System: /usr/share/icons/hicolor/{128x128,scalable}/apps/
    4. User: ~/.local/share/icons/hicolor/{128x128,scalable}/apps/

    Returns:
        Absolute path to the icon file, or None if not found
    """
    # Prefer PNG (PIL can read it directly), then SVG
    icon_filenames = [
        "io.github.linx_systems.ClamUI.png",
        "io.github.linx_systems.ClamUI.svg",
    ]

    module_dir = Path(__file__).parent
    search_paths = [
        module_dir.parent.parent / "icons",  # Development: src/ui -> src -> project/icons
        # Flatpak - check size-specific first (PNG), then scalable (SVG)
        Path("/app/share/icons/hicolor/128x128/apps"),
        Path("/app/share/icons/hicolor/scalable/apps"),
        # System installs
        Path("/usr/share/icons/hicolor/128x128/apps"),
        Path("/usr/share/icons/hicolor/scalable/apps"),
        Path("/usr/local/share/icons/hicolor/128x128/apps"),
        Path("/usr/local/share/icons/hicolor/scalable/apps"),
        # User install
        Path.home() / ".local/share/icons/hicolor/128x128/apps",
        Path.home() / ".local/share/icons/hicolor/scalable/apps",
    ]

    # First pass: look for PNG (preferred)
    for search_path in search_paths:
        icon_path = search_path / icon_filenames[0]  # PNG
        if icon_path.exists():
            logger.info(f"Found ClamUI PNG icon at: {icon_path}")
            return str(icon_path.absolute())

    # Second pass: look for SVG (fallback - requires conversion)
    for search_path in search_paths:
        icon_path = search_path / icon_filenames[1]  # SVG
        if icon_path.exists():
            logger.info(f"Found ClamUI SVG icon at: {icon_path}")
            # Note: SVG requires cairosvg or similar to convert
            # For now, return it and let the caller handle it
            return str(icon_path.absolute())

    logger.warning(f"ClamUI base icon not found. Searched paths: {[str(p) for p in search_paths]}")
    return None


def get_tray_icon_cache_dir() -> str:
    """
    Get the directory for generated tray icons.

    Uses XDG_DATA_HOME/icons which is in GTK3's standard icon theme search path,
    so AppIndicator can find icons by name without needing set_icon_theme_path().

    Returns:
        Path to the icon directory (following hicolor theme structure)
    """
    xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    # Use standard hicolor icon theme structure in XDG data directory
    icon_dir = Path(xdg_data) / "icons" / "hicolor" / "22x22" / "apps"
    return str(icon_dir)


class TrayIconGenerator:
    """
    Generates composite tray icons with status overlay badges.

    Creates PNG icons by compositing the ClamUI logo with small colored
    badges indicating the current protection status.
    """

    # Status colors (RGBA)
    OVERLAY_COLORS = {
        "protected": (76, 175, 80, 255),  # Green
        "scanning": (33, 150, 243, 255),  # Blue
        "warning": (255, 193, 7, 255),  # Yellow/Amber
        "threat": (244, 67, 54, 255),  # Red
    }

    # Standard tray icon size
    ICON_SIZE = 22

    # Overlay badge size
    OVERLAY_SIZE = 10

    def __init__(self, base_icon_path: str, cache_dir: str) -> None:
        """
        Initialize the icon generator.

        Args:
            base_icon_path: Path to the base ClamUI icon (PNG or SVG)
            cache_dir: Directory to cache generated icons
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("PIL/Pillow is required for icon generation")

        self._base_icon_path = Path(base_icon_path)
        self._cache_dir = Path(cache_dir)
        self._converted_png_path: Path | None = None

        # Ensure cache directory exists
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Validate base icon exists
        if not self._base_icon_path.exists():
            raise FileNotFoundError(f"Base icon not found: {base_icon_path}")

        # If base icon is SVG, convert it to PNG first
        if self._base_icon_path.suffix.lower() == ".svg":
            if not CAIROSVG_AVAILABLE:
                raise RuntimeError(
                    "cairosvg is required to use SVG icons. Install it with: pip install cairosvg"
                )
            self._convert_svg_to_png()

        logger.debug(f"TrayIconGenerator initialized with base: {base_icon_path}")

    def _convert_svg_to_png(self) -> None:
        """Convert SVG base icon to PNG for PIL processing."""
        converted_path = self._cache_dir / "clamui-base-converted.png"

        # Check if conversion is needed (source newer than cached)
        if converted_path.exists():
            if converted_path.stat().st_mtime >= self._base_icon_path.stat().st_mtime:
                self._converted_png_path = converted_path
                logger.debug(f"Using cached PNG conversion: {converted_path}")
                return

        logger.info(f"Converting SVG to PNG: {self._base_icon_path}")
        try:
            # Convert SVG to PNG at a reasonable size for tray icons
            # Use 128x128 as source, will be resized to ICON_SIZE later
            cairosvg.svg2png(
                url=str(self._base_icon_path),
                write_to=str(converted_path),
                output_width=128,
                output_height=128,
            )
            self._converted_png_path = converted_path
            logger.info(f"SVG converted to PNG: {converted_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to convert SVG to PNG: {e}") from e

    def _get_base_icon_path(self) -> Path:
        """Get the path to the base icon (converted PNG if SVG was provided)."""
        if self._converted_png_path is not None:
            return self._converted_png_path
        return self._base_icon_path

    def get_icon_path(self, status: str) -> str:
        """
        Get path to icon for given status, generating if needed.

        Args:
            status: Protection status ('protected', 'warning', 'scanning', 'threat')

        Returns:
            Absolute path to the generated icon
        """
        # Normalize status
        if status not in self.OVERLAY_COLORS:
            logger.warning(f"Unknown status '{status}', defaulting to 'protected'")
            status = "protected"

        cache_path = self._cache_dir / f"clamui-tray-{status}.png"

        # Check if cached icon exists and is newer than base icon
        base_icon = self._get_base_icon_path()
        if cache_path.exists() and cache_path.stat().st_mtime >= base_icon.stat().st_mtime:
            return str(cache_path)

        # Generate new icon
        self._generate_icon(status, cache_path)
        return str(cache_path)

    def pregenerate_all(self) -> None:
        """Pre-generate icons for all statuses to improve responsiveness."""
        for status in self.OVERLAY_COLORS:
            try:
                self.get_icon_path(status)
                logger.debug(f"Pre-generated icon for status: {status}")
            except Exception as e:
                logger.error(f"Failed to pre-generate icon for {status}: {e}")

    def _generate_icon(self, status: str, output_path: Path) -> None:
        """
        Generate composite icon with overlay badge.

        Args:
            status: Protection status
            output_path: Path to save the generated icon
        """
        # Load and resize base icon (use converted PNG if original was SVG)
        base_icon = self._get_base_icon_path()
        base = Image.open(base_icon).convert("RGBA")
        base = base.resize((self.ICON_SIZE, self.ICON_SIZE), Image.Resampling.LANCZOS)

        # Create overlay badge
        overlay = self._create_overlay(status)

        # Position overlay at bottom-right corner
        overlay_pos = (
            self.ICON_SIZE - self.OVERLAY_SIZE - 1,
            self.ICON_SIZE - self.OVERLAY_SIZE - 1,
        )

        # Composite overlay onto base
        base.paste(overlay, overlay_pos, overlay)

        # Save the result
        base.save(output_path, "PNG")
        logger.debug(f"Generated tray icon: {output_path}")

    def _create_overlay(self, status: str) -> "Image.Image":
        """
        Create overlay badge image for status.

        Args:
            status: Protection status

        Returns:
            PIL Image with the overlay badge
        """
        img = Image.new("RGBA", (self.OVERLAY_SIZE, self.OVERLAY_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        color = self.OVERLAY_COLORS.get(status, self.OVERLAY_COLORS["protected"])

        # Draw status-specific badge
        if status == "protected":
            self._draw_checkmark_badge(draw, color)
        elif status == "scanning":
            self._draw_sync_badge(draw, color)
        elif status == "warning":
            self._draw_warning_badge(draw, color)
        elif status == "threat":
            self._draw_threat_badge(draw, color)
        else:
            self._draw_checkmark_badge(draw, color)

        return img

    def _draw_checkmark_badge(
        self, draw: "ImageDraw.ImageDraw", color: tuple[int, int, int, int]
    ) -> None:
        """Draw a green circle with a white checkmark."""
        size = self.OVERLAY_SIZE
        # Draw filled circle
        draw.ellipse([0, 0, size - 1, size - 1], fill=color)
        # Draw white checkmark
        white = (255, 255, 255, 255)
        # Checkmark path: starts bottom-left of check, goes down to bottom, then up to top-right
        draw.line([(2, 5), (4, 7)], fill=white, width=1)
        draw.line([(4, 7), (8, 3)], fill=white, width=1)

    def _draw_sync_badge(
        self, draw: "ImageDraw.ImageDraw", color: tuple[int, int, int, int]
    ) -> None:
        """Draw a blue circle indicating sync/scanning activity."""
        size = self.OVERLAY_SIZE
        # Draw filled circle
        draw.ellipse([0, 0, size - 1, size - 1], fill=color)
        # Draw two curved arrows (simplified as lines)
        white = (255, 255, 255, 255)
        # Top arrow pointing right
        draw.line([(2, 3), (7, 3)], fill=white, width=1)
        draw.line([(5, 2), (7, 3), (5, 4)], fill=white, width=1)
        # Bottom arrow pointing left
        draw.line([(3, 7), (8, 7)], fill=white, width=1)
        draw.line([(5, 6), (3, 7), (5, 8)], fill=white, width=1)

    def _draw_warning_badge(
        self, draw: "ImageDraw.ImageDraw", color: tuple[int, int, int, int]
    ) -> None:
        """Draw a yellow warning triangle with exclamation mark."""
        size = self.OVERLAY_SIZE
        # Draw triangle pointing up
        center_x = size // 2
        draw.polygon(
            [(center_x, 0), (size - 1, size - 1), (0, size - 1)],
            fill=color,
        )
        # Draw black exclamation mark
        black = (0, 0, 0, 255)
        draw.line([(center_x, 3), (center_x, 6)], fill=black, width=1)
        draw.point((center_x, 8), fill=black)

    def _draw_threat_badge(
        self, draw: "ImageDraw.ImageDraw", color: tuple[int, int, int, int]
    ) -> None:
        """Draw a red circle with white exclamation mark."""
        size = self.OVERLAY_SIZE
        center_x = size // 2
        # Draw filled circle
        draw.ellipse([0, 0, size - 1, size - 1], fill=color)
        # Draw white exclamation mark
        white = (255, 255, 255, 255)
        draw.line([(center_x, 2), (center_x, 5)], fill=white, width=1)
        draw.point((center_x, 7), fill=white)


def is_available() -> bool:
    """
    Check if tray icon generation is available.

    Returns:
        True if PIL is available and a usable base icon can be found
    """
    if not PIL_AVAILABLE:
        return False

    base_icon = find_clamui_base_icon()
    if base_icon is None:
        return False

    # If it's an SVG, we need cairosvg to convert it
    if base_icon.lower().endswith(".svg") and not CAIROSVG_AVAILABLE:
        logger.warning(
            "Found SVG icon but cairosvg is not available. "
            "Install cairosvg for SVG support, or provide a PNG icon."
        )
        return False

    return True
