# ClamUI Battery Manager Module
"""
Battery manager module for ClamUI providing system battery status detection.
Uses psutil for cross-platform battery status checking to support
battery-aware scheduled scanning (skip scans when on battery power).
"""

from dataclasses import dataclass

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


@dataclass
class BatteryStatus:
    """
    Battery status information.

    Attributes:
        has_battery: Whether the system has a battery (False for desktops)
        is_plugged: Whether the system is plugged in (AC power)
        percent: Battery charge percentage (0-100), None if no battery
        time_remaining: Estimated seconds until battery empty/full, None if unknown
    """

    has_battery: bool
    is_plugged: bool
    percent: float | None = None
    time_remaining: int | None = None


class BatteryManager:
    """
    Manager for system battery status detection.

    Provides methods for checking battery status to enable
    battery-aware scheduled scanning. Gracefully handles
    desktop systems without batteries.
    """

    def __init__(self):
        """
        Initialize the BatteryManager.

        No configuration required - psutil handles detection automatically.
        """
        self._psutil_available = PSUTIL_AVAILABLE

    def get_status(self) -> BatteryStatus:
        """
        Get current battery status.

        Returns:
            BatteryStatus with current power state information.
            For desktops without batteries, returns has_battery=False
            and is_plugged=True (always on AC power).
        """
        if not self._psutil_available:
            # psutil not installed - assume plugged in
            return BatteryStatus(
                has_battery=False, is_plugged=True, percent=None, time_remaining=None
            )

        try:
            battery = psutil.sensors_battery()
        except Exception:
            # Handle any psutil errors gracefully
            return BatteryStatus(
                has_battery=False, is_plugged=True, percent=None, time_remaining=None
            )

        if battery is None:
            # No battery detected (desktop system)
            return BatteryStatus(
                has_battery=False, is_plugged=True, percent=None, time_remaining=None
            )

        # Battery detected (laptop or similar). psutil reports power_plugged as
        # None when AC status is undetermined; treat that as plugged-in so we do
        # not wrongly skip scheduled scans.
        is_plugged = bool(battery.power_plugged) if battery.power_plugged is not None else True
        return BatteryStatus(
            has_battery=True,
            is_plugged=is_plugged,
            percent=battery.percent,
            time_remaining=battery.secsleft if battery.secsleft > 0 else None,
        )

    def is_on_battery(self) -> bool:
        """
        Check if system is running on battery power.

        Returns:
            True if running on battery (not plugged in),
            False if plugged in or no battery present.
        """
        status = self.get_status()
        return status.has_battery and not status.is_plugged

    def should_skip_scan(self, skip_on_battery: bool = True) -> bool:
        """
        Determine if a scheduled scan should be skipped based on power status.

        Args:
            skip_on_battery: Whether to skip scans when on battery power.
                             If False, always returns False (never skip).

        Returns:
            True if scan should be skipped (on battery and skip_on_battery=True),
            False otherwise.
        """
        if not skip_on_battery:
            return False
        return self.is_on_battery()

    @property
    def has_battery(self) -> bool:
        """
        Check if system has a battery.

        Returns:
            True if system has a battery (laptop), False otherwise (desktop).
        """
        return self.get_status().has_battery

    @property
    def is_plugged(self) -> bool:
        """
        Check if system is plugged in (on AC power).

        Returns:
            True if plugged in or no battery, False if on battery power.
        """
        return self.get_status().is_plugged

    @property
    def battery_percent(self) -> float | None:
        """
        Get current battery charge percentage.

        Returns:
            Battery percentage (0-100), or None if no battery.
        """
        return self.get_status().percent

    @property
    def psutil_available(self) -> bool:
        """
        Check if psutil is available.

        Returns:
            True if psutil is installed and can be used.
        """
        return self._psutil_available
