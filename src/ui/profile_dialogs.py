# ClamUI Profile Dialogs
"""
Dialog components for creating and editing scan profiles.
"""

import logging

import gi

logger = logging.getLogger(__name__)

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, GObject, Gtk

from ..core.i18n import _, ngettext
from .compat import (
    create_entry_row,
    create_toolbar_view,
    open_paths_dialog,
    save_path_dialog,
)
from .utils import add_row_icon, resolve_icon_name

if TYPE_CHECKING:
    from ..profiles.models import ScanProfile
    from ..profiles.profile_manager import ProfileManager


class ProfileDialog(Adw.Window):
    """
    A dialog for creating or editing scan profiles.

    Provides a form interface for configuring profile settings including:
    - Profile name and description
    - Target directories/files to scan
    - Exclusion paths and patterns

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        # Create new profile
        dialog = ProfileDialog(profile_manager=app.profile_manager)
        dialog.set_transient_for(parent_window)
        dialog.present()

        # Edit existing profile
        dialog = ProfileDialog(profile_manager=app.profile_manager, profile=existing_profile)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    # Maximum profile name length
    MAX_NAME_LENGTH = 50

    def __init__(
        self,
        profile_manager: "ProfileManager" = None,
        profile: "ScanProfile" = None,
        **kwargs,
    ):
        """
        Initialize the profile dialog.

        Args:
            profile_manager: The ProfileManager instance for saving profiles.
                             If None, changes won't be persisted.
            profile: Optional existing profile to edit. If None, creates a new profile.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._profile_manager = profile_manager
        self._profile = profile
        self._is_edit_mode = profile is not None

        # Target and exclusion lists
        self._targets: list[str] = []
        self._exclusion_paths: list[str] = []
        self._exclusion_patterns: list[str] = []

        # Callback for when a profile is saved
        self._on_profile_saved = None

        # Configure the dialog
        self._setup_dialog()

        # Set up the UI
        self._setup_ui()

        # Load existing profile data if editing
        if self._is_edit_mode:
            self._load_profile_data()

    def _setup_dialog(self):
        """Configure the dialog properties."""
        if self._is_edit_mode:
            self.set_title(_("Edit Profile"))
        else:
            self.set_title(_("New Profile"))

        self.set_default_size(500, 600)

        # Configure as modal dialog
        self.set_modal(True)
        self.set_deletable(True)

    def _setup_ui(self):
        """Set up the dialog UI layout."""
        # Create main container with toolbar view for header bar
        toolbar_view = create_toolbar_view()

        # Create header bar with save button
        header_bar = Adw.HeaderBar()

        # Cancel button
        cancel_button = Gtk.Button()
        cancel_button.set_label(_("Cancel"))
        cancel_button.connect("clicked", self._on_cancel_clicked)
        header_bar.pack_start(cancel_button)

        # Save button
        self._save_button = Gtk.Button()
        self._save_button.set_label(_("Save"))
        self._save_button.add_css_class("suggested-action")
        self._save_button.connect("clicked", self._on_save_clicked)
        header_bar.pack_end(self._save_button)

        toolbar_view.add_top_bar(header_bar)

        # Create scrolled window for content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Create preferences page using Adwaita patterns
        preferences_page = Adw.PreferencesPage()

        # Basic info group
        self._create_basic_info_group(preferences_page)

        # Targets group
        self._create_targets_group(preferences_page)

        # Exclusions group
        self._create_exclusions_group(preferences_page)

        scrolled.set_child(preferences_page)
        toolbar_view.set_content(scrolled)

        # Set the toolbar view as the dialog content
        self.set_content(toolbar_view)

    def _create_basic_info_group(self, preferences_page: Adw.PreferencesPage):
        """Create the basic profile info group."""
        basic_group = Adw.PreferencesGroup()
        basic_group.set_title(_("Profile Information"))
        basic_group.set_description(_("Basic profile settings"))

        # Profile name entry row
        # Note: Adw.EntryRow doesn't have set_max_length - validation is done in _on_name_changed
        self._name_row = create_entry_row()
        self._name_row.set_title(_("Name"))
        self._name_row.connect("changed", self._on_name_changed)
        basic_group.add(self._name_row)

        # Description entry row
        self._description_row = create_entry_row()
        self._description_row.set_title(_("Description"))
        basic_group.add(self._description_row)

        # Validation message (hidden by default)
        self._validation_label = Gtk.Label()
        self._validation_label.set_halign(Gtk.Align.START)
        self._validation_label.set_margin_start(12)
        self._validation_label.set_margin_top(6)
        self._validation_label.add_css_class("error")
        self._validation_label.set_visible(False)
        basic_group.add(self._validation_label)

        preferences_page.add(basic_group)

    def _create_targets_group(self, preferences_page: Adw.PreferencesPage):
        """Create the scan targets group."""
        self._targets_group = Adw.PreferencesGroup()
        self._targets_group.set_title(_("Scan Targets"))
        self._targets_group.set_description(_("Directories and files to scan"))

        # Add target buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)

        add_folder_btn = Gtk.Button()
        add_folder_btn.set_icon_name(resolve_icon_name("folder-new-symbolic"))
        add_folder_btn.set_tooltip_text(_("Add folder"))
        add_folder_btn.add_css_class("flat")
        add_folder_btn.connect("clicked", self._on_add_target_folder_clicked)
        button_box.append(add_folder_btn)

        add_file_btn = Gtk.Button()
        add_file_btn.set_icon_name(resolve_icon_name("document-new-symbolic"))
        add_file_btn.set_tooltip_text(_("Add file"))
        add_file_btn.add_css_class("flat")
        add_file_btn.connect("clicked", self._on_add_target_file_clicked)
        button_box.append(add_file_btn)

        self._targets_group.set_header_suffix(button_box)

        # Targets list box
        self._targets_listbox = Gtk.ListBox()
        self._targets_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._targets_listbox.add_css_class("boxed-list")

        # Placeholder for empty list
        self._targets_placeholder = Adw.ActionRow()
        self._targets_placeholder.set_title(_("No targets added"))
        self._targets_placeholder.set_subtitle(
            _("Click the folder or file button to add scan targets")
        )
        add_row_icon(self._targets_placeholder, "folder-symbolic")
        self._targets_placeholder.add_css_class("dim-label")
        self._targets_listbox.append(self._targets_placeholder)

        self._targets_group.add(self._targets_listbox)
        preferences_page.add(self._targets_group)

    def _create_exclusions_group(self, preferences_page: Adw.PreferencesPage):
        """Create the exclusions group."""
        self._exclusions_group = Adw.PreferencesGroup()
        self._exclusions_group.set_title(_("Exclusions"))
        self._exclusions_group.set_description(_("Paths and patterns to skip during scan"))

        # Add exclusion buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)

        add_path_btn = Gtk.Button()
        add_path_btn.set_icon_name(resolve_icon_name("folder-new-symbolic"))
        add_path_btn.set_tooltip_text(_("Add exclusion path"))
        add_path_btn.add_css_class("flat")
        add_path_btn.connect("clicked", self._on_add_exclusion_path_clicked)
        button_box.append(add_path_btn)

        add_pattern_btn = Gtk.Button()
        add_pattern_btn.set_icon_name(resolve_icon_name("edit-symbolic"))
        add_pattern_btn.set_tooltip_text(_("Add exclusion pattern"))
        add_pattern_btn.add_css_class("flat")
        add_pattern_btn.connect("clicked", self._on_add_exclusion_pattern_clicked)
        button_box.append(add_pattern_btn)

        self._exclusions_group.set_header_suffix(button_box)

        # Exclusions list box
        self._exclusions_listbox = Gtk.ListBox()
        self._exclusions_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._exclusions_listbox.add_css_class("boxed-list")

        # Placeholder for empty list
        self._exclusions_placeholder = Adw.ActionRow()
        self._exclusions_placeholder.set_title(_("No exclusions added"))
        self._exclusions_placeholder.set_subtitle(
            _("Add paths or patterns to exclude from scanning")
        )
        add_row_icon(self._exclusions_placeholder, "action-unavailable-symbolic")
        self._exclusions_placeholder.add_css_class("dim-label")
        self._exclusions_listbox.append(self._exclusions_placeholder)

        self._exclusions_group.add(self._exclusions_listbox)
        preferences_page.add(self._exclusions_group)

    def _load_profile_data(self):
        """Load existing profile data into the form."""
        if self._profile is None:
            return

        # Set basic info
        self._name_row.set_text(self._profile.name)
        self._description_row.set_text(self._profile.description or "")

        # Default profiles are recreated by name at startup, so renaming one would
        # orphan it and create a duplicate default. Mirror the delete-button
        # protection and lock the name field for defaults.
        if self._profile.is_default:
            self._name_row.set_sensitive(False)
            self._name_row.set_tooltip_text(_("Default profiles cannot be renamed"))

        # Load targets
        for target in self._profile.targets:
            self._add_target_to_list(target)

        # Load exclusions
        exclusions = self._profile.exclusions or {}
        for path in exclusions.get("paths", []):
            self._add_exclusion_path_to_list(path)
        for pattern in exclusions.get("patterns", []):
            self._add_exclusion_pattern_to_list(pattern)

    def _on_name_changed(self, entry_row):
        """Handle name entry changes for validation."""
        name = entry_row.get_text().strip()

        if not name:
            self._show_validation_error(_("Profile name is required"))
            self._save_button.set_sensitive(False)
        elif len(name) > self.MAX_NAME_LENGTH:
            self._show_validation_error(
                _("Name must be {max_length} characters or less").format(
                    max_length=self.MAX_NAME_LENGTH
                )
            )
            self._save_button.set_sensitive(False)
        else:
            self._hide_validation_error()
            self._save_button.set_sensitive(True)

    def _show_validation_error(self, message: str):
        """Show a validation error message."""
        self._validation_label.set_text(message)
        self._validation_label.set_visible(True)

    def _hide_validation_error(self):
        """Hide the validation error message."""
        self._validation_label.set_visible(False)

    def _on_add_target_folder_clicked(self, button):
        """Handle add target folder button click."""
        self._open_file_dialog(select_folder=True, multiple=True, callback=self._add_target_paths)

    def _on_add_target_file_clicked(self, button):
        """Handle add target file button click."""
        self._open_file_dialog(select_folder=False, multiple=True, callback=self._add_target_paths)

    def _on_add_exclusion_path_clicked(self, button):
        """Handle add exclusion path button click."""
        self._open_file_dialog(
            select_folder=True,
            multiple=True,
            callback=self._add_exclusion_paths,
        )

    def _on_add_exclusion_pattern_clicked(self, button):
        """Handle add exclusion pattern button click."""
        # Show pattern entry dialog
        dialog = PatternEntryDialog()
        dialog.connect("response", self._on_pattern_dialog_response)
        dialog.set_transient_for(self)
        dialog.present()

    def _on_pattern_dialog_response(self, dialog, response):
        """Handle pattern entry dialog response."""
        if response == "add":
            pattern = dialog.get_pattern()
            if pattern and pattern not in self._exclusion_patterns:
                self._add_exclusion_pattern_to_list(pattern)

    def _open_file_dialog(self, select_folder: bool, multiple: bool, callback):
        """
        Open a file/folder selection dialog with optional multi-selection.

        Args:
            select_folder: True to select folders, False for files
            multiple: True to allow selecting multiple items
            callback: Callback function that receives a list of selected paths
        """
        window = self.get_root()
        if window is None:
            return

        if select_folder:
            title = _("Select Folders") if multiple else _("Select Folder")
        else:
            title = _("Select Files") if multiple else _("Select File")

        open_paths_dialog(
            window,
            title=title,
            on_selected=callback,
            select_folders=select_folder,
            multiple=multiple,
        )

    def _add_target_paths(self, paths: list[str]) -> None:
        """Add selected target paths to the dialog."""
        for path in paths:
            if path and path not in self._targets:
                self._add_target_to_list(path)

    def _add_exclusion_paths(self, paths: list[str]) -> None:
        """Add selected exclusion paths to the dialog."""
        for path in paths:
            if path and path not in self._exclusion_paths:
                self._add_exclusion_path_to_list(path)

    def _on_target_files_selected(self, dialog, result):
        """Handle multiple file selection for targets."""
        try:
            files = dialog.open_multiple_finish(result)
            if files is None:
                return
            self._process_selected_targets(files)
        except GLib.Error:
            return  # User cancelled

    def _on_target_folders_selected(self, dialog, result):
        """Handle multiple folder selection for targets."""
        try:
            files = dialog.select_multiple_folders_finish(result)
            if files is None:
                return
            self._process_selected_targets(files)
        except GLib.Error:
            return  # User cancelled

    def _process_selected_targets(self, files):
        """Process selected files/folders and add to target list."""
        for i in range(files.get_n_items()):
            file = files.get_item(i)
            if file:
                path = file.get_path()
                if path and path not in self._targets:
                    self._add_target_to_list(path)

    def _on_exclusion_paths_selected(self, dialog, result):
        """Handle multi-select exclusion path selection result."""
        try:
            files = dialog.select_multiple_folders_finish(result)
            if files is None:
                return

            # Iterate through the ListModel of Gio.File objects
            # Duplicate detection is handled in _add_exclusion_path_to_list
            for i in range(files.get_n_items()):
                file = files.get_item(i)
                if file:
                    path = file.get_path()
                    if path and path not in self._exclusion_paths:
                        self._add_exclusion_path_to_list(path)

        except GLib.Error:
            return  # User cancelled

    def _add_target_to_list(self, path: str):
        """Add a target path to the list UI."""
        # Remove placeholder if this is the first target
        if not self._targets:
            self._targets_listbox.remove(self._targets_placeholder)

        self._targets.append(path)

        # Create target row
        row = self._create_path_row(
            path=path,
            icon_name="folder-symbolic",
            on_remove=lambda: self._remove_target(path),
        )
        self._targets_listbox.append(row)

        # Update header count
        self._update_targets_header()

    def _add_exclusion_path_to_list(self, path: str):
        """Add an exclusion path to the list UI."""
        # Remove placeholder if this is the first exclusion
        if not self._exclusion_paths and not self._exclusion_patterns:
            self._exclusions_listbox.remove(self._exclusions_placeholder)

        self._exclusion_paths.append(path)

        # Create exclusion row
        row = self._create_path_row(
            path=path,
            icon_name="folder-symbolic",
            on_remove=lambda: self._remove_exclusion_path(path),
            subtitle=_("Path"),
        )
        self._exclusions_listbox.append(row)

        # Update header count
        self._update_exclusions_header()

    def _add_exclusion_pattern_to_list(self, pattern: str):
        """Add an exclusion pattern to the list UI."""
        # Remove placeholder if this is the first exclusion
        if not self._exclusion_paths and not self._exclusion_patterns:
            self._exclusions_listbox.remove(self._exclusions_placeholder)

        self._exclusion_patterns.append(pattern)

        # Create pattern row
        row = self._create_path_row(
            path=pattern,
            icon_name="edit-symbolic",
            on_remove=lambda: self._remove_exclusion_pattern(pattern),
            subtitle=_("Pattern"),
        )
        self._exclusions_listbox.append(row)

        # Update header count
        self._update_exclusions_header()

    def _create_path_row(
        self, path: str, icon_name: str, on_remove, subtitle: str = None
    ) -> Adw.ActionRow:
        """
        Create a row for displaying a path with remove button.

        Args:
            path: The path or pattern to display
            icon_name: Icon name to show
            on_remove: Callback when remove is clicked
            subtitle: Optional subtitle text

        Returns:
            Configured Adw.ActionRow
        """
        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(path))
        if subtitle:
            row.set_subtitle(GLib.markup_escape_text(subtitle))
        add_row_icon(row, icon_name)

        # Remove button
        remove_btn = Gtk.Button()
        remove_btn.set_icon_name(resolve_icon_name("user-trash-symbolic"))
        remove_btn.set_tooltip_text(_("Remove"))
        remove_btn.add_css_class("flat")
        remove_btn.add_css_class("error")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.connect("clicked", lambda btn: self._handle_remove(row, on_remove))

        row.add_suffix(remove_btn)
        return row

    def _handle_remove(self, row: Adw.ActionRow, on_remove):
        """Handle remove button click."""
        # Get the parent listbox
        parent = row.get_parent()
        if parent:
            parent.remove(row)
        on_remove()

        # Restore placeholder if lists are empty
        self._update_placeholders()

        # Update headers to reflect new counts
        self._update_targets_header()
        self._update_exclusions_header()

    def _remove_target(self, path: str):
        """Remove a target path."""
        if path in self._targets:
            self._targets.remove(path)

    def _remove_exclusion_path(self, path: str):
        """Remove an exclusion path."""
        if path in self._exclusion_paths:
            self._exclusion_paths.remove(path)

    def _remove_exclusion_pattern(self, pattern: str):
        """Remove an exclusion pattern."""
        if pattern in self._exclusion_patterns:
            self._exclusion_patterns.remove(pattern)

    def _update_placeholders(self):
        """Update placeholder visibility for empty lists."""
        # Targets placeholder
        if not self._targets:
            # Check if placeholder already exists
            first_row = self._targets_listbox.get_row_at_index(0)
            if first_row is None:
                self._targets_listbox.append(self._targets_placeholder)

        # Exclusions placeholder
        if not self._exclusion_paths and not self._exclusion_patterns:
            first_row = self._exclusions_listbox.get_row_at_index(0)
            if first_row is None:
                self._exclusions_listbox.append(self._exclusions_placeholder)

    def _update_targets_header(self):
        """Update the targets group header to show item count."""
        count = len(self._targets)
        if count > 0:
            self._targets_group.set_title(_("Scan Targets ({count})").format(count=count))
        else:
            self._targets_group.set_title(_("Scan Targets"))

    def _update_exclusions_header(self):
        """Update the exclusions group header to show item count."""
        count = len(self._exclusion_paths) + len(self._exclusion_patterns)
        if count > 0:
            self._exclusions_group.set_title(_("Exclusions ({count})").format(count=count))
        else:
            self._exclusions_group.set_title(_("Exclusions"))

    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self.close()

    def _on_save_clicked(self, button):
        """Handle save button click."""
        name = self._name_row.get_text().strip()
        description = self._description_row.get_text().strip()

        # Validate name
        if not name:
            self._show_validation_error(_("Profile name is required"))
            return

        # Build exclusions dictionary
        exclusions = {}
        if self._exclusion_paths:
            exclusions["paths"] = self._exclusion_paths.copy()
        if self._exclusion_patterns:
            exclusions["patterns"] = self._exclusion_patterns.copy()

        # Save profile
        if self._profile_manager is not None:
            try:
                if self._is_edit_mode and self._profile:
                    # Update existing profile
                    self._profile_manager.update_profile(
                        self._profile.id,
                        name=name,
                        description=description,
                        targets=self._targets.copy(),
                        exclusions=exclusions,
                    )
                    saved_profile = self._profile_manager.get_profile(self._profile.id)
                else:
                    # Create new profile
                    saved_profile = self._profile_manager.create_profile(
                        name=name,
                        targets=self._targets.copy(),
                        exclusions=exclusions,
                        description=description,
                    )

                # Notify callback
                if self._on_profile_saved:
                    self._on_profile_saved(saved_profile)

                self.close()

            except ValueError as e:
                self._show_validation_error(str(e))
        else:
            self.close()

    def set_on_profile_saved(self, callback):
        """
        Set callback for when a profile is saved.

        Args:
            callback: Callable that receives the saved ScanProfile
        """
        self._on_profile_saved = callback

    def get_profile_data(self) -> dict:
        """
        Get the current profile data from the form.

        Returns:
            Dictionary with profile data
        """
        exclusions = {}
        if self._exclusion_paths:
            exclusions["paths"] = self._exclusion_paths.copy()
        if self._exclusion_patterns:
            exclusions["patterns"] = self._exclusion_patterns.copy()

        return {
            "name": self._name_row.get_text().strip(),
            "description": self._description_row.get_text().strip(),
            "targets": self._targets.copy(),
            "exclusions": exclusions,
        }


class PatternEntryDialog(Adw.Window):
    """
    A simple dialog for entering exclusion patterns.

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        dialog = PatternEntryDialog()
        dialog.connect("response", on_response)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    __gsignals__ = {"response": (GObject.SignalFlags.RUN_LAST, None, (str,))}

    def __init__(self, **kwargs):
        """Initialize the pattern entry dialog."""
        super().__init__(**kwargs)

        self.set_title(_("Add Exclusion Pattern"))
        self.set_default_size(400, 200)

        # Configure as modal dialog
        self.set_modal(True)
        self.set_deletable(True)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        # Create main container
        toolbar_view = create_toolbar_view()

        # Header bar
        header_bar = Adw.HeaderBar()

        cancel_button = Gtk.Button()
        cancel_button.set_label(_("Cancel"))
        cancel_button.connect("clicked", self._on_cancel_clicked)
        header_bar.pack_start(cancel_button)

        add_button = Gtk.Button()
        add_button.set_label(_("Add"))
        add_button.add_css_class("suggested-action")
        add_button.connect("clicked", self._on_add_clicked)
        self._add_button = add_button
        header_bar.pack_end(add_button)

        toolbar_view.add_top_bar(header_bar)

        # Content
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(24)
        content_box.set_margin_bottom(24)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)

        # Pattern entry group
        pattern_group = Adw.PreferencesGroup()
        pattern_group.set_description(
            _("Enter a glob pattern to exclude (e.g., *.tmp, .git/*, cache/*)")
        )

        self._pattern_row = create_entry_row()
        self._pattern_row.set_title(_("Pattern"))
        self._pattern_row.connect("changed", self._on_pattern_changed)
        self._pattern_row.connect("entry-activated", lambda r: self._on_add_clicked(None))
        pattern_group.add(self._pattern_row)

        content_box.append(pattern_group)

        toolbar_view.set_content(content_box)
        self.set_content(toolbar_view)

    def _on_pattern_changed(self, entry_row):
        """Handle pattern entry changes."""
        pattern = entry_row.get_text().strip()
        self._add_button.set_sensitive(bool(pattern))

    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self.emit("response", "cancel")
        self.close()

    def _on_add_clicked(self, button):
        """Handle add button click."""
        pattern = self._pattern_row.get_text().strip()
        if pattern:
            self.emit("response", "add")
            self.close()

    def get_pattern(self) -> str:
        """Get the entered pattern."""
        return self._pattern_row.get_text().strip()


class DeleteProfileDialog(Adw.Window):
    """
    Confirmation dialog for deleting a profile.

    Uses Adw.Window instead of Adw.AlertDialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        def on_response(dialog, response):
            if response == "delete":
                # Delete the profile
                pass

        dialog = DeleteProfileDialog(profile_name="Quick Scan")
        dialog.connect("response", on_response)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    __gsignals__ = {"response": (GObject.SignalFlags.RUN_LAST, None, (str,))}

    def __init__(self, profile_name: str, **kwargs):
        """
        Initialize the delete confirmation dialog.

        Args:
            profile_name: Name of the profile to delete
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._profile_name = profile_name
        self._heading = _("Delete Profile?")
        self._body = (
            _('Are you sure you want to delete the profile "{profile_name}"?').format(
                profile_name=profile_name
            )
            + "\n\n"
            + _("This action cannot be undone.")
        )

        self.set_title(self._heading)
        self.set_default_size(400, -1)  # Natural height

        # Configure as modal dialog
        self.set_modal(True)
        self.set_deletable(True)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        # Create main container with toolbar view for header bar
        toolbar_view = create_toolbar_view()

        # Create header bar
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Main content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(24)

        # Warning icon
        warning_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-warning-symbolic"))
        warning_icon.set_pixel_size(48)
        warning_icon.add_css_class("warning")
        warning_icon.set_halign(Gtk.Align.CENTER)
        content_box.append(warning_icon)

        # Body text
        body_label = Gtk.Label()
        body_label.set_text(self._body)
        body_label.set_wrap(True)
        body_label.set_xalign(0.5)
        body_label.set_justify(Gtk.Justification.CENTER)
        content_box.append(body_label)

        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(12)

        # Cancel button
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(cancel_button)

        # Delete button
        delete_button = Gtk.Button(label=_("Delete"))
        delete_button.add_css_class("destructive-action")
        delete_button.connect("clicked", self._on_delete_clicked)
        button_box.append(delete_button)

        content_box.append(button_box)

        toolbar_view.set_content(content_box)
        self.set_content(toolbar_view)

    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self.emit("response", "cancel")
        self.close()

    def _on_delete_clicked(self, button):
        """Handle delete button click."""
        self.emit("response", "delete")
        self.close()

    def get_heading(self) -> str:
        """Get the dialog heading/title (for test compatibility)."""
        return self._heading

    def get_body(self) -> str:
        """Get the dialog body text (for test compatibility)."""
        return self._body


class RestoreDefaultsDialog(Adw.Window):
    """
    Confirmation dialog for restoring default profiles.

    Uses Adw.Window instead of Adw.AlertDialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        def on_response(dialog, response):
            if response == "restore":
                # Restore default profiles
                pass

        dialog = RestoreDefaultsDialog()
        dialog.connect("response", on_response)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    __gsignals__ = {"response": (GObject.SignalFlags.RUN_LAST, None, (str,))}

    def __init__(self, **kwargs):
        """
        Initialize the restore defaults confirmation dialog.

        Args:
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._heading = _("Restore Default Profiles?")
        self._body = (
            _(
                "This will reset Quick Scan, Full Scan, and Home Folder profiles "
                "to their original settings. Any changes you made to these profiles "
                "will be lost."
            )
            + "\n\n"
            + _("Your custom profiles will not be affected.")
        )

        self.set_title(self._heading)
        self.set_default_size(400, -1)  # Natural height

        # Configure as modal dialog
        self.set_modal(True)
        self.set_deletable(True)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        # Create main container with toolbar view for header bar
        toolbar_view = create_toolbar_view()

        # Create header bar
        header_bar = Adw.HeaderBar()
        toolbar_view.add_top_bar(header_bar)

        # Main content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(24)

        # Info icon (not warning since this is restorative, not destructive)
        info_icon = Gtk.Image.new_from_icon_name(resolve_icon_name("dialog-information-symbolic"))
        info_icon.set_pixel_size(48)
        info_icon.add_css_class("accent")
        info_icon.set_halign(Gtk.Align.CENTER)
        content_box.append(info_icon)

        # Body text
        body_label = Gtk.Label()
        body_label.set_text(self._body)
        body_label.set_wrap(True)
        body_label.set_xalign(0.5)
        body_label.set_justify(Gtk.Justification.CENTER)
        content_box.append(body_label)

        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(12)

        # Cancel button
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(cancel_button)

        # Restore button (suggested-action since it's restorative, not destructive)
        restore_button = Gtk.Button(label=_("Restore"))
        restore_button.add_css_class("suggested-action")
        restore_button.connect("clicked", self._on_restore_clicked)
        button_box.append(restore_button)

        content_box.append(button_box)

        toolbar_view.set_content(content_box)
        self.set_content(toolbar_view)

    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        self.emit("response", "cancel")
        self.close()

    def _on_restore_clicked(self, button):
        """Handle restore button click."""
        self.emit("response", "restore")
        self.close()

    def get_heading(self) -> str:
        """Get the dialog heading/title (for test compatibility)."""
        return self._heading

    def get_body(self) -> str:
        """Get the dialog body text (for test compatibility)."""
        return self._body


class ProfileListDialog(Adw.Window):
    """
    A dialog for managing scan profiles.

    Displays a list of all profiles with options to create, edit, and delete profiles.

    Uses Adw.Window instead of Adw.Dialog for compatibility with
    libadwaita < 1.5 (Ubuntu 22.04, Pop!_OS 22.04).

    Usage:
        dialog = ProfileListDialog(profile_manager=app.profile_manager)
        dialog.set_transient_for(parent_window)
        dialog.present()
    """

    def __init__(self, profile_manager: "ProfileManager" = None, **kwargs):
        """
        Initialize the profile list dialog.

        Args:
            profile_manager: The ProfileManager instance for profile operations.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._profile_manager = profile_manager

        # Callback for when a profile is selected for use
        self._on_profile_selected = None

        # Configure the dialog
        self._setup_dialog()

        # Set up the UI
        self._setup_ui()

        # Load profiles
        self._refresh_profile_list()

    def _setup_dialog(self):
        """Configure the dialog properties."""
        self.set_title(_("Manage Profiles"))
        self.set_default_size(500, 500)

        # Configure as modal dialog
        self.set_modal(True)
        self.set_deletable(True)

    def _setup_ui(self):
        """Set up the dialog UI layout."""
        # Create main container with toolbar view for header bar
        toolbar_view = create_toolbar_view()

        # Create header bar with new profile button
        header_bar = Adw.HeaderBar()

        # Restore defaults button (left side)
        restore_button = Gtk.Button()
        restore_button.set_icon_name(resolve_icon_name("view-refresh-symbolic"))
        restore_button.set_tooltip_text(_("Restore default profiles"))
        restore_button.connect("clicked", self._on_restore_defaults_clicked)
        header_bar.pack_start(restore_button)

        # Import profile button
        import_button = Gtk.Button()
        import_button.set_icon_name(resolve_icon_name("document-open-symbolic"))
        import_button.set_tooltip_text(_("Import profile from file"))
        import_button.connect("clicked", self._on_import_clicked)
        header_bar.pack_end(import_button)

        # New profile button
        new_profile_button = Gtk.Button()
        new_profile_button.set_icon_name(resolve_icon_name("list-add-symbolic"))
        new_profile_button.set_tooltip_text(_("Create new profile"))
        new_profile_button.add_css_class("suggested-action")
        new_profile_button.connect("clicked", self._on_new_profile_clicked)
        header_bar.pack_end(new_profile_button)

        toolbar_view.add_top_bar(header_bar)

        # Create scrolled window for content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Create preferences page using Adwaita patterns
        preferences_page = Adw.PreferencesPage()

        # Profiles group
        self._profiles_group = Adw.PreferencesGroup()
        self._profiles_group.set_title(_("Scan Profiles"))
        self._profiles_group.set_description(_("Select a profile to edit or use for scanning"))

        # Profiles list box
        self._profiles_listbox = Gtk.ListBox()
        self._profiles_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._profiles_listbox.add_css_class("boxed-list")

        # Placeholder for empty list
        self._profiles_placeholder = Adw.ActionRow()
        self._profiles_placeholder.set_title(_("No profiles available"))
        self._profiles_placeholder.set_subtitle(_("Click the + button to create a new profile"))
        add_row_icon(self._profiles_placeholder, "document-new-symbolic")
        self._profiles_placeholder.add_css_class("dim-label")

        self._profiles_group.add(self._profiles_listbox)
        preferences_page.add(self._profiles_group)

        scrolled.set_child(preferences_page)
        toolbar_view.set_content(scrolled)

        # Set the toolbar view as the dialog content
        self.set_content(toolbar_view)

    def _refresh_profile_list(self):
        """Refresh the profile list from the profile manager."""
        # Clear existing rows - use remove_all() for O(1) instead of O(n²) loop removal
        self._profiles_listbox.remove_all()

        # Get profiles from manager
        if self._profile_manager is None:
            self._profiles_listbox.append(self._profiles_placeholder)
            return

        profiles = self._profile_manager.list_profiles()

        if not profiles:
            self._profiles_listbox.append(self._profiles_placeholder)
            return

        # Add profile rows
        for profile in profiles:
            row = self._create_profile_row(profile)
            self._profiles_listbox.append(row)

    def _create_profile_row(self, profile: "ScanProfile") -> Adw.ActionRow:
        """
        Create a row for displaying a profile with action buttons.

        Args:
            profile: The ScanProfile to display

        Returns:
            Configured Adw.ActionRow
        """
        row = Adw.ActionRow()
        row.set_title(GLib.markup_escape_text(profile.name))

        # Build subtitle with profile details
        subtitle_parts = []
        if profile.description:
            subtitle_parts.append(profile.description)
        target_count = len(profile.targets) if profile.targets else 0
        if target_count > 0:
            subtitle_parts.append(
                ngettext(
                    "{count} target",
                    "{count} targets",
                    target_count,
                ).format(count=target_count)
            )
        if profile.is_default:
            subtitle_parts.append(_("Default profile"))

        if subtitle_parts:
            row.set_subtitle(GLib.markup_escape_text(" \u2022 ".join(subtitle_parts)))

        # Set icon based on profile type
        if profile.is_default:
            add_row_icon(row, "emblem-default-symbolic")
        else:
            add_row_icon(row, "document-properties-symbolic")

        # Action buttons container
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_valign(Gtk.Align.CENTER)

        # Use profile button
        use_button = Gtk.Button()
        use_button.set_icon_name(resolve_icon_name("media-playback-start-symbolic"))
        use_button.set_tooltip_text(_("Use this profile"))
        use_button.add_css_class("flat")
        use_button.add_css_class("success")
        use_button.connect("clicked", lambda btn, p=profile: self._on_use_profile_clicked(p))
        button_box.append(use_button)

        # Edit button
        edit_button = Gtk.Button()
        edit_button.set_icon_name(resolve_icon_name("document-edit-symbolic"))
        edit_button.set_tooltip_text(_("Edit profile"))
        edit_button.add_css_class("flat")
        edit_button.connect("clicked", lambda btn, p=profile: self._on_edit_profile_clicked(p))
        button_box.append(edit_button)

        # Delete button (disabled for default profiles)
        delete_button = Gtk.Button()
        delete_button.set_icon_name(resolve_icon_name("user-trash-symbolic"))
        delete_button.set_tooltip_text(_("Delete profile"))
        delete_button.add_css_class("flat")
        if profile.is_default:
            delete_button.set_sensitive(False)
            delete_button.set_tooltip_text(_("Cannot delete default profile"))
        else:
            delete_button.add_css_class("error")
            delete_button.connect(
                "clicked", lambda btn, p=profile: self._on_delete_profile_clicked(p)
            )
        button_box.append(delete_button)

        # Export button
        export_button = Gtk.Button()
        export_button.set_icon_name(resolve_icon_name("document-save-symbolic"))
        export_button.set_tooltip_text(_("Export profile"))
        export_button.add_css_class("flat")
        export_button.connect("clicked", lambda btn, p=profile: self._on_export_profile_clicked(p))
        button_box.append(export_button)

        row.add_suffix(button_box)
        row.set_activatable(True)
        row.connect("activated", lambda r, p=profile: self._on_use_profile_clicked(p))

        return row

    def _on_import_clicked(self, button):
        """Handle import button click."""
        self.import_profile()

    def _on_restore_defaults_clicked(self, button):
        """Handle restore defaults button click."""
        dialog = RestoreDefaultsDialog()
        dialog.connect("response", self._on_restore_response)
        dialog.set_transient_for(self)
        dialog.present()

    def _on_restore_response(self, dialog, response: str):
        """
        Handle restore defaults dialog response.

        Args:
            dialog: The dialog instance
            response: The dialog response ("restore" or "cancel")
        """
        if response == "restore" and self._profile_manager is not None:
            self._profile_manager.restore_default_profiles()
            self._refresh_profile_list()

    def _on_new_profile_clicked(self, button):
        """Handle new profile button click."""
        dialog = ProfileDialog(profile_manager=self._profile_manager)
        dialog.set_on_profile_saved(self._on_profile_saved)
        dialog.set_transient_for(self)
        dialog.present()

    def _on_edit_profile_clicked(self, profile: "ScanProfile"):
        """
        Handle edit profile button click.

        Args:
            profile: The profile to edit
        """
        dialog = ProfileDialog(profile_manager=self._profile_manager, profile=profile)
        dialog.set_on_profile_saved(self._on_profile_saved)
        dialog.set_transient_for(self)
        dialog.present()

    def _on_delete_profile_clicked(self, profile: "ScanProfile"):
        """
        Handle delete profile button click.

        Args:
            profile: The profile to delete
        """
        dialog = DeleteProfileDialog(profile_name=profile.name)
        dialog.connect("response", lambda d, r, p=profile: self._on_delete_response(r, p))
        dialog.set_transient_for(self)
        dialog.present()

    def _on_delete_response(self, response: str, profile: "ScanProfile"):
        """
        Handle delete confirmation dialog response.

        Args:
            response: The dialog response ("delete" or "cancel")
            profile: The profile to delete
        """
        if response == "delete" and self._profile_manager is not None:
            try:
                self._profile_manager.delete_profile(profile.id)
                self._refresh_profile_list()
            except ValueError:
                # Cannot delete default profile - should not happen since button is disabled
                logger.debug("Attempted to delete a protected default profile", exc_info=True)

    def _on_use_profile_clicked(self, profile: "ScanProfile"):
        """
        Handle use profile button click.

        Args:
            profile: The profile to use
        """
        if self._on_profile_selected:
            self._on_profile_selected(profile)
        self.close()

    def _on_export_profile_clicked(self, profile: "ScanProfile"):
        """
        Handle export profile button click.

        Args:
            profile: The profile to export
        """
        if self._profile_manager is None:
            return

        # Generate default filename from profile name
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in profile.name)
        initial_name = f"{safe_name}.json"

        # Set up file filter for JSON files
        json_filter = Gtk.FileFilter()
        json_filter.set_name(_("JSON Files"))
        json_filter.add_mime_type("application/json")
        json_filter.add_pattern("*.json")
        save_path_dialog(
            self.get_root(),
            title=_("Export Profile"),
            on_selected=lambda path: self._export_profile_to_path(profile.id, path),
            initial_name=initial_name,
            filters=[json_filter],
        )

    def _export_profile_to_path(self, profile_id: str, file_path: str) -> None:
        """Export the selected profile to disk."""
        if self._profile_manager is None or not file_path:
            return

        if not file_path.endswith(".json"):
            file_path += ".json"

        try:
            from pathlib import Path

            self._profile_manager.export_profile(profile_id, Path(file_path))
        except (ValueError, OSError) as e:
            logger.warning("Failed to export profile: %s", e)

    def _on_profile_saved(self, profile: "ScanProfile"):
        """
        Handle profile saved callback from ProfileDialog.

        Args:
            profile: The saved profile
        """
        self._refresh_profile_list()

    def set_on_profile_selected(self, callback):
        """
        Set callback for when a profile is selected for use.

        Args:
            callback: Callable that receives the selected ScanProfile
        """
        self._on_profile_selected = callback

    def import_profile(self):
        """Open file dialog to import a profile."""
        if self._profile_manager is None:
            return

        # Set up file filter for JSON files
        json_filter = Gtk.FileFilter()
        json_filter.set_name(_("JSON Files"))
        json_filter.add_mime_type("application/json")
        json_filter.add_pattern("*.json")
        open_paths_dialog(
            self.get_root(),
            title=_("Import Profile"),
            on_selected=lambda paths: self._import_profile_from_path(paths[0]),
            filters=[json_filter],
        )

    def _import_profile_from_path(self, file_path: str) -> None:
        """Import a profile from disk and refresh the list."""
        if self._profile_manager is None or not file_path:
            return

        try:
            from pathlib import Path

            self._profile_manager.import_profile(Path(file_path))
            self._refresh_profile_list()
        except (ValueError, OSError) as e:
            logger.warning("Failed to import profile: %s", e)
