# ClamUI Quarantine Command Tests
"""
Tests for the quarantine CLI command's text output.

Focuses on the security-sensitive path where filesystem-derived strings
(original paths) and ClamAV-derived threat names are printed to the terminal
and must be sanitized to prevent ANSI/control-sequence injection.
"""

import argparse

import src.cli.quarantine_cmd as quarantine_cmd
from src.core.quarantine.database import QuarantineEntry


class _FakeManager:
    """Minimal QuarantineManager stand-in returning fixed entries."""

    def __init__(self, entries):
        self._entries = entries

    def get_all_entries(self):
        return self._entries

    def get_total_size(self):
        return sum(e.file_size for e in self._entries)


class TestQuarantineListSanitization:
    """The list table must strip terminal escape sequences from untrusted fields."""

    def test_threat_name_and_path_are_sanitized(self, capsys, monkeypatch):
        entry = QuarantineEntry(
            id=1,
            original_path="\x1b[31m/evil/path",
            quarantine_path="/q/abc",
            threat_name="Evil\x1b[2Jname",
            detection_date="2026-06-09T12:00:00",
            file_size=10,
            file_hash="deadbeef",
            original_permissions=0o644,
        )
        monkeypatch.setattr(quarantine_cmd, "QuarantineManager", lambda: _FakeManager([entry]))

        rc = quarantine_cmd.run_list(argparse.Namespace(json_output=False))

        captured = capsys.readouterr()
        assert rc == 0
        assert "\x1b" not in captured.out
        assert "Evilname" in captured.out
        assert "/evil/path" in captured.out
