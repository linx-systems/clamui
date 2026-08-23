# ClamUI Scanner Types
"""
Type definitions for ClamAV scanner operations.

This module defines the shared data types used by scanner implementations:
- ScanStatus: Enum for scan result states
- ThreatDetail: Dataclass for threat information
- ScanResult: Dataclass for complete scan results
"""

from dataclasses import dataclass, field
from enum import Enum


class ScanStatus(Enum):
    """Status of a scan operation."""

    CLEAN = "clean"  # No threats found (exit code 0)
    INFECTED = "infected"  # Threats found (exit code 1)
    ERROR = "error"  # Error occurred (exit code 2 or exception)
    CANCELLED = "cancelled"  # Scan was cancelled


@dataclass
class ThreatDetail:
    """Detailed information about a detected threat."""

    file_path: str
    threat_name: str
    category: str
    severity: str


@dataclass
class ScanProgress:
    """Real-time scan progress information.

    This dataclass is used to report progress updates during a scan operation,
    allowing the UI to display live information about the scanning process.
    """

    current_file: str
    """Path of the file currently being scanned."""

    files_scanned: int
    """Number of files processed so far."""

    files_total: int | None
    """Total number of files to scan (None if unknown/not counted)."""

    infected_count: int
    """Number of infections found so far."""

    infected_files: list[str]
    """List of infected file paths found so far."""

    bytes_scanned: int = 0
    """Number of bytes processed (if available from scanner output)."""

    estimate_exceeded: bool = False
    """True if the number of files scanned has exceeded the initial estimate."""

    infected_threats: dict[str, str] | None = None
    """Map of file path -> threat name for infected files found so far."""

    @property
    def percentage(self) -> float | None:
        """Calculate scan completion percentage.

        Returns:
            Percentage (0-100) if files_total is known and > 0, None otherwise.
        """
        if self.files_total and self.files_total > 0:
            pct = (self.files_scanned / self.files_total) * 100
            return min(100.0, max(0.0, pct))
        return None


@dataclass
class ScanResult:
    """Result of a scan operation."""

    status: ScanStatus
    path: str
    stdout: str
    stderr: str
    exit_code: int
    infected_files: list[str]
    scanned_files: int
    scanned_dirs: int
    infected_count: int
    error_message: str | None
    threat_details: list[ThreatDetail]
    skipped_files: list[str] | None = None  # Files that couldn't be scanned (permissions)
    skipped_count: int = 0  # Count of skipped files
    warning_message: str | None = None  # User-friendly warning about skipped files
    nonfatal_warnings: list[str] = field(default_factory=list)  # Non-fatal ClamAV warning lines

    @property
    def is_clean(self) -> bool:
        """Check if scan found no threats."""
        return self.status == ScanStatus.CLEAN

    @property
    def has_threats(self) -> bool:
        """Check if scan found threats."""
        return self.status == ScanStatus.INFECTED

    @property
    def has_warnings(self) -> bool:
        """Check if scan completed with warnings (e.g., skipped files)."""
        return self.skipped_count > 0 or bool(self.nonfatal_warnings)
