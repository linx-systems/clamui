# ClamUI History Command
"""
CLI command for viewing scan history.

Displays recent scan results from the persistent log store,
with filtering by type and configurable output limit.

Usage:
    clamui history
    clamui history --limit 50
    clamui history --type scan --json
"""

import argparse

from ..core.i18n import _
from ..core.log_manager import LogManager
from .output import format_timestamp, print_error, print_json, print_table


def positive_int(value: str) -> int:
    """Argparse type for a strictly positive integer (>= 1)."""
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(_("--limit must be a positive integer")) from None
    if parsed < 1:
        raise argparse.ArgumentTypeError(_("--limit must be a positive integer"))
    return parsed


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the history subcommand with the CLI router."""
    parser = subparsers.add_parser(
        "history",
        help=_("View scan history"),
        description=_("Display recent scan, update, and VirusTotal results."),
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=positive_int,
        default=20,
        help=_("Number of entries to show (default: 20)"),
    )
    parser.add_argument(
        "--type",
        "-t",
        choices=["scan", "update", "virustotal"],
        dest="log_type",
        help=_("Filter by log type"),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=_("Output as JSON"),
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """
    Display scan history entries.

    Args:
        args: Parsed CLI arguments (expects limit, log_type, json_output).

    Returns:
        Exit code: 0 = success, 1 = error.
    """
    log_manager = LogManager()

    try:
        entries = log_manager.get_logs(limit=args.limit, log_type=args.log_type)
    except Exception as e:
        print_error(_("Failed to load history: {error}").format(error=str(e)))
        return 1

    if args.json_output:
        print_json([e.to_dict() for e in entries])
        return 0

    if not entries:
        print(_("No scan history found."))
        return 0

    headers = [_("Date"), _("Type"), _("Status"), _("Summary")]
    rows = []
    for entry in entries:
        summary = entry.summary
        if len(summary) > 60:
            summary = summary[:57] + "..."
        rows.append(
            [
                format_timestamp(entry.timestamp),
                entry.type,
                entry.status,
                summary,
            ]
        )

    print_table(headers, rows)

    try:
        total = log_manager.get_log_count()
    except Exception:
        total = len(entries)

    if total > len(entries):
        print(
            _("\nShowing {shown} of {total} entries. Use --limit to see more.").format(
                shown=len(entries), total=total
            )
        )

    return 0
