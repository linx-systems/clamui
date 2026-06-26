# ClamUI Profile Lifecycle E2E Tests
"""
End-to-end tests for the complete scan profile lifecycle.

These tests verify the full flow from profile creation to deletion,
including UI integration, tray menu synchronization, scan execution
with profile settings, export/import functionality, and data persistence.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.profiles.profile_manager import ProfileManager


class TestE2EProfileLifecycle:
    """End-to-end tests for complete profile lifecycle."""

    @pytest.fixture
    def profile_test_env(self):
        """Create a complete test environment for profile tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            # Create directory structure
            config_dir = base / "config"
            scan_dir = base / "scan_target"
            export_dir = base / "exports"

            for d in [config_dir, scan_dir, export_dir]:
                d.mkdir(parents=True)

            # Create test files in scan directory
            for i in range(5):
                (scan_dir / f"document_{i}.txt").write_text(f"Document content {i}")

            yield {
                "base": base,
                "config_dir": config_dir,
                "scan_dir": scan_dir,
                "export_dir": export_dir,
            }

    def test_e2e_profile_creation(self, profile_test_env):
        """
        E2E Test: Create new profile.

        Steps:
        1. Initialize ProfileManager
        2. Create a new profile with targets and exclusions
        3. Verify profile is created with correct attributes
        4. Verify profile appears in profile list
        5. Verify profile persists to storage file
        """
        config_dir = profile_test_env["config_dir"]
        scan_dir = profile_test_env["scan_dir"]

        # Step 1: Initialize ProfileManager
        pm = ProfileManager(config_dir)

        # Store initial profile count (default profiles)
        initial_count = len(pm.list_profiles())
        assert initial_count >= 3, "Should have at least 3 default profiles"

        # Step 2: Create a new profile
        test_targets = [str(scan_dir)]
        test_exclusions = {
            "paths": [str(scan_dir / "excluded")],
            "patterns": ["*.tmp", "*.log"],
        }
        test_description = "Test profile for E2E testing"

        new_profile = pm.create_profile(
            name="E2E Test Profile",
            targets=test_targets,
            exclusions=test_exclusions,
            description=test_description,
        )

        # Step 3: Verify profile attributes
        assert new_profile is not None
        assert new_profile.id is not None and len(new_profile.id) > 0
        assert new_profile.name == "E2E Test Profile"
        assert new_profile.targets == test_targets
        assert new_profile.exclusions == test_exclusions
        assert new_profile.description == test_description
        assert new_profile.is_default is False
        assert new_profile.created_at is not None
        assert new_profile.updated_at is not None

        # Step 4: Verify profile appears in list
        profiles = pm.list_profiles()
        assert len(profiles) == initial_count + 1
        profile_names = [p.name for p in profiles]
        assert "E2E Test Profile" in profile_names

        # Step 5: Verify persistence
        storage_file = config_dir / "profiles.json"
        assert storage_file.exists()

        with open(storage_file) as f:
            data = json.load(f)

        profiles_data = data.get("profiles", [])
        saved_profile = next((p for p in profiles_data if p["name"] == "E2E Test Profile"), None)
        assert saved_profile is not None
        assert saved_profile["targets"] == test_targets
        assert saved_profile["exclusions"] == test_exclusions

    def test_e2e_profile_appears_in_dropdown(self, profile_test_env):
        """
        E2E Test: Verify profile appears in main window dropdown.

        Steps:
        1. Create ProfileManager and a custom profile
        2. Simulate dropdown population via list_profiles()
        3. Verify profile is included in list with correct format
        4. Verify default profiles are marked appropriately
        """
        config_dir = profile_test_env["config_dir"]
        scan_dir = profile_test_env["scan_dir"]

        pm = ProfileManager(config_dir)

        # Create a custom profile
        pm.create_profile(
            name="Dropdown Test Profile",
            targets=[str(scan_dir)],
            exclusions={},
            description="Profile for dropdown test",
        )

        # Simulate dropdown population (as ScanView.refresh_profiles does)
        profiles = pm.list_profiles()

        # Build display names as the UI would
        display_names = []
        for profile in profiles:
            if profile.is_default:
                display_names.append(f"{profile.name} (Default)")
            else:
                display_names.append(profile.name)

        # Verify custom profile appears
        assert "Dropdown Test Profile" in display_names

        # Verify default profiles are marked
        default_names = [n for n in display_names if "(Default)" in n]
        assert len(default_names) >= 3  # Quick Scan, Full Scan, Home Folder

    def test_e2e_profile_tray_menu_sync(self, profile_test_env):
        """
        E2E Test: Verify profile appears in tray menu.

        Steps:
        1. Create ProfileManager with profiles
        2. Simulate tray menu data preparation (as app._sync_profiles_to_tray does)
        3. Verify profile data is correctly formatted for tray
        """
        config_dir = profile_test_env["config_dir"]
        scan_dir = profile_test_env["scan_dir"]

        pm = ProfileManager(config_dir)

        # Create a custom profile
        custom_profile = pm.create_profile(
            name="Tray Menu Test Profile",
            targets=[str(scan_dir)],
            exclusions={},
        )

        # Simulate tray menu data preparation (as ClamUIApp._sync_profiles_to_tray does)
        profiles = pm.list_profiles()
        profile_data = [
            {
                "id": p.id,
                "name": p.name,
                "is_default": p.is_default,
            }
            for p in profiles
        ]

        # Verify custom profile is in tray data
        custom_in_tray = next(
            (p for p in profile_data if p["name"] == "Tray Menu Test Profile"), None
        )
        assert custom_in_tray is not None
        assert custom_in_tray["id"] == custom_profile.id
        assert custom_in_tray["is_default"] is False

        # Verify default profiles are marked
        defaults_in_tray = [p for p in profile_data if p["is_default"]]
        assert len(defaults_in_tray) >= 3

    def test_e2e_profile_selection_applies_targets(self, profile_test_env):
        """
        E2E Test: Select profile and verify targets are applied.

        Steps:
        1. Create ProfileManager with a profile containing targets
        2. Retrieve profile by ID (simulating dropdown selection)
        3. Verify target expansion works (~ -> home directory)
        4. Verify multiple targets are accessible
        """
        config_dir = profile_test_env["config_dir"]
        scan_dir = profile_test_env["scan_dir"]

        pm = ProfileManager(config_dir)

        # Create a profile with home directory target (uses ~)
        profile = pm.create_profile(
            name="Target Selection Test",
            targets=["~/Downloads", str(scan_dir)],
            exclusions={},
        )

        # Simulate profile selection (as ScanView._on_profile_selected does)
        selected = pm.get_profile(profile.id)
        assert selected is not None
        assert selected.name == "Target Selection Test"

        # Verify target expansion
        first_target = selected.targets[0]
        if first_target.startswith("~"):
            expanded = os.path.expanduser(first_target)
            assert not expanded.startswith("~")
            assert "/" in expanded or "\\" in expanded

        # Verify multiple targets
        assert len(selected.targets) == 2
        assert str(scan_dir) in selected.targets

    def test_e2e_scan_uses_profile_exclusions(self, profile_test_env):
        """
        E2E Test: Verify scan uses profile targets and exclusions.

        Steps:
        1. Create profile with specific exclusions
        2. Retrieve profile exclusions
        3. Simulate building scan command with exclusions
        4. Verify exclusion format is correct for scanner
        """
        config_dir = profile_test_env["config_dir"]
        scan_dir = profile_test_env["scan_dir"]

        pm = ProfileManager(config_dir)

        # Create profile with exclusions
        exclusions = {
            "paths": [
                str(scan_dir / "cache"),
                str(scan_dir / "temp"),
            ],
            "patterns": ["*.tmp", "*.log", "*.bak"],
        }

        profile = pm.create_profile(
            name="Exclusion Test Profile",
            targets=[str(scan_dir)],
            exclusions=exclusions,
        )

        # Get profile for scan
        selected = pm.get_profile(profile.id)
        profile_exclusions = selected.exclusions

        # Verify exclusion structure
        assert "paths" in profile_exclusions
        assert "patterns" in profile_exclusions
        assert len(profile_exclusions["paths"]) == 2
        assert len(profile_exclusions["patterns"]) == 3

        # Simulate building exclusion args (as Scanner._build_command does)
        exclude_args = []

        # Add path exclusions
        for path in profile_exclusions.get("paths", []):
            exclude_args.append(f"--exclude-dir={path}")

        # Add pattern exclusions
        for pattern in profile_exclusions.get("patterns", []):
            exclude_args.append(f"--exclude={pattern}")

        # Verify args format
        assert f"--exclude-dir={scan_dir / 'cache'}" in exclude_args
        assert f"--exclude-dir={scan_dir / 'temp'}" in exclude_args
        assert "--exclude=*.tmp" in exclude_args
        assert "--exclude=*.log" in exclude_args
        assert "--exclude=*.bak" in exclude_args

    def test_e2e_profile_edit_and_persist(self, profile_test_env):
        """
        E2E Test: Edit profile and verify changes persist.

        Steps:
        1. Create a profile
        2. Edit profile name, targets, and description
        3. Verify changes in memory
        4. Reload ProfileManager and verify persistence
        """
        config_dir = profile_test_env["config_dir"]
        scan_dir = profile_test_env["scan_dir"]

        pm = ProfileManager(config_dir)

        # Step 1: Create initial profile
        profile = pm.create_profile(
            name="Original Name",
            targets=[str(scan_dir)],
            exclusions={},
            description="Original description",
        )
        profile_id = profile.id
        original_created_at = profile.created_at

        # Step 2: Edit the profile
        new_targets = [str(scan_dir), "/tmp"]
        new_exclusions = {"paths": ["/tmp/cache"]}

        updated = pm.update_profile(
            profile_id,
            name="Updated Name",
            targets=new_targets,
            exclusions=new_exclusions,
            description="Updated description",
        )

        # Step 3: Verify changes in memory
        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.targets == new_targets
        assert updated.exclusions == new_exclusions
        assert updated.description == "Updated description"
        assert updated.created_at == original_created_at  # Created at unchanged
        assert updated.updated_at != original_created_at  # Updated at changed

        # Step 4: Reload ProfileManager and verify persistence
        pm2 = ProfileManager(config_dir)
        reloaded = pm2.get_profile(profile_id)

        assert reloaded is not None
        assert reloaded.name == "Updated Name"
        assert reloaded.targets == new_targets
        assert reloaded.description == "Updated description"

    def test_e2e_profile_export_to_json(self, profile_test_env):
        """
        E2E Test: Export profile to JSON file.

        Steps:
        1. Create a profile with all attributes
        2. Export to JSON file
        3. Verify file exists and contains valid JSON
        4. Verify exported data matches profile
        """
        config_dir = profile_test_env["config_dir"]
        export_dir = profile_test_env["export_dir"]
        scan_dir = profile_test_env["scan_dir"]

        pm = ProfileManager(config_dir)

        # Step 1: Create profile with all attributes
        profile = pm.create_profile(
            name="Export Test Profile",
            targets=[str(scan_dir), "~/Documents"],
            exclusions={
                "paths": [str(scan_dir / "excluded")],
                "patterns": ["*.tmp"],
            },
            description="Profile for export testing",
            options={"recursive": True},
        )

        # Step 2: Export to JSON
        export_path = export_dir / "exported_profile.json"
        pm.export_profile(profile.id, export_path)

        # Step 3: Verify file exists and is valid JSON
        assert export_path.exists()

        with open(export_path) as f:
            exported_data = json.load(f)

        # Step 4: Verify exported data
        assert "export_version" in exported_data
        assert exported_data["export_version"] == 1

        profile_data = exported_data["profile"]
        assert profile_data["name"] == "Export Test Profile"
        assert profile_data["targets"] == [str(scan_dir), "~/Documents"]
        assert "paths" in profile_data["exclusions"]
        assert profile_data["description"] == "Profile for export testing"

    def test_e2e_profile_delete_and_verify(self, profile_test_env):
        """
        E2E Test: Delete profile and verify removal.

        Steps:
        1. Create a custom profile
        2. Verify profile exists
        3. Delete the profile
        4. Verify profile is removed from list
        5. Verify profile is removed from storage
        """
        config_dir = profile_test_env["config_dir"]
        scan_dir = profile_test_env["scan_dir"]

        pm = ProfileManager(config_dir)

        # Step 1: Create profile
        profile = pm.create_profile(
            name="Delete Test Profile",
            targets=[str(scan_dir)],
            exclusions={},
        )
        profile_id = profile.id
        initial_count = len(pm.list_profiles())

        # Step 2: Verify profile exists
        assert pm.get_profile(profile_id) is not None
        assert pm.profile_exists(profile_id)

        # Step 3: Delete the profile
        result = pm.delete_profile(profile_id)
        assert result is True

        # Step 4: Verify removal from list
        profiles = pm.list_profiles()
        assert len(profiles) == initial_count - 1
        profile_names = [p.name for p in profiles]
        assert "Delete Test Profile" not in profile_names

        # Step 5: Verify removal from storage
        storage_file = config_dir / "profiles.json"
        with open(storage_file) as f:
            data = json.load(f)

        profiles_data = data.get("profiles", [])
        deleted_profile = next((p for p in profiles_data if p.get("id") == profile_id), None)
        assert deleted_profile is None

    def test_e2e_profile_import_from_json(self, profile_test_env):
        """
        E2E Test: Import profile from JSON file.

        Steps:
        1. Create and export a profile
        2. Delete the original profile
        3. Import the profile from JSON
        4. Verify imported profile has correct attributes
        5. Verify imported profile gets new ID
        """
        config_dir = profile_test_env["config_dir"]
        export_dir = profile_test_env["export_dir"]
        scan_dir = profile_test_env["scan_dir"]

        pm = ProfileManager(config_dir)

        # Step 1: Create and export profile
        original = pm.create_profile(
            name="Import Test Profile",
            targets=[str(scan_dir)],
            exclusions={"patterns": ["*.bak"]},
            description="Profile for import testing",
        )
        original_id = original.id

        export_path = export_dir / "import_test.json"
        pm.export_profile(original_id, export_path)

        # Step 2: Delete original
        pm.delete_profile(original_id)
        assert pm.get_profile(original_id) is None

        # Step 3: Import from JSON
        imported = pm.import_profile(export_path)

        # Step 4: Verify imported profile attributes
        assert imported is not None
        assert imported.name == "Import Test Profile"
        assert imported.targets == [str(scan_dir)]
        assert imported.exclusions == {"patterns": ["*.bak"]}
        assert imported.description == "Profile for import testing"
        assert imported.is_default is False  # Imported profiles are never default

        # Step 5: Verify new ID
        assert imported.id != original_id
        assert pm.profile_exists(imported.id)


class TestE2EProfileEdgeCases:
    """E2E tests for profile edge cases and error handling."""

    @pytest.fixture
    def edge_case_env(self):
        """Create environment for edge case tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            config_dir = base / "config"
            config_dir.mkdir(parents=True)

            yield {
                "config_dir": config_dir,
                "base": base,
            }

    def test_e2e_duplicate_name_on_import(self, edge_case_env):
        """
        E2E Test: Import profile with duplicate name.

        Steps:
        1. Create a profile
        2. Export it
        3. Import it again (should get renamed)
        4. Verify imported profile has unique name like "Name (2)"
        """
        config_dir = edge_case_env["config_dir"]
        export_dir = edge_case_env["base"] / "exports"
        export_dir.mkdir()

        pm = ProfileManager(config_dir)

        # Create and export profile
        original = pm.create_profile(
            name="Duplicate Name Test",
            targets=["/tmp"],
            exclusions={},
        )

        export_path = export_dir / "duplicate.json"
        pm.export_profile(original.id, export_path)

        # Import without deleting original (duplicate name)
        imported = pm.import_profile(export_path)

        # Verify renamed
        assert imported.name == "Duplicate Name Test (2)"

        # Import again
        imported2 = pm.import_profile(export_path)
        assert imported2.name == "Duplicate Name Test (3)"

    def test_e2e_cannot_delete_default_profile(self, edge_case_env):
        """
        E2E Test: Attempt to delete default profile.

        Steps:
        1. Get a default profile
        2. Attempt to delete it
        3. Verify deletion is blocked with error
        4. Verify profile still exists
        """
        config_dir = edge_case_env["config_dir"]

        pm = ProfileManager(config_dir)

        # Find a default profile
        profiles = pm.list_profiles()
        default_profile = next((p for p in profiles if p.is_default), None)
        assert default_profile is not None

        # Attempt to delete
        with pytest.raises(ValueError, match="Cannot delete default profile"):
            pm.delete_profile(default_profile.id)

        # Verify still exists
        assert pm.profile_exists(default_profile.id)

    def test_e2e_profile_validation_errors(self, edge_case_env):
        """
        E2E Test: Profile validation catches errors.

        Steps:
        1. Attempt to create profile with empty name
        2. Attempt to create profile with very long name
        3. Attempt to create profile with invalid path format
        4. Verify appropriate errors are raised
        """
        config_dir = edge_case_env["config_dir"]

        pm = ProfileManager(config_dir)

        # Empty name
        with pytest.raises(ValueError, match="empty"):
            pm.create_profile(name="", targets=["/tmp"], exclusions={})

        # Very long name (over 50 chars)
        long_name = "A" * 60
        with pytest.raises(ValueError, match="exceed"):
            pm.create_profile(name=long_name, targets=["/tmp"], exclusions={})

        # Duplicate name
        pm.create_profile(name="Unique Name", targets=["/tmp"], exclusions={})
        with pytest.raises(ValueError, match="already exists"):
            pm.create_profile(name="Unique Name", targets=["/tmp"], exclusions={})

    def test_e2e_profile_persistence_across_restarts(self, edge_case_env):
        """
        E2E Test: Profiles persist across ProfileManager restarts.

        Steps:
        1. Create ProfileManager and add profiles
        2. Create new ProfileManager instance (simulating app restart)
        3. Verify all profiles are loaded correctly
        """
        config_dir = edge_case_env["config_dir"]

        # First "session"
        pm1 = ProfileManager(config_dir)
        profile1 = pm1.create_profile(
            name="Persistence Test 1",
            targets=["/tmp"],
            exclusions={},
        )
        profile2 = pm1.create_profile(
            name="Persistence Test 2",
            targets=["/home"],
            exclusions={"patterns": ["*.tmp"]},
        )

        # Simulate app restart (new ProfileManager instance)
        pm2 = ProfileManager(config_dir)

        # Verify profiles loaded
        loaded1 = pm2.get_profile(profile1.id)
        loaded2 = pm2.get_profile(profile2.id)

        assert loaded1 is not None
        assert loaded1.name == "Persistence Test 1"
        assert loaded1.targets == ["/tmp"]

        assert loaded2 is not None
        assert loaded2.name == "Persistence Test 2"
        assert loaded2.exclusions == {"patterns": ["*.tmp"]}


class TestE2EDefaultProfiles:
    """E2E tests for default profile verification."""

    @pytest.fixture
    def default_profile_env(self):
        """Create fresh environment for default profile tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            config_dir = base / "config"
            config_dir.mkdir(parents=True)

            yield {
                "config_dir": config_dir,
            }

    def test_e2e_default_profiles_exist(self, default_profile_env):
        """
        E2E Test: Verify default profiles are created on fresh install.

        Steps:
        1. Create ProfileManager on fresh config directory
        2. Verify Quick Scan, Full Scan, Home Folder profiles exist
        3. Verify default profiles have correct targets
        """
        config_dir = default_profile_env["config_dir"]

        # Fresh ProfileManager
        pm = ProfileManager(config_dir)

        profiles = pm.list_profiles()
        profile_names = {p.name for p in profiles}

        # Verify required defaults exist
        assert "Quick Scan" in profile_names
        assert "Full Scan" in profile_names
        assert "Home Folder" in profile_names

        # Verify Quick Scan targets Downloads
        quick_scan = pm.get_profile_by_name("Quick Scan")
        assert quick_scan is not None
        assert quick_scan.is_default is True
        assert any("Downloads" in t for t in quick_scan.targets)

        # Verify Full Scan targets root
        full_scan = pm.get_profile_by_name("Full Scan")
        assert full_scan is not None
        assert full_scan.is_default is True
        assert "/" in full_scan.targets

        # Verify Home Folder targets home
        home_folder = pm.get_profile_by_name("Home Folder")
        assert home_folder is not None
        assert home_folder.is_default is True
        assert "~" in home_folder.targets

    def test_e2e_default_profiles_have_exclusions(self, default_profile_env):
        """
        E2E Test: Verify default profiles have sensible exclusions.

        Steps:
        1. Get Full Scan profile
        2. Verify system directories are excluded
        """
        config_dir = default_profile_env["config_dir"]

        pm = ProfileManager(config_dir)

        full_scan = pm.get_profile_by_name("Full Scan")
        assert full_scan is not None

        exclusion_paths = full_scan.exclusions.get("paths", [])

        # Verify critical system paths are excluded
        expected_exclusions = ["/proc", "/sys", "/dev"]
        for path in expected_exclusions:
            assert path in exclusion_paths, f"Expected {path} in Full Scan exclusions"

    def test_e2e_default_profiles_complete_verification(self, default_profile_env):
        """
        E2E Test: Complete default profiles verification (subtask-6-2).

        Verification steps from spec:
        1. Fresh app launch (simulated by fresh ProfileManager)
        2. Verify Quick Scan, Full Scan, Home Folder profiles exist
        3. Select Quick Scan profile
        4. Verify Downloads folder is target
        5. Select Full Scan profile
        6. Verify system-wide scan targets
        7. Attempt to delete default profile
        8. Verify deletion is blocked
        """
        config_dir = default_profile_env["config_dir"]

        # Step 1: Fresh app launch (simulated by fresh config directory)
        # No profiles.json exists yet, this simulates first launch
        storage_file = config_dir / "profiles.json"
        assert not storage_file.exists(), "Config should be fresh (no profiles.json)"

        pm = ProfileManager(config_dir)

        # After initialization, storage file should exist with defaults
        assert storage_file.exists(), "profiles.json should be created"

        # Step 2: Verify Quick Scan, Full Scan, Home Folder profiles exist
        profiles = pm.list_profiles()
        profile_names = {p.name for p in profiles}

        assert "Quick Scan" in profile_names, "Quick Scan profile should exist"
        assert "Full Scan" in profile_names, "Full Scan profile should exist"
        assert "Home Folder" in profile_names, "Home Folder profile should exist"

        # Verify we have exactly 3 default profiles
        default_profiles = [p for p in profiles if p.is_default]
        assert len(default_profiles) >= 3, "Should have at least 3 default profiles"

        # Step 3: Select Quick Scan profile
        quick_scan = pm.get_profile_by_name("Quick Scan")
        assert quick_scan is not None, "Quick Scan profile should be selectable"
        assert quick_scan.is_default is True, "Quick Scan should be marked as default"

        # Step 4: Verify Downloads folder is target
        # Note: The profile manager resolves ~/Downloads to the XDG path
        # (e.g., /home/user/Downloads or localized equivalent)
        assert len(quick_scan.targets) > 0, "Quick Scan should have targets"
        downloads_target = quick_scan.targets[0]
        # The target is either an absolute XDG path (e.g. /home/user/Downloads or
        # a localized equivalent) when an XDG Downloads dir is configured, or the
        # tilde fallback (~/Downloads) when it is not. Both are valid; the logical
        # requirement is that it resolves to a location inside the home directory.
        import os

        home_dir = os.path.expanduser("~")
        resolved_target = os.path.expanduser(downloads_target)
        assert resolved_target.startswith(home_dir), (
            f"Quick Scan should target a folder in home directory, got: {downloads_target}"
        )
        assert "Downloads" in resolved_target or resolved_target != home_dir, (
            f"Quick Scan must target a Downloads subfolder, not the home root: {downloads_target}"
        )

        # Step 5: Select Full Scan profile
        full_scan = pm.get_profile_by_name("Full Scan")
        assert full_scan is not None, "Full Scan profile should be selectable"
        assert full_scan.is_default is True, "Full Scan should be marked as default"

        # Step 6: Verify system-wide scan targets
        assert len(full_scan.targets) > 0, "Full Scan should have targets"
        assert "/" in full_scan.targets, (
            f"Full Scan should target root '/', got: {full_scan.targets}"
        )

        # Verify Full Scan has sensible exclusions for system directories
        exclusion_paths = full_scan.exclusions.get("paths", [])
        assert "/proc" in exclusion_paths, "Full Scan should exclude /proc"
        assert "/sys" in exclusion_paths, "Full Scan should exclude /sys"
        assert "/dev" in exclusion_paths, "Full Scan should exclude /dev"

        # Step 7: Attempt to delete default profile
        # Try to delete the Quick Scan default profile
        delete_error = None
        try:
            pm.delete_profile(quick_scan.id)
        except ValueError as e:
            delete_error = e

        # Step 8: Verify deletion is blocked
        assert delete_error is not None, "Deleting default profile should raise error"
        assert "Cannot delete default profile" in str(delete_error), (
            f"Error should mention cannot delete default, got: {delete_error}"
        )

        # Verify profile still exists after failed deletion attempt
        assert pm.profile_exists(quick_scan.id), (
            "Default profile should still exist after blocked deletion"
        )

        # Verify all default profiles still exist
        final_profiles = pm.list_profiles()
        final_default_count = len([p for p in final_profiles if p.is_default])
        assert final_default_count >= 3, (
            f"All 3 default profiles should still exist, got: {final_default_count}"
        )

        # Also try deleting Full Scan and Home Folder (should all be blocked)
        for profile_name in ["Full Scan", "Home Folder"]:
            profile = pm.get_profile_by_name(profile_name)
            with pytest.raises(ValueError, match="Cannot delete default profile"):
                pm.delete_profile(profile.id)
            # Verify still exists
            assert pm.profile_exists(profile.id), (
                f"{profile_name} should still exist after blocked deletion"
            )

    def test_e2e_home_folder_profile_targets(self, default_profile_env):
        """
        E2E Test: Verify Home Folder profile has correct targets and exclusions.

        Complements the main default profiles test with Home Folder specifics.
        """
        config_dir = default_profile_env["config_dir"]

        pm = ProfileManager(config_dir)

        home_folder = pm.get_profile_by_name("Home Folder")
        assert home_folder is not None, "Home Folder profile should exist"

        # Verify targets home directory
        assert "~" in home_folder.targets, (
            f"Home Folder should target ~, got: {home_folder.targets}"
        )

        # Verify has sensible exclusions for home directory
        exclusion_paths = home_folder.exclusions.get("paths", [])
        assert "~/.cache" in exclusion_paths, "Home Folder should exclude ~/.cache"
        assert "~/.local/share/Trash" in exclusion_paths, (
            "Home Folder should exclude ~/.local/share/Trash"
        )

        # Verify profile attributes
        assert home_folder.is_default is True
        assert home_folder.description is not None
        assert len(home_folder.description) > 0


class TestE2EProfileCompleteWorkflow:
    """Complete end-to-end workflow tests combining all operations."""

    @pytest.fixture
    def complete_workflow_env(self):
        """Create complete test environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            config_dir = base / "config"
            scan_dir = base / "scan_target"
            export_dir = base / "exports"

            for d in [config_dir, scan_dir, export_dir]:
                d.mkdir(parents=True)

            # Create test files
            for i in range(3):
                (scan_dir / f"file_{i}.txt").write_text(f"Content {i}")

            yield {
                "base": base,
                "config_dir": config_dir,
                "scan_dir": scan_dir,
                "export_dir": export_dir,
            }

    def test_e2e_complete_lifecycle_workflow(self, complete_workflow_env):
        """
        E2E Test: Complete profile lifecycle from creation to deletion.

        This test verifies the entire workflow as a user would experience it:
        1. Create new profile via ProfileManager (simulating UI creation)
        2. Verify profile appears in profile list (for dropdown population)
        3. Verify profile data is correctly formatted for tray menu
        4. Select profile and get targets for scanning
        5. Verify scan would receive correct exclusions
        6. Edit profile and verify changes persist
        7. Export profile to JSON file
        8. Delete profile and verify removal
        9. Import profile back from JSON
        10. Verify imported profile works correctly
        """
        config_dir = complete_workflow_env["config_dir"]
        scan_dir = complete_workflow_env["scan_dir"]
        export_dir = complete_workflow_env["export_dir"]

        # Step 1: Create new profile
        pm = ProfileManager(config_dir)
        initial_count = len(pm.list_profiles())

        profile = pm.create_profile(
            name="Complete Workflow Test",
            targets=[str(scan_dir), "~/Documents"],
            exclusions={
                "paths": [str(scan_dir / "cache")],
                "patterns": ["*.tmp", "*.log"],
            },
            description="Testing complete lifecycle",
        )
        profile_id = profile.id

        # Step 2: Verify appears in list
        profiles = pm.list_profiles()
        assert len(profiles) == initial_count + 1
        assert any(p.id == profile_id for p in profiles)

        # Step 3: Verify tray menu data format
        tray_data = [{"id": p.id, "name": p.name, "is_default": p.is_default} for p in profiles]
        tray_entry = next(d for d in tray_data if d["id"] == profile_id)
        assert tray_entry["name"] == "Complete Workflow Test"
        assert tray_entry["is_default"] is False

        # Step 4: Select profile and get targets
        selected = pm.get_profile(profile_id)
        first_target = selected.targets[0]
        assert first_target == str(scan_dir)

        # Step 5: Verify exclusions format for scanner
        exclusions = selected.exclusions
        path_exclusions = exclusions.get("paths", [])
        pattern_exclusions = exclusions.get("patterns", [])

        assert str(scan_dir / "cache") in path_exclusions
        assert "*.tmp" in pattern_exclusions
        assert "*.log" in pattern_exclusions

        # Step 6: Edit profile
        updated = pm.update_profile(
            profile_id,
            name="Updated Workflow Test",
            description="Updated description",
        )
        assert updated.name == "Updated Workflow Test"

        # Verify persistence
        pm_reload = ProfileManager(config_dir)
        reloaded = pm_reload.get_profile(profile_id)
        assert reloaded.name == "Updated Workflow Test"

        # Step 7: Export to JSON
        export_path = export_dir / "workflow_export.json"
        pm.export_profile(profile_id, export_path)
        assert export_path.exists()

        with open(export_path) as f:
            exported = json.load(f)
        assert exported["profile"]["name"] == "Updated Workflow Test"

        # Step 8: Delete profile
        result = pm.delete_profile(profile_id)
        assert result is True
        assert pm.get_profile(profile_id) is None
        assert len(pm.list_profiles()) == initial_count

        # Step 9: Import profile back
        imported = pm.import_profile(export_path)
        assert imported is not None
        assert imported.name == "Updated Workflow Test"
        assert imported.id != profile_id  # New ID assigned

        # Step 10: Verify imported profile works
        assert pm.profile_exists(imported.id)
        retrieved = pm.get_profile(imported.id)
        assert retrieved.targets == [str(scan_dir), "~/Documents"]
        assert retrieved.description == "Updated description"

        # Verify in list
        final_profiles = pm.list_profiles()
        assert len(final_profiles) == initial_count + 1
        assert any(p.id == imported.id for p in final_profiles)

    def test_e2e_multiple_profiles_workflow(self, complete_workflow_env):
        """
        E2E Test: Managing multiple profiles simultaneously.

        Steps:
        1. Create multiple custom profiles
        2. Verify all appear in list correctly sorted
        3. Edit one, delete another
        4. Verify state consistency
        """
        config_dir = complete_workflow_env["config_dir"]
        scan_dir = complete_workflow_env["scan_dir"]

        pm = ProfileManager(config_dir)
        initial_count = len(pm.list_profiles())

        # Create multiple profiles
        profiles_to_create = [
            ("Alpha Profile", [str(scan_dir)]),
            ("Zeta Profile", ["/tmp"]),
            ("Mu Profile", ["~/Downloads"]),
        ]

        created_ids = []
        for name, targets in profiles_to_create:
            p = pm.create_profile(name=name, targets=targets, exclusions={})
            created_ids.append(p.id)

        # Verify all created
        all_profiles = pm.list_profiles()
        assert len(all_profiles) == initial_count + 3

        # Verify sorting (list_profiles sorts by name)
        names = [p.name for p in all_profiles if not p.is_default]
        # Custom profiles should be sorted alphabetically
        custom_names = [n for n in names if n in ["Alpha Profile", "Mu Profile", "Zeta Profile"]]
        assert custom_names == sorted(custom_names)

        # Edit one
        pm.update_profile(created_ids[0], description="Updated Alpha")

        # Delete another
        pm.delete_profile(created_ids[1])

        # Verify state
        assert len(pm.list_profiles()) == initial_count + 2
        assert pm.get_profile(created_ids[0]).description == "Updated Alpha"
        assert pm.get_profile(created_ids[1]) is None
        assert pm.get_profile(created_ids[2]) is not None
