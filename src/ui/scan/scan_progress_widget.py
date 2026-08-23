# Scan Progress Widget
"""
Adwaita-styled progress display widget for scan operations.

Single responsibility:
- Display progress bar with pulse animation inside Adw.PreferencesGroup
- Show live file being scanned via Adw.ActionRow with spinner
- Display stats (files scanned, target info) via Adw.ActionRow
- Show real-time threat list as threats are detected
"""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ...core.i18n import _, ngettext
from ...core.scanner import ScanProgress
from ..compat import safe_set_subtitle_lines
from ..utils import resolve_icon_name


class ScanProgressWidget(Gtk.Box):
    """
    Widget showing scan progress with Adwaita-styled groups and rows.

    Contains two groups:
    - Scan Progress: progress bar, current file row, stats row
    - Threats Detected: live threat list (hidden until first detection)
    """

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, **kwargs)
        self.set_visible(False)

        self._pulse_id = None
        self._paused = False
        self._live_threat_count = 0

        self._build_ui()

    def _build_ui(self):
        # --- Scan Progress group ---
        self._progress_group = Adw.PreferencesGroup()
        self._progress_group.set_title(_("Scan Progress"))

        # Progress bar wrapper
        bar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar_box.set_margin_start(12)
        bar_box.set_margin_end(12)
        bar_box.set_margin_top(4)
        bar_box.set_margin_bottom(4)

        self._bar = Gtk.ProgressBar()
        self._bar.add_css_class("progress-bar-compact")
        bar_box.append(self._bar)

        self._status_label = Gtk.Label()
        self._status_label.set_label(_("Scanning..."))
        self._status_label.add_css_class("dim-label")
        self._status_label.set_xalign(0)
        self._status_label.set_margin_top(4)
        bar_box.append(self._status_label)

        self._progress_group.add(bar_box)

        # Currently scanning row
        self._current_file_row = Adw.ActionRow()
        self._current_file_row.set_title(_("Currently scanning"))
        self._current_file_row.set_subtitle(_("Waiting for scan data..."))
        safe_set_subtitle_lines(self._current_file_row, 1)
        self._file_spinner = Gtk.Spinner()
        self._file_spinner.set_spinning(True)
        self._current_file_row.add_prefix(self._file_spinner)
        self._current_file_row.set_visible(False)
        self._progress_group.add(self._current_file_row)

        # Stats row
        self._stats_row = Adw.ActionRow()
        self._stats_row.set_title(_("Scanned 0 files"))
        stats_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("document-open-symbolic"))
        self._stats_row.add_prefix(stats_icon)
        self._stats_row.set_visible(False)
        self._progress_group.add(self._stats_row)

        self.append(self._progress_group)

        # --- Threats Detected group ---
        self._threat_group = Adw.PreferencesGroup()
        self._threat_group.set_title(_("Threats Detected"))
        self._threat_group.set_visible(False)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(200)
        scrolled.set_propagate_natural_height(True)

        self._live_threat_list = Gtk.ListBox()
        self._live_threat_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._live_threat_list.add_css_class("boxed-list")
        scrolled.set_child(self._live_threat_list)

        self._threat_group.add(scrolled)
        self.append(self._threat_group)

    def start(self, show_live_progress: bool = True) -> None:
        """Show widget and start pulsing.

        Args:
            show_live_progress: Whether to show detailed file/stats rows.
        """
        self.set_visible(True)
        self._live_threat_count = 0
        self._current_file_row.set_visible(show_live_progress)
        self._current_file_row.set_subtitle(_("Waiting for scan data..."))
        self._file_spinner.set_spinning(show_live_progress)
        self._stats_row.set_visible(show_live_progress)
        self._stats_row.set_title(_("Scanned 0 files"))
        self._stats_row.set_subtitle("")
        self._threat_group.set_visible(False)
        self._clear_threat_list()
        self._start_pulse()

    def stop(self) -> None:
        """Hide widget and stop pulsing."""
        self._stop_pulse()
        self.set_visible(False)
        self._file_spinner.set_spinning(False)
        self._current_file_row.set_visible(False)
        self._stats_row.set_visible(False)
        self._threat_group.set_visible(False)
        self._clear_threat_list()
        self._live_threat_count = 0

    def update(
        self,
        progress: ScanProgress,
        cumulative_files: int = 0,
        multi_target: bool = False,
        current_target: int = 1,
        total_targets: int = 1,
    ) -> None:
        """Update progress display with Adwaita rows."""
        if self._paused:
            return

        # Progress bar
        if progress.percentage is not None:
            self._stop_pulse()
            self._bar.set_fraction(progress.percentage / 100)
            pct = int(progress.percentage)
            if multi_target:
                self._status_label.set_text(
                    _("Target {current} of {total} \u2014 {pct}%").format(
                        current=current_target, total=total_targets, pct=pct
                    )
                )
            else:
                self._status_label.set_text(_("Scanning... {pct}%").format(pct=pct))

        # Current file row
        if progress.current_file:
            self._current_file_row.set_subtitle(self._truncate_path(progress.current_file))

        # Stats row
        total = cumulative_files + progress.files_scanned
        if multi_target:
            if progress.files_total:
                self._stats_row.set_title(
                    _("Scanned {scanned} / {total} files").format(
                        scanned=f"{progress.files_scanned:,}",
                        total=f"{progress.files_total:,}",
                    )
                )
            else:
                self._stats_row.set_title(
                    _("Scanned {scanned} files").format(
                        scanned=f"{progress.files_scanned:,}",
                    )
                )
            self._stats_row.set_subtitle(
                _("Target {current} of {total} ({cumulative} total)").format(
                    current=current_target,
                    total=total_targets,
                    cumulative=f"{total:,}",
                )
            )
        elif progress.files_total:
            self._stats_row.set_title(
                _("Scanned {scanned} / {total} files").format(
                    scanned=f"{progress.files_scanned:,}",
                    total=f"{progress.files_total:,}",
                )
            )
            self._stats_row.set_subtitle("")
        else:
            self._stats_row.set_title(
                _("Scanned {scanned} files").format(
                    scanned=f"{progress.files_scanned:,}",
                )
            )
            self._stats_row.set_subtitle("")

        # Append new threats. Bump the counter per row so the group title
        # counts correctly when several threats arrive in one update, then
        # sync to the authoritative count (infected_files can lag it).
        if progress.infected_count > self._live_threat_count:
            threats = progress.infected_threats or {}
            for file_path in progress.infected_files[self._live_threat_count :]:
                threat_name = threats.get(file_path, _("Unknown threat"))
                self._live_threat_count += 1
                self._append_threat_row(file_path, threat_name)
            self._live_threat_count = progress.infected_count

    def set_status(self, text: str) -> None:
        """Set status label text."""
        self._status_label.set_text(text)

    def _append_threat_row(self, file_path: str, threat_name: str):
        """Append a threat row to the live threat list."""
        row = Adw.ActionRow()
        row.set_title(Path(file_path).name)
        row.set_subtitle(threat_name)
        row.set_tooltip_text(file_path)

        icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
        icon.add_css_class("warning")
        row.add_prefix(icon)

        self._live_threat_list.append(row)

        self._threat_group.set_title(
            ngettext(
                "Threats Detected ({n})",
                "Threats Detected ({n})",
                self._live_threat_count,
            ).format(n=self._live_threat_count)
        )
        self._threat_group.set_visible(True)

    def _clear_threat_list(self):
        """Remove all rows from the live threat list."""
        while True:
            row = self._live_threat_list.get_row_at_index(0)
            if row is None:
                break
            self._live_threat_list.remove(row)

    def _start_pulse(self):
        if self._pulse_id:
            return
        self._pulse_id = GLib.timeout_add(100, self._do_pulse)

    def _stop_pulse(self):
        if self._pulse_id:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = None

    def _do_pulse(self) -> bool:
        self._bar.pulse()
        return True

    def _truncate_path(self, path: str, max_len: int = 60) -> str:
        if len(path) <= max_len:
            return path
        p = Path(path)
        if p.parent.name:
            return f".../{p.parent.name}/{p.name}"
        return "..." + path[-(max_len - 3) :]

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False
