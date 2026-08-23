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
AppImage and pip installs cannot.  This command lets a user wire it up once
with ``sudo`` regardless of how ClamUI was installed (issue #143).

Inside a Flatpak sandbox the command cannot write to host paths at all; a
Flatpak build must instead rely on a separate ``clamui-privileged-helper``
package installed on the host (see :func:`run`).

Source resolution: the polkit policy is shipped as an importable-package
resource (``src.cli.resources``) and read via :mod:`importlib.resources`, so the
installer works from an installed wheel as well as a source checkout.  The
helper Python modules (:mod:`apply_preferences` and :mod:`privileged_paths`) are
resolved relative to this installed package, which already works in both.

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
import stat
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

from ..core.flatpak import is_flatpak
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


def _source_paths() -> tuple[Path, Path, Traversable]:
    """Resolve the source files to install (helper, its dependency, policy).

    The helper Python modules (``apply_preferences`` and ``privileged_paths``)
    are resolved relative to this installed package -- they always live on the
    filesystem, so plain :class:`~pathlib.Path` objects suffice.  The polkit
    policy, by contrast, is shipped as an :mod:`importlib.resources` resource
    inside ``src.cli.resources`` and is returned as a
    :class:`~importlib.resources.abc.Traversable`: a path-like handle that works
    for on-disk packages *and* zipped wheels, without assuming the policy exists
    at a real filesystem location.

    Returns:
        (apply_preferences.py, privileged_paths.py, polkit .policy) where the
        first two are filesystem ``Path`` objects and the third is a
        ``Traversable`` resource.
    """
    cli_dir = Path(__file__).resolve().parent  # .../src/cli
    apply_src = cli_dir / "apply_preferences.py"
    priv_src = cli_dir.parent / "core" / "privileged_paths.py"
    policy_src = files(f"{__name__.rsplit('.', 1)[0]}.resources") / POLICY_NAME
    return apply_src, priv_src, policy_src


def _create_install_directories(root: Path, dest_dirs: tuple[Path, ...]) -> None:
    """Create missing destination directories with deterministic mode 0o755."""
    try:
        root.mkdir(mode=0o755, parents=True)
    except FileExistsError:
        pass
    else:
        os.chmod(root, 0o755)
    for dest_dir in dest_dirs:
        current = root
        for component in dest_dir.relative_to(root).parts:
            current /= component
            try:
                current.mkdir(mode=0o755)
            except FileExistsError:
                continue
            os.chmod(current, 0o755)


def _atomic_install_file(destination: Path, content: bytes, mode: int) -> None:
    """Atomically install ``content`` as a regular file at ``destination``.

    The bytes are written to a fresh temp regular file created in
    ``destination``'s own directory, then flushed/fsynced, assigned ``mode``
    (and root ownership when the installer is running as root), and swapped
    into place with :func:`os.replace`.  Because ``os.replace`` operates on the
    directory entry rather than following a final-component symlink, a
    pre-existing symlink at ``destination`` is *replaced* by the new regular
    file -- never written through -- so an attacker cannot redirect the
    root-owned write into the symlink's target (VULN-001 class, issue #143).
    """
    # The caller prepares and validates the destination directory chain before
    # any file installation begins.
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(destination.parent),
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    tmp_file = None
    try:
        tmp_file = os.fdopen(tmp_fd, "wb", closefd=True)
        with tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.chmod(tmp_name, mode)
        if os.geteuid() == 0:
            os.chown(tmp_name, 0, 0)
        os.replace(tmp_name, str(destination))
    except BaseException:
        if tmp_file is None:
            os.close(tmp_fd)
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _validate_system_dir_chain(dest_dirs: tuple[Path, ...]) -> str | None:
    """Reject unsafe destination directory chains before a real-system write.

    Every existing ancestor of each directory in ``dest_dirs`` (up to and
    including ``/``) must be a real directory -- never a symlink -- owned by
    root (uid 0) and not group- or world-writable.  Paths that do not yet
    exist are skipped; they will be created fresh.  Returns a translatable
    error message naming the first unsafe directory, or ``None`` when the
    whole chain is safe.
    """
    for dest_dir in dest_dirs:
        for path in (dest_dir, *dest_dir.parents):
            try:
                st = os.stat(path, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError:
                return _("Refusing to install into an unsafe directory: {path}").format(path=path)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or (st.st_mode & 0o022):
                return _("Refusing to install into an unsafe directory: {path}").format(path=path)
    return None


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
    install_dirs = (lib_dir, bin_path.parent, policy_dst.parent)

    # A real system install (prefix == "/") writes root-owned artifacts under
    # /usr. Reject unsafe existing ancestors before creating anything, then
    # revalidate the complete chain after creating missing directories with
    # deterministic permissions. Prefixed/staging installs use their private
    # prefix as the trust boundary rather than root (issue #143).
    validate_system_dirs = prefix == "/" and not is_flatpak()
    if validate_system_dirs:
        chain_error = _validate_system_dir_chain(install_dirs)
        if chain_error is not None:
            return (False, chain_error)

    try:
        _create_install_directories(root, install_dirs)
        if validate_system_dirs:
            chain_error = _validate_system_dir_chain(install_dirs)
            if chain_error is not None:
                return (False, chain_error)

        priv_dst = lib_dir / "clamui_privileged_paths.py"
        apply_dst = lib_dir / "clamui_apply_preferences.py"
        wrapper_content = _WRAPPER_TEMPLATE.format(lib_dir=RUNTIME_LIB_DIR)

        _atomic_install_file(priv_dst, priv_src.read_bytes(), 0o644)
        _atomic_install_file(apply_dst, apply_content.encode("utf-8"), 0o644)
        _atomic_install_file(bin_path, wrapper_content.encode("utf-8"), 0o755)
        _atomic_install_file(policy_dst, policy_src.read_bytes(), 0o644)
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

    # A Flatpak sandbox cannot reach host paths; a real system install there is
    # impossible regardless of privileges.  Delegate it to a separate,
    # host-installed ``clamui-privileged-helper`` package (both root and non-root).
    if prefix == "/" and is_flatpak():
        print(
            _(
                "ClamUI is running inside a Flatpak sandbox, which cannot install "
                "files on the host. Install the matching clamui-privileged-helper "
                "package on the host system instead."
            ),
            file=sys.stderr,
        )
        return 1

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
            "Needed for AppImage and pip installs; the Debian package installs "
            "these automatically. Under Flatpak, the matching "
            "clamui-privileged-helper package must be installed on the host "
            "instead."
        ),
    )
    # Advanced/testing: install under an alternate root instead of "/".
    parser.add_argument("--prefix", default="/", help=argparse.SUPPRESS)
    parser.set_defaults(func=run)
