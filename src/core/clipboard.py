# ClamUI Clipboard Operations
"""
Clipboard operations for ClamUI.

This module provides functions for:
- Copying text to the system clipboard using GTK4 clipboard API
- Supporting both regular desktop and Flatpak environments
- Size-based tiered clipboard operations to prevent UI freezes
- Async clipboard operations for large content
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Size thresholds for clipboard operations
CLIPBOARD_SYNC_THRESHOLD = 1 * 1024 * 1024  # 1 MB - sync copy is safe
CLIPBOARD_ASYNC_THRESHOLD = 10 * 1024 * 1024  # 10 MB - async copy with feedback
# Above CLIPBOARD_ASYNC_THRESHOLD: suggest file export instead


class ClipboardResult(Enum):
    """Result status for clipboard operations."""

    SUCCESS = "success"
    ERROR = "error"
    TOO_LARGE = "too_large"


@dataclass
class ClipboardOperationResult:
    """Result of a clipboard operation with details."""

    status: ClipboardResult
    message: str
    size_bytes: int

    @property
    def is_success(self) -> bool:
        """Check if the operation was successful."""
        return self.status == ClipboardResult.SUCCESS

    @property
    def is_too_large(self) -> bool:
        """Check if the content was too large for clipboard."""
        return self.status == ClipboardResult.TOO_LARGE


def get_text_size(text: str) -> int:
    """
    Get the size of text in bytes (UTF-8 encoded).

    Args:
        text: The text to measure

    Returns:
        Size in bytes
    """
    if not text:
        return 0
    return len(text.encode("utf-8"))


def format_size(size_bytes: int) -> str:
    """
    Format a byte size as a human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Human-readable size string (e.g., "1.5 MB", "256 KB")
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _do_clipboard_set(text: str) -> bool:
    """
    Perform the actual clipboard set operation.

    This is the low-level operation that interacts with GTK.

    Args:
        text: The text to copy

    Returns:
        True if successful, False otherwise
    """
    try:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if display is None:
            return False

        clipboard = display.get_clipboard()
        if clipboard is None:
            return False

        clipboard.set(text)
        return True

    except Exception as e:
        logger.debug("Failed to copy to clipboard: %s", e)
        return False


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to the system clipboard using GTK 4 clipboard API.

    Uses the default display's clipboard to copy text content.
    This works in both regular desktop and Flatpak environments.

    Note: This is a synchronous operation. For large content (>1 MB),
    consider using copy_to_clipboard_with_result() or copy_to_clipboard_async()
    to avoid UI freezes.

    Args:
        text: The text content to copy to the clipboard

    Returns:
        True if the text was successfully copied, False otherwise

    Example:
        >>> copy_to_clipboard("Hello, World!")
        True

        >>> copy_to_clipboard("")
        False
    """
    if not text:
        return False

    return _do_clipboard_set(text)


def copy_to_clipboard_with_result(text: str) -> ClipboardOperationResult:
    """
    Copy text to clipboard with detailed result information.

    Performs size validation and returns structured result with
    status, message, and size information.

    Args:
        text: The text content to copy

    Returns:
        ClipboardOperationResult with status, message, and size_bytes

    Example:
        >>> result = copy_to_clipboard_with_result("Hello")
        >>> result.is_success
        True
        >>> result.size_bytes
        5
    """
    if not text:
        return ClipboardOperationResult(
            status=ClipboardResult.ERROR,
            message="No content to copy",
            size_bytes=0,
        )

    size_bytes = get_text_size(text)

    # Check if content is too large for clipboard
    if size_bytes > CLIPBOARD_ASYNC_THRESHOLD:
        return ClipboardOperationResult(
            status=ClipboardResult.TOO_LARGE,
            message=f"Content too large ({format_size(size_bytes)}). "
            "Consider exporting to a file instead.",
            size_bytes=size_bytes,
        )

    # Perform the copy
    success = _do_clipboard_set(text)

    if success:
        return ClipboardOperationResult(
            status=ClipboardResult.SUCCESS,
            message="Copied to clipboard",
            size_bytes=size_bytes,
        )
    else:
        return ClipboardOperationResult(
            status=ClipboardResult.ERROR,
            message="Failed to access clipboard",
            size_bytes=size_bytes,
        )


def copy_to_clipboard_async(
    text: str,
    callback: Callable[[ClipboardOperationResult], None],
) -> None:
    """
    Copy text to clipboard asynchronously with callback notification.

    The GTK/GDK clipboard must be accessed from the main-loop thread, so the
    copy is scheduled on the main loop via GLib.idle_add() rather than run on a
    background thread (which would be a GTK thread-safety violation). The
    callback is invoked on the main thread when the operation completes.

    This is recommended for content between 1-10 MB where the
    operation might take 10-100ms.

    Args:
        text: The text content to copy
        callback: Function called with ClipboardOperationResult when done.
                 Called on the main GTK thread.

    Example:
        def on_copy_done(result):
            if result.is_success:
                show_toast("Copied!")
            else:
                show_toast(result.message)

        copy_to_clipboard_async(large_text, on_copy_done)
    """
    if not text:
        # For empty text, call callback immediately (no need for thread)
        result = ClipboardOperationResult(
            status=ClipboardResult.ERROR,
            message="No content to copy",
            size_bytes=0,
        )
        callback(result)
        return

    size_bytes = get_text_size(text)

    # Check if content is too large
    if size_bytes > CLIPBOARD_ASYNC_THRESHOLD:
        result = ClipboardOperationResult(
            status=ClipboardResult.TOO_LARGE,
            message=f"Content too large ({format_size(size_bytes)}). "
            "Consider exporting to a file instead.",
            size_bytes=size_bytes,
        )
        callback(result)
        return

    def do_copy() -> bool:
        """Perform the clipboard write on the main loop and notify the caller."""
        success = _do_clipboard_set(text)

        if success:
            result = ClipboardOperationResult(
                status=ClipboardResult.SUCCESS,
                message="Copied to clipboard",
                size_bytes=size_bytes,
            )
        else:
            result = ClipboardOperationResult(
                status=ClipboardResult.ERROR,
                message="Failed to access clipboard",
                size_bytes=size_bytes,
            )

        callback(result)
        return False  # GLib.idle_add: run once, do not reschedule

    # GTK/GDK is not thread-safe: clipboard access must happen on the main-loop
    # thread. Schedule it there instead of spawning a worker thread.
    try:
        from gi.repository import GLib

        GLib.idle_add(do_copy)
    except Exception:
        # If GLib isn't available (e.g. tests), run inline on the current thread.
        do_copy()


def get_clipboard_size_tier(text: str) -> str:
    """
    Determine which size tier the text falls into.

    Useful for deciding which clipboard operation to use.

    Args:
        text: The text to check

    Returns:
        One of "sync", "async", or "too_large"

    Example:
        >>> tier = get_clipboard_size_tier(small_text)
        >>> if tier == "sync":
        ...     copy_to_clipboard(small_text)
    """
    if not text:
        return "sync"

    size_bytes = get_text_size(text)

    if size_bytes <= CLIPBOARD_SYNC_THRESHOLD:
        return "sync"
    elif size_bytes <= CLIPBOARD_ASYNC_THRESHOLD:
        return "async"
    else:
        return "too_large"
