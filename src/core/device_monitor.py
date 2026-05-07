# ClamUI Device Monitor Module
"""
Device monitor module for ClamUI providing automatic scanning of newly
connected storage devices. Uses Gio.VolumeMonitor to detect mount events
and triggers background ClamAV scans with configurable options.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from gi.repository import Gio, GLib

from .battery_manager import BatteryManager
from .i18n import _
from .scanner import Scanner
from .scanner_types import ScanResult
from .settings_manager import SettingsManager

logger = logging.getLogger(__name__)

# Maximum concurrent device scans to prevent resource exhaustion
MAX_CONCURRENT_SCANS = 2

# Time (seconds) to suppress duplicate scans for the same mount point
RECENTLY_SCANNED_TTL = 60


class DeviceType(Enum):
    """Classification of mounted storage devices."""

    REMOVABLE = "removable"  # USB drives, SD cards
    EXTERNAL = "external"  # External HDDs/SSDs (ejectable but not removable media)
    NETWORK = "network"  # NFS, SMB, SSHFS mounts
    INTERNAL = "internal"  # Internal drives
    UNKNOWN = "unknown"


@dataclass
class MountInfo:
    """Information about a mounted device."""

    mount_point: str
    device_name: str
    device_type: DeviceType
    volume_uuid: str = ""
    size_bytes: int = 0


class DeviceMonitor:
    """
    Monitor for newly connected storage devices.

    Watches for mount events via Gio.VolumeMonitor and triggers
    background ClamAV scans based on user-configured filters.
    """

    def __init__(
        self,
        settings_manager: SettingsManager,
        scanner: Scanner,
        notification_callback: Callable | None = None,
        quarantine_manager=None,
    ):
        """
        Initialize the DeviceMonitor.

        Args:
            settings_manager: For reading device scan settings.
            scanner: Scanner instance for running background scans.
            notification_callback: Called with (event_type, info_dict) for notifications.
            quarantine_manager: Optional QuarantineManager for auto-quarantine.
        """
        self._settings_manager = settings_manager
        self._scanner = scanner
        self._notification_callback = notification_callback
        self._quarantine_manager = quarantine_manager
        self._battery_manager = BatteryManager()

        # Must hold a strong reference to prevent GC from disconnecting signals
        self._volume_monitor: Gio.VolumeMonitor | None = None

        # Signal handler IDs for cleanup
        self._mount_added_id: int = 0
        self._mount_removed_id: int = 0

        # Track active and queued scans
        self._active_scans: dict[str, Scanner] = {}
        self._scan_queue: dict[str, MountInfo] = {}
        self._recently_scanned: dict[str, float] = {}  # mount_point -> timestamp
        self._scheduled_sources: dict[str, int] = {}  # mount_point -> GLib source id
        self._lock = threading.Lock()

        self._running = False

    def start(self) -> None:
        """Connect to mount-added and mount-removed signals."""
        if self._running:
            return

        if not self._settings_manager.get("device_auto_scan_enabled", False):
            logger.debug("Device auto-scan is disabled")
            return

        self._volume_monitor = Gio.VolumeMonitor.get()
        self._mount_added_id = self._volume_monitor.connect("mount-added", self._on_mount_added)
        self._mount_removed_id = self._volume_monitor.connect(
            "mount-removed", self._on_mount_removed
        )
        self._running = True
        logger.info("Device monitor started")

    def stop(self) -> None:
        """Disconnect signals and cancel active scans."""
        if not self._running:
            return

        # Disconnect signals
        if self._volume_monitor is not None:
            if self._mount_added_id:
                self._volume_monitor.disconnect(self._mount_added_id)
                self._mount_added_id = 0
            if self._mount_removed_id:
                self._volume_monitor.disconnect(self._mount_removed_id)
                self._mount_removed_id = 0

        # Cancel scheduled scans
        with self._lock:
            for source_id in self._scheduled_sources.values():
                GLib.source_remove(source_id)
            self._scheduled_sources.clear()

            # Cancel active scans
            for mount_point, scanner in list(self._active_scans.items()):
                logger.info("Cancelling device scan for %s", mount_point)
                scanner.cancel()
            self._active_scans.clear()
            self._scan_queue.clear()

        self._volume_monitor = None
        self._running = False
        logger.info("Device monitor stopped")

    def update_settings(self) -> None:
        """Re-read settings. Start or stop monitor as needed."""
        enabled = self._settings_manager.get("device_auto_scan_enabled", False)
        if enabled and not self._running:
            self.start()
        elif not enabled and self._running:
            self.stop()

    @staticmethod
    def classify_device(mount: Gio.Mount) -> DeviceType:
        """
        Classify a mount by its underlying drive characteristics.

        Uses the Gio.Mount -> Volume -> Drive chain:
        - Drive.is_removable() / is_media_removable() -> REMOVABLE
        - Drive.can_eject() but not removable -> EXTERNAL
        - No Drive (e.g. NFS/SMB) -> NETWORK
        - Otherwise -> INTERNAL
        """
        volume = mount.get_volume()
        if volume is None:
            # No volume backing means network or virtual mount
            return DeviceType.NETWORK

        drive = volume.get_drive()
        if drive is None:
            # Volume without a drive (e.g., GVFS network mount)
            return DeviceType.NETWORK

        if drive.is_removable() or drive.is_media_removable():
            return DeviceType.REMOVABLE

        if drive.can_eject():
            return DeviceType.EXTERNAL

        return DeviceType.INTERNAL

    @staticmethod
    def get_mount_info(mount: Gio.Mount) -> MountInfo:
        """
        Extract information from a Gio.Mount.

        Args:
            mount: The Gio.Mount to inspect.

        Returns:
            MountInfo with device details.
        """
        device_type = DeviceMonitor.classify_device(mount)
        device_name = mount.get_name() or _("Unknown Device")

        # Get mount point path from the root GFile
        root = mount.get_root()
        mount_point = root.get_path() or "" if root else ""

        # Try to get volume UUID
        volume_uuid = ""
        volume = mount.get_volume()
        if volume is not None:
            uuid = volume.get_uuid()
            if uuid:
                volume_uuid = uuid

        # Try to get filesystem size
        size_bytes = 0
        if root is not None:
            try:
                info = root.query_filesystem_info(Gio.FILE_ATTRIBUTE_FILESYSTEM_SIZE, None)
                if info:
                    size_bytes = info.get_attribute_uint64(Gio.FILE_ATTRIBUTE_FILESYSTEM_SIZE)
            except Exception as e:
                logger.debug("Could not query filesystem size for '%s': %s", mount_point, e)

        return MountInfo(
            mount_point=mount_point,
            device_name=device_name,
            device_type=device_type,
            volume_uuid=volume_uuid,
            size_bytes=size_bytes,
        )

    def _should_scan_device(self, info: MountInfo) -> bool:
        """
        Decide whether to scan this device based on settings and state.

        Checks: feature enabled, device type filter, max size,
        battery status, and recently-scanned dedup.
        """
        if not self._settings_manager.get("device_auto_scan_enabled", False):
            return False

        # Check device type against user-selected types
        allowed_types = self._settings_manager.get(
            "device_auto_scan_types", ["removable", "external"]
        )
        if info.device_type.value not in allowed_types:
            logger.debug(
                "Skipping %s: type %s not in allowed %s",
                info.device_name,
                info.device_type.value,
                allowed_types,
            )
            return False

        # Check max device size (0 = no limit, fail open if size unknown)
        max_size_gb = self._settings_manager.get("device_auto_scan_max_size_gb", 32)
        if max_size_gb > 0 and info.size_bytes > 0:
            max_size_bytes = max_size_gb * 1024 * 1024 * 1024
            if info.size_bytes > max_size_bytes:
                logger.info(
                    "Skipping %s: size %.1f GB exceeds limit %d GB",
                    info.device_name,
                    info.size_bytes / (1024**3),
                    max_size_gb,
                )
                return False

        # Check battery
        skip_on_battery = self._settings_manager.get("device_auto_scan_skip_on_battery", True)
        if skip_on_battery and self._battery_manager.is_on_battery():
            logger.info("Skipping %s: running on battery", info.device_name)
            return False

        # Dedup: skip if recently scanned
        with self._lock:
            self._cleanup_recently_scanned()
            if info.mount_point in self._recently_scanned:
                logger.debug("Skipping %s: recently scanned", info.device_name)
                return False

        return True

    def _cleanup_recently_scanned(self) -> None:
        """Remove expired entries from the recently-scanned dict. Caller holds lock."""
        now = time.monotonic()
        expired = [
            mp for mp, ts in self._recently_scanned.items() if now - ts > RECENTLY_SCANNED_TTL
        ]
        for mp in expired:
            del self._recently_scanned[mp]

    def _on_mount_added(self, monitor: Gio.VolumeMonitor, mount: Gio.Mount) -> None:
        """Handle mount-added signal."""
        info = self.get_mount_info(mount)
        logger.info(
            "Device mounted: %s at %s (type=%s)",
            info.device_name,
            info.mount_point,
            info.device_type.value,
        )

        if not info.mount_point:
            logger.warning("Mount has no path, skipping: %s", info.device_name)
            return

        if not self._should_scan_device(info):
            return

        self._schedule_scan(info)

    def _on_mount_removed(self, monitor: Gio.VolumeMonitor, mount: Gio.Mount) -> None:
        """Cancel active scan if the device was removed mid-scan."""
        root = mount.get_root()
        mount_point = root.get_path() if root else None
        if not mount_point:
            return

        with self._lock:
            # Cancel scheduled (not yet started) scan
            if mount_point in self._scheduled_sources:
                GLib.source_remove(self._scheduled_sources.pop(mount_point))
                self._scan_queue.pop(mount_point, None)
                logger.info("Cancelled scheduled scan for removed device: %s", mount_point)

            # Cancel active scan
            if mount_point in self._active_scans:
                scanner = self._active_scans.pop(mount_point)
                scanner.cancel()
                logger.info("Cancelled active scan for removed device: %s", mount_point)

    def _schedule_scan(self, info: MountInfo) -> None:
        """Schedule a scan after the configured delay."""
        delay = self._settings_manager.get("device_auto_scan_delay_seconds", 3)

        with self._lock:
            # Don't schedule if already queued or active
            if info.mount_point in self._scan_queue:
                return
            if info.mount_point in self._active_scans:
                return

            self._scan_queue[info.mount_point] = info

        logger.info(
            "Scheduling scan for %s in %d seconds",
            info.device_name,
            delay,
        )

        def on_delay_expired() -> bool:
            with self._lock:
                self._scheduled_sources.pop(info.mount_point, None)
            self._start_background_scan(info)
            return GLib.SOURCE_REMOVE

        source_id = GLib.timeout_add_seconds(delay, on_delay_expired)
        with self._lock:
            self._scheduled_sources[info.mount_point] = source_id

    def _start_background_scan(self, info: MountInfo) -> None:
        """Create a Scanner instance and start a background scan."""
        with self._lock:
            # Enforce concurrent scan limit
            if len(self._active_scans) >= MAX_CONCURRENT_SCANS:
                logger.info(
                    "Max concurrent scans reached, requeueing %s",
                    info.device_name,
                )
                # Re-schedule after a short delay. Track the source id in
                # _scheduled_sources so stop() / _on_mount_removed can cancel
                # it; otherwise a pending re-queue can fire after monitor
                # shutdown and instantiate a Scanner against a torn-down
                # DeviceMonitor (BUG-009).
                self._scan_queue[info.mount_point] = info
                mount_point = info.mount_point

                def on_requeue_expired() -> bool:
                    with self._lock:
                        self._scheduled_sources.pop(mount_point, None)
                    self._start_background_scan(info)
                    return GLib.SOURCE_REMOVE

                requeue_source_id = GLib.timeout_add_seconds(10, on_requeue_expired)
                self._scheduled_sources[mount_point] = requeue_source_id
                return

            self._scan_queue.pop(info.mount_point, None)

            # Create a dedicated scanner for this device scan
            scanner = Scanner(settings_manager=self._settings_manager)
            self._active_scans[info.mount_point] = scanner

        logger.info("Starting device scan: %s at %s", info.device_name, info.mount_point)

        # Notify scan started
        if self._notification_callback:
            self._notification_callback(
                "scan_started",
                {
                    "device_name": info.device_name,
                    "mount_point": info.mount_point,
                },
            )

        def on_scan_complete(result: ScanResult) -> None:
            self._on_scan_complete(info, result)

        scanner.scan_async(info.mount_point, on_scan_complete)

    def _on_scan_complete(self, info: MountInfo, result: ScanResult) -> None:
        """Handle scan completion: auto-quarantine if enabled, send notification."""
        with self._lock:
            self._active_scans.pop(info.mount_point, None)
            self._recently_scanned[info.mount_point] = time.monotonic()

        quarantined_count = 0

        # Auto-quarantine if enabled and threats found
        if (
            result.has_threats
            and self._quarantine_manager is not None
            and self._settings_manager.get("device_auto_scan_auto_quarantine", False)
        ):
            for threat in result.threat_details:
                try:
                    qresult = self._quarantine_manager.quarantine_file(
                        threat.file_path, threat.threat_name
                    )
                    if qresult.is_success:
                        quarantined_count += 1
                except Exception as e:
                    logger.warning("Failed to quarantine %s: %s", threat.file_path, e)

        logger.info(
            "Device scan complete for %s: status=%s, scanned=%d, infected=%d, quarantined=%d",
            info.device_name,
            result.status.value,
            result.scanned_files,
            result.infected_count,
            quarantined_count,
        )

        # Notify scan complete
        if self._notification_callback:
            self._notification_callback(
                "scan_complete",
                {
                    "device_name": info.device_name,
                    "mount_point": info.mount_point,
                    "is_clean": result.is_clean,
                    "infected_count": result.infected_count,
                    "scanned_count": result.scanned_files,
                    "quarantined_count": quarantined_count,
                },
            )

        # Check if queued scans can now start
        with self._lock:
            queued = list(self._scan_queue.values())
        for queued_info in queued:
            self._start_background_scan(queued_info)
            break  # Start one at a time

    @property
    def is_running(self) -> bool:
        """Whether the monitor is actively watching for mount events."""
        return self._running

    @property
    def active_scan_count(self) -> int:
        """Number of currently running device scans."""
        with self._lock:
            return len(self._active_scans)
