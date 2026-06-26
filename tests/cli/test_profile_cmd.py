# ClamUI Profile Command Tests
"""
Tests for the profile CLI command's text output.

Focuses on the security-sensitive path where profile fields are printed to the
terminal. Profiles can be imported from arbitrary JSON (the import/export feature
is meant for sharing), so their name/description/targets/exclusions/options are
untrusted and must be sanitized to prevent ANSI/control-sequence injection.
"""

import argparse

import src.cli.profile_cmd as profile_cmd


class _FakeProfile:
    """Lightweight stand-in exposing the attributes the CLI reads."""

    def __init__(self, **kw):
        self.id = kw.get("id", "id-1")
        self.name = kw["name"]
        self.targets = kw.get("targets", [])
        self.exclusions = kw.get("exclusions", {})
        self.options = kw.get("options", {})
        self.description = kw.get("description", "")
        self.is_default = kw.get("is_default", False)
        self.created_at = kw.get("created_at", "2026-06-09T12:00:00")
        self.updated_at = kw.get("updated_at", "2026-06-09T12:00:00")


class _FakeManager:
    """Minimal ProfileManager stand-in returning fixed profiles."""

    def __init__(self, profiles):
        self._profiles = profiles

    def list_profiles(self):
        return self._profiles

    def get_profile_by_name(self, name):
        for profile in self._profiles:
            if profile.name == name:
                return profile
        return None


def _install(monkeypatch, profiles):
    monkeypatch.setattr(profile_cmd, "ProfileManager", lambda _config_dir: _FakeManager(profiles))
    monkeypatch.setattr(profile_cmd, "get_config_dir", lambda: "/tmp/clamui-test")


class TestProfileCommandSanitization:
    """profile list/show must strip terminal escape sequences from untrusted fields."""

    def test_show_sanitizes_untrusted_fields(self, capsys, monkeypatch):
        profile = _FakeProfile(
            name="Evil\x1b[31mProfile",
            description="desc\x1b[2J",
            targets=["/path\x1b[0m/one"],
            exclusions={"paths": ["/ex\x1b[5mclude"], "patterns": ["*.t\x1bmp"]},
            options={"ke\x1by": "va\x1blue"},
        )
        _install(monkeypatch, [profile])

        rc = profile_cmd.run_show(argparse.Namespace(name=profile.name, json_output=False))

        out = capsys.readouterr().out
        assert rc == 0
        assert "\x1b" not in out
        assert "EvilProfile" in out

    def test_list_sanitizes_untrusted_fields(self, capsys, monkeypatch):
        profile = _FakeProfile(name="Bad\x1b[31mName", targets=["/a\x1b[0m", "/b"])
        _install(monkeypatch, [profile])

        rc = profile_cmd.run_list(argparse.Namespace(json_output=False))

        out = capsys.readouterr().out
        assert rc == 0
        assert "\x1b" not in out
        assert "BadName" in out
