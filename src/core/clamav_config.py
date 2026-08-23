# ClamUI ClamAV Configuration Module
"""
ClamAV configuration file parser and writer.
Supports reading and modifying freshclam.conf and clamd.conf files.
"""

import logging
import math
import os
import shutil
import stat
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .i18n import _
from .privileged_paths import (
    PROTOCOL_VERSION,
    is_running_as_root,
    staging_root_for_uid,
)

logger = logging.getLogger(__name__)

# System path prefixes that are inaccessible from inside a Flatpak sandbox
_SYSTEM_PATH_PREFIXES = ("/etc/", "/usr/", "/var/", "/opt/")

# Canonical, host-installed privileged helper executable handed to pkexec.
# Only this absolute path is ever returned by ``_get_privileged_writer_path``:
# a user-writable venv or ``~/.local`` wrapper that merely shares the helper
# name must never reach pkexec, or an unprivileged user could run arbitrary
# code as root.  Native mode checks this literal path only -- it never consults
# ``sys.executable`` or ``PATH`` -- and the pip wheel deliberately declares no
# ``clamui-apply-preferences`` console script, so a venv install cannot create
# a colliding binary.  The canonical wrapper itself is provisioned by the
# native ``clamui install-privileged-helper`` flow or the
# ``clamui-privileged-helper`` Debian package.  This constant lives in the core
# layer on purpose: the CLI layer is not imported into core.
_PRIVILEGED_HELPER_PATH = "/usr/bin/clamui-apply-preferences"

# Root-owned library directory and the two self-contained modules the wrapper
# imports.  Native ``_get_privileged_writer_path`` requires the wrapper, this
# directory, and both modules to be real, root-owned, not group/world-writable
# entries, so pkexec can never execute or import mutable user-owned helper
# code.  These mirror the paths provisioned by ``clamui
# install-privileged-helper`` and the ``clamui-privileged-helper`` Debian
# package; duplicated here because the core layer does not import the CLI layer.
_PRIVILEGED_LIB_DIR = "/usr/lib/clamui"
_PRIVILEGED_LIB_MODULES = (
    "/usr/lib/clamui/clamui_apply_preferences.py",
    "/usr/lib/clamui/clamui_privileged_paths.py",
)


@dataclass
class ClamAVConfigValue:
    """
    Represents a single configuration value with metadata.

    ClamAV config files may have multiple lines with the same key
    (e.g., multiple DatabaseMirror entries), so each value tracks
    its position in the file for accurate reconstruction.

    Attributes:
        value: The configuration value as a string
        comment: Optional inline comment associated with this value
        line_number: The line number where this value appears (1-indexed)
    """

    value: str
    comment: str | None = None
    line_number: int = 0


@dataclass
class ClamAVConfig:
    """
    Parsed ClamAV configuration file.

    Stores configuration values from ClamAV config files (freshclam.conf,
    clamd.conf) while preserving the original file structure for accurate
    reconstruction when writing changes.

    ClamAV config format:
    - Key-value pairs separated by space (not INI format, no sections)
    - Comments start with #
    - Multi-value options allowed (multiple lines with same key)
    - Boolean values are typically 'yes' or 'no'

    Attributes:
        file_path: Path to the configuration file
        values: Dictionary mapping option names to lists of ClamAVConfigValue.
                Lists are used because some options (like DatabaseMirror)
                can have multiple values.
        raw_lines: Original lines from the file for accurate reconstruction
    """

    file_path: Path
    values: dict[str, list[ClamAVConfigValue]] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)

    def get_value(self, key: str) -> str | None:
        """
        Get the first value for a configuration key.

        Args:
            key: The configuration option name

        Returns:
            The first value if the key exists, None otherwise
        """
        if self.values.get(key):
            return self.values[key][0].value
        return None

    def get_values(self, key: str) -> list[str]:
        """
        Get all values for a configuration key.

        Useful for multi-value options like DatabaseMirror.

        Args:
            key: The configuration option name

        Returns:
            List of all values for the key, empty list if key doesn't exist
        """
        if key in self.values:
            return [v.value for v in self.values[key]]
        return []

    def set_value(self, key: str, value: str, line_number: int = 0) -> None:
        """
        Set a single value for a configuration key.

        Line Number Preservation Logic:
        - When line_number=0 (default) AND key already exists:
          * Retrieves existing line number from self.values[key][0].line_number
          * Reuses that line number for the new value
          * Result: write_config() updates existing line IN-PLACE (line 42 stays line 42)
        - When line_number=0 AND key is new:
          * Line number remains 0
          * Result: write_config() APPENDS to end of file
        - When line_number > 0 (explicit):
          * Uses provided line number directly
          * Result: write_config() updates specific line or creates new line

        Why This Matters:
        - Preserves config file formatting and organization
        - Keeps related settings grouped together
        - Prevents "MaxFileSize /9000" from jumping to bottom on every edit
        - Users see edits where they expect them (no config reorganization)

        Replaces any existing values for the key. If line_number is 0 (default)
        and the key already exists, preserves the original line number to ensure
        in-place updates rather than appends.

        Args:
            key: The configuration option name
            value: The value to set
            line_number: Optional line number for this value (0 = auto-detect)
        """
        # If line_number not provided, try to preserve existing line number
        if line_number == 0 and key in self.values:
            existing_values = self.values[key]
            if existing_values and existing_values[0].line_number > 0:
                # Preserve the original line number for in-place update
                line_number = existing_values[0].line_number

            # Blank orphaned raw_lines for any extra entries beyond the first.
            # Without this, duplicate lines from prior corruption persist
            # because to_string() keeps unmodified raw_lines verbatim.
            for extra in existing_values[1:]:
                if extra.line_number > 0 and extra.line_number <= len(self.raw_lines):
                    self.raw_lines[extra.line_number - 1] = ""

        self.values[key] = [ClamAVConfigValue(value=value, line_number=line_number)]

    def add_value(self, key: str, value: str, line_number: int = 0) -> None:
        """
        Add a value to a configuration key (for multi-value options).

        Args:
            key: The configuration option name
            value: The value to add
            line_number: Optional line number for this value
        """
        if key not in self.values:
            self.values[key] = []
        self.values[key].append(ClamAVConfigValue(value=value, line_number=line_number))

    def remove_key(self, key: str) -> None:
        """
        Remove a key and blank its original lines from raw_lines.

        This ensures that when to_string() reconstructs the file, the old
        lines for this key are replaced with empty strings (which become
        blank lines) rather than being kept verbatim.  Without this,
        values.pop() would orphan the raw_lines entries and cause
        duplicates when new values are later appended with line_number=0.

        Args:
            key: The configuration option name to remove
        """
        if key in self.values:
            for config_value in self.values[key]:
                if config_value.line_number > 0 and config_value.line_number <= len(self.raw_lines):
                    self.raw_lines[config_value.line_number - 1] = ""
            del self.values[key]

    def has_key(self, key: str) -> bool:
        """
        Check if a configuration key exists.

        Args:
            key: The configuration option name

        Returns:
            True if the key exists with at least one value
        """
        return key in self.values and len(self.values[key]) > 0

    def get_bool(self, key: str) -> bool | None:
        """
        Get a boolean configuration value.

        ClamAV uses 'yes'/'no' or 'true'/'false' for booleans.

        Args:
            key: The configuration option name

        Returns:
            True if value is 'yes'/'true', False if 'no'/'false', None if missing
        """
        value = self.get_value(key)
        if value is None:
            return None
        value_lower = value.lower()
        if value_lower in ("yes", "true", "1"):
            return True
        if value_lower in ("no", "false", "0"):
            return False
        return None

    def get_int(self, key: str) -> int | None:
        """
        Get an integer configuration value.

        Args:
            key: The configuration option name

        Returns:
            The integer value if valid, None otherwise
        """
        value = self.get_value(key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def to_string(self) -> str:
        """
        Serialize the configuration back to a string.

        Preserves the original file structure by using raw_lines as a base
        and updating only the modified values. Comments and empty lines
        are preserved in their original positions.

        Returns:
            The configuration as a string ready to write to a file
        """
        if not self.raw_lines:
            # No original content - generate from values only
            lines = []
            for key, value_list in self.values.items():
                for config_value in value_list:
                    if config_value.value:
                        lines.append(f"{key} {config_value.value}")
                    else:
                        # Boolean-style option with no value
                        lines.append(key)
            return "\n".join(lines) + "\n" if lines else ""

        # Build a map of line numbers to new values
        # Track which values have been written by (key, value_index)
        line_updates: dict[int, str] = {}
        value_indices: dict[str, int] = {}

        for key in self.values:
            value_indices[key] = 0

        # First pass: identify which lines need updating based on parsed values
        for key, value_list in self.values.items():
            for _i, config_value in enumerate(value_list):
                if config_value.line_number > 0:
                    # This value has a known line number - update that line
                    if config_value.value:
                        new_line = f"{key} {config_value.value}"
                    else:
                        new_line = key
                    line_updates[config_value.line_number] = new_line

        # Build output lines
        output_lines = []
        for line_number, line in enumerate(self.raw_lines, start=1):
            if line_number in line_updates:
                # Replace this line with updated value
                output_lines.append(line_updates[line_number])
            else:
                # Keep original line (strip trailing newline for consistency)
                output_lines.append(line.rstrip("\n\r"))

        # Add any new values that don't have line numbers
        new_values = []
        for key, value_list in self.values.items():
            for config_value in value_list:
                if config_value.line_number == 0:
                    # New value without a line number
                    if config_value.value:
                        new_values.append(f"{key} {config_value.value}")
                    else:
                        new_values.append(key)

        if new_values:
            # Add blank line separator if content exists
            if output_lines and output_lines[-1].strip():
                output_lines.append("")
            output_lines.extend(new_values)

        # Join with newlines and ensure trailing newline
        result = "\n".join(output_lines)
        if result and not result.endswith("\n"):
            result += "\n"
        return result


def parse_config(file_path: str) -> tuple[ClamAVConfig | None, str | None]:
    """
    Parse a ClamAV configuration file.

    Reads and parses ClamAV config files (freshclam.conf, clamd.conf) which use
    a simple key-value format (not INI format, no sections).

    Format:
    - Key Value (separated by space, value is everything after first space)
    - Lines starting with # are comments
    - Empty lines are preserved
    - Same key can appear multiple times (multi-value options)

    Args:
        file_path: Path to the configuration file

    Returns:
        Tuple of (config, error):
        - (ClamAVConfig, None) on success
        - (None, error_message) on failure
    """
    # Validate file path
    if not file_path or not file_path.strip():
        return (None, "No configuration file path specified")

    try:
        resolved_path = Path(file_path).resolve()
    except (OSError, RuntimeError) as e:
        return (None, f"Invalid file path: {e!s}")

    # Determine if we need to read across the Flatpak sandbox boundary.
    # System paths (/etc, /usr, /var, /opt) don't exist inside the sandbox,
    # so we must use flatpak-spawn --host cat to read them from the host.
    from .flatpak import is_flatpak, read_host_file

    use_host_read = is_flatpak() and any(
        str(resolved_path).startswith(prefix) for prefix in _SYSTEM_PATH_PREFIXES
    )

    if use_host_read:
        # In Flatpak: use config_file_exists() which already handles
        # flatpak-spawn --host test -f, then read via flatpak-spawn --host cat
        from .clamav_detection import config_file_exists

        if not config_file_exists(str(resolved_path)):
            return (None, f"Configuration file not found: {file_path}")

        content, error = read_host_file(str(resolved_path))
        if error or content is None:
            return (None, error or f"Failed to read {file_path}")

        raw_lines = content.splitlines(keepends=True)
        logger.debug("Read config via flatpak-spawn: %s (%d lines)", file_path, len(raw_lines))
    else:
        # Native path or user-writable path in Flatpak: direct file I/O
        if not resolved_path.exists():
            return (None, f"Configuration file not found: {file_path}")

        if not resolved_path.is_file():
            return (None, f"Path is not a file: {file_path}")

        if not os.access(resolved_path, os.R_OK):
            return (None, f"Permission denied: Cannot read {file_path}")

        try:
            with open(resolved_path, encoding="utf-8") as f:
                raw_lines = f.readlines()
        except UnicodeDecodeError:
            try:
                with open(resolved_path, encoding="latin-1") as f:
                    raw_lines = f.readlines()
            except Exception as e:
                return (None, f"Error reading configuration file: {e!s}")
        except PermissionError:
            return (None, f"Permission denied: Cannot read {file_path}")
        except OSError as e:
            return (None, f"Error reading configuration file: {e!s}")

    # Create config object
    config = ClamAVConfig(file_path=resolved_path, raw_lines=raw_lines)

    # Parse each line
    for line_number, line in enumerate(raw_lines, start=1):
        # Strip trailing whitespace/newline but preserve leading whitespace for raw_lines
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # Skip comment lines
        if stripped.startswith("#"):
            continue

        # ClamAV config files (clamd.conf/freshclam.conf) do not support inline
        # comments; only whole-line comments (handled above). Treat the entire
        # stripped line as content so values containing '#' are preserved.
        content = stripped

        # Parse key-value pair
        # ClamAV format: Key Value (separated by first space)
        parts = content.split(None, 1)  # Split on first whitespace

        if len(parts) == 0:
            # Empty after stripping (shouldn't happen, but handle it)
            continue

        key = parts[0]

        # Value is everything after the key (may be empty for boolean-style options)
        value = parts[1] if len(parts) > 1 else ""

        # Add value to config (supports multi-value options)
        config_value = ClamAVConfigValue(value=value, line_number=line_number)

        if key not in config.values:
            config.values[key] = []
        config.values[key].append(config_value)

    return (config, None)


# Configuration option type definitions
# Maps option names to their expected types and validation constraints
CONFIG_OPTION_TYPES = {
    # Path options (directory or file paths)
    "DatabaseDirectory": {"type": "path", "must_exist": False},
    "UpdateLogFile": {"type": "path", "must_exist": False},
    "LogFile": {"type": "path", "must_exist": False},
    "NotifyClamd": {"type": "path", "must_exist": False},
    "PidFile": {"type": "path", "must_exist": False},
    "LocalSocket": {"type": "path", "must_exist": False},
    "TemporaryDirectory": {"type": "path", "must_exist": False},
    # Boolean options
    "LogVerbose": {"type": "boolean"},
    "LogSyslog": {"type": "boolean"},
    "LogTime": {"type": "boolean"},
    "LogRotate": {"type": "boolean"},
    "Foreground": {"type": "boolean"},
    "ScanArchive": {"type": "boolean"},
    "ScanPDF": {"type": "boolean"},
    "ScanHTML": {"type": "boolean"},
    "ScanMail": {"type": "boolean"},
    "ScanOLE2": {"type": "boolean"},
    "ScanPE": {"type": "boolean"},
    "ScanELF": {"type": "boolean"},
    "ScanSWF": {"type": "boolean"},
    "DetectPUA": {"type": "boolean"},
    "AlertBrokenExecutables": {"type": "boolean"},
    "FollowDirectorySymlinks": {"type": "boolean"},
    "FollowFileSymlinks": {"type": "boolean"},
    "CrossFilesystems": {"type": "boolean"},
    # Integer options with ranges
    "Checks": {"type": "integer", "min": 0, "max": 50},
    "HTTPProxyPort": {"type": "integer", "min": 1, "max": 65535},
    "MaxRecursion": {"type": "integer", "min": 1, "max": 100},
    "MaxFiles": {"type": "integer", "min": 0, "max": 100000},
    "MaxThreads": {"type": "integer", "min": 1, "max": 256},
    "MaxDirectoryRecursion": {"type": "integer", "min": 0, "max": 100},
    # Size options that accept integer or size suffix like M, K
    "MaxEmbeddedPE": {"type": "size"},
    "MaxHTMLNormalize": {"type": "size"},
    "MaxHTMLNoTags": {"type": "size"},
    "MaxScriptNormalize": {"type": "size"},
    "MaxZipTypeRcg": {"type": "size"},
    # Pure integer options
    "MaxPartitions": {"type": "integer", "min": 0},
    "MaxIconsPE": {"type": "integer", "min": 0},
    "TCPSocket": {"type": "integer", "min": 1, "max": 65535},
    "IdleTimeout": {"type": "integer", "min": 0},
    "ReadTimeout": {"type": "integer", "min": 0},
    "CommandReadTimeout": {"type": "integer", "min": 0},
    "SendBufTimeout": {"type": "integer", "min": 0},
    # Size options (accept integer or size suffix like M, K)
    "MaxScanSize": {"type": "size"},
    "MaxFileSize": {"type": "size"},
    "StreamMaxLength": {"type": "size"},
    "MaxScanTime": {"type": "integer", "min": 0},
    # String options (no special validation, just non-empty)
    "HTTPProxyServer": {"type": "string"},
    "HTTPProxyUsername": {"type": "string"},
    "HTTPProxyPassword": {"type": "string"},
    "DatabaseMirror": {"type": "string"},
    "DatabaseOwner": {"type": "string"},
    "User": {"type": "string"},
    # URL options (multi-value, supports http(s)/ftp(s)/file URLs)
    "DatabaseCustomURL": {"type": "url"},  # Third-party signature databases
    "PrivateMirror": {"type": "url"},  # Private mirror URLs
    # Additional boolean options
    "ScriptedUpdates": {"type": "boolean"},  # Enable/disable scripted updates
}

_SIZE_SUFFIX_TO_MB = {
    "K": 1 / 1024,
    "M": 1,
    "G": 1024,
    "T": 1024 * 1024,
}


def size_value_to_megabytes(value: str | None) -> int | None:
    """
    Convert a ClamAV size value into an integer number of megabytes.

    For ClamUI's scanner settings UI, bare integer values are interpreted as
    megabytes for backward compatibility with older buggy saves that wrote
    "10" instead of "10M".

    Args:
        value: Raw ClamAV size value (e.g. "10M", "1G", "0", "10")

    Returns:
        Integer megabyte value, or None if the value cannot be parsed
    """
    if value is None:
        return None

    raw = value.strip()
    if not raw:
        return None

    if raw.isdigit():
        return int(raw)

    suffix = raw[-1].upper()
    number_part = raw[:-1].strip()
    if suffix not in _SIZE_SUFFIX_TO_MB or not number_part.isdigit():
        return None

    size_mb = int(number_part) * _SIZE_SUFFIX_TO_MB[suffix]
    return math.ceil(size_mb)


def megabytes_to_size_value(value_mb: int) -> str:
    """
    Serialize a UI megabyte value into a ClamAV size string.

    Args:
        value_mb: Integer size in megabytes

    Returns:
        ClamAV config value ("0" for unlimited, otherwise "<n>M")
    """
    return "0" if value_mb <= 0 else f"{value_mb}M"


def normalize_clamd_size_limit_units(config: ClamAVConfig | None) -> bool:
    """
    Normalize buggy bare-integer clamd size limits to explicit megabyte values.

    Older ClamUI versions saved MaxFileSize/MaxScanSize as plain integers even
    though the UI labels them in megabytes. ClamAV interprets those plain
    integers as bytes, so "10" becomes 10 bytes instead of 10 MB.

    Args:
        config: Parsed clamd.conf configuration

    Returns:
        True if any values were rewritten, False otherwise
    """
    if config is None:
        return False

    changed = False
    for key in ("MaxFileSize", "MaxScanSize"):
        raw_value = config.get_value(key)
        if raw_value is None:
            continue

        normalized = raw_value.strip()
        if normalized.isdigit():
            value_mb = int(normalized)
            if value_mb > 0:
                config.set_value(key, megabytes_to_size_value(value_mb))
                changed = True

    return changed


def validate_option(key: str, value: str) -> tuple[bool, str | None]:
    """
    Validate a configuration option value.

    Args:
        key: The configuration option name
        value: The value to validate

    Returns:
        Tuple of (is_valid, error_message):
        - (True, None) if valid
        - (False, error_message) if invalid
    """
    if key not in CONFIG_OPTION_TYPES:
        # Unknown option - allow it (ClamAV may support options we don't know about)
        return (True, None)

    option_spec = CONFIG_OPTION_TYPES[key]
    option_type = option_spec.get("type", "string")

    if option_type == "path":
        if not value:
            return (False, f"{key}: path cannot be empty")
        must_exist = option_spec.get("must_exist", False)
        path = Path(value).expanduser()
        if must_exist and not path.exists():
            return (False, f"{key}: path does not exist: {value}")
        return (True, None)

    elif option_type == "boolean":
        if value.lower() not in ("yes", "no", "true", "false", "1", "0"):
            return (False, f"{key}: invalid boolean value: {value}")
        return (True, None)

    elif option_type == "integer":
        try:
            int_val = int(value)
        except ValueError:
            return (False, f"{key}: not a valid integer: {value}")
        # Check range constraints
        if "min" in option_spec and int_val < option_spec["min"]:
            return (
                False,
                f"{key}: value {int_val} is below minimum {option_spec['min']}",
            )
        if "max" in option_spec and int_val > option_spec["max"]:
            return (
                False,
                f"{key}: value {int_val} exceeds maximum {option_spec['max']}",
            )
        return (True, None)

    elif option_type == "size":
        # Parse size with optional suffix (M, K, G, etc.)
        if not value:
            return (False, f"{key}: size cannot be empty")
        # Basic validation - just check it starts with a number
        if not value[0].isdigit():
            return (False, f"{key}: size must start with a number: {value}")
        return (True, None)

    elif option_type == "string":
        if not value:
            return (False, f"{key}: string value cannot be empty")
        return (True, None)

    elif option_type == "url":
        # URL validation for DatabaseCustomURL, PrivateMirror, etc.
        if not value:
            return (True, None)  # Empty is valid (allows clearing)
        # Valid schemes for freshclam
        valid_schemes = ("http://", "https://", "ftp://", "ftps://", "file://")
        if not any(value.lower().startswith(scheme) for scheme in valid_schemes):
            return (
                False,
                f"{key}: URL must start with http(s)://, ftp(s)://, or file://",
            )
        return (True, None)

    return (True, None)


def write_config(config: ClamAVConfig) -> tuple[bool, str | None]:
    """
    Write a configuration object back to its file.

    Args:
        config: The ClamAVConfig object to write

    Returns:
        Tuple of (success, error_message):
        - (True, None) on success
        - (False, error_message) on failure
    """
    if not config.file_path:
        return (False, "No file path specified in config object")

    try:
        # Create a backup of the original file
        backup_path = Path(str(config.file_path) + ".bak")
        if config.file_path.exists():
            shutil.copy2(config.file_path, backup_path)

        # Write the updated config
        content = config.to_string()
        with open(config.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return (True, None)
    except PermissionError:
        return (False, f"Permission denied: Cannot write to {config.file_path}")
    except OSError as e:
        return (False, f"Error writing configuration file: {e!s}")
    except Exception as e:
        return (False, f"Unexpected error writing configuration: {e!s}")


def validate_config_file(file_path: str) -> tuple[bool, list[str]]:
    """
    Validate all options in a configuration file.

    Checks that all configuration values are valid according to their type
    and constraints.

    Args:
        file_path: Path to the configuration file

    Returns:
        Tuple of (is_valid, list_of_errors):
        - (True, []) if all options are valid
        - (False, [error1, error2, ...]) if there are validation errors
    """
    config, error = parse_config(file_path)
    if error:
        return (False, [error])

    if config is None:
        return (False, ["Configuration file could not be parsed"])

    errors = []
    for key, value_list in config.values.items():
        for config_value in value_list:
            is_valid, error_msg = validate_option(key, config_value.value)
            if not is_valid:
                errors.append(error_msg)

    return (len(errors) == 0, errors)


def get_config_summary(config: ClamAVConfig) -> str:
    """
    Get a human-readable summary of the configuration.

    Args:
        config: The ClamAVConfig object

    Returns:
        A formatted string summary of the configuration
    """
    if not config.values:
        return "No configuration options defined"

    lines = []
    lines.append(f"Configuration file: {config.file_path}")
    lines.append(f"Total options: {len(config.values)}")
    lines.append("")

    # Group by type
    by_type: dict[str, list[tuple[str, list[str]]]] = {}
    for key, value_list in sorted(config.values.items()):
        option_type = CONFIG_OPTION_TYPES.get(key, {}).get("type", "unknown")
        if option_type not in by_type:
            by_type[option_type] = []
        values = [v.value for v in value_list]
        by_type[option_type].append((key, values))

    for option_type in sorted(by_type.keys()):
        lines.append(f"{option_type.upper()} Options:")
        for key, values in by_type[option_type]:
            if len(values) == 1:
                lines.append(f"  {key}: {values[0]}")
            else:
                lines.append(f"  {key}:")
                for value in values:
                    lines.append(f"    - {value}")
        lines.append("")

    return "\n".join(lines)


def validate_config(config: ClamAVConfig | None) -> tuple[bool, list[str]]:
    """
    Validate all options in a ClamAVConfig object.

    Args:
        config: The ClamAVConfig object to validate (can be None if parse failed)

    Returns:
        Tuple of (is_valid, list_of_errors):
        - (True, []) if all options are valid
        - (False, [error1, error2, ...]) if there are validation errors or config is None
    """
    if config is None:
        return (False, ["Configuration is not loaded. Cannot validate."])

    errors = []
    for key, value_list in config.values.items():
        for config_value in value_list:
            is_valid, error_msg = validate_option(key, config_value.value)
            if not is_valid:
                errors.append(error_msg)

    return (len(errors) == 0, errors)


def backup_config(file_path: str) -> None:
    """
    Create a backup of a configuration file.

    Creates a timestamped backup in the same directory as the original file.
    In Flatpak, system paths are not directly writable so the backup is
    skipped for those paths (the elevated write helper preserves originals).

    Args:
        file_path: Path to the configuration file to backup
    """
    path = Path(file_path)

    # In Flatpak, system paths are read-only from the sandbox.
    # Attempting shutil.copy2 would always fail, so skip early.
    from .flatpak import is_flatpak

    if is_flatpak() and any(
        str(path.resolve()).startswith(prefix) for prefix in _SYSTEM_PATH_PREFIXES
    ):
        logger.debug("Skipping backup of %s (system path in Flatpak)", file_path)
        return

    if not path.exists():
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(f".bak.{timestamp}")

    try:
        shutil.copy2(path, backup_path)
    except (OSError, PermissionError):
        # Silently fail - backup is best effort
        logger.debug("Failed to create ClamAV config backup at %s", backup_path, exc_info=True)


def _path_needs_elevation(file_path: Path) -> bool:
    """
    Check whether a config path requires elevated permissions for writing.

    Inside a Flatpak sandbox the system config directories (/etc, /usr, /var,
    /opt) are NOT the host's: the runtime supplies its own copies, which are
    often writable but ephemeral.  A direct write there appears to succeed and
    then silently vanishes on the next launch (issue #136), while reads are
    redirected to the host via ``flatpak-spawn --host``.  To keep writes and
    reads on the same (host) file, always route system paths through the host
    privileged helper when running in Flatpak rather than trusting the
    sandbox-local writability probe below.

    Args:
        file_path: Target configuration file path

    Returns:
        True if elevation is required, False otherwise
    """
    from .flatpak import is_flatpak

    if is_flatpak() and any(
        str(file_path.resolve()).startswith(prefix) for prefix in _SYSTEM_PATH_PREFIXES
    ):
        return True

    # Already root: every path is directly writable, so never spawn pkexec.
    # This check sits *after* the Flatpak system-path guard above because being
    # root inside the sandbox does not fix the ephemeral-copy redirection that
    # forces those writes through the host helper (issue #136); it only covers
    # the native case where the app was launched with elevated privileges.
    if is_running_as_root():
        return False

    # If the target file already exists, decide on the file's own writability
    # rather than its parent directory.  A user-owned /etc/freshclam.conf (e.g.
    # after `chown $USER /etc/freshclam.conf`) is directly writable even though
    # /etc is not -- the old parent-directory probe always demanded elevation
    # in that case, so even the documented chown workaround failed (issue #143).
    if file_path.exists():
        return not os.access(file_path, os.W_OK)

    parent_dir = file_path.parent

    try:
        # Test if directory is writable
        if parent_dir.exists():
            # Check write permission on existing directory
            test_file = parent_dir / f".write_test_{os.getpid()}"
            try:
                test_file.touch()
                test_file.unlink()
            except (PermissionError, OSError):
                return True
        else:
            # Directory doesn't exist - check if we can create it
            try:
                parent_dir.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError):
                return True
    except Exception:
        # If we can't determine, assume elevation is needed
        return True

    return False


def _running_in_flatpak() -> bool:
    """Return whether this process is running inside a Flatpak sandbox."""
    from .flatpak import is_flatpak

    return is_flatpak()


def _write_config_direct(file_path: Path, content: str) -> tuple[bool, str | None]:
    """
    Write config content directly without privilege elevation.

    Args:
        file_path: Target path to write
        content: Serialized configuration content

    Returns:
        Tuple of (success, error_message)
    """
    try:
        file_path.write_text(content, encoding="utf-8")
        # Set reasonable permissions for user files
        file_path.chmod(0o644)
        return (True, None)
    except Exception as e:
        return (False, f"Failed to write config: {e!s}")


def _is_root_owned_regular(path: str, *, require_executable: bool) -> bool:
    """Return whether ``path`` is a real, root-owned regular file that is not
    group- or world-writable.

    ``os.stat(..., follow_symlinks=False)`` inspects the directory entry
    itself, so a symlink (or any non-regular file) is rejected outright rather
    than followed -- a symlinked wrapper or module must never reach pkexec.
    When ``require_executable`` is set the owner-execute bit must also be
    present.  Existence is probed by :func:`Path.is_file` /
    :func:`os.access` in the caller; this function is the *trust* gate, never
    the sole existence test.
    """
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISREG(st.st_mode)
        and st.st_uid == 0
        and not (st.st_mode & 0o022)
        and (not require_executable or bool(st.st_mode & 0o100))
    )


def _is_root_owned_dir(path: str) -> bool:
    """Return whether ``path`` is a real, root-owned directory that is not
    group- or world-writable, rejecting symlinks outright."""
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == 0 and not (st.st_mode & 0o022)


def _get_privileged_writer_path() -> str | None:
    """
    Resolve the privileged helper command path for pkexec.

    Only the host-installed canonical ``/usr/bin/clamui-apply-preferences`` is
    ever returned, so a user-writable venv or ``~/.local`` wrapper that merely
    shares the helper name can never be handed to pkexec -- otherwise an
    unprivileged user could run arbitrary code as root.

    Native mode inspects *only* the literal canonical path -- it never consults
    ``sys.executable`` or ``PATH`` -- and accepts it only when the wrapper, the
    root-owned ``/usr/lib/clamui`` library directory, and both self-contained
    modules the wrapper imports are real, root-owned, not group/world-writable
    entries (the wrapper owner-executable); a user-owned but runnable binary
    would otherwise let an unprivileged user execute arbitrary code as root
    through pkexec.  Existence is still probed with ``Path.is_file`` /
    ``os.access`` so a venv-only environment fails closed, but those are never
    the sole basis for acceptance.  Under Flatpak the existing host search
    (``flatpak-spawn --host which``) is retained so the helper is resolved
    against the host filesystem rather than the sandbox-internal ``/app/bin``
    (issue #136), but the result is accepted only when it is exactly the
    canonical path.  ``/app``, ``~/.local`` and venv paths, alternate/symlink
    spellings, and absence all yield ``None``.

    Returns:
        The canonical helper path when every native trust check passes (or the
        Flatpak host search resolves the exact canonical path), else None.
    """
    canonical = _PRIVILEGED_HELPER_PATH

    if _running_in_flatpak():
        from .flatpak import which_host_command

        candidate = which_host_command(Path(canonical).name)
        # Accept only the exact canonical path on the host; a user-writable
        # venv/``~/.local`` wrapper or a non-canonical symlink spelling must
        # never reach pkexec.
        return canonical if candidate == canonical else None

    # Existence gate: a monkey-patched environment (e.g. a venv-only PATH) must
    # fail closed here.  This is never the sole basis for acceptance -- the
    # trust checks below also require root ownership, a real directory, and root
    # owned modules, so a user-owned but executable binary cannot reach pkexec.
    if not (Path(canonical).is_file() and os.access(canonical, os.X_OK)):
        return None
    if not _is_root_owned_regular(canonical, require_executable=True):
        return None
    if not _is_root_owned_dir(_PRIVILEGED_LIB_DIR):
        return None
    for module_path in _PRIVILEGED_LIB_MODULES:
        if not _is_root_owned_regular(module_path, require_executable=False):
            return None
    return canonical


def privileged_writer_available() -> bool:
    """Return whether the privileged configuration writer can be resolved."""
    return _get_privileged_writer_path() is not None


def _make_staging_dir() -> Path:
    """
    Create a per-invocation staging directory with mode 0o700.

    The staging root MUST match what the privileged helper expects: the helper
    independently recomputes it via ``staging_root_for_uid`` and *rejects* any
    staged source that does not resolve under that exact directory
    (``validate_source_for_uid``).  We therefore use that single source of
    truth -- ``<passwd-home>/.cache/clamui/privileged-staging``, derived from
    the passwd database (``pwd.getpwuid``) and never from ``$HOME`` -- as the
    only parent.

    Native and Flatpak share this one root: it lives on the host-visible home
    filesystem that the Flatpak manifest grants with ``--filesystem=host``,
    so the privileged helper (which runs on the host via
    ``flatpak-spawn --host`` under Flatpak) reads staged files from the exact
    directory the caller wrote them to.  There is no native/Flatpak branch
    and no second allowed root.

    Earlier ``$XDG_RUNTIME_DIR`` / ``$XDG_CACHE_HOME`` (and, before that,
    ``/run/user/<uid>``) roots produced staged paths the helper structurally
    refused -- they were never equal to the root it recomputes -- turning a
    recoverable situation into an opaque "outside staging root" failure.  If
    the canonical root cannot be created we now raise a clear error instead.

    Returns:
        Newly-created staging directory path with mode 0o700.

    Raises:
        OSError: If the canonical staging root could not be created.
    """
    uid = os.getuid()
    parent = staging_root_for_uid(uid)
    parent.mkdir(parents=True, exist_ok=True)
    os.chmod(parent, 0o700)
    staging = parent / uuid.uuid4().hex
    staging.mkdir(mode=0o700)
    os.chmod(staging, 0o700)
    return staging


def write_configs_with_elevation(configs: list[ClamAVConfig]) -> tuple[bool, str | None]:
    """
    Write one or more configuration files, requesting elevation at most once.

    User-writable paths are written directly. System paths are staged only in
    the per-user, mode-``0o700`` directory returned by
    ``staging_root_for_uid`` and handed to the privileged helper via one
    ``pkexec`` invocation. If that canonical staging root cannot be created,
    the operation fails before invoking pkexec.

    The helper is required: there is no inline-shell fallback.  If the
    helper is not installed on the host we surface a clear error rather
    than silently running an unvalidated ``pkexec sh -c`` script (the
    behaviour that was VULN-001).

    Args:
        configs: Configuration objects to write.

    Returns:
        Tuple of ``(success, error_message)``:

        - ``(True, None)`` on success.
        - ``(False, error_message)`` on failure.
    """
    if not configs:
        return (True, None)

    try:
        pending_writes: list[tuple[Path, str]] = []
        for config in configs:
            if not config.file_path:
                return (False, "No file path specified in config object")
            pending_writes.append((Path(config.file_path), config.to_string()))

        direct_writes: list[tuple[Path, str]] = []
        elevated_writes: list[tuple[Path, str]] = []
        for file_path, content in pending_writes:
            if _path_needs_elevation(file_path):
                elevated_writes.append((file_path, content))
            else:
                direct_writes.append((file_path, content))

        for file_path, content in direct_writes:
            success, error = _write_config_direct(file_path, content)
            if not success:
                return (False, error)

        if not elevated_writes:
            return (True, None)

        helper_path = _get_privileged_writer_path()
        if helper_path is None:
            if _running_in_flatpak():
                return (
                    False,
                    _(
                        "ClamUI privileged helper not installed on the host. "
                        "The Flatpak sandbox cannot write system ClamAV "
                        "configuration files such as /etc/clamav/*.conf "
                        "directly. Download the matching "
                        "'clamui-privileged-helper_<version>_all.deb' from "
                        "the ClamUI releases page and install it on the host "
                        "with 'sudo apt install "
                        "./clamui-privileged-helper_<version>_all.deb' (use "
                        "the same version as the Flatpak). 'sudo flatpak run "
                        "... install-privileged-helper' is not supported: the "
                        "sandbox /usr is not the host /usr."
                    ),
                )
            return (
                False,
                _(
                    "ClamUI privileged helper not installed. Run "
                    "'sudo clamui install-privileged-helper' on this host to "
                    "install it and enable saving system ClamAV "
                    "configuration."
                ),
            )

        staging_dir: Path | None = None
        try:
            staging_dir = _make_staging_dir()
            flat_pairs: list[str] = []
            for file_path, content in elevated_writes:
                staged_name = f"{uuid.uuid4().hex}.conf"
                staged_path = staging_dir / staged_name
                # Write with mode 0o600 so the helper's source-mode check
                # (``mode & 0o022 == 0``) accepts it.
                fd = os.open(
                    str(staged_path),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(content)
                os.chmod(staged_path, 0o600)
                flat_pairs.extend([str(staged_path), str(file_path)])

            use_host_spawn = _running_in_flatpak()
            prefix = ["flatpak-spawn", "--host"] if use_host_spawn else []

            if use_host_spawn:
                # The helper runs on the HOST via flatpak-spawn and reads the
                # staged files from the passwd-home cache root computed by
                # ``staging_root_for_uid``.  The Flatpak manifest exposes that
                # home filesystem to both sides; probe host visibility before
                # invoking pkexec so a permission mismatch fails clearly.
                probe = subprocess.run(
                    ["flatpak-spawn", "--host", "test", "-e", str(staging_dir)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if probe.returncode != 0:
                    return (
                        False,
                        _(
                            "The staging directory is not reachable by the privileged "
                            "helper running on the host, so preferences cannot be applied "
                            "from the Flatpak sandbox. A host-side ClamUI install is "
                            "required to change system configuration."
                        ),
                    )

            argv = [*prefix, "pkexec", helper_path, f"--protocol={PROTOCOL_VERSION}", *flat_pairs]
            result = subprocess.run(argv, capture_output=True, text=True, check=False)

            if result.returncode != 0:
                if result.returncode == 126:
                    return (
                        False,
                        _("Authentication was canceled. Configuration changes were not applied."),
                    )
                if result.returncode == 127:
                    return (
                        False,
                        _(
                            "Could not obtain administrator authorization to apply "
                            "these changes. If you were not shown a password prompt, "
                            "the ClamUI polkit policy or privileged helper is likely "
                            "not installed on this system -- install the "
                            "'clamui-privileged-helper' package (which provides "
                            "clamui-apply-preferences and its polkit policy) to "
                            "enable saving system configuration."
                        ),
                    )
                if result.returncode == 3:
                    return (
                        False,
                        _(
                            "Privileged helper rejected the request: missing "
                            "PKEXEC_UID. The polkit policy may be misconfigured."
                        ),
                    )
                if result.returncode == 4:
                    return (
                        False,
                        _(
                            "Privileged helper rejected the request: protocol "
                            "mismatch. Update the 'clamui-privileged-helper' "
                            "package on the host."
                        ),
                    )
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                return (False, f"Failed to write config: {error_msg}")

            try:
                shutil.rmtree(staging_dir)
            except OSError as cleanup_error:
                return (
                    False,
                    _(
                        "Configuration was applied, but ClamUI could not remove the staged "
                        "copy at {path}: {error}. Verify that this directory is removed."
                    ).format(path=staging_dir, error=cleanup_error),
                )
            staging_dir = None
            return (True, None)

        finally:
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)

    except FileNotFoundError:
        return (False, "pkexec not found - cannot elevate privileges")
    except Exception as e:
        return (False, f"Unexpected error: {e!s}")


def write_config_with_elevation(config: ClamAVConfig) -> tuple[bool, str | None]:
    """
    Write a configuration file with elevated privileges if needed.

    Automatically detects if the file needs privilege elevation:
    - User-writable paths (e.g., ~/.config/clamav/ in Flatpak): write directly
    - System paths (e.g., /etc/clamav/): use pkexec for elevation

    Args:
        config: The ClamAVConfig object to write

    Returns:
        Tuple of (success, error_message):
        - (True, None) on success
        - (False, error_message) on failure
    """
    return write_configs_with_elevation([config])
