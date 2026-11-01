# ClamUI v0.5.0 AppStream release description

```xml
<description>
  <p>Rust/Tauri desktop migration, refined scan workflows, and safer recovery guidance for protected host settings.</p>
  <ul>
    <li>Desktop &amp; workflows: reworked the application around a Rust core and Tauri/WebKitGTK desktop while preserving ClamUI's public application ID, CLI, and existing XDG JSON/SQLite user data. The compact interface keeps profiles, scan details, history, quarantine, exports, and tray workflows available.</li>
    <li>Scanning &amp; results: improved detection and progress updates, and fixed daemon scans of filenames containing carriage returns or newlines while retaining exclusions, original paths, progress, and partial results.</li>
    <li>Network &amp; audit: the Network view shows a snapshot of current TCP/UDP listeners and connections with filtering, copying, and permission-aware process attribution; it is not traffic capture. The advisory firewall audit remains read-only and does not change firewall rules.</li>
    <li>Settings recovery: Save &amp; Apply retains the attempted proposals and reports durable outcomes. For failed or unconfirmed protected changes, See Configuration shows the exact attempted native ClamAV configuration and full target paths for inspection and separate copying; inspect files before manual replacement because some writes may already have occurred.</li>
    <li>Localization &amp; compatibility: the refreshed desktop is available in nine active locales, with translation and compatibility fixes across scanning, profiles, history, quarantine, focus, and CLI workflows.</li>
  </ul>
  <p>ClamUI uses host-installed ClamAV tools: clamscan and freshclam are required, and clamd with clamdscan is required for the daemon backend. The Flatpak desktop runtime does not bundle the ClamAV engine or database. For protected host settings, use the matching trusted native helper with graphical Polkit authorization; on supported hosts, install only a verified matching signed helper package, then explicitly retry Save &amp; Apply. Do not bypass helper trust checks.</p>
</description>
```