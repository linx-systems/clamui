#!/usr/bin/env python3
# ClamUI Scheduled Scan CLI Entry Point
"""
CLI entry point for headless scheduled scan execution.

This module provides the main() function used by the clamui-scheduled-scan
console script entry point defined in pyproject.toml.

It is invoked by systemd timers or cron jobs to execute scheduled antivirus
scans without requiring a GUI environment.

Usage:
    clamui-scheduled-scan [OPTIONS]

Options:
    --skip-on-battery     Skip scan if running on battery power
    --auto-quarantine     Automatically quarantine detected threats
    --target PATH         Path to scan (can be specified multiple times)
    --dry-run             Show what would be done without executing
    --verbose             Enable verbose output
    --help                Show this help message

Examples:
    # Run scheduled scan with settings from config
    clamui-scheduled-scan

    # Scan specific targets with battery skip
    clamui-scheduled-scan --skip-on-battery --target /home/user/Documents

    # Scan with auto-quarantine enabled
    clamui-scheduled-scan --auto-quarantine --target /home/user/Downloads
"""

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..core.battery_manager import BatteryManager
from ..core.i18n import _
from ..core.log_manager import LogEntry, LogManager
from ..core.quarantine import QuarantineManager
from ..core.scanner import Scanner, ScanResult, ScanStatus
from ..core.settings_manager import SettingsManager


@dataclass
class ScanContext:
    """Context object holding all managers and configuration for a scheduled scan."""

    targets: list[str]
    skip_on_battery: bool
    auto_quarantine: bool
    dry_run: bool
    verbose: bool
    settings: SettingsManager | None = None
    battery_manager: BatteryManager | None = None
    log_manager: LogManager | None = None
    scanner: Scanner | None = None

    def __post_init__(self) -> None:
        # Create managers if not provided (allows mocking in tests)
        if self.settings is None:
            self.settings = SettingsManager()
        if self.battery_manager is None:
            self.battery_manager = BatteryManager()
        if self.log_manager is None:
            self.log_manager = LogManager()
        if self.scanner is None:
            self.scanner = Scanner(log_manager=self.log_manager, settings_manager=self.settings)


@dataclass
class ScanAggregateResult:
    """Aggregated results from scanning multiple targets."""

    total_scanned: int = 0
    total_infected: int = 0
    all_infected_files: list[str] = field(default_factory=list)
    all_results: list[ScanResult] = field(default_factory=list)
    has_errors: bool = False
    duration: float = 0.0
    valid_targets: list[str] = field(default_factory=list)


@dataclass
class QuarantineResult:
    """Results from quarantine processing."""

    quarantined_count: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description=_("ClamUI Scheduled Scan - Headless antivirus scanning"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_(
            "\nExamples:\n"
            "  %(prog)s                                    # Use settings from config\n"
            "  %(prog)s --target /home/user/Documents      # Scan specific directory\n"
            "  %(prog)s --skip-on-battery --auto-quarantine "
            "# Skip on battery, quarantine threats\n"
        ),
    )

    parser.add_argument(
        "--skip-on-battery",
        action="store_true",
        default=None,
        help=_("Skip scan if running on battery power"),
    )

    parser.add_argument(
        "--auto-quarantine",
        action="store_true",
        default=None,
        help=_("Automatically quarantine detected threats"),
    )

    parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        metavar="PATH",
        help=_("Path to scan (can be specified multiple times)"),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=_("Show what would be done without executing"),
    )

    parser.add_argument("--verbose", "-v", action="store_true", help=_("Enable verbose output"))

    return parser.parse_args()


def log_message(message: str, verbose: bool = False, is_verbose: bool = False) -> None:
    """
    Log a message to stderr.

    Args:
        message: The message to log
        verbose: Whether verbose mode is enabled
        is_verbose: Whether this is a verbose-only message
    """
    if is_verbose and not verbose:
        return
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", file=sys.stderr)


def send_notification(title: str, body: str, urgency: str = "normal") -> bool:
    """
    Send a desktop notification using notify-send.

    This is a headless alternative to Gio.Notification that works
    without requiring a running GTK application.

    Args:
        title: Notification title
        body: Notification body text
        urgency: Urgency level (low, normal, critical)

    Returns:
        True if notification was sent successfully, False otherwise
    """
    try:
        # Use notify-send for headless notifications
        cmd = ["notify-send"]

        # Set urgency level
        if urgency in ("low", "normal", "critical"):
            cmd.extend(["--urgency", urgency])

        # Add app name for proper categorization
        cmd.extend(["--app-name", "ClamUI"])

        # Add icon if available
        icon_paths = [
            "/app/share/icons/hicolor/scalable/apps/io.github.linx_systems.ClamUI.png",  # Flatpak
            "/usr/share/icons/hicolor/scalable/apps/io.github.linx_systems.ClamUI.png",  # System
            os.path.expanduser(
                "~/.local/share/icons/hicolor/scalable/apps/io.github.linx_systems.ClamUI.png"
            ),  # User
            "dialog-warning",  # Fallback system icon
        ]
        for icon in icon_paths:
            if (icon.startswith("/") and os.path.exists(icon)) or not icon.startswith("/"):
                cmd.extend(["--icon", icon])
                break

        # Add title and body
        cmd.extend([title, body])

        result = subprocess.run(cmd, capture_output=True, timeout=5)
        return result.returncode == 0

    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        # notify-send not available or failed
        return False


def _check_battery_status(ctx: ScanContext) -> int | None:
    """
    Check battery status and skip scan if on battery power.

    Args:
        ctx: Scan context with configuration and managers

    Returns:
        Exit code (0) if scan should be skipped, None to continue
    """
    if not ctx.skip_on_battery:
        return None

    log_message(_("Checking battery status..."), ctx.verbose, is_verbose=True)

    if not ctx.battery_manager.should_skip_scan(skip_on_battery=True):
        return None

    battery_status = ctx.battery_manager.get_status()
    percent = battery_status.percent or 0
    log_message(
        _("Skipping scan: running on battery power ({percent:.0f}%)").format(percent=percent),
        ctx.verbose,
    )

    log_entry = LogEntry.create(
        log_type="scan",
        status="skipped",
        summary=_("Scheduled scan skipped (on battery power)"),
        details=_(
            "Battery level: {percent:.0f}%\nScan skipped due to battery-aware settings."
        ).format(percent=percent),
        path=", ".join(ctx.targets) if ctx.targets else "N/A",
        scheduled=True,
    )
    ctx.log_manager.save_log(log_entry)

    return 0


def _validate_targets(targets: list[str], verbose: bool) -> tuple[list[str], int | None]:
    """
    Validate scan targets and return valid paths.

    Args:
        targets: List of target paths to validate
        verbose: Whether to enable verbose logging

    Returns:
        Tuple of (valid_targets, error_code) where error_code is None if valid
    """
    if not targets:
        log_message(_("Error: No scan targets specified"), verbose)
        return [], 2

    valid_targets = []
    for target in targets:
        target_path = Path(target).expanduser()
        if target_path.exists():
            valid_targets.append(str(target_path))
        else:
            log_message(
                _("Warning: Target does not exist: {target}").format(target=target),
                verbose,
            )

    if not valid_targets:
        log_message(_("Error: No valid scan targets found"), verbose)
        return [], 2

    return valid_targets, None


def _handle_dry_run(ctx: ScanContext, valid_targets: list[str]) -> int:
    """
    Handle dry run mode by logging what would be done.

    Args:
        ctx: Scan context with configuration
        valid_targets: List of validated target paths

    Returns:
        Exit code (0 for dry run)
    """
    log_message(_("Dry run mode - scan not executed"), ctx.verbose)
    log_message(_("  Skip on battery: {value}").format(value=ctx.skip_on_battery), ctx.verbose)
    log_message(_("  Auto quarantine: {value}").format(value=ctx.auto_quarantine), ctx.verbose)
    log_message(_("  Targets: {targets}").format(targets=valid_targets), ctx.verbose)
    return 0


def _check_clamav_availability(
    ctx: ScanContext, valid_targets: list[str]
) -> tuple[str | None, int | None]:
    """
    Check ClamAV availability and return version or error.

    Args:
        ctx: Scan context with scanner
        valid_targets: List of validated target paths

    Returns:
        Tuple of (version_string, error_code) where error_code is None if available
    """
    is_available, version_or_error = ctx.scanner.check_available()

    if is_available:
        log_message(
            _("ClamAV version: {version}").format(version=version_or_error),
            ctx.verbose,
            is_verbose=True,
        )
        return version_or_error, None

    log_message(
        _("Error: ClamAV not available - {error}").format(error=version_or_error),
        ctx.verbose,
    )

    log_entry = LogEntry.create(
        log_type="scan",
        status="error",
        summary=_("Scheduled scan failed: ClamAV not available"),
        details=version_or_error or _("ClamAV is not installed or not accessible"),
        path=", ".join(valid_targets),
        scheduled=True,
    )
    ctx.log_manager.save_log(log_entry)

    send_notification(
        _("Scheduled Scan Failed"),
        _("ClamAV is not available. Please install ClamAV."),
        urgency="critical",
    )
    return None, 2


def _execute_scans(ctx: ScanContext, valid_targets: list[str]) -> ScanAggregateResult:
    """
    Execute scans on all valid targets.

    Args:
        ctx: Scan context with scanner
        valid_targets: List of validated target paths

    Returns:
        Aggregated scan results
    """
    log_message(_("Scanning {count} target(s)...").format(count=len(valid_targets)), ctx.verbose)
    for target in valid_targets:
        log_message(f"  - {target}", ctx.verbose, is_verbose=True)

    agg = ScanAggregateResult(valid_targets=valid_targets)
    start_time = time.monotonic()

    for target in valid_targets:
        log_message(_("Scanning: {target}").format(target=target), ctx.verbose)
        result = ctx.scanner.scan_sync(target, recursive=True)
        agg.all_results.append(result)

        agg.total_scanned += result.scanned_files
        agg.total_infected += result.infected_count
        agg.all_infected_files.extend(result.infected_files)

        if result.status == ScanStatus.ERROR:
            agg.has_errors = True
            log_message(_("  Error: {error}").format(error=result.error_message), ctx.verbose)
        elif result.status == ScanStatus.INFECTED:
            log_message(
                _("  Found {count} threat(s)").format(count=result.infected_count),
                ctx.verbose,
            )
        else:
            log_message(
                _("  Clean ({count} files scanned)").format(count=result.scanned_files),
                ctx.verbose,
            )

    agg.duration = time.monotonic() - start_time
    return agg


def _process_quarantine(ctx: ScanContext, agg: ScanAggregateResult) -> QuarantineResult:
    """
    Process quarantine for infected files if auto_quarantine is enabled.

    Args:
        ctx: Scan context with configuration
        agg: Aggregated scan results

    Returns:
        Quarantine processing results
    """
    qr = QuarantineResult()

    if not agg.all_infected_files or not ctx.auto_quarantine:
        return qr

    log_message(
        _("Quarantining {count} infected file(s)...").format(count=len(agg.all_infected_files)),
        ctx.verbose,
    )

    quarantine_manager = QuarantineManager()

    # Collect all threat details from scan results
    all_threat_details = []
    for result in agg.all_results:
        all_threat_details.extend(result.threat_details)

    # Quarantine each infected file with its threat name
    for threat in all_threat_details:
        quarantine_result = quarantine_manager.quarantine_file(threat.file_path, threat.threat_name)
        if quarantine_result.is_success:
            qr.quarantined_count += 1
        else:
            error_msg = quarantine_result.error_message or str(quarantine_result.status.value)
            qr.failed.append((threat.file_path, error_msg))

    if qr.quarantined_count > 0:
        log_message(
            _("  Successfully quarantined: {count} file(s)").format(count=qr.quarantined_count),
            ctx.verbose,
        )
    if qr.failed:
        log_message(
            _("  Failed to quarantine: {count} file(s)").format(count=len(qr.failed)),
            ctx.verbose,
        )
        for file_path, error in qr.failed:
            log_message(f"    - {file_path}: {error}", ctx.verbose, is_verbose=True)

    return qr


def _build_summary_and_status(
    agg: ScanAggregateResult, qr: QuarantineResult, auto_quarantine: bool
) -> tuple[str, str]:
    """
    Build summary message and status string for logging.

    Args:
        agg: Aggregated scan results
        qr: Quarantine processing results
        auto_quarantine: Whether auto-quarantine was enabled

    Returns:
        Tuple of (summary, status)
    """
    if agg.total_infected > 0:
        if auto_quarantine and qr.quarantined_count > 0:
            summary = _(
                "Scheduled scan found {infected} threat(s), {quarantined} quarantined"
            ).format(
                infected=agg.total_infected,
                quarantined=qr.quarantined_count,
            )
        else:
            summary = _("Scheduled scan found {count} threat(s)").format(count=agg.total_infected)
        status = "infected"
    elif agg.has_errors:
        summary = _("Scheduled scan completed with errors")
        status = "error"
    else:
        summary = _("Scheduled scan completed - {count} files scanned, no threats").format(
            count=agg.total_scanned
        )
        status = "clean"

    return summary, status


def _build_log_details(
    agg: ScanAggregateResult, qr: QuarantineResult, auto_quarantine: bool
) -> str:
    """
    Build detailed log output string.

    Args:
        agg: Aggregated scan results
        qr: Quarantine processing results
        auto_quarantine: Whether auto-quarantine was enabled

    Returns:
        Detailed log string
    """
    details_parts = [
        _("Scan Duration: {duration:.1f} seconds").format(duration=agg.duration),
        _("Files Scanned: {count}").format(count=agg.total_scanned),
        _("Threats Found: {count}").format(count=agg.total_infected),
        _("Targets: {targets}").format(targets=", ".join(agg.valid_targets)),
    ]

    if auto_quarantine and agg.all_infected_files:
        details_parts.append(_("Quarantined: {count}").format(count=qr.quarantined_count))
        if qr.failed:
            details_parts.append(_("Quarantine Failed: {count}").format(count=len(qr.failed)))

    if agg.all_infected_files:
        infected_label = _("Infected Files")
        details_parts.append(f"\n--- {infected_label} ---")
        for result in agg.all_results:
            for threat in result.threat_details:
                details_parts.append(
                    f"  {threat.file_path}: {threat.threat_name} "
                    f"[{threat.category}/{threat.severity}]"
                )

    # Combine stdout from all scan results
    for i, result in enumerate(agg.all_results):
        if result.stdout.strip():
            scan_output_label = _("Scan Output ({target})").format(target=agg.valid_targets[i])
            details_parts.append(f"\n--- {scan_output_label} ---")
            details_parts.append(result.stdout)
        if result.stderr.strip():
            errors_label = _("Errors ({target})").format(target=agg.valid_targets[i])
            details_parts.append(f"\n--- {errors_label} ---")
            details_parts.append(result.stderr)

    return "\n".join(details_parts)


def _save_scan_log(
    ctx: ScanContext,
    agg: ScanAggregateResult,
    qr: QuarantineResult,
    summary: str,
    status: str,
    details: str,
) -> None:
    """
    Create and save the scan log entry.

    Args:
        ctx: Scan context with log manager
        agg: Aggregated scan results
        qr: Quarantine processing results
        summary: Summary message
        status: Status string
        details: Detailed log string
    """
    log_entry = LogEntry.create(
        log_type="scan",
        status=status,
        summary=summary,
        details=details,
        path=", ".join(agg.valid_targets),
        duration=agg.duration,
        scheduled=True,
    )
    ctx.log_manager.save_log(log_entry)


def _send_scan_notification(
    ctx: ScanContext, agg: ScanAggregateResult, qr: QuarantineResult
) -> None:
    """
    Send completion notification based on scan results.

    Args:
        ctx: Scan context with settings
        agg: Aggregated scan results
        qr: Quarantine processing results
    """
    if not ctx.settings.get("notifications_enabled", True):
        return

    if agg.total_infected > 0:
        if qr.quarantined_count > 0:
            body = _("{infected} infected file(s) found, {quarantined} quarantined").format(
                infected=agg.total_infected,
                quarantined=qr.quarantined_count,
            )
        else:
            body = _("{count} infected file(s) found").format(count=agg.total_infected)
        send_notification(_("Scheduled Scan: Threats Detected!"), body, urgency="critical")
    elif agg.has_errors:
        send_notification(
            _("Scheduled Scan Completed"),
            _("Scan completed with some errors. Check logs for details."),
            urgency="normal",
        )
    else:
        send_notification(
            _("Scheduled Scan Complete"),
            _("No threats found ({count} files scanned)").format(count=agg.total_scanned),
            urgency="low",
        )


def _determine_exit_code(agg: ScanAggregateResult) -> int:
    """
    Determine appropriate exit code based on scan results.

    Args:
        agg: Aggregated scan results

    Returns:
        Exit code (0=clean, 1=infected, 2=error)
    """
    if agg.total_infected > 0:
        return 1
    elif agg.has_errors:
        return 2
    else:
        return 0


def run_scheduled_scan(
    targets: list[str],
    skip_on_battery: bool,
    auto_quarantine: bool,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """
    Execute a scheduled scan.

    This function orchestrates the scheduled scan workflow by delegating
    to focused helper functions for each stage of the process.

    Args:
        targets: List of paths to scan
        skip_on_battery: Whether to skip scan if on battery
        auto_quarantine: Whether to quarantine detected threats
        dry_run: If True, show what would be done without executing
        verbose: Enable verbose output

    Returns:
        Exit code (0 for success/clean, 1 for threats found, 2 for error)
    """
    # Initialize context with all managers and configuration
    ctx = ScanContext(
        targets=targets,
        skip_on_battery=skip_on_battery,
        auto_quarantine=auto_quarantine,
        dry_run=dry_run,
        verbose=verbose,
    )

    log_message(_("ClamUI scheduled scan starting..."), verbose)

    # Check battery status
    battery_result = _check_battery_status(ctx)
    if battery_result is not None:
        return battery_result

    # Validate targets
    valid_targets, error_code = _validate_targets(targets, verbose)
    if error_code is not None:
        return error_code

    # Handle dry run mode
    if dry_run:
        return _handle_dry_run(ctx, valid_targets)

    # Check ClamAV availability
    clamav_error = _check_clamav_availability(ctx, valid_targets)[1]
    if clamav_error is not None:
        return clamav_error

    # Execute scans
    agg = _execute_scans(ctx, valid_targets)

    # Process quarantine if needed
    qr = _process_quarantine(ctx, agg)

    # Build log entry components
    summary, status = _build_summary_and_status(agg, qr, auto_quarantine)
    details = _build_log_details(agg, qr, auto_quarantine)

    # Save log and send notification
    _save_scan_log(ctx, agg, qr, summary, status, details)
    _send_scan_notification(ctx, agg, qr)

    log_message(
        _("Scan completed in {duration:.1f} seconds").format(duration=agg.duration),
        verbose,
    )
    log_message(summary, verbose)

    return _determine_exit_code(agg)


def main() -> int:
    """
    Main entry point for the scheduled scan CLI.

    Returns:
        Exit code (0 for success, 1 for threats, 2 for error)
    """
    args = parse_arguments()

    # Load settings
    settings = SettingsManager()

    # Determine effective settings (CLI args override config)
    if args.skip_on_battery is not None:
        skip_on_battery = args.skip_on_battery
    else:
        skip_on_battery = settings.get("schedule_skip_on_battery", True)

    if args.auto_quarantine is not None:
        auto_quarantine = args.auto_quarantine
    else:
        auto_quarantine = settings.get("schedule_auto_quarantine", False)

    # Determine targets (CLI args override config)
    if args.targets:
        targets = args.targets
    else:
        targets = settings.get("schedule_targets", [])
        # If no targets configured, default to home directory
        if not targets:
            home = os.path.expanduser("~")
            targets = [home]

    return run_scheduled_scan(
        targets=targets,
        skip_on_battery=skip_on_battery,
        auto_quarantine=auto_quarantine,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
