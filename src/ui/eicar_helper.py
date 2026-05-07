# EICAR Test File Helper
"""GTK-free helpers for managing the EICAR test file lifecycle.

The EICAR test button writes the standard antivirus test pattern to a
temporary file, scans it, and is supposed to clean it up on completion.
On force-quit / crash / cancel paths the cleanup may be skipped, leaving
the EICAR file in ``~/.cache/clamui/`` or ``/tmp/`` — the next normal
scan of that directory then flags it as a real threat.

This module factors the create / cleanup logic out of the GTK-heavy
ScanView so it can be unit-tested without a display, and adds an
``atexit`` safety net so a stale file never survives a process exit
(see UI-010).
"""

from __future__ import annotations

import atexit
import logging
import tempfile
from contextlib import suppress
from pathlib import Path

logger = logging.getLogger(__name__)

# EICAR test string - industry-standard antivirus test pattern.
# This is NOT malware — it's a safe, non-functional string recognised by
# every AV engine for self-test purposes.
EICAR_TEST_STRING = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def create_eicar_temp(parent_dir: str | None = None) -> str:
    """Write the EICAR test string to a temp file and return its path.

    Args:
        parent_dir: Directory in which to create the temp file. ``None``
            uses the system default tempfile location.

    Returns:
        Absolute path to the created temp file. Caller is responsible for
        cleanup (via :func:`cleanup_eicar_path` and/or
        :func:`register_eicar_atexit_cleanup`).
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        prefix="eicar_test_",
        delete=False,
        dir=parent_dir,
    ) as f:
        f.write(EICAR_TEST_STRING)
        return f.name


def cleanup_eicar_path(path: str | None) -> None:
    """Best-effort removal of an EICAR temp file.

    Safe to call repeatedly, with empty strings, ``None``, or paths that
    no longer exist. Errors are logged at debug level and swallowed —
    cleanup must never raise.
    """
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as e:
        # Permissions, busy file, etc. — never propagate from cleanup.
        logger.debug("Failed to clean up EICAR file %r: %s", path, e)


def register_eicar_atexit_cleanup(path: str | None):
    """Register an ``atexit`` handler to remove the EICAR file on exit.

    Returns a zero-arg callable that unregisters the handler — call it
    after a successful in-process cleanup to avoid a double-unlink on
    interpreter shutdown. Returns a no-op callable when ``path`` is
    falsy.
    """
    if not path:
        return lambda: None

    atexit.register(cleanup_eicar_path, path)

    def _unregister() -> None:
        with suppress(Exception):
            atexit.unregister(cleanup_eicar_path)

    return _unregister
