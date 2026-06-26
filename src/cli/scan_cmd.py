# ClamUI Scan Command
"""
CLI command for headless file and directory scanning.

Provides a lightweight alternative to clamui-scheduled-scan for
one-shot scans without battery checks, notifications, or scheduled
scan infrastructure.

Usage:
    clamui scan /path/to/file
    clamui scan /home/user/Downloads --profile "Quick Scan"
    clamui scan /tmp --quarantine --json
"""

import argparse
import time
from pathlib import Path

from ..core.i18n import _
from ..core.log_manager import LogManager
from ..core.quarantine import QuarantineManager
from ..core.sanitize import sanitize_log_line
from ..core.scanner import Scanner
from ..core.scanner_types import ScanStatus
from ..core.settings_manager import SettingsManager
from ..profiles.profile_manager import ProfileManager
from .output import get_config_dir, print_error, print_info, print_json


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the scan subcommand with the CLI router."""
    parser = subparsers.add_parser(
        "scan",
        help=_("Scan files or directories for threats"),
        description=_(
            "Scan one or more files or directories with ClamAV.\n"
            "Exit codes: 0 = clean, 1 = threats found, 2 = error."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help=_("Files or directories to scan"),
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        default=False,
        help=_("Do not scan directories recursively"),
    )
    parser.add_argument(
        "--profile",
        "-p",
        metavar="NAME",
        help=_("Use a named scan profile for exclusions"),
    )
    parser.add_argument(
        "--quarantine",
        "-q",
        action="store_true",
        help=_("Automatically quarantine detected threats"),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=_("Output results as JSON"),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help=_("Enable verbose output"),
    )
    parser.set_defaults(func=run)


def _validate_paths(paths: list[str]) -> list[str]:
    """
    Validate and resolve scan target paths.

    Args:
        paths: Raw path strings from CLI arguments.

    Returns:
        List of resolved, existing paths.
    """
    valid = []
    for p in paths:
        resolved = Path(p).expanduser().resolve()
        if resolved.exists():
            valid.append(str(resolved))
        else:
            print_error(_("Path not found: {path}").format(path=p))
    return valid


def _resolve_profile_exclusions(profile_name: str, verbose: bool) -> dict | None:
    """
    Look up a scan profile by name and return its exclusions.

    Args:
        profile_name: Name of the scan profile.
        verbose: Whether to log info messages.

    Returns:
        Exclusions dict from the profile, or None on failure.
    """
    pm = ProfileManager(get_config_dir())
    profile = pm.get_profile_by_name(profile_name)
    if profile is None:
        print_error(_("Profile not found: {name}").format(name=profile_name))
        return None
    if verbose:
        print_info(_("Using profile: {name}").format(name=profile.name))
    return profile.exclusions


def _execute_scans(
    scanner: Scanner,
    paths: list[str],
    recursive: bool,
    exclusions: dict | None,
    verbose: bool,
) -> tuple[list, float]:
    """
    Run scans on all validated paths.

    Args:
        scanner: Configured Scanner instance.
        paths: Validated target paths.
        recursive: Whether to recurse into directories.
        exclusions: Profile exclusion dict, or None.
        verbose: Whether to log progress.

    Returns:
        Tuple of (list of ScanResult, duration in seconds).
    """
    results = []
    start = time.monotonic()
    for path in paths:
        if verbose:
            print_info(_("Scanning: {path}").format(path=path))
        result = scanner.scan_sync(path, recursive=recursive, profile_exclusions=exclusions)
        results.append(result)
    return results, time.monotonic() - start


def _quarantine_threats(threats: list) -> tuple[int, list[tuple[str, str]]]:
    """
    Quarantine all detected threats.

    Args:
        threats: List of ThreatDetail objects.

    Returns:
        Tuple of (quarantined count, list of (path, error) failures).
    """
    qm = QuarantineManager()
    quarantined = 0
    failures: list[tuple[str, str]] = []
    for threat in threats:
        qr = qm.quarantine_file(threat.file_path, threat.threat_name)
        if qr.is_success:
            quarantined += 1
        else:
            error_msg = qr.error_message or str(qr.status.value)
            failures.append((threat.file_path, error_msg))
    return quarantined, failures


def _format_json_output(
    results: list,
    valid_paths: list[str],
    duration: float,
    quarantine_info: tuple[int, list[tuple[str, str]]] | None,
) -> dict:
    """Build JSON output dict from scan results."""
    total_scanned = sum(r.scanned_files for r in results)
    total_infected = sum(r.infected_count for r in results)
    has_errors = any(r.status == ScanStatus.ERROR for r in results)
    all_threats = [t for r in results for t in r.threat_details]

    output: dict = {
        "status": "infected" if total_infected > 0 else ("error" if has_errors else "clean"),
        "scanned_files": total_scanned,
        "infected_count": total_infected,
        "duration_seconds": round(duration, 2),
        "targets": valid_paths,
        "threats": [
            {
                "file": t.file_path,
                "threat_name": t.threat_name,
                "category": t.category,
                "severity": t.severity,
            }
            for t in all_threats
        ],
    }

    if quarantine_info is not None:
        quarantined, failures = quarantine_info
        output["quarantined"] = quarantined
        if failures:
            output["quarantine_failures"] = [{"file": f, "error": e} for f, e in failures]

    errors = [r.error_message for r in results if r.status == ScanStatus.ERROR and r.error_message]
    if errors:
        output["errors"] = errors

    return output


def _print_text_output(
    results: list,
    duration: float,
    quarantine_info: tuple[int, list[tuple[str, str]]] | None,
) -> None:
    """Print human-readable scan results to stdout."""
    total_scanned = sum(r.scanned_files for r in results)
    total_infected = sum(r.infected_count for r in results)
    has_errors = any(r.status == ScanStatus.ERROR for r in results)
    all_threats = [t for r in results for t in r.threat_details]

    print(
        _("Scanned {count} files in {duration:.1f}s").format(count=total_scanned, duration=duration)
    )

    if total_infected > 0:
        print(_("\nThreats found: {count}").format(count=total_infected))
        for t in all_threats:
            print(f"  {sanitize_log_line(t.file_path)}")
            print(f"    {sanitize_log_line(t.threat_name)} [{t.category}/{t.severity}]")
        if quarantine_info:
            quarantined, failures = quarantine_info
            if quarantined:
                print(_("\nQuarantined: {count} file(s)").format(count=quarantined))
            if failures:
                print(_("\nFailed to quarantine:"))
                for filepath, error in failures:
                    print(f"  {sanitize_log_line(filepath)}: {sanitize_log_line(error)}")
    elif has_errors:
        print(_("\nScan completed with errors:"))
        for r in results:
            if r.status == ScanStatus.ERROR and r.error_message:
                print(f"  {r.error_message}")
    else:
        print(_("No threats found."))


def run(args: argparse.Namespace) -> int:
    """
    Execute the scan command.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code: 0 = clean, 1 = threats found, 2 = error.
    """
    # Validate paths
    valid_paths = _validate_paths(args.paths)
    if not valid_paths:
        print_error(_("No valid paths to scan"))
        return 2

    # Check ClamAV availability
    log_manager = LogManager()
    settings_manager = SettingsManager()
    scanner = Scanner(log_manager=log_manager, settings_manager=settings_manager)
    is_available, version_or_error = scanner.check_available()
    if not is_available:
        print_error(_("ClamAV not available: {error}").format(error=version_or_error))
        return 2
    if args.verbose:
        print_info(_("ClamAV version: {version}").format(version=version_or_error))

    # Resolve profile exclusions
    exclusions = None
    if args.profile:
        exclusions = _resolve_profile_exclusions(args.profile, args.verbose)
        if exclusions is None:
            return 2

    # Execute scans
    results, duration = _execute_scans(
        scanner, valid_paths, not args.no_recursive, exclusions, args.verbose
    )

    # Auto-quarantine if requested
    quarantine_info = None
    all_threats = [t for r in results for t in r.threat_details]
    if args.quarantine and all_threats:
        quarantine_info = _quarantine_threats(all_threats)

    # Output
    if args.json_output:
        print_json(_format_json_output(results, valid_paths, duration, quarantine_info))
    else:
        _print_text_output(results, duration, quarantine_info)

    # Determine exit code
    total_infected = sum(r.infected_count for r in results)
    has_errors = any(r.status == ScanStatus.ERROR for r in results)
    if total_infected > 0:
        return 1
    elif has_errors:
        return 2
    return 0
