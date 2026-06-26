# ClamUI GUI Construction Smoke Test
"""
Real-GTK construction smoke test.

Runs `_gui_construction_probe.py` in a SUBPROCESS (a pristine real-`gi` process)
under the active display, asserting that every view, preference page, and dialog
constructs without error. Subprocess isolation keeps real GTK out of the
mocked-GTK unit suite (no module-cache contamination).

This guards the class of defect where a view/dialog references a nonexistent
method, a wrong widget API, or bad constructor arguments -- which mocked-GTK
unit tests cannot detect (e.g. the VirusTotal results dialog, which was silently
broken until it was actually constructed). Skips when no display is available
(run under xvfb in CI).
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROBE = Path(__file__).with_name("_gui_construction_probe.py")


@pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="real-GTK construction requires a display (run under xvfb)",
)
def test_all_views_pages_and_dialogs_construct_under_real_gtk():
    """Every view, preference page, and dialog must build under real GTK."""
    assert _PROBE.exists(), f"probe script missing: {_PROBE}"

    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "XDG_CONFIG_HOME": os.path.join(tmp, "config"),
            "XDG_DATA_HOME": os.path.join(tmp, "data"),
            "XDG_CACHE_HOME": os.path.join(tmp, "cache"),
        }
        proc = subprocess.run(
            [sys.executable, str(_PROBE)],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    assert proc.returncode == 0, (
        f"GUI construction probe failed (exit {proc.returncode}):\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    # Sanity: the probe must have actually exercised surfaces.
    assert "surfaces ===" in proc.stdout, f"probe produced no summary:\n{proc.stdout}"
