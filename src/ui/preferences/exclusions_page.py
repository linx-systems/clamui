# ClamUI Exclusions Page
"""
Exclusions preference page for scan exclusion patterns.

This module provides the ExclusionsPage class which handles the UI and logic
for managing scan exclusion patterns, including preset and custom exclusions.
"""

import copy

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ...core.i18n import N_, _
from ...core.settings_manager import PRESET_EXCLUSION_PATTERNS, normalize_exclusion_patterns
from ..compat import create_entry_row, create_switch_row
from ..utils import resolve_icon_name
from .base import PreferencesPageMixin

# Localized metadata for the canonical records defined in the settings layer.
_PRESET_DESCRIPTIONS = (
    N_("Node.js dependencies"),
    N_("Git repository data"),
    N_("Python virtual environment"),
    N_("Build output directory"),
    N_("Distribution output directory"),
    N_("Python bytecode cache"),
)

PRESET_EXCLUSIONS = [
    {**preset, "description": description}
    for preset, description in zip(PRESET_EXCLUSION_PATTERNS, _PRESET_DESCRIPTIONS, strict=True)
]
_PRESET_PATTERNS = frozenset(preset["pattern"] for preset in PRESET_EXCLUSION_PATTERNS)


class ExclusionsPage(PreferencesPageMixin):
    """
    Exclusions preference page for scan exclusion patterns.

    This class creates and manages the UI for scan exclusion patterns,
    including preset exclusions for common development directories and
    custom user-defined patterns.

    The page includes:
    - Preset exclusions (common patterns like node_modules, .git, etc.)
    - Custom exclusions with add/remove/toggle functionality
    - Auto-save for all exclusion changes

    Note: This class uses PreferencesPageMixin for shared utilities. Exclusion
    patterns are stored in ClamUI settings (not ClamAV config files) and are
    auto-saved when modified.
    """

    def __init__(self, settings_manager=None):
        """
        Initialize the ExclusionsPage.

        Args:
            settings_manager: Optional SettingsManager instance for storing exclusion patterns
        """
        self._settings_manager = settings_manager
        self._custom_exclusions_group = None
        self._custom_entry_row = None
        self._restoring_patterns: set[str] = set()

    def _canonical_exclusions(self) -> list:
        """Return an independent, canonical exclusion record list."""
        if self._settings_manager is None:
            return normalize_exclusion_patterns([])
        exclusions = self._settings_manager.get("exclusion_patterns", [])
        return normalize_exclusion_patterns(copy.deepcopy(exclusions))

    def _save_exclusions(self, exclusions: list) -> bool:
        """Persist exclusions and show a compatible error dialog on failure."""
        if self._settings_manager is None:
            return False
        if self._settings_manager.set("exclusion_patterns", exclusions):
            return True
        self._show_error_dialog(
            _("Unable to Save Exclusions"),
            _("Your exclusion changes could not be saved."),
        )
        return False

    def _ensure_canonical_exclusions(self) -> list:
        """Persist legacy exclusions in canonical form before building the UI."""
        if self._settings_manager is None:
            return normalize_exclusion_patterns([])

        original = self._settings_manager.get("exclusion_patterns", [])
        exclusions = normalize_exclusion_patterns(copy.deepcopy(original))
        if exclusions != original and not self._save_exclusions(exclusions):
            return exclusions
        return exclusions

    def create_page(self) -> Adw.PreferencesPage:
        """
        Create the Exclusions preference page.

        Returns:
            Configured Adw.PreferencesPage ready to be added to preferences window
        """
        page = Adw.PreferencesPage(
            title=_("Exclusions"),
            icon_name=resolve_icon_name("action-unavailable-symbolic"),
        )
        exclusions = self._ensure_canonical_exclusions()
        preset_states = {
            exclusion["pattern"]: exclusion.get("enabled", True)
            for exclusion in exclusions
            if isinstance(exclusion, dict) and exclusion.get("pattern") in _PRESET_PATTERNS
        }

        # Preset exclusions group
        preset_group = Adw.PreferencesGroup()
        preset_group.set_title(_("Preset Exclusions (Auto-Saved)"))
        preset_group.set_description(_("Common patterns to exclude. Auto-saved."))

        for preset in PRESET_EXCLUSIONS:
            # Create a row for each preset with folder icon.
            row = create_switch_row("folder-symbolic")
            row.set_title(_(preset["description"]))
            row.set_subtitle(GLib.markup_escape_text(preset["pattern"]))
            row.set_active(preset_states.get(preset["pattern"], preset["enabled"]))
            row.connect("notify::active", self._on_exclusion_toggled, preset["pattern"])
            preset_group.add(row)

        page.add(preset_group)

        # Custom exclusions group
        self._custom_exclusions_group = Adw.PreferencesGroup()
        self._custom_exclusions_group.set_title(_("Custom Exclusions (Auto-Saved)"))
        self._custom_exclusions_group.set_description(_("Your exclusion patterns. Auto-saved."))

        # Custom exclusion entry row
        self._custom_entry_row = create_entry_row("list-add-symbolic")
        self._custom_entry_row.set_title(_("Add Pattern (e.g., /path/to/exclude or *.tmp)"))
        self._custom_entry_row.set_show_apply_button(False)

        # Add button for custom exclusions
        add_button = Gtk.Button()
        add_button.set_label(_("Add"))
        add_button.set_valign(Gtk.Align.CENTER)
        add_button.set_tooltip_text(_("Add custom exclusion pattern"))
        add_button.connect("clicked", self._on_add_custom_exclusion)
        self._custom_entry_row.add_suffix(add_button)

        self._custom_exclusions_group.add(self._custom_entry_row)

        # Load and display existing custom exclusions
        self._load_custom_exclusions()

        page.add(self._custom_exclusions_group)

        return page

    def _load_custom_exclusions(self):
        """Load and display custom exclusions from settings."""
        if self._settings_manager is None:
            return

        exclusions = self._settings_manager.get("exclusion_patterns", [])
        if not isinstance(exclusions, list):
            return

        for exclusion in exclusions:
            if not isinstance(exclusion, dict):
                continue
            pattern = exclusion.get("pattern", "")
            if pattern and pattern not in _PRESET_PATTERNS:
                self._add_custom_exclusion_row(pattern, exclusion.get("enabled", True))

    def _add_custom_exclusion_row(self, pattern: str, enabled: bool = True):
        """
        Add a row for a custom exclusion pattern.

        Args:
            pattern: The exclusion pattern to add
            enabled: Whether the exclusion is enabled (default: True)
        """
        row = create_switch_row("folder-symbolic")
        row.set_title(GLib.markup_escape_text(pattern))
        row.set_active(enabled)

        # Connect switch to save enabled state
        row.connect("notify::active", self._on_exclusion_toggled, pattern)

        # Remove button
        remove_button = Gtk.Button()
        remove_button.set_icon_name(resolve_icon_name("user-trash-symbolic"))
        remove_button.set_valign(Gtk.Align.CENTER)
        remove_button.add_css_class("flat")
        remove_button.set_tooltip_text(_("Remove exclusion"))
        remove_button.connect("clicked", self._on_remove_custom_exclusion, row, pattern)
        row.add_suffix(remove_button)

        # Insert before the entry row (which is always last).
        if self._custom_exclusions_group is not None:
            self._custom_exclusions_group.add(row)

    def _on_exclusion_toggled(self, row, param_spec, pattern: str):
        """
        Handle exclusion toggle state change.

        Args:
            row: The SwitchRow that was toggled
            param_spec: Parameter specification (unused)
            pattern: The pattern that was toggled
        """
        if self._settings_manager is None or pattern in self._restoring_patterns:
            return

        exclusions = self._canonical_exclusions()
        matching_exclusion = next(
            (
                exclusion
                for exclusion in exclusions
                if isinstance(exclusion, dict) and exclusion.get("pattern") == pattern
            ),
            None,
        )
        if matching_exclusion is None:
            return

        previous_enabled = matching_exclusion.get("enabled", True)
        enabled = row.get_active()
        if previous_enabled == enabled:
            return

        matching_exclusion["enabled"] = enabled
        if self._save_exclusions(exclusions):
            return

        self._restoring_patterns.add(pattern)
        try:
            row.set_active(previous_enabled)
        finally:
            self._restoring_patterns.discard(pattern)

    def _on_add_custom_exclusion(self, button):
        """
        Handle adding a new custom exclusion.

        Args:
            button: The button that was clicked (unused)
        """
        if self._custom_entry_row is None or self._settings_manager is None:
            return

        pattern = self._custom_entry_row.get_text().strip()
        if not pattern:
            return

        exclusions = self._canonical_exclusions()
        if any(
            isinstance(exclusion, dict) and exclusion.get("pattern") == pattern
            for exclusion in exclusions
        ):
            return

        exclusions.append(
            {
                "pattern": pattern,
                "type": "file" if pattern.startswith("/") else "pattern",
                "enabled": True,
            }
        )
        if not self._save_exclusions(exclusions):
            return

        self._add_custom_exclusion_row(pattern, True)
        self._custom_entry_row.set_text("")

    def _on_remove_custom_exclusion(self, button, row, pattern: str):
        """
        Handle removing a custom exclusion.

        Args:
            button: The button that was clicked (unused)
            row: The row to remove
            pattern: The pattern to remove
        """
        if self._settings_manager is None or pattern in _PRESET_PATTERNS:
            return

        exclusions = self._canonical_exclusions()
        updated_exclusions = [
            exclusion
            for exclusion in exclusions
            if not isinstance(exclusion, dict) or exclusion.get("pattern") != pattern
        ]
        if updated_exclusions == exclusions or not self._save_exclusions(updated_exclusions):
            return
        if self._custom_exclusions_group is not None:
            self._custom_exclusions_group.remove(row)
