# ClamUI AuditView Tests
"""
Unit tests for the AuditView component.

Tests cover:
- Module import and initialization
- Audit execution flow (cache vs fresh, no-op when checking)
- UI update methods (_update_section_ui, _update_summary_banner)
- State management (_set_checking_state, _reset_sections_to_checking)
- Event handlers (refresh, copy, deep scan buttons)
- Edge cases (_destroyed flag, empty results, GLib callback returns)
"""

import sys
from unittest.mock import MagicMock, patch


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _import_all(mock_gi_modules):
    """Import AuditView and system_audit types from the SAME module load.

    This is critical: mock_gi_modules clears src.* from sys.modules, so
    reimporting audit_view.py creates new enum classes. Using top-level
    imports would give us OLD enum instances that fail dict lookups and
    equality checks against the NEW ones used inside the view code.
    """
    from src.core.system_audit import (
        AuditCategory,
        AuditCheckResult,
        AuditReport,
        AuditSectionResult,
        AuditStatus,
    )
    from src.ui.audit_view import AuditView

    return (
        AuditView,
        AuditCategory,
        AuditCheckResult,
        AuditReport,
        AuditSectionResult,
        AuditStatus,
    )


def _create_view(AuditView):
    """Create an AuditView instance via object.__new__ and set core attributes."""
    view = object.__new__(AuditView)

    # Core state
    view._is_checking = False
    view._destroyed = False
    view._cached_report = None
    view._notification_manager = None
    view._is_first_run = True
    view._initial_load_done = False

    # Section widget references (6 Tier 1 categories — ExpanderRows)
    view._section_expanders = {}
    view._section_rows = {}
    view._section_status_icons = {}
    view._section_spinners = {}

    # Deep scan state
    view._lynis_running = False
    view._rootkit_running = False
    view._lynis_button = MagicMock()
    view._rootkit_button = MagicMock()
    view._lynis_spinner = MagicMock()
    view._rootkit_spinner = MagicMock()
    view._deep_scan_install_rows = {}
    view._deep_scan_results_box = MagicMock()

    # Header widgets
    view._refresh_button = MagicMock()
    view._refresh_spinner = MagicMock()
    view._summary_banner = MagicMock()

    # Deep scan rows
    view._lynis_row = MagicMock()
    view._rootkit_row = MagicMock()
    view._deep_scan_group = MagicMock()

    return view


def _populate_sections(view, AuditCategory):
    """Add mock widget dicts for all 6 Tier 1 categories (ExpanderRows)."""
    from tests.conftest import MockAdwExpanderRow

    for cat in [
        AuditCategory.CLAMAV_HEALTH,
        AuditCategory.FIREWALL,
        AuditCategory.MAC_FRAMEWORK,
        AuditCategory.AUTO_UPDATES,
        AuditCategory.INTRUSION_DETECTION,
        AuditCategory.SSH_HARDENING,
    ]:
        key = cat.value
        view._section_expanders[key] = MockAdwExpanderRow()
        view._section_rows[key] = [MagicMock()]  # Placeholder row
        view._section_spinners[key] = MagicMock()
        view._section_status_icons[key] = MagicMock()


def _make_check(AuditCheckResult, AuditStatus, **kwargs):
    """Create a test AuditCheckResult with defaults."""
    defaults = {
        "name": "Test Check",
        "status": AuditStatus.PASS,
        "detail": "All good",
        "recommendation": None,
        "install_command": None,
        "info_url": None,
        "launch_command": None,
        "launch_label": None,
    }
    defaults.update(kwargs)
    return AuditCheckResult(**defaults)


def _make_section(AuditSectionResult, AuditCategory, AuditCheckResult, AuditStatus, **kwargs):
    """Create a test AuditSectionResult with defaults."""
    defaults = {
        "category": AuditCategory.CLAMAV_HEALTH,
        "title": "ClamAV Health",
        "icon_name": "security-high-symbolic",
        "checks": [_make_check(AuditCheckResult, AuditStatus)],
    }
    defaults.update(kwargs)
    return AuditSectionResult(**defaults)


def _make_report(AuditReport, sections=None):
    """Create a test AuditReport."""
    report = AuditReport(timestamp=1000.0)
    if sections is not None:
        report.sections = sections
    return report


# Package managers the deep scan rows must never probe for: install hints come
# from the distro resolver, not from a local package-manager lookup (issue #184).
_PACKAGE_MANAGER_BINARIES = frozenset(
    {"apt", "apt-get", "aptitude", "dnf", "yum", "pacman", "zypper", "apk"}
)


def _probed_binaries(installed_mock):
    """Binary names passed to is_binary_installed, in call order."""
    return [args[0] for args, _kwargs in installed_mock.call_args_list if args]


def _package_manager_probes(installed_mock):
    """Package-manager binaries probed via is_binary_installed, in call order."""
    return [name for name in _probed_binaries(installed_mock) if name in _PACKAGE_MANAGER_BINARIES]


def _resolved_targets(resolver_mock):
    """InstallTarget values passed to recommend_install_command, in call order."""
    return [
        kwargs["target"] if "target" in kwargs else args[0]
        for args, kwargs in resolver_mock.call_args_list
    ]


def _install_commands_by_tool(setup_mock):
    """Map tool_name -> install_command as handed to _setup_deep_scan_row.

    Reads positional or keyword arguments so the resolver-to-renderer contract
    is asserted independently of the call style the view happens to use. A call
    that carries no install command at all is a contract break, not a None.
    """
    commands = {}
    for args, kwargs in setup_mock.call_args_list:
        tool = kwargs["tool_name"] if "tool_name" in kwargs else args[2]
        if "install_command" in kwargs:
            commands[tool] = kwargs["install_command"]
        elif len(args) > 5:
            commands[tool] = args[5]
        else:
            raise AssertionError(
                f"_setup_deep_scan_row got no install command for {tool!r}: "
                f"args={args!r} kwargs={kwargs!r}"
            )
    return commands


# ═════════════════════════════════════════════════════════════════════════════
# Test Classes
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditViewImport:
    """Test that the module imports correctly."""

    def test_import_module(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        assert AuditView is not None
        _clear_src_modules()


class TestAuditViewInit:
    """Test initialization attributes are set correctly."""

    def test_initial_state_flags(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        assert view._is_checking is False
        assert view._destroyed is False
        assert view._cached_report is None
        _clear_src_modules()

    def test_section_dicts_empty_initially(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        assert view._section_expanders == {}
        assert view._section_rows == {}
        assert view._section_status_icons == {}
        assert view._section_spinners == {}
        _clear_src_modules()

    def test_deep_scan_state_initial(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        assert view._lynis_running is False
        assert view._rootkit_running is False
        _clear_src_modules()

    def test_refresh_widgets_exist(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        assert view._refresh_button is not None
        assert view._refresh_spinner is not None
        assert view._summary_banner is not None
        _clear_src_modules()


class TestAuditExecutionFlow:
    """Test audit execution: cache usage, fresh run, no-op when checking."""

    def test_run_audit_if_needed_triggers_audit_when_no_cache(self, mock_gi_modules):
        """When _cached_report is None, should call _run_audit."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._run_audit = MagicMock()
        view._display_cached_report = MagicMock()

        result = view._run_audit_if_needed()

        view._run_audit.assert_called_once()
        view._display_cached_report.assert_not_called()
        assert result is False
        _clear_src_modules()

    def test_run_audit_if_needed_uses_cache_when_available(self, mock_gi_modules):
        """When _cached_report exists, should display cached report."""
        AuditView, _, _, AuditReport, _, _ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._cached_report = _make_report(AuditReport)
        view._run_audit = MagicMock()
        view._display_cached_report = MagicMock()

        result = view._run_audit_if_needed()

        view._display_cached_report.assert_called_once()
        view._run_audit.assert_not_called()
        assert result is False
        _clear_src_modules()

    def test_run_audit_is_noop_when_already_checking(self, mock_gi_modules):
        """When _is_checking is True, _run_audit should do nothing."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._is_checking = True
        view._set_checking_state = MagicMock()
        view._reset_sections_to_checking = MagicMock()

        view._run_audit()

        view._set_checking_state.assert_not_called()
        view._reset_sections_to_checking.assert_not_called()
        _clear_src_modules()

    @patch("threading.Thread")
    def test_run_audit_starts_background_thread(self, mock_thread, mock_gi_modules):
        """_run_audit should start a daemon thread for background checks."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._set_checking_state = MagicMock()
        view._reset_sections_to_checking = MagicMock()

        view._run_audit()

        view._set_checking_state.assert_called_once_with(True)
        view._reset_sections_to_checking.assert_called_once()
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        _clear_src_modules()

    def test_run_checks_background_skips_when_destroyed(self, mock_gi_modules):
        """Background thread should exit early when _destroyed is True."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True

        view._run_checks_background()
        _clear_src_modules()

    @patch("src.ui.audit_view.GLib")
    @patch("src.ui.audit_view.TIER1_CHECKS")
    @patch("src.ui.audit_view.is_binary_installed")
    def test_run_checks_background_runs_all_checks(
        self, mock_is_installed, mock_tier1, mock_glib, mock_gi_modules
    ):
        """Background thread should execute each tier1 check and push updates."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        check1 = MagicMock(
            return_value=_make_section(
                AuditSectionResult, AuditCategory, AuditCheckResult, AuditStatus
            )
        )
        check2 = MagicMock(
            return_value=_make_section(
                AuditSectionResult,
                AuditCategory,
                AuditCheckResult,
                AuditStatus,
                category=AuditCategory.FIREWALL,
            )
        )
        mock_tier1.__iter__ = MagicMock(return_value=iter([check1, check2]))
        mock_is_installed.return_value = False

        view._run_checks_background()

        check1.assert_called_once()
        check2.assert_called_once()
        # idle_add called for each section update + deep scan availability + finalize
        assert mock_glib.idle_add.call_count >= 3
        _clear_src_modules()

    def test_finalize_audit_caches_report(self, mock_gi_modules):
        """_finalize_audit should cache the report and update banner."""
        AuditView, _, _, AuditReport, _, _ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._update_summary_banner = MagicMock()
        view._set_checking_state = MagicMock()
        report = _make_report(AuditReport)

        result = view._finalize_audit(report)

        assert view._cached_report is report
        view._update_summary_banner.assert_called_once_with(report)
        view._set_checking_state.assert_called_once_with(False)
        assert result is False
        _clear_src_modules()

    def test_finalize_audit_skips_when_destroyed(self, mock_gi_modules):
        """_finalize_audit should do nothing when _destroyed is True."""
        AuditView, _, _, AuditReport, _, _ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True
        view._update_summary_banner = MagicMock()
        view._set_checking_state = MagicMock()

        result = view._finalize_audit(_make_report(AuditReport))

        assert view._cached_report is None
        view._update_summary_banner.assert_not_called()
        assert result is False
        _clear_src_modules()


class TestUpdateSectionUI:
    """Test _update_section_ui replaces rows and updates icons."""

    def test_replaces_placeholder_with_result_rows(self, mock_gi_modules):
        """Should remove old rows from group and add new result rows."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        _populate_sections(view, AuditCategory)

        section = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            checks=[
                _make_check(AuditCheckResult, AuditStatus, name="DB Age", detail="Fresh"),
                _make_check(
                    AuditCheckResult,
                    AuditStatus,
                    name="Daemon",
                    status=AuditStatus.WARNING,
                    detail="Not running",
                ),
            ],
        )

        view._add_check_row = MagicMock(side_effect=lambda g, c: [MagicMock()])
        view._set_status_icon = MagicMock()

        result = view._update_section_ui(section)

        key = AuditCategory.CLAMAV_HEALTH.value
        # Old placeholder row removed
        view._section_expanders[key].remove.assert_called()
        # add_check_row called for each check
        assert view._add_check_row.call_count == 2
        assert result is False
        _clear_src_modules()

    def test_stops_spinner_and_shows_status_icon(self, mock_gi_modules):
        """After updating section, spinner should stop and icon become visible."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        _populate_sections(view, AuditCategory)

        section = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.FIREWALL,
            title="Firewall",
        )
        view._add_check_row = MagicMock(return_value=[MagicMock()])
        view._set_status_icon = MagicMock()

        view._update_section_ui(section)

        key = AuditCategory.FIREWALL.value
        view._section_spinners[key].stop.assert_called_once()
        view._section_spinners[key].set_visible.assert_called_with(False)
        view._section_status_icons[key].set_visible.assert_called_with(True)
        view._set_status_icon.assert_called_once_with(
            view._section_status_icons[key], section.overall_status
        )
        _clear_src_modules()

    def test_returns_false_for_unknown_category(self, mock_gi_modules):
        """Should return False for an unrecognized category key."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        # Don't populate sections — key won't exist

        section = _make_section(AuditSectionResult, AuditCategory, AuditCheckResult, AuditStatus)
        result = view._update_section_ui(section)
        assert result is False
        _clear_src_modules()

    def test_skips_when_destroyed(self, mock_gi_modules):
        """Should return False immediately when _destroyed is True."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True
        _populate_sections(view, AuditCategory)

        section = _make_section(AuditSectionResult, AuditCategory, AuditCheckResult, AuditStatus)
        result = view._update_section_ui(section)

        assert result is False
        key = AuditCategory.CLAMAV_HEALTH.value
        view._section_expanders[key].remove.assert_not_called()
        _clear_src_modules()


class TestUpdateSummaryBanner:
    """Test _update_summary_banner displays correct counts."""

    def test_shows_pass_and_warning_counts(self, mock_gi_modules):
        """Banner should show passed and warning counts."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            AuditReport,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        report = _make_report(
            AuditReport,
            [
                _make_section(
                    AuditSectionResult,
                    AuditCategory,
                    AuditCheckResult,
                    AuditStatus,
                    checks=[_make_check(AuditCheckResult, AuditStatus, name="ok", detail="ok")],
                ),
                _make_section(
                    AuditSectionResult,
                    AuditCategory,
                    AuditCheckResult,
                    AuditStatus,
                    category=AuditCategory.FIREWALL,
                    checks=[
                        _make_check(
                            AuditCheckResult,
                            AuditStatus,
                            name="warn",
                            status=AuditStatus.WARNING,
                            detail="warn",
                        )
                    ],
                ),
            ],
        )

        view._update_summary_banner(report)

        view._summary_banner.set_title.assert_called_once()
        title_arg = view._summary_banner.set_title.call_args[0][0]
        # Contextual banner: "N checks need review · N passed"
        assert "need review" in title_arg
        assert "1 passed" in title_arg
        view._summary_banner.set_revealed.assert_called_with(True)
        _clear_src_modules()

    def test_shows_fail_count(self, mock_gi_modules):
        """Banner should show issue count for failed checks."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            AuditReport,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        report = _make_report(
            AuditReport,
            [
                _make_section(
                    AuditSectionResult,
                    AuditCategory,
                    AuditCheckResult,
                    AuditStatus,
                    checks=[
                        _make_check(
                            AuditCheckResult,
                            AuditStatus,
                            status=AuditStatus.FAIL,
                            detail="broken",
                        )
                    ],
                ),
            ],
        )

        view._update_summary_banner(report)

        title_arg = view._summary_banner.set_title.call_args[0][0]
        # Contextual banner: "N security issues need attention"
        assert "security issues need attention" in title_arg
        _clear_src_modules()

    def test_shows_audit_complete_for_unknown_only(self, mock_gi_modules):
        """Banner should show 'Audit complete' when only UNKNOWN checks exist."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            AuditReport,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        report = _make_report(
            AuditReport,
            [
                _make_section(
                    AuditSectionResult,
                    AuditCategory,
                    AuditCheckResult,
                    AuditStatus,
                    checks=[
                        _make_check(
                            AuditCheckResult,
                            AuditStatus,
                            status=AuditStatus.UNKNOWN,
                            detail="?",
                        )
                    ],
                ),
            ],
        )

        view._update_summary_banner(report)

        title_arg = view._summary_banner.set_title.call_args[0][0]
        # UNKNOWN is not in pass/warning/fail, so falls to "Audit complete"
        assert title_arg == "Audit complete"
        _clear_src_modules()

    def test_empty_report_shows_audit_complete(self, mock_gi_modules):
        """Empty report should show 'Audit complete' and reveal banner."""
        AuditView, _, _, AuditReport, _, _ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        report = _make_report(AuditReport, [])

        view._update_summary_banner(report)

        # Banner always reveals with contextual message
        view._summary_banner.set_title.assert_called_once_with("Audit complete")
        view._summary_banner.set_revealed.assert_called_with(True)
        _clear_src_modules()


class TestDisplayCachedReport:
    """Test _display_cached_report uses cached data."""

    def test_displays_all_cached_sections(self, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            AuditReport,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        report = _make_report(
            AuditReport,
            [
                _make_section(AuditSectionResult, AuditCategory, AuditCheckResult, AuditStatus),
                _make_section(
                    AuditSectionResult,
                    AuditCategory,
                    AuditCheckResult,
                    AuditStatus,
                    category=AuditCategory.FIREWALL,
                ),
            ],
        )
        view._cached_report = report
        view._update_section_ui = MagicMock(return_value=False)
        view._update_summary_banner = MagicMock()

        view._display_cached_report()

        assert view._update_section_ui.call_count == len(report.sections)
        view._update_summary_banner.assert_called_once_with(report)
        _clear_src_modules()

    def test_noop_when_no_cache(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._update_section_ui = MagicMock()
        view._update_summary_banner = MagicMock()

        view._display_cached_report()

        view._update_section_ui.assert_not_called()
        view._update_summary_banner.assert_not_called()
        _clear_src_modules()


class TestSetCheckingState:
    """Test _set_checking_state toggles spinner and button sensitivity."""

    def test_checking_true_disables_refresh_shows_spinner(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        view._set_checking_state(True)

        assert view._is_checking is True
        view._refresh_button.set_sensitive.assert_called_with(False)
        view._refresh_spinner.set_visible.assert_called_with(True)
        view._refresh_spinner.start.assert_called_once()
        view._summary_banner.set_revealed.assert_called_with(False)
        _clear_src_modules()

    def test_checking_false_enables_refresh_hides_spinner(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._is_checking = True

        view._set_checking_state(False)

        assert view._is_checking is False
        view._refresh_button.set_sensitive.assert_called_with(True)
        view._refresh_spinner.stop.assert_called_once()
        view._refresh_spinner.set_visible.assert_called_with(False)
        _clear_src_modules()


class TestResetSectionsToChecking:
    """Test _reset_sections_to_checking resets all sections."""

    def test_resets_all_sections(self, mock_gi_modules):
        """All section spinners should restart and status icons hide."""
        AuditView, AuditCategory, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        _populate_sections(view, AuditCategory)

        # Track old placeholder rows for removal assertions
        old_rows = {k: v[:] for k, v in view._section_rows.items()}

        view._reset_sections_to_checking()

        for key in view._section_expanders:
            # Old rows removed
            for old_row in old_rows[key]:
                view._section_expanders[key].remove.assert_any_call(old_row)
            # Spinner restarted
            view._section_spinners[key].set_visible.assert_called_with(True)
            view._section_spinners[key].start.assert_called()
            # Status icon hidden
            view._section_status_icons[key].set_visible.assert_called_with(False)
            # New placeholder row created
            assert len(view._section_rows[key]) == 1

        _clear_src_modules()


class TestEventHandlers:
    """Test event handler methods."""

    def test_on_refresh_clicked_clears_cache_and_reruns(self, mock_gi_modules):
        AuditView, _, _, AuditReport, _, _ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._cached_report = _make_report(AuditReport)
        view._run_audit = MagicMock()

        view._on_refresh_clicked(MagicMock())

        assert view._cached_report is None
        view._run_audit.assert_called_once()
        _clear_src_modules()

    def test_on_refresh_clicked_noop_when_checking(self, mock_gi_modules):
        AuditView, _, _, AuditReport, _, _ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._is_checking = True
        view._run_audit = MagicMock()
        original_report = _make_report(AuditReport)
        view._cached_report = original_report

        view._on_refresh_clicked(MagicMock())

        assert view._cached_report is original_report
        view._run_audit.assert_not_called()
        _clear_src_modules()

    @patch("src.ui.audit_view.GLib")
    def test_on_copy_clicked_sets_clipboard(self, mock_glib, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        button = MagicMock()
        clipboard = MagicMock()
        button.get_clipboard.return_value = clipboard

        view._on_copy_clicked(button, "sudo apt install lynis")

        clipboard.set.assert_called_once_with("sudo apt install lynis")
        button.set_icon_name.assert_called()
        mock_glib.timeout_add.assert_called_once()
        _clear_src_modules()

    def test_on_run_lynis_noop_when_already_running(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._lynis_running = True

        view._on_run_lynis(MagicMock())

        view._lynis_button.set_sensitive.assert_not_called()
        _clear_src_modules()

    def test_on_run_lynis_noop_when_button_is_none(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._lynis_button = None

        view._on_run_lynis(MagicMock())

        assert view._lynis_running is False
        _clear_src_modules()

    @patch("threading.Thread")
    def test_on_run_lynis_starts_thread(self, mock_thread, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        view._on_run_lynis(MagicMock())

        assert view._lynis_running is True
        view._lynis_button.set_sensitive.assert_called_with(False)
        view._lynis_spinner.set_visible.assert_called_with(True)
        view._lynis_spinner.start.assert_called_once()
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        _clear_src_modules()

    def test_on_run_rootkit_noop_when_already_running(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._rootkit_running = True

        view._on_run_rootkit(MagicMock())

        view._rootkit_button.set_sensitive.assert_not_called()
        _clear_src_modules()

    @patch("threading.Thread")
    def test_on_run_rootkit_starts_thread(self, mock_thread, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        view._on_run_rootkit(MagicMock())

        assert view._rootkit_running is True
        view._rootkit_button.set_sensitive.assert_called_with(False)
        view._rootkit_spinner.set_visible.assert_called_with(True)
        view._rootkit_spinner.start.assert_called_once()
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        _clear_src_modules()


class TestDeepScanComplete:
    """Test _on_deep_scan_complete handler."""

    def test_lynis_complete_resets_state(self, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            AuditReport,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._lynis_running = True
        view._cached_report = _make_report(AuditReport)
        view._show_deep_scan_results = MagicMock()

        result = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.DEEP_SCAN_LYNIS,
            title="Lynis",
        )

        ret = view._on_deep_scan_complete(result, "lynis")

        assert view._lynis_running is False
        view._lynis_button.set_sensitive.assert_called_with(True)
        view._lynis_spinner.stop.assert_called_once()
        view._lynis_spinner.set_visible.assert_called_with(False)
        view._show_deep_scan_results.assert_called_once_with(result)
        assert ret is False
        _clear_src_modules()

    def test_rootkit_complete_resets_state(self, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            AuditReport,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._rootkit_running = True
        view._cached_report = _make_report(AuditReport)
        view._show_deep_scan_results = MagicMock()

        result = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.DEEP_SCAN_ROOTKIT,
            title="Rootkit",
        )

        ret = view._on_deep_scan_complete(result, "rootkit")

        assert view._rootkit_running is False
        view._rootkit_button.set_sensitive.assert_called_with(True)
        view._rootkit_spinner.stop.assert_called_once()
        assert ret is False
        _clear_src_modules()

    def test_deep_scan_appends_to_cached_report(self, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            AuditReport,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._cached_report = _make_report(AuditReport)
        view._show_deep_scan_results = MagicMock()

        result = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.DEEP_SCAN_LYNIS,
            title="Lynis",
        )

        view._on_deep_scan_complete(result, "lynis")

        assert result in view._cached_report.sections
        _clear_src_modules()

    def test_deep_scan_replaces_existing_category(self, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            AuditReport,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        old_result = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.DEEP_SCAN_LYNIS,
            title="Old Lynis",
        )
        view._cached_report = _make_report(AuditReport, [old_result])
        view._show_deep_scan_results = MagicMock()

        new_result = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.DEEP_SCAN_LYNIS,
            title="New Lynis",
        )
        view._on_deep_scan_complete(new_result, "lynis")

        lynis_sections = [
            s for s in view._cached_report.sections if s.category == AuditCategory.DEEP_SCAN_LYNIS
        ]
        assert len(lynis_sections) == 1
        assert lynis_sections[0] is new_result
        _clear_src_modules()

    def test_deep_scan_skips_when_destroyed(self, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True
        view._show_deep_scan_results = MagicMock()

        result = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.DEEP_SCAN_LYNIS,
        )
        ret = view._on_deep_scan_complete(result, "lynis")

        assert ret is False
        view._show_deep_scan_results.assert_not_called()
        _clear_src_modules()


class TestEdgeCases:
    """Test edge cases: destroyed flag, empty results, background threads."""

    def test_destroyed_prevents_stale_update_section_ui(self, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True
        _populate_sections(view, AuditCategory)

        result = view._update_section_ui(
            _make_section(AuditSectionResult, AuditCategory, AuditCheckResult, AuditStatus)
        )
        assert result is False
        _clear_src_modules()

    def test_empty_checks_in_section_result(self, mock_gi_modules):
        """A section with no checks should update cleanly."""
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        _populate_sections(view, AuditCategory)
        view._set_status_icon = MagicMock()
        view._add_check_row = MagicMock(return_value=[])

        section = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            checks=[],
        )

        result = view._update_section_ui(section)

        assert result is False
        key = AuditCategory.CLAMAV_HEALTH.value
        assert view._section_rows[key] == []
        view._section_spinners[key].stop.assert_called_once()
        _clear_src_modules()

    @patch("src.ui.audit_view.GLib")
    @patch("src.ui.audit_view.run_lynis_audit")
    def test_run_lynis_background_skips_when_destroyed(
        self, mock_lynis, mock_glib, mock_gi_modules
    ):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True

        view._run_lynis_background()

        mock_lynis.assert_not_called()
        mock_glib.idle_add.assert_not_called()
        _clear_src_modules()

    @patch("src.ui.audit_view.GLib")
    @patch("src.ui.audit_view.run_lynis_audit")
    def test_run_lynis_background_calls_idle_add(self, mock_lynis, mock_glib, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        mock_lynis.return_value = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.DEEP_SCAN_LYNIS,
        )

        view._run_lynis_background()

        mock_lynis.assert_called_once()
        mock_glib.idle_add.assert_called_once()
        _clear_src_modules()

    @patch("src.ui.audit_view.GLib")
    @patch("src.ui.audit_view.run_rootkit_check")
    def test_run_rootkit_background_skips_when_destroyed(
        self, mock_rootkit, mock_glib, mock_gi_modules
    ):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True

        view._run_rootkit_background()

        mock_rootkit.assert_not_called()
        mock_glib.idle_add.assert_not_called()
        _clear_src_modules()

    @patch("src.ui.audit_view.GLib")
    @patch("src.ui.audit_view.run_rootkit_check")
    def test_run_rootkit_background_calls_idle_add(self, mock_rootkit, mock_glib, mock_gi_modules):
        (
            AuditView,
            AuditCategory,
            AuditCheckResult,
            _,
            AuditSectionResult,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        mock_rootkit.return_value = _make_section(
            AuditSectionResult,
            AuditCategory,
            AuditCheckResult,
            AuditStatus,
            category=AuditCategory.DEEP_SCAN_ROOTKIT,
        )

        view._run_rootkit_background()

        mock_rootkit.assert_called_once()
        mock_glib.idle_add.assert_called_once()
        _clear_src_modules()

    @patch("subprocess.Popen")
    def test_on_launch_clicked_spawns_process(self, mock_popen, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        view._on_launch_clicked(MagicMock(), "gufw")

        mock_popen.assert_called_once()
        assert mock_popen.call_args[0][0] == ["gufw"]
        _clear_src_modules()

    @patch("subprocess.Popen")
    def test_on_launch_clicked_passes_clean_env(self, mock_popen, mock_gi_modules):
        """Issue #155 residual: gufw/firewall-config are host Python/GTK
        scripts. With stderr=DEVNULL a leaked AppImage PYTHONHOME kills them
        instantly and silently, so Popen must get the sanitized environment."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/home/user"}

        with patch("src.core.flatpak.get_clean_env", return_value=clean_env) as mock_clean:
            view._on_launch_clicked(MagicMock(), "gufw")

        mock_clean.assert_called_once()
        assert mock_popen.call_args[0][0] == ["gufw"]
        assert mock_popen.call_args.kwargs["env"] is clean_env
        _clear_src_modules()

    @patch("subprocess.Popen", side_effect=FileNotFoundError)
    def test_on_launch_clicked_handles_missing_binary(self, mock_popen, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        view._on_launch_clicked(MagicMock(), "nonexistent")
        _clear_src_modules()

    @patch("subprocess.Popen", side_effect=OSError("permission denied"))
    def test_on_launch_clicked_handles_os_error(self, mock_popen, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)

        view._on_launch_clicked(MagicMock(), "restricted_app")
        _clear_src_modules()


class TestAddCheckRow:
    """Test _add_check_row creates correct row widgets."""

    def test_basic_check_row(self, mock_gi_modules):
        (
            AuditView,
            _,
            AuditCheckResult,
            _,
            _,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._create_status_image = MagicMock(return_value=MagicMock())

        group = MagicMock()
        check = _make_check(AuditCheckResult, AuditStatus, name="DB Fresh", detail="Up to date")

        rows = view._add_check_row(group, check)

        assert len(rows) >= 1
        group.add.assert_called()
        _clear_src_modules()

    def test_check_with_recommendation_adds_extra_row(self, mock_gi_modules):
        """Failed check with recommendation should add extra row."""
        (
            AuditView,
            _,
            AuditCheckResult,
            _,
            _,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._create_status_image = MagicMock(return_value=MagicMock())

        group = MagicMock()
        check = _make_check(
            AuditCheckResult,
            AuditStatus,
            name="Firewall",
            status=AuditStatus.FAIL,
            detail="Disabled",
            recommendation="Enable UFW firewall",
        )

        rows = view._add_check_row(group, check)

        # Main row + recommendation row
        assert len(rows) >= 2
        _clear_src_modules()

    def test_check_with_install_command(self, mock_gi_modules):
        (
            AuditView,
            _,
            AuditCheckResult,
            _,
            _,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._create_status_image = MagicMock(return_value=MagicMock())
        view._create_command_row = MagicMock(return_value=MagicMock())

        group = MagicMock()
        check = _make_check(
            AuditCheckResult,
            AuditStatus,
            name="fail2ban",
            status=AuditStatus.FAIL,
            detail="Not installed",
            install_command="sudo apt install fail2ban",
        )

        view._add_check_row(group, check)

        view._create_command_row.assert_called_once_with("sudo apt install fail2ban")
        _clear_src_modules()

    def test_pass_check_skips_recommendation(self, mock_gi_modules):
        """PASS status should skip recommendation even if present."""
        (
            AuditView,
            _,
            AuditCheckResult,
            _,
            _,
            AuditStatus,
        ) = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._create_status_image = MagicMock(return_value=MagicMock())

        group = MagicMock()
        check = _make_check(
            AuditCheckResult,
            AuditStatus,
            name="SSH",
            detail="Secure",
            recommendation="This should be skipped",
        )

        rows = view._add_check_row(group, check)

        # Only main row, no recommendation row (status is PASS)
        assert len(rows) == 1
        _clear_src_modules()


class TestDeepScanAvailability:
    """Test _update_deep_scan_availability configures rows correctly."""

    @patch("src.ui.audit_view.is_binary_installed")
    def test_update_deep_scan_both_installed(self, mock_installed, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._setup_deep_scan_row = MagicMock()
        mock_installed.return_value = True

        result = view._update_deep_scan_availability(True, True)

        assert view._setup_deep_scan_row.call_count == 2
        assert view._setup_deep_scan_row.call_args_list[0][0][1] is True
        assert view._setup_deep_scan_row.call_args_list[1][0][1] is True
        assert result is False
        _clear_src_modules()

    @patch("src.ui.audit_view.is_binary_installed")
    def test_update_deep_scan_not_installed(self, mock_installed, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._setup_deep_scan_row = MagicMock()
        mock_installed.return_value = True

        view._update_deep_scan_availability(False, False)

        assert view._setup_deep_scan_row.call_count == 2
        assert view._setup_deep_scan_row.call_args_list[0][0][1] is False
        assert view._setup_deep_scan_row.call_args_list[1][0][1] is False
        _clear_src_modules()

    def test_update_deep_scan_skips_when_destroyed(self, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True
        view._setup_deep_scan_row = MagicMock()

        result = view._update_deep_scan_availability(True, True)

        assert result is False
        view._setup_deep_scan_row.assert_not_called()
        _clear_src_modules()

    @patch("src.ui.audit_view.recommend_install_command", create=True)
    @patch("src.ui.audit_view.is_binary_installed")
    def test_update_deep_scan_replaces_old_install_rows_on_refresh(
        self, mock_installed, mock_recommend, mock_gi_modules
    ):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._create_status_image = MagicMock(return_value=MagicMock())
        view._create_command_row = MagicMock(
            side_effect=[MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        )
        mock_installed.return_value = True
        # Resolver stub keeps both command rows independent of the host distro;
        # create=True tolerates audit_view before the resolver is wired in.
        mock_recommend.return_value = "sudo apt install lynis"

        view._update_deep_scan_availability(False, False)

        first_lynis_row = view._lynis_row
        first_rootkit_row = view._rootkit_row
        first_install_rows = dict(view._deep_scan_install_rows)
        view._deep_scan_group.remove.reset_mock()

        view._update_deep_scan_availability(False, False)

        view._deep_scan_group.remove.assert_any_call(first_lynis_row)
        view._deep_scan_group.remove.assert_any_call(first_rootkit_row)
        for row in first_install_rows.values():
            view._deep_scan_group.remove.assert_any_call(row)
        assert view._deep_scan_install_rows != first_install_rows
        assert len(view._deep_scan_install_rows) == 2
        _clear_src_modules()

    @patch("src.ui.audit_view.is_binary_installed")
    def test_update_deep_scan_passes_info_urls(self, mock_installed, mock_gi_modules):
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._setup_deep_scan_row = MagicMock()
        mock_installed.return_value = True

        view._update_deep_scan_availability(True, False)

        lynis_call = view._setup_deep_scan_row.call_args_list[0][0]
        rootkit_call = view._setup_deep_scan_row.call_args_list[1][0]
        assert lynis_call[4] == "https://cisofy.com/lynis/"
        assert rootkit_call[4] == "https://www.chkrootkit.org/"
        _clear_src_modules()


class TestDeepScanInstallCommandResolution:
    """Deep scan install hints must come from the distro resolver (issue #184).

    Before the fix, _update_deep_scan_availability probed for the apt or dnf
    binary itself, derived both tools' commands from that single prefix, and
    fell back to apt on every other distro -- so Arch users were told to run
    apt, and chkrootkit was advertised where no package exists. The view must
    instead ask recommend_install_command once per tool and forward whatever
    comes back, including None.
    """

    @patch("src.ui.audit_view.recommend_install_command", create=True)
    @patch("src.ui.audit_view.is_binary_installed")
    def test_resolver_consulted_once_per_tool(
        self, mock_installed, mock_recommend, mock_gi_modules
    ):
        """Lynis and chkrootkit are resolved separately, not from one prefix."""
        AuditView, *_ = _import_all(mock_gi_modules)
        from src.core.install_commands import InstallTarget

        view = _create_view(AuditView)
        view._setup_deep_scan_row = MagicMock()
        resolved = {
            InstallTarget.LYNIS: "sudo dnf install lynis",
            InstallTarget.CHKROOTKIT: "sudo dnf install chkrootkit",
        }
        mock_recommend.side_effect = lambda target: resolved[target]

        view._update_deep_scan_availability(False, False)

        assert _resolved_targets(mock_recommend) == [
            InstallTarget.LYNIS,
            InstallTarget.CHKROOTKIT,
        ]
        assert _install_commands_by_tool(view._setup_deep_scan_row) == {
            "lynis": "sudo dnf install lynis",
            "chkrootkit": "sudo dnf install chkrootkit",
        }
        _clear_src_modules()

    @patch("src.ui.audit_view.recommend_install_command", create=True)
    @patch("src.ui.audit_view.is_binary_installed")
    def test_unpackaged_tool_resolves_to_none_without_affecting_the_other(
        self, mock_installed, mock_recommend, mock_gi_modules
    ):
        """Arch packages lynis but not chkrootkit: only chkrootkit loses its command."""
        AuditView, *_ = _import_all(mock_gi_modules)
        from src.core.install_commands import InstallTarget

        view = _create_view(AuditView)
        view._setup_deep_scan_row = MagicMock()
        mock_recommend.side_effect = lambda target: (
            "sudo pacman -S lynis" if target is InstallTarget.LYNIS else None
        )

        view._update_deep_scan_availability(False, False)

        assert _install_commands_by_tool(view._setup_deep_scan_row) == {
            "lynis": "sudo pacman -S lynis",
            "chkrootkit": None,
        }
        _clear_src_modules()

    @patch("src.ui.audit_view.recommend_install_command", create=True)
    @patch("src.ui.audit_view.is_binary_installed")
    def test_unresolvable_distro_passes_no_command(
        self, mock_installed, mock_recommend, mock_gi_modules
    ):
        """Unknown distro: rows receive None, never a fabricated apt fallback."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._setup_deep_scan_row = MagicMock()
        mock_installed.return_value = True  # an apt/dnf probe would succeed here
        mock_recommend.return_value = None

        view._update_deep_scan_availability(False, False)

        assert _install_commands_by_tool(view._setup_deep_scan_row) == {
            "lynis": None,
            "chkrootkit": None,
        }
        _clear_src_modules()

    @patch("src.ui.audit_view.recommend_install_command", create=True)
    @patch("src.ui.audit_view.is_binary_installed")
    def test_row_update_does_not_probe_package_managers(
        self, mock_installed, mock_recommend, mock_gi_modules
    ):
        """Command selection is the resolver's job, not a package-manager probe."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._setup_deep_scan_row = MagicMock()
        mock_installed.return_value = True  # every probe would succeed
        mock_recommend.return_value = "sudo pacman -S lynis"

        view._update_deep_scan_availability(True, False)

        assert _package_manager_probes(mock_installed) == []
        _clear_src_modules()

    @patch("src.ui.audit_view.recommend_install_command", create=True)
    @patch("src.ui.audit_view.GLib")
    @patch("src.ui.audit_view.TIER1_CHECKS")
    @patch("src.ui.audit_view.is_binary_installed")
    def test_availability_flow_probes_only_the_two_tools(
        self, mock_installed, mock_tier1, mock_glib, mock_recommend, mock_gi_modules
    ):
        """Binary probes exist for lynis/chkrootkit availability and nothing else."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._setup_deep_scan_row = MagicMock()
        view._finalize_audit = MagicMock()
        mock_tier1.__iter__ = MagicMock(return_value=iter([]))
        mock_installed.return_value = False
        mock_recommend.return_value = "sudo dnf install lynis"
        mock_glib.idle_add.side_effect = lambda callback, *args: callback(*args)

        view._run_checks_background()

        assert _probed_binaries(mock_installed) == ["lynis", "chkrootkit"]
        _clear_src_modules()

    @patch("src.ui.audit_view.recommend_install_command", create=True)
    def test_destroyed_view_skips_resolver(self, mock_recommend, mock_gi_modules):
        """A destroyed view must not run distro detection on the host."""
        AuditView, *_ = _import_all(mock_gi_modules)
        view = _create_view(AuditView)
        view._destroyed = True
        view._setup_deep_scan_row = MagicMock()

        assert view._update_deep_scan_availability(True, True) is False
        mock_recommend.assert_not_called()
        _clear_src_modules()
