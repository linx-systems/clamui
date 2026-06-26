# Getting Started with ClamUI

[← Back to User Guide](../USER_GUIDE.md)

---

## Getting Started

### Launching ClamUI

After installing ClamUI using your preferred method, you can launch it in several ways:

**From your Application Menu:**

- Look for "ClamUI" in your desktop's application launcher
- On GNOME, press the Super key and type "ClamUI"
- The application appears with a shield icon

**From the Terminal:**

If you installed via Flatpak:

```bash
flatpak run io.github.linx_systems.ClamUI
```

If you installed via .deb package or from source:

```bash
clamui
```

If you installed the AppImage:

```bash
./ClamUI-*.AppImage
```

**With Files to Scan:**

You can also launch ClamUI with files or folders to scan immediately:

```bash
# Flatpak
flatpak run io.github.linx_systems.ClamUI /path/to/file /path/to/folder

# Native installation
clamui /path/to/file /path/to/folder
```

When launched with file arguments, ClamUI will open with those paths pre-loaded in the scan view.

### First-Time Setup

When you first launch ClamUI, the application will:

1. **Check for ClamAV Installation**
    - ClamUI requires ClamAV (the antivirus engine) to be installed on your system
    - All distributions (Flatpak, .deb, and AppImage) rely on ClamAV installed on the host system; none bundle the engine
    - If ClamAV is not found, you'll see a warning message with installation instructions
    - See the [Troubleshooting](troubleshooting.md#clamav-not-found) section if you encounter this issue

2. **Create Default Scan Profiles**
    - ClamUI automatically creates three useful scan profiles:
        - **Quick Scan**: Fast scan of the Downloads folder for quick threat detection
        - **Full Scan**: Comprehensive system-wide scan (root filesystem with exclusions)
        - **Home Folder**: Scans your home directory with common exclusions
    - You can customize these or create your own profiles later

3. **Set Up Configuration Directories**
    - Settings are saved to `~/.config/clamui/`
    - Scan logs and quarantine data are stored in `~/.local/share/clamui/`
    - These directories are created automatically

**Updating Virus Definitions**

Before your first scan, it's important to ensure your virus definitions are up to date:

1. Open the **Database** view from the sidebar (or press `Ctrl+2`)
2. Click the **Update Database** button
3. Wait for the update to complete (this may take a few minutes on first run)
4. You'll see a success message when definitions are current

💡 **Tip**: ClamUI can check for database updates automatically.
See [Database Update Settings](settings.md#database-update-settings) to enable auto-updates.

### Understanding the Main Window

ClamUI uses a clean, modern interface that follows GNOME design guidelines. Here's what you'll see when you open the
application:

**Header Bar (Top)**

The header bar contains quick actions and controls:

- **Scan File / Scan System** buttons for quick one-click scanning
- **Menu Button** (right side): Access Preferences, About, and Quit

**Navigation Sidebar (Left)**

ClamUI uses a GNOME Settings-style sidebar for navigation between seven views:

- **Scan**: Main scanning interface (default view)
- **Database**: Update virus definitions
- **Logs**: Browse scan history
- **Components**: Check ClamAV installation status
- **Quarantine**: Manage isolated threats
- **Statistics**: View protection statistics and scan activity
- **Audit**: System security posture assessment

On narrow windows, the sidebar collapses and a back button appears in the header bar.

**Content Area (Center)**

The main content area displays the currently selected view.

### Navigating Between Views

Switching between different parts of ClamUI is simple and intuitive.

**Using the Navigation Sidebar**

The sidebar on the left lets you quickly jump to any view:

1. Click any sidebar item to switch to that view
2. The active view is highlighted in the sidebar
3. The content area updates immediately to show the selected view

**Keyboard Shortcuts**

ClamUI supports keyboard shortcuts for faster navigation:

| Shortcut | Action                    |
|----------|---------------------------|
| `Ctrl+1` | Switch to Scan View       |
| `Ctrl+2` | Switch to Update View     |
| `Ctrl+3` | Switch to Logs View       |
| `Ctrl+4` | Switch to Components View |
| `Ctrl+5` | Switch to Quarantine View |
| `Ctrl+6` | Switch to Statistics View |
| `Ctrl+7` | Switch to Audit View      |
| `Ctrl+S` | Start Scan                |
| `Ctrl+U` | Start Database Update     |
| `Ctrl+Q` | Quit ClamUI              |
| `Ctrl+,` | Open Preferences          |

Shortcuts work from any view and automatically switch to the relevant view.

**View-Specific Navigation**

Some views have additional navigation within them:

- **Scan View**: Pick a scan profile or add files and folders as targets
- **Logs View**: Filter and search through scan history
- **Statistics View**: Change timeframe filters (Day, Week, Month, All Time)

**Returning to the Scan View**

Click the "Scan" item in the sidebar or press `Ctrl+1` to return to the main scanning interface.

### Your First Scan

Ready to scan for viruses? This walkthrough will guide you through running your very first scan with ClamUI. We'll show
you how to select what to scan, understand what's happening during the scan, and interpret the results.

#### Selecting Files and Folders

ClamUI gives you several ways to choose what to scan. Pick the method that works best for you:

**Method 1: Adding Files and Folders**

This is the most straightforward approach:

1. Look for the **Scan Targets** section in the main view
2. Click the **Add files** button (document icon) or the **Add folders** button (folder icon) in the section's header
3. A file picker dialog will appear ("Select Files" or "Select Folders")
4. Navigate to the file(s) or folder(s) you want to scan and select them
5. Confirm your choice; you can add several targets at once
6. Selected targets appear in the list below — use **Clear All** to start over

💡 **What should I scan first?** Start with your Downloads folder - it's where files from the internet arrive and is most
likely to contain threats.

**Method 2: Drag and Drop**

For quick scanning, you can simply drag files or folders into ClamUI:

1. Open your file manager (Files, Nautilus, etc.)
2. Locate the file or folder you want to scan
3. Drag it into the ClamUI window
4. Drop it anywhere in the scan view
5. The path will be automatically selected

**Visual Feedback**: When dragging over ClamUI, you'll see a highlighted border indicating it's ready to accept your
files.

**Method 3: Using Scan Profiles** (Recommended for beginners)

Scan profiles are pre-configured scan targets that make scanning even easier:

1. Look for the **Scan Profile** section at the top
2. Click the dropdown menu (it says "No Profile (Manual)" by default)
3. Choose one of the default profiles:
    - **Quick Scan**: Fast scan of the Downloads folder
    - **Full Scan**: Comprehensive system-wide scan (root filesystem with exclusions)
    - **Home Folder**: Scans your home directory with common exclusions
4. The scan target will be automatically set when you select a profile

💡 **Tip**: For your first scan, try "Quick Scan" - it's fast and covers the most important areas.

**Method 4: Command-Line Arguments** (Advanced)

If you're comfortable with the terminal, you can launch ClamUI with a path already selected:

```bash
# Flatpak
flatpak run io.github.linx_systems.ClamUI ~/Downloads

# Native installation
clamui ~/Downloads
```

This method is great for integrating ClamUI with other tools or file managers.

#### Understanding Scan Progress

Once you've selected what to scan, you're ready to start. Here's what to expect:

**Starting the Scan**

1. Click the **Start Scan** button (the large blue button)
2. You'll immediately see changes in the interface:
    - The Start Scan and EICAR Test buttons become disabled (grayed out)
    - The Scan Targets controls are disabled so the target list can't change mid-scan
    - A **Cancel** button appears, and live progress is shown
    - A scanning status message is displayed while the scan runs

**During the Scan**

While ClamUI is scanning:

- **Be patient**: Scanning can take time, especially for large folders or if you have many files
- **Stopping early**: Click the **Cancel** button to stop a scan in progress; closing the window also stops it
- **Watch the status**: The status message at the bottom will show "Scanning..." until complete
- **System usage**: You may notice increased CPU usage - this is normal as ClamAV analyzes files

**How long will it take?**

Scan duration depends on:

- **Number of files**: More files = longer scan time
- **File sizes**: Large files take longer to analyze
- **Scan backend**: Daemon (clamd) is faster than standalone clamscan
- **System resources**: Faster CPU = faster scanning

Typical scan times:

- Downloads folder (100-500 files): 10-30 seconds
- Home directory (10,000+ files): 2-10 minutes
- Full system scan: 15-60+ minutes

💡 **Tip**: While your first scan runs, feel free to read ahead in this guide to learn about other features!

**Scan Completion**

When the scan finishes:

- All buttons become active again
- The status message updates with results
- If threats were found, click **View Results (N)** to open the Scan Results dialog
- If no threats were found, you'll see a success message

#### Interpreting Scan Results

After your scan completes, ClamUI displays clear, easy-to-understand results. Let's break down what you'll see:

**Clean Scan (No Threats Found)**

If your files are clean, you'll see:

```
✓ Scan complete: No threats found (XXX files scanned)
```

This green success message means:

- All scanned files are safe
- No viruses, trojans, or malware were detected
- You can continue using your files normally

The number in parentheses shows how many files were examined.

**Threats Detected**

If ClamUI finds threats, you'll see:

```
⚠ Scan complete: X threat(s) found
```

This red warning message is followed by a detailed list of each threat found. Don't panic - ClamUI gives you all the
information and tools you need to handle threats safely.

**Understanding Threat Details**

Each detected threat is displayed in a card showing:

1. **Threat Name** (large text at the top)
    - The technical name of the virus or malware
    - Example: "Eicar-Signature", "Win.Test.EICAR_HDB-1"
    - This name is used by antivirus databases worldwide

2. **Severity Badge** (colored label on the right)
    - **CRITICAL** (red): Dangerous malware, immediate action required
    - **HIGH** (orange): Serious threats, should be quarantined
    - **MEDIUM** (yellow): Moderate concern, investigate further
    - **LOW** (blue): Minor issues or test files

3. **File Path** (monospaced text, second line)
    - The exact location of the infected file
    - You can select and copy this text
    - Example: `/home/username/Downloads/suspicious_file.exe`

4. **Category** (if available)
    - The type of threat detected
    - Examples: "Trojan", "Test", "Malware", "PUA" (Potentially Unwanted Application)

5. **Action Buttons** (bottom of each card)
    - **Quarantine**: Safely isolates the threat file
    - **Exclude**: Adds the file's path to your exclusion patterns
    - **Copy Path**: Copies the file path to your clipboard

**What Should I Do With Detected Threats?**

Here's your action plan:

1. **Don't panic** - ClamUI has already identified the threat and prevented any harm
2. **Review the threat details** - Check the file path to understand what was flagged
3. **Click "Quarantine"** - This safely moves the file to isolation where it can't cause harm
4. **Verify it's not a false positive** - Sometimes legitimate files are mistakenly flagged (see FAQ)

**For most users**: Click "Quarantine" on any detected threats. You can always restore files later if needed.

**Testing With EICAR**

Not sure if ClamUI is working correctly? Use the built-in test feature:

1. Click the **EICAR Test** button next to the Start Scan button
2. ClamUI creates a harmless test file that all antivirus software recognizes
3. The scan runs automatically and should find the test "threat"
4. You'll see a detection for "Eicar-Signature" or similar
5. This confirms ClamUI is working properly

**Important**: EICAR is NOT real malware - it's an industry-standard test pattern that's completely safe. It exists only
to test antivirus software.

**Understanding Large Result Sets**

If a scan finds many threats (50+), ClamUI uses smart pagination:

- Only the first 25 threats are shown initially
- A **"Show More"** button appears at the bottom
- Click it to load 25 more threats at a time
- This keeps the interface responsive even with hundreds of detections

**Next Steps After Your First Scan**

Congratulations on completing your first scan! Now you can:

- **Explore scan profiles** - Try the Quick Scan, Full Scan, or Home Folder profiles
- **Set up scheduled scans** - Automate scanning to run regularly
- **Check the quarantine** - Review what's been isolated
- **View scan history** - See all your past scans in the Logs view
- **Customize settings** - Configure ClamUI to match your preferences

Ready to learn more? Continue reading to discover all of ClamUI's powerful features!

---

