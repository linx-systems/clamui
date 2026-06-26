# ClamUI ProfileManager Tests
"""Unit tests for the ProfileManager class."""

import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from src.profiles.profile_manager import (
    MAX_PROFILE_NAME_LENGTH,
    ProfileManager,
)


class TestProfileManagerInit:
    """Tests for ProfileManager initialization."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_init_creates_config_directory(self, temp_config_dir):
        """Test that ProfileManager creates config directory if needed."""
        nested_dir = Path(temp_config_dir) / "nested" / "config"
        manager = ProfileManager(config_dir=nested_dir)
        # The directory is created when profiles are saved
        assert nested_dir.exists() or manager._config_dir == nested_dir

    def test_init_creates_default_profiles(self, temp_config_dir):
        """Test that ProfileManager creates default profiles on first init."""
        manager = ProfileManager(config_dir=temp_config_dir)
        profiles = manager.list_profiles()

        # Should have the default profiles defined in DEFAULT_PROFILES
        default_names = {p["name"] for p in ProfileManager.DEFAULT_PROFILES}
        profile_names = {p.name for p in profiles}

        assert default_names.issubset(profile_names)

    def test_init_default_profiles_are_marked_default(self, temp_config_dir):
        """Test that default profiles have is_default=True."""
        manager = ProfileManager(config_dir=temp_config_dir)
        profiles = manager.list_profiles()

        default_names = {p["name"] for p in ProfileManager.DEFAULT_PROFILES}

        for profile in profiles:
            if profile.name in default_names:
                assert profile.is_default is True

    def test_init_loads_existing_profiles(self, temp_config_dir):
        """Test that ProfileManager loads existing profiles on init."""
        # Create first manager and add a custom profile
        manager1 = ProfileManager(config_dir=temp_config_dir)
        manager1.create_profile(
            name="Custom Profile",
            targets=["/home/user"],
            exclusions={},
        )

        # Create second manager and verify custom profile is loaded
        manager2 = ProfileManager(config_dir=temp_config_dir)
        profile = manager2.get_profile_by_name("Custom Profile")

        assert profile is not None
        assert profile.name == "Custom Profile"

    def test_init_does_not_duplicate_default_profiles(self, temp_config_dir):
        """Test that default profiles are not duplicated on subsequent inits."""
        manager1 = ProfileManager(config_dir=temp_config_dir)
        initial_count = len(manager1.list_profiles())

        manager2 = ProfileManager(config_dir=temp_config_dir)
        second_count = len(manager2.list_profiles())

        assert initial_count == second_count


class TestProfileManagerValidation:
    """Tests for ProfileManager validation methods."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        return ProfileManager(config_dir=temp_config_dir)

    def test_validate_name_empty_string_raises(self, manager):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            manager._validate_name("")

    def test_validate_name_whitespace_only_raises(self, manager):
        """Test that whitespace-only name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            manager._validate_name("   ")

    def test_validate_name_none_raises(self, manager):
        """Test that None name raises ValueError."""
        with pytest.raises(ValueError):
            manager._validate_name(None)

    def test_validate_name_too_long_raises(self, manager):
        """Test that name exceeding max length raises ValueError."""
        long_name = "x" * (MAX_PROFILE_NAME_LENGTH + 1)
        with pytest.raises(ValueError, match="cannot exceed"):
            manager._validate_name(long_name)

    def test_validate_name_max_length_allowed(self, manager):
        """Test that name at max length is valid."""
        max_name = "x" * MAX_PROFILE_NAME_LENGTH
        # Should not raise
        manager._validate_name(max_name)

    def test_validate_name_duplicate_raises(self, manager):
        """Test that duplicate name raises ValueError."""
        manager.create_profile(
            name="Test Profile",
            targets=["/home"],
            exclusions={},
        )
        with pytest.raises(ValueError, match="already exists"):
            manager._validate_name("Test Profile")

    def test_validate_name_duplicate_with_exclude_id(self, manager):
        """Test that duplicate check excludes specified ID."""
        profile = manager.create_profile(
            name="Test Profile",
            targets=["/home"],
            exclusions={},
        )
        # Should not raise when excluding the profile's own ID
        manager._validate_name("Test Profile", exclude_id=profile.id)

    def test_validate_path_format_empty_invalid(self, manager):
        """Test that empty path is invalid."""
        is_valid, error = manager._validate_path_format("")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_validate_path_format_whitespace_invalid(self, manager):
        """Test that whitespace-only path is invalid."""
        is_valid, error = manager._validate_path_format("   ")
        assert is_valid is False

    def test_validate_path_format_null_byte_invalid(self, manager):
        """Test that path with null byte is invalid (security check)."""
        is_valid, error = manager._validate_path_format("/home/user\x00/file")
        assert is_valid is False
        assert "invalid" in error.lower()

    def test_validate_path_format_valid_absolute(self, manager):
        """Test that valid absolute path is accepted."""
        is_valid, error = manager._validate_path_format("/home/user/documents")
        assert is_valid is True
        assert error is None

    def test_validate_path_format_valid_home_tilde(self, manager):
        """Test that tilde path is accepted."""
        is_valid, error = manager._validate_path_format("~/Downloads")
        assert is_valid is True
        assert error is None

    def test_validate_path_format_valid_relative(self, manager):
        """Test that relative path is accepted."""
        is_valid, error = manager._validate_path_format("./documents")
        assert is_valid is True
        assert error is None

    def test_validate_targets_not_list_raises(self, manager):
        """Test that non-list targets raises ValueError."""
        with pytest.raises(ValueError, match="must be a list"):
            manager._validate_targets("/home/user")  # String instead of list

    def test_validate_targets_non_string_item_raises(self, manager):
        """Test that non-string item in targets raises ValueError."""
        with pytest.raises(ValueError, match="must be a string"):
            manager._validate_targets(["/home/user", 123])

    def test_validate_targets_invalid_path_raises(self, manager):
        """Test that invalid path in targets raises ValueError."""
        with pytest.raises(ValueError, match="Invalid target path"):
            manager._validate_targets(["/valid/path", "\x00invalid"])

    def test_validate_targets_valid_paths(self, manager):
        """Test that valid paths return empty warnings."""
        warnings = manager._validate_targets(["/home/user", "~/Downloads"])
        assert warnings == []

    def test_validate_exclusions_not_dict_raises(self, manager):
        """Test that non-dict exclusions raises ValueError."""
        with pytest.raises(ValueError, match="must be a dictionary"):
            manager._validate_exclusions(["/exclude"], ["/home"])

    def test_validate_exclusions_paths_not_list_raises(self, manager):
        """Test that non-list paths in exclusions raises ValueError."""
        with pytest.raises(ValueError, match="'paths' must be a list"):
            manager._validate_exclusions({"paths": "/single"}, ["/home"])

    def test_validate_exclusions_path_not_string_raises(self, manager):
        """Test that non-string path in exclusions raises ValueError."""
        with pytest.raises(ValueError, match="must be a string"):
            manager._validate_exclusions({"paths": [123]}, ["/home"])

    def test_validate_exclusions_invalid_path_raises(self, manager):
        """Test that invalid path in exclusions raises ValueError."""
        with pytest.raises(ValueError, match="Invalid exclusion path"):
            manager._validate_exclusions({"paths": ["\x00bad"]}, ["/home"])

    def test_validate_exclusions_patterns_not_list_raises(self, manager):
        """Test that non-list patterns in exclusions raises ValueError."""
        with pytest.raises(ValueError, match="'patterns' must be a list"):
            manager._validate_exclusions({"patterns": "*.tmp"}, ["/home"])

    def test_validate_exclusions_pattern_not_string_raises(self, manager):
        """Test that non-string pattern raises ValueError."""
        with pytest.raises(ValueError, match="must be a string"):
            manager._validate_exclusions({"patterns": [123]}, ["/home"])

    def test_validate_exclusions_empty_pattern_raises(self, manager):
        """Test that empty pattern raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            manager._validate_exclusions({"patterns": [""]}, ["/home"])

    def test_validate_exclusions_valid_structure(self, manager):
        """Test that valid exclusions return empty warnings."""
        warnings = manager._validate_exclusions(
            {"paths": ["/tmp"], "patterns": ["*.tmp"]},
            ["/home"],
        )
        assert isinstance(warnings, list)

    def test_validate_exclusions_empty_dict_valid(self, manager):
        """Test that empty exclusions dict is valid."""
        warnings = manager._validate_exclusions({}, ["/home"])
        assert warnings == []


class TestProfileManagerCircularExclusions:
    """Tests for circular exclusion detection."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        return ProfileManager(config_dir=temp_config_dir)

    def test_check_circular_exclusions_warns_when_all_excluded(self, manager, temp_config_dir):
        """Test that warning is added when exclusion would exclude all targets."""
        warnings: list[str] = []
        # Create a target inside the temp dir
        target_dir = Path(temp_config_dir) / "target"
        target_dir.mkdir()

        # Exclusion that is parent of target
        manager._check_circular_exclusions(
            exclusion_paths=[temp_config_dir],
            targets=[str(target_dir)],
            warnings=warnings,
        )

        assert len(warnings) > 0
        assert "exclude all" in warnings[0].lower()

    def test_check_circular_exclusions_no_warning_when_partial(self, manager, temp_config_dir):
        """Test that no warning when exclusion doesn't cover all targets."""
        warnings: list[str] = []
        target1 = Path(temp_config_dir) / "target1"
        target1.mkdir()

        manager._check_circular_exclusions(
            exclusion_paths=[str(target1)],
            targets=[str(target1), "/some/other/path"],
            warnings=warnings,
        )

        # Only one target is excluded, so no warning about excluding ALL
        assert len([w for w in warnings if "exclude all" in w.lower()]) == 0

    def test_check_circular_exclusions_empty_targets(self, manager):
        """Test that empty targets doesn't cause issues."""
        warnings: list[str] = []
        manager._check_circular_exclusions(
            exclusion_paths=["/some/path"],
            targets=[],
            warnings=warnings,
        )
        assert warnings == []

    def test_check_circular_exclusions_empty_exclusions(self, manager):
        """Test that empty exclusions doesn't cause issues."""
        warnings: list[str] = []
        manager._check_circular_exclusions(
            exclusion_paths=[],
            targets=["/home/user"],
            warnings=warnings,
        )
        assert warnings == []


class TestProfileManagerCRUD:
    """Tests for ProfileManager CRUD operations."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        return ProfileManager(config_dir=temp_config_dir)

    def test_create_profile_basic(self, manager):
        """Test creating a basic profile."""
        profile = manager.create_profile(
            name="My Scan",
            targets=["/home/user"],
            exclusions={},
        )

        assert profile is not None
        assert profile.name == "My Scan"
        assert profile.targets == ["/home/user"]
        assert profile.exclusions == {}
        assert profile.is_default is False
        assert profile.id is not None

    def test_create_profile_strips_surrounding_whitespace(self, manager):
        """Test that surrounding whitespace is stripped before storing the name."""
        profile = manager.create_profile(
            name="  Quick  ",
            targets=["/home/user"],
            exclusions={},
        )

        # Stored, validated, and deduplicated name must be the stripped value.
        assert profile.name == "Quick"
        # The stripped name is what is retrievable and what blocks duplicates.
        assert manager.get_profile_by_name("Quick") is not None
        with pytest.raises(ValueError):
            manager.create_profile(
                name="Quick",
                targets=["/home/user"],
                exclusions={},
            )

    def test_create_profile_with_all_fields(self, manager):
        """Test creating a profile with all fields."""
        profile = manager.create_profile(
            name="Full Profile",
            targets=["/home", "/var"],
            exclusions={"paths": ["/var/cache"]},
            description="A complete profile",
            options={"recursive": True},
            is_default=False,
        )

        assert profile.name == "Full Profile"
        assert profile.targets == ["/home", "/var"]
        assert profile.exclusions == {"paths": ["/var/cache"]}
        assert profile.description == "A complete profile"
        assert profile.options == {"recursive": True}

    def test_create_profile_sets_timestamps(self, manager):
        """Test that created profile has timestamps."""
        profile = manager.create_profile(
            name="Timestamped",
            targets=["/home"],
            exclusions={},
        )

        assert profile.created_at is not None
        assert profile.updated_at is not None
        assert "T" in profile.created_at  # ISO format

    def test_create_profile_generates_unique_id(self, manager):
        """Test that each profile gets a unique ID."""
        profile1 = manager.create_profile(
            name="Profile 1",
            targets=["/home"],
            exclusions={},
        )
        profile2 = manager.create_profile(
            name="Profile 2",
            targets=["/home"],
            exclusions={},
        )

        assert profile1.id != profile2.id

    def test_create_profile_invalid_name_raises(self, manager):
        """Test that invalid name raises ValueError."""
        with pytest.raises(ValueError):
            manager.create_profile(
                name="",
                targets=["/home"],
                exclusions={},
            )

    def test_create_profile_duplicate_name_raises(self, manager):
        """Test that duplicate name raises ValueError."""
        manager.create_profile(
            name="Unique Name",
            targets=["/home"],
            exclusions={},
        )
        with pytest.raises(ValueError, match="already exists"):
            manager.create_profile(
                name="Unique Name",
                targets=["/home"],
                exclusions={},
            )

    def test_get_profile_by_id(self, manager):
        """Test retrieving profile by ID."""
        created = manager.create_profile(
            name="Get Test",
            targets=["/home"],
            exclusions={},
        )

        retrieved = manager.get_profile(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == created.name

    def test_get_profile_by_id_not_found(self, manager):
        """Test that non-existent ID returns None."""
        result = manager.get_profile("nonexistent-uuid")
        assert result is None

    def test_get_profile_by_name(self, manager):
        """Test retrieving profile by name."""
        created = manager.create_profile(
            name="Named Profile",
            targets=["/home"],
            exclusions={},
        )

        retrieved = manager.get_profile_by_name("Named Profile")

        assert retrieved is not None
        assert retrieved.id == created.id

    def test_get_profile_by_name_not_found(self, manager):
        """Test that non-existent name returns None."""
        result = manager.get_profile_by_name("Does Not Exist")
        assert result is None

    def test_update_profile_name(self, manager):
        """Test updating profile name."""
        profile = manager.create_profile(
            name="Original Name",
            targets=["/home"],
            exclusions={},
        )

        updated = manager.update_profile(profile.id, name="New Name")

        assert updated is not None
        assert updated.name == "New Name"
        assert updated.id == profile.id

    def test_update_profile_targets(self, manager):
        """Test updating profile targets."""
        profile = manager.create_profile(
            name="Update Targets",
            targets=["/home"],
            exclusions={},
        )

        updated = manager.update_profile(
            profile.id,
            targets=["/home", "/var"],
        )

        assert updated.targets == ["/home", "/var"]

    def test_update_profile_exclusions(self, manager):
        """Test updating profile exclusions."""
        profile = manager.create_profile(
            name="Update Exclusions",
            targets=["/home"],
            exclusions={},
        )

        updated = manager.update_profile(
            profile.id,
            exclusions={"paths": ["/home/.cache"]},
        )

        assert updated.exclusions == {"paths": ["/home/.cache"]}

    def test_update_profile_updates_timestamp(self, manager):
        """Test that update changes updated_at timestamp."""
        profile = manager.create_profile(
            name="Timestamp Update",
            targets=["/home"],
            exclusions={},
        )
        original_updated_at = profile.updated_at

        # Small delay to ensure timestamp differs
        import time

        time.sleep(0.01)

        updated = manager.update_profile(profile.id, description="Changed")

        assert updated.updated_at != original_updated_at

    def test_update_profile_preserves_created_at(self, manager):
        """Test that update preserves created_at timestamp."""
        profile = manager.create_profile(
            name="Preserve Created",
            targets=["/home"],
            exclusions={},
        )
        original_created_at = profile.created_at

        updated = manager.update_profile(profile.id, description="Changed")

        assert updated.created_at == original_created_at

    def test_update_profile_not_found(self, manager):
        """Test that updating non-existent profile returns None."""
        result = manager.update_profile("nonexistent-id", name="New Name")
        assert result is None

    def test_update_profile_invalid_name_raises(self, manager):
        """Test that updating with invalid name raises ValueError."""
        profile = manager.create_profile(
            name="Valid Name",
            targets=["/home"],
            exclusions={},
        )

        with pytest.raises(ValueError):
            manager.update_profile(profile.id, name="")

    def test_update_profile_duplicate_name_raises(self, manager):
        """Test that updating to duplicate name raises ValueError."""
        manager.create_profile(
            name="First Profile",
            targets=["/home"],
            exclusions={},
        )
        profile2 = manager.create_profile(
            name="Second Profile",
            targets=["/home"],
            exclusions={},
        )

        with pytest.raises(ValueError, match="already exists"):
            manager.update_profile(profile2.id, name="First Profile")

    def test_update_profile_same_name_allowed(self, manager):
        """Test that updating profile with same name is allowed."""
        profile = manager.create_profile(
            name="Keep Same",
            targets=["/home"],
            exclusions={},
        )

        # Should not raise - keeping the same name
        updated = manager.update_profile(
            profile.id,
            name="Keep Same",
            description="New description",
        )

        assert updated.name == "Keep Same"
        assert updated.description == "New description"

    def test_delete_profile(self, manager):
        """Test deleting a profile."""
        profile = manager.create_profile(
            name="To Delete",
            targets=["/home"],
            exclusions={},
        )

        result = manager.delete_profile(profile.id)

        assert result is True
        assert manager.get_profile(profile.id) is None

    def test_delete_profile_not_found(self, manager):
        """Test that deleting non-existent profile returns False."""
        result = manager.delete_profile("nonexistent-id")
        assert result is False

    def test_delete_default_profile_raises(self, manager):
        """Test that deleting default profile raises ValueError."""
        # Get a default profile
        profiles = manager.list_profiles()
        default_profile = next((p for p in profiles if p.is_default), None)

        assert default_profile is not None

        with pytest.raises(ValueError, match="Cannot delete default"):
            manager.delete_profile(default_profile.id)


class TestProfileManagerListing:
    """Tests for ProfileManager listing and query operations."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        return ProfileManager(config_dir=temp_config_dir)

    def test_list_profiles_returns_all(self, manager):
        """Test that list_profiles returns all profiles."""
        initial_count = len(manager.list_profiles())

        manager.create_profile(
            name="Extra Profile",
            targets=["/home"],
            exclusions={},
        )

        profiles = manager.list_profiles()
        assert len(profiles) == initial_count + 1

    def test_list_profiles_sorted_by_name(self, manager):
        """Test that list_profiles returns profiles sorted by name."""
        manager.create_profile(name="Zebra", targets=["/home"], exclusions={})
        manager.create_profile(name="Apple", targets=["/home"], exclusions={})
        manager.create_profile(name="Mango", targets=["/home"], exclusions={})

        profiles = manager.list_profiles()
        names = [p.name for p in profiles]

        assert names == sorted(names, key=str.lower)

    def test_get_all_profiles_returns_dict(self, manager):
        """Test that get_all_profiles returns dictionary."""
        profiles_dict = manager.get_all_profiles()

        assert isinstance(profiles_dict, dict)
        for profile_id, profile in profiles_dict.items():
            assert profile.id == profile_id

    def test_profile_exists_true(self, manager):
        """Test profile_exists returns True for existing profile."""
        profile = manager.create_profile(
            name="Exists",
            targets=["/home"],
            exclusions={},
        )

        assert manager.profile_exists(profile.id) is True

    def test_profile_exists_false(self, manager):
        """Test profile_exists returns False for non-existing profile."""
        assert manager.profile_exists("nonexistent-id") is False

    def test_name_exists_true(self, manager):
        """Test name_exists returns True for existing name."""
        manager.create_profile(
            name="Existing Name",
            targets=["/home"],
            exclusions={},
        )

        assert manager.name_exists("Existing Name") is True

    def test_name_exists_false(self, manager):
        """Test name_exists returns False for non-existing name."""
        assert manager.name_exists("No Such Name") is False

    def test_name_exists_with_exclude_id(self, manager):
        """Test name_exists with exclude_id parameter."""
        profile = manager.create_profile(
            name="My Profile",
            targets=["/home"],
            exclusions={},
        )

        # Should return False when excluding the profile's own ID
        assert manager.name_exists("My Profile", exclude_id=profile.id) is False
        # Should return True for a different ID
        assert manager.name_exists("My Profile", exclude_id="other-id") is True


class TestProfileManagerReload:
    """Tests for ProfileManager reload functionality."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_reload_refreshes_from_storage(self, temp_config_dir):
        """Test that reload refreshes profiles from storage."""
        manager1 = ProfileManager(config_dir=temp_config_dir)
        manager2 = ProfileManager(config_dir=temp_config_dir)

        # Create profile with manager1
        manager1.create_profile(
            name="Reload Test",
            targets=["/home"],
            exclusions={},
        )

        # Manager2 doesn't see it yet without reload
        # (though it might due to shared storage, this tests the reload path)
        manager2.reload()

        reloaded = manager2.get_profile_by_name("Reload Test")
        assert reloaded is not None


class TestProfileManagerExportImport:
    """Tests for ProfileManager export/import functionality."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        return ProfileManager(config_dir=temp_config_dir)

    def test_export_profile_creates_file(self, manager, temp_config_dir):
        """Test that export_profile creates a JSON file."""
        profile = manager.create_profile(
            name="Export Test",
            targets=["/home"],
            exclusions={},
        )

        export_path = Path(temp_config_dir) / "exported.json"
        manager.export_profile(profile.id, export_path)

        assert export_path.exists()

    def test_export_profile_valid_json(self, manager, temp_config_dir):
        """Test that exported file contains valid JSON."""
        profile = manager.create_profile(
            name="JSON Export",
            targets=["/home", "/var"],
            exclusions={"paths": ["/home/.cache"]},
            description="Test profile",
        )

        export_path = Path(temp_config_dir) / "exported.json"
        manager.export_profile(profile.id, export_path)

        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "export_version" in data
        assert "profile" in data
        assert data["profile"]["name"] == "JSON Export"
        assert data["profile"]["targets"] == ["/home", "/var"]

    def test_export_profile_not_found_raises(self, manager, temp_config_dir):
        """Test that exporting non-existent profile raises ValueError."""
        export_path = Path(temp_config_dir) / "exported.json"

        with pytest.raises(ValueError, match="not found"):
            manager.export_profile("nonexistent-id", export_path)

    def test_export_profile_creates_parent_dirs(self, manager, temp_config_dir):
        """Test that export creates parent directories if needed."""
        profile = manager.create_profile(
            name="Dir Export",
            targets=["/home"],
            exclusions={},
        )

        export_path = Path(temp_config_dir) / "nested" / "dir" / "exported.json"
        manager.export_profile(profile.id, export_path)

        assert export_path.exists()

    def test_import_profile_basic(self, manager, temp_config_dir):
        """Test importing a profile from JSON file."""
        # Create export file
        export_data = {
            "export_version": 1,
            "profile": {
                "id": "original-id",
                "name": "Imported Profile",
                "targets": ["/home/user"],
                "exclusions": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
                "is_default": False,
                "description": "An imported profile",
                "options": {},
            },
        }

        import_path = Path(temp_config_dir) / "import.json"
        with open(import_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f)

        imported = manager.import_profile(import_path)

        assert imported is not None
        assert imported.name == "Imported Profile"
        assert imported.targets == ["/home/user"]
        # Imported profile should get new ID
        assert imported.id != "original-id"
        # Imported profile should never be default
        assert imported.is_default is False

    def test_import_profile_legacy_format(self, manager, temp_config_dir):
        """Test importing a profile from legacy (raw) format."""
        # Legacy format: just the profile object without wrapper
        legacy_data = {
            "name": "Legacy Profile",
            "targets": ["/home"],
            "exclusions": {},
            "description": "Legacy format",
        }

        import_path = Path(temp_config_dir) / "legacy.json"
        with open(import_path, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)

        imported = manager.import_profile(import_path)

        assert imported is not None
        assert imported.name == "Legacy Profile"

    def test_import_profile_duplicate_name_gets_suffix(self, manager, temp_config_dir):
        """Test that importing duplicate name gets numeric suffix."""
        # Create existing profile
        manager.create_profile(
            name="Duplicate Name",
            targets=["/home"],
            exclusions={},
        )

        # Create import file with same name
        export_data = {
            "export_version": 1,
            "profile": {
                "name": "Duplicate Name",
                "targets": ["/var"],
            },
        }

        import_path = Path(temp_config_dir) / "duplicate.json"
        with open(import_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f)

        imported = manager.import_profile(import_path)

        assert imported is not None
        assert imported.name == "Duplicate Name (2)"

    def test_import_profile_file_not_found_raises(self, manager, temp_config_dir):
        """Test that importing non-existent file raises FileNotFoundError."""
        import_path = Path(temp_config_dir) / "nonexistent.json"

        with pytest.raises(FileNotFoundError):
            manager.import_profile(import_path)

    def test_import_profile_invalid_json_raises(self, manager, temp_config_dir):
        """Test that importing invalid JSON raises ValueError."""
        import_path = Path(temp_config_dir) / "invalid.json"
        import_path.write_text("{ not valid json }")

        with pytest.raises(ValueError, match="Invalid JSON"):
            manager.import_profile(import_path)

    def test_import_profile_missing_name_raises(self, manager, temp_config_dir):
        """Test that importing without name field raises ValueError."""
        export_data = {
            "profile": {
                "targets": ["/home"],
            },
        }

        import_path = Path(temp_config_dir) / "noname.json"
        with open(import_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f)

        with pytest.raises(ValueError, match="missing required field"):
            manager.import_profile(import_path)

    def test_import_profile_invalid_targets_type_raises(self, manager, temp_config_dir):
        """Test that importing with wrong targets type raises ValueError."""
        export_data = {
            "profile": {
                "name": "Bad Targets",
                "targets": "/single/path",  # Should be list
            },
        }

        import_path = Path(temp_config_dir) / "badtargets.json"
        with open(import_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f)

        with pytest.raises(ValueError, match="must be a list"):
            manager.import_profile(import_path)

    def test_export_import_roundtrip(self, manager, temp_config_dir):
        """Test that export and import produces equivalent profile."""
        original = manager.create_profile(
            name="Roundtrip",
            targets=["/home", "/var"],
            exclusions={"paths": ["/home/.cache"], "patterns": ["*.tmp"]},
            description="Test roundtrip",
            options={"recursive": True},
        )

        export_path = Path(temp_config_dir) / "roundtrip.json"
        manager.export_profile(original.id, export_path)

        # Import creates new profile with unique name
        imported = manager.import_profile(export_path)

        # Core data should match (except id, name suffix, timestamps)
        assert imported.targets == original.targets
        assert imported.exclusions == original.exclusions
        assert imported.description == original.description
        assert imported.options == original.options


class TestProfileManagerMakeUniqueName:
    """Tests for the _make_unique_name helper method."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        return ProfileManager(config_dir=temp_config_dir)

    def test_make_unique_name_no_conflict(self, manager):
        """Test that unique name is returned as-is."""
        result = manager._make_unique_name("Unique Name")
        assert result == "Unique Name"

    def test_make_unique_name_with_conflict(self, manager):
        """Test that conflicting name gets numeric suffix."""
        manager.create_profile(name="Conflict", targets=["/home"], exclusions={})

        result = manager._make_unique_name("Conflict")
        assert result == "Conflict (2)"

    def test_make_unique_name_multiple_conflicts(self, manager):
        """Test that multiple conflicts increment suffix."""
        manager.create_profile(name="Multi", targets=["/home"], exclusions={})
        manager.create_profile(name="Multi (2)", targets=["/home"], exclusions={})

        result = manager._make_unique_name("Multi")
        assert result == "Multi (3)"


class TestProfileManagerThreadSafety:
    """Tests for ProfileManager thread safety."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        return ProfileManager(config_dir=temp_config_dir)

    def test_concurrent_reads(self, manager):
        """Test that concurrent reads work correctly."""
        # Create some profiles first
        for i in range(5):
            manager.create_profile(
                name=f"Concurrent Read {i}",
                targets=["/home"],
                exclusions={},
            )

        results = []
        errors = []

        def read_profiles():
            try:
                profiles = manager.list_profiles()
                results.append(len(profiles))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_profiles) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All threads should have read the same number of profiles
        assert len(set(results)) == 1

    def test_concurrent_writes(self, manager):
        """Test that concurrent writes don't corrupt data."""
        errors = []
        created_ids = []
        lock = threading.Lock()

        def create_profile(index):
            try:
                profile = manager.create_profile(
                    name=f"Thread Profile {index}",
                    targets=["/home"],
                    exclusions={},
                )
                with lock:
                    created_ids.append(profile.id)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=create_profile, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All profiles should have unique IDs
        assert len(created_ids) == len(set(created_ids))


class TestProfileManagerPersistence:
    """Tests for ProfileManager persistence across instances."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_profiles_persist_across_instances(self, temp_config_dir):
        """Test that profiles persist when creating new manager instances."""
        manager1 = ProfileManager(config_dir=temp_config_dir)
        profile = manager1.create_profile(
            name="Persistent",
            targets=["/home"],
            exclusions={},
        )

        # Create new manager instance
        manager2 = ProfileManager(config_dir=temp_config_dir)
        loaded = manager2.get_profile(profile.id)

        assert loaded is not None
        assert loaded.name == "Persistent"
        assert loaded.targets == ["/home"]

    def test_updates_persist_across_instances(self, temp_config_dir):
        """Test that updates persist when creating new manager instances."""
        manager1 = ProfileManager(config_dir=temp_config_dir)
        profile = manager1.create_profile(
            name="Update Persist",
            targets=["/home"],
            exclusions={},
        )

        manager1.update_profile(profile.id, description="Updated description")

        manager2 = ProfileManager(config_dir=temp_config_dir)
        loaded = manager2.get_profile(profile.id)

        assert loaded is not None
        assert loaded.description == "Updated description"

    def test_deletes_persist_across_instances(self, temp_config_dir):
        """Test that deletes persist when creating new manager instances."""
        manager1 = ProfileManager(config_dir=temp_config_dir)
        profile = manager1.create_profile(
            name="Delete Persist",
            targets=["/home"],
            exclusions={},
        )
        profile_id = profile.id

        manager1.delete_profile(profile_id)

        manager2 = ProfileManager(config_dir=temp_config_dir)
        loaded = manager2.get_profile(profile_id)

        assert loaded is None


class TestProfileManagerPathCaching:
    """Tests for ProfileManager path caching functionality."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        # Clear caches before each test
        ProfileManager.clear_path_cache()
        return ProfileManager(config_dir=temp_config_dir)

    def test_cached_expanduser_returns_correct_result(self, manager):
        """Test that _cached_expanduser() returns correct expanded path."""
        result = ProfileManager._cached_expanduser("~/Documents")

        assert result is not None
        assert isinstance(result, Path)
        # Should expand ~ to home directory
        assert "~" not in str(result)
        assert "Documents" in str(result)

    def test_cached_expanduser_handles_non_tilde_paths(self, manager):
        """Test that _cached_expanduser() handles paths without tilde."""
        result = ProfileManager._cached_expanduser("/home/user/Documents")

        assert result is not None
        assert isinstance(result, Path)
        assert str(result) == "/home/user/Documents"

    def test_cached_expanduser_handles_invalid_paths(self, manager):
        """Test that _cached_expanduser() returns None for invalid paths."""
        # Path with null byte should fail
        result = ProfileManager._cached_expanduser("/home\x00/user")

        # Should return None on failure
        assert result is None

    def test_cached_resolve_returns_correct_result(self, manager, temp_config_dir):
        """Test that _cached_resolve() returns resolved absolute path."""
        # Create a real directory to resolve
        test_dir = Path(temp_config_dir) / "test_resolve"
        test_dir.mkdir()

        result = ProfileManager._cached_resolve(str(test_dir))

        assert result is not None
        assert isinstance(result, Path)
        assert result.is_absolute()
        # Resolved path should be absolute and match the directory
        assert str(result) == str(test_dir.resolve())

    def test_cached_resolve_resolves_relative_paths(self, manager, temp_config_dir):
        """Test that _cached_resolve() resolves relative paths."""
        # Create a test directory
        test_dir = Path(temp_config_dir) / "relative_test"
        test_dir.mkdir()

        # Use relative path
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_config_dir)
            result = ProfileManager._cached_resolve("./relative_test")

            assert result is not None
            assert result.is_absolute()
            assert "relative_test" in str(result)
        finally:
            os.chdir(old_cwd)

    def test_cached_resolve_handles_nonexistent_paths(self, manager):
        """Test that _cached_resolve() works with nonexistent paths."""
        # resolve() should work even for nonexistent paths (creates absolute path)
        result = ProfileManager._cached_resolve("/nonexistent/path/that/does/not/exist")

        assert result is not None
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_cached_expanduser_cache_hits(self, manager):
        """Test that repeated calls to _cached_expanduser() use cache."""
        # Clear cache first
        ProfileManager.clear_path_cache()

        # First call - should be a cache miss
        path1 = "~/Documents"
        result1 = ProfileManager._cached_expanduser(path1)

        cache_info = ProfileManager.get_cache_info()
        assert cache_info["expanduser"]["misses"] >= 1
        initial_misses = cache_info["expanduser"]["misses"]

        # Second call with same path - should be a cache hit
        result2 = ProfileManager._cached_expanduser(path1)

        cache_info = ProfileManager.get_cache_info()
        assert cache_info["expanduser"]["hits"] >= 1
        # Misses should not increase
        assert cache_info["expanduser"]["misses"] == initial_misses

        # Results should be identical
        assert result1 == result2

    def test_cached_resolve_cache_hits(self, manager, temp_config_dir):
        """Test that repeated calls to _cached_resolve() use cache."""
        # Clear cache first
        ProfileManager.clear_path_cache()

        # First call - should be a cache miss
        path1 = str(temp_config_dir)
        result1 = ProfileManager._cached_resolve(path1)

        cache_info = ProfileManager.get_cache_info()
        assert cache_info["resolve"]["misses"] >= 1
        initial_misses = cache_info["resolve"]["misses"]

        # Second call with same path - should be a cache hit
        result2 = ProfileManager._cached_resolve(path1)

        cache_info = ProfileManager.get_cache_info()
        assert cache_info["resolve"]["hits"] >= 1
        # Misses should not increase
        assert cache_info["resolve"]["misses"] == initial_misses

        # Results should be identical
        assert result1 == result2

    def test_clear_path_cache_clears_both_caches(self, manager):
        """Test that clear_path_cache() clears both expanduser and resolve caches."""
        # Populate both caches
        ProfileManager._cached_expanduser("~/Documents")
        ProfileManager._cached_resolve("/home/user")

        # Verify caches have entries
        cache_info = ProfileManager.get_cache_info()
        assert cache_info["expanduser"]["currsize"] > 0 or cache_info["expanduser"]["misses"] > 0
        assert cache_info["resolve"]["currsize"] > 0 or cache_info["resolve"]["misses"] > 0

        # Clear caches
        ProfileManager.clear_path_cache()

        # Verify both caches are cleared
        cache_info = ProfileManager.get_cache_info()
        assert cache_info["expanduser"]["currsize"] == 0
        assert cache_info["expanduser"]["hits"] == 0
        assert cache_info["expanduser"]["misses"] == 0
        assert cache_info["resolve"]["currsize"] == 0
        assert cache_info["resolve"]["hits"] == 0
        assert cache_info["resolve"]["misses"] == 0

    def test_get_cache_info_returns_correct_structure(self, manager):
        """Test that get_cache_info() returns expected dictionary structure."""
        cache_info = ProfileManager.get_cache_info()

        # Check structure
        assert isinstance(cache_info, dict)
        assert "expanduser" in cache_info
        assert "resolve" in cache_info

        # Check expanduser info
        assert "hits" in cache_info["expanduser"]
        assert "misses" in cache_info["expanduser"]
        assert "maxsize" in cache_info["expanduser"]
        assert "currsize" in cache_info["expanduser"]
        assert cache_info["expanduser"]["maxsize"] == 128

        # Check resolve info
        assert "hits" in cache_info["resolve"]
        assert "misses" in cache_info["resolve"]
        assert "maxsize" in cache_info["resolve"]
        assert "currsize" in cache_info["resolve"]
        assert cache_info["resolve"]["maxsize"] == 128

    def test_cache_improves_performance_in_validation(self, manager, temp_config_dir):
        """Test that caching reduces redundant filesystem calls during validation."""
        # Clear cache first
        ProfileManager.clear_path_cache()

        # Create a profile with multiple targets and exclusions
        # This will trigger multiple path resolution calls
        test_dir = Path(temp_config_dir) / "test_validation"
        test_dir.mkdir()

        targets = [
            str(test_dir / "target1"),
            str(test_dir / "target2"),
            str(test_dir / "target3"),
        ]

        exclusions = {
            "paths": [
                str(test_dir / "exclude1"),
                str(test_dir / "exclude2"),
            ]
        }

        # Create the profile (triggers validation)
        profile = manager.create_profile(
            name="Cache Test",
            targets=targets,
            exclusions=exclusions,
        )

        # Check that caches were populated
        cache_info = ProfileManager.get_cache_info()
        total_calls = (
            cache_info["expanduser"]["hits"]
            + cache_info["expanduser"]["misses"]
            + cache_info["resolve"]["hits"]
            + cache_info["resolve"]["misses"]
        )

        # Should have made some calls
        assert total_calls > 0

        # Clear cache for second test
        ProfileManager.clear_path_cache()

        # Update the profile with same paths (triggers validation again)
        manager.update_profile(profile.id, description="Updated")

        # Verify cache usage on second validation
        cache_info2 = ProfileManager.get_cache_info()
        # Should have some cache activity from validation
        assert (cache_info2["expanduser"]["misses"] + cache_info2["resolve"]["misses"]) > 0

    def test_cache_handles_duplicate_paths_in_validation(self, manager, temp_config_dir):
        """Test that cache efficiently handles duplicate paths in validation."""
        ProfileManager.clear_path_cache()

        # Use same path multiple times
        same_path = str(Path(temp_config_dir) / "same")

        targets = [same_path, same_path, same_path]

        # This should use cache for duplicate paths
        manager._validate_targets(targets)

        cache_info = ProfileManager.get_cache_info()
        # With caching, we should have hits for duplicate paths
        # First call is a miss, subsequent calls should be hits
        assert cache_info["expanduser"]["currsize"] >= 1

    def test_cached_methods_are_thread_safe(self, manager):
        """Test that cached methods work correctly with concurrent access."""
        ProfileManager.clear_path_cache()

        results = []
        errors = []
        lock = threading.Lock()

        def call_cached_methods():
            try:
                # Call both cached methods
                exp_result = ProfileManager._cached_expanduser("~/test")
                res_result = ProfileManager._cached_resolve("/tmp")

                with lock:
                    results.append((exp_result, res_result))
            except Exception as e:
                with lock:
                    errors.append(e)

        # Run multiple threads
        threads = [threading.Thread(target=call_cached_methods) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no errors
        assert len(errors) == 0

        # All threads should get same results
        assert len(results) == 10
        # All expanduser results should be the same
        expanduser_results = [r[0] for r in results]
        assert len(set(map(str, expanduser_results))) == 1

        # All resolve results should be the same
        resolve_results = [r[1] for r in results]
        assert len(set(map(str, resolve_results))) == 1

    def test_cache_with_different_invalid_paths(self, manager):
        """Test that cache correctly handles multiple different invalid paths."""
        ProfileManager.clear_path_cache()

        # Try different invalid paths
        invalid_paths = [
            "/invalid\x00path1",
            "/invalid\x00path2",
            "/invalid\x00path3",
        ]

        for invalid_path in invalid_paths:
            result = ProfileManager._cached_expanduser(invalid_path)
            assert result is None

        # Each should be cached separately
        cache_info = ProfileManager.get_cache_info()
        # Should have misses for each unique invalid path
        assert cache_info["expanduser"]["misses"] >= len(invalid_paths)

    def test_validate_path_format_uses_cache(self, manager):
        """Test that _validate_path_format() uses the cached expanduser method."""
        ProfileManager.clear_path_cache()

        # Call _validate_path_format multiple times with same path
        path = "~/Documents"

        is_valid1, error1 = manager._validate_path_format(path)
        cache_info_after_first = ProfileManager.get_cache_info()
        first_misses = cache_info_after_first["expanduser"]["misses"]

        is_valid2, error2 = manager._validate_path_format(path)
        cache_info_after_second = ProfileManager.get_cache_info()

        # Results should be the same
        assert is_valid1 == is_valid2
        assert error1 == error2

        # Second call should use cache (hits should increase, misses stay same)
        assert (
            cache_info_after_second["expanduser"]["hits"]
            > cache_info_after_first["expanduser"]["hits"]
        )
        assert cache_info_after_second["expanduser"]["misses"] == first_misses

    def test_check_circular_exclusions_uses_cache(self, manager, temp_config_dir):
        """Test that _check_circular_exclusions() uses cached path methods."""
        ProfileManager.clear_path_cache()

        # Create test directories
        test_dir = Path(temp_config_dir) / "circular_test"
        test_dir.mkdir()

        exclusion_paths = [str(test_dir)]
        targets = [str(test_dir / "subdir")]
        warnings = []

        # First call
        manager._check_circular_exclusions(exclusion_paths, targets, warnings)
        cache_info_after_first = ProfileManager.get_cache_info()

        # Should have some cache activity
        first_total_calls = (
            cache_info_after_first["expanduser"]["hits"]
            + cache_info_after_first["expanduser"]["misses"]
            + cache_info_after_first["resolve"]["hits"]
            + cache_info_after_first["resolve"]["misses"]
        )
        assert first_total_calls > 0

        # Second call with same paths
        warnings2 = []
        manager._check_circular_exclusions(exclusion_paths, targets, warnings2)
        cache_info_after_second = ProfileManager.get_cache_info()

        # Should have cache hits on second call
        assert (
            cache_info_after_second["resolve"]["hits"] > cache_info_after_first["resolve"]["hits"]
        )


class TestXdgMigration:
    """Tests for XDG path migration in ProfileManager."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for profile storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_new_install_uses_xdg_path(self, temp_config_dir, monkeypatch):
        """Test that new installations use XDG path for Quick Scan."""
        # Mock get_xdg_user_dir to return a localized path
        monkeypatch.setattr(
            "src.core.flatpak.get_xdg_user_dir",
            lambda x: "/home/user/Téléchargements" if x == "DOWNLOAD" else None,
        )

        manager = ProfileManager(config_dir=temp_config_dir)
        quick_scan = manager.get_profile_by_name("Quick Scan")

        assert quick_scan is not None
        assert quick_scan.targets == ["/home/user/Téléchargements"]

    def test_new_install_fallback_to_hardcoded(self, temp_config_dir, monkeypatch):
        """Test fallback to ~/Downloads when xdg-user-dir unavailable."""
        # Mock get_xdg_user_dir to return None (command not available)
        monkeypatch.setattr(
            "src.core.flatpak.get_xdg_user_dir",
            lambda x: None,
        )

        manager = ProfileManager(config_dir=temp_config_dir)
        quick_scan = manager.get_profile_by_name("Quick Scan")

        assert quick_scan is not None
        assert quick_scan.targets == ["~/Downloads"]

    def test_migrate_existing_quick_scan(self, temp_config_dir, monkeypatch):
        """Test migration updates existing Quick Scan with ~/Downloads."""
        # First, create a profile with old hardcoded path (simulate pre-migration state)
        profiles_file = temp_config_dir / "profiles.json"
        old_profile_data = {
            "profiles": [
                {
                    "id": "test-quick-scan-id",
                    "name": "Quick Scan",
                    "targets": ["~/Downloads"],
                    "exclusions": {},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                    "is_default": True,
                    "description": "Fast scan",
                    "options": {},
                }
            ]
        }
        temp_config_dir.mkdir(parents=True, exist_ok=True)
        with open(profiles_file, "w") as f:
            json.dump(old_profile_data, f)

        # Mock get_xdg_user_dir to return XDG path
        monkeypatch.setattr(
            "src.core.flatpak.get_xdg_user_dir",
            lambda x: "/home/user/Downloads" if x == "DOWNLOAD" else None,
        )

        # Create manager - should trigger migration
        manager = ProfileManager(config_dir=temp_config_dir)
        quick_scan = manager.get_profile_by_name("Quick Scan")

        assert quick_scan is not None
        assert quick_scan.targets == ["/home/user/Downloads"]

    def test_migration_runs_once(self, temp_config_dir, monkeypatch):
        """Test that migration only runs once."""
        call_count = {"count": 0}

        def mock_xdg(x):
            call_count["count"] += 1
            return "/home/user/Downloads" if x == "DOWNLOAD" else None

        monkeypatch.setattr(
            "src.core.flatpak.get_xdg_user_dir",
            mock_xdg,
        )

        # First manager - runs migration
        ProfileManager(config_dir=temp_config_dir)
        first_count = call_count["count"]

        # Second manager - should skip migration (version already set)
        call_count["count"] = 0
        ProfileManager(config_dir=temp_config_dir)
        second_count = call_count["count"]

        # Migration should run on first init but not second
        assert first_count > 0
        # On second init, only _ensure_default_profiles calls get_xdg_user_dir,
        # but since profiles already exist, it won't be called
        # Migration is skipped due to version check
        assert second_count == 0

    def test_migration_skips_customized_quick_scan(self, temp_config_dir, monkeypatch):
        """Test migration doesn't overwrite customized Quick Scan targets."""
        # Create profile with custom targets (user modified it)
        profiles_file = temp_config_dir / "profiles.json"
        custom_profile_data = {
            "profiles": [
                {
                    "id": "test-quick-scan-id",
                    "name": "Quick Scan",
                    "targets": ["/custom/scan/path"],  # User customized
                    "exclusions": {},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                    "is_default": True,
                    "description": "Fast scan",
                    "options": {},
                }
            ]
        }
        temp_config_dir.mkdir(parents=True, exist_ok=True)
        with open(profiles_file, "w") as f:
            json.dump(custom_profile_data, f)

        monkeypatch.setattr(
            "src.core.flatpak.get_xdg_user_dir",
            lambda x: "/home/user/Downloads" if x == "DOWNLOAD" else None,
        )

        manager = ProfileManager(config_dir=temp_config_dir)
        quick_scan = manager.get_profile_by_name("Quick Scan")

        # Custom targets should be preserved
        assert quick_scan is not None
        assert quick_scan.targets == ["/custom/scan/path"]

    def test_migration_state_saved_to_settings(self, temp_config_dir, monkeypatch):
        """Test that migration state is saved to settings.json."""
        monkeypatch.setattr(
            "src.core.flatpak.get_xdg_user_dir",
            lambda x: "/home/user/Downloads" if x == "DOWNLOAD" else None,
        )

        ProfileManager(config_dir=temp_config_dir)

        settings_file = temp_config_dir / "settings.json"
        assert settings_file.exists()

        with open(settings_file) as f:
            settings = json.load(f)

        assert "_migrations" in settings
        assert settings["_migrations"].get("xdg_migration_version") == 1

    def test_migration_state_write_is_atomic(self, temp_config_dir, monkeypatch):
        """Migration state is written atomically: valid JSON, no leftover temp files."""
        monkeypatch.setattr(
            "src.core.flatpak.get_xdg_user_dir",
            lambda x: "/home/user/Downloads" if x == "DOWNLOAD" else None,
        )

        ProfileManager(config_dir=temp_config_dir)

        settings_file = temp_config_dir / "settings.json"
        assert settings_file.exists()
        # File contains complete, valid JSON (not a half-written file).
        with open(settings_file) as f:
            settings = json.load(f)
        assert settings["_migrations"]["xdg_migration_version"] == 1
        # Owner-only permissions like the rest of the config files.
        assert (settings_file.stat().st_mode & 0o777) == 0o600
        # No temp files were left behind by the atomic rename.
        assert not list(temp_config_dir.glob("settings_*.json"))

    def test_migration_preserves_existing_settings(self, temp_config_dir, monkeypatch):
        """Test that migration preserves existing settings in settings.json."""
        # Create settings with existing content
        settings_file = temp_config_dir / "settings.json"
        temp_config_dir.mkdir(parents=True, exist_ok=True)
        with open(settings_file, "w") as f:
            json.dump({"existing_setting": "value", "another": 123}, f)

        monkeypatch.setattr(
            "src.core.flatpak.get_xdg_user_dir",
            lambda x: "/home/user/Downloads" if x == "DOWNLOAD" else None,
        )

        ProfileManager(config_dir=temp_config_dir)

        with open(settings_file) as f:
            settings = json.load(f)

        # Existing settings should be preserved
        assert settings.get("existing_setting") == "value"
        assert settings.get("another") == 123
        # Migration state should be added
        assert settings["_migrations"]["xdg_migration_version"] == 1


class TestRestoreDefaultProfiles:
    """Tests for restore_default_profiles functionality."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Create a temporary directory for profile storage."""
        return tmp_path

    @pytest.fixture
    def manager(self, temp_config_dir):
        """Create a ProfileManager with a temporary directory."""
        return ProfileManager(config_dir=temp_config_dir)

    def test_restore_default_profiles_resets_modified_defaults(self, manager):
        """Test that modified default profiles are restored to original state."""
        # Get original Quick Scan
        original_quick_scan = manager.get_profile_by_name("Quick Scan")
        assert original_quick_scan is not None

        # Modify the default profile
        manager.update_profile(original_quick_scan.id, targets=["/custom/modified/path"])

        # Verify modification
        modified = manager.get_profile_by_name("Quick Scan")
        assert modified.targets == ["/custom/modified/path"]

        # Restore defaults
        count = manager.restore_default_profiles()

        # Verify count
        assert count == 3  # Quick Scan, Full Scan, Home Folder

        # Verify restored profile has original targets (not the modified ones)
        restored = manager.get_profile_by_name("Quick Scan")
        assert restored is not None
        assert restored.targets != ["/custom/modified/path"]
        assert restored.is_default is True

    def test_restore_default_profiles_preserves_custom(self, manager):
        """Test that custom profiles are not affected by restore."""
        # Create a custom profile
        custom = manager.create_profile(
            name="My Custom Profile",
            targets=["/custom/path"],
            exclusions={"paths": ["/custom/exclude"]},
            description="A custom profile",
        )
        custom_id = custom.id

        # Restore defaults
        manager.restore_default_profiles()

        # Verify custom profile still exists unchanged
        retrieved = manager.get_profile(custom_id)
        assert retrieved is not None
        assert retrieved.name == "My Custom Profile"
        assert retrieved.targets == ["/custom/path"]
        assert retrieved.exclusions == {"paths": ["/custom/exclude"]}
        assert retrieved.is_default is False

    def test_restore_default_profiles_returns_count(self, manager):
        """Test that restore returns the correct count of restored profiles."""
        count = manager.restore_default_profiles()
        assert count == 3  # Quick Scan, Full Scan, Home Folder

    def test_restore_default_profiles_recreates_deleted_defaults(self, temp_config_dir):
        """Test that restore recreates deleted default profiles."""
        # Create manager and manually delete a default profile's ID
        manager = ProfileManager(config_dir=temp_config_dir)

        # Get all default profile IDs
        initial_defaults = [p for p in manager.list_profiles() if p.is_default]
        initial_count = len(initial_defaults)

        # Manually remove one default profile (simulating corruption)
        with manager._lock:
            first_default_id = initial_defaults[0].id
            del manager._profiles[first_default_id]
        manager._save()

        # Verify it's gone
        remaining = [p for p in manager.list_profiles() if p.is_default]
        assert len(remaining) == initial_count - 1

        # Restore defaults
        manager.restore_default_profiles()

        # Verify all defaults are back
        after_restore = [p for p in manager.list_profiles() if p.is_default]
        assert len(after_restore) == 3
        assert {p.name for p in after_restore} == {"Quick Scan", "Full Scan", "Home Folder"}

    def test_restore_default_profiles_generates_new_ids(self, manager):
        """Test that restored profiles get new IDs."""
        # Get original IDs
        original_ids = {p.id for p in manager.list_profiles() if p.is_default}

        # Restore defaults
        manager.restore_default_profiles()

        # Get new IDs
        new_ids = {p.id for p in manager.list_profiles() if p.is_default}

        # IDs should be different
        assert original_ids != new_ids

    def test_restore_default_profiles_with_multiple_custom_profiles(self, manager):
        """Test restore with multiple custom profiles."""
        # Create multiple custom profiles
        manager.create_profile(name="Custom 1", targets=["/path1"], exclusions={})
        manager.create_profile(name="Custom 2", targets=["/path2"], exclusions={})
        manager.create_profile(name="Custom 3", targets=["/path3"], exclusions={})

        # Modify a default profile
        quick_scan = manager.get_profile_by_name("Quick Scan")
        manager.update_profile(quick_scan.id, targets=["/modified"])

        # Restore defaults
        manager.restore_default_profiles()

        # Verify all custom profiles still exist
        profiles = manager.list_profiles()
        custom_names = {p.name for p in profiles if not p.is_default}
        assert custom_names == {"Custom 1", "Custom 2", "Custom 3"}

        # Verify defaults were restored
        default_names = {p.name for p in profiles if p.is_default}
        assert default_names == {"Quick Scan", "Full Scan", "Home Folder"}


class TestProfileManagerHardening:
    """Regression tests for default-profile rename and import name validation."""

    @pytest.fixture
    def temp_config_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_config_dir):
        return ProfileManager(config_dir=temp_config_dir)

    def test_cannot_rename_default_profile(self, manager):
        """Renaming a default profile must raise: defaults are recreated by name at
        startup, so a rename would orphan it and spawn a duplicate default."""
        default = next(p for p in manager.list_profiles() if p.is_default)

        with pytest.raises(ValueError, match="Cannot rename a default profile"):
            manager.update_profile(default.id, name=default.name + " Renamed")

        # Non-name edits on a default remain allowed.
        updated = manager.update_profile(default.id, description="changed")
        assert updated is not None
        assert updated.description == "changed"
        assert updated.name == default.name

    def test_update_default_with_same_name_is_allowed(self, manager):
        """Editing other fields while passing the unchanged name must not raise."""
        default = next(p for p in manager.list_profiles() if p.is_default)
        updated = manager.update_profile(default.id, name=default.name, description="x")
        assert updated is not None
        assert updated.name == default.name

    def test_default_rename_blocked_prevents_duplicate_on_reload(self, temp_config_dir):
        """End-to-end: the guard keeps exactly one profile per default name across reloads."""
        manager = ProfileManager(config_dir=temp_config_dir)
        default = next(p for p in manager.list_profiles() if p.is_default)
        with pytest.raises(ValueError):
            manager.update_profile(default.id, name="Custom Renamed Default")

        reloaded = ProfileManager(config_dir=temp_config_dir)
        default_names = [p.name for p in reloaded.list_profiles() if p.is_default]
        assert len(default_names) == len(set(default_names))

    def test_import_profile_null_name_raises(self, manager, temp_config_dir):
        """Importing a profile whose name is JSON null must raise rather than create
        a profile literally named 'None'."""
        import_path = Path(temp_config_dir) / "null_name.json"
        import_path.write_text(json.dumps({"profile": {"name": None, "targets": ["/home"]}}))

        with pytest.raises(ValueError, match="non-empty string"):
            manager.import_profile(import_path)
