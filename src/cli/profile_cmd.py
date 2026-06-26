# ClamUI Profile Command
"""
CLI command for managing scan profiles.

Provides headless access to scan profile CRUD operations
including listing, viewing details, and importing/exporting.

Usage:
    clamui profile list
    clamui profile show "Quick Scan"
    clamui profile export "Quick Scan" backup.json
    clamui profile import backup.json
"""

import argparse

from ..core.i18n import _
from ..core.sanitize import sanitize_log_line
from ..profiles.profile_manager import ProfileManager
from .output import format_timestamp, get_config_dir, print_error, print_json, print_table


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the profile subcommand with the CLI router."""
    parser = subparsers.add_parser(
        "profile",
        help=_("Manage scan profiles"),
        description=_("List, view, export, or import scan profiles."),
    )
    sub = parser.add_subparsers(dest="action")

    # profile list
    list_parser = sub.add_parser("list", help=_("List all scan profiles"))
    list_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=_("Output as JSON"),
    )
    list_parser.set_defaults(func=run_list)

    # profile show <name>
    show_parser = sub.add_parser("show", help=_("Show details of a scan profile"))
    show_parser.add_argument("name", help=_("Profile name"))
    show_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=_("Output as JSON"),
    )
    show_parser.set_defaults(func=run_show)

    # profile export <name> <file>
    export_parser = sub.add_parser("export", help=_("Export a profile to a JSON file"))
    export_parser.add_argument("name", help=_("Profile name"))
    export_parser.add_argument("file", help=_("Output file path"))
    export_parser.set_defaults(func=run_export)

    # profile import <file>
    import_parser = sub.add_parser("import", help=_("Import a profile from a JSON file"))
    import_parser.add_argument("file", help=_("Input file path"))
    import_parser.set_defaults(func=run_import)

    parser.set_defaults(func=lambda args: parser.print_help() or 0)


def run_list(args: argparse.Namespace) -> int:
    """
    List all scan profiles.

    Args:
        args: Parsed CLI arguments (expects json_output flag).

    Returns:
        Exit code (always 0).
    """
    pm = ProfileManager(get_config_dir())
    profiles = pm.list_profiles()

    if args.json_output:
        print_json([p.to_dict() for p in profiles])
        return 0

    if not profiles:
        print(_("No scan profiles configured."))
        return 0

    headers = [_("Name"), _("Targets"), _("Default"), _("Updated")]
    rows = []
    for profile in profiles:
        targets_display = ", ".join(sanitize_log_line(t) for t in profile.targets[:2])
        if len(profile.targets) > 2:
            targets_display += _(" (+{n} more)").format(n=len(profile.targets) - 2)
        rows.append(
            [
                sanitize_log_line(profile.name),
                targets_display or _("(none)"),
                _("yes") if profile.is_default else _("no"),
                format_timestamp(profile.updated_at),
            ]
        )

    print_table(headers, rows)
    print(_("\n{count} profile(s)").format(count=len(profiles)))
    return 0


def run_show(args: argparse.Namespace) -> int:
    """
    Show detailed information about a scan profile.

    Args:
        args: Parsed CLI arguments (expects name and json_output).

    Returns:
        Exit code: 0 = found, 1 = not found.
    """
    pm = ProfileManager(get_config_dir())
    profile = pm.get_profile_by_name(args.name)

    if profile is None:
        print_error(_("Profile not found: {name}").format(name=args.name))
        return 1

    if args.json_output:
        print_json(profile.to_dict())
        return 0

    # Text detail view
    print(_("Name:        {name}").format(name=sanitize_log_line(profile.name)))
    print(_("ID:          {id}").format(id=profile.id))
    print(_("Default:     {value}").format(value=_("yes") if profile.is_default else _("no")))
    if profile.description:
        print(_("Description: {desc}").format(desc=sanitize_log_line(profile.description)))
    print(_("Created:     {date}").format(date=format_timestamp(profile.created_at)))
    print(_("Updated:     {date}").format(date=format_timestamp(profile.updated_at)))

    print(_("\nTargets:"))
    if profile.targets:
        for target in profile.targets:
            print(f"  - {sanitize_log_line(target)}")
    else:
        print(_("  (none)"))

    excl_paths = profile.exclusions.get("paths", [])
    excl_patterns = profile.exclusions.get("patterns", [])
    if excl_paths or excl_patterns:
        print(_("\nExclusions:"))
        for path in excl_paths:
            print(_("  path:    {path}").format(path=sanitize_log_line(path)))
        for pattern in excl_patterns:
            print(_("  pattern: {pattern}").format(pattern=sanitize_log_line(pattern)))

    if profile.options:
        print(_("\nOptions:"))
        for key, value in profile.options.items():
            print(f"  {sanitize_log_line(key)}: {sanitize_log_line(str(value))}")

    return 0


def run_export(args: argparse.Namespace) -> int:
    """
    Export a profile to a JSON file.

    Args:
        args: Parsed CLI arguments (expects name and file).

    Returns:
        Exit code: 0 = success, 1 = failure.
    """
    pm = ProfileManager(get_config_dir())
    profile = pm.get_profile_by_name(args.name)

    if profile is None:
        print_error(_("Profile not found: {name}").format(name=args.name))
        return 1

    try:
        pm.export_profile(profile.id, args.file)
        print(_("Exported '{name}' to {file}").format(name=profile.name, file=args.file))
        return 0
    except (OSError, ValueError) as e:
        print_error(str(e))
        return 1


def run_import(args: argparse.Namespace) -> int:
    """
    Import a profile from a JSON file.

    Args:
        args: Parsed CLI arguments (expects file).

    Returns:
        Exit code: 0 = success, 1 = failure.
    """
    pm = ProfileManager(get_config_dir())

    try:
        profile = pm.import_profile(args.file)
        print(_("Imported profile: {name}").format(name=profile.name))
        return 0
    except (OSError, ValueError) as e:
        print_error(str(e))
        return 1
