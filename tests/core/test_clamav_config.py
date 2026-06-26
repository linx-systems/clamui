# ClamUI ClamAV Config Tests
"""Unit tests for the ClamAV configuration module."""

import contextlib
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from src.core import clamav_config as clamav_config_module
from src.core.clamav_config import (
    ClamAVConfig,
    ClamAVConfigValue,
    parse_config,
    write_config_with_elevation,
    write_configs_with_elevation,
)


class TestClamAVConfigValue:
    """Tests for the ClamAVConfigValue dataclass."""

    def test_create_default_values(self):
        """Test ClamAVConfigValue with default values."""
        config_value = ClamAVConfigValue(value="test")

        assert config_value.value == "test"
        assert config_value.comment is None
        assert config_value.line_number == 0

    def test_create_with_all_fields(self):
        """Test ClamAVConfigValue with all fields specified."""
        config_value = ClamAVConfigValue(
            value="/var/lib/clamav", comment="Database directory", line_number=5
        )

        assert config_value.value == "/var/lib/clamav"
        assert config_value.comment == "Database directory"
        assert config_value.line_number == 5


class TestClamAVConfig:
    """Tests for the ClamAVConfig dataclass."""

    def test_create_empty_config(self):
        """Test creating an empty ClamAVConfig."""
        config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))

        assert config.file_path == Path("/etc/clamav/freshclam.conf")
        assert config.values == {}
        assert config.raw_lines == []

    def test_get_value_existing(self):
        """Test get_value for existing key."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.values["DatabaseDirectory"] = [ClamAVConfigValue(value="/var/lib/clamav")]

        assert config.get_value("DatabaseDirectory") == "/var/lib/clamav"

    def test_get_value_missing(self):
        """Test get_value for missing key."""
        config = ClamAVConfig(file_path=Path("/test"))

        assert config.get_value("NonExistent") is None

    def test_get_values_multiple(self):
        """Test get_values for multi-value option."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.values["DatabaseMirror"] = [
            ClamAVConfigValue(value="database.clamav.net"),
            ClamAVConfigValue(value="db.local.clamav.net"),
        ]

        values = config.get_values("DatabaseMirror")
        assert len(values) == 2
        assert "database.clamav.net" in values
        assert "db.local.clamav.net" in values

    def test_set_value(self):
        """Test set_value replaces existing values."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.values["LogVerbose"] = [ClamAVConfigValue(value="no")]

        config.set_value("LogVerbose", "yes")

        assert config.get_value("LogVerbose") == "yes"
        assert len(config.values["LogVerbose"]) == 1

    def test_set_value_preserves_line_number_for_existing_key(self):
        """Test that set_value preserves line numbers when updating existing keys."""
        config = ClamAVConfig(file_path=Path("/test"))

        # Simulate parsed config with LogVerbose at line 42
        config.values["LogVerbose"] = [ClamAVConfigValue(value="no", line_number=42)]

        # Update the value (line_number not specified → should preserve)
        config.set_value("LogVerbose", "yes")

        # Verify line number was preserved
        assert config.values["LogVerbose"][0].line_number == 42
        assert config.values["LogVerbose"][0].value == "yes"

    def test_set_value_new_key_has_line_number_zero(self):
        """Test that set_value uses line_number=0 for new keys."""
        config = ClamAVConfig(file_path=Path("/test"))

        # Add a new key
        config.set_value("NewOption", "value")

        # Verify line number is 0 (will be appended)
        assert config.values["NewOption"][0].line_number == 0
        assert config.values["NewOption"][0].value == "value"

    def test_set_value_explicit_line_number_overrides(self):
        """Test that explicit line_number parameter overrides preservation."""
        config = ClamAVConfig(file_path=Path("/test"))

        # Simulate parsed config with LogVerbose at line 42
        config.values["LogVerbose"] = [ClamAVConfigValue(value="no", line_number=42)]

        # Update with explicit line_number (should use provided value, not preserve)
        config.set_value("LogVerbose", "yes", line_number=99)

        # Verify explicit line number was used
        assert config.values["LogVerbose"][0].line_number == 99

    def test_to_string_replaces_line_when_line_number_preserved(self):
        """Test that to_string() replaces lines when line_number is preserved."""
        config = ClamAVConfig(file_path=Path("/test"))

        # Simulate raw_lines from parsing
        config.raw_lines = [
            "# Comment",
            "DatabaseDirectory /var/lib/clamav",
            "LogVerbose no",  # ← Line 3 (index 2)
            "Checks 12",
        ]

        # Simulate parsed values with line numbers
        config.values = {
            "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav", line_number=2)],
            "LogVerbose": [ClamAVConfigValue(value="no", line_number=3)],
            "Checks": [ClamAVConfigValue(value="12", line_number=4)],
        }

        # Update LogVerbose (set_value should preserve line 3)
        config.set_value("LogVerbose", "yes")

        # Convert to string
        output = config.to_string()

        # Verify LogVerbose appears only once, as "yes", at original position
        lines = output.split("\n")
        assert "LogVerbose yes" in lines
        assert "LogVerbose no" not in lines
        # Line is at index 2 (third line, since indexing starts at 0)
        assert lines[2] == "LogVerbose yes"

    def test_to_string_no_duplicates_when_line_number_preserved(self):
        """Test that to_string() doesn't create duplicate entries."""
        config = ClamAVConfig(file_path=Path("/test"))

        # Simulate config with raw_lines
        config.raw_lines = [
            "DatabaseDirectory /var/lib/clamav",
            "LogVerbose no",
            "Checks 12",
        ]

        config.values = {
            "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav", line_number=1)],
            "LogVerbose": [ClamAVConfigValue(value="no", line_number=2)],
            "Checks": [ClamAVConfigValue(value="12", line_number=3)],
        }

        # Update LogVerbose multiple times
        config.set_value("LogVerbose", "yes")
        config.set_value("LogVerbose", "no")
        config.set_value("LogVerbose", "yes")

        output = config.to_string()

        # Verify only one LogVerbose entry exists
        log_verbose_count = output.count("LogVerbose")
        assert log_verbose_count == 1
        assert "LogVerbose yes" in output

    def test_add_value(self):
        """Test add_value appends to existing values."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.add_value("DatabaseMirror", "mirror1.clamav.net")
        config.add_value("DatabaseMirror", "mirror2.clamav.net")

        values = config.get_values("DatabaseMirror")
        assert len(values) == 2

    def test_remove_key_blanks_raw_lines_and_deletes_values(self):
        """Test remove_key blanks original lines and removes from values dict."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = [
            "# freshclam config\n",
            "DatabaseDirectory /var/lib/clamav\n",
            "DatabaseCustomURL https://urlhaus.abuse.ch/downloads/urlhaus.ndb\n",
            "DatabaseCustomURL https://example.com/sigs.hdb\n",
            "Checks 12\n",
        ]
        config.values = {
            "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav", line_number=2)],
            "DatabaseCustomURL": [
                ClamAVConfigValue(
                    value="https://urlhaus.abuse.ch/downloads/urlhaus.ndb", line_number=3
                ),
                ClamAVConfigValue(value="https://example.com/sigs.hdb", line_number=4),
            ],
            "Checks": [ClamAVConfigValue(value="12", line_number=5)],
        }

        config.remove_key("DatabaseCustomURL")

        assert "DatabaseCustomURL" not in config.values
        # Original lines at index 2 and 3 should be blanked
        assert config.raw_lines[2] == ""
        assert config.raw_lines[3] == ""
        # Other lines untouched
        assert "DatabaseDirectory" in config.raw_lines[1]

    def test_remove_key_then_add_no_duplicates(self):
        """Test that remove_key + add_value produces exactly one entry per new URL."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = [
            "DatabaseDirectory /var/lib/clamav\n",
            "DatabaseCustomURL https://old-url.example.com/sigs.hdb\n",
            "DatabaseCustomURL https://another-old.example.com/sigs.hdb\n",
            "Checks 12\n",
        ]
        config.values = {
            "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav", line_number=1)],
            "DatabaseCustomURL": [
                ClamAVConfigValue(value="https://old-url.example.com/sigs.hdb", line_number=2),
                ClamAVConfigValue(value="https://another-old.example.com/sigs.hdb", line_number=3),
            ],
            "Checks": [ClamAVConfigValue(value="12", line_number=4)],
        }

        # Simulate what save_page does: remove_key then add new values
        config.remove_key("DatabaseCustomURL")
        config.add_value("DatabaseCustomURL", "https://new-url.example.com/sigs.hdb")

        output = config.to_string()
        assert output.count("DatabaseCustomURL") == 1
        assert "https://new-url.example.com/sigs.hdb" in output
        assert "https://old-url.example.com/sigs.hdb" not in output
        assert "https://another-old.example.com/sigs.hdb" not in output

    def test_remove_key_clears_all_urls(self):
        """Test that remove_key without add_value removes all entries from output."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = [
            "DatabaseDirectory /var/lib/clamav\n",
            "DatabaseCustomURL https://urlhaus.abuse.ch/downloads/urlhaus.ndb\n",
            "Checks 12\n",
        ]
        config.values = {
            "DatabaseDirectory": [ClamAVConfigValue(value="/var/lib/clamav", line_number=1)],
            "DatabaseCustomURL": [
                ClamAVConfigValue(
                    value="https://urlhaus.abuse.ch/downloads/urlhaus.ndb", line_number=2
                ),
            ],
            "Checks": [ClamAVConfigValue(value="12", line_number=3)],
        }

        config.remove_key("DatabaseCustomURL")

        output = config.to_string()
        assert "DatabaseCustomURL" not in output
        assert "DatabaseDirectory /var/lib/clamav" in output
        assert "Checks 12" in output

    def test_remove_key_nonexistent_is_noop(self):
        """Test that remove_key on a missing key does nothing."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = ["LogVerbose yes\n"]
        config.values = {"LogVerbose": [ClamAVConfigValue(value="yes", line_number=1)]}

        config.remove_key("NonExistent")  # Should not raise

        assert config.get_value("LogVerbose") == "yes"
        assert len(config.raw_lines) == 1

    def test_has_key_true(self):
        """Test has_key returns True for existing key."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.set_value("LogVerbose", "yes")

        assert config.has_key("LogVerbose") is True

    def test_has_key_false(self):
        """Test has_key returns False for missing key."""
        config = ClamAVConfig(file_path=Path("/test"))

        assert config.has_key("NonExistent") is False

    def test_get_bool_yes(self):
        """Test get_bool returns True for 'yes'."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.set_value("LogVerbose", "yes")

        assert config.get_bool("LogVerbose") is True

    def test_get_bool_no(self):
        """Test get_bool returns False for 'no'."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.set_value("LogVerbose", "no")

        assert config.get_bool("LogVerbose") is False

    def test_get_bool_missing(self):
        """Test get_bool returns None for missing key."""
        config = ClamAVConfig(file_path=Path("/test"))

        assert config.get_bool("LogVerbose") is None

    def test_get_int_valid(self):
        """Test get_int returns integer for valid value."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.set_value("Checks", "24")

        assert config.get_int("Checks") == 24

    def test_get_int_invalid(self):
        """Test get_int returns None for non-integer value."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.set_value("Checks", "invalid")

        assert config.get_int("Checks") is None


class TestParseConfig:
    """Tests for the parse_config function."""

    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file for testing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".conf", delete=False, encoding="utf-8"
        ) as f:
            f.write("# ClamAV configuration\n")
            f.write("DatabaseDirectory /var/lib/clamav\n")
            f.write("LogVerbose yes\n")
            f.write("\n")
            f.write("Checks 24\n")
            temp_path = f.name
        yield temp_path
        with contextlib.suppress(OSError, PermissionError):
            Path(temp_path).unlink(missing_ok=True)

    def test_parse_valid_config(self, temp_config_file):
        """Test parsing a valid config file."""
        config, error = parse_config(temp_config_file)

        assert error is None
        assert config is not None
        assert config.get_value("DatabaseDirectory") == "/var/lib/clamav"
        assert config.get_value("LogVerbose") == "yes"
        assert config.get_value("Checks") == "24"

    def test_parse_empty_path(self):
        """Test parse_config with empty path."""
        config, error = parse_config("")

        assert config is None
        assert "no configuration file path" in error.lower()

    def test_parse_nonexistent_file(self):
        """Test parse_config with non-existent file."""
        config, error = parse_config("/nonexistent/config.conf")

        assert config is None
        assert "not found" in error.lower()

    def test_parse_directory_fails(self, tmp_path):
        """Test parse_config fails for directory path."""
        config, error = parse_config(str(tmp_path))

        assert config is None
        assert "not a file" in error.lower()

    def test_parse_preserves_raw_lines(self, temp_config_file):
        """Test that parse_config preserves raw lines."""
        config, error = parse_config(temp_config_file)

        assert error is None
        assert len(config.raw_lines) > 0

    def test_parse_config_hash_in_value_is_not_inline_comment(self, tmp_path):
        """ClamAV config has no inline comments: '#' after a value is kept verbatim."""
        config_file = tmp_path / "test.conf"
        config_file.write_text("LogVerbose yes # Enable verbose logging\n")

        config, error = parse_config(str(config_file))

        assert error is None
        # The entire remainder of the line is the value; '#' is not a comment marker.
        assert config.get_value("LogVerbose") == "yes # Enable verbose logging"

    def test_password_with_hash_roundtrips_without_truncation(self, tmp_path):
        """A value containing '#' (e.g. a password) survives parse -> to_string."""
        config_file = tmp_path / "test.conf"
        config_file.write_text("HTTPProxyPassword s3cr#t!\n")

        config, error = parse_config(str(config_file))

        assert error is None
        # Full value preserved on read (not truncated at '#').
        assert config.get_value("HTTPProxyPassword") == "s3cr#t!"

        # Write-back reproduces the line verbatim (no truncation, no ' # ' artifact).
        output = config.to_string()
        assert "HTTPProxyPassword s3cr#t!" in output
        assert "HTTPProxyPassword s3cr\n" not in output
        assert " # t" not in output

    def test_whole_line_comment_still_preserved(self, tmp_path):
        """A real whole-line comment (first non-space char '#') is preserved as-is."""
        config_file = tmp_path / "test.conf"
        config_file.write_text("# This is a comment\nLogVerbose yes\n")

        config, error = parse_config(str(config_file))

        assert error is None
        # The comment line is not parsed as a key/value...
        assert "#" not in config.values
        assert config.get_value("LogVerbose") == "yes"
        # ...and it is retained verbatim in the reconstructed output.
        assert "# This is a comment" in config.to_string()

    def test_parse_config_with_multi_value_options(self, tmp_path):
        """Test parsing config file with multiple values for same key."""
        config_file = tmp_path / "test.conf"
        config_file.write_text(
            "DatabaseMirror mirror1.clamav.net\nDatabaseMirror mirror2.clamav.net\n"
        )

        config, error = parse_config(str(config_file))

        assert error is None
        values = config.get_values("DatabaseMirror")
        assert len(values) == 2

    def test_parse_config_permission_denied(self, tmp_path):
        """Test parse_config handles permission denied."""

        config_file = tmp_path / "unreadable.conf"
        config_file.write_text("LogVerbose yes\n")
        original_mode = config_file.stat().st_mode
        config_file.chmod(0o000)

        try:
            config, error = parse_config(str(config_file))
            assert config is None
            assert "permission" in error.lower()
        finally:
            config_file.chmod(original_mode)

    def test_parse_config_invalid_path(self):
        """Test parse_config with invalid path format."""
        from unittest.mock import patch

        with patch.object(Path, "resolve", side_effect=OSError("Invalid path")):
            config, error = parse_config("some/path")
            assert config is None
            assert "invalid" in error.lower()


class TestValidateOption:
    """Tests for the validate_option function."""

    def test_validate_unknown_option(self):
        """Test validate_option allows unknown options."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("UnknownOption", "some_value")
        assert is_valid is True
        assert error is None

    def test_validate_boolean_yes(self):
        """Test validate_option accepts 'yes' for boolean."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("LogVerbose", "yes")
        assert is_valid is True
        assert error is None

    def test_validate_boolean_no(self):
        """Test validate_option accepts 'no' for boolean."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("LogVerbose", "no")
        assert is_valid is True
        assert error is None

    def test_validate_boolean_invalid(self):
        """Test validate_option rejects invalid boolean."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("LogVerbose", "maybe")
        assert is_valid is False
        assert "invalid boolean" in error.lower()

    def test_validate_path_valid(self):
        """Test validate_option accepts valid path."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseDirectory", "/var/lib/clamav")
        assert is_valid is True
        assert error is None

    def test_validate_path_empty(self):
        """Test validate_option rejects empty path."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseDirectory", "")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_validate_integer_valid(self):
        """Test validate_option accepts valid integer."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("Checks", "24")
        assert is_valid is True
        assert error is None

    def test_validate_integer_invalid(self):
        """Test validate_option rejects non-integer."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("Checks", "not_a_number")
        assert is_valid is False
        assert "not a valid integer" in error.lower()

    def test_validate_integer_below_min(self):
        """Test validate_option rejects integer below minimum."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("Checks", "-1")
        assert is_valid is False
        assert "below minimum" in error.lower()

    def test_validate_integer_above_max(self):
        """Test validate_option rejects integer above maximum."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("Checks", "100")
        assert is_valid is False
        assert "exceeds maximum" in error.lower()

    def test_validate_size_valid(self):
        """Test validate_option accepts valid size."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("MaxFileSize", "100M")
        assert is_valid is True
        assert error is None

    def test_validate_size_empty(self):
        """Test validate_option rejects empty size."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("MaxFileSize", "")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_validate_size_invalid(self):
        """Test validate_option rejects size not starting with digit."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("MaxFileSize", "M100")
        assert is_valid is False
        assert "must start with a number" in error.lower()

    def test_validate_string_valid(self):
        """Test validate_option accepts valid string."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseMirror", "database.clamav.net")
        assert is_valid is True
        assert error is None

    def test_validate_string_empty(self):
        """Test validate_option rejects empty string."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseMirror", "")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_validate_url_https(self):
        """Test validate_option accepts https:// URL."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option(
            "DatabaseCustomURL",
            "https://www.securiteinfo.com/get/signatures/abc123/securiteinfo.hdb",
        )
        assert is_valid is True
        assert error is None

    def test_validate_url_http(self):
        """Test validate_option accepts http:// URL."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseCustomURL", "http://example.com/signatures.hdb")
        assert is_valid is True
        assert error is None

    def test_validate_url_ftp(self):
        """Test validate_option accepts ftp:// URL."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseCustomURL", "ftp://ftp.example.com/sigs.hdb")
        assert is_valid is True
        assert error is None

    def test_validate_url_ftps(self):
        """Test validate_option accepts ftps:// URL."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseCustomURL", "ftps://secure.example.com/sigs.hdb")
        assert is_valid is True
        assert error is None

    def test_validate_url_file(self):
        """Test validate_option accepts file:// URL."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseCustomURL", "file:///var/lib/clamav/local.hdb")
        assert is_valid is True
        assert error is None

    def test_validate_url_empty_allowed(self):
        """Test validate_option allows empty URL (for clearing)."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseCustomURL", "")
        assert is_valid is True
        assert error is None

    def test_validate_url_invalid_scheme(self):
        """Test validate_option rejects invalid URL scheme."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseCustomURL", "gopher://old.example.com/sigs.hdb")
        assert is_valid is False
        assert "URL must start with" in error

    def test_validate_url_no_scheme(self):
        """Test validate_option rejects URL without scheme."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseCustomURL", "www.example.com/sigs.hdb")
        assert is_valid is False
        assert "URL must start with" in error

    def test_validate_url_case_insensitive(self):
        """Test validate_option accepts URL scheme case-insensitively."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("DatabaseCustomURL", "HTTPS://example.com/sigs.hdb")
        assert is_valid is True
        assert error is None

    def test_validate_private_mirror_url(self):
        """Test validate_option accepts PrivateMirror URL."""
        from src.core.clamav_config import validate_option

        is_valid, error = validate_option("PrivateMirror", "https://mirror.internal.com/clamav/")
        assert is_valid is True
        assert error is None


class TestWriteConfig:
    """Tests for the write_config function."""

    def test_write_config_success(self, tmp_path):
        """Test write_config writes successfully."""
        from src.core.clamav_config import write_config

        config_file = tmp_path / "test.conf"
        config_file.write_text("LogVerbose yes\n")

        config = ClamAVConfig(file_path=config_file)
        config.set_value("LogVerbose", "no", line_number=1)
        config.raw_lines = ["LogVerbose yes\n"]

        success, error = write_config(config)

        assert success is True
        assert error is None
        assert config_file.read_text() == "LogVerbose no\n"

    def test_write_config_no_path(self):
        """Test write_config fails with no path."""
        from src.core.clamav_config import write_config

        config = ClamAVConfig(file_path=None)

        success, error = write_config(config)

        assert success is False
        assert "no file path" in error.lower()

    def test_write_config_permission_denied(self, tmp_path):
        """Test write_config handles permission denied."""
        import stat

        from src.core.clamav_config import write_config

        config_file = tmp_path / "readonly.conf"
        config_file.write_text("LogVerbose yes\n")
        original_mode = config_file.stat().st_mode
        config_file.chmod(stat.S_IRUSR)

        config = ClamAVConfig(file_path=config_file)
        config.set_value("LogVerbose", "no")

        try:
            success, error = write_config(config)
            assert success is False
            assert "permission" in error.lower()
        finally:
            config_file.chmod(original_mode)


class TestValidateConfigFile:
    """Tests for the validate_config_file function."""

    def test_validate_config_file_success(self, tmp_path):
        """Test validate_config_file with valid config."""
        from src.core.clamav_config import validate_config_file

        config_file = tmp_path / "test.conf"
        config_file.write_text("LogVerbose yes\nChecks 24\n")

        is_valid, errors = validate_config_file(str(config_file))

        assert is_valid is True
        assert errors == []

    def test_validate_config_file_invalid_option(self, tmp_path):
        """Test validate_config_file with invalid option."""
        from src.core.clamav_config import validate_config_file

        config_file = tmp_path / "test.conf"
        config_file.write_text("LogVerbose maybe\n")

        is_valid, errors = validate_config_file(str(config_file))

        assert is_valid is False
        assert len(errors) > 0

    def test_validate_config_file_nonexistent(self):
        """Test validate_config_file with nonexistent file."""
        from src.core.clamav_config import validate_config_file

        is_valid, errors = validate_config_file("/nonexistent/path.conf")

        assert is_valid is False
        assert len(errors) > 0


class TestGetConfigSummary:
    """Tests for the get_config_summary function."""

    def test_get_config_summary_empty(self):
        """Test get_config_summary with empty config."""
        from src.core.clamav_config import get_config_summary

        config = ClamAVConfig(file_path=Path("/test"))

        summary = get_config_summary(config)

        assert "no configuration options" in summary.lower()

    def test_get_config_summary_with_values(self):
        """Test get_config_summary with values."""
        from src.core.clamav_config import get_config_summary

        config = ClamAVConfig(file_path=Path("/test/config.conf"))
        config.set_value("LogVerbose", "yes")
        config.set_value("Checks", "24")

        summary = get_config_summary(config)

        assert "/test/config.conf" in summary
        assert "LogVerbose" in summary
        assert "Checks" in summary


class TestValidateConfig:
    """Tests for the validate_config function."""

    def test_validate_config_valid(self):
        """Test validate_config with valid config."""
        from src.core.clamav_config import validate_config

        config = ClamAVConfig(file_path=Path("/test"))
        config.set_value("LogVerbose", "yes")
        config.set_value("Checks", "24")

        is_valid, errors = validate_config(config)

        assert is_valid is True
        assert errors == []

    def test_validate_config_invalid(self):
        """Test validate_config with invalid config."""
        from src.core.clamav_config import validate_config

        config = ClamAVConfig(file_path=Path("/test"))
        config.set_value("LogVerbose", "invalid")

        is_valid, errors = validate_config(config)

        assert is_valid is False
        assert len(errors) > 0


class TestBackupConfig:
    """Tests for the backup_config function."""

    def test_backup_config_creates_backup(self, tmp_path):
        """Test backup_config creates a backup file."""
        from src.core.clamav_config import backup_config

        config_file = tmp_path / "test.conf"
        config_file.write_text("LogVerbose yes\n")

        backup_config(str(config_file))

        # Find backup file
        backup_files = list(tmp_path.glob("test.bak.*"))
        assert len(backup_files) == 1
        assert backup_files[0].read_text() == "LogVerbose yes\n"

    def test_backup_config_nonexistent(self, tmp_path):
        """Test backup_config handles nonexistent file."""
        from src.core.clamav_config import backup_config

        # Should not raise exception
        backup_config(str(tmp_path / "nonexistent.conf"))


class TestClamAVConfigToString:
    """Tests for ClamAVConfig.to_string method."""

    def test_to_string_empty_config(self):
        """Test to_string with empty config."""
        config = ClamAVConfig(file_path=Path("/test"))

        result = config.to_string()

        assert result == ""

    def test_to_string_no_raw_lines(self):
        """Test to_string generates from values when no raw lines."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.set_value("LogVerbose", "yes")
        config.set_value("Checks", "24")

        result = config.to_string()

        assert "LogVerbose yes" in result
        assert "Checks 24" in result

    def test_to_string_with_raw_lines(self):
        """Test to_string preserves raw lines structure."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = ["# Comment\n", "LogVerbose yes\n", "\n", "Checks 24\n"]
        config.values["LogVerbose"] = [ClamAVConfigValue(value="no", line_number=2)]
        config.values["Checks"] = [ClamAVConfigValue(value="12", line_number=4)]

        result = config.to_string()

        assert "# Comment" in result
        assert "LogVerbose no" in result
        assert "Checks 12" in result

    def test_to_string_with_new_values(self):
        """Test to_string appends new values without line numbers."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = ["LogVerbose yes\n"]
        config.set_value("NewOption", "value")

        result = config.to_string()

        assert "LogVerbose yes" in result
        assert "NewOption value" in result

    def test_to_string_ignores_comment_field(self):
        """ClamAV config has no inline comments: a value's comment is never written."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = ["LogVerbose yes\n"]
        config.values["LogVerbose"] = [
            ClamAVConfigValue(value="no", comment="Changed to no", line_number=1)
        ]

        result = config.to_string()

        assert "LogVerbose no" in result
        assert "#" not in result


class TestWriteConfigWithElevation:
    """Tests for write_config_with_elevation function."""

    def test_write_to_user_writable_directory(self, tmp_path):
        """Test writing to user-writable directory without elevation."""
        # Create a config for a user-writable path
        config_file = tmp_path / "test.conf"
        config = ClamAVConfig(file_path=config_file)
        config.set_value("DatabaseDirectory", "/var/lib/clamav")

        # Should succeed without needing pkexec
        success, error = write_config_with_elevation(config)

        assert success is True
        assert error is None
        assert config_file.exists()
        assert "DatabaseDirectory /var/lib/clamav" in config_file.read_text()

    def test_write_creates_parent_directory(self, tmp_path):
        """Test writing creates parent directory if it doesn't exist."""
        # Config in a non-existent subdirectory
        config_file = tmp_path / "subdir" / "test.conf"
        config = ClamAVConfig(file_path=config_file)
        config.set_value("LogVerbose", "yes")

        success, error = write_config_with_elevation(config)

        assert success is True
        assert error is None
        assert config_file.exists()
        assert config_file.parent.exists()

    def test_write_without_file_path(self):
        """Test writing config without file path specified."""
        config = ClamAVConfig(file_path=None)
        config.set_value("LogVerbose", "yes")

        success, error = write_config_with_elevation(config)

        assert success is False
        assert "No file path specified" in error

    def test_write_sets_permissions(self, tmp_path):
        """Test writing sets correct file permissions."""
        config_file = tmp_path / "test.conf"
        config = ClamAVConfig(file_path=config_file)
        config.set_value("LogVerbose", "yes")

        success, error = write_config_with_elevation(config)

        assert success is True
        # Check file has 0o644 permissions (rw-r--r--)
        assert (config_file.stat().st_mode & 0o777) == 0o644

    def test_write_preserves_config_content(self, tmp_path):
        """Test writing preserves all config content."""
        config_file = tmp_path / "test.conf"
        config = ClamAVConfig(file_path=config_file)
        config.raw_lines = ["# Comment line\n", "LogVerbose yes\n"]
        config.set_value("DatabaseDirectory", "/var/lib/clamav")

        success, error = write_config_with_elevation(config)

        assert success is True
        content = config_file.read_text()
        assert "# Comment line" in content
        assert "LogVerbose yes" in content
        assert "DatabaseDirectory /var/lib/clamav" in content


class TestWriteConfigsWithElevation:
    """Tests for write_configs_with_elevation function."""

    def test_write_multiple_user_writable_configs(self, tmp_path):
        """Test writing multiple configs in user-writable paths."""
        config_file_a = tmp_path / "freshclam.conf"
        config_file_b = tmp_path / "clamd.conf"

        config_a = ClamAVConfig(file_path=config_file_a)
        config_a.set_value("DatabaseDirectory", "/var/lib/clamav")

        config_b = ClamAVConfig(file_path=config_file_b)
        config_b.set_value("LogVerbose", "yes")

        success, error = write_configs_with_elevation([config_a, config_b])

        assert success is True
        assert error is None
        assert "DatabaseDirectory /var/lib/clamav" in config_file_a.read_text()
        assert "LogVerbose yes" in config_file_b.read_text()

    def test_write_multiple_elevated_configs_uses_single_pkexec_call(self, monkeypatch):
        """Test elevated writes use a single pkexec invocation for all files."""
        config_a = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        config_a.set_value("DatabaseDirectory", "/var/lib/clamav")

        config_b = ClamAVConfig(file_path=Path("/etc/clamav/clamd.conf"))
        config_b.set_value("LogVerbose", "yes")

        monkeypatch.setattr(clamav_config_module, "_path_needs_elevation", lambda _path: True)
        monkeypatch.setattr(
            clamav_config_module,
            "_get_privileged_writer_path",
            lambda: "/usr/bin/clamui-apply-preferences",
        )

        run_calls = []

        def _fake_run(cmd, **kwargs):
            run_calls.append((cmd, kwargs))

            class _Result:
                returncode = 0
                stderr = ""

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, error = write_configs_with_elevation([config_a, config_b])

        assert success is True
        assert error is None
        assert len(run_calls) == 1

        cmd, kwargs = run_calls[0]
        assert cmd[0:3] == ["pkexec", "/usr/bin/clamui-apply-preferences", "--protocol=2"]
        # Two (staged-source, destination) pairs after the protocol token.
        assert len(cmd[3:]) == 4
        # Destinations are at odd offsets within the pair list, i.e. cmd[4::2].
        assert str(config_a.file_path) in cmd[4::2]
        assert str(config_b.file_path) in cmd[4::2]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True

    def test_write_elevated_config_returns_friendly_error_on_auth_cancel(self, monkeypatch):
        """Test auth cancellation returns a user-friendly message."""
        config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        config.set_value("DatabaseDirectory", "/var/lib/clamav")

        monkeypatch.setattr(clamav_config_module, "_path_needs_elevation", lambda _path: True)
        monkeypatch.setattr(
            clamav_config_module,
            "_get_privileged_writer_path",
            lambda: "/usr/bin/clamui-apply-preferences",
        )

        def _fake_run(_cmd, **_kwargs):
            class _Result:
                returncode = 126
                stderr = "Not authorized"

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, error = write_configs_with_elevation([config])

        assert success is False
        assert error == "Authentication was canceled. Configuration changes were not applied."

    def test_write_elevated_config_returns_friendly_error_on_auth_denied(self, monkeypatch):
        """Test auth denial returns a user-friendly message."""
        config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        config.set_value("DatabaseDirectory", "/var/lib/clamav")

        monkeypatch.setattr(clamav_config_module, "_path_needs_elevation", lambda _path: True)
        monkeypatch.setattr(
            clamav_config_module,
            "_get_privileged_writer_path",
            lambda: "/usr/bin/clamui-apply-preferences",
        )

        def _fake_run(_cmd, **_kwargs):
            class _Result:
                returncode = 127
                stderr = "Not authorized"

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, error = write_configs_with_elevation([config])

        assert success is False
        assert error is not None
        # Exit 127 now yields an actionable message naming the polkit policy /
        # helper, instead of a bare "Authorization failed" (issue #143).
        assert "administrator authorization" in error.lower()
        assert "polkit" in error.lower()


class TestFlatpakElevationRouting:
    """Regression tests for issue #136 (Flatpak prefs silently not persisting).

    Two coordinated routing rules must hold inside a Flatpak sandbox so that a
    system-path config write reaches the *host* file instead of a non-persistent
    sandbox copy:

    1. ``_path_needs_elevation`` must force elevation for system paths so the
       write never falls through to a direct (sandbox-local) write.
    2. ``_get_privileged_writer_path`` must resolve the helper on the host, not
       at the sandbox-internal ``/app/bin`` path.
    """

    def test_system_path_forces_elevation_in_flatpak(self, monkeypatch):
        """In Flatpak, /etc paths always require elevation (no sandbox direct write)."""
        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: True)

        assert clamav_config_module._path_needs_elevation(Path("/etc/freshclam.conf")) is True
        assert clamav_config_module._path_needs_elevation(Path("/etc/clamav/clamd.conf")) is True

    def test_user_path_not_forced_to_elevation_in_flatpak(self, monkeypatch, tmp_path):
        """In Flatpak, a writable non-system path still uses the direct write path."""
        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: True)

        # tmp_path is user-writable and not under a system prefix.
        assert clamav_config_module._path_needs_elevation(tmp_path / "freshclam.conf") is False

    def test_existing_user_writable_file_skips_elevation(self, monkeypatch, tmp_path):
        """A writable existing config (e.g. a chown'd /etc/freshclam.conf) writes
        directly without pkexec, so the documented chown workaround works (#143)."""
        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: False)
        f = tmp_path / "freshclam.conf"
        f.write_text("DatabaseDirectory /var/lib/clamav\n")

        assert clamav_config_module._path_needs_elevation(f) is False

    def test_existing_unwritable_file_needs_elevation(self, monkeypatch, tmp_path):
        """An existing config the user cannot write (root:root) still elevates."""
        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: False)
        f = tmp_path / "freshclam.conf"
        f.write_text("DatabaseDirectory /var/lib/clamav\n")
        # Simulate a file the current user cannot write.
        monkeypatch.setattr(clamav_config_module.os, "access", lambda _p, _mode: False)

        assert clamav_config_module._path_needs_elevation(f) is True

    def test_root_skips_elevation_for_system_path(self, monkeypatch):
        """Launched as root, a /etc path writes directly without pkexec."""
        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: False)
        monkeypatch.setattr(clamav_config_module, "is_running_as_root", lambda: True)

        assert clamav_config_module._path_needs_elevation(Path("/etc/freshclam.conf")) is False

    def test_root_still_elevates_system_path_in_flatpak(self, monkeypatch):
        """Even as root, Flatpak system paths route through the host helper
        because the sandbox copy is ephemeral (#136), not a permission issue."""
        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: True)
        monkeypatch.setattr(clamav_config_module, "is_running_as_root", lambda: True)

        assert clamav_config_module._path_needs_elevation(Path("/etc/freshclam.conf")) is True

    def test_writer_path_resolved_on_host_in_flatpak(self, monkeypatch):
        """In Flatpak, the helper is resolved via the host, not /app/bin."""
        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: True)
        monkeypatch.setattr(
            "src.core.flatpak.which_host_command",
            lambda name: f"/usr/bin/{name}",
        )

        assert (
            clamav_config_module._get_privileged_writer_path()
            == "/usr/bin/clamui-apply-preferences"
        )

    def test_missing_host_helper_in_flatpak_gives_clear_error(self, monkeypatch):
        """When the host helper is absent, the save fails with an actionable message
        rather than silently resetting or showing 'Authorization failed'."""
        config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        config.set_value("DatabaseDirectory", "/var/lib/clamav")

        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: True)
        # Host helper not installed -> which returns None.
        monkeypatch.setattr("src.core.flatpak.which_host_command", lambda _name: None)

        success, error = write_configs_with_elevation([config])

        assert success is False
        assert error is not None
        assert "helper not installed" in error.lower()

    def test_flatpak_system_write_uses_host_helper_via_flatpak_spawn(self, monkeypatch, tmp_path):
        """End-to-end: a Flatpak /etc write invokes the HOST helper through
        ``flatpak-spawn --host pkexec`` (never the sandbox /app/bin path)."""
        config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        config.set_value("DatabaseDirectory", "/var/lib/clamav")

        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: True)
        monkeypatch.setattr(
            "src.core.flatpak.which_host_command",
            lambda name: f"/usr/bin/{name}",
        )
        monkeypatch.setattr(
            clamav_config_module,
            "staging_root_for_uid",
            lambda _uid: tmp_path / "clamui-staging",
        )

        run_calls = []

        def _fake_run(cmd, **kwargs):
            run_calls.append(cmd)

            class _Result:
                returncode = 0
                stderr = ""
                stdout = ""

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, error = write_configs_with_elevation([config])

        assert success is True
        assert error is None

        # A host-visibility probe runs first, then the elevated pkexec call.
        pkexec_calls = [c for c in run_calls if "pkexec" in c]
        assert len(pkexec_calls) == 1
        cmd = pkexec_calls[0]
        # Host-spawn prefix, then host helper path (NOT /app/bin/...).
        assert cmd[0:2] == ["flatpak-spawn", "--host"]
        assert cmd[2:5] == ["pkexec", "/usr/bin/clamui-apply-preferences", "--protocol=2"]
        assert not any(str(arg).startswith("/app/bin") for arg in cmd)

        probe_calls = [c for c in run_calls if "test" in c and "-e" in c]
        assert len(probe_calls) == 1

    def test_flatpak_staging_not_host_visible_gives_clear_error(self, monkeypatch, tmp_path):
        """When the staging dir is not reachable on the host, fail clearly and
        never invoke pkexec (issue #136 staging visibility)."""
        config = ClamAVConfig(file_path=Path("/etc/clamav/freshclam.conf"))
        config.set_value("DatabaseDirectory", "/var/lib/clamav")

        monkeypatch.setattr("src.core.flatpak.is_flatpak", lambda: True)
        monkeypatch.setattr(
            "src.core.flatpak.which_host_command",
            lambda name: f"/usr/bin/{name}",
        )
        monkeypatch.setattr(
            clamav_config_module,
            "staging_root_for_uid",
            lambda _uid: tmp_path / "clamui-staging",
        )

        pkexec_calls = []

        def _fake_run(cmd, **kwargs):
            if "pkexec" in cmd:
                pkexec_calls.append(cmd)

            class _Result:
                stderr = ""
                stdout = ""
                # Host-visibility probe (`test -e`) fails; nothing else should run.
                returncode = 1 if ("test" in cmd and "-e" in cmd) else 0

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, error = write_configs_with_elevation([config])

        assert success is False
        assert error is not None
        assert "not reachable" in error.lower()
        assert pkexec_calls == []


class TestParseConfigFlatpak:
    """Tests for parse_config() Flatpak-aware file reading."""

    def test_system_path_in_flatpak_uses_host_read(self):
        """Test that system paths in Flatpak use read_host_file."""
        config_content = "DatabaseDirectory /var/lib/clamav\nLogVerbose yes\n"

        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch(
                "src.core.flatpak.read_host_file",
                return_value=(config_content, None),
            ) as mock_read,
            mock.patch("src.core.clamav_detection.config_file_exists", return_value=True),
        ):
            config, error = parse_config("/etc/clamd.d/scan.conf")

        assert error is None
        assert config is not None
        assert config.get_value("DatabaseDirectory") == "/var/lib/clamav"
        assert config.get_value("LogVerbose") == "yes"
        mock_read.assert_called_once_with("/etc/clamd.d/scan.conf")

    def test_system_path_in_flatpak_file_not_found(self):
        """Test that missing system files in Flatpak return proper error."""
        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch("src.core.clamav_detection.config_file_exists", return_value=False),
        ):
            config, error = parse_config("/etc/clamd.d/scan.conf")

        assert config is None
        assert "not found" in error.lower()

    def test_system_path_in_flatpak_read_error(self):
        """Test that read errors from flatpak-spawn are propagated."""
        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch("src.core.clamav_detection.config_file_exists", return_value=True),
            mock.patch(
                "src.core.flatpak.read_host_file",
                return_value=(None, "Permission denied: Cannot read /etc/clamd.d/scan.conf"),
            ),
        ):
            config, error = parse_config("/etc/clamd.d/scan.conf")

        assert config is None
        assert "permission denied" in error.lower()

    def test_user_path_in_flatpak_uses_direct_io(self, tmp_path):
        """Test that user-writable paths in Flatpak use direct I/O."""
        config_file = tmp_path / "freshclam.conf"
        config_file.write_text("DatabaseDirectory /home/user/.clamav\n")

        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch(
                "src.core.flatpak.read_host_file",
            ) as mock_read,
        ):
            config, error = parse_config(str(config_file))

        assert error is None
        assert config is not None
        assert config.get_value("DatabaseDirectory") == "/home/user/.clamav"
        mock_read.assert_not_called()

    def test_native_ignores_flatpak_logic(self, tmp_path):
        """Test that non-Flatpak mode uses direct I/O for all paths."""
        config_file = tmp_path / "clamd.conf"
        config_file.write_text("LogVerbose yes\n")

        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=False),
            mock.patch(
                "src.core.flatpak.read_host_file",
            ) as mock_read,
        ):
            config, error = parse_config(str(config_file))

        assert error is None
        assert config is not None
        mock_read.assert_not_called()

    def test_var_path_in_flatpak_uses_host_read(self):
        """Test /var/ paths are treated as system paths in Flatpak."""
        config_content = "# empty config\n"

        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch(
                "src.core.flatpak.read_host_file",
                return_value=(config_content, None),
            ),
            mock.patch("src.core.clamav_detection.config_file_exists", return_value=True),
        ):
            config, error = parse_config("/var/lib/clamav/clamd.conf")

        assert error is None
        assert config is not None

    def test_usr_path_in_flatpak_uses_host_read(self):
        """Test /usr/ paths are treated as system paths in Flatpak."""
        config_content = "# usr config\n"

        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch(
                "src.core.flatpak.read_host_file",
                return_value=(config_content, None),
            ),
            mock.patch("src.core.clamav_detection.config_file_exists", return_value=True),
        ):
            config, error = parse_config("/usr/local/etc/clamd.conf")

        assert error is None
        assert config is not None

    def test_opt_path_in_flatpak_uses_host_read(self):
        """Test /opt/ paths are treated as system paths in Flatpak."""
        config_content = "# opt config\n"

        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch(
                "src.core.flatpak.read_host_file",
                return_value=(config_content, None),
            ),
            mock.patch("src.core.clamav_detection.config_file_exists", return_value=True),
        ):
            config, error = parse_config("/opt/clamav/etc/clamd.conf")

        assert error is None
        assert config is not None

    def test_system_path_host_read_returns_none_content_no_error(self):
        """Test fallback message when read_host_file returns (None, None)."""
        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch("src.core.clamav_detection.config_file_exists", return_value=True),
            mock.patch(
                "src.core.flatpak.read_host_file",
                return_value=(None, None),
            ),
        ):
            config, error = parse_config("/etc/clamd.d/scan.conf")

        assert config is None
        assert "Failed to read" in error


class TestSetValueOrphanedRawLines:
    """Tests for set_value blanking orphaned raw_lines from duplicated entries."""

    def test_set_value_blanks_duplicate_entries(self):
        """Test that set_value blanks raw_lines for duplicate key entries."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = [
            "# Comment\n",
            "LogVerbose no\n",
            "Checks 24\n",
            "\n",
            "LogVerbose no\n",  # Duplicate at line 5
            "Checks 24\n",  # Duplicate at line 6
        ]
        config.values = {
            "LogVerbose": [
                ClamAVConfigValue(value="no", line_number=2),
                ClamAVConfigValue(value="no", line_number=5),
            ],
            "Checks": [
                ClamAVConfigValue(value="24", line_number=3),
                ClamAVConfigValue(value="24", line_number=6),
            ],
        }

        config.set_value("LogVerbose", "yes")
        config.set_value("Checks", "12")

        output = config.to_string()
        # Duplicates should be gone
        assert output.count("LogVerbose") == 1
        assert output.count("Checks") == 1
        assert "LogVerbose yes" in output
        assert "Checks 12" in output

    def test_set_value_blanks_many_duplicates(self):
        """Test cleanup of heavily corrupted config (12x duplication)."""
        config = ClamAVConfig(file_path=Path("/test"))

        # Simulate 4 duplicate blocks
        raw = ["# Comment\n", "UpdateLogFile /var/log/freshclam.log\n"]
        values_list = [ClamAVConfigValue(value="/var/log/freshclam.log", line_number=2)]
        for _i in range(3):
            line_num = len(raw) + 1
            raw.append("UpdateLogFile /var/log/freshclam.log\n")
            values_list.append(
                ClamAVConfigValue(value="/var/log/freshclam.log", line_number=line_num)
            )

        config.raw_lines = raw
        config.values = {"UpdateLogFile": values_list}

        config.set_value("UpdateLogFile", "/var/log/freshclam.log")

        output = config.to_string()
        assert output.count("UpdateLogFile") == 1

    def test_set_value_single_entry_no_blanking(self):
        """Test that set_value with a single entry doesn't blank anything."""
        config = ClamAVConfig(file_path=Path("/test"))
        config.raw_lines = ["LogVerbose no\n"]
        config.values = {
            "LogVerbose": [ClamAVConfigValue(value="no", line_number=1)],
        }

        config.set_value("LogVerbose", "yes")

        output = config.to_string()
        assert output.count("LogVerbose") == 1
        assert "LogVerbose yes" in output

    def test_set_value_idempotent_after_cleanup(self, tmp_path):
        """Test that re-saving a cleaned config never re-introduces duplicates."""
        config_file = tmp_path / "test.conf"
        config_file.write_text("# Comment\nLogVerbose no\nChecks 24\n\nLogVerbose no\nChecks 24\n")

        for _ in range(4):
            config, _ = parse_config(str(config_file))
            config.set_value("LogVerbose", "yes")
            config.set_value("Checks", "12")
            output = config.to_string()
            config_file.write_text(output)

            # Must never have duplicates regardless of iteration
            assert output.count("LogVerbose") == 1
            assert output.count("Checks") == 1


class TestWriteConfigsFlatpak:
    """Tests for Flatpak-aware write_configs_with_elevation."""

    def test_flatpak_elevated_write_uses_host_spawn(self, monkeypatch):
        """Test that elevated writes in Flatpak use flatpak-spawn --host."""
        config = ClamAVConfig(file_path=Path("/etc/clamav/clamd.conf"))
        config.set_value("LogVerbose", "yes")

        monkeypatch.setattr(clamav_config_module, "_path_needs_elevation", lambda _: True)
        monkeypatch.setattr(clamav_config_module, "_running_in_flatpak", lambda: True)

        run_calls = []

        def _fake_run(cmd, **kwargs):
            run_calls.append(cmd)

            class _Result:
                returncode = 0
                stderr = ""

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, error = write_configs_with_elevation([config])

        assert success is True
        assert error is None
        # A host-visibility probe precedes the pkexec call; select the latter.
        cmd = next(c for c in run_calls if "pkexec" in c)
        # Must start with flatpak-spawn --host
        assert cmd[0] == "flatpak-spawn"
        assert cmd[1] == "--host"
        assert cmd[2] == "pkexec"

    def test_flatpak_elevated_write_uses_helper_with_protocol(self, monkeypatch):
        """In Flatpak the helper is invoked through flatpak-spawn (no inline shell).

        VULN-001 was the inline ``pkexec sh -c ...`` fallback that ran in the
        Flatpak path: it copied any source path to any destination with no
        allowlist.  After the fix the helper is the only writer and is
        responsible for validating both the source (under per-user staging)
        and the destination (against the allowlist).  Packaging-side work is
        responsible for making the helper reachable from the host.
        """
        config = ClamAVConfig(file_path=Path("/etc/clamav/clamd.conf"))
        config.set_value("LogVerbose", "yes")

        monkeypatch.setattr(clamav_config_module, "_path_needs_elevation", lambda _: True)
        monkeypatch.setattr(clamav_config_module, "_running_in_flatpak", lambda: True)
        monkeypatch.setattr(
            clamav_config_module,
            "_get_privileged_writer_path",
            lambda: "/usr/bin/clamui-apply-preferences",
        )

        run_calls = []

        def _fake_run(cmd, **kwargs):
            run_calls.append(cmd)

            class _Result:
                returncode = 0
                stderr = ""

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, _err = write_configs_with_elevation([config])

        assert success is True
        cmd = next(c for c in run_calls if "pkexec" in c)
        assert cmd[0:2] == ["flatpak-spawn", "--host"]
        assert cmd[2] == "pkexec"
        assert cmd[3] == "/usr/bin/clamui-apply-preferences"
        assert cmd[4] == "--protocol=2"
        # Inline shell is gone; the helper is the only writer.
        assert "sh" not in cmd
        assert "-c" not in cmd

    def test_native_elevated_write_no_host_spawn(self, monkeypatch):
        """Test that native (non-Flatpak) writes don't use flatpak-spawn."""
        config = ClamAVConfig(file_path=Path("/etc/clamav/clamd.conf"))
        config.set_value("LogVerbose", "yes")

        monkeypatch.setattr(clamav_config_module, "_path_needs_elevation", lambda _: True)
        monkeypatch.setattr(clamav_config_module, "_running_in_flatpak", lambda: False)
        monkeypatch.setattr(
            clamav_config_module,
            "_get_privileged_writer_path",
            lambda: "/usr/bin/clamui-apply-preferences",
        )

        run_calls = []

        def _fake_run(cmd, **kwargs):
            run_calls.append(cmd)

            class _Result:
                returncode = 0
                stderr = ""

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, _ = write_configs_with_elevation([config])

        assert success is True
        cmd = run_calls[0]
        assert cmd[0] == "pkexec"
        assert "flatpak-spawn" not in cmd

    def test_staged_files_live_under_per_invocation_staging_dir(self, monkeypatch, tmp_path):
        """Each invocation stages into a fresh per-invocation directory under the
        canonical staging root.

        The staging root is the single source of truth shared with the helper
        (``staging_root_for_uid``); we redirect it under ``tmp_path`` so the
        test does not depend on ``/run/user/<uid>`` existing, and confirm the
        staged file lives under that root.
        """
        config = ClamAVConfig(file_path=Path("/etc/clamav/clamd.conf"))
        config.set_value("LogVerbose", "yes")

        staging_root = tmp_path / "clamui-staging"
        monkeypatch.setattr(clamav_config_module, "_path_needs_elevation", lambda _: True)
        monkeypatch.setattr(clamav_config_module, "_running_in_flatpak", lambda: True)
        monkeypatch.setattr(
            clamav_config_module,
            "_get_privileged_writer_path",
            lambda: "/usr/bin/clamui-apply-preferences",
        )
        monkeypatch.setattr(clamav_config_module, "staging_root_for_uid", lambda _uid: staging_root)

        staged_paths: list[str] = []

        def _fake_run(cmd, **kwargs):
            # Both the host-visibility probe (`test -e <dir>`) and the pkexec
            # call pass; collect the staged source path (ends in .conf).
            for arg in cmd:
                if str(staging_root) in str(arg) and str(arg).endswith(".conf"):
                    staged_paths.append(arg)

            class _Result:
                returncode = 0
                stderr = ""
                stdout = ""

            return _Result()

        monkeypatch.setattr(clamav_config_module.subprocess, "run", _fake_run)

        success, _err = write_configs_with_elevation([config])

        assert success is True
        assert len(staged_paths) == 1
        staged = Path(staged_paths[0])
        assert str(staging_root) in str(staged)
        # The staging-dir cleanup in the finally block runs after subprocess.run
        # returns; the staged file should already be removed by now.
        assert not staged.exists()


class TestBackupConfigFlatpak:
    """Tests for backup_config Flatpak-awareness."""

    def test_backup_skipped_for_system_path_in_flatpak(self):
        """Test that backup is skipped for system paths in Flatpak."""
        from src.core.clamav_config import backup_config

        with (
            mock.patch("src.core.flatpak.is_flatpak", return_value=True),
            mock.patch("shutil.copy2") as mock_copy,
        ):
            backup_config("/etc/clamav/clamd.conf")

        mock_copy.assert_not_called()

    def test_backup_proceeds_for_user_path_in_flatpak(self, tmp_path):
        """Test that backup works for user-writable paths in Flatpak."""
        from src.core.clamav_config import backup_config

        config_file = tmp_path / "freshclam.conf"
        config_file.write_text("# test config\n")

        with mock.patch("src.core.flatpak.is_flatpak", return_value=True):
            backup_config(str(config_file))

        # A backup file should have been created
        backups = list(tmp_path.glob("freshclam.bak.*"))
        assert len(backups) == 1

    def test_backup_proceeds_in_native_mode(self, tmp_path):
        """Test that backup works normally outside Flatpak."""
        from src.core.clamav_config import backup_config

        config_file = tmp_path / "clamd.conf"
        config_file.write_text("# test config\n")

        with mock.patch("src.core.flatpak.is_flatpak", return_value=False):
            backup_config(str(config_file))

        backups = list(tmp_path.glob("clamd.bak.*"))
        assert len(backups) == 1
