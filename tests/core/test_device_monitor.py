# ClamUI Device Monitor Tests
"""Unit tests for the DeviceMonitor class."""

import sys
import time
from unittest.mock import MagicMock, patch

import pytest


def _clear_src_modules():
    """Clear all cached src.* modules to ensure clean imports."""
    modules_to_remove = [mod for mod in list(sys.modules.keys()) if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


# Module-level globals set by fresh import fixture
DeviceType = None
MountInfo = None
DeviceMonitor = None


@pytest.fixture(autouse=True)
def ensure_fresh_imports():
    """Ensure fresh imports for each test."""
    global DeviceType, MountInfo, DeviceMonitor

    # Save existing src.* modules so other test files' references stay valid
    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith("src.")}

    _clear_src_modules()

    from src.core.device_monitor import DeviceMonitor as _DeviceMonitor
    from src.core.device_monitor import DeviceType as _DeviceType
    from src.core.device_monitor import MountInfo as _MountInfo

    DeviceType = _DeviceType
    MountInfo = _MountInfo
    DeviceMonitor = _DeviceMonitor

    yield

    # Restore original modules so other test files' module-level imports
    # (e.g. test_keyring_manager.py) still reference the correct objects
    _clear_src_modules()
    sys.modules.update(saved_modules)


class TestDeviceType:
    """Test DeviceType enum."""

    def test_device_type_values(self):
        """Test that all expected device types exist."""
        assert DeviceType.REMOVABLE.value == "removable"
        assert DeviceType.EXTERNAL.value == "external"
        assert DeviceType.NETWORK.value == "network"
        assert DeviceType.INTERNAL.value == "internal"
        assert DeviceType.UNKNOWN.value == "unknown"


class TestMountInfo:
    """Test MountInfo dataclass."""

    def test_mount_info_creation(self):
        """Test creating a MountInfo with all fields."""
        info = MountInfo(
            mount_point="/media/usb",
            device_name="My USB",
            device_type=DeviceType.REMOVABLE,
            volume_uuid="1234-ABCD",
            size_bytes=1024 * 1024 * 1024,
        )
        assert info.mount_point == "/media/usb"
        assert info.device_name == "My USB"
        assert info.device_type == DeviceType.REMOVABLE
        assert info.volume_uuid == "1234-ABCD"
        assert info.size_bytes == 1024 * 1024 * 1024

    def test_mount_info_defaults(self):
        """Test MountInfo default field values."""
        info = MountInfo(
            mount_point="/mnt/ext",
            device_name="Drive",
            device_type=DeviceType.EXTERNAL,
        )
        assert info.volume_uuid == ""
        assert info.size_bytes == 0


class TestDeviceClassification:
    """Test device classification logic."""

    def test_classify_removable_drive(self):
        """Test that a removable drive is classified as REMOVABLE."""
        mock_mount = MagicMock()
        mock_volume = MagicMock()
        mock_drive = MagicMock()

        mock_mount.get_volume.return_value = mock_volume
        mock_volume.get_drive.return_value = mock_drive
        mock_drive.is_removable.return_value = True
        mock_drive.is_media_removable.return_value = False

        result = DeviceMonitor.classify_device(mock_mount)
        assert result == DeviceType.REMOVABLE

    def test_classify_media_removable(self):
        """Test that media-removable (SD card reader) is classified as REMOVABLE."""
        mock_mount = MagicMock()
        mock_volume = MagicMock()
        mock_drive = MagicMock()

        mock_mount.get_volume.return_value = mock_volume
        mock_volume.get_drive.return_value = mock_drive
        mock_drive.is_removable.return_value = False
        mock_drive.is_media_removable.return_value = True

        result = DeviceMonitor.classify_device(mock_mount)
        assert result == DeviceType.REMOVABLE

    def test_classify_external_ejectable(self):
        """Test that an ejectable non-removable drive is EXTERNAL."""
        mock_mount = MagicMock()
        mock_volume = MagicMock()
        mock_drive = MagicMock()

        mock_mount.get_volume.return_value = mock_volume
        mock_volume.get_drive.return_value = mock_drive
        mock_drive.is_removable.return_value = False
        mock_drive.is_media_removable.return_value = False
        mock_drive.can_eject.return_value = True

        result = DeviceMonitor.classify_device(mock_mount)
        assert result == DeviceType.EXTERNAL

    def test_classify_internal_drive(self):
        """Test that a non-removable, non-ejectable drive is INTERNAL."""
        mock_mount = MagicMock()
        mock_volume = MagicMock()
        mock_drive = MagicMock()

        mock_mount.get_volume.return_value = mock_volume
        mock_volume.get_drive.return_value = mock_drive
        mock_drive.is_removable.return_value = False
        mock_drive.is_media_removable.return_value = False
        mock_drive.can_eject.return_value = False

        result = DeviceMonitor.classify_device(mock_mount)
        assert result == DeviceType.INTERNAL

    def test_classify_no_volume_is_network(self):
        """Test that a mount without a volume is NETWORK."""
        mock_mount = MagicMock()
        mock_mount.get_volume.return_value = None

        result = DeviceMonitor.classify_device(mock_mount)
        assert result == DeviceType.NETWORK

    def test_classify_no_drive_is_network(self):
        """Test that a volume without a drive is NETWORK."""
        mock_mount = MagicMock()
        mock_volume = MagicMock()
        mock_mount.get_volume.return_value = mock_volume
        mock_volume.get_drive.return_value = None

        result = DeviceMonitor.classify_device(mock_mount)
        assert result == DeviceType.NETWORK


class TestShouldScanDevice:
    """Test the _should_scan_device filtering logic."""

    def _make_monitor(self, settings=None):
        """Create a DeviceMonitor with mocked dependencies."""
        default_settings = {
            "device_auto_scan_enabled": True,
            "device_auto_scan_types": ["removable", "external"],
            "device_auto_scan_max_size_gb": 32,
            "device_auto_scan_skip_on_battery": True,
        }
        if settings:
            default_settings.update(settings)

        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: default_settings.get(key, default)

        mock_scanner = MagicMock()

        monitor = DeviceMonitor(
            settings_manager=mock_settings,
            scanner=mock_scanner,
        )
        # Mock battery to say we're on AC power
        monitor._battery_manager = MagicMock()
        monitor._battery_manager.is_on_battery.return_value = False

        return monitor

    def test_should_scan_removable(self):
        """Test that a removable device passes all checks."""
        monitor = self._make_monitor()
        info = MountInfo(
            mount_point="/media/usb",
            device_name="USB",
            device_type=DeviceType.REMOVABLE,
            size_bytes=4 * 1024**3,
        )
        assert monitor._should_scan_device(info) is True

    def test_skip_when_disabled(self):
        """Test that devices are skipped when feature is disabled."""
        monitor = self._make_monitor({"device_auto_scan_enabled": False})
        info = MountInfo(
            mount_point="/media/usb",
            device_name="USB",
            device_type=DeviceType.REMOVABLE,
        )
        assert monitor._should_scan_device(info) is False

    def test_skip_wrong_type(self):
        """Test that devices of non-allowed types are skipped."""
        monitor = self._make_monitor()
        info = MountInfo(
            mount_point="/mnt/nfs",
            device_name="NFS Share",
            device_type=DeviceType.NETWORK,
        )
        assert monitor._should_scan_device(info) is False

    def test_skip_oversized(self):
        """Test that devices exceeding max size are skipped."""
        monitor = self._make_monitor({"device_auto_scan_max_size_gb": 8})
        info = MountInfo(
            mount_point="/media/usb",
            device_name="Big Drive",
            device_type=DeviceType.REMOVABLE,
            size_bytes=16 * 1024**3,  # 16 GB
        )
        assert monitor._should_scan_device(info) is False

    def test_allow_unknown_size(self):
        """Test that devices with unknown size are scanned (fail-open)."""
        monitor = self._make_monitor({"device_auto_scan_max_size_gb": 8})
        info = MountInfo(
            mount_point="/media/usb",
            device_name="Unknown Size",
            device_type=DeviceType.REMOVABLE,
            size_bytes=0,
        )
        assert monitor._should_scan_device(info) is True

    def test_skip_on_battery(self):
        """Test that devices are skipped when on battery."""
        monitor = self._make_monitor()
        monitor._battery_manager.is_on_battery.return_value = True
        info = MountInfo(
            mount_point="/media/usb",
            device_name="USB",
            device_type=DeviceType.REMOVABLE,
        )
        assert monitor._should_scan_device(info) is False

    def test_allow_on_battery_when_disabled(self):
        """Test that battery check is skipped when setting is off."""
        monitor = self._make_monitor({"device_auto_scan_skip_on_battery": False})
        monitor._battery_manager.is_on_battery.return_value = True
        info = MountInfo(
            mount_point="/media/usb",
            device_name="USB",
            device_type=DeviceType.REMOVABLE,
        )
        assert monitor._should_scan_device(info) is True

    def test_skip_recently_scanned(self):
        """Test that recently scanned devices are skipped (dedup)."""
        monitor = self._make_monitor()
        info = MountInfo(
            mount_point="/media/usb",
            device_name="USB",
            device_type=DeviceType.REMOVABLE,
        )
        # Simulate recent scan
        monitor._recently_scanned["/media/usb"] = time.monotonic()
        assert monitor._should_scan_device(info) is False

    def test_no_limit_when_max_size_zero(self):
        """Test that max_size_gb=0 means no limit."""
        monitor = self._make_monitor({"device_auto_scan_max_size_gb": 0})
        info = MountInfo(
            mount_point="/media/usb",
            device_name="Huge Drive",
            device_type=DeviceType.REMOVABLE,
            size_bytes=500 * 1024**3,  # 500 GB
        )
        assert monitor._should_scan_device(info) is True


class TestOnScanComplete:
    """Test scan completion handling."""

    def test_clean_scan_notifies(self):
        """Test that a clean scan triggers notification callback."""
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: {
            "device_auto_scan_enabled": True,
            "device_auto_scan_auto_quarantine": False,
        }.get(key, default)

        callback = MagicMock()
        monitor = DeviceMonitor(
            settings_manager=mock_settings,
            scanner=MagicMock(),
            notification_callback=callback,
        )
        monitor._battery_manager = MagicMock()

        info = MountInfo(
            mount_point="/media/usb",
            device_name="USB",
            device_type=DeviceType.REMOVABLE,
        )

        mock_result = MagicMock()
        mock_result.is_clean = True
        mock_result.has_threats = False
        mock_result.scanned_files = 42
        mock_result.infected_count = 0
        mock_result.status.value = "clean"
        mock_result.threat_details = []

        monitor._on_scan_complete(info, mock_result)

        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0] == "scan_complete"
        assert call_args[1]["is_clean"] is True
        assert call_args[1]["scanned_count"] == 42

    def test_infected_scan_with_auto_quarantine(self):
        """Test that threats are auto-quarantined when enabled."""
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: {
            "device_auto_scan_enabled": True,
            "device_auto_scan_auto_quarantine": True,
        }.get(key, default)

        mock_quarantine = MagicMock()
        mock_qresult = MagicMock()
        mock_qresult.is_success = True
        mock_quarantine.quarantine_file.return_value = mock_qresult

        callback = MagicMock()
        monitor = DeviceMonitor(
            settings_manager=mock_settings,
            scanner=MagicMock(),
            notification_callback=callback,
            quarantine_manager=mock_quarantine,
        )
        monitor._battery_manager = MagicMock()

        info = MountInfo(
            mount_point="/media/usb",
            device_name="USB",
            device_type=DeviceType.REMOVABLE,
        )

        mock_threat = MagicMock()
        mock_threat.file_path = "/media/usb/virus.exe"
        mock_threat.threat_name = "Win.Trojan.Test"

        mock_result = MagicMock()
        mock_result.is_clean = False
        mock_result.has_threats = True
        mock_result.scanned_files = 100
        mock_result.infected_count = 1
        mock_result.status.value = "infected"
        mock_result.threat_details = [mock_threat]

        monitor._on_scan_complete(info, mock_result)

        mock_quarantine.quarantine_file.assert_called_once_with(
            "/media/usb/virus.exe", "Win.Trojan.Test"
        )
        call_args = callback.call_args[0]
        assert call_args[1]["quarantined_count"] == 1


class TestStartStop:
    """Test monitor start/stop lifecycle."""

    @patch("src.core.device_monitor.Gio")
    def test_start_when_enabled(self, mock_gio):
        """Test that start connects signals when enabled."""
        mock_volume_monitor = MagicMock()
        mock_gio.VolumeMonitor.get.return_value = mock_volume_monitor

        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: {
            "device_auto_scan_enabled": True,
        }.get(key, default)

        monitor = DeviceMonitor(
            settings_manager=mock_settings,
            scanner=MagicMock(),
        )
        monitor._battery_manager = MagicMock()
        monitor.start()

        assert monitor.is_running is True
        assert mock_volume_monitor.connect.call_count == 2

    def test_start_when_disabled(self):
        """Test that start does nothing when feature is disabled."""
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: {
            "device_auto_scan_enabled": False,
        }.get(key, default)

        monitor = DeviceMonitor(
            settings_manager=mock_settings,
            scanner=MagicMock(),
        )
        monitor._battery_manager = MagicMock()
        monitor.start()

        assert monitor.is_running is False

    @patch("src.core.device_monitor.Gio")
    def test_stop_disconnects_signals(self, mock_gio):
        """Test that stop disconnects signals and cancels scans."""
        mock_volume_monitor = MagicMock()
        mock_volume_monitor.connect.side_effect = [1, 2]  # signal handler IDs
        mock_gio.VolumeMonitor.get.return_value = mock_volume_monitor

        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: {
            "device_auto_scan_enabled": True,
        }.get(key, default)

        monitor = DeviceMonitor(
            settings_manager=mock_settings,
            scanner=MagicMock(),
        )
        monitor._battery_manager = MagicMock()
        monitor.start()
        monitor.stop()

        assert monitor.is_running is False
        assert mock_volume_monitor.disconnect.call_count == 2

    @patch("src.core.device_monitor.Gio")
    def test_update_settings_starts_monitor(self, mock_gio):
        """Test that update_settings starts monitor when newly enabled."""
        mock_gio.VolumeMonitor.get.return_value = MagicMock()

        # Start with feature disabled
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: {
            "device_auto_scan_enabled": False,
        }.get(key, default)

        monitor = DeviceMonitor(
            settings_manager=mock_settings,
            scanner=MagicMock(),
        )
        monitor._battery_manager = MagicMock()
        monitor.start()  # Should not start (disabled)
        assert monitor.is_running is False

        # Now enable the feature
        mock_settings.get.side_effect = lambda key, default=None: {
            "device_auto_scan_enabled": True,
        }.get(key, default)

        monitor.update_settings()
        assert monitor.is_running is True


class TestRequeueSourceTracking:
    """BUG-009: Re-queued GLib timeout sources must be tracked.

    When MAX_CONCURRENT_SCANS is reached, _start_background_scan re-queues
    via GLib.timeout_add_seconds(10, ...). The returned source id must be
    stored in _scheduled_sources so stop() can cancel it. Otherwise, a
    pending re-queue can fire after monitor shutdown and instantiate a
    Scanner against a torn-down DeviceMonitor.
    """

    def _make_monitor(self):
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key, default=None: {
            "device_auto_scan_enabled": True,
            "device_auto_scan_delay_seconds": 0,
        }.get(key, default)
        monitor = DeviceMonitor(
            settings_manager=mock_settings,
            scanner=MagicMock(),
        )
        monitor._battery_manager = MagicMock()
        monitor._battery_manager.is_on_battery.return_value = False
        return monitor

    @patch("src.core.device_monitor.GLib")
    def test_requeue_source_tracked_in_scheduled_sources(self, mock_glib):
        """When concurrent limit hits, the re-queue source id is tracked."""
        mock_glib.SOURCE_REMOVE = False
        mock_glib.timeout_add_seconds.return_value = 12345  # fake source id

        monitor = self._make_monitor()

        info = MountInfo(
            mount_point="/media/usb1",
            device_name="USB1",
            device_type=DeviceType.REMOVABLE,
        )

        # Simulate two active scans (hits MAX_CONCURRENT_SCANS = 2)
        monitor._active_scans["/media/scanA"] = MagicMock()
        monitor._active_scans["/media/scanB"] = MagicMock()

        monitor._start_background_scan(info)

        # The re-queued source id must be in _scheduled_sources
        assert info.mount_point in monitor._scheduled_sources
        assert monitor._scheduled_sources[info.mount_point] == 12345
        # And no Scanner should have been started (still requeued)
        assert info.mount_point not in monitor._active_scans

    @patch("src.core.device_monitor.GLib")
    def test_stop_removes_pending_requeue_sources(self, mock_glib):
        """stop() must call GLib.source_remove for any tracked re-queue source."""
        mock_glib.SOURCE_REMOVE = False
        mock_glib.timeout_add_seconds.return_value = 67890

        monitor = self._make_monitor()
        monitor._running = True  # bypass start() VolumeMonitor side-effects

        info = MountInfo(
            mount_point="/media/usb2",
            device_name="USB2",
            device_type=DeviceType.REMOVABLE,
        )

        # Force the re-queue branch
        monitor._active_scans["/media/scanA"] = MagicMock()
        monitor._active_scans["/media/scanB"] = MagicMock()
        monitor._start_background_scan(info)
        # Drop the active sentinels so stop() doesn't try to cancel them too
        monitor._active_scans.clear()

        # Sanity: source is tracked
        assert monitor._scheduled_sources.get(info.mount_point) == 67890

        # Now stop the monitor
        monitor.stop()

        # GLib.source_remove must have been called with the re-queue id
        calls = [c.args[0] for c in mock_glib.source_remove.call_args_list]
        assert 67890 in calls
        # And the dict must be empty
        assert monitor._scheduled_sources == {}

    @patch("src.core.device_monitor.GLib")
    def test_requeue_lambda_clears_own_source_id_on_fire(self, mock_glib):
        """When the re-queue lambda fires, it removes its own id from the dict."""
        mock_glib.SOURCE_REMOVE = False
        # First call (the re-queue itself): return source id 111.
        # Second call (the inner _start_background_scan -> if the recursion
        #  itself also hits the requeue branch): return 222.
        mock_glib.timeout_add_seconds.side_effect = [111, 222]

        monitor = self._make_monitor()

        info = MountInfo(
            mount_point="/media/usb3",
            device_name="USB3",
            device_type=DeviceType.REMOVABLE,
        )

        monitor._active_scans["/media/A"] = MagicMock()
        monitor._active_scans["/media/B"] = MagicMock()
        monitor._start_background_scan(info)

        assert monitor._scheduled_sources[info.mount_point] == 111

        # Capture the lambda passed to timeout_add_seconds and invoke it.
        # Simulate the limit being lifted before fire so the recursive
        # _start_background_scan would proceed normally — but we also drop
        # the active scans to ensure that path is taken.
        cb = mock_glib.timeout_add_seconds.call_args_list[0].args[1]
        monitor._active_scans.clear()
        with patch.object(monitor, "_start_background_scan") as mock_inner:
            cb()
            mock_inner.assert_called_once_with(info)

        # After firing, the source id for this mount_point must be gone
        assert info.mount_point not in monitor._scheduled_sources
