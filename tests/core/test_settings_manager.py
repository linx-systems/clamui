# ClamUI SettingsManager Tests
"""Unit tests for the SettingsManager class."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from src.core.settings_manager import SettingsManager


class TestSettingsManagerInit:
    """Tests for SettingsManager initialization."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_init_creates_settings_with_defaults(self, temp_config_dir):
        """Test that SettingsManager initializes with default settings."""
        manager = SettingsManager(config_dir=temp_config_dir)
        assert manager.get("notifications_enabled") is True

    def test_init_with_custom_config_dir(self, temp_config_dir):
        """Test SettingsManager uses custom config directory."""
        custom_dir = Path(temp_config_dir) / "custom"
        manager = SettingsManager(config_dir=custom_dir)
        assert manager._config_dir == custom_dir

    def test_init_with_default_directory(self, monkeypatch):
        """Test SettingsManager uses XDG_CONFIG_HOME by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("XDG_CONFIG_HOME", tmpdir)
            manager = SettingsManager()
            expected_path = Path(tmpdir) / "clamui"
            assert manager._config_dir == expected_path

    def test_init_with_default_xdg_fallback(self, monkeypatch):
        """Test SettingsManager falls back to ~/.config when XDG_CONFIG_HOME unset."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            # We can't easily test home directory without mocking
            # Just verify no crashes when XDG_CONFIG_HOME is unset
            with mock.patch.object(Path, "expanduser", return_value=Path(tmpdir)):
                manager = SettingsManager()
                assert manager._config_dir is not None

    def test_init_loads_existing_settings(self, temp_config_dir):
        """Test that SettingsManager loads existing settings from file."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text(json.dumps({"notifications_enabled": False}))

        manager = SettingsManager(config_dir=config_dir)
        assert manager.get("notifications_enabled") is False


class TestSettingsManagerSaveLoad:
    """Tests for SettingsManager save and load operations."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_save_creates_settings_file(self, settings_manager, temp_config_dir):
        """Test that save creates the settings file."""
        result = settings_manager.save()
        assert result is True
        settings_file = Path(temp_config_dir) / "settings.json"
        assert settings_file.exists()

    def test_save_creates_config_directory(self, temp_config_dir):
        """Test that save creates the config directory if it doesn't exist."""
        nested_dir = Path(temp_config_dir) / "nested" / "config"
        manager = SettingsManager(config_dir=nested_dir)
        result = manager.save()
        assert result is True
        assert nested_dir.exists()

    def test_save_writes_json_content(self, settings_manager, temp_config_dir):
        """Test that save writes valid JSON content."""
        settings_manager.set("notifications_enabled", False)
        settings_file = Path(temp_config_dir) / "settings.json"

        with open(settings_file, encoding="utf-8") as f:
            data = json.load(f)

        assert data["notifications_enabled"] is False

    def test_load_returns_defaults_when_file_missing(self, temp_config_dir):
        """Test that load returns defaults when settings file is missing."""
        manager = SettingsManager(config_dir=temp_config_dir)
        # Defaults should be loaded
        assert manager.get("notifications_enabled") is True

    def test_load_handles_corrupted_json(self, temp_config_dir):
        """Test that load handles corrupted JSON files gracefully."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("{ invalid json content }")

        manager = SettingsManager(config_dir=config_dir)
        # Should fall back to defaults
        assert manager.get("notifications_enabled") is True

    def test_load_handles_empty_file(self, temp_config_dir):
        """Test that load handles empty files gracefully."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("")

        manager = SettingsManager(config_dir=config_dir)
        # Should fall back to defaults
        assert manager.get("notifications_enabled") is True

    def test_load_merges_with_defaults(self, temp_config_dir):
        """Test that load merges existing settings with defaults."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        # Write a partial settings file (missing notifications_enabled)
        settings_file.write_text(json.dumps({"custom_setting": "value"}))

        manager = SettingsManager(config_dir=config_dir)
        # Default should still be present
        assert manager.get("notifications_enabled") is True
        # Custom setting should also be present
        assert manager.get("custom_setting") == "value"

    def test_settings_persist_across_instances(self, temp_config_dir):
        """Test that settings persist across manager instances."""
        manager1 = SettingsManager(config_dir=temp_config_dir)
        manager1.set("notifications_enabled", False)

        manager2 = SettingsManager(config_dir=temp_config_dir)
        assert manager2.get("notifications_enabled") is False


class TestSettingsManagerGetSet:
    """Tests for SettingsManager get and set operations."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_get_returns_default_setting(self, settings_manager):
        """Test get returns default settings."""
        assert settings_manager.get("notifications_enabled") is True

    def test_get_returns_custom_default_for_missing_key(self, settings_manager):
        """Test get returns custom default for missing keys."""
        result = settings_manager.get("nonexistent_key", "custom_default")
        assert result == "custom_default"

    def test_get_returns_none_for_missing_key_without_default(self, settings_manager):
        """Test get returns None for missing keys when no default provided."""
        result = settings_manager.get("nonexistent_key")
        assert result is None

    def test_set_updates_value(self, settings_manager):
        """Test set updates the setting value."""
        settings_manager.set("notifications_enabled", False)
        assert settings_manager.get("notifications_enabled") is False

    def test_set_returns_save_result(self, settings_manager):
        """Test set returns the result of save operation."""
        result = settings_manager.set("notifications_enabled", False)
        assert result is True

    def test_set_creates_new_settings(self, settings_manager):
        """Test set can create new setting keys."""
        settings_manager.set("new_setting", "new_value")
        assert settings_manager.get("new_setting") == "new_value"

    def test_set_handles_different_value_types(self, settings_manager):
        """Test set handles various value types correctly."""
        # String
        settings_manager.set("string_setting", "hello")
        assert settings_manager.get("string_setting") == "hello"

        # Integer
        settings_manager.set("int_setting", 42)
        assert settings_manager.get("int_setting") == 42

        # Float
        settings_manager.set("float_setting", 3.14)
        assert settings_manager.get("float_setting") == 3.14

        # Boolean
        settings_manager.set("bool_setting", True)
        assert settings_manager.get("bool_setting") is True

        # List
        settings_manager.set("list_setting", [1, 2, 3])
        assert settings_manager.get("list_setting") == [1, 2, 3]

        # Dictionary
        settings_manager.set("dict_setting", {"key": "value"})
        assert settings_manager.get("dict_setting") == {"key": "value"}

    def test_set_persists_to_file(self, settings_manager, temp_config_dir):
        """Test that set persists changes to file."""
        settings_manager.set("test_key", "test_value")

        # Read directly from file
        settings_file = Path(temp_config_dir) / "settings.json"
        with open(settings_file, encoding="utf-8") as f:
            data = json.load(f)

        assert data["test_key"] == "test_value"


class TestSettingsManagerResetAndGetAll:
    """Tests for SettingsManager reset_to_defaults and get_all methods."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_reset_to_defaults_clears_custom_settings(self, settings_manager):
        """Test that reset_to_defaults removes custom settings."""
        settings_manager.set("custom_setting", "custom_value")
        settings_manager.reset_to_defaults()

        assert settings_manager.get("custom_setting") is None

    def test_reset_to_defaults_restores_default_values(self, settings_manager):
        """Test that reset_to_defaults restores default values."""
        settings_manager.set("notifications_enabled", False)
        settings_manager.reset_to_defaults()

        assert settings_manager.get("notifications_enabled") is True

    def test_reset_to_defaults_returns_save_result(self, settings_manager):
        """Test that reset_to_defaults returns the save result."""
        result = settings_manager.reset_to_defaults()
        assert result is True

    def test_reset_to_defaults_persists_to_file(self, settings_manager, temp_config_dir):
        """Test that reset_to_defaults persists changes to file."""
        settings_manager.set("custom_setting", "custom_value")
        settings_manager.reset_to_defaults()

        # Create a new instance to verify persistence
        new_manager = SettingsManager(config_dir=temp_config_dir)
        assert new_manager.get("custom_setting") is None
        assert new_manager.get("notifications_enabled") is True

    def test_get_all_returns_copy(self, settings_manager):
        """Test that get_all returns a copy of settings."""
        all_settings = settings_manager.get_all()
        # Modify the returned dict
        all_settings["notifications_enabled"] = False
        # Original should be unchanged
        assert settings_manager.get("notifications_enabled") is True

    def test_get_all_contains_all_settings(self, settings_manager):
        """Test that get_all contains all current settings."""
        settings_manager.set("custom_key", "custom_value")
        all_settings = settings_manager.get_all()

        assert "notifications_enabled" in all_settings
        assert "custom_key" in all_settings
        assert all_settings["custom_key"] == "custom_value"


class TestSettingsManagerListeners:
    """Tests for keyed settings change listeners."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_add_listener_notified_on_set(self, settings_manager):
        """Test listeners receive the new value when a setting changes."""
        callback = mock.MagicMock()
        settings_manager.add_listener("scan_backend", callback)

        settings_manager.set("scan_backend", "daemon")

        callback.assert_called_once_with("daemon")

    def test_remove_listener_stops_notifications(self, settings_manager):
        """Test removed listeners no longer receive setting updates."""
        callback = mock.MagicMock()
        settings_manager.add_listener("scan_backend", callback)
        settings_manager.remove_listener("scan_backend", callback)

        settings_manager.set("scan_backend", "daemon")

        callback.assert_not_called()

    def test_reset_to_defaults_notifies_changed_keys(self, settings_manager):
        """Test listeners are notified when reset changes an observed key."""
        callback = mock.MagicMock()
        settings_manager.add_listener("scan_backend", callback)
        settings_manager.set("scan_backend", "daemon")
        callback.reset_mock()

        settings_manager.reset_to_defaults()

        callback.assert_called_once_with("auto")


class TestSettingsManagerErrorHandling:
    """Tests for SettingsManager error handling."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_save_handles_permission_error(self, temp_config_dir):
        """Test that save handles permission errors gracefully."""
        manager = SettingsManager(config_dir=temp_config_dir)

        with mock.patch("os.fdopen", side_effect=PermissionError):
            result = manager.save()
            assert result is False

    def test_save_handles_os_error(self, temp_config_dir):
        """Test that save handles OS errors gracefully."""
        manager = SettingsManager(config_dir=temp_config_dir)

        with mock.patch("os.fdopen", side_effect=OSError("Test error")):
            result = manager.save()
            assert result is False

    def test_set_returns_false_on_save_failure(self, temp_config_dir):
        """Test that set returns False when save fails."""
        manager = SettingsManager(config_dir=temp_config_dir)

        with mock.patch.object(manager, "save", return_value=False):
            result = manager.set("key", "value")
            assert result is False

    def test_load_handles_permission_error_on_read(self, temp_config_dir):
        """Test that load handles permission errors when reading file."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text(json.dumps({"notifications_enabled": False}))

        with mock.patch("builtins.open", side_effect=PermissionError):
            manager = SettingsManager(config_dir=config_dir)
            # Should fall back to defaults
            assert manager.get("notifications_enabled") is True


class TestSettingsManagerThreadSafety:
    """Tests for thread safety in SettingsManager."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_concurrent_get_operations(self, settings_manager):
        """Test that concurrent get operations are thread-safe."""
        import threading

        results = []
        errors = []

        def get_setting(index):
            try:
                value = settings_manager.get("notifications_enabled")
                results.append((index, value))
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(20):
            t = threading.Thread(target=get_setting, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20
        # All results should be True (the default)
        for _, value in results:
            assert value is True

    def test_concurrent_set_operations(self, settings_manager):
        """Test that concurrent set operations are thread-safe."""
        import threading

        errors = []

        def set_setting(index):
            try:
                # Alternate between True and False
                value = index % 2 == 0
                settings_manager.set(f"concurrent_key_{index}", value)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(20):
            t = threading.Thread(target=set_setting, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0

        # Verify all values were set correctly
        for i in range(20):
            expected = i % 2 == 0
            assert settings_manager.get(f"concurrent_key_{i}") == expected

    def test_concurrent_read_write_operations(self, settings_manager):
        """Test that concurrent read and write operations don't corrupt data."""
        import threading

        errors = []
        read_results = []

        def write_setting(index):
            try:
                settings_manager.set("shared_key", f"value_{index}")
            except Exception as e:
                errors.append(f"Write error: {e}")

        def read_setting(index):
            try:
                value = settings_manager.get("shared_key")
                read_results.append(value)
            except Exception as e:
                errors.append(f"Read error: {e}")

        threads = []
        for i in range(10):
            t = threading.Thread(target=write_setting, args=(i,))
            threads.append(t)
            t = threading.Thread(target=read_setting, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        # All read values should be either None (not yet set) or a valid value
        for value in read_results:
            assert value is None or value.startswith("value_")


class TestSettingsManagerDefaults:
    """Tests for SettingsManager DEFAULT_SETTINGS."""

    def test_default_settings_has_notifications_enabled(self):
        """Test that DEFAULT_SETTINGS contains notifications_enabled."""
        assert "notifications_enabled" in SettingsManager.DEFAULT_SETTINGS
        assert SettingsManager.DEFAULT_SETTINGS["notifications_enabled"] is True

    def test_default_settings_has_close_behavior(self):
        """Test that DEFAULT_SETTINGS contains close_behavior."""
        assert "close_behavior" in SettingsManager.DEFAULT_SETTINGS
        assert SettingsManager.DEFAULT_SETTINGS["close_behavior"] is None

    def test_default_settings_has_clamd_conf_path(self):
        """Test that DEFAULT_SETTINGS contains clamd_conf_path."""
        assert "clamd_conf_path" in SettingsManager.DEFAULT_SETTINGS
        assert SettingsManager.DEFAULT_SETTINGS["clamd_conf_path"] == ""

    def test_default_settings_has_freshclam_conf_path(self):
        """Test that DEFAULT_SETTINGS contains freshclam_conf_path."""
        assert "freshclam_conf_path" in SettingsManager.DEFAULT_SETTINGS
        assert SettingsManager.DEFAULT_SETTINGS["freshclam_conf_path"] == ""

    def test_default_settings_is_not_modified(self):
        """Test that DEFAULT_SETTINGS is not modified by operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_defaults = dict(SettingsManager.DEFAULT_SETTINGS)
            manager = SettingsManager(config_dir=tmpdir)
            manager.set("notifications_enabled", False)
            manager.set("new_key", "new_value")

            # DEFAULT_SETTINGS should be unchanged
            assert original_defaults == SettingsManager.DEFAULT_SETTINGS

    def test_mutable_default_not_shared_between_instances(self):
        """Mutating a mutable default on one instance must not pollute the class default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager1 = SettingsManager(config_dir=tmpdir)
            # exclusion_patterns is absent on disk -> served from defaults.
            patterns = manager1.get("exclusion_patterns")
            patterns.append({"pattern": "/tmp/evil"})

            # Class-level default must remain unpolluted.
            assert SettingsManager.DEFAULT_SETTINGS["exclusion_patterns"] == []

            # A second manager and reset must both yield the clean default.
            with tempfile.TemporaryDirectory() as tmpdir2:
                manager2 = SettingsManager(config_dir=tmpdir2)
                assert manager2.get("exclusion_patterns") == []

            manager1.reset_to_defaults()
            assert manager1.get("exclusion_patterns") == []


class TestSettingsCloseBehavior:
    """Tests for close_behavior settings."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_close_behavior_default_is_none(self, settings_manager):
        """Test that close_behavior defaults to None (first-run state)."""
        assert settings_manager.get("close_behavior") is None

    def test_close_behavior_set_minimize(self, settings_manager):
        """Test setting close_behavior to 'minimize'."""
        settings_manager.set("close_behavior", "minimize")
        assert settings_manager.get("close_behavior") == "minimize"

    def test_close_behavior_set_quit(self, settings_manager):
        """Test setting close_behavior to 'quit'."""
        settings_manager.set("close_behavior", "quit")
        assert settings_manager.get("close_behavior") == "quit"

    def test_close_behavior_set_ask(self, settings_manager):
        """Test setting close_behavior to 'ask'."""
        settings_manager.set("close_behavior", "ask")
        assert settings_manager.get("close_behavior") == "ask"

    def test_close_behavior_persists_across_instances(self, temp_config_dir):
        """Test that close_behavior persists across manager instances."""
        manager1 = SettingsManager(config_dir=temp_config_dir)
        manager1.set("close_behavior", "minimize")

        manager2 = SettingsManager(config_dir=temp_config_dir)
        assert manager2.get("close_behavior") == "minimize"

    def test_close_behavior_reset_to_defaults(self, settings_manager):
        """Test that reset_to_defaults resets close_behavior to None."""
        settings_manager.set("close_behavior", "quit")
        settings_manager.reset_to_defaults()
        assert settings_manager.get("close_behavior") is None

    def test_close_behavior_in_get_all(self, settings_manager):
        """Test that close_behavior appears in get_all output."""
        settings_manager.set("close_behavior", "ask")
        all_settings = settings_manager.get_all()
        assert "close_behavior" in all_settings
        assert all_settings["close_behavior"] == "ask"


class TestSettingsExclusions:
    """Tests for exclusion_patterns settings persistence."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_default_exclusion_patterns_is_empty_list(self, settings_manager):
        """Test that default exclusion_patterns is an empty list."""
        patterns = settings_manager.get("exclusion_patterns")
        assert patterns == []
        assert isinstance(patterns, list)

    def test_default_settings_has_exclusion_patterns(self):
        """Test that DEFAULT_SETTINGS contains exclusion_patterns."""
        assert "exclusion_patterns" in SettingsManager.DEFAULT_SETTINGS
        assert SettingsManager.DEFAULT_SETTINGS["exclusion_patterns"] == []

    def test_set_exclusion_patterns_single_pattern(self, settings_manager):
        """Test setting a single exclusion pattern."""
        pattern = {"pattern": "*.log", "type": "pattern", "enabled": True}
        settings_manager.set("exclusion_patterns", [pattern])

        patterns = settings_manager.get("exclusion_patterns")
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "*.log"
        assert patterns[0]["type"] == "pattern"
        assert patterns[0]["enabled"] is True

    def test_set_exclusion_patterns_multiple_patterns(self, settings_manager):
        """Test setting multiple exclusion patterns."""
        patterns = [
            {"pattern": "node_modules", "type": "directory", "enabled": True},
            {"pattern": ".git", "type": "directory", "enabled": True},
            {"pattern": "*.log", "type": "pattern", "enabled": False},
        ]
        settings_manager.set("exclusion_patterns", patterns)

        retrieved = settings_manager.get("exclusion_patterns")
        assert len(retrieved) == 3
        assert retrieved[0]["pattern"] == "node_modules"
        assert retrieved[1]["pattern"] == ".git"
        assert retrieved[2]["pattern"] == "*.log"
        assert retrieved[2]["enabled"] is False

    def test_exclusion_patterns_persist_to_file(self, settings_manager, temp_config_dir):
        """Test that exclusion patterns persist to the settings file."""
        patterns = [
            {"pattern": "*.tmp", "type": "file", "enabled": True},
            {"pattern": "__pycache__", "type": "directory", "enabled": True},
        ]
        settings_manager.set("exclusion_patterns", patterns)

        # Read directly from file
        settings_file = Path(temp_config_dir) / "settings.json"
        with open(settings_file, encoding="utf-8") as f:
            data = json.load(f)

        assert "exclusion_patterns" in data
        assert len(data["exclusion_patterns"]) == 2
        assert data["exclusion_patterns"][0]["pattern"] == "*.tmp"
        assert data["exclusion_patterns"][1]["pattern"] == "__pycache__"

    def test_exclusion_patterns_persist_across_instances(self, temp_config_dir):
        """Test that exclusion patterns persist across manager instances."""
        patterns = [
            {"pattern": ".venv", "type": "directory", "enabled": True},
            {"pattern": "build", "type": "directory", "enabled": False},
        ]

        manager1 = SettingsManager(config_dir=temp_config_dir)
        manager1.set("exclusion_patterns", patterns)

        manager2 = SettingsManager(config_dir=temp_config_dir)
        retrieved = manager2.get("exclusion_patterns")

        assert len(retrieved) == 2
        assert retrieved[0]["pattern"] == ".venv"
        assert retrieved[0]["enabled"] is True
        assert retrieved[1]["pattern"] == "build"
        assert retrieved[1]["enabled"] is False

    def test_exclusion_patterns_load_from_existing_file(self, temp_config_dir):
        """Test loading exclusion patterns from an existing settings file."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"

        existing_data = {
            "notifications_enabled": True,
            "exclusion_patterns": [{"pattern": "dist", "type": "directory", "enabled": True}],
        }
        settings_file.write_text(json.dumps(existing_data))

        manager = SettingsManager(config_dir=config_dir)
        patterns = manager.get("exclusion_patterns")

        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "dist"

    def test_exclusion_patterns_empty_list_after_clear(self, settings_manager):
        """Test clearing exclusion patterns to an empty list."""
        patterns = [{"pattern": "*.log", "type": "pattern", "enabled": True}]
        settings_manager.set("exclusion_patterns", patterns)

        # Clear patterns
        settings_manager.set("exclusion_patterns", [])
        retrieved = settings_manager.get("exclusion_patterns")

        assert retrieved == []

    def test_exclusion_patterns_all_types(self, settings_manager):
        """Test all three exclusion pattern types."""
        patterns = [
            {"pattern": "/path/to/file.txt", "type": "file", "enabled": True},
            {"pattern": "node_modules", "type": "directory", "enabled": True},
            {"pattern": "*.log", "type": "pattern", "enabled": True},
        ]
        settings_manager.set("exclusion_patterns", patterns)

        retrieved = settings_manager.get("exclusion_patterns")
        assert retrieved[0]["type"] == "file"
        assert retrieved[1]["type"] == "directory"
        assert retrieved[2]["type"] == "pattern"

    def test_exclusion_patterns_enabled_toggle(self, settings_manager):
        """Test toggling enabled state of exclusion patterns."""
        patterns = [{"pattern": "*.log", "type": "pattern", "enabled": True}]
        settings_manager.set("exclusion_patterns", patterns)

        # Toggle to disabled
        patterns[0]["enabled"] = False
        settings_manager.set("exclusion_patterns", patterns)

        retrieved = settings_manager.get("exclusion_patterns")
        assert retrieved[0]["enabled"] is False

        # Toggle back to enabled
        patterns[0]["enabled"] = True
        settings_manager.set("exclusion_patterns", patterns)

        retrieved = settings_manager.get("exclusion_patterns")
        assert retrieved[0]["enabled"] is True

    def test_exclusion_patterns_reset_to_defaults(self, settings_manager):
        """Test that reset_to_defaults clears exclusion patterns."""
        patterns = [{"pattern": "*.log", "type": "pattern", "enabled": True}]
        settings_manager.set("exclusion_patterns", patterns)

        settings_manager.reset_to_defaults()

        retrieved = settings_manager.get("exclusion_patterns")
        assert retrieved == []

    def test_exclusion_patterns_in_get_all(self, settings_manager):
        """Test that exclusion_patterns appears in get_all output."""
        patterns = [{"pattern": "*.tmp", "type": "file", "enabled": True}]
        settings_manager.set("exclusion_patterns", patterns)

        all_settings = settings_manager.get_all()

        assert "exclusion_patterns" in all_settings
        assert len(all_settings["exclusion_patterns"]) == 1
        assert all_settings["exclusion_patterns"][0]["pattern"] == "*.tmp"

    def test_exclusion_patterns_merge_with_defaults(self, temp_config_dir):
        """Test that exclusion_patterns merges correctly when file has partial settings."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"

        # Write settings without exclusion_patterns
        settings_file.write_text(json.dumps({"notifications_enabled": False}))

        manager = SettingsManager(config_dir=config_dir)

        # Should get default empty list
        assert manager.get("exclusion_patterns") == []
        # Other settings should be from file
        assert manager.get("notifications_enabled") is False

    def test_exclusion_patterns_special_characters(self, settings_manager):
        """Test exclusion patterns with special characters."""
        patterns = [
            {"pattern": "path with spaces", "type": "directory", "enabled": True},
            {"pattern": "file[1-9].txt", "type": "pattern", "enabled": True},
            {"pattern": "special_chars!@#", "type": "file", "enabled": True},
        ]
        settings_manager.set("exclusion_patterns", patterns)

        retrieved = settings_manager.get("exclusion_patterns")
        assert retrieved[0]["pattern"] == "path with spaces"
        assert retrieved[1]["pattern"] == "file[1-9].txt"
        assert retrieved[2]["pattern"] == "special_chars!@#"

    def test_exclusion_patterns_preset_development_directories(self, settings_manager):
        """Test saving common development directory exclusion presets."""
        preset_patterns = [
            {"pattern": "node_modules", "type": "directory", "enabled": True},
            {"pattern": ".git", "type": "directory", "enabled": True},
            {"pattern": ".venv", "type": "directory", "enabled": True},
            {"pattern": "build", "type": "directory", "enabled": True},
            {"pattern": "dist", "type": "directory", "enabled": True},
            {"pattern": "__pycache__", "type": "directory", "enabled": True},
        ]
        settings_manager.set("exclusion_patterns", preset_patterns)

        retrieved = settings_manager.get("exclusion_patterns")
        assert len(retrieved) == 6
        pattern_names = [p["pattern"] for p in retrieved]
        assert "node_modules" in pattern_names
        assert ".git" in pattern_names
        assert ".venv" in pattern_names
        assert "__pycache__" in pattern_names


class TestSettingsManagerLoadEdgeCases:
    """Edge case tests for SettingsManager load operations."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_load_handles_non_dict_json(self, temp_config_dir):
        """Test that load handles JSON file containing non-dict data gracefully.

        Non-dict JSON (arrays, primitives) is treated as corrupted and backed up,
        with defaults returned instead of raising TypeError.
        """
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        # Write a JSON array instead of dict
        settings_file.write_text('["item1", "item2"]')

        # Should handle gracefully by backing up and returning defaults
        manager = SettingsManager(config_dir=config_dir)
        assert manager.get("notifications_enabled") is True

        # Verify backup was created
        backup_path = config_dir / "settings.json.corrupted"
        assert backup_path.exists()
        assert backup_path.read_text() == '["item1", "item2"]'

    def test_load_handles_null_json(self, temp_config_dir):
        """Test that load handles JSON file containing null gracefully.

        Null JSON is treated as corrupted and backed up, with defaults returned
        instead of raising TypeError.
        """
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("null")

        # Should handle gracefully by backing up and returning defaults
        manager = SettingsManager(config_dir=config_dir)
        assert manager.get("notifications_enabled") is True

        # Verify backup was created
        backup_path = config_dir / "settings.json.corrupted"
        assert backup_path.exists()
        assert backup_path.read_text() == "null"

    def test_load_handles_json_with_unicode(self, temp_config_dir):
        """Test that load handles JSON with unicode characters."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text(
            json.dumps({"notifications_enabled": True, "unicode_setting": "文字テスト 🎉"})
        )

        manager = SettingsManager(config_dir=config_dir)
        assert manager.get("unicode_setting") == "文字テスト 🎉"

    def test_load_handles_very_large_file(self, temp_config_dir):
        """Test that load handles a large settings file."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"

        # Create a settings dict with many keys
        large_settings = {"notifications_enabled": False}
        for i in range(1000):
            large_settings[f"setting_{i}"] = f"value_{i}"

        settings_file.write_text(json.dumps(large_settings))

        manager = SettingsManager(config_dir=config_dir)
        assert manager.get("notifications_enabled") is False
        assert manager.get("setting_500") == "value_500"

    def test_load_handles_deeply_nested_json(self, temp_config_dir):
        """Test that load handles deeply nested JSON structures."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"

        nested_value = {"level": 1}
        current = nested_value
        for i in range(2, 20):
            current["nested"] = {"level": i}
            current = current["nested"]

        settings_file.write_text(
            json.dumps({"notifications_enabled": True, "deeply_nested": nested_value})
        )

        manager = SettingsManager(config_dir=config_dir)
        assert manager.get("deeply_nested") is not None
        assert manager.get("deeply_nested")["level"] == 1


class TestSettingsManagerSaveEdgeCases:
    """Edge case tests for SettingsManager save operations."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_save_handles_mkdir_permission_error(self, temp_config_dir):
        """Test that save handles permission error when creating directory."""
        manager = SettingsManager(config_dir=temp_config_dir)

        with mock.patch.object(
            Path, "mkdir", side_effect=PermissionError("Cannot create directory")
        ):
            result = manager.save()
            assert result is False

    def test_save_handles_mkdir_oserror(self, temp_config_dir):
        """Test that save handles OSError when creating directory."""
        manager = SettingsManager(config_dir=temp_config_dir)

        with mock.patch.object(Path, "mkdir", side_effect=OSError("Disk full")):
            result = manager.save()
            assert result is False

    def test_save_handles_json_serialization_error(self, temp_config_dir):
        """Test that save handles non-serializable values gracefully.

        The implementation catches all exceptions (including TypeError from
        json.dump) and returns False rather than propagating the error.
        """
        manager = SettingsManager(config_dir=temp_config_dir)

        # Set a value that can't be JSON serialized
        with manager._lock:
            manager._settings["bad_value"] = object()

        # Implementation catches TypeError and returns False
        result = manager.save()
        assert result is False

    def test_save_handles_unicode_values(self, temp_config_dir):
        """Test that save correctly handles unicode values."""
        manager = SettingsManager(config_dir=temp_config_dir)
        manager.set("unicode_key", "Привет мир 🌍")

        # Reload and verify
        manager2 = SettingsManager(config_dir=temp_config_dir)
        assert manager2.get("unicode_key") == "Привет мир 🌍"

    def test_save_creates_parent_directories(self, temp_config_dir):
        """Test that save creates parent directories if they don't exist."""
        nested_dir = Path(temp_config_dir) / "deep" / "nested" / "config"
        manager = SettingsManager(config_dir=nested_dir)
        result = manager.save()

        assert result is True
        assert nested_dir.exists()
        assert (nested_dir / "settings.json").exists()


class TestSettingsManagerScheduledScanEdgeCases:
    """Edge case tests for scheduled scan settings."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_schedule_frequency_edge_values(self, settings_manager):
        """Test setting various schedule frequency values."""
        valid_frequencies = ["daily", "weekly", "monthly"]
        for freq in valid_frequencies:
            settings_manager.set("schedule_frequency", freq)
            assert settings_manager.get("schedule_frequency") == freq

    def test_schedule_time_edge_values(self, settings_manager):
        """Test setting edge case time values."""
        edge_times = ["00:00", "23:59", "12:00", "06:30"]
        for time_val in edge_times:
            settings_manager.set("schedule_time", time_val)
            assert settings_manager.get("schedule_time") == time_val

    def test_schedule_day_of_week_edge_values(self, settings_manager):
        """Test setting edge case day of week values."""
        # Valid range is 0-6
        for day in range(7):
            settings_manager.set("schedule_day_of_week", day)
            assert settings_manager.get("schedule_day_of_week") == day

    def test_schedule_day_of_month_edge_values(self, settings_manager):
        """Test setting edge case day of month values."""
        # Valid range is 1-28
        for day in [1, 15, 28]:
            settings_manager.set("schedule_day_of_month", day)
            assert settings_manager.get("schedule_day_of_month") == day

    def test_schedule_targets_empty_list(self, settings_manager):
        """Test that schedule_targets defaults to empty list."""
        assert settings_manager.get("schedule_targets") == []

    def test_schedule_targets_with_paths(self, settings_manager):
        """Test setting schedule_targets with multiple paths."""
        targets = ["/home/user/Documents", "/home/user/Downloads"]
        settings_manager.set("schedule_targets", targets)
        assert settings_manager.get("schedule_targets") == targets

    def test_schedule_boolean_settings(self, settings_manager):
        """Test scheduled scan boolean settings."""
        assert settings_manager.get("scheduled_scans_enabled") is False
        assert settings_manager.get("schedule_skip_on_battery") is True
        assert settings_manager.get("schedule_auto_quarantine") is False

        settings_manager.set("scheduled_scans_enabled", True)
        settings_manager.set("schedule_skip_on_battery", False)
        settings_manager.set("schedule_auto_quarantine", True)

        assert settings_manager.get("scheduled_scans_enabled") is True
        assert settings_manager.get("schedule_skip_on_battery") is False
        assert settings_manager.get("schedule_auto_quarantine") is True


class TestSettingsManagerQuarantineEdgeCases:
    """Edge case tests for quarantine settings."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_quarantine_directory_default_empty(self, settings_manager):
        """Test that quarantine_directory defaults to empty string."""
        assert settings_manager.get("quarantine_directory") == ""

    def test_quarantine_directory_custom_path(self, settings_manager):
        """Test setting custom quarantine directory."""
        custom_path = "/custom/quarantine/path"
        settings_manager.set("quarantine_directory", custom_path)
        assert settings_manager.get("quarantine_directory") == custom_path

    def test_quarantine_directory_with_spaces(self, settings_manager):
        """Test quarantine directory with spaces in path."""
        path_with_spaces = "/home/user/My Quarantine Folder"
        settings_manager.set("quarantine_directory", path_with_spaces)
        assert settings_manager.get("quarantine_directory") == path_with_spaces


class TestSettingsManagerMalformedExclusionEdgeCases:
    """Edge case tests for handling malformed exclusion patterns."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_load_exclusions_with_missing_keys(self, temp_config_dir):
        """Test loading exclusion patterns with missing required keys."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"

        # Write exclusions with various missing keys
        settings_file.write_text(
            json.dumps(
                {
                    "exclusion_patterns": [
                        {"pattern": "*.log"},  # Missing type and enabled
                        {"type": "file", "enabled": True},  # Missing pattern
                        {
                            "pattern": "",
                            "type": "file",
                            "enabled": True,
                        },  # Empty pattern
                    ]
                }
            )
        )

        manager = SettingsManager(config_dir=config_dir)
        patterns = manager.get("exclusion_patterns")

        # Should load all patterns (validation is done elsewhere)
        assert len(patterns) == 3

    def test_load_exclusions_with_wrong_types(self, temp_config_dir):
        """Test loading exclusion patterns with wrong value types."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"

        # Write exclusions with wrong types
        settings_file.write_text(
            json.dumps(
                {
                    "exclusion_patterns": [
                        {
                            "pattern": 123,
                            "type": "file",
                            "enabled": True,
                        },  # pattern should be string
                        {
                            "pattern": "*.log",
                            "type": 456,
                            "enabled": True,
                        },  # type should be string
                        {
                            "pattern": "*.tmp",
                            "type": "file",
                            "enabled": "yes",
                        },  # enabled should be bool
                    ]
                }
            )
        )

        manager = SettingsManager(config_dir=config_dir)
        patterns = manager.get("exclusion_patterns")

        # Should load all patterns (type checking is not done in SettingsManager)
        assert len(patterns) == 3

    def test_exclusion_patterns_not_a_list(self, temp_config_dir):
        """Test loading when exclusion_patterns is not a list."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"

        # Write exclusion_patterns as a dict instead of list
        settings_file.write_text(
            json.dumps({"exclusion_patterns": {"pattern": "*.log", "enabled": True}})
        )

        manager = SettingsManager(config_dir=config_dir)
        patterns = manager.get("exclusion_patterns")

        # Should load the value as-is (validation happens elsewhere)
        assert isinstance(patterns, dict)

    def test_exclusion_patterns_null_value(self, temp_config_dir):
        """Test loading when exclusion_patterns is null."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"

        settings_file.write_text(
            json.dumps({"notifications_enabled": True, "exclusion_patterns": None})
        )

        manager = SettingsManager(config_dir=config_dir)
        patterns = manager.get("exclusion_patterns")

        # Should return None (the stored value)
        assert patterns is None


class TestSettingsManagerAtomicWrite:
    """Tests for atomic write behavior in SettingsManager."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def settings_manager(self, temp_config_dir):
        """Create a SettingsManager with a temporary directory."""
        return SettingsManager(config_dir=temp_config_dir)

    def test_save_uses_atomic_write(self, settings_manager):
        """Test that save uses atomic write pattern (temp file + rename)."""
        with (
            mock.patch("tempfile.mkstemp") as mock_mkstemp,
            mock.patch("os.fdopen") as mock_fdopen,
            mock.patch.object(Path, "replace") as mock_replace,
            mock.patch.object(Path, "chmod") as mock_chmod,
            mock.patch.object(Path, "mkdir"),
        ):
            # Setup mocks
            mock_mkstemp.return_value = (1, "/tmp/settings_test.json")
            mock_file = mock.MagicMock()
            mock_file.__enter__ = mock.MagicMock(return_value=mock_file)
            mock_file.__exit__ = mock.MagicMock(return_value=False)
            mock_fdopen.return_value = mock_file

            # Perform save
            result = settings_manager.save()

            # Verify atomic write pattern was used
            assert result is True
            mock_mkstemp.assert_called_once()
            mock_fdopen.assert_called_once()
            mock_replace.assert_called_once()
            # Verify file permissions are hardened (owner read/write only)
            mock_chmod.assert_called_once_with(0o600)

    def test_save_cleans_up_temp_file_on_failure(self, temp_config_dir):
        """Test that save cleans up temp file if write fails."""
        settings_manager = SettingsManager(config_dir=temp_config_dir)

        # Mock json.dump to fail during write
        with mock.patch("json.dump", side_effect=Exception("Write error")):
            result = settings_manager.save()

        assert result is False
        # Verify no temp files are left behind
        temp_files = list(Path(temp_config_dir).glob("settings_*.json"))
        assert len(temp_files) == 0

    def test_save_preserves_original_on_failure(self, temp_config_dir):
        """Test that original file is not corrupted if save fails mid-write."""
        settings_manager = SettingsManager(config_dir=temp_config_dir)

        # Save initial data
        settings_manager.set("test_key", "original_value")
        settings_file = Path(temp_config_dir) / "settings.json"
        assert settings_file.exists()

        # Read original content
        original_content = settings_file.read_text()

        # Mock to fail during atomic rename (after temp file is written)
        with mock.patch.object(Path, "replace", side_effect=OSError("Rename failed")):
            result = settings_manager.set("test_key", "corrupted_value")

        # Verify save failed
        assert result is False

        # Verify original file is preserved and not corrupted
        assert settings_file.exists()
        current_content = settings_file.read_text()
        assert current_content == original_content

        # Verify original value is still readable
        manager2 = SettingsManager(config_dir=temp_config_dir)
        assert manager2.get("test_key") == "original_value"

    def test_save_creates_temp_file_in_same_directory(self, temp_config_dir):
        """Test that temp file is created in the same directory as settings file."""
        settings_manager = SettingsManager(config_dir=temp_config_dir)

        with mock.patch("tempfile.mkstemp") as mock_mkstemp:
            # Setup mock to return a temp file path
            mock_mkstemp.return_value = (
                mock.MagicMock(),
                str(Path(temp_config_dir) / "settings_temp.json"),
            )
            with (
                mock.patch("os.fdopen"),
                mock.patch.object(Path, "replace"),
                mock.patch.object(Path, "unlink"),
            ):
                # Trigger exception to test cleanup
                with mock.patch("json.dump", side_effect=Exception()):
                    settings_manager.save()

            # Verify mkstemp was called with the correct directory
            call_kwargs = mock_mkstemp.call_args[1]
            assert call_kwargs["dir"] == Path(temp_config_dir)
            assert call_kwargs["prefix"] == "settings_"
            assert call_kwargs["suffix"] == ".json"

    def test_save_handles_mkdir_failure(self, temp_config_dir):
        """Test that save handles directory creation failures gracefully."""
        settings_manager = SettingsManager(config_dir=temp_config_dir)

        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("Cannot create dir")):
            result = settings_manager.save()

        assert result is False

    def test_save_handles_mkstemp_failure(self, temp_config_dir):
        """Test that save handles temp file creation failures gracefully."""
        settings_manager = SettingsManager(config_dir=temp_config_dir)

        with mock.patch("tempfile.mkstemp", side_effect=OSError("Cannot create temp file")):
            result = settings_manager.save()

        assert result is False


class TestSettingsManagerBackupCorruptedFile:
    """Tests for SettingsManager _backup_corrupted_file method and backup behavior."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_backup_creates_corrupted_suffix_file(self, temp_config_dir):
        """Test that backup creates file with .corrupted suffix."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("corrupted data")

        manager = SettingsManager(config_dir=config_dir)
        manager._backup_corrupted_file()

        backup_path = config_dir / "settings.json.corrupted"
        assert backup_path.exists()
        assert not settings_file.exists()

    def test_backup_does_nothing_if_file_missing(self, temp_config_dir):
        """Test that backup does nothing if file doesn't exist."""
        config_dir = Path(temp_config_dir)
        manager = SettingsManager(config_dir=config_dir)

        # Should not raise
        manager._backup_corrupted_file()

        backup_path = config_dir / "settings.json.corrupted"
        assert not backup_path.exists()

    def test_backup_does_not_overwrite_existing_backup(self, temp_config_dir):
        """Test that backup doesn't overwrite existing backup file."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        backup_path = config_dir / "settings.json.corrupted"

        # Create existing backup
        backup_path.write_text("original backup")
        settings_file.write_text("new corrupted data")

        manager = SettingsManager(config_dir=config_dir)
        manager._backup_corrupted_file()

        # Original backup should be preserved
        assert backup_path.read_text() == "original backup"
        # Original file should still exist
        assert settings_file.exists()

    def test_backup_handles_permission_error(self, temp_config_dir):
        """Test that backup handles permission errors silently."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("corrupted")

        manager = SettingsManager(config_dir=config_dir)

        with mock.patch.object(Path, "rename", side_effect=PermissionError):
            # Should not raise
            manager._backup_corrupted_file()

    def test_backup_handles_os_error(self, temp_config_dir):
        """Test that backup handles OS errors silently."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("corrupted")

        manager = SettingsManager(config_dir=config_dir)

        with mock.patch.object(Path, "rename", side_effect=OSError):
            # Should not raise
            manager._backup_corrupted_file()

    def test_load_creates_backup_on_corrupted_json(self, temp_config_dir):
        """Test that load creates backup of corrupted JSON file."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("{ corrupted json }")

        manager = SettingsManager(config_dir=config_dir)

        # Verify backup was created
        backup_path = config_dir / "settings.json.corrupted"
        assert backup_path.exists()

        # Verify defaults are returned
        assert manager.get("notifications_enabled") is True

    def test_load_creates_backup_on_non_dict_json(self, temp_config_dir):
        """Test that load creates backup when JSON contains non-dict data."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        # Write a JSON array instead of dict
        settings_file.write_text('["item1", "item2"]')

        manager = SettingsManager(config_dir=config_dir)

        # Verify backup was created
        backup_path = config_dir / "settings.json.corrupted"
        assert backup_path.exists()

        # Verify defaults are returned
        assert manager.get("notifications_enabled") is True
        assert manager.get("custom_setting") is None

    def test_load_creates_backup_on_null_json(self, temp_config_dir):
        """Test that load creates backup when JSON contains null."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        settings_file.write_text("null")

        manager = SettingsManager(config_dir=config_dir)

        # Verify backup was created
        backup_path = config_dir / "settings.json.corrupted"
        assert backup_path.exists()

        # Verify defaults are returned
        assert manager.get("notifications_enabled") is True

    def test_backup_preserves_corrupted_content(self, temp_config_dir):
        """Test that backup preserves the original corrupted content."""
        config_dir = Path(temp_config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_file = config_dir / "settings.json"
        corrupted_content = "{ invalid: json, content }"
        settings_file.write_text(corrupted_content)

        _manager = SettingsManager(config_dir=config_dir)

        # Verify backup contains original corrupted content
        backup_path = config_dir / "settings.json.corrupted"
        assert backup_path.read_text() == corrupted_content


class TestSettingsManagerConcurrencyEdgeCases:
    """Edge case tests for concurrent access to SettingsManager."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for settings storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_concurrent_reset_operations(self, temp_config_dir):
        """Test concurrent reset_to_defaults operations."""
        import threading

        manager = SettingsManager(config_dir=temp_config_dir)
        errors = []

        def reset_settings():
            try:
                for _ in range(10):
                    manager.reset_to_defaults()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reset_settings) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # After all resets, should have defaults
        assert manager.get("notifications_enabled") is True

    def test_concurrent_get_all_operations(self, temp_config_dir):
        """Test concurrent get_all operations."""
        import threading

        manager = SettingsManager(config_dir=temp_config_dir)
        manager.set("test_key", "test_value")

        results = []
        errors = []

        def get_all_settings():
            try:
                for _ in range(10):
                    all_settings = manager.get_all()
                    results.append(all_settings)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=get_all_settings) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 50  # 5 threads * 10 iterations

    def test_concurrent_mixed_operations(self, temp_config_dir):
        """Test concurrent mixed get/set/reset operations."""
        import threading

        manager = SettingsManager(config_dir=temp_config_dir)
        errors = []

        def do_gets():
            try:
                for _ in range(20):
                    manager.get("notifications_enabled")
                    manager.get("nonexistent_key", "default")
            except Exception as e:
                errors.append(f"Get error: {e}")

        def do_sets():
            try:
                for i in range(20):
                    manager.set(f"key_{i}", f"value_{i}")
            except Exception as e:
                errors.append(f"Set error: {e}")

        def do_resets():
            try:
                for _ in range(5):
                    manager.reset_to_defaults()
            except Exception as e:
                errors.append(f"Reset error: {e}")

        threads = [
            threading.Thread(target=do_gets),
            threading.Thread(target=do_sets),
            threading.Thread(target=do_resets),
            threading.Thread(target=do_gets),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
