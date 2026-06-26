# ClamUI Tray Manager
"""
Manager for the system tray indicator subprocess.

This module spawns and communicates with the tray_service subprocess,
which runs with GTK3 to avoid GTK4 version conflicts. Communication
is done via JSON messages over stdin/stdout.

For detailed architecture documentation including process boundaries, IPC protocol,
threading model, and sequence diagrams, see: docs/architecture/tray-subprocess.md
"""

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import weakref
from collections.abc import Callable
from pathlib import Path

from gi.repository import GLib

logger = logging.getLogger(__name__)

# Module-level registry of TrayManager instances for atexit cleanup
# Uses weak references to avoid preventing garbage collection
_active_managers: weakref.WeakSet["TrayManager"] = weakref.WeakSet()
_atexit_registered = False


def _cleanup_all_managers() -> None:
    """Atexit handler to clean up all active TrayManager instances."""
    for manager in list(_active_managers):
        try:
            manager._close_pipes()
        except Exception:
            logger.debug("Failed to close tray manager pipes during atexit cleanup", exc_info=True)


class TrayManager:
    """
    Manager for the system tray indicator subprocess.

    Spawns tray_service.py as a subprocess and communicates with it
    via JSON messages. This avoids GTK3/GTK4 version conflicts by
    isolating GTK3 in a separate process.
    """

    # Bounded-respawn parameters: at most MAX_RESPAWNS within RESPAWN_WINDOW
    # seconds. Beyond that we declare the tray "down" and stop trying.
    MAX_RESPAWNS = 3
    RESPAWN_WINDOW = 60.0

    def __init__(self) -> None:
        """Initialize the TrayManager."""
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None

        # Thread lock for shared state accessed by reader threads
        self._state_lock = threading.Lock()
        self._running = False
        self._ready = False
        self._current_status = "protected"

        # Crash recovery state (UI-001).
        # _shutting_down distinguishes deliberate stop() from subprocess crash;
        # _respawn_count + _last_respawn_time implement a sliding-window
        # circuit breaker; _tray_down is observable for UI feedback.
        self._shutting_down = False
        self._respawn_count = 0
        self._last_respawn_time = 0.0
        self._tray_down = False

        # Callbacks for menu actions
        self._on_quick_scan: Callable[[], None] | None = None
        self._on_full_scan: Callable[[], None] | None = None
        self._on_update: Callable[[], None] | None = None
        self._on_quit: Callable[[], None] | None = None
        self._on_window_toggle: Callable[[], None] | None = None
        self._on_profile_select: Callable[[str], None] | None = None

        # Profile state
        self._current_profile_id: str | None = None
        # Last-known menu state, re-pushed to a respawned subprocess on "ready".
        self._current_profiles: list[dict] = []

        # Register for atexit cleanup
        global _atexit_registered
        _active_managers.add(self)
        if not _atexit_registered:
            atexit.register(_cleanup_all_managers)
            _atexit_registered = True

    def __del__(self) -> None:
        """
        Destructor to ensure pipes are closed on garbage collection.

        This acts as a safety net for cleanup when stop() is not called
        (e.g., during abnormal termination or when references are lost).
        """
        self._close_pipes()

    def _close_pipes(self) -> None:
        """
        Close subprocess pipes to prevent resource leaks.

        This method is safe to call multiple times and handles all exceptions
        silently to avoid issues during garbage collection or atexit.
        """
        if self._process is None:
            return

        for pipe in (self._process.stdin, self._process.stdout, self._process.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except Exception:
                    logger.debug("Failed to close tray subprocess pipe", exc_info=True)

    def start(self, respawn: bool = False) -> bool:
        """
        Start the tray service subprocess.

        Returns:
            True if subprocess started successfully, False otherwise.
        """
        if self._process is not None:
            logger.warning("Tray service already running")
            return True

        with self._state_lock:
            if respawn:
                # Respawn path: a deliberate stop() that raced ahead of
                # crash-respawn must win. Do NOT clear _shutting_down here.
                if self._shutting_down:
                    logger.info("Tray respawn aborted: shutdown requested")
                    return False
            else:
                # Re-arming after a previous stop() or respawn: clear state.
                self._shutting_down = False
                self._tray_down = False

        try:
            # Find the tray_service module path
            service_path = self._get_service_path()
            if not service_path:
                logger.error("Could not find tray_service.py")
                return False

            # Build command
            python_executable = sys.executable
            cmd = [python_executable, str(service_path)]

            # Set up environment
            env = os.environ.copy()
            if logger.isEnabledFor(logging.DEBUG):
                env["CLAMUI_DEBUG"] = "1"

            # Start subprocess
            logger.info(f"Starting tray service: {' '.join(cmd)}")
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                env=env,
            )

            with self._state_lock:
                self._running = True

            # Start reader thread for stdout
            self._reader_thread = threading.Thread(
                target=self._read_stdout, daemon=True, name="TrayManagerReader"
            )
            self._reader_thread.start()

            # Start stderr reader for logging
            stderr_thread = threading.Thread(
                target=self._read_stderr, daemon=True, name="TrayManagerStderr"
            )
            stderr_thread.start()

            # Wait a moment for ready signal
            # The actual ready check happens in _read_stdout
            logger.info("Tray service subprocess started")
            return True

        except Exception as e:
            logger.error(f"Failed to start tray service: {e}")
            self._process = None
            return False

    def _get_service_path(self) -> Path | None:
        """Get the path to tray_service.py."""
        # Try relative to this file
        this_dir = Path(__file__).parent
        service_path = this_dir / "tray_service.py"
        if service_path.exists():
            return service_path

        # Try as module path
        # This handles the case when installed as a package
        from . import tray_service as tray_service_module

        module_path = Path(tray_service_module.__file__)
        if module_path.exists():
            return module_path

        return None

    # Maximum size for JSON messages from subprocess (1MB)
    MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB

    def _read_stdout(self) -> None:
        """Read messages from the subprocess stdout."""
        try:
            if self._process is None or self._process.stdout is None:
                return

            for line in self._process.stdout:
                with self._state_lock:
                    if not self._running:
                        break

                line = line.strip()
                if not line:
                    continue

                # Security: Limit message size to prevent memory exhaustion
                if len(line) > self.MAX_MESSAGE_SIZE:
                    logger.error(
                        f"Message from tray service exceeds size limit "
                        f"({len(line)} > {self.MAX_MESSAGE_SIZE} bytes)"
                    )
                    continue

                try:
                    message = json.loads(line)

                    # Security: Validate message structure is not excessively nested
                    if not self._validate_message_structure(message):
                        logger.error("Message from tray service has invalid structure")
                        continue

                    self._handle_message(message)
                except (json.JSONDecodeError, ValueError, RecursionError) as e:
                    logger.error(f"Invalid JSON from tray service: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error reading tray service stdout: {e}")
        finally:
            logger.debug("Tray service stdout reader ended")
            # UI-001: subprocess EOF means the tray service died. Reset _ready,
            # capture exit code, and attempt bounded respawn unless we're
            # shutting down deliberately.
            self._handle_subprocess_exit()

    def _handle_subprocess_exit(self) -> None:
        """Handle subprocess EOF / exit detected by the stdout reader.

        On unexpected exit (crash): resets ``_ready``, polls for the exit
        code, and attempts a bounded respawn (max ``MAX_RESPAWNS`` per
        ``RESPAWN_WINDOW`` seconds).

        On deliberate shutdown (``_shutting_down`` set, or ``_running``
        already False): does nothing — the caller of ``stop()`` is the
        owner of the ``_ready`` flag in that case.
        """
        import time

        with self._state_lock:
            shutting_down = self._shutting_down
            running = self._running
            if shutting_down or not running:
                # Deliberate shutdown — leave _ready alone; stop() handles it.
                return
            # Unexpected EOF (subprocess crashed). Reset _ready now.
            self._ready = False

        # Capture exit code for logging.
        exit_code: int | None = None
        if self._process is not None:
            try:
                exit_code = self._process.poll()
            except Exception:
                logger.debug("Failed to poll tray subprocess for exit code", exc_info=True)

        # poll() returning None means the child is still alive — the reader
        # ended for another reason. Do NOT respawn, or we'd orphan a live child.
        if exit_code is None:
            logger.warning(
                "Tray subprocess reader ended but child still alive "
                "(poll()=None); not respawning to avoid orphaning it"
            )
            return

        # Sliding-window circuit breaker.
        now = time.monotonic()
        with self._state_lock:
            window_open = (now - self._last_respawn_time) <= self.RESPAWN_WINDOW
            if window_open and self._respawn_count >= self.MAX_RESPAWNS:
                self._tray_down = True
                logger.error(
                    "Tray subprocess crashed (exit_code=%s); circuit breaker "
                    "engaged after %d respawns within %.0fs — giving up",
                    exit_code,
                    self._respawn_count,
                    self.RESPAWN_WINDOW,
                )
                return
            if not window_open:
                # Window expired — reset counter.
                self._respawn_count = 0
            self._respawn_count += 1
            self._last_respawn_time = now
            # Clear stale process so start() will spawn a new one.
            self._process = None
            self._running = False

        logger.warning(
            "Tray subprocess exited (exit_code=%s); attempting respawn (%d/%d)",
            exit_code,
            self._respawn_count,
            self.MAX_RESPAWNS,
        )
        try:
            ok = self.start(respawn=True)
        except Exception:
            logger.exception("Tray subprocess respawn raised")
            ok = False
        if not ok:
            logger.error("Tray subprocess respawn failed (exit_code=%s)", exit_code)

    # Maximum nesting depth for JSON messages
    MAX_NESTING_DEPTH = 10

    def _validate_message_structure(self, obj: object, depth: int = 0) -> bool:
        """
        Validate that a JSON message has a safe structure.

        Checks for:
        - Excessive nesting depth (could cause stack overflow)
        - Valid message type (must be a dict with expected fields)

        Args:
            obj: The parsed JSON object to validate
            depth: Current nesting depth (for recursion)

        Returns:
            True if the structure is valid, False otherwise
        """
        # Check nesting depth
        if depth > self.MAX_NESTING_DEPTH:
            return False

        if isinstance(obj, dict):
            # Top-level message must have an "event" field
            if depth == 0 and "event" not in obj:
                return False

            # Recursively check nested structures
            for value in obj.values():
                if not self._validate_message_structure(value, depth + 1):
                    return False

        elif isinstance(obj, list):
            # Recursively check list items
            for item in obj:
                if not self._validate_message_structure(item, depth + 1):
                    return False

        # Primitive types (str, int, float, bool, None) are always valid

        return True

    def _read_stderr(self) -> None:
        """Read and log stderr from the subprocess."""
        try:
            if self._process is None or self._process.stderr is None:
                return

            for line in self._process.stderr:
                with self._state_lock:
                    if not self._running:
                        break
                line = line.strip()
                if line:
                    logger.debug(f"[TrayService] {line}")

        except Exception as e:
            logger.error(f"Error reading tray service stderr: {e}")

    def _handle_message(self, message: dict) -> None:
        """Handle a message from the tray service."""
        event = message.get("event")

        if event == "ready":
            with self._state_lock:
                self._ready = True
            logger.info("Tray service is ready")
            # Re-push cached state on the GTK main loop. Essential after a crash
            # respawn (the new subprocess starts from defaults, so the icon would
            # otherwise show the wrong badge and an empty profile submenu); a
            # harmless no-op on the initial ready. Marshalled via idle_add so it
            # does not race other main-thread _send_command writers.
            GLib.idle_add(self._resync_tray_state)

        elif event == "pong":
            logger.debug("Received pong from tray service")

        elif event == "error":
            error_msg = message.get("message", "Unknown error")
            logger.error(f"Tray service error: {error_msg}")

        elif event == "menu_action":
            action = message.get("action")
            self._handle_menu_action(action, message)

        else:
            logger.warning(f"Unknown event from tray service: {event}")

    def _handle_menu_action(self, action: str, message: dict) -> None:
        """Handle a menu action from the tray service."""
        logger.debug(f"Menu action: {action}")

        # Use GLib.idle_add to ensure callbacks run on GTK main thread
        if action == "quick_scan" and self._on_quick_scan:
            GLib.idle_add(self._on_quick_scan)
        elif action == "full_scan" and self._on_full_scan:
            GLib.idle_add(self._on_full_scan)
        elif action == "update" and self._on_update:
            GLib.idle_add(self._on_update)
        elif action == "quit" and self._on_quit:
            GLib.idle_add(self._on_quit)
        elif action == "toggle_window" and self._on_window_toggle:
            GLib.idle_add(self._on_window_toggle)
        elif action == "select_profile" and self._on_profile_select:
            profile_id = message.get("profile_id")
            if profile_id:
                with self._state_lock:
                    self._current_profile_id = profile_id
                GLib.idle_add(self._on_profile_select, profile_id)
            else:
                logger.warning("select_profile action missing profile_id")
        else:
            logger.warning(f"No handler for action: {action}")

    def _resync_tray_state(self) -> bool:
        """Re-push cached tray state to the (possibly just-respawned) subprocess.

        Runs on the GTK main loop. After a crash respawn the new subprocess starts
        from defaults (status "protected", empty submenu); without this the tray
        would misreport state until the next change. Idempotent on first ready.
        """
        with self._state_lock:
            status = self._current_status
            profiles = list(self._current_profiles)
            profile_id = self._current_profile_id
        self._send_command({"action": "update_status", "status": status})
        if profiles:
            self._send_command(
                {
                    "action": "update_profiles",
                    "profiles": profiles,
                    "current_profile_id": profile_id,
                }
            )
        return False  # GLib.idle_add: run once

    def _send_command(self, command: dict) -> bool:
        """Send a command to the tray service."""
        if self._process is None or self._process.stdin is None:
            return False

        try:
            message = json.dumps(command) + "\n"
            self._process.stdin.write(message)
            self._process.stdin.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to send command to tray service: {e}")
            return False

    def set_action_callbacks(
        self,
        on_quick_scan: Callable[[], None] | None = None,
        on_full_scan: Callable[[], None] | None = None,
        on_update: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        """
        Set callbacks for menu actions.

        Args:
            on_quick_scan: Callback for Quick Scan action
            on_full_scan: Callback for Full Scan action
            on_update: Callback for Update Definitions action
            on_quit: Callback for Quit action
        """
        self._on_quick_scan = on_quick_scan
        self._on_full_scan = on_full_scan
        self._on_update = on_update
        self._on_quit = on_quit
        logger.debug("Action callbacks configured")

    def set_window_toggle_callback(
        self,
        on_toggle: Callable[[], None],
        get_visible: Callable[[], bool] | None = None,
    ) -> None:
        """
        Set the callback for window show/hide toggle.

        Args:
            on_toggle: Callback to invoke when toggling window visibility
            get_visible: Callback to query current window visibility (optional)
        """
        self._on_window_toggle = on_toggle
        logger.debug("Window toggle callback configured")

    def set_profile_select_callback(self, on_select: Callable[[str], None]) -> None:
        """
        Set the callback for profile selection from tray menu.

        Args:
            on_select: Callback to invoke when a profile is selected.
                       Receives the profile_id as argument.
        """
        self._on_profile_select = on_select
        logger.debug("Profile select callback configured")

    def update_status(self, status: str) -> None:
        """
        Update the tray icon based on protection status.

        Args:
            status: One of 'protected', 'warning', 'scanning', 'threat'
        """
        with self._state_lock:
            self._current_status = status
        self._send_command({"action": "update_status", "status": status})

    def update_scan_progress(self, percentage: int) -> None:
        """
        Show scan progress percentage in the tray.

        Args:
            percentage: Progress percentage (0-100). Use 0 to clear.
        """
        self._send_command({"action": "update_progress", "percentage": percentage})

    def update_window_menu_label(self, visible: bool = True) -> None:
        """
        Update the Show/Hide Window menu item label.

        Args:
            visible: Whether the window is currently visible
        """
        self._send_command({"action": "update_window_visible", "visible": visible})

    def update_profiles(self, profiles: list[dict], current_profile_id: str | None = None) -> None:
        """
        Update the profiles list in the tray menu.

        Args:
            profiles: List of profile dictionaries with 'id', 'name', 'is_default' keys
            current_profile_id: ID of the currently selected profile (optional)
        """
        with self._state_lock:
            if current_profile_id is not None:
                self._current_profile_id = current_profile_id
            profile_id_to_send = self._current_profile_id
            self._current_profiles = list(profiles)
        self._send_command(
            {
                "action": "update_profiles",
                "profiles": profiles,
                "current_profile_id": profile_id_to_send,
            }
        )
        logger.debug(f"Updated tray profiles: {len(profiles)} profiles")

    def stop(self) -> None:
        """Stop the tray service subprocess."""
        with self._state_lock:
            # _shutting_down tells the stdout reader's exit handler not to
            # attempt a respawn for THIS process death.
            self._shutting_down = True
            self._running = False

        if self._process is not None:
            try:
                # Send quit command
                self._send_command({"action": "quit"})

                # Wait for graceful shutdown
                try:
                    self._process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    logger.warning("Tray service didn't stop gracefully, terminating")
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        logger.warning("Tray service didn't terminate, killing")
                        self._process.kill()

            except Exception as e:
                logger.error(f"Error stopping tray service: {e}")
            finally:
                # Explicitly close pipes to prevent ResourceWarning
                self._close_pipes()
                self._process = None

        with self._state_lock:
            self._ready = False
        logger.info("Tray manager stopped")

    def cleanup(self) -> None:
        """
        Clean up resources.

        Alias for stop() for API compatibility.
        """
        self.stop()

        # Clear callbacks
        self._on_quick_scan = None
        self._on_full_scan = None
        self._on_update = None
        self._on_quit = None
        self._on_window_toggle = None
        self._on_profile_select = None

    @property
    def is_active(self) -> bool:
        """Check if the tray service is running and ready."""
        with self._state_lock:
            return self._running and self._ready and self._process is not None

    @property
    def is_library_available(self) -> bool:
        """
        Check if the tray indicator is available.

        Always returns True for TrayManager since availability
        is determined by subprocess startup success.
        """
        with self._state_lock:
            return self._running and self._process is not None

    @property
    def current_status(self) -> str:
        """Get the current protection status."""
        with self._state_lock:
            return self._current_status


def is_available() -> bool:
    """
    Check if the tray service can be started.

    Returns:
        True (we always try subprocess approach)
    """
    return True


def get_unavailable_reason() -> str | None:
    """
    Get the reason why tray is unavailable.

    Returns:
        None (subprocess approach handles availability internally)
    """
    return None
