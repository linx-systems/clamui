# ClamUI Components View Tests
"""
Tests for the ComponentsView component.

Covers: initialization, background component checks, status updates for
installed/not-installed states, daemon status handling, Flatpak behaviour,
setup guide rendering, and copy-to-clipboard.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


def _clear_src_modules():
    """Clear all cached src.* modules to prevent test pollution."""
    modules_to_remove = [mod for mod in sys.modules if mod.startswith("src.")]
    for mod in modules_to_remove:
        del sys.modules[mod]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _import_view(mock_gi_modules):
    """Import ComponentsView and dependencies with mocks in place."""
    from src.core.log_manager import DaemonStatus
    from src.ui.components_view import SETUP_GUIDES, ComponentsView

    return ComponentsView, DaemonStatus, SETUP_GUIDES


def _create_view(ComponentsView):
    """Create a ComponentsView instance via object.__new__ and set core attributes."""
    view = object.__new__(ComponentsView)
    view._log_manager = MagicMock()
    view._is_checking = False
    view._destroyed = False
    view._component_rows = {}
    view._status_icons = {}
    view._status_labels = {}
    view._guide_rows = {}
    view._components_group = MagicMock()
    view._refresh_button = MagicMock()
    view._refresh_spinner = MagicMock()
    return view


def _populate_component_widgets(view, component_id):
    """Add mock widgets for a component, matching what _create_component_row does."""
    view._component_rows[component_id] = MagicMock()
    view._status_icons[component_id] = MagicMock()
    view._status_labels[component_id] = MagicMock()
    view._guide_rows[component_id] = MagicMock()


# ═════════════════════════════════════════════════════════════════════════════
# Test Classes
# ═════════════════════════════════════════════════════════════════════════════


class TestComponentsViewImport:
    """Test that the module imports correctly."""

    def test_import_module(self, mock_gi_modules):
        from src.ui.components_view import ComponentsView

        assert ComponentsView is not None
        _clear_src_modules()


class TestComponentsViewInit:
    """Test constructor initialises component storage dicts."""

    def test_creates_empty_component_dicts(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        assert view._component_rows == {}
        assert view._status_icons == {}
        assert view._status_labels == {}
        assert view._guide_rows == {}
        _clear_src_modules()

    def test_initial_state_flags(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        assert view._is_checking is False
        assert view._destroyed is False
        _clear_src_modules()

    def test_log_manager_integration(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        assert view._log_manager is not None
        _clear_src_modules()


class TestSetupGuides:
    """Test SETUP_GUIDES data structure."""

    def test_has_all_components(self, mock_gi_modules):
        SETUP_GUIDES = _import_view(mock_gi_modules)[2]

        assert "clamscan" in SETUP_GUIDES
        assert "freshclam" in SETUP_GUIDES
        assert "clamdscan" in SETUP_GUIDES
        assert "clamd" in SETUP_GUIDES
        _clear_src_modules()

    @pytest.mark.parametrize("component_id", ["clamscan", "freshclam", "clamdscan", "clamd"])
    def test_guide_has_required_keys(self, mock_gi_modules, component_id):
        SETUP_GUIDES = _import_view(mock_gi_modules)[2]
        guide = SETUP_GUIDES[component_id]

        assert "title" in guide
        assert "commands" in guide
        assert "notes" in guide
        _clear_src_modules()

    @pytest.mark.parametrize("component_id", ["clamscan", "freshclam", "clamdscan", "clamd"])
    def test_guide_commands_are_tuples(self, mock_gi_modules, component_id):
        SETUP_GUIDES = _import_view(mock_gi_modules)[2]
        guide = SETUP_GUIDES[component_id]

        for item in guide["commands"]:
            assert isinstance(item, tuple)
            assert len(item) == 2
            distro, command = item
            assert isinstance(distro, str)
            assert isinstance(command, str)
        _clear_src_modules()


class TestCheckComponents:
    """Test _check_all_components and _check_components_background."""

    def test_check_all_sets_checking_state(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            view._check_all_components()

        assert view._is_checking is True
        _clear_src_modules()

    def test_check_all_spawns_thread(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        with patch("threading.Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_thread.return_value = mock_instance
            view._check_all_components()

        mock_thread.assert_called_once()
        mock_instance.start.assert_called_once()
        _clear_src_modules()

    def test_check_all_returns_false_for_glib(self, mock_gi_modules):
        """GLib.idle_add expects False to not repeat."""
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        with patch("threading.Thread"):
            result = view._check_all_components()

        assert result is False
        _clear_src_modules()

    @patch("src.ui.components_view.check_freshclam_installed")
    @patch("src.ui.components_view.check_clamdscan_installed")
    @patch("src.ui.components_view.check_clamav_installed")
    def test_check_components_background_calls_all_checks(
        self, mock_clam, mock_clamdscan, mock_freshclam, mock_gi_modules
    ):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        mock_clam.return_value = (True, "ClamAV 1.0")
        mock_freshclam.return_value = (True, "freshclam 1.0")
        mock_clamdscan.return_value = (True, "clamdscan 1.0")
        view._log_manager.get_daemon_status.return_value = (DaemonStatus.RUNNING, "Running")

        view._check_components_background()

        mock_clam.assert_called_once()
        mock_freshclam.assert_called_once()
        mock_clamdscan.assert_called_once()
        view._log_manager.get_daemon_status.assert_called_once()
        _clear_src_modules()

    @patch("src.ui.components_view.check_freshclam_installed")
    @patch("src.ui.components_view.check_clamdscan_installed")
    @patch("src.ui.components_view.check_clamav_installed")
    def test_check_background_skips_when_destroyed(
        self, mock_clam, mock_clamdscan, mock_freshclam, mock_gi_modules
    ):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        view._destroyed = True

        view._check_components_background()

        mock_clam.assert_not_called()
        _clear_src_modules()

    @patch("src.ui.components_view.check_clamav_installed")
    def test_check_background_failure_still_schedules_ui_reset(self, mock_clam, mock_gi_modules):
        """A raising check must not strand the spinner.

        Without a try/finally the worker thread dies before scheduling the UI
        update, so _set_checking_state(False) never runs and the spinner spins
        forever. The UI reset must still be scheduled with whatever results
        were collected (here: none).
        """
        import src.ui.components_view as cv

        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        view._is_checking = True

        mock_clam.side_effect = RuntimeError("subprocess blew up")

        with patch.object(cv, "GLib") as mock_glib:
            # Must not propagate the exception out of the worker.
            view._check_components_background()
            # The main-thread UI update (which resets the checking state) is
            # still scheduled, with partial/empty results.
            mock_glib.idle_add.assert_called_once_with(view._update_components_ui, {})

        _clear_src_modules()


class TestSetCheckingState:
    """Test _set_checking_state UI updates."""

    def test_checking_true_disables_button(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        view._set_checking_state(True)

        assert view._is_checking is True
        view._refresh_button.set_sensitive.assert_called_with(False)
        view._refresh_spinner.set_visible.assert_called_with(True)
        view._refresh_spinner.start.assert_called_once()
        _clear_src_modules()

    def test_checking_false_enables_button(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        view._set_checking_state(False)

        assert view._is_checking is False
        view._refresh_button.set_sensitive.assert_called_with(True)
        view._refresh_spinner.stop.assert_called_once()
        view._refresh_spinner.set_visible.assert_called_with(False)
        _clear_src_modules()


class TestOnRefreshClicked:
    """Test _on_refresh_clicked handler."""

    def test_skips_when_already_checking(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        view._is_checking = True

        with patch("threading.Thread") as mock_thread:
            view._on_refresh_clicked(MagicMock())

        mock_thread.assert_not_called()
        _clear_src_modules()

    def test_starts_check_when_idle(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        view._is_checking = False

        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            view._on_refresh_clicked(MagicMock())

        mock_thread.assert_called_once()
        _clear_src_modules()


class TestUpdateComponentStatus:
    """Test _update_component_status for installed/not-installed states."""

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_installed_native(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamscan")

        view._update_component_status("clamscan", True, "ClamAV 1.0.0")

        view._status_labels["clamscan"].set_text.assert_called_with("Installed")
        view._component_rows["clamscan"].set_subtitle.assert_called_with("ClamAV 1.0.0")
        view._guide_rows["clamscan"].set_visible.assert_called_with(False)
        view._component_rows["clamscan"].set_enable_expansion.assert_called_with(False)
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_not_installed_native(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "freshclam")

        view._update_component_status("freshclam", False, "Not found")

        view._status_labels["freshclam"].set_text.assert_called_with("Not installed")
        view._guide_rows["freshclam"].set_visible.assert_called_with(True)
        view._component_rows["freshclam"].set_enable_expansion.assert_called_with(True)
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=True)
    def test_installed_flatpak_host_component(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamscan")

        view._update_component_status("clamscan", True, "ClamAV 1.0.0")

        view._status_labels["clamscan"].set_text.assert_called_with("Installed")
        view._component_rows["clamscan"].set_subtitle.assert_called_with("ClamAV 1.0.0")
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=True)
    def test_not_installed_flatpak_host_component_shows_setup(self, mock_flatpak, mock_gi_modules):
        """Flatpak host components that aren't found should show setup instructions."""
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamscan")

        view._update_component_status("clamscan", False, "Not found")

        view._status_labels["clamscan"].set_text.assert_called_with("Not installed")
        view._component_rows["clamscan"].set_enable_expansion.assert_called_with(True)
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=True)
    def test_non_bundled_in_flatpak_shows_normal_status(self, mock_flatpak, mock_gi_modules):
        """clamdscan is NOT bundled even in Flatpak; should show normal not-installed."""
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamdscan")

        view._update_component_status("clamdscan", False, "Not found")

        view._status_labels["clamdscan"].set_text.assert_called_with("Not installed")
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_installed_hides_guide_row(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamscan")

        view._update_component_status("clamscan", True, "v1.0")

        view._guide_rows["clamscan"].set_visible.assert_called_with(False)
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_installed_with_empty_message(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamscan")

        view._update_component_status("clamscan", True, "")

        # Should fallback to "Installed" text
        view._component_rows["clamscan"].set_subtitle.assert_called_with("Installed")
        _clear_src_modules()

    def test_missing_widgets_returns_early(self, mock_gi_modules):
        """If component widgets are not found, should not raise."""
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        # No widgets populated for "unknown_component"

        view._update_component_status("unknown_component", True, "v1.0")

        # Should not raise
        _clear_src_modules()


class TestDaemonStatus:
    """Test _update_daemon_status for all DaemonStatus values."""

    def test_running(self, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamd")

        view._update_daemon_status("clamd", DaemonStatus.RUNNING, "Daemon running")

        view._status_labels["clamd"].set_text.assert_called_with("Running")
        view._component_rows["clamd"].set_subtitle.assert_called_with("Daemon is running")
        view._guide_rows["clamd"].set_visible.assert_called_with(False)
        view._component_rows["clamd"].set_enable_expansion.assert_called_with(False)
        _clear_src_modules()

    def test_stopped(self, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamd")

        view._update_daemon_status("clamd", DaemonStatus.STOPPED, "Stopped")

        view._status_labels["clamd"].set_text.assert_called_with("Stopped")
        view._component_rows["clamd"].set_subtitle.assert_called_with(
            "Daemon is installed but not running"
        )
        view._guide_rows["clamd"].set_visible.assert_called_with(True)
        view._component_rows["clamd"].set_enable_expansion.assert_called_with(True)
        _clear_src_modules()

    def test_not_installed(self, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamd")

        view._update_daemon_status("clamd", DaemonStatus.NOT_INSTALLED, "Not found")

        view._status_labels["clamd"].set_text.assert_called_with("Not installed")
        view._component_rows["clamd"].set_subtitle.assert_called_with(
            "Not installed - expand for setup instructions"
        )
        view._guide_rows["clamd"].set_visible.assert_called_with(True)
        view._component_rows["clamd"].set_enable_expansion.assert_called_with(True)
        _clear_src_modules()

    def test_unknown(self, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamd")

        view._update_daemon_status("clamd", DaemonStatus.UNKNOWN, "Cannot determine status")

        view._status_labels["clamd"].set_text.assert_called_with("Unknown")
        view._component_rows["clamd"].set_subtitle.assert_called_with("Cannot determine status")
        view._guide_rows["clamd"].set_visible.assert_called_with(True)
        view._component_rows["clamd"].set_enable_expansion.assert_called_with(True)
        _clear_src_modules()

    def test_unknown_with_empty_message(self, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        _populate_component_widgets(view, "clamd")

        view._update_daemon_status("clamd", DaemonStatus.UNKNOWN, "")

        # Should fall back to default text
        view._component_rows["clamd"].set_subtitle.assert_called_with("Unable to determine status")
        _clear_src_modules()

    def test_missing_widgets_returns_early(self, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        # No widgets for "clamd"

        view._update_daemon_status("clamd", DaemonStatus.RUNNING, "Running")

        # Should not raise
        _clear_src_modules()


class TestUpdateComponentsUI:
    """Test _update_components_ui main thread callback."""

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_updates_all_components(self, mock_flatpak, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        for cid in ("clamscan", "freshclam", "clamdscan", "clamd"):
            _populate_component_widgets(view, cid)

        results = {
            "clamscan": (True, "ClamAV 1.0"),
            "freshclam": (True, "freshclam 1.0"),
            "clamdscan": (False, "Not found"),
            "clamd": (DaemonStatus.RUNNING.value, "Running"),
        }

        view._update_components_ui(results)

        assert view._is_checking is False
        view._status_labels["clamscan"].set_text.assert_called_with("Installed")
        view._status_labels["clamdscan"].set_text.assert_called_with("Not installed")
        view._status_labels["clamd"].set_text.assert_called_with("Running")
        _clear_src_modules()

    def test_skips_when_destroyed(self, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        view._destroyed = True

        result = view._update_components_ui({})

        assert result is False
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_returns_false_for_glib(self, mock_flatpak, mock_gi_modules):
        ComponentsView, DaemonStatus, _ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        for cid in ("clamscan", "freshclam", "clamdscan", "clamd"):
            _populate_component_widgets(view, cid)

        results = {
            "clamscan": (True, "v1"),
            "freshclam": (True, "v1"),
            "clamdscan": (True, "v1"),
            "clamd": (DaemonStatus.RUNNING.value, "Running"),
        }

        result = view._update_components_ui(results)

        assert result is False
        _clear_src_modules()


class TestFlatpakBehavior:
    """Test Flatpak-specific behaviour."""

    @patch("src.ui.components_view.is_flatpak", return_value=True)
    def test_add_setup_guide_flatpak_host_component(self, mock_flatpak, mock_gi_modules):
        """Flatpak host components should get install commands."""
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        expander = MagicMock()

        view._add_setup_guide(expander, "clamscan")

        # Should have added a guide row
        expander.add_row.assert_called_once()
        assert "clamscan" in view._guide_rows
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_add_setup_guide_native_component(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        expander = MagicMock()

        view._add_setup_guide(expander, "clamscan")

        expander.add_row.assert_called_once()
        assert "clamscan" in view._guide_rows
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_add_setup_guide_unknown_component(self, mock_flatpak, mock_gi_modules):
        """Unknown component_id should gracefully handle empty guide."""
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        expander = MagicMock()

        view._add_setup_guide(expander, "nonexistent")

        # Should still add a guide row (even if empty)
        expander.add_row.assert_called_once()
        _clear_src_modules()


class TestSetupGuideRendering:
    """Test _create_command_row and _add_setup_guide rendering."""

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_create_command_row_returns_widget(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        row = view._create_command_row("Ubuntu/Debian", "sudo apt install clamav")

        assert row is not None
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_create_command_row_multiline_command(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)

        row = view._create_command_row(
            "Ubuntu/Debian",
            "sudo apt install clamav-daemon\nsudo systemctl enable clamav-daemon",
        )

        assert row is not None
        _clear_src_modules()

    @pytest.mark.parametrize("component_id", ["clamscan", "freshclam", "clamdscan", "clamd"])
    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_setup_guide_renders_all_components(self, mock_flatpak, mock_gi_modules, component_id):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        expander = MagicMock()

        view._add_setup_guide(expander, component_id)

        expander.add_row.assert_called_once()
        _clear_src_modules()


class TestCopyButton:
    """Test _on_copy_clicked handler."""

    def test_copy_sets_clipboard(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        button = MagicMock()
        clipboard = MagicMock()
        button.get_clipboard.return_value = clipboard

        view._on_copy_clicked(button, "sudo apt install clamav")

        clipboard.set.assert_called_once_with("sudo apt install clamav")
        _clear_src_modules()

    def test_copy_changes_icon_for_feedback(self, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        button = MagicMock()
        button.get_clipboard.return_value = MagicMock()

        view._on_copy_clicked(button, "command")

        # Should change icon to checkmark
        button.set_icon_name.assert_called_once()
        _clear_src_modules()


class TestCreateComponentRow:
    """Test _create_component_row populates widget dicts."""

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_creates_and_stores_widgets(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        group = MagicMock()

        view._create_component_row(group, "clamscan", "Virus Scanner", "security-high-symbolic")

        assert "clamscan" in view._component_rows
        assert "clamscan" in view._status_icons
        assert "clamscan" in view._status_labels
        assert "clamscan" in view._guide_rows
        group.add.assert_called_once()
        _clear_src_modules()

    @patch("src.ui.components_view.is_flatpak", return_value=False)
    def test_creates_multiple_components(self, mock_flatpak, mock_gi_modules):
        ComponentsView, *_ = _import_view(mock_gi_modules)
        view = _create_view(ComponentsView)
        group = MagicMock()

        view._create_component_row(group, "clamscan", "Scanner", "icon1")
        view._create_component_row(group, "freshclam", "Updater", "icon2")

        assert "clamscan" in view._component_rows
        assert "freshclam" in view._component_rows
        assert group.add.call_count == 2
        _clear_src_modules()
