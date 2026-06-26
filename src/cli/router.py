# ClamUI CLI Router
"""
Subcommand router for the ClamUI command-line interface.

Dispatches CLI subcommands (scan, quarantine, profile, status, history)
to their respective handler modules. This module is only imported when
a CLI subcommand is detected, avoiding GTK initialization overhead.

Usage:
    clamui scan /path/to/file
    clamui quarantine list
    clamui profile list
    clamui status
    clamui history
"""

import argparse
import sys

from ..core.i18n import _

# Set of recognized subcommand names for detection in main.py
CLI_SUBCOMMANDS = frozenset(
    {
        "scan",
        "quarantine",
        "profile",
        "status",
        "history",
        "help",
        "install-privileged-helper",
    }
)


def cli_main() -> int:
    """
    Parse CLI arguments and dispatch to the appropriate subcommand handler.

    Each subcommand module provides a ``register(subparsers)`` function that
    configures its argument parser and sets ``args.func`` to its entry point.

    Returns:
        Exit code from the dispatched subcommand handler.
    """
    parser = argparse.ArgumentParser(
        prog="clamui",
        description=_("ClamUI — ClamAV antivirus management"),
        epilog=_(
            "Run 'clamui <command> --help' for details on a specific command.\n"
            "Run 'clamui' without arguments to launch the graphical interface."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title=_("commands"),
        metavar="<command>",
    )

    # Register all subcommands (lazy imports to avoid unnecessary loading)
    from .help_cmd import register as register_help
    from .history_cmd import register as register_history
    from .install_helper import register as register_install_helper
    from .profile_cmd import register as register_profile
    from .quarantine_cmd import register as register_quarantine
    from .scan_cmd import register as register_scan
    from .status_cmd import register as register_status

    register_scan(subparsers)
    register_quarantine(subparsers)
    register_profile(subparsers)
    register_status(subparsers)
    register_history(subparsers)
    register_help(subparsers)
    register_install_helper(subparsers)

    args = parser.parse_args(sys.argv[1:])

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)
