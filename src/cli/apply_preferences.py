# ClamUI Privileged Preferences Apply Helper
"""
Helper command for applying configuration files with elevated privileges.

This CLI is intended to be invoked via ``pkexec`` by the GUI layer.  It is
deliberately small, has no GTK dependency, and treats every input as
adversarial.  See ``src/core/privileged_paths.py`` for the validators that
form the actual security boundary; this module is the wiring around them.

Protocol (version 4):

    PKEXEC_UID=<uid>  pkexec  clamui-apply-preferences  --protocol=4 \
        <staged-src-1> <dest-1>  [<staged-src-2> <dest-2> ...]

    PKEXEC_UID=<uid>  pkexec  clamui-apply-preferences  --protocol=4 \
        --read-config <allowlisted-config>

The helper:

1. Reads ``PKEXEC_UID`` from the environment; refuses if missing, ``0``,
   or non-numeric (exit 3).  This pins source-file authentication to the
   user who actually authorised the elevation, not to the running root
   process.
2. Requires ``--protocol=4`` as the first positional argument so an
   outdated caller paired with the hardened helper fails closed (exit 4)
   instead of being interpreted as ``src dest src dest ...``.
3. For ``--read-config``, validates the requested path against the same
   configuration allowlist used for writes, opens it without following
   symlinks, and emits at most 1 MiB to stdout.
4. Resolves the per-user staging root, opens it ``O_NOFOLLOW`` /
   ``O_DIRECTORY``, and verifies it is owned by the calling UID with
   mode ``0o700`` (or stricter).
5. For each ``(src, dst)`` pair:

   - Opens ``src`` with ``O_RDONLY | O_NOFOLLOW | O_NONBLOCK`` (refuses
     symlinks atomically, refuses to block on FIFOs).
   - ``fstat``s the descriptor and confirms regular-file, owning UID,
     no group/world write, resolved path under the staging root.
   - Validates the destination against the allowlist (``.conf`` extension,
     no traversal, parent must be one of the allowed dirs after symlink
     resolution) and retains only its canonical allowed path.
   - Atomically installs via ``mkstemp`` in the destination directory,
     ``copyfileobj`` from the validated FD, ``fsync``, preserves the existing
     regular destination's owner and mode, then ``os.replace``s it. New files
     retain ``mkstemp``'s restrictive ``0o600`` mode. On any error the temp
     file is unlinked.

6. Restarts any active ClamAV systemd units affected by the writes.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from ..core.privileged_paths import (
    MAX_CONFIG_READ_BYTES,
    PROTOCOL_VERSION,
    staging_root_for_uid,
    validate_destination,
    validate_source_for_uid,
    verify_staging_root,
)

logger = logging.getLogger(__name__)


_FRESHCLAM_UNITS: tuple[str, ...] = (
    "clamav-freshclam.service",
    "freshclam.service",
)

_CLAMD_UNITS: tuple[str, ...] = (
    "clamav-daemon.service",
    "clamd.service",
    "clamd@scan.service",
    "clamav-clamonacc.service",
)


# --- Exit codes -----------------------------------------------------------
# 0  success
# 1  generic error (validation failure, IO error, restart failure)
# 2  argument parsing error (odd number of pairs, no pairs)
# 3  PKEXEC_UID missing/zero/non-numeric
# 4  protocol mismatch (caller did not pass --protocol=4 first)
EXIT_OK = 0
EXIT_GENERIC_ERROR = 1
EXIT_BAD_ARGS = 2
EXIT_BAD_PKEXEC_UID = 3
EXIT_BAD_PROTOCOL = 4


def _parse_path_pairs(args: list[str]) -> list[tuple[Path, Path]]:
    """
    Parse remaining arguments into ``(source, destination)`` path pairs.

    Args:
        args: Flat list of alternating source and destination paths
            (after the ``--protocol=4`` token has been consumed).

    Returns:
        List of ``(source, destination)`` ``Path`` tuples.

    Raises:
        ValueError: If args are empty or not provided as pairs.
    """
    if not args:
        raise ValueError("No staged configuration files were provided.")
    if len(args) % 2 != 0:
        raise ValueError("Invalid arguments: expected source/destination path pairs.")

    pairs: list[tuple[Path, Path]] = []
    for idx in range(0, len(args), 2):
        pairs.append((Path(args[idx]), Path(args[idx + 1])))
    return pairs


def _parse_pkexec_uid() -> int | None:
    """Return ``PKEXEC_UID`` as an int, or ``None`` if missing/zero/invalid."""
    raw = os.environ.get("PKEXEC_UID")
    if raw is None:
        return None
    try:
        uid = int(raw)
    except ValueError:
        return None
    if uid <= 0:
        return None
    return uid


def _resolve_staging_root(uid: int) -> Path:
    """Indirection seam so tests can redirect the staging root under tmp_path."""
    return staging_root_for_uid(uid)


def _existing_destination_metadata(destination: Path) -> tuple[int, int, int] | None:
    """Return a regular destination's ``(uid, gid, mode)``, without following links."""
    try:
        fd = os.open(str(destination), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None

    try:
        destination_stat = os.fstat(fd)
    finally:
        os.close(fd)

    if not stat.S_ISREG(destination_stat.st_mode):
        raise ValueError(f"Configuration destination is not a regular file: {destination}")

    return (
        destination_stat.st_uid,
        destination_stat.st_gid,
        stat.S_IMODE(destination_stat.st_mode),
    )


def _atomic_install(source_fd: int, destination: Path) -> None:
    """
    Atomically install ``source_fd``'s content into ``destination``.

    Existing regular destinations retain their ownership and permissions;
    newly created configurations use ``mkstemp``'s restrictive ``0o600`` mode.
    The temp file is created in the destination directory so ``os.replace`` is
    atomic for this one file. This function takes ownership of ``source_fd`` and
    closes it even if destination preparation fails.
    """
    with os.fdopen(source_fd, "rb", closefd=True) as source_file:
        destination.parent.mkdir(parents=True, exist_ok=True)
        existing_metadata = _existing_destination_metadata(destination)
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        tmp_file = None
        try:
            tmp_file = os.fdopen(tmp_fd, "wb", closefd=True)
            with tmp_file:
                shutil.copyfileobj(source_file, tmp_file)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
                if existing_metadata is not None:
                    uid, gid, mode = existing_metadata
                    os.fchown(tmp_file.fileno(), uid, gid)
                    os.fchmod(tmp_file.fileno(), mode)
                    os.fsync(tmp_file.fileno())
            os.replace(tmp_name, destination)
        except BaseException:
            if tmp_file is None:
                os.close(tmp_fd)
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise


def _open_and_validate_source(
    source: Path,
    expected_uid: int,
    staging_root: Path,
) -> int:
    """Open and validate a staged source, returning the retained descriptor."""
    source_fd = os.open(
        str(source),
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
    )
    try:
        validate_source_for_uid(source_fd, source, expected_uid, staging_root)
    except BaseException:
        os.close(source_fd)
        raise
    return source_fd


def _read_allowlisted_config(requested_path: Path) -> int:
    """Write one bounded, allowlisted configuration file to stdout."""
    try:
        config_path = validate_destination(requested_path)
        fd = os.open(str(config_path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb", closefd=True) as config_file:
            file_stat = os.fstat(config_file.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError(f"Configuration is not a regular file: {config_path}")
            if file_stat.st_size > MAX_CONFIG_READ_BYTES:
                raise ValueError(
                    f"Configuration exceeds {MAX_CONFIG_READ_BYTES} byte read limit: {config_path}"
                )
            content = config_file.read(MAX_CONFIG_READ_BYTES + 1)
            if len(content) > MAX_CONFIG_READ_BYTES:
                raise ValueError(
                    f"Configuration exceeds {MAX_CONFIG_READ_BYTES} byte read limit: {config_path}"
                )
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    sys.stdout.buffer.write(content)
    return EXIT_OK


def _restart_units_for_destinations(destinations: list[Path]) -> None:
    """
    Restart active ClamAV services affected by the written config files.

    Only active services are restarted so distro-specific or disabled units
    are skipped without failing the save operation.

    Args:
        destinations: Final config destinations that were updated.
    """
    if shutil.which("systemctl") is None:
        return

    units_to_restart: list[str] = []
    for destination in destinations:
        if destination.name == "freshclam.conf":
            units_to_restart.extend(_FRESHCLAM_UNITS)
        elif destination.name == "clamd.conf" or destination.parent == Path("/etc/clamd.d"):
            units_to_restart.extend(_CLAMD_UNITS)

    seen_units: set[str] = set()
    for unit in units_to_restart:
        if unit in seen_units:
            continue
        seen_units.add(unit)

        active_result = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            capture_output=True,
            text=True,
        )
        if active_result.returncode != 0:
            continue

        restart_result = subprocess.run(
            ["systemctl", "restart", unit],
            capture_output=True,
            text=True,
        )
        if restart_result.returncode != 0:
            error = (
                restart_result.stderr.strip() or restart_result.stdout.strip() or "unknown error"
            )
            raise RuntimeError(f"Failed to restart {unit}: {error}")


def main(argv: list[str] | None = None) -> int:
    """
    Entry point for the privileged preferences apply helper.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit status code.  See module docstring for the meaning of each code.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    uid = _parse_pkexec_uid()
    if uid is None:
        print(
            "Error: PKEXEC_UID is missing or invalid; refusing to run.",
            file=sys.stderr,
        )
        return EXIT_BAD_PKEXEC_UID

    expected_protocol = f"--protocol={PROTOCOL_VERSION}"
    if not args or args[0] != expected_protocol:
        print(
            f"Error: missing or wrong protocol token; expected {expected_protocol} as the "
            "first argument.",
            file=sys.stderr,
        )
        return EXIT_BAD_PROTOCOL
    args = args[1:]

    if args and args[0] == "--read-config":
        if len(args) != 2:
            print("Error: expected exactly one configuration path to read.", file=sys.stderr)
            return EXIT_BAD_ARGS
        return _read_allowlisted_config(Path(args[1]))

    try:
        pairs = _parse_path_pairs(args)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_BAD_ARGS

    staging_root = _resolve_staging_root(uid)
    try:
        verify_staging_root(staging_root, uid)
    except (ValueError, OSError) as error:
        print(f"Error: invalid staging root: {error}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    # Preflight phase 1: validate and canonicalize every destination before
    # opening any source. A bad destination short-circuits with no descriptors
    # held, and every later phase uses only the canonical allowed paths.
    try:
        pairs = [(source, validate_destination(destination)) for source, destination in pairs]
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    # Preflight phase 2: open and authenticate every staged source, holding
    # the validated descriptors open.  No destination is written until *every*
    # source has cleared the uid/mode/staging-root checks, so a failure on
    # pair #2 leaves pair #1's destination untouched -- no write begins
    # before every input validates.  This is input preflight, not
    # all-or-nothing I/O: it does not roll back an install once one starts.
    validated: list[tuple[int, Path]] = []  # (source_fd, destination)
    try:
        for source, destination in pairs:
            src_fd = _open_and_validate_source(source, uid, staging_root)
            validated.append((src_fd, destination))
    except Exception as error:
        # Nothing has been installed yet; close every source preflight opened.
        for src_fd, _destination in validated:
            try:
                os.close(src_fd)
            except OSError:
                pass
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    # Install phase: copy each preflighted descriptor into its destination.
    # _atomic_install reuses the preflight-opened descriptor (no reopen, so
    # no source TOCTOU) and owns/closes it on every exit path.
    destinations: list[Path] = []
    try:
        for src_fd, destination in validated:
            _atomic_install(src_fd, destination)
            destinations.append(destination)
        _restart_units_for_destinations(destinations)
    except Exception as error:
        # _atomic_install has consumed (and closed) the descriptors it was
        # handed -- the first len(destinations) pairs plus the one that
        # failed.  Close only the descriptors for the pairs we never reached,
        # never the consumed ones, so a descriptor is never closed twice.
        for src_fd, _destination in validated[len(destinations) + 1 :]:
            try:
                os.close(src_fd)
            except OSError:
                pass
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
