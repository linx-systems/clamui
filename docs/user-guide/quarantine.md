# Quarantine Management

[← Back to User Guide](../USER_GUIDE.md)

---

## Quarantine Management

When ClamUI detects a threat, you can **quarantine** the file - a safe isolation process that prevents the threat from
causing harm while giving you options to review, restore, or delete it permanently.

### What is Quarantine?

**Quarantine** is a secure storage area where detected threats are isolated from your system. Think of it as a digital "
holding cell" for suspicious files.

#### How Quarantine Works

When you quarantine a file, ClamUI:

1. **Moves the file** from its original location to a secure quarantine directory
2. **Records metadata** in a database (original path, threat name, detection date, file size, hash)
3. **Calculates a hash** (SHA-256) to verify file integrity
4. **Stores it safely** where it cannot execute or spread

**Important facts about quarantine**:

- ✅ **Safe**: Quarantined files cannot run or infect your system
- ✅ **Reversible**: You can restore files if they're false positives
- ✅ **Verifiable**: File integrity is checked before restoration
- ✅ **Automatic cleanup**: Old items can be cleared after 30 days
- ✅ **Detailed records**: Full metadata preserved for each file

#### When to Use Quarantine

**Quarantine immediately for**:

- 🔴 **CRITICAL** threats (ransomware, rootkits)
- 🟠 **HIGH** threats (trojans, worms, backdoors)
- 🟡 **MEDIUM** threats (adware, PUA, spyware) - investigate first

**Consider before quarantining**:

- 🔵 **LOW** threats (EICAR tests, heuristic detections) - likely false positives
- **Known safe files**: Software tools, security utilities, test files
- **Development files**: Build tools, compilers that trigger PUA detections

💡 **Tip**: If you're unsure whether a detection is legitimate, research the threat name online or quarantine it
temporarily while you investigate.

### Viewing Quarantined Files

Access your quarantined files through the **Quarantine view** to review isolated threats and manage them.

#### Opening the Quarantine View

**From the main window**:

1. Click the **Quarantine** button in the left navigation sidebar
2. The quarantine list loads automatically

**Keyboard shortcut**: No dedicated shortcut, but navigate using Tab or arrow keys.

#### Understanding the Quarantine List

The quarantine list shows all isolated files with key information:

**Main List View**:

```
┌─────────────────────────────────────────────────────┐
│ Storage Header                                      │
│ Total Size: 2.5 MB                        12 items │
├─────────────────────────────────────────────────────┤
│ ⚠ Win.Trojan.Generic-12345                         │
│   .../Downloads/suspicious.exe                      │
│   2024-01-15 14:30 • 1.2 MB                 [▼]    │
│                                                     │
│ ⚠ PUA.Linux.Miner.Generic                          │
│   .../Documents/crypto-miner                        │
│   2024-01-10 09:15 • 856 KB                 [▼]    │
└─────────────────────────────────────────────────────┘
```

**Storage Information Section** (at the top):

- **Total Size**: Combined size of all quarantined files
- **Item Count**: Number of files in quarantine
- **Purpose**: Quick overview of quarantine usage

**Each Entry Shows**:

**1. Threat Name** (title line):

- The virus/malware name from ClamAV's database
- Examples: `Win.Trojan.Generic-12345`, `Eicar-Test-Signature`
- This is the primary identifier

**2. Original Path** (subtitle line):

- Shows where the file was located before quarantine
- Long paths are truncated with `...` at the start
- Example: `.../Downloads/suspicious.exe` (full path in details)

**3. Metadata** (date and size):

- **Detection Date**: When the file was quarantined (YYYY-MM-DD HH:MM)
- **File Size**: Human-readable size (KB, MB, or GB)
- Separated by bullet point: `2024-01-15 14:30 • 1.2 MB`

**4. Expand Arrow** (`[▼]`):

- Click any entry to expand and see full details
- Expands to show complete information and action buttons

#### Viewing Detailed Information

Click any quarantined file entry to expand it and see complete details:

**Expanded View**:

```
┌─────────────────────────────────────────────────────┐
│ ⚠ Win.Trojan.Generic-12345                  [▲]    │
│   .../Downloads/suspicious.exe                      │
│   2024-01-15 14:30 • 1.2 MB                        │
│                                                     │
│   📁 Original Path                                  │
│      /home/user/Downloads/suspicious.exe            │
│                                                     │
│   📅 Detection Date                                 │
│      2024-01-15 14:30                               │
│                                                     │
│   💾 File Size                                      │
│      1.2 MB (1,258,291 bytes)                       │
│                                                     │
│   [Restore]  [Delete]                               │
└─────────────────────────────────────────────────────┘
```

**Detailed Fields**:

**Original Path**:

- Full absolute path to where the file was located
- Selectable text - you can copy it
- Useful for remembering where the file came from

**Detection Date**:

- Exact date and time when the file was quarantined
- Formatted as `YYYY-MM-DD HH:MM`
- Helps track when threats were detected

**File Size**:

- Human-readable size (e.g., "1.2 MB")
- Exact byte count in parentheses (e.g., "1,258,291 bytes")
- Useful for identifying large files taking up storage

**Action Buttons**:

- **Restore** (blue): Recover the file to its original location
- **Delete** (red): Permanently remove the file
- See sections below for details on each action

#### List Features

**Search**:

- A search box sits at the top of the list (placeholder *"Search by threat name or path..."*)
- Filters entries by **case-insensitive substring** match against both the threat name and the original path
- The header count switches to *"X of Y items"* while a search is active; the total size always reflects the full quarantine
- If nothing matches, a **"No matching entries"** placeholder appears

**Pagination** (for large lists):

- **Initial display**: First 25 entries shown automatically
- **Show More**: Click button to load 25 more entries
- **Show All**: Load all remaining entries at once (if many remain)
- **Progress indicator**: "Showing X of Y entries"

**Empty State**:
If no files are quarantined, you'll see:

```
        🛡️
  No Quarantined Files
  Detected threats will be isolated here for review
```

**Refresh Button**:

- Click the **refresh icon** (↻) in the header to reload the list
- Useful after quarantining files from scans
- The list auto-refreshes when you open the view

**Loading State**:
While loading, you'll see:

```
   ⏳  Loading quarantine entries...
```

### Restoring Files from Quarantine

If a quarantined file is actually safe (a **false positive**), you can restore it to its original location.

⚠️ **Important**: Only restore files you are **absolutely certain** are safe. If you're unsure, leave the file
quarantined or delete it.

#### When to Restore Files

**Restore if**:

- ✅ You recognize the file as legitimate software
- ✅ The threat is flagged as **LOW** severity (often EICAR tests or heuristics)
- ✅ You verified the file source and it's from a trusted developer
- ✅ You researched the threat name and confirmed it's a known false positive
- ✅ You need the file for work and have verified its safety

**Do NOT restore if**:

- ❌ The threat is **CRITICAL** or **HIGH** severity
- ❌ You don't recognize the file or don't remember downloading it
- ❌ The file came from an untrusted source (unknown website, email attachment)
- ❌ You cannot verify the file is safe
- ❌ The detection is for ransomware, trojan, or malware

#### How to Restore a File

**Step-by-Step**:

1. **Open Quarantine View**:
    - Navigate to the **Quarantine** view

2. **Find the File**:
    - Locate the quarantined file in the list
    - Check the threat name and original path

3. **Expand the Entry**:
    - Click the file entry to expand it
    - Review the full details (path, date, size)

4. **Click Restore**:
    - Click the **Restore** button (blue button)
    - A confirmation dialog appears

5. **Review the Warning**:
   ```
   Restore File?

   This will restore the file to its original location:
   /home/user/Downloads/suspicious.exe

   Warning: This file was detected as a threat (Win.Trojan.Generic-12345).
   Only restore if you are certain it is a false positive.

   [Cancel]  [Restore]
   ```

6. **Confirm Restoration**:
    - Read the warning carefully
    - Verify the original path is correct
    - Click **Restore** to proceed, or **Cancel** to abort

7. **Wait for Completion**:
    - ClamUI verifies file integrity (checks SHA-256 hash)
    - Moves the file back to its original location
    - Removes the entry from quarantine
    - Shows success/failure message

**Success Message**:

```
✓ File restored successfully
```

**The file is now**:

- Back in its original location
- Removed from quarantine
- Can be used normally

#### Restore Errors

If restoration fails, you'll see an error message explaining why:

**Common Errors**:

| Error Message                                                      | Cause                                                  | Solution                                                                                  |
|--------------------------------------------------------------------|--------------------------------------------------------|-------------------------------------------------------------------------------------------|
| **Cannot restore: A file already exists at the original location** | Another file now exists at the same path               | Manually choose a different location for the file, or delete/move the existing file first |
| **File integrity verification failed**                             | The quarantined file was modified or corrupted         | Do NOT restore - file may be damaged or tampered with. Delete it instead.                 |
| **Permission denied**                                              | You don't have write access to the original directory  | Run ClamUI with appropriate permissions, or manually move the file as root                |
| **Quarantine entry not found**                                     | The database entry is missing                          | The file may have been deleted. Refresh the quarantine list.                              |
| **File not found**                                                 | The quarantined file was manually deleted from storage | The file is gone. Remove the database entry by clicking Delete.                           |

💡 **Troubleshooting Tip**: If you need the file but restoration fails, you can find it manually in the quarantine
storage directory (see [Understanding Quarantine Storage](#understanding-quarantine-storage)) and copy it yourself.

#### After Restoring

Once a file is restored:

1. **Rescan it**: Run a scan on the restored file to verify it's still detected
    - If ClamAV still flags it → likely a real threat, quarantine again
    - If ClamAV doesn't flag it → may have been a false positive

2. **Add an exclusion** (if it's a known false positive):
    - Go to **Preferences** → **Exclusion Patterns**
    - Add the file path or a pattern to prevent future detections
    - See [Managing Exclusion Patterns](settings.md#managing-exclusion-patterns)

3. **Report false positives** (optional):
    - Visit the ClamAV false positive reporting page
    - Help improve ClamAV's detection accuracy
    - [https://www.clamav.net/reports/fp](https://www.clamav.net/reports/fp)

### Permanently Deleting Threats

If a quarantined file is genuinely malicious, you should **permanently delete** it to free up storage and ensure it
cannot be accidentally restored.

⚠️ **Warning**: Deletion is **permanent and irreversible**. Once deleted, the file cannot be recovered.

#### When to Delete Files

**Delete immediately for**:

- 🔴 **CRITICAL** threats (ransomware, rootkits, bootkits)
- 🟠 **HIGH** threats (trojans, worms, backdoors) - after you're sure they're not false positives
- Known malware that you've verified is not a false positive

**Consider keeping quarantined (don't delete yet) if**:

- You're not 100% certain the file is malicious
- You want to investigate further
- The threat is **LOW** severity and might be a false positive
- You need time to verify with antivirus vendors or security forums

💡 **Best Practice**: When in doubt, keep files quarantined for a few days/weeks while you research. You can delete them
later using the "Clear Old Items" feature.

#### How to Delete a File

**Step-by-Step**:

1. **Open Quarantine View**:
    - Navigate to the **Quarantine** view

2. **Find the File**:
    - Locate the quarantined threat in the list
    - Verify the threat name and path

3. **Expand the Entry**:
    - Click the file entry to expand it
    - Double-check you're deleting the right file

4. **Click Delete**:
    - Click the **Delete** button (red button)
    - A confirmation dialog appears

5. **Review the Warning**:
   ```
   Permanently Delete File?

   This will permanently delete the quarantined file:

   Threat: Win.Trojan.Generic-12345
   Size: 1.2 MB

   This action cannot be undone.

   [Cancel]  [Delete]
   ```

6. **Confirm Deletion**:
    - Verify the threat name and size
    - Click **Delete** to proceed, or **Cancel** to abort
    - **There is no undo** - be certain before confirming

7. **Wait for Completion**:
    - ClamUI deletes the file from quarantine storage
    - Removes the database entry
    - Shows success/failure message

**Success Message**:

```
✓ File deleted permanently
```

**The file is now**:

- Permanently deleted from quarantine storage
- Removed from the quarantine database
- Cannot be recovered

#### Delete Errors

If deletion fails, you'll see an error message:

**Common Errors**:

| Error Message                  | Cause                                             | Solution                                                                   |
|--------------------------------|---------------------------------------------------|----------------------------------------------------------------------------|
| **Permission denied**          | ClamUI doesn't have permission to delete the file | Check quarantine directory permissions. May need to run as different user. |
| **File not found**             | File was already deleted manually                 | Click Refresh to update the list. The entry will be cleaned up.            |
| **Quarantine entry not found** | Database entry is missing                         | Refresh the list. The file may have already been removed.                  |

💡 **Tip**: If deletion fails, you can manually delete files from the quarantine storage directory.
See [Understanding Quarantine Storage](#understanding-quarantine-storage).

### Clearing Old Quarantine Items

Over time, quarantined files accumulate and use disk space. ClamUI provides a **Clear Old Items** feature to
automatically remove files older than 30 days.

#### Why Clear Old Items?

**Benefits**:

- 🗑️ **Free up disk space**: Remove old threats you've forgotten about
- 🧹 **Reduce clutter**: Keep the quarantine list focused on recent detections
- ⏰ **Automatic cleanup**: Don't manually review old files one by one
- 🔒 **Safe timeframe**: 30 days is enough time to verify false positives

**When to use it**:

- After several months of use when quarantine is filling up
- When you notice quarantine storage is taking significant space
- As part of regular system maintenance (monthly/quarterly)
- When you're confident old detections are genuine threats

#### How to Clear Old Items

**Step-by-Step**:

1. **Open Quarantine View**:
    - Navigate to the **Quarantine** view

2. **Click "Clear Old Items"**:
    - Look for the **Clear Old Items** button in the header
    - Located near the Refresh button (top right of quarantine list)

3. **Review the Confirmation Dialog**:
   ```
   Clear Old Items?

   This will permanently delete 8 quarantined file(s) that are older than 30 days.

   This action cannot be undone.

   [Cancel]  [Clear Old Items]
   ```

4. **Check the Count**:
    - The dialog shows how many files will be deleted
    - Make sure the number seems reasonable
    - If it's higher than expected, consider reviewing the list first

5. **Confirm Cleanup**:
    - Click **Clear Old Items** to proceed
    - Click **Cancel** if you want to review files individually first

6. **Wait for Completion**:
    - ClamUI deletes all files older than 30 days
    - Removes database entries
    - Shows success message with count

**Success Message**:

```
✓ Removed 8 old item(s)
```

**If no old items exist**:

```
ℹ No items older than 30 days
```

#### What Gets Cleared

**Files included**:

- ✅ Any file quarantined **more than 30 days ago** (based on detection date)
- ✅ All threat types (CRITICAL, HIGH, MEDIUM, LOW)
- ✅ All file sizes

**Files excluded**:

- ❌ Files quarantined **less than 30 days ago** (kept in quarantine)
- ❌ Files you've just added this month

**Age calculation**:

- Based on the **Detection Date** field
- Calculated from current date/time
- Exactly 30 days = 30 × 24 hours from detection timestamp

💡 **Example**: If today is February 15, 2024:

- File from January 15, 2024 → Cleared (30 days old)
- File from January 16, 2024 → Kept (29 days old)
- File from February 1, 2024 → Kept (14 days old)

#### Before Clearing: Review the List

**Recommended workflow**:

1. **Sort by age** (mentally):
    - Scroll through the quarantine list
    - Older entries appear with earlier detection dates
    - Identify files from >30 days ago

2. **Check for false positives**:
    - Look for **LOW** severity threats in old entries
    - Review any files you recognize as safe
    - Restore false positives before clearing

3. **Verify critical threats**:
    - Confirm CRITICAL/HIGH threats are genuine malware
    - Research any unfamiliar threat names
    - Decide if you want to keep them longer for reference

4. **Then clear**:
    - Once you're satisfied, run "Clear Old Items"
    - Old threats are removed automatically

⚠️ **Warning**: The 30-day threshold is **fixed** and cannot be customized in the current version. If you want to keep
files longer, don't use this feature - delete files individually instead.

### Managing Quarantine from the Command Line

ClamUI ships a headless `clamui quarantine` subcommand for managing isolated files without opening the GUI — useful over SSH or in scripts:

```bash
# List all quarantined files (add --json for machine-readable output)
clamui quarantine list
clamui quarantine list --json

# Restore a quarantined file to its original location (by entry ID)
clamui quarantine restore 42

# Permanently delete a quarantined file (by entry ID)
clamui quarantine delete 42
```

The numeric **ID** comes from the first column of `clamui quarantine list`. Restore performs the same SHA-256 integrity check as the GUI and refuses if a file already exists at the destination.

### Understanding Quarantine Storage

Quarantined files are stored securely on your system. Understanding where and how they're stored helps with
troubleshooting and advanced management.

#### Storage Location

**Default Quarantine Directory**:

```
~/.local/share/clamui/quarantine/
```

**Full path example**:

```
/home/username/.local/share/clamui/quarantine/
```

**What this means**:

- `~` = Your home directory
- `.local/share/` = User-specific application data (XDG Base Directory standard)
- `clamui/` = ClamUI's data directory
- `quarantine/` = Isolated threat storage

**Database Location**:

```
~/.local/share/clamui/quarantine.db
```

This SQLite database stores metadata for each quarantined file:

- Original file path
- Quarantine storage path
- Threat name
- Detection date/time
- File size
- SHA-256 hash (for integrity verification)

#### How Files Are Stored

When you quarantine a file, ClamUI:

1. **Generates a unique filename**:
    - Prefixes a random 16-character hex identifier (from a UUID) to the original filename
    - Example: `a3f9d8e1c2b40f17_virus.exe`
    - The original filename is preserved as a suffix for easier identification

2. **Moves the file atomically**:
    - From original location (e.g., `/home/user/Downloads/virus.exe`)
    - To quarantine directory (e.g., `~/.local/share/clamui/quarantine/a3f9d8e1c2b40f17_virus.exe`)
    - Uses an `O_NOFOLLOW` fd-based copy followed by unlink of the original (no symlink following)

3. **Calculates SHA-256 hash**:
    - Creates a cryptographic fingerprint of the file
    - Stored in database for integrity verification
    - Used to detect tampering before restoration

4. **Records metadata**:
    - All information saved to `quarantine.db`
    - Links the quarantined file to its original path

**Example quarantine storage**:

```
~/.local/share/clamui/
├── quarantine/
│   ├── a3f9d8e1c2b40f17_suspicious.exe   (Win.Trojan.Generic)
│   ├── b7e4f2c9d1086a35_crypto-miner     (PUA.Linux.Miner)
│   └── c1d8a3f70e92b461_eicar.txt        (Eicar-Test-Signature)
└── quarantine.db                               (Metadata database)
```

#### File Permissions

**Security measures**:

- The quarantine directory itself is owner-only (`0o700`); no other user can list or enter it
- Quarantined files are stored **owner read-only** (`0o400`) so they cannot be executed or modified in place
- All file operations use `O_NOFOLLOW` (symlinks are rejected) and an atomic fd-based copy-then-unlink — never a plain move — to close TOCTOU races
- The metadata database and its WAL/SHM sidecar files are owner read/write only (`0o600`)
- Isolation is enforced by both location and restrictive permissions, not just database tracking

**Default permissions**:

- Quarantine directory (`quarantine/`): `700` (rwx------, owner only)
- Quarantined files: `400` (r--------, owner read-only — cannot execute)
- Metadata database (`quarantine.db`) and WAL/SHM files: `600` (rw-------, owner read/write)

#### Storage Considerations

**Disk Space Usage**:

- Quarantined files consume disk space equal to their original size
- Large files (ISOs, videos) take significant space
- Monitor with: **Total Size** in quarantine view header
- Example: 50 quarantined files = ~100 MB (varies widely)

**Quota Limits**:

- No built-in quota limit
- Quarantine can grow indefinitely if not cleared
- Use "Clear Old Items" regularly to manage space
- Consider manual cleanup if storage is constrained

**Best Practices for Storage Management**:

💡 **Tips**:

1. **Regular cleanup**:
    - Use "Clear Old Items" monthly or quarterly
    - Delete confirmed threats after a few days/weeks
    - Don't keep EICAR test files in quarantine

2. **Monitor storage**:
    - Check "Total Size" indicator in Quarantine view
    - If it exceeds 500 MB, review and delete old files
    - Large quarantine may slow down list loading

3. **Delete large false positives**:
    - If you restore a large file (e.g., 100+ MB ISO)
    - It's removed from quarantine automatically
    - But if you delete without restoring, it frees space immediately

4. **Backup considerations**:
    - Do NOT include `~/.local/share/clamui/quarantine/` in backups
    - These are isolated threats - you don't want to back them up
    - The database (`quarantine.db`) can be backed up safely (only metadata)

#### Manual File Management

**Advanced users** can manually manage quarantine files:

**Viewing files**:

```bash
ls -lh ~/.local/share/clamui/quarantine/
```

**Checking storage size**:

```bash
du -sh ~/.local/share/clamui/quarantine/
```

**Manually deleting all quarantined files** (⚠️ use with caution):

```bash
rm -rf ~/.local/share/clamui/quarantine/*
rm ~/.local/share/clamui/quarantine.db
```

**Restoring a file manually** (if ClamUI fails):

```bash
# Find the original path in the database first, then:
cp ~/.local/share/clamui/quarantine/quarantined_XXXXXX /original/path/filename
```

⚠️ **Warning**: Manual management bypasses integrity checks and database updates. Only use if ClamUI's built-in features
aren't working.

#### Flatpak Considerations

If you installed ClamUI via **Flatpak**, the quarantine location is different:

**Flatpak Quarantine Directory**:

```
~/.var/app/io.github.linx_systems.ClamUI/data/clamui/quarantine/
```

**Flatpak Database**:

```
~/.var/app/io.github.linx_systems.ClamUI/data/clamui/quarantine.db
```

**Accessing Flatpak quarantine**:

- Same directory structure, just different base path
- All ClamUI features work identically
- Manual file operations require Flatpak-specific paths

💡 **Tip**: You can check if you're using Flatpak by running:

```bash
flatpak list | grep -i clamui
```

If output appears, you're using the Flatpak version.

#### Troubleshooting Storage Issues

**Problem: Quarantine list shows files but directory is empty**

**Cause**: Database entries exist but files were manually deleted

**Solution**:

1. Click each entry and click **Delete** to clean up database entries
2. Or manually delete the database file (⚠️ removes all quarantine records):
   ```bash
   rm ~/.local/share/clamui/quarantine.db
   ```

**Problem: File restoration fails with "File integrity verification failed"**

**Cause**: The quarantined file was modified or corrupted in storage

**Solution**:

- Do NOT restore this file - it may be damaged or tampered with
- Delete the entry permanently
- If you need the file, obtain it from the original source again

**Problem: Quarantine view loads slowly**

**Cause**: Too many entries in the database (hundreds or thousands)

**Solution**:

1. Use "Clear Old Items" to reduce count
2. Delete old entries manually
3. Consider clearing the entire quarantine if all files are confirmed threats

**Problem: Permission denied when quarantining/restoring/deleting**

**Cause**: Incorrect file permissions on quarantine directory

**Solution**:

```bash
# Fix quarantine directory permissions:
chmod 700 ~/.local/share/clamui/quarantine/
chmod 400 ~/.local/share/clamui/quarantine/*
chmod 600 ~/.local/share/clamui/quarantine.db
```

---

