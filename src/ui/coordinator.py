# View Coordinator
"""
View coordination for ClamUI.

This module manages view lifecycle and navigation, extracting view
management logic from ClamUIApp to reduce complexity.

Key Responsibilities:
    - Lazy view creation and caching
    - View switching and navigation
    - Current view tracking
    - View setup callbacks

Design Pattern:
    ViewCoordinator uses the Coordinator pattern to centralize view
    management. Views are created lazily only when first accessed,
    reducing startup time and memory usage.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

if TYPE_CHECKING:
    from ..core.app_context import AppContext

logger = logging.getLogger(__name__)


class ContentViewHost(Protocol):
    """Protocol for windows that can host content views."""

    def set_content_view(self, view: Gtk.Widget) -> None:
        pass

    def set_active_view(self, view_name: str) -> None:
        pass


class ViewCoordinator:
    """
    Coordinates view lifecycle and navigation.

    Manages lazy loading of views, caches created instances, and
    handles view switching through callbacks.

    Attributes:
        current_view: Name of the currently active view.
    """

    def __init__(self, app_context: "AppContext"):
        """
        Initialize the view coordinator.

        Args:
            app_context: Application context with shared services.
        """
        self._context = app_context

        self._scan_view = None
        self._update_view = None
        self._logs_view = None
        self._components_view = None
        self._statistics_view = None
        self._quarantine_view = None

        self._current_view: str | None = None

        self._statistics_quick_scan_callback: Callable | None = None

    @property
    def current_view(self) -> str | None:
        """Get the name of the currently active view."""
        return self._current_view

    @property
    def scan_view(self):
        """Get the scan view instance, creating it lazily if needed."""
        from .scan_view import ScanView

        if self._scan_view is None:
            self._scan_view = ScanView(
                settings_manager=self._context.settings_manager,
                quarantine_manager=self._context.quarantine_manager,
            )
        return self._scan_view

    @property
    def update_view(self):
        """Get the update view instance, creating it lazily if needed."""
        from .update_view import UpdateView

        if self._update_view is None:
            self._update_view = UpdateView(settings_manager=self._context.settings_manager)
        return self._update_view

    @property
    def logs_view(self):
        """Get the logs view instance, creating it lazily if needed."""
        from .logs_view import LogsView

        if self._logs_view is None:
            self._logs_view = LogsView()
        return self._logs_view

    @property
    def components_view(self):
        """Get the components view instance, creating it lazily if needed."""
        from .components_view import ComponentsView

        if self._components_view is None:
            self._components_view = ComponentsView()
        return self._components_view

    @property
    def statistics_view(self):
        """Get the statistics view instance, creating it lazily if needed."""
        from .statistics_view import StatisticsView

        if self._statistics_view is None:
            self._statistics_view = StatisticsView()
            if self._statistics_quick_scan_callback:
                self._statistics_view.set_quick_scan_callback(self._statistics_quick_scan_callback)
        return self._statistics_view

    @property
    def quarantine_view(self):
        """Get the quarantine view instance, creating it lazily if needed."""
        from .quarantine_view import QuarantineView

        if self._quarantine_view is None:
            self._quarantine_view = QuarantineView(
                quarantine_manager=self._context.quarantine_manager,
            )
        return self._quarantine_view

    def set_statistics_quick_scan_callback(self, callback: Callable) -> None:
        """
        Set the callback for quick scan from statistics view.

        Args:
            callback: Function to call when quick scan is requested.
        """
        self._statistics_quick_scan_callback = callback
        if self._statistics_view is not None:
            self._statistics_view.set_quick_scan_callback(callback)

    def switch_to(
        self,
        view_name: str,
        window: ContentViewHost,
        force: bool = False,
    ) -> bool:
        """
        Switch to a named view.

        Args:
            view_name: Name of the view to switch to.
            window: Main window to update.
            force: Switch even if already on the view.

        Returns:
            True if view was switched, False if already on that view.
        """
        if self._current_view == view_name and not force:
            return False

        view = self._get_view(view_name)
        if view is None:
            logger.warning("Unknown view: %s", view_name)
            return False

        window.set_content_view(view)
        window.set_active_view(view_name)
        self._current_view = view_name
        return True

    def _get_view(self, name: str):
        """Get a view by name."""
        views = {
            "scan": self.scan_view,
            "update": self.update_view,
            "logs": self.logs_view,
            "components": self.components_view,
            "statistics": self.statistics_view,
            "quarantine": self.quarantine_view,
        }
        return views.get(name)

    def activate_scan_view(self, window: ContentViewHost) -> None:
        """Set scan view as active and update window."""
        window.set_content_view(self.scan_view)
        window.set_active_view("scan")
        self._current_view = "scan"

    def cleanup(self) -> None:
        """Clear all view references for garbage collection."""
        self._scan_view = None
        self._update_view = None
        self._logs_view = None
        self._components_view = None
        self._statistics_view = None
        self._quarantine_view = None
        self._current_view = None
