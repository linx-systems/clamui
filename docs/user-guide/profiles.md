# Scan Profiles

[← Back to User Guide](../USER_GUIDE.md)

---

## Scan Profiles

Scan profiles are pre-configured scan settings that save you time and make scanning more convenient. Instead of manually
selecting folders and configuring options every time you scan, profiles let you save your preferred scanning setups and
launch them with a single click.

### What are Scan Profiles?

A **scan profile** is a saved configuration that contains:

- **Target directories/files**: What to scan (e.g., Downloads, Home folder, entire system)
- **Exclusion rules**: What to skip (specific paths or file patterns)
- **Profile metadata**: Name, description, creation date

**Why use profiles?**

✅ **Save time**: Launch common scans instantly without browsing for folders
✅ **Consistency**: Ensure you scan the same locations every time
✅ **Convenience**: Create specialized profiles for different purposes
✅ **Efficiency**: Skip irrelevant files automatically with exclusions

**Common use cases**:

- Quick check of downloaded files
- Weekly scan of your home directory
- Full system scan with common exclusions (system folders, caches)
- Scan external USB drives with specific exclusion patterns

### Using Default Profiles

ClamUI includes three built-in profiles that cover the most common scanning needs. These profiles are created
automatically when you first launch ClamUI.

#### Quick Scan

**Purpose**: Fast scan of commonly infected locations

**What it scans**:

- `~/Downloads` - Your Downloads folder

**Exclusions**: None

**When to use**:

- After downloading files from the internet
- Quick daily security check
- Testing suspicious downloads
- When you want fast results (typically 10-30 seconds)

**How to use**:

1. Click the **Scan Profile** dropdown in the scan view
2. Select **Quick Scan**
3. Click the **Scan** button
4. Wait for results

💡 **Tip**: Quick Scan is perfect for beginners or as a daily habit. It focuses on your Downloads folder where most
threats enter your system.

#### Full Scan

**Purpose**: Comprehensive system-wide security check

**What it scans**:

- `/` - The entire root filesystem (all directories and files)

**Exclusions**:
The following system directories are excluded for performance and to avoid false positives:

- `/proc` - Kernel process information (virtual filesystem)
- `/sys` - Kernel system information (virtual filesystem)
- `/dev` - Device files (not regular files)
- `/run` - Runtime data (temporary)
- `/tmp` - Temporary files
- `/var/cache` - Application caches
- `/var/tmp` - More temporary files

**When to use**:

- Monthly or quarterly comprehensive scan
- After suspecting a system compromise
- Before important backups
- When you have time for a thorough check (30-90+ minutes)

**How to use**:

1. Ensure you have time available (this can take 30-90+ minutes)
2. Select **Full Scan** from the Scan Profile dropdown
3. Click **Scan**
4. Let it run in the background

⚠️ **Important**: Full Scan examines hundreds of thousands of files and can take a significant amount of time. It's best
run when you don't need your computer for other tasks, or schedule it to run automatically (
see [Scheduled Scans](scheduling.md)).

#### Home Folder Scan

**Purpose**: Balanced scan of your personal files

**What it scans**:

- `~` - Your entire home directory (includes Documents, Pictures, Videos, Downloads, Desktop, etc.)

**Exclusions**:

- `~/.cache` - Application cache files (typically safe)
- `~/.local/share/Trash` - Your trash folder (files you've deleted)

**When to use**:

- Weekly personal files security check
- Before backing up your home directory
- After installing new software
- When you want thorough coverage without scanning system files (10-30 minutes)

**How to use**:

1. Select **Home Folder** from the Scan Profile dropdown
2. Click **Scan**
3. Review results when complete

💡 **Tip**: Home Folder is a good middle ground between Quick Scan (fast but limited) and Full Scan (thorough but slow).
It covers all your personal data while excluding common cache locations.

### Creating Custom Profiles

While the default profiles cover most needs, you can create custom profiles for specific purposes like scanning USB
drives, project folders, or specialized directories.

#### How to Create a Profile

**Step-by-Step**:

1. **Open the Profile Manager**:
    - In the **Scan** view, click the **Manage profiles** button (the gear / settings icon) next to the **Scan Profile** dropdown
    - The **Manage Profiles** window opens

2. **Create a New Profile**:
    - Click the **+** button (tooltip: "Create new profile") in the window's header bar
    - The **New Profile** dialog appears

3. **Fill in Basic Information**:
    - **Name** (required): Give your profile a descriptive name
        - Maximum 50 characters
        - Must be unique (no duplicate names)
        - Examples: "USB Drives", "Project Files", "Work Documents"
    - **Description** (optional): Explain what this profile is for
        - Helpful reminder of the profile's purpose
        - Example: "Scans all USB drives connected to /media"

4. **Add Scan Targets**:
    - In the **Scan Targets** section, click the **Add folder** button (folder icon) to pick a directory, or the **Add file** button (document icon) to pick a single file
    - A file/folder chooser opens; select the location to scan
    - Repeat to add multiple locations
    - **Tips**:
        - Use `~` to represent your home directory (e.g., `~/Projects`)
        - You can add both files and folders
        - Each target is scanned recursively (includes all subfolders)

5. **Add Exclusions** (optional):
    - **By Path**: Exclude specific directories
        - Click **Add Exclusion Path**
        - Browse to or enter the path to exclude
        - Example: `~/Projects/node_modules` (skip npm packages)
    - **By Pattern**: Exclude files matching patterns
        - Click **Add Exclusion Pattern**
        - Enter a glob pattern (e.g., `*.tmp`, `*.log`)
        - Example: `*.iso` (skip large disk images)

6. **Save the Profile**:
    - Click the **Save** button
    - Your new profile appears in the Scan Profile dropdown immediately

**Example Custom Profiles**:

**USB Drive Scanner**:

- Name: "External Drives"
- Targets: `/media`, `/mnt`
- Exclusions: `*.mp4`, `*.mkv` (skip video files for speed)
- Purpose: Quickly scan USB sticks and external hard drives

**Development Projects**:

- Name: "Code Projects"
- Targets: `~/Projects`, `~/workspace`
- Exclusions: `*/node_modules`, `*/.git`, `*/build`, `*/dist`
- Purpose: Scan source code while skipping dependencies and build artifacts

**Important Documents**:

- Name: "Documents Only"
- Targets: `~/Documents`, `~/Desktop`
- Exclusions: None
- Purpose: Focused scan of your important work files

#### Profile Creation Tips

💡 **Best Practices**:

- **Descriptive names**: Use clear names that explain what the profile scans
- **Start simple**: Create basic profiles first, add complexity as needed
- **Test your profile**: Run it once to ensure it scans what you expect
- **Exclude wisely**: Skip large files/folders that are unlikely to contain threats
- **Use ~ for home paths**: Makes profiles portable across systems

⚠️ **Common Mistakes to Avoid**:

- **Don't exclude everything**: If your exclusions cover all targets, the scan will find nothing
- **Watch name length**: Profile names are limited to 50 characters
- **Verify paths exist**: While non-existent paths are allowed, they won't be scanned
- **Don't scan virtual filesystems**: Skip `/proc`, `/sys`, `/dev` (these aren't real files)

### Editing Existing Profiles

You can modify any profile, including the built-in default profiles. If you change a default profile and later want it back, use **Restore default profiles** (see [Restoring Default Profiles](#restoring-default-profiles)).

#### How to Edit a Profile

**Step-by-Step**:

1. **Open the Profile Manager**:
    - In the **Scan** view, click the **Manage profiles** button (gear icon) next to the **Scan Profile** dropdown

2. **Select the Profile to Edit**:
    - Find the profile in the list
    - Click the **Edit** button (pencil icon) next to it

3. **Modify Settings**:
    - Change the name, description, targets, or exclusions
    - Add or remove target directories
    - Add or remove exclusion rules
    - All fields work the same as when creating a profile

4. **Save Changes**:
    - Click **Save** to apply your changes
    - Click **Cancel** to discard changes

**What you can edit**:

- ✅ Profile name (must remain unique)
- ✅ Description
- ✅ Target directories (add/remove)
- ✅ Exclusion paths and patterns (add/remove)

**What you cannot edit**:

- ❌ Profile ID (internal identifier)
- ❌ Creation date
- ❌ Default profile flag (`is_default`) — editing a built-in profile keeps it marked as a default

**Editing Default Profiles**:

Default profiles (Quick Scan, Full Scan, Home Folder) **can** be edited directly — the **Edit** button is available for them just like custom profiles. Only **deletion** is blocked for defaults.

If you want to keep the originals untouched, you can instead duplicate a default by exporting and re-importing it (the import creates a copy with a new name like "Quick Scan (2)"), then edit the copy. Either way, you can always revert the built-in profiles to their shipped configuration with **Restore default profiles**.

### Managing Exclusions

Exclusions let you skip files and folders during scanning, improving performance and reducing false positives.

#### Why Use Exclusions?

**Performance reasons**:

- Skip large files that are unlikely to contain threats (videos, disk images)
- Avoid scanning build artifacts and dependencies (node_modules, .git)
- Exclude temporary files and caches

**Reduce false positives**:

- Development tools sometimes flag legitimate software as "PUA" (Potentially Unwanted Application)
- Test files and security tools might trigger detections

**Privacy and system stability**:

- Skip trash folders (files you've already deleted)
- Avoid virtual filesystems that can cause errors (`/proc`, `/sys`)

#### Types of Exclusions

**1. Path Exclusions** (Skip specific directories)

Exclude by exact path:

```
~/.cache
~/Projects/node_modules
/tmp
```

**How they work**:

- Each path is passed to ClamAV as `--exclude-dir`, so it excludes that directory
- Recursive: Excluding a directory skips everything inside it
- Supports `~` for home directory
- Case-sensitive on Linux

**Examples**:

- `~/Downloads/archives` - Skip your download archives subfolder
- `~/.local/share/Trash` - Skip trash (already in Home Folder default)
- `/var/cache` - Skip system cache (already in Full Scan default)

**2. Pattern Exclusions** (Skip files matching patterns)

Exclude by filename pattern using glob syntax:

```
*.tmp
*.log
*.iso
node_modules
```

**How they work**:

- Glob pattern matching (like shell wildcards)
- `*` matches any characters
- `?` matches a single character
- Internally each glob is converted to a regular expression and passed to ClamAV (`--exclude`), so a pattern like `*.tmp` matches any file ending in `.tmp` regardless of directory

**Common patterns**:

- `*.tmp` - Skip all temporary files
- `*.log` - Skip log files
- `*.iso` - Skip disk images (large and unlikely to be infected)
- `*.mp4` - Skip video files (for speed)
- `.DS_Store` - Skip macOS metadata files

#### Adding Exclusions to a Profile

**When creating or editing a profile**:

1. **In the Profile Dialog**:
    - Look for the **Exclusions** section

2. **Add Path Exclusion**:
    - Click **Add Exclusion Path**
    - A new row appears
    - Enter or browse to the path
    - Example: `~/Projects/node_modules`

3. **Add Pattern Exclusion**:
    - Click **Add Exclusion Pattern**
    - A new row appears
    - Enter the pattern
    - Example: `*.tmp`

4. **Remove an Exclusion**:
    - Click the **minus (-)** button next to the exclusion
    - The exclusion is removed immediately

**Exclusion Validation**:

ClamUI validates exclusions when you save:

- ✅ **Valid**: Accepted and saved
- ⚠️ **Warning**: Saved, but you'll see a warning (e.g., "This exclusion might exclude all targets")
- ❌ **Error**: Invalid format, must be corrected before saving

#### Global vs. Profile Exclusions

**Profile Exclusions** (Configured in each profile):

- Apply only when using that specific profile
- Different profiles can have different exclusions
- Stored with the profile

**Global Exclusions** (Configured in Preferences):

- Apply to ALL scans, regardless of profile
- Useful for system-wide exclusions you never want to scan
- Configured in Preferences → **Exclusions**
- See [Managing Exclusion Patterns](settings.md#managing-exclusion-patterns)

💡 **Tip**: Use global exclusions for system directories (`/proc`, `/sys`) and profile exclusions for profile-specific
needs (skip videos in USB scanner profile, but not in Documents profile).

#### Exclusion Best Practices

**DO**:

- ✅ Exclude build artifacts and dependencies (`node_modules`, `vendor`, `build`)
- ✅ Skip virtual filesystems (`/proc`, `/sys`, `/dev`)
- ✅ Exclude large media files if scanning for speed (`.iso`, `.mp4`)
- ✅ Skip caches and temporary directories
- ✅ Test your profile after adding exclusions

**DON'T**:

- ❌ Exclude your entire scan target (this creates a circular exclusion)
- ❌ Exclude important data folders like Documents or Downloads
- ❌ Blindly exclude common file types (.exe, .zip) - these can contain threats
- ❌ Over-exclude just to make scans faster - you might miss threats

**Example Exclusions by Use Case**:

| Use Case           | Recommended Exclusions                                                        |
|--------------------|-------------------------------------------------------------------------------|
| **Development**    | `*/node_modules`, `*/.git`, `*/build`, `*/dist`, `*/__pycache__`              |
| **Media Library**  | `*.mp4`, `*.mkv`, `*.avi`, `*.mp3`, `*.flac` (if just scanning for documents) |
| **USB Drives**     | `*/lost+found`, `*.iso`, `System Volume Information`                          |
| **Home Directory** | `~/.cache`, `~/.local/share/Trash`, `~/Downloads/archives`                    |
| **System Scan**    | `/proc`, `/sys`, `/dev`, `/run`, `/tmp`, `/var/cache`                         |

### Importing and Exporting Profiles

Profiles can be exported to JSON files for backup, sharing, or transferring between computers.

#### Exporting a Profile

**Purpose**: Save a profile to a file

**Step-by-Step**:

1. **Open the Profile Manager**:
    - Scan view → **Manage profiles** button (gear icon) next to the Scan Profile dropdown

2. **Select the Profile**:
    - Find the profile you want to export
    - Click the **Export** button (download icon) next to it

3. **Choose Save Location**:
    - A file save dialog appears
    - Navigate to where you want to save the file
    - The filename defaults to `ProfileName.json`
    - Click **Save**

4. **Confirmation**:
    - The profile is exported to the JSON file
    - You'll see a success message

**What's in the export file?**

The JSON file contains:

- Profile `id`, `name`, and `description`
- Target directories list (`targets`)
- Exclusions (`exclusions` — `paths` and/or `patterns`)
- Extra scan options (`options`)
- Metadata: `is_default` flag and `created_at` / `updated_at` timestamps

> Note: on import the `id` is regenerated and `is_default` is forced to `false`, regardless of what the file contains.

**Example export file** (`Quick-Scan.json`):

```json
{
  "export_version": 1,
  "profile": {
    "id": "6f1c2e7a-...",
    "name": "Quick Scan",
    "description": "Fast scan of the Downloads folder for quick threat detection",
    "targets": [
      "~/Downloads"
    ],
    "exclusions": {},
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z",
    "is_default": true,
    "options": {}
  }
}
```

**Use cases for exporting**:

- **Backup**: Save your custom profiles before system reinstall
- **Sharing**: Send profiles to colleagues or friends
- **Version control**: Track changes to important scan configurations
- **Migration**: Move profiles to another computer

#### Importing a Profile

**Purpose**: Load a profile from a JSON file

**Step-by-Step**:

1. **Open the Profile Manager**:
    - Scan view → **Manage profiles** button (gear icon) next to the Scan Profile dropdown

2. **Click "Import Profile"**:
    - Look for the **Import** button (usually with an upload icon)
    - A file chooser dialog appears

3. **Select the JSON File**:
    - Navigate to your exported profile JSON file
    - Select the file (must have `.json` extension)
    - Click **Open**

4. **Handle Duplicate Names**:
    - If a profile with the same name already exists:
        - ClamUI automatically appends a number: `"Quick Scan (2)"`
        - The imported profile gets a new unique ID
        - Both profiles coexist independently

5. **Confirmation**:
    - You'll see a success message
    - The imported profile appears in your profile list immediately
    - It's available in the Scan Profile dropdown

**Import Validation**:

ClamUI validates imported profiles:

- ✅ Checks JSON syntax is valid
- ✅ Ensures the required `name` field is present (`targets` and `exclusions` default to empty if absent)
- ✅ Validates paths and exclusions
- ❌ Rejects invalid files with error message

**Import Behavior**:

- **New ID**: Imported profiles always get a new unique ID
- **Never default**: Imported profiles are never marked as default (even if the export was from a default profile)
- **Name uniqueness**: Duplicate names get numeric suffix `(2)`, `(3)`, etc.
- **Editable**: Imported profiles can be edited or deleted

**Troubleshooting Import Errors**:

| Error                           | Cause                           | Solution                                                 |
|---------------------------------|---------------------------------|----------------------------------------------------------|
| "Invalid JSON format"           | File is corrupted or not JSON   | Re-export the profile or check file contents             |
| "Missing required field 'name'" | Export file is incomplete       | Ensure file was exported correctly                       |
| "Invalid path format"           | Paths in the file are malformed | Edit the JSON file to fix paths, or create a new profile |
| "File not found"                | JSON file path is incorrect     | Verify file location and try again                       |

#### Sharing Profiles

**Best practices for sharing**:

1. **Export to a descriptive filename**:
    - Good: `USB-Scanner-Profile.json`
    - Bad: `profile.json`

2. **Include documentation**:
    - Add a README explaining what the profile does
    - Note any system-specific paths that might need adjustment

3. **Test on target system**:
    - Import the profile on the destination computer
    - Run a scan to verify it works as expected
    - Adjust paths if needed (e.g., `/media/usb` vs `/mnt/usb`)

4. **Version your profiles**:
    - Include version or date in filename: `Dev-Scan-v2-2024-01.json`
    - Keep older versions as backups

**Privacy note**: Exported profiles contain paths from your system, which might reveal usernames or directory
structures. Review the JSON file before sharing publicly.

### Command-Line Profile Management

You can also work with profiles from a terminal using the `clamui profile` subcommand (handy for scripting or headless machines):

```
clamui profile list                          # List all profiles
clamui profile show "Quick Scan"             # Show one profile's targets and exclusions
clamui profile export "Quick Scan" backup.json   # Export a profile to a JSON file
clamui profile import backup.json            # Import a profile from a JSON file
```

`list` and `show` accept `--json` for machine-readable output. Import and export use the same JSON format described above, so files are interchangeable between the GUI and the CLI.

### Managing Profiles

#### Viewing All Profiles

**In the Profile Manager** (Scan view → **Manage profiles** gear button):

You'll see a list of all profiles with:

- **Profile name** (e.g., "Quick Scan")
- **Description** (if provided)
- **Default badge** (for built-in profiles)
- **Action buttons**: Edit, Export, Delete

#### Deleting a Profile

**To remove a custom profile**:

1. Open the Profile Manager
2. Find the profile to delete
3. Click the **Delete** button (trash icon)
4. Confirm deletion in the dialog

**Important**:

- ❌ Default profiles cannot be deleted (Quick Scan, Full Scan, Home Folder)
- ✅ Custom profiles can be deleted freely
- ⚠️ Deletion is permanent (export first if you want to keep a backup)

#### Restoring Default Profiles

If you've edited or deleted the built-in profiles and want them back, use the **Restore default profiles** button (the refresh / circular-arrow icon on the left of the Manage Profiles header bar):

1. Open the Profile Manager
2. Click the **Restore default profiles** button
3. Confirm in the **Restore Default Profiles?** dialog

This resets **Quick Scan**, **Full Scan**, and **Home Folder** to their original shipped configuration. Any custom profiles you created are left untouched.

#### Using Profiles in Scans

**From the Scan View**:

1. **Select a profile**:
    - Click the **Scan Profile** dropdown
    - Choose a profile from the list
    - The target path updates automatically

2. **Start scanning**:
    - Click the **Scan** button
    - The scan uses the profile's targets and exclusions

3. **Switch back to manual**:
    - Select **No Profile (Manual)** from the dropdown
    - You can now add paths with the **Add files** / **Add folders** buttons

**Profile indicator**:

- When a profile is selected, the dropdown shows the profile name
- The **Scan Targets (N)** group lists the profile's targets

#### Profile Tips and Tricks

💡 **Productivity Tips**:

1. **Create profiles for recurring tasks**:
    - Weekly home scan: "Weekly Home Check"
    - After downloads: "Post-Download Quick Scan"
    - Before backup: "Pre-Backup Full Scan"

2. **Name profiles by frequency or purpose**:
    - "Daily Downloads Check"
    - "Monthly System Scan"
    - "USB Drive Inspector"

3. **Use exclusions strategically**:
    - Development scans: Exclude `node_modules`, `.git`, build folders
    - Media scans: Exclude video files if you only care about documents
    - System scans: Exclude virtual filesystems and caches

4. **Combine with scheduled scans**:
    - Create a profile
    - Use it in scheduled scans for automated security
    - See [Scheduled Scans](scheduling.md)

5. **Keep profiles updated**:
    - As your directory structure changes, update profile targets
    - Add new exclusions as you discover slowdowns
    - Delete unused profiles to reduce clutter

---

