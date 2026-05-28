# ClamUI TrayService Tests
"""
Unit tests for the TrayService class.

Tests cover:
- Class constants and configuration
- Status update handling
- Progress update handling
- Window visibility updates
- Profile management
- Command dispatch (handle_command)
- Helper methods for icon/tooltip/status
- IPC message handling

The TrayService uses D-Bus SNI protocol via GIO. Tests mock the GLib/Gio
dependencies to avoid requiring a running D-Bus session.
"""

import json
import sys
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def mock_glib_gio(monkeypatch):
    """Mock GLib and Gio modules for all tests."""
    mock_glib = mock.MagicMock()
    mock_gio = mock.MagicMock()

    # GLib.Variant should return a simple mock
    mock_glib.Variant = mock.MagicMock(return_value=mock.MagicMock())
    mock_glib.MainLoop = mock.MagicMock()
    mock_glib.idle_add = mock.MagicMock(side_effect=lambda fn, *args: fn(*args))

    monkeypatch.setitem(sys.modules, "gi", mock.MagicMock())
    monkeypatch.setitem(sys.modules, "gi.repository", mock.MagicMock())
    monkeypatch.setitem(sys.modules, "gi.repository.GLib", mock_glib)
    monkeypatch.setitem(sys.modules, "gi.repository.Gio", mock_gio)

    # Mock Dbusmenu as unavailable by default
    monkeypatch.setitem(sys.modules, "gi.repository.Dbusmenu", None)

    yield {"glib": mock_glib, "gio": mock_gio}


@pytest.fixture
def mock_tray_icons(monkeypatch):
    """Mock tray_icons module."""
    mock_module = mock.MagicMock()
    mock_module.find_clamui_base_icon = mock.MagicMock(return_value=None)
    mock_module.get_tray_icon_cache_dir = mock.MagicMock(return_value="/tmp/test")
    mock_module.TrayIconGenerator = mock.MagicMock()
    mock_module.CUSTOM_ICONS_AVAILABLE = False
    monkeypatch.setitem(sys.modules, "src.ui.tray_icons", mock_module)
    return mock_module


@pytest.fixture
def tray_service_class(mock_glib_gio, mock_tray_icons, monkeypatch):
    """Get TrayService class with mocked dependencies."""
    # Clear any cached import
    if "src.ui.tray_service" in sys.modules:
        del sys.modules["src.ui.tray_service"]

    from src.ui.tray_service import TrayService

    return TrayService


@pytest.fixture
def tray_service(tray_service_class):
    """Create a TrayService instance for testing."""
    service = object.__new__(tray_service_class)

    # Initialize state without calling __init__
    service._loop = None
    service._bus = None
    service._sni_registration_id = 0
    service._bus_name_id = 0
    service._running = True
    service._watcher_registered = False
    service._watcher_name = None
    service._watcher_retry_source_id = 0
    service._icon_pixmap_cache = {}

    # Status state
    service._current_status = "protected"
    service._window_visible = True
    service._progress_label = ""

    # Profile state
    service._profiles = []
    service._current_profile_id = None

    # Icon generator
    service._icon_generator = None
    service._using_custom_icons = False

    # DBusMenu
    service._dbusmenu_server = None
    service._menu_root = None

    return service


class TestTrayServiceConstants:
    """Tests for TrayService class constants."""

    def test_icon_map_has_all_statuses(self, tray_service_class):
        """Test ICON_MAP contains all expected status keys."""
        expected_statuses = ["protected", "warning", "scanning", "threat"]
        for status in expected_statuses:
            assert status in tray_service_class.ICON_MAP
            assert isinstance(tray_service_class.ICON_MAP[status], str)

    def test_sni_status_map_has_all_statuses(self, tray_service_class):
        """Test SNI_STATUS_MAP contains all expected status keys."""
        expected_statuses = ["protected", "warning", "scanning", "threat"]
        for status in expected_statuses:
            assert status in tray_service_class.SNI_STATUS_MAP
            assert tray_service_class.SNI_STATUS_MAP[status] in [
                "Active",
                "NeedsAttention",
                "Passive",
            ]

    def test_dbus_name_format(self, tray_service_class):
        """Test DBUS_NAME follows D-Bus naming conventions."""
        assert tray_service_class.DBUS_NAME.startswith("io.github")
        assert "." in tray_service_class.DBUS_NAME
        # D-Bus names should not have underscores
        assert "ClamUI" in tray_service_class.DBUS_NAME

    def test_sni_path_format(self, tray_service_class):
        """Test SNI_PATH is valid D-Bus object path."""
        assert tray_service_class.SNI_PATH.startswith("/")
        assert tray_service_class.SNI_PATH == "/StatusNotifierItem"

    def test_menu_path_format(self, tray_service_class):
        """Test MENU_PATH is valid D-Bus object path."""
        assert tray_service_class.MENU_PATH.startswith("/")


class TestTrayServiceInitialization:
    """Tests for TrayService initialization state."""

    def test_initial_status_is_protected(self, tray_service):
        """Test initial status is 'protected'."""
        assert tray_service._current_status == "protected"

    def test_initial_window_visible_is_true(self, tray_service):
        """Test window is initially visible."""
        assert tray_service._window_visible is True

    def test_initial_progress_label_is_empty(self, tray_service):
        """Test progress label is initially empty."""
        assert tray_service._progress_label == ""

    def test_initial_profiles_is_empty(self, tray_service):
        """Test profiles list is initially empty."""
        assert tray_service._profiles == []

    def test_initial_current_profile_is_none(self, tray_service):
        """Test current profile ID is initially None."""
        assert tray_service._current_profile_id is None

    def test_running_flag_is_true(self, tray_service):
        """Test running flag is initially True."""
        assert tray_service._running is True


class TestUpdateStatus:
    """Tests for update_status method."""

    def test_update_status_sets_current_status(self, tray_service):
        """Test update_status sets the current status."""
        tray_service._emit_signal = mock.MagicMock()

        tray_service.update_status("scanning")
        assert tray_service._current_status == "scanning"

    def test_update_status_unknown_defaults_to_protected(self, tray_service):
        """Test unknown status defaults to 'protected'."""
        tray_service._emit_signal = mock.MagicMock()

        tray_service.update_status("unknown_status")
        assert tray_service._current_status == "protected"

    def test_update_status_emits_signals(self, tray_service):
        """Test update_status emits required D-Bus signals."""
        tray_service._emit_signal = mock.MagicMock()

        tray_service.update_status("warning")

        # Should emit NewIcon, NewToolTip, and NewStatus signals
        signal_names = [call[0][0] for call in tray_service._emit_signal.call_args_list]
        assert "NewIcon" in signal_names
        assert "NewToolTip" in signal_names
        assert "NewStatus" in signal_names

    def test_update_status_all_valid_statuses(self, tray_service):
        """Test all valid status values are accepted."""
        tray_service._emit_signal = mock.MagicMock()

        for status in ["protected", "warning", "scanning", "threat"]:
            tray_service.update_status(status)
            assert tray_service._current_status == status


class TestUpdateProgress:
    """Tests for update_progress method."""

    def test_update_progress_sets_label(self, tray_service):
        """Test update_progress sets progress label."""
        tray_service._emit_signal = mock.MagicMock()

        tray_service.update_progress(50)
        assert tray_service._progress_label == "50%"

    def test_update_progress_zero_clears_label(self, tray_service):
        """Test progress of 0 clears the label."""
        tray_service._emit_signal = mock.MagicMock()
        tray_service._progress_label = "50%"

        tray_service.update_progress(0)
        assert tray_service._progress_label == ""

    def test_update_progress_over_100_clears_label(self, tray_service):
        """Test progress over 100 clears the label."""
        tray_service._emit_signal = mock.MagicMock()
        tray_service._progress_label = "50%"

        tray_service.update_progress(101)
        assert tray_service._progress_label == ""

    def test_update_progress_100_is_valid(self, tray_service):
        """Test progress of 100 is valid."""
        tray_service._emit_signal = mock.MagicMock()

        tray_service.update_progress(100)
        assert tray_service._progress_label == "100%"

    def test_update_progress_emits_tooltip_signal(self, tray_service):
        """Test update_progress emits NewToolTip signal."""
        tray_service._emit_signal = mock.MagicMock()

        tray_service.update_progress(75)

        tray_service._emit_signal.assert_called_with("NewToolTip")


class TestUpdateWindowVisible:
    """Tests for update_window_visible method."""

    def test_update_window_visible_sets_state(self, tray_service):
        """Test update_window_visible sets visibility state."""
        tray_service._rebuild_menu = mock.MagicMock()

        tray_service.update_window_visible(False)
        assert tray_service._window_visible is False

        tray_service.update_window_visible(True)
        assert tray_service._window_visible is True

    def test_update_window_visible_rebuilds_menu(self, tray_service):
        """Test update_window_visible rebuilds the menu."""
        tray_service._rebuild_menu = mock.MagicMock()

        tray_service.update_window_visible(False)
        tray_service._rebuild_menu.assert_called_once()


class TestUpdateProfiles:
    """Tests for update_profiles method."""

    def test_update_profiles_sets_profiles_list(self, tray_service):
        """Test update_profiles sets the profiles list."""
        profiles = [
            {"id": "1", "name": "Quick Scan"},
            {"id": "2", "name": "Full Scan"},
        ]

        tray_service.update_profiles(profiles)
        assert tray_service._profiles == profiles

    def test_update_profiles_sets_current_profile_id(self, tray_service):
        """Test update_profiles sets current profile ID."""
        profiles = [{"id": "1", "name": "Quick Scan"}]

        tray_service.update_profiles(profiles, current_profile_id="1")
        assert tray_service._current_profile_id == "1"

    def test_update_profiles_without_current_id_preserves_existing(self, tray_service):
        """Test update_profiles without current_id preserves existing ID."""
        tray_service._current_profile_id = "original"
        profiles = [{"id": "1", "name": "Quick Scan"}]

        tray_service.update_profiles(profiles)
        assert tray_service._current_profile_id == "original"


class TestHandleCommand:
    """Tests for handle_command dispatch method."""

    def test_handle_update_status_command(self, tray_service):
        """Test handling update_status command."""
        tray_service.update_status = mock.MagicMock()

        # Patch GLib.idle_add at module level
        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command({"action": "update_status", "status": "scanning"})

        tray_service.update_status.assert_called_with("scanning")

    def test_handle_update_progress_command(self, tray_service):
        """Test handling update_progress command."""
        tray_service.update_progress = mock.MagicMock()

        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command({"action": "update_progress", "percentage": 75})

        tray_service.update_progress.assert_called_with(75)

    def test_handle_update_window_visible_command(self, tray_service):
        """Test handling update_window_visible command."""
        tray_service.update_window_visible = mock.MagicMock()

        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command({"action": "update_window_visible", "visible": False})

        tray_service.update_window_visible.assert_called_with(False)

    def test_handle_update_profiles_command(self, tray_service):
        """Test handling update_profiles command."""
        tray_service.update_profiles = mock.MagicMock()
        profiles = [{"id": "1", "name": "Test"}]

        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command(
                {
                    "action": "update_profiles",
                    "profiles": profiles,
                    "current_profile_id": "1",
                }
            )

        tray_service.update_profiles.assert_called_with(profiles, "1")

    def test_handle_quit_command(self, tray_service):
        """Test handling quit command."""
        tray_service._quit = mock.MagicMock()

        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command({"action": "quit"})

        tray_service._quit.assert_called_once()

    def test_handle_ping_command(self, tray_service):
        """Test handling ping command sends pong response."""
        tray_service._send_message = mock.MagicMock()

        tray_service.handle_command({"action": "ping"})

        tray_service._send_message.assert_called_with({"event": "pong"})

    def test_handle_unknown_command(self, tray_service):
        """Test handling unknown command logs warning."""
        tray_service._send_message = mock.MagicMock()

        # Should not raise, just log warning
        tray_service.handle_command({"action": "unknown_action"})

    def test_handle_command_missing_action(self, tray_service):
        """Test handling command without action key."""
        # Should handle gracefully
        tray_service.handle_command({})


class TestHelperMethods:
    """Tests for helper methods."""

    def test_get_icon_name_returns_mapped_icon(self, tray_service, tray_service_class):
        """Test _get_icon_name returns correct icon for status."""
        tray_service._current_status = "protected"

        result = tray_service._get_icon_name()
        assert result == tray_service_class.ICON_MAP["protected"]

    def test_get_icon_name_with_custom_icons(self, tray_service):
        """Test _get_icon_name with custom icon generator."""
        mock_generator = mock.MagicMock()
        mock_generator.get_icon_name.return_value = "clamui-tray-protected"

        tray_service._using_custom_icons = True
        tray_service._icon_generator = mock_generator
        tray_service._current_status = "protected"

        result = tray_service._get_icon_name()
        assert result == "clamui-tray-protected"

    def test_get_tooltip_shows_status(self, tray_service):
        """Test _get_tooltip includes status information."""
        tray_service._current_status = "protected"
        tray_service._progress_label = ""

        result = tray_service._get_tooltip()
        assert "ClamUI" in result

    def test_get_tooltip_includes_progress(self, tray_service):
        """Test _get_tooltip includes progress when scanning."""
        tray_service._current_status = "scanning"
        tray_service._progress_label = "75%"

        result = tray_service._get_tooltip()
        assert "75%" in result

    def test_get_sni_status_returns_mapped_status(self, tray_service, tray_service_class):
        """Test _get_sni_status returns correct SNI status."""
        tray_service._current_status = "threat"

        result = tray_service._get_sni_status()
        assert result == tray_service_class.SNI_STATUS_MAP["threat"]


class TestSendMessage:
    """Tests for IPC message sending."""

    def test_send_message_outputs_json(self, tray_service, capsys):
        """Test _send_message outputs valid JSON to stdout."""
        message = {"event": "test", "data": "value"}

        tray_service._send_message(message)

        captured = capsys.readouterr()
        assert json.loads(captured.out.strip()) == message

    def test_send_action_creates_action_message(self, tray_service):
        """Test _send_action creates properly formatted action message."""
        tray_service._send_message = mock.MagicMock()

        tray_service._send_action("toggle_window")

        tray_service._send_message.assert_called_once()
        message = tray_service._send_message.call_args[0][0]
        assert message["event"] == "menu_action"  # SNI uses menu_action
        assert message["action"] == "toggle_window"


class TestQuit:
    """Tests for quit behavior."""

    def test_quit_sets_running_to_false(self, tray_service):
        """Test _quit sets running flag to False."""
        tray_service._running = True

        tray_service._quit()

        assert tray_service._running is False

    def test_quit_quits_main_loop(self, tray_service):
        """Test _quit quits the GLib main loop."""
        mock_loop = mock.MagicMock()
        tray_service._loop = mock_loop

        tray_service._quit()

        mock_loop.quit.assert_called_once()

    def test_quit_unregisters_dbus_objects(self, tray_service):
        """Test _quit unregisters D-Bus objects."""
        mock_bus = mock.MagicMock()
        tray_service._bus = mock_bus
        tray_service._sni_registration_id = 123

        tray_service._quit()

        mock_bus.unregister_object.assert_called_with(123)


# =============================================================================
# TestSNIProtocol - D-Bus StatusNotifierItem property getters
# =============================================================================


class TestSNIProtocol:
    """Tests for StatusNotifierItem D-Bus interface properties."""

    def _get_prop(self, tray_service, prop_name):
        """Helper to call _handle_get_property with standard args."""
        return tray_service._handle_get_property(
            None, "sender", "/StatusNotifierItem", "org.kde.StatusNotifierItem", prop_name
        )

    def test_get_property_category_returns_variant(self, tray_service):
        """Test Category property returns a non-None result."""
        result = self._get_prop(tray_service, "Category")
        assert result is not None

    def test_get_property_id_returns_variant(self, tray_service):
        """Test Id property returns a non-None result."""
        result = self._get_prop(tray_service, "Id")
        assert result is not None

    def test_get_property_title_returns_variant(self, tray_service):
        """Test Title property returns a non-None result."""
        result = self._get_prop(tray_service, "Title")
        assert result is not None

    def test_get_property_status_returns_variant(self, tray_service):
        """Test Status property returns a non-None result for all statuses."""
        for status in ["protected", "warning", "scanning", "threat"]:
            tray_service._current_status = status
            result = self._get_prop(tray_service, "Status")
            assert result is not None

    def test_get_property_icon_name_returns_variant(self, tray_service):
        """Test IconName property returns a non-None result."""
        tray_service._current_status = "warning"
        result = self._get_prop(tray_service, "IconName")
        assert result is not None

    def test_get_property_icon_pixmap_returns_variant(self, tray_service):
        """Test IconPixmap property returns a non-None result."""
        result = self._get_prop(tray_service, "IconPixmap")
        assert result is not None

    def test_get_property_window_id_returns_variant(self, tray_service):
        """Test WindowId property returns a non-None result."""
        result = self._get_prop(tray_service, "WindowId")
        assert result is not None

    def test_get_property_item_is_menu_returns_variant(self, tray_service):
        """Test ItemIsMenu property returns a non-None result."""
        result = self._get_prop(tray_service, "ItemIsMenu")
        assert result is not None

    def test_get_property_menu_returns_variant(self, tray_service):
        """Test Menu property returns a non-None result."""
        result = self._get_prop(tray_service, "Menu")
        assert result is not None

    def test_get_property_overlay_icon_name_returns_variant(self, tray_service):
        """Test OverlayIconName property returns a non-None result."""
        result = self._get_prop(tray_service, "OverlayIconName")
        assert result is not None

    def test_get_property_overlay_icon_pixmap_returns_variant(self, tray_service):
        """Test OverlayIconPixmap property returns a non-None result."""
        result = self._get_prop(tray_service, "OverlayIconPixmap")
        assert result is not None

    def test_get_property_attention_icon_name_returns_variant(self, tray_service):
        """Test AttentionIconName property returns a non-None result."""
        result = self._get_prop(tray_service, "AttentionIconName")
        assert result is not None

    def test_get_property_attention_icon_pixmap_returns_variant(self, tray_service):
        """Test AttentionIconPixmap property returns a non-None result."""
        result = self._get_prop(tray_service, "AttentionIconPixmap")
        assert result is not None

    def test_get_property_tooltip_returns_variant(self, tray_service):
        """Test ToolTip property returns a non-None result."""
        result = self._get_prop(tray_service, "ToolTip")
        assert result is not None

    def test_get_property_icon_theme_path_returns_variant(self, tray_service):
        """Test IconThemePath property returns a non-None result."""
        result = self._get_prop(tray_service, "IconThemePath")
        assert result is not None

    def test_get_property_attention_movie_name_returns_variant(self, tray_service):
        """Test AttentionMovieName property returns a non-None result."""
        result = self._get_prop(tray_service, "AttentionMovieName")
        assert result is not None

    def test_get_property_unknown_returns_none(self, tray_service):
        """Test unknown property returns None."""
        result = tray_service._handle_get_property(
            None,
            "sender",
            "/StatusNotifierItem",
            "org.kde.StatusNotifierItem",
            "NonExistentProperty",
        )

        assert result is None

    def test_register_with_watcher_calls_dbus(self, tray_service, mock_glib_gio):
        """Test _register_with_watcher calls D-Bus RegisterStatusNotifierItem."""
        mock_bus = mock.MagicMock()
        tray_service._bus = mock_bus

        with mock.patch(
            "src.ui.tray_service.GLib.Variant",
            side_effect=lambda signature, value: (signature, value),
        ):
            tray_service._register_with_watcher()

        mock_bus.call.assert_called_once()
        call_args = mock_bus.call.call_args
        # First arg is the watcher service name
        assert "StatusNotifierWatcher" in call_args[0][0]
        # Method name
        assert call_args[0][3] == "RegisterStatusNotifierItem"
        assert call_args[0][4] == ("(s)", (tray_service.SNI_PATH,))

    def test_register_with_watcher_falls_back_to_next_watcher(self, tray_service):
        """Test watcher registration falls back when the first watcher is unavailable."""
        mock_bus = mock.MagicMock()
        mock_bus.call_finish.side_effect = RuntimeError("watcher unavailable")
        tray_service._bus = mock_bus
        tray_service._schedule_watcher_retry = mock.MagicMock()

        tray_service._register_with_watcher()

        first_call = mock_bus.call.call_args_list[0]
        callback = first_call[0][9]
        user_data = first_call[0][10]
        callback(mock_bus, mock.sentinel.result, user_data)

        assert mock_bus.call.call_count == 2
        assert mock_bus.call.call_args_list[0][0][0] == "org.x.StatusNotifierWatcher"
        assert mock_bus.call.call_args_list[1][0][0] == "org.kde.StatusNotifierWatcher"

    def test_register_with_watcher_schedules_retry_after_all_watchers_fail(self, tray_service):
        """Test watcher registration retries after all known watcher names fail."""
        mock_bus = mock.MagicMock()
        mock_bus.call_finish.side_effect = RuntimeError("watcher unavailable")
        tray_service._bus = mock_bus
        tray_service._schedule_watcher_retry = mock.MagicMock()

        tray_service._register_with_watcher()

        for _ in range(3):
            call = mock_bus.call.call_args_list[-1]
            callback = call[0][9]
            user_data = call[0][10]
            callback(mock_bus, mock.sentinel.result, user_data)

        assert mock_bus.call.call_count == 3
        tray_service._schedule_watcher_retry.assert_called_once()

    def test_register_with_watcher_marks_successful_registration(self, tray_service):
        """Test successful watcher registration records the watcher name."""
        mock_bus = mock.MagicMock()
        tray_service._bus = mock_bus
        tray_service._clear_watcher_retry = mock.MagicMock()

        tray_service._register_with_watcher()

        first_call = mock_bus.call.call_args
        callback = first_call[0][9]
        user_data = first_call[0][10]
        callback(mock_bus, mock.sentinel.result, user_data)

        assert tray_service._watcher_registered is True
        assert tray_service._watcher_name == "org.x.StatusNotifierWatcher"
        tray_service._clear_watcher_retry.assert_called_once()

    def test_register_with_watcher_noop_when_no_bus(self, tray_service):
        """Test _register_with_watcher does nothing when no bus connection."""
        tray_service._bus = None

        # Should not raise
        tray_service._register_with_watcher()

    def test_on_bus_acquired_registers_sni_interface_without_watcher_registration(
        self, tray_service, mock_glib_gio
    ):
        """Test SNI object export happens on bus acquisition, before watcher registration."""
        connection = mock.MagicMock()
        tray_service._register_with_watcher = mock.MagicMock()

        tray_service._on_bus_acquired(connection, tray_service.DBUS_NAME)

        connection.register_object.assert_called_once()
        tray_service._register_with_watcher.assert_not_called()

    def test_on_name_acquired_starts_watcher_registration(self, tray_service):
        """Test watcher registration starts only after the bus name is owned."""
        tray_service._register_with_watcher = mock.MagicMock()

        tray_service._on_name_acquired(mock.MagicMock(), tray_service.DBUS_NAME)

        tray_service._register_with_watcher.assert_called_once()


# =============================================================================
# TestMethodCalls - D-Bus method call handling
# =============================================================================


class TestMethodCalls:
    """Tests for _handle_method_call D-Bus method dispatch."""

    def test_activate_sends_toggle_window(self, tray_service):
        """Test Activate method sends toggle_window action."""
        tray_service._send_action = mock.MagicMock()
        mock_invocation = mock.MagicMock()

        tray_service._handle_method_call(
            None,
            "sender",
            "/StatusNotifierItem",
            "org.kde.StatusNotifierItem",
            "Activate",
            mock.MagicMock(),
            mock_invocation,
        )

        tray_service._send_action.assert_called_with("toggle_window")
        mock_invocation.return_value.assert_called_with(None)

    def test_context_menu_returns_value(self, tray_service):
        """Test ContextMenu method returns value without sending action."""
        tray_service._send_action = mock.MagicMock()
        mock_invocation = mock.MagicMock()

        tray_service._handle_method_call(
            None,
            "sender",
            "/StatusNotifierItem",
            "org.kde.StatusNotifierItem",
            "ContextMenu",
            mock.MagicMock(),
            mock_invocation,
        )

        # ContextMenu is handled by DBusMenu, not by sending an action
        tray_service._send_action.assert_not_called()
        mock_invocation.return_value.assert_called_with(None)

    def test_secondary_activate_returns_value(self, tray_service):
        """Test SecondaryActivate (middle click) returns value."""
        mock_invocation = mock.MagicMock()

        tray_service._handle_method_call(
            None,
            "sender",
            "/StatusNotifierItem",
            "org.kde.StatusNotifierItem",
            "SecondaryActivate",
            mock.MagicMock(),
            mock_invocation,
        )

        mock_invocation.return_value.assert_called_with(None)

    def test_scroll_returns_value(self, tray_service):
        """Test Scroll method returns value."""
        mock_invocation = mock.MagicMock()
        mock_params = mock.MagicMock()
        mock_params.unpack.return_value = (10, "vertical")

        tray_service._handle_method_call(
            None,
            "sender",
            "/StatusNotifierItem",
            "org.kde.StatusNotifierItem",
            "Scroll",
            mock_params,
            mock_invocation,
        )

        mock_invocation.return_value.assert_called_with(None)

    def test_unknown_method_returns_error(self, tray_service):
        """Test unknown method returns D-Bus error."""
        mock_invocation = mock.MagicMock()

        tray_service._handle_method_call(
            None,
            "sender",
            "/StatusNotifierItem",
            "org.kde.StatusNotifierItem",
            "UnknownMethod",
            mock.MagicMock(),
            mock_invocation,
        )

        mock_invocation.return_dbus_error.assert_called_once()
        error_args = mock_invocation.return_dbus_error.call_args[0]
        assert "UnknownMethod" in error_args[0] or "UnknownMethod" in error_args[1]


# =============================================================================
# TestMenuHandling - menu item callbacks
# =============================================================================


class TestMenuHandling:
    """Tests for menu item activation callbacks."""

    def test_on_menu_toggle_window(self, tray_service):
        """Test toggle window menu item sends toggle_window action."""
        tray_service._send_action = mock.MagicMock()

        tray_service._on_menu_toggle_window(mock.MagicMock(), 0)

        tray_service._send_action.assert_called_with("toggle_window")

    def test_on_menu_quick_scan(self, tray_service):
        """Test quick scan menu item sends quick_scan action."""
        tray_service._send_action = mock.MagicMock()

        tray_service._on_menu_quick_scan(mock.MagicMock(), 0)

        tray_service._send_action.assert_called_with("quick_scan")

    def test_on_menu_full_scan(self, tray_service):
        """Test full scan menu item sends full_scan action."""
        tray_service._send_action = mock.MagicMock()

        tray_service._on_menu_full_scan(mock.MagicMock(), 0)

        tray_service._send_action.assert_called_with("full_scan")

    def test_on_menu_update(self, tray_service):
        """Test update menu item sends update action."""
        tray_service._send_action = mock.MagicMock()

        tray_service._on_menu_update(mock.MagicMock(), 0)

        tray_service._send_action.assert_called_with("update")

    def test_on_menu_quit(self, tray_service):
        """Test quit menu item sends quit action."""
        tray_service._send_action = mock.MagicMock()

        tray_service._on_menu_quit(mock.MagicMock(), 0)

        tray_service._send_action.assert_called_with("quit")


# =============================================================================
# TestStatusUpdates - handle_command for status/progress/icon changes
# =============================================================================


class TestStatusUpdates:
    """Tests for status, progress, and icon update command handling."""

    def test_handle_command_update_status_dispatches(self, tray_service):
        """Test handle_command dispatches update_status with correct args."""
        tray_service.update_status = mock.MagicMock()

        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command({"action": "update_status", "status": "threat"})

        tray_service.update_status.assert_called_with("threat")

    def test_handle_command_update_status_defaults_to_protected(self, tray_service):
        """Test update_status defaults to 'protected' when status key missing."""
        tray_service.update_status = mock.MagicMock()

        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command({"action": "update_status"})

        tray_service.update_status.assert_called_with("protected")

    def test_handle_command_update_progress_dispatches(self, tray_service):
        """Test handle_command dispatches update_progress with percentage."""
        tray_service.update_progress = mock.MagicMock()

        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command({"action": "update_progress", "percentage": 42})

        tray_service.update_progress.assert_called_with(42)

    def test_handle_command_update_progress_defaults_to_zero(self, tray_service):
        """Test update_progress defaults to 0 when percentage missing."""
        tray_service.update_progress = mock.MagicMock()

        with mock.patch(
            "src.ui.tray_service.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)
        ):
            tray_service.handle_command({"action": "update_progress"})

        tray_service.update_progress.assert_called_with(0)

    def test_update_status_emits_new_status_signal(self, tray_service, mock_glib_gio):
        """Test update_status emits NewStatus signal with SNI status string."""
        tray_service._emit_signal = mock.MagicMock()

        tray_service.update_status("threat")

        # Should emit NewStatus with variant
        new_status_calls = [
            c for c in tray_service._emit_signal.call_args_list if c[0][0] == "NewStatus"
        ]
        assert len(new_status_calls) == 1

    def test_emit_signal_uses_bus(self, tray_service, mock_glib_gio):
        """Test _emit_signal sends signal via D-Bus connection."""
        mock_bus = mock.MagicMock()
        tray_service._bus = mock_bus

        tray_service._emit_signal("NewIcon")

        mock_bus.emit_signal.assert_called_once()
        call_args = mock_bus.emit_signal.call_args[0]
        assert call_args[2] == "org.kde.StatusNotifierItem"
        assert call_args[3] == "NewIcon"

    def test_emit_signal_noop_when_no_bus(self, tray_service):
        """Test _emit_signal does nothing when bus is None."""
        tray_service._bus = None

        # Should not raise
        tray_service._emit_signal("NewIcon")

    def test_emit_signal_handles_exception(self, tray_service):
        """Test _emit_signal catches exceptions."""
        mock_bus = mock.MagicMock()
        mock_bus.emit_signal.side_effect = RuntimeError("D-Bus error")
        tray_service._bus = mock_bus

        # Should not raise
        tray_service._emit_signal("NewIcon")


# =============================================================================
# TestIPCProtocol - stdin/stdout JSON message handling
# =============================================================================


class TestIPCProtocol:
    """Tests for IPC protocol (stdin reading, stdout writing)."""

    def test_read_stdin_parses_json(self, tray_service):
        """Test _read_stdin parses JSON lines and dispatches to handle_command."""
        tray_service.handle_command = mock.MagicMock()
        tray_service._quit = mock.MagicMock()

        lines = ['{"action": "ping"}\n', '{"action": "update_status", "status": "scanning"}\n']

        with mock.patch("src.ui.tray_service.GLib.idle_add"):
            with mock.patch("sys.stdin", lines):
                tray_service._read_stdin()

        assert tray_service.handle_command.call_count == 2
        tray_service.handle_command.assert_any_call({"action": "ping"})
        tray_service.handle_command.assert_any_call(
            {"action": "update_status", "status": "scanning"}
        )

    def test_read_stdin_skips_empty_lines(self, tray_service):
        """Test _read_stdin skips empty lines."""
        tray_service.handle_command = mock.MagicMock()
        tray_service._quit = mock.MagicMock()

        lines = ["\n", "   \n", '{"action": "ping"}\n']

        with mock.patch("src.ui.tray_service.GLib.idle_add"):
            with mock.patch("sys.stdin", lines):
                tray_service._read_stdin()

        assert tray_service.handle_command.call_count == 1

    def test_read_stdin_handles_malformed_json(self, tray_service):
        """Test _read_stdin handles invalid JSON without crashing."""
        tray_service.handle_command = mock.MagicMock()
        tray_service._quit = mock.MagicMock()

        lines = ["not valid json\n", '{"action": "ping"}\n']

        with mock.patch("src.ui.tray_service.GLib.idle_add"):
            with mock.patch("sys.stdin", lines):
                tray_service._read_stdin()

        # Should still process the valid line
        assert tray_service.handle_command.call_count == 1
        tray_service.handle_command.assert_called_with({"action": "ping"})

    def test_read_stdin_stops_when_not_running(self, tray_service):
        """Test _read_stdin stops reading when _running is False."""
        call_count = 0

        def stop_after_first(cmd):
            nonlocal call_count
            call_count += 1
            tray_service._running = False

        tray_service.handle_command = mock.MagicMock(side_effect=stop_after_first)
        tray_service._quit = mock.MagicMock()

        lines = ['{"action": "ping"}\n', '{"action": "ping"}\n']

        with mock.patch("src.ui.tray_service.GLib.idle_add"):
            with mock.patch("sys.stdin", lines):
                tray_service._read_stdin()

        assert call_count == 1

    def test_read_stdin_calls_quit_on_eof(self, tray_service):
        """Test _read_stdin calls _quit via idle_add when stdin ends."""
        tray_service.handle_command = mock.MagicMock()
        mock_idle_add = mock.MagicMock()

        with mock.patch("src.ui.tray_service.GLib.idle_add", mock_idle_add):
            with mock.patch("sys.stdin", []):
                tray_service._read_stdin()

        # Should schedule _quit via idle_add in the finally block
        mock_idle_add.assert_called_with(tray_service._quit)

    def test_send_message_outputs_json_with_newline(self, tray_service, capsys):
        """Test _send_message outputs valid JSON followed by newline."""
        message = {"event": "ready"}

        tray_service._send_message(message)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert parsed == message

    def test_send_message_handles_exception(self, tray_service):
        """Test _send_message catches exceptions from print."""
        with mock.patch("builtins.print", side_effect=OSError("broken pipe")):
            # Should not raise
            tray_service._send_message({"event": "test"})

    def test_send_action_sends_menu_action_event(self, tray_service):
        """Test _send_action formats and sends menu_action event."""
        tray_service._send_message = mock.MagicMock()

        tray_service._send_action("quick_scan")

        tray_service._send_message.assert_called_once_with(
            {"event": "menu_action", "action": "quick_scan"}
        )


# =============================================================================
# TestIconThemePath - custom icon theme path
# =============================================================================


class TestIconThemePath:
    """Tests for icon theme path generation."""

    def test_get_icon_theme_path_empty_when_no_custom_icons(self, tray_service):
        """Test _get_icon_theme_path returns empty string without custom icons."""
        tray_service._using_custom_icons = False

        result = tray_service._get_icon_theme_path()

        assert result == ""

    def test_get_icon_theme_path_returns_parent_dir_with_custom_icons(
        self, tray_service, mock_tray_icons
    ):
        """Test _get_icon_theme_path returns parent of cache dir with custom icons."""
        mock_generator = mock.MagicMock()
        tray_service._using_custom_icons = True
        tray_service._icon_generator = mock_generator
        mock_tray_icons.get_tray_icon_cache_dir.return_value = (
            "/home/user/.local/share/icons/hicolor/22x22/apps"
        )

        # Need to patch the module-level function
        with mock.patch(
            "src.ui.tray_service.get_tray_icon_cache_dir",
            return_value="/home/user/.local/share/icons/hicolor/22x22/apps",
        ):
            result = tray_service._get_icon_theme_path()

        # Should return grandparent: /home/user/.local/share/icons/hicolor
        assert result == "/home/user/.local/share/icons/hicolor"


# =============================================================================
# TestIconPixmap - SNI pixmap fallback for stricter tray hosts
# =============================================================================


class TestIconPixmap:
    """Tests for icon pixmap generation."""

    def test_get_icon_pixmap_empty_without_custom_icons(self, tray_service):
        """Without generated custom icons, IconPixmap should be an empty array."""
        tray_service._using_custom_icons = False

        with mock.patch(
            "src.ui.tray_service.GLib.Variant",
            side_effect=lambda signature, value: (signature, value),
        ):
            result = tray_service._get_icon_pixmap()

        assert result == ("a(iiay)", [])

    def test_load_icon_pixmap_converts_rgba_to_argb(self, tray_service, tmp_path):
        """SNI IconPixmap bytes should be ARGB32 in network byte order."""
        image_module = pytest.importorskip("PIL.Image")
        icon_path = tmp_path / "icon.png"
        image_module.new("RGBA", (1, 1), (1, 2, 3, 4)).save(icon_path)

        with mock.patch(
            "src.ui.tray_service.GLib.Variant",
            side_effect=lambda signature, value: (signature, value),
        ):
            result = tray_service._load_icon_pixmap(str(icon_path))

        assert result == ("a(iiay)", [(1, 1, bytes([4, 1, 2, 3]))])

    def test_get_icon_pixmap_uses_generated_status_icon(self, tray_service):
        """IconPixmap should load the generated PNG for the requested status."""
        tray_service._using_custom_icons = True
        tray_service._icon_generator = mock.MagicMock()
        tray_service._icon_generator.get_icon_path.return_value = "/tmp/clamui-tray-threat.png"
        tray_service._load_icon_pixmap = mock.MagicMock(return_value=mock.sentinel.pixmap)

        result = tray_service._get_icon_pixmap("threat")

        assert result is mock.sentinel.pixmap
        tray_service._icon_generator.get_icon_path.assert_called_once_with("threat")
        tray_service._load_icon_pixmap.assert_called_once_with("/tmp/clamui-tray-threat.png")


# =============================================================================
# TestAttentionIcon - branded AttentionIcon for NeedsAttention statuses
# =============================================================================


class TestAttentionIcon:
    """Tests for the AttentionIcon mirroring the branded status icon."""

    def test_attention_icon_name_uses_custom_icon_for_threat(self, tray_service):
        """When status=threat with custom icons, AttentionIconName mirrors the custom name."""
        tray_service._current_status = "threat"
        tray_service._using_custom_icons = True
        tray_service._icon_generator = mock.MagicMock()
        tray_service._icon_generator.get_icon_name.return_value = "clamui-tray-threat"

        assert tray_service._get_attention_icon_name() == "clamui-tray-threat"
        tray_service._icon_generator.get_icon_name.assert_called_with("threat")

    def test_attention_icon_name_uses_custom_icon_for_warning(self, tray_service):
        """When status=warning with custom icons, AttentionIconName uses warning icon, not threat."""
        tray_service._current_status = "warning"
        tray_service._using_custom_icons = True
        tray_service._icon_generator = mock.MagicMock()
        tray_service._icon_generator.get_icon_name.return_value = "clamui-tray-warning"

        assert tray_service._get_attention_icon_name() == "clamui-tray-warning"
        tray_service._icon_generator.get_icon_name.assert_called_with("warning")

    def test_attention_icon_name_falls_back_to_threat_theme_icon(self, tray_service):
        """Without custom icons, AttentionIconName uses the threat theme icon."""
        tray_service._current_status = "protected"
        tray_service._using_custom_icons = False
        tray_service._icon_generator = None

        # Maps to ICON_MAP["threat"] = "dialog-error-symbolic"
        assert tray_service._get_attention_icon_name() == "dialog-error-symbolic"

    def test_update_status_emits_new_attention_icon(self, tray_service):
        """update_status must signal NewAttentionIcon so hosts re-read the branded attention icon."""
        tray_service._emit_signal = mock.MagicMock()

        tray_service.update_status("threat")

        emitted_signals = [call.args[0] for call in tray_service._emit_signal.call_args_list]
        assert "NewAttentionIcon" in emitted_signals
        assert "NewIcon" in emitted_signals
        assert "NewStatus" in emitted_signals


# =============================================================================
# TestQuitExtended - extended quit behavior tests
# =============================================================================


class TestQuitExtended:
    """Extended tests for quit behavior."""

    def test_quit_releases_bus_name(self, tray_service):
        """Test _quit releases the D-Bus bus name."""
        tray_service._bus_name_id = 42

        with mock.patch("src.ui.tray_service.Gio") as mock_gio:
            tray_service._quit()
            mock_gio.bus_unown_name.assert_called_with(42)

    def test_quit_skips_bus_name_release_when_zero(self, tray_service):
        """Test _quit skips bus name release when ID is 0."""
        tray_service._bus_name_id = 0

        with mock.patch("src.ui.tray_service.Gio") as mock_gio:
            tray_service._quit()
            mock_gio.bus_unown_name.assert_not_called()

    def test_quit_skips_unregister_when_no_registration(self, tray_service):
        """Test _quit skips unregister when sni_registration_id is 0."""
        mock_bus = mock.MagicMock()
        tray_service._bus = mock_bus
        tray_service._sni_registration_id = 0

        tray_service._quit()

        mock_bus.unregister_object.assert_not_called()
