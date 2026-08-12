# ClamUI Test Configuration
"""
Pytest configuration and shared fixtures for ClamUI tests.

This file provides:
- Centralized GTK/GI mocking for all UI tests
- Common test utilities and fixtures
- Module cache management for test isolation
- Locale forcing (LANGUAGE=C) to ensure English gettext output
"""

import contextlib
import gettext
import os
import sys
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Force English locale for tests (must run before any src.* imports)
# =============================================================================
# On non-English systems, gettext returns translated strings which break test
# assertions that check for English text. Setting LANGUAGE=C disables
# translation lookup, causing gettext to return the original source strings.

os.environ["LANGUAGE"] = "C"
os.environ["LC_ALL"] = "C"
# Reinitialize gettext so the C locale takes effect for any already-imported
# modules (e.g. i18n.py initializes on import).
gettext.textdomain("clamui")

# =============================================================================
# GTK Mock Base Classes
# =============================================================================
# These classes allow GTK widgets to work with object.__new__() for Python 3.13+
# compatibility. They must be real classes, not MagicMock, for inheritance to work.


class MockGtkWidget:
    """
    Base mock class for all GTK widgets.

    Supports object.__new__() instantiation and returns MagicMock for
    any undefined attribute access, enabling method chaining.

    Method calls are tracked via _mocks dict for test assertions.
    """

    def __init__(self, *args, **kwargs):
        # Store mock methods in __dict__ to avoid __getattr__ recursion
        object.__setattr__(self, "_mocks", {})

    def __getattr__(self, name):
        """Return a persistent MagicMock for method tracking."""
        # Allow single underscore attributes (private instance vars)
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            mocks = object.__getattribute__(self, "_mocks")
        except AttributeError:
            # Initialize _mocks if it doesn't exist (happens with object.__new__)
            object.__setattr__(self, "_mocks", {})
            mocks = object.__getattribute__(self, "_mocks")
        if name not in mocks:
            mocks[name] = MagicMock()
        return mocks[name]


class MockGtkBox(MockGtkWidget):
    """Mock for Gtk.Box with Orientation constants."""

    class Orientation:
        VERTICAL = 0
        HORIZONTAL = 1

    @classmethod
    def do_unmap(cls, instance):
        """Mock for Gtk.Box.do_unmap class method."""
        pass

    @classmethod
    def do_map(cls, instance):
        """Mock for Gtk.Box.do_map class method."""
        pass


class MockAdwPreferencesWindow(MockGtkWidget):
    """Mock for Adw.PreferencesWindow with tracked method calls."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Store mock methods in __dict__ to avoid __getattr__ recursion
        object.__setattr__(self, "_mocks", {})

    def __getattr__(self, name):
        """Return a persistent MagicMock for method tracking."""
        # Allow single underscore attributes (private instance vars)
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            mocks = object.__getattribute__(self, "_mocks")
        except AttributeError:
            # Initialize _mocks if it doesn't exist (happens with object.__new__)
            object.__setattr__(self, "_mocks", {})
            mocks = object.__getattribute__(self, "_mocks")
        if name not in mocks:
            mocks[name] = MagicMock()
        return mocks[name]


class MockAdwDialog(MockGtkWidget):
    """Mock for Adw.Dialog (legacy - now using Adw.Window for libadwaita 1.0+ compat)."""

    pass


class MockAdwWindow(MockGtkWidget):
    """Mock for Adw.Window (used for dialogs in libadwaita 1.0+)."""

    pass


class MockAdwApplicationWindow(MockGtkWidget):
    """Mock for Adw.ApplicationWindow."""

    pass


class MockAdwExpanderRow(MockGtkWidget):
    """Mock for Adw.ExpanderRow (used as collapsible section containers)."""

    pass


class MockGtkListBox(MockGtkWidget):
    """Mock for Gtk.ListBox."""

    pass


class MockGtkListBoxRow(MockGtkWidget):
    """Mock for Gtk.ListBoxRow."""

    pass


# =============================================================================
# Flatpak Cache Reset
# =============================================================================


@pytest.fixture(autouse=True)
def reset_flatpak_cache():
    """
    Reset the Flatpak detection cache before each test.

    The flatpak.py module caches the is_flatpak() result in _flatpak_detected
    for performance. In test environments where /.flatpak-info exists (e.g.,
    Flatpak development environments), this cache can cause tests to fail
    because mocking is_flatpak() doesn't work when the cache is already set.

    This fixture:
    1. Resets the cache variable to None
    2. Patches os.path.exists to return False for /.flatpak-info
       (handles cases where modules are reimported during tests)

    The original value is restored after the test to avoid affecting other tests.
    """
    import os
    import sys as _sys

    # Always use the CURRENT module from sys.modules, not a cached import.
    # Test files with _clear_src_modules() (test_scanner, test_scheduler,
    # test_device_monitor) replace sys.modules['src.core.flatpak'] with a
    # fresh module. A plain `import` caches the first module object, which
    # becomes stale after the swap - resetting _flatpak_detected on the
    # stale module leaves the active module's cache poisoned.
    flatpak_module = _sys.modules.get("src.core.flatpak")
    if flatpak_module is None:
        import src.core.flatpak as flatpak_module

    original_value = flatpak_module._flatpak_detected
    flatpak_module._flatpak_detected = None

    # Patch os.path.exists to return False for /.flatpak-info
    # This ensures that even if the flatpak module is reimported,
    # is_flatpak() will return False
    original_exists = os.path.exists

    def patched_exists(path):
        if path == "/.flatpak-info":
            return False
        return original_exists(path)

    os.path.exists = patched_exists

    try:
        yield
    finally:
        # Restore on the CURRENT module (may differ from setup if modules were swapped)
        current_flatpak = _sys.modules.get("src.core.flatpak")
        if current_flatpak is not None:
            current_flatpak._flatpak_detected = original_value
        os.path.exists = original_exists


# =============================================================================
# Module Cache Management
# =============================================================================


def _clear_src_modules():
    """
    Clear all cached src.* modules from sys.modules.

    This ensures each test starts with a fresh import of source modules,
    preventing stale mock references from affecting subsequent tests.
    """
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


@contextlib.contextmanager
def preserve_displaced_modules(match=None):
    """Snapshot matching sys.modules entries and restore them on exit.

    Test modules that clear or mock src.* (or gi/matplotlib) modules must put
    the ORIGINAL module objects back afterwards: other test modules bind src
    symbols at collection time, and patching a re-imported module while
    calling a stale reference makes assertions silently miss (see the
    tests/cli/test_scan_cmd.py pollution this pattern fixed). Use this instead
    of hand-rolling the snapshot/restore idiom.

    Args:
        match: Predicate on the module name; defaults to src.* modules.
    """
    if match is None:

        def match(name):
            return name.startswith("src.")

    snapshot = {name: module for name, module in sys.modules.items() if match(name)}
    try:
        yield
    finally:
        for name in [mod for mod in sys.modules if match(mod)]:
            del sys.modules[name]
        sys.modules.update(snapshot)


# =============================================================================
# Centralized GTK/GI Mocking
# =============================================================================


@pytest.fixture
def mock_gi_modules():
    """
    Unified GTK/GLib mocking for UI tests.

    This fixture provides consistent mocking of GTK/GLib/Adw modules across
    all test files. It:
    - Temporarily clears cached src.* modules while preserving the Flatpak module
    - Sets up real base classes for widgets (required for object.__new__)
    - Provides access to mock objects via returned dict

    Usage:
        def test_something(mock_gi_modules):
            gtk = mock_gi_modules['gtk']
            # gtk.SomeClass is available

        # Or just use it for side effects:
        def test_something(mock_gi_modules):
            from src.ui.some_view import SomeView
            # SomeView can now be imported with mocked GTK

    Yields:
        dict: Dictionary containing mock objects for gtk, adw, gio, glib
    """
    with preserve_displaced_modules(lambda name: name == "src.core.flatpak"):
        yield from _mock_gi_modules()


def _mock_gi_modules():
    """Build and yield the temporary GI module mocks."""
    # Clear any cached src modules first
    _clear_src_modules()

    # Create mock modules
    mock_gtk = MagicMock()
    mock_adw = MagicMock()
    mock_gio = MagicMock()
    mock_glib = MagicMock()
    # markup_escape_text must pass through text so tests can assert on actual values
    mock_glib.markup_escape_text = MagicMock(side_effect=lambda text, *args: text)

    # Set real classes for widgets (required for object.__new__)
    mock_gtk.Box = MockGtkBox
    mock_gtk.Widget = MockGtkWidget
    mock_gtk.ListBox = MockGtkListBox
    mock_gtk.ListBoxRow = MockGtkListBoxRow
    mock_gtk.Orientation = MockGtkBox.Orientation

    mock_adw.PreferencesWindow = MockAdwPreferencesWindow
    mock_adw.Dialog = MockAdwDialog
    mock_adw.Window = MockAdwWindow
    mock_adw.ApplicationWindow = MockAdwApplicationWindow
    mock_adw.ExpanderRow = MockAdwExpanderRow

    # Widget row constructors return unique MagicMock instances to track calls separately
    mock_adw.ActionRow = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_adw.ComboRow = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_adw.SwitchRow = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_adw.EntryRow = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_adw.SpinRow = MagicMock()
    mock_adw.SpinRow.new_with_range = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    # Container widgets - tests may set return_value to control what's returned
    mock_adw.PreferencesGroup = MagicMock()
    mock_adw.PreferencesPage = MagicMock()
    mock_adw.AlertDialog = MagicMock()

    # Leaflet and navigation mocks for sidebar layout
    mock_adw.Leaflet = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_adw.LeafletTransitionType = MagicMock()
    mock_adw.LeafletTransitionType.SLIDE = 1
    mock_adw.NavigationDirection = MagicMock()
    mock_adw.NavigationDirection.BACK = 0
    mock_adw.NavigationDirection.FORWARD = 1
    mock_adw.HeaderBar = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_adw.ToolbarView = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_adw.ToastOverlay = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_adw.StatusPage = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())

    # GTK widget constructors used by compat.py - must return unique instances
    mock_gtk.Entry = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_gtk.Switch = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())

    # GTK widget constructors - tests may set return_value
    mock_gtk.Button = MagicMock()
    mock_gtk.Button.new_from_icon_name = MagicMock(return_value=MagicMock())
    mock_gtk.Image = MagicMock()
    mock_gtk.Image.new_from_icon_name = MagicMock()
    mock_gtk.StringList = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_gtk.Adjustment = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_gtk.Separator = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_gtk.Label = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_gtk.MenuButton = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_gtk.ScrolledWindow = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    mock_gtk.SelectionMode = MagicMock()
    mock_gtk.SelectionMode.SINGLE = 1
    mock_gtk.IconSize = MagicMock()
    mock_gtk.IconSize.NORMAL = 1
    mock_gtk.PolicyType = MagicMock()
    mock_gtk.PolicyType.NEVER = 0
    mock_gtk.PolicyType.AUTOMATIC = 1

    # GTK version functions - return realistic values (GTK 4.14 for FileDialog support)
    mock_gtk.get_minor_version = MagicMock(return_value=14)
    mock_gtk.get_major_version = MagicMock(return_value=4)
    mock_gtk.get_micro_version = MagicMock(return_value=0)

    # Build gi module structure
    mock_gi_module = MagicMock()
    mock_gi_module.require_version = MagicMock()
    # Set version_info to a real tuple to support matplotlib version checks
    mock_gi_module.version_info = (3, 48, 0)

    mock_repository = MagicMock()
    mock_repository.Gtk = mock_gtk
    mock_repository.Adw = mock_adw
    mock_repository.Gio = mock_gio
    mock_repository.GLib = mock_glib

    # Patch sys.modules
    with patch.dict(
        sys.modules,
        {
            "gi": mock_gi_module,
            "gi.repository": mock_repository,
            "gi.repository.Gtk": mock_gtk,
            "gi.repository.Adw": mock_adw,
            "gi.repository.Gio": mock_gio,
            "gi.repository.GLib": mock_glib,
        },
    ):
        yield {
            "gtk": mock_gtk,
            "adw": mock_adw,
            "gio": mock_gio,
            "glib": mock_glib,
            "gi": mock_gi_module,
            "repository": mock_repository,
        }

    # Cleanup after test; the fixture wrapper restores the original Flatpak module.
    _clear_src_modules()


# =============================================================================
# Utility Functions
# =============================================================================


def create_instance_without_init(cls):
    """
    Create an instance of a class without calling __init__.

    This is a Python 3.13+ compatible alternative to:
        with mock.patch.object(cls, '__init__', lambda self, **kwargs: None):
            instance = cls()

    Python 3.13 disallows patching __init__ as a magic method, so we use
    object.__new__ to bypass it entirely.

    Args:
        cls: The class to instantiate

    Returns:
        An instance of cls with no attributes set
    """
    return object.__new__(cls)


# EICAR standard test string - recognized by antivirus software as a test file
# This string MUST be exact (any modification breaks detection)
# See: https://www.eicar.org/download-anti-malware-testfile/
EICAR_STRING = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


@pytest.fixture
def eicar_file(tmp_path: Path) -> Path:
    """
    Create a temporary EICAR test file for antivirus testing.

    The EICAR test file is a standard test file used to verify antivirus
    detection without using real malware. ClamAV classifies EICAR as:
    - Category: "Test"
    - Severity: "low"

    The file is automatically cleaned up after the test completes.

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Yields:
        Path: Path to the temporary EICAR test file
    """
    eicar_path = tmp_path / "eicar_test_file.txt"
    try:
        eicar_path.write_text(EICAR_STRING)
        yield eicar_path
    finally:
        # Ensure cleanup even if test fails
        if eicar_path.exists():
            eicar_path.unlink()


@pytest.fixture
def eicar_directory(tmp_path: Path) -> Path:
    """
    Create a temporary directory containing an EICAR test file.

    Useful for testing directory scanning with infected files.
    The directory structure is:
        tmp_path/
            eicar_dir/
                eicar_test_file.txt (EICAR content)
                clean_file.txt (clean content)

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Yields:
        Path: Path to the temporary directory containing test files
    """
    eicar_dir = tmp_path / "eicar_dir"
    eicar_dir.mkdir()
    eicar_file_path = eicar_dir / "eicar_test_file.txt"
    clean_file_path = eicar_dir / "clean_file.txt"

    try:
        eicar_file_path.write_text(EICAR_STRING)
        clean_file_path.write_text("This is a clean file with no threats.")
        yield eicar_dir
    finally:
        # Ensure cleanup even if test fails
        if eicar_file_path.exists():
            eicar_file_path.unlink()
        if clean_file_path.exists():
            clean_file_path.unlink()
        if eicar_dir.exists():
            eicar_dir.rmdir()


@pytest.fixture
def clean_test_file(tmp_path: Path) -> Path:
    """
    Create a temporary clean test file for scanning.

    Useful for testing clean scan results.

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Yields:
        Path: Path to the temporary clean test file
    """
    clean_path = tmp_path / "clean_test_file.txt"
    try:
        clean_path.write_text("This is a clean file with no malicious content.")
        yield clean_path
    finally:
        if clean_path.exists():
            clean_path.unlink()


@pytest.fixture
def mock_scanner():
    """
    Create a mock Scanner object for testing.

    Provides a pre-configured MagicMock that mimics the Scanner interface.
    Commonly used methods are pre-configured with sensible defaults:
    - scan_sync: Returns a clean ScanResult mock by default
    - scan_async: Returns a clean ScanResult mock by default
    - cancel_scan: Does nothing by default
    - _build_command: Returns a basic clamscan command

    The mock can be easily customized in individual tests by modifying
    return_value or side_effect on specific methods.

    Example usage:
        def test_something(mock_scanner):
            # Use default behavior
            result = mock_scanner.scan_sync("/path")

            # Or customize for specific test
            mock_scanner.scan_sync.return_value.status = ScanStatus.INFECTED
            mock_scanner.scan_sync.return_value.infected_count = 1

    Yields:
        MagicMock: A mock Scanner object with pre-configured methods
    """
    scanner = mock.MagicMock()

    # Configure default scan result (clean scan)
    clean_result = mock.MagicMock()
    clean_result.status = "clean"
    clean_result.is_clean = True
    clean_result.has_threats = False
    clean_result.infected_count = 0
    clean_result.scanned_files = 0
    clean_result.scanned_dirs = 0
    clean_result.infected_files = []
    clean_result.threat_details = []
    clean_result.error_message = None
    clean_result.stdout = ""
    clean_result.stderr = ""
    clean_result.exit_code = 0

    # Configure default return values for scanner methods
    scanner.scan_sync.return_value = clean_result
    scanner.scan_async.return_value = clean_result
    scanner.cancel_scan.return_value = None
    scanner._build_command.return_value = ["clamscan", "-i"]
    scanner._cancel_event = MagicMock()
    scanner._cancel_event.is_set.return_value = False
    scanner._current_process = None

    yield scanner
