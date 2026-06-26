# ClamUI Battery Manager Tests
"""Unit tests for the BatteryManager class."""

from unittest import mock

import pytest

from src.core.battery_manager import PSUTIL_AVAILABLE, BatteryManager, BatteryStatus


class TestBatteryStatus:
    """Tests for BatteryStatus dataclass."""

    def test_battery_status_creation(self):
        """Test BatteryStatus can be created with all fields."""
        status = BatteryStatus(
            has_battery=True, is_plugged=False, percent=75.0, time_remaining=3600
        )
        assert status.has_battery is True
        assert status.is_plugged is False
        assert status.percent == 75.0
        assert status.time_remaining == 3600

    def test_battery_status_defaults(self):
        """Test BatteryStatus has correct default values."""
        status = BatteryStatus(has_battery=False, is_plugged=True)
        assert status.percent is None
        assert status.time_remaining is None


class TestBatteryManagerInit:
    """Tests for BatteryManager initialization."""

    def test_init_detects_psutil_availability(self):
        """Test BatteryManager detects psutil availability."""
        manager = BatteryManager()
        assert manager._psutil_available == PSUTIL_AVAILABLE

    def test_psutil_available_property(self):
        """Test psutil_available property reflects module status."""
        manager = BatteryManager()
        assert manager.psutil_available == PSUTIL_AVAILABLE


class TestBatteryManagerGetStatus:
    """Tests for BatteryManager.get_status()."""

    def test_get_status_no_psutil(self):
        """Test get_status returns desktop-like status when psutil unavailable."""
        manager = BatteryManager()
        manager._psutil_available = False

        status = manager.get_status()

        assert status.has_battery is False
        assert status.is_plugged is True
        assert status.percent is None
        assert status.time_remaining is None

    def test_get_status_desktop_no_battery(self):
        """Test get_status for desktop system (no battery)."""
        manager = BatteryManager()

        with mock.patch("psutil.sensors_battery", return_value=None):
            status = manager.get_status()

        assert status.has_battery is False
        assert status.is_plugged is True

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not installed")
    def test_get_status_laptop_plugged_in(self):
        """Test get_status for laptop plugged in."""
        manager = BatteryManager()

        mock_battery = mock.MagicMock()
        mock_battery.percent = 85.0
        mock_battery.power_plugged = True
        mock_battery.secsleft = -1  # -1 when charging

        with mock.patch("psutil.sensors_battery", return_value=mock_battery):
            status = manager.get_status()

        assert status.has_battery is True
        assert status.is_plugged is True
        assert status.percent == 85.0
        assert status.time_remaining is None  # -1 is converted to None

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not installed")
    def test_get_status_laptop_on_battery(self):
        """Test get_status for laptop on battery power."""
        manager = BatteryManager()

        mock_battery = mock.MagicMock()
        mock_battery.percent = 45.0
        mock_battery.power_plugged = False
        mock_battery.secsleft = 7200  # 2 hours remaining

        with mock.patch("psutil.sensors_battery", return_value=mock_battery):
            status = manager.get_status()

        assert status.has_battery is True
        assert status.is_plugged is False
        assert status.percent == 45.0
        assert status.time_remaining == 7200

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not installed")
    def test_get_status_power_plugged_undetermined(self):
        """Test undetermined power_plugged (None) is treated as plugged-in."""
        manager = BatteryManager()

        mock_battery = mock.MagicMock()
        mock_battery.percent = 50.0
        mock_battery.power_plugged = None  # psutil reports None when AC is undetermined
        mock_battery.secsleft = -1

        with mock.patch("psutil.sensors_battery", return_value=mock_battery):
            status = manager.get_status()
            # Undetermined => plugged-in => do NOT skip scheduled scans
            assert status.is_plugged is True
            assert manager.is_on_battery() is False

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not installed")
    def test_get_status_handles_psutil_exception(self):
        """Test get_status handles psutil exceptions gracefully."""
        manager = BatteryManager()

        with mock.patch("psutil.sensors_battery", side_effect=Exception("psutil error")):
            status = manager.get_status()

        # Should return safe defaults (no battery, plugged in)
        assert status.has_battery is False
        assert status.is_plugged is True


class TestBatteryManagerIsOnBattery:
    """Tests for BatteryManager.is_on_battery()."""

    def test_is_on_battery_desktop(self):
        """Test is_on_battery returns False for desktop systems."""
        manager = BatteryManager()

        with mock.patch.object(
            manager, "get_status", return_value=BatteryStatus(has_battery=False, is_plugged=True)
        ):
            assert manager.is_on_battery() is False

    def test_is_on_battery_laptop_plugged_in(self):
        """Test is_on_battery returns False when laptop is plugged in."""
        manager = BatteryManager()

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=True, percent=80.0),
        ):
            assert manager.is_on_battery() is False

    def test_is_on_battery_laptop_unplugged(self):
        """Test is_on_battery returns True when laptop is on battery."""
        manager = BatteryManager()

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=False, percent=60.0),
        ):
            assert manager.is_on_battery() is True


class TestBatteryManagerShouldSkipScan:
    """Tests for BatteryManager.should_skip_scan()."""

    def test_should_skip_scan_disabled(self):
        """Test should_skip_scan returns False when skip_on_battery is False."""
        manager = BatteryManager()

        # Even on battery, should not skip if option is disabled
        with mock.patch.object(manager, "is_on_battery", return_value=True):
            assert manager.should_skip_scan(skip_on_battery=False) is False

    def test_should_skip_scan_on_battery(self):
        """Test should_skip_scan returns True when on battery and option enabled."""
        manager = BatteryManager()

        with mock.patch.object(manager, "is_on_battery", return_value=True):
            assert manager.should_skip_scan(skip_on_battery=True) is True

    def test_should_skip_scan_plugged_in(self):
        """Test should_skip_scan returns False when plugged in."""
        manager = BatteryManager()

        with mock.patch.object(manager, "is_on_battery", return_value=False):
            assert manager.should_skip_scan(skip_on_battery=True) is False

    def test_should_skip_scan_desktop(self):
        """Test should_skip_scan returns False for desktop systems."""
        manager = BatteryManager()

        # Desktop has no battery, so is_on_battery returns False
        with mock.patch.object(manager, "is_on_battery", return_value=False):
            assert manager.should_skip_scan(skip_on_battery=True) is False


class TestBatteryManagerProperties:
    """Tests for BatteryManager properties."""

    def test_has_battery_property(self):
        """Test has_battery property."""
        manager = BatteryManager()

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=True, percent=100.0),
        ):
            assert manager.has_battery is True

        with mock.patch.object(
            manager, "get_status", return_value=BatteryStatus(has_battery=False, is_plugged=True)
        ):
            assert manager.has_battery is False

    def test_is_plugged_property(self):
        """Test is_plugged property."""
        manager = BatteryManager()

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=True, percent=80.0),
        ):
            assert manager.is_plugged is True

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=False, percent=50.0),
        ):
            assert manager.is_plugged is False

    def test_battery_percent_property(self):
        """Test battery_percent property."""
        manager = BatteryManager()

        with mock.patch.object(
            manager,
            "get_status",
            return_value=BatteryStatus(has_battery=True, is_plugged=True, percent=75.5),
        ):
            assert manager.battery_percent == 75.5

        with mock.patch.object(
            manager, "get_status", return_value=BatteryStatus(has_battery=False, is_plugged=True)
        ):
            assert manager.battery_percent is None
