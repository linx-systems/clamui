# Troubleshooting

[← Back to User Guide](../USER_GUIDE.md)

---

## Troubleshooting

This section helps you diagnose and fix common issues with ClamUI. If you encounter a problem not covered here, please
check the [FAQ](faq.md) section or visit
the [GitHub Issues](https://github.com/linx-systems/clamui/issues) page.

### ClamAV Not Found

**Problem:** ClamUI reports that ClamAV is not installed or cannot be found.

**Symptoms:**

- Error message: "ClamAV is not installed"
- Cannot start scans
- Application shows "ClamAV components not found" on startup
- Components view shows ClamAV as unavailable

#### Solution 1: Install ClamAV

ClamUI requires ClamAV to be installed on your system. The installation method depends on your Linux distribution:

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install clamav clamav-daemon clamav-freshclam
```

**Fedora:**

```bash
sudo dnf install clamav clamd clamav-update
```

**Arch Linux:**

```bash
sudo pacman -S clamav
```

**After installation:**

1. Close and restart ClamUI
2. Wait for virus database update (happens automatically on first run)
3. Try scanning a file to verify installation

💡 **Tip:** The `clamav-daemon` package is optional but recommended for faster scanning.
See [Scan Backend Options](settings.md#scan-backend-options) for details.

#### Solution 2: Check if ClamAV is in PATH

If you've installed ClamAV but ClamUI still can't find it, verify it's accessible:

```bash
which clamscan
clamscan --version
```

**Expected output:**

```
/usr/bin/clamscan
ClamAV 1.0.0/...
```

**If command not found:**

- ClamAV may be installed in a non-standard location
- Your PATH environment variable may not include the ClamAV binary directory
- Try reinstalling ClamAV using your distribution's package manager

#### Solution 3: Flatpak-Specific Issues

If you installed ClamUI via Flatpak, install ClamAV on the host system. The Flatpak runs host `clamscan`,
`freshclam`, and `clamdscan` through `flatpak-spawn --host`.

**If you still see "ClamAV Not Found" errors:**

1. **Install host ClamAV**:
   ```bash
   sudo apt install clamav clamav-freshclam      # Ubuntu/Debian
   sudo dnf install clamav clamav-update        # Fedora
   sudo pacman -S clamav                        # Arch Linux
   ```

2. **Check for database update errors**:
   - Open ClamUI and go to the "Update" view
   - Click "Update Database" and watch for errors
   - Or run `sudo freshclam` on the host
   - Check logs in `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/logs/`

3. **Reinstall the Flatpak** (may fix corrupted installation):
   ```bash
   flatpak uninstall io.github.linx_systems.ClamUI
   flatpak install flathub io.github.linx_systems.ClamUI
   ```

**Note:** The daemon scan backend requires host `clamd`/`clamdscan`. If you want to use daemon scanning, install
`clamav-daemon` on your host and set `"scan_backend": "daemon"` in settings.

**Check Flatpak permissions:**

```bash
flatpak info --show-permissions io.github.linx_systems.ClamUI
```

Should include:

```
talk=org.freedesktop.Flatpak
```

Accessibility support still works without an explicit `talk=org.a11y.Bus` entry because Flatpak provides an accessibility bus proxy automatically.

#### Troubleshooting Table

| Error Message                             | Cause                            | Solution                                      |
|-------------------------------------------|----------------------------------|-----------------------------------------------|
| "ClamAV is not installed"                 | ClamAV package not installed     | Install `clamav` package for your distro      |
| "ClamAV found but returned error"         | ClamAV installed but broken      | Reinstall ClamAV: `sudo apt reinstall clamav` |
| "ClamAV check timed out"                  | System unresponsive or very slow | Restart your computer and try again           |
| "ClamAV executable not found"             | ClamAV not in PATH               | Check PATH, reinstall ClamAV                  |
| "Permission denied when accessing ClamAV" | Incorrect file permissions       | Run: `sudo chmod +x /usr/bin/clamscan`        |

⚠️ **Warning:** Never install ClamAV from unofficial sources or untrusted repositories. Always use your distribution's
official package manager.

---

### Daemon Connection Issues

**Problem:** ClamUI cannot connect to the ClamAV daemon (clamd), or daemon-based scanning is unavailable.

**Symptoms:**

- Scans are slow (falling back to clamscan instead of daemon)
- Scan backend shows "Daemon not available"
- Error: "clamd not accessible"
- Statistics view shows "Daemon: Stopped" or "Unknown"
- Daemon logs tab shows "Could not access daemon logs"

#### Understanding the ClamAV Daemon

The ClamAV daemon (`clamd`) is an optional component that keeps virus definitions loaded in memory for much faster
scanning (10-50x faster than standalone `clamscan`). If the daemon isn't running, ClamUI automatically falls back to
using `clamscan`, which works but is slower.

**Performance comparison:**

- **With daemon**: 1000 files in ~30 seconds
- **Without daemon**: 1000 files in ~5-10 minutes

#### Solution 1: Install clamav-daemon

The daemon is a separate package from the base ClamAV scanner.

**Ubuntu/Debian:**

```bash
sudo apt install clamav-daemon
```

**Fedora:**

```bash
sudo dnf install clamd
```

**Arch Linux:**

```bash
sudo pacman -S clamav
# Daemon is included, but needs to be enabled
```

**Verify installation:**

```bash
clamdscan --version
```

#### Solution 2: Start the Daemon Service

After installing, the daemon must be running.

**Check daemon status:**

```bash
systemctl status clamav-daemon
# or on some systems:
systemctl status clamd@scan
```

**Start the daemon:**

```bash
sudo systemctl start clamav-daemon
sudo systemctl enable clamav-daemon  # Enable autostart on boot
```

**For Fedora/RHEL:**

```bash
sudo systemctl start clamd@scan
sudo systemctl enable clamd@scan
```

**Verify daemon is responding:**

```bash
clamdscan --ping 3
```

Expected output: `PONG`

#### Solution 3: Check Socket Permissions

The daemon communicates via a Unix socket. Permission issues can prevent access.

**Find the socket:**

```bash
# Common locations (checked in this order):
ls -la /var/run/clamav/clamd.ctl      # Ubuntu/Debian
ls -la /run/clamav/clamd.ctl          # Alternative (Ubuntu/Debian)
ls -la /run/clamd.scan/clamd.sock     # Fedora/RHEL
ls -la /var/run/clamd.scan/clamd.sock # Fedora/RHEL (alternative)
```

**Check permissions:**

```bash
ls -la /var/run/clamav/clamd.ctl
```

Should show something like:

```
srwxrwxrwx 1 clamav clamav 0 Jan 02 10:00 /var/run/clamav/clamd.ctl
```

**If permissions are wrong:**

```bash
# Add your user to the clamav group
sudo usermod -a -G clamav $USER

# Log out and back in for group changes to take effect
# Or use: newgrp clamav
```

#### Solution 4: Update Database First

The daemon may fail to start if virus definitions are missing or outdated.

**Update virus definitions:**

```bash
sudo freshclam
```

**Then restart daemon:**

```bash
sudo systemctl restart clamav-daemon
```

#### Solution 5: Check Daemon Configuration

Incorrect configuration can prevent the daemon from starting.

**Check daemon configuration:**

```bash
sudo nano /etc/clamav/clamd.conf
```

On Fedora/RHEL the daemon config lives at `/etc/clamd.d/scan.conf` instead:

```bash
sudo nano /etc/clamd.d/scan.conf
```

**Key settings to verify:**

```
# Make sure these are set:
LocalSocket /var/run/clamav/clamd.ctl
# LocalSocketGroup clamav
# LocalSocketMode 666

# Make sure Example line is commented out:
# Example
```

⚠️ **Important:** If you see `Example` without a `#` at the start, the config file is using example mode and will be
ignored. Comment it out.

**After editing, restart:**

```bash
sudo systemctl restart clamav-daemon
```

#### Solution 6: Check Daemon Logs for Errors

**View daemon logs:**

```bash
sudo journalctl -u clamav-daemon -n 50
# or:
sudo tail -f /var/log/clamav/clamav.log
```

**Common errors in logs:**

| Log Error                                                             | Cause                            | Solution                                                            |
|-----------------------------------------------------------------------|----------------------------------|---------------------------------------------------------------------|
| "Can't open/parse the config file"                                    | Configuration syntax error       | Check `/etc/clamav/clamd.conf` for typos                            |
| "Database initialization error"                                       | Missing or corrupted definitions | Run `sudo freshclam` to update                                      |
| "Can't create temporary directory"                                    | Permission or disk space issue   | Check `/tmp` permissions and free space                             |
| "bind(): Address already in use"                                      | Socket file already exists       | Remove old socket: `sudo rm /var/run/clamav/clamd.ctl` then restart |
| "LibClamAV Error: cli_loaddbdir(): No supported database files found" | No virus database                | Run `sudo freshclam` to download                                    |

#### Troubleshooting Table

| Symptom                                     | Cause                                  | Solution                                                   |
|---------------------------------------------|----------------------------------------|------------------------------------------------------------|
| "clamdscan is not installed"                | Daemon package missing                 | Install `clamav-daemon` package                            |
| "Daemon not responding: Connection refused" | clamd not running                      | Start service: `sudo systemctl start clamav-daemon`        |
| "Could not find clamd socket"               | Socket doesn't exist or wrong location | Check socket exists, verify clamd.conf LocalSocket setting |
| "Connection to clamd timed out"             | Daemon is frozen or overloaded         | Restart daemon: `sudo systemctl restart clamav-daemon`     |
| "Permission denied" accessing socket        | User not in clamav group               | Add user to group: `sudo usermod -a -G clamav $USER`       |
| Daemon starts then immediately stops        | Database missing or config error       | Run `sudo freshclam`, check daemon logs                    |

💡 **Tip:** If the daemon continues to have issues, you can still use ClamUI effectively with the `clamscan` backend. Go
to Preferences → Scan Backend and select "Clamscan" instead of "Auto" or "Daemon".

⚠️ **Note:** After making daemon configuration changes or group membership changes, you may need to:

1. Restart the daemon service
2. Log out and back in (for group changes)
3. Restart ClamUI

---

### Scan Errors

**Problem:** Scans fail to complete or return errors instead of results.

**Symptoms:**

- Scan stops with error message
- Status shows "Scan error" with red warning icon
- Error messages in scan results or logs
- Scans never start or immediately fail

#### Common Scan Errors

##### Error: "No path specified"

**Cause:** No file or folder was selected for scanning.

**Solution:**

1. Click the **Browse** button to select a file or folder
2. Or drag and drop a file/folder onto the main window
3. Or use a scan profile (Quick Scan, Full Scan, Home Folder)

##### Error: "Path does not exist"

**Cause:** The file or folder you're trying to scan has been deleted, moved, or renamed.

**Solution:**

1. Verify the path still exists: `ls -la /path/to/folder`
2. Select a different, existing file or folder
3. If using a scan profile, edit the profile to update the path
4. If using command-line arguments, check for typos in the path

##### Error: "Permission denied: Cannot read"

**Cause:** You don't have permission to access the file or folder.

**Solution:**

**For user files:**

```bash
# Make file readable
chmod +r /path/to/file

# For folders, add execute permission
chmod +rx /path/to/folder
```

**For system files (requires sudo):**

```bash
# Scan with elevated permissions (advanced users only)
sudo clamui
```

⚠️ **Warning:** Running ClamUI as root (with sudo) can be dangerous. Only do this if you need to scan system directories
you don't own, and be careful not to quarantine critical system files.

**Better approach for system scans:**

1. Use the **Full Scan** profile (already excludes dangerous system areas)
2. Or add specific system directories you need to scan to a custom profile
3. System scans will skip files you can't read (this is normal and safe)

##### Error: "Symlink escapes to protected directory"

**Cause:** The path contains a symbolic link that points outside your user directories to a protected system area.

**Solution:**

1. This is a security feature to prevent scanning system files unintentionally
2. If you need to scan the target, navigate to the actual directory (not the symlink)
3. Or scan the symlink target directly: `readlink -f /path/to/symlink` to see where it points

##### Error: "Daemon not available" or "clamd not accessible"

**Cause:** Scan backend is set to "Daemon" but clamd isn't running.

**Solution:**

1. See [Daemon Connection Issues](#daemon-connection-issues) for detailed troubleshooting
2. Or change scan backend to "Clamscan" in Preferences → Scan Backend
3. Restart ClamUI and try scanning again

##### Error: "Database initialization error" or "No supported database files found"

**Cause:** ClamAV virus definitions are missing or corrupted.

**Solution:**

**Update virus definitions:**

```bash
sudo freshclam
```

**If freshclam fails, check:**

```bash
# Check database location
ls -la /var/lib/clamav/

# Should see files like:
# main.cvd or main.cld
# daily.cvd or daily.cld
# bytecode.cvd or bytecode.cld
```

**If database files are missing:**

```bash
# Remove any corrupted files
sudo rm /var/lib/clamav/*.cvd
sudo rm /var/lib/clamav/*.cld

# Re-download fresh databases
sudo freshclam
```

**Check database update logs:**

```bash
sudo tail -f /var/log/clamav/freshclam.log
```

##### Error: "Scan timeout" or "Process killed"

**Cause:**

- Scanning very large files or directories
- System ran out of memory
- Scan took too long and was terminated

**Solution:**

**For large scans:**

1. Break up the scan into smaller chunks
2. Create custom profiles for specific subdirectories
3. Add exclusions for very large files you don't need to scan
4. Use daemon backend for better performance (10-50x faster)

**Check available memory:**

```bash
free -h
```

ClamAV needs ~100-200 MB of RAM typically. Large archive files can require more.

**Increase system resources:**

- Close other applications to free RAM
- Disable browser with many tabs open
- Wait for other resource-intensive tasks to complete

**Exclude very large files:**

```bash
# Example: Exclude files over 1 GB
# In Preferences → Scanner Configuration → clamd.conf:
MaxFileSize 1000M
MaxScanSize 1000M
```

##### Error: "Archive: Encrypted" or "Archive: Unsupported"

**Cause:** The file is a password-protected archive or uses an unsupported archive format.

**Status:** This is informational, not an error.

**Explanation:**

- ClamAV cannot scan inside encrypted (password-protected) archives
- This is expected behavior - the file itself isn't infected, just cannot be fully scanned
- Common with: password-protected .zip, .7z, .rar files

**What to do:**

1. If you trust the source, you can ignore this message
2. If suspicious, extract the archive and scan the contents manually
3. Consider adding an exclusion if you frequently see this for trusted archives

##### Error: "Heuristics.Limits.Exceeded"

**Cause:** File exceeds ClamAV's scanning limits (file size, recursion depth, or file count in archive).

**Status:** Partial scan completed, but some content was skipped.

**Solution:**

1. Usually safe to ignore for personal files (photos, videos, large documents)
2. The file isn't necessarily infected - just too complex to fully scan
3. To scan anyway, increase limits in Preferences → Scanner Configuration:
    - `MaxFileSize` - Maximum individual file size
    - `MaxScanSize` - Maximum data scanned per archive
    - `MaxRecursion` - Depth of nested archives
    - `MaxFiles` - Files to scan in an archive

⚠️ **Warning:** Increasing limits too high can cause scans to take a very long time or consume excessive RAM.

#### Scan Error Troubleshooting Table

| Error Message                                    | Cause                          | Quick Fix                                                 |
|--------------------------------------------------|--------------------------------|-----------------------------------------------------------|
| "No path specified"                              | Nothing selected               | Select a file/folder or use a profile                     |
| "Path does not exist"                            | File/folder moved or deleted   | Select an existing path                                   |
| "Permission denied"                              | Insufficient file permissions  | Use `chmod +r` or scan as owner                           |
| "Symlink escapes to protected directory"         | Security check triggered       | Scan the actual target directory                          |
| "Remote files cannot be scanned"                 | Tried to scan network location | Copy file to local disk first                             |
| "Daemon not available"                           | clamd not running              | See [Daemon Connection Issues](#daemon-connection-issues) |
| "Database initialization error"                  | Missing virus definitions      | Run `sudo freshclam`                                      |
| "Can't allocate memory"                          | Out of RAM                     | Close other apps, scan smaller directory                  |
| "Archive: Encrypted"                             | Password-protected file        | Extract and scan contents manually                        |
| "Heuristics.Limits.Exceeded"                     | File too complex               | Increase limits in Scanner Configuration                  |
| "LibClamAV Error: cli_scandesc: Can't read file" | File locked or in use          | Close programs using the file                             |

#### General Troubleshooting Steps

If you're experiencing persistent scan errors:

1. **Check ClamAV installation:**
   ```bash
   clamscan --version
   ```

2. **Update virus definitions:**
   ```bash
   sudo freshclam
   ```

3. **Test with EICAR:**
    - Click the **Test with EICAR** button in scan view
    - Should detect "Eicar-Test-Signature"
    - If this fails, ClamAV isn't working correctly

4. **Check scan logs:**
    - Navigate to **Logs** view
    - Find the failed scan entry
    - Click to view full output
    - Look for specific error messages

5. **Try different scan backend:**
    - Go to Preferences → Scan Backend
    - Try "Clamscan" if "Auto" or "Daemon" is failing
    - Or try "Auto" if "Clamscan" is having issues

6. **Check system resources:**
   ```bash
   df -h  # Check disk space
   free -h  # Check available RAM
   ```

7. **Review exclusions:**
    - Check if path is being excluded in global exclusions
    - Preferences → Managing Exclusion Patterns
    - Or profile exclusions if using a scan profile

💡 **Tip:** When reporting scan errors, include:

- The exact error message from ClamUI
- The path you were trying to scan
- Output from: `clamscan --version`
- Output from: `ls -la /path/to/file/or/folder`
- Contents of scan log from Logs view

---

### Quarantine Problems

**Problem:** Issues with quarantining, restoring, or deleting quarantined files.

**Symptoms:**

- Cannot quarantine detected threats
- Error when trying to restore files
- Quarantine view shows errors
- Files missing from quarantine
- Disk space issues

#### Common Quarantine Errors

##### Error: "Permission denied" (quarantine)

**Cause:** ClamUI cannot write to the quarantine directory.

**Solution:**

**Check quarantine directory permissions:**

```bash
ls -la ~/.local/share/clamui/quarantine/
```

**Fix permissions:**

```bash
chmod 700 ~/.local/share/clamui/quarantine/
chown $USER:$USER ~/.local/share/clamui/quarantine/
```

**For Flatpak:**

```bash
ls -la ~/.var/app/io.github.linx_systems.ClamUI/data/clamui/quarantine/
chmod 700 ~/.var/app/io.github.linx_systems.ClamUI/data/clamui/quarantine/
```

##### Error: "Disk full" or "No space left on device"

**Cause:** Not enough disk space to move file to quarantine.

**Solution:**

**Check available space:**

```bash
df -h ~/.local/share/clamui/
```

**Free up space:**

```bash
# Clear old quarantine items (30+ days old)
# Via ClamUI: Quarantine view → Clear Old Items button

# Or check current quarantine size:
du -sh ~/.local/share/clamui/quarantine/
```

**Manually delete old quarantine files (advanced):**

```bash
# List quarantine files by age
ls -lt ~/.local/share/clamui/quarantine/

# Remove specific file (if you know it's safe)
rm ~/.local/share/clamui/quarantine/quarantine_XXXXXX
```

⚠️ **Warning:** Manual deletion bypasses integrity checks. Use the ClamUI interface when possible.

##### Error: "File already quarantined"

**Cause:** The file has already been moved to quarantine in a previous scan.

**Status:** This is informational, not an error.

**What happened:**

- The file was already quarantined earlier
- You're trying to quarantine it again
- This is prevented to avoid duplicates

**Solution:**

1. Check the Quarantine view to see the existing entry
2. No action needed - file is already safely isolated

##### Error: "Restore destination already exists"

**Cause:** Trying to restore a file to its original location, but a file with that name already exists there.

**Solution:**

**Option 1: Rename or move the existing file**

```bash
# Move the existing file to a backup location
mv /path/to/original/file /path/to/original/file.backup
```

Then retry restore in ClamUI.

**Option 2: Delete the existing file (if safe)**

```bash
# Only if you're sure the existing file is unwanted
rm /path/to/original/file
```

**Option 3: Copy quarantined file to different location**

Instead of restoring to original location:

1. Manually copy from quarantine (advanced):
   ```bash
   # Find the quarantined file
   ls ~/.local/share/clamui/quarantine/

   # Copy to safe location
   cp ~/.local/share/clamui/quarantine/quarantine_XXXXXX ~/Desktop/recovered_file
   ```

2. Then delete from quarantine via ClamUI interface

##### Error: "Database error" during quarantine

**Cause:** The quarantine database (quarantine.db) is corrupted or locked.

**Solution:**

**Check database:**

```bash
# View database location
ls -la ~/.local/share/clamui/quarantine.db

# Check if database is locked
lsof ~/.local/share/clamui/quarantine.db
```

**If database is corrupted:**

```bash
# Backup existing database
cp ~/.local/share/clamui/quarantine.db ~/.local/share/clamui/quarantine.db.backup

# Verify database with SQLite
sqlite3 ~/.local/share/clamui/quarantine.db "PRAGMA integrity_check;"
```

Expected output: `ok`

**If integrity check fails:**

```bash
# Try to repair
sqlite3 ~/.local/share/clamui/quarantine.db ".recover" > repaired.sql
sqlite3 ~/.local/share/clamui/quarantine_new.db < repaired.sql

# Backup old and replace
mv ~/.local/share/clamui/quarantine.db ~/.local/share/clamui/quarantine.db.corrupt
mv ~/.local/share/clamui/quarantine_new.db ~/.local/share/clamui/quarantine.db
```

⚠️ **Warning:** Database corruption is rare but can result in lost quarantine metadata. The quarantined files themselves
should still be safe in the quarantine/ directory.

##### Error: "Entry not found" when restoring

**Cause:** The quarantine database has a record, but the actual quarantined file is missing.

**Possible reasons:**

- File was manually deleted from quarantine directory
- Disk error or corruption
- External process removed the file

**Solution:**

**Verify file is really missing:**

```bash
# Check quarantine directory
ls -la ~/.local/share/clamui/quarantine/
```

**If file is truly gone:**

1. The file cannot be restored (it's been permanently deleted)
2. You can delete the database entry via ClamUI:
    - Open Quarantine view
    - Find the entry
    - Click **Delete** button
    - This removes the orphaned database record

##### Quarantine File Missing After Restart

**Cause:** Quarantine database and directory out of sync.

**Solution:**

**Refresh quarantine view:**

1. Click the Refresh button in Quarantine view
2. Close and reopen ClamUI

**Verify files are actually in quarantine:**

```bash
# List all quarantined files
ls -la ~/.local/share/clamui/quarantine/

# Check database entries
sqlite3 ~/.local/share/clamui/quarantine.db "SELECT original_path, quarantine_path FROM quarantine;"
```

**Manually reconcile (advanced):**

If you see files in the directory but not in the database, or vice versa, you may need to manually clean up:

```bash
# List files in directory
ls ~/.local/share/clamui/quarantine/

# List entries in database
sqlite3 ~/.local/share/clamui/quarantine.db "SELECT * FROM quarantine;"
```

If they don't match, the safest approach is:

1. Export important files from quarantine before cleanup
2. Clear all quarantine (Quarantine view → Clear Old Items won't work for this)
3. Manually remove quarantine files:
   ```bash
   rm -rf ~/.local/share/clamui/quarantine/*
   ```
4. Delete and recreate database:
   ```bash
   rm ~/.local/share/clamui/quarantine.db
   # Database will be recreated on next launch
   ```

#### Quarantine Troubleshooting Table

| Error                        | Cause                                   | Solution                                                       |
|------------------------------|-----------------------------------------|----------------------------------------------------------------|
| "Permission denied"          | Cannot write to quarantine directory    | Fix permissions: `chmod 700 ~/.local/share/clamui/quarantine/` |
| "Disk full"                  | Not enough space                        | Clear old quarantine items or free disk space                  |
| "File already quarantined"   | Duplicate quarantine attempt            | Check Quarantine view for existing entry                       |
| "Restore destination exists" | File exists at original location        | Rename/move existing file first                                |
| "Database error"             | Corrupted or locked database            | Check with SQLite, repair if needed                            |
| "Entry not found"            | File missing from quarantine            | Delete orphaned database entry                                 |
| "File not found"             | Original file deleted before quarantine | Nothing to quarantine - informational only                     |
| "Hash mismatch" on restore   | File modified/corrupted in quarantine   | Don't restore - file integrity compromised                     |

#### Quarantine Storage Maintenance

**Check quarantine size:**

```bash
du -sh ~/.local/share/clamui/quarantine/
```

**View quarantine contents:**

```bash
ls -lh ~/.local/share/clamui/quarantine/
```

**Count quarantined items:**

```bash
ls -1 ~/.local/share/clamui/quarantine/ | wc -l
```

**Safe cleanup:**

1. Use ClamUI's **Clear Old Items** feature (removes items 30+ days old)
2. Review and delete individual items via Quarantine view
3. Only use manual file deletion as a last resort

💡 **Tip:** Regular maintenance prevents quarantine storage issues:

- Review quarantine monthly
- Delete confirmed threats (CRITICAL/HIGH severity)
- Keep potential false positives (LOW severity) for verification
- Use "Clear Old Items" every few months
- Monitor disk space if you scan frequently

---

### Scheduled Scan Not Running

**Problem:** Automated scheduled scans are not executing as expected.

**Symptoms:**

- No scan logs appearing at scheduled time
- Scheduled scan shows as "enabled" but never runs
- Battery-powered laptop always skips scans
- Scan happens but no notifications
- Scheduled scan logs show errors

#### Understanding Scheduled Scans

ClamUI uses your system's scheduler to run scans automatically:

- **Primary**: systemd user timers (most modern Linux systems)
- **Fallback**: cron (older systems or if systemd unavailable)

Scheduled scans run even when ClamUI GUI is closed, as long as your computer is powered on.

#### Solution 1: Verify Scheduler is Available

**Check which scheduler is available:**

```bash
# Check systemd
systemctl --user status
# If this works, systemd is available

# Check cron
which crontab
# If this returns a path, cron is available
```

**If neither is available:**

- Scheduled scans cannot work without a system scheduler
- Your system may not have systemd or cron installed
- Install cron: `sudo apt install cron` (Ubuntu/Debian)

#### Solution 2: Verify Schedule is Enabled

**In ClamUI:**

1. Open Preferences (hamburger menu → Preferences, or Ctrl+,)
2. Scroll to **Scheduled Scans** section
3. Check that **Enable scheduled scans** is toggled ON
4. Verify schedule settings (frequency, time, targets)
5. Click **Save & Apply**

⚠️ **Important:** Changes to scheduled scans require clicking **Save & Apply** to take effect. The schedule won't
activate until you do this.

#### Solution 3: Check Systemd Timer Status

If using systemd (most common):

**Check timer status:**

```bash
systemctl --user status clamui-scheduled-scan.timer
```

**Expected output:**

```
● clamui-scheduled-scan.timer - ClamUI Scheduled Scan
     Loaded: loaded (/home/user/.config/systemd/user/clamui-scheduled-scan.timer; enabled)
     Active: active (waiting) since ...
```

**If timer is not found:**

```bash
# List all ClamUI-related user timers
systemctl --user list-timers | grep clamui

# If nothing appears, the schedule wasn't created
# Try re-saving in ClamUI Preferences
```

**If timer is "dead" or "failed":**

```bash
# Reload systemd user daemon
systemctl --user daemon-reload

# Restart the timer
systemctl --user restart clamui-scheduled-scan.timer

# Enable it for autostart
systemctl --user enable clamui-scheduled-scan.timer
```

**Check next scheduled run:**

```bash
systemctl --user list-timers clamui-scheduled-scan.timer
```

Shows when the next scan will run.

**View timer configuration:**

```bash
cat ~/.config/systemd/user/clamui-scheduled-scan.timer
```

**View service configuration:**

```bash
cat ~/.config/systemd/user/clamui-scheduled-scan.service
```

#### Solution 4: Check Cron Schedule

If using cron:

**View crontab:**

```bash
crontab -l | grep clamui
```

**Expected output (example for daily at 2:00 AM):**

```
0 2 * * * /usr/bin/clamui-scheduled-scan --target /home/user
```

**If nothing appears:**

- The schedule wasn't created properly
- Try re-saving in ClamUI Preferences → Scheduled Scans

**Test cron is working:**

```bash
# Add a simple test job (runs every minute)
(crontab -l ; echo "* * * * * echo 'Cron works' >> /tmp/cron-test.log") | crontab -

# Wait 2 minutes, then check:
cat /tmp/cron-test.log

# Should show timestamps. If it does, cron is working.

# Remove test job:
crontab -l | grep -v "Cron works" | crontab -
rm /tmp/cron-test.log
```

#### Solution 5: Check Battery-Aware Settings

If you're on a laptop and scans never run:

**Symptom:** Scheduled scan always skips due to "Running on battery power"

**Check battery-aware setting:**

1. Preferences → Scheduled Scans
2. Look for **Skip scans when running on battery**
3. If enabled and you're always on battery, scans will never run

**Solutions:**

- **Disable battery-aware scanning** if you want scans to run even on battery
- **Plug in laptop** at scheduled scan time
- **Change schedule time** to when laptop is typically plugged in

**Verify in logs:**

1. Navigate to Logs view
2. Look for scheduled scan entries around the scheduled time
3. If you see: "Skipped scan - running on battery power" - this is the issue

#### Solution 6: Check Scan Targets Are Valid

**Invalid targets prevent scans from running.**

**Verify targets exist:**

```bash
# Example: if target is /home/user/Downloads
ls /home/user/Downloads
```

**Common issues:**

- Path doesn't exist (typo, folder moved/deleted)
- Path is on external drive that's not connected
- Permission denied (user can't read directory)

**Check in Preferences:**

1. Preferences → Scheduled Scans → Configure Scan Targets
2. Verify all paths are correct and exist
3. Remove any invalid paths
4. Save & Apply

#### Solution 7: Test Scheduled Scan Manually

Run the scheduled scan command manually to see errors:

**For systemd:**

```bash
# Trigger the service manually
systemctl --user start clamui-scheduled-scan.service

# View output/errors
journalctl --user -u clamui-scheduled-scan.service -n 50
```

**For cron or manual test:**

```bash
# Run the scheduled scan script directly
clamui-scheduled-scan --target ~/Downloads

# Or with full path:
/usr/bin/clamui-scheduled-scan --target ~/Downloads
```

**Check for errors:**

- "ClamAV not found" - see [ClamAV Not Found](#clamav-not-found)
- "Permission denied" - see [Scan Errors](#scan-errors)
- "No targets specified" - add targets in Preferences
- Command not found - scheduled scan CLI not installed properly

#### Solution 8: Check Notifications

**Scans might be running, but you're not seeing notifications.**

**Verify notifications are enabled:**

1. Preferences → Notification Settings
2. Ensure **Enable desktop notifications** is checked
3. Save & Apply

**Check system notifications are working:**

```bash
# Send test notification
notify-send "Test" "This is a test notification"
```

If you don't see it, your desktop notification system may not be working.

**Check scan logs:**

1. Navigate to Logs view
2. Look for entries with scheduled icon (if it exists in logs)
3. Check timestamps match your schedule
4. If scans appear in logs, they ARE running - just notification issue

#### Solution 9: Check Logs for Scheduled Scan Errors

**View scheduled scan results:**

1. Open Logs view
2. Look for scans at your scheduled time
3. Click to view full details
4. Look for error messages in output

**Common log errors:**

| Log Error                           | Cause                         | Solution                      |
|-------------------------------------|-------------------------------|-------------------------------|
| "Skipped scan - running on battery" | Battery-aware setting enabled | Disable or plug in laptop     |
| "Target path does not exist"        | Invalid scan target           | Update targets in Preferences |
| "Permission denied"                 | Cannot access target          | Fix directory permissions     |
| "ClamAV not found"                  | ClamAV not installed          | Install ClamAV                |
| "Database outdated"                 | Virus definitions old         | Run `sudo freshclam`          |
| No log entries at scheduled time    | Scan not running at all       | Check timer/cron status       |

#### Troubleshooting Table

| Symptom                        | Cause                                    | Solution                                                    |
|--------------------------------|------------------------------------------|-------------------------------------------------------------|
| No scans appearing in logs     | Schedule not enabled or not saved        | Re-enable and click Save & Apply                            |
| Timer shows "dead" or "failed" | Systemd timer not started                | Run: `systemctl --user restart clamui-scheduled-scan.timer` |
| Cron schedule missing          | Crontab entry not created                | Re-save schedule in Preferences                             |
| Always skips on battery        | Battery-aware enabled, always on battery | Disable battery-aware or plug in                            |
| Scans at wrong time            | Timezone or time format issue            | Check time setting is HH:MM format (24-hour)                |
| No notifications but scans run | Notifications disabled or broken         | Check Preferences → Notifications                           |
| "Target path does not exist"   | Invalid target path                      | Update targets in Preferences                               |
| Systemd timer not found        | systemd not available                    | Check if cron fallback is working                           |

#### Verifying Scheduled Scans Work

**Complete verification workflow:**

1. **Set up a test schedule:**
    - Preferences → Scheduled Scans
    - Enable scheduled scans
    - Frequency: Hourly (for quick testing)
    - Time: 5 minutes from now (e.g., if it's 14:25, set to 14:30)
    - Targets: ~/Downloads (small directory)
    - Battery-aware: Disabled (for testing)
    - Save & Apply

2. **Verify schedule is active:**
   ```bash
   # For systemd:
   systemctl --user list-timers clamui-scheduled-scan.timer

   # For cron:
   crontab -l | grep clamui
   ```

3. **Wait for scheduled time to pass**

4. **Check logs:**
    - Open ClamUI → Logs view
    - Refresh
    - Look for new scan entry at scheduled time

5. **If scan ran successfully:**
    - You'll see the scan entry with results
    - Change schedule back to your desired frequency (daily/weekly/monthly)
    - Don't forget to Save & Apply!

6. **If no scan appeared:**
    - Check system logs:
      ```bash
      # Systemd:
      journalctl --user -u clamui-scheduled-scan -n 50
 
      # Cron:
      grep clamui /var/log/syslog
      ```

💡 **Tip:** The scheduled scan system uses the `clamui-scheduled-scan` command-line tool. You can test it directly:

```bash
clamui-scheduled-scan --help
clamui-scheduled-scan --target ~/Downloads
```

---

### Performance Issues

**Problem:** ClamUI or scans are running slowly, consuming excessive resources, or causing system lag.

**Symptoms:**

- Scans take an extremely long time
- Computer becomes unresponsive during scans
- High CPU usage (100%)
- Excessive RAM consumption
- UI freezes or becomes sluggish
- System fans running at full speed

#### Understanding Scan Performance

**Typical scan durations:**

- **Quick Scan** (Downloads folder): 10-30 seconds
- **Home folder scan**: 10-30 minutes
- **Full system scan**: 30-90+ minutes

**Factors affecting speed:**

1. **Scan backend**: Daemon is 10-50x faster than clamscan
2. **File count**: More files = longer scan
3. **File sizes**: Large files take longer
4. **File types**: Archives, compressed files are slower
5. **Storage speed**: SSD is much faster than HDD
6. **System resources**: CPU, RAM availability

#### Solution 1: Use Daemon Backend

**The single biggest performance improvement.**

**Check current backend:**

1. Preferences → Scan Backend Options
2. Current setting: Auto / Daemon / Clamscan

**If set to "Clamscan":**

- This is the slowest option
- Change to "Auto" or "Daemon" for 10-50x speedup

**If set to "Auto" or "Daemon" but still slow:**

- Check if daemon is actually running
- See [Daemon Connection Issues](#daemon-connection-issues)

**Verify daemon is being used:**

1. Start a scan
2. In another terminal, check running processes:
   ```bash
   ps aux | grep -E "clamscan|clamdscan"
   ```
3. If you see `clamdscan` - daemon is being used (fast)
4. If you see `clamscan` - falling back to slow method

**Performance comparison:**

```
Scanning 1000 files (~500 MB):
- With daemon (clamdscan): 30 seconds
- Without daemon (clamscan): 8 minutes

Scanning 10,000 files (~2 GB):
- With daemon (clamdscan): 4 minutes
- Without daemon (clamscan): 45 minutes
```

#### Solution 2: Reduce Scan Scope

**Don't scan more than necessary.**

**Use exclusions:**

1. Preferences → Managing Exclusion Patterns
2. Add common patterns to exclude:
    - `node_modules` (if you're a developer)
    - `.git` (version control directories)
    - `.cache` (browser/application caches)
    - `*.iso` (large ISO images you trust)

**Recommended exclusions for performance:**

| Pattern        | Saves Time | Why Exclude                                 |
|----------------|------------|---------------------------------------------|
| `node_modules` | +++++      | Thousands of small files, rarely infected   |
| `.git`         | +++        | Many small objects, version controlled code |
| `__pycache__`  | ++         | Generated Python cache files                |
| `.cache`       | ++++       | Application caches, frequently changing     |
| `build/`       | +++        | Compiled output, regenerated often          |
| `dist/`        | +++        | Distribution builds, trusted source code    |
| `.venv/`       | ++++       | Python virtual environments                 |
| `*.vmdk`       | +++++      | Virtual machine disk images (huge)          |
| `*.iso`        | +++++      | OS images (very large, trusted)             |

**Create targeted profiles:**

- Instead of Full System Scan, create profiles for specific areas
- Example: "Documents Only" scanning ~/Documents
- Example: "Downloads Only" (Quick Scan already does this)

#### Solution 3: Adjust ClamAV Limits

**Reduce resource consumption by limiting what ClamAV scans inside files.**

**Edit scanner limits:**

1. Preferences → Scanner Configuration
2. Click to edit clamd.conf (for daemon) or use clamscan options

**Key limits to adjust:**

```
# Maximum file size to scan (default: 25 MB)
MaxFileSize 100M

# Maximum data to scan from each file (default: 100 MB)
MaxScanSize 100M

# Maximum recursion depth for archives (default: 17)
MaxRecursion 10

# Maximum files to scan in an archive (default: 10000)
MaxFiles 5000
```

**Recommended for performance:**

- **Desktop users**: MaxFileSize 50M, MaxScanSize 100M
- **Developers**: MaxFileSize 100M, MaxRecursion 8
- **Low-end systems**: MaxFileSize 25M, MaxScanSize 50M, MaxFiles 3000

**Trade-offs:**

- ✅ Faster scans, less RAM usage
- ❌ Very large files won't be fully scanned
- ❌ Deeply nested archives might be skipped

For most users, these limits are fine - files exceeding limits are usually:

- Virtual machine images
- Large video files
- OS installation ISOs
- Massive compressed archives

#### Solution 4: Scan During Idle Time

**If scans slow down your work, schedule them for when you're away.**

**Best practices:**

1. Use scheduled scans instead of manual scans
2. Set schedule for:
    - Early morning (e.g., 2:00 AM if computer left on)
    - Lunch break (e.g., 12:00 PM)
    - Evening (e.g., 6:00 PM after work)
3. Enable "Skip on battery" for laptops
4. Use background scanning + minimize to tray

**Scheduled scan advantages:**

- Runs when you're not using the computer
- Can use lower priority (nice level)
- Won't interrupt your work

#### Solution 5: Close Other Applications

**ClamAV competes for resources.**

**Before large scans:**

- Close web browsers (especially Chrome with many tabs)
- Close IDEs and development tools
- Close video players, games
- Close other resource-intensive apps

**Check what's using resources:**

```bash
# CPU usage
top
# Press P to sort by CPU
# Press M to sort by memory

# Or use htop (more user-friendly)
htop
```

**Check available RAM:**

```bash
free -h
```

ClamAV needs:

- ~100-200 MB for daemon
- ~50-100 MB for clamscan
- More for large archives (can spike to 500 MB+)

#### Solution 6: Scan on SSD Not HDD

**Storage speed is crucial for scan performance.**

**If possible:**

- Copy files to SSD before scanning (if scanning external HDD)
- Install ClamAV database on SSD partition
- Use profiles to scan SSD-backed directories first

**Check storage type:**

```bash
# List block devices
lsblk -o NAME,ROTA,TYPE,SIZE,MOUNTPOINT

# ROTA=1 means HDD (rotational)
# ROTA=0 means SSD (non-rotational)
```

**Performance difference:**

- **SSD**: Can scan 1000 files in 20-30 seconds
- **HDD**: Same scan might take 2-5 minutes

#### Solution 7: Use Nice Priority for Background Scans

**Lower CPU priority for scheduled scans so they don't slow down other work.**

**For manual nice adjustment (advanced):**

```bash
# Run scan with low priority
nice -n 19 clamui-scheduled-scan --target ~/Downloads

# Or for systemd (edit service file):
nano ~/.config/systemd/user/clamui-scheduled-scan.service

# Add under [Service]:
# Nice=19
# IOSchedulingClass=idle
```

**What this does:**

- `Nice=19`: Lowest CPU priority (don't slow down other apps)
- `IOSchedulingClass=idle`: Only use disk when nothing else is

#### Solution 8: Update ClamAV and Virus Definitions

**Older versions may be less optimized.**

**Check ClamAV version:**

```bash
clamscan --version
```

**Update to latest:**

```bash
# Ubuntu/Debian:
sudo apt update
sudo apt upgrade clamav clamav-daemon

# Check if newer version is available:
apt-cache policy clamav
```

**Update virus definitions:**

```bash
sudo freshclam
```

Outdated definitions can sometimes cause performance issues.

#### Performance Troubleshooting Table

| Symptom                               | Cause                                 | Solution                                          |
|---------------------------------------|---------------------------------------|---------------------------------------------------|
| Scans taking 10x longer than expected | Using clamscan instead of daemon      | Enable daemon backend                             |
| High CPU (100%) during scan           | Normal for clamscan                   | Use daemon or reduce MaxRecursion                 |
| Extremely high RAM usage (>1 GB)      | Scanning huge archive files           | Reduce MaxFileSize and MaxScanSize                |
| System freezes during scan            | Clamscan blocking I/O                 | Use daemon, reduce scan scope, add exclusions     |
| Slow scans on specific folders        | Many small files (node_modules, .git) | Add exclusions for these directories              |
| UI becomes unresponsive               | Main thread blocked                   | Normal during scan startup - wait a few seconds   |
| Laptop fans at full speed             | High CPU usage from scanning          | Use scheduled scans, enable battery-aware mode    |
| Scan never completes                  | Huge directory or infinite loop       | Break into smaller scans, check for symlink loops |

#### Performance Checklist

For best performance:

- ✅ Use daemon backend (Preferences → Scan Backend → Auto)
- ✅ Add exclusions for dev folders (node_modules, .git, .cache)
- ✅ Set reasonable limits (MaxFileSize: 100M, MaxRecursion: 10)
- ✅ Scan on SSD if possible, not external HDD
- ✅ Close resource-heavy apps before large scans
- ✅ Use scheduled scans during idle time
- ✅ Keep ClamAV and definitions updated
- ✅ Create targeted profiles instead of full system scans

**Expected performance benchmarks:**

```
With daemon backend + SSD + modern CPU:
- 100 files (~50 MB): ~5 seconds
- 1,000 files (~500 MB): ~30 seconds
- 10,000 files (~2 GB): ~4 minutes
- 100,000 files (~10 GB): ~30 minutes

Without daemon (clamscan) - multiply by 10-50x
On HDD - add 2-5x more time
With low-end CPU - add 1.5-2x more time
```

💡 **Tip:** If you need maximum performance and security isn't critical (e.g., scanning known-safe development files),
you can:

1. Disable scanning of archives: `ScanArchive no` in clamd.conf
2. Disable heuristic checks: `HeuristicScanPrecedence no`
3. Scan specific file types only: `--include=*.exe` flag

⚠️ **Warning:** Disabling features reduces detection capability. Only do this if you understand the trade-offs.

---

**Troubleshooting Summary:**

If you're still experiencing issues after trying these solutions:

1. **Check system logs:**
   ```bash
   journalctl -xe
   dmesg | tail
   ```

2. **Test ClamAV directly:**
   ```bash
   clamscan --version
   clamscan ~/Downloads
   ```

3. **Report an issue:**
    - Visit [GitHub Issues](https://github.com/linx-systems/clamui/issues)
    - Include: OS version, ClamAV version, exact error message, steps to reproduce
    - Attach scan/update logs from the **Logs** view
    - For deeper diagnostics, attach a debug-log bundle: Preferences → **Debug** → **Export Logs** writes a
      privacy-redacted ZIP (file paths, hashes, and report URLs are stripped). Raise verbosity first with
      Preferences → **Debug** → **Log Level** (the `debug_log_level` setting), reproduce the issue, then export.
      Debug logs live in `~/.local/share/clamui/debug/`, separate from the scan/update history in
      `~/.local/share/clamui/logs/`.

4. **Get help:**
    - Check the [FAQ](faq.md) for common questions
    - Review [DEVELOPMENT.md](../DEVELOPMENT.md) for technical details

💡 **Tip:** When troubleshooting, start with the simplest solution first:

1. Test with EICAR button (verifies ClamAV works)
2. Try scanning a small, known directory (~/Downloads)
3. Check scan logs for specific error messages
4. Only then dive into system-level debugging

---
