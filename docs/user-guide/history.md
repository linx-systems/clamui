# Scan History

[← Back to User Guide](../USER_GUIDE.md)

---

## Scan History

ClamUI keeps a detailed history of all your scans and virus definition updates. This allows you to review past
operations, check when you last scanned specific folders, and investigate previous threat detections.

### Viewing Past Scan Results

#### Opening the Scan History View

To access your scan history:

1. Click the **"Logs"** navigation button in the sidebar (document icon)
2. The view opens with two tabs:
    - **Historical Logs** - Past scan and update operations (default)
    - **ClamAV Daemon** - Live logs from the clamd daemon (advanced users)

Make sure you're on the **Historical Logs** tab to view past scans.

#### Understanding the Historical Logs List

The logs list shows all your past operations, with the newest entries at the top:

```
┌─────────────────────────────────────────────────────────────────┐
│ Historical Logs                [↻] [⤓ CSV] [⤓ JSON] [Clear All] │
│ Previous scan and update operations                             │
├─────────────────────────────────────────────────────────────────┤
│  📁 Clean scan of /home/user/Downloads                      ✅  │
│     2024-01-15 14:30 • clean • .../Downloads                    │
├─────────────────────────────────────────────────────────────────┤
│  🔄 Virus database update completed                         ✅  │
│     2024-01-15 09:00 • success                                  │
├─────────────────────────────────────────────────────────────────┤
│  📁 Found 1 threat(s) in /home/user/Documents               ⚠️  │
│     2024-01-14 16:45 • infected • .../Documents                 │
├─────────────────────────────────────────────────────────────────┤
│  📁 Scan error: /mnt/external                               ⚠️  │
│     2024-01-14 12:00 • error • /mnt/external                    │
└─────────────────────────────────────────────────────────────────┘
```

**Entry Components:**

- **Icon**: 📁 for scans, 🔄 for updates
- **Summary**: Brief description of what happened
- **Timestamp**: Date and time of the operation (YYYY-MM-DD HH:MM format)
- **Status**: Operation outcome (clean, infected, success, error, etc.)
- **Path**: Location that was scanned (truncated if long, showing last 40 characters)
- **Status Indicator**: ✅ for successful operations, ⚠️ for warnings/errors

#### Viewing Detailed Log Information

To see the full details of a scan or update:

1. **Click on any log entry** in the list
2. The **Log Details** panel below shows complete information:

```
SCAN LOG
==================================================

ID: 7a3b9f12-4e56-7890-abcd-ef1234567890
Timestamp: 2024-01-15T14:30:45.123456
Type: scan
Status: clean
Path: /home/user/Downloads
Duration: 12.34 seconds

Summary:
  Clean scan of /home/user/Downloads

--------------------------------------------------
Full Output:
--------------------------------------------------
Scanned: 1,234 files, 45 directories
```

**Detail Fields Explained:**

- **ID**: Unique identifier for the log entry (useful for troubleshooting)
- **Timestamp**: Full ISO format timestamp with milliseconds
- **Type**: `scan` (antivirus scan) or `update` (virus definition update)
- **Status**: Operation result
    - `clean` - No threats found
    - `infected` - Threats detected
    - `success` - Update completed successfully
    - `up_to_date` - Virus definitions already current
    - `error` - Operation failed
    - `cancelled` - User cancelled the operation
- **Path**: Full path that was scanned (only for scan operations)
- **Duration**: How long the operation took, in seconds
- **Summary**: Human-readable description
- **Full Output**: Complete details including:
    - File and directory counts
    - List of detected threats (if infected)
    - Error messages (if operation failed)
    - Raw command output

#### List Features and Navigation

**Pagination:**

The logs list displays 25 entries initially to keep the interface responsive. If you have more logs:

1. **"Show More" button** appears at the bottom
    - Click to load the next 25 entries
    - Shows current count: "Showing 25 of 150 logs"
2. **"Show All" button** (appears when more than 25 logs remain)
    - Click to load all remaining logs at once
    - Useful for searching through history

**Empty State:**

If you haven't performed any scans or updates yet, you'll see:

```
     📄
  No logs yet

  Logs from scans and updates will appear here
```

**Refresh:**

Click the **Refresh button** (🔄 icon) in the top-right to reload the log list. Useful after:

- Completing a new scan in another window
- Running scheduled scans
- Clearing logs in another ClamUI instance

**Loading State:**

While logs are loading, you'll see:

```
  ⌛ Loading logs...
```

The refresh button and Clear All button are disabled during loading.

---

### Filtering Scan History

ClamUI automatically sorts your scan history by date, showing the **newest entries first**. This ensures you always see
your most recent scans at the top of the list.

#### Current Filtering Behavior

**Automatic Date Sorting:**

- Logs are sorted by timestamp in descending order (newest to oldest)
- The most recent scan or update always appears at the top
- No manual date filtering is currently available

**Viewing Older Logs:**

Use the pagination buttons to navigate through your history:

1. **Initial view**: Shows your 25 most recent operations
2. **Show More**: Loads the next 25 older entries
3. **Show All**: Displays all historical logs

#### Identifying Log Types

While there's no filter dropdown, you can easily identify log types by their icons:

- **📁 Folder icon** = Scan operation
- **🔄 Update icon** = Virus definition update

#### Finding Specific Scans

To find a particular scan in your history:

1. Look for the **path** in the subtitle (e.g., ".../Downloads")
2. Check the **timestamp** to narrow down by date
3. Check the **status indicator**:
    - ✅ Green checkmark = Clean scan or successful update
    - ⚠️ Warning symbol = Infected scan or error

**Example search workflow:**

> "I want to find when I last scanned my Documents folder for threats..."

1. Scan the list for entries showing ".../Documents" in the subtitle
2. Look for entries with ⚠️ warning indicators (infections)
3. Click the entry to view full details including threat names

💡 **Tip**: If you have many logs, use **Show All** to load everything, then use your browser's find feature (Ctrl+F) to
search through the visible entries.

---

### Understanding Log Entries

#### Log Entry Structure

Every log entry contains both **summary information** (visible in the list) and **detailed information** (shown when
selected).

**Summary Information** (Always Visible):

| Field         | Description           | Example                                 |
|---------------|-----------------------|-----------------------------------------|
| **Icon**      | Visual type indicator | 📁 = scan, 🔄 = update                  |
| **Title**     | Operation summary     | "Clean scan of /home/user/Downloads"    |
| **Timestamp** | When it happened      | "2024-01-15 14:30"                      |
| **Status**    | Operation outcome     | "clean", "infected", "success", "error" |
| **Path**      | Target location       | ".../Downloads" (truncated to 40 chars) |
| **Indicator** | Visual status         | ✅ = success, ⚠️ = warning/error         |

**Detailed Information** (Click to View):

| Field           | Description                     | When Present                 |
|-----------------|---------------------------------|------------------------------|
| **ID**          | Unique UUID                     | Always                       |
| **Timestamp**   | Full ISO timestamp              | Always                       |
| **Type**        | "scan" or "update"              | Always                       |
| **Status**      | Detailed status code            | Always                       |
| **Path**        | Complete file path              | Scan operations only         |
| **Duration**    | Operation time (seconds)        | Always (0.00 if unavailable) |
| **Summary**     | Human-readable description      | Always                       |
| **Full Output** | Complete details and raw output | Always                       |

#### Status Meanings

**Scan Statuses:**

- **`clean`** - ✅ No threats detected
    - All scanned files are safe
    - Example: "Clean scan of /home/user/Downloads"

- **`infected`** - ⚠️ Threats found and logged
    - One or more threats detected
    - View details to see threat list
    - Example: "Found 2 threat(s) in /home/user/Documents"

- **`error`** - ⚠️ Scan failed to complete
    - Could be permission denied, path not found, or ClamAV error
    - Check Full Output for error message
    - Example: "Scan error: /mnt/external"

- **`cancelled`** - ℹ️ User stopped the scan
    - You clicked "Cancel" during scanning
    - Partial results may be available

**Update Statuses:**

- **`success`** - ✅ Database update completed
    - New virus definitions downloaded and installed
    - Example: "Virus database update completed"

- **`up_to_date`** - ✅ Already have latest definitions
    - No update needed
    - Example: "Virus definitions are up to date"

- **`error`** - ⚠️ Update failed
    - Could be network issue, permission denied, or service unavailable
    - Check Full Output for error details

#### Interpreting Full Output

When you select a log entry, the **Full Output** section shows operation-specific details.

**For Clean Scans:**

```
Scanned: 1,234 files, 45 directories
```

- **Files**: Number of individual files checked
- **Directories**: Number of folders traversed
- No threat details (scan was clean)

**For Infected Scans:**

```
Scanned: 567 files, 12 directories
Threats found: 2
  - /home/user/Documents/suspicious.exe: Win.Trojan.Generic-1234
  - /home/user/Downloads/test.pdf: Pdf.Exploit.CVE-2023-12345
```

- Shows file and directory counts
- Lists threat count
- Provides detailed threat information:
    - **Full file path** where threat was found
    - **Threat name** as identified by ClamAV

**For Errors:**

```
Error: Permission denied scanning /root/private
```

or

```
Error: Path not found: /mnt/external/backup
```

- Shows the specific error message
- Helps diagnose why the scan failed

**For Updates:**

```
Database updated successfully
Updated from version 26523 to 26524
```

or simply:

```
Virus definitions are already up to date (version 26524)
```

#### Scheduled vs Manual Scans

Log entries include a hidden `scheduled` flag indicating whether the scan was automatic:

- **Manual scans**: You started them through the UI or command line
- **Scheduled scans**: Automatically run by systemd timer or cron

Currently, both types appear the same in the UI. You can infer scheduled scans by:

- Consistent timestamps (e.g., every day at 9:00 AM)
- Scanning common profile targets (Downloads, Home Folder, Full System)

---

### Exporting Scan Logs

ClamUI lets you export log entries for record-keeping, sharing with IT support, or archival purposes.

#### Export Options

When you select a log entry, four export actions become available:

1. **Copy to Clipboard** - Quick copy for pasting into emails or documents
2. **Export to Text File** - Save as human-readable `.txt` file
3. **Export to CSV File** - Save as spreadsheet-compatible `.csv` file
4. **Export to JSON File** - Save as machine-readable `.json` file

All export buttons are located in the **Log Details** section header.

#### Copying to Clipboard

To quickly copy log details:

1. **Select a log entry** from the list
2. Click the **Copy button** (📋 icon) in the Log Details header
3. A toast notification confirms: "Log details copied to clipboard"
4. **Paste** (Ctrl+V) into any application

**What gets copied:**

The complete text from the Log Details panel, including:

- Header (SCAN LOG or UPDATE LOG)
- All metadata fields (ID, timestamp, status, path, duration)
- Summary
- Full output with separator lines

**Example clipboard content:**

```
SCAN LOG
==================================================

ID: 7a3b9f12-4e56-7890-abcd-ef1234567890
Timestamp: 2024-01-15T14:30:45.123456
Type: scan
Status: infected
Path: /home/user/Downloads
Duration: 12.34 seconds

Summary:
  Found 1 threat(s) in /home/user/Downloads

--------------------------------------------------
Full Output:
--------------------------------------------------
Scanned: 1,234 files, 45 directories
Threats found: 1
  - /home/user/Downloads/test.exe: Win.Trojan.Eicar-Test
```

💡 **Tip**: Use this for quick sharing via email, chat, or support tickets.

#### Exporting to Text File

To save a log entry as a text file:

1. **Select a log entry** from the list
2. Click the **Export to Text** button (💾 icon)
3. A file save dialog appears
4. **Choose a location** and optionally rename the file
    - Default name: `clamui_log_YYYYMMDD_HHMMSS.txt`
    - Example: `clamui_log_20240115_143045.txt`
5. Click **Save**
6. A toast notification confirms: "Log exported to clamui_log_20240115_143045.txt"

**Text File Format:**

The exported `.txt` file contains exactly the same content as the clipboard export:

- Plain text format
- UTF-8 encoding
- Readable in any text editor
- Same structure as displayed in the UI

**Use Cases:**

- Archiving scan results for compliance
- Creating scan reports for documentation
- Sharing with users who need human-readable format

**Export Error Handling:**

| Error                              | Cause                              | Solution                                                                |
|------------------------------------|------------------------------------|-------------------------------------------------------------------------|
| "Permission denied"                | Cannot write to selected location  | Choose a location you have write access to (e.g., Documents, Downloads) |
| "Invalid file path selected"       | Selected a remote/network location | Select a local folder on your computer                                  |
| File dialog closes with no message | Cancelled by clicking "Cancel"     | Normal behavior, try again                                              |

#### Exporting to CSV File

To save a log entry as a CSV file:

1. **Select a log entry** from the list
2. Click the **Export to CSV** button (📊 icon)
3. A file save dialog appears
4. **Choose a location** and optionally rename the file
    - Default name: `clamui_log_YYYYMMDD_HHMMSS.csv`
    - Example: `clamui_log_20240115_143045.csv`
5. Click **Save**
6. A toast notification confirms: "Log exported to clamui_log_20240115_143045.csv"

**CSV File Format:**

The exported CSV file contains a header row and one data row:

| timestamp                  | type | status | path                 | summary                            | duration |
|----------------------------|------|--------|----------------------|------------------------------------|----------|
| 2024-01-15T14:30:45.123456 | scan | clean  | /home/user/Downloads | Clean scan of /home/user/Downloads | 12.34    |

**CSV Characteristics:**

- Standard RFC 4180 CSV format
- UTF-8 encoding
- Proper quoting for fields containing commas
- Opens in Excel, LibreOffice Calc, Google Sheets
- Easy to import into databases or analysis tools

**Use Cases:**

- Importing into spreadsheet software for analysis
- Creating scan history reports with charts
- Bulk processing scan data with scripts
- Compliance reporting requiring structured data

💡 **Tip**: To create a comprehensive scan history CSV with all your logs, you'll need to export each entry individually
and then combine them. The CSV format makes this easy - just copy the data rows (excluding headers) and paste into a
master spreadsheet.

#### Exporting to JSON File

To save a log entry as a JSON file:

1. **Select a log entry** from the list
2. Click the **Export to JSON** button (💾 icon)
3. A file save dialog appears
4. **Choose a location** and optionally rename the file
    - Default name: `clamui_log_YYYYMMDD_HHMMSS.json`
5. Click **Save**
6. A toast notification confirms the export

**JSON File Format:**

The exported `.json` file wraps the log entry with export metadata plus the full
structured fields (id, timestamp, type, status, path, summary, details, duration).
Useful for scripting, archival, or importing into other tools.

#### Exporting Multiple Logs

**Export All Logs at Once:**

The **Historical Logs** header (next to the Refresh and Clear All buttons) provides
two bulk-export buttons that write every log entry currently loaded in the list:

- **Export all logs to CSV** (📊 icon) - one `.csv` file with a header row and one
  row per entry (default name `clamui_logs_YYYYMMDD_HHMMSS.csv`)
- **Export all logs to JSON** (💾 icon) - one `.json` file containing all entries
  with export metadata (default name `clamui_logs_YYYYMMDD_HHMMSS.json`)

Both buttons activate once logs have loaded. They export only the entries currently
displayed, so use **Show All** first if you want your entire history in one file.

**Accessing Logs from the Command Line:**

You can also list history headlessly with the `clamui history` command:

```bash
# Show the 20 most recent entries (default)
clamui history

# Show the 50 most recent entries
clamui history --limit 50

# Filter by type: scan, update, or virustotal
clamui history --type scan

# Machine-readable JSON output
clamui history --type update --json
```

**Direct File Access (Advanced):**

If you need all your scan history:

1. Locate the log storage directory:
    - Default: `~/.local/share/clamui/logs/`
    - Flatpak: `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/logs/` (if applicable)
2. **Copy the entire directory** to your desired backup location
3. Each log is stored as `<UUID>.json` (e.g., `7a3b9f12-4e56-7890-abcd-ef1234567890.json`)
4. Use a script or JSON tools to process these files if needed

**Manual JSON Processing Example:**

```bash
# List all log files
ls ~/.local/share/clamui/logs/

# View a specific log
cat ~/.local/share/clamui/logs/7a3b9f12-4e56-7890-abcd-ef1234567890.json | jq

# Count total logs
ls ~/.local/share/clamui/logs/*.json | wc -l
```

---

### Viewing Daemon Logs (Advanced)

The **ClamAV Daemon** tab shows live logs from the clamd background service. This is useful for troubleshooting
daemon-related issues or monitoring real-time activity.

#### Opening Daemon Logs

1. Navigate to **Logs** view
2. Click the **ClamAV Daemon** tab at the top
3. The daemon status and log viewer appear

#### Understanding Daemon Status

The status row shows clamd's current state:

**🟢 Running:**

- Daemon is active and ready to scan
- Live log updates available
- Example: "Daemon Status: Running"

**⚪ Stopped:**

- Daemon is installed but not running
- Start it with: `sudo systemctl start clamav-daemon`
- Live logs unavailable

**ℹ️ Not installed:**

- clamd package not detected
- ClamUI can still scan using `clamscan` command
- Helpful message explains daemon is optional

**❓ Unknown:**

- Unable to determine daemon status
- May indicate permission issues or system configuration

#### Using Live Log Updates

To view real-time daemon logs:

1. Ensure daemon status shows **"Running"**
2. Click the **Play button** (▶️) to start live updates
    - Button changes to ⏸️ (pause icon)
    - Tooltip changes to "Stop live log updates"
3. Logs refresh automatically every 3 seconds
4. Scroll automatically jumps to newest entries
5. Click **Pause** (⏸️) to stop auto-refresh

**What You'll See:**

```
Mon Jan 15 14:30:01 2024 -> +++ Started at Mon Jan 15 14:30:01 2024
Mon Jan 15 14:30:01 2024 -> clamd daemon 1.0.0 (OS: linux-gnu, ARCH: x86_64)
Mon Jan 15 14:30:01 2024 -> Log file size limit disabled.
Mon Jan 15 14:30:01 2024 -> Reading databases from /var/lib/clamav
Mon Jan 15 14:30:03 2024 -> Database correctly loaded (7654321 signatures)
Mon Jan 15 14:30:03 2024 -> TCP: Bound to address [::]:3310
Mon Jan 15 14:30:03 2024 -> Running as user clamav (UID 108, GID 113)
Mon Jan 15 14:35:12 2024 -> /home/user/Downloads/file.txt: OK
```

**Log Entry Types:**

- **Startup messages**: Daemon initialization, database loading
- **Scan results**: Files scanned via daemon (`OK`, `FOUND`)
- **Database updates**: When freshclam updates definitions
- **Connection events**: Client connections and disconnections
- **Errors**: Permission issues, configuration problems

#### Viewing in Fullscreen

For easier reading of long daemon logs:

1. Click the **Fullscreen button** (⛶ icon) in the Daemon Logs header
2. A fullscreen dialog opens with the complete log content
3. Read and scroll comfortably in the expanded view
4. **Close** or press **Escape** to return

💡 **Tip**: Use fullscreen mode when diagnosing daemon issues or copying large portions of logs for support tickets.

#### Exporting Daemon Logs

Click the **Export button** (💾 icon) in the Daemon Logs header to save the
currently displayed daemon log output to a `.txt` file.

#### Troubleshooting Daemon Log Access

**"Permission denied" errors:**

If you see permission errors reading `/var/log/clamav/clamd.log`:

```
Permission denied reading /var/log/clamav/clamd.log

The daemon log file requires elevated permissions.
Options:
  • Add your user to the 'adm' or 'clamav' group:
    sudo usermod -aG adm $USER
  • Or check if clamd logs to systemd journal:
    journalctl -u clamav-daemon
```

**Solutions:**

1. **Add yourself to the log-reading group:**
   ```bash
   sudo usermod -aG adm $USER
   ```
   Then log out and back in for changes to take effect.

2. **Use journalctl instead** (if clamd uses systemd):
   ```bash
   journalctl -u clamav-daemon -n 100 --no-pager
   ```

3. **Check if clamd is actually running:**
   ```bash
   systemctl status clamav-daemon
   ```

**"Daemon log file not found" errors:**

ClamUI checks these locations automatically:

- `/var/log/clamav/clamd.log`
- `/var/log/clamd.log`
- Log path from `/etc/clamav/clamd.conf`

If none exist, clamd may not be installed or may log to journalctl instead.

---

### Managing Your Log History

#### Clearing Old Logs

Over time, your log history can grow large. Clear old logs to free up disk space:

1. Navigate to **Logs** view → **Historical Logs** tab
2. Click **Clear All** button in the top-right
3. A confirmation dialog appears:
   ```
   Clear All Logs?

   This will permanently delete all historical logs.
   This action cannot be undone.

   [Cancel]  [Clear All]
   ```
4. Click **Clear All** to confirm (button is red/destructive)
5. All log entries are deleted immediately
6. The empty state appears: "No logs yet"

⚠️ **Warning**: This action is permanent and cannot be undone. Export important logs before clearing.

💡 **Tip**: If you want to preserve certain logs, export them to text or CSV files before clearing.

#### Log Storage Location

Logs are stored as individual JSON files on your system:

**Default Installation:**

```
~/.local/share/clamui/logs/
├── 7a3b9f12-4e56-7890-abcd-ef1234567890.json
├── b2c4d5e6-f789-0123-4567-89abcdef0123.json
└── ... (one file per log entry)
```

**Flatpak Installation** (if applicable):

```
~/.var/app/io.github.linx_systems.ClamUI/data/clamui/logs/
```

**Storage Considerations:**

- Each log entry is typically 500 bytes to 2 KB
- 1,000 logs ≈ 1-2 MB of disk space
- JSON format is human-readable if you open files directly
- Files are named by UUID (matches the ID field in log details)

**Manual Log Management:**

For advanced users, you can manage logs directly:

```bash
# View log count
ls ~/.local/share/clamui/logs/*.json | wc -l

# Check storage usage
du -sh ~/.local/share/clamui/logs/

# Backup all logs
cp -r ~/.local/share/clamui/logs/ ~/clamui-logs-backup/

# Delete logs older than 30 days
find ~/.local/share/clamui/logs/ -name "*.json" -mtime +30 -delete

# View a specific log file
cat ~/.local/share/clamui/logs/<UUID>.json | jq
```

⚠️ **Warning**: Manually deleting log files bypasses the UI's "Clear All" confirmation dialog. Be certain before running
manual deletion commands.

---

### Log History Best Practices

**Regular Review:**

- Check logs weekly to ensure scans are running as expected
- Verify scheduled scans are completing successfully
- Investigate any recurring errors

**Export Important Findings:**

- Export logs showing threat detections for your records
- Save CSV exports for monthly/quarterly security reports
- Keep text exports when reporting false positives to ClamAV

**Periodic Cleanup:**

- Clear very old logs (6+ months) if you don't need historical data
- Or export to backup before clearing to free up space
- Consider disk space if you perform many scans daily

**Compliance and Auditing:**

- Use log exports to demonstrate regular antivirus scanning
- CSV format makes it easy to generate scan frequency reports
- Logs include precise timestamps for audit trails

**Troubleshooting:**

- Check logs when scans fail to understand what went wrong
- Compare clean vs infected scan outputs to identify patterns
- Use daemon logs to diagnose clamd connection issues

💡 **Tip**: Set a monthly reminder to review your scan history and export any logs you need to keep before clearing the
rest.

---

