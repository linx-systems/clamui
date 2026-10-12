"""
Property-based tests for src/core/sanitize.py.

These exercise the sanitizer guarantees systematically across adversarial
input space: ANSI stripping, bidirectional-override removal, control-char
filtering, surrogate handling, idempotence, and path redaction.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.core.sanitize import (
    ANSI_ESCAPE_PATTERN,
    REDACTED_PATH,
    UNICODE_BIDI_PATTERN,
    redact_sensitive_log_data,
    sanitize_log_line,
    sanitize_log_text,
    sanitize_path_for_logging,
    sanitize_surrogate_path,
)
from tests.property.strategies import adversarial_text, surrogate_text

pytestmark = pytest.mark.property


@given(adversarial_text())
def test_sanitize_log_line_strips_all_ansi(text: str) -> None:
    result = sanitize_log_line(text)
    assert ANSI_ESCAPE_PATTERN.search(result) is None


@given(adversarial_text())
def test_sanitize_log_line_strips_bidi_overrides(text: str) -> None:
    result = sanitize_log_line(text)
    assert UNICODE_BIDI_PATTERN.search(result) is None


@given(adversarial_text())
def test_sanitize_log_line_has_no_forbidden_control_chars(text: str) -> None:
    """Output keeps only printable (>= 0x20) plus tab (0x09)."""
    result = sanitize_log_line(text)
    for ch in result:
        code = ord(ch)
        assert code >= 0x20 or code == 0x09, f"forbidden control char U+{code:04X}"
        assert code != 0x7F, "DEL must be stripped"


@given(adversarial_text())
def test_sanitize_log_line_has_no_newlines_or_nulls(text: str) -> None:
    """Single-line fields must not contain LF/CR/NUL in the output."""
    result = sanitize_log_line(text)
    assert "\n" not in result
    assert "\r" not in result
    assert "\x00" not in result


@given(adversarial_text())
def test_sanitize_log_line_is_idempotent(text: str) -> None:
    once = sanitize_log_line(text)
    assert sanitize_log_line(once) == once


@given(adversarial_text())
def test_sanitize_log_line_is_utf8_encodable(text: str) -> None:
    """Output must never raise when encoded to UTF-8 (surrogates stripped)."""
    result = sanitize_log_line(text)
    result.encode("utf-8")


@given(adversarial_text())
def test_sanitize_log_text_strips_ansi_and_bidi(text: str) -> None:
    result = sanitize_log_text(text)
    assert ANSI_ESCAPE_PATTERN.search(result) is None
    assert UNICODE_BIDI_PATTERN.search(result) is None


@given(adversarial_text())
def test_sanitize_log_text_preserves_newlines_tabs(text: str) -> None:
    """Multi-line variant keeps \\n, \\r, \\t and printable chars only."""
    result = sanitize_log_text(text)
    for ch in result:
        code = ord(ch)
        ok = code >= 0x20 or code in (0x09, 0x0A, 0x0D)
        assert ok, f"forbidden control char U+{code:04X}"
        assert code != 0x7F


@given(adversarial_text())
def test_sanitize_log_text_is_idempotent(text: str) -> None:
    once = sanitize_log_text(text)
    assert sanitize_log_text(once) == once


@given(adversarial_text())
def test_sanitize_log_text_has_no_nulls(text: str) -> None:
    result = sanitize_log_text(text)
    assert "\x00" not in result


@given(surrogate_text())
def test_sanitize_surrogate_path_is_utf8_encodable(text: str) -> None:
    sanitize_surrogate_path(text).encode("utf-8")


@given(st.text())
def test_sanitize_surrogate_path_keeps_utf8_text(text: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return
    assert sanitize_surrogate_path(text) == text


@given(st.one_of(st.none(), st.text()))
def test_sanitize_log_line_none_and_str_total(text: str | None) -> None:
    """Never raises for None or any string."""
    result = sanitize_log_line(text)
    assert isinstance(result, str)


@given(st.one_of(st.none(), st.text()))
def test_sanitize_log_text_none_and_str_total(text: str | None) -> None:
    result = sanitize_log_text(text)
    assert isinstance(result, str)


@given(
    st.lists(
        st.sampled_from(
            [
                "/home/user/file.txt",
                "~/Documents/report.pdf",
                "/etc/clamav/clamd.conf",
                "C:\\Users\\alice\\file.exe",
                "file:///tmp/x",
            ]
        ),
        min_size=1,
        max_size=4,
    ),
    st.text(alphabet="abcdefgh ", max_size=30),
)
def test_redact_sensitive_log_data_replaces_paths(paths: list[str], filler: str) -> None:
    """When any known path prefix appears, at least one REDACTED_PATH is emitted."""
    text = filler.join(paths) + filler
    result = redact_sensitive_log_data(text)
    assert REDACTED_PATH in result


@given(st.one_of(st.none(), st.text()))
def test_redact_sensitive_log_data_total(text: str | None) -> None:
    result = redact_sensitive_log_data(text)
    assert isinstance(result, str)


@given(st.one_of(st.none(), st.text()))
def test_sanitize_path_for_logging_total(text: str | None) -> None:
    result = sanitize_path_for_logging(text)
    assert isinstance(result, str)
