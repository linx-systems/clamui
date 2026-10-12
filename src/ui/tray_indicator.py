# ClamUI Tray Indicator Module
"""
Tray indicator compatibility wrapper for ClamUI.

The tray implementation moved to `tray_manager.py` + `tray_service.py`
(subprocess + StatusNotifierItem over D-Bus). This module keeps the
historical `TrayIndicator` API used by app wiring and delegates to
`TrayManager`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .tray_manager import TrayManager

logger = logging.getLogger(__name__)


class TrayIndicator:
    """
    App-facing tray indicator wrapper around TrayManager.

    This class provides the legacy methods expected by `app.py` and
    `tray_integration.py` while using the subprocess-based tray backend.
    """

    def __init__(self, app: Any):
        """
        Initialize tray integration and start the tray subprocess.

        Args:
            app: ClamUI application instance exposing tray callback handlers.
        """
        self._app = app
        self._manager: TrayManager | None = TrayManager()

        self._manager.set_action_callbacks(
            on_quick_scan=self._app._on_tray_quick_scan,
            on_full_scan=self._app._on_tray_full_scan,
            on_update=self._app._on_tray_update,
            on_quit=self._app._on_tray_quit,
        )
        self._manager.set_window_toggle_callback(on_toggle=self._app._on_tray_window_toggle)
        self._manager.set_profile_select_callback(on_select=self._app._on_tray_profile_select)
        self._manager.set_availability_callback(self._app._on_tray_availability_changed)

        if self._manager.start():
            logger.info("Tray indicator subprocess started")
        else:
            logger.warning("Failed to start tray indicator subprocess")
            self._manager = None
            raise RuntimeError("Tray subprocess failed to start")

    @property
    def is_available(self) -> bool:
        """Whether a desktop tray host has registered this indicator."""
        return self._manager is not None and self._manager.is_available

    @staticmethod
    def _normalize_profile_item(profile: object) -> dict[str, object] | None:
        """
        Normalize a profile entry to the tray-service payload format.

        Supported input formats:
        - `{\"id\": str, \"name\": str, \"is_default\": bool}` dict
        - `(id, name)` or `(id, name, description)` sequence
        """
        if isinstance(profile, dict):
            profile_id = profile.get("id")
            profile_name = profile.get("name")
            if not profile_id or not profile_name:
                return None
            return {
                "id": str(profile_id),
                "name": str(profile_name),
                "is_default": bool(profile.get("is_default", False)),
            }

        if isinstance(profile, Sequence) and not isinstance(profile, str):
            if len(profile) < 2:
                return None
            return {
                "id": str(profile[0]),
                "name": str(profile[1]),
                "is_default": False,
            }

        return None

    def _normalize_profiles(self, profiles: list[object]) -> list[dict[str, object]]:
        """Normalize mixed profile input into tray-service profile dicts."""
        normalized: list[dict[str, object]] = []
        for profile in profiles:
            normalized_item = self._normalize_profile_item(profile)
            if normalized_item is None:
                logger.debug("Skipping invalid tray profile entry: %r", profile)
                continue
            normalized.append(normalized_item)
        return normalized

    def update_status(self, status: str) -> None:
        """Update tray icon/status state."""
        if self._manager is not None:
            self._manager.update_status(status)

    def update_scan_progress(self, percentage: int) -> None:
        """Update scan progress shown in tray."""
        if self._manager is not None:
            self._manager.update_scan_progress(percentage)

    def update_window_menu_label(self, visible: bool = True) -> None:
        """Update the Show/Hide Window tray menu label."""
        if self._manager is not None:
            self._manager.update_window_menu_label(visible=visible)

    def set_profiles(self, profiles: list[object], current_profile_id: str | None = None) -> None:
        """
        Legacy profile API used by app wiring.

        Accepts tuple-list profile data and normalizes it for TrayManager.
        """
        self.update_profiles(profiles, current_profile_id)

    def update_profiles(
        self, profiles: list[object], current_profile_id: str | None = None
    ) -> None:
        """Update tray profile menu entries."""
        if self._manager is None:
            return
        normalized = self._normalize_profiles(profiles)
        self._manager.update_profiles(normalized, current_profile_id)

    def cleanup(self) -> None:
        """Stop the tray subprocess and release resources."""
        if self._manager is not None:
            self._manager.cleanup()
            self._manager = None


def is_available() -> bool:
    """
    Check if the tray indicator functionality is available.

    Returns:
        True if subprocess tray integration can be attempted.
    """
    return True


def get_unavailable_reason() -> str | None:
    """
    Get the reason why tray indicator is unavailable.

    Returns:
        None because tray startup validity is determined at runtime.
    """
    return None
