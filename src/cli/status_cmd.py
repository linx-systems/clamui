# ClamUI Status Command
"""
CLI command for displaying ClamAV and ClamUI status.

Shows ClamAV availability, active backend, daemon status,
and quarantine/log statistics.

Usage:
    clamui status
    clamui status --json
"""

import argparse

from ..core.i18n import _
from ..core.log_manager import LogManager
from ..core.quarantine import QuarantineManager
from ..core.scanner import Scanner
from ..core.settings_manager import SettingsManager
from .output import format_size, print_json


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the status subcommand with the CLI router."""
    parser = subparsers.add_parser(
        "status",
        help=_("Show ClamAV and ClamUI status"),
        description=_("Display ClamAV availability, backend, daemon, and statistics."),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=_("Output as JSON"),
    )
    parser.set_defaults(func=run)


def _collect_clamav_info(scanner: Scanner, log_manager: LogManager) -> dict:
    """
    Gather ClamAV availability and backend information.

    Returns:
        Dict with version, backend, daemon_status, and availability.
    """
    is_available, version_or_error = scanner.check_available()
    backend = scanner.get_active_backend()
    daemon_status, _ = log_manager.get_daemon_status()

    return {
        "available": is_available,
        "version": version_or_error if is_available else None,
        "error": version_or_error if not is_available else None,
        "backend": backend,
        "daemon_status": daemon_status.value,
    }


def _collect_quarantine_stats() -> dict:
    """
    Gather quarantine statistics.

    Returns:
        Dict with entry count and total size.
    """
    try:
        qm = QuarantineManager()
        return {
            "entries": qm.get_entry_count(),
            "total_size": qm.get_total_size(),
        }
    except Exception:
        return {"entries": 0, "total_size": 0}


def _collect_log_stats(log_manager: LogManager) -> dict:
    """
    Gather log statistics.

    Returns:
        Dict with total entry count.
    """
    try:
        return {"total_entries": log_manager.get_log_count()}
    except Exception:
        return {"total_entries": 0}


def run(args: argparse.Namespace) -> int:
    """
    Display ClamAV and ClamUI status information.

    Args:
        args: Parsed CLI arguments (expects json_output flag).

    Returns:
        Exit code (always 0).
    """
    settings = SettingsManager()
    log_manager = LogManager()
    # Pass the settings manager so the reported backend honors the user's
    # scan_backend / clamd_conf_path settings instead of always showing
    # the "auto" default.
    scanner = Scanner(log_manager=log_manager, settings_manager=settings)

    clamav_info = _collect_clamav_info(scanner, log_manager)
    quarantine_stats = _collect_quarantine_stats()
    log_stats = _collect_log_stats(log_manager)

    if args.json_output:
        data = {
            "clamav": clamav_info,
            "quarantine": quarantine_stats,
            "logs": log_stats,
            "settings": {
                "scan_backend": settings.get("scan_backend", "auto"),
                "notifications_enabled": settings.get("notifications_enabled", True),
            },
        }
        print_json(data)
        return 0

    # Text output
    print(_("ClamAV"))
    if clamav_info["available"]:
        print(_("  Version:  {version}").format(version=clamav_info["version"]))
    else:
        print(_("  Status:   not available"))
        print(_("  Error:    {error}").format(error=clamav_info["error"]))
    print(_("  Backend:  {backend}").format(backend=clamav_info["backend"]))
    print(_("  Daemon:   {status}").format(status=clamav_info["daemon_status"]))

    print(_("\nQuarantine"))
    print(_("  Entries:  {count}").format(count=quarantine_stats["entries"]))
    print(_("  Size:     {size}").format(size=format_size(quarantine_stats["total_size"])))

    print(_("\nScan History"))
    print(_("  Entries:  {count}").format(count=log_stats["total_entries"]))

    return 0
