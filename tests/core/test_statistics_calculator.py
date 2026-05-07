# ClamUI StatisticsCalculator Tests
"""Unit tests for the StatisticsCalculator class and caching functionality."""

import tempfile
import time
from datetime import datetime, timedelta
from unittest import mock

import pytest

from src.core.log_manager import LogEntry, LogManager
from src.core.statistics_calculator import (
    FILES_SCANNED_PATTERNS,
    THREATS_FOUND_PATTERNS,
    ProtectionLevel,
    ProtectionStatus,
    ScanStatistics,
    StatisticsCalculator,
    Timeframe,
)


@pytest.fixture
def mock_log_manager():
    """
    Create a mock LogManager for testing.

    Returns a MagicMock configured with:
    - get_logs method that returns sample scan log entries
    - Tracking of call count to verify caching behavior
    """
    log_manager = mock.MagicMock()

    # Create sample log entries with different timestamps and statuses
    sample_logs = [
        LogEntry(
            id="log-1",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scanned 100 files - No threats found",
            details="Scan complete",
            path="/home/user/documents",
            duration=60.0,
            scheduled=False,
        ),
        LogEntry(
            id="log-2",
            timestamp="2024-01-14T14:30:00",
            type="scan",
            status="infected",
            summary="Found 2 threats in 50 files",
            details="Infected files detected",
            path="/home/user/downloads",
            duration=45.5,
            scheduled=True,
        ),
        LogEntry(
            id="log-3",
            timestamp="2024-01-13T09:15:00",
            type="scan",
            status="clean",
            summary="Scanned 200 files - No threats found",
            details="Scan complete",
            path="/home/user",
            duration=120.0,
            scheduled=False,
        ),
        LogEntry(
            id="log-4",
            timestamp="2024-01-12T16:45:00",
            type="scan",
            status="error",
            summary="Scan failed - Permission denied",
            details="Error during scan",
            path="/root",
            duration=5.0,
            scheduled=False,
        ),
    ]

    # Configure get_logs to return sample logs
    log_manager.get_logs.return_value = sample_logs

    return log_manager


@pytest.fixture
def statistics_calculator(mock_log_manager):
    """
    Create a StatisticsCalculator instance with a mock LogManager.

    Args:
        mock_log_manager: The mock LogManager fixture

    Returns:
        StatisticsCalculator instance configured for testing
    """
    return StatisticsCalculator(log_manager=mock_log_manager)


@pytest.fixture
def empty_log_manager():
    """
    Create a mock LogManager that returns no logs.

    Useful for testing edge cases with no scan history.
    """
    log_manager = mock.MagicMock()
    log_manager.get_logs.return_value = []
    return log_manager


@pytest.fixture
def large_log_dataset():
    """
    Create a large dataset of log entries for testing performance and caching.

    Returns a list of LogEntry objects spanning multiple days with varied statuses.
    """
    logs = []
    base_time = datetime(2024, 1, 1, 10, 0, 0)

    for i in range(100):
        timestamp = base_time + timedelta(hours=i)
        status = ["clean", "infected", "clean", "clean"][i % 4]  # 75% clean, 25% infected
        logs.append(
            LogEntry(
                id=f"log-{i}",
                timestamp=timestamp.isoformat(),
                type="scan",
                status=status,
                summary=f"Scanned {10 * (i + 1)} files",
                details=f"Details for scan {i}",
                path=f"/test/path/{i}",
                duration=float(30 + (i % 10)),
                scheduled=(i % 2 == 0),  # Alternating scheduled/manual
            )
        )

    return logs


class TestTimeframe:
    """Tests for the Timeframe enum."""

    def test_timeframe_values(self):
        """Test Timeframe enum has expected values."""
        assert Timeframe.DAILY.value == "daily"
        assert Timeframe.WEEKLY.value == "weekly"
        assert Timeframe.MONTHLY.value == "monthly"
        assert Timeframe.ALL.value == "all"


class TestProtectionLevel:
    """Tests for the ProtectionLevel enum."""

    def test_protection_level_values(self):
        """Test ProtectionLevel enum has expected values."""
        assert ProtectionLevel.PROTECTED.value == "protected"
        assert ProtectionLevel.AT_RISK.value == "at_risk"
        assert ProtectionLevel.UNPROTECTED.value == "unprotected"
        assert ProtectionLevel.UNKNOWN.value == "unknown"


class TestScanStatistics:
    """Tests for the ScanStatistics dataclass."""

    def test_scan_statistics_creation(self):
        """Test creating a ScanStatistics instance."""
        stats = ScanStatistics(
            timeframe="daily",
            total_scans=10,
            files_scanned=1000,
            threats_detected=2,
            clean_scans=8,
            infected_scans=1,
            error_scans=1,
            average_duration=60.5,
            total_duration=605.0,
            scheduled_scans=5,
            manual_scans=5,
            start_date="2024-01-01T00:00:00",
            end_date="2024-01-02T00:00:00",
        )

        assert stats.timeframe == "daily"
        assert stats.total_scans == 10
        assert stats.files_scanned == 1000
        assert stats.threats_detected == 2
        assert stats.clean_scans == 8
        assert stats.infected_scans == 1
        assert stats.error_scans == 1
        assert stats.average_duration == 60.5
        assert stats.total_duration == 605.0
        assert stats.scheduled_scans == 5
        assert stats.manual_scans == 5

    def test_scan_statistics_to_dict(self):
        """Test ScanStatistics.to_dict serialization."""
        stats = ScanStatistics(
            timeframe="weekly",
            total_scans=5,
            files_scanned=500,
            threats_detected=1,
            clean_scans=4,
            infected_scans=1,
            error_scans=0,
            average_duration=45.0,
            total_duration=225.0,
            scheduled_scans=3,
            manual_scans=2,
        )

        data = stats.to_dict()

        assert data["timeframe"] == "weekly"
        assert data["total_scans"] == 5
        assert data["files_scanned"] == 500
        assert data["threats_detected"] == 1
        assert data["clean_scans"] == 4
        assert data["infected_scans"] == 1
        assert data["error_scans"] == 0
        assert data["average_duration"] == 45.0
        assert data["total_duration"] == 225.0
        assert data["scheduled_scans"] == 3
        assert data["manual_scans"] == 2


class TestProtectionStatus:
    """Tests for the ProtectionStatus dataclass."""

    def test_protection_status_creation(self):
        """Test creating a ProtectionStatus instance."""
        status = ProtectionStatus(
            level="protected",
            last_scan_timestamp="2024-01-15T10:00:00",
            last_scan_age_hours=2.5,
            last_definition_update="2024-01-15T08:00:00",
            definition_age_hours=4.5,
            message="System is protected",
            is_protected=True,
        )

        assert status.level == "protected"
        assert status.last_scan_timestamp == "2024-01-15T10:00:00"
        assert status.last_scan_age_hours == 2.5
        assert status.last_definition_update == "2024-01-15T08:00:00"
        assert status.definition_age_hours == 4.5
        assert status.message == "System is protected"
        assert status.is_protected is True

    def test_protection_status_to_dict(self):
        """Test ProtectionStatus.to_dict serialization."""
        status = ProtectionStatus(
            level="at_risk",
            last_scan_timestamp="2024-01-10T10:00:00",
            last_scan_age_hours=120.0,
            last_definition_update=None,
            definition_age_hours=None,
            message="Last scan was over a week ago",
            is_protected=False,
        )

        data = status.to_dict()

        assert data["level"] == "at_risk"
        assert data["last_scan_timestamp"] == "2024-01-10T10:00:00"
        assert data["last_scan_age_hours"] == 120.0
        assert data["last_definition_update"] is None
        assert data["definition_age_hours"] is None
        assert data["message"] == "Last scan was over a week ago"
        assert data["is_protected"] is False


class TestStatisticsCalculator:
    """Tests for the StatisticsCalculator class."""

    def test_init_with_log_manager(self, mock_log_manager):
        """Test StatisticsCalculator initialization with provided LogManager."""
        calculator = StatisticsCalculator(log_manager=mock_log_manager)
        assert calculator._log_manager is mock_log_manager

    def test_init_without_log_manager(self):
        """Test StatisticsCalculator initialization creates default LogManager."""
        calculator = StatisticsCalculator()
        assert calculator._log_manager is not None

    def test_cache_initialized(self, statistics_calculator):
        """Test that cache data structures are initialized."""
        assert hasattr(statistics_calculator, "_cache")
        assert hasattr(statistics_calculator, "_cache_timestamp")
        assert hasattr(statistics_calculator, "_lock")
        assert isinstance(statistics_calculator._cache, dict)
        assert statistics_calculator._cache_timestamp is None

    def test_cache_ttl_constant(self):
        """Test that CACHE_TTL_SECONDS constant is defined."""
        assert hasattr(StatisticsCalculator, "CACHE_TTL_SECONDS")
        assert StatisticsCalculator.CACHE_TTL_SECONDS == 30


class TestStatisticsCalculatorBasicFunctionality:
    """Tests for basic StatisticsCalculator functionality without caching focus."""

    def test_get_statistics_returns_scan_statistics(self, statistics_calculator):
        """Test that get_statistics returns a ScanStatistics object."""
        stats = statistics_calculator.get_statistics(timeframe="all")
        assert isinstance(stats, ScanStatistics)

    def test_get_statistics_with_empty_logs(self, empty_log_manager):
        """Test get_statistics with no log entries."""
        calculator = StatisticsCalculator(log_manager=empty_log_manager)
        stats = calculator.get_statistics(timeframe="all")

        assert stats.total_scans == 0
        assert stats.files_scanned == 0
        assert stats.threats_detected == 0
        assert stats.clean_scans == 0
        assert stats.infected_scans == 0
        assert stats.error_scans == 0
        assert stats.average_duration == 0.0

    def test_invalidate_cache_method_exists(self, statistics_calculator):
        """Test that invalidate_cache method exists and is callable."""
        assert hasattr(statistics_calculator, "invalidate_cache")
        assert callable(statistics_calculator.invalidate_cache)

    def test_get_scan_trend_data_returns_list(self, statistics_calculator):
        """Test that get_scan_trend_data returns a list of data points."""
        trend_data = statistics_calculator.get_scan_trend_data(timeframe="weekly", data_points=7)
        assert isinstance(trend_data, list)


class TestStatisticsCalculatorCacheHit:
    """Tests for cache hit behavior - verifying log_manager.get_logs() is only called once."""

    def test_get_statistics_caches_log_data(self, statistics_calculator, mock_log_manager):
        """Test that get_statistics caches log data for subsequent calls."""
        # First call should fetch from log_manager
        stats1 = statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 1

        # Second call should use cached data (no additional fetch)
        stats2 = statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 1  # Still 1, not 2

        # Both results should be the same (using same data)
        assert stats1.total_scans == stats2.total_scans
        assert stats1.threats_detected == stats2.threats_detected

    def test_get_scan_trend_data_caches_log_data(self, statistics_calculator, mock_log_manager):
        """Test that get_scan_trend_data caches log data for subsequent calls."""
        # First call should fetch from log_manager
        trend1 = statistics_calculator.get_scan_trend_data(timeframe="weekly", data_points=7)
        assert mock_log_manager.get_logs.call_count == 1

        # Second call should use cached data (no additional fetch)
        trend2 = statistics_calculator.get_scan_trend_data(timeframe="weekly", data_points=7)
        assert mock_log_manager.get_logs.call_count == 1  # Still 1, not 2

        # Both results should be the same
        assert len(trend1) == len(trend2)

    def test_get_statistics_then_get_scan_trend_data_shares_cache(
        self, statistics_calculator, mock_log_manager
    ):
        """
        Test that get_statistics() and get_scan_trend_data() share the same cache.

        This is the key test: when called in succession, log_manager.get_logs()
        should only be called once because both methods use the same cache key
        (limit=10000, log_type='scan').
        """
        # Reset call count to ensure clean state
        mock_log_manager.get_logs.reset_mock()

        # First call to get_statistics should fetch from log_manager
        stats = statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 1
        assert isinstance(stats, ScanStatistics)

        # Second call to get_scan_trend_data should use cached data (cache hit!)
        trend_data = statistics_calculator.get_scan_trend_data(timeframe="weekly", data_points=7)
        assert mock_log_manager.get_logs.call_count == 1  # Still 1 - cache hit!
        assert isinstance(trend_data, list)

    def test_get_scan_trend_data_then_get_statistics_shares_cache(
        self, statistics_calculator, mock_log_manager
    ):
        """
        Test cache sharing in reverse order (trend data first, then statistics).

        Verifies that the cache works bidirectionally - either method can
        populate the cache for the other.
        """
        # Reset call count to ensure clean state
        mock_log_manager.get_logs.reset_mock()

        # First call to get_scan_trend_data should fetch from log_manager
        trend_data = statistics_calculator.get_scan_trend_data(timeframe="weekly", data_points=7)
        assert mock_log_manager.get_logs.call_count == 1
        assert isinstance(trend_data, list)

        # Second call to get_statistics should use cached data (cache hit!)
        stats = statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 1  # Still 1 - cache hit!
        assert isinstance(stats, ScanStatistics)

    def test_multiple_successive_calls_all_use_cache(self, statistics_calculator, mock_log_manager):
        """Test that multiple successive calls all use the same cache."""
        # Reset call count
        mock_log_manager.get_logs.reset_mock()

        # First call
        statistics_calculator.get_statistics(timeframe="daily")
        assert mock_log_manager.get_logs.call_count == 1

        # Second call - different timeframe but uses cache
        statistics_calculator.get_statistics(timeframe="weekly")
        assert mock_log_manager.get_logs.call_count == 1

        # Third call - trend data also uses cache
        statistics_calculator.get_scan_trend_data(timeframe="monthly", data_points=4)
        assert mock_log_manager.get_logs.call_count == 1


class TestStatisticsCalculatorCacheExpiry:
    """Tests for cache expiry behavior - verifying cache invalidation after TTL."""

    def test_cache_expires_after_ttl(self, statistics_calculator, mock_log_manager):
        """Test that cache expires after CACHE_TTL_SECONDS."""
        # First call populates cache
        statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 1

        # Manually expire the cache by going back in time
        statistics_calculator._cache_timestamp = time.time() - 31  # 31 seconds ago

        # Next call should fetch again because cache expired
        statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 2

    def test_invalidate_cache_clears_all_data(self, statistics_calculator, mock_log_manager):
        """Test that invalidate_cache() clears the cache."""
        # Populate cache
        statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 1
        assert len(statistics_calculator._cache) > 0

        # Invalidate cache
        statistics_calculator.invalidate_cache()
        assert len(statistics_calculator._cache) == 0
        assert statistics_calculator._cache_timestamp is None

        # Next call should fetch again
        statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 2

    def test_cache_still_valid_before_expiry(self, statistics_calculator, mock_log_manager):
        """Test that cache is still valid before TTL expires."""
        # First call
        statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 1

        # Advance time by less than TTL
        statistics_calculator._cache_timestamp = time.time() - 15  # 15 seconds ago

        # Cache should still be valid
        statistics_calculator.get_statistics(timeframe="all")
        assert mock_log_manager.get_logs.call_count == 1  # No additional fetch


class TestStatisticsCalculatorCacheConcurrency:
    """Tests for thread safety of cache operations."""

    def test_cache_uses_lock_for_thread_safety(self, statistics_calculator):
        """Test that cache operations use a lock for thread safety."""
        assert hasattr(statistics_calculator, "_lock")
        import threading

        assert isinstance(statistics_calculator._lock, type(threading.Lock()))


class TestStatisticsCalculatorEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_get_statistics_with_different_timeframes(self, statistics_calculator):
        """Test get_statistics with different timeframe values."""
        for timeframe in ["daily", "weekly", "monthly", "all"]:
            stats = statistics_calculator.get_statistics(timeframe=timeframe)
            assert isinstance(stats, ScanStatistics)
            assert stats.timeframe == timeframe

    def test_get_scan_trend_data_with_different_data_points(self, statistics_calculator):
        """Test get_scan_trend_data with different data_points values."""
        for data_points in [1, 7, 30, 100]:
            trend_data = statistics_calculator.get_scan_trend_data(
                timeframe="daily", data_points=data_points
            )
            assert isinstance(trend_data, list)

    def test_large_dataset_performance(self, large_log_dataset):
        """Test StatisticsCalculator performance with large dataset."""
        log_manager = mock.MagicMock()
        log_manager.get_logs.return_value = large_log_dataset
        calculator = StatisticsCalculator(log_manager=log_manager)

        # Should complete without timeout
        stats = calculator.get_statistics(timeframe="all")
        assert isinstance(stats, ScanStatistics)
        assert stats.total_scans == 100

    def test_cache_with_large_dataset(self, large_log_dataset):
        """Test caching works correctly with large dataset."""
        log_manager = mock.MagicMock()
        log_manager.get_logs.return_value = large_log_dataset
        calculator = StatisticsCalculator(log_manager=log_manager)

        # First call
        stats1 = calculator.get_statistics(timeframe="all")
        assert log_manager.get_logs.call_count == 1

        # Second call should use cache
        stats2 = calculator.get_statistics(timeframe="all")
        assert log_manager.get_logs.call_count == 1
        assert stats1.total_scans == stats2.total_scans


class TestExtractDirectoriesScanned:
    """Tests for _extract_directories_scanned method."""

    def test_extract_directories_scanned_pattern_1(self, statistics_calculator):
        """Test extraction with '5 directories scanned' pattern."""
        entry = LogEntry(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scan complete",
            details="Scanned: 100 files, 5 directories",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 5

    def test_extract_directories_scanned_pattern_2(self, statistics_calculator):
        """Test extraction with 'scanned 3 directories' pattern."""
        entry = LogEntry(
            id="test-2",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scanned 3 directories successfully",
            details="Operation complete",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 3

    def test_extract_directories_scanned_pattern_3(self, statistics_calculator):
        """Test extraction with 'directories: 10' pattern."""
        entry = LogEntry(
            id="test-3",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scan report",
            details="Files: 200, Directories: 10",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 10

    def test_extract_directories_scanned_pattern_4(self, statistics_calculator):
        """Test extraction with '20 directories' pattern."""
        entry = LogEntry(
            id="test-4",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="20 directories processed",
            details="Scan completed successfully",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 20

    def test_extract_directories_scanned_case_insensitive(self, statistics_calculator):
        """Test extraction is case insensitive."""
        entry = LogEntry(
            id="test-5",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="15 DIRECTORIES SCANNED",
            details="Operation complete",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 15

    def test_extract_directories_scanned_singular_form(self, statistics_calculator):
        """Test extraction with singular 'directory'."""
        entry = LogEntry(
            id="test-6",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="1 directory scanned",
            details="Operation complete",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 1

    def test_extract_directories_scanned_not_found(self, statistics_calculator):
        """Test extraction returns 0 when no directory count found."""
        entry = LogEntry(
            id="test-7",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scan complete",
            details="No directory information available",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 0

    def test_extract_directories_scanned_empty_details(self, statistics_calculator):
        """Test extraction with empty details."""
        entry = LogEntry(
            id="test-8",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="",
            details="",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 0

    def test_extract_directories_scanned_large_number(self, statistics_calculator):
        """Test extraction with large directory count."""
        entry = LogEntry(
            id="test-9",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scanned 9999 directories",
            details="Large scan operation",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 9999

    def test_extract_directories_scanned_zero_count(self, statistics_calculator):
        """Test extraction with zero directories."""
        entry = LogEntry(
            id="test-10",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="0 directories scanned",
            details="File-only scan",
            path="/home/user/file.txt",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 0

    def test_extract_directories_scanned_mixed_content(self, statistics_calculator):
        """Test extraction from mixed content with files and directories."""
        entry = LogEntry(
            id="test-11",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scan complete",
            details="Scanned 250 files and 12 directories in /home/user",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 12

    def test_extract_directories_scanned_from_summary_only(self, statistics_calculator):
        """Test extraction when directory count is only in summary."""
        entry = LogEntry(
            id="test-12",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Processed 8 directories",
            details="",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 8

    def test_extract_directories_scanned_from_details_only(self, statistics_calculator):
        """Test extraction when directory count is only in details."""
        entry = LogEntry(
            id="test-13",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="",
            details="Total directories scanned: 25",
            path="/home/user",
            duration=30.0,
            scheduled=False,
        )
        result = statistics_calculator._extract_directories_scanned(entry)
        assert result == 25


class TestExtractEntryStatistics:
    """Tests for extract_entry_statistics method."""

    def test_extract_entry_statistics_complete_data(self, statistics_calculator):
        """Test extraction with complete statistics data."""
        entry = LogEntry(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scan complete",
            details="Scanned: 100 files, 5 directories",
            path="/home/user",
            duration=45.5,
            scheduled=False,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert isinstance(result, dict)
        assert "files_scanned" in result
        assert "directories_scanned" in result
        assert "duration" in result
        assert result["files_scanned"] == 100
        assert result["directories_scanned"] == 5
        assert result["duration"] == 45.5

    def test_extract_entry_statistics_partial_data(self, statistics_calculator):
        """Test extraction when only some statistics are available."""
        entry = LogEntry(
            id="test-2",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="50 files scanned",
            details="No directory information",
            path="/home/user",
            duration=20.0,
            scheduled=False,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert result["files_scanned"] == 50
        assert result["directories_scanned"] == 0
        assert result["duration"] == 20.0

    def test_extract_entry_statistics_no_scan_data(self, statistics_calculator):
        """Test extraction when no scan statistics are found."""
        entry = LogEntry(
            id="test-3",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="error",
            summary="Scan failed",
            details="Permission denied",
            path="/home/user",
            duration=1.5,
            scheduled=False,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert result["files_scanned"] == 0
        assert result["directories_scanned"] == 0
        assert result["duration"] == 1.5

    def test_extract_entry_statistics_zero_duration(self, statistics_calculator):
        """Test extraction with zero duration."""
        entry = LogEntry(
            id="test-4",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Quick scan: 10 files, 2 directories",
            details="Instant scan completed",
            path="/home/user/file.txt",
            duration=0.0,
            scheduled=False,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert result["files_scanned"] == 10
        assert result["directories_scanned"] == 2
        assert result["duration"] == 0.0

    def test_extract_entry_statistics_large_numbers(self, statistics_calculator):
        """Test extraction with large file and directory counts."""
        entry = LogEntry(
            id="test-5",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Large scan completed",
            details="Scanned 50000 files in 999 directories",
            path="/home",
            duration=3600.5,
            scheduled=True,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert result["files_scanned"] == 50000
        assert result["directories_scanned"] == 999
        assert result["duration"] == 3600.5

    def test_extract_entry_statistics_infected_scan(self, statistics_calculator):
        """Test extraction from infected scan log."""
        entry = LogEntry(
            id="test-6",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="infected",
            summary="Found 3 threats",
            details="Scanned: 75 files, 8 directories. Detected 3 infected files.",
            path="/home/user/downloads",
            duration=60.0,
            scheduled=False,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert result["files_scanned"] == 75
        assert result["directories_scanned"] == 8
        assert result["duration"] == 60.0

    def test_extract_entry_statistics_update_log(self, statistics_calculator):
        """Test extraction from update log (should return zeros for scan stats)."""
        entry = LogEntry(
            id="test-7",
            timestamp="2024-01-15T10:00:00",
            type="update",
            status="success",
            summary="Database updated successfully",
            details="Updated to version 12345",
            path=None,
            duration=120.0,
            scheduled=True,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        # Update logs won't have file/directory scan information
        assert result["files_scanned"] == 0
        assert result["directories_scanned"] == 0
        assert result["duration"] == 120.0

    def test_extract_entry_statistics_empty_entry(self, statistics_calculator):
        """Test extraction from entry with empty strings."""
        entry = LogEntry(
            id="test-8",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="",
            details="",
            path="",
            duration=0.0,
            scheduled=False,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert result["files_scanned"] == 0
        assert result["directories_scanned"] == 0
        assert result["duration"] == 0.0

    def test_extract_entry_statistics_return_type(self, statistics_calculator):
        """Test that return value is always a dictionary with expected keys."""
        entry = LogEntry(
            id="test-9",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Test scan",
            details="Test details",
            path="/test",
            duration=10.0,
            scheduled=False,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert isinstance(result, dict)
        assert len(result) == 3
        assert set(result.keys()) == {
            "files_scanned",
            "directories_scanned",
            "duration",
        }
        assert isinstance(result["files_scanned"], int)
        assert isinstance(result["directories_scanned"], int)
        assert isinstance(result["duration"], float)

    def test_extract_entry_statistics_scheduled_scan(self, statistics_calculator):
        """Test extraction from scheduled scan."""
        entry = LogEntry(
            id="test-10",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scheduled scan completed",
            details="Scanned 300 files and 15 directories",
            path="/home/user",
            duration=90.25,
            scheduled=True,
        )
        result = statistics_calculator.extract_entry_statistics(entry)

        assert result["files_scanned"] == 300
        assert result["directories_scanned"] == 15
        assert result["duration"] == 90.25


# =============================================================================
# Tests merged from tests/test_statistics_calculator.py
# =============================================================================


class TestPrecompiledPatterns:
    """Tests for pre-compiled regex patterns at module level."""

    def test_files_scanned_patterns_defined(self):
        """Test FILES_SCANNED_PATTERNS is defined at module level."""
        assert FILES_SCANNED_PATTERNS is not None

    def test_files_scanned_patterns_is_list(self):
        """Test FILES_SCANNED_PATTERNS is a list."""
        assert isinstance(FILES_SCANNED_PATTERNS, list)

    def test_files_scanned_patterns_count(self):
        """Test FILES_SCANNED_PATTERNS has expected number of patterns."""
        assert len(FILES_SCANNED_PATTERNS) == 4

    def test_files_scanned_patterns_are_compiled_regex(self):
        """Test FILES_SCANNED_PATTERNS contains compiled regex objects."""
        import re

        for pattern in FILES_SCANNED_PATTERNS:
            assert isinstance(pattern, type(re.compile("")))

    def test_threats_found_patterns_defined(self):
        """Test THREATS_FOUND_PATTERNS is defined at module level."""
        assert THREATS_FOUND_PATTERNS is not None

    def test_threats_found_patterns_is_list(self):
        """Test THREATS_FOUND_PATTERNS is a list."""
        assert isinstance(THREATS_FOUND_PATTERNS, list)

    def test_threats_found_patterns_count(self):
        """Test THREATS_FOUND_PATTERNS has expected number of patterns."""
        assert len(THREATS_FOUND_PATTERNS) == 3

    def test_threats_found_patterns_are_compiled_regex(self):
        """Test THREATS_FOUND_PATTERNS contains compiled regex objects."""
        import re

        for pattern in THREATS_FOUND_PATTERNS:
            assert isinstance(pattern, type(re.compile("")))


class TestStatisticsCalculatorWithRealLogManager:
    """Tests for StatisticsCalculator using real LogManager instances."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    @pytest.fixture
    def calculator(self, log_manager):
        """Create a StatisticsCalculator with the test LogManager."""
        return StatisticsCalculator(log_manager=log_manager)

    def test_get_statistics_empty_logs(self, calculator):
        """Test get_statistics with no scan logs."""
        stats = calculator.get_statistics()
        assert stats.total_scans == 0
        assert stats.files_scanned == 0
        assert stats.threats_detected == 0
        assert stats.clean_scans == 0
        assert stats.infected_scans == 0
        assert stats.error_scans == 0
        assert stats.average_duration == 0.0
        assert stats.total_duration == 0.0

    def test_get_statistics_all_timeframe(self, calculator, log_manager):
        """Test get_statistics with 'all' timeframe."""
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="100 files scanned",
            details="",
            duration=60.0,
        )
        entry2 = LogEntry.create(
            log_type="scan",
            status="infected",
            summary="2 threats detected",
            details="",
            duration=120.0,
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry2)

        stats = calculator.get_statistics(timeframe="all")
        assert stats.timeframe == "all"
        assert stats.total_scans == 2
        assert stats.clean_scans == 1
        assert stats.infected_scans == 1
        assert stats.total_duration == 180.0
        assert stats.average_duration == 90.0

    def test_get_statistics_counts_scan_types(self, calculator, log_manager):
        """Test get_statistics correctly counts scan types."""
        clean_entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Clean scan",
            details="",
        )
        infected_entry = LogEntry.create(
            log_type="scan",
            status="infected",
            summary="Infected",
            details="",
        )
        error_entry = LogEntry.create(
            log_type="scan",
            status="error",
            summary="Error occurred",
            details="",
        )
        log_manager.save_log(clean_entry)
        log_manager.save_log(infected_entry)
        log_manager.save_log(error_entry)

        stats = calculator.get_statistics(timeframe="all")
        assert stats.total_scans == 3
        assert stats.clean_scans == 1
        assert stats.infected_scans == 1
        assert stats.error_scans == 1

    def test_get_statistics_counts_scheduled_vs_manual(self, calculator, log_manager):
        """Test get_statistics correctly counts scheduled vs manual scans."""
        scheduled_entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scheduled scan",
            details="",
            scheduled=True,
        )
        manual_entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Manual scan 1",
            details="",
            scheduled=False,
        )
        manual_entry2 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Manual scan 2",
            details="",
            scheduled=False,
        )
        log_manager.save_log(scheduled_entry)
        log_manager.save_log(manual_entry1)
        log_manager.save_log(manual_entry2)

        stats = calculator.get_statistics(timeframe="all")
        assert stats.scheduled_scans == 1
        assert stats.manual_scans == 2

    def test_get_statistics_ignores_update_logs(self, calculator, log_manager):
        """Test get_statistics only counts scan logs, not update logs."""
        scan_entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scan",
            details="",
        )
        update_entry = LogEntry.create(
            log_type="update",
            status="success",
            summary="Database updated",
            details="",
        )
        log_manager.save_log(scan_entry)
        log_manager.save_log(update_entry)

        stats = calculator.get_statistics(timeframe="all")
        assert stats.total_scans == 1

    def test_get_statistics_calculates_average_duration(self, calculator, log_manager):
        """Test get_statistics correctly calculates average duration."""
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scan 1",
            details="",
            duration=100.0,
        )
        entry2 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scan 2",
            details="",
            duration=200.0,
        )
        entry3 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scan 3",
            details="",
            duration=300.0,
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry2)
        log_manager.save_log(entry3)

        stats = calculator.get_statistics(timeframe="all")
        assert stats.total_duration == 600.0
        assert stats.average_duration == 200.0


class TestStatisticsCalculatorTimeframeRange:
    """Tests for timeframe range calculation."""

    @pytest.fixture
    def calculator(self):
        """Create a StatisticsCalculator with mocked LogManager."""
        mock_log_manager = mock.Mock(spec=LogManager)
        mock_log_manager.get_logs.return_value = []
        return StatisticsCalculator(log_manager=mock_log_manager)

    def test_get_timeframe_range_daily(self, calculator):
        """Test daily timeframe range calculation."""
        start, end = calculator._get_timeframe_range("daily")
        delta = end - start
        assert delta.days == 1 or (delta.days == 0 and delta.seconds > 0)

    def test_get_timeframe_range_weekly(self, calculator):
        """Test weekly timeframe range calculation."""
        start, end = calculator._get_timeframe_range("weekly")
        delta = end - start
        assert 6 <= delta.days <= 7

    def test_get_timeframe_range_monthly(self, calculator):
        """Test monthly timeframe range calculation."""
        start, end = calculator._get_timeframe_range("monthly")
        delta = end - start
        assert 29 <= delta.days <= 30

    def test_get_timeframe_range_all(self, calculator):
        """Test 'all' timeframe range calculation."""
        start, end = calculator._get_timeframe_range("all")
        assert start.year == 1970


class TestStatisticsCalculatorTimestampParsing:
    """Tests for timestamp parsing functionality."""

    @pytest.fixture
    def calculator(self):
        """Create a StatisticsCalculator with mocked LogManager."""
        mock_log_manager = mock.Mock(spec=LogManager)
        mock_log_manager.get_logs.return_value = []
        return StatisticsCalculator(log_manager=mock_log_manager)

    def test_parse_timestamp_valid_iso(self, calculator):
        """Test parsing valid ISO format timestamp."""
        result = calculator._parse_timestamp("2024-01-15T10:30:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_timestamp_with_microseconds(self, calculator):
        """Test parsing timestamp with microseconds."""
        result = calculator._parse_timestamp("2024-01-15T10:30:00.123456")
        assert result is not None
        assert result.year == 2024

    def test_parse_timestamp_with_z_suffix(self, calculator):
        """Test parsing timestamp with Z suffix (UTC)."""
        result = calculator._parse_timestamp("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024

    def test_parse_timestamp_invalid(self, calculator):
        """Test parsing invalid timestamp returns None."""
        result = calculator._parse_timestamp("invalid-timestamp")
        assert result is None

    def test_parse_timestamp_empty(self, calculator):
        """Test parsing empty timestamp returns None."""
        result = calculator._parse_timestamp("")
        assert result is None

    def test_parse_timestamp_with_none(self, calculator):
        """Test _parse_timestamp handles None input."""
        result = calculator._parse_timestamp(None)
        assert result is None


class TestStatisticsCalculatorFilesScannedExtraction:
    """Tests for extracting files scanned count from log entries."""

    @pytest.fixture
    def calculator(self):
        """Create a StatisticsCalculator with mocked LogManager."""
        mock_log_manager = mock.Mock(spec=LogManager)
        return StatisticsCalculator(log_manager=mock_log_manager)

    def test_extract_files_scanned_pattern_1(self, calculator):
        """Test extracting file count from 'X files scanned' pattern."""
        entry = LogEntry(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="500 files scanned",
            details="",
        )
        result = calculator._extract_files_scanned(entry)
        assert result == 500

    def test_extract_files_scanned_pattern_2(self, calculator):
        """Test extracting file count from 'Scanned X files' pattern."""
        entry = LogEntry(
            id="test-2",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scanned 1234 files",
            details="",
        )
        result = calculator._extract_files_scanned(entry)
        assert result == 1234

    def test_extract_files_scanned_from_details(self, calculator):
        """Test extracting file count from details field."""
        entry = LogEntry(
            id="test-3",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scan complete",
            details="Files: 2500",
        )
        result = calculator._extract_files_scanned(entry)
        assert result == 2500

    def test_extract_files_scanned_no_match(self, calculator):
        """Test extracting file count returns 0 when no pattern matches."""
        entry = LogEntry(
            id="test-4",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="Scan complete",
            details="No threats found",
        )
        result = calculator._extract_files_scanned(entry)
        assert result == 0

    def test_extract_files_scanned_with_large_numbers(self, calculator):
        """Test extracting large file counts."""
        entry = LogEntry(
            id="test",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="1000000 files scanned",
            details="",
        )
        result = calculator._extract_files_scanned(entry)
        assert result == 1000000


class TestStatisticsCalculatorThreatsExtraction:
    """Tests for extracting threats count from log entries."""

    @pytest.fixture
    def calculator(self):
        """Create a StatisticsCalculator with mocked LogManager."""
        mock_log_manager = mock.Mock(spec=LogManager)
        return StatisticsCalculator(log_manager=mock_log_manager)

    def test_extract_threats_found_clean_scan(self, calculator):
        """Test threats count is 0 for clean scans."""
        entry = LogEntry(
            id="test-1",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="clean",
            summary="No threats found",
            details="",
        )
        result = calculator._extract_threats_found(entry)
        assert result == 0

    def test_extract_threats_found_infected_with_count(self, calculator):
        """Test extracting threat count from infected scan with count."""
        entry = LogEntry(
            id="test-2",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="infected",
            summary="3 threats detected",
            details="",
        )
        result = calculator._extract_threats_found(entry)
        assert result == 3

    def test_extract_threats_found_infected_default(self, calculator):
        """Test infected scan defaults to 1 threat when count not found."""
        entry = LogEntry(
            id="test-3",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="infected",
            summary="Malware found",
            details="",
        )
        result = calculator._extract_threats_found(entry)
        assert result == 1

    def test_extract_threats_found_pattern_found(self, calculator):
        """Test extracting threat count from 'Found X' pattern."""
        entry = LogEntry(
            id="test-4",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="infected",
            summary="Found 5 items",
            details="",
        )
        result = calculator._extract_threats_found(entry)
        assert result == 5


class TestStatisticsCalculatorTimeframeFiltering:
    """Tests for timeframe filtering functionality."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    @pytest.fixture
    def calculator(self, log_manager):
        """Create a StatisticsCalculator with the test LogManager."""
        return StatisticsCalculator(log_manager=log_manager)

    def test_filter_entries_by_timeframe_all(self, calculator):
        """Test that 'all' timeframe returns all entries."""
        now = datetime.now()
        entries = [
            LogEntry(
                id="1",
                timestamp=(now - timedelta(days=365)).isoformat(),
                type="scan",
                status="clean",
                summary="Old scan",
                details="",
            ),
            LogEntry(
                id="2",
                timestamp=now.isoformat(),
                type="scan",
                status="clean",
                summary="Recent scan",
                details="",
            ),
        ]
        filtered = calculator._filter_entries_by_timeframe(entries, "all")
        assert len(filtered) == 2

    def test_filter_entries_by_timeframe_daily(self, calculator):
        """Test that 'daily' timeframe filters correctly."""
        now = datetime.now()
        entries = [
            LogEntry(
                id="1",
                timestamp=(now - timedelta(hours=2)).isoformat(),
                type="scan",
                status="clean",
                summary="Recent scan",
                details="",
            ),
            LogEntry(
                id="2",
                timestamp=(now - timedelta(days=5)).isoformat(),
                type="scan",
                status="clean",
                summary="Old scan",
                details="",
            ),
        ]
        filtered = calculator._filter_entries_by_timeframe(entries, "daily")
        assert len(filtered) == 1
        assert filtered[0].id == "1"

    def test_filter_entries_by_timeframe_weekly(self, calculator):
        """Test that 'weekly' timeframe filters correctly."""
        now = datetime.now()
        entries = [
            LogEntry(
                id="1",
                timestamp=(now - timedelta(days=3)).isoformat(),
                type="scan",
                status="clean",
                summary="This week scan",
                details="",
            ),
            LogEntry(
                id="2",
                timestamp=(now - timedelta(days=14)).isoformat(),
                type="scan",
                status="clean",
                summary="Two weeks ago scan",
                details="",
            ),
        ]
        filtered = calculator._filter_entries_by_timeframe(entries, "weekly")
        assert len(filtered) == 1
        assert filtered[0].id == "1"

    def test_filter_entries_by_timeframe_monthly(self, calculator):
        """Test that 'monthly' timeframe filters correctly."""
        now = datetime.now()
        entries = [
            LogEntry(
                id="1",
                timestamp=(now - timedelta(days=15)).isoformat(),
                type="scan",
                status="clean",
                summary="This month scan",
                details="",
            ),
            LogEntry(
                id="2",
                timestamp=(now - timedelta(days=60)).isoformat(),
                type="scan",
                status="clean",
                summary="Two months ago scan",
                details="",
            ),
        ]
        filtered = calculator._filter_entries_by_timeframe(entries, "monthly")
        assert len(filtered) == 1
        assert filtered[0].id == "1"


class TestStatisticsCalculatorAverageDuration:
    """Tests for the calculate_average_duration method."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    @pytest.fixture
    def calculator(self, log_manager):
        """Create a StatisticsCalculator with the test LogManager."""
        return StatisticsCalculator(log_manager=log_manager)

    def test_calculate_average_duration_empty(self, calculator):
        """Test average duration is 0 when no scans exist."""
        result = calculator.calculate_average_duration()
        assert result == 0.0

    def test_calculate_average_duration_single_scan(self, calculator, log_manager):
        """Test average duration with single scan."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="",
            duration=150.0,
        )
        log_manager.save_log(entry)

        result = calculator.calculate_average_duration()
        assert result == 150.0

    def test_calculate_average_duration_multiple_scans(self, calculator, log_manager):
        """Test average duration with multiple scans."""
        for duration in [100.0, 200.0, 300.0, 400.0]:
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary="Test scan",
                details="",
                duration=duration,
            )
            log_manager.save_log(entry)

        result = calculator.calculate_average_duration()
        assert result == 250.0  # (100+200+300+400) / 4


class TestStatisticsCalculatorProtectionStatus:
    """Tests for the get_protection_status method."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    @pytest.fixture
    def calculator(self, log_manager):
        """Create a StatisticsCalculator with the test LogManager."""
        return StatisticsCalculator(log_manager=log_manager)

    def test_protection_status_no_scans(self, calculator):
        """Test protection status when no scans have been performed."""
        status = calculator.get_protection_status()
        assert status.level == ProtectionLevel.UNPROTECTED.value
        assert status.is_protected is False
        assert "no scans" in status.message.lower()
        assert status.last_scan_timestamp is None

    def test_protection_status_recent_scan_protected(self, calculator, log_manager):
        """Test protection status with recent scan is protected."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Recent scan",
            details="",
        )
        log_manager.save_log(entry)

        status = calculator.get_protection_status()
        assert status.level == ProtectionLevel.PROTECTED.value
        assert status.is_protected is True
        assert status.last_scan_timestamp is not None
        assert status.last_scan_age_hours is not None
        assert status.last_scan_age_hours < 1

    def test_protection_status_old_scan_at_risk(self, calculator, log_manager):
        """Test protection status with scan over a week old is at_risk."""
        old_timestamp = (datetime.now() - timedelta(days=8)).isoformat()
        entry = LogEntry(
            id="old-scan",
            timestamp=old_timestamp,
            type="scan",
            status="clean",
            summary="Old scan",
            details="",
        )
        log_manager.save_log(entry)

        status = calculator.get_protection_status()
        assert status.level == ProtectionLevel.AT_RISK.value
        assert status.is_protected is False
        assert "week" in status.message.lower()

    def test_protection_status_very_old_scan_unprotected(self, calculator, log_manager):
        """Test protection status with scan over 30 days old is unprotected."""
        old_timestamp = (datetime.now() - timedelta(days=35)).isoformat()
        entry = LogEntry(
            id="very-old-scan",
            timestamp=old_timestamp,
            type="scan",
            status="clean",
            summary="Very old scan",
            details="",
        )
        log_manager.save_log(entry)

        status = calculator.get_protection_status()
        assert status.level == ProtectionLevel.UNPROTECTED.value
        assert status.is_protected is False
        assert "30 days" in status.message.lower()

    def test_protection_status_with_stale_definitions(self, calculator, log_manager):
        """Test protection status with outdated definitions."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Recent scan",
            details="",
        )
        log_manager.save_log(entry)

        old_def_timestamp = (datetime.now() - timedelta(days=8)).isoformat()
        status = calculator.get_protection_status(last_definition_update=old_def_timestamp)
        assert status.level == ProtectionLevel.AT_RISK.value
        assert "definitions" in status.message.lower() or "outdated" in status.message.lower()

    def test_protection_status_with_fresh_definitions(self, calculator, log_manager):
        """Test protection status with fresh definitions."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Recent scan",
            details="",
        )
        log_manager.save_log(entry)

        fresh_def_timestamp = (datetime.now() - timedelta(hours=1)).isoformat()
        status = calculator.get_protection_status(last_definition_update=fresh_def_timestamp)
        assert status.level == ProtectionLevel.PROTECTED.value
        assert status.is_protected is True

    def test_protection_status_includes_definition_age(self, calculator, log_manager):
        """Test protection status includes definition age when provided."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Recent scan",
            details="",
        )
        log_manager.save_log(entry)

        def_timestamp = (datetime.now() - timedelta(hours=12)).isoformat()
        status = calculator.get_protection_status(last_definition_update=def_timestamp)
        assert status.definition_age_hours is not None
        assert 11 <= status.definition_age_hours <= 13


class TestStatisticsCalculatorScanTrendData:
    """Tests for the get_scan_trend_data method."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    @pytest.fixture
    def calculator(self, log_manager):
        """Create a StatisticsCalculator with the test LogManager."""
        return StatisticsCalculator(log_manager=log_manager)

    def test_get_scan_trend_data_empty(self, calculator):
        """Test trend data with no scans returns full date range with zeros."""
        trend = calculator.get_scan_trend_data(timeframe="weekly", data_points=7)
        assert len(trend) == 7
        for point in trend:
            assert point["scans"] == 0
            assert point["threats"] == 0

    def test_get_scan_trend_data_returns_correct_points(self, calculator):
        """Test trend data returns requested number of data points."""
        trend = calculator.get_scan_trend_data(timeframe="weekly", data_points=5)
        assert len(trend) == 5

    def test_get_scan_trend_data_has_dates(self, calculator):
        """Test trend data includes ISO date strings."""
        trend = calculator.get_scan_trend_data(timeframe="daily", data_points=4)
        for point in trend:
            assert "date" in point
            datetime.fromisoformat(point["date"])

    def test_get_scan_trend_data_aggregates_scans(self, calculator, log_manager):
        """Test trend data correctly aggregates scan counts."""
        for _ in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary="Test scan",
                details="",
            )
            log_manager.save_log(entry)

        trend = calculator.get_scan_trend_data(timeframe="daily", data_points=4)
        total_scans = sum(point["scans"] for point in trend)
        assert total_scans == 5


class TestStatisticsCalculatorMergedEdgeCases:
    """Additional edge case tests merged from root test file."""

    @pytest.fixture
    def calculator(self):
        """Create a StatisticsCalculator with mocked LogManager."""
        mock_log_manager = mock.Mock(spec=LogManager)
        mock_log_manager.get_logs.return_value = []
        return StatisticsCalculator(log_manager=mock_log_manager)

    def test_get_statistics_with_invalid_timeframe(self, calculator):
        """Test get_statistics handles invalid timeframe gracefully."""
        stats = calculator.get_statistics(timeframe="invalid")
        assert stats.timeframe == "invalid"
        assert stats.total_scans == 0

    def test_statistics_with_zero_duration_entries(self, calculator):
        """Test statistics calculation with zero duration entries."""
        mock_log_manager = calculator._log_manager
        entries = [
            LogEntry(
                id="1",
                timestamp=datetime.now().isoformat(),
                type="scan",
                status="clean",
                summary="Scan 1",
                details="",
                duration=0.0,
            ),
            LogEntry(
                id="2",
                timestamp=datetime.now().isoformat(),
                type="scan",
                status="clean",
                summary="Scan 2",
                details="",
                duration=0.0,
            ),
        ]
        mock_log_manager.get_logs.return_value = entries

        stats = calculator.get_statistics()
        assert stats.average_duration == 0.0
        assert stats.total_duration == 0.0


class TestParseTimestampTimezone:
    """Tests for _parse_timestamp tz-aware behavior (BUG-003)."""

    @pytest.fixture
    def calculator(self, mock_log_manager):
        return StatisticsCalculator(log_manager=mock_log_manager)

    def test_parse_timestamp_with_z_suffix_converts_to_local_naive(self, calculator):
        """Z-suffixed UTC string converts to local naive datetime consistently."""
        from datetime import UTC

        ts = "2025-12-31T23:59:00Z"
        result = calculator._parse_timestamp(ts)
        # Expected: parse as aware UTC, convert to local, drop tzinfo
        expected = datetime(2025, 12, 31, 23, 59, 0, tzinfo=UTC).astimezone().replace(tzinfo=None)
        assert result == expected
        # Result must be naive (so it can be compared to datetime.now())
        assert result is not None
        assert result.tzinfo is None

    def test_parse_timestamp_with_offset_handles_correctly(self, calculator):
        """Timestamp with explicit offset converts to local naive consistently."""
        from datetime import UTC, timedelta, timezone

        ts = "2025-12-31T20:00:00-04:00"
        result = calculator._parse_timestamp(ts)
        # 20:00 -04:00 == 00:00 UTC next day
        expected_utc = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        # Equivalent: aware datetime with -04:00 offset
        aware = datetime(2025, 12, 31, 20, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
        assert aware == expected_utc
        expected = aware.astimezone().replace(tzinfo=None)
        assert result == expected
        assert result is not None
        assert result.tzinfo is None

    def test_parse_timestamp_preserves_instant_across_offsets(self, calculator):
        """Same instant expressed in different ways yields same naive local time."""
        ts_utc = "2025-06-15T12:00:00+00:00"
        ts_z = "2025-06-15T12:00:00Z"
        ts_offset = "2025-06-15T08:00:00-04:00"  # same instant
        a = calculator._parse_timestamp(ts_utc)
        b = calculator._parse_timestamp(ts_z)
        c = calculator._parse_timestamp(ts_offset)
        assert a == b == c

    def test_parse_timestamp_naive_input_still_returns_datetime(self, calculator):
        """Naive ISO timestamps (no tz) still parse and return a naive datetime."""
        ts = "2024-01-15T10:00:00"
        result = calculator._parse_timestamp(ts)
        assert result is not None
        assert result.tzinfo is None
        assert result == datetime(2024, 1, 15, 10, 0, 0)

    def test_parse_timestamp_with_microseconds_and_z(self, calculator):
        """Timestamp with microseconds and Z suffix parses to local naive."""
        from datetime import UTC

        ts = "2025-12-31T23:59:59.123456Z"
        result = calculator._parse_timestamp(ts)
        expected = (
            datetime(2025, 12, 31, 23, 59, 59, 123456, tzinfo=UTC).astimezone().replace(tzinfo=None)
        )
        assert result == expected
        assert result is not None
        assert result.tzinfo is None

    def test_parse_timestamp_none_returns_none(self, calculator):
        """None input returns None (preserves existing contract)."""
        assert calculator._parse_timestamp(None) is None

    def test_parse_timestamp_invalid_returns_none(self, calculator):
        """Invalid input returns None (preserves existing contract)."""
        assert calculator._parse_timestamp("not a timestamp") is None

    def test_filter_does_not_misbucket_at_utc_local_boundary(self, calculator):
        """Two UTC timestamps that map to same local 'today' both pass daily filter.

        Picks two UTC timestamps separated by 30 minutes that both fall within
        the same local day after UTC->local conversion. The previous (buggy)
        implementation stripped the timezone, mis-bucketing entries near
        midnight boundaries. With proper tz-aware parsing, both timestamps
        compare correctly against datetime.now() (local naive).
        """
        from datetime import UTC

        # Pick a 'now' well into the local day so 30 minutes earlier and the
        # current moment both fall on the same local day regardless of host tz.
        local_now = datetime.now().replace(hour=12, minute=30, second=0, microsecond=0)
        # Express same instants as UTC ISO strings
        utc_now = local_now.astimezone(UTC)
        ts_recent = utc_now.isoformat().replace("+00:00", "Z")
        ts_30min_ago = (utc_now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")

        with mock.patch("src.core.statistics_calculator.datetime") as mock_dt:
            # Make datetime.now() return our fixed local naive time
            mock_dt.now.return_value = local_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            entries = [
                LogEntry(
                    id="r1",
                    timestamp=ts_recent,
                    type="scan",
                    status="clean",
                    summary="recent",
                    details="",
                    duration=0.0,
                ),
                LogEntry(
                    id="r2",
                    timestamp=ts_30min_ago,
                    type="scan",
                    status="clean",
                    summary="30 min ago",
                    details="",
                    duration=0.0,
                ),
            ]
            filtered = calculator._filter_entries_by_timeframe(entries, Timeframe.DAILY.value)

        assert len(filtered) == 2, (
            "Both timestamps within the last 30 minutes should pass the daily "
            "filter when timestamps are tz-aware-parsed correctly"
        )
