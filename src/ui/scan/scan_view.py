# Main Scan View
"""
Main scan view composing profile selection, target selection, and scan control.

This is the composition root that wires together:
- ProfileSelector: Profile management
- TargetSelector: Path selection
- ScanController: Scan orchestration
- ScanProgressWidget: Progress display
- ScanResultsWidget: Results button
"""

import os
import tempfile
from contextlib import suppress
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

from ...core.i18n import _
from ...core.quarantine import QuarantineManager
from ...core.result_formatters import clean_scan_status_message
from ...core.scanner import Scanner, ScanResult, ScanStatus
from ...core.settings_manager import SettingsManager
from ...core.utils import format_scan_path, is_flatpak
from ..compat import create_banner
from ..scan_results_dialog import ScanResultsDialog
from ..view_helpers import StatusLevel, set_status_class
from .profile_selector import ProfileSelector
from .scan_controller import ScanController, ScanState
from .scan_progress_widget import ScanProgressWidget
from .scan_results_widget import ScanResultsWidget
from .target_selector import TargetSelector

EICAR_TEST_STRING = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

try:
    _GTK_MINOR_VERSION = Gtk.get_minor_version()
    _HAS_CSS_LOAD_STRING = _GTK_MINOR_VERSION >= 12
except (TypeError, AttributeError):
    _HAS_CSS_LOAD_STRING = False


class ScanView(Gtk.Box):
    """
    Main scan view - composition root.

    Delegates to:
    - ProfileSelector: Profile management
    - TargetSelector: Path selection
    - ScanController: Scan orchestration
    - ScanProgressWidget: Progress display
    - ScanResultsWidget: Results button
    """

    def __init__(
        self,
        settings_manager: SettingsManager | None = None,
        quarantine_manager: QuarantineManager | None = None,
        log_manager=None,
        **kwargs,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)

        self._settings_manager = settings_manager
        self._quarantine_manager = quarantine_manager or QuarantineManager()
        self._log_manager = log_manager
        self._current_result: ScanResult | None = None
        self._scan_state_callback = None
        self._eicar_temp_path = ""

        self._setup_css()
        # The controller must exist before the UI: _setup_ui() builds the
        # backend indicator from self._scanner.
        self._setup_controller()
        self._setup_ui()

    def _setup_css(self):
        css_provider = Gtk.CssProvider()
        css_string = """
            .progress-section { padding: 12px 0; }
            .progress-bar-compact { min-height: 6px; border-radius: 3px; }
            .drop-active {
                border: 2px dashed @accent_color;
                border-radius: 12px;
                background-color: alpha(@accent_bg_color, 0.1);
            }
        """
        if _HAS_CSS_LOAD_STRING:
            css_provider.load_from_string(css_string)
        else:
            css_provider.load_from_data(css_string.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _setup_ui(self):
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_spacing(12)

        # Profile selector
        self._profile_selector = ProfileSelector(self._get_profile_manager)
        self._profile_selector.connect("targets-changed", self._on_profile_targets)
        self._profile_selector.connect("start-scan-requested", lambda w: self._start_scan())
        self.append(self._profile_selector)

        # Target selector
        self._target_selector = TargetSelector(is_scanning=self._is_scanning)
        self.append(self._target_selector)

        # Scan buttons
        self._append_scan_controls()

        # Progress widget
        self._progress_widget = ScanProgressWidget()
        self.append(self._progress_widget)

        # Results widget
        self._results_widget = ScanResultsWidget(self._show_results_dialog)
        self.append(self._results_widget)

        # Backend indicator
        self._append_backend_indicator()

        # Status banner
        self._status_banner = create_banner()
        self._status_banner.connect("button-clicked", lambda b: b.set_revealed(False))
        self.append(self._status_banner)

        # Drop target
        self._setup_drop_target()

    def _setup_controller(self):
        self._scanner = Scanner(
            log_manager=self._log_manager, settings_manager=self._settings_manager
        )

        self._controller = ScanController(self._scanner, self._settings_manager)
        self._controller.set_callbacks(
            on_progress=self._on_progress,
            on_complete=self._on_scan_complete,
            on_state_change=self._on_state_change,
        )

    def _append_scan_controls(self):
        group = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        self._start_btn = Gtk.Button(label=_("Start Scan"))
        self._start_btn.add_css_class("suggested-action")
        self._start_btn.set_size_request(150, -1)
        self._start_btn.connect("clicked", lambda b: self._start_scan())
        box.append(self._start_btn)

        self._eicar_btn = Gtk.Button(label=_("EICAR Test"))
        self._eicar_btn.set_tooltip_text(
            _("Run a scan with EICAR test file to verify antivirus detection")
        )
        self._eicar_btn.set_size_request(120, -1)
        self._eicar_btn.connect("clicked", self._on_eicar_test)
        box.append(self._eicar_btn)

        self._cancel_btn = Gtk.Button(label=_("Cancel"))
        self._cancel_btn.add_css_class("destructive-action")
        self._cancel_btn.set_size_request(120, -1)
        self._cancel_btn.set_visible(False)
        self._cancel_btn.connect("clicked", lambda b: self._controller.cancel())
        box.append(self._cancel_btn)

        group.add(box)
        self.append(group)

    def _append_backend_indicator(self):
        label = Gtk.Label()
        label.set_halign(Gtk.Align.CENTER)
        label.add_css_class("dim-label")
        label.add_css_class("caption")
        backend = self._scanner.get_active_backend()
        names = {"daemon": "clamd (daemon)", "clamscan": "clamscan (standalone)"}
        label.set_label(_("Backend: {name}").format(name=names.get(backend, backend)))
        self.append(label)

    def _setup_drop_target(self):
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        drop.connect(
            "enter", lambda *args: (self.add_css_class("drop-active"), Gdk.DragAction.COPY)[1]
        )
        drop.connect("leave", lambda t: self.remove_css_class("drop-active"))
        drop.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(drop)

    def _on_drop(self, target, value, x, y) -> bool:
        self.remove_css_class("drop-active")
        if self._is_scanning():
            self._show_toast(_("Cannot add targets while scanning"))
            return False

        files = value.get_files()
        paths = [f.get_path() for f in files if f.get_path()]

        from ...core.utils import validate_dropped_files

        valid, errors = validate_dropped_files(paths)

        for p in valid:
            self._target_selector.add_path(p)

        if errors and not valid:
            self._show_toast(errors[0])

        return len(valid) > 0

    # --- Controller callbacks ---

    def _on_progress(self, progress, cumulative, total_targets):
        self._progress_widget.update(
            progress,
            cumulative_files=cumulative,
            multi_target=len(self._target_selector.paths) > 1,
            current_target=self._controller.current_target_idx,
            total_targets=self._controller.total_targets,
        )

    def _on_scan_complete(self, result: ScanResult):
        self._current_result = result
        self._cleanup_eicar()

        self._progress_widget.stop()
        self._start_btn.set_sensitive(True)
        self._eicar_btn.set_sensitive(True)
        self._target_selector.set_sensitive(True)
        self._cancel_btn.set_visible(False)

        self._results_widget.show(result.infected_count)

        if result.status == ScanStatus.INFECTED:
            self._show_banner(
                _("Scan complete - {count} threat(s) detected").format(count=result.infected_count),
                StatusLevel.WARNING,
            )
        elif result.status == ScanStatus.CLEAN:
            self._show_banner(clean_scan_status_message(result), StatusLevel.SUCCESS)
        elif result.status == ScanStatus.CANCELLED:
            self._show_banner(_("Scan cancelled"), StatusLevel.WARNING)
        else:
            self._show_banner(
                _("Scan error: {error}").format(error=result.error_message or "Unknown"),
                StatusLevel.ERROR,
            )

    def _on_state_change(self, state: ScanState):
        if self._scan_state_callback:
            self._scan_state_callback(state == ScanState.SCANNING, self._current_result)

    # --- User actions ---

    def _start_scan(self):
        paths = self._target_selector.paths
        if not paths:
            self._show_banner(_("Please select a file or folder to scan"), StatusLevel.WARNING)
            return

        if not self._check_database():
            return

        self._start_btn.set_sensitive(False)
        self._eicar_btn.set_sensitive(False)
        self._target_selector.set_sensitive(False)
        self._cancel_btn.set_visible(True)
        self._status_banner.set_revealed(False)
        self._results_widget.hide()
        # Match the controller: with live progress off it creates no progress
        # callback, so the file/stats rows would sit on "Waiting for scan
        # data..." forever if shown.
        show_live = True
        if self._settings_manager:
            show_live = self._settings_manager.get("show_live_progress", True)
        self._progress_widget.start(show_live_progress=show_live)
        self._progress_widget.set_status(_("Scanning..."))

        self._controller.start_scan(
            paths,
            profile_exclusions=self._profile_selector.get_exclusions(),
            on_target_progress=self._on_target_progress,
        )

    def _on_target_progress(self, current: int, total: int, path: str):
        display = format_scan_path(path)
        if len(display) > 40:
            display = "..." + display[-37:]
        if total > 1:
            self._progress_widget.set_status(
                _("Target {current} of {total}: {path}").format(
                    current=current, total=total, path=display
                )
            )
        else:
            self._progress_widget.set_status(_("Scanning {path}").format(path=display))

    def _on_eicar_test(self, button):
        if not self._check_database():
            return

        try:
            if is_flatpak():
                temp_dir = str(Path.home() / ".cache" / "clamui")
                Path(temp_dir).mkdir(parents=True, exist_ok=True)
            else:
                temp_dir = None

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", prefix="eicar_", delete=False, dir=temp_dir
            ) as f:
                f.write(EICAR_TEST_STRING)
                self._eicar_temp_path = f.name

            self._target_selector.set_paths([self._eicar_temp_path])
            self._start_scan()
        except OSError as e:
            self._show_banner(
                _("Failed to create EICAR test file: {error}").format(error=e), StatusLevel.ERROR
            )

    # --- Helper methods ---

    def _is_scanning(self) -> bool:
        return self._controller.is_scanning

    def _get_profile_manager(self):
        root = self.get_root()
        if not root:
            return None
        app = root.get_application() if hasattr(root, "get_application") else None
        return getattr(app, "profile_manager", None) if app else None

    def _on_profile_targets(self, selector, targets):
        self._target_selector.set_paths(targets)

    def _check_database(self) -> bool:
        from ...core.clamav_detection import check_database_available

        available, _ = check_database_available()
        if not available:
            from ..database_missing_dialog import DatabaseMissingDialog

            root = self.get_root()
            if root:

                def on_response(choice):
                    if choice == "download":
                        app = root.get_application()
                        if app:
                            app.activate_action("show-update", None)

                dialog = DatabaseMissingDialog(callback=on_response)
                dialog.set_transient_for(root)
                dialog.present()
        return available

    def _show_results_dialog(self):
        if not self._current_result or not self.get_root():
            return
        dialog = ScanResultsDialog(
            scan_result=self._current_result,
            quarantine_manager=self._quarantine_manager,
            settings_manager=self._settings_manager,
        )
        dialog.set_transient_for(self.get_root())
        dialog.present()

    def _show_banner(self, message: str, level: StatusLevel):
        self._status_banner.set_title(message)
        set_status_class(self._status_banner, level)
        self._status_banner.set_revealed(True)

    def _show_toast(self, message: str):
        root = self.get_root()
        if root and hasattr(root, "add_toast"):
            root.add_toast(Adw.Toast.new(message))

    def _cleanup_eicar(self):
        if self._eicar_temp_path and os.path.exists(self._eicar_temp_path):
            with suppress(OSError):
                os.remove(self._eicar_temp_path)
            self._eicar_temp_path = ""

    # --- Public API ---

    @property
    def is_scanning(self) -> bool:
        """Whether a scan is currently in progress."""
        return self._controller.is_scanning

    def set_scan_state_changed_callback(self, callback):
        self._scan_state_callback = callback

    def get_selected_profile(self):
        return self._profile_selector.selected_profile

    def set_selected_profile(self, profile_id: str) -> bool:
        return self._profile_selector.set_selected_profile(profile_id)

    def refresh_profiles(self):
        self._profile_selector.refresh()

    def show_file_picker(self):
        self._target_selector._show_file_dialog(select_folders=True)

    def _set_selected_path(self, path: str):
        self._target_selector.set_paths([path])

    def _replace_selected_paths(self, paths: list[str]) -> None:
        self._target_selector.set_paths(paths)

    def _start_scan_public(self):
        self._start_scan()
