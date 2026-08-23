# ClamUI Help Command
"""
CLI command for displaying detailed help and usage examples.

Provides a richer overview than --help, including all available
subcommands with descriptions and common usage patterns.

Usage:
    clamui help
    clamui help scan
    clamui help quarantine
"""

import argparse
import sys

from ..core.i18n import N_, _

# Command descriptions and examples, kept in one place for maintainability.
# Summaries use N_() for deferred translation; translated at display time with _().
_COMMANDS: dict[str, dict[str, str | list[str]]] = {
    "scan": {
        "summary": N_("Scan files or directories for threats"),
        "examples": [
            "clamui scan /home/user/Downloads",
            "clamui scan /tmp --quarantine --json",
            'clamui scan . --profile "Quick Scan" -v',
            "clamui scan file1.txt dir/ --no-recursive",
        ],
    },
    "quarantine": {
        "summary": N_("Manage quarantined files"),
        "examples": [
            "clamui quarantine list",
            "clamui quarantine list --json",
            "clamui quarantine restore 42",
            "clamui quarantine delete 42",
        ],
    },
    "profile": {
        "summary": N_("Manage scan profiles"),
        "examples": [
            "clamui profile list",
            'clamui profile show "Full Scan"',
            'clamui profile export "Quick Scan" backup.json',
            "clamui profile import backup.json",
        ],
    },
    "status": {
        "summary": N_("Show ClamAV and ClamUI status"),
        "examples": [
            "clamui status",
            "clamui status --json",
        ],
    },
    "history": {
        "summary": N_("View scan history"),
        "examples": [
            "clamui history",
            "clamui history --limit 50",
            "clamui history --type scan --json",
        ],
    },
    "install-privileged-helper": {
        "summary": N_(
            "Install the polkit helper for saving system ClamAV configs (native host only)"
        ),
        "examples": [
            "sudo clamui install-privileged-helper",
        ],
    },
    "help": {
        "summary": N_("Show this help message"),
        "examples": [
            "clamui help",
            "clamui help scan",
        ],
    },
}


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the help subcommand with the CLI router."""
    parser = subparsers.add_parser(
        "help",
        help=_("Show detailed help and usage examples"),
        description=_("Display an overview of all commands or detailed help for a specific one."),
    )
    parser.add_argument(
        "topic",
        nargs="?",
        metavar="COMMAND",
        help=_("Command to show help for"),
    )
    parser.set_defaults(func=run)


def _print_overview() -> None:
    """Print the full command overview with all subcommands."""
    print(_("ClamUI — ClamAV antivirus management\n"))
    print(_("Usage:"))
    print(_("  clamui                   Launch the graphical interface"))
    print(_("  clamui <command> [args]   Run a CLI command\n"))
    print(_("Commands:"))

    # Determine column width from longest command name
    width = max(len(name) for name in _COMMANDS) + 2
    for name, info in _COMMANDS.items():
        summary = str(info["summary"])
        print(f"  {name:<{width}} {_(summary)}")

    print(_("\nGlobal options:"))
    print(_("  --json                   Machine-readable JSON output"))
    print(_("  -v, --verbose            Verbose output"))
    print(_("  -h, --help               Show help for any command\n"))
    print(_("Run 'clamui help <command>' for usage examples."))
    print(_("Run 'clamui' without arguments to launch the GUI."))


def _print_command_help(name: str) -> int:
    """
    Print detailed help for a single command.

    Args:
        name: Command name to look up.

    Returns:
        Exit code: 0 = found, 1 = unknown command.
    """
    info = _COMMANDS.get(name)
    if info is None:
        print(
            _("Unknown command: {name}\n").format(name=name),
            file=sys.stderr,
        )
        _print_overview()
        return 1

    summary = str(info["summary"])
    print(_("clamui {name} — {summary}\n").format(name=name, summary=_(summary)))
    print(_("Examples:"))
    for example in info.get("examples", []):
        print(f"  $ {example}")
    print(_("\nRun 'clamui {name} --help' for full option reference.").format(name=name))
    return 0


def run(args: argparse.Namespace) -> int:
    """
    Display help information.

    Args:
        args: Parsed CLI arguments (expects optional topic).

    Returns:
        Exit code: 0 = success, 1 = unknown topic.
    """
    if args.topic:
        return _print_command_help(args.topic)

    _print_overview()
    return 0
