# Scan Controller
"""
Scan orchestration logic extracted from ScanView.

Single responsibility:
- Starting/cancelling scans
- Multi-target coordination
- Progress aggregation
- Result compilation
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from gi.repository import GLib

from ...core.result_formatters import compose_scan_warning
from ...core.scanner import Scanner, ScanProgress, ScanResult, ScanStatus
from ...core.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class ScanState(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    CANCELLED = "cancelled"


@dataclass
class AggregatedResult:
    """Combined result from multi-target scan."""

    status: ScanStatus = ScanStatus.CLEAN
    total_files: int = 0
    total_dirs: int = 0
    total_infected: int = 0
    infected_files: list[str] = field(default_factory=list)
    threat_details: list = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    skipped_count: int = 0
    nonfatal_warnings: list[str] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)

    def to_scan_result(self, paths: list[str]) -> ScanResult:
        """Convert to ScanResult for dialog compatibility."""
        exit_code = 1 if self.status == ScanStatus.INFECTED else (2 if self.error_messages else 0)
        warning_message = compose_scan_warning(self.skipped_count, self.warning_messages)
        return ScanResult(
            status=self.status,
            path=", ".join(paths) if len(paths) > 1 else paths[0] if paths else "",
            stdout="",
            stderr="",
            exit_code=exit_code,
            infected_files=self.infected_files,
            scanned_files=self.total_files,
            scanned_dirs=self.total_dirs,
            infected_count=self.total_infected,
            error_message="; ".join(self.error_messages) if self.error_messages else None,
            threat_details=self.threat_details,
            skipped_files=self.skipped_files,
            skipped_count=self.skipped_count,
            warning_message=warning_message,
            nonfatal_warnings=self.nonfatal_warnings,
        )


class ScanController:
    """
    Orchestrates scan operations.

    Usage:
        controller = ScanController(scanner, settings_manager)
        controller.set_callbacks(
            on_progress=update_progress_ui,
            on_complete=show_results,
            on_state_change=update_buttons,
        )
        controller.start_scan(paths, profile_exclusions)
        controller.cancel()
    """

    def __init__(self, scanner: Scanner, settings_manager: SettingsManager | None = None):
        self._scanner = scanner
        self._settings = settings_manager

        self._state = ScanState.IDLE
        self._cancel_all = False
        self._cumulative_files = 0
        self._current_target_idx = 1
        self._total_targets = 1

        self._on_progress: Callable[[ScanProgress, int, int], None] | None = None
        self._on_complete: Callable[[ScanResult], None] | None = None
        self._on_state_change: Callable[[ScanState], None] | None = None
        self._on_target_progress: Callable[[int, int, str], None] | None = None

    def set_callbacks(
        self,
        on_progress: Callable[[ScanProgress, int, int], None] | None = None,
        on_complete: Callable[[ScanResult], None] | None = None,
        on_state_change: Callable[[ScanState], None] | None = None,
    ):
        """Set callbacks for UI updates."""
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_state_change = on_state_change

    @property
    def state(self) -> ScanState:
        return self._state

    @property
    def is_scanning(self) -> bool:
        return self._state == ScanState.SCANNING

    @property
    def current_target_idx(self) -> int:
        return self._current_target_idx

    @property
    def total_targets(self) -> int:
        return self._total_targets

    def start_scan(
        self,
        paths: list[str],
        profile_exclusions: dict | None = None,
        on_target_progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """
        Start scanning multiple paths.

        Args:
            paths: List of paths to scan
            profile_exclusions: Optional exclusions from profile
            on_target_progress: Callback for multi-target progress (current, total, path)
        """
        if not paths:
            return

        # Ignore re-entrant starts: a scan already running would otherwise spawn
        # a second worker thread sharing this controller's Scanner, racing on
        # cancellation state and delivering duplicate completion callbacks.
        if self._state == ScanState.SCANNING:
            return

        self._state = ScanState.SCANNING
        self._cancel_all = False
        self._cumulative_files = 0
        self._total_targets = len(paths)
        self._on_target_progress = on_target_progress

        if self._on_state_change:
            self._on_state_change(self._state)

        thread = threading.Thread(
            target=self._scan_worker,
            args=(paths, profile_exclusions),
            daemon=True,
        )
        thread.start()

    def cancel(self) -> None:
        """Cancel current scan and skip remaining targets."""
        self._cancel_all = True
        self._scanner.cancel()

    def _scan_worker(self, paths: list[str], profile_exclusions: dict | None):
        """Background worker for multi-target scanning."""
        result = AggregatedResult()
        try:
            total_targets = len(paths)

            show_live = True
            if self._settings:
                show_live = self._settings.get("show_live_progress", True)

            progress_callback = self._create_progress_callback() if show_live else None

            for idx, path in enumerate(paths, start=1):
                if self._cancel_all:
                    result.status = ScanStatus.CANCELLED
                    break

                self._current_target_idx = idx

                if self._on_target_progress:
                    GLib.idle_add(self._on_target_progress, idx, total_targets, path)

                scan_result = self._scanner.scan_sync(
                    path,
                    recursive=True,
                    profile_exclusions=profile_exclusions,
                    progress_callback=progress_callback,
                )

                if scan_result.status == ScanStatus.CANCELLED or self._cancel_all:
                    self._aggregate_partial(result, scan_result)
                    result.status = ScanStatus.CANCELLED
                    break

                self._cumulative_files += scan_result.scanned_files
                self._aggregate_result(result, scan_result)

            if result.status != ScanStatus.CANCELLED:
                if result.total_infected > 0:
                    result.status = ScanStatus.INFECTED
                elif result.error_messages:
                    result.status = ScanStatus.ERROR
                else:
                    result.status = ScanStatus.CLEAN
        except Exception as exc:
            # A crash in the scan worker thread must never leave the UI stuck
            # in the SCANNING state (spinner spinning, buttons disabled). Record
            # the failure as an error result and fall through to finalization so
            # on_state_change(IDLE) and on_complete still fire on the main loop.
            logger.exception("Scan worker thread crashed")
            result.status = ScanStatus.ERROR
            if not result.error_messages:
                result.error_messages.append(str(exc))
        finally:
            final_result = result.to_scan_result(paths)

            def _finalize():
                # Runs on the main thread: flipping to IDLE here (rather than
                # on the worker thread) keeps is_scanning True until callers
                # of start_scan — which is main-thread-only — can no longer
                # race a second worker against this one. Completion is
                # delivered BEFORE the state change: state-change consumers
                # (tray status, coordinator) read the current result, and
                # firing IDLE first would hand them the previous scan's
                # result (or None) — e.g. a "protected" tray icon right
                # after threats were found.
                self._state = ScanState.IDLE
                if self._on_complete:
                    self._on_complete(final_result)
                if self._on_state_change:
                    self._on_state_change(self._state)
                return False

            GLib.idle_add(_finalize)

    def _aggregate_result(self, agg: AggregatedResult, scan: ScanResult):
        """Add scan result to aggregated total."""
        self._aggregate_partial(agg, scan)

        if scan.status == ScanStatus.ERROR and scan.error_message:
            agg.error_messages.append(scan.error_message)
        elif scan.status == ScanStatus.INFECTED:
            agg.status = ScanStatus.INFECTED

    def _aggregate_partial(self, agg: AggregatedResult, scan: ScanResult):
        """Add partial results from cancelled scan."""
        agg.total_files += scan.scanned_files
        agg.total_dirs += scan.scanned_dirs
        agg.total_infected += scan.infected_count
        agg.infected_files.extend(scan.infected_files)
        agg.threat_details.extend(scan.threat_details)
        seen_skipped = set(agg.skipped_files)
        for skipped in scan.skipped_files or []:
            if skipped not in seen_skipped:
                seen_skipped.add(skipped)
                agg.skipped_files.append(skipped)
        # Keep the count in sync with the deduplicated list so overlapping
        # targets never over-report skipped files.
        agg.skipped_count = len(agg.skipped_files)
        seen_warnings = set(agg.nonfatal_warnings)
        for warning in scan.nonfatal_warnings or []:
            if warning not in seen_warnings:
                seen_warnings.add(warning)
                agg.nonfatal_warnings.append(warning)
        if scan.warning_message and scan.warning_message not in agg.warning_messages:
            agg.warning_messages.append(scan.warning_message)

    def _create_progress_callback(self):
        """Create throttled progress callback."""
        MIN_INTERVAL = 0.1
        last_update = [0.0]
        controller_self = self

        def callback(progress: ScanProgress):
            now = time.monotonic()
            if now - last_update[0] < MIN_INTERVAL:
                return
            last_update[0] = now

            if controller_self._on_progress:
                GLib.idle_add(
                    controller_self._on_progress,
                    progress,
                    controller_self._cumulative_files,
                    controller_self._total_targets,
                )

        return callback
