# ClamUI History Command Tests
"""
Tests for the history CLI command argument parsing.

Focuses on the --limit validation: non-positive values must be rejected
rather than silently producing a wrong slice.
"""

import argparse

import pytest

from src.cli.history_cmd import positive_int, register


def _build_parser() -> argparse.ArgumentParser:
    """Build a parser with only the history subcommand registered."""
    parser = argparse.ArgumentParser(prog="clamui")
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers)
    return parser


class TestPositiveInt:
    """Tests for the positive_int argparse type."""

    def test_accepts_positive(self):
        assert positive_int("5") == 5

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_rejects_non_positive(self, value):
        with pytest.raises(argparse.ArgumentTypeError):
            positive_int(value)

    def test_rejects_non_integer(self):
        with pytest.raises(argparse.ArgumentTypeError):
            positive_int("abc")


class TestHistoryLimitArgument:
    """Tests for --limit validation via the registered parser."""

    def test_valid_limit_is_accepted(self):
        parser = _build_parser()
        args = parser.parse_args(["history", "--limit", "5"])
        assert args.limit == 5

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_non_positive_limit_is_rejected(self, value):
        parser = _build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["history", "--limit", value])
        assert excinfo.value.code != 0
