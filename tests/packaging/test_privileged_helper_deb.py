# ClamUI Privileged Helper Debian Artifact Tests
"""
Behavioral test for the standalone privileged-helper Debian artifact.

``debian/build-privileged-helper-deb.sh`` produces a
``clamui-privileged-helper_<version>_all.deb`` whose payload is the pkexec
wrapper, the two apply-preferences Python library modules, and the polkit
policy file. The released ``clamui`` 0.3.0 package already owns those paths,
so the helper package declares ``Replaces: clamui (<= VERSION)`` -- letting
dpkg transfer file ownership during upgrade -- while declaring no
Conflicts/Breaks, so it remains co-installable with the full clamui package.

This test drives the builder end-to-end (no source-text inspection) and asserts:
- exactly one correctly named .deb is emitted in the given output directory;
- dpkg-deb metadata exposes resolved Package/Architecture/Version matching the
  project version, Depends, and the upgrade-transition Replaces;
- no Conflicts or Breaks are declared;
- the regular-file payload is exactly the four canonical files (via tar
  metadata, excluding directory and package-metadata entries);
- every filesystem tar entry is uid/gid root (root-owned security model);
- the wrapper is executable by its owner;
- the installed library and policy files are not group- or world-writable.

A dpkg unpack regression that would exercise the Replaces-driven path transfer
against a synthetic older clamui is intentionally omitted: plain rootless
``dpkg --unpack --root`` hard-fails requiring superuser, and ``fakeroot`` is an
extra, non-guaranteed dependency across supported pytest environments, so such
a test would skip (rather than run) where it is most needed. The exact
``Replaces == clamui (<= <project version>)`` field assertion above is the
deterministic coverage that catches a missing or wrong transition line.
"""

import io
import shutil
import stat
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
BUILDER = PROJECT_ROOT / "debian" / "build-privileged-helper-deb.sh"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

# Canonical payload of the privileged-helper package, relative to the .deb root.
WRAPPER = "usr/bin/clamui-apply-preferences"
LIBRARY_FILES = (
    "usr/lib/clamui/clamui_apply_preferences.py",
    "usr/lib/clamui/clamui_privileged_paths.py",
)
POLICY_FILE = "usr/share/polkit-1/actions/io.github.linx_systems.ClamUI.policy"
ALL_FILES = (WRAPPER, *LIBRARY_FILES, POLICY_FILE)


def _project_version() -> str:
    """Read the declared version straight from pyproject.toml metadata."""
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


class TestPrivilegedHelperDeb:
    """End-to-end behavioral test for the privileged-helper .deb builder."""

    def test_builds_a_valid_privileged_helper_deb(self, tmp_path: Path) -> None:
        if shutil.which("dpkg-deb") is None:
            pytest.skip("dpkg-deb is required to inspect and extract the .deb artifact")

        version = _project_version()
        expected_deb_name = f"clamui-privileged-helper_{version}_all.deb"

        # Drive the builder directly (shell disabled) so a missing or
        # non-executable builder fails loudly instead of slipping through bash.
        subprocess.run(
            [str(BUILDER), str(tmp_path)],
            check=True,
            capture_output=True,
        )

        debs = sorted(tmp_path.glob("*.deb"))
        assert len(debs) == 1, f"expected exactly one .deb in {tmp_path}, got {debs}"
        assert debs[0].name == expected_deb_name
        deb = debs[0]

        # --- Metadata (dpkg-deb --field) -------------------------------------------
        field_output = subprocess.run(
            [
                "dpkg-deb",
                "--field",
                str(deb),
                "Package",
                "Architecture",
                "Version",
                "Depends",
                "Replaces",
                "Conflicts",
                "Breaks",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        fields = {
            key.strip(): value.strip()
            for line in field_output.splitlines()
            for key, sep, value in [line.partition(":")]
            if sep
        }
        assert fields.get("Package") == "clamui-privileged-helper"
        assert fields.get("Architecture") == "all"
        # The control Version must resolve to the project version, proving the
        # builder substituted the template placeholder rather than shipping the
        # literal token.
        assert fields.get("Version") == version, (
            f"control Version must equal project version {version!r}, got {fields.get('Version')!r}"
        )
        # Depends is asserted exactly (whitespace-normalized): no extras,
        # no `python3-dev` slipping through via a loose substring match.
        depends = fields.get("Depends", "")
        assert " ".join(depends.split()) == "python3, pkexec | policykit-1", (
            f"unexpected Depends: {depends!r}"
        )
        # Upgrade-transition metadata: the released clamui 0.3.0 already owns
        # the helper/library/policy paths, so the helper must Replaces it (at
        # most the same version) so dpkg can transfer ownership. No
        # Conflicts/Breaks: Replaces does not force removal, so the two
        # packages stay co-installable.
        assert fields.get("Replaces") == f"clamui (<= {version})", (
            f"unexpected Replaces: {fields.get('Replaces')!r}; expected 'clamui (<= {version})'"
        )
        assert not fields.get("Conflicts"), (
            f"unexpected Conflicts (would force removal): {fields.get('Conflicts')!r}"
        )
        assert not fields.get("Breaks"), (
            f"unexpected Breaks (would force removal): {fields.get('Breaks')!r}"
        )

        # --- Payload set & ownership (dpkg-deb --fsys-tarfile + tarfile) ---------
        # Inspect the raw filesystem tar (not --contents text) so the
        # regular-file set and ownership are checked exactly without parsing
        # frame layout or localized output.
        payload_tar = subprocess.run(
            ["dpkg-deb", "--fsys-tarfile", str(deb)],
            check=True,
            capture_output=True,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(payload_tar)) as tf:
            regular_files = sorted(
                m.name.lstrip("./").rstrip("/") for m in tf.getmembers() if m.isfile()
            )
            assert regular_files == sorted(ALL_FILES), (
                "regular-file payload must be exactly the four canonical files "
                f"(no package metadata, no extras); got {regular_files}"
            )
            # The helper is built with --root-owner-group: every filesystem
            # entry (files and directories) must be root-owned, matching its
            # root-owned security model.
            for m in tf.getmembers():
                assert m.uid == 0 and m.gid == 0, (
                    f"payload entry {m.name!r} must be root-owned (uid={m.uid}, gid={m.gid})"
                )

        # --- Payload (dpkg-deb --extract) ------------------------------------------
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        subprocess.run(
            ["dpkg-deb", "--extract", str(deb), str(extracted)],
            check=True,
            capture_output=True,
        )
        for relative in ALL_FILES:
            assert (extracted / relative).is_file(), f"missing canonical file: {relative}"

        # The wrapper must be executable by its owner.
        wrapper_mode = stat.S_IMODE((extracted / WRAPPER).stat().st_mode)
        assert wrapper_mode & stat.S_IXUSR, "wrapper should be executable by its owner"

        # Installed library and policy files must not be group- or world-writable.
        for relative in (*LIBRARY_FILES, POLICY_FILE):
            mode = stat.S_IMODE((extracted / relative).stat().st_mode)
            assert not (mode & stat.S_IWGRP), f"{relative} must not be group-writable"
            assert not (mode & stat.S_IWOTH), f"{relative} must not be world-writable"
