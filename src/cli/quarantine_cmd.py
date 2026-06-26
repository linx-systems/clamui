# ClamUI Quarantine Command
"""
CLI command for managing quarantined files.

Provides headless access to the quarantine subsystem for listing,
restoring, and deleting quarantined threats.

Usage:
    clamui quarantine list
    clamui quarantine list --json
    clamui quarantine restore 42
    clamui quarantine delete 42
"""

import argparse

from ..core.i18n import _
from ..core.quarantine import QuarantineManager
from ..core.sanitize import sanitize_log_line
from .output import format_size, format_timestamp, print_error, print_json, print_table


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the quarantine subcommand with the CLI router."""
    parser = subparsers.add_parser(
        "quarantine",
        help=_("Manage quarantined files"),
        description=_("List, restore, or permanently delete quarantined files."),
    )
    sub = parser.add_subparsers(dest="action")

    # quarantine list
    list_parser = sub.add_parser("list", help=_("List all quarantined files"))
    list_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=_("Output as JSON"),
    )
    list_parser.set_defaults(func=run_list)

    # quarantine restore <id>
    restore_parser = sub.add_parser(
        "restore", help=_("Restore a quarantined file to its original location")
    )
    restore_parser.add_argument("entry_id", type=int, metavar="ID", help=_("Quarantine entry ID"))
    restore_parser.set_defaults(func=run_restore)

    # quarantine delete <id>
    delete_parser = sub.add_parser("delete", help=_("Permanently delete a quarantined file"))
    delete_parser.add_argument("entry_id", type=int, metavar="ID", help=_("Quarantine entry ID"))
    delete_parser.set_defaults(func=run_delete)

    parser.set_defaults(func=lambda args: parser.print_help() or 0)


def run_list(args: argparse.Namespace) -> int:
    """
    List all quarantined files.

    Args:
        args: Parsed CLI arguments (expects json_output flag).

    Returns:
        Exit code (always 0).
    """
    qm = QuarantineManager()
    entries = qm.get_all_entries()

    if args.json_output:
        print_json([e.to_dict() for e in entries])
        return 0

    if not entries:
        print(_("No quarantined files."))
        return 0

    headers = [_("ID"), _("File"), _("Threat"), _("Date"), _("Size")]
    rows = []
    for entry in entries:
        rows.append(
            [
                str(entry.id),
                sanitize_log_line(entry.original_path),
                sanitize_log_line(entry.threat_name),
                format_timestamp(entry.detection_date),
                format_size(entry.file_size),
            ]
        )

    print_table(headers, rows)

    total_size = qm.get_total_size()
    print(
        _("\n{count} entry/entries ({size} total)").format(
            count=len(entries), size=format_size(total_size)
        )
    )
    return 0


def run_restore(args: argparse.Namespace) -> int:
    """
    Restore a quarantined file to its original location.

    Args:
        args: Parsed CLI arguments (expects entry_id).

    Returns:
        Exit code: 0 = success, 1 = failure.
    """
    qm = QuarantineManager()
    entry = qm.get_entry(args.entry_id)
    if entry is None:
        print_error(_("Quarantine entry not found: {id}").format(id=args.entry_id))
        return 1

    result = qm.restore_file(args.entry_id)
    if result.is_success:
        print(_("Restored: {path}").format(path=entry.original_path))
        return 0

    error_msg = result.error_message or str(result.status.value)
    print_error(_("Restore failed: {error}").format(error=error_msg))
    return 1


def run_delete(args: argparse.Namespace) -> int:
    """
    Permanently delete a quarantined file.

    Args:
        args: Parsed CLI arguments (expects entry_id).

    Returns:
        Exit code: 0 = success, 1 = failure.
    """
    qm = QuarantineManager()
    entry = qm.get_entry(args.entry_id)
    if entry is None:
        print_error(_("Quarantine entry not found: {id}").format(id=args.entry_id))
        return 1

    result = qm.delete_file(args.entry_id)
    if result.is_success:
        print(_("Deleted: {path}").format(path=entry.original_path))
        return 0

    error_msg = result.error_message or str(result.status.value)
    print_error(_("Delete failed: {error}").format(error=error_msg))
    return 1
