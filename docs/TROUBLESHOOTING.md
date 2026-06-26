# Troubleshooting Guide

This guide covers common issues and solutions for ClamUI.

## Table of Contents

1. [Flatpak-Specific Issues](#flatpak-specific-issues)
2. [ClamAV Installation Issues](#clamav-installation-issues)
3. [File Manager Context Menu Issues](#file-manager-context-menu-issues)
4. [System Tray Icon Issues](#system-tray-icon-issues)
5. [Scan Issues](#scan-issues)
6. [Database Update Issues](#database-update-issues)

---

## Flatpak-Specific Issues

### ClamAV Not Working in Flatpak

**Symptom:** Scans fail or ClamAV commands don't work in the Flatpak version.

**Note:** The ClamUI Flatpak does not bundle ClamAV. Install ClamAV on the host system; ClamUI runs host
`clamscan`, `freshclam`, and `clamdscan` through `flatpak-spawn --host`.

**Possible causes and solutions:**

1. **Host ClamAV not installed**: Install ClamAV with your distribution package manager.
2. **Virus definitions not downloaded**: Run a database update from within ClamUI or run `sudo freshclam` on the host.
3. **Corrupted installation**: Try reinstalling the Flatpak:
   ```bash
   flatpak uninstall io.github.linx_systems.ClamUI
   flatpak install flathub io.github.linx_systems.ClamUI
   ```
4. **Check for errors**: Open **Preferences → Debug** and use **Export Logs**, or inspect the debug logs in `~/.var/app/io.github.linx_systems.ClamUI/data/clamui/debug/`

### Permission Denied Errors

**Symptom:** "Permission denied" when scanning certain directories.

**Cause:** Flatpak sandbox permissions may not cover all directories.

**Solution:**

Grant additional filesystem access:

```bash
# Grant access to a specific directory
flatpak override --user --filesystem=/path/to/directory io.github.linx_systems.ClamUI

# Or grant broader access (use with caution)
flatpak override --user --filesystem=host io.github.linx_systems.ClamUI
```

### Freshclam Database Updates Fail

**Symptom:** Database updates fail with permission or path errors in Flatpak.

**Cause:** Host `freshclam` needs network access and usually administrator/service permissions to update the host
database directory.

**Solution:**

ClamUI runs host `freshclam` from inside the Flatpak. If updates fail:

1. Check host ClamAV is installed (`clamscan --version`, `freshclam --version`)
2. Verify internet connectivity
3. Check the host `freshclam.conf` path shown in Preferences
4. Try `sudo freshclam` on the host to confirm ClamAV can update outside ClamUI

---

## ClamAV Installation Issues

> **Note:** This section applies to all installation methods, including Flatpak. The Flatpak version requires host
> ClamAV.

### clamscan Not Found

**Symptom:** ClamUI cannot find the `clamscan` binary.

**Solution:**

1. Install ClamAV:

   ```bash
   # Ubuntu/Debian
   sudo apt install clamav

   # Fedora
   sudo dnf install clamav

   # Arch Linux
   sudo pacman -S clamav
   ```

2. Verify installation:

   ```bash
   which clamscan
   clamscan --version
   ```

### Virus Definitions Outdated

**Symptom:** ClamUI warns that virus definitions are outdated.

**Solution:**

- Use ClamUI's built-in update feature, or run `sudo freshclam` on the host.

### clamd Daemon Not Running

**Symptom:** Daemon scanner backend unavailable.

**Solution:**

1. Check daemon status:

   ```bash
   sudo systemctl status clamav-daemon
   ```

2. Start the daemon:

   ```bash
   sudo systemctl start clamav-daemon
   sudo systemctl enable clamav-daemon
   ```

3. Verify the socket exists (path varies by distribution):

   ```bash
   # Debian/Ubuntu
   ls -la /var/run/clamav/clamd.ctl   # or /run/clamav/clamd.ctl
   # Fedora/RHEL
   ls -la /run/clamd.scan/clamd.sock
   ```

4. Confirm the daemon responds:

   ```bash
   clamdscan --ping 3
   ```

---

## File Manager Context Menu Issues

### "Scan with ClamUI" Not Appearing

**Symptom:** Right-click menu doesn't show the scan option.

**Cause:** The file manager integration is missing, installed in the wrong directory, or not executable.

**Solution for GNOME (Nautilus):**

1. Create the scripts directory:

   ```bash
   mkdir -p ~/.local/share/nautilus/scripts
   ```

2. Copy the scan script:

   ```bash
   cp /usr/share/clamui/integrations/clamui-scan-nautilus.sh ~/.local/share/nautilus/scripts/Scan\ with\ ClamUI
   chmod +x ~/.local/share/nautilus/scripts/Scan\ with\ ClamUI
   ```

3. Restart Nautilus:

   ```bash
   nautilus -q
   ```

**Solution for KDE (Dolphin):**

1. Create the service menu directory:

   ```bash
   mkdir -p ~/.local/share/kio/servicemenus
   ```

   On older KDE Plasma 5 systems, use `~/.local/share/kservices5/ServiceMenus` instead.

2. Copy the Dolphin service menu files:

   ```bash
   cp /usr/share/kio/servicemenus/io.github.linx_systems.ClamUI.service.desktop ~/.local/share/kio/servicemenus/
   cp /usr/share/kio/servicemenus/io.github.linx_systems.ClamUI-virustotal.desktop ~/.local/share/kio/servicemenus/
   chmod +x ~/.local/share/kio/servicemenus/io.github.linx_systems.ClamUI.service.desktop
   chmod +x ~/.local/share/kio/servicemenus/io.github.linx_systems.ClamUI-virustotal.desktop
   ```

3. Refresh the KDE service cache:

   ```bash
   kbuildsycoca6 --noincremental || kbuildsycoca5 --noincremental
   ```

**Solution for Cinnamon (Nemo):**

1. Create actions directory:

   ```bash
   mkdir -p ~/.local/share/nemo/actions
   ```

2. Copy the Nemo action:

   ```bash
   cp /usr/share/nemo/actions/io.github.linx_systems.ClamUI.nemo_action ~/.local/share/nemo/actions/
   ```

3. Restart Nemo:

   ```bash
   nemo -q
   ```

### Context Menu Shows But Doesn't Work

**Symptom:** Clicking "Scan with ClamUI" does nothing.

**Solution:**

1. Check if ClamUI is installed and executable:

   ```bash
   which clamui
   clamui help
   ```

2. Try running manually with a test file:

   ```bash
   clamui /path/to/test/file
   ```

---

## System Tray Icon Issues

### Tray Icon Not Appearing

**Symptom:** System tray icon doesn't show even when enabled in settings.

**Cause:** Desktop environment does not support the StatusNotifierItem (SNI) D-Bus protocol, or missing tray extension.

**Solution:**

1. ClamUI uses GIO D-Bus to implement the SNI protocol (no external tray library required for the icon itself).

2. For context menus, install libdbusmenu:

   ```bash
   # Ubuntu/Debian
   sudo apt install gir1.2-dbusmenu-0.4

   # Fedora
   sudo dnf install libdbusmenu

   # Arch Linux
   sudo pacman -S libdbusmenu-glib
   ```

3. For GNOME, install a tray extension:
    - [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/)

4. Restart ClamUI.

### Tray Menu Not Working

**Symptom:** Tray icon appears but right-click menu doesn't work.

**Cause:** Desktop environment may not fully support StatusNotifierItem protocol.

**Solution:**

1. Try clicking the icon (some desktops use left-click for menu)
2. Check your desktop environment's system tray settings
3. On GNOME, ensure the AppIndicator extension is enabled and up to date

---

## Scan Issues

### Scans Taking Too Long

**Symptom:** Scans are much slower than expected.

**Solution:**

1. **Use daemon backend**: Switch to `daemon` scan backend in settings for faster scanning
2. **Create exclusion patterns**: Add large directories (like `node_modules`, `.git`) to exclusions
3. **Use scan profiles**: Create focused profiles that target specific directories

### False Positives

**Symptom:** ClamAV reports threats in files you know are safe.

**Solution:**

1. **Verify with VirusTotal**: Use ClamUI's VirusTotal integration to check against multiple engines
2. **Check ClamAV signatures**: Some signatures are known to have false positives
3. **Add to exclusions**: If confirmed safe, add the file pattern to exclusions
4. **Report to ClamAV**: Submit false positives to the ClamAV community

### Scan Hangs or Crashes

**Symptom:** Scan stops responding or ClamUI crashes.

**Solution:**

1. **Check file permissions**: Ensure ClamUI can read the target files
2. **Avoid special files**: Exclude device files, sockets, and virtual filesystems
3. **Check system resources**: Ensure adequate memory and disk space
4. **Try clamscan backend**: Switch from daemon to clamscan backend

### Profile has no Valid targets

**Symptom:** Unable to start the scan using the selected profile. Notification: "Profile <selected profile> has no valid targets."

**Solution:**

1. **Reset Scan Profile**: Return scan profiles to default values

---

## Database Update Issues

### Freshclam Permission Denied

**Symptom:** Database updates fail with permission errors.

**Solution:**

1. For native installations, run with sudo or fix permissions:

   ```bash
   sudo freshclam
   # or fix directory ownership
   sudo chown -R clamav:clamav /var/lib/clamav
   ```

2. For Flatpak, check host ClamAV database permissions and confirm `sudo freshclam` succeeds on the host.

### Network Errors During Update

**Symptom:** Updates fail with connection or timeout errors.

**Solution:**

1. Check internet connectivity
2. Try a different mirror in freshclam configuration
3. Check firewall settings for outbound connections to database.clamav.net

### Corrupt Database Files

**Symptom:** ClamAV reports database errors after update.

**Solution:**

1. Remove corrupt files and re-download:

   ```bash
   # Native installation
   sudo rm /var/lib/clamav/*.cvd /var/lib/clamav/*.cld
   sudo freshclam

   # Flatpak: the database lives on the host (ClamAV is not bundled);
   # use the same host commands above, then run an update from ClamUI.
   ```

---

## Getting Help

If you can't resolve your issue:

1. **Check existing issues**: [GitHub Issues](https://github.com/linx-systems/clamui/issues)
2. **Report a bug**: Create a new issue with:
    - ClamUI version
    - Operating system and version
    - Installation method (Flatpak, .deb, source)
    - Steps to reproduce
    - Error messages or logs
    - Debug logs: open **Preferences → Debug**, raise the **Log Level** if
      needed, then use **Export Logs** to save a ZIP (paths are redacted).
      Debug logs live in `~/.local/share/clamui/debug/`
      (`~/.var/app/io.github.linx_systems.ClamUI/data/clamui/debug/` in Flatpak).

3. **Community support**: Join discussions on the GitHub repository
