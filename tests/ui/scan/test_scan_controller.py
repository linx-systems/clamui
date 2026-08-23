# ScanController Tests
"""
Unit tests for the ScanController component.

Tests cover:
- ScanState transitions (IDLE -> SCANNING -> IDLE)
- Starting scans with single/multiple paths
- Cancel logic (sets cancel flag, delegates to scanner)
- Callback wiring (on_progress, on_complete, on_state_change)
- AggregatedResult compilation from multi-target scans
- Empty paths edge case (no-op)
- Error aggregation from failed scans
- Progress callback throttling
"""

import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers - use .value for enum comparison to avoid dual-import identity
# issues (the test imports ScanStatus once, but the module under test may
# have a different instance after module cache clears).
# ---------------------------------------------------------------------------


def _assert_status(obj, expected_value: str):
    """Assert status by comparing .value strings to avoid enum identity issues."""
    assert obj.status.value == expected_value, (
        f"Expected status '{expected_value}', got '{obj.status.value}'"
    )


def _make_result(
    status_value="clean",
    path="/test",
    scanned_files=10,
    scanned_dirs=2,
    infected_count=0,
    infected_files=None,
    error_message=None,
    threat_details=None,
    skipped_files=None,
    skipped_count=0,
    warning_message=None,
    nonfatal_warnings=None,
):
    """Create a ScanResult using fresh imports to avoid enum identity issues."""
    from src.core.scanner_types import ScanResult, ScanStatus

    status_map = {s.value: s for s in ScanStatus}
    return ScanResult(
        status=status_map[status_value],
        path=path,
        stdout="",
        stderr="" if status_value != "error" else "error output",
        exit_code={"clean": 0, "infected": 1, "error": 2, "cancelled": 0}[status_value],
        infected_files=infected_files or [],
        scanned_files=scanned_files,
        scanned_dirs=scanned_dirs,
        infected_count=infected_count,
        error_message=error_message,
        threat_details=threat_details or [],
        skipped_files=skipped_files or [],
        skipped_count=skipped_count,
        warning_message=warning_message,
        nonfatal_warnings=nonfatal_warnings or [],
    )


def _get_scan_status(value: str):
    """Get a ScanStatus enum member by string value, using fresh import."""
    from src.core.scanner_types import ScanStatus

    status_map = {s.value: s for s in ScanStatus}
    return status_map[value]


@pytest.fixture
def mock_gi_for_controller():
    """Minimal GLib mock needed by scan_controller (uses GLib.idle_add)."""
    mock_glib = MagicMock()
    # Make GLib.idle_add execute the callback immediately for deterministic tests
    mock_glib.idle_add = MagicMock(side_effect=lambda fn, *a: fn(*a))

    mock_gi = MagicMock()
    mock_gi.require_version = MagicMock()
    mock_repository = MagicMock()
    mock_repository.GLib = mock_glib

    with patch.dict(
        sys.modules,
        {
            "gi": mock_gi,
            "gi.repository": mock_repository,
            "gi.repository.GLib": mock_glib,
        },
    ):
        yield mock_glib


@pytest.fixture
def scanner():
    """Create a mock Scanner."""
    s = MagicMock()
    # Default: scan_sync returns a clean result
    s.scan_sync.return_value = _make_result(status_value="clean")
    return s


@pytest.fixture
def settings():
    """Create a mock SettingsManager."""
    s = MagicMock()
    s.get.return_value = True  # show_live_progress defaults to True
    return s


@pytest.fixture
def controller(mock_gi_for_controller, scanner, settings):
    """Create a ScanController with mocked dependencies."""
    # Clear cached module so it picks up the mocked GLib
    if "src.ui.scan.scan_controller" in sys.modules:
        del sys.modules["src.ui.scan.scan_controller"]

    from src.ui.scan.scan_controller import ScanController

    return ScanController(scanner, settings)


# =============================================================================
# ScanState & Properties
# =============================================================================


class TestScanControllerState:
    """Tests for state management properties."""

    def test_initial_state_is_idle(self, controller):
        from src.ui.scan.scan_controller import ScanState

        assert controller.state == ScanState.IDLE
        assert controller.is_scanning is False

    def test_current_target_idx_default(self, controller):
        assert controller.current_target_idx == 1

    def test_total_targets_default(self, controller):
        assert controller.total_targets == 1


# =============================================================================
# Starting Scans
# =============================================================================


class TestStartScan:
    """Tests for scan start logic."""

    def test_start_scan_empty_paths_is_noop(self, controller, scanner):
        """Starting a scan with empty paths should do nothing."""
        on_state = MagicMock()
        controller.set_callbacks(on_state_change=on_state)

        controller.start_scan([])

        scanner.scan_sync.assert_not_called()
        on_state.assert_not_called()

    def test_start_scan_sets_state_to_scanning(self, controller, scanner):
        """start_scan should transition state to SCANNING immediately."""
        from src.ui.scan.scan_controller import ScanState

        states = []

        def track_state(state):
            states.append(state)

        controller.set_callbacks(on_state_change=track_state)

        controller.start_scan(["/tmp/test"])

        # Give the thread a moment to complete
        time.sleep(0.2)

        # Should have seen SCANNING then IDLE
        assert ScanState.SCANNING in states
        assert states[-1] == ScanState.IDLE

    def test_start_scan_calls_scanner_for_each_path(self, controller, scanner):
        """Each path should be scanned via scan_sync."""
        paths = ["/path/a", "/path/b", "/path/c"]
        controller.start_scan(paths)
        time.sleep(0.3)

        assert scanner.scan_sync.call_count == 3

    def test_start_scan_single_path(self, controller, scanner):
        """Single path scan should work correctly."""
        on_complete = MagicMock()
        controller.set_callbacks(on_complete=on_complete)

        controller.start_scan(["/single/path"])
        time.sleep(0.2)

        scanner.scan_sync.assert_called_once()
        on_complete.assert_called_once()

    def test_start_scan_passes_profile_exclusions(self, controller, scanner):
        """Profile exclusions should be passed through to scanner."""
        exclusions = {"paths": ["/skip/this"], "patterns": ["*.log"]}
        controller.start_scan(["/test"], profile_exclusions=exclusions)
        time.sleep(0.2)

        call_kwargs = scanner.scan_sync.call_args
        assert call_kwargs[1]["profile_exclusions"] == exclusions

    def test_start_scan_calls_on_target_progress(self, controller, scanner):
        """Multi-target progress callback should fire for each target."""
        on_target = MagicMock()
        controller.start_scan(
            ["/a", "/b"],
            on_target_progress=on_target,
        )
        time.sleep(0.3)

        assert on_target.call_count == 2


# =============================================================================
# Cancel Logic
# =============================================================================


class TestCancelScan:
    """Tests for scan cancellation."""

    def test_cancel_sets_flag(self, controller, scanner):
        """cancel() should set the internal cancel flag."""
        controller.cancel()
        assert controller._cancel_all is True

    def test_cancel_delegates_to_scanner(self, controller, scanner):
        """cancel() should call scanner.cancel()."""
        controller.cancel()
        scanner.cancel.assert_called_once()

    def test_cancel_during_scan_stops_remaining_targets(self, controller, scanner):
        """Cancelling during a multi-target scan should skip remaining paths."""
        call_count = [0]

        def slow_scan(path, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # After first scan completes, simulate cancel
                controller._cancel_all = True
            return _make_result(
                status_value="cancelled" if controller._cancel_all else "clean",
                path=path,
                scanned_files=5,
                scanned_dirs=1,
            )

        scanner.scan_sync.side_effect = slow_scan

        on_complete = MagicMock()
        controller.set_callbacks(on_complete=on_complete)
        controller.start_scan(["/a", "/b", "/c"])
        time.sleep(0.3)

        # Should have scanned at most 2 (first completes, second sees cancel)
        assert scanner.scan_sync.call_count <= 2
        on_complete.assert_called_once()
        result = on_complete.call_args[0][0]
        _assert_status(result, "cancelled")

    def test_start_scan_ignored_while_already_scanning(self, controller, scanner):
        """start_scan() while a scan is in progress must be ignored (no second
        worker thread, no scanner invocation, no state re-notification)."""
        from src.ui.scan.scan_controller import ScanState

        controller._state = ScanState.SCANNING
        on_state = MagicMock()
        controller.set_callbacks(on_state_change=on_state)

        controller.start_scan(["/tmp/second"])
        time.sleep(0.1)

        scanner.scan_sync.assert_not_called()
        on_state.assert_not_called()


# =============================================================================
# Callbacks
# =============================================================================


class TestCallbacks:
    """Tests for callback wiring."""

    def test_set_callbacks_stores_references(self, controller):
        """set_callbacks should store all callback references."""
        on_p = MagicMock()
        on_c = MagicMock()
        on_s = MagicMock()
        controller.set_callbacks(on_progress=on_p, on_complete=on_c, on_state_change=on_s)

        assert controller._on_progress is on_p
        assert controller._on_complete is on_c
        assert controller._on_state_change is on_s

    def test_on_complete_receives_scan_result(self, controller, scanner):
        """on_complete should receive a ScanResult object."""
        from src.core.scanner_types import ScanResult

        on_complete = MagicMock()
        controller.set_callbacks(on_complete=on_complete)

        controller.start_scan(["/test"])
        time.sleep(0.2)

        on_complete.assert_called_once()
        result = on_complete.call_args[0][0]
        assert isinstance(result, ScanResult)

    def test_on_state_change_fires_on_start_and_end(self, controller, scanner):
        """on_state_change should fire with SCANNING on start and IDLE on end."""
        from src.ui.scan.scan_controller import ScanState

        states = []
        controller.set_callbacks(on_state_change=lambda s: states.append(s))

        controller.start_scan(["/test"])
        time.sleep(0.2)

        assert ScanState.SCANNING in states
        assert ScanState.IDLE in states

    def test_no_callbacks_no_error(self, controller, scanner):
        """Running a scan without setting callbacks should not error."""
        controller.start_scan(["/test"])
        time.sleep(0.2)
        # No exception means pass


# =============================================================================
# AggregatedResult
# =============================================================================


class TestAggregatedResult:
    """Tests for the AggregatedResult dataclass."""

    def test_aggregated_result_defaults(self, mock_gi_for_controller):
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        _assert_status(agg, "clean")
        assert agg.total_files == 0
        assert agg.total_dirs == 0
        assert agg.total_infected == 0
        assert agg.infected_files == []
        assert agg.threat_details == []
        assert agg.error_messages == []

    def test_to_scan_result_clean(self, mock_gi_for_controller):
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult(total_files=50, total_dirs=5)
        result = agg.to_scan_result(["/a", "/b"])
        _assert_status(result, "clean")
        assert result.path == "/a, /b"
        assert result.exit_code == 0
        assert result.scanned_files == 50

    def test_to_scan_result_infected(self, mock_gi_for_controller):
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult(
            status=_get_scan_status("infected"),
            total_files=100,
            total_infected=2,
            infected_files=["/bad1", "/bad2"],
        )
        result = agg.to_scan_result(["/scan"])
        _assert_status(result, "infected")
        assert result.exit_code == 1
        assert result.infected_count == 2
        assert result.path == "/scan"

    def test_to_scan_result_error(self, mock_gi_for_controller):
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult(
            error_messages=["Permission denied"],
        )
        result = agg.to_scan_result(["/test"])
        # exit_code should be 2 for errors when status is not INFECTED
        assert result.exit_code == 2
        assert result.error_message == "Permission denied"

    def test_to_scan_result_empty_paths(self, mock_gi_for_controller):
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        result = agg.to_scan_result([])
        assert result.path == ""

    def test_to_scan_result_single_path(self, mock_gi_for_controller):
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        result = agg.to_scan_result(["/only/one"])
        assert result.path == "/only/one"

    def test_to_scan_result_forwards_skipped_warning_fields(self, mock_gi_for_controller):
        """Skipped files and nonfatal warnings must survive the conversion."""
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult(
            skipped_files=["/a/locked", "/b/locked"],
            skipped_count=2,
            nonfatal_warnings=["LibClamAV Warning: cli_scanxz: exceeds limits"],
        )
        result = agg.to_scan_result(["/a", "/b"])
        assert result.skipped_files == ["/a/locked", "/b/locked"]
        assert result.skipped_count == 2
        assert result.nonfatal_warnings == ["LibClamAV Warning: cli_scanxz: exceeds limits"]
        assert result.warning_message == "2 file(s) could not be accessed"
        assert result.has_warnings

    def test_to_scan_result_warning_message_without_skips(self, mock_gi_for_controller):
        """Without skipped files, distinct per-target messages are joined."""
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult(warning_messages=["limit warning A", "limit warning B"])
        result = agg.to_scan_result(["/a"])
        assert result.warning_message == "limit warning A; limit warning B"
        assert result.skipped_count == 0

    def test_to_scan_result_no_warnings_yields_none_message(self, mock_gi_for_controller):
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        result = agg.to_scan_result(["/a"])
        assert result.warning_message is None
        assert not result.has_warnings


# =============================================================================
# Result Aggregation Logic
# =============================================================================


class TestResultAggregation:
    """Tests for _aggregate_result and _aggregate_partial."""

    def test_aggregate_result_accumulates_files(self, controller):
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        scan = _make_result(status_value="clean", path="/a", scanned_files=20, scanned_dirs=3)
        controller._aggregate_result(agg, scan)
        assert agg.total_files == 20
        assert agg.total_dirs == 3

    def test_aggregate_result_accumulates_infections(self, controller):
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        scan = _make_result(
            status_value="infected",
            path="/a",
            scanned_files=10,
            scanned_dirs=1,
            infected_count=1,
            infected_files=["/a/bad.exe"],
        )
        controller._aggregate_result(agg, scan)
        assert agg.total_infected == 1
        assert agg.infected_files == ["/a/bad.exe"]
        _assert_status(agg, "infected")

    def test_aggregate_result_accumulates_errors(self, controller):
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        scan = _make_result(
            status_value="error",
            path="/a",
            scanned_files=0,
            scanned_dirs=0,
            error_message="Permission denied",
        )
        controller._aggregate_result(agg, scan)
        assert agg.error_messages == ["Permission denied"]

    def test_aggregate_multiple_results(self, controller):
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()

        clean = _make_result(status_value="clean", path="/a", scanned_files=10, scanned_dirs=2)
        infected = _make_result(
            status_value="infected",
            path="/b",
            scanned_files=15,
            scanned_dirs=3,
            infected_count=1,
            infected_files=["/b/virus.exe"],
        )

        controller._aggregate_result(agg, clean)
        controller._aggregate_result(agg, infected)

        assert agg.total_files == 25
        assert agg.total_dirs == 5
        assert agg.total_infected == 1
        _assert_status(agg, "infected")

    def test_aggregate_result_merges_skipped_and_warning_fields(self, controller):
        """Skipped files dedup across targets; count matches the deduped list;
        messages stay distinct."""
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        first = _make_result(
            status_value="clean",
            path="/a",
            skipped_files=["/a/locked", "/shared/locked"],
            skipped_count=2,
            warning_message="2 file(s) could not be accessed",
            nonfatal_warnings=["LibClamAV Warning: cli_tnef: file truncated, returning CLEAN"],
        )
        second = _make_result(
            status_value="clean",
            path="/b",
            skipped_files=["/shared/locked", "/b/locked"],
            skipped_count=2,
            warning_message="2 file(s) could not be accessed",
            nonfatal_warnings=[
                "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN",
                "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits",
            ],
        )

        controller._aggregate_result(agg, first)
        controller._aggregate_result(agg, second)

        assert agg.skipped_files == ["/a/locked", "/shared/locked", "/b/locked"]
        # The count must equal the deduplicated list, not the sum of the
        # per-target counts (the shared file would otherwise count twice).
        assert agg.skipped_count == len(agg.skipped_files) == 3
        assert agg.nonfatal_warnings == [
            "LibClamAV Warning: cli_tnef: file truncated, returning CLEAN",
            "LibClamAV Warning: cli_scanxz: decompress file size exceeds limits",
        ]
        assert agg.warning_messages == ["2 file(s) could not be accessed"]

    def test_aggregate_partial_from_cancelled(self, controller):
        """_aggregate_partial should accumulate partial data without status change."""
        from src.ui.scan.scan_controller import AggregatedResult

        agg = AggregatedResult()
        partial = _make_result(
            status_value="cancelled",
            path="/a",
            scanned_files=5,
            scanned_dirs=1,
            infected_count=1,
            infected_files=["/a/partial_bad"],
        )
        controller._aggregate_partial(agg, partial)
        assert agg.total_files == 5
        assert agg.total_infected == 1
        assert agg.infected_files == ["/a/partial_bad"]
        # Status should not be changed by _aggregate_partial
        _assert_status(agg, "clean")


# =============================================================================
# Multi-target scan end-to-end
# =============================================================================


class TestMultiTargetScan:
    """Integration-style tests for full multi-target scan flows."""

    def test_clean_multi_target_result(self, controller, scanner):
        """Multi-target scan with all clean results."""
        on_complete = MagicMock()
        controller.set_callbacks(on_complete=on_complete)

        controller.start_scan(["/a", "/b"])
        time.sleep(0.3)

        result = on_complete.call_args[0][0]
        _assert_status(result, "clean")
        assert result.scanned_files == 20  # 10 per scan (mock default)

    def test_infected_multi_target_result(self, controller, scanner):
        """If any target has infections, final result should be INFECTED."""
        clean_result = _make_result(status_value="clean", path="/a")
        infected_result = _make_result(
            status_value="infected",
            path="/b",
            scanned_files=5,
            scanned_dirs=1,
            infected_count=1,
            infected_files=["/b/malware.bin"],
        )
        scanner.scan_sync.side_effect = [clean_result, infected_result]

        on_complete = MagicMock()
        controller.set_callbacks(on_complete=on_complete)

        controller.start_scan(["/a", "/b"])
        time.sleep(0.3)

        result = on_complete.call_args[0][0]
        _assert_status(result, "infected")
        assert result.infected_count == 1

    def test_error_multi_target_result(self, controller, scanner):
        """If a target errors and none are infected, final result should be ERROR."""
        error_result = _make_result(
            status_value="error",
            path="/a",
            scanned_files=0,
            scanned_dirs=0,
            error_message="clamscan not found",
        )
        scanner.scan_sync.return_value = error_result

        on_complete = MagicMock()
        controller.set_callbacks(on_complete=on_complete)

        controller.start_scan(["/a"])
        time.sleep(0.2)

        result = on_complete.call_args[0][0]
        _assert_status(result, "error")

    def test_total_targets_tracked(self, controller, scanner):
        """total_targets should reflect the number of paths."""
        controller.start_scan(["/a", "/b", "/c"])
        time.sleep(0.3)

        # After completion, total_targets should still reflect original count
        assert controller._total_targets == 3


# =============================================================================
# Progress Callback
# =============================================================================


class TestProgressCallback:
    """Tests for the throttled progress callback."""

    def test_progress_callback_created_when_live_progress_enabled(
        self, controller, scanner, settings
    ):
        """Progress callback should be created when show_live_progress is True."""
        settings.get.return_value = True
        on_progress = MagicMock()
        controller.set_callbacks(on_progress=on_progress)

        # The progress callback is passed to scan_sync
        controller.start_scan(["/test"])
        time.sleep(0.2)

        call_kwargs = scanner.scan_sync.call_args
        assert call_kwargs[1]["progress_callback"] is not None

    def test_no_progress_callback_when_live_progress_disabled(self, controller, scanner, settings):
        """No progress callback when show_live_progress is False."""
        settings.get.return_value = False

        controller.start_scan(["/test"])
        time.sleep(0.2)

        call_kwargs = scanner.scan_sync.call_args
        assert call_kwargs[1]["progress_callback"] is None

    def test_progress_callback_throttles(self, mock_gi_for_controller, scanner, settings):
        """Progress callback should throttle updates to MIN_INTERVAL."""
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.core.scanner_types import ScanProgress
        from src.ui.scan.scan_controller import ScanController

        ctrl = ScanController(scanner, settings)
        on_progress = MagicMock()
        ctrl.set_callbacks(on_progress=on_progress)

        callback = ctrl._create_progress_callback()

        progress = ScanProgress(
            current_file="/test",
            files_scanned=1,
            files_total=10,
            infected_count=0,
            infected_files=[],
        )

        # First call should go through
        callback(progress)
        # Second immediate call should be throttled
        callback(progress)
        callback(progress)

        # Only first call should have triggered idle_add
        assert mock_gi_for_controller.idle_add.call_count == 1


# =============================================================================
# Worker exception recovery
# =============================================================================


class TestWorkerExceptionRecovery:
    """A crash inside the scan thread must not leave the UI stuck scanning."""

    def test_scanner_exception_resets_state_and_completes(self, controller, scanner):
        """If scan_sync raises, the worker must still reset state to IDLE and
        deliver a completion callback so the spinner/buttons recover."""
        from src.ui.scan.scan_controller import ScanState

        scanner.scan_sync.side_effect = RuntimeError("backend exploded")

        states = []
        on_complete = MagicMock()
        controller.set_callbacks(
            on_state_change=lambda s: states.append(s),
            on_complete=on_complete,
        )

        controller.start_scan(["/tmp/target"])
        time.sleep(0.2)

        # State must return to IDLE (not stuck in SCANNING forever).
        assert controller.state == ScanState.IDLE
        assert controller.is_scanning is False
        assert states and states[-1] == ScanState.IDLE
        # Completion must fire exactly once so the UI leaves the scanning state.
        on_complete.assert_called_once()
        _assert_status(on_complete.call_args[0][0], "error")


# =============================================================================
# Finalization ordering (is_scanning race)
# =============================================================================


class TestScanFinalization:
    """The worker must not flip state to IDLE before the main-loop finalizer.

    Regression: the worker thread set _state = IDLE in its finally block
    before the queued idle callbacks ran, opening a window where a re-entrant
    start_scan() on the main thread could spawn a second worker while the
    first scan's completion callbacks were still pending.
    """

    def test_state_stays_scanning_until_finalizer_runs(
        self, mock_gi_for_controller, scanner, settings
    ):
        if "src.ui.scan.scan_controller" in sys.modules:
            del sys.modules["src.ui.scan.scan_controller"]
        from src.ui.scan.scan_controller import ScanController, ScanState

        # Queue idle callbacks instead of executing them, emulating a busy
        # main loop that has not dispatched them yet.
        queued = []
        mock_gi_for_controller.idle_add.side_effect = lambda fn, *a: queued.append((fn, a)) or 1

        controller = ScanController(scanner, settings)
        states = []
        on_complete = MagicMock()
        controller.set_callbacks(
            on_state_change=lambda s: states.append(s),
            on_complete=on_complete,
        )

        controller.start_scan(["/tmp/target"])

        # Wait for the worker thread to finish and queue the finalizer.
        deadline = time.monotonic() + 2.0
        while not queued and time.monotonic() < deadline:
            time.sleep(0.01)
        assert queued, "worker never queued the finalizer idle callback"

        # Worker is done, but the finalizer has not run: still SCANNING, no
        # completion delivered, and a re-entrant start is ignored.
        assert controller.state == ScanState.SCANNING
        assert controller.is_scanning is True
        on_complete.assert_not_called()
        controller.start_scan(["/tmp/second"])
        assert scanner.scan_sync.call_count == 1

        # Dispatch the queued idles as the main loop would.
        for fn, args in list(queued):
            fn(*args)

        assert controller.state == ScanState.IDLE
        assert controller.is_scanning is False
        assert states[-1] == ScanState.IDLE
        on_complete.assert_called_once()
        _assert_status(on_complete.call_args[0][0], "clean")
