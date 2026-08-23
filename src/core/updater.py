# ClamUI Updater Module
"""
Updater module for ClamUI providing freshclam subprocess execution and async database updates.
"""

import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from gi.repository import GLib

from .flatpak import (
    get_clamav_database_dir,
    is_flatpak,
    which_host_command,
)
from .i18n import _
from .log_manager import LogEntry, LogManager
from .utils import (
    check_freshclam_installed,
    get_clean_env,
    get_freshclam_path,
    systemd_unit_exists,
    wrap_host_command,
)

logger = logging.getLogger(__name__)

# Timeout constants (seconds)
_TERMINATE_GRACE_TIMEOUT = 5  # Time to wait after SIGTERM before SIGKILL
_KILL_WAIT_TIMEOUT = 2  # Time to wait after SIGKILL
_UPDATE_COMMUNICATE_TIMEOUT = 600  # 10 minutes for freshclam (network operations)
_DATABASE_FILE_RE = re.compile(r"\b([A-Za-z0-9_.-]+\.(?:cvd|cld|cud))\b", re.IGNORECASE)
_COOLDOWN_UNTIL_RE = re.compile(r"cool[- ]down until after:\s*(.+)$", re.IGNORECASE)
_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "rate-limit",
    "rate limited",
    "429",
    "too many requests",
    "temporarily blocked",
    "blocked temporarily",
)


def _build_force_update_script(database_dir: str = "/var/lib/clamav") -> str:
    """Build the shell transaction used by a forced freshclam update.

    Freshclam downloads into a hidden staging directory first, so the live
    database remains readable while mirrors are contacted.  Only a successful
    download containing at least one database file is promoted.  The script
    keeps freshclam as positional ``$1`` data rather than interpolating its
    path into shell source.
    """
    quoted_database_dir = shlex.quote(database_dir)
    return (
        "d="
        + quoted_database_dir
        + r"""

staging=
staged_manifest=
original_manifest=
backup=
promoting=0
freshclam_pid=

rollback() {
    [ "$promoting" -eq 1 ] || return 0
    [ -f "$staged_manifest" ] || return 1

    rollback_status=0
    # Remove every staged name currently in the live directory, then restore
    # the complete original set from the transaction backup.
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        rm -f -- "$d/$name" || rollback_status=1
    done < "$staged_manifest"
    if [ -f "$original_manifest" ]; then
        while IFS= read -r name; do
            [ -n "$name" ] || continue
            if ! mv -f -- "$backup/$name" "$d/$name"; then
                if ! cp -p -- "$backup/$name" "$d/$name"; then
                    rollback_status=1
                fi
            fi
        done < "$original_manifest"
    fi
    return "$rollback_status"
}
interrupt() {
    rc=$1
    if [ -n "$freshclam_pid" ]; then
        kill "$freshclam_pid" 2>/dev/null || :
    fi
    exit "$rc"
}


cleanup() {
    rc=$?
    # Do not let a second signal interrupt rollback or staging cleanup.
    trap '' HUP INT QUIT TERM
    trap - 0
    if [ "$promoting" -eq 1 ]; then
        rollback || rc=1
    fi
    if [ -n "$staging" ] && [ -d "$staging" ]; then
        rm -rf -- "$staging" || :
    fi
    exit "$rc"
}
trap cleanup 0
trap 'interrupt 129' HUP
trap 'interrupt 130' INT
trap 'interrupt 131' QUIT
trap 'interrupt 143' TERM

if [ ! -d "$d" ]; then
    exit 1
fi

# Match the live directory's access and ownership so root and non-root
# freshclam installations use the same permissions without a distro owner
# assumption.
dir_mode=$(stat -c '%a' "$d") || exit 1
dir_owner=$(stat -c '%u' "$d") || exit 1
dir_group=$(stat -c '%g' "$d") || exit 1
staging=$(mktemp -d "$d/.clamui-force-update.XXXXXX") || exit 1
chmod "$dir_mode" "$staging" || exit 1
chown "$dir_owner:$dir_group" "$staging" || exit 1

# Keep every live database name in place while freshclam is blocked or
# downloading.  Freshclam may notify clamd while staging according to its
# configuration; the explicit reload after promotion below ensures daemon
# scans observe the promoted generation.
# Preserve the caller's stdin explicitly: POSIX shells otherwise connect
# asynchronous commands to /dev/null.
exec 3<&0
"$1" --datadir="$staging" --verbose <&3 &
freshclam_pid=$!
exec 3<&-
wait "$freshclam_pid"
freshclam_status=$?
freshclam_pid=
[ "$freshclam_status" -eq 0 ] || exit "$freshclam_status"

# A successful freshclam exit without a database file is not a usable force
# update and must not alter the live definitions.
staged_count=0
for f in "$staging"/*.cvd "$staging"/*.cld "$staging"/*.cud; do
    if [ -f "$f" ]; then
        staged_count=$((staged_count + 1))
    fi
done
[ "$staged_count" -gt 0 ] || exit 1

# Build transaction metadata only after downloads are ready, so freshclam
# sees an otherwise empty staging datadir.
backup="$staging/.original"
original_manifest="$staging/.originals"
staged_manifest="$staging/.staged"
mkdir -- "$backup" || exit 1

# Back up the complete live database set.  Force semantics remove old-only
# names after successful promotion; rollback restores every original name.
for f in "$d"/*.cvd "$d"/*.cld "$d"/*.cud; do
    [ -f "$f" ] || continue
    name=${f##*/}
    cp -p -- "$f" "$backup/$name" || exit 1
    printf '%s\n' "$name" >> "$original_manifest" || exit 1
done

# Record every staged name so rollback can remove newly introduced files.
for f in "$staging"/*.cvd "$staging"/*.cld "$staging"/*.cud; do
    [ -f "$f" ] || continue
    name=${f##*/}
    printf '%s\n' "$name" >> "$staged_manifest" || exit 1
done

# rename(2) replaces each target atomically.  Existing live names therefore
# never have a deletion gap; old-only names are removed only after at least
# one staged name is live.  Rollback restores originals if this is
# interrupted or a later move fails.
promoting=1
for f in "$staging"/*.cvd "$staging"/*.cld "$staging"/*.cud; do
    [ -f "$f" ] || continue
    name=${f##*/}
    mv -f -- "$f" "$d/$name" || exit 1
done
for f in "$d"/*.cvd "$d"/*.cld "$d"/*.cud; do
    [ -f "$f" ] || continue
    name=${f##*/}
    is_staged=0
    while IFS= read -r staged_name; do
        if [ "$staged_name" = "$name" ]; then
            is_staged=1
            break
        fi
    done < "$staged_manifest"
    if [ "$is_staged" -eq 0 ]; then
        rm -f -- "$f" || exit 1
    fi
done
promoting=0
# Notify a running clamd only after the complete promoted generation is live.
# The daemon is optional, and an unavailable daemon must not undo a successful
# database promotion.  Track the best-effort child so cancellation still
# reaches it if a daemon command hangs.
if command -v clamdscan >/dev/null 2>&1; then
    clamdscan --reload </dev/null >/dev/null 2>&1 &
    freshclam_pid=$!
    wait "$freshclam_pid" || :
    freshclam_pid=
fi
exit 0
"""
    )


def get_pkexec_path() -> str | None:
    """
    Get the full path to the pkexec executable for privilege elevation.

    Returns:
        The full path to pkexec if found, None otherwise
    """

    return which_host_command("pkexec")


class UpdateStatus(Enum):
    """Status of a database update operation."""

    SUCCESS = "success"  # Database updated successfully (exit code 0)
    UP_TO_DATE = "up_to_date"  # Database already current (exit code 0, no updates)
    ERROR = "error"  # Error occurred (exit code 1 or exception)
    CANCELLED = "cancelled"  # Update was cancelled


class UpdateMethod(Enum):
    """How the update was triggered."""

    SERVICE_SIGNAL = "service_signal"  # Via SIGUSR1 to freshclam service
    MANUAL = "manual"  # Via pkexec freshclam subprocess


class FreshclamServiceStatus(Enum):
    """Status of the freshclam systemd service."""

    RUNNING = "running"  # Service active, can trigger via signal
    STOPPED = "stopped"  # Service exists but not running
    NOT_FOUND = "not_found"  # No systemd service detected
    UNKNOWN = "unknown"  # Error checking status


@dataclass
class UpdateResult:
    """Result of a database update operation."""

    status: UpdateStatus
    stdout: str
    stderr: str
    exit_code: int
    databases_updated: int
    error_message: str | None
    update_method: UpdateMethod = UpdateMethod.MANUAL
    updated_databases: list[str] = field(default_factory=list)
    up_to_date_databases: list[str] = field(default_factory=list)
    rate_limited_databases: dict[str, str | None] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Check if update completed successfully."""
        return self.status in (UpdateStatus.SUCCESS, UpdateStatus.UP_TO_DATE)

    @property
    def has_error(self) -> bool:
        """Check if update encountered an error."""
        return self.status == UpdateStatus.ERROR


@dataclass
class _ParsedFreshclamOutput:
    """Structured freshclam output parsed per database."""

    updated_databases: list[str] = field(default_factory=list)
    up_to_date_databases: list[str] = field(default_factory=list)
    rate_limited_databases: dict[str, str | None] = field(default_factory=dict)


class FreshclamUpdater:
    """
    ClamAV database updater with async execution support.

    Provides methods for running freshclam in a background thread
    while safely updating the UI via GLib.idle_add.
    """

    def __init__(self, log_manager: LogManager | None = None):
        """
        Initialize the updater.

        Args:
            log_manager: Optional LogManager instance for saving update logs.
                         If not provided, a default instance is created.
        """
        self._current_process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._update_cancelled = False
        self._force_update_backup_dir: Path | None = None
        self._log_manager = log_manager if log_manager else LogManager()

    def check_available(self) -> tuple[bool, str | None]:
        """
        Check if freshclam is available for database updates.

        Returns:
            Tuple of (is_available, version_or_error)
        """
        return check_freshclam_installed()

    def check_freshclam_service(self) -> tuple[FreshclamServiceStatus, str | None]:
        """
        Check if freshclam is running as a systemd service.

        Checks for both 'clamav-freshclam.service' (Debian/Ubuntu/Fedora/Arch)
        and 'freshclam.service' (openSUSE).

        Returns:
            Tuple of (status, pid_or_error_message)
            - RUNNING: (RUNNING, pid_string)
            - STOPPED: (STOPPED, None)
            - NOT_FOUND: (NOT_FOUND, None)
            - UNKNOWN: (UNKNOWN, error_message)
        """
        # Service names to check (in order of preference)
        service_names = ["clamav-freshclam.service", "freshclam.service"]

        for service_name in service_names:
            try:
                # Check if service is active
                result = subprocess.run(
                    wrap_host_command(["systemctl", "is-active", service_name]),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=get_clean_env(),
                )

                state = result.stdout.strip().lower()
                if result.returncode == 0 and state == "active":
                    # Service is active, get the PID
                    try:
                        pid_result = subprocess.run(
                            wrap_host_command(["pidof", "freshclam"]),
                            capture_output=True,
                            text=True,
                            timeout=5,
                            env=get_clean_env(),
                        )
                        if pid_result.returncode == 0:
                            pid = pid_result.stdout.strip().split()[0]  # Take first PID
                            logger.debug(
                                "Found running freshclam service: %s (PID %s)",
                                service_name,
                                pid,
                            )
                            return FreshclamServiceStatus.RUNNING, pid
                    except (subprocess.TimeoutExpired, OSError) as e:
                        logger.warning("Failed to get freshclam PID: %s", e)
                    # Service is active even if the PID lookup failed
                    return FreshclamServiceStatus.RUNNING, None

                elif state in ("inactive", "failed", "activating", "deactivating"):
                    # systemd prints "inactive" even for units it has never
                    # heard of, so confirm the unit actually exists before
                    # concluding installed-but-stopped — otherwise a distro
                    # using the other unit name (openSUSE's freshclam.service)
                    # would short-circuit here and never be probed.
                    if systemd_unit_exists(service_name):
                        logger.debug("Service %s exists but is not running", service_name)
                        return FreshclamServiceStatus.STOPPED, None

            except subprocess.TimeoutExpired:
                logger.warning("Timeout checking service %s", service_name)
                continue
            except OSError as e:
                logger.warning("Error checking service %s: %s", service_name, e)
                continue

        # No service found
        return FreshclamServiceStatus.NOT_FOUND, None

    def trigger_service_update(self) -> tuple[bool, str]:
        """
        Trigger a database update via the freshclam service using SIGUSR1.

        This is a non-blocking operation - the service handles the update
        in the background. Check service logs (journalctl -u clamav-freshclam)
        for results.

        Returns:
            Tuple of (success, message)
        """
        # Check service status first
        status, pid = self.check_freshclam_service()

        if status != FreshclamServiceStatus.RUNNING:
            return False, _("Freshclam service not running (status: {status})").format(
                status=status.value
            )

        if not pid:
            # Try to get PID again
            try:
                pid_result = subprocess.run(
                    wrap_host_command(["pidof", "freshclam"]),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=get_clean_env(),
                )
                if pid_result.returncode == 0:
                    pid = pid_result.stdout.strip().split()[0]
                else:
                    return False, _("Could not determine freshclam PID")
            except (subprocess.TimeoutExpired, OSError) as e:
                return False, _("Failed to get freshclam PID: {error}").format(error=e)

        # Send SIGUSR1 to trigger update
        try:
            # Use kill command to send signal (works without root for processes owned by same user)
            result = subprocess.run(
                wrap_host_command(["kill", "-s", "SIGUSR1", pid]),
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )

            if result.returncode == 0:
                logger.info("Sent SIGUSR1 to freshclam service (PID %s)", pid)
                return True, _("Update signal sent to freshclam service (PID {pid})").format(
                    pid=pid
                )

            # Regular signal failed (likely permission denied for clamav-owned process)
            # Try with pkexec elevation
            error = result.stderr.strip() or "Unknown error"
            logger.info("Regular kill failed (%s), trying elevated signal via pkexec", error)
            pkexec = get_pkexec_path()
            if pkexec:
                try:
                    elevated_result = subprocess.run(
                        wrap_host_command([pkexec, "kill", "-s", "SIGUSR1", pid]),
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=get_clean_env(),
                    )
                    if elevated_result.returncode == 0:
                        logger.info("Sent SIGUSR1 to freshclam via pkexec (PID %s)", pid)
                        return True, _(
                            "Update signal sent to freshclam service (PID {pid})"
                        ).format(pid=pid)
                    else:
                        elevated_error = elevated_result.stderr.strip() or error
                        logger.warning("Elevated signal also failed: %s", elevated_error)
                        return False, _("Failed to send signal: {error}").format(
                            error=elevated_error
                        )
                except subprocess.TimeoutExpired:
                    return False, _("Timeout sending elevated signal to freshclam")
                except OSError as e:
                    logger.warning("pkexec signal failed: %s", e)

            # Both attempts failed (or pkexec not available)
            logger.warning("Failed to send signal to freshclam: %s", error)
            return False, _("Failed to send signal: {error}").format(error=error)

        except subprocess.TimeoutExpired:
            return False, _("Timeout sending signal to freshclam")
        except OSError as e:
            return False, _("Error sending signal: {error}").format(error=e)

    def _check_freshclam_running(self) -> tuple[bool, str | None]:
        """
        Check if a freshclam process is currently running.

        Uses pidof to detect running freshclam instances. In Flatpak this runs
        on the host via flatpak-spawn.

        Returns:
            Tuple of (is_running, pid_string_or_none)
        """
        try:
            pid_result = subprocess.run(
                wrap_host_command(["pidof", "freshclam"]),
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )
            if pid_result.returncode == 0 and pid_result.stdout.strip():
                pid = pid_result.stdout.strip().split()[0]
                return True, pid
        except Exception as e:
            logger.debug("Failed to check if freshclam is running: %s", e)
        return False, None

    def _create_result(
        self,
        status: UpdateStatus,
        *,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = -1,
        databases_updated: int = 0,
        error_message: str | None = None,
        update_method: UpdateMethod = UpdateMethod.MANUAL,
    ) -> UpdateResult:
        """Build a basic update result for non-parser-driven branches."""
        return UpdateResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            databases_updated=databases_updated,
            error_message=error_message,
            update_method=update_method,
        )

    def _finish_update(
        self,
        result: UpdateResult,
        start_time: float,
        *,
        restore_backup: bool = False,
    ) -> UpdateResult:
        """Persist the update log, optionally restore backups, and return the result."""
        if restore_backup:
            restore_success, restore_error = self._restore_databases_from_backup()
            if not restore_success:
                if restore_error:
                    note = _("previous database could not be restored: {error}").format(
                        error=restore_error
                    )
                else:
                    note = _("previous database could not be restored")
                if result.error_message:
                    result.error_message = f"{result.error_message} ({note})"
                else:
                    result.error_message = note

        duration = time.monotonic() - start_time
        self._save_update_log(result, duration)
        self._cleanup_backup()
        return result

    def _check_availability_result(self) -> UpdateResult | None:
        """Return an error result when freshclam is unavailable."""
        is_installed, version_or_error = check_freshclam_installed()
        if is_installed:
            return None

        return self._create_result(
            UpdateStatus.ERROR,
            stderr=version_or_error or "freshclam not installed",
            error_message=version_or_error,
        )

    def _try_service_update_result(
        self, *, force: bool, prefer_service: bool
    ) -> UpdateResult | None:
        """Try the service-triggered update path and return a finished result if used."""
        if force or not prefer_service:
            return None

        service_status, _service_pid = self.check_freshclam_service()
        if service_status != FreshclamServiceStatus.RUNNING:
            return None

        success, message = self.trigger_service_update()
        if success:
            return self._create_result(
                UpdateStatus.SUCCESS,
                stdout=message,
                exit_code=0,
                update_method=UpdateMethod.SERVICE_SIGNAL,
            )

        logger.warning(
            "Service update trigger failed (%s), "
            "not falling back to manual method (service holds locks)",
            message,
        )
        return self._create_result(
            UpdateStatus.ERROR,
            stderr=message,
            error_message=_(
                "Could not trigger freshclam service update. "
                "Try restarting the service: "
                "sudo systemctl restart clamav-freshclam"
            ),
        )

    def _prepare_force_update_result(self, *, force: bool) -> UpdateResult | None:
        """Keep the legacy hook side-effect free.

        Force updates now stage and promote inside the privileged shell
        transaction.  In particular, no Python-side backup or deletion may
        run before freshclam has completed.
        """
        return None

    def _get_running_instance_result(self) -> UpdateResult | None:
        """Return an error result when another freshclam instance is active."""
        is_running, running_pid = self._check_freshclam_running()
        if not (is_running and running_pid):
            return None

        logger.warning(
            "Another freshclam instance running (PID %s), aborting manual update",
            running_pid,
        )
        return self._create_result(
            UpdateStatus.ERROR,
            error_message=_(
                "Another freshclam instance is running (PID {pid}). "
                "Stop it first: sudo systemctl stop clamav-freshclam"
            ).format(pid=running_pid),
        )

    @staticmethod
    def _decode_timeout_stream(stream: bytes | str | None) -> str:
        """Normalize TimeoutExpired stdout/stderr values to text."""
        if not stream:
            return ""
        if isinstance(stream, str):
            return stream
        return stream.decode("utf-8", errors="replace")

    @staticmethod
    def _process_group_exists(pid: int | None) -> bool:
        """Return whether a POSIX process group still has any members."""
        if (
            os.name != "posix"
            or not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid <= 0
            or not callable(getattr(os, "killpg", None))
        ):
            return False

        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # The group exists, but this process is not allowed to signal it.
            return True
        except OSError:
            return False
        return True

    def _signal_process_group(
        self,
        process: subprocess.Popen,
        signal_number: int | None,
    ) -> bool | None:
        """Signal an isolated process group, falling back to the process handle.

        Returns ``True`` when a usable POSIX process-group target was found,
        ``False`` when the process-level fallback succeeded, and ``None`` when
        the fallback could not signal an already-gone process.
        """
        pid = getattr(process, "pid", None)
        group_available = (
            os.name == "posix"
            and isinstance(pid, int)
            and not isinstance(pid, bool)
            and pid > 0
            and signal_number is not None
            and callable(getattr(os, "killpg", None))
        )
        fallback_method = (
            process.terminate if signal_number == getattr(signal, "SIGTERM", None) else process.kill
        )

        if group_available:
            try:
                os.killpg(pid, signal_number)
            except (OSError, ProcessLookupError):
                logger.debug(
                    "Failed to signal update process group (pgid=%s, signal=%s)",
                    pid,
                    signal_number,
                    exc_info=True,
                )
                try:
                    fallback_method()
                except (OSError, ProcessLookupError):
                    logger.debug(
                        "Failed to signal update process after group signal failure",
                        exc_info=True,
                    )
            return True

        try:
            fallback_method()
        except (OSError, ProcessLookupError):
            logger.debug("Failed to signal update process", exc_info=True)
            return None
        return False

    def _collect_timeout_output(
        self,
        process: subprocess.Popen,
        timeout_error: subprocess.TimeoutExpired,
    ) -> tuple[str, str]:
        """Collect partial subprocess output after a communicate timeout."""
        partial_stdout = self._decode_timeout_stream(timeout_error.stdout)
        partial_stderr = self._decode_timeout_stream(timeout_error.stderr)

        try:
            remaining_stdout, remaining_stderr = process.communicate(timeout=_KILL_WAIT_TIMEOUT)
            return partial_stdout + (remaining_stdout or ""), partial_stderr + (
                remaining_stderr or ""
            )
        except subprocess.TimeoutExpired:
            return partial_stdout, partial_stderr

    def _cleanup_current_process(self) -> None:
        """Clear the active process handle and ensure the process is no longer running."""
        with self._process_lock:
            process = self._current_process
            if process is None:
                return
            self._current_process = None
        try:
            if process.poll() is None:
                self._signal_process_group(process, getattr(signal, "SIGKILL", None))
            process.wait(timeout=_KILL_WAIT_TIMEOUT)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            logger.debug("Failed to forcefully terminate update process", exc_info=True)

    def _run_update_process(self, cmd: list[str]) -> tuple[str, str, int, bool]:
        """Execute the freshclam subprocess and return its output and timeout state."""
        self._update_cancelled = False
        with self._process_lock:
            popen_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "env": get_clean_env(),
            }
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(cmd, **popen_kwargs)
            self._current_process = process

        timed_out = False
        stdout = ""
        stderr = ""
        exit_code = -1

        try:
            stdout, stderr = process.communicate(timeout=_UPDATE_COMMUNICATE_TIMEOUT)
            exit_code = process.returncode
        except subprocess.TimeoutExpired as e:
            logger.warning("Update process timed out, requesting graceful shutdown")
            timed_out = True
            terminate_mode = self._signal_process_group(
                process,
                getattr(signal, "SIGTERM", None),
            )
            if terminate_mode:
                try:
                    process.wait(timeout=_TERMINATE_GRACE_TIMEOUT)
                except subprocess.TimeoutExpired:
                    logger.warning("Update process didn't terminate gracefully")
                except (OSError, ProcessLookupError):
                    logger.debug(
                        "Update process disappeared during graceful timeout cleanup",
                        exc_info=True,
                    )

                # The wrapper can exit after its EXIT trap removes staging while
                # a stubborn descendant keeps the process group alive.
                if self._process_group_exists(getattr(process, "pid", None)):
                    self._signal_process_group(
                        process,
                        getattr(signal, "SIGKILL", None),
                    )
            elif terminate_mode is False:
                # Preserve process-level fallback behavior for non-POSIX
                # platforms and mocks without a usable process group.
                try:
                    process.wait(timeout=_TERMINATE_GRACE_TIMEOUT)
                except subprocess.TimeoutExpired:
                    logger.warning("Update process didn't terminate gracefully, killing")
                    self._signal_process_group(
                        process,
                        getattr(signal, "SIGKILL", None),
                    )
                except (OSError, ProcessLookupError):
                    logger.debug(
                        "Update process disappeared during graceful timeout cleanup",
                        exc_info=True,
                    )
            stdout, stderr = self._collect_timeout_output(process, e)
        finally:
            self._cleanup_current_process()

        return stdout, stderr, exit_code, timed_out

    def _run_manual_update(self, *, force: bool, start_time: float) -> UpdateResult:
        """Execute the manual freshclam path once preconditions have passed."""
        running_result = self._get_running_instance_result()
        if running_result is not None:
            return self._finish_update(running_result, start_time)

        cmd = self._build_command(force=force)

        try:
            stdout, stderr, exit_code, timed_out = self._run_update_process(cmd)
        except FileNotFoundError:
            return self._finish_update(
                self._create_result(
                    UpdateStatus.ERROR,
                    stderr="freshclam executable not found",
                    error_message=_("freshclam executable not found"),
                ),
                start_time,
            )
        except PermissionError as e:
            return self._finish_update(
                self._create_result(
                    UpdateStatus.ERROR,
                    stderr=str(e),
                    error_message=_("Permission denied: {error}").format(error=e),
                ),
                start_time,
            )
        except Exception as e:
            return self._finish_update(
                self._create_result(
                    UpdateStatus.ERROR,
                    stderr=str(e),
                    error_message=_("Update failed: {error}").format(error=e),
                ),
                start_time,
            )

        if timed_out and not self._update_cancelled:
            return self._finish_update(
                self._create_result(
                    UpdateStatus.ERROR,
                    stdout=stdout,
                    stderr=stderr,
                    error_message=_("Update timed out after 10 minutes"),
                ),
                start_time,
            )

        if self._update_cancelled:
            return self._finish_update(
                self._create_result(
                    UpdateStatus.CANCELLED,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    error_message=_("Update cancelled by user"),
                ),
                start_time,
            )

        result = self._parse_results(stdout, stderr, exit_code)

        return self._finish_update(result, start_time)

    def update_sync(self, force: bool = False, prefer_service: bool = True) -> UpdateResult:
        """
        Execute a synchronous database update.

        WARNING: This will block the calling thread. For UI applications,
        use update_async() instead.

        Args:
            force: If True, download into a staging directory and promote
                   fresh database files only after a successful freshclam
                   run. Existing live definitions stay readable during the
                   download and are preserved if it fails.
            prefer_service: If True (default), attempt to trigger update via
                           freshclam systemd service using SIGUSR1 when available.
                           Falls back to manual method if service not running.
                           Force updates always use manual method.

        Returns:
            UpdateResult with update details
        """
        start_time = time.monotonic()

        availability_result = self._check_availability_result()
        if availability_result is not None:
            return self._finish_update(availability_result, start_time)

        service_result = self._try_service_update_result(force=force, prefer_service=prefer_service)
        if service_result is not None:
            return self._finish_update(service_result, start_time)

        return self._run_manual_update(force=force, start_time=start_time)

    def update_async(
        self,
        callback: Callable[[UpdateResult], None],
        force: bool = False,
        prefer_service: bool = True,
    ) -> None:
        """
        Execute an asynchronous database update.

        The update runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        Args:
            callback: Function to call with UpdateResult when update completes
            force: If True, download into a staging directory and promote
                   fresh database files only after a successful freshclam
                   run. Existing live definitions stay readable during the
                   download and are preserved if it fails.
            prefer_service: If True (default), attempt to trigger update via
                           freshclam systemd service using SIGUSR1 when available.
                           Force updates always use manual method.
        """

        def update_thread():
            result = self.update_sync(force=force, prefer_service=prefer_service)
            # Schedule callback on main thread
            GLib.idle_add(callback, result)

        thread = threading.Thread(target=update_thread)
        thread.daemon = True
        thread.start()

    def cancel(self) -> None:
        """
        Cancel the current update operation with graceful shutdown escalation.

        If an update is in progress, it will be terminated with SIGTERM first,
        then escalated to SIGKILL if the process doesn't respond within
        the grace period.
        """
        self._update_cancelled = True
        with self._process_lock:
            process = self._current_process
        if process is None:
            return

        terminate_mode = self._signal_process_group(
            process,
            getattr(signal, "SIGTERM", None),
        )
        if terminate_mode is None:
            # Process already gone
            return

        if terminate_mode:
            # The leader can exit while descendants keep the group alive. Always
            # send SIGKILL to the group after the graceful wait.
            try:
                process.wait(timeout=_TERMINATE_GRACE_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.warning("Update process didn't terminate gracefully, killing")
            except (OSError, ProcessLookupError):
                logger.debug("Update process disappeared during graceful shutdown", exc_info=True)

            self._signal_process_group(process, getattr(signal, "SIGKILL", None))
            try:
                process.wait(timeout=_KILL_WAIT_TIMEOUT)
            except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
                logger.debug(
                    "Failed to kill update process group after graceful shutdown timeout",
                    exc_info=True,
                )
            return

        # Preserve the process-level fallback's existing conditional escalation.
        try:
            process.wait(timeout=_TERMINATE_GRACE_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.warning("Update process didn't terminate gracefully, killing")
            kill_mode = self._signal_process_group(
                process,
                getattr(signal, "SIGKILL", None),
            )
            if kill_mode is None:
                return
            try:
                process.wait(timeout=_KILL_WAIT_TIMEOUT)
            except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
                logger.debug(
                    "Failed to kill update process after graceful shutdown timeout",
                    exc_info=True,
                )
        except (OSError, ProcessLookupError):
            logger.debug("Update process disappeared during graceful shutdown", exc_info=True)

    def _build_command(self, force: bool = False) -> list[str]:
        """
        Build the freshclam command arguments with privilege elevation.

        Uses pkexec for privilege elevation since freshclam requires
        root access to update the ClamAV database in /var/lib/clamav/.

        When running inside a Flatpak sandbox, the command is automatically
        wrapped with 'flatpak-spawn --host' to execute freshclam on the host
        system.

        Args:
            force: If True, download into a staging directory and promote
                   database files only after freshclam succeeds.  The live
                   database remains available throughout the download.

        Returns:
            List of command arguments (wrapped with flatpak-spawn if in Flatpak)
        """
        freshclam = get_freshclam_path() or "freshclam"
        pkexec = get_pkexec_path()

        if force:
            script = _build_force_update_script()
            if pkexec:
                # Pass freshclam as $1 (positional data), never as shell source.
                # This keeps paths containing shell metacharacters harmless.
                cmd = [
                    pkexec,
                    "sh",
                    "-c",
                    script,
                    "clamui-force-update",  # $0 (script name for diagnostics)
                    freshclam,  # $1 (safe — not interpreted as shell syntax)
                ]
            else:
                # Without pkexec the same transaction is attempted directly;
                # it may fail with a permission error for root-owned databases,
                # but it never falls back to deleting live definitions.
                cmd = [
                    "sh",
                    "-c",
                    script,
                    "clamui-force-update",
                    freshclam,
                ]
            return wrap_host_command(cmd)

        if pkexec:
            cmd = [pkexec, freshclam]
        else:
            # Fallback to running without elevation (may fail with permission error)
            cmd = [freshclam]

        # Add verbose flag for more detailed output
        cmd.append("--verbose")

        # Wrap with flatpak-spawn if running inside Flatpak sandbox
        return wrap_host_command(cmd)

    def _parse_results(self, stdout: str, stderr: str, exit_code: int) -> UpdateResult:
        """
        Parse freshclam output into an UpdateResult.

        freshclam exit codes:
        - 0: Success (updates downloaded or already current)
        - 1: Error occurred

        Args:
            stdout: Standard output from freshclam
            stderr: Standard error from freshclam
            exit_code: Process exit code

        Returns:
            Parsed UpdateResult
        """
        parsed_output = self._parse_output_details(stdout, stderr)
        databases_updated = len(parsed_output.updated_databases)

        # Determine status from exit code and parsed info
        if exit_code == 0:
            if databases_updated > 0:
                status = UpdateStatus.SUCCESS
            else:
                status = UpdateStatus.UP_TO_DATE
            error_message = None
        else:
            status = UpdateStatus.ERROR
            # Try to extract a meaningful error message
            error_message = self._extract_error_message(
                stdout,
                stderr,
                exit_code,
                parsed_output=parsed_output,
            )

        return UpdateResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            databases_updated=databases_updated,
            error_message=error_message,
            updated_databases=parsed_output.updated_databases,
            up_to_date_databases=parsed_output.up_to_date_databases,
            rate_limited_databases=parsed_output.rate_limited_databases,
        )

    @staticmethod
    def _append_unique(items: list[str], value: str | None) -> None:
        """Append a database name to a list once while preserving order."""
        if value and value not in items:
            items.append(value)

    @staticmethod
    def _extract_database_name_from_line(line: str) -> str | None:
        """Extract a ClamAV database filename from a freshclam output line."""
        match = _DATABASE_FILE_RE.search(line)
        return match.group(1) if match else None

    def _parse_output_details(self, stdout: str, stderr: str) -> _ParsedFreshclamOutput:
        """
        Parse freshclam output and preserve per-database state.

        freshclam may update one database, leave another up to date, and rate-limit
        a third. We keep that structure so callers can present partial progress
        instead of flattening everything into a single generic error.
        """
        parsed = _ParsedFreshclamOutput()
        output = "\n".join(part for part in (stdout, stderr) if part)

        current_database_context: str | None = None
        pending_rate_limit = False
        pending_cooldown_until: str | None = None
        pending_rate_limit_database: str | None = None

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            line_lower = line.lower()
            database = self._extract_database_name_from_line(line)
            if database:
                current_database_context = database

            if "updated (version:" in line_lower and database:
                self._append_unique(parsed.updated_databases, database)
                parsed.rate_limited_databases.pop(database, None)
                if pending_rate_limit_database == database:
                    pending_rate_limit = False
                    pending_cooldown_until = None
                    pending_rate_limit_database = None
                if current_database_context == database:
                    current_database_context = None
                continue

            if ("is up-to-date" in line_lower or "is up to date" in line_lower) and database:
                self._append_unique(parsed.up_to_date_databases, database)
                parsed.rate_limited_databases.pop(database, None)
                if pending_rate_limit_database == database:
                    pending_rate_limit = False
                    pending_cooldown_until = None
                    pending_rate_limit_database = None
                if current_database_context == database:
                    current_database_context = None
                continue

            cooldown_match = _COOLDOWN_UNTIL_RE.search(line)
            if cooldown_match:
                pending_rate_limit = True
                pending_cooldown_until = cooldown_match.group(1).strip()
                target_database = pending_rate_limit_database or current_database_context
                if target_database:
                    pending_rate_limit_database = target_database
                    parsed.rate_limited_databases[target_database] = pending_cooldown_until
                continue

            rate_limit_detected = any(pattern in line_lower for pattern in _RATE_LIMIT_PATTERNS)
            if "cloudfront" in line_lower or "cloudflare" in line_lower:
                rate_limit_detected = True

            if rate_limit_detected:
                pending_rate_limit = True
                target_database = database or current_database_context
                if target_database:
                    pending_rate_limit_database = target_database
                    parsed.rate_limited_databases.setdefault(
                        target_database,
                        pending_cooldown_until,
                    )
                continue

            download_failed = "can't download" in line_lower or "cannot download" in line_lower
            update_failed = "failed to update" in line_lower
            if database and (download_failed or update_failed) and pending_rate_limit:
                parsed.rate_limited_databases[database] = pending_cooldown_until
                pending_rate_limit_database = database
                if update_failed:
                    pending_rate_limit = False
                    pending_cooldown_until = None
                    pending_rate_limit_database = None
                    if current_database_context == database:
                        current_database_context = None

        return parsed

    @staticmethod
    def _format_database_list(databases: list[str]) -> str:
        """Format database names for human-readable summaries."""
        return ", ".join(databases)

    @staticmethod
    def _format_rate_limited_databases(rate_limited_databases: dict[str, str | None]) -> str:
        """Format per-database rate limit details for summaries."""
        entries = []
        for database, cooldown_until in rate_limited_databases.items():
            if cooldown_until:
                entries.append(
                    _("{database} until {cooldown}").format(
                        database=database,
                        cooldown=cooldown_until,
                    )
                )
            else:
                entries.append(database)
        return ", ".join(entries)

    def _extract_error_message(
        self,
        stdout: str,
        stderr: str,
        exit_code: int = 1,
        parsed_output: _ParsedFreshclamOutput | None = None,
    ) -> str:
        """
        Extract a meaningful error message from freshclam output.

        Args:
            stdout: Standard output from freshclam
            stderr: Standard error from freshclam
            exit_code: Process exit code

        Returns:
            Extracted error message
        """
        parsed_output = parsed_output or self._parse_output_details(stdout, stderr)

        # Check for common error patterns
        output = stdout + stderr
        output_lower = output.lower()

        # Check for pkexec authentication errors
        # Exit code 126 = pkexec: user dismissed auth dialog
        # Exit code 127 = pkexec: not authorized
        if exit_code == 126:
            return _("Authentication cancelled. Database update requires administrator privileges.")
        if exit_code == 127 and "pkexec" in output_lower:
            return _("Authorization failed. You are not authorized to update the database.")

        if parsed_output.rate_limited_databases:
            details = self._format_rate_limited_databases(parsed_output.rate_limited_databases)
            progress_parts = []
            if parsed_output.updated_databases:
                progress_parts.append(
                    _("Updated: {databases}").format(
                        databases=self._format_database_list(parsed_output.updated_databases)
                    )
                )
            if parsed_output.up_to_date_databases:
                progress_parts.append(
                    _("Already current: {databases}").format(
                        databases=self._format_database_list(parsed_output.up_to_date_databases)
                    )
                )

            if progress_parts:
                return _(
                    "Database update partially completed. {progress}. Rate limited: {details}."
                ).format(progress=". ".join(progress_parts), details=details)

            return _("Update rate limited for: {details}.").format(details=details)

        # Rate limiting errors
        if any(pattern in output_lower for pattern in _RATE_LIMIT_PATTERNS):
            return _("Update rate limited by mirror. Please wait a few minutes and try again.")

        # CDN/Proxy errors (often indicate rate limiting)
        if "cloudfront" in output_lower or "cloudflare" in output_lower:
            return _(
                "Update blocked by CDN. This may be due to rate limiting."
                " Please wait and try again later."
            )

        # Mirror unavailable
        if "mirror" in output_lower and ("down" in output_lower or "unavailable" in output_lower):
            return _("ClamAV mirror is currently unavailable. Please try again later.")

        # Certificate/SSL errors
        if any(
            p in output_lower for p in ["certificate", "ssl error", "tls error", "verify failed"]
        ):
            return _("SSL/TLS certificate error. The mirror may have configuration issues.")

        # Timeout errors
        if "timeout" in output_lower or "timed out" in output_lower:
            return _("Connection timed out. Please check your network connection.")

        # Check for polkit/pkexec related errors
        if "not authorized" in output_lower or "authorization" in output_lower:
            return _("Authorization failed. Please try again and enter your password.")

        # Check for lock file error (another freshclam running)
        if "locked" in output_lower or "lock" in output_lower:
            return _("Database is locked. Another freshclam instance may be running.")

        # Check for permission errors
        if "permission denied" in output_lower:
            return _("Permission denied. You may need elevated privileges to update the database.")

        # Check for network errors
        if "can't connect" in output_lower or "connection" in output_lower:
            return _("Connection error. Please check your network connection.")

        # Check for DNS errors
        if "can't resolve" in output_lower or "host not found" in output_lower:
            return _("DNS resolution failed. Please check your network settings.")

        # Default to stderr content if available
        if stderr.strip():
            return stderr.strip()

        return _("Update failed with an unknown error. Check the logs for details.")

    def _save_update_log(self, result: UpdateResult, duration: float) -> None:
        """
        Save an update result to the log manager.

        Args:
            result: The UpdateResult to log
            duration: Duration of the update in seconds
        """
        # Build summary based on update result
        if result.status == UpdateStatus.SUCCESS:
            summary = _("Database update completed - {count} database(s) updated").format(
                count=result.databases_updated
            )
        elif result.status == UpdateStatus.UP_TO_DATE:
            summary = _("Database update completed - Already up to date")
        elif result.status == UpdateStatus.CANCELLED:
            summary = _("Database update cancelled")
        else:
            summary = _("Database update failed: {error}").format(
                error=result.error_message or _("Unknown error")
            )

        # Build details combining stdout and stderr
        details_parts = []
        if result.stdout:
            details_parts.append(result.stdout)
        if result.stderr:
            details_parts.append(f"--- Errors ---\n{result.stderr}")
        details = "\n".join(details_parts) if details_parts else "(No output)"

        # Create and save log entry
        log_entry = LogEntry.create(
            log_type="update",
            status=result.status.value,
            summary=summary,
            details=details,
            path=None,  # Updates don't have a path
            duration=duration,
        )

        self._log_manager.save_log(log_entry)

    def _backup_local_databases(self) -> tuple[bool, str | None, list[Path]]:
        """
        Backup local ClamAV database files to a temporary directory.

        Returns:
            Tuple of (success, error_message, list_of_backed_files)
        """
        # Determine database directory
        if is_flatpak():
            db_dir = get_clamav_database_dir()
            if db_dir is None:
                return False, "Database directory not configured", []
        else:
            db_dir = Path("/var/lib/clamav")

        if not db_dir.exists():
            return False, "Database directory not found", []

        # Create backup directory with timestamp
        backup_dir = Path(tempfile.mkdtemp(prefix="clamav_backup_"))
        self._force_update_backup_dir = backup_dir

        # Common ClamAV database files
        db_patterns = ["*.cvd", "*.cld", "*.cud"]
        backed_up = []

        for pattern in db_patterns:
            for db_file in db_dir.glob(pattern):
                try:
                    backup_path = backup_dir / db_file.name
                    shutil.copy2(db_file, backup_path)
                    backed_up.append(backup_path)
                    logger.debug("Backed up database file: %s", db_file.name)
                except OSError as e:
                    # Cleanup on failure
                    shutil.rmtree(backup_dir, ignore_errors=True)
                    return False, f"Failed to backup {db_file.name}: {e}", []

        if not backed_up:
            shutil.rmtree(backup_dir, ignore_errors=True)
            return False, "No database files found to backup", []

        logger.info("Backed up %d database file(s) to %s", len(backed_up), backup_dir)
        return True, None, backed_up

    def _restore_databases_from_backup(self) -> tuple[bool, str | None]:
        """
        Restore database files from backup.

        Returns:
            Tuple of (success, error_message)
        """
        backup_dir = self._force_update_backup_dir
        if not backup_dir or not backup_dir.exists():
            return False, "No backup available"

        # Determine database directory
        if is_flatpak():
            db_dir = get_clamav_database_dir()
            if db_dir is None:
                return False, "Database directory not configured"
        else:
            db_dir = Path("/var/lib/clamav")

        if not db_dir.exists():
            return False, "Database directory not found"

        restored_count = 0
        for backup_file in backup_dir.glob("*"):
            try:
                target_path = db_dir / backup_file.name
                shutil.copy2(backup_file, target_path)
                restored_count += 1
                logger.debug("Restored database file: %s", backup_file.name)
            except OSError as e:
                return False, f"Failed to restore {backup_file.name}: {e}"

        logger.info("Restored %d database file(s) from backup", restored_count)
        return True, f"Restored {restored_count} database file(s)"

    def _cleanup_backup(self) -> None:
        """Clean up backup directory."""
        backup_dir = self._force_update_backup_dir
        if backup_dir and backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
            self._force_update_backup_dir = None
            logger.debug("Cleaned up backup directory: %s", backup_dir)

    def _delete_local_databases(self) -> tuple[bool, str | None, int]:
        """
        Delete local ClamAV database files to force fresh download.

        Returns:
            Tuple of (success, error_message, deleted_count)
        """
        # Determine database directory
        if is_flatpak():
            db_dir = get_clamav_database_dir()
            if db_dir is None:
                return False, "Database directory not configured", 0
        else:
            db_dir = Path("/var/lib/clamav")

        if not db_dir.exists():
            return False, "Database directory not found", 0

        # Common ClamAV database files
        db_patterns = ["*.cvd", "*.cld", "*.cud"]
        deleted_count = 0
        errors = []

        for pattern in db_patterns:
            for db_file in db_dir.glob(pattern):
                try:
                    db_file.unlink()
                    deleted_count += 1
                    logger.debug("Deleted database file: %s", db_file.name)
                except OSError as e:
                    errors.append(f"{db_file.name}: {e}")

        if errors:
            error_msg = f"Some files could not be deleted: {'; '.join(errors)}"
            if deleted_count == 0:
                return False, error_msg, 0
            # Partial success - log warning but continue
            logger.warning(error_msg)

        logger.info("Deleted %d database file(s)", deleted_count)
        return True, None, deleted_count
