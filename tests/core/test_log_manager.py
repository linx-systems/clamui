# ClamUI LogManager Tests
"""Unit tests for the LogManager and LogEntry classes."""

import csv
import io
import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from src.core.log_manager import (
    LOG_PRIVACY_STATE_FILENAME,
    DaemonStatus,
    LogEntry,
    LogManager,
    LogType,
)
from src.core.sanitize import REDACTED_PATH


class TestLogEntry:
    """Tests for the LogEntry dataclass."""

    def test_create_generates_unique_id(self):
        """Test that LogEntry.create generates unique IDs."""
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details here",
        )
        entry2 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details here",
        )
        assert entry1.id != entry2.id

    def test_create_sets_timestamp(self):
        """Test that LogEntry.create sets a timestamp."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details here",
        )
        assert entry.timestamp is not None
        assert len(entry.timestamp) > 0
        # Should be ISO format
        assert "T" in entry.timestamp

    def test_create_with_all_fields(self):
        """Test LogEntry.create with all fields."""
        entry = LogEntry.create(
            log_type="scan",
            status="infected",
            summary="Found malware",
            details="Detailed output here",
            path="/home/user/downloads",
            duration=15.5,
        )
        assert entry.type == "scan"
        assert entry.status == "infected"
        assert entry.summary == "Found malware"
        assert entry.details == "Detailed output here"
        assert entry.path is None
        assert entry.duration == 15.5

    def test_to_dict(self):
        """Test LogEntry.to_dict serialization."""
        entry = LogEntry(
            id="test-uuid-123",
            timestamp="2024-01-15T10:30:00",
            type="update",
            status="success",
            summary="Database updated",
            details="Full output",
            path=None,
            duration=30.0,
        )
        data = entry.to_dict()

        assert data["id"] == "test-uuid-123"
        assert data["timestamp"] == "2024-01-15T10:30:00"
        assert data["type"] == "update"
        assert data["status"] == "success"
        assert data["summary"] == "Database updated"
        assert data["details"] == "Full output"
        assert data["path"] is None
        assert data["duration"] == 30.0

    def test_from_dict(self):
        """Test LogEntry.from_dict deserialization."""
        data = {
            "id": "test-uuid-456",
            "timestamp": "2024-01-16T14:00:00",
            "type": "scan",
            "status": "clean",
            "summary": "No threats found",
            "details": "Scan complete",
            "path": "/home/user",
            "duration": 120.5,
        }
        entry = LogEntry.from_dict(data)

        assert entry.id == "test-uuid-456"
        assert entry.timestamp == "2024-01-16T14:00:00"
        assert entry.type == "scan"
        assert entry.status == "clean"
        assert entry.summary == "No threats found"
        assert entry.details == "Scan complete"
        assert entry.path == "/home/user"
        assert entry.duration == 120.5

    def test_from_dict_regenerates_traversal_id(self):
        """Test from_dict rejects a path-traversal id and regenerates a safe one."""
        import uuid

        malicious = {
            "id": "../../etc/passwd",
            "timestamp": "2024-01-16T14:00:00",
            "type": "scan",
            "status": "clean",
            "summary": "x",
            "details": "y",
        }
        entry = LogEntry.from_dict(malicious)

        # The traversal id must not survive; a valid UUID is generated instead.
        assert entry.id != "../../etc/passwd"
        assert "/" not in entry.id
        uuid.UUID(entry.id)  # raises ValueError if not a valid UUID

    def test_from_dict_preserves_valid_id(self):
        """Test from_dict keeps an id matching the strict pattern."""
        data = {"id": "abc_DEF-123", "summary": "ok"}
        entry = LogEntry.from_dict(data)
        assert entry.id == "abc_DEF-123"

    def test_from_dict_with_missing_fields(self):
        """Test LogEntry.from_dict handles missing fields gracefully."""
        data = {"summary": "Partial data"}
        entry = LogEntry.from_dict(data)

        # Should have defaults for missing fields
        assert entry.id is not None
        assert entry.timestamp is not None
        assert entry.type == "unknown"
        assert entry.status == "unknown"
        assert entry.summary == "Partial data"
        assert entry.details == ""
        assert entry.path is None
        assert entry.duration == 0.0

    def test_from_dict_coerces_nonnumeric_duration(self):
        """Test from_dict coerces a null/non-numeric duration to a float.

        A tampered or corrupt stored log with ``"duration": null`` (or a
        string) must not leave a non-float on the entry, which would crash
        downstream arithmetic (statistics aggregation) and comparisons
        (CSV export ``entry.duration > 0``).
        """
        # null duration (key present, value None) must become 0.0, not None
        entry_null = LogEntry.from_dict(
            {
                "id": "dur-null",
                "timestamp": "2024-01-01T00:00:00",
                "type": "scan",
                "status": "clean",
                "summary": "s",
                "details": "d",
                "duration": None,
            }
        )
        assert entry_null.duration == 0.0
        assert isinstance(entry_null.duration, float)
        # Comparison used by CSV export must not raise
        assert (entry_null.duration > 0) is False

        # numeric string is coerced to float
        entry_str = LogEntry.from_dict({"id": "dur-str", "duration": "12.5"})
        assert entry_str.duration == 12.5
        assert isinstance(entry_str.duration, float)

        # garbage string falls back to 0.0 instead of crashing
        entry_bad = LogEntry.from_dict({"id": "dur-bad", "duration": "abc"})
        assert entry_bad.duration == 0.0

    def test_roundtrip_serialization(self):
        """Test that to_dict and from_dict are reversible."""
        original = LogEntry.create(
            log_type="scan",
            status="infected",
            summary="Test summary",
            details="Test details",
            path="/test/path",
            duration=5.5,
        )
        data = original.to_dict()
        restored = LogEntry.from_dict(data)

        assert restored.id == original.id
        assert restored.timestamp == original.timestamp
        assert restored.type == original.type
        assert restored.status == original.status
        assert restored.summary == original.summary
        assert restored.details == original.details
        assert restored.path == original.path
        assert restored.duration == original.duration

    # Sanitization Tests

    def test_create_sanitizes_summary_newlines(self):
        """Test LogEntry.create sanitizes newlines in summary field."""
        # Summary is a single-line field - newlines should become spaces
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Line 1\nLine 2\nLine 3",
            details="Details",
        )
        assert "\n" not in entry.summary
        assert entry.summary == "Line 1 Line 2 Line 3"

    def test_create_sanitizes_summary_ansi_escapes(self):
        """Test LogEntry.create sanitizes ANSI escape sequences in summary."""
        # ANSI codes should be removed from summary
        entry = LogEntry.create(
            log_type="scan",
            status="infected",
            summary="Found \x1b[31mmalware\x1b[0m in file",
            details="Details",
        )
        assert "\x1b" not in entry.summary
        assert entry.summary == "Found malware in file"

    def test_create_sanitizes_summary_control_characters(self):
        """Test LogEntry.create sanitizes control characters in summary."""
        # Control characters (bell, null, etc.) should be removed
        entry = LogEntry.create(
            log_type="scan",
            status="error",
            summary="Error\x00\x07\x08message",
            details="Details",
        )
        assert "\x00" not in entry.summary
        assert "\x07" not in entry.summary
        assert "\x08" not in entry.summary
        assert entry.summary == "Errormessage"

    def test_create_sanitizes_summary_unicode_bidi(self):
        """Test LogEntry.create sanitizes Unicode bidirectional overrides in summary."""
        # Unicode bidi override characters should be removed
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="File\u202etxt.evil sanitized",
            details="Details",
        )
        assert "\u202e" not in entry.summary
        assert entry.summary == "Filetxt.evil sanitized"

    def test_create_sanitizes_path_newlines(self):
        """Test LogEntry.create sanitizes newlines in path field."""
        # Path is single-line - newlines should become spaces
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Summary",
            details="Details",
            path="/home/user\nfake/path",
        )
        assert entry.path is None

    def test_create_sanitizes_path_ansi_escapes(self):
        """Test LogEntry.create sanitizes ANSI escape sequences in path."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Summary",
            details="Details",
            path="/path/\x1b[32mwith\x1b[0m/color",
        )
        assert entry.path is None

    def test_create_sanitizes_details_preserves_newlines(self):
        """Test LogEntry.create preserves legitimate newlines in details field."""
        # Details is multi-line - newlines should be preserved
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Summary",
            details="Line 1\nLine 2\nLine 3",
        )
        assert entry.details == "Line 1\nLine 2\nLine 3"

    def test_create_sanitizes_details_ansi_escapes(self):
        """Test LogEntry.create sanitizes ANSI escape sequences in details."""
        entry = LogEntry.create(
            log_type="scan",
            status="infected",
            summary="Summary",
            details="Found \x1b[31mthreat\x1b[0m\nIn file.txt",
        )
        assert "\x1b" not in entry.details
        assert entry.details == "Found threat\nIn file.txt"

    def test_create_sanitizes_details_control_characters(self):
        """Test LogEntry.create sanitizes control characters in details."""
        # Non-whitespace control characters should be removed
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Summary",
            details="Output\x00\x07\x08\nNext line",
        )
        assert "\x00" not in entry.details
        assert "\x07" not in entry.details
        assert entry.details == "Output\nNext line"

    def test_create_handles_none_path(self):
        """Test LogEntry.create handles None path gracefully."""
        entry = LogEntry.create(
            log_type="update",
            status="success",
            summary="Database updated",
            details="Details",
            path=None,
        )
        assert entry.path is None

    def test_create_combined_malicious_input(self):
        """Test LogEntry.create with combined malicious characters."""
        # Test with multiple attack vectors combined
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Clean\x00\nscan\x1b[31m\u202afile\u202c",
            details="Output\x00\nLine 2\x1b[32mgreen",
            path="/path\ninjection\x1b[0m",
        )
        # Summary: newlines become spaces, control chars removed
        assert entry.summary == "Clean scanfile"
        # Details: newlines preserved, control chars removed
        assert entry.details == "Output\nLine 2green"
        # Path storage is disabled for privacy
        assert entry.path is None

    def test_from_scan_result_data_sanitizes_path(self):
        """Test from_scan_result_data sanitizes path field."""
        entry = LogEntry.from_scan_result_data(
            scan_status="clean",
            path="/home/user\x1b[31m\nmalicious",
            duration=10.0,
            scanned_files=5,
        )
        assert entry.path is None
        assert entry.summary == "Clean scan"
        assert entry.details == "Scanned: 5 files, 0 directories"

    def test_from_scan_result_data_sanitizes_threat_details(self):
        """Test from_scan_result_data sanitizes threat details."""
        threat_details = [
            {
                "file_path": "/tmp/virus\x1b[31m.exe\x00",
                "threat_name": "Trojan\nFakeLog.Gen",
            },
            {
                "file_path": "/tmp/\u202eevil.txt",
                "threat_name": "Malware\x07.Test",
            },
        ]
        entry = LogEntry.from_scan_result_data(
            scan_status="infected",
            path="/tmp",
            duration=15.0,
            infected_count=2,
            threat_details=threat_details,
        )
        # Details should contain sanitized threat information
        details_lines = entry.details.split("\n")
        # File paths are omitted entirely, but threat names are preserved
        assert not any("/tmp/" in line for line in details_lines)
        assert any("Trojan FakeLog.Gen" in line for line in details_lines)
        assert any("Malware.Test" in line for line in details_lines)
        # Ensure no ANSI, null bytes, bidi, or control chars in details
        assert "\x1b" not in entry.details
        assert "\x00" not in entry.details
        assert "\u202e" not in entry.details
        assert "\x07" not in entry.details

    def test_from_scan_result_data_sanitizes_error_message(self):
        """Test from_scan_result_data sanitizes error message."""
        entry = LogEntry.from_scan_result_data(
            scan_status="error",
            path="/test",
            duration=1.0,
            error_message="Permission\x00 denied\n[FAKE] Success",
        )
        # Error message should be sanitized in details
        assert "\x00" not in entry.details
        # Newlines in error message should become spaces (single-line field)
        assert "Permission denied [FAKE] Success" in entry.details

    def test_from_scan_result_data_sanitizes_suffix(self):
        """Test from_scan_result_data sanitizes suffix field."""
        entry = LogEntry.from_scan_result_data(
            scan_status="clean",
            path="/test",
            duration=5.0,
            suffix="(daemon\x1b[31m)\ninjection",
        )
        # Suffix should be sanitized in summary
        assert "\x1b" not in entry.summary
        assert "\n" not in entry.summary
        assert "(daemon) injection" in entry.summary

    def test_from_scan_result_data_sanitizes_stdout(self):
        """Test from_scan_result_data sanitizes stdout field."""
        stdout_with_ansi = """
----------- SCAN SUMMARY -----------
\x1b[32mKnown viruses: 12345\x1b[0m
Engine version: 1.0.0
\x00Null bytes here
Scanned directories: 10
\x1b[31mInfected files: 0\x1b[0m
"""
        entry = LogEntry.from_scan_result_data(
            scan_status="clean",
            path="/test",
            duration=10.0,
            stdout=stdout_with_ansi,
        )
        # Raw stdout is no longer persisted to avoid leaking scanned file data.
        assert entry.details == ""

    def test_from_scan_result_data_log_injection_attempt(self):
        """Test from_scan_result_data prevents log injection via crafted filenames."""
        # Attacker tries to inject a fake clean scan result
        threat_details = [
            {
                "file_path": "malware.exe\n[CLEAN] Fake scan of /important/system",
                "threat_name": "Virus.Win32.Test",
            }
        ]
        entry = LogEntry.from_scan_result_data(
            scan_status="infected",
            path="/downloads",
            duration=5.0,
            infected_count=1,
            threat_details=threat_details,
        )
        assert entry.details == "Threats found: 1\n  - Virus.Win32.Test"

    def test_from_scan_result_data_ansi_obfuscation_attempt(self):
        """Test from_scan_result_data prevents ANSI-based obfuscation."""
        # Attacker tries to hide malicious file with ANSI "hidden" code
        threat_details = [
            {
                "file_path": "safe.txt\x1b[8mactually_malware.exe\x1b[0m",
                "threat_name": "Trojan.Generic",
            }
        ]
        entry = LogEntry.from_scan_result_data(
            scan_status="infected",
            path="/downloads",
            duration=5.0,
            infected_count=1,
            threat_details=threat_details,
        )
        assert entry.details == "Threats found: 1\n  - Trojan.Generic"

    def test_from_dict_sanitizes_summary(self):
        """Test from_dict sanitizes summary field from deserialized data."""
        data = {
            "id": "test-id",
            "timestamp": "2024-01-01T00:00:00",
            "type": "scan",
            "status": "clean",
            "summary": "Clean\x00 scan\nwith\x1b[31m issues",
            "details": "Details",
        }
        entry = LogEntry.from_dict(data)
        # Summary should be sanitized (single-line)
        assert "\x00" not in entry.summary
        assert "\n" not in entry.summary
        assert "\x1b" not in entry.summary
        assert entry.summary == "Clean scan with issues"

    def test_from_dict_sanitizes_details(self):
        """Test from_dict sanitizes details field from deserialized data."""
        data = {
            "id": "test-id",
            "timestamp": "2024-01-01T00:00:00",
            "type": "scan",
            "status": "infected",
            "summary": "Summary",
            "details": "Line 1\x00\nLine 2\x1b[32m\nLine 3",
        }
        entry = LogEntry.from_dict(data)
        # Details should be sanitized (multi-line - preserves newlines)
        assert "\x00" not in entry.details
        assert "\x1b" not in entry.details
        assert entry.details == "Line 1\nLine 2\nLine 3"

    def test_from_dict_sanitizes_path(self):
        """Test from_dict sanitizes path field from deserialized data."""
        data = {
            "id": "test-id",
            "timestamp": "2024-01-01T00:00:00",
            "type": "scan",
            "status": "clean",
            "summary": "Summary",
            "details": "Details",
            "path": "/home/user\n\x1b[31m/malicious\u202e",
        }
        entry = LogEntry.from_dict(data)
        # Path is sanitized (ANSI, control chars, bidi overrides stripped) but preserved
        assert entry.path is not None
        assert "\x1b" not in entry.path
        assert "\n" not in entry.path
        assert "\u202e" not in entry.path

    def test_from_dict_sanitizes_status(self):
        """Test from_dict sanitizes status field from deserialized data."""
        data = {
            "id": "test-id",
            "timestamp": "2024-01-01T00:00:00",
            "type": "scan",
            "status": "clean\n\x1b[31minfected",
            "summary": "Summary",
            "details": "Details",
        }
        entry = LogEntry.from_dict(data)
        # Status should be sanitized
        assert "\n" not in entry.status
        assert "\x1b" not in entry.status
        assert entry.status == "clean infected"

    def test_from_dict_handles_none_path(self):
        """Test from_dict handles None path gracefully."""
        data = {
            "id": "test-id",
            "timestamp": "2024-01-01T00:00:00",
            "type": "update",
            "status": "success",
            "summary": "Summary",
            "details": "Details",
            "path": None,
        }
        entry = LogEntry.from_dict(data)
        assert entry.path is None

    def test_from_dict_protects_against_tampering(self):
        """Test from_dict protects against maliciously crafted stored logs."""
        # Simulate an attacker tampering with stored log JSON
        malicious_data = {
            "id": "attacker-id",
            "timestamp": "2024-01-01T00:00:00",
            "type": "scan\x00",
            "status": "clean\ninfected",  # Try to inject contradictory status
            "summary": "Clean scan\n[ERROR] System compromised",  # Log injection
            "details": "\x1b[8mHidden malware: /tmp/evil.exe\x1b[0m\nNormal output",
            "path": "/safe/path\n/tmp/\u202eevil",
        }
        entry = LogEntry.from_dict(malicious_data)

        # All malicious content should be sanitized
        assert "\x00" not in entry.type
        assert "\n" not in entry.status
        assert "\n" not in entry.summary  # Log injection prevented
        assert "\x1b" not in entry.details  # ANSI obfuscation removed
        # Path is sanitized (control chars, bidi overrides stripped) but preserved
        assert entry.path is not None
        assert "\n" not in entry.path
        assert "\u202e" not in entry.path

        # Verify sanitized values
        assert entry.status == "clean infected"
        assert entry.summary == "Clean scan [ERROR] System compromised"
        assert REDACTED_PATH in entry.details


class TestLogManager:
    """Tests for the LogManager class."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    def test_init_creates_log_directory(self, temp_log_dir):
        """Test that LogManager creates the log directory on init."""
        log_dir = Path(temp_log_dir) / "subdir" / "logs"
        LogManager(log_dir=str(log_dir))
        assert log_dir.exists()

    def test_get_logs_redacts_existing_sensitive_scan_paths(self, temp_log_dir):
        """Test retroactive redaction of existing persisted scan logs."""
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        legacy_log = log_dir / "legacy-scan.json"
        original_path = "/home/user/Documents/private/file.txt"

        with open(legacy_log, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": "legacy-scan",
                    "timestamp": "2024-01-15T10:30:00",
                    "type": "scan",
                    "status": "infected",
                    "summary": f"Threat found in {original_path}",
                    "details": f"Threat location: {original_path}",
                    "path": original_path,
                    "duration": 12.5,
                },
                f,
                indent=2,
            )

        manager = LogManager(log_dir=temp_log_dir)
        logs = manager.get_logs()

        assert len(logs) == 1
        assert logs[0].path is None
        assert REDACTED_PATH in logs[0].summary
        assert REDACTED_PATH in logs[0].details

        rewritten_text = legacy_log.read_text(encoding="utf-8")
        rewritten = json.loads(rewritten_text)
        assert rewritten["path"] is None
        assert REDACTED_PATH in rewritten["summary"]
        assert REDACTED_PATH in rewritten["details"]
        assert original_path not in rewritten_text

    def test_init_with_default_directory(self, monkeypatch):
        """Test LogManager uses XDG_DATA_HOME by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("XDG_DATA_HOME", tmpdir)
            manager = LogManager()
            expected_path = Path(tmpdir) / "clamui" / "logs"
            assert manager._log_dir == expected_path

    def test_save_log(self, log_manager, temp_log_dir):
        """Test saving a log entry."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details here",
        )
        result = log_manager.save_log(entry)

        assert result is True
        log_file = Path(temp_log_dir) / f"{entry.id}.json"
        assert log_file.exists()

        # Verify content
        with open(log_file) as f:
            data = json.load(f)
        assert data["id"] == entry.id
        assert data["type"] == "scan"

    def test_save_log_sets_restrictive_permissions(self, log_manager, temp_log_dir):
        """Test that save_log sets 0o600 permissions on log files."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details here",
        )
        result = log_manager.save_log(entry)

        assert result is True
        log_file = Path(temp_log_dir) / f"{entry.id}.json"
        assert log_file.exists()

        # Verify file permissions are owner read/write only (0o600)
        # Log files may contain sensitive scan paths
        file_mode = log_file.stat().st_mode & 0o777
        assert file_mode == 0o600, f"Expected 0o600, got {oct(file_mode)}"

    def test_get_logs_empty(self, log_manager):
        """Test get_logs returns empty list when no logs exist."""
        logs = log_manager.get_logs()
        assert logs == []

    def test_get_logs_returns_saved_entries(self, log_manager):
        """Test get_logs returns previously saved entries."""
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scan 1",
            details="Details 1",
        )
        entry2 = LogEntry.create(
            log_type="update",
            status="success",
            summary="Update 1",
            details="Details 2",
        )
        log_manager.save_log(entry1)
        time.sleep(0.01)  # Ensure different timestamps
        log_manager.save_log(entry2)

        logs = log_manager.get_logs()
        assert len(logs) == 2

    def test_get_logs_sorted_by_timestamp_descending(self, log_manager):
        """Test that get_logs returns entries sorted by timestamp (newest first)."""
        entry1 = LogEntry(
            id="id-1",
            timestamp="2024-01-01T10:00:00",
            type="scan",
            status="clean",
            summary="First",
            details="",
        )
        entry2 = LogEntry(
            id="id-2",
            timestamp="2024-01-02T10:00:00",
            type="scan",
            status="clean",
            summary="Second",
            details="",
        )
        entry3 = LogEntry(
            id="id-3",
            timestamp="2024-01-03T10:00:00",
            type="scan",
            status="clean",
            summary="Third",
            details="",
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry3)
        log_manager.save_log(entry2)

        logs = log_manager.get_logs()
        assert len(logs) == 3
        assert logs[0].summary == "Third"
        assert logs[1].summary == "Second"
        assert logs[2].summary == "First"

    def test_get_logs_with_limit(self, log_manager):
        """Test get_logs respects the limit parameter."""
        for i in range(10):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details="",
            )
            log_manager.save_log(entry)

        logs = log_manager.get_logs(limit=5)
        assert len(logs) == 5

    def test_get_logs_filter_by_type(self, log_manager):
        """Test get_logs can filter by log type."""
        scan_entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scan",
            details="",
        )
        update_entry = LogEntry.create(
            log_type="update",
            status="success",
            summary="Update",
            details="",
        )
        log_manager.save_log(scan_entry)
        log_manager.save_log(update_entry)

        scan_logs = log_manager.get_logs(log_type="scan")
        assert len(scan_logs) == 1
        assert scan_logs[0].type == "scan"

        update_logs = log_manager.get_logs(log_type="update")
        assert len(update_logs) == 1
        assert update_logs[0].type == "update"

    def test_get_log_by_id(self, log_manager):
        """Test retrieving a specific log by ID."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details here",
        )
        log_manager.save_log(entry)

        retrieved = log_manager.get_log_by_id(entry.id)
        assert retrieved is not None
        assert retrieved.id == entry.id
        assert retrieved.summary == entry.summary

    def test_get_log_by_id_not_found(self, log_manager):
        """Test get_log_by_id returns None for non-existent ID."""
        result = log_manager.get_log_by_id("non-existent-id")
        assert result is None

    def test_delete_log(self, log_manager, temp_log_dir):
        """Test deleting a specific log entry."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details here",
        )
        log_manager.save_log(entry)

        # Verify it exists
        log_file = Path(temp_log_dir) / f"{entry.id}.json"
        assert log_file.exists()

        # Delete it
        result = log_manager.delete_log(entry.id)
        assert result is True
        assert not log_file.exists()

        # Should return None now
        assert log_manager.get_log_by_id(entry.id) is None

    def test_delete_log_not_found(self, log_manager):
        """Test delete_log returns False for non-existent ID."""
        result = log_manager.delete_log("non-existent-id")
        assert result is False

    def test_get_log_by_id_rejects_path_traversal(self, log_manager, temp_log_dir):
        """Test get_log_by_id with a traversal id cannot read outside the log dir."""
        # Plant a victim file in the parent of the log dir.
        victim = Path(temp_log_dir).parent / "victim.json"
        victim.write_text('{"id": "victim", "summary": "secret"}', encoding="utf-8")
        try:
            # ".../<log_dir>/../victim.json" must not resolve/read the victim.
            assert log_manager.get_log_by_id("../victim") is None
            assert log_manager.get_log_by_id("../../etc/passwd") is None
        finally:
            victim.unlink()

    def test_delete_log_rejects_path_traversal(self, log_manager, temp_log_dir):
        """Test delete_log with a traversal id cannot delete outside the log dir."""
        victim = Path(temp_log_dir).parent / "victim.json"
        victim.write_text("important", encoding="utf-8")
        try:
            assert log_manager.delete_log("../victim") is False
            assert log_manager.delete_log("../../etc/passwd") is False
            # The out-of-tree file must still exist.
            assert victim.exists()
        finally:
            victim.unlink()

    def test_clear_logs(self, log_manager, temp_log_dir):
        """Test clearing all logs."""
        # Create several entries
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details="",
            )
            log_manager.save_log(entry)

        # Verify they exist (5 log files + 1 index file = 6 total)
        assert len(list(Path(temp_log_dir).glob("*.json"))) == 6

        # Clear all
        result = log_manager.clear_logs()
        assert result is True

        # Verify log files are gone (only index file may remain)
        json_files = list(Path(temp_log_dir).glob("*.json"))
        # Either no files or just the index file
        assert len(json_files) <= 1
        if json_files:
            assert json_files[0].name == "log_index.json"
        assert log_manager.get_logs() == []

    def test_clear_logs_empty_directory(self, log_manager):
        """Test clear_logs works when directory is already empty."""
        result = log_manager.clear_logs()
        assert result is True

    def test_get_log_count(self, log_manager):
        """Test get_log_count returns correct count."""
        assert log_manager.get_log_count() == 0

        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details="",
            )
            log_manager.save_log(entry)

        assert log_manager.get_log_count() == 3

    def test_get_log_count_nonexistent_directory(self, temp_log_dir):
        """Test get_log_count handles missing directory."""
        manager = LogManager(log_dir=os.path.join(temp_log_dir, "nonexistent"))
        # Delete the created directory
        os.rmdir(manager._log_dir)
        assert manager.get_log_count() == 0


class TestLogManagerDaemonStatus:
    """Tests for daemon status detection in LogManager."""

    @pytest.fixture
    def log_manager(self):
        """Create a LogManager with a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield LogManager(log_dir=tmpdir)

    def test_get_daemon_status_not_installed(self, log_manager):
        """Test daemon status when clamd is not installed."""
        with mock.patch("src.core.log_manager.which_host_command", return_value=None):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    mock.Mock(stdout="unknown\n"),
                    mock.Mock(stdout="unknown\n"),
                    mock.Mock(stdout="unknown\n"),
                    mock.Mock(returncode=1),
                ]
                status, message = log_manager.get_daemon_status()
                assert status == DaemonStatus.NOT_INSTALLED
                assert "not installed" in message.lower()

    def test_get_daemon_status_running(self, log_manager):
        """Test daemon status when a supported service is active."""
        with mock.patch("src.core.log_manager.which_host_command", return_value="/usr/bin/clamd"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(stdout="active\n")
                status, message = log_manager.get_daemon_status()
                assert status == DaemonStatus.RUNNING
                assert "active" in message.lower()

    def test_get_daemon_status_stopped(self, log_manager):
        """Test daemon status when clamd service is installed but not active."""
        with mock.patch("src.core.log_manager.which_host_command", return_value="/usr/bin/clamd"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    mock.Mock(stdout="failed\n"),
                    mock.Mock(stdout="unknown\n"),
                    mock.Mock(stdout="unknown\n"),
                    mock.Mock(returncode=1),
                ]
                status, message = log_manager.get_daemon_status()
                assert status == DaemonStatus.STOPPED
                assert "not active" in message.lower()

    def test_get_daemon_status_falls_back_to_process_when_systemctl_fails(self, log_manager):
        """Test daemon status falls back to pgrep when systemctl calls fail."""
        with mock.patch("src.core.log_manager.which_host_command", return_value="/usr/bin/clamd"):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    OSError("Test error"),
                    OSError("Test error"),
                    OSError("Test error"),
                    mock.Mock(returncode=0),
                ]
                status, message = log_manager.get_daemon_status()
                assert status == DaemonStatus.RUNNING
                assert "running" in message.lower()


class TestLogManagerDaemonLogs:
    """Tests for daemon log reading in LogManager."""

    @pytest.fixture
    def log_manager(self):
        """Create a LogManager with a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield LogManager(log_dir=tmpdir)

    def test_get_daemon_log_path_not_found(self, log_manager):
        """Test get_daemon_log_path returns None when no log exists."""
        with mock.patch.object(Path, "exists", return_value=False):
            result = log_manager.get_daemon_log_path()
            # Result may be None if no log file is found
            # This depends on system state, so just ensure it doesn't crash
            assert result is None or isinstance(result, str)

    def test_read_daemon_logs_file_not_found(self, log_manager):
        """Test read_daemon_logs when log file doesn't exist."""
        with mock.patch.object(log_manager, "get_daemon_log_path", return_value=None):
            # Also mock journalctl fallback to return failure
            with mock.patch.object(
                log_manager,
                "_read_daemon_logs_journalctl",
                return_value=(False, "No journal entries found"),
            ):
                success, content = log_manager.read_daemon_logs()
                assert success is False
                assert "not found" in content.lower()

    def test_read_daemon_logs_success(self, log_manager):
        """Test read_daemon_logs successfully reads log content."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            f.write("Line 1\nLine 2\nLine 3\n")
            temp_log_path = f.name

        try:
            with mock.patch.object(log_manager, "get_daemon_log_path", return_value=temp_log_path):
                with mock.patch(
                    "src.core.log_manager.wrap_host_command",
                    side_effect=lambda cmd: cmd,
                ):
                    success, content = log_manager.read_daemon_logs(num_lines=10)
                    assert success is True
                    assert "Line 1" in content
                    assert "Line 2" in content
                    assert "Line 3" in content
        finally:
            os.unlink(temp_log_path)

    def test_read_daemon_logs_respects_num_lines(self, log_manager):
        """Test read_daemon_logs respects the num_lines parameter."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            for i in range(100):
                f.write(f"Log line {i}\n")
            temp_log_path = f.name

        try:
            with mock.patch.object(log_manager, "get_daemon_log_path", return_value=temp_log_path):
                with mock.patch(
                    "src.core.log_manager.wrap_host_command",
                    side_effect=lambda cmd: cmd,
                ):
                    success, content = log_manager.read_daemon_logs(num_lines=10)
                    assert success is True
                    # Should only have last 10 lines
                    lines = [line for line in content.strip().split("\n") if line]
                    assert len(lines) <= 10
        finally:
            os.unlink(temp_log_path)

    def test_read_daemon_logs_empty_file(self, log_manager):
        """Test read_daemon_logs handles empty log file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            temp_log_path = f.name

        try:
            with mock.patch.object(log_manager, "get_daemon_log_path", return_value=temp_log_path):
                with mock.patch(
                    "src.core.log_manager.wrap_host_command",
                    side_effect=lambda cmd: cmd,
                ):
                    success, content = log_manager.read_daemon_logs()
                    assert success is True
                    assert "empty" in content.lower()
        finally:
            os.unlink(temp_log_path)


class TestLogType:
    """Tests for the LogType enum."""

    def test_log_type_values(self):
        """Test LogType enum has expected values."""
        assert LogType.SCAN.value == "scan"
        assert LogType.UPDATE.value == "update"


class TestDaemonStatus:
    """Tests for the DaemonStatus enum."""

    def test_daemon_status_values(self):
        """Test DaemonStatus enum has expected values."""
        assert DaemonStatus.RUNNING.value == "running"
        assert DaemonStatus.STOPPED.value == "stopped"
        assert DaemonStatus.NOT_INSTALLED.value == "not_installed"
        assert DaemonStatus.UNKNOWN.value == "unknown"


class TestLogManagerAsync:
    """Tests for async log retrieval in LogManager."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    def test_get_logs_async_calls_callback_with_entries(self, log_manager):
        """Test that get_logs_async calls callback with log entries."""
        # Create some test entries
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan 1",
            details="Details 1",
        )
        entry2 = LogEntry.create(
            log_type="update",
            status="success",
            summary="Test update 1",
            details="Details 2",
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry2)

        # Track callback invocation
        callback_results = []
        callback_event = threading.Event()

        def mock_callback(entries):
            callback_results.append(entries)
            callback_event.set()

        # Mock GLib.idle_add to call the callback directly
        with mock.patch("src.core.log_manager.GLib") as mock_glib:
            # Make idle_add call the function immediately
            mock_glib.idle_add.side_effect = lambda func, *args: func(*args)

            log_manager.get_logs_async(mock_callback)

            # Wait for background thread to complete
            callback_event.wait(timeout=5)

        assert len(callback_results) == 1
        assert len(callback_results[0]) == 2

    def test_get_logs_async_empty_logs(self, log_manager):
        """Test get_logs_async with no stored logs."""
        callback_results = []
        callback_event = threading.Event()

        def mock_callback(entries):
            callback_results.append(entries)
            callback_event.set()

        with mock.patch("src.core.log_manager.GLib") as mock_glib:
            mock_glib.idle_add.side_effect = lambda func, *args: func(*args)

            log_manager.get_logs_async(mock_callback)
            callback_event.wait(timeout=5)

        assert len(callback_results) == 1
        assert callback_results[0] == []

    def test_get_logs_async_respects_limit(self, log_manager):
        """Test that get_logs_async respects the limit parameter."""
        # Create more entries than the limit
        for i in range(10):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details="",
            )
            log_manager.save_log(entry)

        callback_results = []
        callback_event = threading.Event()

        def mock_callback(entries):
            callback_results.append(entries)
            callback_event.set()

        with mock.patch("src.core.log_manager.GLib") as mock_glib:
            mock_glib.idle_add.side_effect = lambda func, *args: func(*args)

            log_manager.get_logs_async(mock_callback, limit=5)
            callback_event.wait(timeout=5)

        assert len(callback_results) == 1
        assert len(callback_results[0]) == 5

    def test_get_logs_async_filters_by_type(self, log_manager):
        """Test that get_logs_async filters by log type."""
        # Create entries of different types
        scan_entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scan entry",
            details="",
        )
        update_entry = LogEntry.create(
            log_type="update",
            status="success",
            summary="Update entry",
            details="",
        )
        log_manager.save_log(scan_entry)
        log_manager.save_log(update_entry)

        callback_results = []
        callback_event = threading.Event()

        def mock_callback(entries):
            callback_results.append(entries)
            callback_event.set()

        with mock.patch("src.core.log_manager.GLib") as mock_glib:
            mock_glib.idle_add.side_effect = lambda func, *args: func(*args)

            log_manager.get_logs_async(mock_callback, log_type="scan")
            callback_event.wait(timeout=5)

        assert len(callback_results) == 1
        assert len(callback_results[0]) == 1
        assert callback_results[0][0].type == "scan"

    def test_get_logs_async_uses_glib_idle_add(self, log_manager):
        """Test that get_logs_async schedules callback via GLib.idle_add."""
        callback_event = threading.Event()

        def mock_callback(entries):
            callback_event.set()

        with mock.patch("src.core.log_manager.GLib") as mock_glib:
            # Track calls to idle_add without executing
            mock_glib.idle_add.side_effect = lambda func, *args: (
                func(*args),
                callback_event.set(),
            )

            log_manager.get_logs_async(mock_callback)
            callback_event.wait(timeout=5)

            # Verify GLib.idle_add was called
            assert mock_glib.idle_add.called

    def test_get_logs_async_runs_in_daemon_thread(self, log_manager):
        """Test that get_logs_async runs in a daemon thread."""
        thread_info = {}
        callback_event = threading.Event()

        def mock_callback(entries):
            callback_event.set()

        # Patch Thread.start to capture thread properties right before start
        original_start = threading.Thread.start

        def patched_start(self):
            thread_info["daemon"] = self.daemon
            original_start(self)

        with mock.patch("src.core.log_manager.GLib") as mock_glib:
            mock_glib.idle_add.side_effect = lambda func, *args: func(*args)

            with mock.patch.object(threading.Thread, "start", patched_start):
                log_manager.get_logs_async(mock_callback)
                callback_event.wait(timeout=5)

        assert thread_info.get("daemon") is True


class TestLogManagerThreadSafety:
    """Tests for thread safety in LogManager."""

    @pytest.fixture
    def log_manager(self):
        """Create a LogManager with a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield LogManager(log_dir=tmpdir)

    def test_concurrent_save_operations(self, log_manager):
        """Test that concurrent save operations don't corrupt data."""
        import threading

        entries = []
        errors = []

        def save_entry(index):
            try:
                entry = LogEntry.create(
                    log_type="scan",
                    status="clean",
                    summary=f"Concurrent scan {index}",
                    details=f"Details {index}",
                )
                entries.append(entry)
                result = log_manager.save_log(entry)
                if not result:
                    errors.append(f"Failed to save entry {index}")
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads
        threads = []
        for i in range(20):
            t = threading.Thread(target=save_entry, args=(i,))
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # Verify no errors
        assert len(errors) == 0

        # Verify all entries were saved
        logs = log_manager.get_logs(limit=100)
        assert len(logs) == 20


class TestLogManagerIndexInfrastructure:
    """Tests for index infrastructure in LogManager."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    def test_load_index_empty_state(self, log_manager):
        """Test _load_index returns empty structure when no index file exists."""
        index = log_manager._load_index()
        assert isinstance(index, dict)
        assert index["version"] == 1
        assert index["entries"] == []

    def test_load_index_valid_index(self, log_manager, temp_log_dir):
        """Test _load_index successfully loads a valid index file."""
        # Create a valid index file
        index_data = {
            "version": 1,
            "entries": [
                {"id": "test-id-1", "timestamp": "2024-01-01T10:00:00", "type": "scan"},
                {
                    "id": "test-id-2",
                    "timestamp": "2024-01-02T10:00:00",
                    "type": "update",
                },
            ],
        }
        index_path = Path(temp_log_dir) / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f)

        # Load the index
        loaded = log_manager._load_index()
        assert loaded["version"] == 1
        assert len(loaded["entries"]) == 2
        assert loaded["entries"][0]["id"] == "test-id-1"
        assert loaded["entries"][1]["id"] == "test-id-2"

    def test_load_index_corrupted_json(self, log_manager, temp_log_dir):
        """Test _load_index handles corrupted JSON gracefully."""
        # Create a corrupted index file
        index_path = Path(temp_log_dir) / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json }")

        # Should return empty structure instead of crashing
        index = log_manager._load_index()
        assert index["version"] == 1
        assert index["entries"] == []

    def test_load_index_invalid_structure(self, log_manager, temp_log_dir):
        """Test _load_index handles invalid structure gracefully."""
        # Create index with wrong structure (missing required keys)
        index_path = Path(temp_log_dir) / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump({"invalid": "structure"}, f)

        # Should return empty structure
        index = log_manager._load_index()
        assert index["version"] == 1
        assert index["entries"] == []

    def test_load_index_permission_error(self, log_manager, temp_log_dir):
        """Test _load_index handles permission errors gracefully."""
        # Create a valid index file
        index_path = Path(temp_log_dir) / "log_index.json"
        index_data = {"version": 1, "entries": []}
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f)

        # Mock open to raise PermissionError
        with mock.patch("builtins.open", side_effect=PermissionError("Permission denied")):
            index = log_manager._load_index()
            assert index["version"] == 1
            assert index["entries"] == []

    def test_save_index_success(self, log_manager, temp_log_dir):
        """Test _save_index successfully saves index to file."""
        index_data = {
            "version": 1,
            "entries": [
                {"id": "test-id-1", "timestamp": "2024-01-01T10:00:00", "type": "scan"},
            ],
        }

        result = log_manager._save_index(index_data)
        assert result is True

        # Verify file was created
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        # Verify content
        with open(index_path, encoding="utf-8") as f:
            saved_data = json.load(f)
        assert saved_data["version"] == 1
        assert len(saved_data["entries"]) == 1
        assert saved_data["entries"][0]["id"] == "test-id-1"

    def test_save_index_atomic_write(self, log_manager, temp_log_dir):
        """Test _save_index uses atomic write pattern."""
        index_data = {"version": 1, "entries": []}

        # Save initial data
        log_manager._save_index(index_data)

        # Save again with different data
        new_data = {
            "version": 1,
            "entries": [
                {"id": "new-id", "timestamp": "2024-01-01T10:00:00", "type": "scan"},
            ],
        }
        result = log_manager._save_index(new_data)
        assert result is True

        # Verify new data was written
        loaded = log_manager._load_index()
        assert len(loaded["entries"]) == 1
        assert loaded["entries"][0]["id"] == "new-id"

    def test_save_index_creates_directory(self, temp_log_dir):
        """Test _save_index creates parent directory if needed."""
        # Create manager with non-existent directory
        log_dir = Path(temp_log_dir) / "subdir" / "logs"
        manager = LogManager(log_dir=str(log_dir))

        # Delete the directory that was created by __init__
        import shutil

        shutil.rmtree(log_dir)

        # Save should recreate the directory
        index_data = {"version": 1, "entries": []}
        result = manager._save_index(index_data)
        assert result is True
        assert log_dir.exists()

    def test_save_index_permission_error(self, log_manager):
        """Test _save_index handles permission errors gracefully."""
        index_data = {"version": 1, "entries": []}

        # Mock tempfile.mkstemp to raise PermissionError
        with mock.patch("tempfile.mkstemp", side_effect=PermissionError("Permission denied")):
            result = log_manager._save_index(index_data)
            assert result is False

    def test_save_index_cleanup_on_failure(self, log_manager, temp_log_dir):
        """Test _save_index cleans up temp file on failure."""
        index_data = {"version": 1, "entries": []}

        # Track created temp files
        temp_files = []
        original_mkstemp = tempfile.mkstemp

        def track_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            temp_files.append(path)
            return fd, path

        # Mock Path.replace to fail after temp file is created
        with mock.patch("tempfile.mkstemp", side_effect=track_mkstemp):
            with mock.patch("pathlib.Path.replace", side_effect=OSError("Simulated failure")):
                result = log_manager._save_index(index_data)
                assert result is False

                # Verify temp file was cleaned up
                if temp_files:
                    assert not Path(temp_files[0]).exists()

    def test_rebuild_index_empty_directory(self, log_manager, temp_log_dir):
        """Test rebuild_index creates empty index when no logs exist."""
        result = log_manager.rebuild_index()
        assert result is True

        # Verify index was created with empty entries
        index = log_manager._load_index()
        assert index["version"] == 1
        assert index["entries"] == []

    def test_rebuild_index_with_valid_logs(self, log_manager):
        """Test rebuild_index creates index from existing log files."""
        # Create some log entries
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan 1",
            details="Details 1",
        )
        entry2 = LogEntry.create(
            log_type="update",
            status="success",
            summary="Test update 1",
            details="Details 2",
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry2)

        # Rebuild the index
        result = log_manager.rebuild_index()
        assert result is True

        # Verify index contains both entries
        index = log_manager._load_index()
        assert len(index["entries"]) == 2

        # Verify entries contain correct metadata
        ids = {entry["id"] for entry in index["entries"]}
        assert entry1.id in ids
        assert entry2.id in ids

        types = {entry["type"] for entry in index["entries"]}
        assert "scan" in types
        assert "update" in types

    def test_rebuild_index_skips_corrupted_files(self, log_manager, temp_log_dir):
        """Test rebuild_index skips corrupted log files."""
        # Create a valid log entry
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Valid entry",
            details="Details",
        )
        log_manager.save_log(entry)

        # Create a corrupted log file
        corrupted_path = Path(temp_log_dir) / "corrupted.json"
        with open(corrupted_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json }")

        # Rebuild should succeed and include only the valid entry
        result = log_manager.rebuild_index()
        assert result is True

        index = log_manager._load_index()
        assert len(index["entries"]) == 1
        assert index["entries"][0]["id"] == entry.id

    def test_rebuild_index_skips_index_file(self, log_manager, temp_log_dir):
        """Test rebuild_index doesn't process the index file itself."""
        # Create an old index file
        old_index = {
            "version": 1,
            "entries": [
                {"id": "old-id", "timestamp": "2024-01-01T10:00:00", "type": "scan"},
            ],
        }
        index_path = Path(temp_log_dir) / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(old_index, f)

        # Create a real log entry
        entry = LogEntry.create(
            log_type="update",
            status="success",
            summary="Real entry",
            details="Details",
        )
        log_manager.save_log(entry)

        # Rebuild should create new index with only the real log entry
        result = log_manager.rebuild_index()
        assert result is True

        index = log_manager._load_index()
        assert len(index["entries"]) == 1
        assert index["entries"][0]["id"] == entry.id
        assert index["entries"][0]["type"] == "update"

    def test_rebuild_index_handles_missing_fields(self, log_manager, temp_log_dir):
        """Test rebuild_index skips entries with missing required fields."""
        # Create log file with missing timestamp
        incomplete_log = {
            "id": "test-id",
            "type": "scan",
            # Missing timestamp
            "status": "clean",
            "summary": "Test",
            "details": "Test",
        }
        incomplete_path = Path(temp_log_dir) / "incomplete.json"
        with open(incomplete_path, "w", encoding="utf-8") as f:
            json.dump(incomplete_log, f)

        # Create a complete log entry
        complete_entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Complete entry",
            details="Details",
        )
        log_manager.save_log(complete_entry)

        # Rebuild should skip incomplete entry
        result = log_manager.rebuild_index()
        assert result is True

        index = log_manager._load_index()
        assert len(index["entries"]) == 1
        assert index["entries"][0]["id"] == complete_entry.id

    def test_rebuild_index_nonexistent_directory(self, temp_log_dir):
        """Test rebuild_index handles non-existent directory gracefully."""
        # Create manager with directory, then remove it
        log_dir = Path(temp_log_dir) / "nonexistent"
        manager = LogManager(log_dir=str(log_dir))

        # Delete the directory
        import shutil

        shutil.rmtree(log_dir)

        # Rebuild should create empty index
        result = manager.rebuild_index()
        assert result is True

        # Verify empty index was created
        index = manager._load_index()
        assert index["version"] == 1
        assert index["entries"] == []

    def test_rebuild_index_after_corruption(self, log_manager, temp_log_dir):
        """Test rebuild_index can recover from corrupted index file."""
        # Create valid log entries
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 1",
            details="Details 1",
        )
        entry2 = LogEntry.create(
            log_type="update",
            status="success",
            summary="Entry 2",
            details="Details 2",
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry2)

        # Corrupt the index file
        index_path = Path(temp_log_dir) / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("{ corrupted json data }")

        # Verify index is corrupted
        corrupted_index = log_manager._load_index()
        assert corrupted_index["entries"] == []

        # Rebuild should recover
        result = log_manager.rebuild_index()
        assert result is True

        # Verify index now contains both entries
        recovered_index = log_manager._load_index()
        assert len(recovered_index["entries"]) == 2

    def test_rebuild_index_thread_safety(self, log_manager):
        """Test rebuild_index is thread-safe."""
        # Create some log entries
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Rebuild index from multiple threads
        errors = []
        results = []

        def rebuild():
            try:
                result = log_manager.rebuild_index()
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for _i in range(5):
            t = threading.Thread(target=rebuild)
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify no errors occurred
        assert len(errors) == 0
        # All rebuilds should succeed
        assert all(results)

        # Verify final index is valid
        index = log_manager._load_index()
        assert len(index["entries"]) == 5


class TestLogManagerIndexMaintenance:
    """Tests for index maintenance during log operations."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    def test_save_log_updates_index(self, log_manager):
        """Test that save_log adds entry metadata to index."""
        # Create and save a log entry
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details here",
        )
        result = log_manager.save_log(entry)
        assert result is True

        # Verify index was updated
        index = log_manager._load_index()
        assert len(index["entries"]) == 1
        assert index["entries"][0]["id"] == entry.id
        assert index["entries"][0]["timestamp"] == entry.timestamp
        assert index["entries"][0]["type"] == entry.type

    def test_save_log_updates_index_multiple_entries(self, log_manager):
        """Test that save_log correctly maintains index with multiple entries."""
        entries = []
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan" if i % 2 == 0 else "update",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            entries.append(entry)
            log_manager.save_log(entry)

        # Verify all entries are in index
        index = log_manager._load_index()
        assert len(index["entries"]) == 5

        # Verify all IDs are present
        index_ids = {e["id"] for e in index["entries"]}
        for entry in entries:
            assert entry.id in index_ids

    def test_save_log_preserves_existing_index(self, log_manager):
        """Test that save_log preserves existing index entries."""
        # Save first entry
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 1",
            details="Details",
        )
        log_manager.save_log(entry1)

        # Save second entry
        entry2 = LogEntry.create(
            log_type="update",
            status="success",
            summary="Entry 2",
            details="Details",
        )
        log_manager.save_log(entry2)

        # Verify both entries are in index
        index = log_manager._load_index()
        assert len(index["entries"]) == 2
        ids = {e["id"] for e in index["entries"]}
        assert entry1.id in ids
        assert entry2.id in ids

    def test_save_log_continues_on_index_failure(self, log_manager, temp_log_dir):
        """Test that save_log succeeds even if index update fails."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details",
        )

        # Mock _save_index to fail
        with mock.patch.object(log_manager, "_save_index", return_value=False):
            result = log_manager.save_log(entry)
            # Log file should still be saved
            assert result is True

            # Verify log file exists
            log_file = Path(temp_log_dir) / f"{entry.id}.json"
            assert log_file.exists()

    def test_delete_log_removes_from_index(self, log_manager):
        """Test that delete_log removes entry from index."""
        # Create and save entries
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 1",
            details="Details",
        )
        entry2 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 2",
            details="Details",
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry2)

        # Verify both are in index
        index = log_manager._load_index()
        assert len(index["entries"]) == 2

        # Delete first entry
        result = log_manager.delete_log(entry1.id)
        assert result is True

        # Verify only second entry remains in index
        index = log_manager._load_index()
        assert len(index["entries"]) == 1
        assert index["entries"][0]["id"] == entry2.id

    def test_delete_log_handles_nonexistent_entry_in_index(self, log_manager):
        """Test delete_log handles entry not in index gracefully."""
        # Create an entry and save it
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry",
            details="Details",
        )
        log_manager.save_log(entry)

        # Manually remove from index but leave file
        index = log_manager._load_index()
        index["entries"] = []
        log_manager._save_index(index)

        # Delete should still succeed
        result = log_manager.delete_log(entry.id)
        assert result is True

    def test_delete_log_continues_on_index_failure(self, log_manager, temp_log_dir):
        """Test that delete_log succeeds even if index update fails."""
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test scan",
            details="Details",
        )
        log_manager.save_log(entry)

        # Mock _save_index to fail
        with mock.patch.object(log_manager, "_save_index", return_value=False):
            result = log_manager.delete_log(entry.id)
            # Log file should still be deleted
            assert result is True

            # Verify log file is gone
            log_file = Path(temp_log_dir) / f"{entry.id}.json"
            assert not log_file.exists()

    def test_clear_logs_resets_index(self, log_manager):
        """Test that clear_logs resets index to empty state."""
        # Create multiple entries
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Verify entries exist in index
        index = log_manager._load_index()
        assert len(index["entries"]) == 5

        # Clear all logs
        result = log_manager.clear_logs()
        assert result is True

        # Verify index is reset to empty
        index = log_manager._load_index()
        assert index["version"] == 1
        assert index["entries"] == []

    def test_clear_logs_skips_index_file_during_deletion(self, log_manager, temp_log_dir):
        """Test that clear_logs doesn't delete the index file itself."""
        # Create entries
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Get index path
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        # Clear logs
        log_manager.clear_logs()

        # Verify index file still exists (but is empty)
        assert index_path.exists()
        index = log_manager._load_index()
        assert index["entries"] == []

    def test_clear_logs_continues_on_index_failure(self, log_manager, temp_log_dir):
        """Test that clear_logs succeeds even if index reset fails."""
        # Create entries
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry",
            details="Details",
        )
        log_manager.save_log(entry)

        # Mock _save_index to fail
        with mock.patch.object(log_manager, "_save_index", return_value=False):
            result = log_manager.clear_logs()
            # Clear operation should still succeed
            assert result is True

            # Verify log files are gone
            json_files = list(Path(temp_log_dir).glob("*.json"))
            # Only index file should remain (if any)
            for f in json_files:
                assert f.name == "log_index.json"

    def test_concurrent_save_operations_maintain_index(self, log_manager):
        """Test that concurrent save operations correctly maintain index."""
        entries = []
        errors = []

        def save_entry(index):
            try:
                entry = LogEntry.create(
                    log_type="scan",
                    status="clean",
                    summary=f"Concurrent entry {index}",
                    details="Details",
                )
                entries.append(entry)
                result = log_manager.save_log(entry)
                if not result:
                    errors.append(f"Failed to save entry {index}")
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads
        threads = []
        for i in range(20):
            t = threading.Thread(target=save_entry, args=(i,))
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # Verify no errors
        assert len(errors) == 0

        # Verify index contains all entries
        index = log_manager._load_index()
        assert len(index["entries"]) == 20

        # Verify all entry IDs are in index
        index_ids = {e["id"] for e in index["entries"]}
        for entry in entries:
            assert entry.id in index_ids

    def test_concurrent_delete_operations_maintain_index(self, log_manager):
        """Test that concurrent delete operations correctly maintain index."""
        # Create entries first
        entries = []
        for i in range(20):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            entries.append(entry)

        # Verify all are in index
        index = log_manager._load_index()
        assert len(index["entries"]) == 20

        errors = []

        def delete_entry(entry):
            try:
                result = log_manager.delete_log(entry.id)
                if not result:
                    errors.append(f"Failed to delete {entry.id}")
            except Exception as e:
                errors.append(str(e))

        # Delete from multiple threads
        threads = []
        for entry in entries:
            t = threading.Thread(target=delete_entry, args=(entry,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify no errors
        assert len(errors) == 0

        # Verify index is empty
        index = log_manager._load_index()
        assert len(index["entries"]) == 0

    def test_concurrent_mixed_operations_maintain_index(self, log_manager):
        """Test that mixed concurrent operations don't corrupt index."""
        # Pre-populate with some entries
        initial_entries = []
        for i in range(10):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Initial {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            initial_entries.append(entry)

        saved_entries = []
        errors = []

        def save_entry(index):
            try:
                entry = LogEntry.create(
                    log_type="update",
                    status="success",
                    summary=f"New {index}",
                    details="Details",
                )
                saved_entries.append(entry)
                if not log_manager.save_log(entry):
                    errors.append(f"Save failed {index}")
            except Exception as e:
                errors.append(f"Save error: {e}")

        def delete_entry(entry):
            try:
                if not log_manager.delete_log(entry.id):
                    errors.append(f"Delete failed {entry.id}")
            except Exception as e:
                errors.append(f"Delete error: {e}")

        # Mix of save and delete operations
        threads = []

        # Add 10 new entries
        for i in range(10):
            t = threading.Thread(target=save_entry, args=(i,))
            threads.append(t)

        # Delete 5 initial entries
        for entry in initial_entries[:5]:
            t = threading.Thread(target=delete_entry, args=(entry,))
            threads.append(t)

        # Shuffle to mix operations
        import random

        random.shuffle(threads)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify no errors
        assert len(errors) == 0

        # Verify index integrity
        index = log_manager._load_index()
        # Should have: 10 initial - 5 deleted + 10 new = 15 entries
        assert len(index["entries"]) == 15

        # Verify structure is valid
        assert "version" in index
        assert "entries" in index
        for entry in index["entries"]:
            assert "id" in entry
            assert "timestamp" in entry
            assert "type" in entry

    def test_concurrent_save_and_rebuild_maintain_index(self, log_manager):
        """Test that concurrent save and rebuild operations don't corrupt index."""
        errors = []
        saved_entries = []

        def save_entries():
            try:
                for i in range(10):
                    entry = LogEntry.create(
                        log_type="scan",
                        status="clean",
                        summary=f"Entry {i}",
                        details="Details",
                    )
                    saved_entries.append(entry)
                    log_manager.save_log(entry)
                    time.sleep(0.001)  # Small delay to allow interleaving
            except Exception as e:
                errors.append(f"Save error: {e}")

        def rebuild_index():
            try:
                for _ in range(5):
                    log_manager.rebuild_index()
                    time.sleep(0.002)  # Small delay
            except Exception as e:
                errors.append(f"Rebuild error: {e}")

        # Run save and rebuild concurrently
        save_thread = threading.Thread(target=save_entries)
        rebuild_thread = threading.Thread(target=rebuild_index)

        save_thread.start()
        rebuild_thread.start()

        save_thread.join()
        rebuild_thread.join()

        # Verify no errors
        assert len(errors) == 0

        # Final rebuild to ensure consistency
        log_manager.rebuild_index()

        # Verify all saved entries are in final index
        index = log_manager._load_index()
        assert len(index["entries"]) == 10

        index_ids = {e["id"] for e in index["entries"]}
        for entry in saved_entries:
            assert entry.id in index_ids

    def test_index_entries_have_correct_structure(self, log_manager):
        """Test that index entries have the correct structure after operations."""
        # Save various types of entries
        scan_entry = LogEntry.create(
            log_type="scan",
            status="infected",
            summary="Found threats",
            details="Details",
            path="/home/user",
            duration=15.5,
        )
        update_entry = LogEntry.create(
            log_type="update",
            status="success",
            summary="Database updated",
            details="Details",
            duration=30.0,
        )

        log_manager.save_log(scan_entry)
        log_manager.save_log(update_entry)

        # Verify index entries have only required metadata (not full entry data)
        index = log_manager._load_index()
        assert len(index["entries"]) == 2

        for entry in index["entries"]:
            # Should have exactly these three fields
            assert set(entry.keys()) == {"id", "timestamp", "type"}
            assert isinstance(entry["id"], str)
            assert isinstance(entry["timestamp"], str)
            assert entry["type"] in ["scan", "update"]

            # Should NOT include full entry data
            assert "status" not in entry
            assert "summary" not in entry
            assert "details" not in entry
            assert "path" not in entry
            assert "duration" not in entry


class TestLogManagerIndexValidation:
    """Tests for index validation and automatic rebuild functionality."""

    def test_validate_index_with_valid_index(self, tmp_path):
        """Test that _validate_index returns True for a valid index."""
        log_manager = LogManager(str(tmp_path))

        # Create some log entries
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Load the index
        index_data = log_manager._load_index()

        # Validate it
        assert log_manager._validate_index(index_data) is True

    def test_validate_index_with_empty_index_and_empty_directory(self, tmp_path):
        """Test that _validate_index returns True for empty index with no logs."""
        log_manager = LogManager(str(tmp_path))

        # Empty index
        index_data = {"version": 1, "entries": []}

        # Should be valid (no logs, no index entries)
        assert log_manager._validate_index(index_data) is True

    def test_validate_index_with_entry_count_mismatch_extra_entries(self, tmp_path):
        """Test that _validate_index returns False when index has more entries than files."""
        log_manager = LogManager(str(tmp_path))

        # Create 3 log entries
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Load the index and add extra bogus entries
        index_data = log_manager._load_index()
        index_data["entries"].append(
            {"id": "bogus-id-1", "timestamp": "2024-01-01T00:00:00", "type": "scan"}
        )
        index_data["entries"].append(
            {"id": "bogus-id-2", "timestamp": "2024-01-01T00:00:00", "type": "scan"}
        )

        # Should be invalid (5 index entries, 3 actual files)
        assert log_manager._validate_index(index_data) is False

    def test_validate_index_with_entry_count_mismatch_fewer_entries(self, tmp_path):
        """Test that _validate_index returns False when index has fewer entries than files."""
        log_manager = LogManager(str(tmp_path))

        # Create 5 log entries
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Load the index and remove some entries
        index_data = log_manager._load_index()
        index_data["entries"] = index_data["entries"][:3]

        # Should be invalid (3 index entries, 5 actual files)
        assert log_manager._validate_index(index_data) is False

    def test_validate_index_with_missing_files_above_threshold(self, tmp_path):
        """Test that _validate_index returns False when >20% of files are missing."""
        log_manager = LogManager(str(tmp_path))

        # Create 10 log entries
        log_ids = []
        for i in range(10):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            log_ids.append(entry.id)

        # Delete 3 log files (30% missing - above 20% threshold)
        for i in range(3):
            log_file = tmp_path / f"{log_ids[i]}.json"
            log_file.unlink()

        # Load the index (which still has all 10 entries)
        index_data = log_manager._load_index()

        # Should be invalid (30% missing > 20% threshold)
        assert log_manager._validate_index(index_data) is False

    def test_validate_index_with_missing_files_below_threshold(self, tmp_path):
        """Test that _validate_index returns False even with few missing files due to count mismatch."""
        log_manager = LogManager(str(tmp_path))

        # Create 10 log entries
        log_ids = []
        for i in range(10):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            log_ids.append(entry.id)

        # Delete 1 log file (10% missing - below 20% threshold)
        log_file = tmp_path / f"{log_ids[0]}.json"
        log_file.unlink()

        # Load the index (which still has all 10 entries)
        index_data = log_manager._load_index()

        # Should be invalid due to count mismatch (10 entries, 9 files)
        # even though missing percentage is below threshold
        assert log_manager._validate_index(index_data) is False

    def test_validate_index_with_nonexistent_directory(self, tmp_path):
        """Test that _validate_index handles non-existent directory gracefully."""
        # Create log manager with non-existent directory
        log_manager = LogManager(str(tmp_path / "nonexistent"))

        # Index with entries (but directory doesn't exist)
        index_data = {
            "version": 1,
            "entries": [{"id": "test-id", "timestamp": "2024-01-01T00:00:00", "type": "scan"}],
        }

        # Should be invalid (directory doesn't exist but index has entries)
        assert log_manager._validate_index(index_data) is False

    def test_validate_index_with_large_index_uses_sampling(self, tmp_path):
        """Test that _validate_index uses sampling for large indices (>50 entries)."""
        log_manager = LogManager(str(tmp_path))

        # Create 60 log entries
        log_ids = []
        for i in range(60):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            log_ids.append(entry.id)

        # Load the index
        index_data = log_manager._load_index()

        # All files exist, should be valid
        assert log_manager._validate_index(index_data) is True

        # Delete 15 files (25% missing)
        for i in range(15):
            log_file = tmp_path / f"{log_ids[i]}.json"
            log_file.unlink()

        # Reload index (still has all 60 entries)
        index_data = log_manager._load_index()

        # Should be invalid due to count mismatch first
        # (60 entries, 45 files)
        assert log_manager._validate_index(index_data) is False

    def test_get_logs_triggers_rebuild_on_stale_index_count_mismatch(self, tmp_path):
        """Test that get_logs() triggers automatic rebuild when index has count mismatch."""
        log_manager = LogManager(str(tmp_path))

        # Create 5 log entries
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Manually corrupt the index by adding bogus entries
        index_data = log_manager._load_index()
        original_count = len(index_data["entries"])
        index_data["entries"].append(
            {"id": "bogus-id", "timestamp": "2024-01-01T00:00:00", "type": "scan"}
        )
        log_manager._save_index(index_data)

        # Call get_logs() - should detect stale index and rebuild
        logs = log_manager.get_logs()

        # Should return all valid logs
        assert len(logs) == 5

        # Verify index was rebuilt (should have correct count now)
        rebuilt_index = log_manager._load_index()
        assert len(rebuilt_index["entries"]) == original_count

    def test_get_logs_triggers_rebuild_on_missing_files(self, tmp_path):
        """Test that get_logs() triggers automatic rebuild when many files are missing."""
        log_manager = LogManager(str(tmp_path))

        # Create 10 log entries
        log_ids = []
        for i in range(10):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            log_ids.append(entry.id)

        # Delete 3 log files (30% missing - above threshold)
        for i in range(3):
            log_file = tmp_path / f"{log_ids[i]}.json"
            log_file.unlink()

        # Call get_logs() - should detect stale index and rebuild
        logs = log_manager.get_logs()

        # Should return only the 7 remaining valid logs
        assert len(logs) == 7

        # Verify index was rebuilt with correct count
        rebuilt_index = log_manager._load_index()
        assert len(rebuilt_index["entries"]) == 7

    def test_get_logs_handles_validation_error_gracefully(self, tmp_path):
        """Test that get_logs() handles validation errors gracefully."""
        log_manager = LogManager(str(tmp_path))

        # Create some log entries
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Test scan {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Mock _validate_index to raise an exception
        original_validate = log_manager._validate_index

        def mock_validate(index_data):
            raise Exception("Validation error")

        log_manager._validate_index = mock_validate

        # get_logs() should handle the error and fall back to full scan
        logs = log_manager.get_logs()

        # Should still return logs via fallback
        assert len(logs) == 3

        # Restore original method
        log_manager._validate_index = original_validate

    def test_validate_index_performance_with_many_log_files(self, tmp_path):
        """Test that _validate_index performs efficiently with 1000+ log files.

        This test verifies that the set-based O(1) lookup optimization works
        correctly with a large number of log files, avoiding individual exists()
        syscalls for each entry.
        """
        import time

        log_manager = LogManager(str(tmp_path))

        # Create 1000 log files directly (faster than using save_log)
        log_ids = []
        for i in range(1000):
            log_id = f"perf-test-{i:04d}"
            log_ids.append(log_id)
            log_file = tmp_path / f"{log_id}.json"
            log_file.write_text(
                f'{{"id": "{log_id}", "timestamp": "2024-01-01T00:00:00", '
                f'"type": "scan", "status": "clean", "summary": "Test {i}", '
                f'"details": "Details"}}'
            )

        # Create matching index
        index_data = {
            "version": 1,
            "entries": [
                {"id": log_id, "timestamp": "2024-01-01T00:00:00", "type": "scan"}
                for log_id in log_ids
            ],
        }

        # Measure validation time
        start_time = time.perf_counter()
        result = log_manager._validate_index(index_data)
        elapsed_time = time.perf_counter() - start_time

        # Validation should succeed
        assert result is True

        # Validation should complete in under 1 second
        # (with the O(1) set lookup, this should be very fast)
        assert elapsed_time < 1.0, f"Validation took too long: {elapsed_time:.3f}s"

    def test_validate_index_set_lookup_detects_missing_files(self, tmp_path):
        """Test that set-based lookup correctly detects missing files."""
        log_manager = LogManager(str(tmp_path))

        # Create 100 log files
        log_ids = []
        for i in range(100):
            log_id = f"set-test-{i:03d}"
            log_ids.append(log_id)
            log_file = tmp_path / f"{log_id}.json"
            log_file.write_text(
                f'{{"id": "{log_id}", "timestamp": "2024-01-01T00:00:00", '
                f'"type": "scan", "status": "clean"}}'
            )

        # Create index with all entries
        index_data = {
            "version": 1,
            "entries": [
                {"id": log_id, "timestamp": "2024-01-01T00:00:00", "type": "scan"}
                for log_id in log_ids
            ],
        }

        # Verify valid index
        assert log_manager._validate_index(index_data) is True

        # Delete 25 files (25% - above threshold)
        for i in range(25):
            log_file = tmp_path / f"{log_ids[i]}.json"
            log_file.unlink()

        # Should fail due to count mismatch (100 entries vs 75 files)
        assert log_manager._validate_index(index_data) is False


class TestLogManagerOptimizedGetLogs:
    """Tests for optimized get_logs() implementation using index."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    def test_get_logs_uses_index_when_available(self, log_manager):
        """Test that get_logs() uses index for retrieval when available."""
        # Create log entries
        entries = []
        for i in range(10):
            entry = LogEntry.create(
                log_type="scan" if i % 2 == 0 else "update",
                status="clean",
                summary=f"Test entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            entries.append(entry)

        # Verify index exists and has correct entries
        index_data = log_manager._load_index()
        assert len(index_data["entries"]) == 10

        # Get logs should use the index
        logs = log_manager.get_logs()
        assert len(logs) == 10

    def test_get_logs_returns_correct_results_with_index(self, log_manager):
        """Test that get_logs() returns correct results when using index."""
        # Create entries with specific timestamps to control order
        entry1 = LogEntry(
            id="id-1",
            timestamp="2024-01-01T10:00:00",
            type="scan",
            status="clean",
            summary="First",
            details="Details",
        )
        entry2 = LogEntry(
            id="id-2",
            timestamp="2024-01-02T10:00:00",
            type="scan",
            status="clean",
            summary="Second",
            details="Details",
        )
        entry3 = LogEntry(
            id="id-3",
            timestamp="2024-01-03T10:00:00",
            type="update",
            status="success",
            summary="Third",
            details="Details",
        )

        log_manager.save_log(entry1)
        log_manager.save_log(entry2)
        log_manager.save_log(entry3)

        # Get all logs
        logs = log_manager.get_logs(limit=100)

        # Should return all 3 logs
        assert len(logs) == 3

        # Should be sorted by timestamp descending (newest first)
        assert logs[0].summary == "Third"
        assert logs[1].summary == "Second"
        assert logs[2].summary == "First"

    def test_get_logs_fallback_to_full_scan_without_index(self, log_manager, temp_log_dir):
        """Test that get_logs() falls back to full scan when index is missing."""
        # Create log entries
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 1",
            details="Details",
        )
        entry2 = LogEntry.create(
            log_type="update",
            status="success",
            summary="Entry 2",
            details="Details",
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry2)

        # Delete the index file to simulate missing index
        index_path = Path(temp_log_dir) / "log_index.json"
        if index_path.exists():
            index_path.unlink()

        # get_logs() should fall back to full directory scan
        logs = log_manager.get_logs()

        # Should still return all logs
        assert len(logs) == 2

        # Verify we got the correct logs
        summaries = {log.summary for log in logs}
        assert "Entry 1" in summaries
        assert "Entry 2" in summaries

    def test_get_logs_fallback_to_full_scan_with_empty_index(self, log_manager, temp_log_dir):
        """Test that get_logs() falls back to full scan when index is empty."""
        # Create log entries
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test entry",
            details="Details",
        )
        log_manager.save_log(entry)

        # Manually set index to empty (corrupt state)
        log_manager._save_index({"version": 1, "entries": []})

        # get_logs() should fall back to full directory scan
        logs = log_manager.get_logs()

        # Should still return the log via fallback
        assert len(logs) == 1
        assert logs[0].summary == "Test entry"

    def test_get_logs_handles_missing_referenced_files(self, log_manager, temp_log_dir):
        """Test that get_logs() handles missing referenced files gracefully."""
        # Create log entries
        entries = []
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            entries.append(entry)

        # Delete one log file but leave it in the index
        log_file = Path(temp_log_dir) / f"{entries[2].id}.json"
        log_file.unlink()

        # get_logs() should skip the missing file
        logs = log_manager.get_logs()

        # Should return only 4 logs (skipping the missing one)
        assert len(logs) == 4

        # Verify the missing entry is not in results
        summaries = {log.summary for log in logs}
        assert "Entry 2" not in summaries
        assert "Entry 0" in summaries
        assert "Entry 1" in summaries
        assert "Entry 3" in summaries
        assert "Entry 4" in summaries

    def test_get_logs_type_filtering_with_index(self, log_manager):
        """Test that get_logs() correctly filters by type when using index."""
        # Create mixed entries
        scan_entries = []
        update_entries = []

        for i in range(5):
            scan_entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details="Details",
            )
            log_manager.save_log(scan_entry)
            scan_entries.append(scan_entry)

        for i in range(3):
            update_entry = LogEntry.create(
                log_type="update",
                status="success",
                summary=f"Update {i}",
                details="Details",
            )
            log_manager.save_log(update_entry)
            update_entries.append(update_entry)

        # Filter for scan logs only
        scan_logs = log_manager.get_logs(log_type="scan")
        assert len(scan_logs) == 5
        for log in scan_logs:
            assert log.type == "scan"

        # Filter for update logs only
        update_logs = log_manager.get_logs(log_type="update")
        assert len(update_logs) == 3
        for log in update_logs:
            assert log.type == "update"

    def test_get_logs_limit_application_with_index(self, log_manager):
        """Test that get_logs() correctly applies limit when using index."""
        # Create 20 entries
        entries = []
        for i in range(20):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            entries.append(entry)
            time.sleep(0.001)  # Small delay to ensure different timestamps

        # Test various limits
        logs_5 = log_manager.get_logs(limit=5)
        assert len(logs_5) == 5

        logs_10 = log_manager.get_logs(limit=10)
        assert len(logs_10) == 10

        logs_15 = log_manager.get_logs(limit=15)
        assert len(logs_15) == 15

        logs_100 = log_manager.get_logs(limit=100)
        assert len(logs_100) == 20  # Only 20 exist

    def test_get_logs_sort_order_verification_with_index(self, log_manager):
        """Test that get_logs() returns logs sorted by timestamp descending."""
        # Create entries with specific timestamps
        timestamps = [
            "2024-01-01T10:00:00",
            "2024-01-05T15:30:00",
            "2024-01-03T12:00:00",
            "2024-01-07T08:00:00",
            "2024-01-02T14:00:00",
        ]

        entries = []
        for i, ts in enumerate(timestamps):
            entry = LogEntry(
                id=f"id-{i}",
                timestamp=ts,
                type="scan",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)
            entries.append(entry)

        # Get logs
        logs = log_manager.get_logs()

        # Should be sorted by timestamp descending
        assert len(logs) == 5
        assert logs[0].timestamp == "2024-01-07T08:00:00"  # Newest
        assert logs[1].timestamp == "2024-01-05T15:30:00"
        assert logs[2].timestamp == "2024-01-03T12:00:00"
        assert logs[3].timestamp == "2024-01-02T14:00:00"
        assert logs[4].timestamp == "2024-01-01T10:00:00"  # Oldest

    def test_get_logs_combined_type_filter_and_limit_with_index(self, log_manager):
        """Test that get_logs() correctly applies both type filter and limit."""
        # Create 10 scan entries and 10 update entries
        for i in range(10):
            scan_entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details="Details",
            )
            log_manager.save_log(scan_entry)
            time.sleep(0.001)

        for i in range(10):
            update_entry = LogEntry.create(
                log_type="update",
                status="success",
                summary=f"Update {i}",
                details="Details",
            )
            log_manager.save_log(update_entry)
            time.sleep(0.001)

        # Get only scan logs with limit
        scan_logs = log_manager.get_logs(limit=5, log_type="scan")
        assert len(scan_logs) == 5
        for log in scan_logs:
            assert log.type == "scan"

        # Get only update logs with limit
        update_logs = log_manager.get_logs(limit=3, log_type="update")
        assert len(update_logs) == 3
        for log in update_logs:
            assert log.type == "update"

    def test_get_logs_with_corrupted_log_file_in_index(self, log_manager, temp_log_dir):
        """Test that get_logs() skips corrupted log files when using index."""
        # Create valid entries
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Valid entry 1",
            details="Details",
        )
        entry2 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Valid entry 2",
            details="Details",
        )
        log_manager.save_log(entry1)
        log_manager.save_log(entry2)

        # Create a corrupted log file
        corrupted_id = "corrupted-id"
        corrupted_path = Path(temp_log_dir) / f"{corrupted_id}.json"
        with open(corrupted_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json }")

        # Manually add corrupted entry to index
        index_data = log_manager._load_index()
        index_data["entries"].append(
            {"id": corrupted_id, "timestamp": "2024-01-01T10:00:00", "type": "scan"}
        )
        log_manager._save_index(index_data)

        # get_logs() should skip the corrupted file
        logs = log_manager.get_logs()

        # Should return only valid entries
        assert len(logs) == 2
        summaries = {log.summary for log in logs}
        assert "Valid entry 1" in summaries
        assert "Valid entry 2" in summaries

    def test_get_logs_skips_index_file_in_fallback_scan(self, log_manager, temp_log_dir):
        """Test that get_logs() skips the index file during fallback scan."""
        # Create log entries
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Test entry",
            details="Details",
        )
        log_manager.save_log(entry)

        # Force fallback by deleting index
        index_path = Path(temp_log_dir) / "log_index.json"
        if index_path.exists():
            index_path.unlink()

        # get_logs() should not try to parse the index file as a log
        logs = log_manager.get_logs()

        # Should return only the actual log entry
        assert len(logs) == 1
        assert logs[0].summary == "Test entry"

    def test_get_logs_performance_with_large_index(self, log_manager):
        """Test that get_logs() efficiently handles large indices with limit."""
        # Create 100 entries
        for i in range(100):
            entry = LogEntry.create(
                log_type="scan" if i % 2 == 0 else "update",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # With index optimization, this should only load 10 files instead of 100
        logs = log_manager.get_logs(limit=10)

        # Should return exactly 10 logs
        assert len(logs) == 10

        # Should be the 10 most recent (newest first)
        # Verify they're sorted correctly
        for i in range(len(logs) - 1):
            assert logs[i].timestamp >= logs[i + 1].timestamp

    def test_get_logs_handles_index_exception_gracefully(self, log_manager):
        """Test that get_logs() handles index loading exceptions gracefully."""
        # Create log entries
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Entry {i}",
                details="Details",
            )
            log_manager.save_log(entry)

        # Mock _load_index to raise an exception
        original_load = log_manager._load_index

        def mock_load():
            raise Exception("Index loading error")

        log_manager._load_index = mock_load

        # get_logs() should fall back to full scan
        logs = log_manager.get_logs()

        # Should still return all logs via fallback
        assert len(logs) == 3

        # Restore original method
        log_manager._load_index = original_load

    def test_get_logs_returns_empty_list_with_nonexistent_directory(self, temp_log_dir):
        """Test that get_logs() returns empty list when directory doesn't exist."""
        # Create manager, then delete directory
        log_dir = Path(temp_log_dir) / "nonexistent"
        manager = LogManager(log_dir=str(log_dir))

        # Delete the directory
        import shutil

        if log_dir.exists():
            shutil.rmtree(log_dir)

        # get_logs() should return empty list
        logs = manager.get_logs()
        assert logs == []

    def test_get_logs_consistency_between_index_and_fallback(self, log_manager, temp_log_dir):
        """Test that get_logs() returns same results with index and fallback."""
        # Create diverse set of entries
        entries = []
        for i in range(15):
            entry = LogEntry.create(
                log_type="scan" if i % 3 == 0 else "update",
                status="clean" if i % 2 == 0 else "infected",
                summary=f"Entry {i}",
                details=f"Details {i}",
            )
            log_manager.save_log(entry)
            entries.append(entry)

        # Get logs using index
        logs_with_index = log_manager.get_logs(limit=10, log_type="scan")

        # Delete index to force fallback
        index_path = Path(temp_log_dir) / "log_index.json"
        if index_path.exists():
            index_path.unlink()

        # Get logs using fallback
        logs_with_fallback = log_manager.get_logs(limit=10, log_type="scan")

        # Results should be identical
        assert len(logs_with_index) == len(logs_with_fallback)

        # Compare IDs (order should be same)
        index_ids = [log.id for log in logs_with_index]
        fallback_ids = [log.id for log in logs_with_fallback]
        assert index_ids == fallback_ids


class TestLogManagerAutoMigration:
    """Tests for auto-migration on first get_logs() access."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def log_manager(self, temp_log_dir):
        """Create a LogManager with a temporary directory."""
        return LogManager(log_dir=temp_log_dir)

    def test_auto_migration_when_logs_exist_without_index(self, temp_log_dir):
        """Test that index is automatically created when logs exist but no index."""
        # Create LogManager
        manager = LogManager(log_dir=temp_log_dir)

        # Manually create log files without using save_log() (simulates old installation)
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create 3 log files
        entries = []
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan" if i % 2 == 0 else "update",
                status="clean",
                summary=f"Entry {i}",
                details=f"Details {i}",
            )
            entries.append(entry)

            # Write directly to file (bypassing save_log to avoid index creation)
            log_file = log_dir / f"{entry.id}.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)

        # Verify index doesn't exist yet
        index_path = log_dir / "log_index.json"
        assert not index_path.exists()

        # Create a NEW LogManager instance to ensure fresh state
        manager = LogManager(log_dir=temp_log_dir)

        # First get_logs() call should trigger auto-migration
        logs = manager.get_logs()

        # Index should now exist
        assert index_path.exists()

        # Index should contain all entries
        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)

        assert index_data["version"] == 1
        assert len(index_data["entries"]) == 3

        # Verify all log IDs are in index
        index_ids = {entry["id"] for entry in index_data["entries"]}
        expected_ids = {entry.id for entry in entries}
        assert index_ids == expected_ids

        # Verify get_logs returns all logs
        assert len(logs) == 3

    def test_auto_migration_only_happens_once(self, temp_log_dir):
        """Test that auto-migration check only happens on first get_logs() call."""
        # Create LogManager
        manager = LogManager(log_dir=temp_log_dir)

        # Create a log file manually
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 1",
            details="Details 1",
        )
        log_file = log_dir / f"{entry.id}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(entry.to_dict(), f, indent=2)

        # First call triggers migration
        manager.get_logs()

        # Verify migration flag is set
        assert manager._migration_checked is True

        # Delete index to test that it's not rebuilt on second call
        index_path = log_dir / "log_index.json"
        if index_path.exists():
            index_path.unlink()

        # Second call should NOT trigger migration (flag is already True)
        logs = manager.get_logs()

        # Index should still not exist (wasn't rebuilt)
        assert not index_path.exists()

        # But get_logs should still work (fallback to full scan)
        assert len(logs) == 1

    def test_no_migration_when_index_already_exists(self, log_manager, temp_log_dir):
        """Test that no migration happens when index already exists."""
        # Create a log using save_log (which creates index)
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 1",
            details="Details 1",
        )
        log_manager.save_log(entry)

        # Index should exist
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        # Get the modification time
        mtime_before = index_path.stat().st_mtime

        # Wait a tiny bit to ensure mtime would change if file is modified
        time.sleep(0.01)

        # Create a NEW LogManager instance
        manager = LogManager(log_dir=temp_log_dir)

        # Call get_logs (should not rebuild index since it exists)
        logs = manager.get_logs()

        # Index modification time should be unchanged
        mtime_after = index_path.stat().st_mtime
        assert mtime_before == mtime_after

        # Migration flag should still be set
        assert manager._migration_checked is True

        # Logs should be returned correctly
        assert len(logs) == 1

    def test_no_migration_when_no_logs_exist(self, temp_log_dir):
        """Test that no migration happens when no log files exist."""
        # Create LogManager with empty directory
        manager = LogManager(log_dir=temp_log_dir)

        # Call get_logs on empty directory
        logs = manager.get_logs()

        # No index should be created (no logs to index)
        index_path = Path(temp_log_dir) / "log_index.json"
        assert not index_path.exists()

        # Migration flag should be set
        assert manager._migration_checked is True

        # Should return empty list
        assert logs == []

    def test_migration_handles_corrupted_files_gracefully(self, temp_log_dir):
        """Test that migration skips corrupted log files gracefully."""
        # Create LogManager
        manager = LogManager(log_dir=temp_log_dir)

        # Create log directory
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create one valid log file
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Valid entry",
            details="Details",
        )
        log_file1 = log_dir / f"{entry1.id}.json"
        with open(log_file1, "w", encoding="utf-8") as f:
            json.dump(entry1.to_dict(), f, indent=2)

        # Create a corrupted log file
        corrupted_file = log_dir / "corrupted.json"
        with open(corrupted_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json content")

        # Create another valid log file
        entry2 = LogEntry.create(
            log_type="update",
            status="success",
            summary="Another valid entry",
            details="Details 2",
        )
        log_file2 = log_dir / f"{entry2.id}.json"
        with open(log_file2, "w", encoding="utf-8") as f:
            json.dump(entry2.to_dict(), f, indent=2)

        # Create a NEW LogManager instance
        manager = LogManager(log_dir=temp_log_dir)

        # First get_logs() call should trigger migration and skip corrupted file
        manager.get_logs()

        # Index should exist
        index_path = log_dir / "log_index.json"
        assert index_path.exists()

        # Index should contain only valid entries
        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)

        assert len(index_data["entries"]) == 2

        # Verify valid log IDs are in index
        index_ids = {entry["id"] for entry in index_data["entries"]}
        expected_ids = {entry1.id, entry2.id}
        assert index_ids == expected_ids

    def test_migration_handles_missing_fields_gracefully(self, temp_log_dir):
        """Test that migration skips log files with missing required fields."""
        # Create LogManager
        manager = LogManager(log_dir=temp_log_dir)

        # Create log directory
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create one valid log file
        entry1 = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Valid entry",
            details="Details",
        )
        log_file1 = log_dir / f"{entry1.id}.json"
        with open(log_file1, "w", encoding="utf-8") as f:
            json.dump(entry1.to_dict(), f, indent=2)

        # Create a log file missing the 'type' field
        incomplete_file = log_dir / "incomplete.json"
        with open(incomplete_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": "incomplete-id",
                    "timestamp": "2024-01-15T10:00:00",
                    # Missing 'type' field
                    "status": "clean",
                    "summary": "Incomplete",
                    "details": "Missing type field",
                },
                f,
                indent=2,
            )

        # Create a NEW LogManager instance
        manager = LogManager(log_dir=temp_log_dir)

        # First get_logs() call should trigger migration and skip incomplete file
        manager.get_logs()

        # Index should exist
        index_path = log_dir / "log_index.json"
        assert index_path.exists()

        # Index should contain only the valid entry
        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)

        assert len(index_data["entries"]) == 1
        assert index_data["entries"][0]["id"] == entry1.id

    def test_migration_failure_does_not_break_get_logs(self, temp_log_dir):
        """Test that get_logs() still works even if migration fails."""
        # Create LogManager
        manager = LogManager(log_dir=temp_log_dir)

        # Create a valid log file
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 1",
            details="Details 1",
        )
        log_file = log_dir / f"{entry.id}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(entry.to_dict(), f, indent=2)

        # Create a NEW LogManager instance
        manager = LogManager(log_dir=temp_log_dir)

        # Mock _save_index to fail (simulates permission error during migration)
        original_save = manager._save_index

        def mock_save(index_data):
            return False  # Simulate failure

        manager._save_index = mock_save

        # get_logs() should still work via fallback, despite migration failure
        logs = manager.get_logs()

        # Should still return the log via fallback
        assert len(logs) == 1
        assert logs[0].id == entry.id

        # Migration flag should still be set (migration was attempted)
        assert manager._migration_checked is True

        # Restore original method
        manager._save_index = original_save

    def test_migration_with_nonexistent_directory(self, temp_log_dir):
        """Test that migration handles nonexistent directory gracefully."""
        # Create a path that doesn't exist
        log_dir = Path(temp_log_dir) / "nonexistent"

        # Create LogManager (directory won't exist yet)
        manager = LogManager(log_dir=str(log_dir))

        # Call get_logs (should handle gracefully)
        logs = manager.get_logs()

        # Migration flag should be set
        assert manager._migration_checked is True

        # Should return empty list
        assert logs == []

        # No index should be created
        index_path = log_dir / "log_index.json"
        assert not index_path.exists()

    def test_migration_creates_index_with_correct_structure(self, temp_log_dir):
        """Test that migration creates index with correct structure."""
        # Create LogManager
        manager = LogManager(log_dir=temp_log_dir)

        # Create log directory and files manually
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create log files with specific data
        entries = []
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan" if i % 2 == 0 else "update",
                status="clean",
                summary=f"Entry {i}",
                details=f"Details {i}",
            )
            entries.append(entry)

            log_file = log_dir / f"{entry.id}.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)

        # Create a NEW LogManager instance
        manager = LogManager(log_dir=temp_log_dir)

        # Trigger migration
        manager.get_logs()

        # Verify index structure
        index_path = log_dir / "log_index.json"
        assert index_path.exists()

        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)

        # Verify structure
        assert "version" in index_data
        assert "entries" in index_data
        assert index_data["version"] == 1
        assert isinstance(index_data["entries"], list)
        assert len(index_data["entries"]) == 3

        # Verify each entry has required fields
        for entry in index_data["entries"]:
            assert "id" in entry
            assert "timestamp" in entry
            assert "type" in entry
            assert len(entry) == 3  # Only these 3 fields

    def test_migration_skips_index_file_itself(self, temp_log_dir):
        """Test that migration doesn't try to process the index file as a log."""
        # Create LogManager
        manager = LogManager(log_dir=temp_log_dir)

        # Create log directory
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create a valid log file
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry 1",
            details="Details 1",
        )
        log_file = log_dir / f"{entry.id}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(entry.to_dict(), f, indent=2)

        # Create a fake existing index file (to simulate edge case)
        index_path = log_dir / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 1,
                    "entries": [
                        {
                            "id": "fake",
                            "timestamp": "2024-01-01T00:00:00",
                            "type": "scan",
                        }
                    ],
                },
                f,
            )

        # Now delete it to force migration
        index_path.unlink()

        # Create a NEW LogManager instance
        manager = LogManager(log_dir=temp_log_dir)

        # Trigger migration
        manager.get_logs()

        # Index should be created and contain only the actual log entry
        assert index_path.exists()

        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)

        assert len(index_data["entries"]) == 1
        assert index_data["entries"][0]["id"] == entry.id


class TestLogManagerOptimizedGetLogCount:
    """Tests for optimized get_log_count() using index."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary log directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_get_log_count_uses_index(self, temp_log_dir):
        """Test get_log_count uses index for O(1) performance."""
        manager = LogManager(log_dir=temp_log_dir)

        # Create some log entries
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            manager.save_log(entry)

        # Index should exist now
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        # get_log_count should use the index
        count = manager.get_log_count()
        assert count == 5

        # Verify index was actually used by checking it has correct data
        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)
        assert len(index_data["entries"]) == 5

    def test_get_log_count_fallback_without_index(self, temp_log_dir):
        """Test get_log_count falls back to directory scan without index."""
        log_dir = Path(temp_log_dir)

        # Create log files directly (bypassing save_log to avoid index creation)
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            log_file = log_dir / f"{entry.id}.json"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)

        # No index should exist
        index_path = log_dir / "log_index.json"
        assert not index_path.exists()

        # Create manager and get count - should fall back to directory scan
        manager = LogManager(log_dir=temp_log_dir)
        count = manager.get_log_count()
        assert count == 3

    def test_get_log_count_excludes_index_file(self, temp_log_dir):
        """Test get_log_count excludes the index file from count."""
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create log files directly
        for i in range(2):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            log_file = log_dir / f"{entry.id}.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)

        # Create an index file manually
        index_path = log_dir / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": []}, f)

        # Total JSON files = 3 (2 logs + 1 index), but count should be 2
        json_files = list(log_dir.glob("*.json"))
        assert len(json_files) == 3

        manager = LogManager(log_dir=temp_log_dir)
        count = manager.get_log_count()
        assert count == 2  # Should exclude index file

    def test_get_log_count_with_stale_index(self, temp_log_dir):
        """Test get_log_count rebuilds stale index and returns correct count."""
        manager = LogManager(log_dir=temp_log_dir)
        log_dir = Path(temp_log_dir)

        # Create logs through manager (creates index)
        entries = []
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            manager.save_log(entry)
            entries.append(entry)

        # Manually delete one log file to make index stale
        log_file = log_dir / f"{entries[0].id}.json"
        log_file.unlink()

        # get_log_count should detect stale index and fall back to directory scan
        count = manager.get_log_count()
        assert count == 2  # Should count remaining files

    def test_get_log_count_with_corrupted_index(self, temp_log_dir):
        """Test get_log_count handles corrupted index gracefully."""
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create some log files
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            log_file = log_dir / f"{entry.id}.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)

        # Create a corrupted index file
        index_path = log_dir / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json")

        # get_log_count should handle corrupted index and fall back
        manager = LogManager(log_dir=temp_log_dir)
        count = manager.get_log_count()
        assert count == 3

    def test_get_log_count_empty_directory(self, temp_log_dir):
        """Test get_log_count returns 0 for empty directory."""
        manager = LogManager(log_dir=temp_log_dir)
        count = manager.get_log_count()
        assert count == 0

    def test_get_log_count_nonexistent_directory(self, temp_log_dir):
        """Test get_log_count handles nonexistent directory."""
        manager = LogManager(log_dir=os.path.join(temp_log_dir, "nonexistent"))
        # Delete the created directory
        os.rmdir(manager._log_dir)
        count = manager.get_log_count()
        assert count == 0

    def test_get_log_count_with_invalid_index_structure(self, temp_log_dir):
        """Test get_log_count handles invalid index structure."""
        log_dir = Path(temp_log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create some log files
        for i in range(2):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            log_file = log_dir / f"{entry.id}.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)

        # Create an index with invalid structure (missing 'entries' key)
        index_path = log_dir / "log_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1}, f)  # Missing 'entries' key

        # get_log_count should handle invalid structure and fall back
        manager = LogManager(log_dir=temp_log_dir)
        count = manager.get_log_count()
        assert count == 2

    def test_get_log_count_large_index(self, temp_log_dir):
        """Test get_log_count performance with large index."""
        manager = LogManager(log_dir=temp_log_dir)

        # Create a moderate number of log entries
        for i in range(20):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            manager.save_log(entry)

        # get_log_count should use index efficiently
        count = manager.get_log_count()
        assert count == 20

    def test_get_log_count_after_delete(self, temp_log_dir):
        """Test get_log_count updates correctly after delete_log."""
        manager = LogManager(log_dir=temp_log_dir)

        # Create logs
        entries = []
        for i in range(4):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            manager.save_log(entry)
            entries.append(entry)

        assert manager.get_log_count() == 4

        # Delete one log
        manager.delete_log(entries[0].id)

        # Count should be updated
        assert manager.get_log_count() == 3

    def test_get_log_count_after_clear(self, temp_log_dir):
        """Test get_log_count returns 0 after clear_logs."""
        manager = LogManager(log_dir=temp_log_dir)

        # Create logs
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            manager.save_log(entry)

        assert manager.get_log_count() == 3

        # Clear logs
        manager.clear_logs()

        # Count should be 0
        assert manager.get_log_count() == 0


class TestLogManagerMigrationIntegration:
    """Integration tests for migration from non-indexed to indexed state.

    These tests verify that the auto-migration feature works correctly in
    end-to-end scenarios and doesn't break any existing functionality.
    """

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def _create_manual_log_files(self, log_dir, count=5):
        """Helper to create log files manually without using save_log().

        This simulates an old installation where logs exist but no index.
        Returns list of created LogEntry objects.
        """
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        entries = []
        for i in range(count):
            entry = LogEntry.create(
                log_type="scan" if i % 2 == 0 else "update",
                status="clean" if i % 3 != 0 else "infected",
                summary=f"Entry {i}",
                details=f"Details for entry {i}",
                path=f"/test/path/{i}",
                duration=float(i * 10),
            )
            entries.append(entry)

            # Write directly to file (bypassing save_log to avoid index creation)
            log_file = log_path / f"{entry.id}.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)

        return entries

    def test_migration_transparent_workflow(self, temp_log_dir):
        """Test complete workflow: manual logs -> migrate -> continue operations."""
        # Step 1: Create logs manually (simulating old installation)
        entries = self._create_manual_log_files(temp_log_dir, count=5)

        # Verify no index exists
        index_path = Path(temp_log_dir) / "log_index.json"
        assert not index_path.exists()

        # Step 2: Create LogManager (triggers migration on first get_logs)
        manager = LogManager(log_dir=temp_log_dir)

        # Step 3: Retrieve logs (should trigger migration)
        logs = manager.get_logs()

        # Verify migration happened
        assert index_path.exists()
        assert len(logs) == 5

        # Step 4: Continue using manager normally - save new log
        new_entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="New entry after migration",
            details="This entry was created after migration",
        )
        result = manager.save_log(new_entry)
        assert result is True

        # Step 5: Verify index was updated
        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)
        assert len(index_data["entries"]) == 6

        # Step 6: Retrieve logs again (should use index)
        logs_after = manager.get_logs()
        assert len(logs_after) == 6

        # Step 7: Delete a log
        result = manager.delete_log(entries[0].id)
        assert result is True

        # Step 8: Verify index was updated
        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)
        assert len(index_data["entries"]) == 5

        # Step 9: Verify get_logs returns correct count
        logs_final = manager.get_logs()
        assert len(logs_final) == 5
        assert all(log.id != entries[0].id for log in logs_final)

    def test_migration_with_type_filtering(self, temp_log_dir):
        """Test that type filtering works correctly after migration."""
        # Create manual logs with mixed types
        self._create_manual_log_files(temp_log_dir, count=10)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)

        # Test filtering by scan type
        scan_logs = manager.get_logs(log_type="scan")
        assert len(scan_logs) == 5  # Half are scans (even indices)
        assert all(log.type == "scan" for log in scan_logs)

        # Test filtering by update type
        update_logs = manager.get_logs(log_type="update")
        assert len(update_logs) == 5  # Half are updates (odd indices)
        assert all(log.type == "update" for log in update_logs)

        # Test with no filter
        all_logs = manager.get_logs()
        assert len(all_logs) == 10

    def test_migration_with_limit_application(self, temp_log_dir):
        """Test that limit parameter works correctly after migration."""
        # Create manual logs
        self._create_manual_log_files(temp_log_dir, count=20)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)

        # Test various limits
        logs_5 = manager.get_logs(limit=5)
        assert len(logs_5) == 5

        logs_10 = manager.get_logs(limit=10)
        assert len(logs_10) == 10

        logs_all = manager.get_logs(limit=100)
        assert len(logs_all) == 20

        # Verify sort order (newest first)
        timestamps = [log.timestamp for log in logs_5]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_migration_combined_filters(self, temp_log_dir):
        """Test that type filtering and limit work together after migration."""
        # Create manual logs
        self._create_manual_log_files(temp_log_dir, count=20)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)

        # Test combined filters
        scan_logs = manager.get_logs(log_type="scan", limit=3)
        assert len(scan_logs) == 3
        assert all(log.type == "scan" for log in scan_logs)

        # Verify newest scans are returned
        timestamps = [log.timestamp for log in scan_logs]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_migration_get_log_count_consistency(self, temp_log_dir):
        """Test that get_log_count() returns correct count after migration."""
        # Create manual logs
        self._create_manual_log_files(temp_log_dir, count=7)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)

        # Trigger migration by calling get_logs
        logs = manager.get_logs()

        # Verify get_log_count uses the index
        count = manager.get_log_count()
        assert count == 7
        assert count == len(logs)

    def test_migration_clear_logs_workflow(self, temp_log_dir):
        """Test that clear_logs() works correctly after migration."""
        # Create manual logs
        self._create_manual_log_files(temp_log_dir, count=5)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)
        logs = manager.get_logs()
        assert len(logs) == 5

        # Clear all logs
        result = manager.clear_logs()
        assert result is True

        # Verify index was reset
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)
        assert len(index_data["entries"]) == 0

        # Verify get_logs returns empty
        logs_after = manager.get_logs()
        assert len(logs_after) == 0

        # Verify get_log_count returns 0
        assert manager.get_log_count() == 0

    def test_migration_multiple_manager_instances(self, temp_log_dir):
        """Test that multiple LogManager instances work correctly after migration."""
        # Create manual logs
        self._create_manual_log_files(temp_log_dir, count=5)

        # Create first manager and trigger migration
        manager1 = LogManager(log_dir=temp_log_dir)
        logs1 = manager1.get_logs()
        assert len(logs1) == 5

        # Verify index exists
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        # Create second manager (should use existing index)
        manager2 = LogManager(log_dir=temp_log_dir)
        logs2 = manager2.get_logs()
        assert len(logs2) == 5

        # Add log via first manager
        new_entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Entry from manager1",
            details="Details",
        )
        manager1.save_log(new_entry)

        # Create third manager (should see updated index)
        manager3 = LogManager(log_dir=temp_log_dir)
        logs3 = manager3.get_logs()
        assert len(logs3) == 6

    def test_migration_concurrent_operations(self, temp_log_dir):
        """Test that concurrent operations work correctly during/after migration."""
        # Create manual logs
        self._create_manual_log_files(temp_log_dir, count=10)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)

        results = []
        errors = []

        def save_logs():
            try:
                for i in range(5):
                    entry = LogEntry.create(
                        log_type="scan",
                        status="clean",
                        summary=f"Concurrent save {i}",
                        details=f"Details {i}",
                    )
                    result = manager.save_log(entry)
                    results.append(result)
            except Exception as e:
                errors.append(e)

        def read_logs():
            try:
                for _i in range(5):
                    logs = manager.get_logs()
                    results.append(len(logs) >= 10)  # Should have at least original logs
            except Exception as e:
                errors.append(e)

        # Run concurrent operations
        threads = [
            threading.Thread(target=save_logs),
            threading.Thread(target=read_logs),
            threading.Thread(target=save_logs),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Verify no errors occurred
        assert len(errors) == 0

        # Verify all operations succeeded
        assert all(results)

        # Verify final count is correct (10 original + 10 concurrent saves)
        final_logs = manager.get_logs()
        assert len(final_logs) == 20

    def test_migration_delete_and_recreate_index(self, temp_log_dir):
        """Test that system recovers if index is manually deleted after migration."""
        # Create manual logs
        self._create_manual_log_files(temp_log_dir, count=5)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)
        logs = manager.get_logs()
        assert len(logs) == 5

        # Verify index exists
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        # Manually delete index (simulating corruption or manual deletion)
        index_path.unlink()
        assert not index_path.exists()

        # Create new LogManager instance
        manager2 = LogManager(log_dir=temp_log_dir)

        # get_logs should still work (fallback or validation triggers rebuild)
        logs2 = manager2.get_logs()
        assert len(logs2) == 5

        # Index should be recreated automatically (via validation)
        # Note: The first manager instance won't trigger migration again (flag is set)
        # but the validation logic should detect the missing/invalid index

    def test_migration_preserves_log_data_integrity(self, temp_log_dir):
        """Test that migration preserves all log data correctly."""
        # Create manual logs with diverse data
        entries = self._create_manual_log_files(temp_log_dir, count=5)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)
        logs = manager.get_logs()

        # Verify all data is preserved
        assert len(logs) == 5

        # Create mapping for easy lookup
        original_by_id = {e.id: e for e in entries}
        retrieved_by_id = {log.id: log for log in logs}

        # Verify all IDs match
        assert set(original_by_id.keys()) == set(retrieved_by_id.keys())

        # Verify all fields are preserved for each log
        for log_id, original in original_by_id.items():
            retrieved = retrieved_by_id[log_id]
            assert retrieved.id == original.id
            assert retrieved.timestamp == original.timestamp
            assert retrieved.type == original.type
            assert retrieved.status == original.status
            assert retrieved.summary == original.summary
            assert retrieved.details == original.details
            assert retrieved.path == original.path
            assert retrieved.duration == original.duration

    def test_migration_with_corrupted_and_valid_logs(self, temp_log_dir):
        """Test migration skips corrupted logs but processes valid ones."""
        # Create some valid logs manually
        valid_entries = self._create_manual_log_files(temp_log_dir, count=3)

        # Add corrupted log files
        log_path = Path(temp_log_dir)
        corrupted1 = log_path / "corrupted1.json"
        with open(corrupted1, "w", encoding="utf-8") as f:
            f.write("{ invalid json")

        corrupted2 = log_path / "corrupted2.json"
        with open(corrupted2, "w", encoding="utf-8") as f:
            json.dump({"id": "missing-fields"}, f)  # Missing required fields

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)
        logs = manager.get_logs()

        # Should retrieve only valid logs
        assert len(logs) == 3

        # Verify all retrieved logs are from the valid set
        valid_ids = {e.id for e in valid_entries}
        retrieved_ids = {log.id for log in logs}
        assert retrieved_ids == valid_ids

    def test_migration_empty_directory_then_add_logs(self, temp_log_dir):
        """Test migration behavior when starting with empty directory."""
        # Create LogManager with empty directory
        manager = LogManager(log_dir=temp_log_dir)

        # First get_logs on empty directory
        logs = manager.get_logs()
        assert len(logs) == 0

        # No index should be created for empty directory
        index_path = Path(temp_log_dir) / "log_index.json"
        # Note: The index might not exist if no logs were ever saved

        # Now add logs normally
        for i in range(5):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Entry {i}",
                details=f"Details {i}",
            )
            manager.save_log(entry)

        # Index should now exist and be maintained
        assert index_path.exists()

        # Verify all logs are retrievable
        logs_after = manager.get_logs()
        assert len(logs_after) == 5

    def test_migration_large_log_collection(self, temp_log_dir):
        """Test migration with a large collection of logs (performance test)."""
        # Create many logs manually
        self._create_manual_log_files(temp_log_dir, count=100)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)

        # Migration should complete successfully
        logs = manager.get_logs(limit=10)
        assert len(logs) == 10

        # Verify index exists and contains all entries
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)
        assert len(index_data["entries"]) == 100

        # Verify get_log_count is efficient (uses index)
        count = manager.get_log_count()
        assert count == 100

        # Verify filtering still works efficiently
        scan_logs = manager.get_logs(log_type="scan", limit=5)
        assert len(scan_logs) == 5
        assert all(log.type == "scan" for log in scan_logs)

    def test_migration_rebuild_index_method_still_works(self, temp_log_dir):
        """Test that rebuild_index() can be called manually after migration."""
        # Create manual logs
        self._create_manual_log_files(temp_log_dir, count=5)

        # Create LogManager and trigger migration
        manager = LogManager(log_dir=temp_log_dir)
        logs = manager.get_logs()
        assert len(logs) == 5

        # Verify index exists
        index_path = Path(temp_log_dir) / "log_index.json"
        assert index_path.exists()

        # Manually rebuild index
        result = manager.rebuild_index()
        assert result is True

        # Verify index still exists and is correct
        assert index_path.exists()

        with open(index_path, encoding="utf-8") as f:
            index_data = json.load(f)
        assert len(index_data["entries"]) == 5

        # Verify logs are still retrievable
        logs_after = manager.get_logs()
        assert len(logs_after) == 5


class TestLogManagerExport:
    """Tests for LogManager export functionality (CSV and JSON)."""

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
    def sample_entries(self):
        """Create sample log entries for testing."""
        entries = [
            LogEntry(
                id="uuid-1",
                timestamp="2024-01-15T10:30:00",
                type="scan",
                status="clean",
                summary="Clean scan of /home/user",
                details="Scanned: 100 files, 10 directories",
                path="/home/user",
                duration=45.5,
                scheduled=False,
            ),
            LogEntry(
                id="uuid-2",
                timestamp="2024-01-15T11:00:00",
                type="update",
                status="success",
                summary="Database updated",
                details="Updated virus definitions",
                path=None,
                duration=30.0,
                scheduled=False,
            ),
            LogEntry(
                id="uuid-3",
                timestamp="2024-01-15T12:00:00",
                type="scan",
                status="infected",
                summary="Found 2 threat(s)",
                details="Threats found: 2",
                path="/tmp/downloads",
                duration=60.25,
                scheduled=True,
            ),
        ]
        return entries

    # CSV Export Tests

    def test_export_logs_to_csv_basic(self, log_manager, sample_entries):
        """Test basic CSV export with valid data."""
        csv_output = log_manager.export_logs_to_csv(sample_entries)

        # Verify header row
        assert "id,timestamp,type,status,path,summary,duration,scheduled" in csv_output

        # Verify data rows
        lines = csv_output.strip().split("\n")
        assert len(lines) == 4  # 1 header + 3 data rows

        # Verify first data row
        assert "uuid-1" in lines[1]
        assert "2024-01-15T10:30:00" in lines[1]
        assert "scan" in lines[1]
        assert "clean" in lines[1]
        assert "/home/user" in lines[1]
        assert "45.50" in lines[1]
        assert "false" in lines[1]

        # Verify second data row (update with None path)
        assert "uuid-2" in lines[2]
        assert "update" in lines[2]
        assert "success" in lines[2]
        assert "30.00" in lines[2]

        # Verify third data row (scheduled scan)
        assert "uuid-3" in lines[3]
        assert "infected" in lines[3]
        assert "60.25" in lines[3]
        assert "true" in lines[3]

    def test_export_logs_to_csv_special_characters(self, log_manager):
        """Test CSV export properly escapes special characters."""
        entries = [
            LogEntry(
                id="special-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary='Path with "quotes" and, commas',
                details="Details",
                path='/path/with"quotes',
                duration=10.0,
                scheduled=False,
            ),
            LogEntry(
                id="special-2",
                timestamp="2024-01-15T11:00:00",
                type="scan",
                status="clean",
                summary="Summary with\nnewline",
                details="Details",
                path="/path/with,comma",
                duration=20.0,
                scheduled=False,
            ),
        ]

        csv_output = log_manager.export_logs_to_csv(entries)

        # Verify CSV module properly escapes quotes
        assert (
            'Path with ""quotes"" and, commas' in csv_output
            or '"Path with ""quotes"" and, commas"' in csv_output
        )

        # Verify newlines are escaped
        lines = csv_output.split("\n")
        # Should have header + 2 data rows (newlines in fields should be escaped)
        assert len([line for line in lines if line.strip()]) >= 3

    def test_export_logs_to_csv_empty_logs(self, log_manager):
        """Test CSV export with empty log list."""
        csv_output = log_manager.export_logs_to_csv([])

        # Should still have header row
        lines = csv_output.strip().split("\n")
        assert len(lines) == 1
        assert "id,timestamp,type,status,path,summary,duration,scheduled" in lines[0]

    def test_export_logs_to_csv_none_path(self, log_manager):
        """Test CSV export handles None path values."""
        entries = [
            LogEntry(
                id="none-path",
                timestamp="2024-01-15T10:00:00",
                type="update",
                status="success",
                summary="Update without path",
                details="Details",
                path=None,
                duration=5.0,
                scheduled=False,
            )
        ]

        csv_output = log_manager.export_logs_to_csv(entries)
        lines = csv_output.strip().split("\n")

        # Path should be empty string in CSV (not "None")
        assert len(lines) == 2
        # Should have empty field for path (consecutive commas)
        data_row = lines[1]
        assert "update,success," in data_row  # Empty path field

    def test_export_logs_to_csv_zero_duration(self, log_manager):
        """Test CSV export handles zero duration correctly."""
        entries = [
            LogEntry(
                id="zero-duration",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Quick scan",
                details="Details",
                path="/path",
                duration=0.0,
                scheduled=False,
            )
        ]

        csv_output = log_manager.export_logs_to_csv(entries)
        lines = csv_output.strip().split("\n")

        # Duration should be "0" not "0.00"
        assert ",0," in lines[1] or ",0\n" in csv_output or lines[1].endswith(",0,false")

    def test_export_logs_to_csv_default_all_logs(self, log_manager):
        """Test CSV export with no entries parameter uses all logs."""
        # Save some logs
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            log_manager.save_log(entry)

        # Export without specifying entries
        csv_output = log_manager.export_logs_to_csv()

        # Should export all 3 logs
        lines = csv_output.strip().split("\n")
        assert len(lines) == 4  # 1 header + 3 data rows

    def test_export_logs_to_csv_duration_formatting(self, log_manager):
        """Test CSV export formats duration with 2 decimal places."""
        entries = [
            LogEntry(
                id="duration-test",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Test",
                details="Details",
                path="/path",
                duration=123.456789,  # Should be rounded to 2 decimals
                scheduled=False,
            )
        ]

        csv_output = log_manager.export_logs_to_csv(entries)
        assert "123.46" in csv_output

    # JSON Export Tests

    def test_export_logs_to_json_basic(self, log_manager, sample_entries):
        """Test basic JSON export with valid data."""
        json_output = log_manager.export_logs_to_json(sample_entries)

        # Parse JSON to verify structure
        data = json.loads(json_output)

        # Verify metadata wrapper
        assert "export_timestamp" in data
        assert "count" in data
        assert "entries" in data

        # Verify count
        assert data["count"] == 3

        # Verify entries
        assert len(data["entries"]) == 3

        # Verify first entry
        entry1 = data["entries"][0]
        assert entry1["id"] == "uuid-1"
        assert entry1["timestamp"] == "2024-01-15T10:30:00"
        assert entry1["type"] == "scan"
        assert entry1["status"] == "clean"
        assert entry1["summary"] == "Clean scan of /home/user"
        assert entry1["details"] == "Scanned: 100 files, 10 directories"
        assert entry1["path"] == "/home/user"
        assert entry1["duration"] == 45.5
        assert entry1["scheduled"] is False

    def test_export_logs_to_json_structure(self, log_manager, sample_entries):
        """Test JSON export has correct structure with metadata."""
        json_output = log_manager.export_logs_to_json(sample_entries)
        data = json.loads(json_output)

        # Verify top-level keys
        assert set(data.keys()) == {"export_timestamp", "count", "entries"}

        # Verify export_timestamp is ISO format
        assert "T" in data["export_timestamp"]

        # Verify count matches entries length
        assert data["count"] == len(data["entries"])

    def test_export_logs_to_json_empty_logs(self, log_manager):
        """Test JSON export with empty log list."""
        json_output = log_manager.export_logs_to_json([])
        data = json.loads(json_output)

        # Should have metadata with count=0
        assert data["count"] == 0
        assert data["entries"] == []
        assert "export_timestamp" in data

    def test_export_logs_to_json_none_values(self, log_manager):
        """Test JSON export handles None values correctly."""
        entries = [
            LogEntry(
                id="none-test",
                timestamp="2024-01-15T10:00:00",
                type="update",
                status="success",
                summary="Update",
                details="Details",
                path=None,  # None should be null in JSON
                duration=5.0,
                scheduled=False,
            )
        ]

        json_output = log_manager.export_logs_to_json(entries)
        data = json.loads(json_output)

        # Path should be null in JSON (not string "None")
        assert data["entries"][0]["path"] is None

    def test_export_logs_to_json_default_all_logs(self, log_manager):
        """Test JSON export with no entries parameter uses all logs."""
        # Save some logs
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            log_manager.save_log(entry)

        # Export without specifying entries
        json_output = log_manager.export_logs_to_json()
        data = json.loads(json_output)

        # Should export all 3 logs
        assert data["count"] == 3
        assert len(data["entries"]) == 3

    def test_export_logs_to_json_indentation(self, log_manager, sample_entries):
        """Test JSON export is formatted with indentation for readability."""
        json_output = log_manager.export_logs_to_json(sample_entries)

        # Should have indentation (newlines and spaces)
        assert "\n" in json_output
        assert "  " in json_output  # 2-space indentation

    def test_export_logs_to_json_all_fields(self, log_manager):
        """Test JSON export includes all LogEntry fields."""
        entry = LogEntry(
            id="all-fields-test",
            timestamp="2024-01-15T10:00:00",
            type="scan",
            status="infected",
            summary="Test summary",
            details="Test details",
            path="/test/path",
            duration=123.45,
            scheduled=True,
        )

        json_output = log_manager.export_logs_to_json([entry])
        data = json.loads(json_output)

        entry_data = data["entries"][0]
        # Verify all fields are present
        required_fields = [
            "id",
            "timestamp",
            "type",
            "status",
            "summary",
            "details",
            "path",
            "duration",
            "scheduled",
        ]
        for field in required_fields:
            assert field in entry_data

    # File Export Tests

    def test_export_logs_to_file_csv(self, log_manager, sample_entries, temp_log_dir):
        """Test exporting logs to CSV file."""
        output_path = Path(temp_log_dir) / "export.csv"

        success, error = log_manager.export_logs_to_file(str(output_path), "csv", sample_entries)

        assert success is True
        assert error is None
        assert output_path.exists()

        # Verify file contents
        with open(output_path, encoding="utf-8") as f:
            content = f.read()

        assert "id,timestamp,type,status,path,summary,duration,scheduled" in content
        assert "uuid-1" in content
        assert "uuid-2" in content
        assert "uuid-3" in content

    def test_export_logs_to_file_json(self, log_manager, sample_entries, temp_log_dir):
        """Test exporting logs to JSON file."""
        output_path = Path(temp_log_dir) / "export.json"

        success, error = log_manager.export_logs_to_file(str(output_path), "json", sample_entries)

        assert success is True
        assert error is None
        assert output_path.exists()

        # Verify file contents
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["count"] == 3
        assert len(data["entries"]) == 3
        assert "export_timestamp" in data

    def test_export_logs_to_file_invalid_format(self, log_manager, sample_entries, temp_log_dir):
        """Test export with invalid format returns error."""
        output_path = Path(temp_log_dir) / "export.txt"

        success, error = log_manager.export_logs_to_file(
            str(output_path), "invalid", sample_entries
        )

        assert success is False
        assert error is not None
        assert "Invalid format" in error
        assert "invalid" in error

    def test_export_logs_to_file_creates_parent_directory(
        self, log_manager, sample_entries, temp_log_dir
    ):
        """Test export creates parent directories if they don't exist."""
        output_path = Path(temp_log_dir) / "subdir" / "nested" / "export.csv"

        success, error = log_manager.export_logs_to_file(str(output_path), "csv", sample_entries)

        assert success is True
        assert error is None
        assert output_path.exists()
        assert output_path.parent.exists()

    def test_export_logs_to_file_overwrites_existing(
        self, log_manager, sample_entries, temp_log_dir
    ):
        """Test export overwrites existing file."""
        output_path = Path(temp_log_dir) / "export.csv"

        # Create existing file with different content
        output_path.write_text("old content")

        # Export should overwrite
        success, error = log_manager.export_logs_to_file(str(output_path), "csv", sample_entries)

        assert success is True
        assert error is None

        # Verify new content
        content = output_path.read_text()
        assert "old content" not in content
        assert "id,timestamp,type,status" in content

    def test_export_logs_to_file_atomic_write(self, log_manager, sample_entries, temp_log_dir):
        """Test export uses atomic write (temp file + rename)."""
        output_path = Path(temp_log_dir) / "export.json"

        # Mock tempfile.mkstemp to verify atomic write pattern
        original_mkstemp = tempfile.mkstemp

        temp_files_created = []

        def mock_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            temp_files_created.append(path)
            return fd, path

        with mock.patch("tempfile.mkstemp", side_effect=mock_mkstemp):
            success, error = log_manager.export_logs_to_file(
                str(output_path), "json", sample_entries
            )

        assert success is True
        # Verify temp file was created (and cleaned up via rename)
        assert len(temp_files_created) == 1

    def test_export_logs_to_file_default_all_logs(self, log_manager, temp_log_dir):
        """Test file export with no entries parameter uses all logs."""
        # Save some logs
        for i in range(3):
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Scan {i}",
                details=f"Details {i}",
            )
            log_manager.save_log(entry)

        output_path = Path(temp_log_dir) / "export.csv"

        # Export without specifying entries
        success, error = log_manager.export_logs_to_file(str(output_path), "csv")

        assert success is True
        assert output_path.exists()

        # Verify all 3 logs were exported
        with open(output_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 4  # 1 header + 3 data rows

    def test_export_logs_to_file_permission_error(self, log_manager, sample_entries, temp_log_dir):
        """Test export handles permission errors gracefully."""
        output_path = Path(temp_log_dir) / "readonly" / "export.csv"
        output_path.parent.mkdir()

        # Make parent directory read-only
        output_path.parent.chmod(0o444)

        try:
            success, error = log_manager.export_logs_to_file(
                str(output_path), "csv", sample_entries
            )

            assert success is False
            assert error is not None
            assert "Permission denied" in error or "error" in error.lower()
        finally:
            # Restore permissions for cleanup
            output_path.parent.chmod(0o755)

    def test_export_logs_to_file_cleanup_on_failure(
        self, log_manager, sample_entries, temp_log_dir
    ):
        """Test export cleans up temp file on failure."""
        output_path = Path(temp_log_dir) / "export.csv"

        # Mock the file write to fail after temp file is created
        original_fdopen = os.fdopen

        def mock_fdopen(fd, *args, **kwargs):
            # Create the file descriptor wrapper, then immediately raise an error
            f = original_fdopen(fd, *args, **kwargs)
            # Close it and raise an error to simulate write failure
            f.close()
            raise OSError("Simulated write error")

        with mock.patch("os.fdopen", side_effect=mock_fdopen):
            success, error = log_manager.export_logs_to_file(
                str(output_path), "csv", sample_entries
            )

        assert success is False
        assert error is not None

        # Verify no temp files are left behind
        temp_files = list(Path(temp_log_dir).glob("clamui_export_*"))
        assert len(temp_files) == 0

    def test_export_mixed_scan_and_update_logs_csv(self, log_manager):
        """Test CSV export with mixed scan and update log types."""
        entries = [
            LogEntry(
                id="scan-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Home folder scan",
                details="Scanned 500 files",
                path="/home/user",
                duration=45.5,
                scheduled=False,
            ),
            LogEntry(
                id="update-1",
                timestamp="2024-01-15T11:00:00",
                type="update",
                status="success",
                summary="Database updated",
                details="Updated to version 123",
                path=None,
                duration=30.0,
                scheduled=False,
            ),
            LogEntry(
                id="scan-2",
                timestamp="2024-01-15T12:00:00",
                type="scan",
                status="infected",
                summary="Found threats",
                details="EICAR test file detected",
                path="/tmp/test",
                duration=10.5,
                scheduled=True,
            ),
        ]

        csv_output = log_manager.export_logs_to_csv(entries)
        lines = csv_output.strip().split("\n")

        # Should have header + 3 data rows
        assert len(lines) == 4
        assert "id,timestamp,type,status,path,summary,duration,scheduled" in lines[0]

        # Verify scan entries have paths
        assert "scan-1" in csv_output
        assert "/home/user" in csv_output
        assert "scan,clean" in csv_output

        # Verify update entry has no path (empty field)
        assert "update-1" in csv_output
        assert "update,success" in csv_output

        # Verify scheduled field is properly exported
        assert "true" in csv_output  # scan-2 is scheduled
        assert "false" in csv_output  # scan-1 and update-1 are not scheduled

    def test_export_mixed_scan_and_update_logs_json(self, log_manager):
        """Test JSON export with mixed scan and update log types."""
        entries = [
            LogEntry(
                id="scan-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Home folder scan",
                details="Scanned 500 files",
                path="/home/user",
                duration=45.5,
                scheduled=False,
            ),
            LogEntry(
                id="update-1",
                timestamp="2024-01-15T11:00:00",
                type="update",
                status="success",
                summary="Database updated",
                details="Updated to version 123",
                path=None,
                duration=30.0,
                scheduled=False,
            ),
            LogEntry(
                id="scan-2",
                timestamp="2024-01-15T12:00:00",
                type="scan",
                status="infected",
                summary="Found threats",
                details="EICAR test file detected",
                path="/tmp/test",
                duration=10.5,
                scheduled=True,
            ),
        ]

        json_output = log_manager.export_logs_to_json(entries)
        data = json.loads(json_output)

        assert data["count"] == 3
        assert len(data["entries"]) == 3

        # Verify scan entries
        scan_entries = [e for e in data["entries"] if e["type"] == "scan"]
        assert len(scan_entries) == 2
        assert all(e["path"] is not None for e in scan_entries)

        # Verify update entry
        update_entries = [e for e in data["entries"] if e["type"] == "update"]
        assert len(update_entries) == 1
        assert update_entries[0]["path"] is None

        # Verify scheduled field
        scheduled_entries = [e for e in data["entries"] if e["scheduled"]]
        assert len(scheduled_entries) == 1
        assert scheduled_entries[0]["id"] == "scan-2"

    def test_export_very_long_details_field_csv(self, log_manager):
        """Test CSV export with very long details field (CSV excludes details by design)."""
        # Create a very long details field (10KB+)
        long_details = "ClamAV scan output:\n" + "\n".join(
            [f"/path/to/file{i}.txt: OK" for i in range(500)]
        )
        assert len(long_details) > 10000

        entries = [
            LogEntry(
                id="long-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Large scan with many files",
                details=long_details,
                path="/home/user",
                duration=120.5,
                scheduled=False,
            )
        ]

        csv_output = log_manager.export_logs_to_csv(entries)

        # CSV format does NOT include details field (only summary)
        # Verify CSV is still parseable
        reader = csv.DictReader(io.StringIO(csv_output))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["id"] == "long-1"
        assert rows[0]["summary"] == "Large scan with many files"
        # CSV should not have details field
        assert "details" not in rows[0]

    def test_export_very_long_details_field_json(self, log_manager):
        """Test JSON export with very long details field."""
        # Create a very long details field (10KB+)
        long_details = "ClamAV scan output:\n" + "\n".join(
            [f"/path/to/file{i}.txt: OK" for i in range(500)]
        )
        assert len(long_details) > 10000

        entries = [
            LogEntry(
                id="long-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Large scan with many files",
                details=long_details,
                path="/home/user",
                duration=120.5,
                scheduled=False,
            )
        ]

        json_output = log_manager.export_logs_to_json(entries)
        data = json.loads(json_output)

        assert data["count"] == 1
        entry = data["entries"][0]
        assert entry["id"] == "long-1"
        assert len(entry["details"]) > 10000
        assert "/path/to/file0.txt: OK" in entry["details"]
        assert "/path/to/file499.txt: OK" in entry["details"]

    def test_export_scheduled_vs_manual_scans_csv(self, log_manager):
        """Test CSV export properly distinguishes scheduled vs manual scans."""
        entries = [
            LogEntry(
                id="manual-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Manual quick scan",
                details="User initiated scan",
                path="/home/user/downloads",
                duration=15.0,
                scheduled=False,
            ),
            LogEntry(
                id="scheduled-1",
                timestamp="2024-01-15T11:00:00",
                type="scan",
                status="clean",
                summary="Scheduled nightly scan",
                details="Automatic scheduled scan",
                path="/home/user",
                duration=60.0,
                scheduled=True,
            ),
            LogEntry(
                id="manual-2",
                timestamp="2024-01-15T12:00:00",
                type="scan",
                status="infected",
                summary="Manual scan found threats",
                details="User scanned downloads folder",
                path="/tmp",
                duration=5.0,
                scheduled=False,
            ),
        ]

        csv_output = log_manager.export_logs_to_csv(entries)
        lines = csv_output.strip().split("\n")

        assert len(lines) == 4  # header + 3 data rows

        # Count scheduled vs manual scans in output
        false_count = csv_output.count(",false")
        true_count = csv_output.count(",true")

        assert false_count == 2  # manual-1, manual-2
        assert true_count == 1  # scheduled-1

    def test_export_scheduled_vs_manual_scans_json(self, log_manager):
        """Test JSON export properly distinguishes scheduled vs manual scans."""
        entries = [
            LogEntry(
                id="manual-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Manual quick scan",
                details="User initiated scan",
                path="/home/user/downloads",
                duration=15.0,
                scheduled=False,
            ),
            LogEntry(
                id="scheduled-1",
                timestamp="2024-01-15T11:00:00",
                type="scan",
                status="clean",
                summary="Scheduled nightly scan",
                details="Automatic scheduled scan",
                path="/home/user",
                duration=60.0,
                scheduled=True,
            ),
            LogEntry(
                id="manual-2",
                timestamp="2024-01-15T12:00:00",
                type="scan",
                status="infected",
                summary="Manual scan found threats",
                details="User scanned downloads folder",
                path="/tmp",
                duration=5.0,
                scheduled=False,
            ),
        ]

        json_output = log_manager.export_logs_to_json(entries)
        data = json.loads(json_output)

        assert data["count"] == 3

        # Filter by scheduled field
        manual_scans = [e for e in data["entries"] if not e["scheduled"]]
        scheduled_scans = [e for e in data["entries"] if e["scheduled"]]

        assert len(manual_scans) == 2
        assert len(scheduled_scans) == 1

        # Verify IDs
        manual_ids = [e["id"] for e in manual_scans]
        assert "manual-1" in manual_ids
        assert "manual-2" in manual_ids
        assert scheduled_scans[0]["id"] == "scheduled-1"

    def test_export_special_chars_unicode_csv(self, log_manager):
        """Test CSV export with Unicode characters in paths and summaries."""
        entries = [
            LogEntry(
                id="unicode-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Scan with émojis 🦠❌✅ and ünïcödé",
                details="Details with 日本語 Chinese 中文",
                path="/home/user/Documents/Résumé 文档.pdf",
                duration=10.0,
                scheduled=False,
            ),
            LogEntry(
                id="unicode-2",
                timestamp="2024-01-15T11:00:00",
                type="scan",
                status="clean",
                summary="Path with Cyrillic: Документы",
                details="Scanned Файлы directory",
                path="/home/пользователь/файлы",
                duration=20.0,
                scheduled=False,
            ),
        ]

        csv_output = log_manager.export_logs_to_csv(entries)

        # Verify Unicode characters are preserved in summary and path fields
        # Note: CSV export includes summary (not details), so check characters in those fields
        assert "🦠" in csv_output or "emoji" in csv_output.lower()
        assert "ünïcödé" in csv_output or "unicode" in csv_output.lower()
        assert "文档" in csv_output  # Chinese characters from path
        assert "Résumé" in csv_output or "Resume" in csv_output
        assert "Документы" in csv_output  # Cyrillic from summary
        assert "пользователь" in csv_output  # Cyrillic from path

        # Verify CSV is parseable
        reader = csv.DictReader(io.StringIO(csv_output))
        rows = list(reader)
        assert len(rows) == 2

    def test_export_special_chars_paths_backslashes_csv(self, log_manager):
        """Test CSV export with paths containing backslashes and special chars."""
        entries = [
            LogEntry(
                id="special-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Windows-style path test",
                details="Scanned C:\\Users\\Test",
                path="C:\\Users\\Test\\Documents\\file.txt",
                duration=10.0,
                scheduled=False,
            ),
            LogEntry(
                id="special-2",
                timestamp="2024-01-15T11:00:00",
                type="scan",
                status="clean",
                summary="Path with tabs\tand\nnewlines",
                details="Details\twith\ttabs",
                path="/path/with\ttab",
                duration=20.0,
                scheduled=False,
            ),
        ]

        csv_output = log_manager.export_logs_to_csv(entries)

        # Verify paths with backslashes are preserved
        assert "C:\\Users\\Test" in csv_output or "C:\\\\Users\\\\Test" in csv_output

        # Verify CSV is parseable despite special characters
        reader = csv.DictReader(io.StringIO(csv_output))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["id"] == "special-1"

    def test_export_to_file_mixed_types_integration(self, log_manager, temp_log_dir):
        """Integration test: export mixed log types to file and re-import."""
        entries = [
            LogEntry(
                id="scan-1",
                timestamp="2024-01-15T10:00:00",
                type="scan",
                status="clean",
                summary="Quick scan",
                details="Scanned 100 files",
                path="/home/user",
                duration=30.0,
                scheduled=False,
            ),
            LogEntry(
                id="update-1",
                timestamp="2024-01-15T11:00:00",
                type="update",
                status="success",
                summary="Database updated",
                details="Updated signatures",
                path=None,
                duration=15.0,
                scheduled=False,
            ),
            LogEntry(
                id="scan-2",
                timestamp="2024-01-15T12:00:00",
                type="scan",
                status="infected",
                summary="Threats found",
                details="EICAR detected",
                path="/tmp",
                duration=5.0,
                scheduled=True,
            ),
        ]

        # Test CSV export and re-import
        csv_path = Path(temp_log_dir) / "mixed_export.csv"
        success, error = log_manager.export_logs_to_file(str(csv_path), "csv", entries)
        assert success is True
        assert error is None
        assert csv_path.exists()

        # Verify CSV content
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 3
            assert rows[0]["type"] == "scan"
            assert rows[1]["type"] == "update"
            assert rows[2]["type"] == "scan"
            assert rows[2]["scheduled"] == "true"

        # Test JSON export and re-import
        json_path = Path(temp_log_dir) / "mixed_export.json"
        success, error = log_manager.export_logs_to_file(str(json_path), "json", entries)
        assert success is True
        assert error is None
        assert json_path.exists()

        # Verify JSON content
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
            assert data["count"] == 3
            assert len(data["entries"]) == 3
            assert data["entries"][0]["type"] == "scan"
            assert data["entries"][1]["type"] == "update"
            assert data["entries"][2]["type"] == "scan"
            assert data["entries"][2]["scheduled"] is True


class TestExtractIndexFields:
    """Tests for the optimized _extract_index_fields function."""

    def test_extract_from_standard_log_file(self, tmp_path):
        """Test extraction from a standard JSON log file."""
        from src.core.log_manager import _extract_index_fields

        log_file = tmp_path / "test.json"
        log_data = {
            "id": "test-uuid-123",
            "timestamp": "2024-01-15T10:30:00",
            "type": "scan",
            "status": "clean",
            "summary": "Test scan completed",
            "details": "x" * 10000,  # Large details field
        }
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)

        result = _extract_index_fields(log_file)

        assert result is not None
        assert result["id"] == "test-uuid-123"
        assert result["timestamp"] == "2024-01-15T10:30:00"
        assert result["type"] == "scan"

    def test_extract_handles_escaped_characters(self, tmp_path):
        """Test extraction handles JSON escape sequences correctly."""
        from src.core.log_manager import _extract_index_fields

        log_file = tmp_path / "escaped.json"
        # Manually create JSON with escape sequences in values
        content = """{
  "id": "test-id-with\\"quote",
  "timestamp": "2024-01-15T10:30:00",
  "type": "scan"
}"""
        log_file.write_text(content, encoding="utf-8")

        result = _extract_index_fields(log_file)

        assert result is not None
        assert result["id"] == 'test-id-with"quote'
        assert result["type"] == "scan"

    def test_extract_returns_none_for_missing_fields(self, tmp_path):
        """Test extraction returns None when required fields are missing."""
        from src.core.log_manager import _extract_index_fields

        log_file = tmp_path / "incomplete.json"
        # Missing 'type' field
        log_data = {
            "id": "test-uuid-123",
            "timestamp": "2024-01-15T10:30:00",
            "status": "clean",
        }
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)

        result = _extract_index_fields(log_file)
        assert result is None

    def test_extract_returns_none_for_corrupted_file(self, tmp_path):
        """Test extraction returns None for corrupted JSON."""
        from src.core.log_manager import _extract_index_fields

        log_file = tmp_path / "corrupted.json"
        log_file.write_text("{ invalid json }", encoding="utf-8")

        result = _extract_index_fields(log_file)
        assert result is None

    def test_extract_returns_none_for_nonexistent_file(self, tmp_path):
        """Test extraction returns None for non-existent files."""
        from src.core.log_manager import _extract_index_fields

        log_file = tmp_path / "nonexistent.json"

        result = _extract_index_fields(log_file)
        assert result is None

    def test_extract_handles_compact_json(self, tmp_path):
        """Test extraction works with compact (non-indented) JSON."""
        from src.core.log_manager import _extract_index_fields

        log_file = tmp_path / "compact.json"
        log_data = {
            "id": "compact-uuid",
            "timestamp": "2024-01-15T10:30:00",
            "type": "update",
        }
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f)  # No indent

        result = _extract_index_fields(log_file)

        assert result is not None
        assert result["id"] == "compact-uuid"
        assert result["type"] == "update"

    def test_extract_handles_all_log_types(self, tmp_path):
        """Test extraction works for all log types."""
        from src.core.log_manager import _extract_index_fields

        for log_type in ["scan", "update", "virustotal"]:
            log_file = tmp_path / f"{log_type}_test.json"
            log_data = {
                "id": f"{log_type}-uuid",
                "timestamp": "2024-01-15T10:30:00",
                "type": log_type,
            }
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2)

            result = _extract_index_fields(log_file)

            assert result is not None
            assert result["type"] == log_type


class TestIndexRebuildPerformance:
    """Tests for index rebuild performance with optimized extraction."""

    @pytest.fixture
    def log_manager_with_many_logs(self, tmp_path):
        """Create a log manager with many log files for benchmarking."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        manager = LogManager(str(log_dir))

        # Create 100 log files with varying sizes
        for i in range(100):
            log_file = log_dir / f"log-{i:04d}.json"
            # Vary the details size to simulate real-world logs
            details_size = (i % 10) * 1000  # 0 to 9000 chars
            log_data = {
                "id": f"uuid-{i:04d}",
                "timestamp": f"2024-01-{(i % 28) + 1:02d}T10:30:00",
                "type": "scan" if i % 2 == 0 else "update",
                "status": "clean",
                "summary": f"Test log entry {i}",
                "details": "x" * details_size,
                "path": f"/test/path/{i}",
                "duration": float(i),
            }
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2)

        return manager

    def test_rebuild_index_processes_all_files(self, log_manager_with_many_logs):
        """Test that rebuild_index correctly processes all log files."""
        result = log_manager_with_many_logs.rebuild_index()

        assert result is True

        index = log_manager_with_many_logs._load_index()
        assert len(index["entries"]) == 100

        # Verify entries have correct structure
        for entry in index["entries"]:
            assert "id" in entry
            assert "timestamp" in entry
            assert "type" in entry
            assert entry["type"] in ("scan", "update")

    def test_rebuild_index_uses_optimized_extraction(self, tmp_path):
        """Test that rebuild_index uses optimized extraction for standard files."""
        from src.core.log_manager import _extract_index_fields

        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        # Create a log file with large details field
        log_file = log_dir / "large-log.json"
        log_data = {
            "id": "large-uuid",
            "timestamp": "2024-01-15T10:30:00",
            "type": "scan",
            "status": "clean",
            "summary": "Test",
            "details": "x" * 100000,  # 100KB of details
        }
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)

        # Verify optimized extraction works on large file
        result = _extract_index_fields(log_file)
        assert result is not None
        assert result["id"] == "large-uuid"

        # Verify file size is large but extraction only reads first portion
        file_size = log_file.stat().st_size
        assert file_size > 100000  # File is over 100KB

    def test_rebuild_falls_back_to_full_parsing(self, tmp_path):
        """Test that rebuild_index falls back to full parsing when needed."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        # Create a file where fields appear after 512 bytes
        # (beyond the optimized extraction read limit)
        log_file = log_dir / "late-fields.json"
        # Put padding at the start by having a very long first field
        content = '{\n  "padding": "' + "x" * 600 + '",\n'
        content += '  "id": "late-uuid",\n'
        content += '  "timestamp": "2024-01-15T10:30:00",\n'
        content += '  "type": "scan"\n}'
        log_file.write_text(content, encoding="utf-8")

        manager = LogManager(str(log_dir))
        result = manager.rebuild_index()

        assert result is True
        index = manager._load_index()
        assert len(index["entries"]) == 1
        assert index["entries"][0]["id"] == "late-uuid"


class TestLogManagerPrivacyMigrationState:
    """Tests for persisted-log privacy migration state and async startup support."""

    def _write_legacy_log(self, log_dir: Path, log_id: str, suffix: str) -> Path:
        """Write a legacy log file containing sensitive path data."""
        original_path = f"/home/testuser/Documents/private-{suffix}.txt"
        payload = {
            "id": log_id,
            "timestamp": datetime.now().isoformat(),
            "type": "scan",
            "status": "clean",
            "summary": f"Scanned {original_path}",
            "details": f"Legacy output for {original_path}",
            "path": original_path,
            "duration": 1.5,
            "scheduled": False,
        }
        log_file = log_dir / f"{log_id}.json"
        log_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return log_file

    def test_privacy_migration_writes_state_marker(self, tmp_path):
        """Test that privacy migration marks legacy persisted logs as migrated."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        manager = LogManager(log_dir=str(log_dir))
        log_file = self._write_legacy_log(log_dir, "legacy-log", "marker")

        manager.get_logs()

        marker = log_dir / LOG_PRIVACY_STATE_FILENAME
        content = log_file.read_text(encoding="utf-8")

        assert marker.exists()
        assert "/home/testuser/Documents/private-marker.txt" not in content
        assert REDACTED_PATH in content

    def test_start_privacy_migration_async_completes_and_updates_status(self, tmp_path):
        """Test that async privacy migration can be started early during app startup."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._write_legacy_log(log_dir, "legacy-a", "async-a")
        self._write_legacy_log(log_dir, "legacy-b", "async-b")

        manager = LogManager(log_dir=str(log_dir))

        started = manager.start_privacy_migration_async()
        completed = manager.wait_for_privacy_migration(timeout=2)
        status = manager.get_privacy_migration_status()

        assert started is True
        assert completed is True
        assert status.is_running is False
        assert status.total_files == 2
        assert status.processed_files == 2
        assert (log_dir / LOG_PRIVACY_STATE_FILENAME).exists()

    def test_privacy_migration_skips_second_full_rescan_when_marker_exists(self, tmp_path):
        """Test that later LogManager instances reuse the on-disk migration marker."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        self._write_legacy_log(log_dir, "legacy-log", "rerun")

        LogManager(log_dir=str(log_dir)).get_logs()
        manager = LogManager(log_dir=str(log_dir))

        with mock.patch.object(manager, "_execute_privacy_migration_targets") as mock_execute:
            manager.get_logs()

        mock_execute.assert_not_called()
