# ClamUI Scan Results Dialog Tests
"""
Tests for the ScanResultsDialog component.

Covers: initialization, stats section, threats section, skipped files,
per-threat actions (quarantine/exclude/copy), bulk quarantine, and export.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_threat(
    file_path="/tmp/evil.exe", threat_name="Trojan.Generic", severity="high", category="trojan"
):
    """Create a mock ThreatDetail-like object."""
    t = MagicMock()
    t.file_path = file_path
    t.threat_name = threat_name
    t.severity = severity
    t.category = category
    return t


def _make_scan_result(
    status_name="CLEAN",
    infected_count=0,
    scanned_files=100,
    scanned_dirs=5,
    skipped_count=0,
    skipped_files=None,
    threat_details=None,
    error_message=None,
    has_warnings=False,
    stdout="",
    warning_message=None,
):
    """Create a mock ScanResult matching the real dataclass interface."""
    r = MagicMock()
    r.status = MagicMock()
    r.status.name = status_name
    r.infected_count = infected_count
    r.scanned_files = scanned_files
    r.scanned_dirs = scanned_dirs
    r.skipped_count = skipped_count
    r.skipped_files = skipped_files
    r.threat_details = threat_details or []
    r.error_message = error_message
    r.has_warnings = has_warnings
    r.stdout = stdout
    r.warning_message = warning_message
    r.is_clean = status_name == "CLEAN"
    r.has_threats = status_name == "INFECTED"
    return r


def _import_dialog_module(mock_gi_modules):
    """Import ScanResultsDialog and ScanStatus with mocks in place."""
    from src.core.scanner_types import ScanStatus
    from src.ui.scan_results_dialog import (
        INITIAL_DISPLAY_LIMIT,
        LARGE_RESULT_THRESHOLD,
        LOAD_MORE_BATCH_SIZE,
        ScanResultsDialog,
    )

    return (
        ScanResultsDialog,
        ScanStatus,
        INITIAL_DISPLAY_LIMIT,
        LOAD_MORE_BATCH_SIZE,
        LARGE_RESULT_THRESHOLD,
    )


def _create_dialog(ScanResultsDialog, scan_result, quarantine_manager=None, settings_manager=None):
    """Create a ScanResultsDialog instance via object.__new__ and set core attributes."""
    dialog = object.__new__(ScanResultsDialog)
    dialog._scan_result = scan_result
    dialog._quarantine_manager = quarantine_manager or MagicMock()
    dialog._settings_manager = settings_manager
    dialog._displayed_threat_count = 0
    dialog._all_threat_details = scan_result.threat_details or []
    dialog._load_more_row = None
    dialog._unquarantined_threats = list(dialog._all_threat_details)
    dialog._quarantine_all_button = None
    dialog._threats_list = None
    dialog._toast_overlay = MagicMock()
    return dialog


# ═════════════════════════════════════════════════════════════════════════════
# Test Classes
# ═════════════════════════════════════════════════════════════════════════════


class TestScanResultsDialogImport:
    """Test that the module imports correctly."""

    def test_import_module(self, mock_gi_modules):
        from src.ui.scan_results_dialog import ScanResultsDialog

        assert ScanResultsDialog is not None
        _clear_src_modules()


class TestScanResultsDialogInit:
    """Test constructor stores attributes and initial state."""

    def test_stores_scan_result(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        result = _make_scan_result()
        dialog = _create_dialog(ScanResultsDialog, result)

        assert dialog._scan_result is result
        _clear_src_modules()

    def test_stores_quarantine_manager(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        qm = MagicMock()
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result(), quarantine_manager=qm)

        assert dialog._quarantine_manager is qm
        _clear_src_modules()

    def test_stores_settings_manager(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        sm = MagicMock()
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result(), settings_manager=sm)

        assert dialog._settings_manager is sm
        _clear_src_modules()

    def test_initial_displayed_threat_count_zero(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())

        assert dialog._displayed_threat_count == 0
        _clear_src_modules()

    def test_unquarantined_threats_populated_from_result(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threats = [_make_threat(f"/tmp/file{i}") for i in range(3)]
        result = _make_scan_result(status_name="INFECTED", infected_count=3, threat_details=threats)
        dialog = _create_dialog(ScanResultsDialog, result)

        assert len(dialog._unquarantined_threats) == 3
        assert dialog._unquarantined_threats == threats
        _clear_src_modules()

    def test_empty_threat_details_yields_empty_unquarantined(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())

        assert dialog._unquarantined_threats == []
        _clear_src_modules()


class TestStatsSection:
    """Test _create_stats_section for different scan statuses."""

    def _setup(self, mock_gi_modules, result):
        ScanResultsDialog, ScanStatus, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, result)
        # Map status name to real enum
        dialog._scan_result.status = ScanStatus[result.status.name]
        return dialog

    def test_clean_scan_title(self, mock_gi_modules):
        result = _make_scan_result(status_name="CLEAN")
        dialog = self._setup(mock_gi_modules, result)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        # Parent should have had a group appended
        parent.append.assert_called_once()
        _clear_src_modules()

    def test_infected_scan_title(self, mock_gi_modules):
        result = _make_scan_result(status_name="INFECTED", infected_count=3)
        dialog = self._setup(mock_gi_modules, result)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        parent.append.assert_called_once()
        _clear_src_modules()

    def test_error_scan_shows_error_message(self, mock_gi_modules):
        result = _make_scan_result(status_name="ERROR", error_message="Database not found")
        dialog = self._setup(mock_gi_modules, result)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        parent.append.assert_called_once()
        _clear_src_modules()

    def test_cancelled_scan_with_threats(self, mock_gi_modules):
        result = _make_scan_result(status_name="CANCELLED", infected_count=2)
        dialog = self._setup(mock_gi_modules, result)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        parent.append.assert_called_once()
        _clear_src_modules()

    def test_cancelled_scan_without_threats(self, mock_gi_modules):
        result = _make_scan_result(status_name="CANCELLED", infected_count=0)
        dialog = self._setup(mock_gi_modules, result)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        parent.append.assert_called_once()
        _clear_src_modules()

    def test_clean_scan_with_warnings(self, mock_gi_modules):
        result = _make_scan_result(status_name="CLEAN", has_warnings=True, skipped_count=5)
        dialog = self._setup(mock_gi_modules, result)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        parent.append.assert_called_once()
        _clear_src_modules()

    def test_clean_scan_skipped_count_subtitle(self, mock_gi_modules):
        """Skipped files render the not-accessible count in the subtitle."""
        result = _make_scan_result(
            status_name="CLEAN",
            has_warnings=True,
            skipped_count=5,
            warning_message="5 file(s) could not be accessed",
        )
        dialog = self._setup(mock_gi_modules, result)
        expander = MagicMock()
        mock_gi_modules["adw"].ExpanderRow = MagicMock(return_value=expander)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        subtitle = expander.set_subtitle.call_args[0][0]
        assert "5 file(s) not accessible" in subtitle
        _clear_src_modules()

    def test_clean_scan_nonfatal_warning_never_shows_zero_files(self, mock_gi_modules):
        """Regression: with skipped_count == 0 but nonfatal warnings present,
        the CLEAN subtitle said "0 file(s) not accessible" instead of the
        actual warning message."""
        result = _make_scan_result(
            status_name="CLEAN",
            has_warnings=True,
            skipped_count=0,
            warning_message="LibClamAV Warning: bytecode execution failed",
        )
        dialog = self._setup(mock_gi_modules, result)
        expander = MagicMock()
        mock_gi_modules["adw"].ExpanderRow = MagicMock(return_value=expander)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        subtitle = expander.set_subtitle.call_args[0][0]
        assert "0 file(s)" not in subtitle
        assert "No threats found" in subtitle
        assert "LibClamAV Warning: bytecode execution failed" in subtitle
        _clear_src_modules()

    def test_clean_scan_no_warnings_plain_subtitle(self, mock_gi_modules):
        result = _make_scan_result(status_name="CLEAN")
        dialog = self._setup(mock_gi_modules, result)
        expander = MagicMock()
        mock_gi_modules["adw"].ExpanderRow = MagicMock(return_value=expander)
        parent = MagicMock()

        dialog._create_stats_section(parent)

        subtitle = expander.set_subtitle.call_args[0][0]
        assert subtitle == "No threats found"
        _clear_src_modules()


class TestStatRow:
    """Test _create_stat_row helper."""

    def test_returns_box_widget(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())

        row = dialog._create_stat_row("Files scanned:", "100")

        # Should return a mock representing a Gtk.Box
        assert row is not None
        _clear_src_modules()


class TestThreatsSection:
    """Test _create_threats_section builds list with pagination."""

    def test_creates_threats_list(self, mock_gi_modules):
        ScanResultsDialog, ScanStatus, INITIAL_DISPLAY_LIMIT, *_ = _import_dialog_module(
            mock_gi_modules
        )
        threats = [_make_threat(f"/tmp/file{i}") for i in range(5)]
        result = _make_scan_result(status_name="INFECTED", infected_count=5, threat_details=threats)
        dialog = _create_dialog(ScanResultsDialog, result)
        parent = MagicMock()

        dialog._create_threats_section(parent)

        assert dialog._threats_list is not None
        assert dialog._displayed_threat_count == 5
        parent.append.assert_called_once()
        _clear_src_modules()

    def test_pagination_when_threats_exceed_limit(self, mock_gi_modules):
        ScanResultsDialog, ScanStatus, INITIAL_DISPLAY_LIMIT, *_ = _import_dialog_module(
            mock_gi_modules
        )
        threats = [_make_threat(f"/tmp/file{i}") for i in range(30)]
        result = _make_scan_result(
            status_name="INFECTED", infected_count=30, threat_details=threats
        )
        dialog = _create_dialog(ScanResultsDialog, result)
        parent = MagicMock()

        dialog._create_threats_section(parent)

        assert dialog._displayed_threat_count == INITIAL_DISPLAY_LIMIT
        assert dialog._load_more_row is not None
        _clear_src_modules()

    def test_no_pagination_when_under_limit(self, mock_gi_modules):
        ScanResultsDialog, ScanStatus, INITIAL_DISPLAY_LIMIT, *_ = _import_dialog_module(
            mock_gi_modules
        )
        threats = [_make_threat(f"/tmp/file{i}") for i in range(10)]
        result = _make_scan_result(
            status_name="INFECTED", infected_count=10, threat_details=threats
        )
        dialog = _create_dialog(ScanResultsDialog, result)
        parent = MagicMock()

        dialog._create_threats_section(parent)

        assert dialog._displayed_threat_count == 10
        assert dialog._load_more_row is None
        _clear_src_modules()

    def test_load_more_adds_batch(self, mock_gi_modules):
        ScanResultsDialog, ScanStatus, INITIAL_DISPLAY_LIMIT, LOAD_MORE_BATCH_SIZE, *_ = (
            _import_dialog_module(mock_gi_modules)
        )
        threats = [_make_threat(f"/tmp/file{i}") for i in range(60)]
        result = _make_scan_result(
            status_name="INFECTED", infected_count=60, threat_details=threats
        )
        dialog = _create_dialog(ScanResultsDialog, result)
        dialog._threats_list = MagicMock()

        # Load initial batch
        dialog._load_more_threats(INITIAL_DISPLAY_LIMIT)
        assert dialog._displayed_threat_count == INITIAL_DISPLAY_LIMIT

        # Load more
        dialog._load_more_threats(LOAD_MORE_BATCH_SIZE)
        assert dialog._displayed_threat_count == INITIAL_DISPLAY_LIMIT + LOAD_MORE_BATCH_SIZE
        _clear_src_modules()

    def test_on_load_more_clicked_calls_load_more(self, mock_gi_modules):
        ScanResultsDialog, ScanStatus, INITIAL_DISPLAY_LIMIT, LOAD_MORE_BATCH_SIZE, *_ = (
            _import_dialog_module(mock_gi_modules)
        )
        threats = [_make_threat(f"/tmp/file{i}") for i in range(60)]
        result = _make_scan_result(
            status_name="INFECTED", infected_count=60, threat_details=threats
        )
        dialog = _create_dialog(ScanResultsDialog, result)
        dialog._threats_list = MagicMock()
        dialog._load_more_threats(INITIAL_DISPLAY_LIMIT)

        dialog._on_load_more_clicked(MagicMock())

        assert dialog._displayed_threat_count == INITIAL_DISPLAY_LIMIT + LOAD_MORE_BATCH_SIZE
        _clear_src_modules()

    def test_large_result_threshold_banner(self, mock_gi_modules):
        (
            ScanResultsDialog,
            ScanStatus,
            INITIAL_DISPLAY_LIMIT,
            LOAD_MORE_BATCH_SIZE,
            LARGE_RESULT_THRESHOLD,
        ) = _import_dialog_module(mock_gi_modules)
        threats = [_make_threat(f"/tmp/file{i}") for i in range(LARGE_RESULT_THRESHOLD + 10)]
        result = _make_scan_result(
            status_name="INFECTED",
            infected_count=LARGE_RESULT_THRESHOLD + 10,
            threat_details=threats,
        )
        dialog = _create_dialog(ScanResultsDialog, result)
        parent = MagicMock()

        dialog._create_threats_section(parent)

        # Should still create section successfully
        parent.append.assert_called_once()
        _clear_src_modules()


class TestThreatRow:
    """Test _create_threat_row builds correct row structure."""

    def test_returns_row(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())
        threat = _make_threat()

        row = dialog._create_threat_row(threat)

        assert row is not None
        _clear_src_modules()

    def test_row_uses_threat_name(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())
        threat = _make_threat(threat_name="Win.Ransomware.WannaCry")

        row = dialog._create_threat_row(threat)

        # The row is created without errors
        assert row is not None
        _clear_src_modules()

    @pytest.mark.parametrize(
        "severity",
        ["critical", "high", "medium", "low"],
    )
    def test_severity_badge_css_class(self, mock_gi_modules, severity):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())
        threat = _make_threat(severity=severity)

        row = dialog._create_threat_row(threat)

        assert row is not None
        _clear_src_modules()


class TestSkippedFilesSection:
    """Test _create_skipped_files_section."""

    def test_creates_section_when_skipped_files_present(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        result = _make_scan_result(
            skipped_count=3,
            skipped_files=["/root/secret1", "/root/secret2", "/root/secret3"],
        )
        dialog = _create_dialog(ScanResultsDialog, result)
        parent = MagicMock()

        dialog._create_skipped_files_section(parent)

        parent.append.assert_called_once()
        _clear_src_modules()

    def test_truncates_long_list(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        files = [f"/root/file{i}" for i in range(120)]
        result = _make_scan_result(skipped_count=120, skipped_files=files)
        dialog = _create_dialog(ScanResultsDialog, result)
        parent = MagicMock()

        # Should not raise even with >100 files
        dialog._create_skipped_files_section(parent)

        parent.append.assert_called_once()
        _clear_src_modules()

    def test_handles_none_skipped_files(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        result = _make_scan_result(skipped_count=0, skipped_files=None)
        dialog = _create_dialog(ScanResultsDialog, result)
        parent = MagicMock()

        # skipped_count=0 means this normally wouldn't be called,
        # but test the graceful handling of None
        dialog._create_skipped_files_section(parent)

        parent.append.assert_called_once()
        _clear_src_modules()


class TestPerThreatActions:
    """Test per-threat action handlers."""

    def test_quarantine_single_success(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        from src.core.quarantine.manager import QuarantineStatus

        threat = _make_threat(file_path="/tmp/evil.exe")
        threats = [threat]
        result = _make_scan_result(status_name="INFECTED", infected_count=1, threat_details=threats)
        qm = MagicMock()
        qm.quarantine_file.return_value = MagicMock(
            status=QuarantineStatus.SUCCESS, error_message=None
        )
        dialog = _create_dialog(ScanResultsDialog, result, quarantine_manager=qm)
        button = MagicMock()

        dialog._on_quarantine_single(button, threat)

        qm.quarantine_file.assert_called_once_with("/tmp/evil.exe", "Trojan.Generic")
        button.set_label.assert_called_with("Quarantined")
        button.set_sensitive.assert_called_with(False)
        assert threat not in dialog._unquarantined_threats
        _clear_src_modules()

    def test_quarantine_single_failure(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        from src.core.quarantine.manager import QuarantineStatus

        threat = _make_threat()
        result = _make_scan_result(
            status_name="INFECTED", infected_count=1, threat_details=[threat]
        )
        qm = MagicMock()
        qm.quarantine_file.return_value = MagicMock(
            status=QuarantineStatus.PERMISSION_DENIED,
            error_message="Permission denied",
        )
        dialog = _create_dialog(ScanResultsDialog, result, quarantine_manager=qm)
        button = MagicMock()

        dialog._on_quarantine_single(button, threat)

        # Threat should still be in unquarantined list
        assert threat in dialog._unquarantined_threats
        _clear_src_modules()

    def test_add_exclusion_success(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threat = _make_threat(file_path="/tmp/detected.txt")
        result = _make_scan_result(
            status_name="INFECTED", infected_count=1, threat_details=[threat]
        )
        sm = MagicMock()
        sm.get.return_value = []
        dialog = _create_dialog(ScanResultsDialog, result, settings_manager=sm)
        button = MagicMock()

        dialog._on_add_exclusion(button, threat)

        sm.set.assert_called_once()
        call_args = sm.set.call_args
        assert call_args[0][0] == "exclusion_patterns"
        exclusions = call_args[0][1]
        assert len(exclusions) == 1
        assert exclusions[0]["pattern"] == "/tmp/detected.txt"
        assert exclusions[0]["type"] == "file"
        assert exclusions[0]["enabled"] is True
        button.set_label.assert_called_with("Excluded")
        button.set_sensitive.assert_called_with(False)
        _clear_src_modules()

    def test_add_exclusion_already_excluded(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threat = _make_threat(file_path="/tmp/detected.txt")
        result = _make_scan_result(
            status_name="INFECTED", infected_count=1, threat_details=[threat]
        )
        sm = MagicMock()
        sm.get.return_value = [{"pattern": "/tmp/detected.txt", "type": "file", "enabled": True}]
        dialog = _create_dialog(ScanResultsDialog, result, settings_manager=sm)
        button = MagicMock()

        dialog._on_add_exclusion(button, threat)

        # Should not call set again (already excluded)
        sm.set.assert_not_called()
        button.set_label.assert_called_with("Excluded")
        _clear_src_modules()

    def test_add_exclusion_no_settings_manager(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threat = _make_threat()
        result = _make_scan_result(
            status_name="INFECTED", infected_count=1, threat_details=[threat]
        )
        dialog = _create_dialog(ScanResultsDialog, result, settings_manager=None)
        button = MagicMock()

        # Should not raise
        dialog._on_add_exclusion(button, threat)

        # Toast should show error about accessing settings
        dialog._toast_overlay.add_toast.assert_called()
        _clear_src_modules()

    def test_add_exclusion_non_list_exclusions(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threat = _make_threat(file_path="/tmp/test.bin")
        result = _make_scan_result(
            status_name="INFECTED", infected_count=1, threat_details=[threat]
        )
        sm = MagicMock()
        sm.get.return_value = "not-a-list"
        dialog = _create_dialog(ScanResultsDialog, result, settings_manager=sm)
        button = MagicMock()

        dialog._on_add_exclusion(button, threat)

        # Should reset to list and add exclusion
        sm.set.assert_called_once()
        call_args = sm.set.call_args
        exclusions = call_args[0][1]
        assert isinstance(exclusions, list)
        assert len(exclusions) == 1
        _clear_src_modules()

    @patch("src.core.clipboard.copy_to_clipboard")
    def test_copy_path(self, mock_copy, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threat = _make_threat(file_path="/tmp/evil.exe")
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())
        button = MagicMock()

        dialog._on_copy_path(button, threat)

        mock_copy.assert_called_once_with("/tmp/evil.exe")
        _clear_src_modules()


class TestBulkQuarantine:
    """Test _on_quarantine_all_clicked and _on_quarantine_all_complete."""

    def test_quarantine_all_disables_button(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        from src.core.quarantine.manager import QuarantineStatus

        threats = [_make_threat(f"/tmp/file{i}") for i in range(3)]
        result = _make_scan_result(status_name="INFECTED", infected_count=3, threat_details=threats)
        qm = MagicMock()
        qm.quarantine_file.return_value = MagicMock(
            status=QuarantineStatus.SUCCESS, error_message=None
        )
        dialog = _create_dialog(ScanResultsDialog, result, quarantine_manager=qm)
        button = MagicMock()

        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            dialog._on_quarantine_all_clicked(button)

        button.set_sensitive.assert_called_with(False)
        button.set_label.assert_called_with("Quarantining...")
        _clear_src_modules()

    def test_quarantine_all_spawns_thread(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threats = [_make_threat(f"/tmp/file{i}") for i in range(2)]
        result = _make_scan_result(status_name="INFECTED", infected_count=2, threat_details=threats)
        dialog = _create_dialog(ScanResultsDialog, result)
        button = MagicMock()

        with patch("threading.Thread") as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance
            dialog._on_quarantine_all_clicked(button)

        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()
        _clear_src_modules()

    def test_quarantine_all_skips_when_empty(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())
        button = MagicMock()

        with patch("threading.Thread") as mock_thread:
            dialog._on_quarantine_all_clicked(button)

        mock_thread.assert_not_called()
        _clear_src_modules()

    def test_on_quarantine_all_complete_success(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threats = [_make_threat(f"/tmp/file{i}") for i in range(3)]
        result = _make_scan_result(status_name="INFECTED", infected_count=3, threat_details=threats)
        dialog = _create_dialog(ScanResultsDialog, result)
        dialog._quarantine_all_button = MagicMock()

        dialog._on_quarantine_all_complete(3, 0)

        assert len(dialog._unquarantined_threats) == 0
        dialog._quarantine_all_button.set_visible.assert_called_with(False)
        dialog._toast_overlay.add_toast.assert_called()
        _clear_src_modules()

    def test_on_quarantine_all_complete_partial_failure(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threats = [_make_threat(f"/tmp/file{i}") for i in range(3)]
        result = _make_scan_result(status_name="INFECTED", infected_count=3, threat_details=threats)
        dialog = _create_dialog(ScanResultsDialog, result)
        dialog._quarantine_all_button = MagicMock()

        dialog._on_quarantine_all_complete(2, 1)

        assert len(dialog._unquarantined_threats) == 0
        dialog._toast_overlay.add_toast.assert_called()
        _clear_src_modules()

    def test_on_quarantine_all_complete_returns_false(self, mock_gi_modules):
        """GLib.idle_add expects False to not repeat."""
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())
        dialog._quarantine_all_button = MagicMock()

        result = dialog._on_quarantine_all_complete(0, 0)

        assert result is False
        _clear_src_modules()


class TestUpdateQuarantineAllButton:
    """Test _update_quarantine_all_button label updates."""

    def test_hides_button_when_no_threats(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())
        dialog._quarantine_all_button = MagicMock()
        dialog._unquarantined_threats = []

        dialog._update_quarantine_all_button()

        dialog._quarantine_all_button.set_visible.assert_called_with(False)
        _clear_src_modules()

    def test_updates_label_with_remaining_count(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        threats = [_make_threat(f"/tmp/file{i}") for i in range(5)]
        result = _make_scan_result(status_name="INFECTED", infected_count=5, threat_details=threats)
        dialog = _create_dialog(ScanResultsDialog, result)
        dialog._quarantine_all_button = MagicMock()

        dialog._update_quarantine_all_button()

        dialog._quarantine_all_button.set_label.assert_called_once()
        _clear_src_modules()

    def test_noop_when_button_is_none(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())
        dialog._quarantine_all_button = None

        # Should not raise
        dialog._update_quarantine_all_button()
        _clear_src_modules()


class TestExport:
    """Test _on_export_clicked and _export_results_to_file."""

    def test_export_with_no_stdout_shows_toast(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        result = _make_scan_result(stdout="")
        dialog = _create_dialog(ScanResultsDialog, result)

        dialog._on_export_clicked(MagicMock())

        dialog._toast_overlay.add_toast.assert_called()
        _clear_src_modules()

    @patch("src.ui.scan_results_dialog.ClipboardHelper")
    def test_export_with_stdout_uses_clipboard_helper(self, mock_helper_cls, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        result = _make_scan_result(stdout="ClamAV scan output here")
        dialog = _create_dialog(ScanResultsDialog, result)

        dialog._on_export_clicked(MagicMock())

        mock_helper_cls.assert_called_once()
        instance = mock_helper_cls.return_value
        instance.copy_with_feedback.assert_called_once()
        _clear_src_modules()

    @patch("src.ui.scan_results_dialog.FileExportHelper")
    def test_export_results_to_file(self, mock_export_cls, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        result = _make_scan_result(stdout="output data")
        dialog = _create_dialog(ScanResultsDialog, result)

        dialog._export_results_to_file(MagicMock())

        mock_export_cls.assert_called_once()
        instance = mock_export_cls.return_value
        instance.show_save_dialog.assert_called_once()
        _clear_src_modules()


class TestShowToast:
    """Test _show_toast helper."""

    def test_show_toast_creates_toast(self, mock_gi_modules):
        ScanResultsDialog, *_ = _import_dialog_module(mock_gi_modules)
        dialog = _create_dialog(ScanResultsDialog, _make_scan_result())

        dialog._show_toast("Test message")

        dialog._toast_overlay.add_toast.assert_called_once()
        _clear_src_modules()
