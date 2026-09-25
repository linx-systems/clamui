"""
Property-based tests for src/core/threat_classifier.py.

Exercises the classification and categorization logic against adversarial
and realistic threat-name inputs. These are pure functions - no mocking
needed.
"""

from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.core.threat_classifier import (
    CRITICAL_PATTERNS,
    HIGH_PATTERNS,
    HIGH_PRIORITY_CATEGORY_PATTERNS,
    LOW_PATTERNS,
    LOW_PRIORITY_CATEGORY_PATTERNS,
    MEDIUM_PATTERNS,
    ThreatSeverity,
    categorize_threat,
    classify_threat_severity,
    classify_threat_severity_str,
)
from tests.property.strategies import threat_name, unknown_threat_name

pytestmark = pytest.mark.property


@given(st.one_of(st.none(), st.just("")))
def test_severity_empty_or_none_is_medium(text: str | None) -> None:
    assert classify_threat_severity(text or "") == ThreatSeverity.MEDIUM


@given(st.one_of(st.none(), st.just("")))
def test_category_empty_or_none_is_unknown(text: str | None) -> None:
    assert categorize_threat(text or "") == "Unknown"


@given(threat_name())
def test_severity_is_case_insensitive(name: str) -> None:
    assert classify_threat_severity(name.upper()) == classify_threat_severity(name)
    assert classify_threat_severity(name.lower()) == classify_threat_severity(name)


@given(threat_name())
def test_category_is_case_insensitive(name: str) -> None:
    assert categorize_threat(name.upper()) == categorize_threat(name)
    assert categorize_threat(name.lower()) == categorize_threat(name)


@given(threat_name())
def test_severity_str_matches_enum_value(name: str) -> None:
    """classify_threat_severity_str is a string projection of the enum."""
    assert classify_threat_severity_str(name) == classify_threat_severity(name).value


@given(threat_name())
def test_severity_is_valid_enum_member(name: str) -> None:
    assert classify_threat_severity(name) in set(ThreatSeverity)


@given(unknown_threat_name())
def test_unknown_name_defaults_to_medium(name: str) -> None:
    assert classify_threat_severity(name) == ThreatSeverity.MEDIUM


@given(unknown_threat_name())
def test_unknown_name_defaults_to_virus(name: str) -> None:
    assert categorize_threat(name) == "Virus"


@given(
    st.text(alphabet=string.ascii_letters + string.digits + ".-", max_size=10),
    st.text(alphabet=string.ascii_letters + string.digits + ".-", max_size=10),
    st.sampled_from(CRITICAL_PATTERNS),
)
def test_critical_pattern_dominates(prefix: str, suffix: str, pattern: str) -> None:
    """Any name containing a critical pattern classifies CRITICAL."""
    name = f"{prefix}{pattern}{suffix}"
    assert classify_threat_severity(name) == ThreatSeverity.CRITICAL


@given(
    st.text(alphabet=string.ascii_letters, max_size=10),
    st.text(alphabet=string.ascii_letters, max_size=10),
    st.sampled_from(HIGH_PATTERNS),
)
def test_high_pattern_yields_high_when_no_critical(prefix: str, suffix: str, pattern: str) -> None:
    """A high-severity pattern yields HIGH unless a critical pattern also appears."""
    name = f"{prefix}{pattern}{suffix}"
    lowered = name.lower()
    if any(c in lowered for c in CRITICAL_PATTERNS):
        return
    assert classify_threat_severity(name) == ThreatSeverity.HIGH


@given(
    st.text(alphabet=string.ascii_letters, max_size=10),
    st.text(alphabet=string.ascii_letters, max_size=10),
    st.sampled_from(LOW_PATTERNS),
)
def test_low_pattern_yields_low_when_no_higher(prefix: str, suffix: str, pattern: str) -> None:
    name = f"{prefix}{pattern}{suffix}"
    lowered = name.lower()
    if any(c in lowered for c in CRITICAL_PATTERNS + HIGH_PATTERNS + MEDIUM_PATTERNS):
        return
    assert classify_threat_severity(name) == ThreatSeverity.LOW


@given(st.text(alphabet=string.ascii_letters + ".-", min_size=1, max_size=20))
def test_category_is_nonempty_string(name_prefix: str) -> None:
    """categorize_threat always returns a non-empty string."""
    result = categorize_threat(name_prefix + "payload")
    assert isinstance(result, str)
    assert result != ""


@given(threat_name())
def test_severity_is_total(name: str) -> None:
    """classify_threat_severity never raises for any threat_name()-generated input."""
    assert classify_threat_severity(name) in set(ThreatSeverity)


@given(st.text(max_size=100))
def test_severity_is_total_any_text(name: str) -> None:
    """classify_threat_severity accepts any string without raising."""
    assert classify_threat_severity(name) in set(ThreatSeverity)


@given(st.text(max_size=100))
def test_categorize_is_total_any_text(name: str) -> None:
    """categorize_threat accepts any string without raising."""
    result = categorize_threat(name)
    valid_categories = {cat for _, cat in HIGH_PRIORITY_CATEGORY_PATTERNS}
    valid_categories |= {cat for _, cat in LOW_PRIORITY_CATEGORY_PATTERNS}
    valid_categories |= {"Virus", "Unknown"}
    assert result in valid_categories
