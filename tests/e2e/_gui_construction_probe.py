"""Real-GTK construction probe (run as a subprocess by test_gui_construction.py).

Forces construction of every ClamUI view, preference page, and dialog under a
real, activated Adw.Application. This catches the class of bug where a view or
dialog references a nonexistent method / wrong widget API / bad constructor
argument -- defects that mocked-GTK unit tests cannot see (e.g. the VirusTotal
results dialog, which was silently broken until it was actually constructed).

Exit code 0 = every surface constructed cleanly; 1 = at least one failed.
Run via the parent test under xvfb; not collected by pytest itself.
"""

import dataclasses
import sys
import traceback
import typing

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib

from src.app import ClamUIApp

results: dict[str, tuple[str, str]] = {}

VIEW_PROPS = [
    "scan_view",
    "update_view",
    "logs_view",
    "components_view",
    "statistics_view",
    "quarantine_view",
    "audit_view",
]


def _noop(*_args, **_kwargs):
    return None


def make_dc(cls, **overrides):
    """Build a dataclass instance, filling required fields by resolved type."""
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in overrides:
            kwargs[f.name] = overrides[f.name]
            continue
        if f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING:
            continue
        hint = hints.get(f.name, str)
        origin = typing.get_origin(hint)
        args = typing.get_args(hint)
        if origin in (list, tuple, set):
            kwargs[f.name] = []
        elif type(None) in args:
            kwargs[f.name] = None
        elif hint is int:
            kwargs[f.name] = 0
        elif hint is float:
            kwargs[f.name] = 0.0
        elif hint is bool:
            kwargs[f.name] = False
        elif hint is str:
            kwargs[f.name] = ""
        else:
            kwargs[f.name] = None
    return cls(**kwargs)


def _record(name, fn):
    try:
        fn()
        results[name] = ("OK", "")
    except Exception as e:
        results[name] = ("FAIL", repr(e) + "\n" + traceback.format_exc())


def _probe_dialogs(app):
    from src.core.scanner_types import ScanResult, ScanStatus
    from src.core.virustotal import VTScanResult, VTScanStatus
    from src.ui.close_behavior_dialog import CloseBehaviorDialog
    from src.ui.database_missing_dialog import DatabaseMissingDialog
    from src.ui.file_manager_integration_dialog import FileManagerIntegrationDialog
    from src.ui.fullscreen_dialog import FullscreenLogDialog
    from src.ui.profile_dialogs import (
        DeleteProfileDialog,
        PatternEntryDialog,
        ProfileDialog,
        ProfileListDialog,
        RestoreDefaultsDialog,
    )
    from src.ui.scan_in_progress_dialog import ScanInProgressDialog
    from src.ui.scan_results_dialog import ScanResultsDialog
    from src.ui.virustotal_results_dialog import VirusTotalResultsDialog
    from src.ui.virustotal_setup_dialog import VirusTotalSetupDialog

    sm = app.settings_manager
    pm = app.profile_manager
    qm = app.quarantine_manager
    default_profile = next((p for p in pm.list_profiles() if p.is_default), None)

    scan_clean = make_dc(ScanResult, status=ScanStatus.CLEAN)
    scan_infected = make_dc(
        ScanResult, status=ScanStatus.INFECTED, infected_count=1, infected_files=["/tmp/x"]
    )
    vt_clean = make_dc(VTScanResult, status=VTScanStatus.CLEAN)
    vt_detected = make_dc(
        VTScanResult, status=VTScanStatus.DETECTED, detections=3, total_engines=70
    )

    _record("CloseBehaviorDialog", lambda: CloseBehaviorDialog(callback=_noop))
    _record("DatabaseMissingDialog", lambda: DatabaseMissingDialog(callback=_noop))
    _record(
        "FileManagerIntegrationDialog",
        lambda: FileManagerIntegrationDialog(settings_manager=sm, on_complete=_noop),
    )
    _record("FullscreenLogDialog", lambda: FullscreenLogDialog(title="T", content="body"))
    _record("PatternEntryDialog", PatternEntryDialog)
    _record("RestoreDefaultsDialog", RestoreDefaultsDialog)
    _record("DeleteProfileDialog", lambda: DeleteProfileDialog(profile_name="Quick Scan"))
    _record("ProfileListDialog", lambda: ProfileListDialog(profile_manager=pm))
    _record("ProfileDialog(create)", lambda: ProfileDialog(profile_manager=pm, profile=None))
    _record(
        "ProfileDialog(edit)", lambda: ProfileDialog(profile_manager=pm, profile=default_profile)
    )
    _record("ScanInProgressDialog", lambda: ScanInProgressDialog(callback=_noop))
    _record(
        "ScanResultsDialog(clean)",
        lambda: ScanResultsDialog(
            scan_result=scan_clean, quarantine_manager=qm, settings_manager=sm
        ),
    )
    _record(
        "ScanResultsDialog(infected)",
        lambda: ScanResultsDialog(
            scan_result=scan_infected, quarantine_manager=qm, settings_manager=sm
        ),
    )
    _record("VirusTotalResultsDialog(clean)", lambda: VirusTotalResultsDialog(vt_result=vt_clean))
    _record(
        "VirusTotalResultsDialog(detected)",
        lambda: VirusTotalResultsDialog(vt_result=vt_detected),
    )
    _record(
        "VirusTotalSetupDialog",
        lambda: VirusTotalSetupDialog(
            settings_manager=sm, on_key_saved=_noop, on_open_website=_noop
        ),
    )


def probe():
    app = _app
    for name in VIEW_PROPS:
        _record(name, lambda n=name: getattr(app, n))

    try:
        from src.ui.preferences.window import PreferencesWindow

        pw = PreferencesWindow(
            settings_manager=app.settings_manager,
            tray_available=False,
            transient_for=app.props.active_window,
        )
        results["PreferencesWindow"] = ("OK", "")
        for pid, factory in list(getattr(pw, "_page_factories", {}).items()):
            _record(f"prefs:{pid}", factory)
    except Exception as e:
        results["PreferencesWindow"] = ("FAIL", repr(e) + "\n" + traceback.format_exc())

    _probe_dialogs(app)

    app.quit()
    return False


def on_activate(_a):
    GLib.idle_add(probe)


_app = ClamUIApp()
# Force a local instance: without this, a ClamUI already running on the session
# bus would make run() delegate to it and the probe would silently no-op.
_app.set_flags(_app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
_app.connect("activate", on_activate)
_app.run([])

if not results:
    sys.stderr.write("probe did not run (activate never fired)\n")
    sys.exit(2)

failed = 0
for name, (status, info) in results.items():
    if status == "OK":
        print(f"OK   {name}")
    else:
        failed += 1
        print(f"FAIL {name}: {info}")
print(f"=== {failed} failures / {len(results)} surfaces ===")
sys.exit(1 if failed else 0)
