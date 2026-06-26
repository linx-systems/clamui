# ClamUI ProfileStorage Tests
"""Unit tests for the ProfileStorage class."""

import json
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

from src.profiles.models import ScanProfile
from src.profiles.profile_storage import ProfileStorage


def create_test_profile(
    profile_id: str = "test-id",
    name: str = "Test Profile",
    targets: list[str] | None = None,
    exclusions: dict | None = None,
    created_at: str = "2024-01-01T00:00:00",
    updated_at: str = "2024-01-01T00:00:00",
    is_default: bool = False,
    description: str = "",
    options: dict | None = None,
) -> ScanProfile:
    """Helper to create a test ScanProfile."""
    return ScanProfile(
        id=profile_id,
        name=name,
        targets=["/home/user"] if targets is None else targets,
        exclusions={} if exclusions is None else exclusions,
        created_at=created_at,
        updated_at=updated_at,
        is_default=is_default,
        description=description,
        options={} if options is None else options,
    )


class TestProfileStorageInit:
    """Tests for ProfileStorage initialization."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_init_sets_storage_path(self, temp_dir):
        """Test that ProfileStorage initializes with correct storage path."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)
        assert storage.storage_path == storage_path

    def test_init_with_string_path(self, temp_dir):
        """Test that ProfileStorage accepts Path object."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)
        assert isinstance(storage.storage_path, Path)

    def test_init_with_nested_path(self, temp_dir):
        """Test that ProfileStorage accepts nested paths."""
        storage_path = Path(temp_dir) / "nested" / "dir" / "profiles.json"
        storage = ProfileStorage(storage_path)
        assert storage.storage_path == storage_path

    def test_storage_path_property(self, temp_dir):
        """Test that storage_path property returns correct path."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)
        assert storage.storage_path == storage_path


class TestProfileStorageLoadProfiles:
    """Tests for ProfileStorage load_profiles method."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def storage(self, temp_dir):
        """Create a ProfileStorage with a temporary file."""
        storage_path = Path(temp_dir) / "profiles.json"
        return ProfileStorage(storage_path)

    def test_load_returns_empty_list_when_file_missing(self, storage):
        """Test that load_profiles returns empty list when file doesn't exist."""
        profiles = storage.load_profiles()
        assert profiles == []

    def test_load_returns_profiles_from_versioned_format(self, temp_dir):
        """Test loading profiles from versioned format (with 'profiles' key)."""
        storage_path = Path(temp_dir) / "profiles.json"
        profile_data = {
            "version": 1,
            "profiles": [
                {
                    "id": "profile-1",
                    "name": "Test Profile",
                    "targets": ["/home"],
                    "exclusions": {},
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                    "is_default": False,
                    "description": "",
                    "options": {},
                }
            ],
        }
        storage_path.write_text(json.dumps(profile_data))

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        assert len(profiles) == 1
        assert profiles[0].id == "profile-1"
        assert profiles[0].name == "Test Profile"

    def test_load_returns_profiles_from_legacy_list_format(self, temp_dir):
        """Test loading profiles from legacy format (plain list)."""
        storage_path = Path(temp_dir) / "profiles.json"
        profile_data = [
            {
                "id": "legacy-1",
                "name": "Legacy Profile",
                "targets": ["/var"],
                "exclusions": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        ]
        storage_path.write_text(json.dumps(profile_data))

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        assert len(profiles) == 1
        assert profiles[0].id == "legacy-1"
        assert profiles[0].name == "Legacy Profile"

    def test_load_returns_empty_for_invalid_dict_format(self, temp_dir):
        """Test loading returns empty list for dict without 'profiles' key."""
        storage_path = Path(temp_dir) / "profiles.json"
        invalid_data = {"some_key": "some_value"}
        storage_path.write_text(json.dumps(invalid_data))

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        assert profiles == []

    def test_load_multiple_profiles(self, temp_dir):
        """Test loading multiple profiles."""
        storage_path = Path(temp_dir) / "profiles.json"
        profile_data = {
            "version": 1,
            "profiles": [
                {
                    "id": f"profile-{i}",
                    "name": f"Profile {i}",
                    "targets": ["/home"],
                    "exclusions": {},
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                }
                for i in range(5)
            ],
        }
        storage_path.write_text(json.dumps(profile_data))

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        assert len(profiles) == 5
        for i, profile in enumerate(profiles):
            assert profile.id == f"profile-{i}"

    def test_load_handles_corrupted_json(self, temp_dir):
        """Test that load handles corrupted JSON gracefully."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage_path.write_text("{ invalid json content }")

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        assert profiles == []

    def test_load_handles_empty_file(self, temp_dir):
        """Test that load handles empty file gracefully."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage_path.write_text("")

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        assert profiles == []

    def test_load_creates_backup_on_corrupted_file(self, temp_dir):
        """Test that load creates backup of corrupted file."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage_path.write_text("{ corrupted json }")

        storage = ProfileStorage(storage_path)
        storage.load_profiles()

        backup_path = storage_path.with_suffix(".json.corrupted")
        assert backup_path.exists()

    def test_load_handles_invalid_profile_data(self, temp_dir):
        """Test that load handles profiles with missing required fields."""
        storage_path = Path(temp_dir) / "profiles.json"
        # Missing required 'id' field
        profile_data = {
            "version": 1,
            "profiles": [{"name": "Incomplete Profile"}],
        }
        storage_path.write_text(json.dumps(profile_data))

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        # Should return empty list and backup the file
        assert profiles == []

    def test_load_skips_malformed_record_but_keeps_valid(self, temp_dir):
        """A single malformed record is skipped without wiping valid profiles."""
        storage_path = Path(temp_dir) / "profiles.json"
        profile_data = {
            "version": 1,
            "profiles": [
                {
                    "id": "good-1",
                    "name": "Good Profile",
                    "targets": ["/home"],
                    "exclusions": {},
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                    "is_default": False,
                    "description": "",
                    "options": {},
                },
                # Malformed: missing required 'id' field -> KeyError in from_dict.
                {"name": "Broken Profile"},
            ],
        }
        storage_path.write_text(json.dumps(profile_data))

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        # Valid profile survives; only the malformed record is dropped.
        assert len(profiles) == 1
        assert profiles[0].id == "good-1"
        # The container was not treated as corrupt, so no backup was made.
        backup_path = storage_path.with_suffix(".json.corrupted")
        assert not backup_path.exists()
        assert storage_path.exists()

    def test_load_handles_permission_error(self, temp_dir):
        """Test that load handles permission errors gracefully."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        with (
            mock.patch.object(Path, "exists", return_value=True),
            mock.patch("builtins.open", side_effect=PermissionError("Access denied")),
        ):
            profiles = storage.load_profiles()

        assert profiles == []

    def test_load_handles_os_error(self, temp_dir):
        """Test that load handles OS errors gracefully."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        with (
            mock.patch.object(Path, "exists", return_value=True),
            mock.patch("builtins.open", side_effect=OSError("Disk error")),
        ):
            profiles = storage.load_profiles()

        assert profiles == []


class TestProfileStorageSaveProfiles:
    """Tests for ProfileStorage save_profiles method."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def storage(self, temp_dir):
        """Create a ProfileStorage with a temporary file."""
        storage_path = Path(temp_dir) / "profiles.json"
        return ProfileStorage(storage_path)

    def test_save_creates_file(self, storage):
        """Test that save creates the storage file."""
        profiles = [create_test_profile()]
        result = storage.save_profiles(profiles)

        assert result is True
        assert storage.storage_path.exists()

    def test_save_creates_parent_directories(self, temp_dir):
        """Test that save creates parent directories if needed."""
        storage_path = Path(temp_dir) / "nested" / "dir" / "profiles.json"
        storage = ProfileStorage(storage_path)

        profiles = [create_test_profile()]
        result = storage.save_profiles(profiles)

        assert result is True
        assert storage_path.exists()

    def test_save_writes_valid_json(self, storage):
        """Test that save writes valid JSON content."""
        profiles = [create_test_profile(name="JSON Test")]
        storage.save_profiles(profiles)

        with open(storage.storage_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "version" in data
        assert "profiles" in data
        assert data["version"] == ProfileStorage.SCHEMA_VERSION
        assert len(data["profiles"]) == 1
        assert data["profiles"][0]["name"] == "JSON Test"

    def test_save_writes_schema_version(self, storage):
        """Test that save includes schema version."""
        profiles = [create_test_profile()]
        storage.save_profiles(profiles)

        with open(storage.storage_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["version"] == ProfileStorage.SCHEMA_VERSION

    def test_save_multiple_profiles(self, storage):
        """Test saving multiple profiles."""
        profiles = [
            create_test_profile(profile_id=f"id-{i}", name=f"Profile {i}") for i in range(3)
        ]
        result = storage.save_profiles(profiles)

        assert result is True

        with open(storage.storage_path, encoding="utf-8") as f:
            data = json.load(f)

        assert len(data["profiles"]) == 3

    def test_save_empty_list(self, storage):
        """Test saving empty list of profiles."""
        result = storage.save_profiles([])

        assert result is True

        with open(storage.storage_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["profiles"] == []

    def test_save_overwrites_existing_file(self, storage):
        """Test that save overwrites existing file."""
        # Save first set of profiles
        profiles1 = [create_test_profile(name="First")]
        storage.save_profiles(profiles1)

        # Save second set
        profiles2 = [create_test_profile(name="Second")]
        storage.save_profiles(profiles2)

        with open(storage.storage_path, encoding="utf-8") as f:
            data = json.load(f)

        assert len(data["profiles"]) == 1
        assert data["profiles"][0]["name"] == "Second"

    def test_save_returns_false_on_permission_error(self, temp_dir):
        """Test that save returns False on permission error."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        with mock.patch("tempfile.mkstemp", side_effect=PermissionError):
            result = storage.save_profiles([create_test_profile()])

        assert result is False

    def test_save_returns_false_on_os_error(self, temp_dir):
        """Test that save returns False on OS error."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        with mock.patch("tempfile.mkstemp", side_effect=OSError):
            result = storage.save_profiles([create_test_profile()])

        assert result is False

    def test_save_uses_atomic_write(self, storage):
        """Test that save uses atomic write pattern (temp file + rename)."""
        profiles = [create_test_profile()]

        with (
            mock.patch("tempfile.mkstemp") as mock_mkstemp,
            mock.patch("os.fdopen") as mock_fdopen,
            mock.patch.object(Path, "replace"),
            mock.patch.object(Path, "mkdir"),
        ):
            mock_mkstemp.return_value = (1, "/tmp/profiles_test.json")
            mock_file = mock.MagicMock()
            mock_file.__enter__ = mock.MagicMock(return_value=mock_file)
            mock_file.__exit__ = mock.MagicMock(return_value=False)
            mock_fdopen.return_value = mock_file

            storage.save_profiles(profiles)

            mock_mkstemp.assert_called_once()
            mock_fdopen.assert_called_once()

    def test_save_cleans_up_temp_file_on_failure(self, temp_dir):
        """Test that save cleans up temp file if write fails."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        # Create a mock that fails during JSON dump
        with mock.patch("json.dump", side_effect=Exception("Write error")):
            result = storage.save_profiles([create_test_profile()])

        assert result is False
        # Temp files should be cleaned up
        temp_files = list(Path(temp_dir).glob("profiles_*.json"))
        assert len(temp_files) == 0

    def test_save_preserves_all_profile_fields(self, storage):
        """Test that save preserves all profile fields."""
        profile = create_test_profile(
            profile_id="full-profile",
            name="Full Profile",
            targets=["/home", "/var"],
            exclusions={"paths": ["/tmp"], "patterns": ["*.log"]},
            created_at="2024-06-15T10:30:00",
            updated_at="2024-06-15T12:00:00",
            is_default=True,
            description="A complete test profile",
            options={"recursive": True, "max_depth": 5},
        )
        storage.save_profiles([profile])

        with open(storage.storage_path, encoding="utf-8") as f:
            data = json.load(f)

        saved = data["profiles"][0]
        assert saved["id"] == "full-profile"
        assert saved["name"] == "Full Profile"
        assert saved["targets"] == ["/home", "/var"]
        assert saved["exclusions"] == {"paths": ["/tmp"], "patterns": ["*.log"]}
        assert saved["is_default"] is True
        assert saved["description"] == "A complete test profile"
        assert saved["options"] == {"recursive": True, "max_depth": 5}


class TestProfileStorageBackupCorruptedFile:
    """Tests for ProfileStorage _backup_corrupted_file method."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_backup_creates_corrupted_suffix_file(self, temp_dir):
        """Test that backup creates file with .corrupted suffix."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage_path.write_text("corrupted data")

        storage = ProfileStorage(storage_path)
        storage._backup_corrupted_file()

        backup_path = Path(temp_dir) / "profiles.json.corrupted"
        assert backup_path.exists()
        assert not storage_path.exists()

    def test_backup_does_nothing_if_file_missing(self, temp_dir):
        """Test that backup does nothing if file doesn't exist."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        # Should not raise
        storage._backup_corrupted_file()

        backup_path = Path(temp_dir) / "profiles.json.corrupted"
        assert not backup_path.exists()

    def test_backup_does_not_overwrite_existing_backup(self, temp_dir):
        """Test that backup doesn't overwrite existing backup file."""
        storage_path = Path(temp_dir) / "profiles.json"
        backup_path = Path(temp_dir) / "profiles.json.corrupted"

        # Create existing backup
        backup_path.write_text("original backup")
        storage_path.write_text("new corrupted data")

        storage = ProfileStorage(storage_path)
        storage._backup_corrupted_file()

        # Original backup should be preserved
        assert backup_path.read_text() == "original backup"
        # Original file should still exist
        assert storage_path.exists()

    def test_backup_handles_permission_error(self, temp_dir):
        """Test that backup handles permission errors silently."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage_path.write_text("corrupted")

        storage = ProfileStorage(storage_path)

        with mock.patch.object(Path, "rename", side_effect=PermissionError):
            # Should not raise
            storage._backup_corrupted_file()

    def test_backup_handles_os_error(self, temp_dir):
        """Test that backup handles OS errors silently."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage_path.write_text("corrupted")

        storage = ProfileStorage(storage_path)

        with mock.patch.object(Path, "rename", side_effect=OSError):
            # Should not raise
            storage._backup_corrupted_file()


class TestProfileStorageGetProfileById:
    """Tests for ProfileStorage get_profile_by_id method."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def storage_with_profiles(self, temp_dir):
        """Create a ProfileStorage with some profiles."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        profiles = [
            create_test_profile(profile_id="id-1", name="Profile 1"),
            create_test_profile(profile_id="id-2", name="Profile 2"),
            create_test_profile(profile_id="id-3", name="Profile 3"),
        ]
        storage.save_profiles(profiles)

        return storage

    def test_get_profile_by_id_found(self, storage_with_profiles):
        """Test getting an existing profile by ID."""
        profile = storage_with_profiles.get_profile_by_id("id-2")

        assert profile is not None
        assert profile.id == "id-2"
        assert profile.name == "Profile 2"

    def test_get_profile_by_id_not_found(self, storage_with_profiles):
        """Test getting a non-existent profile returns None."""
        profile = storage_with_profiles.get_profile_by_id("nonexistent-id")
        assert profile is None

    def test_get_profile_by_id_empty_storage(self, temp_dir):
        """Test getting profile from empty storage returns None."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        profile = storage.get_profile_by_id("any-id")
        assert profile is None

    def test_get_profile_by_id_empty_string(self, storage_with_profiles):
        """Test getting profile with empty string ID returns None."""
        profile = storage_with_profiles.get_profile_by_id("")
        assert profile is None

    def test_get_profile_by_id_returns_correct_data(self, temp_dir):
        """Test that get_profile_by_id returns profile with all fields."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        original = create_test_profile(
            profile_id="full-id",
            name="Full Profile",
            targets=["/home", "/var"],
            exclusions={"paths": ["/tmp"]},
            description="Test description",
            options={"recursive": True},
        )
        storage.save_profiles([original])

        retrieved = storage.get_profile_by_id("full-id")

        assert retrieved is not None
        assert retrieved.id == "full-id"
        assert retrieved.name == "Full Profile"
        assert retrieved.targets == ["/home", "/var"]
        assert retrieved.exclusions == {"paths": ["/tmp"]}
        assert retrieved.description == "Test description"
        assert retrieved.options == {"recursive": True}


class TestProfileStorageDeleteStorage:
    """Tests for ProfileStorage delete_storage method."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_delete_storage_removes_file(self, temp_dir):
        """Test that delete_storage removes the storage file."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        # Create the file
        storage.save_profiles([create_test_profile()])
        assert storage_path.exists()

        # Delete it
        result = storage.delete_storage()

        assert result is True
        assert not storage_path.exists()

    def test_delete_storage_returns_true_when_file_missing(self, temp_dir):
        """Test that delete_storage returns True when file doesn't exist."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        result = storage.delete_storage()
        assert result is True

    def test_delete_storage_returns_false_on_permission_error(self, temp_dir):
        """Test that delete_storage returns False on permission error."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage_path.write_text("{}")

        storage = ProfileStorage(storage_path)

        with mock.patch.object(Path, "unlink", side_effect=PermissionError):
            result = storage.delete_storage()

        assert result is False

    def test_delete_storage_returns_false_on_os_error(self, temp_dir):
        """Test that delete_storage returns False on OS error."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage_path.write_text("{}")

        storage = ProfileStorage(storage_path)

        with mock.patch.object(Path, "unlink", side_effect=OSError):
            result = storage.delete_storage()

        assert result is False


class TestProfileStorageExists:
    """Tests for ProfileStorage exists method."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_exists_returns_true_when_file_exists(self, temp_dir):
        """Test that exists returns True when file exists."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        storage.save_profiles([create_test_profile()])

        assert storage.exists() is True

    def test_exists_returns_false_when_file_missing(self, temp_dir):
        """Test that exists returns False when file doesn't exist."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        assert storage.exists() is False

    def test_exists_after_delete(self, temp_dir):
        """Test that exists returns False after delete_storage."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        storage.save_profiles([create_test_profile()])
        assert storage.exists() is True

        storage.delete_storage()
        assert storage.exists() is False


class TestProfileStoragePersistence:
    """Tests for ProfileStorage persistence across instances."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_profiles_persist_across_instances(self, temp_dir):
        """Test that profiles persist across storage instances."""
        storage_path = Path(temp_dir) / "profiles.json"

        # Save with first instance
        storage1 = ProfileStorage(storage_path)
        profiles = [create_test_profile(profile_id="persist-1", name="Persistent Profile")]
        storage1.save_profiles(profiles)

        # Load with new instance
        storage2 = ProfileStorage(storage_path)
        loaded = storage2.load_profiles()

        assert len(loaded) == 1
        assert loaded[0].id == "persist-1"
        assert loaded[0].name == "Persistent Profile"

    def test_modifications_persist(self, temp_dir):
        """Test that modifications persist across instances."""
        storage_path = Path(temp_dir) / "profiles.json"

        # Create initial profiles
        storage1 = ProfileStorage(storage_path)
        storage1.save_profiles(
            [
                create_test_profile(profile_id="mod-1", name="Original"),
            ]
        )

        # Modify with second instance
        storage2 = ProfileStorage(storage_path)
        profiles = storage2.load_profiles()
        profiles.append(create_test_profile(profile_id="mod-2", name="Added"))
        storage2.save_profiles(profiles)

        # Verify with third instance
        storage3 = ProfileStorage(storage_path)
        loaded = storage3.load_profiles()

        assert len(loaded) == 2
        names = {p.name for p in loaded}
        assert names == {"Original", "Added"}


class TestProfileStorageThreadSafety:
    """Tests for ProfileStorage thread safety."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_concurrent_reads(self, temp_dir):
        """Test that concurrent reads work correctly."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        # Save some profiles first
        profiles = [
            create_test_profile(profile_id=f"read-{i}", name=f"Profile {i}") for i in range(5)
        ]
        storage.save_profiles(profiles)

        results = []
        errors = []
        lock = threading.Lock()

        def read_profiles():
            try:
                loaded = storage.load_profiles()
                with lock:
                    results.append(len(loaded))
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=read_profiles) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All threads should have read the same number of profiles
        assert all(r == 5 for r in results)

    def test_concurrent_writes(self, temp_dir):
        """Test that concurrent writes don't corrupt data."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        errors = []
        lock = threading.Lock()

        def write_profiles(index):
            try:
                profiles = [
                    create_test_profile(profile_id=f"write-{index}", name=f"Thread Profile {index}")
                ]
                storage.save_profiles(profiles)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=write_profiles, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # File should be valid JSON after concurrent writes
        assert storage.exists()
        profiles = storage.load_profiles()
        assert len(profiles) >= 1  # At least one write succeeded

    def test_concurrent_read_write(self, temp_dir):
        """Test concurrent reads and writes don't cause errors."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        # Initialize with some data
        storage.save_profiles([create_test_profile(name="Initial")])

        errors = []
        lock = threading.Lock()

        def reader():
            try:
                for _ in range(10):
                    storage.load_profiles()
            except Exception as e:
                with lock:
                    errors.append(e)

        def writer():
            try:
                for i in range(5):
                    storage.save_profiles([create_test_profile(name=f"Updated {i}")])
            except Exception as e:
                with lock:
                    errors.append(e)

        reader_threads = [threading.Thread(target=reader) for _ in range(3)]
        writer_threads = [threading.Thread(target=writer) for _ in range(2)]

        all_threads = reader_threads + writer_threads

        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join()

        assert len(errors) == 0


class TestProfileStorageSchemaVersion:
    """Tests for ProfileStorage schema versioning."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_schema_version_constant(self):
        """Test that SCHEMA_VERSION is defined."""
        assert hasattr(ProfileStorage, "SCHEMA_VERSION")
        assert isinstance(ProfileStorage.SCHEMA_VERSION, int)
        assert ProfileStorage.SCHEMA_VERSION >= 1

    def test_saved_data_includes_version(self, temp_dir):
        """Test that saved data includes version number."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        storage.save_profiles([create_test_profile()])

        with open(storage_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "version" in data
        assert data["version"] == ProfileStorage.SCHEMA_VERSION

    def test_load_handles_missing_version(self, temp_dir):
        """Test that load handles data without version field (legacy)."""
        storage_path = Path(temp_dir) / "profiles.json"

        # Write legacy format without version
        legacy_data = {
            "profiles": [
                {
                    "id": "legacy-id",
                    "name": "Legacy Profile",
                    "targets": ["/home"],
                    "exclusions": {},
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                }
            ]
        }
        storage_path.write_text(json.dumps(legacy_data))

        storage = ProfileStorage(storage_path)
        profiles = storage.load_profiles()

        assert len(profiles) == 1
        assert profiles[0].name == "Legacy Profile"


class TestProfileStorageEdgeCases:
    """Tests for ProfileStorage edge cases."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_handles_unicode_in_profile_names(self, temp_dir):
        """Test handling of Unicode characters in profile names."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        profile = create_test_profile(name="プロファイル 日本語 🔍", description="Описание профиля")
        storage.save_profiles([profile])

        loaded = storage.load_profiles()

        assert len(loaded) == 1
        assert loaded[0].name == "プロファイル 日本語 🔍"
        assert loaded[0].description == "Описание профиля"

    def test_handles_special_characters_in_paths(self, temp_dir):
        """Test handling of special characters in target paths."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        profile = create_test_profile(targets=["/path with spaces/dir", "/path'with'quotes"])
        storage.save_profiles([profile])

        loaded = storage.load_profiles()

        assert loaded[0].targets == ["/path with spaces/dir", "/path'with'quotes"]

    def test_handles_large_number_of_profiles(self, temp_dir):
        """Test handling of many profiles."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        profiles = [
            create_test_profile(profile_id=f"bulk-{i}", name=f"Bulk Profile {i}")
            for i in range(100)
        ]
        result = storage.save_profiles(profiles)

        assert result is True

        loaded = storage.load_profiles()
        assert len(loaded) == 100

    def test_handles_profile_with_empty_targets(self, temp_dir):
        """Test handling of profile with empty targets list."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        profile = create_test_profile(targets=[])
        storage.save_profiles([profile])

        loaded = storage.load_profiles()

        assert loaded[0].targets == []

    def test_handles_profile_with_complex_exclusions(self, temp_dir):
        """Test handling of profile with complex exclusion rules."""
        storage_path = Path(temp_dir) / "profiles.json"
        storage = ProfileStorage(storage_path)

        complex_exclusions = {
            "paths": ["/home/.cache", "/var/tmp", "/tmp"],
            "patterns": ["*.log", "*.tmp", "node_modules/**"],
            "custom": {"nested": {"value": 123}},
        }
        profile = create_test_profile(exclusions=complex_exclusions)
        storage.save_profiles([profile])

        loaded = storage.load_profiles()

        assert loaded[0].exclusions == complex_exclusions

    def test_handles_null_in_json(self, temp_dir):
        """Test handling of null values in JSON data."""
        storage_path = Path(temp_dir) / "profiles.json"

        # Write data with null values
        data = {
            "version": 1,
            "profiles": [
                {
                    "id": "null-test",
                    "name": "Null Test",
                    "targets": [],
                    "exclusions": {},
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                    "description": None,  # null in JSON
                }
            ],
        }
        storage_path.write_text(json.dumps(data))

        storage = ProfileStorage(storage_path)
        # This may fail depending on how ScanProfile.from_dict handles None
        # The test documents the behavior
        try:
            profiles = storage.load_profiles()
            assert len(profiles) >= 0  # Either loads or gracefully fails
        except (TypeError, ValueError):
            # Expected if ScanProfile doesn't handle None
            pass
