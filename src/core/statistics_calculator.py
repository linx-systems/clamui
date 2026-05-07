# ClamUI Statistics Calculator Module
"""
Statistics calculator module for ClamUI providing scan statistics aggregation.
Calculates metrics across different timeframes from stored scan logs.
"""

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .log_manager import LogEntry, LogManager

# Pre-compiled regex patterns for extracting file counts
# These patterns are used to parse scan log entries for file count information
FILES_SCANNED_PATTERNS = [
    re.compile(r"(\d+)\s*files?\s*scanned", re.IGNORECASE),
    re.compile(r"scanned\s*(\d+)\s*files?", re.IGNORECASE),
    re.compile(r"files[:\s]+(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s*files?", re.IGNORECASE),
]

# Pre-compiled regex patterns for extracting threat counts
# These patterns are used to parse scan log entries for threat/infection counts
THREATS_FOUND_PATTERNS = [
    re.compile(r"(\d+)\s*(?:threats?|infections?|infected)", re.IGNORECASE),
    re.compile(r"found\s*(\d+)", re.IGNORECASE),
    re.compile(r"detected\s*(\d+)", re.IGNORECASE),
]

# Pre-compiled regex patterns for extracting directory counts
# These patterns are used to parse scan log entries for directory count information
DIRS_SCANNED_PATTERNS = [
    re.compile(r"director(?:y|ies)\s+scanned[:\s]+(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s*director(?:y|ies)\s*scanned", re.IGNORECASE),
    re.compile(r"scanned\s*(\d+)\s*director(?:y|ies)", re.IGNORECASE),
    re.compile(r"director(?:y|ies)[:\s]+(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s*director(?:y|ies)", re.IGNORECASE),
]


class Timeframe(Enum):
    """Timeframe options for statistics aggregation."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ALL = "all"


class ProtectionLevel(Enum):
    """Protection status levels based on scan recency and definition freshness."""

    PROTECTED = "protected"
    AT_RISK = "at_risk"
    UNPROTECTED = "unprotected"
    UNKNOWN = "unknown"


@dataclass
class ScanStatistics:
    """Aggregated scan statistics for a given timeframe."""

    timeframe: str
    total_scans: int
    files_scanned: int
    threats_detected: int
    clean_scans: int
    infected_scans: int
    error_scans: int
    average_duration: float  # in seconds
    total_duration: float  # in seconds
    scheduled_scans: int
    manual_scans: int
    start_date: str | None = None  # ISO format
    end_date: str | None = None  # ISO format

    def to_dict(self) -> dict:
        """Convert ScanStatistics to dictionary."""
        return {
            "timeframe": self.timeframe,
            "total_scans": self.total_scans,
            "files_scanned": self.files_scanned,
            "threats_detected": self.threats_detected,
            "clean_scans": self.clean_scans,
            "infected_scans": self.infected_scans,
            "error_scans": self.error_scans,
            "average_duration": self.average_duration,
            "total_duration": self.total_duration,
            "scheduled_scans": self.scheduled_scans,
            "manual_scans": self.manual_scans,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


@dataclass
class ProtectionStatus:
    """Protection status indicating system security posture."""

    level: str  # ProtectionLevel value
    last_scan_timestamp: str | None  # ISO format
    last_scan_age_hours: float | None
    last_definition_update: str | None  # ISO format
    definition_age_hours: float | None
    message: str
    is_protected: bool

    def to_dict(self) -> dict:
        """Convert ProtectionStatus to dictionary."""
        return {
            "level": self.level,
            "last_scan_timestamp": self.last_scan_timestamp,
            "last_scan_age_hours": self.last_scan_age_hours,
            "last_definition_update": self.last_definition_update,
            "definition_age_hours": self.definition_age_hours,
            "message": self.message,
            "is_protected": self.is_protected,
        }


class StatisticsCalculator:
    """
    Calculator for scan statistics and protection status.

    Provides methods for aggregating scan data across different timeframes
    and determining the current protection status of the system.
    """

    # Thresholds for protection status (in hours)
    SCAN_WARNING_THRESHOLD_HOURS = 24 * 7  # 7 days
    SCAN_CRITICAL_THRESHOLD_HOURS = 24 * 30  # 30 days
    DEFINITION_WARNING_THRESHOLD_HOURS = 24  # 1 day
    DEFINITION_CRITICAL_THRESHOLD_HOURS = 24 * 7  # 7 days

    # Cache TTL in seconds
    CACHE_TTL_SECONDS = 30

    def __init__(self, log_manager: LogManager | None = None):
        """
        Initialize the StatisticsCalculator.

        Args:
            log_manager: Optional LogManager instance. Creates a new one if not provided.
        """
        self._log_manager = log_manager if log_manager else LogManager()

        # Cache for log data to prevent redundant disk I/O
        self._cache: dict = {}
        self._cache_timestamp: float | None = None

        # Thread lock for safe concurrent access
        self._lock = threading.Lock()

    def _get_cached_logs(self, limit: int, log_type: str) -> list[LogEntry]:
        """
        Get logs from cache if fresh, otherwise fetch from log_manager.

        Thread-safe method that checks cache validity based on TTL.
        If cache is stale or doesn't exist, fetches fresh data from
        log_manager, updates cache, and returns the data.

        Args:
            limit: Maximum number of logs to retrieve
            log_type: Type of logs to retrieve (e.g., 'scan')

        Returns:
            List of LogEntry objects
        """
        with self._lock:
            cache_key = (limit, log_type)
            current_time = time.time()

            # Check if cache exists and is fresh
            if (
                cache_key in self._cache
                and self._cache_timestamp is not None
                and (current_time - self._cache_timestamp) < self.CACHE_TTL_SECONDS
            ):
                # Return cached data
                return self._cache[cache_key]

            # Fetch fresh data from log_manager
            logs = self._log_manager.get_logs(limit=limit, log_type=log_type)

            # Update cache
            self._cache[cache_key] = logs
            self._cache_timestamp = current_time

            return logs

    def invalidate_cache(self) -> None:
        """
        Invalidate the cache, forcing fresh data on the next fetch.

        This method clears all cached log data and resets the cache timestamp.
        Useful for testing or when new logs are written and fresh data is needed
        immediately without waiting for TTL expiration.

        Thread-safe operation using internal lock.
        """
        with self._lock:
            self._cache.clear()
            self._cache_timestamp = None

    def _get_timeframe_range(self, timeframe: str) -> tuple[datetime, datetime]:
        """
        Calculate the date range for a given timeframe.

        Args:
            timeframe: One of 'daily', 'weekly', 'monthly', or 'all'

        Returns:
            Tuple of (start_datetime, end_datetime)
        """
        now = datetime.now()

        if timeframe == Timeframe.DAILY.value:
            start = now - timedelta(days=1)
        elif timeframe == Timeframe.WEEKLY.value:
            start = now - timedelta(weeks=1)
        elif timeframe == Timeframe.MONTHLY.value:
            start = now - timedelta(days=30)
        else:  # 'all' or any other value
            start = datetime.min
            # Replace tzinfo-naive datetime.min with a usable minimum
            start = datetime(1970, 1, 1)

        return (start, now)

    def _parse_timestamp(self, timestamp: str | None) -> datetime | None:
        """
        Parse an ISO format timestamp string to datetime.

        Tz-aware inputs (Z suffix, explicit offsets) are converted to the
        local timezone, then their tzinfo is dropped so the result can be
        compared against ``datetime.now()`` (which is naive local). Naive
        inputs are returned as-is. This avoids mis-bucketing entries near
        midnight or DST boundaries (BUG-003).

        Args:
            timestamp: ISO format timestamp string

        Returns:
            datetime object (always naive) or None if parsing fails or
            timestamp is None.
        """
        if timestamp is None:
            return None
        try:
            # Python 3.11+ fromisoformat accepts trailing 'Z'.
            parsed = datetime.fromisoformat(timestamp)
        except (ValueError, AttributeError, TypeError):
            return None
        if parsed.tzinfo is not None:
            # Convert tz-aware -> local naive for consistent comparison
            # with datetime.now() (which is local naive).
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed

    def _filter_entries_by_timeframe(
        self, entries: list[LogEntry], timeframe: str
    ) -> list[LogEntry]:
        """
        Filter log entries to those within the specified timeframe.

        Args:
            entries: List of LogEntry objects
            timeframe: One of 'daily', 'weekly', 'monthly', or 'all'

        Returns:
            Filtered list of LogEntry objects
        """
        if timeframe == Timeframe.ALL.value:
            return entries

        start_date, end_date = self._get_timeframe_range(timeframe)
        filtered = []

        for entry in entries:
            entry_time = self._parse_timestamp(entry.timestamp)
            if entry_time and start_date <= entry_time <= end_date:
                filtered.append(entry)

        return filtered

    def _extract_files_scanned(self, entry: LogEntry) -> int:
        """
        Extract the number of files scanned from a log entry.

        Parses the summary or details to find file count information.

        Args:
            entry: LogEntry to extract file count from

        Returns:
            Number of files scanned, or 0 if not found
        """
        text = f"{entry.summary} {entry.details}"

        # Use pre-compiled patterns for faster matching
        for pattern in FILES_SCANNED_PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    return int(match.group(1))
                except (ValueError, IndexError):
                    continue

        return 0

    def _extract_directories_scanned(self, entry: LogEntry) -> int:
        """
        Extract the number of directories scanned from a log entry.

        Parses the summary or details to find directory count information.

        Args:
            entry: LogEntry to extract directory count from

        Returns:
            Number of directories scanned, or 0 if not found
        """
        text = f"{entry.summary} {entry.details}"

        # Use pre-compiled patterns for faster matching
        for pattern in DIRS_SCANNED_PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    return int(match.group(1))
                except (ValueError, IndexError):
                    continue

        return 0

    def _extract_threats_found(self, entry: LogEntry) -> int:
        """
        Extract the number of threats found from a log entry.

        Args:
            entry: LogEntry to extract threat count from

        Returns:
            Number of threats found, or 0 if not found
        """
        # If status indicates infection, try to count
        if entry.status == "infected":
            text = f"{entry.summary} {entry.details}"

            # Use pre-compiled patterns for faster matching
            for pattern in THREATS_FOUND_PATTERNS:
                match = pattern.search(text)
                if match:
                    try:
                        return int(match.group(1))
                    except (ValueError, IndexError):
                        continue

            # Default to 1 if infected but count not found
            return 1

        return 0

    def extract_entry_statistics(self, entry: LogEntry) -> dict:
        """
        Extract statistics from a single log entry.

        Provides a clean interface for extracting scan statistics from an individual
        log entry. Useful for displaying statistics in log detail views without
        needing to aggregate across multiple entries.

        Args:
            entry: LogEntry to extract statistics from

        Returns:
            Dictionary with the following keys:
                - files_scanned: Number of files scanned (int)
                - directories_scanned: Number of directories scanned (int)
                - duration: Scan duration in seconds (float)

        Example:
            >>> entry = LogEntry(...)
            >>> stats = calculator.extract_entry_statistics(entry)
            >>> print(f"Scanned {stats['files_scanned']} files in {stats['duration']}s")
        """
        return {
            "files_scanned": self._extract_files_scanned(entry),
            "directories_scanned": self._extract_directories_scanned(entry),
            "duration": entry.duration,
        }

    def get_statistics(self, timeframe: str = "all") -> ScanStatistics:
        """
        Calculate aggregated scan statistics for the specified timeframe.

        Args:
            timeframe: One of 'daily', 'weekly', 'monthly', or 'all'

        Returns:
            ScanStatistics dataclass with aggregated metrics
        """
        # Get all scan logs (filter by type="scan")
        all_entries = self._get_cached_logs(limit=10000, log_type="scan")

        # Filter by timeframe
        entries = self._filter_entries_by_timeframe(all_entries, timeframe)

        # Initialize counters
        total_scans = len(entries)
        files_scanned = 0
        threats_detected = 0
        clean_scans = 0
        infected_scans = 0
        error_scans = 0
        total_duration = 0.0
        scheduled_scans = 0
        manual_scans = 0

        # Aggregate metrics
        for entry in entries:
            files_scanned += self._extract_files_scanned(entry)
            threats_detected += self._extract_threats_found(entry)

            if entry.status == "clean":
                clean_scans += 1
            elif entry.status == "infected":
                infected_scans += 1
            elif entry.status == "error":
                error_scans += 1

            total_duration += entry.duration

            if entry.scheduled:
                scheduled_scans += 1
            else:
                manual_scans += 1

        # Calculate average duration
        average_duration = total_duration / total_scans if total_scans > 0 else 0.0

        # Calculate date range
        start_date, end_date = self._get_timeframe_range(timeframe)

        return ScanStatistics(
            timeframe=timeframe,
            total_scans=total_scans,
            files_scanned=files_scanned,
            threats_detected=threats_detected,
            clean_scans=clean_scans,
            infected_scans=infected_scans,
            error_scans=error_scans,
            average_duration=round(average_duration, 2),
            total_duration=round(total_duration, 2),
            scheduled_scans=scheduled_scans,
            manual_scans=manual_scans,
            start_date=start_date.isoformat() if timeframe != Timeframe.ALL.value else None,
            end_date=end_date.isoformat(),
        )

    def calculate_average_duration(self, timeframe: str = "all") -> float:
        """
        Calculate the average scan duration for the specified timeframe.

        Args:
            timeframe: One of 'daily', 'weekly', 'monthly', or 'all'

        Returns:
            Average duration in seconds, or 0.0 if no scans found
        """
        stats = self.get_statistics(timeframe)
        return stats.average_duration

    def get_scan_trend_data(self, timeframe: str = "weekly", data_points: int = 7) -> list[dict]:
        """
        Get scan trend data for charting/graphing.

        Returns a list of data points with date, scan count, and threat count
        for the specified timeframe, suitable for trend visualization.
        Generates the full date range for the timeframe with zeros for empty periods.

        Args:
            timeframe: One of 'daily', 'weekly', 'monthly', or 'all'
            data_points: Number of data points to return

        Returns:
            List of dicts with 'date' (ISO format), 'scans' (count), and 'threats' (count) keys
        """
        # Get all scan logs using cache
        all_entries = self._get_cached_logs(limit=10000, log_type="scan")

        # Filter by timeframe
        entries = self._filter_entries_by_timeframe(all_entries, timeframe)

        # Group scans and threats by date
        scans_by_date: dict[str, int] = {}
        threats_by_date: dict[str, int] = {}
        for entry in entries:
            entry_time = self._parse_timestamp(entry.timestamp)
            if entry_time:
                date_key = entry_time.strftime("%Y-%m-%d")
                scans_by_date[date_key] = scans_by_date.get(date_key, 0) + 1
                threats_by_date[date_key] = threats_by_date.get(
                    date_key, 0
                ) + self._extract_threats_found(entry)

        # Generate date range based on timeframe
        start_date, end_date = self._get_timeframe_range(timeframe)

        # Calculate interval size based on data_points and timeframe
        total_days = (end_date - start_date).days
        if total_days <= 0:
            total_days = 1

        # For "all" timeframe, use actual data range if we have entries
        if timeframe == Timeframe.ALL.value and entries:
            oldest_entry = None
            for entry in entries:
                entry_time = self._parse_timestamp(entry.timestamp)
                if entry_time and (oldest_entry is None or entry_time < oldest_entry):
                    oldest_entry = entry_time
            if oldest_entry:
                start_date = oldest_entry
                total_days = (end_date - start_date).days
                if total_days <= 0:
                    total_days = 1

        # Calculate days per interval
        days_per_interval = max(1, total_days // data_points)

        # Generate data points at regular intervals
        result = []
        current_date = start_date
        for _ in range(data_points):
            if current_date > end_date:
                break

            # Calculate interval end
            interval_end = current_date + timedelta(days=days_per_interval)

            # Sum scans and threats in this interval
            interval_scans = 0
            interval_threats = 0
            check_date = current_date
            while check_date < interval_end and check_date <= end_date:
                date_key = check_date.strftime("%Y-%m-%d")
                interval_scans += scans_by_date.get(date_key, 0)
                interval_threats += threats_by_date.get(date_key, 0)
                check_date += timedelta(days=1)

            result.append(
                {
                    "date": current_date.strftime("%Y-%m-%d"),
                    "scans": interval_scans,
                    "threats": interval_threats,
                }
            )

            current_date = interval_end

        return result

    def get_protection_status(self, last_definition_update: str | None = None) -> ProtectionStatus:
        """
        Determine the current protection status of the system.

        Evaluates based on:
        - Time since last scan
        - Freshness of virus definitions

        Args:
            last_definition_update: Optional ISO timestamp of last definition update

        Returns:
            ProtectionStatus dataclass with status details
        """
        now = datetime.now()

        # Get the most recent scan
        recent_logs = self._log_manager.get_logs(limit=1, log_type="scan")

        last_scan_timestamp: str | None = None
        last_scan_age_hours: float | None = None

        if recent_logs:
            last_scan_timestamp = recent_logs[0].timestamp
            last_scan_time = self._parse_timestamp(last_scan_timestamp)
            if last_scan_time:
                delta = now - last_scan_time
                last_scan_age_hours = delta.total_seconds() / 3600

        # Parse definition update time
        definition_age_hours: float | None = None
        if last_definition_update:
            def_time = self._parse_timestamp(last_definition_update)
            if def_time:
                delta = now - def_time
                definition_age_hours = delta.total_seconds() / 3600

        # Determine protection level and message
        level = ProtectionLevel.UNKNOWN
        message = "Unable to determine protection status"
        is_protected = False

        if last_scan_age_hours is None:
            level = ProtectionLevel.UNPROTECTED
            message = "No scans performed yet"
            is_protected = False
        elif last_scan_age_hours > self.SCAN_CRITICAL_THRESHOLD_HOURS:
            level = ProtectionLevel.UNPROTECTED
            message = "Last scan was over 30 days ago"
            is_protected = False
        elif last_scan_age_hours > self.SCAN_WARNING_THRESHOLD_HOURS:
            level = ProtectionLevel.AT_RISK
            message = "Last scan was over a week ago"
            is_protected = False
        elif (
            definition_age_hours is not None
            and definition_age_hours > self.DEFINITION_CRITICAL_THRESHOLD_HOURS
        ):
            level = ProtectionLevel.AT_RISK
            message = "Virus definitions are over 7 days old"
            is_protected = False
        elif (
            definition_age_hours is not None
            and definition_age_hours > self.DEFINITION_WARNING_THRESHOLD_HOURS
        ):
            level = ProtectionLevel.AT_RISK
            message = "Virus definitions are over 1 day old"
            is_protected = False
        else:
            level = ProtectionLevel.PROTECTED
            message = "System is protected"
            is_protected = True

        return ProtectionStatus(
            level=level.value,
            last_scan_timestamp=last_scan_timestamp,
            last_scan_age_hours=last_scan_age_hours,
            last_definition_update=last_definition_update,
            definition_age_hours=definition_age_hours,
            message=message,
            is_protected=is_protected,
        )
