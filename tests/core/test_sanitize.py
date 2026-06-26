# ClamUI Input Sanitization Tests
"""Unit tests for the sanitize module functions."""

from src.core.sanitize import (
    REDACTED_HASH,
    REDACTED_PATH,
    REDACTED_URL,
    _consume_path,
    _has_path_boundary,
    _is_windows_path_start,
    _looks_like_path_continuation,
    redact_sensitive_log_data,
    sanitize_log_line,
    sanitize_log_text,
    sanitize_path_for_logging,
)


class TestSanitizeLogLine:
    """Tests for the sanitize_log_line function (single-line fields)."""

    def test_sanitize_log_line_clean_text(self):
        """Test sanitize_log_line with clean text - no changes."""
        assert (
            sanitize_log_line("Clean text without special characters")
            == "Clean text without special characters"
        )

    def test_sanitize_log_line_none_input(self):
        """Test sanitize_log_line with None input returns empty string."""
        assert sanitize_log_line(None) == ""

    def test_sanitize_log_line_empty_string(self):
        """Test sanitize_log_line with empty string returns empty string."""
        assert sanitize_log_line("") == ""

    def test_sanitize_log_line_whitespace_only(self):
        """Test sanitize_log_line with whitespace-only string preserves spaces and tabs."""
        assert sanitize_log_line("   \t  ") == "   \t  "

    def test_sanitize_log_line_removes_newlines(self):
        """Test sanitize_log_line removes newline characters (LF)."""
        assert sanitize_log_line("Line 1\nLine 2") == "Line 1 Line 2"
        assert sanitize_log_line("Line 1\n\nLine 2") == "Line 1  Line 2"

    def test_sanitize_log_line_removes_carriage_returns(self):
        """Test sanitize_log_line removes carriage return characters (CR)."""
        assert sanitize_log_line("Line 1\rLine 2") == "Line 1 Line 2"
        assert sanitize_log_line("Line 1\r\nLine 2") == "Line 1  Line 2"

    def test_sanitize_log_line_preserves_tabs(self):
        """Test sanitize_log_line preserves tab characters."""
        assert sanitize_log_line("Column1\tColumn2\tColumn3") == "Column1\tColumn2\tColumn3"

    def test_sanitize_log_line_preserves_spaces(self):
        """Test sanitize_log_line preserves space characters."""
        assert sanitize_log_line("Word1 Word2  Word3   Word4") == "Word1 Word2  Word3   Word4"

    def test_sanitize_log_line_removes_null_bytes(self):
        """Test sanitize_log_line removes null bytes."""
        assert sanitize_log_line("Text\x00with\x00nulls") == "Textwithnulls"
        assert sanitize_log_line("\x00Start") == "Start"
        assert sanitize_log_line("End\x00") == "End"

    def test_sanitize_log_line_removes_ansi_escape_sequences(self):
        """Test sanitize_log_line removes ANSI escape sequences."""
        # Basic color codes
        assert sanitize_log_line("Normal\x1b[31mRED\x1b[0m") == "NormalRED"
        assert sanitize_log_line("\x1b[32mGREEN\x1b[0m") == "GREEN"
        assert sanitize_log_line("\x1b[1;33mYELLOW BOLD\x1b[0m") == "YELLOW BOLD"

        # Cursor movement
        assert sanitize_log_line("Text\x1b[2JClear") == "TextClear"
        assert sanitize_log_line("\x1b[HHome") == "Home"

        # Complex ANSI sequences
        assert sanitize_log_line("\x1b[1;31;40mComplex\x1b[0m") == "Complex"

    def test_sanitize_log_line_removes_unicode_bidi_overrides(self):
        """Test sanitize_log_line removes Unicode bidirectional override characters."""
        # U+202A - U+202E (deprecated but still supported)
        assert sanitize_log_line("Text\u202aOverride\u202c") == "TextOverride"
        assert sanitize_log_line("\u202bLRE\u202c") == "LRE"
        assert sanitize_log_line("Test\u202dTest\u202c") == "TestTest"

        # U+2066 - U+2069 (modern equivalents)
        assert sanitize_log_line("Text\u2066Override\u2069") == "TextOverride"
        assert sanitize_log_line("\u2067RLI\u2069") == "RLI"
        assert sanitize_log_line("Test\u2068FSI\u2069") == "TestFSI"

    def test_sanitize_log_line_removes_control_characters(self):
        """Test sanitize_log_line removes various control characters."""
        # Bell, backspace, form feed, etc.
        assert sanitize_log_line("Text\x07Bell") == "TextBell"
        assert sanitize_log_line("Text\x08Backspace") == "TextBackspace"
        assert sanitize_log_line("Text\x0cFormFeed") == "TextFormFeed"

        # DEL character (0x7F)
        assert sanitize_log_line("Text\x7fDEL") == "TextDEL"

        # Various control characters
        assert sanitize_log_line("\x01\x02\x03Text") == "Text"
        assert sanitize_log_line("Text\x1b\x1cTest") == "TextTest"

    def test_sanitize_log_line_combined_malicious_input(self):
        """Test sanitize_log_line with combined malicious characters."""
        # Combining newlines, ANSI, null bytes, and bidi overrides
        malicious = "Path\x00\nFile\x1b[31m\u202aEvil\u202c\x1b[0m"
        # Should remove: \x00, \n (becomes space), \x1b[31m, \u202A, \u202C, \x1b[0m
        assert sanitize_log_line(malicious) == "Path FileEvil"

    def test_sanitize_log_line_log_injection_attempt(self):
        """Test sanitize_log_line prevents log injection with fake entries."""
        # Attacker tries to inject a fake log entry using newlines
        injection = "legitimate.txt\n[CLEAN] Fake scan result for malware.exe"
        # Newlines should become spaces, preventing injection
        assert (
            sanitize_log_line(injection)
            == "legitimate.txt [CLEAN] Fake scan result for malware.exe"
        )

    def test_sanitize_log_line_ansi_obfuscation_attempt(self):
        """Test sanitize_log_line prevents ANSI-based obfuscation."""
        # Attacker tries to hide text with ANSI sequences
        obfuscated = "safe.txt\x1b[8mHIDDEN_MALWARE\x1b[0m"
        # Hidden text should be revealed (ANSI codes removed)
        assert sanitize_log_line(obfuscated) == "safe.txtHIDDEN_MALWARE"

    def test_sanitize_log_line_unicode_spoofing(self):
        """Test sanitize_log_line prevents Unicode direction spoofing."""
        # Right-to-left override to reverse displayed text
        # "file\u202Etxt.evil" displays as "file" + "live.txt" (reversed)
        spoofed = "file\u202etxt.evil"
        assert sanitize_log_line(spoofed) == "filetxt.evil"

    def test_sanitize_log_line_very_long_string(self):
        """Test sanitize_log_line handles very long strings."""
        # 10,000 character string
        long_text = "A" * 10000
        result = sanitize_log_line(long_text)
        assert len(result) == 10000
        assert result == long_text

        # Long string with malicious content spread throughout
        long_malicious = ("Clean" + "\x00" + "Text" + "\n") * 1000
        result = sanitize_log_line(long_malicious)
        # Each iteration: "CleanText " (10 chars)
        assert len(result) == 10000
        assert "\x00" not in result
        assert "\n" not in result

    def test_sanitize_log_line_preserves_unicode_text(self):
        """Test sanitize_log_line preserves legitimate Unicode characters."""
        # Various language scripts
        assert sanitize_log_line("文档/テスト/résumé.pdf") == "文档/テスト/résumé.pdf"
        assert sanitize_log_line("Привет мир") == "Привет мир"
        assert sanitize_log_line("🔒 secure_file.txt") == "🔒 secure_file.txt"

    def test_sanitize_log_line_special_characters(self):
        """Test sanitize_log_line preserves legitimate special characters."""
        # File path characters
        assert sanitize_log_line("/home/user/file.txt") == "/home/user/file.txt"
        assert sanitize_log_line("C:\\Users\\file.exe") == "C:\\Users\\file.exe"

        # Common punctuation
        assert sanitize_log_line("File (copy).txt") == "File (copy).txt"
        assert sanitize_log_line("project-v2.1_final!.zip") == "project-v2.1_final!.zip"

    def test_sanitize_log_line_mixed_safe_and_unsafe(self):
        """Test sanitize_log_line with mix of safe and unsafe characters."""
        # Legitimate path with injected control characters
        mixed = "/home/user\x00/Documents\nmalicious\x1b[31m/file.txt"
        assert sanitize_log_line(mixed) == "/home/user/Documents malicious/file.txt"

    def test_sanitize_log_line_multiple_spaces_preserved(self):
        """Test sanitize_log_line preserves multiple consecutive spaces."""
        assert sanitize_log_line("Text    with    spaces") == "Text    with    spaces"

    def test_sanitize_log_line_only_control_characters(self):
        """Test sanitize_log_line with only control characters."""
        # Should return mostly empty or spaces
        assert sanitize_log_line("\x00\x01\x02") == ""
        assert sanitize_log_line("\n\r\n") == "   "  # Newlines become spaces

    def test_sanitize_log_line_starts_with_control_chars(self):
        """Test sanitize_log_line with control characters at start."""
        assert sanitize_log_line("\x00\x01Clean") == "Clean"
        assert sanitize_log_line("\nClean") == " Clean"

    def test_sanitize_log_line_ends_with_control_chars(self):
        """Test sanitize_log_line with control characters at end."""
        assert sanitize_log_line("Clean\x00\x01") == "Clean"
        assert sanitize_log_line("Clean\n") == "Clean "

    def test_sanitize_log_line_removes_unicode_line_separators(self):
        """Test sanitize_log_line maps Unicode line separators to spaces.

        U+0085 (NEL), U+2028 (LINE SEPARATOR), and U+2029 (PARAGRAPH
        SEPARATOR) are treated as line breaks by str.splitlines(), so they
        must not survive single-line sanitization (log injection bypass).
        """
        for separator in ("\u0085", "\u2028", "\u2029"):
            result = sanitize_log_line(f"real{separator}FORGED")
            assert len(result.splitlines()) == 1
            assert separator not in result
            assert result == "real FORGED"

    def test_sanitize_log_line_removes_c1_control_characters(self):
        """Test sanitize_log_line removes C1 control characters (0x80-0x9F)."""
        # 8-bit CSI (U+009B) and a neighboring C1 control (U+0090)
        assert sanitize_log_line("Text\u009bCSI") == "TextCSI"
        assert sanitize_log_line("Text\u0090DCS") == "TextDCS"
        assert "\u009b" not in sanitize_log_line("\u009b\u0080\u009f")

    def test_sanitize_log_line_removes_bidi_marks(self):
        """Test sanitize_log_line removes LRM/RLM/ALM bidi marks."""
        assert sanitize_log_line("file\u200ename.txt") == "filename.txt"
        assert sanitize_log_line("file\u200fname.txt") == "filename.txt"
        assert sanitize_log_line("file\u061cname.txt") == "filename.txt"


class TestSanitizeLogText:
    """Tests for the sanitize_log_text function (multi-line fields)."""

    def test_sanitize_log_text_clean_text(self):
        """Test sanitize_log_text with clean text - no changes."""
        assert (
            sanitize_log_text("Clean text without special characters")
            == "Clean text without special characters"
        )

    def test_sanitize_log_text_none_input(self):
        """Test sanitize_log_text with None input returns empty string."""
        assert sanitize_log_text(None) == ""

    def test_sanitize_log_text_empty_string(self):
        """Test sanitize_log_text with empty string returns empty string."""
        assert sanitize_log_text("") == ""

    def test_sanitize_log_text_preserves_newlines(self):
        """Test sanitize_log_text preserves newline characters (LF)."""
        assert sanitize_log_text("Line 1\nLine 2") == "Line 1\nLine 2"
        assert sanitize_log_text("Line 1\n\nLine 2") == "Line 1\n\nLine 2"
        assert sanitize_log_text("Line 1\nLine 2\nLine 3") == "Line 1\nLine 2\nLine 3"

    def test_sanitize_log_text_preserves_carriage_returns(self):
        """Test sanitize_log_text preserves carriage return characters (CR)."""
        assert sanitize_log_text("Line 1\rLine 2") == "Line 1\rLine 2"
        assert sanitize_log_text("Line 1\r\nLine 2") == "Line 1\r\nLine 2"

    def test_sanitize_log_text_preserves_tabs(self):
        """Test sanitize_log_text preserves tab characters."""
        assert sanitize_log_text("Column1\tColumn2\tColumn3") == "Column1\tColumn2\tColumn3"

    def test_sanitize_log_text_preserves_spaces(self):
        """Test sanitize_log_text preserves space characters."""
        assert sanitize_log_text("Word1 Word2  Word3   Word4") == "Word1 Word2  Word3   Word4"

    def test_sanitize_log_text_removes_null_bytes(self):
        """Test sanitize_log_text removes null bytes."""
        assert sanitize_log_text("Text\x00with\x00nulls") == "Textwithnulls"
        assert sanitize_log_text("\x00Start") == "Start"
        assert sanitize_log_text("End\x00") == "End"

    def test_sanitize_log_text_removes_ansi_escape_sequences(self):
        """Test sanitize_log_text removes ANSI escape sequences."""
        # Basic color codes
        assert sanitize_log_text("Normal\x1b[31mRED\x1b[0m") == "NormalRED"
        assert sanitize_log_text("\x1b[32mGREEN\x1b[0m") == "GREEN"
        assert sanitize_log_text("\x1b[1;33mYELLOW BOLD\x1b[0m") == "YELLOW BOLD"

        # With newlines preserved
        assert sanitize_log_text("Line1\x1b[31m\nLine2\x1b[0m") == "Line1\nLine2"

    def test_sanitize_log_text_removes_unicode_bidi_overrides(self):
        """Test sanitize_log_text removes Unicode bidirectional override characters."""
        # U+202A - U+202E
        assert sanitize_log_text("Text\u202aOverride\u202c") == "TextOverride"
        assert sanitize_log_text("\u202bLRE\u202c") == "LRE"

        # U+2066 - U+2069
        assert sanitize_log_text("Text\u2066Override\u2069") == "TextOverride"
        assert sanitize_log_text("\u2067RLI\u2069") == "RLI"

        # With newlines preserved
        assert sanitize_log_text("Line1\u202a\nLine2\u202c") == "Line1\nLine2"

    def test_sanitize_log_text_removes_control_characters(self):
        """Test sanitize_log_text removes control characters except safe whitespace."""
        # Bell, backspace, form feed should be removed
        assert sanitize_log_text("Text\x07Bell") == "TextBell"
        assert sanitize_log_text("Text\x08Backspace") == "TextBackspace"
        assert sanitize_log_text("Text\x0cFormFeed") == "TextFormFeed"

        # DEL character (0x7F)
        assert sanitize_log_text("Text\x7fDEL") == "TextDEL"

        # But newlines, CR, tabs should be preserved
        assert sanitize_log_text("Text\nNew\rLine\tTab") == "Text\nNew\rLine\tTab"

    def test_sanitize_log_text_multiline_output(self):
        """Test sanitize_log_text with typical multi-line ClamAV output."""
        clamav_output = """----------- SCAN SUMMARY -----------
Known viruses: 8647632
Engine version: 1.0.0
Scanned directories: 1
Scanned files: 2
Infected files: 1
Data scanned: 0.00 MB
Time: 10.123 sec (0 m 10 s)"""

        result = sanitize_log_text(clamav_output)
        # Should preserve all newlines
        assert result == clamav_output
        assert result.count("\n") == 7

    def test_sanitize_log_text_multiline_with_malicious_content(self):
        """Test sanitize_log_text removes malicious content but preserves structure."""
        malicious = "Line 1\x00\nLine 2\x1b[31mRED\x1b[0m\nLine 3\u202aOverride"
        expected = "Line 1\nLine 2RED\nLine 3Override"
        assert sanitize_log_text(malicious) == expected

    def test_sanitize_log_text_combined_malicious_input(self):
        """Test sanitize_log_text with combined malicious characters."""
        # Combining null bytes, ANSI, bidi overrides (but preserving newlines)
        malicious = "Path\x00\nFile\x1b[31m\u202aEvil\u202c\x1b[0m\nEnd"
        # Should remove: \x00, ANSI codes, bidi overrides; keep: \n
        assert sanitize_log_text(malicious) == "Path\nFileEvil\nEnd"

    def test_sanitize_log_text_very_long_string(self):
        """Test sanitize_log_text handles very long multi-line strings."""
        # 1000 lines of text
        long_text = "\n".join([f"Line {i}" for i in range(1000)])
        result = sanitize_log_text(long_text)
        assert result.count("\n") == 999
        assert "Line 0" in result
        assert "Line 999" in result

        # Long string with malicious content
        long_malicious = ("Clean\x00Text\n") * 1000
        result = sanitize_log_text(long_malicious)
        assert result.count("\n") == 1000
        assert "\x00" not in result

    def test_sanitize_log_text_preserves_unicode_text(self):
        """Test sanitize_log_text preserves legitimate Unicode characters."""
        # Multi-line with Unicode
        unicode_text = "文档\nテスト\nrésumé"
        assert sanitize_log_text(unicode_text) == unicode_text

        # Emoji and symbols
        assert sanitize_log_text("🔒 Line 1\n🔑 Line 2") == "🔒 Line 1\n🔑 Line 2"

    def test_sanitize_log_text_windows_line_endings(self):
        """Test sanitize_log_text preserves Windows-style line endings."""
        windows_text = "Line 1\r\nLine 2\r\nLine 3"
        assert sanitize_log_text(windows_text) == windows_text

    def test_sanitize_log_text_mixed_line_endings(self):
        """Test sanitize_log_text preserves mixed line endings."""
        mixed = "Line 1\nLine 2\r\nLine 3\rLine 4"
        assert sanitize_log_text(mixed) == mixed

    def test_sanitize_log_text_only_whitespace(self):
        """Test sanitize_log_text with only whitespace characters."""
        assert sanitize_log_text("   \n\t\r\n   ") == "   \n\t\r\n   "

    def test_sanitize_log_text_only_control_characters(self):
        """Test sanitize_log_text with only non-whitespace control characters."""
        # Should remove all except newlines/CR/tabs
        assert sanitize_log_text("\x00\x01\x02") == ""
        assert sanitize_log_text("\x00\n\x01") == "\n"

    def test_sanitize_log_text_empty_lines(self):
        """Test sanitize_log_text preserves empty lines."""
        text = "Line 1\n\nLine 3\n\n\nLine 6"
        assert sanitize_log_text(text) == text

    def test_sanitize_log_text_indented_content(self):
        """Test sanitize_log_text preserves indentation."""
        indented = "Main\n\tIndent 1\n\t\tIndent 2\n\tIndent 1"
        assert sanitize_log_text(indented) == indented

    def test_sanitize_log_text_clamav_error_output(self):
        """Test sanitize_log_text with typical error messages."""
        error = "ERROR: Can't access file /path/to/file\nERROR: Permission denied"
        assert sanitize_log_text(error) == error

    def test_sanitize_log_text_starts_with_control_chars(self):
        """Test sanitize_log_text with control characters at start."""
        assert sanitize_log_text("\x00\x01Clean") == "Clean"
        # Newline at start should be preserved
        assert sanitize_log_text("\nClean") == "\nClean"

    def test_sanitize_log_text_ends_with_control_chars(self):
        """Test sanitize_log_text with control characters at end."""
        assert sanitize_log_text("Clean\x00\x01") == "Clean"
        # Newline at end should be preserved
        assert sanitize_log_text("Clean\n") == "Clean\n"

    def test_sanitize_log_text_real_world_scan_output(self):
        """Test sanitize_log_text with realistic ClamAV scan output."""
        scan_output = """/home/user/Downloads/file1.txt: OK
/home/user/Downloads/malware.exe: Win.Trojan.Agent FOUND
/home/user/Downloads/file2.doc: OK

----------- SCAN SUMMARY -----------
Infected files: 1
Time: 5.234 sec"""

        # Should preserve all structure
        result = sanitize_log_text(scan_output)
        assert result == scan_output
        assert "Win.Trojan.Agent FOUND" in result
        assert result.count("\n") == 6

    def test_sanitize_log_text_removes_unicode_line_separators(self):
        """Test sanitize_log_text maps Unicode line separators to spaces.

        U+0085 (NEL), U+2028 (LINE SEPARATOR), and U+2029 (PARAGRAPH
        SEPARATOR) are not legitimate line breaks here (only LF/CR are), so
        they must not survive as breaks that str.splitlines() would split on.
        """
        for separator in ("\u0085", "\u2028", "\u2029"):
            result = sanitize_log_text(f"real{separator}FORGED")
            assert len(result.splitlines()) == 1
            assert separator not in result
            assert result == "real FORGED"

    def test_sanitize_log_text_removes_c1_control_characters(self):
        """Test sanitize_log_text removes C1 control characters (0x80-0x9F)."""
        # 8-bit CSI (U+009B) and a neighboring C1 control (U+0090)
        assert sanitize_log_text("Text\u009bCSI") == "TextCSI"
        assert sanitize_log_text("Text\u0090DCS") == "TextDCS"
        assert "\u009b" not in sanitize_log_text("\u009b\u0080\u009f")

    def test_sanitize_log_text_preserves_char_after_lone_esc(self):
        """A stray ESC must not swallow the following newline or printable.

        Regression: the ANSI pattern's non-CSI branch matched ESC + ANY char, so a
        lone ESC before a newline merged two lines (breaking the multi-line
        contract) and ESC before a letter ate the letter. The branch now only
        consumes a valid Fe final byte (0x40-0x5F); a lone ESC is left for the
        control-char pass to strip, preserving the following character.
        """
        # ESC immediately before a newline: the newline must survive.
        assert sanitize_log_text("line1\x1b\nline2") == "line1\nline2"
        # ESC before a lowercase letter (not a valid Fe escape): letter preserved.
        assert sanitize_log_text("\x1bhello") == "hello"
        # Real CSI sequences are still fully stripped (no regression).
        assert sanitize_log_text("a\x1b[31mb\x1b[0m") == "ab"
        # No ESC survives either way (injection-safe).
        assert "\x1b" not in sanitize_log_text("x\x1b\ny")


class TestSanitizationEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_sanitize_functions_idempotent(self):
        """Test that sanitizing twice produces the same result (idempotent)."""
        malicious = "Path\x00\nFile\x1b[31m\u202aEvil\u202c"

        # sanitize_log_line
        result1 = sanitize_log_line(malicious)
        result2 = sanitize_log_line(result1)
        assert result1 == result2

        # sanitize_log_text
        result3 = sanitize_log_text(malicious)
        result4 = sanitize_log_text(result3)
        assert result3 == result4

    def test_sanitize_functions_with_only_malicious_chars(self):
        """Test sanitization when input is only malicious characters."""
        only_malicious = "\x00\x01\x1b[31m\u202a\u202c"

        assert sanitize_log_line(only_malicious) == ""
        assert sanitize_log_text(only_malicious) == ""

    def test_sanitize_functions_performance_with_large_input(self):
        """Test sanitization performance doesn't degrade with large input."""
        # 100KB of text
        large_text = "Clean text. " * 8000  # ~96KB

        result_line = sanitize_log_line(large_text)
        assert len(result_line) > 0

        result_text = sanitize_log_text(large_text)
        assert len(result_text) > 0

    def test_sanitize_log_line_vs_log_text_difference(self):
        """Test the key difference between sanitize_log_line and sanitize_log_text."""
        text_with_newlines = "Line 1\nLine 2\nLine 3"

        # sanitize_log_line should replace newlines with spaces
        line_result = sanitize_log_line(text_with_newlines)
        assert line_result == "Line 1 Line 2 Line 3"
        assert "\n" not in line_result

        # sanitize_log_text should preserve newlines
        text_result = sanitize_log_text(text_with_newlines)
        assert text_result == "Line 1\nLine 2\nLine 3"
        assert "\n" in text_result

    def test_all_unicode_bidi_characters_removed(self):
        """Test that all Unicode bidirectional override characters are removed."""
        # U+202A through U+202E
        bidi_old = "\u202a\u202b\u202c\u202d\u202e"
        assert sanitize_log_line("Text" + bidi_old + "End") == "TextEnd"
        assert sanitize_log_text("Text" + bidi_old + "End") == "TextEnd"

        # U+2066 through U+2069
        bidi_new = "\u2066\u2067\u2068\u2069"
        assert sanitize_log_line("Text" + bidi_new + "End") == "TextEnd"
        assert sanitize_log_text("Text" + bidi_new + "End") == "TextEnd"

    def test_ansi_escape_patterns(self):
        """Test various ANSI escape sequence patterns are removed."""
        # CSI sequences with different parameters
        patterns = [
            "\x1b[0m",  # Reset
            "\x1b[31m",  # Red foreground
            "\x1b[1;31m",  # Bold red
            "\x1b[1;31;40m",  # Bold red on black background
            "\x1b[2J",  # Clear screen
            "\x1b[H",  # Move cursor to home
            "\x1b[10;20H",  # Move cursor to row 10, col 20
            "\x1b[?25h",  # Show cursor
        ]

        for pattern in patterns:
            result = sanitize_log_line(f"Before{pattern}After")
            assert result == "BeforeAfter", f"Failed to remove pattern: {pattern!r}"

    def test_boundary_ascii_values(self):
        """Test handling of boundary ASCII values."""
        # 0x00 - null (should be removed)
        assert sanitize_log_line("\x00") == ""

        # 0x09 - tab (should be preserved)
        assert sanitize_log_line("\x09") == "\x09"

        # 0x0A - newline (should become space in log_line, preserved in log_text)
        assert sanitize_log_line("\x0a") == " "
        assert sanitize_log_text("\x0a") == "\x0a"

        # 0x0D - carriage return (should become space in log_line, preserved in log_text)
        assert sanitize_log_line("\x0d") == " "
        assert sanitize_log_text("\x0d") == "\x0d"

        # 0x1F - last control character (should be removed)
        assert sanitize_log_line("\x1f") == ""

        # 0x20 - space (should be preserved)
        assert sanitize_log_line("\x20") == "\x20"

        # 0x7E - tilde (should be preserved)
        assert sanitize_log_line("\x7e") == "\x7e"

        # 0x7F - DEL (should be removed)
        assert sanitize_log_line("\x7f") == ""

    def test_real_world_malicious_filename(self):
        """Test with realistic malicious filename examples."""
        # Filename that tries to hide .exe extension
        filename1 = "document.pdf\u202e\u202dexe.evil"
        assert "document.pdfexe.evil" in sanitize_log_line(filename1)

        # Filename with ANSI codes to hide part of it
        filename2 = "safe.txt\x1b[8mmalware.exe\x1b[0m"
        assert "safe.txtmalware.exe" in sanitize_log_line(filename2)

        # Filename with newline injection
        filename3 = "file.txt\nFake log entry: CLEAN"
        assert "\n" not in sanitize_log_line(filename3)


class TestSanitizePathForLogging:
    """Tests for path redaction in persisted and debug logs."""

    def test_redacts_unix_path_with_spaces_without_swallowing_prose(self):
        """Test Unix paths with spaces are redacted without eating trailing words."""
        text = "Processing /home/user/My Documents/file.txt now"
        assert sanitize_path_for_logging(text) == f"Processing {REDACTED_PATH} now"

    def test_redacts_file_uri_without_swallowing_punctuation(self):
        """Test file URIs are redacted and punctuation around them is preserved."""
        text = "Open file:///home/user/file.txt, then continue"
        assert sanitize_path_for_logging(text) == f"Open {REDACTED_PATH}, then continue"

    def test_redacts_windows_path(self):
        """Test Windows-style absolute paths are redacted."""
        text = "Path C:/Users/test/file.exe should be hidden"
        assert sanitize_path_for_logging(text) == f"Path {REDACTED_PATH} should be hidden"

    def test_redacts_virustotal_report_urls(self):
        """Test VirusTotal report URLs are replaced with the URL placeholder."""
        text = (
            "See https://www.virustotal.com/gui/file/"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        assert sanitize_path_for_logging(text) == f"See {REDACTED_URL}"

    def test_preserves_text_without_sensitive_markers(self):
        """Test unrelated text is returned unchanged."""
        text = "Logging configured successfully"
        assert sanitize_path_for_logging(text) == text


class TestIsWindowsPathStart:
    """Tests for _is_windows_path_start helper."""

    def test_valid_windows_path_with_backslash(self):
        """Test recognises C:\\ as a Windows path start."""
        assert _is_windows_path_start("C:\\Users\\test", 0) is True

    def test_valid_windows_path_with_forward_slash(self):
        """Test recognises D:/ as a Windows path start."""
        assert _is_windows_path_start("D:/Users/test", 0) is True

    def test_various_drive_letters(self):
        """Test multiple valid drive letters are accepted."""
        for letter in ("A", "Z", "a", "z", "E"):
            assert _is_windows_path_start(f"{letter}:\\dir", 0) is True

    def test_offset_index(self):
        """Test detection works when path starts at a non-zero index."""
        text = "Open C:\\file.txt"
        assert _is_windows_path_start(text, 5) is True

    def test_string_too_short(self):
        """Test returns False when text is too short for a Windows path start."""
        assert _is_windows_path_start("C:", 0) is False
        assert _is_windows_path_start("C", 0) is False
        assert _is_windows_path_start("", 0) is False

    def test_no_colon_after_letter(self):
        """Test returns False when second character is not a colon."""
        assert _is_windows_path_start("CC\\dir", 0) is False

    def test_no_separator_after_colon(self):
        """Test returns False when third character is not / or \\."""
        assert _is_windows_path_start("C:x", 0) is False

    def test_digit_before_colon(self):
        """Test returns False when first character is a digit, not a letter."""
        assert _is_windows_path_start("1:\\dir", 0) is False

    def test_special_char_before_colon(self):
        """Test returns False when first character is not alphabetic."""
        assert _is_windows_path_start("@:\\dir", 0) is False


class TestHasPathBoundary:
    """Tests for _has_path_boundary helper."""

    def test_start_of_string(self):
        """Test index 0 is always a valid boundary."""
        assert _has_path_boundary("/home/user", 0) is True

    def test_after_space(self):
        """Test boundary after a space character."""
        assert _has_path_boundary("text /path", 5) is True

    def test_after_tab(self):
        """Test boundary after a tab character."""
        assert _has_path_boundary("text\t/path", 5) is True

    def test_after_single_quote(self):
        """Test boundary after a single quote."""
        assert _has_path_boundary("open '/path'", 6) is True

    def test_after_double_quote(self):
        """Test boundary after a double quote."""
        assert _has_path_boundary('open "/path"', 6) is True

    def test_after_open_paren(self):
        """Test boundary after an opening parenthesis."""
        assert _has_path_boundary("see (/path)", 5) is True

    def test_after_open_bracket(self):
        """Test boundary after an opening square bracket."""
        assert _has_path_boundary("[/path]", 1) is True

    def test_after_equals(self):
        """Test boundary after an equals sign."""
        assert _has_path_boundary("key=/path", 4) is True

    def test_after_comma(self):
        """Test boundary after a comma."""
        assert _has_path_boundary("a,/path", 2) is True

    def test_after_colon(self):
        """Test boundary after a colon."""
        assert _has_path_boundary("prefix:/path", 7) is True

    def test_mid_word_not_boundary(self):
        """Test that a position mid-word is not a boundary."""
        assert _has_path_boundary("notapath", 3) is False

    def test_after_letter(self):
        """Test that a position after a letter is not a boundary."""
        assert _has_path_boundary("x/foo", 1) is False

    def test_after_digit(self):
        """Test that a position after a digit is not a boundary."""
        assert _has_path_boundary("3/foo", 1) is False


class TestLooksLikePathContinuation:
    """Tests for _looks_like_path_continuation helper."""

    def test_space_then_path_with_slash(self):
        """Test space followed by segment with slash looks like continuation."""
        text = "Documents/file.txt"
        assert _looks_like_path_continuation(text, 0) is True

    def test_space_then_dotfile(self):
        """Test space followed by dot-prefixed token looks like continuation."""
        text = ".bashrc"
        assert _looks_like_path_continuation(text, 0) is True

    def test_space_then_filename_with_extension(self):
        """Test space followed by filename with extension looks like continuation."""
        text = "file.txt"
        assert _looks_like_path_continuation(text, 0) is True

    def test_space_then_plain_word(self):
        """Test space followed by plain word does not look like continuation."""
        text = "now"
        assert _looks_like_path_continuation(text, 0) is False

    def test_space_then_prose_word(self):
        """Test space followed by common prose word is not continuation."""
        text = "should"
        assert _looks_like_path_continuation(text, 0) is False

    def test_multiple_leading_spaces(self):
        """Test leading spaces are skipped before analysing the token."""
        text = "  file.txt"
        assert _looks_like_path_continuation(text, 0) is True

    def test_at_end_of_string(self):
        """Test returns False when starting at or past end of string."""
        assert _looks_like_path_continuation("", 0) is False
        assert _looks_like_path_continuation("abc", 5) is False

    def test_only_spaces_remain(self):
        """Test returns False when only trailing spaces remain."""
        assert _looks_like_path_continuation("   ", 0) is False

    def test_tilde_prefix(self):
        """Test tilde-prefixed token looks like continuation."""
        text = "~/Documents"
        assert _looks_like_path_continuation(text, 0) is True

    def test_word_with_no_dot_or_slash(self):
        """Test word without dots or slashes is not a path continuation."""
        text = "continue"
        assert _looks_like_path_continuation(text, 0) is False

    def test_stop_char_breaks_token(self):
        """Test stop characters (quotes, angle brackets) end the token scan."""
        text = 'file"rest'
        # token is "file" (no dot, no slash) -> not continuation
        assert _looks_like_path_continuation(text, 0) is False


class TestConsumePath:
    """Tests for _consume_path helper."""

    def test_simple_unix_path(self):
        """Test consuming a simple Unix path like /foo/bar."""
        text = "/foo/bar"
        end = _consume_path(text, 0)
        assert text[0:end] == "/foo/bar"

    def test_path_with_extension(self):
        """Test consuming a path ending in a file extension."""
        text = "/home/user/file.txt"
        end = _consume_path(text, 0)
        assert text[0:end] == "/home/user/file.txt"

    def test_path_stops_at_space_without_continuation(self):
        """Test path consumption stops at a space followed by prose."""
        text = "/home/user/file.txt now"
        end = _consume_path(text, 0)
        assert text[0:end] == "/home/user/file.txt"

    def test_path_with_spaces_in_filename(self):
        """Test path consumption continues through spaces in path-like context."""
        text = "/home/user/My Documents/file.txt rest"
        end = _consume_path(text, 0)
        consumed = text[0:end]
        assert "My Documents" in consumed
        assert "file.txt" in consumed

    def test_file_uri(self):
        """Test consuming a file:// URI."""
        text = "file:///tmp/test.txt"
        end = _consume_path(text, 0)
        assert text[0:end] == "file:///tmp/test.txt"

    def test_home_tilde_path(self):
        """Test consuming a tilde-prefixed path."""
        text = "~/Documents/secret.txt"
        end = _consume_path(text, 0)
        assert text[0:end] == "~/Documents/secret.txt"

    def test_windows_path_backslash(self):
        """Test consuming a Windows path with backslashes."""
        text = "C:\\Users\\test\\file.exe"
        end = _consume_path(text, 0)
        assert text[0:end] == "C:\\Users\\test\\file.exe"

    def test_windows_path_forward_slash(self):
        """Test consuming a Windows path with forward slashes."""
        text = "C:/Users/test/file.exe"
        end = _consume_path(text, 0)
        assert text[0:end] == "C:/Users/test/file.exe"

    def test_path_stops_at_delimiter(self):
        """Test path stops at delimiter characters like quotes."""
        text = '/home/user/file.txt"rest'
        end = _consume_path(text, 0)
        assert text[0:end] == "/home/user/file.txt"

    def test_trailing_comma_stripped(self):
        """Test trailing comma is stripped from consumed path."""
        text = "/home/user/file.txt, more text"
        end = _consume_path(text, 0)
        assert text[0:end] == "/home/user/file.txt"

    def test_trailing_semicolon_stripped(self):
        """Test trailing semicolon is stripped from consumed path."""
        text = "/home/user/file.txt; next"
        end = _consume_path(text, 0)
        assert text[0:end] == "/home/user/file.txt"

    def test_trailing_close_paren_stripped(self):
        """Test trailing close paren is stripped from consumed path."""
        text = "/home/user/file.txt) rest"
        end = _consume_path(text, 0)
        assert text[0:end] == "/home/user/file.txt"

    def test_trailing_close_bracket_stripped(self):
        """Test trailing close bracket is stripped from consumed path."""
        text = "/home/user/file.txt] rest"
        end = _consume_path(text, 0)
        assert text[0:end] == "/home/user/file.txt"

    def test_trailing_close_brace_stripped(self):
        """Test trailing close brace is stripped from consumed path."""
        text = "/home/user/file.txt} rest"
        end = _consume_path(text, 0)
        assert text[0:end] == "/home/user/file.txt"

    def test_path_at_nonzero_offset(self):
        """Test consuming a path starting at a non-zero offset."""
        text = "open /etc/config.conf please"
        end = _consume_path(text, 5)
        assert text[5:end] == "/etc/config.conf"

    def test_root_path(self):
        """Test consuming the root path /."""
        text = "/ rest"
        end = _consume_path(text, 0)
        # Just "/" with no continuation, should consume at least the "/"
        assert end >= 1

    def test_path_stops_at_angle_bracket(self):
        """Test path stops at < character."""
        text = "/path/to/file<tag>"
        end = _consume_path(text, 0)
        assert text[0:end] == "/path/to/file"

    def test_path_stops_at_pipe(self):
        """Test path stops at | character."""
        text = "/path/to/file|other"
        end = _consume_path(text, 0)
        assert text[0:end] == "/path/to/file"


class TestRedactSensitiveLogData:
    """Tests for the main redact_sensitive_log_data function."""

    # -- None and empty input --

    def test_none_input_returns_empty(self):
        """Test None input returns an empty string."""
        assert redact_sensitive_log_data(None) == ""

    def test_empty_string_returns_empty(self):
        """Test empty string input returns an empty string."""
        assert redact_sensitive_log_data("") == ""

    # -- Text with no sensitive data --

    def test_plain_text_unchanged(self):
        """Test plain text without paths or hashes is returned unchanged."""
        text = "Scan completed successfully with 0 threats"
        assert redact_sensitive_log_data(text) == text

    def test_text_with_numbers_not_hash_length(self):
        """Test short hex-like strings below 32 chars are not redacted."""
        text = "Error code: 0x1f3a status 42"
        assert redact_sensitive_log_data(text) == text

    # -- Unix paths --

    def test_simple_unix_path(self):
        """Test redaction of a simple Unix absolute path."""
        text = "Scanning /home/user/file.txt"
        result = redact_sensitive_log_data(text)
        assert REDACTED_PATH in result
        assert "/home/user/file.txt" not in result

    def test_unix_path_with_deep_nesting(self):
        """Test redaction of a deeply nested Unix path."""
        text = "Found /var/lib/clamav/daily.cld"
        result = redact_sensitive_log_data(text)
        assert result == f"Found {REDACTED_PATH}"

    def test_unix_path_at_start_of_string(self):
        """Test redaction of a path at the very start of the string."""
        text = "/etc/clamav/clamd.conf loaded"
        result = redact_sensitive_log_data(text)
        assert result == f"{REDACTED_PATH} loaded"

    def test_unix_path_at_end_of_string(self):
        """Test redaction of a path at the end of the string."""
        text = "Reading /etc/clamav/freshclam.conf"
        result = redact_sensitive_log_data(text)
        assert result == f"Reading {REDACTED_PATH}"

    def test_unix_path_is_entire_string(self):
        """Test redaction when the entire string is a path."""
        text = "/home/user/Documents/file.txt"
        result = redact_sensitive_log_data(text)
        assert result == REDACTED_PATH

    # -- Windows paths --

    def test_windows_path_backslash(self):
        """Test redaction of a Windows path with backslashes."""
        text = "Scanning C:\\Users\\test\\file.exe"
        result = redact_sensitive_log_data(text)
        assert REDACTED_PATH in result
        assert "C:\\Users" not in result

    def test_windows_path_forward_slash(self):
        """Test redaction of a Windows path with forward slashes."""
        text = "Found D:/Projects/build/output.dll"
        result = redact_sensitive_log_data(text)
        assert REDACTED_PATH in result
        assert "D:/Projects" not in result

    # -- Home paths --

    def test_tilde_home_path(self):
        """Test redaction of a tilde-prefixed home path."""
        text = "Checking ~/Documents/secret.txt"
        result = redact_sensitive_log_data(text)
        assert result == f"Checking {REDACTED_PATH}"

    def test_tilde_path_at_start(self):
        """Test redaction of tilde path at start of string."""
        text = "~/Downloads/report.pdf was scanned"
        result = redact_sensitive_log_data(text)
        assert result == f"{REDACTED_PATH} was scanned"

    # -- File URIs --

    def test_file_uri_simple(self):
        """Test redaction of a file:// URI."""
        text = "Opening file:///tmp/test"
        result = redact_sensitive_log_data(text)
        assert result == f"Opening {REDACTED_PATH}"

    def test_file_uri_with_spaces_in_path(self):
        """Test redaction of a file:// URI with path components."""
        text = "Loaded file:///home/user/My Documents/file.txt done"
        result = redact_sensitive_log_data(text)
        assert REDACTED_PATH in result
        assert "file:///" not in result

    # -- Hash values --

    def test_sha256_hash_redacted(self):
        """Test SHA-256 hash (64 hex chars) is redacted."""
        sha256 = "a" * 64
        text = f"Hash: {sha256}"
        result = redact_sensitive_log_data(text)
        assert result == f"Hash: {REDACTED_HASH}"
        assert sha256 not in result

    def test_md5_hash_redacted(self):
        """Test MD5 hash (32 hex chars) is redacted."""
        md5 = "d41d8cd98f00b204e9800998ecf8427e"
        text = f"MD5: {md5}"
        result = redact_sensitive_log_data(text)
        assert result == f"MD5: {REDACTED_HASH}"
        assert md5 not in result

    def test_sha1_hash_redacted(self):
        """Test SHA-1 hash (40 hex chars) is redacted."""
        sha1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        text = f"SHA1: {sha1}"
        result = redact_sensitive_log_data(text)
        assert result == f"SHA1: {REDACTED_HASH}"

    def test_mixed_case_hex_hash(self):
        """Test hash with mixed case hex digits is redacted."""
        mixed_hash = "aAbBcCdDeEfF" * 4  # 48 hex chars
        text = f"Value: {mixed_hash}"
        result = redact_sensitive_log_data(text)
        assert REDACTED_HASH in result

    def test_short_hex_not_redacted(self):
        """Test that hex strings shorter than 32 chars are not treated as hashes."""
        short_hex = "abcdef1234567890"  # 16 chars
        text = f"Code: {short_hex}"
        result = redact_sensitive_log_data(text)
        assert short_hex in result
        assert REDACTED_HASH not in result

    # -- VirusTotal URLs --

    def test_virustotal_url_redacted(self):
        """Test VirusTotal URL with hash is redacted."""
        vt_hash = "a" * 64
        text = f"Report: https://www.virustotal.com/gui/file/{vt_hash}"
        result = redact_sensitive_log_data(text)
        assert result == f"Report: {REDACTED_URL}"
        assert vt_hash not in result

    def test_virustotal_url_http(self):
        """Test VirusTotal URL with http (not https) is redacted."""
        text = "See http://virustotal.com/gui/file/abc123"
        result = redact_sensitive_log_data(text)
        assert result == f"See {REDACTED_URL}"

    def test_virustotal_url_without_www(self):
        """Test VirusTotal URL without www prefix is redacted."""
        text = "Link https://virustotal.com/gui/file/abc123"
        result = redact_sensitive_log_data(text)
        assert result == f"Link {REDACTED_URL}"

    # -- Multiple sensitive values --

    def test_multiple_paths_in_one_string(self):
        """Test multiple paths in a single string are all redacted."""
        text = "Copied /home/user/a.txt to /tmp/b.txt"
        result = redact_sensitive_log_data(text)
        assert result.count(REDACTED_PATH) == 2
        assert "/home/user/a.txt" not in result
        assert "/tmp/b.txt" not in result

    def test_path_and_hash_in_same_string(self):
        """Test both a path and a hash are redacted in the same string."""
        sha256 = "b" * 64
        text = f"File /home/user/malware.exe hash {sha256}"
        result = redact_sensitive_log_data(text)
        assert REDACTED_PATH in result
        assert REDACTED_HASH in result
        assert "/home/user/malware.exe" not in result
        assert sha256 not in result

    def test_path_hash_and_url_together(self):
        """Test path, hash, and VT URL are all redacted in the same string."""
        sha256 = "c" * 64
        text = (
            f"Scanned /home/user/file.bin with hash {sha256} "
            f"see https://www.virustotal.com/gui/file/{sha256}"
        )
        result = redact_sensitive_log_data(text)
        assert REDACTED_PATH in result
        assert REDACTED_HASH in result or REDACTED_URL in result
        assert "/home/user/file.bin" not in result

    # -- Edge cases --

    def test_path_followed_by_comma(self):
        """Test path followed by comma: comma is not consumed as part of path."""
        text = "Found /tmp/a.txt, continuing"
        result = redact_sensitive_log_data(text)
        assert result == f"Found {REDACTED_PATH}, continuing"

    def test_path_followed_by_semicolon(self):
        """Test path followed by semicolon preserves the semicolon."""
        text = "Target /tmp/a.txt; scanning"
        result = redact_sensitive_log_data(text)
        assert result == f"Target {REDACTED_PATH}; scanning"

    def test_path_in_parentheses(self):
        """Test path within parentheses redacts correctly."""
        text = "error (see /var/log/syslog) for details"
        result = redact_sensitive_log_data(text)
        assert REDACTED_PATH in result
        assert "/var/log/syslog" not in result

    def test_path_in_quotes(self):
        """Test path within quotes redacts the path."""
        text = 'file "/home/user/test.txt" found'
        result = redact_sensitive_log_data(text)
        assert REDACTED_PATH in result
        assert "/home/user/test.txt" not in result

    def test_slash_in_prose_not_redacted(self):
        """Test that a standalone slash in mid-word is not redacted as a path."""
        # "and/or" has no boundary before the slash
        text = "true and/or false"
        result = redact_sensitive_log_data(text)
        assert "and" in result
        assert "false" in result

    def test_no_false_positive_on_plain_text(self):
        """Test plain text without slashes is not redacted."""
        text = "ClamAV engine version 1.0.0"
        assert redact_sensitive_log_data(text) == text

    def test_idempotent(self):
        """Test redacting twice gives the same result."""
        text = "Scan /home/user/file.txt hash " + "a" * 64
        result1 = redact_sensitive_log_data(text)
        result2 = redact_sensitive_log_data(result1)
        assert result1 == result2

    def test_path_with_special_chars_in_filename(self):
        """Test paths with dots, hyphens, underscores in filenames."""
        text = "Loading /etc/clamav/freshclam-custom_v2.conf"
        result = redact_sensitive_log_data(text)
        assert result == f"Loading {REDACTED_PATH}"

    def test_multiple_adjacent_paths(self):
        """Test two paths separated only by a space."""
        text = "/path/one /path/two"
        result = redact_sensitive_log_data(text)
        # Both should be redacted; we just need to verify no path text leaks
        assert "/path/one" not in result
        assert "/path/two" not in result

    def test_hash_at_word_boundary(self):
        """Test hash redaction respects word boundaries."""
        # 31 hex chars should NOT be redacted (below 32 threshold)
        text = "value " + "f" * 31 + " end"
        result = redact_sensitive_log_data(text)
        assert REDACTED_HASH not in result

    def test_128_char_hex_redacted(self):
        """Test very long hex string (128 chars) is still redacted as hash."""
        long_hash = "a" * 128
        text = f"Token: {long_hash}"
        result = redact_sensitive_log_data(text)
        assert result == f"Token: {REDACTED_HASH}"

    def test_hex_over_128_not_redacted(self):
        """Test hex string over 128 chars is not redacted (exceeds pattern)."""
        too_long = "a" * 129
        text = f"Data: {too_long}"
        result = redact_sensitive_log_data(text)
        # The 129-char string should not match the 32-128 char hash pattern
        assert REDACTED_HASH not in result
