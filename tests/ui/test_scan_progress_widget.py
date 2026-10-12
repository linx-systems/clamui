"""Tests for raw-filename rendering in the scan progress widget."""

from unittest.mock import MagicMock


def _clear_src_modules():
    import sys

    for module_name in [name for name in sys.modules if name.startswith("src.")]:
        del sys.modules[module_name]


def test_live_threat_row_sanitizes_surrogate_filename(mock_gi_modules):
    """GTK receives only a display-safe version of a raw filesystem path."""
    from src.ui.scan.scan_progress_widget import ScanProgressWidget

    row = MagicMock()
    mock_gi_modules["adw"].ActionRow.side_effect = lambda: row
    widget = object.__new__(ScanProgressWidget)
    widget._live_threat_list = MagicMock()
    widget._threat_group = MagicMock()
    widget._live_threat_count = 1

    widget._append_threat_row("/tmp/infected_\udcff", "TestThreat")

    row.set_title.assert_called_once_with("infected_\ufffd")
    row.set_tooltip_text.assert_called_once_with("/tmp/infected_\ufffd")
    _clear_src_modules()
