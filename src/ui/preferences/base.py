# ClamUI Preferences Base Module
"""
Shared base classes and utility functions for preference pages.

This module provides a mixin class with common functionality used across
all preference pages, including dialog helpers, permission indicators,
and file location displays.
"""

import logging
import os
import subprocess

import gi

logger = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ...core.i18n import _
from ...core.path_validation import validate_path
from ..compat import (
    create_entry_row,
    create_toolbar_view,
    safe_set_subtitle_selectable,
)
from ..utils import resolve_icon_name


def styled_prefix_icon(icon_name: str) -> Gtk.Image:
    """
    Create a properly styled prefix icon for ActionRow widgets.

    This helper creates icons following GNOME Settings visual patterns:
    - 12px start margin for proper spacing
    - dim-label CSS class for subtle appearance

    Args:
        icon_name: The symbolic icon name (e.g., "folder-symbolic")

    Returns:
        Configured Gtk.Image ready to be added as row prefix
    """
    icon = Gtk.Image.new_from_icon_name(resolve_icon_name(icon_name))
    icon.set_margin_start(12)
    icon.add_css_class("dim-label")
    return icon


def create_status_row(
    title: str,
    status_ok: bool,
    ok_message: str,
    error_message: str,
) -> tuple[Adw.ActionRow, Gtk.Image]:
    """
    Create a status row with semantic icon (replaces emoji in subtitles).

    This helper follows GNOME Settings visual patterns by using proper
    semantic icons instead of emoji characters for status indication.

    Args:
        title: Row title text
        status_ok: Whether the status is OK (True) or has an error (False)
        ok_message: Message to show when status is OK
        error_message: Message to show when status has an error

    Returns:
        Tuple of (row, status_icon) - store status_icon for later updates
    """
    row = Adw.ActionRow()
    row.set_title(title)

    if status_ok:
        row.set_subtitle(ok_message)
        status_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("object-select-symbolic"))
        status_icon.add_css_class("success")
    else:
        row.set_subtitle(error_message)
        status_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
        status_icon.add_css_class("warning")

    row.add_suffix(status_icon)
    return row, status_icon


def update_status_row(
    row: Adw.ActionRow,
    status_icon: Gtk.Image,
    status_ok: bool,
    ok_message: str,
    error_message: str,
) -> None:
    """
    Update an existing status row with new status.

    Args:
        row: The ActionRow to update
        status_icon: The status icon widget to update
        status_ok: Whether the status is OK (True) or has an error (False)
        ok_message: Message to show when status is OK
        error_message: Message to show when status has an error
    """
    if status_ok:
        row.set_subtitle(ok_message)
        status_icon.set_from_icon_name(resolve_icon_name("object-select-symbolic"))
        status_icon.remove_css_class("warning")
        status_icon.add_css_class("success")
    else:
        row.set_subtitle(error_message)
        status_icon.set_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
        status_icon.remove_css_class("success")
        status_icon.add_css_class("warning")


def create_navigation_row(
    title: str,
    subtitle: str | None = None,
    icon_name: str | None = None,
) -> Adw.ActionRow:
    """
    Create a navigation row with chevron suffix.

    This helper creates rows following GNOME Settings visual patterns
    for navigation items that open dialogs or external links.

    Args:
        title: Row title text
        subtitle: Optional subtitle text
        icon_name: Optional prefix icon name

    Returns:
        Configured Adw.ActionRow ready to connect to "activated" signal
    """
    row = Adw.ActionRow()
    row.set_title(title)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_activatable(True)

    if icon_name:
        icon = styled_prefix_icon(icon_name)
        row.add_prefix(icon)

    # Add chevron to indicate it's clickable
    chevron = Gtk.Image.new_from_icon_name(resolve_icon_name("go-next-symbolic"))
    chevron.add_css_class("dim-label")
    row.add_suffix(chevron)

    return row


def create_password_entry_row(title: str) -> Adw.ActionRow:
    """
    Create a password entry row compatible with libadwaita 1.0+.

    Replaces Adw.PasswordEntryRow (1.2+) with an ActionRow configured
    for password input with visibility toggle button.

    Args:
        title: The title/label for the entry row

    Returns:
        Configured Adw.ActionRow with password functionality
    """
    row = create_entry_row()
    row.set_title(title)
    row.set_input_purpose(Gtk.InputPurpose.PASSWORD)
    row.set_show_apply_button(False)

    # Get the underlying entry widget
    entry = row._compat_entry

    # Add visibility toggle button as suffix
    toggle_button = Gtk.ToggleButton()
    toggle_button.set_icon_name("view-conceal-symbolic")
    toggle_button.set_valign(Gtk.Align.CENTER)
    toggle_button.add_css_class("flat")
    toggle_button.set_tooltip_text(_("Show password"))

    def on_toggle(btn):
        visible = btn.get_active()
        entry.set_visibility(visible)
        btn.set_icon_name("view-reveal-symbolic" if visible else "view-conceal-symbolic")
        btn.set_tooltip_text(_("Hide password") if visible else _("Show password"))

    toggle_button.connect("toggled", on_toggle)
    row.add_suffix(toggle_button)

    # Start with text hidden (after widget is realized)
    def hide_text():
        entry.set_visibility(False)
        return False  # Don't repeat

    GLib.idle_add(hide_text)

    return row


def create_spin_row(
    title: str,
    subtitle: str,
    min_val: float,
    max_val: float,
    step: float = 1,
    page_step: float = 10,
) -> tuple[Adw.ActionRow, Gtk.SpinButton]:
    """
    Create a spin row compatible with libadwaita 1.0+.

    Replaces Adw.SpinRow (1.2+) with Adw.ActionRow + Gtk.SpinButton suffix.

    Args:
        title: The title for the row
        subtitle: The subtitle/description for the row
        min_val: Minimum value for the spin button
        max_val: Maximum value for the spin button
        step: Step increment for up/down buttons (default: 1)
        page_step: Page increment for larger jumps (default: 10)

    Returns:
        Tuple of (row, spin_button) - use spin_button for get/set_value()
    """
    row = Adw.ActionRow()
    row.set_title(title)
    if subtitle:
        row.set_subtitle(subtitle)

    adjustment = Gtk.Adjustment(
        value=min_val,
        lower=min_val,
        upper=max_val,
        step_increment=step,
        page_increment=page_step,
        page_size=0,
    )

    spin_button = Gtk.SpinButton()
    spin_button.set_adjustment(adjustment)
    spin_button.set_numeric(True)
    spin_button.set_valign(Gtk.Align.CENTER)

    row.add_suffix(spin_button)
    row.set_activatable_widget(spin_button)

    return row, spin_button


def _get_widget_method(widgets_dict: dict, key: str, method_name: str):
    """
    Get a callable widget method safely.

    Args:
        widgets_dict: Dictionary containing widget references
        key: Widget key in dictionary
        method_name: Method name to look up on the widget

    Returns:
        Callable widget method, or None if missing/invalid
    """
    widget = widgets_dict.get(key)
    if widget is None:
        logger.warning("Missing preferences widget for key: %s", key)
        return None

    method = getattr(widget, method_name, None)
    if not callable(method):
        logger.warning("Widget '%s' does not support method '%s'", key, method_name)
        return None

    return method


def _call_widget_method(widgets_dict: dict, key: str, method_name: str):
    """
    Call a widget method safely.

    Returns:
        Method return value, or None if widget/method is unavailable or call fails
    """
    method = _get_widget_method(widgets_dict, key, method_name)
    if method is None:
        return None

    try:
        return method()
    except Exception:
        logger.warning("Failed calling %s() on widget '%s'", method_name, key, exc_info=True)
        return None


def _set_widget_method(widgets_dict: dict, key: str, method_name: str, value) -> bool:
    """
    Set widget state safely.

    Returns:
        True if the setter method was called successfully, False otherwise
    """
    method = _get_widget_method(widgets_dict, key, method_name)
    if method is None:
        return False

    try:
        method(value)
    except Exception:
        logger.warning("Failed calling %s() on widget '%s'", method_name, key, exc_info=True)
        return False

    return True


def get_widget_text(widgets_dict: dict, key: str, strip: bool = False) -> str | None:
    """
    Read text from a widget safely.

    Args:
        widgets_dict: Dictionary containing widget references
        key: Widget key in dictionary
        strip: Whether to strip leading/trailing whitespace

    Returns:
        Text value, or None if unavailable
    """
    value = _call_widget_method(widgets_dict, key, "get_text")
    if value is None:
        return None

    text = value if isinstance(value, str) else str(value)
    return text.strip() if strip else text


def get_widget_active(widgets_dict: dict, key: str) -> bool | None:
    """
    Read active state from a switch widget safely.

    Args:
        widgets_dict: Dictionary containing widget references
        key: Widget key in dictionary

    Returns:
        Boolean active state, or None if unavailable
    """
    value = _call_widget_method(widgets_dict, key, "get_active")
    if value is None:
        return None
    return bool(value)


def get_widget_selected(widgets_dict: dict, key: str) -> int | None:
    """
    Read selected index from a combo widget safely.

    Args:
        widgets_dict: Dictionary containing widget references
        key: Widget key in dictionary

    Returns:
        Selected index as int, or None if unavailable/invalid
    """
    value = _call_widget_method(widgets_dict, key, "get_selected")
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid selected value for widget '%s': %r", key, value)
        return None


def get_widget_int_value(widgets_dict: dict, key: str) -> int | None:
    """
    Read numeric value from a spin widget safely and convert to int.

    Args:
        widgets_dict: Dictionary containing widget references
        key: Widget key in dictionary

    Returns:
        Integer value, or None if unavailable/invalid
    """
    value = _call_widget_method(widgets_dict, key, "get_value")
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        logger.warning("Invalid numeric value for widget '%s': %r", key, value)
        return None


def set_widget_active(widgets_dict: dict, key: str, value: bool) -> bool:
    """Safely call set_active on a widget."""
    return _set_widget_method(widgets_dict, key, "set_active", bool(value))


def set_widget_selected(widgets_dict: dict, key: str, value: int) -> bool:
    """Safely call set_selected on a widget."""
    return _set_widget_method(widgets_dict, key, "set_selected", int(value))


def set_widget_value(widgets_dict: dict, key: str, value: int | float) -> bool:
    """Safely call set_value on a widget."""
    return _set_widget_method(widgets_dict, key, "set_value", value)


def set_widget_text(widgets_dict: dict, key: str, value: str) -> bool:
    """Safely call set_text on a widget."""
    return _set_widget_method(widgets_dict, key, "set_text", value)


def populate_bool_field(config, widgets_dict: dict, key: str, default: bool = False) -> None:
    """
    Populate a boolean switch widget from config.

    Args:
        config: Parsed config object with has_key() and get_value() methods
        widgets_dict: Dictionary containing widget references
        key: Config key name (widget key must match)
        default: Default value if key is missing (False = "no", True = "yes")
    """
    if config.has_key(key):
        value = config.get_value(key)
        is_yes = value.lower() == "yes" if value else False
        set_widget_active(widgets_dict, key, is_yes)
    else:
        # Key missing - use default value
        set_widget_active(widgets_dict, key, default)


def populate_int_field(config, widgets_dict: dict, key: str) -> None:
    """
    Populate an integer spin row widget from config.

    Args:
        config: Parsed config object with has_key() and get_value() methods
        widgets_dict: Dictionary containing widget references
        key: Config key name (widget key must match)
    """
    if config.has_key(key):
        try:
            set_widget_value(widgets_dict, key, int(config.get_value(key)))
        except (ValueError, TypeError) as e:
            logger.debug("Invalid integer value for config key '%s': %s", key, e)


def populate_text_field(config, widgets_dict: dict, key: str) -> None:
    """
    Populate a text entry widget from config.

    Args:
        config: Parsed config object with has_key() and get_value() methods
        widgets_dict: Dictionary containing widget references
        key: Config key name (widget key must match)
    """
    if config.has_key(key):
        value = config.get_value(key)
        if value is not None:
            set_widget_text(widgets_dict, key, value)


def populate_multivalue_field(config, widgets_dict: dict, key: str, separator: str = ", ") -> None:
    """
    Populate a text entry widget with comma-separated values from config.

    Args:
        config: Parsed config object with has_key() and get_values() methods
        widgets_dict: Dictionary containing widget references
        key: Config key name (widget key must match)
        separator: Separator to join multiple values (default: ", ")
    """
    if config.has_key(key):
        values = config.get_values(key)
        if values:
            set_widget_text(widgets_dict, key, separator.join(values))


class PreferencesPageMixin:
    """
    Mixin class providing shared utility methods for preference pages.

    This mixin provides common functionality used across multiple preference pages:
    - Permission indicators for admin-required settings
    - File manager integration for configuration files
    - Error and success dialog helpers
    - File location display widgets

    Classes using this mixin should inherit from a GTK window class (like
    Adw.PreferencesWindow) so that dialogs can be presented relative to `self`.
    """

    def _create_permission_indicator(self) -> Gtk.Box:
        """
        Create a permission indicator widget showing a lock icon.

        Used to indicate that modifying settings in a group requires
        administrator (root) privileges via pkexec elevation.

        Icon options:
        - system-lock-screen-symbolic: Standard lock icon (used)
        - changes-allow-symbolic: Alternative shield/lock icon

        Returns:
            A Gtk.Box containing the lock icon with tooltip.  When the app is
            already running as root the box is returned empty: no elevation is
            required, so flagging the group as admin-only would be misleading.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        # Running as root: every config path is directly writable and the save
        # flow skips pkexec entirely, so omit the lock affordance.
        from ...core.privileged_paths import is_running_as_root

        if is_running_as_root():
            return box

        # Create lock icon - using system-lock-screen-symbolic
        # Alternative: changes-allow-symbolic for a shield-style icon
        lock_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("system-lock-screen-symbolic"))
        lock_icon.add_css_class("dim-label")
        lock_icon.set_tooltip_text(_("Requires administrator privileges to modify"))

        box.append(lock_icon)
        return box

    def _open_folder_in_file_manager(self, folder_path: str):
        """
        Open a folder in the system's default file manager.

        In Flatpak, system paths (/etc, /usr, etc.) don't exist inside
        the sandbox, so we use flatpak-spawn --host to both check existence
        and launch xdg-open on the host.

        Args:
            folder_path: The folder path to open
        """
        is_valid, error = validate_path(folder_path)
        if not is_valid:
            self._show_simple_dialog(
                _("Invalid Path"),
                error or _("The path is not valid."),
            )
            return

        from ...core.flatpak import is_flatpak

        if is_flatpak():
            try:
                # Check if directory exists on the host (test -d for directories)
                check = subprocess.run(
                    ["flatpak-spawn", "--host", "test", "-d", folder_path],
                    capture_output=True,
                    timeout=5,
                )
                if check.returncode != 0:
                    self._show_simple_dialog(
                        _("Folder Not Found"),
                        _("The folder '{path}' does not exist.").format(path=folder_path),
                    )
                    return
                # Open on the host filesystem
                subprocess.Popen(
                    ["flatpak-spawn", "--host", "xdg-open", folder_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception as e:
                self._show_simple_dialog(
                    _("Error Opening Folder"),
                    _("Could not open folder: {error}").format(error=str(e)),
                )
        else:
            if not os.path.isdir(folder_path):
                self._show_simple_dialog(
                    _("Folder Not Found"),
                    _("The folder '{path}' does not exist.").format(path=folder_path),
                )
                return
            try:
                subprocess.Popen(
                    ["xdg-open", folder_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception as e:
                self._show_simple_dialog(
                    _("Error Opening Folder"),
                    _("Could not open folder: {error}").format(error=str(e)),
                )

    def _show_simple_dialog(self, title: str, message: str):
        """
        Show a simple message dialog with an OK button.

        Uses Adw.Window for compatibility with libadwaita < 1.5.

        Args:
            title: Dialog title/heading
            message: Message body text
        """
        dialog = Adw.Window()
        dialog.set_title(title)
        dialog.set_default_size(350, -1)
        dialog.set_modal(True)
        dialog.set_deletable(True)
        # Resolve the transient parent window.
        # 'self' may be a Gtk.Window (e.g. PreferencesWindow) or a plain mixin
        # helper (e.g. _ScannerPageHelper) that stores the window reference.
        parent = getattr(self, "_parent_window", None) or self
        try:
            dialog.set_transient_for(parent)
        except TypeError:
            logger.debug("No valid transient parent available for dialog", exc_info=True)

        # Create content
        toolbar_view = create_toolbar_view()
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(24)

        # Message label
        label = Gtk.Label()
        label.set_text(message)
        label.set_wrap(True)
        label.set_xalign(0)
        content_box.append(label)

        # OK button
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(12)

        ok_button = Gtk.Button(label=_("OK"))
        ok_button.add_css_class("suggested-action")
        ok_button.connect("clicked", lambda btn: dialog.close())
        button_box.append(ok_button)

        content_box.append(button_box)
        toolbar_view.set_content(content_box)
        dialog.set_content(toolbar_view)

        dialog.present()

    def _show_error_dialog(self, title: str, message: str):
        """
        Show an error dialog to the user.

        Args:
            title: Dialog title
            message: Error message text
        """
        self._show_simple_dialog(title, message)

    def _show_success_dialog(self, title: str, message: str):
        """
        Show a success dialog to the user.

        Args:
            title: Dialog title
            message: Success message text
        """
        self._show_simple_dialog(title, message)

    def _create_file_location_group(
        self,
        page: Adw.PreferencesPage,
        title: str,
        file_path: str,
        description: str,
        on_detect=None,
        on_browse=None,
    ):
        """
        Create a group showing the configuration file location.

        Displays the filesystem path to the configuration file so users
        know where to find it, with buttons to open the containing folder
        and optionally detect or browse for the config file.

        Args:
            page: The preferences page to add the group to
            title: Title for the group
            file_path: The filesystem path to display
            description: Description text for the group
            on_detect: Optional callback for auto-detecting the config path
            on_browse: Optional callback for browsing for the config file

        Returns:
            The Adw.ActionRow displaying the file path (for dynamic updates)
        """
        group = Adw.PreferencesGroup()
        group.set_title(title)
        group.set_description(description)

        # File path row
        path_row = Adw.ActionRow()
        path_row.set_title(_("File Location"))
        path_row.set_subtitle(GLib.markup_escape_text(file_path))
        safe_set_subtitle_selectable(path_row, True)

        # Add folder icon as prefix
        folder_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("folder-open-symbolic"))
        folder_icon.set_margin_start(6)
        path_row.add_prefix(folder_icon)

        # Add "Open folder" button as suffix
        open_folder_button = Gtk.Button()
        open_folder_button.set_label(_("Open Folder"))
        open_folder_button.set_valign(Gtk.Align.CENTER)
        open_folder_button.add_css_class("flat")
        open_folder_button.set_tooltip_text(_("Open containing folder in file manager"))

        def _open_current_folder(_button):
            # Resolve from the row so Detect/Browse updates are respected.
            current_path = file_path
            get_subtitle = getattr(path_row, "get_subtitle", None)
            if callable(get_subtitle):
                subtitle = get_subtitle()
                if isinstance(subtitle, str) and subtitle.strip():
                    current_path = subtitle.strip()

            self._open_folder_in_file_manager(os.path.dirname(current_path))

        # Connect click handler to open the current containing folder
        open_folder_button.connect("clicked", _open_current_folder)

        path_row.add_suffix(open_folder_button)

        # Optionally add Detect button
        if on_detect is not None:
            detect_button = Gtk.Button()
            detect_button.set_label(_("Detect"))
            detect_button.set_valign(Gtk.Align.CENTER)
            detect_button.add_css_class("flat")
            detect_button.set_tooltip_text(_("Auto-detect configuration file location"))
            detect_button.connect("clicked", lambda btn: on_detect())
            path_row.add_suffix(detect_button)

        # Optionally add Browse button
        if on_browse is not None:
            browse_button = Gtk.Button()
            browse_button.set_label(_("Browse"))
            browse_button.set_valign(Gtk.Align.CENTER)
            browse_button.add_css_class("flat")
            browse_button.set_tooltip_text(_("Browse for configuration file"))
            browse_button.connect("clicked", lambda btn: on_browse())
            path_row.add_suffix(browse_button)

        # Make it look like an informational row
        path_row.add_css_class("property")

        group.add(path_row)
        page.add(group)

        return path_row
