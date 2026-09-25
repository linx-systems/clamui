# ClamUI Audit Notification Tests
"""
Tests for audit completion notification behavior.

Verifies that:
- Notifications fire on first audit run when issues are found
- No notification on refresh (second run)
- No notification when all checks pass
- Notification respects missing notification_manager
"""

import sys
from unittest.mock import MagicMock


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


def _import_audit_types():
    """Import audit types from the SAME module instance used by audit_view.

    Enum identity matters: dict.get() uses ``is`` comparison for enum keys,
    so the AuditStatus used to build the report must be the exact same objects
    that _finalize_audit sees.  Re-importing after _clear_src_modules() would
    create duplicate enum classes, breaking dict lookups.
    """
    from src.core.system_audit import (
        AuditCategory,
        AuditCheckResult,
        AuditReport,
        AuditSectionResult,
        AuditStatus,
    )

    return AuditCategory, AuditCheckResult, AuditReport, AuditSectionResult, AuditStatus


def _create_view(mock_gi_modules):
    """Create a minimal AuditView for testing _finalize_audit."""
    from src.ui.audit_view import AuditView

    view = object.__new__(AuditView)
    view._is_checking = False
    view._destroyed = False
    view._cached_report = None
    view._notification_manager = None
    view._is_first_run = True
    view._initial_load_done = False
    view._section_groups = {}
    view._section_rows = {}
    view._section_status_icons = {}
    view._section_spinners = {}
    view._summary_banner = MagicMock()
    view._refresh_button = MagicMock()
    view._refresh_spinner = MagicMock()
    view._update_summary_banner = MagicMock()
    view._set_checking_state = MagicMock()
    return view


def _make_report(statuses):
    """Create a minimal AuditReport with sections of the given overall statuses.

    Must be called AFTER _create_view to use the same module instance.
    """
    AuditCategory, AuditCheckResult, AuditReport, AuditSectionResult, AuditStatus = (
        _import_audit_types()
    )
    categories = list(AuditCategory)
    sections = []
    for i, status in enumerate(statuses):
        cat = categories[i % len(categories)]
        check = AuditCheckResult(name=f"check_{i}", status=status, detail=f"detail_{i}")
        sections.append(
            AuditSectionResult(
                category=cat,
                title=f"Section {i}",
                icon_name="dialog-information-symbolic",
                checks=[check],
            )
        )
    return AuditReport(sections=sections)


class TestAuditNotificationOnFirstRun:
    """Notification fires on first audit run when issues are found."""

    def test_notifies_on_fail(self, mock_gi_modules):
        """Should notify when audit finds FAIL results."""
        view = _create_view(mock_gi_modules)
        *_, AuditStatus = _import_audit_types()
        mock_nm = MagicMock()
        view._notification_manager = mock_nm

        report = _make_report([AuditStatus.PASS, AuditStatus.FAIL])
        view._finalize_audit(report)

        mock_nm.notify_audit_complete.assert_called_once_with(warnings=0, issues=1)
        _clear_src_modules()

    def test_notifies_on_warning(self, mock_gi_modules):
        """Should notify when audit finds WARNING results."""
        view = _create_view(mock_gi_modules)
        *_, AuditStatus = _import_audit_types()
        mock_nm = MagicMock()
        view._notification_manager = mock_nm

        report = _make_report([AuditStatus.PASS, AuditStatus.WARNING])
        view._finalize_audit(report)

        mock_nm.notify_audit_complete.assert_called_once_with(warnings=1, issues=0)
        _clear_src_modules()

    def test_notifies_on_mixed_issues(self, mock_gi_modules):
        """Should count both warnings and issues correctly."""
        view = _create_view(mock_gi_modules)
        *_, AuditStatus = _import_audit_types()
        mock_nm = MagicMock()
        view._notification_manager = mock_nm

        report = _make_report(
            [
                AuditStatus.FAIL,
                AuditStatus.WARNING,
                AuditStatus.WARNING,
                AuditStatus.PASS,
            ]
        )
        view._finalize_audit(report)

        mock_nm.notify_audit_complete.assert_called_once_with(warnings=2, issues=1)
        _clear_src_modules()


class TestAuditNotificationSuppressed:
    """Notification is suppressed in expected scenarios."""

    def test_no_notification_when_all_pass(self, mock_gi_modules):
        """Should NOT notify when all checks pass."""
        view = _create_view(mock_gi_modules)
        *_, AuditStatus = _import_audit_types()
        mock_nm = MagicMock()
        view._notification_manager = mock_nm

        report = _make_report([AuditStatus.PASS, AuditStatus.PASS])
        view._finalize_audit(report)

        mock_nm.notify_audit_complete.assert_not_called()
        _clear_src_modules()

    def test_no_notification_on_refresh(self, mock_gi_modules):
        """Should NOT notify on second run (refresh)."""
        view = _create_view(mock_gi_modules)
        *_, AuditStatus = _import_audit_types()
        mock_nm = MagicMock()
        view._notification_manager = mock_nm

        # First run
        report = _make_report([AuditStatus.FAIL])
        view._finalize_audit(report)
        mock_nm.notify_audit_complete.assert_called_once()

        # Second run (refresh) - should NOT notify
        mock_nm.reset_mock()
        view._finalize_audit(report)
        mock_nm.notify_audit_complete.assert_not_called()
        _clear_src_modules()

    def test_no_notification_without_manager(self, mock_gi_modules):
        """Should handle missing notification_manager gracefully."""
        view = _create_view(mock_gi_modules)
        *_, AuditStatus = _import_audit_types()
        view._notification_manager = None

        report = _make_report([AuditStatus.FAIL])
        # Should not raise
        view._finalize_audit(report)
        assert view._cached_report is report
        _clear_src_modules()

    def test_no_notification_when_destroyed(self, mock_gi_modules):
        """Should not notify if view is destroyed."""
        view = _create_view(mock_gi_modules)
        *_, AuditStatus = _import_audit_types()
        mock_nm = MagicMock()
        view._notification_manager = mock_nm
        view._destroyed = True

        report = _make_report([AuditStatus.FAIL])
        view._finalize_audit(report)

        mock_nm.notify_audit_complete.assert_not_called()
        _clear_src_modules()


class TestNotifyAuditCompleteMethod:
    """Tests for NotificationManager.notify_audit_complete."""

    def test_returns_false_when_no_issues(self, mock_gi_modules):
        """Should return False (no notification) when no issues."""
        from src.core.notification_manager import NotificationManager

        nm = object.__new__(NotificationManager)
        nm._app = MagicMock()
        nm._settings = MagicMock()
        nm._settings.get.return_value = True

        result = nm.notify_audit_complete(warnings=0, issues=0)
        assert result is False
        _clear_src_modules()

    def test_sends_notification_for_issues(self, mock_gi_modules):
        """Should send notification when issues are present."""
        from src.core.notification_manager import NotificationManager

        nm = object.__new__(NotificationManager)
        nm._app = MagicMock()
        nm._settings = MagicMock()
        nm._settings.get.return_value = True

        result = nm.notify_audit_complete(warnings=2, issues=1)
        assert result is True
        nm._app.send_notification.assert_called_once()
        _clear_src_modules()

    def test_respects_disabled_notifications(self, mock_gi_modules):
        """Should return False when notifications are disabled."""
        from src.core.notification_manager import NotificationManager

        nm = object.__new__(NotificationManager)
        nm._app = MagicMock()
        nm._settings = MagicMock()
        nm._settings.get.return_value = False  # notifications disabled

        result = nm.notify_audit_complete(warnings=1, issues=0)
        assert result is False
        _clear_src_modules()
