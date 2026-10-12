"""Observable state-transition tests for the privileged-helper dialog."""

import gc
import sys
import weakref
from unittest import mock


def _clear_src_modules() -> None:
    for name in [module for module in sys.modules if module.startswith("src.")]:
        del sys.modules[name]


class _SynchronousThread:
    def __init__(self, *, target, **_kwargs):
        self._target = target

    def start(self) -> None:
        self._target()


def _successful_result():
    from src.core.privileged_helper import (
        PrivilegedHelperInstallResult,
        PrivilegedHelperState,
        PrivilegedHelperStatus,
    )

    status = PrivilegedHelperStatus(PrivilegedHelperState.INSTALLED, "helper.deb", "1.0")
    return PrivilegedHelperInstallResult(True, status, "Installed")


def _failed_result():
    from src.core.privileged_helper import (
        PrivilegedHelperInstallResult,
        PrivilegedHelperState,
        PrivilegedHelperStatus,
    )

    status = PrivilegedHelperStatus(PrivilegedHelperState.INSTALLABLE, "helper.deb", "1.0")
    return PrivilegedHelperInstallResult(False, status, "Authorization was cancelled")


def _run_idle(callback, *args):
    return callback(*args)


class TestPrivilegedHelperDialogInstall:
    def test_successful_install_updates_ui_and_calls_callback(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        on_installed = mock.MagicMock()
        application = mock.MagicMock()
        dialog = dialog_module.PrivilegedHelperDialog(on_installed=on_installed)
        dialog.get_application = mock.MagicMock(return_value=application)
        thread_factory = mock.MagicMock(side_effect=lambda **kwargs: _SynchronousThread(**kwargs))

        with (
            mock.patch.object(dialog_module.threading, "Thread", thread_factory),
            mock.patch.object(dialog_module.GLib, "idle_add", side_effect=_run_idle),
            mock.patch.object(
                dialog_module,
                "install_matching_privileged_helper",
                return_value=_successful_result(),
            ),
        ):
            dialog._on_install_clicked(mock.MagicMock())

        assert dialog._installation_succeeded is True
        assert dialog._installing is False
        dialog._status_label.set_text.assert_called_with("Helper installed successfully.")
        dialog._install_button.set_visible.assert_called_once_with(False)
        dialog._cancel_button.set_label.assert_called_once_with("Close")
        thread_factory.assert_called_once_with(target=mock.ANY, daemon=False)
        application.hold.assert_called_once_with()
        application.release.assert_called_once_with()
        on_installed.assert_called_once_with()
        _clear_src_modules()

    def test_failed_install_reenables_retry_without_callback(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        on_installed = mock.MagicMock()
        dialog = dialog_module.PrivilegedHelperDialog(on_installed=on_installed)

        with (
            mock.patch.object(dialog_module.threading, "Thread", _SynchronousThread),
            mock.patch.object(dialog_module.GLib, "idle_add", side_effect=_run_idle),
            mock.patch.object(
                dialog_module,
                "install_matching_privileged_helper",
                return_value=_failed_result(),
            ),
        ):
            dialog._on_install_clicked(mock.MagicMock())

        assert dialog._installation_succeeded is False
        assert dialog._installing is False
        dialog._install_button.set_sensitive.assert_called_with(True)
        dialog._cancel_button.set_sensitive.assert_called_with(True)
        dialog._status_label.set_text.assert_called_with(
            "Installation failed: Authorization was cancelled"
        )
        on_installed.assert_not_called()
        _clear_src_modules()

    def test_unexpected_install_error_hides_exception_text(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        dialog = dialog_module.PrivilegedHelperDialog()
        with (
            mock.patch.object(dialog_module.GLib, "idle_add", side_effect=_run_idle),
            mock.patch.object(
                dialog_module,
                "install_matching_privileged_helper",
                side_effect=RuntimeError("host token must remain private"),
            ),
            mock.patch.object(dialog_module.logger, "exception") as log_exception,
        ):
            dialog._install_in_background()

        log_exception.assert_called_once()
        dialog._status_label.set_text.assert_called_with(
            "Installation failed: An unexpected error occurred while installing the helper. "
            "Please try again."
        )
        _clear_src_modules()

    def test_thread_start_failure_releases_hold_and_restores_retry_ui(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        application = mock.MagicMock()
        dialog = dialog_module.PrivilegedHelperDialog()
        dialog.get_application = mock.MagicMock(return_value=application)
        thread = mock.MagicMock()
        thread.start.side_effect = RuntimeError("thread startup failed")

        with (
            mock.patch.object(dialog_module.threading, "Thread", return_value=thread),
            mock.patch.object(dialog_module.logger, "exception") as log_exception,
        ):
            dialog._on_install_clicked(mock.MagicMock())

        log_exception.assert_called_once()
        application.hold.assert_called_once_with()
        application.release.assert_called_once_with()
        assert dialog._installing is False
        dialog._install_button.set_sensitive.assert_called_with(True)
        dialog._status_label.set_text.assert_called_with(
            "Installation failed: An unexpected error occurred while installing the helper. "
            "Please try again."
        )
        _clear_src_modules()


class TestPrivilegedHelperDialogDismissal:
    def test_cancel_and_titlebar_notify_dismissal_once(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        on_dismissed = mock.MagicMock()
        dialog = dialog_module.PrivilegedHelperDialog(on_dismissed=on_dismissed)
        dialog.close.side_effect = lambda: dialog._on_close_request(dialog)

        dialog._on_cancel_clicked(mock.MagicMock())

        assert dialog._on_close_request(dialog) is False
        dialog.close.assert_called_once_with()
        on_dismissed.assert_called_once_with()
        dialog_module.Gtk.Button.assert_any_call(label="Not Now")
        _clear_src_modules()

    def test_close_during_install_does_not_notify_dismissal(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        on_dismissed = mock.MagicMock()
        dialog = dialog_module.PrivilegedHelperDialog(on_dismissed=on_dismissed)
        dialog._installing = True

        dialog._on_cancel_clicked(mock.MagicMock())

        assert dialog._on_close_request(dialog) is True
        dialog.close.assert_not_called()
        on_dismissed.assert_not_called()
        _clear_src_modules()

    def test_close_after_success_does_not_notify_dismissal(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        on_dismissed = mock.MagicMock()
        dialog = dialog_module.PrivilegedHelperDialog(on_dismissed=on_dismissed)

        dialog._finish_install(_successful_result(), False)

        assert dialog._on_close_request(dialog) is False
        on_dismissed.assert_not_called()
        _clear_src_modules()


class TestPrivilegedHelperDialogPresenter:
    def test_presenter_reuses_dialog_and_deduplicates_callback(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        parent_one = mock.MagicMock()
        parent_two = mock.MagicMock()
        on_installed = mock.MagicMock()
        dialog = mock.MagicMock()
        dialog._installing = False

        with mock.patch.object(
            dialog_module, "PrivilegedHelperDialog", return_value=dialog
        ) as dialog_class:
            assert (
                dialog_module.present_privileged_helper_dialog(parent_one, on_installed) is dialog
            )
            assert (
                dialog_module.present_privileged_helper_dialog(parent_two, on_installed) is dialog
            )

        dialog_class.assert_called_once()
        dialog.set_transient_for.assert_has_calls([mock.call(parent_one), mock.call(parent_two)])
        assert dialog.present.call_count == 2
        install_callback = dialog_class.call_args.kwargs["on_installed"]
        install_callback()
        on_installed.assert_called_once_with()

        assert dialog_module._clear_active_dialog_on_close(dialog) is False
        assert dialog_module._active_dialog is None
        assert dialog_module._active_install_callbacks == []
        assert dialog_module._active_dismiss_callbacks == []
        _clear_src_modules()

    def test_presenter_reuses_dialog_and_deduplicates_dismissal_callback(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        parent_one = mock.MagicMock()
        parent_two = mock.MagicMock()
        on_installed = mock.MagicMock()
        on_dismissed = mock.MagicMock()
        dialog = mock.MagicMock()
        dialog._installing = False

        with mock.patch.object(
            dialog_module, "PrivilegedHelperDialog", return_value=dialog
        ) as dialog_class:
            assert (
                dialog_module.present_privileged_helper_dialog(
                    parent_one,
                    on_installed=on_installed,
                    on_dismissed=on_dismissed,
                )
                is dialog
            )
            assert (
                dialog_module.present_privileged_helper_dialog(
                    parent_two,
                    on_installed=on_installed,
                    on_dismissed=on_dismissed,
                )
                is dialog
            )

        dialog_class.assert_called_once()
        dialog.set_transient_for.assert_has_calls([mock.call(parent_one), mock.call(parent_two)])
        assert dialog.present.call_count == 2
        dismiss_callback = dialog_class.call_args.kwargs["on_dismissed"]
        dismiss_callback()
        on_dismissed.assert_called_once_with()

        assert dialog_module._clear_active_dialog_on_close(dialog) is False
        assert dialog_module._active_install_callbacks == []
        assert dialog_module._active_dismiss_callbacks == []
        _clear_src_modules()

    def test_presenter_drops_dead_bound_callback(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        class CallbackOwner:
            def installed(self):
                pass

        owner = CallbackOwner()
        owner_ref = weakref.ref(owner)
        dialog_module._register_install_callback(owner.installed)
        del owner
        gc.collect()

        dialog_module._prune_install_callbacks()

        assert owner_ref() is None
        assert dialog_module._active_install_callbacks == []
        _clear_src_modules()

    def test_presenter_drops_dead_bound_dismissal_callback(self, mock_gi_modules):
        from src.ui import privileged_helper_dialog as dialog_module

        class CallbackOwner:
            def dismissed(self):
                pass

        owner = CallbackOwner()
        owner_ref = weakref.ref(owner)
        dialog_module._register_dismiss_callback(owner.dismissed)
        del owner
        gc.collect()

        dialog_module._prune_dismiss_callbacks()

        assert owner_ref() is None
        assert dialog_module._active_dismiss_callbacks == []
        _clear_src_modules()
