# ClamUI Privileged Paths Validators
"""
Security validators for the privileged preferences-apply helper.

This module is the single source of truth for:
- The destination allowlist that pkexec-elevated writes are permitted to touch
- Source-file authentication (uid, mode, staging-root containment) used by
  the helper before copying staged content into a system path
- Staging-root verification used by both the unprivileged caller and the
  privileged helper

The module is pure-Python with no GTK or I/O side effects beyond ``os.fstat``
on file descriptors that the caller has already opened with ``O_NOFOLLOW``.
That keeps it cheap to unit-test and easy to reason about as the security
boundary of the elevated helper.
"""

from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path

# Single source of truth for the destination allowlist.  Both the helper and
# the caller import these tuples; tests should monkey-patch them with paths
# under ``tmp_path`` rather than redefining the policy.
ALLOWED_DEST_DIRS: tuple[Path, ...] = (
    Path("/etc/clamav"),
    Path("/etc/clamd.d"),
    Path("/etc/clamav-unofficial-sigs"),
)
ALLOWED_DEST_FILES: tuple[Path, ...] = (Path("/etc/freshclam.conf"),)

# Bumped to 3 so every callsite explicitly opts into canonical destination
# binding. The helper rejects any argv that does not lead with
# ``--protocol=3``; this lets a freshly-installed helper coexist with an
# out-of-date caller and fail closed.
PROTOCOL_VERSION = 3


def is_running_as_root() -> bool:
    """
    Return whether the current process has an effective UID of 0 (root).

    When ClamUI is launched as root every configuration path under ``/etc``
    is directly writable, so the pkexec elevation flow is both unnecessary and
    counter-productive (it would spawn a second authentication step for a user
    who already holds the required privileges).  Callers use this to skip
    elevation entirely and to suppress the "requires administrator privileges"
    UI affordances in the preferences window.

    Returns:
        True if the effective UID is 0, False otherwise.
    """
    return os.geteuid() == 0


def staging_root_for_uid(uid: int) -> Path:
    """
    Return the per-user staging root under the passwd-database home.

    The canonical root is ``<passwd-home>/.cache/clamui/privileged-staging``::

        pwd.getpwuid(uid).pw_dir / .cache / clamui / privileged-staging

    Native and Flatpak share this single root so the privileged helper --
    which runs on the host (via ``flatpak-spawn --host`` under Flatpak) and
    independently recomputes it here -- always reads staged files from the
    exact directory the caller wrote them to.  The path lives under the
    host-visible home filesystem that the Flatpak manifest grants with
    ``--filesystem=host``, so it is reachable from both sides of the
    sandbox/host boundary.

    The home directory is taken from the passwd database
    (``pwd.getpwuid``), **never** from ``$HOME``: inside a Flatpak sandbox
    ``$HOME`` points at ``~/.var/app/<id>`` rather than the real home, so a
    ``$HOME``-derived root would not match what the host-visible helper
    computes.  Native and Flatpak therefore agree because both consult the
    same passwd entry for ``uid``.

    The directory is *not* created here -- the caller (``_make_staging_dir``)
    is responsible for creating it with mode 0o700 before invoking the
    helper.  This function is intentionally pure (only a ``getpwuid``
    lookup; no file I/O or other side effects) so it can be safely called
    from the privileged helper before any other validation has run.

    Args:
        uid: The user ID whose staging root should be returned.

    Returns:
        Absolute path to the per-user staging root.
    """
    return Path(pwd.getpwuid(uid).pw_dir) / ".cache" / "clamui" / "privileged-staging"


def validate_destination(destination: Path) -> Path:
    """
    Validate ``destination`` against the ClamAV configuration allowlist.

    A destination is accepted iff at least one of the following holds:

    1. Its canonical path exactly equals one of :data:`ALLOWED_DEST_FILES`.
    2. Its canonical path lives directly under one of
       :data:`ALLOWED_DEST_DIRS` (no nested subdirectories) and ends in
       ``.conf`` with a non-empty stem.

    The parent directory is resolved via ``Path.resolve(strict=False)`` so
    that symlinked parents cannot be used to escape the allowlist; the
    destination *file* itself is not resolved because it may not exist yet.
    The canonical ``resolved_parent / destination.name`` is returned so
    callers use the exact allowlisted destination after validation.

    Args:
        destination: Proposed destination file path.

    Returns:
        Canonical allowlisted destination path.

    Raises:
        ValueError: If the destination is outside the allowlist, has the
            wrong extension, or has an empty stem.
    """
    # Reject components like ``..`` early.  Path.resolve() collapses these
    # but we also reject any symlinked ancestor by resolving the parent and
    # comparing it to ALLOWED_DEST_DIRS.
    try:
        resolved_parent = destination.parent.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Cannot resolve destination parent: {destination}") from exc

    candidate = resolved_parent / destination.name

    if candidate in ALLOWED_DEST_FILES:
        return candidate

    if candidate.suffix != ".conf":
        raise ValueError(f"Destination must have a .conf extension: {destination}")

    if candidate.stem == "":
        raise ValueError(f"Destination must have a non-empty file name: {destination}")

    if resolved_parent not in ALLOWED_DEST_DIRS:
        raise ValueError(f"Destination is not in allowed config directories: {destination}")
    return candidate


def _fstat_strict(fd: int) -> os.stat_result:
    """Return ``os.fstat(fd)``; convenience seam for tests."""
    return os.fstat(fd)


def validate_source_for_uid(
    source_fd: int,
    source_path: Path,
    expected_uid: int,
    staging_root: Path,
) -> None:
    """
    Authenticate a staged source file against the calling user.

    The caller MUST have already opened ``source_fd`` with
    ``os.O_RDONLY | os.O_NOFOLLOW`` (and typically ``O_NONBLOCK`` for
    safety against FIFOs).  We then ``fstat`` the descriptor (NOT the
    path -- that would re-introduce a TOCTOU window) and verify:

    - The file is a regular file (``S_ISREG``).
    - The owning UID matches ``expected_uid``.
    - The file is not group-writable or world-writable.
    - The file's resolved path lives strictly under ``staging_root``
      (so a malicious bind-mount cannot redirect the helper to read
      ``/etc/shadow``).

    Args:
        source_fd: File descriptor opened with ``O_NOFOLLOW`` by the caller.
        source_path: The path the caller used to open ``source_fd``.
        expected_uid: The UID that must own the file (typically the
            caller's UID extracted from ``PKEXEC_UID``).
        staging_root: The per-invocation staging directory; ``source_path``
            must resolve under this directory.

    Raises:
        ValueError: On any validation failure.
    """
    st = _fstat_strict(source_fd)

    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"Staged source is not a regular file: {source_path}")

    if st.st_uid != expected_uid:
        raise ValueError(
            f"Staged source uid={st.st_uid} does not match expected uid={expected_uid}: "
            f"{source_path}"
        )

    if st.st_mode & 0o022:
        raise ValueError(f"Staged source has unsafe mode {oct(st.st_mode & 0o777)}: {source_path}")

    try:
        resolved_source = source_path.resolve(strict=True)
        resolved_staging = staging_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Cannot resolve staged source path: {source_path}") from exc

    try:
        resolved_source.relative_to(resolved_staging)
    except ValueError as exc:
        raise ValueError(
            f"Staged source {resolved_source} is outside staging root {resolved_staging}"
        ) from exc


def verify_staging_root(staging_root: Path, expected_uid: int) -> None:
    """
    Verify the per-user staging directory is safe to read from.

    Opens the directory with ``O_NOFOLLOW`` (so a symlinked staging root
    cannot escape) and ``O_DIRECTORY`` (so a regular file masquerading as
    the staging root is rejected by the kernel).  Then ``fstat`` confirms:

    - The kernel returned a directory (``S_ISDIR``).
    - The directory is owned by ``expected_uid``.
    - No group or world bits are set (mode 0o700 or stricter).

    Args:
        staging_root: Path to the per-user staging directory.
        expected_uid: Expected owning UID.

    Raises:
        ValueError: On any mismatch.
        OSError: From the underlying ``os.open`` (e.g. ``ELOOP`` if the
            path is a symlink, ``ENOTDIR`` if it is a regular file).
    """
    fd = os.open(str(staging_root), os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        st = _fstat_strict(fd)
    finally:
        os.close(fd)

    if not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"Staging root is not a directory: {staging_root}")

    if st.st_uid != expected_uid:
        raise ValueError(
            f"Staging root uid={st.st_uid} does not match expected uid={expected_uid}: "
            f"{staging_root}"
        )

    if st.st_mode & 0o077:
        raise ValueError(f"Staging root has unsafe mode {oct(st.st_mode & 0o777)}: {staging_root}")
