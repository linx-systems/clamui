# ClamUI Scheduler Module
"""
Scheduler module for ClamUI providing system-level scheduled scanning.
Supports systemd timers (primary) and cron (fallback) for persistent
scheduling that runs even when the GUI application is closed.
"""

import logging
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .utils import get_clean_env, is_flatpak, which_host_command, wrap_host_command

logger = logging.getLogger(__name__)


def _validate_target_paths(targets: list[str]) -> str | None:
    """
    Validate target paths for security issues.

    Checks for:
    - Newlines (could inject additional cron/systemd entries)
    - Other control characters that could cause injection

    Args:
        targets: List of target paths to validate

    Returns:
        Error message if validation fails, None if all paths are valid
    """
    for target in targets:
        # Check for newlines (crontab injection)
        if "\n" in target or "\r" in target:
            return f"Invalid path contains newline characters: {target}"
        # Check for null bytes (path truncation attacks)
        if "\x00" in target:
            return f"Invalid path contains null bytes: {target}"
    return None


def _is_clamui_cron_command(line: str) -> bool:
    """Return True if a crontab line looks like a ClamUI scheduled-scan command.

    Used as a safety check before dropping the line that follows a ClamUI
    marker line. We intentionally accept any of the known invocations:
    - ``clamui-scheduled-scan`` entry-point binary (PATH or absolute)
    - ``-m src.cli.scheduled_scan`` module form (venv fallback)
    - ``flatpak run --command=clamui-scheduled-scan ...`` Flatpak form
    """
    stripped = line.strip()
    if not stripped:
        return False
    return "clamui-scheduled-scan" in stripped or "src.cli.scheduled_scan" in stripped


class SchedulerBackend(Enum):
    """Available scheduler backends."""

    SYSTEMD = "systemd"
    CRON = "cron"
    NONE = "none"


class ScheduleFrequency(Enum):
    """Schedule frequency options."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class ScheduleConfig:
    """
    Configuration for a scheduled scan.

    Attributes:
        enabled: Whether the schedule is active
        frequency: How often to run (daily, weekly, monthly)
        time: Time of day to run in HH:MM format (24-hour)
        targets: List of paths to scan
        skip_on_battery: Whether to skip scan when on battery power
        auto_quarantine: Whether to automatically quarantine threats
        day_of_week: Day for weekly scans (0=Monday, 6=Sunday)
        day_of_month: Day for monthly scans (1-28)
    """

    enabled: bool = False
    frequency: ScheduleFrequency = ScheduleFrequency.DAILY
    time: str = "02:00"
    targets: list[str] | None = None
    skip_on_battery: bool = True
    auto_quarantine: bool = False
    day_of_week: int = 0  # Monday
    day_of_month: int = 1

    def __post_init__(self):
        """Initialize mutable default."""
        if self.targets is None:
            self.targets = []


# Detection caches (None = not checked)
_systemd_available: bool | None = None
_cron_available: bool | None = None
_scheduler_cache_lock = threading.Lock()


def _check_systemd_available() -> bool:
    """
    Check if systemd is available and usable for user-level timers.

    In Flatpak environments, assumes systemd is available on the host since
    'which systemctl' detection fails in the sandbox but actual systemctl
    commands work via flatpak-spawn --host. If systemd is not actually
    available, enable/disable operations will fail with a clear error.

    Thread-safe via lock.

    Returns:
        True if systemd user timers are available, False otherwise
    """
    global _systemd_available

    with _scheduler_cache_lock:
        if _systemd_available is not None:
            return _systemd_available

        # In Flatpak, assume systemd is available on the host.
        # The 'which systemctl' detection fails in the sandbox, but
        # actual systemctl commands work via flatpak-spawn --host.
        # Most modern Linux desktops have systemd, and if not,
        # the enable/disable operations will fail with a clear error.
        if is_flatpak():
            logger.debug("Flatpak detected: assuming systemd available on host")
            _systemd_available = True
            return True

        # Check if systemctl exists
        systemctl_path = which_host_command("systemctl")
        if systemctl_path is None:
            _systemd_available = False
            return False

        # Verify systemd user session is running
        try:
            result = subprocess.run(
                wrap_host_command(["systemctl", "--user", "status"]),
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )
            # systemctl --user status returns 0 even if no units
            # It returns non-zero if user session isn't available
            _systemd_available = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as e:
            logger.debug("Systemd check failed with expected error: %s", e)
            _systemd_available = False
        except Exception as e:
            logger.debug("Systemd availability check failed: %s", e)
            _systemd_available = False

        return _systemd_available


def _check_cron_available() -> bool:
    """
    Check if cron is available.

    Thread-safe via lock.

    Returns:
        True if crontab command is available, False otherwise
    """
    global _cron_available

    with _scheduler_cache_lock:
        if _cron_available is not None:
            return _cron_available

        # Check if crontab command exists
        crontab_path = which_host_command("crontab")
        _cron_available = crontab_path is not None

        return _cron_available


class Scheduler:
    """
    Manager for scheduled scan configuration and system scheduler integration.

    Provides abstraction layer for systemd timers and cron jobs,
    automatically detecting the best available backend.
    """

    # Service and timer file names
    SERVICE_NAME = "clamui-scheduled-scan"
    TIMER_NAME = "clamui-scheduled-scan"

    # Crontab marker for identifying ClamUI entries
    CRON_MARKER = "# ClamUI Scheduled Scan"

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize the Scheduler.

        Args:
            config_dir: Optional custom config directory for systemd files.
                        Defaults to XDG_CONFIG_HOME/systemd/user or
                        ~/.config/systemd/user
        """
        if config_dir is not None:
            self._config_dir = Path(config_dir)
        else:
            xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "~/.config")
            self._config_dir = Path(xdg_config_home).expanduser()

        # In Flatpak, systemd files must be written to the HOST's config dir,
        # not the sandboxed XDG_CONFIG_HOME. Path.home() returns the real home
        # directory, and we have --filesystem=~/.config/systemd/user:create
        # permission to write there.
        if is_flatpak():
            self._systemd_dir = Path.home() / ".config" / "systemd" / "user"
        else:
            self._systemd_dir = self._config_dir / "systemd" / "user"

        # Detect available backend
        self._backend = self._detect_backend()

    def _detect_backend(self) -> SchedulerBackend:
        """
        Detect the best available scheduler backend.

        Returns:
            SchedulerBackend indicating which system to use
        """
        if _check_systemd_available():
            return SchedulerBackend.SYSTEMD
        elif _check_cron_available():
            return SchedulerBackend.CRON
        else:
            return SchedulerBackend.NONE

    @property
    def backend(self) -> SchedulerBackend:
        """
        Get the current scheduler backend.

        Returns:
            SchedulerBackend indicating which system is being used
        """
        return self._backend

    @property
    def is_available(self) -> bool:
        """
        Check if any scheduler backend is available.

        Returns:
            True if either systemd or cron is available
        """
        return self._backend != SchedulerBackend.NONE

    @property
    def systemd_available(self) -> bool:
        """
        Check if systemd user timers are available.

        Returns:
            True if systemd is available
        """
        return _check_systemd_available()

    @property
    def cron_available(self) -> bool:
        """
        Check if cron is available.

        Returns:
            True if cron is available
        """
        return _check_cron_available()

    def get_backend_name(self) -> str:
        """
        Get human-readable name of the current backend.

        Returns:
            String name of the backend (e.g., "systemd timers")
        """
        if self._backend == SchedulerBackend.SYSTEMD:
            return "systemd timers"
        elif self._backend == SchedulerBackend.CRON:
            return "cron"
        else:
            return "none"

    def get_status(self) -> tuple[bool, str | None]:
        """
        Get current scheduler status.

        Returns:
            Tuple of (is_scheduled, next_run_time_or_error):
            - (True, next_run_time) if schedule is active
            - (False, None) if no schedule is active
            - (False, error_message) if an error occurred
        """
        if not self.is_available:
            return (False, "No scheduler backend available")

        if self._backend == SchedulerBackend.SYSTEMD:
            return self._get_systemd_status()
        elif self._backend == SchedulerBackend.CRON:
            return self._get_cron_status()
        else:
            return (False, None)

    def _get_systemd_status(self) -> tuple[bool, str | None]:
        """
        Get status of systemd timer.

        Returns:
            Tuple of (is_active, next_run_or_error)
        """
        try:
            result = subprocess.run(
                wrap_host_command(["systemctl", "--user", "is-active", f"{self.TIMER_NAME}.timer"]),
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )

            if result.returncode == 0:
                # Timer is active, get next run time
                next_result = subprocess.run(
                    wrap_host_command(
                        [
                            "systemctl",
                            "--user",
                            "show",
                            f"{self.TIMER_NAME}.timer",
                            "--property=NextElapseUSecRealtime",
                        ]
                    ),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=get_clean_env(),
                )

                if next_result.returncode == 0:
                    output = next_result.stdout.strip()
                    if "=" in output:
                        next_time = output.split("=", 1)[1]
                        return (True, next_time if next_time else None)

                return (True, None)
            else:
                return (False, None)

        except subprocess.TimeoutExpired:
            return (False, "Timeout checking timer status")
        except Exception as e:
            return (False, f"Error checking timer: {e!s}")

    def _get_cron_status(self) -> tuple[bool, str | None]:
        """
        Get status of cron entry.

        Returns:
            Tuple of (has_entry, None_or_error)
        """
        try:
            result = subprocess.run(
                wrap_host_command(["crontab", "-l"]),
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )

            if result.returncode == 0:
                if self.CRON_MARKER in result.stdout:
                    return (True, None)
                return (False, None)
            else:
                # No crontab or empty
                return (False, None)

        except subprocess.TimeoutExpired:
            return (False, "Timeout checking crontab")
        except Exception as e:
            return (False, f"Error checking crontab: {e!s}")

    def _generate_oncalendar(
        self,
        frequency: ScheduleFrequency,
        time: str,
        day_of_week: int = 0,
        day_of_month: int = 1,
    ) -> str:
        """
        Generate systemd OnCalendar specification.

        Args:
            frequency: Schedule frequency
            time: Time in HH:MM format
            day_of_week: Day of week (0=Monday) for weekly
            day_of_month: Day of month (1-28) for monthly

        Returns:
            OnCalendar specification string
        """
        # Validate time format
        try:
            hour, minute = time.split(":")
            hour = int(hour)
            minute = int(minute)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time")
        except (ValueError, AttributeError):
            # Default to 2:00 AM if invalid
            hour, minute = 2, 0

        time_str = f"{hour:02d}:{minute:02d}:00"

        if frequency == ScheduleFrequency.HOURLY:
            # Run at minute 0 of every hour
            return "*-*-* *:00:00"
        elif frequency == ScheduleFrequency.DAILY:
            return f"*-*-* {time_str}"
        elif frequency == ScheduleFrequency.WEEKLY:
            # Convert day_of_week (0=Monday) to systemd format
            days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            day = days[day_of_week % 7]
            return f"{day} *-*-* {time_str}"
        elif frequency == ScheduleFrequency.MONTHLY:
            # Ensure day is in valid range (1-28 for all months)
            day = max(1, min(28, day_of_month))
            return f"*-*-{day:02d} {time_str}"
        else:
            return f"*-*-* {time_str}"

    def _generate_crontab_entry(
        self,
        frequency: ScheduleFrequency,
        time: str,
        day_of_week: int = 0,
        day_of_month: int = 1,
    ) -> str:
        """
        Generate crontab entry specification.

        Args:
            frequency: Schedule frequency
            time: Time in HH:MM format
            day_of_week: Day of week (0=Monday) for weekly
            day_of_month: Day of month (1-28) for monthly

        Returns:
            Crontab time specification (e.g., "0 2 * * *")
        """
        # Validate time format
        try:
            hour, minute = time.split(":")
            hour = int(hour)
            minute = int(minute)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time")
        except (ValueError, AttributeError):
            # Default to 2:00 AM if invalid
            hour, minute = 2, 0

        if frequency == ScheduleFrequency.HOURLY:
            # Run at minute 0 of every hour: 0 * * * *
            return "0 * * * *"
        elif frequency == ScheduleFrequency.DAILY:
            # minute hour * * *
            return f"{minute} {hour} * * *"
        elif frequency == ScheduleFrequency.WEEKLY:
            # minute hour * * day_of_week
            # Cron uses 0=Sunday, 1=Monday, etc.
            # Convert from 0=Monday to cron format
            cron_day = (day_of_week + 1) % 7
            return f"{minute} {hour} * * {cron_day}"
        elif frequency == ScheduleFrequency.MONTHLY:
            # minute hour day_of_month * *
            day = max(1, min(28, day_of_month))
            return f"{minute} {hour} {day} * *"
        else:
            return f"{minute} {hour} * * *"

    def _get_venv_paths(self) -> list[Path]:
        """
        Get list of well-known ClamUI venv installation paths.

        These are the standard locations where install.sh installs ClamUI:
        - User installation: ~/.local/share/clamui/venv
        - System installation: /usr/local/share/clamui/venv or /usr/share/clamui/venv

        Returns:
            List of Path objects for potential venv locations
        """
        paths = []

        # User installation location (respects XDG_DATA_HOME)
        xdg_data_home = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        user_venv = Path(xdg_data_home) / "clamui" / "venv"
        paths.append(user_venv)

        # System installation locations
        paths.append(Path("/usr/local/share/clamui/venv"))
        paths.append(Path("/usr/share/clamui/venv"))

        return paths

    def _check_path_exists(self, path: Path) -> bool:
        """
        Check if a path exists, accounting for Flatpak sandbox.

        When running inside Flatpak, uses flatpak-spawn to check the host
        filesystem since the venv is installed on the host, not in the sandbox.

        Args:
            path: Path to check for existence

        Returns:
            True if the path exists, False otherwise
        """
        if is_flatpak():
            try:
                result = subprocess.run(
                    ["flatpak-spawn", "--host", "test", "-f", str(path)],
                    capture_output=True,
                    timeout=5,
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.debug("Path existence check failed for %s: %s", path, e)
                return False
            except Exception as e:
                logger.debug("Unexpected error checking path existence for %s: %s", path, e)
                return False
        return path.exists()

    def _get_cli_command_path(self) -> list[str] | None:
        """
        Get the command tokens to invoke the clamui-scheduled-scan CLI.

        Searches in order:
        0. Flatpak: use 'flatpak run <app-id>' command
        1. PATH (via which_host_command) - works when installed to /usr/bin etc.
        2. Well-known venv locations - for install.sh installations
        3. Fallback to module execution with venv's Python

        Returns:
            Command as a list of argv tokens, or None if not found. Tokens
            are kept unsplit so an executable path containing spaces or
            quotes survives intact (issue #150).
        """
        # 0. In Flatpak, use 'flatpak run --command=' to invoke the CLI from host systemd
        if is_flatpak():
            app_id = os.environ.get("FLATPAK_ID", "io.github.linx_systems.ClamUI")
            return ["flatpak", "run", "--command=clamui-scheduled-scan", app_id]

        # 1. First try to find it in PATH
        cli_path = which_host_command("clamui-scheduled-scan")
        if cli_path:
            return [cli_path]

        # 2. Check well-known venv installation locations for the entry point
        for venv_path in self._get_venv_paths():
            cli_bin = venv_path / "bin" / "clamui-scheduled-scan"
            if self._check_path_exists(cli_bin):
                return [str(cli_bin)]

        # 3. Check well-known venv locations for Python to run the module
        for venv_path in self._get_venv_paths():
            python_bin = venv_path / "bin" / "python"
            if self._check_path_exists(python_bin):
                # Use the venv's Python with the correct module path
                return [str(python_bin), "-m", "src.cli.scheduled_scan"]

        # 4. Last resort: System Python with correct module path
        # (This likely won't work unless installed system-wide via pip)
        python_path = which_host_command("python3") or which_host_command("python")
        if python_path:
            return [python_path, "-m", "src.cli.scheduled_scan"]

        return None

    def enable_schedule(
        self,
        frequency: str,
        time: str,
        targets: list[str],
        day_of_week: int = 0,
        day_of_month: int = 1,
        skip_on_battery: bool = True,
        auto_quarantine: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Enable scheduled scanning.

        Creates systemd timer/service files or crontab entry based on
        the available backend.

        Args:
            frequency: Schedule frequency ("daily", "weekly", "monthly")
            time: Time in HH:MM format (24-hour)
            targets: List of paths to scan
            day_of_week: Day of week for weekly (0=Monday)
            day_of_month: Day of month for monthly (1-28)
            skip_on_battery: Skip scan when on battery power
            auto_quarantine: Automatically quarantine threats

        Returns:
            Tuple of (success, error_message):
            - (True, None) if schedule was enabled
            - (False, error_message) if failed
        """
        if not self.is_available:
            return (
                False,
                "No scheduler backend available. "
                "Install systemd or cron to enable scheduled scans.",
            )

        # Validate target paths for security issues (newlines, null bytes)
        validation_error = _validate_target_paths(targets)
        if validation_error:
            return (False, validation_error)

        # Convert frequency string to enum
        try:
            freq = ScheduleFrequency(frequency.lower())
        except ValueError:
            return (False, f"Invalid frequency: {frequency}")

        if self._backend == SchedulerBackend.SYSTEMD:
            return self._enable_systemd_schedule(
                freq,
                time,
                targets,
                day_of_week,
                day_of_month,
                skip_on_battery,
                auto_quarantine,
            )
        elif self._backend == SchedulerBackend.CRON:
            return self._enable_cron_schedule(
                freq,
                time,
                targets,
                day_of_week,
                day_of_month,
                skip_on_battery,
                auto_quarantine,
            )
        else:
            return (False, "No scheduler backend available")

    def _enable_systemd_schedule(
        self,
        frequency: ScheduleFrequency,
        time: str,
        targets: list[str],
        day_of_week: int,
        day_of_month: int,
        skip_on_battery: bool,
        auto_quarantine: bool,
    ) -> tuple[bool, str | None]:
        """
        Create and enable systemd timer/service.

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Ensure systemd user directory exists
            self._systemd_dir.mkdir(parents=True, exist_ok=True)

            # Get CLI command tokens
            cli_command = self._get_cli_command_path()
            if not cli_command:
                return (False, "Could not find clamui-scheduled-scan command")

            # Generate OnCalendar specification
            on_calendar = self._generate_oncalendar(frequency, time, day_of_week, day_of_month)

            # Create service file
            service_content = self._generate_service_file(
                cli_command, targets, skip_on_battery, auto_quarantine
            )
            service_path = self._systemd_dir / f"{self.SERVICE_NAME}.service"
            service_path.write_text(service_content, encoding="utf-8")

            # Create timer file
            timer_content = self._generate_timer_file(on_calendar)
            timer_path = self._systemd_dir / f"{self.TIMER_NAME}.timer"
            timer_path.write_text(timer_content, encoding="utf-8")

            # Reload systemd daemon
            subprocess.run(
                wrap_host_command(["systemctl", "--user", "daemon-reload"]),
                capture_output=True,
                timeout=10,
                env=get_clean_env(),
            )

            # Enable and start timer
            result = subprocess.run(
                wrap_host_command(
                    [
                        "systemctl",
                        "--user",
                        "enable",
                        "--now",
                        f"{self.TIMER_NAME}.timer",
                    ]
                ),
                capture_output=True,
                text=True,
                timeout=10,
                env=get_clean_env(),
            )

            if result.returncode != 0:
                return (False, f"Failed to enable timer: {result.stderr.strip()}")

            return (True, None)

        except PermissionError:
            return (False, "Permission denied creating systemd files")
        except OSError as e:
            return (False, f"Error creating systemd files: {e!s}")
        except subprocess.TimeoutExpired:
            return (False, "Timeout enabling systemd timer")
        except Exception as e:
            return (False, f"Error enabling schedule: {e!s}")

    def _generate_service_file(
        self,
        cli_command: list[str],
        targets: list[str],
        skip_on_battery: bool,
        auto_quarantine: bool,
    ) -> str:
        """
        Generate systemd service file content.

        Args:
            cli_command: CLI invocation as a list of argv tokens (e.g.
                ['flatpak', 'run', ...]).
            targets: List of paths to scan
            skip_on_battery: Skip scan when on battery power
            auto_quarantine: Automatically quarantine threats

        Returns:
            Service file content as string
        """
        # Quote each argv token separately so multi-token commands (e.g.
        # 'flatpak run ...') stay an executable ExecStart rather than one
        # quoted blob, while shlex.quote() still prevents injection via
        # malicious paths.
        exec_cmd = " ".join(shlex.quote(tok) for tok in cli_command)

        # Neutralize systemd environment-variable expansion in user-supplied
        # paths.  Unlike a shell, systemd expands "${VAR}" (and a standalone
        # "$VAR" argument) even inside single quotes -- shlex.quote() does NOT
        # protect against this -- so a target such as "/data/${HOME}/x" would
        # be silently rewritten to a wrong/empty path at scan time.  The
        # documented escape for a literal dollar sign is "$$".  systemd does
        # NOT variable-expand the executable word, so only the argument
        # portion is escaped; doubling '$' in argv[0] would corrupt an
        # executable path containing a literal '$'.
        arg_str = ""
        if skip_on_battery:
            arg_str += " --skip-on-battery"
        if auto_quarantine:
            arg_str += " --auto-quarantine"
        for target in targets:
            arg_str += f" --target {shlex.quote(target)}"
        exec_cmd += arg_str.replace("$", "$$")

        # Escape literal '%' so systemd does not interpret it as a specifier
        # (e.g. legitimate directory names may contain '%').  Specifier
        # expansion covers the whole line including the executable word, so
        # this stays whole-line.
        exec_cmd = exec_cmd.replace("%", "%%")

        return f"""[Unit]
Description=ClamUI Scheduled Antivirus Scan
After=network.target

[Service]
Type=oneshot
ExecStart={exec_cmd}
Nice=19
IOSchedulingClass=idle

[Install]
WantedBy=default.target
"""

    def _generate_timer_file(self, on_calendar: str) -> str:
        """
        Generate systemd timer file content.

        Args:
            on_calendar: OnCalendar specification

        Returns:
            Timer file content as string
        """
        return f"""[Unit]
Description=ClamUI Scheduled Scan Timer

[Timer]
OnCalendar={on_calendar}
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
"""

    def _enable_cron_schedule(
        self,
        frequency: ScheduleFrequency,
        time: str,
        targets: list[str],
        day_of_week: int,
        day_of_month: int,
        skip_on_battery: bool,
        auto_quarantine: bool,
    ) -> tuple[bool, str | None]:
        """
        Create and enable cron entry.

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Get CLI command tokens
            cli_command = self._get_cli_command_path()
            if not cli_command:
                return (False, "Could not find clamui-scheduled-scan command")

            # Generate cron time specification
            cron_time = self._generate_crontab_entry(frequency, time, day_of_week, day_of_month)

            # Build command
            # Quote each argv token separately so multi-token commands (e.g.
            # 'flatpak run ...') stay an executable command rather than one
            # quoted blob, while shlex.quote() still prevents injection via
            # malicious paths.
            cron_cmd = " ".join(shlex.quote(tok) for tok in cli_command)
            if skip_on_battery:
                cron_cmd += " --skip-on-battery"
            if auto_quarantine:
                cron_cmd += " --auto-quarantine"
            for target in targets:
                cron_cmd += f" --target {shlex.quote(target)}"

            # Escape literal '%' so cron does not treat it as a newline/stdin
            # separator (e.g. legitimate directory names may contain '%').
            cron_cmd = cron_cmd.replace("%", "\\%")

            # Create cron entry
            cron_entry = f"{cron_time} {cron_cmd}"

            # Get current crontab
            result = subprocess.run(
                wrap_host_command(["crontab", "-l"]),
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )

            if result.returncode == 0:
                current_crontab = result.stdout
            else:
                current_crontab = ""

            # Remove any existing ClamUI entries.
            # Use anchored equality (with .strip()) to avoid dropping user
            # lines that merely contain the marker text as a substring.
            # Also verify the following line actually looks like a ClamUI
            # cron command before consuming it — defense against a marker
            # whose paired command was previously edited away by the user.
            lines = current_crontab.splitlines()
            new_lines = []
            skip_next = False
            for line in lines:
                if skip_next:
                    skip_next = False
                    if not _is_clamui_cron_command(line):
                        # Don't drop a user line that doesn't look like ours.
                        logger.warning(
                            "ClamUI cron marker found but next line is not a "
                            "ClamUI command; preserving user line: %r",
                            line,
                        )
                        new_lines.append(line)
                    continue
                if line.strip() == self.CRON_MARKER:
                    skip_next = True  # Skip the marker and the next line
                    continue
                new_lines.append(line)

            # Add new entry with marker
            new_lines.append(self.CRON_MARKER)
            new_lines.append(cron_entry)

            # Write new crontab
            new_crontab = "\n".join(new_lines) + "\n"

            result = subprocess.run(
                wrap_host_command(["crontab", "-"]),
                input=new_crontab,
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )

            if result.returncode != 0:
                return (False, f"Failed to update crontab: {result.stderr.strip()}")

            return (True, None)

        except subprocess.TimeoutExpired:
            return (False, "Timeout updating crontab")
        except Exception as e:
            return (False, f"Error enabling schedule: {e!s}")

    def disable_schedule(self) -> tuple[bool, str | None]:
        """
        Disable scheduled scanning.

        Removes systemd timer/service files or crontab entry.

        Returns:
            Tuple of (success, error_message):
            - (True, None) if schedule was disabled
            - (False, error_message) if failed
        """
        if not self.is_available:
            return (True, None)  # Nothing to disable

        if self._backend == SchedulerBackend.SYSTEMD:
            return self._disable_systemd_schedule()
        elif self._backend == SchedulerBackend.CRON:
            return self._disable_cron_schedule()
        else:
            return (True, None)

    def _disable_systemd_schedule(self) -> tuple[bool, str | None]:
        """
        Disable and remove systemd timer/service.

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Stop and disable timer
            subprocess.run(
                wrap_host_command(
                    [
                        "systemctl",
                        "--user",
                        "disable",
                        "--now",
                        f"{self.TIMER_NAME}.timer",
                    ]
                ),
                capture_output=True,
                timeout=10,
                env=get_clean_env(),
            )

            # Remove files
            service_path = self._systemd_dir / f"{self.SERVICE_NAME}.service"
            timer_path = self._systemd_dir / f"{self.TIMER_NAME}.timer"

            if service_path.exists():
                service_path.unlink()
            if timer_path.exists():
                timer_path.unlink()

            # Reload daemon
            subprocess.run(
                wrap_host_command(["systemctl", "--user", "daemon-reload"]),
                capture_output=True,
                timeout=10,
                env=get_clean_env(),
            )

            return (True, None)

        except PermissionError:
            return (False, "Permission denied removing systemd files")
        except OSError as e:
            return (False, f"Error removing systemd files: {e!s}")
        except subprocess.TimeoutExpired:
            return (False, "Timeout disabling systemd timer")
        except Exception as e:
            return (False, f"Error disabling schedule: {e!s}")

    def _disable_cron_schedule(self) -> tuple[bool, str | None]:
        """
        Remove cron entry.

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Get current crontab
            result = subprocess.run(
                wrap_host_command(["crontab", "-l"]),
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )

            if result.returncode != 0:
                return (True, None)  # No crontab to modify

            # Remove ClamUI entries.
            # Use anchored equality (with .strip()) to avoid dropping user
            # lines containing the marker as a substring, and verify the
            # following line is actually a ClamUI cron command before
            # consuming it.
            lines = result.stdout.splitlines()
            new_lines = []
            skip_next = False
            for line in lines:
                if skip_next:
                    skip_next = False
                    if not _is_clamui_cron_command(line):
                        logger.warning(
                            "ClamUI cron marker found but next line is not a "
                            "ClamUI command; preserving user line: %r",
                            line,
                        )
                        new_lines.append(line)
                    continue
                if line.strip() == self.CRON_MARKER:
                    skip_next = True
                    continue
                new_lines.append(line)

            # Write new crontab
            if new_lines:
                new_crontab = "\n".join(new_lines) + "\n"
                result = subprocess.run(
                    wrap_host_command(["crontab", "-"]),
                    input=new_crontab,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=get_clean_env(),
                )
            else:
                # Remove crontab entirely if empty
                result = subprocess.run(
                    wrap_host_command(["crontab", "-r"]),
                    capture_output=True,
                    timeout=5,
                    env=get_clean_env(),
                )

            if result.returncode != 0:
                return (
                    False,
                    f"Failed to update crontab: {result.stderr.strip() if hasattr(result, 'stderr') else ''}",
                )

            return (True, None)

        except subprocess.TimeoutExpired:
            return (False, "Timeout updating crontab")
        except Exception as e:
            return (False, f"Error disabling schedule: {e!s}")

    def is_schedule_active(self) -> bool:
        """
        Check if a schedule is currently active.

        Returns:
            True if schedule is active, False otherwise
        """
        is_active, _ = self.get_status()
        return is_active
