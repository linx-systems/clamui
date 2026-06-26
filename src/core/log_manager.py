# ClamUI Log Manager Module
"""
Log manager module for ClamUI providing log persistence and retrieval.
Stores scan/update operation logs and provides daemon log access.

Security: Input Sanitization for Log Injection Prevention
==========================================================

This module implements comprehensive input sanitization to prevent log injection
attacks and log obfuscation when storing file paths, threat names, and ClamAV
output in log entries.

Attack Vectors Mitigated
------------------------

1. **Control Characters**
   Threat: Malicious filenames containing control characters (e.g., \\x07 bell,
   \\x08 backspace, \\x0C form feed) could manipulate terminal output or confuse
   log viewing tools.
   Mitigation: All control characters except safe whitespace (space, tab) are
   removed from single-line fields. Multi-line fields preserve newlines/tabs but
   remove other control characters.

2. **ANSI Escape Sequences**
   Threat: ANSI escape codes (e.g., \\x1b[31m for red text, \\x1b[2J to clear
   screen) embedded in filenames could hide malicious content, modify displayed
   text, or obscure log entries when viewed in terminals.
   Mitigation: All ANSI escape sequences are detected and removed using a
   comprehensive regex pattern that matches CSI sequences (\\x1b[...m) and other
   escape codes.

3. **Unicode Bidirectional Overrides**
   Threat: Unicode bidirectional control characters (U+202A-U+202E, U+2066-U+2069)
   can reverse or modify the displayed order of text, allowing attackers to craft
   filenames that appear benign but actually reference malicious files. Example:
   "file\\u202Etxt.exe" displays as "fileexe.txt" but is actually an executable.
   Mitigation: All Unicode bidirectional override characters are removed from all
   log fields.

4. **Log Injection via Newlines**
   Threat: Crafted filenames containing newline characters (\\n or \\r) could
   inject fake log entries or split a single log entry across multiple lines,
   potentially forging scan results or hiding malicious activity. Example:
   "clean.txt\\nINFECTED: virus.exe\\nClean scan" could appear as three separate
   log lines.
   Mitigation: Newlines are converted to spaces in single-line fields (summary,
   path, threat names) to prevent entry injection. Multi-line fields (details,
   stdout) preserve legitimate newlines from ClamAV output.

5. **Null Byte Injection**
   Threat: Null bytes (\\x00) can truncate strings in some contexts or confuse
   parsers, potentially hiding parts of filenames or log content.
   Mitigation: All null bytes are removed from all fields before storage.

Sanitization Implementation
---------------------------

The module uses two sanitization functions from src/core/sanitize.py:

- **sanitize_log_line()**: For single-line fields (summary, path, threat names)
  Removes: control chars, ANSI escapes, Unicode bidi, null bytes, newlines
  Preserves: printable text, spaces, tabs

- **sanitize_log_text()**: For multi-line fields (details, stdout)
  Removes: control chars (except newlines/tabs), ANSI escapes, Unicode bidi, null bytes
  Preserves: printable text, spaces, tabs, newlines, carriage returns

Entry Points Sanitized
-----------------------

All LogEntry creation methods apply sanitization:

1. **LogEntry.create()** - Direct entry creation
   - Sanitizes: summary (line), details (text), path (line)

2. **LogEntry.from_scan_result_data()** - Scanner integration
   - Sanitizes: path, threat_details (file_path, threat_name), error_message,
     stdout, suffix
   - Used by: Scanner, DaemonScanner

3. **LogEntry.from_dict()** - JSON deserialization
   - Sanitizes: type, status, summary, details, path
   - Protection: Defense against tampering with stored log files

Defense in Depth
----------------

Sanitization is applied at multiple layers:

1. **Input Layer**: All user-controlled input from scan results is sanitized
   before building log entry fields (from_scan_result_data).

2. **Creation Layer**: All fields are sanitized again when creating LogEntry
   instances (create method).

3. **Deserialization Layer**: Fields are sanitized when reading from disk to
   protect against maliciously crafted or tampered log files (from_dict).

This multi-layer approach ensures that even if log files are manually edited or
replaced by an attacker, the malicious content cannot affect log viewers or
exploit downstream systems.

Example Attack Scenarios Prevented
-----------------------------------

1. **ANSI Obfuscation**:
   Malicious file: "/tmp/\\x1b[2Kharmless.txt\\x1b[31m[INFECTED]\\x1b[0m"
   Without sanitization: Clears line and shows fake infection marker in red
   With sanitization: "/tmp/harmless.txt[INFECTED]" (escape codes removed)

2. **Log Injection**:
   Malicious file: "safe.txt\\n[2024-01-15] INFECTED: virus.exe\\nClean scan"
   Without sanitization: Appears as three log entries, forging an infection
   With sanitization: "safe.txt [2024-01-15] INFECTED: virus.exe Clean scan"

3. **Unicode Direction Spoofing**:
   Malicious file: "document\\u202Efdp.exe" (displays as "documentexe.pdf")
   Without sanitization: Appears to be a PDF but is actually an executable
   With sanitization: "documentfdp.exe" (true extension visible)

Security Testing
----------------

The sanitization implementation has comprehensive test coverage:

- tests/core/test_sanitize.py: 80+ unit tests for sanitization functions
- tests/core/test_log_manager.py: Integration tests for LogEntry sanitization
- Coverage includes: control chars, ANSI escapes, Unicode bidi, null bytes,
  newlines, edge cases, real-world attack scenarios, ClamAV output formats

For implementation details, see: src/core/sanitize.py
"""

import contextlib
import csv
import io
import json
import logging
import os
import re
import secrets
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from gi.repository import GLib

from .sanitize import redact_sensitive_log_data, sanitize_log_line, sanitize_log_text
from .utils import get_clean_env, is_flatpak, which_host_command, wrap_host_command

logger = logging.getLogger(__name__)

# Regex patterns for extracting index fields from JSON without full parsing.
# These patterns match JSON key-value pairs in the format: "key": "value"
# They are designed to work with json.dump() output (indent=2).
_INDEX_FIELD_PATTERN = re.compile(r'"(id|timestamp|type)"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')

# Maximum bytes to read when extracting index fields.
# Log files store id, timestamp, type near the top. With indent=2 formatting:
# - Opening brace + newline: ~2 bytes
# - "id": "uuid" line: ~50 bytes (UUID is 36 chars)
# - "timestamp": "iso" line: ~45 bytes (ISO timestamp ~26 chars)
# - "type": "scan|update" line: ~25 bytes
# Total ~122 bytes minimum. Using 512 bytes provides safety margin for
# whitespace variations and ensures we capture all three fields.
_INDEX_EXTRACT_MAX_BYTES = 512

# Valid log entry id: UUIDs and any opaque token of word chars / dashes. Used to
# reject ids ingested from on-disk JSON or the index before they reach a
# filesystem path, preventing path traversal (e.g. "../../etc/passwd").
_VALID_LOG_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _sanitize_private_line(text: str | None) -> str:
    """Sanitize log-injection vectors and redact sensitive identifiers."""
    return redact_sensitive_log_data(sanitize_log_line(text))


def _sanitize_private_text(text: str | None) -> str:
    """Sanitize multi-line log text and redact sensitive identifiers."""
    return redact_sensitive_log_data(sanitize_log_text(text))


def _extract_first_int(pattern: str, text: str) -> int | None:
    """Extract the first integer captured by pattern from text."""
    match = re.search(pattern, text)
    if not match:
        return None

    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_detection_counts(text: str) -> tuple[int | None, int | None]:
    """Extract VirusTotal detection counts from existing summary/detail text."""
    match = re.search(r"Detections:\s*(\d+)\s*/\s*(\d+)", text)
    if match:
        try:
            return (int(match.group(1)), int(match.group(2)))
        except (TypeError, ValueError):
            return (None, None)

    match = re.search(r"(\d+)\s*/\s*(\d+)\s+engines", text)
    if match:
        try:
            return (int(match.group(1)), int(match.group(2)))
        except (TypeError, ValueError):
            return (None, None)

    return (None, None)


def _build_scan_summary(scan_status: str, infected_count: int = 0, suffix: str = "") -> str:
    """Build a privacy-safe summary for scan log entries."""
    suffix_text = f" {suffix}" if suffix else ""

    if scan_status == "clean":
        return f"Clean scan{suffix_text}"
    if scan_status == "infected":
        if infected_count > 0:
            return f"Found {infected_count} threat(s){suffix_text}"
        return f"Threats detected{suffix_text}"
    if scan_status == "cancelled":
        return f"Scan cancelled{suffix_text}"
    return f"Scan error{suffix_text}"


def _build_scan_details(
    scanned_files: int = 0,
    scanned_dirs: int = 0,
    infected_count: int = 0,
    threat_names: list[str] | None = None,
    error_message: str | None = None,
) -> str:
    """Build privacy-safe details for a scan log entry."""
    details_parts = []
    if scanned_files > 0 or scanned_dirs > 0:
        details_parts.append(f"Scanned: {scanned_files} files, {scanned_dirs} directories")
    if infected_count > 0:
        details_parts.append(f"Threats found: {infected_count}")
        for threat_name in threat_names or []:
            if threat_name:
                details_parts.append(f"  - {threat_name}")
    if error_message:
        details_parts.append(f"Error: {error_message}")
    return "\n".join(details_parts)


def _build_virustotal_summary(
    vt_status: str,
    detections: int = 0,
    total_engines: int = 0,
) -> str:
    """Build a privacy-safe summary for VirusTotal log entries."""
    if vt_status == "clean":
        return "VirusTotal: Clean scan"
    if vt_status == "detected":
        if detections > 0 and total_engines > 0:
            return f"VirusTotal: {detections}/{total_engines} engines detected threats"
        return "VirusTotal: Threats detected"
    if vt_status == "rate_limited":
        return "VirusTotal: Rate limit exceeded"
    if vt_status == "pending":
        return "VirusTotal: Analysis pending"
    if vt_status == "not_found":
        return "VirusTotal: File not previously analyzed"
    if vt_status == "file_too_large":
        return "VirusTotal: File too large for upload"
    return "VirusTotal: Scan error"


def _build_virustotal_details(
    detections: int = 0,
    total_engines: int = 0,
    detection_lines: list[str] | None = None,
    error_message: str | None = None,
) -> str:
    """Build privacy-safe details for a VirusTotal log entry."""
    details_parts = []

    if total_engines > 0:
        details_parts.append(f"Scanned by: {total_engines} engines")

    if detections > 0 or total_engines > 0:
        details_parts.append(f"Detections: {detections}/{total_engines}")
        for detection_line in detection_lines or []:
            if detection_line:
                details_parts.append(f"  - {detection_line}")

    if error_message:
        details_parts.append(f"Error: {error_message}")

    return "\n".join(details_parts)


def _sanitize_existing_scan_details(details: str) -> str:
    """Retain only privacy-safe scan detail lines from existing persisted logs."""
    preserved_lines: list[str] = []

    for line in _sanitize_private_text(details).splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("Scanned:"):
            preserved_lines.append(stripped)
            continue

        if stripped.startswith("Threats found:"):
            preserved_lines.append(stripped)
            continue

        if stripped.startswith("Error:"):
            error_text = stripped.split("Error:", 1)[1].strip()
            preserved_lines.append(f"Error: {_sanitize_private_line(error_text)}")
            continue

        if line.startswith("  - "):
            threat_text = line[4:].strip()
            if ": " in threat_text:
                threat_text = threat_text.rsplit(": ", 1)[-1]
            threat_text = _sanitize_private_line(threat_text)
            if threat_text:
                preserved_lines.append(f"  - {threat_text}")

    return "\n".join(preserved_lines)


def _sanitize_existing_virustotal_details(details: str) -> str:
    """Retain only privacy-safe VirusTotal detail lines from existing persisted logs."""
    preserved_lines: list[str] = []

    for line in _sanitize_private_text(details).splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith(("Scanned by:", "Detections:")):
            preserved_lines.append(stripped)
            continue

        if stripped.startswith("Error:"):
            error_text = stripped.split("Error:", 1)[1].strip()
            preserved_lines.append(f"Error: {_sanitize_private_line(error_text)}")
            continue

        if line.startswith("  - "):
            detection_line = _sanitize_private_line(line[4:].strip())
            if detection_line:
                preserved_lines.append(f"  - {detection_line}")

    return "\n".join(preserved_lines)


def _sanitize_persisted_log_data(data: dict) -> dict:
    """Redact stored log JSON data in-place-safe form for migration."""
    sanitized = dict(data)
    log_type = _sanitize_private_line(data.get("type", "unknown"))
    status = _sanitize_private_line(data.get("status", "unknown"))
    raw_summary = data.get("summary", "")
    raw_details = data.get("details", "")

    sanitized["type"] = log_type
    sanitized["status"] = status
    sanitized["path"] = None

    sanitized["summary"] = _sanitize_private_line(raw_summary)
    sanitized["details"] = _sanitize_private_text(raw_details)
    return sanitized


def _extract_index_fields(file_path: Path) -> dict[str, str] | None:
    """
    Extract index fields (id, timestamp, type) from a log file without full JSON parsing.

    This function reads only the first portion of the log file and uses regex
    to extract the required fields, avoiding the overhead of parsing the entire
    JSON structure including potentially large 'details' and 'summary' fields.

    Args:
        file_path: Path to the JSON log file

    Returns:
        Dict with 'id', 'timestamp', 'type' keys if all found, None otherwise
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            # Read only the beginning of the file where index fields are located
            content = f.read(_INDEX_EXTRACT_MAX_BYTES)

        # Extract all matching fields
        matches = _INDEX_FIELD_PATTERN.findall(content)
        if not matches:
            return None

        # Build result dict from matches
        result = {}
        for key, value in matches:
            # Decode JSON escape sequences (e.g., \n, \", \\)
            try:
                result[key] = json.loads(f'"{value}"')
            except json.JSONDecodeError:
                result[key] = value

        # Return only if all required fields are present
        if "id" in result and "timestamp" in result and "type" in result:
            return result

        return None
    except (OSError, UnicodeDecodeError):
        return None


class LogType(Enum):
    """Type of log entry."""

    SCAN = "scan"
    UPDATE = "update"
    VIRUSTOTAL = "virustotal"


class DaemonStatus(Enum):
    """Status of the clamd daemon."""

    RUNNING = "running"
    STOPPED = "stopped"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


@dataclass
class LogEntry:
    """A single log entry for a scan or update operation."""

    id: str
    timestamp: str  # ISO format string for JSON serialization
    type: str  # "scan" or "update"
    status: str  # e.g., "clean", "infected", "success", "error"
    summary: str
    details: str
    path: str | None = None  # Scanned path (for scans)
    duration: float = 0.0  # Operation duration in seconds
    scheduled: bool = False  # Whether this was a scheduled automatic scan

    @classmethod
    def create(
        cls,
        log_type: str,
        status: str,
        summary: str,
        details: str,
        path: str | None = None,
        duration: float = 0.0,
        scheduled: bool = False,
    ) -> "LogEntry":
        """
        Create a new LogEntry with auto-generated id and timestamp.

        Args:
            log_type: Type of operation ("scan" or "update")
            status: Status of the operation
            summary: Brief description of the operation
            details: Full output/details
            path: Scanned path (for scan operations)
            duration: Operation duration in seconds
            scheduled: Whether this was a scheduled automatic scan

        Returns:
            New LogEntry instance
        """
        if path:
            # Paths are intentionally discarded from persisted logs, but we still
            # sanitize the input to keep the privacy boundary explicit.
            _sanitize_private_line(path)

        return cls(
            id=str(uuid.uuid4()),
            timestamp=datetime.now().isoformat(),
            type=log_type,
            status=status,
            summary=_sanitize_private_line(summary),
            details=_sanitize_private_text(details),
            path=None,
            duration=duration,
            scheduled=scheduled,
        )

    def to_dict(self) -> dict:
        """Convert LogEntry to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LogEntry":
        """
        Create LogEntry from dictionary.

        Sanitizes fields when deserializing from JSON to protect against
        tampering with stored log files or reading maliciously crafted log entries.
        """
        # Extract and sanitize fields
        # Timestamps are system-controlled, don't need sanitization.
        # The id flows into a filesystem path on read/delete, so reject ids that
        # don't match the strict pattern and regenerate a safe one (prevents path
        # traversal from tampered/crafted log files, e.g. "../../etc/passwd").
        raw_id = data.get("id")
        log_id = (
            raw_id
            if isinstance(raw_id, str) and _VALID_LOG_ID_PATTERN.match(raw_id)
            else str(uuid.uuid4())
        )
        # Type and status should be controlled enums but sanitize for defense in depth
        raw_summary = data.get("summary", "")
        raw_details = data.get("details", "")
        raw_status = data.get("status", "unknown")
        raw_type = data.get("type", "unknown")
        raw_path = data.get("path")
        # duration is annotated float; coerce defensively so a tampered/corrupt
        # stored log with a null or non-numeric duration cannot crash downstream
        # arithmetic (statistics aggregation) or comparisons (CSV export).
        raw_duration = data.get("duration", 0.0)
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            duration = 0.0

        return cls(
            id=log_id,
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            type=_sanitize_private_line(raw_type),
            status=_sanitize_private_line(raw_status),
            summary=_sanitize_private_line(raw_summary),
            details=_sanitize_private_text(raw_details),
            path=sanitize_log_line(raw_path) if raw_path else None,
            duration=duration,
            scheduled=data.get("scheduled", False),
        )

    @classmethod
    def from_scan_result_data(
        cls,
        scan_status: str,
        path: str,
        duration: float,
        scanned_files: int = 0,
        scanned_dirs: int = 0,
        infected_count: int = 0,
        threat_details: list | None = None,
        error_message: str | None = None,
        stdout: str = "",
        suffix: str = "",
        scheduled: bool = False,
    ) -> "LogEntry":
        """
        Create a LogEntry from scan result data.

        This factory method handles the common logic for creating log entries
        from scan results, used by both Scanner and DaemonScanner.

        Args:
            scan_status: Status of the scan ("clean", "infected", "cancelled", "error")
            path: The path that was scanned
            duration: Scan duration in seconds
            scanned_files: Number of files scanned
            scanned_dirs: Number of directories scanned
            infected_count: Number of infections found
            threat_details: List of threat details (dicts with file_path, threat_name)
            error_message: Error message if status is error
            stdout: Raw stdout from scan command
            suffix: Optional suffix for summary (e.g., "(daemon)")
            scheduled: Whether this was a scheduled scan

        Returns:
            New LogEntry instance
        """
        threat_details = threat_details or []
        if path:
            _sanitize_private_line(path)
        if stdout:
            _sanitize_private_text(stdout)

        sanitized_suffix = _sanitize_private_line(suffix) if suffix else ""
        sanitized_error_message = _sanitize_private_line(error_message) if error_message else None

        if scan_status == "clean":
            status = "clean"
        elif scan_status == "infected":
            status = "infected"
        elif scan_status == "cancelled":
            status = "cancelled"
        else:
            status = "error"

        summary = _build_scan_summary(
            status,
            infected_count=infected_count,
            suffix=sanitized_suffix,
        )
        threat_names = [
            _sanitize_private_line(threat.get("threat_name", threat.get("name", "unknown")))
            for threat in threat_details
        ]
        details = _build_scan_details(
            scanned_files=scanned_files,
            scanned_dirs=scanned_dirs,
            infected_count=infected_count,
            threat_names=threat_names,
            error_message=sanitized_error_message,
        )

        return cls.create(
            log_type="scan",
            status=status,
            summary=summary,
            details=details,
            path=None,
            duration=duration,
            scheduled=scheduled,
        )

    @classmethod
    def from_virustotal_result_data(
        cls,
        vt_status: str,
        file_path: str,
        duration: float,
        sha256: str,
        detections: int = 0,
        total_engines: int = 0,
        detection_details: list | None = None,
        permalink: str | None = None,
        error_message: str | None = None,
    ) -> "LogEntry":
        """
        Create a LogEntry from VirusTotal scan result data.

        This factory method handles the common logic for creating log entries
        from VirusTotal scan results.

        Args:
            vt_status: Status of the scan ("clean", "detected", "error",
                       "rate_limited", "pending", "not_found", "file_too_large")
            file_path: The path to the scanned file
            duration: Scan duration in seconds
            sha256: SHA256 hash of the file
            detections: Number of engines that detected threats
            total_engines: Total number of engines that analyzed the file
            detection_details: List of detection dicts with engine_name, category, result
            permalink: URL to the VirusTotal report
            error_message: Error message if status is error

        Returns:
            New LogEntry instance
        """
        detection_details = detection_details or []
        if file_path:
            _sanitize_private_line(file_path)
        if sha256:
            _sanitize_private_line(sha256)
        if permalink:
            _sanitize_private_line(permalink)

        sanitized_error_message = _sanitize_private_line(error_message) if error_message else None

        if vt_status == "clean":
            status = "clean"
        elif vt_status == "detected":
            status = "infected"
        elif vt_status == "rate_limited":
            status = "error"
        elif vt_status == "pending":
            status = "pending"
        elif vt_status == "not_found":
            status = "unknown"
        elif vt_status == "file_too_large":
            status = "error"
        else:
            status = "error"

        summary = _build_virustotal_summary(
            vt_status,
            detections=detections,
            total_engines=total_engines,
        )
        detection_lines = []
        for detection in detection_details:
            engine = _sanitize_private_line(detection.get("engine_name", "unknown"))
            result = _sanitize_private_line(detection.get("result", "unknown"))
            category = _sanitize_private_line(detection.get("category", "unknown"))
            detection_lines.append(f"{engine} ({category}): {result}")

        details = _build_virustotal_details(
            detections=detections,
            total_engines=total_engines,
            detection_lines=detection_lines,
            error_message=sanitized_error_message,
        )

        return cls.create(
            log_type="virustotal",
            status=status,
            summary=summary,
            details=details,
            path=None,
            duration=duration,
            scheduled=False,
        )


# Common locations for clamd log files
CLAMD_LOG_PATHS = [
    "/var/log/clamav/clamd.log",
    "/var/log/clamd.log",
]

# Index file for optimized log retrieval
INDEX_FILENAME = "log_index.json"
LOG_PRIVACY_VERSION = 1
LOG_PRIVACY_STATE_FILENAME = ".log-privacy-version"


@dataclass(frozen=True)
class LogPrivacyMigrationStatus:
    """Shared progress snapshot for persisted log privacy migration."""

    is_running: bool
    processed_files: int = 0
    total_files: int = 0


@dataclass
class _LogPrivacyMigrationTracker:
    """Process-local tracker for one log directory's privacy migration."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    done_event: threading.Event = field(default_factory=threading.Event)
    running: bool = False
    processed_files: int = 0
    total_files: int = 0
    thread: threading.Thread | None = None

    def __post_init__(self) -> None:
        self.done_event.set()


class LogManager:
    """
    Manager for log persistence and retrieval.

    Provides methods for saving scan/update logs, retrieving historical logs,
    and accessing clamd daemon logs.

    Index Schema:
        The log index file (log_index.json) contains metadata for fast log retrieval:
        {
            "version": 1,
            "entries": [
                {"id": "uuid-string", "timestamp": "ISO-8601-string", "type": "scan|update"},
                ...
            ]
        }
    """

    _privacy_tracker_lock = threading.Lock()
    _privacy_trackers: dict[str, _LogPrivacyMigrationTracker] = {}

    def __init__(self, log_dir: str | None = None):
        """
        Initialize the LogManager.

        Args:
            log_dir: Optional custom log directory. Defaults to XDG_DATA_HOME/clamui/logs
        """
        if log_dir:
            self._log_dir = Path(log_dir)
        else:
            xdg_data_home = os.environ.get("XDG_DATA_HOME", "~/.local/share")
            self._log_dir = Path(xdg_data_home).expanduser() / "clamui" / "logs"

        # Thread lock for safe concurrent access
        self._lock = threading.Lock()

        # Flag to track if migration check has been performed
        self._migration_checked = False
        self._privacy_migration_checked = False

        # Ensure log directory exists
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Ensure the log directory exists."""
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            logger.warning("Failed to create log directory %s: %s", self._log_dir, e)

    @property
    def _privacy_state_path(self) -> Path:
        """Get the state file used to track persisted-log privacy migration."""
        return self._log_dir / LOG_PRIVACY_STATE_FILENAME

    def _read_privacy_state_version_unlocked(self) -> int:
        """Read the completed persisted-log privacy migration version from disk."""
        try:
            return int(self._privacy_state_path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            return 0

    def _has_completed_privacy_migration_unlocked(self) -> bool:
        """Return True when persisted logs have already been privacy-migrated."""
        return self._read_privacy_state_version_unlocked() >= LOG_PRIVACY_VERSION

    def _mark_privacy_migration_complete_unlocked(self) -> None:
        """Persist the current privacy migration version for stored logs."""
        self._ensure_log_dir()

        fd, temp_path = tempfile.mkstemp(prefix="log_privacy_", dir=self._log_dir)
        try:
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
            except Exception:
                with contextlib.suppress(OSError):
                    os.close(fd)
                raise

            with f:
                f.write(str(LOG_PRIVACY_VERSION))

            Path(temp_path).replace(self._privacy_state_path)
            self._privacy_state_path.chmod(0o600)
        except Exception:
            with contextlib.suppress(OSError):
                Path(temp_path).unlink(missing_ok=True)

    def _clear_privacy_migration_state_unlocked(self) -> None:
        """Delete the persisted-log privacy migration state marker."""
        with contextlib.suppress(OSError):
            self._privacy_state_path.unlink()

    def _collect_privacy_migration_targets_unlocked(self) -> list[Path]:
        """Collect persisted log files that need one-time privacy migration."""
        if not self._log_dir.exists():
            return []

        return sorted(
            log_file for log_file in self._log_dir.glob("*.json") if log_file.name != INDEX_FILENAME
        )

    @classmethod
    def _get_privacy_tracker_for_log_dir(cls, log_dir: Path) -> _LogPrivacyMigrationTracker:
        """Return the shared privacy migration tracker for a log directory."""
        tracker_key = str(log_dir.expanduser().resolve(strict=False))

        with cls._privacy_tracker_lock:
            tracker = cls._privacy_trackers.get(tracker_key)
            if tracker is None:
                tracker = _LogPrivacyMigrationTracker()
                cls._privacy_trackers[tracker_key] = tracker
            return tracker

    def _get_privacy_tracker(self) -> _LogPrivacyMigrationTracker:
        """Return the shared privacy migration tracker for this manager's log directory."""
        return self._get_privacy_tracker_for_log_dir(self._log_dir)

    @property
    def _index_path(self) -> Path:
        """
        Get the path to the log index file.

        Returns:
            Path object pointing to log_index.json in the log directory
        """
        return self._log_dir / INDEX_FILENAME

    def _load_index(self) -> dict:
        """
        Load the log index from file.

        Returns a dictionary with 'version' and 'entries' keys. If the file doesn't
        exist or is corrupted, returns an empty structure with version 1 and empty entries list.

        Returns:
            Dictionary with structure: {"version": 1, "entries": [...]}
        """
        try:
            if self._index_path.exists():
                with open(self._index_path, encoding="utf-8") as f:
                    data = json.load(f)
                    # Validate structure has required keys
                    if isinstance(data, dict) and "version" in data and "entries" in data:
                        return data
            # File doesn't exist or invalid structure - return empty index
            return {"version": 1, "entries": []}
        except (OSError, json.JSONDecodeError, PermissionError) as e:
            logger.debug("Failed to load log index: %s", e)
            return {"version": 1, "entries": []}

    def _save_index(self, index_data: dict) -> bool:
        """
        Atomically save the log index to file.

        Uses a temporary file and rename pattern to prevent corruption
        during write operations (crash safety).

        Args:
            index_data: Dictionary with structure {"version": 1, "entries": [...]}

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Ensure parent directory exists
            self._log_dir.mkdir(parents=True, exist_ok=True)

            # Atomic write using temp file + rename
            fd, temp_path = tempfile.mkstemp(
                suffix=".json",
                prefix="log_index_",
                dir=self._log_dir,
            )
            try:
                try:
                    f = os.fdopen(fd, "w", encoding="utf-8")
                except Exception:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                    raise

                with f:
                    json.dump(index_data, f, indent=2)

                # Atomic rename
                temp_path_obj = Path(temp_path)
                temp_path_obj.replace(self._index_path)
                return True
            except Exception as e:
                # Clean up temp file on failure
                logger.debug("Failed to save index, cleaning up temp file: %s", e)
                with contextlib.suppress(OSError):
                    Path(temp_path).unlink(missing_ok=True)
                raise

        except Exception as e:
            logger.warning("Failed to save log index: %s", e)
            return False

    def _validate_index(self, index_data: dict) -> bool:
        """
        Validate that the index is not stale or invalid.

        Checks for:
        - Entry count mismatch (index entries vs actual log files)
        - Missing referenced files (>20% of indexed files don't exist)

        Args:
            index_data: The loaded index data

        Returns:
            True if index is valid, False if it needs to be rebuilt
        """
        try:
            if not self._log_dir.exists():
                # No log directory means index should be empty
                return len(index_data.get("entries", [])) == 0

            # Single glob() call, convert to set of stems for O(1) membership testing
            # This avoids multiple filesystem syscalls for individual exists() checks
            actual_file_stems = {
                f.stem for f in self._log_dir.glob("*.json") if f.name != INDEX_FILENAME
            }
            actual_count = len(actual_file_stems)

            # Get index entry count
            index_entries = index_data.get("entries", [])
            index_count = len(index_entries)

            # If counts don't match, index is stale
            if index_count != actual_count:
                return False

            # Check for missing referenced files (sample check to avoid excessive I/O)
            # If we have many entries, check a sample; otherwise check all
            entries_to_check = index_entries
            if len(index_entries) > 50:
                # Sample 50 entries for large indices. Use a CSPRNG so an
                # attacker cannot predict which entries are verified.
                entries_to_check = secrets.SystemRandom().sample(index_entries, 50)

            # Use set membership for O(1) lookup instead of exists() syscalls
            missing_count = sum(
                1 for entry in entries_to_check if entry.get("id") not in actual_file_stems
            )

            # Calculate missing percentage
            checked_count = len(entries_to_check)
            if checked_count > 0:
                missing_percentage = (missing_count / checked_count) * 100
                # If >20% of files are missing, index is stale
                if missing_percentage > 20:
                    return False

            return True

        except Exception as e:
            logger.debug("Index validation error, treating as invalid: %s", e)
            return False

    def _rebuild_index_unlocked(self) -> dict:
        """
        Rebuild the log index without acquiring lock.

        Internal method for use by callers that already hold the lock.
        Scans all log files and builds index data structure.

        Uses optimized partial file reading with regex extraction to avoid
        parsing entire JSON files. Falls back to full JSON parsing if the
        optimized extraction fails (e.g., for non-standard file formats).

        Returns:
            Index data dict with "version" and "entries" keys
        """
        entries = []

        # Ensure log directory exists
        if not self._log_dir.exists():
            return {"version": 1, "entries": []}

        # Scan all JSON log files (exclude the index file itself)
        for log_file in self._log_dir.glob("*.json"):
            # Skip the index file
            if log_file.name == INDEX_FILENAME:
                continue

            # Try optimized extraction first (reads only first 512 bytes)
            fields = _extract_index_fields(log_file)
            if fields:
                entries.append(
                    {
                        "id": fields["id"],
                        "timestamp": fields["timestamp"],
                        "type": fields["type"],
                    }
                )
                continue

            # Fall back to full JSON parsing for non-standard files
            try:
                with open(log_file, encoding="utf-8") as f:
                    data = json.load(f)

                    # Extract only the required fields
                    log_id = data.get("id")
                    timestamp = data.get("timestamp")
                    log_type = data.get("type")

                    # Only add if all required fields are present
                    if log_id and timestamp and log_type:
                        entries.append({"id": log_id, "timestamp": timestamp, "type": log_type})
            except (OSError, json.JSONDecodeError):
                # Skip corrupted or unreadable files
                continue

        return {"version": 1, "entries": entries}

    def rebuild_index(self) -> bool:
        """
        Rebuild the log index from scratch by scanning all log files.

        Used for migration from non-indexed state and recovery from index corruption.
        Reads only id, timestamp, and type from each log file (minimal parsing).

        Returns:
            True if rebuilt successfully, False otherwise
        """
        with self._lock:
            try:
                index_data = self._rebuild_index_unlocked()
                return self._save_index(index_data)
            except Exception as e:
                logger.warning("Failed to rebuild log index: %s", e)
                return False

    def _write_log_file_unlocked(self, log_file: Path, data: dict) -> None:
        """Atomically write a JSON log file without acquiring the manager lock."""
        fd, temp_path = tempfile.mkstemp(
            suffix=".json",
            prefix="log_entry_",
            dir=self._log_dir,
        )
        try:
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
            except Exception:
                with contextlib.suppress(OSError):
                    os.close(fd)
                raise

            with f:
                json.dump(data, f, indent=2)

            Path(temp_path).replace(log_file)
            log_file.chmod(0o600)
        except Exception:
            with contextlib.suppress(OSError):
                Path(temp_path).unlink(missing_ok=True)
            raise

    def _execute_privacy_migration_targets(
        self, tracker: _LogPrivacyMigrationTracker, targets: list[Path]
    ) -> None:
        """Rewrite legacy persisted logs so only privacy-safe data remains on disk."""
        try:
            for log_file in targets:
                try:
                    with open(log_file, encoding="utf-8") as f:
                        data = json.load(f)

                    required_fields = ("id", "timestamp", "type")
                    if any(not data.get(field) for field in required_fields):
                        continue

                    sanitized = _sanitize_persisted_log_data(data)
                    if sanitized != data:
                        self._write_log_file_unlocked(log_file, sanitized)
                except (OSError, json.JSONDecodeError) as e:
                    logger.debug("Privacy migration skipped for %s: %s", log_file.name, e)
                finally:
                    with tracker.lock:
                        tracker.processed_files += 1

            self._mark_privacy_migration_complete_unlocked()
            self._privacy_migration_checked = True
        finally:
            migration_complete = self._has_completed_privacy_migration_unlocked()
            with tracker.lock:
                if migration_complete:
                    tracker.processed_files = tracker.total_files
                tracker.running = False
                tracker.done_event.set()

    def start_privacy_migration_async(self) -> bool:
        """
        Start the one-time persisted-log privacy migration in a background thread.

        Returns:
            True when migration is running after this call, False otherwise.
        """
        if self._privacy_migration_checked or self._has_completed_privacy_migration_unlocked():
            self._privacy_migration_checked = True
            return False

        targets = self._collect_privacy_migration_targets_unlocked()
        if not targets:
            self._mark_privacy_migration_complete_unlocked()
            self._privacy_migration_checked = True
            return False

        tracker = self._get_privacy_tracker()
        with tracker.lock:
            if tracker.running:
                return True

            tracker.running = True
            tracker.processed_files = 0
            tracker.total_files = len(targets)
            tracker.done_event.clear()

            thread = threading.Thread(
                target=self._execute_privacy_migration_targets,
                args=(tracker, targets),
                name="clamui-log-privacy-migration",
                daemon=True,
            )
            tracker.thread = thread

        thread.start()
        return True

    def get_privacy_migration_status(self) -> LogPrivacyMigrationStatus:
        """Return a process-local snapshot of persisted-log privacy migration progress."""
        tracker = self._get_privacy_tracker()

        with tracker.lock:
            if tracker.running:
                return LogPrivacyMigrationStatus(
                    is_running=True,
                    processed_files=tracker.processed_files,
                    total_files=tracker.total_files,
                )

            processed_files = tracker.processed_files
            total_files = tracker.total_files

        if self._has_completed_privacy_migration_unlocked():
            self._privacy_migration_checked = True
            processed_files = total_files

        return LogPrivacyMigrationStatus(
            is_running=False,
            processed_files=processed_files,
            total_files=total_files,
        )

    def wait_for_privacy_migration(self, timeout: float | None = None) -> bool:
        """
        Wait for any in-flight persisted-log privacy migration to finish.

        Returns:
            True when migration completed successfully, False on timeout or failure.
        """
        if self._has_completed_privacy_migration_unlocked():
            self._privacy_migration_checked = True
            return True

        tracker = self._get_privacy_tracker()
        with tracker.lock:
            if not tracker.running:
                return False
            done_event = tracker.done_event

        if not done_event.wait(timeout):
            return False

        migration_complete = self._has_completed_privacy_migration_unlocked()
        if migration_complete:
            self._privacy_migration_checked = True
        return migration_complete

    def _reset_privacy_migration_tracker_unlocked(self) -> None:
        """Reset in-memory privacy migration progress after log storage is cleared."""
        tracker = self._get_privacy_tracker()
        with tracker.lock:
            tracker.running = False
            tracker.processed_files = 0
            tracker.total_files = 0
            tracker.thread = None
            tracker.done_event.set()

    def _check_and_run_privacy_migration_unlocked(self, *, wait: bool = True) -> None:
        """Ensure legacy persisted logs are privacy-migrated before reading them."""
        if self._privacy_migration_checked:
            return

        if self._has_completed_privacy_migration_unlocked():
            self._privacy_migration_checked = True
            return

        if not wait:
            self.start_privacy_migration_async()
            return

        tracker = self._get_privacy_tracker()
        with tracker.lock:
            if tracker.running:
                done_event = tracker.done_event
                targets: list[Path] | None = None
            else:
                targets = self._collect_privacy_migration_targets_unlocked()
                if not targets:
                    self._mark_privacy_migration_complete_unlocked()
                    self._privacy_migration_checked = True
                    return

                tracker.running = True
                tracker.processed_files = 0
                tracker.total_files = len(targets)
                tracker.done_event.clear()
                done_event = None

        if done_event is not None:
            done_event.wait()
            if self._has_completed_privacy_migration_unlocked():
                self._privacy_migration_checked = True
            return

        self._execute_privacy_migration_targets(tracker, targets or [])

    def save_log(self, entry: LogEntry) -> bool:
        """
        Save a log entry to storage and update the index.

        Args:
            entry: The LogEntry to save

        Returns:
            True if saved successfully, False otherwise
        """
        with self._lock:
            try:
                self._ensure_log_dir()
                self._check_and_run_privacy_migration_unlocked(wait=False)
                log_file = self._log_dir / f"{entry.id}.json"
                self._write_log_file_unlocked(log_file, entry.to_dict())

                # Update index with new entry metadata (best-effort)
                try:
                    index_data = self._load_index()
                    index_data["entries"].append(
                        {
                            "id": entry.id,
                            "timestamp": entry.timestamp,
                            "type": entry.type,
                        }
                    )
                    self._save_index(index_data)
                except Exception as e:
                    # Index update failed, but log file was saved successfully
                    # Index can be rebuilt later if needed
                    logger.debug("Index update failed after saving log: %s", e)

                return True
            except (OSError, PermissionError, json.JSONDecodeError) as e:
                logger.warning("Failed to save log entry %s: %s", entry.id, e)
                return False

    def _check_and_run_migration_unlocked(self) -> None:
        """
        Check and perform index migration on first access (without lock).

        Internal method for use by callers that already hold the lock.
        If no index exists but log files do, rebuilds the index to migrate
        existing installations to the indexed retrieval system.
        """
        if self._migration_checked:
            return

        self._migration_checked = True

        # Check if index exists
        if self._index_path.exists():
            return

        # Check if any log files exist - if so, rebuild index
        try:
            if self._log_dir.exists():
                log_files = [f for f in self._log_dir.glob("*.json") if f.name != INDEX_FILENAME]
                if log_files:
                    # Rebuild index using shared unlocked method
                    index_data = self._rebuild_index_unlocked()
                    self._save_index(index_data)
        except Exception as e:
            # If migration fails, continue normally - will fall back to full scan
            logger.debug("Index migration failed: %s", e)

    def _get_valid_index_unlocked(self) -> dict:
        """
        Load and validate the index, rebuilding if necessary (without lock).

        Internal method for use by callers that already hold the lock.
        Returns a valid index data structure, or an empty one if loading/validation fails.

        Returns:
            Dictionary with structure: {"version": 1, "entries": [...]}
        """
        # Try to load index
        try:
            index_data = self._load_index()
        except Exception as e:
            logger.debug("Index loading failed: %s", e)
            return {"version": 1, "entries": []}

        # If index is empty, return as-is
        if not index_data.get("entries"):
            return index_data

        # Validate index
        try:
            valid = self._validate_index(index_data)
        except Exception as e:
            logger.debug("Index validation raised exception: %s", e)
            valid = False

        if not valid:
            # Index is stale/invalid - rebuild
            try:
                index_data = self._rebuild_index_unlocked()
                self._save_index(index_data)
            except Exception as e:
                logger.debug("Index rebuild in get_logs failed: %s", e)
                return {"version": 1, "entries": []}

        return index_data

    def _filter_and_sort_index_entries(
        self, entries: list[dict], log_type: str | None, limit: int
    ) -> list[dict]:
        """
        Filter, sort, and limit index entries.

        Args:
            entries: List of index entry dicts with 'id', 'timestamp', 'type' keys
            log_type: Optional filter by type ("scan" or "update")
            limit: Maximum number of entries to return

        Returns:
            Filtered, sorted, and limited list of index entries
        """
        # Filter by type if specified
        if log_type is not None:
            entries = [entry for entry in entries if entry.get("type") == log_type]

        # Sort by timestamp descending (newest first)
        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        # Apply limit
        return entries[:limit]

    def _safe_log_file(self, log_id: str | None) -> Path | None:
        """
        Resolve <log_id>.json inside the log directory, rejecting traversal.

        Returns None when the id is missing, fails the strict id pattern, or the
        constructed path would escape the log directory (defense-in-depth against
        a tampered id reaching open()/unlink()).
        """
        if not log_id or not _VALID_LOG_ID_PATTERN.match(log_id):
            return None
        log_file = self._log_dir / f"{log_id}.json"
        try:
            if not log_file.resolve().is_relative_to(self._log_dir.resolve()):
                return None
        except OSError:
            return None
        return log_file

    def _load_log_entries_by_ids(self, index_entries: list[dict]) -> list[LogEntry]:
        """
        Load LogEntry objects for the given index entries.

        Args:
            index_entries: List of index entry dicts with 'id' keys

        Returns:
            List of LogEntry objects (skips corrupted/missing files)
        """
        entries = []
        for index_entry in index_entries:
            log_id = index_entry.get("id")
            if not log_id:
                continue
            try:
                log_file = self._safe_log_file(log_id)
                if log_file is not None and log_file.exists():
                    with open(log_file, encoding="utf-8") as f:
                        data = json.load(f)
                        entries.append(LogEntry.from_dict(data))
            except (OSError, json.JSONDecodeError):
                # Skip corrupted or missing files
                continue
        return entries

    def _retrieve_logs_from_index(
        self, index_data: dict, log_type: str | None, limit: int
    ) -> list[LogEntry] | None:
        """
        Retrieve logs using index-based approach.

        Args:
            index_data: Valid index data structure
            log_type: Optional filter by type ("scan" or "update")
            limit: Maximum number of entries to return

        Returns:
            List of LogEntry objects, or None if retrieval fails
        """
        if not index_data.get("entries"):
            return None

        try:
            filtered_entries = self._filter_and_sort_index_entries(
                index_data["entries"], log_type, limit
            )
            return self._load_log_entries_by_ids(filtered_entries)
        except Exception as e:
            logger.debug("Index-based retrieval failed, falling back: %s", e)
            return None

    def _retrieve_logs_full_scan(self, log_type: str | None, limit: int) -> list[LogEntry]:
        """
        Retrieve logs using full directory scan (fallback method).

        Scans all log files in the directory, applies filtering and sorting.

        Args:
            log_type: Optional filter by type ("scan" or "update")
            limit: Maximum number of entries to return

        Returns:
            List of LogEntry objects
        """
        entries = []
        try:
            if not self._log_dir.exists():
                return entries

            for log_file in self._log_dir.glob("*.json"):
                # Skip the index file
                if log_file.name == INDEX_FILENAME:
                    continue

                try:
                    with open(log_file, encoding="utf-8") as f:
                        data = json.load(f)
                        entry = LogEntry.from_dict(data)

                        # Apply type filter if specified
                        if log_type is None or entry.type == log_type:
                            entries.append(entry)
                except (OSError, json.JSONDecodeError):
                    # Skip corrupted files
                    continue

        except OSError:
            return entries

        # Sort by timestamp (newest first) and apply limit
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def get_logs(self, limit: int = 100, log_type: str | None = None) -> list[LogEntry]:
        """
        Retrieve stored log entries, sorted by timestamp (newest first).

        Uses an index file for optimized retrieval. Validates the index and
        triggers automatic rebuild if stale/invalid. Falls back to full directory
        scan if the index is missing or corrupted.

        On first access, automatically rebuilds the index if logs exist but no
        index is present (migration for existing installations).

        Args:
            limit: Maximum number of entries to return
            log_type: Optional filter by type ("scan" or "update")

        Returns:
            List of LogEntry objects
        """
        with self._lock:
            self._check_and_run_privacy_migration_unlocked()
            # Perform auto-migration check on first access
            self._check_and_run_migration_unlocked()

            # Get valid index (loads, validates, rebuilds if needed)
            index_data = self._get_valid_index_unlocked()

            # Try index-based retrieval first
            entries = self._retrieve_logs_from_index(index_data, log_type, limit)
            if entries is not None:
                return entries

            # Fallback: full directory scan
            return self._retrieve_logs_full_scan(log_type, limit)

    def get_logs_async(
        self,
        callback: Callable[[list["LogEntry"]], None],
        limit: int = 100,
        log_type: str | None = None,
    ) -> None:
        """
        Retrieve stored log entries asynchronously.

        The log retrieval runs in a background thread and the callback is invoked
        on the main GTK thread via GLib.idle_add when complete.

        Args:
            callback: Function to call with list of LogEntry objects when loading completes
            limit: Maximum number of entries to return
            log_type: Optional filter by type ("scan" or "update")
        """

        def _load_logs_thread():
            try:
                entries = self.get_logs(limit=limit, log_type=log_type)
            except Exception as e:
                # On any error, return empty list to ensure callback is always called
                # This prevents loading state from getting stuck forever
                logger.debug("Async log loading failed: %s", e)
                entries = []
            # Schedule callback on main thread - always called to reset loading state
            GLib.idle_add(callback, entries)

        thread = threading.Thread(target=_load_logs_thread)
        thread.daemon = True
        thread.start()

    def get_log_by_id(self, log_id: str) -> LogEntry | None:
        """
        Retrieve a specific log entry by ID.

        Args:
            log_id: The UUID of the log entry

        Returns:
            LogEntry if found, None otherwise
        """
        with self._lock:
            try:
                self._check_and_run_privacy_migration_unlocked()
                log_file = self._safe_log_file(log_id)
                if log_file is not None and log_file.exists():
                    with open(log_file, encoding="utf-8") as f:
                        data = json.load(f)
                        return LogEntry.from_dict(data)
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Failed to load log by id %s: %s", log_id, e)
        return None

    def delete_log(self, log_id: str) -> bool:
        """
        Delete a specific log entry and remove it from the index.

        Args:
            log_id: The UUID of the log entry to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        with self._lock:
            try:
                log_file = self._safe_log_file(log_id)
                if log_file is not None and log_file.exists():
                    log_file.unlink()

                    # Update index by removing the deleted entry (best-effort)
                    try:
                        index_data = self._load_index()
                        index_data["entries"] = [
                            entry for entry in index_data["entries"] if entry.get("id") != log_id
                        ]
                        self._save_index(index_data)
                    except Exception as e:
                        # Index update failed, but log file was deleted successfully
                        # Index can be rebuilt later if needed
                        logger.debug("Index update failed after deleting log: %s", e)

                    return True
            except OSError as e:
                logger.debug("Failed to delete log %s: %s", log_id, e)
        return False

    def clear_logs(self) -> bool:
        """
        Clear all stored log entries and reset the index.

        Returns:
            True if cleared successfully, False otherwise
        """
        with self._lock:
            try:
                tracker = self._get_privacy_tracker()
                with tracker.lock:
                    done_event = tracker.done_event if tracker.running else None
                if done_event is not None:
                    done_event.wait()

                if self._log_dir.exists():
                    for log_file in self._log_dir.glob("*.json"):
                        # Skip the index file - we'll reset it separately
                        if log_file.name == INDEX_FILENAME:
                            continue
                        with contextlib.suppress(OSError):
                            log_file.unlink()

                # Reset index to empty state (best-effort)
                try:
                    self._save_index({"version": 1, "entries": []})
                except Exception as e:
                    # Index reset failed, but log files were cleared successfully
                    # Index can be rebuilt later if needed
                    logger.debug("Index reset failed after clearing logs: %s", e)

                self._clear_privacy_migration_state_unlocked()
                self._reset_privacy_migration_tracker_unlocked()
                self._privacy_migration_checked = False
                return True
            except OSError as e:
                logger.warning("Failed to clear logs: %s", e)
                return False

    def get_log_count(self) -> int:
        """
        Get the total number of stored logs.

        Uses the index for O(1) performance when available. Falls back to
        directory globbing if the index is missing or corrupted.

        Returns:
            Number of log entries
        """
        with self._lock:
            try:
                self._check_and_run_privacy_migration_unlocked()
                if not self._log_dir.exists():
                    return 0

                # Try to use index for O(1) performance
                index_data = self._load_index()
                if index_data.get("entries"):
                    # Validate the index
                    if self._validate_index(index_data):
                        return len(index_data["entries"])

                # Fallback: count log files directly (excluding index file)
                log_files = [f for f in self._log_dir.glob("*.json") if f.name != INDEX_FILENAME]
                return len(log_files)
            except OSError as e:
                logger.debug("Failed to get log count: %s", e)
                return 0

    def export_logs_to_csv(self, entries: list[LogEntry] | None = None) -> str:
        """
        Export log entries to CSV format.

        Creates a CSV formatted string with the following columns:
        - id: The unique identifier for the log entry
        - timestamp: The ISO timestamp when the operation occurred
        - type: The type of operation (scan or update)
        - status: The status of the operation (clean, infected, success, error, etc.)
        - path: The path that was scanned (empty for updates)
        - summary: Brief description of the operation
        - duration: Operation duration in seconds
        - scheduled: Whether this was a scheduled automatic scan

        Uses Python's csv module for proper escaping of special characters
        (commas, quotes, newlines) in paths and summaries.

        Args:
            entries: Optional list of LogEntry objects to export.
                    If None, exports all logs (up to 1000 entries).

        Returns:
            CSV formatted string suitable for export to .csv file

        Example output:
            id,timestamp,type,status,path,summary,duration,scheduled
            uuid-1,2024-01-15T10:30:00,scan,clean,/home/user,Clean scan,45.5,false
            uuid-2,2024-01-15T11:00:00,update,success,,Database updated,30.0,false
        """
        # If no entries provided, get all logs (up to 1000)
        if entries is None:
            entries = self.get_logs(limit=1000)

        # Use StringIO to write CSV to a string
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Write header row
        writer.writerow(
            [
                "id",
                "timestamp",
                "type",
                "status",
                "path",
                "summary",
                "duration",
                "scheduled",
            ]
        )

        # Write data rows
        for entry in entries:
            writer.writerow(
                [
                    entry.id,
                    entry.timestamp,
                    entry.type,
                    entry.status,
                    entry.path or "",  # Handle None path gracefully
                    entry.summary,
                    f"{entry.duration:.2f}" if entry.duration > 0 else "0",
                    "true" if entry.scheduled else "false",
                ]
            )

        return output.getvalue()

    def export_logs_to_json(self, entries: list[LogEntry] | None = None) -> str:
        """
        Export log entries to JSON format with metadata wrapper.

        Creates a JSON formatted string with the following structure:
        {
            "export_timestamp": "2024-01-15T12:00:00Z",
            "count": 2,
            "entries": [
                {
                    "id": "uuid-1",
                    "timestamp": "2024-01-15T10:30:00",
                    "type": "scan",
                    "status": "clean",
                    "summary": "Clean scan",
                    "details": "...",
                    "path": "/home/user",
                    "duration": 45.5,
                    "scheduled": false
                }
            ]
        }

        Uses LogEntry.to_dict() for serialization, ensuring all fields
        (including optional ones) are properly included.

        Args:
            entries: Optional list of LogEntry objects to export.
                    If None, exports all logs (up to 1000 entries).

        Returns:
            JSON formatted string suitable for export to .json file

        Example usage:
            json_output = log_manager.export_logs_to_json()
            with open('logs.json', 'w') as f:
                f.write(json_output)
        """
        # If no entries provided, get all logs (up to 1000)
        if entries is None:
            entries = self.get_logs(limit=1000)

        # Build the JSON structure with metadata
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "count": len(entries),
            "entries": [entry.to_dict() for entry in entries],
        }

        # Serialize to JSON with indentation for readability
        return json.dumps(export_data, indent=2)

    def export_logs_to_file(
        self, file_path: str, format: str, entries: list[LogEntry] | None = None
    ) -> tuple[bool, str | None]:
        """
        Export log entries to a file in the specified format.

        This method provides a unified interface for exporting logs to both CSV and JSON
        formats. Uses atomic write pattern (temp file + rename) for crash safety.

        Supported formats:
        - "csv": Exports logs to CSV format with header row
        - "json": Exports logs to JSON format with metadata wrapper

        The write operation is atomic, meaning the file will either be written completely
        or not at all - partial writes won't occur even if the process crashes.

        Args:
            file_path: The destination file path for the export
            format: The export format ("csv" or "json")
            entries: Optional list of LogEntry objects to export.
                    If None, exports all logs (up to 1000 entries).

        Returns:
            Tuple of (success, error_message) where:
            - success is True if the export succeeded, False otherwise
            - error_message is None on success, or an error description on failure

        Example usage:
            success, error = log_manager.export_logs_to_file("/tmp/logs.csv", "csv")
            if not success:
                print(f"Export failed: {error}")

            # Export specific entries
            recent_logs = log_manager.get_logs(limit=10)
            success, error = log_manager.export_logs_to_file("/tmp/recent.json", "json", recent_logs)
        """
        # Validate format parameter
        if format not in ("csv", "json"):
            return (False, f"Invalid format '{format}'. Must be 'csv' or 'json'.")

        try:
            # Generate the export content based on format
            if format == "csv":
                content = self.export_logs_to_csv(entries)
            else:  # format == "json"
                content = self.export_logs_to_json(entries)

            # Ensure parent directory exists
            file_path_obj = Path(file_path)
            parent_dir = file_path_obj.parent
            if parent_dir:
                parent_dir.mkdir(parents=True, exist_ok=True)

            # Atomic write using temp file + rename pattern
            # Create temp file in same directory as target to ensure same filesystem
            fd, temp_path = tempfile.mkstemp(
                suffix=f".{format}",
                prefix="clamui_export_",
                dir=parent_dir,
            )
            try:
                # Write content to temp file
                try:
                    f = os.fdopen(fd, "w", encoding="utf-8")
                except Exception:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                    raise

                with f:
                    f.write(content)

                # Atomic rename (replace target file if it exists)
                temp_path_obj = Path(temp_path)
                temp_path_obj.replace(file_path_obj)
                return (True, None)

            except Exception as e:
                # Clean up temp file on failure
                with contextlib.suppress(OSError):
                    Path(temp_path).unlink(missing_ok=True)
                raise e

        except PermissionError as e:
            return (False, f"Permission denied: {e}")
        except OSError as e:
            return (False, f"File operation error: {e}")
        except Exception as e:
            return (False, f"Unexpected error: {e}")

    def get_daemon_status(self) -> tuple[DaemonStatus, str | None]:
        """
        Check the status of the clamd daemon.

        Returns:
            Tuple of (DaemonStatus, optional_message)
        """
        service_names = (
            "clamav-daemon.service",
            "clamd@scan.service",
            "clamd.service",
        )
        saw_installed_service = False

        for service_name in service_names:
            try:
                result = subprocess.run(
                    wrap_host_command(["systemctl", "is-active", service_name]),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=get_clean_env(),
                )
                status_text = sanitize_log_line(result.stdout.strip())
                if status_text == "active":
                    return (DaemonStatus.RUNNING, f"{service_name} is active")
                if status_text in {"inactive", "failed", "activating", "deactivating"}:
                    saw_installed_service = True
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                logger.debug("systemctl is-active failed for %s", service_name, exc_info=True)

        # Check if clamd process is running (on host if in Flatpak)
        try:
            result = subprocess.run(
                wrap_host_command(["pgrep", "-x", "clamd"]),
                capture_output=True,
                text=True,
                timeout=5,
                env=get_clean_env(),
            )
            if result.returncode == 0:
                return (DaemonStatus.RUNNING, "clamd daemon is running")
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            logger.debug("pgrep failed while checking clamd status", exc_info=True)

        if saw_installed_service:
            return (DaemonStatus.STOPPED, "clamd service is installed but not active")

        # Check if clamd is installed (checking host if in Flatpak)
        clamd_path = which_host_command("clamd")
        if clamd_path is None:
            return (DaemonStatus.NOT_INSTALLED, "clamd is not installed")

        return (DaemonStatus.STOPPED, "clamd daemon is not running")

    def _file_exists_on_host(self, path: str) -> bool:
        """
        Check if a file exists, using host filesystem if in Flatpak.

        Args:
            path: Path to check

        Returns:
            True if file exists, False otherwise
        """
        if is_flatpak():
            try:
                result = subprocess.run(
                    ["flatpak-spawn", "--host", "test", "-f", path],
                    capture_output=True,
                    timeout=5,
                )
                return result.returncode == 0
            except Exception as e:
                logger.debug("Failed to check host file existence for %s: %s", path, e)
                return False
        return Path(path).exists()

    def get_daemon_log_path(self) -> str | None:
        """
        Find the clamd log file path.

        Checks common locations for the clamd log file.

        Returns:
            Path to the log file if found, None otherwise
        """
        for log_path in CLAMD_LOG_PATHS:
            if self._file_exists_on_host(log_path):
                return log_path

        # Also try to get from clamd.conf if it exists
        from .clamav_detection import detect_clamd_conf_path

        detected = detect_clamd_conf_path()
        clamd_conf_paths = [detected] if detected else []

        for conf_path in clamd_conf_paths:
            if self._file_exists_on_host(conf_path):
                try:
                    # Read config file (use host command in Flatpak)
                    if is_flatpak():
                        result = subprocess.run(
                            ["flatpak-spawn", "--host", "cat", conf_path],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        if result.returncode != 0:
                            continue
                        config_content = result.stdout
                    else:
                        with open(conf_path, encoding="utf-8") as f:
                            config_content = f.read()

                    for line in config_content.splitlines():
                        line = line.strip()
                        if line.startswith("LogFile"):
                            parts = line.split(None, 1)
                            if len(parts) == 2:
                                log_file = parts[1].strip()
                                if self._file_exists_on_host(log_file):
                                    return log_file
                except (OSError, PermissionError, subprocess.SubprocessError):
                    continue

        return None

    def read_daemon_logs(self, num_lines: int = 100) -> tuple[bool, str]:
        """
        Read the last N lines from the clamd daemon log.

        Uses tail-like behavior to read only the end of the file,
        avoiding loading large log files into memory.

        Tries multiple methods in order:
        1. tail command (wrapped for Flatpak)
        2. journalctl for systemd-based systems
        3. Direct file read (non-Flatpak only)

        Args:
            num_lines: Number of lines to read from the end of the log

        Returns:
            Tuple of (success, log_content_or_error_message)
        """
        log_path = self.get_daemon_log_path()

        # Try reading log file with tail
        if log_path is not None:
            try:
                # Use tail command - wrapped for Flatpak host access
                tail_cmd = wrap_host_command(["tail", "-n", str(num_lines), log_path])
                result = subprocess.run(tail_cmd, capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    content = result.stdout
                    if not content.strip():
                        return (True, "(Log file is empty)")
                    return (True, _sanitize_private_text(content))
                # If tail failed (permission denied), fall through to journalctl

            except subprocess.TimeoutExpired:
                return (False, "Timeout reading log file")
            except FileNotFoundError:
                logger.debug("tail command not available, falling back to journalctl")
            except OSError as e:
                logger.debug("OSError reading daemon log via tail: %s", e)

        # Try journalctl as fallback (works on systemd systems, no root needed)
        journalctl_result = self._read_daemon_logs_journalctl(num_lines)
        if journalctl_result[0]:
            return journalctl_result

        # If we found a log path but couldn't read it, give helpful error
        if log_path is not None:
            return (
                False,
                _sanitize_private_text(
                    f"Permission denied reading {log_path}\n\n"
                    "The daemon log file requires elevated permissions.\n"
                    "Options:\n"
                    "  • Add your user to the 'adm' or 'clamav' group:\n"
                    "    sudo usermod -aG adm $USER\n"
                    "  • Or check if clamd logs to systemd journal:\n"
                    "    journalctl -u clamav-daemon"
                ),
            )

        return (
            False,
            "Daemon log file not found.\n\n"
            "ClamAV daemon (clamd) may not be installed or configured.\n"
            "Common log locations checked:\n"
            "  • /var/log/clamav/clamd.log\n"
            "  • /var/log/clamd.log",
        )

    def _read_daemon_logs_journalctl(self, num_lines: int) -> tuple[bool, str]:
        """
        Read daemon logs from systemd journal.

        Args:
            num_lines: Number of lines to read

        Returns:
            Tuple of (success, content_or_error)
        """
        # Try different unit names used by various distros
        unit_names = [
            "clamav-daemon",
            "clamav-daemon.service",
            "clamd",
            "clamd.service",
            "clamd@scan",
            "clamd@scan.service",
        ]

        for unit in unit_names:
            try:
                cmd = wrap_host_command(
                    [
                        "journalctl",
                        "-u",
                        unit,
                        "-n",
                        str(num_lines),
                        "--no-pager",
                        "-q",  # Quiet - suppress info messages
                    ]
                )
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

                if result.returncode == 0 and result.stdout.strip():
                    return (True, _sanitize_private_text(result.stdout))

            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                continue

        return (False, "No journal entries found for clamd")

    def _read_file_tail(self, file_path: str, num_lines: int) -> tuple[bool, str]:
        """
        Read the last N lines from a file directly (fallback method).

        Args:
            file_path: Path to the file
            num_lines: Number of lines to read

        Returns:
            Tuple of (success, content_or_error)
        """
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                # For small files, read all and return last N lines
                lines = f.readlines()
                tail_lines = lines[-num_lines:] if len(lines) > num_lines else lines
                content = "".join(tail_lines)
                if not content.strip():
                    return (True, "(Log file is empty)")
                return (True, _sanitize_private_text(content))
        except PermissionError:
            return (False, "Permission denied reading log file")
        except OSError as e:
            return (False, _sanitize_private_text(f"Error reading log file: {e}"))
