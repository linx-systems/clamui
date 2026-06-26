# ClamUI Input Sanitization Module
"""
Input sanitization functions for log entries to prevent log injection attacks.

This module provides functions to sanitize user-controlled input (file paths,
threat names, ClamAV output) before storing in log entries. It protects against:
- Control characters that could manipulate terminal output
- ANSI escape sequences that could hide or modify displayed content
- Unicode bidirectional overrides that could obscure malicious filenames
- Null bytes that could truncate or confuse log parsing
- Newline injection in single-line fields that could forge log entries
"""

import re

# ANSI escape sequence pattern (CSI sequences and other escape codes)
# Matches ESC followed by [ and optional parameters, or other ESC sequences
ANSI_ESCAPE_PATTERN = re.compile(
    r"""
    \x1b     # ESC character
    (?:      # Non-capturing group for alternatives
        \[   # CSI sequence: ESC [
        [?]? # Optional ? prefix for private sequences
        [0-9;]*  # Optional numeric parameters separated by semicolons
        [a-zA-Z] # Final character (command)
    |
        [@A-Z\\\]^_]   # Other ESC: ESC + one Fe final byte (0x40-0x5F, excl. '['); leaves a lone ESC for the control-char pass to strip, so newlines/printables after a stray ESC are preserved
    )
    """,
    re.VERBOSE,
)

# Unicode bidirectional override characters that can be used to obscure text
# U+202A - U+202E: LRE, RLE, PDF, LRO, RLO (deprecated but still supported)
# U+2066 - U+2069: LRI, RLI, FSI, PDI (modern equivalents)
# U+200E, U+200F: LRM, RLM (bidi marks); U+061C: ALM (Arabic letter mark)
UNICODE_BIDI_PATTERN = re.compile(r"[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]")

# Sensitive value placeholders used across runtime and persisted logs.
REDACTED_PATH = "[REDACTED_PATH]"
REDACTED_HASH = "[REDACTED_HASH]"
REDACTED_URL = "[REDACTED_URL]"

# Hash-like values (SHA256, MD5, etc.) can identify files and should not appear
# in exported or persisted debug logs.
HASH_PATTERN = re.compile(r"\b[a-fA-F0-9]{32,128}\b")

# VirusTotal report URLs include the file hash in the path, so redact them as a unit.
VIRUSTOTAL_URL_PATTERN = re.compile(r"https?://(?:www\.)?virustotal\.com/\S+")

# Fast path matcher for likely path starts. Full boundary validation still
# happens in Python before a candidate is redacted.
PATH_START_PATTERN = re.compile(r"file://|~/|/|[A-Za-z]:[\\/]")

_PATH_BOUNDARY_CHARS = " \t\r\n'\"([{=,:"
_PATH_STOP_CHARS = "\r\n\t\"'<>|:,;)]}"


def _is_windows_path_start(text: str, index: int) -> bool:
    """Return True when text[index:] looks like an absolute Windows path."""
    return (
        index + 2 < len(text)
        and text[index].isalpha()
        and text[index + 1] == ":"
        and text[index + 2] in ("/", "\\")
    )


def _has_path_boundary(text: str, index: int) -> bool:
    """Return True when index is at a valid boundary for a path candidate."""
    return index == 0 or text[index - 1] in _PATH_BOUNDARY_CHARS


def _looks_like_path_continuation(text: str, start: int) -> bool:
    """
    Heuristic for allowing spaces inside a path candidate.

    We continue consuming after a space only if the following token still looks
    like a path segment or filename rather than normal prose.
    """
    index = start
    text_length = len(text)

    while index < text_length and text[index] == " ":
        index += 1

    if index >= text_length:
        return False

    token_has_dot = text[index] in (".", "~")

    while index < text_length:
        char = text[index]
        if char == " " or char in _PATH_STOP_CHARS:
            break
        if char in "/\\":
            return True
        if char == ".":
            token_has_dot = True
        index += 1

    return token_has_dot


def _consume_path(text: str, start: int) -> int:
    """Consume a filesystem-path-like substring starting at start."""
    index = start

    if text.startswith("file://", start):
        index += len("file://")
    elif text.startswith("~/", start):
        index += 2
    elif _is_windows_path_start(text, start):
        index += 3
    else:
        index += 1

    while index < len(text):
        char = text[index]

        if char in _PATH_STOP_CHARS:
            break

        if char == " ":
            if _looks_like_path_continuation(text, index + 1):
                index += 1
                continue
            break

        index += 1

    while index > start and text[index - 1] in ",;)]}":
        index -= 1

    return index


def redact_sensitive_log_data(text: str | None) -> str:
    """
    Redact filesystem paths and other file-identifying values from log text.

    This is intentionally privacy-first: it removes scan targets, file paths,
    file URIs, VirusTotal report URLs, and long hash-like values that can
    identify user files across shared logs.
    """
    if text is None:
        return ""

    redacted = VIRUSTOTAL_URL_PATTERN.sub(REDACTED_URL, text)
    redacted = HASH_PATTERN.sub(REDACTED_HASH, redacted)

    if "/" not in redacted and "\\" not in redacted and "~/" not in redacted:
        return redacted

    output: list[str] = []
    cursor = 0
    for match in PATH_START_PATTERN.finditer(redacted):
        start = match.start()
        if start < cursor or not _has_path_boundary(redacted, start):
            continue

        end = _consume_path(redacted, start)
        if end <= start:
            continue

        output.append(redacted[cursor:start])
        output.append(REDACTED_PATH)
        cursor = end

    if cursor == 0:
        return redacted

    output.append(redacted[cursor:])

    return "".join(output)


def sanitize_log_line(text: str | None) -> str:
    """
    Sanitize a string for use in single-line log fields.

    Removes control characters (including newlines), ANSI escape sequences,
    Unicode bidirectional overrides, and null bytes. This function is used
    for single-line fields like summary, path, and threat names where
    newlines could be used to inject fake log entries.

    Safe whitespace characters (space and tab) are preserved.

    Args:
        text: The input string to sanitize. If None, returns empty string.

    Returns:
        Sanitized string safe for single-line log fields

    Example:
        >>> sanitize_log_line("Clean\\npath")
        "Clean path"
        >>> sanitize_log_line("File\\x1b[31mRED\\x1b[0m")
        "FileRED"
        >>> sanitize_log_line("\\x00null\\x00bytes")
        "nullbytes"
    """
    if text is None:
        return ""

    # Remove null bytes first (they can truncate strings in some contexts)
    sanitized = text.replace("\x00", "")

    # Remove ANSI escape sequences
    sanitized = ANSI_ESCAPE_PATTERN.sub("", sanitized)

    # Remove Unicode bidirectional override characters
    sanitized = UNICODE_BIDI_PATTERN.sub("", sanitized)

    # Remove control characters except safe whitespace (space, tab)
    # Control characters are 0x00-0x1F and 0x7F (DEL)
    # We keep: 0x20 (space), 0x09 (tab)
    # We remove: 0x0A (LF), 0x0D (CR), and all other control characters
    result = []
    for char in sanitized:
        code = ord(char)
        # Strip surrogate code points (U+D800-U+DFFF) that arise from
        # reading non-UTF-8 filenames with surrogateescape error handling
        if 0xD800 <= code <= 0xDFFF:
            continue
        # Unicode line separators (NEL, LS, PS) are treated as line breaks by
        # str.splitlines(); map them to space so they cannot inject log lines.
        if char in ("\u0085", "\u2028", "\u2029"):
            result.append(" ")
            continue
        # Keep printable characters (>= 0x20) and tab (0x09)
        # Skip all other control characters (0x00-0x1F except 0x09), DEL (0x7F),
        # and C1 controls (0x80-0x9F, including the 8-bit CSI U+009B)
        if (code >= 0x20 or code == 0x09) and not (0x80 <= code <= 0x9F):
            if code != 0x7F:  # Skip DEL character
                result.append(char)
        # Control characters (including newlines) are replaced with space
        elif code in (0x0A, 0x0D):  # Newlines specifically become spaces
            result.append(" ")

    return "".join(result)


def sanitize_log_text(text: str | None) -> str:
    """
    Sanitize a string for use in multi-line log fields.

    Removes control characters (except newlines and tabs), ANSI escape sequences,
    Unicode bidirectional overrides, and null bytes. This function is used for
    multi-line fields like details and stdout where legitimate newlines should
    be preserved for readability.

    Safe whitespace characters (space, tab, newline, carriage return) are preserved.

    Args:
        text: The input string to sanitize. If None, returns empty string.

    Returns:
        Sanitized string safe for multi-line log fields

    Example:
        >>> sanitize_log_text("Line 1\\nLine 2")
        "Line 1\\nLine 2"
        >>> sanitize_log_text("Text\\x1b[32mGREEN\\x1b[0m")
        "TextGREEN"
        >>> sanitize_log_text("Data\\x00with\\x00nulls")
        "Datawithnulls"
    """
    if text is None:
        return ""

    # Remove null bytes first
    sanitized = text.replace("\x00", "")

    # Remove ANSI escape sequences
    sanitized = ANSI_ESCAPE_PATTERN.sub("", sanitized)

    # Remove Unicode bidirectional override characters
    sanitized = UNICODE_BIDI_PATTERN.sub("", sanitized)

    # Remove control characters except safe whitespace (space, tab, newline, CR)
    # Control characters are 0x00-0x1F and 0x7F (DEL)
    # We keep: 0x20 (space), 0x09 (tab), 0x0A (LF), 0x0D (CR)
    result = []
    for char in sanitized:
        code = ord(char)
        # Strip surrogate code points (U+D800-U+DFFF) that arise from
        # reading non-UTF-8 filenames with surrogateescape error handling
        if 0xD800 <= code <= 0xDFFF:
            continue
        # Unicode line separators (NEL, LS, PS) are treated as line breaks by
        # str.splitlines(); map them to space rather than preserving them as
        # newlines (only LF/CR are legitimate line breaks here).
        if char in ("\u0085", "\u2028", "\u2029"):
            result.append(" ")
            continue
        # Keep printable characters (>= 0x20) and safe whitespace; drop C1
        # controls (0x80-0x9F, including the 8-bit CSI U+009B)
        if code >= 0x20 and not (0x80 <= code <= 0x9F):
            if code != 0x7F:  # Skip DEL character
                result.append(char)
        elif code in (0x09, 0x0A, 0x0D):  # Keep tab, LF, CR
            result.append(char)
        # All other control characters are silently removed

    return "".join(result)


def sanitize_path_for_logging(text: str | None) -> str:
    """
    Sanitize text for logging by redacting sensitive path-like values.

    This function is used for debug logs and exported log content where user
    scan targets, file hashes, or report URLs must never be written to disk.

    Args:
        text: The text to sanitize. If None, returns empty string.

    Returns:
        Text with sensitive values replaced by redaction placeholders.

    Example:
        >>> sanitize_path_for_logging("/home/user/Documents/file.txt")
        "[REDACTED_PATH]"
        >>> sanitize_path_for_logging("Processing /home/user/file.txt now")
        "Processing [REDACTED_PATH] now"
        >>> sanitize_path_for_logging("/etc/clamav/clamd.conf")
        "[REDACTED_PATH]"
        >>> sanitize_path_for_logging(None)
        ""
    """
    return redact_sensitive_log_data(text)


def sanitize_surrogate_path(path: str) -> str:
    """
    Replace surrogate escape characters in a filesystem path with U+FFFD.

    On Linux, filenames are raw bytes (not necessarily UTF-8). Python 3 uses
    PEP 383 "surrogate escape" to represent non-UTF-8 bytes as code points
    in U+DC80-U+DCFF. These surrogates cause UnicodeEncodeError when the
    string is later encoded to UTF-8 (e.g., writing to a file, logging, or
    passing to subprocess).

    This function replaces any surrogate code points with the Unicode
    replacement character (U+FFFD), making the string safe for UTF-8 encoding.

    Args:
        path: A filesystem path that may contain surrogate escapes.

    Returns:
        The path with surrogates replaced by U+FFFD.
    """
    # Fast path: try encoding to UTF-8; if it works, no surrogates present
    try:
        path.encode("utf-8")
        return path
    except UnicodeEncodeError:
        return path.encode("utf-8", errors="replace").decode("utf-8")
