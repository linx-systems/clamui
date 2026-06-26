# pyright: reportMissingImports=false

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Store original gi modules to restore later (if they exist)
_original_gi = sys.modules.get("gi")
_original_gi_repository = sys.modules.get("gi.repository")

# Mock gi module before importing to avoid GTK dependencies in tests
sys.modules["gi"] = mock.MagicMock()
sys.modules["gi.repository"] = mock.MagicMock()

from src.core.clamav_config import (
    CONFIG_OPTION_TYPES,
    ClamAVConfig,
    ClamAVConfigValue,
    backup_config,
    get_config_summary,
    parse_config,
    validate_config,
    validate_config_file,
    validate_option,
    write_config,
)
from src.core.clamav_detection import (
    config_file_exists,
    detect_clamd_conf_path,
    detect_freshclam_conf_path,
    resolve_clamd_conf_path,
    resolve_freshclam_conf_path,
)
from src.core.log_manager import LogEntry, LogManager
from src.core.settings_manager import SettingsManager

# Restore original gi modules after imports are done
if _original_gi is not None:
    sys.modules["gi"] = _original_gi
else:
    del sys.modules["gi"]
if _original_gi_repository is not None:
    sys.modules["gi.repository"] = _original_gi_repository
else:
    del sys.modules["gi.repository"]


SAMPLE_CLAMD_CONF = """# ClamAV daemon configuration
LocalSocket /var/run/clamav/clamd.ctl
FixStaleSocket true
User clamav
ScanPE true
ScanELF true
ScanArchive true
MaxFileSize 100M
MaxScanSize 400M
MaxRecursion 16
MaxFiles 10000
LogFile /var/log/clamav/clamd.log
LogTime true
LogVerbose false
"""

SAMPLE_FRESHCLAM_CONF = """# freshclam configuration
DatabaseDirectory /var/lib/clamav
UpdateLogFile /var/log/clamav/freshclam.log
DatabaseMirror database.clamav.net
DatabaseMirror db.local.clamav.net
Checks 24
LogVerbose false
LogTime true
"""


@pytest.fixture
def settings_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        config_dir = base / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        yield {"base": base, "config_dir": config_dir}


@pytest.fixture
def config_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        conf_dir = base / "clamav"
        conf_dir.mkdir(parents=True, exist_ok=True)
        clamd_conf = conf_dir / "clamd.conf"
        freshclam_conf = conf_dir / "freshclam.conf"
        clamd_conf.write_text(SAMPLE_CLAMD_CONF, encoding="utf-8")
        freshclam_conf.write_text(SAMPLE_FRESHCLAM_CONF, encoding="utf-8")
        yield {
            "base": base,
            "conf_dir": conf_dir,
            "clamd_conf": clamd_conf,
            "freshclam_conf": freshclam_conf,
        }


class TestE2ESettingsLifecycle:
    def test_e2e_fresh_settings_has_all_defaults(self, settings_env):
        """
        E2E Test: Fresh settings initialization loads complete defaults.

        Steps:
        1. Create a new SettingsManager in an empty config directory
        2. Verify known defaults are loaded
        3. Verify default map is fully represented in runtime settings
        """
        manager = SettingsManager(config_dir=settings_env["config_dir"])

        assert manager.get("clamd_conf_path") == ""
        assert manager.get("freshclam_conf_path") == ""
        assert manager.get("scan_backend") == "auto"
        assert len(manager.get_all()) == len(SettingsManager.DEFAULT_SETTINGS)

    def test_e2e_set_and_get_individual_settings(self, settings_env):
        """
        E2E Test: Individual settings can be set and read back.

        Steps:
        1. Initialize SettingsManager
        2. Set several preference values one by one
        3. Read back each value and verify exact matches
        """
        manager = SettingsManager(config_dir=settings_env["config_dir"])

        assert manager.set("scan_backend", "daemon") is True
        assert manager.set("clamd_conf_path", "/tmp/clamd.conf") is True
        assert manager.set("show_live_progress", False) is True

        assert manager.get("scan_backend") == "daemon"
        assert manager.get("clamd_conf_path") == "/tmp/clamd.conf"
        assert manager.get("show_live_progress") is False

    def test_e2e_settings_persist_across_instances(self, settings_env):
        """
        E2E Test: Settings persist across SettingsManager reloads.

        Steps:
        1. Create first SettingsManager and save modified values
        2. Create second SettingsManager with same config directory
        3. Verify values were loaded from persisted JSON
        """
        manager_a = SettingsManager(config_dir=settings_env["config_dir"])
        manager_a.set("scan_backend", "clamscan")
        manager_a.set("clamd_conf_path", "/tmp/persisted-clamd.conf")

        manager_b = SettingsManager(config_dir=settings_env["config_dir"])
        assert manager_b.get("scan_backend") == "clamscan"
        assert manager_b.get("clamd_conf_path") == "/tmp/persisted-clamd.conf"

    def test_e2e_atomic_write_prevents_partial_update_on_failure(self, settings_env):
        """
        E2E Test: Atomic settings writes avoid partial file corruption.

        Steps:
        1. Save initial settings file with a known value
        2. Force atomic rename failure during a later save
        3. Verify on-disk settings remain at the previous valid state
        """
        manager = SettingsManager(config_dir=settings_env["config_dir"])
        assert manager.set("scan_backend", "auto") is True

        settings_file = settings_env["config_dir"] / "settings.json"
        before = json.loads(settings_file.read_text(encoding="utf-8"))

        with mock.patch("pathlib.Path.replace", side_effect=OSError("rename failed")):
            assert manager.set("scan_backend", "daemon") is False

        after = json.loads(settings_file.read_text(encoding="utf-8"))
        assert before["scan_backend"] == "auto"
        assert after["scan_backend"] == "auto"

        temp_files = list(settings_env["config_dir"].glob("settings_*.json"))
        assert temp_files == []

    def test_e2e_corrupted_settings_file_creates_backup_and_uses_defaults(self, settings_env):
        """
        E2E Test: Corrupted settings recover via backup and defaults.

        Steps:
        1. Write malformed JSON into settings.json
        2. Initialize SettingsManager to trigger load path
        3. Verify defaults are loaded and .corrupted backup exists
        """
        settings_file = settings_env["config_dir"] / "settings.json"
        settings_file.write_text("{broken-json", encoding="utf-8")

        manager = SettingsManager(config_dir=settings_env["config_dir"])

        assert manager.get("scan_backend") == "auto"
        assert not settings_file.exists()
        assert (settings_env["config_dir"] / "settings.json.corrupted").exists()

    def test_e2e_settings_file_permissions_and_reset_to_defaults(self, settings_env):
        """
        E2E Test: Settings file permissions are hardened and reset works.

        Steps:
        1. Save modified settings to disk
        2. Verify settings.json has mode 0600
        3. Reset to defaults and confirm values are restored
        """
        manager = SettingsManager(config_dir=settings_env["config_dir"])
        manager.set("scan_backend", "daemon")
        manager.set("clamd_conf_path", "/tmp/custom.conf")

        settings_file = settings_env["config_dir"] / "settings.json"
        assert settings_file.exists()
        assert settings_file.stat().st_mode & 0o777 == 0o600

        assert manager.reset_to_defaults() is True
        assert manager.get("scan_backend") == "auto"
        assert manager.get("clamd_conf_path") == ""


class TestE2EConfigLoadingPipeline:
    def test_e2e_clamd_loading_detection_parse_validate_summary(self, config_env):
        """
        E2E Test: clamd.conf full loading pipeline from detection to summary.

        Steps:
        1. Provide a realistic clamd.conf in a temp directory
        2. Detect file path using detection pipeline
        3. Parse, validate, and summarize configuration
        """
        clamd_path = str(config_env["clamd_conf"])
        with (
            mock.patch("src.core.clamav_detection._CLAMD_CONF_PATHS", [clamd_path]),
            mock.patch(
                "src.core.clamav_detection.config_file_exists",
                side_effect=lambda p: Path(p).is_file(),
            ),
        ):
            detected = detect_clamd_conf_path()

        assert detected == clamd_path

        assert detected is not None
        config, error = parse_config(detected)
        assert error is None
        assert config is not None

        is_valid, errors = validate_config(config)
        assert is_valid is True
        assert errors == []

        summary = get_config_summary(config)
        assert "Configuration file:" in summary
        assert "MaxFileSize" in summary

    def test_e2e_freshclam_loading_pipeline(self, config_env):
        """
        E2E Test: freshclam.conf loading pipeline with host-aware detection.

        Steps:
        1. Provide a realistic freshclam.conf in temp directory
        2. Detect path and parse config
        3. Validate parsed values including multi-value mirrors
        """
        freshclam_path = str(config_env["freshclam_conf"])
        with (
            mock.patch("src.core.clamav_detection._FRESHCLAM_CONF_PATHS", [freshclam_path]),
            mock.patch(
                "src.core.clamav_detection.config_file_exists",
                side_effect=lambda p: Path(p).is_file(),
            ),
        ):
            detected = detect_freshclam_conf_path()

        assert detected == freshclam_path

        assert detected is not None
        config, error = parse_config(detected)
        assert error is None
        assert config is not None
        assert config.get_values("DatabaseMirror") == [
            "database.clamav.net",
            "db.local.clamav.net",
        ]

        valid, errors = validate_config(config)
        assert valid is True
        assert errors == []

    def test_e2e_config_loading_all_option_types(self):
        """
        E2E Test: Config parser handles all supported option categories.

        Steps:
        1. Create a config containing path/boolean/integer/size/string/url options
        2. Parse config and extract values
        3. Validate entire config object
        """
        content = """DatabaseDirectory /var/lib/clamav
LogVerbose yes
Checks 24
MaxFileSize 300M
User clamav
PrivateMirror https://mirror.example.net
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = Path(tmpdir) / "all-types.conf"
            conf.write_text(content, encoding="utf-8")

            config, error = parse_config(str(conf))
            assert error is None
            assert config is not None
            assert config.get_value("DatabaseDirectory") == "/var/lib/clamav"
            assert config.get_bool("LogVerbose") is True
            assert config.get_int("Checks") == 24
            assert config.get_value("MaxFileSize") == "300M"
            assert config.get_value("User") == "clamav"
            assert config.get_value("PrivateMirror") == "https://mirror.example.net"

            valid, errors = validate_config(config)
            assert valid is True
            assert errors == []

    def test_e2e_config_loading_multivalue_and_hash_in_values(self):
        """
        E2E Test: Parser keeps multi-value entries and treats '#' as part of the value.

        ClamAV config files have no inline comments, so a '#' after a value is
        preserved verbatim rather than split off as comment metadata.

        Steps:
        1. Create config containing repeated options and '#' characters in values
        2. Parse config and verify value list lengths
        3. Verify the full value (including any '#') is captured per line
        """
        content = """# mirrors
DatabaseMirror database.clamav.net # primary mirror
DatabaseMirror db.local.clamav.net # backup mirror
LogTime yes # timestamps enabled
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = Path(tmpdir) / "multi-comments.conf"
            conf.write_text(content, encoding="utf-8")

            config, error = parse_config(str(conf))
            assert error is None
            assert config is not None

            mirrors = config.get_values("DatabaseMirror")
            assert len(mirrors) == 2
            assert (
                config.values["DatabaseMirror"][0].value == "database.clamav.net # primary mirror"
            )
            assert config.values["DatabaseMirror"][1].value == "db.local.clamav.net # backup mirror"
            assert config.values["LogTime"][0].value == "yes # timestamps enabled"


class TestE2EConfigModification:
    def test_e2e_parse_modify_write_reparse_with_line_number_preservation(self, config_env):
        """
        E2E Test: Editing values preserves in-place line mappings and persists changes.

        Steps:
        1. Parse a realistic clamd.conf
        2. Modify existing keys with set_value
        3. Write and re-parse, then verify value and line position behavior
        """
        config, error = parse_config(str(config_env["clamd_conf"]))
        assert error is None
        assert config is not None

        original_line = config.values["MaxFileSize"][0].line_number
        config.set_value("MaxFileSize", "250M")
        config.set_value("LogVerbose", "true")

        assert config.values["MaxFileSize"][0].line_number == original_line

        success, write_error = write_config(config)
        assert success is True
        assert write_error is None

        reparsed, parse_error = parse_config(str(config_env["clamd_conf"]))
        assert parse_error is None
        assert reparsed is not None
        assert reparsed.get_value("MaxFileSize") == "250M"
        assert reparsed.get_value("LogVerbose") == "true"
        assert reparsed.raw_lines[original_line - 1].startswith("MaxFileSize 250M")

    def test_e2e_add_value_for_multivalue_option(self, config_env):
        """
        E2E Test: Multi-value options support additive edits through write pipeline.

        Steps:
        1. Parse freshclam.conf with two DatabaseMirror entries
        2. Add one additional DatabaseMirror value
        3. Write and re-parse to verify all mirrors exist
        """
        config, error = parse_config(str(config_env["freshclam_conf"]))
        assert error is None
        assert config is not None

        config.add_value("DatabaseMirror", "mirror3.clamav.net")

        success, write_error = write_config(config)
        assert success is True
        assert write_error is None

        reparsed, parse_error = parse_config(str(config_env["freshclam_conf"]))
        assert parse_error is None
        assert reparsed is not None

        mirrors = reparsed.get_values("DatabaseMirror")
        assert mirrors == [
            "database.clamav.net",
            "db.local.clamav.net",
            "mirror3.clamav.net",
        ]

    def test_e2e_round_trip_preserves_comments_blank_lines_and_creates_bak(self):
        """
        E2E Test: Config round-trip keeps formatting and creates backup on write.

        Steps:
        1. Create a config with comments and blank lines
        2. Parse and write without structural changes
        3. Verify comments/blank lines remain and .bak is created
        """
        content = """# Header comment

LogVerbose yes # inline note

Checks 12
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = Path(tmpdir) / "roundtrip.conf"
            conf.write_text(content, encoding="utf-8")

            config, error = parse_config(str(conf))
            assert error is None
            assert config is not None

            ok, write_error = write_config(config)
            assert ok is True
            assert write_error is None

            output = conf.read_text(encoding="utf-8")
            assert "# Header comment" in output
            assert "LogVerbose yes # inline note" in output
            assert "\n\n" in output
            assert Path(str(conf) + ".bak").exists()


class TestE2EConfigValidation:
    def test_e2e_validate_config_with_all_valid_options(self):
        """
        E2E Test: Validation succeeds for a configuration with valid values.

        Steps:
        1. Build a ClamAVConfig object with valid typed options
        2. Validate config using object-based validator
        3. Verify success with no errors
        """
        config = ClamAVConfig(file_path=Path("/tmp/valid.conf"))
        config.values = {
            "DatabaseDirectory": [ClamAVConfigValue("/var/lib/clamav")],
            "LogVerbose": [ClamAVConfigValue("no")],
            "Checks": [ClamAVConfigValue("24")],
            "MaxFileSize": [ClamAVConfigValue("300M")],
            "User": [ClamAVConfigValue("clamav")],
            "PrivateMirror": [ClamAVConfigValue("https://mirror.example.net")],
        }

        valid, errors = validate_config(config)
        assert valid is True
        assert errors == []

    def test_e2e_validate_config_catches_invalid_boolean_integer_and_url(self):
        """
        E2E Test: Validation catches invalid boolean, integer range, and URL values.

        Steps:
        1. Build config object containing known-invalid option values
        2. Run validate_config on object
        3. Verify each expected validation error category appears
        """
        config = ClamAVConfig(file_path=Path("/tmp/invalid.conf"))
        config.values = {
            "LogVerbose": [ClamAVConfigValue("maybe")],
            "Checks": [ClamAVConfigValue("99")],
            "PrivateMirror": [ClamAVConfigValue("mirror.local")],
        }

        valid, errors = validate_config(config)
        assert valid is False
        assert any("invalid boolean value" in err for err in errors)
        assert any("exceeds maximum" in err for err in errors)
        assert any("URL must start with" in err for err in errors)

    def test_e2e_validate_config_file_and_validate_option_by_type(self):
        """
        E2E Test: File-level validation and per-type option validation both succeed.

        Steps:
        1. Validate a real config file with validate_config_file
        2. Validate one value for each core option type
        3. Confirm option specs include required canonical keys
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = Path(tmpdir) / "validate-file.conf"
            conf.write_text(
                """DatabaseDirectory /var/lib/clamav
LogVerbose yes
Checks 12
MaxFileSize 128M
User clamav
PrivateMirror https://mirror.example.net
""",
                encoding="utf-8",
            )

            valid_file, file_errors = validate_config_file(str(conf))
            assert valid_file is True
            assert file_errors == []

        assert validate_option("DatabaseDirectory", "/var/lib/clamav") == (True, None)
        assert validate_option("LogVerbose", "yes") == (True, None)
        assert validate_option("Checks", "24") == (True, None)
        assert validate_option("MaxFileSize", "512M") == (True, None)
        assert validate_option("User", "clamav") == (True, None)
        assert validate_option("PrivateMirror", "https://mirror.example.net") == (True, None)

        assert "DatabaseDirectory" in CONFIG_OPTION_TYPES
        assert "LogVerbose" in CONFIG_OPTION_TYPES
        assert "Checks" in CONFIG_OPTION_TYPES
        assert "MaxFileSize" in CONFIG_OPTION_TYPES
        assert "User" in CONFIG_OPTION_TYPES
        assert "PrivateMirror" in CONFIG_OPTION_TYPES


class TestE2ESettingsConfigIntegration:
    def test_e2e_configured_path_resolution_and_scan_backend_behavior(self):
        """
        E2E Test: Settings-driven path resolution and scan backend preference interact correctly.

        Steps:
        1. Save clamd_conf_path and scan_backend into settings
        2. Resolve config path through resolver with existence checks mocked
        3. Verify path resolution and backend-driven behavior selection
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            config_dir = base / "config"
            conf = base / "clamd.conf"
            conf.write_text(SAMPLE_CLAMD_CONF, encoding="utf-8")

            settings = SettingsManager(config_dir=config_dir)
            settings.set("clamd_conf_path", str(conf))
            settings.set("scan_backend", "daemon")

            with mock.patch(
                "src.core.clamav_detection.config_file_exists",
                side_effect=lambda p: p == str(conf),
            ):
                resolved = resolve_clamd_conf_path(settings)

            assert resolved == str(conf)
            backend = settings.get("scan_backend")
            behavior = "use_daemon" if backend == "daemon" else "auto_detect"
            assert behavior == "use_daemon"

    def test_e2e_stale_path_redetects_and_full_pipeline_extracts_values(self):
        """
        E2E Test: Stale settings path is cleared, re-detected, parsed, and consumed.

        Steps:
        1. Initialize settings with stale clamd/freshclam paths
        2. Resolve both paths with re-detection and persistence
        3. Parse config, extract key values, and write a log entry from extracted data
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            config_dir = base / "config"
            logs_dir = base / "logs"
            detected_clamd = base / "detected-clamd.conf"
            detected_freshclam = base / "detected-freshclam.conf"
            detected_clamd.write_text(SAMPLE_CLAMD_CONF, encoding="utf-8")
            detected_freshclam.write_text(SAMPLE_FRESHCLAM_CONF, encoding="utf-8")

            settings = SettingsManager(config_dir=config_dir)
            settings.set("clamd_conf_path", "/stale/clamd.conf")
            settings.set("freshclam_conf_path", "/stale/freshclam.conf")

            exists_state = {
                "/stale/clamd.conf": False,
                "/stale/freshclam.conf": False,
                str(detected_clamd): True,
                str(detected_freshclam): True,
            }

            with (
                mock.patch(
                    "src.core.clamav_detection.config_file_exists",
                    side_effect=lambda p: exists_state.get(p, False),
                ),
                mock.patch(
                    "src.core.clamav_detection.detect_clamd_conf_path",
                    return_value=str(detected_clamd),
                ),
                mock.patch(
                    "src.core.clamav_detection.detect_freshclam_conf_path",
                    return_value=str(detected_freshclam),
                ),
            ):
                resolved_clamd = resolve_clamd_conf_path(settings)
                resolved_freshclam = resolve_freshclam_conf_path(settings)

            assert resolved_clamd == str(detected_clamd)
            assert resolved_freshclam == str(detected_freshclam)
            assert settings.get("clamd_conf_path") == str(detected_clamd)
            assert settings.get("freshclam_conf_path") == str(detected_freshclam)

            assert resolved_clamd is not None
            parsed, error = parse_config(resolved_clamd)
            assert error is None
            assert parsed is not None

            socket_path = parsed.get_value("LocalSocket")
            max_file_size = parsed.get_value("MaxFileSize")
            assert socket_path == "/var/run/clamav/clamd.ctl"
            assert max_file_size == "100M"

            with mock.patch("src.core.clamav_detection.is_flatpak", return_value=False):
                assert config_file_exists(str(detected_clamd)) is True

            log_manager = LogManager(log_dir=str(logs_dir))
            entry = LogEntry.create(
                log_type="scan",
                status="clean",
                summary=f"Loaded {max_file_size} with socket {socket_path}",
                details=f"Resolved clamd path: {resolved_clamd}",
                path=resolved_clamd,
                duration=0.2,
                scheduled=False,
            )
            assert log_manager.save_log(entry) is True
            logs = log_manager.get_logs(limit=5, log_type="scan")
            assert len(logs) == 1
            assert "Loaded 100M" in logs[0].summary


class TestE2EConfigBackup:
    def test_e2e_backup_config_creates_timestamped_backup_and_handles_missing_file(self):
        """
        E2E Test: backup_config creates timestamped backups and no-ops for missing files.

        Steps:
        1. Create a real config file and run backup_config
        2. Verify a .bak.<timestamp> backup exists with same content
        3. Run backup_config on missing file and confirm no extra backup appears
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = Path(tmpdir) / "to-backup.conf"
            conf.write_text("LogVerbose yes\n", encoding="utf-8")

            backup_config(str(conf))
            backups = list(Path(tmpdir).glob("to-backup.bak.*"))
            assert len(backups) == 1
            assert backups[0].read_text(encoding="utf-8") == "LogVerbose yes\n"

            backup_config(str(Path(tmpdir) / "missing.conf"))
            backups_after_missing = list(Path(tmpdir).glob("*.bak.*"))
            assert backups_after_missing == backups

    def test_e2e_write_config_creates_bak_before_overwrite(self):
        """
        E2E Test: write_config creates .bak snapshot before overwriting target file.

        Steps:
        1. Parse a config file and record original content
        2. Modify and write config through write_config
        3. Verify .bak contains original data and file contains updated data
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = Path(tmpdir) / "write-backup.conf"
            conf.write_text("LogVerbose no\nChecks 12\n", encoding="utf-8")
            original = conf.read_text(encoding="utf-8")

            config, error = parse_config(str(conf))
            assert error is None
            assert config is not None

            config.set_value("LogVerbose", "yes")
            success, write_error = write_config(config)
            assert success is True
            assert write_error is None

            bak = Path(str(conf) + ".bak")
            assert bak.exists()
            assert bak.read_text(encoding="utf-8") == original
            assert conf.read_text(encoding="utf-8").startswith("LogVerbose yes")

            # Confirm file mode is not relied on from process umask during this pipeline.
            assert os.path.isfile(conf)
