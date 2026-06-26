# ClamUI Privileged Helper Installer
"""
``clamui install-privileged-helper`` -- install the privileged configuration
helper and its polkit policy on the host.

ClamUI writes system ClamAV configuration (``/etc/freshclam.conf``,
``/etc/clamav/clamd.conf``) via a ``pkexec``-elevated helper.  For pkexec to
authorize the action the helper must live at exactly
``/usr/bin/clamui-apply-preferences`` (the path named in the polkit policy) and
the polkit policy must be installed under ``/usr/share/polkit-1/actions``.  Only
a root-level install can place files there, which the Debian package does -- but
AppImage, Flatpak and pip installs cannot.  This command lets a user wire it up
once with ``sudo`` regardless of how ClamUI was installed (issue #143).

Security: the installed helper is **self-contained and root-owned**.  We copy
``apply_preferences`` and its only dependency (``privileged_paths`` -- both pure
standard-library) into a root-owned ``/usr/lib/clamui`` directory and generate a
wrapper that runs under the *system* ``python3``.  pkexec therefore never
executes code from a user-writable virtualenv (which would reintroduce the
VULN-001 class of privilege escalation).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from ..core.i18n import _

# Canonical runtime locations.  These are fixed because the polkit policy's
# ``exec.path`` annotation names ``/usr/bin/clamui-apply-preferences`` and the
# generated wrapper hard-codes the library directory it loads from.
RUNTIME_BIN = "/usr/bin/clamui-apply-preferences"
RUNTIME_LIB_DIR = "/usr/lib/clamui"
POLKIT_ACTIONS_DIR = "/usr/share/polkit-1/actions"
POLICY_NAME = "io.github.linx_systems.ClamUI.policy"

# Original relative import inside apply_preferences.py and its flat-namespace
# replacement for the copied, self-contained helper.
_ORIGINAL_IMPORT = "from ..core.privileged_paths import"
_REWRITTEN_IMPORT = "from clamui_privileged_paths import"

_WRAPPER_TEMPLATE = """\
#!/usr/bin/python3
# ClamUI privileged preferences helper.
# Installed by `clamui install-privileged-helper`. Invoked as root via pkexec;
# loads the self-contained, root-owned helper modules under {lib_dir}.
import sys

sys.path.insert(0, "{lib_dir}")
from clamui_apply_preferences import main

sys.exit(main())
"""


def _source_paths() -> tuple[Path, Path, Path]:
    """Resolve the source files to install (helper, its dependency, policy).

    Returns:
        (apply_preferences.py, privileged_paths.py, polkit .policy) paths.
    """
    cli_dir = Path(__file__).resolve().parent  # .../src/cli
    apply_src = cli_dir / "apply_preferences.py"
    priv_src = cli_dir.parent / "core" / "privileged_paths.py"
    policy_src = cli_dir.parents[1] / "data" / POLICY_NAME  # repo-root/data/...
    return apply_src, priv_src, policy_src


def install_privileged_helper(prefix: str = "/") -> tuple[bool, str]:
    """Install the privileged helper, its library, and the polkit policy.

    Args:
        prefix: Install root.  Defaults to ``/`` (a real system install); tests
            pass a temporary directory.  The generated wrapper always references
            the canonical :data:`RUNTIME_LIB_DIR`, since at runtime the files
            live at their real locations.

    Returns:
        ``(success, message)``.
    """
    apply_src, priv_src, policy_src = _source_paths()
    for src in (apply_src, priv_src, policy_src):
        if not src.is_file():
            return (False, _("Required source file not found: {path}").format(path=src))

    # Rewrite apply_preferences' single relative import so the copied module can
    # be imported from a flat, root-owned directory under the system python.
    apply_content = apply_src.read_text(encoding="utf-8").replace(
        _ORIGINAL_IMPORT, _REWRITTEN_IMPORT
    )
    if "from ..core" in apply_content or "\nfrom ." in apply_content:
        return (
            False,
            _("Unexpected relative import remains in the helper source; aborting."),
        )

    root = Path(prefix)
    lib_dir = root / RUNTIME_LIB_DIR.lstrip("/")
    bin_path = root / RUNTIME_BIN.lstrip("/")
    policy_dst = root / POLKIT_ACTIONS_DIR.lstrip("/") / POLICY_NAME

    try:
        lib_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(lib_dir, 0o755)

        priv_dst = lib_dir / "clamui_privileged_paths.py"
        priv_dst.write_text(priv_src.read_text(encoding="utf-8"), encoding="utf-8")
        os.chmod(priv_dst, 0o644)

        apply_dst = lib_dir / "clamui_apply_preferences.py"
        apply_dst.write_text(apply_content, encoding="utf-8")
        os.chmod(apply_dst, 0o644)

        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(_WRAPPER_TEMPLATE.format(lib_dir=RUNTIME_LIB_DIR), encoding="utf-8")
        os.chmod(bin_path, 0o755)

        policy_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(policy_src, policy_dst)
        os.chmod(policy_dst, 0o644)
    except OSError as e:
        return (False, _("Failed to install privileged helper: {error}").format(error=e))

    return (
        True,
        _(
            "Installed privileged helper at {bin} and polkit policy at {policy}. "
            "Saving system ClamAV configuration from ClamUI should now work."
        ).format(bin=bin_path, policy=policy_dst),
    )


def run(args: argparse.Namespace) -> int:
    """Entry point for the ``install-privileged-helper`` subcommand."""
    prefix = getattr(args, "prefix", "/")

    # A real system install needs root; a prefixed install (tests/staging) does not.
    if prefix == "/" and os.geteuid() != 0:
        print(
            _(
                "This command installs files under /usr and /usr/share and must be "
                "run as root. Try: sudo clamui install-privileged-helper"
            ),
            file=sys.stderr,
        )
        return 1

    success, message = install_privileged_helper(prefix)
    if success:
        print(message)
        return 0

    print(_("Error: {message}").format(message=message), file=sys.stderr)
    return 1


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the install-privileged-helper subcommand with the CLI router."""
    parser = subparsers.add_parser(
        "install-privileged-helper",
        help=_("Install the privileged config helper and polkit policy (run with sudo)"),
        description=_(
            "Install /usr/bin/clamui-apply-preferences and its polkit policy so "
            "ClamUI can save system ClamAV configuration. Run as root (sudo). "
            "Needed for AppImage, Flatpak, and pip installs; the Debian package "
            "installs these automatically."
        ),
    )
    # Advanced/testing: install under an alternate root instead of "/".
    parser.add_argument("--prefix", default="/", help=argparse.SUPPRESS)
    parser.set_defaults(func=run)
