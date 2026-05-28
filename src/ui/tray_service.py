#!/usr/bin/env python3
# ClamUI Tray Service - StatusNotifierItem D-Bus Implementation
"""
Standalone tray indicator service using the StatusNotifierItem (SNI) D-Bus protocol.

This implementation uses GIO's D-Bus API directly, avoiding the need for GTK3.
It implements the org.kde.StatusNotifierItem specification which is supported by:
- Cinnamon (via xapp-sn-watcher)
- KDE Plasma
- XFCE (with status notifier plugin)
- Many other desktop environments

The SNI protocol uses DBusMenu for context menus, which allows right-click
functionality without requiring GTK.

For detailed architecture documentation, see: docs/architecture/tray-subprocess.md

Protocol:
- Input (stdin): JSON commands like {"action": "update_status", "status": "scanning"}
- Output (stdout): JSON responses like {"event": "menu_action", "action": "quick_scan"}

Usage:
    python -m src.ui.tray_service
"""

import gettext
import json
import logging
import os
import sys
import threading
from pathlib import Path

# Configure logging to stderr (stdout is used for IPC)
logging.basicConfig(
    level=logging.DEBUG if os.environ.get("CLAMUI_DEBUG") else logging.INFO,
    format="[TrayService] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# GLib/Gio imports for D-Bus (part of GObject, works with GTK4)
try:
    import gi

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib

    DBUS_AVAILABLE = True
except (ValueError, ImportError) as e:
    logger.error(f"Failed to load GIO D-Bus: {e}")
    DBUS_AVAILABLE = False

# Try to load libdbusmenu for menu export
DBUSMENU_AVAILABLE = False
Dbusmenu = None
try:
    gi.require_version("Dbusmenu", "0.4")
    from gi.repository import Dbusmenu

    DBUSMENU_AVAILABLE = True
    logger.info("libdbusmenu available for menu export")
except (ValueError, ImportError) as e:
    logger.info(f"libdbusmenu not available, menu will not be shown: {e}")

if not DBUS_AVAILABLE:
    sys.stdout.write(json.dumps({"event": "error", "message": "GIO D-Bus not available"}) + "\n")
    sys.stdout.flush()
    sys.exit(1)

# Initialize i18n for this subprocess
# Uses the same dual-import strategy as tray_icons below:
# relative import when loaded as a package, direct init when run as a script.
try:
    try:
        from ..core.i18n import _
    except ImportError:
        import importlib.util

        _i18n_path = Path(__file__).parent.parent / "core" / "i18n.py"
        _i18n_spec = importlib.util.spec_from_file_location("i18n", _i18n_path)
        _i18n_module = importlib.util.module_from_spec(_i18n_spec)
        _i18n_spec.loader.exec_module(_i18n_module)
        _ = _i18n_module._
except Exception:
    # Ultimate fallback: passthrough (no translations)
    _ = gettext.gettext

# Import tray icon generator
CUSTOM_ICONS_AVAILABLE = False
TrayIconGenerator = None
find_clamui_base_icon = None
get_tray_icon_cache_dir = None

try:
    try:
        from .tray_icons import (
            TrayIconGenerator,
            find_clamui_base_icon,
            get_tray_icon_cache_dir,
        )
        from .tray_icons import (
            is_available as icons_available,
        )
    except ImportError:
        import importlib.util

        tray_icons_path = Path(__file__).parent / "tray_icons.py"
        spec = importlib.util.spec_from_file_location("tray_icons", tray_icons_path)
        tray_icons_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tray_icons_module)
        TrayIconGenerator = tray_icons_module.TrayIconGenerator
        find_clamui_base_icon = tray_icons_module.find_clamui_base_icon
        get_tray_icon_cache_dir = tray_icons_module.get_tray_icon_cache_dir
        icons_available = tray_icons_module.is_available

    CUSTOM_ICONS_AVAILABLE = icons_available()
    if CUSTOM_ICONS_AVAILABLE:
        logger.info("Custom tray icon generation available")
    else:
        logger.info("Custom tray icons not available (PIL or base icon missing)")
except Exception as e:
    logger.warning(f"Could not import tray_icons module: {e}")


# StatusNotifierItem D-Bus interface XML
STATUS_NOTIFIER_ITEM_XML = """
<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property type="s" name="Category" access="read"/>
    <property type="s" name="Id" access="read"/>
    <property type="s" name="Title" access="read"/>
    <property type="s" name="Status" access="read"/>
    <property type="u" name="WindowId" access="read"/>
    <property type="s" name="IconName" access="read"/>
    <property type="a(iiay)" name="IconPixmap" access="read"/>
    <property type="s" name="IconThemePath" access="read"/>
    <property type="s" name="OverlayIconName" access="read"/>
    <property type="a(iiay)" name="OverlayIconPixmap" access="read"/>
    <property type="s" name="AttentionIconName" access="read"/>
    <property type="a(iiay)" name="AttentionIconPixmap" access="read"/>
    <property type="s" name="AttentionMovieName" access="read"/>
    <property type="(sa(iiay)ss)" name="ToolTip" access="read"/>
    <property type="b" name="ItemIsMenu" access="read"/>
    <property type="o" name="Menu" access="read"/>
    <method name="ContextMenu">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="Activate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="Scroll">
      <arg type="i" name="delta" direction="in"/>
      <arg type="s" name="orientation" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewIconThemePath"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg type="s" name="status"/>
    </signal>
  </interface>
</node>
"""


class TrayService:
    """
    System tray indicator service using StatusNotifierItem (SNI) D-Bus protocol.

    This implementation doesn't require GTK3 - it uses GIO's D-Bus API which
    is part of GLib and works with GTK4. It uses DBusMenu for the context menu.
    """

    # Icon mapping for different protection states
    ICON_MAP = {
        "protected": "object-select-symbolic",
        "warning": "dialog-warning-symbolic",
        "scanning": "view-refresh-symbolic",
        "threat": "dialog-error-symbolic",
    }

    # SNI status mapping
    SNI_STATUS_MAP = {
        "protected": "Active",
        "warning": "NeedsAttention",
        "scanning": "Active",
        "threat": "NeedsAttention",
    }

    DBUS_NAME = "io.github.linx_systems.ClamUI.tray"
    SNI_PATH = "/StatusNotifierItem"
    MENU_PATH = "/MenuBar"
    WATCHER_NAMES = [
        "org.x.StatusNotifierWatcher",
        "org.kde.StatusNotifierWatcher",
        "org.freedesktop.StatusNotifierWatcher",
    ]
    WATCHER_RETRY_DELAY_MS = 2000

    def __init__(self):
        """Initialize the tray service."""
        self._loop: GLib.MainLoop | None = None
        self._bus: Gio.DBusConnection | None = None
        self._sni_registration_id = 0
        self._bus_name_id = 0
        self._running = True
        self._watcher_registered = False
        self._watcher_name: str | None = None
        self._watcher_retry_source_id = 0
        self._icon_pixmap_cache: dict[tuple[str, int], GLib.Variant] = {}

        # Status state
        self._current_status = "protected"
        self._window_visible = True
        self._progress_label = ""

        # Profile state
        self._profiles: list[dict] = []
        self._current_profile_id: str | None = None

        # Custom icon generator
        self._icon_generator: TrayIconGenerator | None = None
        self._using_custom_icons = False

        # DBusMenu server for context menu
        self._dbusmenu_server = None
        self._menu_root = None

        # Set up custom icons
        self._setup_custom_icons()

        # Set up DBusMenu
        self._setup_dbusmenu()

    def _setup_custom_icons(self) -> None:
        """Set up custom ClamUI icon generation."""
        if not CUSTOM_ICONS_AVAILABLE:
            logger.debug("Custom icons not available, using theme icons")
            return

        base_icon = find_clamui_base_icon()
        if not base_icon:
            logger.info("ClamUI base icon not found, using theme icons")
            return

        try:
            cache_dir = get_tray_icon_cache_dir()
            self._icon_generator = TrayIconGenerator(base_icon, cache_dir)
            self._icon_generator.pregenerate_all()
            self._using_custom_icons = True
            logger.info(f"Custom tray icons enabled, cache: {cache_dir}")
        except Exception as e:
            logger.warning(f"Failed to set up custom icons: {e}")
            self._using_custom_icons = False

    def _setup_dbusmenu(self) -> None:
        """Set up the DBusMenu server for context menu export."""
        if not DBUSMENU_AVAILABLE:
            logger.debug("DBusMenu not available, context menu will not be shown")
            return

        try:
            # Create server at the MenuBar path (standard for SNI)
            self._dbusmenu_server = Dbusmenu.Server.new(self.MENU_PATH)

            # Create root menu item
            self._menu_root = Dbusmenu.Menuitem.new()

            # Build menu structure
            self._rebuild_menu()

            # Set root node
            self._dbusmenu_server.set_root(self._menu_root)

            logger.info(f"DBusMenu server initialized at {self.MENU_PATH}")
        except Exception as e:
            logger.warning(f"Failed to set up DBusMenu: {e}")
            self._dbusmenu_server = None
            self._menu_root = None

    def _rebuild_menu(self) -> None:
        """Rebuild the menu structure."""
        if not self._menu_root or not DBUSMENU_AVAILABLE:
            return

        # Clear existing children
        children = self._menu_root.get_children()
        for child in children:
            self._menu_root.child_delete(child)

        # Create menu items with unique IDs (using new_with_id)
        item_id = 1

        # Show/Hide Window
        toggle_item = Dbusmenu.Menuitem.new_with_id(item_id)
        item_id += 1
        toggle_label = _("Hide Window") if self._window_visible else _("Show Window")
        toggle_item.property_set(Dbusmenu.MENUITEM_PROP_LABEL, toggle_label)
        toggle_item.connect("item-activated", self._on_menu_toggle_window)
        self._menu_root.child_append(toggle_item)

        # Separator
        sep1 = Dbusmenu.Menuitem.new_with_id(item_id)
        item_id += 1
        sep1.property_set(Dbusmenu.MENUITEM_PROP_TYPE, "separator")
        self._menu_root.child_append(sep1)

        # Quick Scan
        quick_scan = Dbusmenu.Menuitem.new_with_id(item_id)
        item_id += 1
        quick_scan.property_set(Dbusmenu.MENUITEM_PROP_LABEL, _("Quick Scan"))
        quick_scan.connect("item-activated", self._on_menu_quick_scan)
        self._menu_root.child_append(quick_scan)

        # Full Scan
        full_scan = Dbusmenu.Menuitem.new_with_id(item_id)
        item_id += 1
        full_scan.property_set(Dbusmenu.MENUITEM_PROP_LABEL, _("Full Scan"))
        full_scan.connect("item-activated", self._on_menu_full_scan)
        self._menu_root.child_append(full_scan)

        # Scan with profile submenu (one entry per configured profile)
        if self._profiles:
            profile_root = Dbusmenu.Menuitem.new_with_id(item_id)
            item_id += 1
            profile_root.property_set(Dbusmenu.MENUITEM_PROP_LABEL, _("Scan with profile"))
            self._menu_root.child_append(profile_root)
            for profile in self._profiles:
                profile_id = profile.get("id")
                profile_name = profile.get("name", "")
                if not profile_id or not profile_name:
                    continue
                entry = Dbusmenu.Menuitem.new_with_id(item_id)
                item_id += 1
                entry.property_set(Dbusmenu.MENUITEM_PROP_LABEL, profile_name)
                entry.connect("item-activated", self._on_menu_select_profile, profile_id)
                profile_root.child_append(entry)

        # Separator
        sep2 = Dbusmenu.Menuitem.new_with_id(item_id)
        item_id += 1
        sep2.property_set(Dbusmenu.MENUITEM_PROP_TYPE, "separator")
        self._menu_root.child_append(sep2)

        # Update Definitions
        update_item = Dbusmenu.Menuitem.new_with_id(item_id)
        item_id += 1
        update_item.property_set(Dbusmenu.MENUITEM_PROP_LABEL, _("Update Definitions"))
        update_item.connect("item-activated", self._on_menu_update)
        self._menu_root.child_append(update_item)

        # Separator
        sep3 = Dbusmenu.Menuitem.new_with_id(item_id)
        item_id += 1
        sep3.property_set(Dbusmenu.MENUITEM_PROP_TYPE, "separator")
        self._menu_root.child_append(sep3)

        # Quit
        quit_item = Dbusmenu.Menuitem.new_with_id(item_id)
        quit_item.property_set(Dbusmenu.MENUITEM_PROP_LABEL, _("Quit"))
        quit_item.connect("item-activated", self._on_menu_quit)
        self._menu_root.child_append(quit_item)

        logger.debug("Menu rebuilt")

    def _on_menu_toggle_window(self, menuitem, timestamp):
        """Handle toggle window menu item activation."""
        self._send_action("toggle_window")

    def _on_menu_quick_scan(self, menuitem, timestamp):
        """Handle quick scan menu item activation."""
        self._send_action("quick_scan")

    def _on_menu_full_scan(self, menuitem, timestamp):
        """Handle full scan menu item activation."""
        self._send_action("full_scan")

    def _on_menu_select_profile(self, menuitem, timestamp, profile_id):
        """Handle profile selection menu item activation."""
        self._send_message(
            {"event": "menu_action", "action": "select_profile", "profile_id": profile_id}
        )

    def _on_menu_update(self, menuitem, timestamp):
        """Handle update definitions menu item activation."""
        self._send_action("update")

    def _on_menu_quit(self, menuitem, timestamp):
        """Handle quit menu item activation."""
        self._send_action("quit")

    def _get_icon_name(self) -> str:
        """Get the current icon name based on status."""
        if self._using_custom_icons and self._icon_generator:
            return self._icon_generator.get_icon_name(self._current_status)
        return self.ICON_MAP.get(self._current_status, "object-select-symbolic")

    def _get_attention_status(self) -> str:
        # SNI hosts only render AttentionIcon when Status == "NeedsAttention",
        # which we set for "threat" and "warning". Reuse the current status so
        # the alert icon matches what triggered attention; default to "threat"
        # for non-attention states (the value is unused by hosts then).
        if self._current_status in ("threat", "warning"):
            return self._current_status
        return "threat"

    def _get_attention_icon_name(self) -> str:
        # Mirror _get_icon_name so the AttentionIcon stays branded. Hosts
        # (Plasma 6, xapp-sn-watcher, ayatana) that prefer AttentionIcon over
        # Icon in NeedsAttention state otherwise render a generic theme icon
        # — which is the wrong icon in Flatpak where the host theme may not
        # even contain "dialog-error-symbolic".
        status = self._get_attention_status()
        if self._using_custom_icons and self._icon_generator:
            return self._icon_generator.get_icon_name(status)
        return self.ICON_MAP.get(status, "dialog-error-symbolic")

    def _get_icon_theme_path(self) -> str:
        """Get the icon theme path for custom icons."""
        if self._using_custom_icons and self._icon_generator:
            # Return the parent of the icon cache directory
            cache_dir = Path(get_tray_icon_cache_dir())
            # Icons are in ~/.local/share/icons/hicolor/22x22/apps
            # Theme path should be ~/.local/share/icons/hicolor
            return str(cache_dir.parent.parent)
        return ""

    def _empty_icon_pixmap(self) -> GLib.Variant:
        """Return an empty SNI icon pixmap array."""
        return GLib.Variant("a(iiay)", [])

    def _get_icon_pixmap(self, status: str | None = None) -> GLib.Variant:
        """
        Return a StatusNotifierItem IconPixmap fallback.

        Some tray hosts do not honor IconThemePath reliably, especially when
        the app is sandboxed. Keep IconName as the preferred path, but expose a
        real pixmap so those hosts can still render the icon.
        """
        if not (self._using_custom_icons and self._icon_generator):
            return self._empty_icon_pixmap()

        icon_status = status or self._current_status
        try:
            icon_path = self._icon_generator.get_icon_path(icon_status)
            return self._load_icon_pixmap(icon_path)
        except Exception as e:
            logger.debug(f"Failed to load tray icon pixmap for {icon_status}: {e}")
            return self._empty_icon_pixmap()

    def _load_icon_pixmap(self, icon_path: str) -> GLib.Variant:
        """Load a PNG icon as SNI's ARGB32 icon pixmap variant."""
        path = Path(icon_path)
        mtime_ns = path.stat().st_mtime_ns
        cache_key = (str(path), mtime_ns)
        cached = self._icon_pixmap_cache.get(cache_key)
        if cached is not None:
            return cached

        from PIL import Image

        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            width, height = rgba.size
            rgba_bytes = rgba.tobytes()

        argb_bytes = bytearray(len(rgba_bytes))
        for index in range(0, len(rgba_bytes), 4):
            red, green, blue, alpha = rgba_bytes[index : index + 4]
            argb_bytes[index : index + 4] = bytes((alpha, red, green, blue))

        pixmap = GLib.Variant("a(iiay)", [(width, height, bytes(argb_bytes))])
        # There are only a handful of status icons; keep the cache bounded.
        if len(self._icon_pixmap_cache) > len(self.ICON_MAP) * 2:
            self._icon_pixmap_cache.clear()
        self._icon_pixmap_cache[cache_key] = pixmap
        return pixmap

    def _get_tooltip(self) -> str:
        """Get the tooltip text."""
        status_display = self._current_status.capitalize()
        tooltip = _("ClamUI - {status}").format(status=status_display)
        if self._progress_label:
            tooltip += f" ({self._progress_label})"
        return tooltip

    def _get_sni_status(self) -> str:
        """Get the SNI status string."""
        return self.SNI_STATUS_MAP.get(self._current_status, "Active")

    def _handle_method_call(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        # Threat model: SNI is a same-session protocol — the DE's taskbar
        # widget must be able to call Activate, so we cannot restrict by
        # sender. All handlers below are limited to benign UI events
        # (show/hide window) and must never be given destructive side effects
        # without an additional trust boundary.
        logger.debug(f"Method call: {method_name} from {sender}")

        if method_name == "Activate":
            # Left click - toggle window
            self._send_action("toggle_window")
            invocation.return_value(None)

        elif method_name == "ContextMenu":
            # Right click - menu is handled by DBusMenu
            # The applet will query our Menu property and use DBusMenu
            invocation.return_value(None)

        elif method_name == "SecondaryActivate":
            # Middle click
            invocation.return_value(None)

        elif method_name == "Scroll":
            delta, orientation = parameters.unpack()
            logger.debug(f"Scroll: delta={delta}, orientation={orientation}")
            invocation.return_value(None)

        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod", f"Unknown method: {method_name}"
            )

    def _handle_get_property(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        property_name: str,
    ) -> GLib.Variant | None:
        """Handle D-Bus property reads for org.kde.StatusNotifierItem."""
        if property_name == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        elif property_name == "Id":
            return GLib.Variant("s", "clamui")
        elif property_name == "Title":
            return GLib.Variant("s", "ClamUI")
        elif property_name == "Status":
            return GLib.Variant("s", self._get_sni_status())
        elif property_name == "WindowId":
            return GLib.Variant("u", 0)
        elif property_name == "IconName":
            return GLib.Variant("s", self._get_icon_name())
        elif property_name == "IconPixmap":
            return self._get_icon_pixmap()
        elif property_name == "IconThemePath":
            return GLib.Variant("s", self._get_icon_theme_path())
        elif property_name == "OverlayIconName":
            return GLib.Variant("s", "")
        elif property_name == "OverlayIconPixmap":
            return self._empty_icon_pixmap()
        elif property_name == "AttentionIconName":
            return GLib.Variant("s", self._get_attention_icon_name())
        elif property_name == "AttentionIconPixmap":
            return self._get_icon_pixmap(self._get_attention_status())
        elif property_name == "AttentionMovieName":
            return GLib.Variant("s", "")
        elif property_name == "ToolTip":
            # ToolTip is (icon_name, icon_data, title, description)
            # icon_data is array of (width, height, pixel_data)
            tooltip = self._get_tooltip()
            return GLib.Variant("(sa(iiay)ss)", ("", [], "ClamUI", tooltip))
        elif property_name == "ItemIsMenu":
            return GLib.Variant("b", False)
        elif property_name == "Menu":
            return GLib.Variant("o", self.MENU_PATH)
        return None

    def _emit_signal(self, signal_name: str, args: GLib.Variant | None = None) -> None:
        """Emit a signal on the StatusNotifierItem interface."""
        if self._bus:
            try:
                self._bus.emit_signal(
                    None,
                    self.SNI_PATH,
                    "org.kde.StatusNotifierItem",
                    signal_name,
                    args,
                )
            except Exception as e:
                logger.error(f"Failed to emit {signal_name}: {e}")

    def _clear_watcher_retry(self) -> None:
        """Cancel a pending watcher retry timer."""
        if not self._watcher_retry_source_id:
            return

        source_remove = getattr(GLib, "source_remove", None)
        if source_remove is not None:
            source_remove(self._watcher_retry_source_id)
        self._watcher_retry_source_id = 0

    def _schedule_watcher_retry(self) -> None:
        """Retry watcher registration when the host is not ready yet."""
        if not self._running or self._watcher_registered or self._watcher_retry_source_id:
            return

        self._watcher_retry_source_id = GLib.timeout_add(
            self.WATCHER_RETRY_DELAY_MS,
            self._retry_register_with_watcher,
        )
        logger.info("No StatusNotifierWatcher available yet; retrying registration")

    def _retry_register_with_watcher(self) -> bool:
        """Timer callback to retry watcher registration."""
        self._watcher_retry_source_id = 0
        self._register_with_watcher()
        return False

    def _register_with_watcher(self) -> None:
        """Register with the first available StatusNotifierWatcher."""
        if not self._bus or self._watcher_registered:
            return

        self._try_register_with_watcher(0)

    def _try_register_with_watcher(self, watcher_index: int) -> None:
        """Attempt watcher registration, falling back across known watcher names."""
        if not self._bus or self._watcher_registered:
            return

        if watcher_index >= len(self.WATCHER_NAMES):
            self._schedule_watcher_retry()
            return

        watcher_name = self.WATCHER_NAMES[watcher_index]
        try:
            # Register the object path instead of a well-known item bus name.
            # Watchers then use the caller's unique bus name, which works
            # across Flatpak's D-Bus proxy and avoids broad org.kde.* ownership.
            self._bus.call(
                watcher_name,
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self.SNI_PATH,)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._on_register_complete,
                (watcher_name, watcher_index + 1),
            )
            logger.info(f"Registering with {watcher_name}...")
        except Exception as e:
            logger.debug(f"Could not start registration with {watcher_name}: {e}")
            self._try_register_with_watcher(watcher_index + 1)

    def _on_register_complete(self, source, result, user_data):
        """Callback when registration completes."""
        watcher_name, next_watcher_index = user_data
        try:
            source.call_finish(result)
            self._watcher_registered = True
            self._watcher_name = watcher_name
            self._clear_watcher_retry()
            logger.info(f"Successfully registered with {watcher_name}")
        except Exception as e:
            logger.debug(f"Failed to register with {watcher_name}: {e}")
            self._try_register_with_watcher(next_watcher_index)

    def _on_bus_acquired(
        self, connection: Gio.DBusConnection, name: str, user_data: object = None
    ) -> None:
        """Called when D-Bus connection is acquired."""
        logger.info(f"D-Bus connection acquired: {name}")
        self._bus = connection

        # Register the StatusNotifierItem interface
        node_info = Gio.DBusNodeInfo.new_for_xml(STATUS_NOTIFIER_ITEM_XML)
        self._sni_registration_id = connection.register_object(
            self.SNI_PATH,
            node_info.interfaces[0],
            self._handle_method_call,
            self._handle_get_property,
            None,
        )
        logger.info(f"StatusNotifierItem interface registered at {self.SNI_PATH}")

    def _on_name_acquired(
        self, connection: Gio.DBusConnection, name: str, user_data: object = None
    ) -> None:
        """Called when D-Bus name is acquired."""
        logger.info(f"D-Bus name acquired: {name}")
        self._register_with_watcher()

    def _on_name_lost(
        self, connection: Gio.DBusConnection, name: str, user_data: object = None
    ) -> None:
        """Called when D-Bus name is lost."""
        logger.warning(f"D-Bus name lost: {name}")
        self._watcher_registered = False
        self._watcher_name = None
        self._clear_watcher_retry()

    def _send_action(self, action: str) -> None:
        """Send an action event to the main application."""
        message = {"event": "menu_action", "action": action}
        self._send_message(message)

    def _send_message(self, message: dict) -> None:
        """Send a JSON message to stdout."""
        try:
            print(json.dumps(message), flush=True)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def update_status(self, status: str) -> None:
        """Update the tray icon based on protection status."""
        if status not in self.ICON_MAP:
            logger.warning(f"Unknown status '{status}', using 'protected'")
            status = "protected"

        self._current_status = status

        # Emit signals to update the icon
        self._emit_signal("NewIcon")
        self._emit_signal("NewAttentionIcon")
        self._emit_signal("NewToolTip")
        self._emit_signal("NewStatus", GLib.Variant("(s)", (self._get_sni_status(),)))

        logger.debug(f"Status updated to: {status}")

    def update_progress(self, percentage: int) -> None:
        """Show scan progress percentage."""
        if 0 < percentage <= 100:
            self._progress_label = f"{percentage}%"
        else:
            self._progress_label = ""

        self._emit_signal("NewToolTip")

    def update_window_visible(self, visible: bool) -> None:
        """Update window visibility state."""
        self._window_visible = visible
        # Update DBusMenu to reflect new Show/Hide label
        self._rebuild_menu()

    def update_profiles(self, profiles: list[dict], current_profile_id: str | None = None) -> None:
        """Update the profiles list."""
        self._profiles = profiles
        if current_profile_id is not None:
            self._current_profile_id = current_profile_id
        logger.debug(f"Updated profiles: {len(profiles)} profiles")
        # Schedule menu rebuild on the main thread so the new profiles
        # appear in the tray submenu. update_profiles can be invoked from
        # the IPC reader thread, so use idle_add for thread safety.
        GLib.idle_add(self._rebuild_menu)

    def handle_command(self, command: dict) -> None:
        """Handle a command from the main application."""
        action = command.get("action")

        if action == "update_status":
            status = command.get("status", "protected")
            GLib.idle_add(self.update_status, status)

        elif action == "update_progress":
            percentage = command.get("percentage", 0)
            GLib.idle_add(self.update_progress, percentage)

        elif action == "update_window_visible":
            visible = command.get("visible", True)
            GLib.idle_add(self.update_window_visible, visible)

        elif action == "update_profiles":
            profiles = command.get("profiles", [])
            current_profile_id = command.get("current_profile_id")
            GLib.idle_add(self.update_profiles, profiles, current_profile_id)

        elif action == "quit":
            logger.info("Received quit command")
            GLib.idle_add(self._quit)

        elif action == "ping":
            self._send_message({"event": "pong"})

        else:
            logger.warning(f"Unknown command: {action}")

    def _quit(self) -> None:
        """Quit the service."""
        self._running = False

        # Unregister D-Bus objects
        if self._bus:
            if self._sni_registration_id:
                self._bus.unregister_object(self._sni_registration_id)

        # Release bus name
        if self._bus_name_id:
            Gio.bus_unown_name(self._bus_name_id)
            self._bus_name_id = 0

        self._watcher_registered = False
        self._watcher_name = None
        self._clear_watcher_retry()

        # Quit main loop
        if self._loop:
            self._loop.quit()

    def run(self) -> None:
        """Run the tray service main loop."""
        # Export on our session-bus connection and register the object path
        # with the watcher. This avoids requiring a StatusNotifierItem-style
        # well-known bus name, which is fragile under Flatpak.
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        connection_name = connection.get_unique_name() or "session bus"
        self._on_bus_acquired(connection, connection_name)
        self._register_with_watcher()

        # Send ready event
        self._send_message({"event": "ready"})

        # Start stdin reader thread
        reader_thread = threading.Thread(target=self._read_stdin, daemon=True)
        reader_thread.start()

        # Run GLib main loop
        logger.info("Starting GLib main loop")
        self._loop = GLib.MainLoop()
        self._loop.run()
        logger.info("GLib main loop ended")

    # Maximum length (bytes) of a single IPC command line. The parent process
    # sends short JSON records; anything larger is either a bug or a hostile
    # input and must not be parsed.
    _MAX_IPC_LINE_BYTES = 64 * 1024

    def _read_stdin(self) -> None:
        """Read commands from stdin in a background thread."""
        try:
            for line in sys.stdin:
                if not self._running:
                    break

                if len(line) > self._MAX_IPC_LINE_BYTES:
                    logger.error(
                        "Dropping IPC line of %d bytes (cap %d)",
                        len(line),
                        self._MAX_IPC_LINE_BYTES,
                    )
                    continue

                line = line.strip()
                if not line:
                    continue

                try:
                    command = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    continue

                if not isinstance(command, dict):
                    logger.error("Dropping IPC command: not a JSON object")
                    continue

                self.handle_command(command)

        except Exception as e:
            logger.error(f"Error reading stdin: {e}")
        finally:
            GLib.idle_add(self._quit)


def main():
    """Main entry point for the tray service."""
    if not DBUS_AVAILABLE:
        logger.error("GIO D-Bus not available, exiting")
        sys.exit(1)

    try:
        service = TrayService()
        service.run()
    except Exception as e:
        logger.error(f"Tray service error: {e}")
        print(json.dumps({"event": "error", "message": str(e)}), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
