# Settings and Preferences

[← Back to User Guide](../USER_GUIDE.md)

---

## Settings and Preferences

ClamUI provides comprehensive configuration options to customize how virus scanning works on your system. This section
covers all available settings, from choosing the scan backend to configuring advanced ClamAV options.

💡 **Tip:** Most users only need to adjust a few basic settings. Advanced options like ClamAV configuration files are for
experienced users who want fine-grained control.

---

### Accessing Preferences

ClamUI's preferences are organized into several pages covering different aspects of the application.

**How to Open Preferences:**

1. **Using Keyboard Shortcut:**
    - Press `Ctrl+,` (Comma) from anywhere in ClamUI

2. **Using Menu:**
    - Click the menu button (☰) in the header bar
    - Select "Preferences"

**Preferences Window Layout:**

The preferences window uses a sidebar with these pages:

| Sidebar Page   | Purpose                                                                           | Save Behavior                                                  |
|----------------|-----------------------------------------------------------------------------------|----------------------------------------------------------------|
| **Behavior**   | Window close behavior, live scan progress, and file manager integration (Flatpak) | Auto-saved                                                     |
| **Exclusions** | Preset and custom scan exclusions                                                 | Auto-saved                                                     |
| **Database**   | `freshclam.conf` update settings                                                  | Save & Apply (admin)                                           |
| **Scanner**    | Scan backend + `clamd.conf` scanner settings                                      | Backend auto-saved, `clamd.conf` settings require Save & Apply |
| **Scheduled**  | Automatic scan schedule and targets                                               | Save & Apply                                                   |
| **Device Scan** | Automatic scanning of newly connected USB, external, and network devices | Auto-saved |
| **On-Access**  | Real-time on-access scanning settings (`clamd.conf`)                              | Save & Apply (admin)                                           |
| **VirusTotal** | API key and missing-key behavior                                                  | Saved when changed                                             |
| **Debug**      | Log level, log export/clear, system info                                          | Log level auto-saved; actions apply immediately                |
| **Save**       | Apply pending system configuration writes                                         | Use after editing Database, Scanner, Scheduled, or On-Access   |

**Navigation and Saving:**

- Click any sidebar item to open that settings page.
- Auto-saved pages apply changes immediately.
- Pages that modify ClamAV system config files require **Save & Apply** and usually prompt for administrator
  authentication.

⚠️ **Important:** Many settings require administrator (root) privileges to modify because they change system-wide ClamAV
configuration files. You'll see a lock icon (🔒) next to settings groups that require elevated permissions.

---

### Preferences Pages Overview

Use this quick guide when deciding where to make a change:

- **Behavior**: App/window behavior and scan UI behavior.
- **Scanner**: Choose scan backend (`auto`, `daemon`, `clamscan`) and scanner limits.
- **Database**: Control update frequency, mirrors, custom signatures, and proxy settings.
- **Scheduled**: Configure automated scans and target paths.
- **Device Scan**: Automatically scan USB/external/network devices when connected.
- **On-Access**: Configure real-time filesystem monitoring behavior.
- **Exclusions**: Exclude trusted paths/patterns from scans.
- **VirusTotal**: Manage your API key and missing-key actions.
- **Debug**: Troubleshooting controls and log management.
- **Save**: Apply pending edits to system config files.

### Simple Explanations Quick Reference

This is an option-by-option list of the current Preferences UI (`src/ui/preferences/*.py`), explained in plain language.
For raw JSON keys, defaults, and deployment-style examples, see `docs/CONFIGURATION.md`.

#### Behavior (auto-saved)

| Option                                   | Simple explanation                                                                          |
|------------------------------------------|---------------------------------------------------------------------------------------------|
| **Language**                             | Override the display language (auto uses system locale). Requires restart.                   |
| **When closing window**                  | Choose whether closing ClamUI minimizes to tray, quits, or asks every time.                 |
| **Show Live Scan Progress**              | Shows each file being scanned in real time. Turn off for a quieter progress display.        |
| **Configure Integration** (Flatpak only) | Installs/manages right-click "Scan with ClamUI" actions in supported file managers.         |

#### Exclusions (auto-saved)

| Option                                     | Simple explanation                                                              |
|--------------------------------------------|---------------------------------------------------------------------------------|
| **Node.js dependencies** (`node_modules`)  | Skips huge dependency folders to speed up scans.                                |
| **Git repository data** (`.git`)           | Skips Git internals that are rarely useful to scan.                             |
| **Python virtual environment** (`.venv`)   | Skips virtualenv packages and binaries.                                         |
| **Build output directory** (`build`)       | Skips temporary build artifacts.                                                |
| **Distribution output directory** (`dist`) | Skips packaged release output.                                                  |
| **Python bytecode cache** (`__pycache__`)  | Skips Python cache files.                                                       |
| **Custom Exclusions**                      | Add your own path or wildcard pattern (for example `/path/to/safe` or `*.tmp`). |

#### Database Updates (`freshclam.conf`, Save & Apply, admin)

| Option                                               | Simple explanation                                                           |
|------------------------------------------------------|------------------------------------------------------------------------------|
| **Database Directory**                               | Folder where ClamAV signatures are stored.                                   |
| **Update Log File**                                  | File where database update logs are written.                                 |
| **Notify ClamD Config**                              | Path to `clamd.conf` so freshclam can tell the daemon to reload signatures.  |
| **Verbose Logging**                                  | Adds more detail to update logs (useful for troubleshooting).                |
| **Syslog Logging**                                   | Sends update logs to system log (`syslog`/`journal`).                        |
| **Checks Per Day**                                   | How often ClamAV checks for new definitions (`0` disables automatic checks). |
| **Database Mirror**                                  | Mirror server used to download signature updates.                            |
| **Custom Signature Databases** (`DatabaseCustomURL`) | Add/remove third-party signature URLs (for example URLhaus).                 |
| **Proxy Server**                                     | Proxy hostname/IP for update traffic.                                        |
| **Proxy Port**                                       | Proxy port (`0` disables proxy use).                                         |
| **Proxy Username**                                   | Optional proxy login user.                                                   |
| **Proxy Password**                                   | Optional proxy login password.                                               |

#### Scanner (`clamd.conf`, Save & Apply for `clamd.conf` fields)

| Option                        | Simple explanation                                                                        |
|-------------------------------|-------------------------------------------------------------------------------------------|
| **Scan Backend** (auto-saved) | Select scan engine mode: auto, daemon-only (fastest), or clamscan-only (most compatible). |
| **Daemon Status**             | Shows whether `clamd` is reachable; use **Refresh Status** to re-check.                   |
| **Scan PE Files**             | Scan Windows executables (`.exe`, `.dll`).                                                |
| **Scan ELF Files**            | Scan Linux/Unix executables.                                                              |
| **Scan OLE2 Files**           | Scan Microsoft Office legacy document formats.                                            |
| **Scan PDF Files**            | Scan PDF documents.                                                                       |
| **Scan HTML Files**           | Scan HTML content.                                                                        |
| **Scan Archive Files**        | Scan compressed files (ZIP, RAR, etc.).                                                   |
| **Max File Size (MB)**        | Skip files larger than this limit (`0` = unlimited).                                      |
| **Max Scan Size (MB)**        | Limit total extracted/processed data (`0` = unlimited).                                   |
| **Max Archive Recursion**     | Limit nested archive depth to avoid archive bombs.                                        |
| **Max Files in Archive**      | Limit how many files are scanned inside one archive (`0` = unlimited).                    |
| **Log File Path**             | Destination file for scanner logs.                                                        |
| **Verbose Logging**           | More detailed scanner log output.                                                         |
| **Syslog Logging**            | Send scanner logs to system log.                                                          |

#### Scheduled (Save & Apply)

| Option                     | Simple explanation                                              |
|----------------------------|-----------------------------------------------------------------|
| **Enable Scheduled Scans** | Turns automatic scanning on/off.                                |
| **Scan Frequency**         | Run hourly, daily, weekly, or monthly.                          |
| **Scan Time**              | Time of day for scheduled runs (24-hour format).                |
| **Day of Week**            | Used only for weekly schedules.                                 |
| **Day of Month**           | Used only for monthly schedules (1-28).                         |
| **Scan Targets**           | Comma-separated directories/files to scan automatically.        |
| **Skip on Battery**        | Avoid running scheduled scans while on battery power.           |
| **Auto-Quarantine**        | Automatically quarantine detected threats from scheduled scans. |

#### Device Scan (auto-saved)

Automatically scans newly connected storage devices (USB, external drives, network mounts).

| Option                      | Simple explanation                                                |
|-----------------------------|-------------------------------------------------------------------|
| **Enable Device Auto-Scan** | Scan newly mounted devices in the background.                      |
| **Removable Devices**       | Include USB flash drives, SD cards, and other removable media.     |
| **External Drives**         | Include external HDDs/SSDs (ejectable but not removable media).    |
| **Network Mounts**          | Include NFS, SMB/CIFS, and SSHFS mounts.                           |
| **Max Device Size (GB)**    | Skip devices larger than this (`0` = no limit).                    |
| **Scan Delay (seconds)**    | Wait this long after a device is mounted before scanning.          |
| **Auto-Quarantine Threats** | Automatically move detected threats to quarantine.                |
| **Notifications**           | Show desktop notifications for device scan start/complete events.  |
| **Skip on Battery**         | Do not scan devices while running on battery power.                |

#### On-Access (`clamd.conf`, Save & Apply, admin)

| Option                     | Simple explanation                                                                                                                                                                     |
|----------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Include Paths**          | Folders to monitor in real time.                                                                                                                                                       |
| **Exclude Paths**          | Monitored folders to skip.                                                                                                                                                             |
| **Prevention Mode**        | Blocks access when malware is detected.                                                                                                                                                |
| **Extra Scanning**         | Triggers extra checks for create/move events.                                                                                                                                          |
| **Deny on Error**          | If scanning fails, block access anyway (strict mode).                                                                                                                                  |
| **Disable DDD**            | Turns off Dynamic Directory Determination. Usually keep this **off** so monitoring stays recursive. Turn it **on** only for specific non-recursive/legacy behavior or troubleshooting. |
| **Max Threads**            | How many worker threads on-access scanning may use.                                                                                                                                    |
| **Max File Size (MB)**     | Skip very large files during on-access scans (`0` = unlimited).                                                                                                                        |
| **Curl Timeout (seconds)** | Timeout for on-access client communication.                                                                                                                                            |
| **Retry Attempts**         | Retries after failed on-access scan attempts.                                                                                                                                          |
| **Exclude Username**       | Skip events from a specific user (usually `clamav`) to prevent scan loops.                                                                                                             |
| **Exclude User ID**        | Skip events from a numeric UID.                                                                                                                                                        |
| **Exclude Root User**      | Skip events from root (`UID 0`).                                                                                                                                                       |

#### VirusTotal (saved when changed)

| Option                      | Simple explanation                                                                            |
|-----------------------------|-----------------------------------------------------------------------------------------------|
| **API Key**                 | Stores your VirusTotal API key for cloud reputation scans.                                    |
| **When API key is missing** | Choose fallback behavior: ask every time, open VirusTotal website, or show notification only. |
| **Delete Key**              | Removes the saved key.                                                                        |

#### Debug

| Option               | Simple explanation                                                          |
|----------------------|-----------------------------------------------------------------------------|
| **Log Level**        | Controls how detailed ClamUI logs are (`WARNING` is default and practical). |
| **Open Log Folder**  | Opens the folder containing log files.                                      |
| **Export Logs**      | Creates a ZIP archive for troubleshooting/support.                          |
| **Clear Logs**       | Deletes log files to free disk space.                                       |
| **Copy System Info** | Copies OS/runtime details for bug reports.                                  |

#### Advanced JSON-Only Settings (not exposed in Preferences UI)

These are in `~/.config/clamui/settings.json`:

- `notifications_enabled` (default: `true`): Desktop notifications on/off.
- `minimize_to_tray` (default: `false`): Minimize window into tray instead of taskbar.
- `start_minimized` (default: `false`): Start hidden/minimized at launch (when tray is available).
- `quarantine_directory` (default: `""`): Override default quarantine folder.
- `daemon_socket_path` (default: `""`): Custom daemon socket path.
- `clamd_conf_path` (default: `""`): Custom path to `clamd.conf`.
- `freshclam_conf_path` (default: `""`): Custom path to `freshclam.conf`.
- `debug_log_max_size_mb` (default: `5`): Max size (MB) per debug log file before rotation.
- `debug_log_max_files` (default: `3`): Number of rotated debug log files to keep.

> **Note:** The `device_auto_scan_*` keys are configured through the **Device Scan** preferences page
> (see [Device Scan Settings](#device-scan-settings)), and the `schedule_*` keys through the **Scheduled**
> page, so they are not JSON-only.

---

### Behavior Settings

The **Behavior** page controls how ClamUI behaves when you close the app and how scan progress is shown.

#### Opening Behavior Settings

1. Open Preferences (`Ctrl+,`)
2. Click **Behavior** in the sidebar

#### Window Behavior

- **When closing window**:
    - **Minimize to tray**
    - **Quit completely**
    - **Always ask**
- If system tray support is unavailable, this section shows an informational message instead of controls.

#### Scan Behavior

- **Show Live Scan Progress**:
    - **On**: show real-time file-by-file scan progress
    - **Off**: show simpler progress without live file updates

#### File Manager Integration (Flatpak only)

- Open **Configure Integration** to install/manage “Scan with ClamUI” context-menu actions in supported file managers.

💡 **Tip:** Behavior settings are auto-saved, so you do not need to use **Save & Apply** for these options.

---

### Scan Backend Options

The scan backend determines how ClamUI performs virus scanning. Choose the method that best fits your setup.

#### Understanding Scan Backends

ClamUI supports three scanning methods:

| Backend                           | Description                                                           | Speed                                | When to Use                                                                                        |
|-----------------------------------|-----------------------------------------------------------------------|--------------------------------------|----------------------------------------------------------------------------------------------------|
| **Auto (Recommended)**            | Automatically prefer clamd daemon if available, fall back to clamscan | Fast (daemon) or Moderate (clamscan) | Default choice for most users. Gets best performance automatically.                                |
| **ClamAV Daemon (clamd)**         | Use the ClamAV daemon exclusively                                     | Very Fast (10-50x faster)            | When daemon is always running and you want guaranteed fast scans. **Requires clamd to be active.** |
| **Standalone Scanner (clamscan)** | Use standalone clamscan command                                       | Moderate                             | When clamd is not available, or for compatibility with specific scan profiles.                     |

**Performance Comparison:**

The ClamAV daemon (clamd) keeps virus signatures loaded in memory, making scans **10-50 times faster** than the
standalone scanner (clamscan), which must load signatures from disk for every scan.

**Example scan time for 10,000 files:**

- Daemon (clamd): 10-30 seconds
- Standalone (clamscan): 2-5 minutes

#### Choosing Your Scan Backend

**To Select Scan Backend:**

1. Open Preferences (`Ctrl+,`)
2. Click "Scanner" in the sidebar
3. Locate the "Scan Backend" section at the top
4. Click the "Scan Backend" dropdown
5. Select your preferred option:
    - "Auto (prefer daemon)" - Recommended
    - "ClamAV Daemon (clamd)" - Fast, requires daemon
    - "Standalone Scanner (clamscan)" - Compatible

**The selection is saved immediately** - no need to click Save & Apply for this setting.

#### Checking Daemon Status

Below the scan backend selector, you'll see the **Daemon Status** indicator:

**Status Messages:**

| Status               | Icon              | Meaning                                | What to Do                                                            |
|----------------------|-------------------|----------------------------------------|-----------------------------------------------------------------------|
| "Connected to clamd" | ✅ Green checkmark | Daemon is running and accessible       | No action needed. Fast scanning available.                            |
| "Not available: ..." | ⚠️ Warning        | Daemon is not running or not installed | Install clamd or use Auto/Clamscan backend. Details shown in message. |

**To Refresh Daemon Status:**

1. Click the "Refresh Status" button next to the status indicator
2. Status updates immediately with current daemon state

**Common Daemon Status Issues:**

| Error Message          | Cause                              | Solution                                                                                  |
|------------------------|------------------------------------|-------------------------------------------------------------------------------------------|
| "Socket not found"     | clamd not installed or not running | Install clamav-daemon package and start the service: `sudo systemctl start clamav-daemon` |
| "Connection refused"   | Socket permissions issue           | Check socket permissions or run ClamUI with appropriate access                            |
| "Daemon not installed" | ClamAV daemon package missing      | Install: `sudo apt install clamav-daemon` (Ubuntu/Debian)                                 |

💡 **Tip:** If you're unsure whether clamd is installed, use the "Auto (prefer daemon)" backend. ClamUI will
automatically use the daemon if available and fall back to clamscan otherwise.

⚠️ **Note:** On some distributions, the daemon is installed separately from the main ClamAV package. Check your
distribution's package manager for "clamav-daemon" or "clamd".

---

### Database Update Settings

ClamUI allows you to configure how ClamAV updates its virus definition databases through the `freshclam.conf`
configuration file.

🔒 **Requires Administrator Privileges:** These settings modify `/etc/clamav/freshclam.conf` and require root access.

#### Opening Database Update Settings

1. Open Preferences (`Ctrl+,`)
2. Click "Database" in the sidebar (Database Updates page)

You'll see several configuration groups:

#### Configuration File Location

At the top of the page, you'll see the configuration file path:

**File Location:** `/etc/clamav/freshclam.conf`

**To Open the Configuration Folder:**

- Click "Open Folder" button to view the file in your file manager
- Useful for manual edits or viewing backup files

#### Paths Configuration

**DatabaseDirectory** - Where virus definition files are stored

- **Default:** `/var/lib/clamav`
- **Purpose:** Storage location for virus signature databases (main.cvd, daily.cld, etc.)
- **When to change:** If you want databases on a different partition or faster storage
- **Example:** `/mnt/ssd/clamav-db` (for SSD storage)

**Update Log File** - Log file for database update operations

- **Default:** `/var/log/clamav/freshclam.log`
- **Purpose:** Records all database update attempts, successes, and failures
- **When to check:** Troubleshooting update issues, verifying update schedule
- **Example:** `/var/log/freshclam-updates.log`

**Notify ClamD Config** - Path to clamd.conf for reload notification

- **Default:** `/etc/clamav/clamd.conf`
- **Purpose:** Tells freshclam to notify the daemon when databases are updated
- **When to change:** If clamd.conf is in a non-standard location
- **Why it matters:** Ensures the daemon reloads new signatures without restart

**Verbose Logging** - Enable detailed logging

- **Options:** On/Off (switch)
- **Default:** Usually Off
- **When to enable:** Troubleshooting update failures, monitoring update process
- **Impact:** Larger log files, more detailed information

**Syslog Logging** - Send log messages to system log

- **Options:** On/Off (switch)
- **Default:** Usually Off
- **When to enable:** Centralized logging, system monitoring integration
- **Location:** Messages appear in `/var/log/syslog` or journalctl

#### Update Behavior Configuration

**Checks Per Day** - How often to check for database updates

- **Range:** 0-50 checks per day
- **Default:** Usually 24 (once per hour)
- **Recommended:** 12-24 for most users
- **Special value:** 0 disables automatic updates (not recommended)
- **Impact:** More frequent checks catch new threats faster but use more bandwidth

**Update Frequency Recommendations:**

| Checks/Day | Update Interval     | Best For                          | Bandwidth Impact        |
|------------|---------------------|-----------------------------------|-------------------------|
| 24         | Every hour          | Security-conscious users, servers | Low (~10-20 MB/day)     |
| 12         | Every 2 hours       | Standard desktop users            | Very Low (~5-10 MB/day) |
| 6          | Every 4 hours       | Low-bandwidth connections         | Minimal (~2-5 MB/day)   |
| 2          | Every 12 hours      | Infrequent usage                  | Negligible              |
| 0          | Never (manual only) | Testing/offline systems           | None                    |

**Database Mirror** - Mirror server URL for downloading databases

- **Default:** `database.clamav.net`
- **Purpose:** Server that provides virus definition database files
- **When to change:** Local mirror available, connection issues with default mirror
- **Format:** Hostname only (e.g., `db.local.clamav.net`) or full URL
- **Example:** `your-company-mirror.local`

⚠️ **Warning:** Only use trusted mirror servers. Malicious mirrors could provide compromised definitions.

#### Proxy Settings Configuration

If your network requires an HTTP proxy for internet access, configure these settings:

**Proxy Server** - Proxy server hostname or IP address

- **Example:** `proxy.company.com` or `192.168.1.1`
- **When needed:** Corporate networks, restricted internet access
- **Leave empty** if no proxy is required

**Proxy Port** - Proxy server port number

- **Range:** 0-65535
- **Common values:** 8080 (HTTP proxy), 3128 (Squid proxy)
- **Special value:** 0 disables proxy usage
- **Default:** 0

**Proxy Username** - Authentication username for proxy (optional)

- **When needed:** Proxy requires authentication
- **Leave empty** for anonymous proxies

**Proxy Password** - Authentication password for proxy (optional)

- **When needed:** Proxy requires authentication
- **Security:** Stored in plaintext in freshclam.conf
- **Leave empty** for anonymous proxies

**Example Proxy Configuration:**

| Scenario                  | Server              | Port | Username   | Password      |
|---------------------------|---------------------|------|------------|---------------|
| Corporate proxy with auth | `proxy.company.com` | 8080 | `john.doe` | `password123` |
| Local Squid proxy         | `192.168.1.1`       | 3128 | *(empty)*  | *(empty)*     |
| No proxy                  | *(empty)*           | 0    | *(empty)*  | *(empty)*     |

⚠️ **Security Note:** Proxy passwords are stored in plaintext in the configuration file. Use a dedicated proxy account
with minimal privileges.

#### Applying Database Update Settings

After configuring database update settings:

1. Navigate to "Save & Apply" page in the sidebar
2. Click the "Save & Apply" button
3. Enter your administrator password when prompted
4. Wait for confirmation dialog: "Configuration Saved"

**What Happens When You Save:**

- Backups are created of existing config files (`.bak` extension)
- New settings are written to `/etc/clamav/freshclam.conf`
- freshclam service may need restart to apply changes

**To Apply Changes Immediately:**

```bash
# Restart freshclam service (systemd)
sudo systemctl restart clamav-freshclam

# Or run freshclam manually once
sudo freshclam
```

💡 **Tip:** Test your configuration by running `sudo freshclam` manually. This will attempt a database update and show
any errors immediately.

---

### Scanner Configuration

ClamUI allows you to configure the ClamAV daemon scanner (clamd) behavior through the `clamd.conf` configuration file.

🔒 **Requires Administrator Privileges:** These settings modify `/etc/clamav/clamd.conf` and require root access.

⚠️ **Note:** Scanner settings are only available if `clamd.conf` exists. If you see "ClamD Configuration - clamd.conf
not found", install the clamav-daemon package.

#### Opening Scanner Settings

1. Open Preferences (`Ctrl+,`)
2. Click "Scanner" in the sidebar
3. Scroll past the "Scan Backend" section (covered earlier)

You'll see the configuration file location and scanner-specific settings.

#### Configuration File Location

**File Location:** `/etc/clamav/clamd.conf`

**To Open the Configuration Folder:**

- Click "Open Folder" button to view the file in your file manager

#### File Type Scanning

Control which file types ClamAV scans. Disabling unnecessary file types can improve scan performance.

**Available File Type Options:**

| Setting                | What It Scans                                 | Recommended | When to Disable                        |
|------------------------|-----------------------------------------------|-------------|----------------------------------------|
| **Scan PE Files**      | Windows/DOS executables (.exe, .dll, .sys)    | ✅ Yes       | Never - critical for Windows malware   |
| **Scan ELF Files**     | Unix/Linux executables                        | ✅ Yes       | Never - critical for Linux malware     |
| **Scan OLE2 Files**    | Microsoft Office documents (.doc, .xls, .ppt) | ✅ Yes       | If you never work with Office files    |
| **Scan PDF Files**     | PDF documents                                 | ✅ Yes       | If you never work with PDFs            |
| **Scan HTML Files**    | HTML documents and emails                     | ✅ Yes       | Only if you trust all HTML sources     |
| **Scan Archive Files** | Compressed archives (ZIP, RAR, 7z, etc.)      | ✅ Yes       | Never - archives often contain malware |

**Default Configuration:** All file types enabled (recommended)

**Performance Considerations:**

Disabling file types provides minimal performance improvement. Only disable if you have a specific reason:

- **Office documents:** Large OLE2 files (50+ MB) can slow scans
- **Archives:** Deeply nested archives can increase scan time significantly
- **HTML:** Scanning HTML is very fast, minimal impact

💡 **Tip:** Unless you have performance issues, leave all file types enabled for maximum protection.

⚠️ **Warning:** Disabling file type scanning creates security gaps. Malware often hides in "trusted" file types like
PDFs and Office documents.

**To Enable/Disable File Type Scanning:**

1. Locate the "File Type Scanning" group
2. Toggle the switch for each file type
3. Navigate to "Save & Apply" page
4. Click "Save & Apply" and enter administrator password

#### Performance and Limits

These settings control resource usage and prevent excessive scan times.

**MaxFileSize** - Maximum individual file size to scan (MB)

- **Range:** 0-4000 MB
- **Default:** Usually 25-100 MB
- **Special value:** 0 = unlimited (not recommended)
- **Purpose:** Skip extremely large files to prevent timeouts
- **Recommendation:** 100-200 MB for desktop, 500+ MB for servers

**MaxScanSize** - Maximum total scan size (MB)

- **Range:** 0-4000 MB
- **Default:** Usually 100-400 MB
- **Special value:** 0 = unlimited (not recommended)
- **Purpose:** Limit total data scanned within archives
- **Recommendation:** 400-800 MB for most users

**MaxRecursion** - Maximum recursion depth for archives

- **Range:** 0-255 levels
- **Default:** Usually 16
- **Purpose:** Prevent infinite recursion in maliciously crafted archives
- **Recommendation:** 10-20 for most users
- **Example:** ZIP containing ZIP containing ZIP (3 levels deep)

**MaxFiles** - Maximum number of files in an archive

- **Range:** 0-1,000,000 files
- **Default:** Usually 10,000
- **Special value:** 0 = unlimited (dangerous)
- **Purpose:** Prevent "zip bomb" attacks with millions of tiny files
- **Recommendation:** 5,000-20,000 for most users

**Understanding Performance Settings:**

```
Example Scan Scenario:
───────────────────────────────────────────────
Archive: suspicious.zip (50 MB compressed)
  ├─ file1.bin (150 MB)         ← MaxFileSize applies
  ├─ nested.zip
  │   └─ level2.zip
  │       └─ level3.zip         ← MaxRecursion applies
  └─ [20,000 tiny files]        ← MaxFiles applies

Total extracted: 800 MB          ← MaxScanSize applies
```

**Performance Tuning Guide:**

| Use Case                       | MaxFileSize | MaxScanSize | MaxRecursion | MaxFiles |
|--------------------------------|-------------|-------------|--------------|----------|
| **Fast scans (less thorough)** | 50 MB       | 200 MB      | 10           | 5,000    |
| **Balanced (recommended)**     | 100 MB      | 400 MB      | 16           | 10,000   |
| **Thorough scans (slower)**    | 500 MB      | 1000 MB     | 20           | 50,000   |
| **Maximum protection**         | 1000 MB     | 2000 MB     | 25           | 100,000  |

💡 **Tip:** If scans are too slow, reduce MaxScanSize and MaxFiles first. These have the biggest performance impact.

⚠️ **Warning:** Setting values to 0 (unlimited) can cause scans to hang on malicious archives designed to consume
resources (zip bombs, recursive archives).

**To Configure Performance Limits:**

1. Locate the "Performance and Limits" group
2. Adjust the values using the number spinners
3. Navigate to "Save & Apply" page
4. Click "Save & Apply" and enter administrator password

#### Logging Configuration

Control how the ClamAV daemon logs scan operations.

**Log File Path** - Location of the scanner log file

- **Default:** `/var/log/clamav/clamav.log`
- **Purpose:** Records all daemon scan operations and errors
- **When to change:** Different partition, centralized logging
- **Example:** `/var/log/clamd-scans.log`

**Verbose Logging** - Enable detailed scan logging

- **Options:** On/Off (switch)
- **Default:** Usually Off
- **When to enable:** Troubleshooting scan issues, detailed audit trail
- **Impact:** **Much larger log files** - can grow quickly with frequent scans
- **What's logged:** Every file scanned, scan results, virus signatures matched

**Syslog Logging** - Send log messages to system log

- **Options:** On/Off (switch)
- **Default:** Usually Off
- **When to enable:** Centralized logging, system monitoring integration
- **Location:** Messages appear in `/var/log/syslog` or via journalctl
- **Integration:** Works with log aggregation tools (Splunk, ELK, etc.)

**Logging Recommendations:**

| Scenario                   | Verbose | Syslog | Log File    |
|----------------------------|---------|--------|-------------|
| **Home desktop user**      | Off     | Off    | Default     |
| **Troubleshooting**        | On      | Off    | Default     |
| **Server with monitoring** | Off     | On     | Default     |
| **Compliance/audit**       | On      | On     | Custom path |

💡 **Tip:** Enable verbose logging temporarily when troubleshooting, then disable it to reduce log file size.

**To View Daemon Logs:**

ClamUI provides built-in log viewing:

1. Go to the "Scan History" view
2. Click the "ClamAV Daemon" tab
3. View live daemon logs with auto-refresh

Or use command line:

```bash
# View daemon log file
sudo tail -f /var/log/clamav/clamav.log

# View via systemd journal
journalctl -u clamav-daemon -f
```

**To Configure Logging:**

1. Locate the "Logging" group
2. Set the log file path if needed
3. Toggle verbose and syslog switches
4. Navigate to "Save & Apply" page
5. Click "Save & Apply" and enter administrator password

---

### On-Access Settings

The **On-Access** page configures ClamAV real-time file monitoring through `clamd.conf` (used by `clamonacc`).

🔒 **Requires Administrator Privileges:** On-Access options modify `/etc/clamav/clamd.conf`.

⚠️ **Availability Note:** If `clamd.conf` is missing, this page shows "On Access Configuration ... unavailable" and
settings cannot be edited.

#### How On-Access Scanning Works

ClamAV's on-access scanning uses two complementary layers to monitor your filesystem in real time:

- **Layer 1 — fanotify (base on-access):** A Linux kernel interface that intercepts file **open** and **access** events.
  Whenever any process tries to read or execute a file, fanotify notifies ClamAV so the file can be scanned. This layer
  is always active when on-access scanning is configured. With Prevention Mode enabled, fanotify can also **block** the
  file access until the scan completes.

- **Layer 2 — inotify (Extra Scanning / DDD):** A separate kernel interface that catches file **creation** and
  **move/rename** events. Without this layer, a file dropped into a monitored folder is *not* scanned until something
  actually tries to open it. Enabling Extra Scanning adds this coverage so new files are scanned immediately when they
  appear.

Together, these two layers provide comprehensive real-time protection. Most users should enable both.

> **Kernel note:** On kernels >= 5.1, fanotify gained support for some creation/move events natively. Even so, enabling
> Extra Scanning is still recommended for the most reliable coverage across kernel versions.

#### Opening On-Access Settings

1. Open Preferences (`Ctrl+,`)
2. Click **On-Access** in the sidebar

#### Monitored Paths

- **Include Paths**: Comma-separated directories to monitor in real time.
- **Exclude Paths**: Comma-separated directories to skip from real-time monitoring.

Example:

```text
Include Paths: /home/user/Downloads, /home/user/Desktop
Exclude Paths: /home/user/Downloads/large-archives
```

#### Behavior Settings

| Setting             | Simple explanation                                      | Recommended for most users                                           |
|---------------------|---------------------------------------------------------|----------------------------------------------------------------------|
| **Prevention Mode** | Blocks file access when malware is found.               | **On** if you want active blocking, not just detection.              |
| **Extra Scanning**  | Adds more event coverage for file create/move activity. | **On** for better real-time coverage.                                |
| **Deny on Error**   | If scan cannot complete, access is denied anyway.       | **Off** unless you need strict fail-closed policy.                   |
| **Disable DDD**     | Disables Dynamic Directory Determination (DDD).         | **Off** (default behavior is safer for normal recursive monitoring). |

**Prevention Mode** — controls what happens when malware is detected:

- **Off** (notification-only): Files are scanned when accessed. If malware is found, ClamAV logs an alert, but the
  process that opened the file is **not blocked** — it can still read the file. Useful for monitoring without disrupting
  workflows.
- **On** (active blocking): Fanotify uses kernel-level permission events to **block** the process from opening the
  file. The process receives an "Operation not permitted" error. This is true real-time protection.
- Requires `CONFIG_FANOTIFY_ACCESS_PERMISSIONS=y` in the kernel (most desktop Linux distributions have this enabled by
  default).

**Extra Scanning** — controls whether file creation and move events are caught:

- **Off**: Only file open/access events are caught via fanotify. A new file created or moved into a monitored directory
  is **not** scanned until a process tries to open it. On kernels >= 5.1, fanotify can catch some of these events
  natively, reducing the gap.
- **On**: Uses inotify (via the DDD system) to also catch `create` and `move-to` events. Files are scanned immediately
  when they appear in monitored directories, not just when accessed. Recommended for better coverage.

**Deny on Error** — controls behavior when a scan fails (only takes effect when Prevention Mode is On):

- **Off** (fail-open): If a scan fails (e.g., timeout, daemon unavailable), the file access is **allowed**. The user
  can still open the file. This avoids disruption but means an unscanned file may be accessed.
- **On** (fail-closed): If a scan fails, access is **denied** anyway. Stricter security, but may block legitimate files
  during scanner issues (e.g., daemon restart, high load).

**Disable DDD** — controls recursive subdirectory monitoring:

- **Off** (DDD enabled, default): DDD uses inotify to recursively track **all subdirectories** under each Include Path
  in real time. New subdirectories created later are also picked up automatically. This is the recommended setting.
- **On** (DDD disabled): Only the exact directories listed in Include Paths are monitored — **not** their
  subdirectories. Use this only if you hit inotify watch-point limits (see [Performance Settings](#performance-settings)
  below) or want intentionally narrow monitoring.

#### Comparison: Base vs Extra Scanning

This table shows which filesystem events are caught by each layer:

| Event                          | Base (fanotify) | Extra Scanning (inotify) |
|--------------------------------|-----------------|--------------------------|
| File opened / read             | Caught          | —                        |
| File executed                  | Caught          | —                        |
| New file created               | Not caught\*    | Caught                   |
| File moved / renamed into dir  | Not caught\*    | Caught                   |
| New subdirectory tracking      | —               | Caught (via DDD)         |

\* On kernel >= 5.1, fanotify may also catch these events natively.

For most desktop users, enabling **both** Prevention Mode and Extra Scanning provides the most complete protection.

Reference documentation:

- ClamAV On-Access manual: <https://docs.clamav.net/manual/OnAccess.html>
- ClamAV configuration overview: <https://docs.clamav.net/manual/Usage/Configuration.html>

#### Performance Settings

- **Max Threads**: 1-64 scanning threads.
- **Max File Size (MB)**: 0-4000 (`0` = unlimited).
- **Curl Timeout (seconds)**: 0-3600 (`0` disables timeout).
- **Retry Attempts**: 0-10 retries after scan failures.

**inotify watch-point limit:** When Extra Scanning and DDD are enabled, ClamAV creates an inotify watch for every
subdirectory under your Include Paths. The default system limit is often 8192 watches, which may not be enough for
large directory trees (e.g., an entire home folder). If you see errors about inotify watches in system logs:

```bash
# Check current limit
cat /proc/sys/fs/inotify/max_user_watches

# Increase temporarily (until next reboot)
sudo sysctl fs.inotify.max_user_watches=65536

# Increase permanently
echo "fs.inotify.max_user_watches=65536" | sudo tee -a /etc/sysctl.d/90-inotify.conf
sudo sysctl --system
```

#### Scan Loop Prevention (Critical)

On-Access scanning watches filesystem activity in real time.  
Without exclusions, the scanner can accidentally trigger itself:

1. ClamAV opens a file to scan it.
2. That file access is seen as a new "file access event."
3. ClamAV tries to scan its own scan activity again.
4. CPU usage spikes and scanning can become unstable.

To prevent this, configure exclusions for the scanner account:

- **Exclude Username** (recommended: `clamav`)
- **Exclude User ID** (UID of the scanner user)
- **Exclude Root User** (UID 0)

#### Recommended Setup (for new users)

Use this safe default on a typical Linux desktop install:

1. Set **Exclude Username** to `clamav`
2. Set **Exclude User ID** to the UID of `clamav`
3. Leave **Exclude Root User** off unless your scanner actually runs as root

#### Finding the Scanner UID (Simple)

On a vanilla install, the scanner service account is usually `clamav`, but the numeric UID is not the same on every
system.

Check your exact UID with:

```bash
id -u clamav
```

You can also see full details:

```bash
id clamav
```

Example output:

```text
uid=108(clamav) gid=113(clamav) groups=113(clamav)
```

In this example, set **Exclude User ID** to `108`.

💡 **Note:** Some systems may use a different value (for example `129`). Always use the value returned on your machine.

⚠️ **Important:** Do not leave all loop-prevention fields unset when enabling On-Access scanning.

#### Applying On-Access Changes

1. Go to **Save** in Preferences
2. Click **Save & Apply**
3. Authenticate when prompted
4. Restart related services if needed:

```bash
sudo systemctl restart clamav-daemon
sudo systemctl restart clamav-clamonacc  # if this service exists on your distro
```

💡 **Tip:** Start with a small include path (for example, `~/Downloads`) and verify system behavior before expanding
coverage.

---

### Device Scan Settings

The **Device Scan** page configures automatic scanning of newly connected storage devices — USB flash drives,
external drives, and network mounts. All settings on this page are **auto-saved** immediately; **Save & Apply** is
not required.

#### Opening Device Scan Settings

1. Open Preferences (`Ctrl+,`)
2. Click **Device Scan** in the sidebar

#### General

- **Enable Device Auto-Scan** (`device_auto_scan_enabled`, default off): Turns automatic device scanning on or off.
  When on, ClamUI watches for newly mounted volumes and scans them in the background.

#### Device Types

Choose which kinds of devices are auto-scanned (`device_auto_scan_types`, default `["removable", "external"]`):

- **Removable Devices** — USB flash drives, SD cards, and other removable media.
- **External Drives** — external HDDs and SSDs (ejectable but not removable media).
- **Network Mounts** — NFS, SMB/CIFS, and SSHFS mounts.

#### Options

| Option                      | Setting key                        | Default | Meaning                                          |
|-----------------------------|------------------------------------|---------|--------------------------------------------------|
| **Max Device Size (GB)**    | `device_auto_scan_max_size_gb`     | `32`    | Skip devices larger than this (`0` = no limit).  |
| **Scan Delay (seconds)**    | `device_auto_scan_delay_seconds`   | `3`     | Wait before scanning after a device is mounted.  |
| **Auto-Quarantine Threats** | `device_auto_scan_auto_quarantine` | off     | Automatically move detected threats to quarantine. |
| **Notifications**           | `device_auto_scan_notify`          | on      | Show desktop notifications for device scan events. |
| **Skip on Battery**         | `device_auto_scan_skip_on_battery` | on      | Do not scan devices while running on battery power. |

💡 **Tip:** Device auto-scan automatically checks USB drives the moment you plug them in. Keep **Skip on Battery** on
for laptops to avoid draining power during scans.

---

### Managing Exclusion Patterns

Exclusion patterns allow you to skip certain files or directories during scans, improving performance and reducing false
positives.

💡 **Note:** Exclusions configured here are **global exclusions** that apply to all scans. For profile-specific
exclusions, use the Scan Profiles feature (see the [Scan Profiles guide](profiles.md)).

#### Opening Exclusions Settings

1. Open Preferences (`Ctrl+,`)
2. Click "Exclusions" in the sidebar

You'll see two groups: Preset Exclusions and Custom Exclusions.

#### Understanding Exclusion Types

ClamUI supports two types of exclusions:

**Path Exclusions:**

- Exact file or directory paths
- Example: `/home/user/safe-folder` or `/opt/myapp/cache`
- Use for: Specific directories you trust completely

**Pattern Exclusions:**

- Glob patterns matching multiple files/directories
- Example: `*.tmp`, `node_modules`, `/home/*/.cache`
- Use for: Common file types or directory names anywhere on the system

**Global vs Profile Exclusions:**

| Type                   | Where Configured             | Applies To                                       | Use Case                     |
|------------------------|------------------------------|--------------------------------------------------|------------------------------|
| **Global Exclusions**  | Preferences → Exclusions     | **All scans** (manual, scheduled, profile-based) | System-wide safe directories |
| **Profile Exclusions** | Scan Profiles → Edit Profile | **Only that profile**                            | Profile-specific needs       |

💡 **Tip:** Use global exclusions for directories you **never** want to scan (system caches, temp directories). Use
profile exclusions for context-specific needs.

#### Preset Exclusions

ClamUI provides common development directory patterns as presets. These are especially useful for developers and can
significantly improve scan performance.

**Available Preset Exclusions:**

| Pattern        | Description                   | Typical Size | Why Exclude                                          |
|----------------|-------------------------------|--------------|------------------------------------------------------|
| `node_modules` | Node.js dependencies          | 100-500 MB   | Thousands of files, false positives, build artifacts |
| `.git`         | Git repository data           | 10-100 MB    | Binary objects, not executable, no malware risk      |
| `.venv`        | Python virtual environment    | 50-200 MB    | Python packages, duplicates system packages          |
| `build`        | Build output directory        | 50-500 MB    | Compiled artifacts, temporary files                  |
| `dist`         | Distribution output directory | 10-100 MB    | Packaged builds, minified code                       |
| `__pycache__`  | Python bytecode cache         | 1-50 MB      | Compiled Python, not executable                      |

**To Enable/Disable Preset Exclusions:**

1. Locate the "Preset Exclusions" group
2. Toggle the switch for each pattern
3. Enabled (On) = pattern will be excluded from scans
4. Disabled (Off) = pattern will be scanned normally

**Changes take effect immediately** - no need to Save & Apply for preset exclusions.

**When to Enable Presets:**

✅ **Enable if you:**

- Are a software developer
- Have projects in your home directory
- Want faster scans
- Experience false positives in build directories

❌ **Disable if you:**

- Don't use development tools
- Want maximum thorough scanning
- Work with untrusted downloaded projects

💡 **Tip:** Enabling all preset exclusions is safe for developers. These directories rarely contain executable malware
and are rebuilt frequently.

#### Custom Exclusions

Add your own exclusion patterns for directories and files specific to your system.

**To Add a Custom Exclusion Pattern:**

1. Locate the "Custom Exclusions" group
2. Click in the entry field labeled "Add Pattern"
3. Type your exclusion pattern
4. Click the "Add" button

**Pattern Examples:**

| Pattern            | What It Excludes          | Use Case                        |
|--------------------|---------------------------|---------------------------------|
| `/home/user/Music` | Entire Music directory    | Media library (no malware risk) |
| `/opt/safe-app`    | Entire application folder | Trusted proprietary software    |
| `*.iso`            | All ISO disk images       | Large files, CD/DVD images      |
| `*.mp4`            | All MP4 video files       | Video library                   |
| `/mnt/*`           | All mounted filesystems   | External drives, network shares |
| `/var/log`         | System log directory      | Log files (no executable risk)  |
| `Thumbs.db`        | Windows thumbnail cache   | Temporary system files          |

**Pattern Syntax:**

- **Exact paths:** Start with `/` for absolute paths (e.g., `/home/user/safe`)
- **Wildcards:** Use `*` for any characters (e.g., `*.tmp` or `/home/*/Downloads/*.pdf`)
- **Recursive:** Patterns match at any depth (e.g., `node_modules` matches `/project/node_modules` and
  `/project/sub/node_modules`)

**Pattern Validation:**

When you add a pattern, ClamUI validates it:

| Indicator         | Meaning                            | Action                            |
|-------------------|------------------------------------|-----------------------------------|
| ✅ Green checkmark | Valid pattern                      | Pattern will work correctly       |
| ⚠️ Yellow warning | Pattern works but may be too broad | Review pattern for accuracy       |
| ❌ Red X           | Invalid pattern syntax             | Correct the pattern before adding |

**To Remove a Custom Exclusion:**

1. Locate the exclusion in the custom exclusions list
2. Click the remove/delete button (🗑️) next to the pattern
3. Confirm removal if prompted

**Changes take effect immediately** - no need to Save & Apply for custom exclusions.

#### Best Practices for Exclusions

**DO:**

- ✅ Exclude large media libraries (Music, Videos, Photos)
- ✅ Exclude development directories with many files
- ✅ Exclude system cache directories
- ✅ Exclude known safe application data folders
- ✅ Test exclusions by running a scan and checking the file count

**DON'T:**

- ❌ Exclude your Downloads folder (common malware entry point)
- ❌ Exclude Documents folder (macros in Office files)
- ❌ Exclude your entire home directory (too broad)
- ❌ Exclude email attachment directories
- ❌ Exclude USB mount points (external media often contains threats)

**Performance Impact Example:**

```
Scan without exclusions:
├─ Files scanned: 250,000
├─ Scan time: 8 minutes
└─ False positives: 15 detections in build/

Scan with exclusions (node_modules, build, .git):
├─ Files scanned: 45,000
├─ Scan time: 90 seconds
└─ False positives: 0 detections
```

⚠️ **Warning:** Every exclusion reduces protection. Only exclude directories you completely trust.

💡 **Tip:** Use the Statistics Dashboard to see how many files are scanned. If the number drops unexpectedly after adding
exclusions, review your patterns.

---

### VirusTotal Settings

The **VirusTotal** page lets you connect an API key for cloud reputation checks.

#### Opening VirusTotal Settings

1. Open Preferences (`Ctrl+,`)
2. Click **VirusTotal** in the sidebar

#### What You Can Configure

- **API Key**: Paste your key and click **Save Key**.
- **Missing Key Behavior**: Choose what happens when scanning without an API key:
    - Always ask
    - Open VirusTotal website
    - Show notification only
- **Key Removal**: Click **Delete Key** to remove a saved key.

#### Notes

- Your API key is stored securely in the system keyring (libsecret), **not** in `settings.json`. A plaintext fallback
  in `settings.json` is used only if you explicitly opt in via `allow_plaintext_api_key_fallback`.
- API key changes are applied immediately; **Save & Apply** is not required.
- Free-tier limits apply: **4 requests per minute** and **500 requests per day**. Files up to **650 MB** can be
  scanned (uploads larger than 32 MB use VirusTotal's large-file upload flow automatically).

---

### Debug and Diagnostics

The **Debug** page helps with troubleshooting and support.

#### Opening Debug Settings

1. Open Preferences (`Ctrl+,`)
2. Click **Debug** in the sidebar

#### Logging and Diagnostics Tools

- **Log Level** combo (`DEBUG`, `INFO`, `WARNING`, `ERROR`) controls ClamUI's own diagnostic verbosity. Default is
  `WARNING`.
- **Log File Location** shows the debug-log folder with an **Open** button to reveal it in your file manager.
- **Export Logs** saves all debug log files to a **redacted ZIP archive** (file paths, hashes, and report URLs are
  stripped) for sharing in bug reports.
- **Clear Logs** deletes all debug log files to free disk space.
- **System Information** panel (installation type, distribution, desktop environment, Python/GTK versions) with a
  **Copy System Info** action for support tickets.

These are ClamUI's own **debug/diagnostic** logs, which are stored separately from scan and update history logs:

```text
~/.local/share/clamui/debug/   ← ClamUI debug/diagnostic logs (this page)
~/.local/share/clamui/logs/    ← scan and update history logs (shown in the Logs view)
```

Debug logs rotate automatically: each file is capped at `debug_log_max_size_mb` (default `5` MB), and up to
`debug_log_max_files` (default `3`) rotated files are kept. These two rotation values live in `settings.json` only.

#### Notes

- Log-level changes are auto-saved and applied to the running logger immediately.
- Export/Clear actions apply immediately.

---

### Notification Settings

ClamUI can display desktop notifications when scans complete, threats are detected, or virus definitions are updated.

#### Managing Desktop Notifications

Notifications are enabled by default.

In the current Preferences UI, there is no dedicated notification toggle.

Use `settings.json` to change this option:

1. Open `~/.config/clamui/settings.json`
2. Set `"notifications_enabled": true` (or `false` to disable)
3. Restart ClamUI

For Flatpak installs, use:

`~/.var/app/io.github.linx_systems.ClamUI/config/clamui/settings.json`

**When Notifications Appear:**

| Event                       | Notification                                 | Priority                          |
|-----------------------------|----------------------------------------------|-----------------------------------|
| **Scan Complete (Clean)**   | "No threats found (X files scanned)"         | Normal                            |
| **Threats Detected**        | "Threats Detected! X infected file(s) found" | **Urgent** (stays visible longer) |
| **Database Update Success** | "Virus definitions updated"                  | Normal                            |
| **Database Update Failed**  | "Database update failed" with error          | Normal                            |
| **Scheduled Scan Complete** | "Scheduled scan complete" with results       | Normal                            |

**Notification Behavior:**

- Appear in the GNOME notification area (top-right on most systems)
- Click a notification to open ClamUI and view details
- Dismiss automatically after a few seconds (except urgent threats)
- Persist in notification center for review

**When to Enable Notifications:**

✅ **Enable if you:**

- Want immediate awareness of scan results
- Run scheduled scans while away from computer
- Need alerts for detected threats
- Multitask and may not watch scan progress

❌ **Disable if you:**

- Find notifications distracting
- Always monitor scans manually
- Run frequent scans that would spam notifications
- Use ClamUI in a server/headless environment

**Notification Examples:**

```
┌─────────────────────────────────────────┐
│ ClamUI                              [×] │
│ ─────────────────────────────────────── │
│ Scan Complete                           │
│ No threats found (1,234 files scanned)  │
│                                  2m ago │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ ClamUI                              [×] │
│ ─────────────────────────────────────── │
│ ⚠️ Threats Detected!                    │
│ 3 infected file(s) found                │
│                                  now    │
└─────────────────────────────────────────┘
```

💡 **Tip:** Notifications are especially useful for scheduled scans. Enable them to get alerts even when you're not
actively using ClamUI.

⚠️ **Note:** Notifications require a GNOME-compatible desktop environment. They may not work in all Linux desktop
environments.

**To Test Notifications:**

1. Ensure notifications are enabled
2. Run a Quick Scan (Downloads folder)
3. Wait for scan to complete
4. You should see a "Scan Complete" notification

If notifications don't appear:

- Check your desktop environment notification settings
- Ensure ClamUI has notification permissions
- Try the "Test EICAR" button (should trigger threat notification)

---

### Saving and Applying Settings

Only some settings require **Save & Apply**.

Auto-saved settings include:

- Behavior options
- Exclusions
- Scan backend selection
- VirusTotal behavior/API key actions
- Debug log level

#### Save & Apply Page

1. Open Preferences (`Ctrl+,`)
2. Navigate to "Save" in the sidebar (the Save & Apply page)
3. Review the "Current Status" indicator:
    - **"Ready"** ✅ - Settings can be saved
    - **"Saving..."** ⏳ - Save in progress
    - **"Error"** ❌ - Previous save failed

#### Applying Configuration Changes

**To Save All Settings:**

1. Click the **"Save & Apply"** button (blue/suggested-action style)
2. **For ClamAV configuration changes** (Database, Scanner, On-Access):
    - Authentication dialog appears
    - Enter your administrator/sudo password
    - Click "Authenticate"
3. Wait for confirmation: "Configuration Saved" dialog
4. Click "OK" to dismiss confirmation

> **Privileged helper (optional):** Saving `freshclam.conf`/`clamd.conf` uses `pkexec` to elevate just the
> configuration write, so you are prompted for your administrator password each time. For a one-time setup that
> registers a dedicated polkit action instead, run `clamui install-privileged-helper` (needs `sudo`). This installs
> the `clamui-apply-preferences` helper and its polkit policy used for elevated config writes.

**What Gets Saved:**

| Settings Page                  | What Changes                                       | Requires Admin Password |
|--------------------------------|----------------------------------------------------|-------------------------|
| Database                       | `/etc/clamav/freshclam.conf`                       | ✅ Yes                   |
| Scanner (`clamd.conf` options) | `/etc/clamav/clamd.conf`                           | ✅ Yes                   |
| On-Access                      | `/etc/clamav/clamd.conf`                           | ✅ Yes                   |
| Scheduled Scans                | `~/.config/clamui/settings.json` + system schedule | Usually no              |

**Not Saved Here (Already Auto-Saved):**

- Behavior
- Exclusions
- Scan Backend
- VirusTotal behavior/key operations
- Debug log level

**Automatic Backups:**

Before saving ClamAV configuration files, ClamUI creates backups:

```
/etc/clamav/freshclam.conf.bak  ← Previous version
/etc/clamav/clamd.conf.bak      ← Previous version
```

💡 **Tip:** If changes cause problems, restore from backups:

```bash
sudo cp /etc/clamav/freshclam.conf.bak /etc/clamav/freshclam.conf
sudo systemctl restart clamav-freshclam
```

#### Applying Changes to Services

Some changes require service restarts to take effect:

**After Changing Database Update Settings:**

```bash
# Restart freshclam service
sudo systemctl restart clamav-freshclam

# Or run a manual update
sudo freshclam
```

**After Changing Scanner Settings:**

```bash
# Restart clamd service
sudo systemctl restart clamav-daemon

# Verify daemon is running
systemctl status clamav-daemon
```

**After Changing Scheduled Scans:**
No action needed - ClamUI automatically creates/updates systemd timers or crontab entries.

**To Verify Schedule Changes:**

```bash
# View systemd timer
systemctl --user list-timers clamui-scheduled-scan.timer

# View crontab entry
crontab -l | grep clamui
```

#### Troubleshooting Save Errors

**Common Errors:**

| Error                       | Cause                      | Solution                                                         |
|-----------------------------|----------------------------|------------------------------------------------------------------|
| "Authentication failed"     | Wrong password             | Re-enter correct sudo password                                   |
| "Permission denied"         | Not in sudoers             | Add user to sudo group: `sudo usermod -aG sudo USERNAME`         |
| "File not found"            | Config file missing        | Install ClamAV packages: `sudo apt install clamav clamav-daemon` |
| "Invalid configuration"     | Syntax error in settings   | Review settings, check error message details                     |
| "Failed to enable schedule" | Systemd/cron not available | Check system has systemd or cron installed                       |

**If Save Fails:**

1. Check the error message details in the dialog
2. Verify ClamAV is installed: `clamscan --version`
3. Check file permissions: `ls -l /etc/clamav/`
4. Try manual config edit: `sudo nano /etc/clamav/freshclam.conf`
5. Check ClamUI logs for detailed errors

💡 **Tip:** Always save and test settings one page at a time. This makes it easier to identify which change caused an
issue.

---

### Settings Storage Locations

Understanding where settings are stored helps with backups and troubleshooting.

**ClamUI Application Settings:**

```
~/.config/clamui/settings.json
```

Contains:

- Scan backend preference
- Notification enabled/disabled
- Scheduled scan configuration
- Global exclusion patterns
- Minimize to tray settings
- Device auto-scan preferences

**ClamAV System Configuration:**

```
/etc/clamav/freshclam.conf  ← Database updates
/etc/clamav/clamd.conf      ← Scanner daemon
```

**Scan Profiles:**

```
~/.config/clamui/profiles.json
```

**Scheduled Scan Scripts:**

```
# Systemd user timer
~/.config/systemd/user/clamui-scheduled-scan.timer
~/.config/systemd/user/clamui-scheduled-scan.service

# Or crontab entry (alternative)
crontab -l
```

**Backup Recommendations:**

To backup all your ClamUI settings:

```bash
# Backup ClamUI application settings
cp -r ~/.config/clamui ~/clamui-settings-backup

# Backup ClamAV system configuration (requires sudo)
sudo cp /etc/clamav/freshclam.conf ~/freshclam.conf.backup
sudo cp /etc/clamav/clamd.conf ~/clamd.conf.backup
```

To restore settings:

```bash
# Restore ClamUI application settings
cp -r ~/clamui-settings-backup/* ~/.config/clamui/

# Restore ClamAV system configuration (requires sudo)
sudo cp ~/freshclam.conf.backup /etc/clamav/freshclam.conf
sudo cp ~/clamd.conf.backup /etc/clamav/clamd.conf
sudo systemctl restart clamav-freshclam clamav-daemon
```

---

### Settings Best Practices

**For Home Desktop Users:**

- ✅ Scan Backend: "Auto (prefer daemon)"
- ✅ Database Updates: 12-24 checks per day
- ✅ Scanner: All file types enabled, balanced limits
- ✅ Exclusions: Enable preset development directories if applicable
- ✅ Notifications: Enabled

**For Developers:**

- ✅ Scan Backend: "Auto (prefer daemon)" for speed
- ✅ Exclusions: Enable all preset patterns (node_modules, .git, etc.)
- ✅ Custom Exclusions: Add project-specific build directories
- ✅ Scanner Limits: Increase MaxFiles (20,000+) for large projects

**For Security-Conscious Users:**

- ✅ Scan Backend: "ClamAV Daemon (clamd)" if available
- ✅ Database Updates: 24 checks per day (hourly)
- ✅ Scanner: All file types enabled, high limits
- ✅ Exclusions: Minimal - only media libraries
- ✅ Logging: Verbose enabled for audit trail
- ✅ Notifications: Enabled for immediate threat alerts

**For Low-Bandwidth Connections:**

- ✅ Database Updates: 4-6 checks per day
- ✅ Scanner Limits: Lower MaxScanSize (200 MB) for faster scans
- ✅ Consider local mirror if available

💡 **Tip:** Start with default settings and adjust only when you have a specific need. ClamAV's defaults are chosen for
good security and performance balance.

---

