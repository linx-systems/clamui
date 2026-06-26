# Scheduled Scans

[← Back to User Guide](../USER_GUIDE.md)

---

## Scheduled Scans

Set up automatic virus scanning to protect your system without manual intervention. ClamUI's scheduled scans run in the
background at your chosen times, keeping your computer safe while you work.

### Why Use Scheduled Scans?

Scheduled scans provide continuous protection by automatically scanning your system at regular intervals.

**Key Benefits**:

1. **Automatic Protection**: Scans run without manual intervention
2. **Consistent Coverage**: Regular scanning catches threats quickly
3. **Flexible Scheduling**: Choose when scans run to avoid interrupting work
4. **Battery-Aware**: Automatically skip scans on laptops when unplugged
5. **Auto-Quarantine**: Optionally isolate threats immediately when found

**Common Use Cases**:

- **Daily Downloads Scan**: Check your Downloads folder every evening for threats
- **Weekly Home Scan**: Scan your home directory every Sunday night
- **Monthly Full Scan**: Deep scan of your entire system once per month
- **USB Drive Scanning**: Regular scans of external drives when connected
- **After Hours Scanning**: Heavy scans during lunch breaks or overnight

💡 **Tip**: Schedule scans during low-activity periods (early morning, lunch, overnight) to minimize system impact.

---

### Enabling Automatic Scanning

Configure scheduled scans through the Preferences window.

#### Opening Scheduled Scans Settings

1. Click the **menu button** (☰) in the header bar
2. Select **Preferences**
3. Navigate to **Scheduled Scans** page (on the left sidebar)

The Scheduled Scans page contains all configuration options:

```
┌─────────────────────────────────────────────────┐
│ Scheduled Scans Configuration                   │
├─────────────────────────────────────────────────┤
│ ⚙ Enable Scheduled Scans              [Toggle] │
│   Run automatic scans at specified intervals    │
│                                                  │
│ 📅 Scan Frequency             [Daily ▼]         │
│ 🕐 Scan Time                  [02:00]           │
│ 📁 Scan Targets               [~/]              │
│ 🔋 Skip on Battery             [✓]              │
│ 🔒 Auto-Quarantine            [ ]               │
└─────────────────────────────────────────────────┘
```

#### Enabling Scheduled Scans

1. Open the **Scheduled Scans** page in Preferences
2. Toggle **Enable Scheduled Scans** to ON
3. Configure your preferences (frequency, time, targets - see sections below)
4. Click **Save & Apply** at the bottom of the Preferences window
5. Close Preferences

**What happens when you enable**:

- ClamUI creates a user-level scheduled task (systemd user timer or cron job)
- The schedule persists across system restarts
- Scans run even when the ClamUI GUI is closed
- You receive desktop notifications when scans complete

#### Disabling Scheduled Scans

1. Open the **Scheduled Scans** page in Preferences
2. Toggle **Enable Scheduled Scans** to OFF
3. Click **Save & Apply**

**What happens when you disable**:

- The user-level scheduled task is removed
- No automatic scans will run
- Existing scan history is preserved
- You can still run manual scans anytime

⚠️ **Important**: You must click **Save & Apply** for changes to take effect. Simply toggling the switch is not enough.

---

### Choosing Scan Frequency

Select how often scheduled scans should run.

#### Available Frequencies

**Hourly** - Scans run every hour on the hour (e.g., 1:00, 2:00, 3:00)

- **Best for**: Critical systems requiring frequent checks
- **Use case**: Servers or public computers handling many downloads
- **System impact**: High - scans run 24 times per day
- **Duration**: Only suitable for small scan targets (Downloads folder)
- **Recommendation**: Use sparingly; usually too frequent for desktops

**Daily** - Scans run once per day at your specified time

- **Best for**: Most users and typical protection needs
- **Use case**: Daily Downloads folder scans, evening home directory scans
- **System impact**: Low - single scan per day
- **Duration**: 2-30 minutes depending on targets
- **Recommendation**: ✅ **Recommended for most users**

**Weekly** - Scans run once per week on your chosen day

- **Best for**: Larger scan jobs like full home directory scans
- **Use case**: Weekend full scans, weekly document folder checks
- **System impact**: Very low - single scan per week
- **Duration**: 10-60 minutes depending on targets
- **Recommendation**: Good for comprehensive scans without daily overhead

**Monthly** - Scans run once per month on your chosen day

- **Best for**: Full system scans and comprehensive checks
- **Use case**: Complete system scan on the 1st of each month
- **System impact**: Minimal - single scan per month
- **Duration**: 30-120+ minutes for full system scan
- **Recommendation**: Good for thorough monthly security audits

#### Selecting Frequency

1. Open **Preferences** → **Scheduled Scans**
2. Click the **Scan Frequency** dropdown
3. Select your desired frequency:
    - Hourly
    - Daily
    - Weekly
    - Monthly
4. Configure additional settings based on frequency (see next section)
5. Click **Save & Apply**

**Frequency-Specific Settings**:

| Frequency | Additional Settings             | Notes                         |
|-----------|---------------------------------|-------------------------------|
| Hourly    | None                            | Runs at :00 of every hour     |
| Daily     | Scan Time (HH:MM)               | Choose what time to run       |
| Weekly    | Day of Week + Scan Time         | Choose day (Mon-Sun) and time |
| Monthly   | Day of Month (1-28) + Scan Time | Choose day (1-28) and time    |

💡 **Tip**: Start with **Daily** scans of your Downloads folder, then add **Weekly** home scans if needed.

---

### Setting Scan Times

Configure when your scheduled scans run.

#### Understanding Scan Time

**Format**: 24-hour time (HH:MM)

- `02:00` = 2:00 AM
- `14:30` = 2:30 PM
- `23:45` = 11:45 PM

**Default**: `02:00` (2:00 AM)

**Applies to**: Daily, Weekly, and Monthly scans (Hourly scans always run at :00)

#### Choosing the Best Time

**Early Morning (2:00 - 6:00 AM)** ✅ Recommended

- **Pros**: Computer likely idle, scans complete before work starts
- **Cons**: Computer must be on (or wake-on-timer configured)
- **Best for**: Desktop computers left on overnight
- **Example**: `02:00` for minimal interference

**Evening (19:00 - 23:00)**

- **Pros**: Computer still on, scans during low-activity evening
- **Cons**: May slow down evening browsing/entertainment
- **Best for**: Laptops that aren't left on overnight
- **Example**: `20:00` after dinner

**Lunch/Break Times (12:00 - 14:00)**

- **Pros**: Minimal work disruption during lunch
- **Cons**: Computer must be on and awake
- **Best for**: Work computers with regular lunch breaks
- **Example**: `12:30` during lunch hour

**After Hours (18:00 - 22:00)**

- **Pros**: Work is done, computer still on
- **Cons**: May interfere with personal computer use
- **Best for**: Work-only computers
- **Example**: `18:15` just after work hours

#### Setting the Time

1. Open **Preferences** → **Scheduled Scans**
2. Find the **Scan Time** field
3. Enter time in 24-hour format (e.g., `02:00`, `14:30`, `20:00`)
4. Click **Save & Apply**

**Valid Time Formats**:

- ✅ `02:00` - Correct (2:00 AM)
- ✅ `14:30` - Correct (2:30 PM)
- ✅ `23:59` - Correct (11:59 PM)
- ❌ `2:00` - Missing leading zero
- ❌ `14:30:45` - Seconds not supported
- ❌ `2:00 PM` - 12-hour format not supported

⚠️ **Important**: Your computer must be powered on at the scheduled time for scans to run. Most laptops don't support
wake-on-timer by default.

#### Day of Week (Weekly Scans)

For weekly scans, choose which day the scan runs:

1. Set **Scan Frequency** to **Weekly**
2. Click the **Day of Week** dropdown
3. Select your preferred day:
    - Monday
    - Tuesday
    - Wednesday
    - Thursday
    - Friday
    - Saturday ✅ Recommended for home users
    - Sunday ✅ Recommended for home users
4. Set your preferred **Scan Time**
5. Click **Save & Apply**

**Recommendation**: Weekend days (Saturday/Sunday) at early morning hours (e.g., Sunday 02:00).

#### Day of Month (Monthly Scans)

For monthly scans, choose which day of the month the scan runs:

1. Set **Scan Frequency** to **Monthly**
2. Use the **Day of Month** spinner to select a day (1-28)
3. Set your preferred **Scan Time**
4. Click **Save & Apply**

**Day Range**: 1-28 only (ensures scan runs every month, even February)

**Common Choices**:

- **1st of month**: Start each month with a clean scan
- **15th of month**: Mid-month comprehensive check
- **Last week**: Use day 28 for near-end-of-month scans

💡 **Tip**: Choose day 1 (first of month) for easy-to-remember monthly scans.

---

### Configuring Scan Targets

Specify which files and folders to scan automatically.

#### Understanding Scan Targets

**Scan targets** are the paths that ClamUI will scan during scheduled scans.

**Target Format**:

- Comma-separated list of paths
- Example: `/home/user/Downloads, /home/user/Documents`
- Example: `~/Downloads, ~/Documents` (tilde ~ = your home directory)

**Default Target**: Your home directory (`~` or `/home/username`)

**How Scanning Works**:

- Each target is scanned **recursively** (includes all subdirectories)
- Multiple targets are scanned sequentially (one after another)
- Scan duration depends on total size and file count across all targets

#### Recommended Scan Targets

**Downloads Folder Only** - ✅ Recommended for daily scans

```
~/Downloads
```

- **Scan time**: 10-30 seconds (typical)
- **File count**: 50-200 files
- **Best for**: Daily scans to catch threats quickly
- **Why**: Most threats arrive via downloads

**Home Directory** - Good for weekly scans

```
~
```

- **Scan time**: 10-30 minutes (typical)
- **File count**: 50,000-200,000 files
- **Best for**: Weekly comprehensive scans
- **Why**: Covers all user data without system files

**Multiple Specific Folders** - Customized protection

```
~/Downloads, ~/Documents, ~/Pictures
```

- **Scan time**: Varies by folder size
- **File count**: Varies
- **Best for**: Targeted scanning of important folders
- **Why**: Focus on data you care about

**Full System** - For monthly deep scans

```
/
```

- **Scan time**: 30-120+ minutes
- **File count**: 500,000+ files
- **Best for**: Monthly full system audits
- **Why**: Complete system coverage
- ⚠️ **Warning**: Very slow, only suitable for monthly scans

**External Drives** - Monitor USB drives and backups

```
/media/username/USB-Drive, ~/Backups
```

- **Scan time**: Varies by drive size
- **File count**: Varies
- **Best for**: Regular checks of external media
- **Why**: USB drives are common malware vectors
- ⚠️ **Note**: Drive must be connected at scan time

💡 **Tip**: For drives that aren't connected at the scheduled time, ClamUI can also scan USB/removable media **automatically when they're plugged in** — a separate feature configured in **Preferences** → **Device Scan** (see the [Settings guide](settings.md)).

#### Setting Scan Targets

1. Open **Preferences** → **Scheduled Scans**
2. Find the **Scan Targets** field
3. Enter your target paths, separated by commas:
    - Use full paths: `/home/user/Downloads, /home/user/Documents`
    - Or use tilde shortcuts: `~/Downloads, ~/Documents`
    - Or mix both: `~/Downloads, /media/usb`
4. Click **Save & Apply**

**Path Tips**:

- ✅ Use `~` for home directory (portable across users)
- ✅ Separate multiple paths with commas
- ✅ Both absolute and relative paths work
- ❌ Don't include quotes around paths
- ❌ Don't use wildcards (* or ?)

**Example Configurations**:

| Use Case          | Frequency      | Targets                                | Rationale                             |
|-------------------|----------------|----------------------------------------|---------------------------------------|
| Basic protection  | Daily          | `~/Downloads`                          | Catch threats as they arrive          |
| Home user         | Daily + Weekly | `~/Downloads` (daily)<br>`~` (weekly)  | Daily quick scans + weekly full scans |
| Privacy-conscious | Weekly         | `~/Downloads, ~/Documents, ~/Pictures` | Skip browser cache and config files   |
| Developer         | Daily          | `~/Downloads, ~/projects`              | Protect code and downloads            |
| Server admin      | Daily          | `/var/www, /home`                      | Web files and user directories        |

💡 **Recommendation**: Start with `~/Downloads` for daily scans. Add more targets only if needed.

---

### Battery-Aware Scanning

Automatically skip scans when your laptop is running on battery power.

#### What is Battery-Aware Scanning?

**Battery-aware scanning** checks your laptop's power status before running scheduled scans:

- **Plugged in (AC power)**: Scan runs normally
- **On battery (unplugged)**: Scan is skipped to save battery life

**Default**: Enabled (Skip on Battery = ON)

**Applies to**: Laptops and devices with batteries (desktops always run scans)

#### How It Works

When a scheduled scan is triggered:

1. **Check power status**: Is the laptop plugged in?
2. **If plugged in**: Run the scan normally
3. **If on battery**: Skip the scan and log the skip event
4. **Next schedule**: The scan will try again at the next scheduled time

**What happens when skipped**:

- A log entry is created: "Scheduled scan skipped (on battery power)"
- No notification is shown (to avoid interruptions)
- The scan is **not rescheduled** - it waits until the next normal schedule
- Battery percentage is recorded in the log

**Example scenario**:

- You schedule daily scans at 2:00 AM
- Your laptop is unplugged at night
- Scan is skipped on Monday night (on battery)
- Scan runs on Tuesday night (plugged in while charging)

#### When to Use Battery-Aware Scanning

**Enable "Skip on Battery" (✓)** - ✅ Recommended

Good for:

- Laptops used unplugged frequently
- Battery life is a priority
- You charge overnight regularly
- Casual home use

Benefits:

- Preserves battery life
- Reduces CPU load when unplugged
- Scans still run when plugged in
- No performance impact during mobile use

**Disable "Skip on Battery" ( )** - Force scans even on battery

Good for:

- Critical systems requiring guaranteed scans
- Laptops plugged in most of the time
- Security is more important than battery life
- Desktop computers (no battery to preserve)

Drawbacks:

- Drains battery faster
- May slow down laptop when unplugged
- Increases CPU usage on battery
- Reduces mobile battery life by 10-30 minutes (typical scan)

#### Enabling/Disabling Battery-Aware Scanning

1. Open **Preferences** → **Scheduled Scans**
2. Find the **Skip on Battery** switch
3. **Enable** (✓) to skip scans when on battery (recommended for laptops)
4. **Disable** ( ) to run scans regardless of power status
5. Click **Save & Apply**

**Desktop Computers**:
Desktop computers without batteries are always treated as "plugged in", so this setting has no effect.

#### Checking Battery Skip Events

To see when scans were skipped due to battery:

1. Open the **Logs** view (click Logs in the navigation)
2. Look for log entries with status: "Skipped"
3. Summary will say: "Scheduled scan skipped (on battery power)"
4. Details show battery percentage at skip time

Example log entry:

```
Date: 2026-01-03 02:00
Status: Skipped
Summary: Scheduled scan skipped (on battery power)
Details:
  Battery level: 67%
  Scan skipped due to battery-aware settings.
```

💡 **Tip**: If you notice scans being skipped frequently, consider:

- Scheduling scans during times when you're typically plugged in (evening while working)
- Plugging in your laptop overnight if you schedule early morning scans
- Disabling "Skip on Battery" if scans rarely run

---

### Auto-Quarantine Options

Automatically isolate detected threats without manual intervention.

#### What is Auto-Quarantine?

**Auto-quarantine** automatically moves infected files to quarantine when they're detected during scheduled scans.

**Manual Scans**: Always require manual action (you choose whether to quarantine)

**Scheduled Scans**: Can optionally quarantine automatically with this setting

**Default**: Disabled (Auto-Quarantine = OFF) for safety

#### How Auto-Quarantine Works

**When enabled** and a scheduled scan finds threats:

1. **Scan completes** and identifies infected files
2. **Automatic quarantine**: Each infected file is moved to quarantine storage
3. **Integrity hash**: SHA-256 hash is calculated for each file
4. **Metadata saved**: Original path, threat name, date are recorded
5. **Notification**: You receive a notification with quarantine count
6. **Log entry**: Detailed log shows "X threats found, Y quarantined"

**What gets quarantined**:

- All files detected as infected (regardless of severity)
- Both individual files and files within archives
- Files from all scan targets

**What happens to quarantined files**:

- ✅ Moved to secure quarantine storage (`~/.local/share/clamui/quarantine/`)
- ✅ Isolated from the rest of your system
- ✅ Can be reviewed in the Quarantine view
- ✅ Can be restored if false positive (with hash verification)
- ✅ Can be permanently deleted
- ✅ Auto-cleared after 30 days with "Clear Old Items"

#### Automatic vs Manual Quarantine

| Aspect              | Manual (Default)                                    | Auto-Quarantine (Enabled)                      |
|---------------------|-----------------------------------------------------|------------------------------------------------|
| **Action**          | You review threats and choose whether to quarantine | Threats quarantined immediately                |
| **Notification**    | Shows threat count, requires your review            | Shows threat + quarantine count                |
| **Safety**          | ✅ Safer - you control what's quarantined            | ⚠️ Riskier - false positives quarantined too   |
| **Convenience**     | ❌ Requires manual action                            | ✅ Fully automatic                              |
| **Review**          | Before quarantine                                   | After quarantine (via Logs + Quarantine views) |
| **Best for**        | Users who want control                              | Users who want hands-off protection            |
| **False positives** | You can skip quarantine                             | Automatically quarantined, must restore later  |

#### When to Enable Auto-Quarantine

**Enable Auto-Quarantine (✓)**

Good for:

- Fully automated protection ("set and forget")
- Systems handling untrusted files frequently
- Users who don't want to review every detection
- Downloads folders with high malware risk
- Servers and unattended systems

Benefits:

- Threats are isolated immediately
- No manual intervention required
- Full protection even when you're away
- Automated response to threats

Risks:

- ⚠️ False positives are automatically quarantined
- ⚠️ Important files might be removed without your knowledge
- ⚠️ You must check logs and quarantine view to know what happened

**Disable Auto-Quarantine ( )** - ✅ Recommended for most users

Good for:

- Users who want control over quarantine decisions
- Systems with important files that might trigger false positives
- Users who review scan results regularly
- Development environments (source code might trigger heuristics)
- Document folders with macros or scripts

Benefits:

- ✅ You choose what to quarantine
- ✅ Review each detection before taking action
- ✅ Avoid accidentally quarantining false positives
- ✅ Understand what was detected and why

Drawbacks:

- Requires manual review of scheduled scan results (check Logs view)
- Threats remain in place until you quarantine them manually

#### Enabling/Disabling Auto-Quarantine

1. Open **Preferences** → **Scheduled Scans**
2. Find the **Auto-Quarantine** switch
3. **Enable** (✓) to automatically quarantine all detected threats
4. **Disable** ( ) to require manual review (recommended)
5. Click **Save & Apply**

⚠️ **Important Recommendation**: Start with auto-quarantine **disabled**. Enable it only after:

- Running several scheduled scans to understand what gets detected
- Verifying your scan targets don't trigger frequent false positives
- Understanding how to review and restore files from quarantine

#### Reviewing Auto-Quarantined Files

If you enable auto-quarantine, regularly check what was quarantined:

**Via Logs View** (see what scans found):

1. Open **Logs** view
2. Look for scheduled scan entries (check timestamp matching your schedule)
3. Read the summary: "Scheduled scan found X threats, Y quarantined"
4. Expand the log to see detailed threat information
5. Note: Each threat's name, path, severity, and category

**Via Quarantine View** (see what was quarantined):

1. Open **Quarantine** view
2. Review quarantined files by threat name and original path
3. Check detection date to match scheduled scan times
4. **If false positive**: Restore the file (see Quarantine Management section)
5. **If legitimate threat**: Leave in quarantine or delete permanently

**Notifications** (immediate alerts):

When auto-quarantine runs, you'll receive a notification:

```
┌────────────────────────────────────┐
│ 🔴 Scheduled Scan: Threats Detected│
│                                    │
│ 3 infected files found,            │
│ 3 quarantined                      │
│                                    │
│ 2 minutes ago                      │
└────────────────────────────────────┘
```

Click the notification to open ClamUI and review the scan logs.

💡 **Best Practice**: Check the Logs view once a week to review what scheduled scans found, even with auto-quarantine
enabled.

#### Quarantine Failures

If auto-quarantine is enabled but quarantine fails for some files:

**Possible causes**:

- File no longer exists (deleted between detection and quarantine)
- Insufficient permissions (file owned by root or another user)
- File in use (locked by another application)
- Disk space full (no room for quarantine storage)

**What happens**:

- Scan continues and logs the failure
- Successfully quarantined files are still quarantined
- Failed files remain in their original location ⚠️
- Log entry shows: "Found X threats, Y quarantined, Z failed"

**How to check**:

1. Open **Logs** view
2. Expand the scheduled scan entry
3. Look for "Quarantine Failed" section in details
4. Each failed file is listed with error reason

**How to handle**:

- Manual quarantine: Find the file and quarantine it via a manual scan
- Fix permissions: Change file ownership or permissions
- Delete manually: If it's confirmed malware, delete via terminal with sudo

---

### Managing Scheduled Scans

Monitor, test, and troubleshoot your scheduled scan configuration.

#### Checking Scheduled Scan Status

**Via Preferences** (current configuration):

1. Open **Preferences** → **Scheduled Scans**
2. Check the **Enable Scheduled Scans** switch:
    - ✅ ON = Scheduled scans are active
    - ⚪ OFF = Scheduled scans are disabled
3. Review your current configuration:
    - Frequency, time, targets, battery skip, auto-quarantine

**Via System Commands** (advanced - verify backend):

ClamUI uses your system's scheduler (systemd or cron). To check the backend:

**For systemd (most modern Linux)**:

```bash
# Check if timer is active
systemctl --user is-active clamui-scheduled-scan.timer

# View timer status
systemctl --user status clamui-scheduled-scan.timer

# List all timers to see when next scan runs
systemctl --user list-timers clamui-scheduled-scan.timer
```

**For cron (older systems)**:

```bash
# View your crontab (look for "ClamUI Scheduled Scan")
crontab -l
```

#### Testing Your Schedule

Before relying on scheduled scans, test that they work:

**Option 1: Trigger a Test Scan Manually**

Since scheduled scans use the same `clamui-scheduled-scan` command, you can test it manually:

```bash
# Test with dry-run (shows what would happen without scanning)
clamui-scheduled-scan --dry-run --verbose

# Run a real test scan
clamui-scheduled-scan --verbose
```

This runs the scan immediately with your configured settings and shows verbose output.

**Option 2: Temporarily Change Schedule Time**

1. Note your current schedule time
2. Change it to 2-3 minutes in the future
3. Click **Save & Apply**
4. Wait for the scheduled time
5. Check the **Logs** view for a new scan entry
6. Change time back to your desired schedule
7. Click **Save & Apply** again

**Option 3: Check Logs After First Scheduled Run**

1. Wait until after your first scheduled scan time
2. Open **Logs** view
3. Look for a scan entry matching your scheduled time
4. Verify the scan ran and completed successfully

**What successful scheduled scans look like**:

In the Logs view:

```
📁 Scheduled scan completed - 1,234 files scanned, no threats
   2026-01-03 02:00 • Clean • ~/Downloads

Click to expand:
  Scan Duration: 12.3 seconds
  Files Scanned: 1,234
  Threats Found: 0
  Targets: /home/user/Downloads
```

#### Modifying Your Schedule

To change scheduled scan settings:

1. Open **Preferences** → **Scheduled Scans**
2. Modify any setting:
    - Toggle **Enable Scheduled Scans** to disable entirely
    - Change **Scan Frequency** (hourly/daily/weekly/monthly)
    - Update **Scan Time** (HH:MM in 24-hour format)
    - Edit **Scan Targets** (comma-separated paths)
    - Toggle **Skip on Battery** or **Auto-Quarantine**
3. **Must click Save & Apply** for changes to take effect
4. Close Preferences

⚠️ **Important**: Simply changing values doesn't update the schedule. You **must** click **Save & Apply** for ClamUI to
update the system scheduler.

#### Viewing Scheduled Scan History

All scheduled scans are logged separately from manual scans:

1. Open the **Logs** view
2. Look for scan entries matching your scheduled time
3. Scheduled scans show:
    - 📁 Folder icon
    - Timestamp matching your schedule (e.g., 02:00, 14:00)
    - "Scheduled scan" in the summary
4. Click an entry to see full details

**Identifying scheduled vs manual scans**:

- Scheduled scans have precise times matching your schedule (02:00, not 02:03)
- Summary explicitly says "Scheduled scan..."
- Internal metadata marks them as `scheduled=true` (not visible in UI)

#### Troubleshooting Scheduled Scans

**Problem: Scans aren't running at scheduled time**

Possible causes and solutions:

| Cause                                | How to Check                                        | Solution                                              |
|--------------------------------------|-----------------------------------------------------|-------------------------------------------------------|
| Schedule not enabled                 | Check Preferences → Scheduled Scans → Enable switch | Toggle ON and click Save & Apply                      |
| Forgot to click "Save & Apply"       | Check system timer (see commands above)             | Go to Preferences and click Save & Apply              |
| Computer is off at scheduled time    | Check if computer is on during schedule             | Change schedule time or leave computer on             |
| On battery (Skip on Battery enabled) | Check Logs for "skipped" entries                    | Disable Skip on Battery or plug in at scheduled time  |
| Systemd/cron not available           | Run test commands (see above)                       | Check system logs, may need systemd or cron installed |
| No scan targets configured           | Check Preferences → Scan Targets field              | Add at least one valid path                           |
| Invalid scan target paths            | Check Logs for error entries                        | Fix paths in Preferences (use ~ or full paths)        |

**Problem: No notification shown after scheduled scan**

Possible causes:

- Notifications disabled in ClamUI Preferences
- Notifications disabled at system level
- Desktop notification service not running
- Scan ran while you were logged out

Solutions:

- Check **Preferences** → ensure notifications are enabled
- Check **Logs** view - scan logs are always recorded even without notifications
- Test notification system: `notify-send "Test" "This is a test"`

**Problem: Scheduled scan found threats but didn't quarantine**

Possible causes:

- Auto-Quarantine is disabled (this is normal and expected)
- Quarantine failed due to permissions or disk space

Solutions:

- If auto-quarantine disabled: Review Logs, then manually scan and quarantine
- If auto-quarantine enabled: Check Logs for "Quarantine Failed" section
- Fix permissions or free disk space, then re-scan manually

**Problem: Can't save scheduled scan settings (permission error)**

This shouldn't happen for scheduled scans (they don't require root), but if you see errors:

Solutions:

- Check that ~/.config/systemd/user/ directory exists: `mkdir -p ~/.config/systemd/user`
- Verify you have write permissions: `ls -ld ~/.config/systemd/user`
- Check disk space: `df -h ~`
- Try creating the schedule via terminal (see command-line option below)

#### Command-Line Scheduled Scan (Advanced)

For advanced users, you can run scheduled scans manually or customize further:

**Basic manual execution**:

```bash
clamui-scheduled-scan
```

**With options**:

```bash
# Scan specific targets
clamui-scheduled-scan --target ~/Downloads --target ~/Documents

# Skip scan if on battery
clamui-scheduled-scan --skip-on-battery

# Auto-quarantine detected threats
clamui-scheduled-scan --auto-quarantine

# Combine options
clamui-scheduled-scan --skip-on-battery --auto-quarantine --target ~/Downloads

# Dry run (test without scanning)
clamui-scheduled-scan --dry-run --verbose

# Verbose output
clamui-scheduled-scan --verbose
```

**Use cases**:

- Testing scheduled scan configuration
- Running scans from custom scripts
- Triggering scans from other automation tools
- Debugging scheduling issues

**Help**:

```bash
clamui-scheduled-scan --help
```

#### Scheduler Backend Information

ClamUI automatically detects and uses the best available scheduler:

**systemd timers** (preferred - modern Linux):

- More reliable and flexible
- Better logging and status checking
- Shows next run time
- Handles missed scans (persistent timers)
- Used by: Ubuntu 16.04+, Fedora, Arch, most modern distros

**cron** (fallback - older systems):

- Traditional Unix scheduler
- Works on older systems
- Less flexible than systemd
- Used by: Systems without systemd, older distributions

**Detection**:
ClamUI automatically detects which is available and uses it transparently. You don't need to choose.

**Which backend am I using?**

Run this command to check:

```bash
# Check for systemd timer
systemctl --user is-active clamui-scheduled-scan.timer 2>/dev/null && echo "Using systemd"

# Check for cron
crontab -l 2>/dev/null | grep -q "ClamUI Scheduled Scan" && echo "Using cron"
```

💡 **Tip**: If neither systemd nor cron is available, you'll see an error when trying to enable scheduled scans. Install
systemd (recommended) or cron to enable this feature.

---

**Scheduled Scans Summary**:

✅ **Do**:

- Start with daily Downloads folder scans
- Use early morning times (2:00-6:00 AM) when computer is idle
- Enable "Skip on Battery" on laptops to preserve battery
- Keep auto-quarantine disabled initially until you understand what gets detected
- Check Logs view weekly to review scheduled scan results
- Test your schedule after setting it up

❌ **Don't**:

- Schedule hourly scans unless absolutely necessary (too frequent)
- Scan entire filesystem (`/`) daily (too slow)
- Enable auto-quarantine without understanding it (risks false positives)
- Forget to click "Save & Apply" after changing settings
- Schedule scans when computer is typically off

💡 **Recommended Setup for Most Users**:

- **Frequency**: Daily
- **Time**: 02:00 (2:00 AM)
- **Targets**: ~/Downloads
- **Skip on Battery**: Enabled (✓)
- **Auto-Quarantine**: Disabled ( )

This provides daily protection of your most vulnerable folder (Downloads) with minimal system impact and maximum control

---

