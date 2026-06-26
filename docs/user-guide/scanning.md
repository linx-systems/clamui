# Scanning for Viruses

[← Back to User Guide](../USER_GUIDE.md)

---

## Scanning for Viruses

Now that you've completed your first scan, let's dive deeper into ClamUI's scanning capabilities. This section provides
comprehensive reference information about all scanning features.

### File and Folder Scanning

ClamUI provides flexible options for selecting files and folders to scan. Understanding these options helps you scan
exactly what you need, when you need it.

#### Understanding Scan Targets

A **scan target** is the file or folder you want ClamUI to check for viruses. You can scan:

- **Individual files**: Any single file on your system (useful for checking downloads)
- **Folders/directories**: Entire folders and all their contents (recursive scanning)
- **Multiple locations**: Using scan profiles, you can scan multiple folders at once
- **External drives**: USB sticks, external hard drives, network locations (if accessible)

**Important**: ClamUI scans recursively by default. When you select a folder, all files and subfolders inside it are
scanned automatically.

#### Selecting Files to Scan

**Using the Add Buttons**

The **Scan Targets** group has two buttons in its header:

1. **Add files** (document icon): opens a file chooser; select one or more files
2. **Add folders** (folder icon): opens a folder chooser; select one or more folders

In the chooser:

- Navigate using the folder sidebar, the path bar, or search (Ctrl+F)
- Select one or several items, then click **Open**/**Select**
- You can type a path directly in the location bar (Ctrl+L)

Each chosen item is added as its own row in the target list. A **Clear All** button appears once more than one
target is listed, and every row has a remove (×) button.

**Tips for selecting targets**:

- You can add as many files and folders as you like; they are all scanned in one run
- Duplicate paths are ignored automatically
- The chooser respects hidden files based on your file manager settings

#### Path Display and Validation

Each selected target appears as a row in the **Scan Targets** list (the group title shows the count, e.g.
"Scan Targets (3)"):

```
/home/username/Downloads
/home/username/Documents/report.pdf
```

The path is validated automatically:

- ✅ **Valid paths** display normally in monospaced font
- ❌ **Invalid paths** show an error banner with details
- 🔒 **Permission issues** are detected before scanning starts

**Common path validation errors**:

- Path does not exist (file/folder was deleted or moved)
- Insufficient permissions to read the location
- Path is on a remote filesystem that's not mounted
- Special system paths that require root access

If you see a validation error, choose a different path or check the file permissions.

### Drag-and-Drop Scanning

Drag-and-drop provides the fastest way to scan files in ClamUI. Simply grab a file or folder from your file manager and
drop it into the ClamUI window.

#### How Drag-and-Drop Works

**Visual Feedback**

When you drag files over the ClamUI window:

1. **Drag starts**: Pick up a file/folder in your file manager
2. **Drag over ClamUI**: The entire window highlights with a colored border
3. **Border style**: Dashed blue/accent color border appears
4. **Background tint**: Light transparent overlay shows the drop is accepted
5. **Drop the file**: Release your mouse button anywhere in the window
6. **Border disappears**: Visual feedback clears immediately
7. **Targets update**: Each dropped file/folder is added to the "Scan Targets" list

This visual feedback confirms ClamUI is ready to accept your file.

#### Drag-and-Drop Behavior

**What you can drop**:

- ✅ Files from your local filesystem
- ✅ Folders/directories
- ✅ Multiple files and folders (every valid item is added to the target list)
- ✅ Files from archive managers (if they provide local paths)

**What won't work**:

- ❌ Remote files (http://, ftp://, etc.) - must be downloaded first
- ❌ Files from cloud storage (unless locally synced)
- ❌ Dropping during an active scan (rejected with error message)
- ❌ Special URIs that don't resolve to local paths

**Multi-file drops**: You can drop several files and folders at once — every valid path is added to the target list
and included in the next scan. Invalid paths (nonexistent locations, or symlinks that point into protected system
directories) are rejected by validation, and an error toast explains why if nothing valid was dropped.

#### Drop Error Handling

If a drag-and-drop operation fails, ClamUI displays an error banner explaining why:

- **"Scan in progress"**: You can't change the scan target while scanning
- **"No files were dropped"**: The drag operation didn't contain valid file data
- **"Remote files not supported"**: The file is not on your local filesystem
- **"Path does not exist"**: The file was moved or deleted during the drag
- **"Permission denied"**: You don't have read access to the dropped file

These error banners can be dismissed by clicking the "×" button or automatically disappear after a few seconds.

### Testing with the EICAR Test File

The **EICAR test file** is a special tool for verifying that antivirus software is working correctly. ClamUI includes a
convenient "EICAR Test" button for instant testing.

#### What is EICAR?

EICAR (European Institute for Computer Antivirus Research) created a standard test file that **all antivirus software
recognizes as a threat**, but which is **completely harmless**.

**Important facts about EICAR**:

- ✅ It's NOT real malware - it cannot harm your computer
- ✅ It's just a specific text string that antivirus programs look for
- ✅ It's used worldwide to test antivirus installations
- ✅ It's safe to create, download, and delete
- ❌ It won't do anything malicious (it's not even executable code)

The EICAR string looks like this:

```
X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*
```

When ClamAV scans this string, it detects it as a threat with names like:

- `Eicar-Signature`
- `Eicar-Test-Signature`
- `Win.Test.EICAR_HDB-1`

#### Using the EICAR Test Button

ClamUI makes EICAR testing simple with a dedicated test button:

**Step-by-Step**:

1. **Find the Test button**: Located next to the main Scan button in the scan view
2. **Click "EICAR Test"**: The button is next to the main Scan button
3. **Automatic test file creation**: ClamUI creates a temporary EICAR file
4. **Scan starts immediately**: No need to select a path
5. **Wait for results**: Scanning completes in 1-2 seconds
6. **Review detection**: You should see the EICAR threat detected
7. **Automatic cleanup**: The test file is deleted after scanning

**Expected Results**:

✅ **Working correctly**: ClamUI shows a threat detection with:

- Threat name containing "EICAR" or "Eicar-Signature"
- Severity level: **LOW** (blue badge)
- Category: **Test**
- File path: Temporary directory path

❌ **Not working**: If no threat is detected:

- ClamAV may not be properly installed
- Virus definitions may be outdated
- Scan backend might have issues
- See [Troubleshooting](troubleshooting.md) for solutions

#### When to Use EICAR Testing

**Use the EICAR test when**:

- You just installed ClamUI and want to verify it works
- You updated virus definitions and want to confirm they loaded
- You suspect ClamUI isn't detecting threats correctly
- You're demonstrating ClamUI to someone
- You changed scan backend settings and want to test

**How often to test**: Testing once after installation is usually sufficient. You don't need to test regularly unless
you suspect problems.

### Automatic Device Scanning

ClamUI can automatically scan removable and external drives (USB sticks, external disks) as soon as they are
mounted. This is off by default; enable and tune it under **Preferences → Device Scan** (which device types to
watch, a maximum size, an optional auto-quarantine, and whether to skip while on battery).

### Understanding Scan Progress

When you click the Scan button, ClamUI performs several operations behind the scenes. Understanding what's happening
helps you interpret scan behavior and diagnose issues.

#### The Scanning Lifecycle

**1. Scan Initialization (< 1 second)**

When you click Scan:

- UI elements become disabled (buttons grayed out)
- Visual indication shows scanning is in progress
- ClamUI validates your scan target path one final time
- Settings are read (exclusion patterns, scan backend choice)
- The scanner is configured with your chosen options

**2. Backend Selection**

ClamUI chooses which scanning method to use:

- **Auto mode** (default):
    - First, try to connect to clamd daemon
    - If daemon is running: Use daemon for faster scanning
    - If daemon is unavailable: Fall back to clamscan
- **Daemon mode**: Use clamd only (error if unavailable)
- **Clamscan mode**: Use standalone clamscan only

ClamUI caches the daemon-availability check for 60 seconds, so repeated scans in auto mode don't re-probe the
socket every time. Change the backend in **Preferences → Scanner Settings** (stored as `scan_backend` in
`settings.json`, one of `auto`, `daemon`, or `clamscan`).

**Backend performance**:

- **clamd (daemon)**: Fast (10-50x faster), lower CPU usage, requires running daemon
- **clamscan (standalone)**: Slower, higher CPU usage, always available

💡 **Tip**: The scan view shows a "Backend: …" label under the buttons, and the Components view (in the sidebar) shows full daemon/clamscan status

**3. Scanning Process**

ClamAV analyzes files looking for malware signatures:

- Files are read from disk sequentially
- Each file is checked against the virus definition database
- Suspicious patterns trigger detections
- Results are collected as scanning progresses
- Exclusion patterns (if configured) skip matched files

**What ClamAV checks**:

- File contents (signature matching)
- File headers and structure
- Embedded scripts and macros
- Archive contents (zip, tar, rar, etc.)
- Email attachments and formats
- Compressed and encoded data

**System impact during scanning**:

- **CPU usage**: 20-80% of one CPU core (varies by backend)
- **Disk I/O**: Reading files from disk (SSD is faster than HDD)
- **Memory**: Typically 50-200 MB (higher for large archives)
- **Other apps**: Should remain responsive during scanning

**4. Scan Completion**

When scanning finishes:

- Results are parsed from ClamAV output
- Threat details are extracted and classified
- Severity levels are assigned to detected threats
- Scan log is saved to history
- UI updates with results
- Buttons become active again

**Exit codes** (technical reference):

- `0` = Clean (no threats found)
- `1` = Infected (threats detected)
- `2` = Error (scanning failed)

#### Scan Duration Estimates

How long a scan takes depends on several factors:

**File count**: More files = longer scan time

- 100 files: ~10-30 seconds
- 1,000 files: ~1-3 minutes
- 10,000 files: ~5-15 minutes
- 100,000+ files: ~30-120 minutes

**File sizes**: Large files take longer to scan

- Small text files: Milliseconds per file
- Large documents (PDFs, Office files): 1-5 seconds each
- Videos and archives: 5-30 seconds each
- ISO images and disk images: Minutes per file

**File types**: Different formats have different scan complexity

- ⚡ Fast: Plain text, small binaries
- 🐌 Slow: Archives (zip, tar.gz), large PDFs, disk images

**Scan backend**:

- clamd (daemon): Up to 50x faster
- clamscan (standalone): Slower but always available

**Storage speed**:

- SSD: 2-5x faster than HDD
- Network drives: Much slower (depends on network speed)
- USB 2.0: Slower than internal drives
- USB 3.0/3.1: Similar to internal HDDs

**Example scan times** (typical modern system with SSD):

| Location         | File Count     | Backend  | Duration  |
|------------------|----------------|----------|-----------|
| Downloads folder | 200 files      | daemon   | 10-20s    |
| Downloads folder | 200 files      | clamscan | 30-60s    |
| Home directory   | 15,000 files   | daemon   | 3-8 min   |
| Home directory   | 15,000 files   | clamscan | 10-20 min |
| Full system      | 500,000+ files | daemon   | 30-90 min |

💡 **Tip**: For faster scans, run the clamd daemon and select the daemon (or auto) backend in Preferences → Scanner Settings

#### Monitoring Scan Progress

**What you can see during scanning**:

- A status message at the top of the progress area: "Scanning…", or "Target X of Y: <path>" when several targets are queued
- A progress bar that pulses continuously; when file-count estimates are available it shows a percentage (e.g. "42%")
- The file currently being scanned, with a spinner
- Running counts (files scanned, and target N of M for multi-target runs)
- A live threat list that fills in as infected files are found

Live progress details can be turned off with the `show_live_progress` setting (Preferences → Behavior); the pulsing progress bar still appears.

**What you can do during scanning**:

- ✅ Leave the window open (don't minimize or close)
- ✅ Read other parts of this guide
- ✅ Use other applications
- ❌ Don't close ClamUI window (stops the scan)
- ❌ Don't put your computer to sleep
- ❌ Don't unmount the drive being scanned

### Reading Scan Results

After a scan completes, ClamUI presents results in a clear, structured format. This section explains how to read and
understand every detail.

#### Result Status Messages

**Clean Scan (No Threats)**:

```
✓ Scan complete - No threats found
```

This green success message tells you:

- ✅ All scanned files are safe
- ✅ No viruses, trojans, or malware detected
- ✅ The number of files examined is shown in the View Results dialog and progress stats
- ✅ You can use your files normally

**Threats Detected**:

```
⚠ Scan complete - 3 threat(s) detected
```

This orange/red warning message indicates:

- ⚠️ ClamAV found infected or suspicious files
- ⚠️ Number of distinct threats detected
- ⚠️ A **View Results (N)** button appears; click it to open the Scan Results dialog with detailed threat cards
- ⚠️ Action is recommended (quarantine or review)

**Scan Error**:

```
✗ Scan error: [error details]
```

This red error message means:

- ❌ The scan couldn't complete
- ❌ Error details explain what went wrong
- ❌ Common causes: missing ClamAV, permission denied, path not found
- ❌ See error message and [Troubleshooting](troubleshooting.md) section

#### Threat Detail Cards

Each detected threat is displayed in its own card with complete information:

**Card Layout**:

```
┌─────────────────────────────────────────────────────────┐
│ Win.Trojan.Generic-12345                         [HIGH] │
│ /home/user/Downloads/suspicious-file.exe                │
│ Category: Trojan                                        │
│                                                         │
│ [Quarantine]  [Exclude]  [Copy Path]                    │
└─────────────────────────────────────────────────────────┘
```

**Card Components Explained**:

**1. Threat Name** (top, large bold text)

- The technical name from ClamAV's virus database
- Format varies: `Platform.Type.Variant-ID`
- Examples:
    - `Win.Trojan.Generic-12345` (Windows trojan)
    - `Eicar-Test-Signature` (EICAR test)
    - `PUA.Linux.Miner.Generic` (potentially unwanted app)
- This name is recognized globally across all antivirus software

**2. Severity Badge** (top-right, colored label)

- Visual indicator of threat danger level
- Four levels: CRITICAL, HIGH, MEDIUM, LOW
- Color-coded for quick recognition
- See [Threat Severity Levels](#threat-severity-levels) for details

**3. File Path** (second line, monospaced)

- Absolute path to the infected file
- You can select this text and copy it
- Format: `/full/path/to/infected/file.ext`
- Use this to locate the file in your file manager

**4. Category** (third line, if available)

- The type of malware or threat
- Common categories:
    - **Virus**: Traditional computer viruses
    - **Trojan**: Trojan horse malware
    - **Worm**: Self-replicating worms
    - **Ransomware**: File-encrypting ransomware
    - **Adware**: Advertising software
    - **PUA**: Potentially Unwanted Application
    - **Test**: Test signatures (like EICAR)
    - **Spyware**: Information-stealing software
    - **Rootkit**: System-hiding malware
    - **Backdoor**: Remote access tools
    - **Exploit**: Vulnerability exploits
    - **Macro**: Macro viruses (documents)
    - **Phishing**: Phishing attempts
    - **Heuristic**: Behavior-based detection

**5. Action Buttons** (bottom)

- **Quarantine**: Safely isolate the threat file
    - Moves file to secure quarantine storage
    - File can't execute or spread from quarantine
    - You can restore it later if it's a false positive
    - See [Quarantine Management](quarantine.md) for details
- **Exclude**: Add this file's path to your exclusion patterns so future scans skip it (use only for confirmed false positives)
- **Copy Path**: Copy file path to clipboard
    - Useful for reporting or manual investigation
    - You can paste the path into a terminal or file manager
    - Helps you locate the file without typing the full path

A bulk **Quarantine All ({n})** button in the dialog header isolates every detected threat at once. Quarantined files
are copied to secure storage, hashed with SHA-256, and verified against that hash before any later restore (see
[Quarantine Management](quarantine.md)).

#### Understanding File Counts

At the end of a scan, ClamUI reports:

```
No threats found (1,543 files scanned)
```

**What "files scanned" means**:

- Individual files examined by ClamAV
- Includes files in subdirectories (recursive count)
- Does NOT include:
    - Directories themselves (only files within)
    - Excluded files (via exclusion patterns)
    - Files ClamAV couldn't read (permission denied)
    - Symbolic links (unless they point to files)

**Why the count might seem low**:

- Hidden files might not be counted
- Some files might be skipped due to exclusions
- Symlinks to outside the scan path are ignored
- Empty directories contain zero files

**Why the count might seem high**:

- Archives are unpacked and contents are counted individually
- Cache files and temp files are included
- Each file in nested folders is counted

### Threat Severity Levels

ClamUI automatically classifies detected threats into four severity levels. Understanding these levels helps you
prioritize your response to detections.

#### How Severity is Determined

ClamUI analyzes the threat name from ClamAV and matches it against known patterns to determine severity. This
classification is based on:

- **Threat type keywords**: Ransomware, Trojan, Adware, etc.
- **Malware capabilities**: What the threat can do
- **Potential damage**: How dangerous the threat is
- **Industry standards**: Common classification practices

**Classification is automatic**: You don't need to understand threat names yourself - ClamUI does the analysis for you.

#### The Four Severity Levels

**🔴 CRITICAL (Red Badge)**

The most dangerous threats requiring immediate action.

**Threat types**:

- **Ransomware**: Encrypts your files and demands payment
    - Examples: `Ransom.Locky`, `CryptoLocker`, `WannaCry`
- **Rootkits**: Hides malware presence and provides deep system access
    - Examples: `Rootkit.Win32`, `Bootkit.Generic`
- **Bootkits**: Infects boot process for persistence
    - Examples: `Bootkit.MBR`, `Rootkit.Boot`

**What they can do**:

- Encrypt all your personal files
- Hide themselves from antivirus software
- Survive system restarts
- Provide attackers with complete system control
- Steal credentials and sensitive data

**Recommended action**:

1. **Quarantine immediately** - Don't delay
2. **Scan other systems** - Check if it spread
3. **Change passwords** - If the system was compromised
4. **Consider professional help** - For business/critical systems

**🟠 HIGH (Orange Badge)**

Serious threats that should be quarantined promptly.

**Threat types**:

- **Trojans**: Disguised malware that performs malicious actions
    - Examples: `Win.Trojan.Agent`, `Trojan.Generic`
- **Worms**: Self-replicating malware that spreads automatically
    - Examples: `Worm.Win32`, `Worm.AutoRun`
- **Backdoors**: Provides remote access to attackers
    - Examples: `Backdoor.Linux.Generic`, `RAT.Win32`
- **Exploits**: Takes advantage of software vulnerabilities
    - Examples: `Exploit.CVE-2021-12345`, `Exploit.PDF`
- **Downloaders/Droppers**: Downloads additional malware
    - Examples: `Downloader.Generic`, `Dropper.Win32`
- **Keyloggers**: Records keyboard input to steal credentials
    - Examples: `Keylogger.Win32`, `Spyware.KeyLog`

**What they can do**:

- Steal passwords and personal information
- Download more malware to your system
- Give hackers remote control of your computer
- Spread to other computers on your network
- Monitor your activities and communications

**Recommended action**:

1. **Quarantine the file** - Isolate the threat
2. **Run a full system scan** - Check for related infections
3. **Review recent downloads** - Identify the source
4. **Update software** - Patch exploited vulnerabilities

**🟡 MEDIUM (Yellow Badge)**

Concerning threats that warrant investigation.

**Threat types**:

- **Adware**: Displays unwanted advertisements
    - Examples: `Adware.Generic`, `PUA.Adware.Win32`
- **PUA/PUP**: Potentially Unwanted Applications/Programs
    - Examples: `PUA.Win.Generic`, `PUP.Optional.Toolbar`
- **Spyware**: Monitors activities and collects information
    - Examples: `Spyware.Win32`, `Monitor.Generic`
- **Miners**: Uses your computer to mine cryptocurrency
    - Examples: `CoinMiner.Win32`, `Miner.Linux`
- **Unknown threats**: Threats not matching specific patterns
    - Examples: `Generic.Suspicious`, `Unknown.Malware`

**What they can do**:

- Slow down your computer (especially miners)
- Display annoying ads and pop-ups
- Track your browsing habits
- Modify browser settings and search engines
- Consume resources for cryptocurrency mining
- Collect data for marketing purposes

**Recommended action**:

1. **Review the file** - Is it something you intentionally installed?
2. **Check if it's a false positive** - See [FAQ](faq.md)
3. **Quarantine if unsure** - Better safe than sorry
4. **Uninstall related software** - Remove the source application

**🔵 LOW (Blue Badge)**

Minor issues and test files that pose little to no real danger.

**Threat types**:

- **EICAR test signatures**: Industry-standard antivirus test files
    - Examples: `Eicar-Signature`, `Test.File.EICAR`
- **Heuristic detections**: Behavior-based suspicious patterns
    - Examples: `Heuristic.Generic`, `Suspicious.Behavior`
- **Generic detections**: Very broad pattern matches
    - Examples: `Generic.Low`, `Possible.Threat`
- **Test files**: Created intentionally for testing
    - Examples: `Test-Signature`, `Sample.Test`

**What they are**:

- Harmless test files (EICAR)
- Files that "look suspicious" but may be safe
- Overly broad matches that catch legitimate software
- Test malware samples (if you're a security researcher)

**Recommended action**:

1. **Don't panic** - These are usually safe
2. **Verify the file purpose** - Why do you have this file?
3. **For EICAR**: This confirms your antivirus works - you can delete it
4. **For heuristics**: Check if it's a known program
5. **Quarantine if unknown** - Or delete if it's just a test file

#### Severity Classification Examples

Here are real-world examples showing how ClamUI classifies different threat names:

| Threat Name              | Severity | Category   | Reasoning             |
|--------------------------|----------|------------|-----------------------|
| `Ransom.WannaCry`        | CRITICAL | Ransomware | Ransomware = critical |
| `Win.Rootkit.Generic`    | CRITICAL | Rootkit    | Rootkit = critical    |
| `Trojan.Agent.Win32`     | HIGH     | Trojan     | Trojan = high         |
| `Worm.AutoRun.VBS`       | HIGH     | Worm       | Worm = high           |
| `Backdoor.Linux.Generic` | HIGH     | Backdoor   | Backdoor = high       |
| `Exploit.CVE-2021-1234`  | HIGH     | Exploit    | Exploit = high        |
| `PUA.Win.Adware.Generic` | MEDIUM   | Adware     | Adware = medium       |
| `Spyware.KeyLogger`      | HIGH     | Spyware    | Keylogger = high      |
| `CoinMiner.Linux.XMRig`  | MEDIUM   | Miner      | Miner = medium        |
| `Eicar-Test-Signature`   | LOW      | Test       | EICAR = low           |
| `Heuristic.Suspicious`   | LOW      | Heuristic  | Heuristic = low       |

#### Severity Limitations and False Positives

**Important notes about severity classification**:

- ⚠️ **Severity is based on the threat name only**: ClamUI can't analyze the actual malware behavior
- ⚠️ **New threats**: Very new malware might get generic names and lower severity ratings
- ⚠️ **False positives**: Legitimate software can be flagged incorrectly
- ⚠️ **Platform matters**: A Windows virus on Linux can't execute (but should still be removed)

**When severity might be misleading**:

- Generic detections: `Generic.Trojan` might be critical or might be benign
- Test files: Security researchers might have high-severity test samples that are safely contained
- Cross-platform threats: Windows malware on Linux isn't immediately dangerous but should be quarantined

**Always use your judgment**: Severity is a guide, not a definitive risk assessment. When in doubt, quarantine the file
and research the threat name online.

### Command-Line Scanning

ClamUI also ships a headless scanner for scripts and terminals:

```
clamui scan PATH [PATH ...]
```

Useful options:

- `--no-recursive` — do not descend into directories
- `--profile NAME` / `-p NAME` — apply a saved profile's exclusion patterns
- `--quarantine` / `-q` — automatically quarantine detected threats
- `--json` — emit machine-readable JSON
- `--verbose` / `-v` — print the ClamAV version and extra detail

The command exits `0` when clean, `1` when threats are found, and `2` on error — the same codes ClamAV uses. Run
`clamui help` for the full subcommand list.

---

---

