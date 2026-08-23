# ClamUI installed-wheel privileged-helper tests
"""
RED regression for the installed-layout failure of the privileged-helper
installer.

The approved fix ships the polkit policy inside an importable package
(``src.cli.resources``) and resolves it with ``importlib.resources``, so
``install_privileged_helper`` can locate it after the project is built into a
wheel and installed, where the checkout's ``data/`` directory no longer exists.

This regression would resurface if the resource were omitted from the wheel
build (``packages = ["src"]`` in ``pyproject.toml``) -- the installer would
return ``(False, "not found")`` -- so it end-to-end verifies that the package
resource is bundled and locatable from an isolated interpreter.

This is a genuine end-to-end installation check, not a mock: it builds the
project wheel, installs it into an isolated virtual environment with no other
dependency, runs *that interpreter* with ``-I`` (isolated mode) from a temporary
directory so it cannot import the checkout, and verifies the helper installs the
policy to a staging prefix.  It is skipped only when a tool the parent project
mandates (``uv``) is unavailable.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

# Get project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ``uv`` is the project's package/build front-end (see repo CLAUDE.md).  Gate the
# whole module on it being present -- a genuine external executable the wheel
# test cannot function without.  No module-level assert: pytest evaluates the
# skip only after importing, so a collection-time check would raise instead of
# skip on a machine without ``uv``.  ``cast`` narrows the type without a runtime
# check; the skip has already guaranteed truthiness by the time the body runs.
_UV = shutil.which("uv")
pytestmark = pytest.mark.skipif(not _UV, reason="uv not available")
uv = cast(str, _UV)


def _run_for_json(result: subprocess.CompletedProcess) -> dict:
    """Decode JSON produced by the isolation probe or fail with the captured
    streaming output for diagnosis."""
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise AssertionError(
            f"isolation probe exited {result.returncode} with non-JSON output:\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        ) from None


class TestInstalledWheelInstallsPolicy:
    """After a real ``uv`` build + install, the privileged helper must still find
    and install the polkit policy from the installed package."""

    def test_policy_resource_discovered_from_wheel(self, tmp_path):
        # 1. Build the wheel into an isolated output directory.
        wheel_out = tmp_path / "wheelhouse"
        wheel_out.mkdir()
        build = subprocess.run(
            [uv, "build", "--wheel", "--out-dir", str(wheel_out)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        assert build.returncode == 0, f"uv build --wheel failed:\n{build.stderr}"
        wheels = list(wheel_out.glob("clamui-*.whl"))
        assert wheels, "no wheel produced"
        wheel = wheels[0]

        # 2. Install it into a throwaway venv with no dependencies.
        venv_dir = tmp_path / "venv"
        create = subprocess.run(
            [uv, "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert create.returncode == 0, f"uv venv failed:\n{create.stderr}"

        venv_python = venv_dir / "bin" / "python"
        install = subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(venv_python),
                "--no-deps",
                str(wheel),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert install.returncode == 0, f"uv pip install failed:\n{install.stderr}"

        # 3. Run the installed interpreter in isolated mode (-I) from a directory
        #    that is NOT the checkout, so it cannot import the checkout's ``src``.
        #    The probe reports the FILE the helper module was loaded FROM (the
        #    module's __file__, never the function's __file__, which a plain
        #    function lacks) so we can prove the import did not come from the tree.
        probe = tmp_path / "probe.py"
        probe.write_text(
            "import json\n"
            "from src.cli import install_helper\n"
            "print(json.dumps({'file': install_helper.__file__}))\n",
            encoding="utf-8",
        )
        runnable = subprocess.run(
            [str(venv_python), "-I", str(probe)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
            # Scrub anything that could let the child find the checkout.
            env={"LC_ALL": "C", "LANGUAGE": "C", "PATH": os.environ.get("PATH", "")},
        )
        assert runnable.returncode == 0, f"isolated import probe failed:\n{runnable.stderr}"
        info = _run_for_json(runnable)

        # The module must have been imported from inside the venv's site-packages,
        # proving the install (and not the checkout on sys.path) supplied it.
        loaded_from = info.get("file", "")
        assert loaded_from, (
            "could not determine install_helper.__file__ from the installed interpreter"
        )
        assert str(venv_dir) in loaded_from, (
            f"install_helper imported from outside the venv: {loaded_from}\n"
            f"checkout isolation failed"
        )
        assert str(PROJECT_ROOT) not in Path(loaded_from).resolve().as_posix(), (
            f"install_helper leaked into the checkout: {loaded_from}"
        )

        # 4. The real installed-layout assertion: call the installer for a staging
        #    prefix (no root needed) and require the policy to land on disk.  This
        #    is where current production fails: the policy source is not packaged,
        #    so install_privileged_helper returns (False, "not found").
        target_root = tmp_path / "target"
        runner = tmp_path / "install.py"
        runner.write_text(
            "import sys\n"
            "from src.cli import install_helper\n"
            "ok, msg = install_helper.install_privileged_helper(prefix=sys.argv[1])\n"
            "print(msg, file=sys.stderr)\n"
            "sys.exit(0 if ok else 1)\n",
            encoding="utf-8",
        )
        install_run = subprocess.run(
            [str(venv_python), "-I", str(runner), str(target_root)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
            env={"LC_ALL": "C", "LANGUAGE": "C", "PATH": os.environ.get("PATH", "")},
        )
        assert install_run.returncode == 0, (
            f"install from the installed wheel failed (policy not locatable):\n{install_run.stderr}"
        )
        policy = target_root / "usr/share/polkit-1/actions" / "io.github.linx_systems.ClamUI.policy"
        assert policy.is_file(), f"polkit policy was not installed to the staging root:\n{policy}"
        assert policy.read_text(encoding="utf-8").strip(), "installed policy file is empty"
