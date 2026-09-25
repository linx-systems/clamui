#!/usr/bin/env python3
# ClamUI Entry Point
"""
Main entry point for the ClamUI application.

This module provides the entry point for launching the ClamUI GTK4/Adwaita
desktop application and the CLI subcommand router. It handles path setup,
CLI argument parsing, and routes to either the graphical interface or
headless CLI commands.

Usage:
    clamui                                        # Launch GUI
    clamui /path/to/file.txt                      # GUI scan
    clamui --virustotal /path/to/file              # GUI VirusTotal scan
    clamui scan /path/to/file                      # Headless CLI scan
    clamui quarantine list                         # Manage quarantine
    clamui profile list                            # Manage profiles
    clamui status                                  # ClamAV health check
    clamui history                                 # View scan history
"""

import contextlib
import logging
import os
import sys


def _setup_path():
    """
    Ensure the project root is in sys.path.

    This allows the application to be run directly as a script
    (python src/main.py) while still supporting proper package imports.
    """
    # Get the directory containing this file (src/)
    src_dir = os.path.dirname(os.path.abspath(__file__))
    # Get project root (parent of src/)
    project_root = os.path.dirname(src_dir)

    if project_root not in sys.path:
        sys.path.insert(0, project_root)


# Set up path before importing application modules
_setup_path()


def _apply_language_setting():
    """
    Read the language setting from settings.json and set LANGUAGE env var.

    This reads the JSON file directly (without importing SettingsManager or
    i18n) to set the LANGUAGE environment variable before gettext is
    initialized at i18n import time.
    """
    import json

    config_dir = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    settings_path = os.path.join(config_dir, "clamui", "settings.json")
    try:
        with open(settings_path, encoding="utf-8") as f:
            settings = json.load(f)
        language = settings.get("language", "auto")
        if language and language != "auto":
            os.environ["LANGUAGE"] = language
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass  # No settings yet or invalid - use system default


# Apply language override BEFORE i18n initializes gettext
_apply_language_setting()

# Initialize i18n before any translatable strings are used
from .core.i18n import _  # noqa: F401 - initializes i18n at import time


def _configure_logging():
    """
    Configure the logging system early in startup.

    This must be called before importing modules that use logging
    so they inherit the correct log level and handlers.
    """
    from .core.logging_config import configure_logging
    from .core.settings_manager import SettingsManager

    settings = SettingsManager()
    configure_logging(
        log_level=settings.get("debug_log_level", "WARNING"),
        max_bytes=settings.get("debug_log_max_size_mb", 5) * 1024 * 1024,
        backup_count=settings.get("debug_log_max_files", 3),
    )


# Configure logging before other imports
_configure_logging()

# NOTE: ClamUIApp (GTK4) import is deferred to main() to allow CLI
# subcommands to run without initializing GTK.

logger = logging.getLogger(__name__)


def uri_to_path(uri: str) -> str:
    """
    Convert a file:// URI to a local filesystem path.

    Handles both file:// URIs (from Flatpak/portal) and regular paths.

    Args:
        uri: A file:// URI or regular filesystem path.

    Returns:
        The filesystem path.
    """
    from urllib.parse import unquote, urlparse

    if uri.startswith("file://"):
        parsed = urlparse(uri)
        # Decode percent-encoded characters (e.g., %20 -> space)
        return unquote(parsed.path)
    return uri


def parse_arguments(argv: list[str]) -> tuple[list[str], bool, list[str]]:
    """
    Parse command line arguments for file paths and VirusTotal flag.

    This function extracts file and folder paths from the command line
    arguments, typically passed from file manager context menu actions
    via the %U field code in desktop files. It handles both file:// URIs
    (used by Flatpak/portal) and regular filesystem paths.

    Args:
        argv: Command line arguments (sys.argv).

    Returns:
        Tuple of (file_paths, is_virustotal_scan, unknown_args):
        - file_paths: List of file/folder paths to scan. Empty list if none.
        - is_virustotal_scan: True if --virustotal flag was provided.
        - unknown_args: List of unrecognized args to pass to GTK.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="ClamUI - Graphical interface for ClamAV antivirus",
        prog="clamui",
    )
    parser.add_argument(
        "--virustotal",
        action="store_true",
        help="Scan files with VirusTotal instead of ClamAV",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files or directories to scan (paths or file:// URIs)",
    )

    # Parse only known args to allow GTK to process its own arguments
    args, unknown_args = parser.parse_known_args(argv[1:])

    # Convert URIs to paths (handles both file:// URIs and regular paths)
    file_paths = [uri_to_path(f) for f in args.files] if args.files else []

    if file_paths:
        # Keep startup diagnostics privacy-safe: report counts only.
        mode = "VirusTotal" if args.virustotal else "ClamAV"
        print(
            f"ClamUI: Received {len(file_paths)} path(s) for {mode} scanning.",
            file=sys.stderr,
        )

    return file_paths, args.virustotal, unknown_args


def parse_file_arguments(argv: list[str]) -> list[str]:
    """
    Parse file/folder paths from command line arguments.

    This function extracts file and folder paths from the command line
    arguments, typically passed from file manager context menu actions
    via the %F field code in desktop files.

    .. deprecated:: 0.2.0
        Use :func:`parse_arguments` instead, which also supports the
        --virustotal flag.

    Args:
        argv: Command line arguments (sys.argv).

    Returns:
        List of file/folder paths to scan. Empty list if no paths provided.
    """
    return parse_arguments(argv)[0]


def _run_gui_application(app, argv: list[str]) -> int:
    """
    Run the GTK application and translate Ctrl+C into a clean exit code.

    PyGObject's SIGINT fallback calls ``app.quit()`` and then re-raises
    ``KeyboardInterrupt`` when unwinding ``Gio.Application.run()``. Catch that
    here so terminal launches exit without a traceback.
    """
    try:
        return app.run(argv)
    except KeyboardInterrupt:
        with contextlib.suppress(Exception):
            app.quit()
        logger.info("Application interrupted by SIGINT")
        return 130


def main():
    """
    Application entry point.

    Routes to CLI subcommands if the first argument is a recognized
    command name (scan, quarantine, profile, status, history).
    Otherwise launches the GTK4 graphical interface.

    Returns:
        int: Exit code from the application (0 for success).
    """
    # Route to CLI if first argument is a known subcommand
    from .cli.router import CLI_SUBCOMMANDS

    if len(sys.argv) > 1 and sys.argv[1] in CLI_SUBCOMMANDS:
        from .cli.router import cli_main

        return cli_main()

    # Import GTK application class (deferred to avoid GTK init for CLI)
    from .app import ClamUIApp

    # Create application instance
    app = ClamUIApp()

    # Pass all arguments to app.run() - do_command_line() will process them
    # This enables single-instance behavior: when ClamUI is already running,
    # arguments from file manager context menu are forwarded to the running
    # instance via D-Bus, allowing it to start a new scan.
    return _run_gui_application(app, sys.argv)


if __name__ == "__main__":
    sys.exit(main())
