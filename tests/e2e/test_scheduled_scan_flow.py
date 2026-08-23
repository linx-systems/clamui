# ClamUI Scheduled Scan E2E Tests
"""
End-to-end tests for the complete scheduled scan workflow.

These tests verify the full flow from configuration to execution,
including systemd/cron integration, battery awareness, quarantine,
notifications, and logging.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Store original gi modules to restore later (if they exist)
_original_gi = sys.modules.get("gi")
_original_gi_repository = sys.modules.get("gi.repository")

# Mock gi module before importing to avoid GTK dependencies in tests
sys.modules["gi"] = mock.MagicMock()
sys.modules["gi.repository"] = mock.MagicMock()

from src.core.battery_manager import BatteryManager, BatteryStatus
from src.core.log_manager import LogEntry, LogManager
from src.core.quarantine.manager import (
    QuarantineManager,
    QuarantineStatus,
)
from src.core.sanitize import REDACTED_PATH
from src.core.scheduler import ScheduleFrequency, Scheduler, SchedulerBackend
from src.core.settings_manager import SettingsManager

# Restore original gi modules after imports are done
if _original_gi is not None:
    sys.modules["gi"] = _original_gi
else:
    del sys.modules["gi"]
if _original_gi_repository is not None:
    sys.modules["gi.repository"] = _original_gi_repository
else:
    del sys.modules["gi.repository"]


class TestE2EScheduleConfiguration:
    """E2E tests for schedule configuration flow."""

    @pytest.fixture
    def full_test_env(self):
        """Create a complete test environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            # Create directory structure
            config_dir = base / "config"
            log_dir = base / "logs"
            data_dir = base / "data"
            scan_dir = base / "scan_target"
            quarantine_dir = data_dir / "quarantine"

            for d in [config_dir, log_dir, data_dir, scan_dir]:
                d.mkdir(parents=True)

            # Create test files to scan
            for i in range(10):
                (scan_dir / f"document_{i}.txt").write_text(f"Document content {i}")

            yield {
                "base": base,
                "config_dir": config_dir,
                "log_dir": log_dir,
                "data_dir": data_dir,
                "scan_dir": scan_dir,
                "quarantine_dir": quarantine_dir,
            }

    def test_e2e_configure_weekly_schedule(self, full_test_env):
        """
        E2E Test: Configure weekly schedule via settings.

        Steps:
        1. Configure weekly schedule with battery skip enabled
        2. Verify settings persisted correctly
        3. Verify scheduler can create schedule
        """
        config_dir = full_test_env["config_dir"]
        scan_dir = full_test_env["scan_dir"]

        # Step 1: Configure settings
        settings = SettingsManager(config_dir=config_dir)
        settings.set("scheduled_scans_enabled", True)
        settings.set("schedule_frequency", "weekly")
        settings.set("schedule_time", "02:00")
        settings.set("schedule_targets", [str(scan_dir)])
        settings.set("schedule_skip_on_battery", True)
        settings.set("schedule_auto_quarantine", False)
        settings.set("schedule_day_of_week", 0)  # Monday

        # Step 2: Verify settings persisted
        settings_file = config_dir / "settings.json"
        assert settings_file.exists()

        with open(settings_file) as f:
            saved = json.load(f)

        assert saved["scheduled_scans_enabled"] is True
        assert saved["schedule_frequency"] == "weekly"
        assert saved["schedule_time"] == "02:00"
        assert saved["schedule_targets"] == [str(scan_dir)]
        assert saved["schedule_skip_on_battery"] is True

        # Step 3: Verify scheduler can work with these settings
        scheduler = Scheduler(config_dir=config_dir)
        assert scheduler.is_available or scheduler.backend == SchedulerBackend.NONE

    def test_e2e_scheduler_creates_timer_or_crontab(self, full_test_env):
        """
        E2E Test: Verify systemd timer created OR crontab entry added.

        This tests the scheduler integration with the system.
        """
        config_dir = full_test_env["config_dir"]
        scan_dir = full_test_env["scan_dir"]

        scheduler = Scheduler(config_dir=config_dir)

        if not scheduler.is_available:
            pytest.skip("No scheduler backend available on this system")

        # Mock the CLI path to avoid needing the actual executable
        with mock.patch.object(
            scheduler, "_get_cli_command_path", return_value=["/usr/bin/clamui-scheduled-scan"]
        ):
            if scheduler.backend == SchedulerBackend.SYSTEMD:
                # Test systemd timer creation
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")

                    success, error = scheduler.enable_schedule(
                        frequency="weekly",
                        time="02:00",
                        targets=[str(scan_dir)],
                        day_of_week=0,
                        skip_on_battery=True,
                        auto_quarantine=False,
                    )

                    if success:
                        # Verify timer file was created
                        timer_file = scheduler._systemd_dir / "clamui-scheduled-scan.timer"
                        assert timer_file.exists()

                        # Verify timer content
                        content = timer_file.read_text()
                        assert "OnCalendar=" in content
                        assert "Mon" in content  # Monday
                        assert "02:00" in content

            elif scheduler.backend == SchedulerBackend.CRON:
                # Test cron entry format
                cron_entry = scheduler._generate_crontab_entry(
                    ScheduleFrequency.WEEKLY, "02:00", day_of_week=0
                )
                # Monday is 0 in our format, 1 in cron format
                assert cron_entry == "0 2 * * 1"


class TestE2EScheduledScanExecution:
    """E2E tests for scheduled scan execution."""

    @pytest.fixture
    def scan_test_env(self):
        """Create environment for scan execution tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            config_dir = base / "config"
            log_dir = base / "logs"
            scan_dir = base / "scan_target"
            quarantine_dir = base / "quarantine"

            for d in [config_dir, log_dir, scan_dir]:
                d.mkdir(parents=True)

            # Create test files
            for i in range(5):
                (scan_dir / f"file_{i}.txt").write_text(f"Content {i}")

            yield {
                "base": base,
                "config_dir": config_dir,
                "log_dir": log_dir,
                "scan_dir": scan_dir,
                "quarantine_dir": quarantine_dir,
            }

    def test_e2e_cli_wrapper_dry_run(self, scan_test_env):
        """
        E2E Test: Trigger scheduled scan manually via CLI wrapper (dry run).

        Steps:
        1. Run CLI wrapper in dry-run mode
        2. Verify it completes successfully
        3. Verify no actual scan was performed
        """
        from src.cli.scheduled_scan import run_scheduled_scan

        scan_dir = scan_test_env["scan_dir"]

        # Run in dry-run mode
        result = run_scheduled_scan(
            targets=[str(scan_dir)],
            skip_on_battery=False,
            auto_quarantine=False,
            dry_run=True,
            verbose=True,
        )

        # Should complete successfully
        assert result == 0

    def test_e2e_scheduled_scan_creates_log(self, scan_test_env):
        """
        E2E Test: Verify scan creates log entry with scheduled=True.

        Steps:
        1. Create a log entry as a scheduled scan would
        2. Verify entry has scheduled=True
        3. Verify entry appears in log manager
        """
        log_dir = scan_test_env["log_dir"]
        scan_dir = scan_test_env["scan_dir"]

        log_manager = LogManager(log_dir=log_dir)

        # Create log entry as scheduled scan would
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scheduled scan completed - 5 files scanned, no threats",
            details="Scan Duration: 3.2 seconds\nFiles Scanned: 5\nThreats Found: 0",
            path=str(scan_dir),
            duration=3.2,
            scheduled=True,
        )
        log_manager.save_log(entry)

        # Verify log entry
        logs = log_manager.get_logs()
        assert len(logs) == 1

        saved_entry = logs[0]
        assert saved_entry.scheduled is True
        assert saved_entry.type == "scan"
        assert saved_entry.status == "clean"
        assert "5 files scanned" in saved_entry.summary


class TestE2EBatterySkip:
    """E2E tests for battery skip behavior."""

    def test_e2e_battery_skip_on_battery(self):
        """
        E2E Test: Battery skip behavior when on battery.

        Steps:
        1. Mock battery manager to report on battery
        2. Verify should_skip_scan returns True
        """
        manager = BatteryManager()

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=False, percent=45.0),
        ):
            assert manager.should_skip_scan(skip_on_battery=True) is True

    def test_e2e_battery_skip_when_plugged(self):
        """
        E2E Test: Battery skip behavior when plugged in.

        Steps:
        1. Mock battery manager to report plugged in
        2. Verify should_skip_scan returns False
        """
        manager = BatteryManager()

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=True, percent=100.0),
        ):
            assert manager.should_skip_scan(skip_on_battery=True) is False

    def test_e2e_battery_skip_desktop(self):
        """
        E2E Test: Battery skip behavior on desktop (no battery).

        Steps:
        1. Mock battery manager to report no battery
        2. Verify should_skip_scan returns False (never skip on desktop)
        """
        manager = BatteryManager()

        with mock.patch.object(
            manager, "get_status", return_value=BatteryStatus(has_battery=False, is_plugged=True)
        ):
            assert manager.should_skip_scan(skip_on_battery=True) is False

    def test_e2e_battery_skip_disabled(self):
        """
        E2E Test: Battery skip when option disabled.

        Steps:
        1. Mock battery manager to report on battery
        2. Verify should_skip_scan returns False when skip_on_battery=False
        """
        manager = BatteryManager()

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=False, percent=20.0),
        ):
            # Even on battery, should not skip if option disabled
            assert manager.should_skip_scan(skip_on_battery=False) is False


class TestE2EQuarantine:
    """E2E tests for automatic quarantine using QuarantineManager."""

    @pytest.fixture
    def quarantine_test_env(self):
        """Create environment for quarantine tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            scan_dir = base / "infected_files"
            quarantine_dir = base / "quarantine"
            db_path = base / "quarantine.db"
            scan_dir.mkdir(parents=True)

            # Create "infected" test files
            infected_files = []
            for i in range(3):
                f = scan_dir / f"infected_{i}.exe"
                f.write_bytes(f"malware content {i}".encode())
                infected_files.append(str(f))

            yield {
                "base": base,
                "scan_dir": scan_dir,
                "quarantine_dir": quarantine_dir,
                "db_path": db_path,
                "infected_files": infected_files,
            }

    @pytest.fixture
    def manager(self, quarantine_test_env):
        """Create a QuarantineManager for testing."""
        mgr = QuarantineManager(
            quarantine_directory=str(quarantine_test_env["quarantine_dir"]),
            database_path=str(quarantine_test_env["db_path"]),
        )
        yield mgr
        mgr._database.close()

    def test_e2e_quarantine_infected_files(self, quarantine_test_env, manager):
        """
        E2E Test: QuarantineManager moves infected files.

        Steps:
        1. Use QuarantineManager to quarantine detected threats
        2. Verify files moved to quarantine
        3. Verify database entries created
        """
        quarantine_dir = quarantine_test_env["quarantine_dir"]
        infected_files = quarantine_test_env["infected_files"]

        # Quarantine each file using QuarantineManager
        quarantined = []
        failed = []
        for file_path in infected_files:
            result = manager.quarantine_file(file_path, f"Win.Trojan.Test-{Path(file_path).name}")
            if result.is_success:
                quarantined.append(result.entry)
            else:
                failed.append((file_path, result.error_message))

        # Verify all files were quarantined
        assert len(quarantined) == 3
        assert len(failed) == 0

        # Verify original files are gone
        for f in infected_files:
            assert not Path(f).exists()

        # Verify quarantine directory has files
        assert quarantine_dir.exists()
        assert manager.get_entry_count() == 3

        # Verify each quarantined file exists
        for entry in quarantined:
            assert Path(entry.quarantine_path).exists()
            assert entry.quarantine_path.startswith(str(quarantine_dir))

        # Verify quarantine directory permissions
        mode = quarantine_dir.stat().st_mode & 0o777
        assert mode == 0o700

    def test_e2e_quarantine_file_permissions(self, quarantine_test_env, manager):
        """
        E2E Test: Quarantined files have restricted permissions.

        Steps:
        1. Quarantine a file using QuarantineManager
        2. Verify file has read-only permissions (0400)
        """
        infected_files = quarantine_test_env["infected_files"][:1]  # Just one file

        # Quarantine using QuarantineManager
        result = manager.quarantine_file(infected_files[0], "Win.Trojan.Test")
        assert result.is_success is True
        assert result.status == QuarantineStatus.SUCCESS
        assert result.entry is not None

        # Check file permissions (should be 0400 - read-only for owner)
        quarantine_path = Path(result.entry.quarantine_path)
        assert quarantine_path.exists()
        mode = quarantine_path.stat().st_mode & 0o777
        assert mode == 0o400

    def test_e2e_quarantine_database_integration(self, quarantine_test_env, manager):
        """
        E2E Test: QuarantineManager records entries in database.

        Steps:
        1. Quarantine files
        2. Verify database entries match quarantined files
        3. Verify entry metadata is correct
        """
        infected_files = quarantine_test_env["infected_files"]

        # Quarantine files
        entries = []
        for i, file_path in enumerate(infected_files):
            threat_name = f"Win.Trojan.Variant{i}"
            result = manager.quarantine_file(file_path, threat_name)
            assert result.is_success
            entries.append(result.entry)

        # Verify database entries
        all_entries = manager.get_all_entries()
        assert len(all_entries) == 3

        # Verify entry metadata
        for entry in entries:
            retrieved = manager.get_entry(entry.id)
            assert retrieved is not None
            assert retrieved.original_path == entry.original_path
            assert retrieved.threat_name == entry.threat_name
            assert len(retrieved.file_hash) == 64  # SHA256 hash

    def test_e2e_quarantine_total_size_tracking(self, quarantine_test_env, manager):
        """
        E2E Test: QuarantineManager tracks total quarantine size.

        Steps:
        1. Get initial total size (should be 0)
        2. Quarantine files
        3. Verify total size updated correctly
        """
        infected_files = quarantine_test_env["infected_files"]

        # Initial state
        assert manager.get_total_size() == 0
        assert manager.get_entry_count() == 0

        # Get expected total size before quarantining
        expected_total = sum(Path(f).stat().st_size for f in infected_files)

        # Quarantine all files
        for file_path in infected_files:
            result = manager.quarantine_file(file_path, "TestThreat")
            assert result.is_success

        # Verify total size matches
        assert manager.get_total_size() == expected_total
        assert manager.get_entry_count() == 3


class TestE2EFullWorkflow:
    """Complete end-to-end workflow tests."""

    @pytest.fixture
    def complete_env(self):
        """Create a complete test environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            config_dir = base / "config"
            log_dir = base / "logs"
            scan_dir = base / "scan_target"
            quarantine_dir = base / "quarantine"
            db_path = base / "quarantine.db"

            for d in [config_dir, log_dir, scan_dir]:
                d.mkdir(parents=True)

            # Create clean test files
            for i in range(10):
                (scan_dir / f"document_{i}.txt").write_text(f"Clean document {i}")

            yield {
                "base": base,
                "config_dir": config_dir,
                "log_dir": log_dir,
                "scan_dir": scan_dir,
                "quarantine_dir": quarantine_dir,
                "db_path": db_path,
            }

    def test_e2e_complete_workflow(self, complete_env):
        """
        E2E Test: Complete scheduled scan workflow.

        Steps:
        1. Configure weekly schedule with battery skip and quarantine options
        2. Verify settings saved
        3. Simulate scheduled scan execution
        4. Verify log entry created with scheduled=True
        5. Verify all components work together
        """
        config_dir = complete_env["config_dir"]
        log_dir = complete_env["log_dir"]
        scan_dir = complete_env["scan_dir"]

        # Step 1: Configure settings
        settings = SettingsManager(config_dir=config_dir)
        settings.set("scheduled_scans_enabled", True)
        settings.set("schedule_frequency", "weekly")
        settings.set("schedule_time", "02:00")
        settings.set("schedule_targets", [str(scan_dir)])
        settings.set("schedule_skip_on_battery", True)
        settings.set("schedule_auto_quarantine", True)
        settings.set("schedule_day_of_week", 0)

        # Step 2: Verify settings
        settings2 = SettingsManager(config_dir=config_dir)
        assert settings2.get("scheduled_scans_enabled") is True
        assert settings2.get("schedule_frequency") == "weekly"

        # Step 3: Check battery status (simulated)
        battery = BatteryManager()
        with mock.patch.object(
            battery,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=True, percent=100.0),
        ):
            should_skip = battery.should_skip_scan(
                skip_on_battery=settings2.get("schedule_skip_on_battery")
            )
            assert should_skip is False  # Plugged in, should not skip

        # Step 4: Simulate scan execution and log creation
        log_manager = LogManager(log_dir=log_dir)

        # Create log entry as the CLI wrapper would
        entry = LogEntry.create(
            log_type="scan",
            status="clean",
            summary="Scheduled scan completed - 10 files scanned, no threats",
            details=(
                "Scan Duration: 5.3 seconds\n"
                "Files Scanned: 10\n"
                "Threats Found: 0\n"
                f"Targets: {scan_dir}"
            ),
            path=str(scan_dir),
            duration=5.3,
            scheduled=True,
        )
        log_manager.save_log(entry)

        # Step 5: Verify log entry
        logs = log_manager.get_logs()
        assert len(logs) == 1
        assert logs[0].scheduled is True
        assert logs[0].status == "clean"
        assert "10 files scanned" in logs[0].summary

        # Persisted logs should keep scan metadata without storing the target path.
        assert logs[0].path is None
        assert str(scan_dir) not in logs[0].details
        assert REDACTED_PATH in logs[0].details
        assert logs[0].duration == 5.3

    def test_e2e_workflow_with_threats(self, complete_env):
        """
        E2E Test: Complete workflow when threats are found.

        Steps:
        1. Create "infected" files
        2. Simulate scan finding threats
        3. Quarantine files using QuarantineManager
        4. Verify log shows quarantine count
        """
        log_dir = complete_env["log_dir"]
        scan_dir = complete_env["scan_dir"]
        quarantine_dir = complete_env["quarantine_dir"]
        db_path = complete_env["db_path"]

        # Create "infected" files
        infected_files = []
        for i in range(2):
            f = scan_dir / f"malware_{i}.exe"
            f.write_bytes(f"malware content {i}".encode())
            infected_files.append(str(f))

        # Quarantine files using QuarantineManager
        log_manager = LogManager(log_dir=log_dir)
        quarantine_manager = QuarantineManager(
            quarantine_directory=str(quarantine_dir),
            database_path=str(db_path),
        )

        quarantined = []
        failed = []
        for file_path in infected_files:
            result = quarantine_manager.quarantine_file(
                file_path, f"Win.Trojan.Test-{Path(file_path).name}"
            )
            if result.is_success:
                quarantined.append(result.entry)
            else:
                failed.append((file_path, result.error_message))

        # Create log entry as scheduled scan would
        entry = LogEntry.create(
            log_type="scan",
            status="infected",
            summary=f"Scheduled scan found 2 threat(s), {len(quarantined)} quarantined",
            details=(
                "Scan Duration: 8.1 seconds\n"
                f"Files Scanned: 12\n"
                f"Threats Found: 2\n"
                f"Quarantined: {len(quarantined)}\n"
                f"Targets: {scan_dir}"
            ),
            path=str(scan_dir),
            duration=8.1,
            scheduled=True,
        )
        log_manager.save_log(entry)

        # Verify
        logs = log_manager.get_logs()
        assert len(logs) == 1
        assert logs[0].scheduled is True
        assert logs[0].status == "infected"
        assert "2 threat(s)" in logs[0].summary
        assert "quarantined" in logs[0].summary.lower()

        # Verify quarantine worked using QuarantineManager
        assert len(quarantined) == 2
        assert len(failed) == 0
        assert quarantine_manager.get_entry_count() == 2

        # Verify files are in quarantine directory
        for entry in quarantined:
            assert Path(entry.quarantine_path).exists()
            assert entry.quarantine_path.startswith(str(quarantine_dir))

        # Cleanup
        quarantine_manager._database.close()
