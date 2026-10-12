"""Dialog for installing the Flatpak privileged helper."""

import logging
import threading
from collections.abc import Callable
from inspect import ismethod
from weakref import WeakMethod

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ..core.i18n import _
from ..core.privileged_helper import (
    PrivilegedHelperInstallResult,
    install_matching_privileged_helper,
)
from .compat import create_toolbar_view
from .utils import enable_escape_to_close

logger = logging.getLogger(__name__)


class PrivilegedHelperDialog(Adw.Window):
    """Offer to install the version-matched privileged host helper."""

    def __init__(
        self,
        on_installed: Callable[[], None] | None = None,
        on_dismissed: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._on_installed = on_installed
        self._on_dismissed = on_dismissed
        self._installing = False
        self._installation_succeeded = False
        self._dismissal_notified = False
        self._held_application = None

        self._setup_dialog()
        self._setup_ui()

    def _setup_dialog(self) -> None:
        self.set_title(_("Install Privileged Helper"))
        self.set_default_size(420, -1)
        self.set_modal(True)
        self.set_deletable(True)
        enable_escape_to_close(self)
        self.connect("close-request", self._on_close_request)

    def _setup_ui(self) -> None:
        toolbar_view = create_toolbar_view()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_margin_top(12)
        content.set_margin_bottom(24)

        icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        icon.set_pixel_size(48)
        icon.set_halign(Gtk.Align.CENTER)
        content.append(icon)

        title = Gtk.Label(label=_("Privileged Helper Required"))
        title.add_css_class("title-2")
        title.set_halign(Gtk.Align.CENTER)
        content.append(title)

        description = Gtk.Label(
            label=_(
                "ClamUI needs its matching privileged helper to save system "
                "configuration. It will download the exact release helper, verify "
                "the download, then ask once for administrator authorization."
            )
        )
        description.set_wrap(True)
        description.set_justify(Gtk.Justification.CENTER)
        description.set_xalign(0.5)
        description.add_css_class("dim-label")
        content.append(description)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.set_halign(Gtk.Align.CENTER)
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        status_box.append(self._spinner)

        self._status_label = Gtk.Label(label=_("Ready to install the helper."))
        self._status_label.set_wrap(True)
        self._status_label.set_justify(Gtk.Justification.CENTER)
        self._status_label.set_xalign(0.5)
        status_box.append(self._status_label)
        content.append(status_box)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        buttons.set_halign(Gtk.Align.CENTER)
        buttons.set_margin_top(8)

        self._cancel_button = Gtk.Button(label=_("Not Now"))
        self._cancel_button.connect("clicked", self._on_cancel_clicked)
        buttons.append(self._cancel_button)

        self._install_button = Gtk.Button(label=_("Install Helper"))
        self._install_button.add_css_class("suggested-action")
        self._install_button.connect("clicked", self._on_install_clicked)
        buttons.append(self._install_button)
        content.append(buttons)

        toolbar_view.set_content(content)
        self.set_content(toolbar_view)

    def _on_cancel_clicked(self, _button: Gtk.Button) -> None:
        if not self._installing:
            self.close()

    def _on_close_request(self, _window: Adw.Window) -> bool:
        if self._installing:
            return True
        if not self._installation_succeeded and not self._dismissal_notified:
            self._dismissal_notified = True
            if self._on_dismissed is not None:
                self._on_dismissed()
        return False

    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        if self._installing or self._installation_succeeded:
            return

        self._installing = True
        self.set_deletable(False)
        self._cancel_button.set_sensitive(False)
        self._install_button.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()
        self._status_label.set_text(_("Installing helper…"))

        get_application = getattr(self, "get_application", None)
        application = get_application() if get_application is not None else None
        if application is not None:
            try:
                application.hold()
            except Exception:
                logger.exception("Failed to hold application for privileged helper installation")
                self._finish_install(None, True)
                return
            self._held_application = application

        try:
            threading.Thread(target=self._install_in_background, daemon=False).start()
        except Exception:
            logger.exception("Failed to start privileged helper installation")
            self._finish_install(None, True)

    def _install_in_background(self) -> None:
        try:
            result = install_matching_privileged_helper()
        except Exception:  # Defensive boundary around host integration.
            logger.exception("Privileged helper installation failed unexpectedly")
            GLib.idle_add(self._finish_install, None, True)
        else:
            GLib.idle_add(self._finish_install, result, False)

    def _finish_install(
        self,
        result: PrivilegedHelperInstallResult | None,
        unexpected_failure: bool,
    ) -> bool:
        """Apply a completed installation result on the GTK main thread."""
        self._release_application_hold()
        self._installing = False
        self.set_deletable(True)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if result is not None and result.success:
            self._installation_succeeded = True
            self._status_label.set_text(_("Helper installed successfully."))
            self._install_button.set_visible(False)
            self._cancel_button.set_label(_("Close"))
            self._cancel_button.set_sensitive(True)
            if self._on_installed is not None:
                self._on_installed()
            return False

        self._cancel_button.set_sensitive(True)
        self._install_button.set_sensitive(True)
        if unexpected_failure:
            message = _(
                "An unexpected error occurred while installing the helper. Please try again."
            )
        elif result is not None and result.message:
            message = result.message
        else:
            message = _("The helper could not be installed. Please try again.")
        self._status_label.set_text(_("Installation failed: {message}").format(message=message))
        return False

    def _release_application_hold(self) -> None:
        """Release the application hold acquired for an in-progress install."""
        application = self._held_application
        self._held_application = None
        if application is not None:
            application.release()


CallbackReference = Callable[[], None] | WeakMethod

_active_dialog: PrivilegedHelperDialog | None = None
_active_install_callbacks: list[CallbackReference] = []
_active_dismiss_callbacks: list[CallbackReference] = []


def present_privileged_helper_dialog(
    parent: Gtk.Window,
    on_installed: Callable[[], None] | None = None,
    on_dismissed: Callable[[], None] | None = None,
) -> PrivilegedHelperDialog:
    """Present the process-wide helper dialog, reusing it when already open."""
    global _active_dialog

    if on_installed is not None:
        _register_install_callback(on_installed)
    if on_dismissed is not None:
        _register_dismiss_callback(on_dismissed)
    if _active_dialog is not None:
        _active_dialog.set_transient_for(parent)
        _active_dialog.present()
        return _active_dialog

    dialog = PrivilegedHelperDialog(
        on_installed=_notify_install_callbacks,
        on_dismissed=_notify_dismiss_callbacks,
    )
    _active_dialog = dialog
    dialog.connect("close-request", _clear_active_dialog_on_close)
    dialog.set_transient_for(parent)
    dialog.present()
    return dialog


def _register_install_callback(callback: Callable[[], None]) -> None:
    """Track a live success callback without retaining a bound owner."""
    _prune_install_callbacks()
    if any(_resolve_callback(reference) == callback for reference in _active_install_callbacks):
        return

    if ismethod(callback) and callback.__self__ is not None:
        reference: CallbackReference = WeakMethod(callback)
    else:
        reference = callback
    _active_install_callbacks.append(reference)


def _register_dismiss_callback(callback: Callable[[], None]) -> None:
    """Track a live dismissal callback without retaining a bound owner."""
    _prune_dismiss_callbacks()
    if any(_resolve_callback(reference) == callback for reference in _active_dismiss_callbacks):
        return

    if ismethod(callback) and callback.__self__ is not None:
        reference: CallbackReference = WeakMethod(callback)
    else:
        reference = callback
    _active_dismiss_callbacks.append(reference)


def _resolve_callback(reference: CallbackReference) -> Callable[[], None] | None:
    if isinstance(reference, WeakMethod):
        return reference()
    return reference


def _prune_install_callbacks() -> None:
    _active_install_callbacks[:] = [
        reference
        for reference in _active_install_callbacks
        if _resolve_callback(reference) is not None
    ]


def _prune_dismiss_callbacks() -> None:
    _active_dismiss_callbacks[:] = [
        reference
        for reference in _active_dismiss_callbacks
        if _resolve_callback(reference) is not None
    ]


def _notify_install_callbacks() -> None:
    """Notify every interested surface after the helper was installed."""
    _prune_install_callbacks()
    for reference in tuple(_active_install_callbacks):
        callback = _resolve_callback(reference)
        if callback is not None:
            callback()


def _notify_dismiss_callbacks() -> None:
    """Notify every interested surface after the helper dialog was dismissed."""
    _prune_dismiss_callbacks()
    for reference in tuple(_active_dismiss_callbacks):
        callback = _resolve_callback(reference)
        if callback is not None:
            callback()


def _clear_active_dialog_on_close(dialog: PrivilegedHelperDialog) -> bool:
    """Release presenter state after the active dialog is actually closing."""
    global _active_dialog
    if dialog is _active_dialog and not dialog._installing:
        _active_dialog = None
        _active_install_callbacks.clear()
        _active_dismiss_callbacks.clear()
    return False
