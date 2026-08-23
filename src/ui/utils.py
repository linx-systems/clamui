"""UI utility functions for ClamUI."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gtk

# Fallbacks for icon names that may be missing in some icon themes (e.g., KDE).
ICON_FALLBACKS: dict[str, tuple[str, ...]] = {
    "software-update-available-symbolic": (
        "system-software-update-symbolic",
        "view-refresh-symbolic",
        "emblem-synchronizing-symbolic",
    ),
    "security-high-symbolic": (
        "security-high",
        "emblem-ok-symbolic",
        "object-select-symbolic",
    ),
    "security-medium-symbolic": (
        "security-medium",
        "dialog-warning-symbolic",
        "object-select-symbolic",
    ),
    "shield-safe-symbolic": (
        "security-high-symbolic",
        "emblem-ok-symbolic",
        "object-select-symbolic",
    ),
    "folder-saved-search-symbolic": (
        "folder-symbolic",
        "folder-open-symbolic",
        "document-open-recent-symbolic",
    ),
    "action-unavailable-symbolic": (
        "dialog-warning-symbolic",
        "dialog-information-symbolic",
        "edit-delete-symbolic",
    ),
    "emblem-synchronizing-symbolic": (
        "view-refresh-symbolic",
        "media-playback-start-symbolic",
    ),
    "emblem-system-symbolic": ("preferences-system-symbolic",),
    "preferences-system-time-symbolic": (
        "x-office-calendar-symbolic",
        "alarm-symbolic",
        "preferences-system-symbolic",
    ),
    "system-run-symbolic": (
        "utilities-terminal-symbolic",
        "preferences-system-symbolic",
    ),
    "utilities-terminal-symbolic": (
        "system-run-symbolic",
        "preferences-system-symbolic",
    ),
    "applications-science-symbolic": (
        "applications-system-symbolic",
        "preferences-system-symbolic",
    ),
    "applications-system-symbolic": ("preferences-system-symbolic",),
    "object-select-symbolic": (
        "emblem-ok-symbolic",
        "emblem-default-symbolic",
        "dialog-information-symbolic",
    ),
    "dialog-question-symbolic": (
        "dialog-information-symbolic",
        "help-about-symbolic",
    ),
    "system-lock-screen-symbolic": (
        "changes-prevent-symbolic",
        "channel-secure-symbolic",
        "security-high-symbolic",
        "preferences-system-symbolic",
    ),
    "network-server-symbolic": (
        "network-workgroup-symbolic",
        "preferences-system-symbolic",
    ),
    "help-about-symbolic": ("dialog-information-symbolic",),
    "info-symbolic": ("dialog-information-symbolic",),
    "web-browser-symbolic": (
        "network-server-symbolic",
        "system-file-manager-symbolic",
    ),
    "network-workgroup-symbolic": ("network-server-symbolic",),
    "document-properties-symbolic": (
        "dialog-information-symbolic",
        "document-open-symbolic",
    ),
    "drive-harddisk-symbolic": ("drive-harddisk", "folder-symbolic"),
    "avatar-default-symbolic": ("user-identity-symbolic", "dialog-information-symbolic"),
    "alarm-symbolic": ("x-office-calendar-symbolic", "dialog-information-symbolic"),
}


def resolve_icon_name(icon_name: str | None, fallback: str | None = None) -> str | None:
    """
    Resolve an icon name to one that exists in the current icon theme.

    This avoids missing icons on themes that don't ship every symbolic name.
    """
    if not icon_name:
        return icon_name

    display = Gdk.Display.get_default()
    if display is None:
        return fallback or icon_name

    theme = Gtk.IconTheme.get_for_display(display)
    candidates: list[str] = []

    def add_candidate(name: str | None) -> None:
        if name and name not in candidates:
            candidates.append(name)

    add_candidate(icon_name)
    if icon_name.endswith("-symbolic"):
        add_candidate(icon_name[: -len("-symbolic")])
    else:
        add_candidate(f"{icon_name}-symbolic")

    for candidate in ICON_FALLBACKS.get(icon_name, ()):
        add_candidate(candidate)

    add_candidate(fallback)
    add_candidate("dialog-information-symbolic")
    add_candidate("dialog-warning-symbolic")
    add_candidate("dialog-error-symbolic")
    add_candidate("io.github.linx_systems.ClamUI")

    for candidate in candidates:
        if theme.has_icon(candidate):
            return candidate

    return icon_name


def add_row_icon(row: Adw.ActionRow | Adw.ExpanderRow, icon_name: str) -> Gtk.Image:
    """
    Add an icon to an ActionRow or ExpanderRow as a prefix widget.

    This is the modern replacement for the deprecated set_icon_name() method
    which was deprecated in libadwaita 1.3.

    Args:
        row: The ActionRow or ExpanderRow to add the icon to
        icon_name: The symbolic icon name (e.g., "folder-symbolic")

    Returns:
        The Gtk.Image widget, useful for dynamic icon updates
    """
    icon = Gtk.Image.new_from_icon_name(resolve_icon_name(icon_name))
    row.add_prefix(icon)
    return icon


def enable_escape_to_close(window: Gtk.Window) -> None:
    """
    Make Escape close a dialog window.

    The project's dialogs are Adw.Window subclasses (for libadwaita 1.1
    compatibility), which — unlike Gtk.Dialog/Adw.MessageDialog — do not
    bind Escape by default. GNOME HIG expects every dialog to close on
    Escape; call this from the dialog's __init__.

    Closing goes through Gtk.Window.close(), so close-request handlers
    (the same path as the titlebar close button) still run.
    """

    def _on_escape(widget, args):
        window.close()
        return True

    controller = Gtk.ShortcutController()
    controller.add_shortcut(
        Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("Escape"),
            Gtk.CallbackAction.new(_on_escape),
        )
    )
    window.add_controller(controller)


def present_dialog(dialog: Adw.Window, parent: Gtk.Window) -> None:
    """
    Present a modal dialog window with proper parent relationship.

    This helper provides a consistent way to present Adw.Window-based dialogs
    that mimics the Adw.Dialog.present(parent) API pattern. Use this for
    backwards compatibility with libadwaita < 1.5.

    Args:
        dialog: The Adw.Window dialog to present
        parent: The parent window for the dialog
    """
    dialog.set_transient_for(parent)
    dialog.present()
