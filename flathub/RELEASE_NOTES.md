# ClamUI v0.6.1 AppStream release description

```xml
<description>
  <p>ClamUI 0.6.1 fixes a blank window in the Flatpak and improves the security audit.</p>
  <ul>
    <li>Fix a blank window by using shared-memory WebKitGTK rendering instead of disabling the DMA-BUF renderer.</li>
    <li>Check OpenSnitch separately and let security audit warnings be acknowledged.</li>
    <li>Show startup errors in the window and log where a blank start got stuck.</li>
    <li>New dashboard layout, automatic preference saving, and fixes for daemon scans of FUSE mounts.</li>
  </ul>
</description>
```

This description is prepared for Flathub submission; it does not state that the store has published v0.6.1. The Flatpak uses host ClamAV and targets GNOME Platform 51. Protected host settings require a trusted protocol-v4 helper and graphical Polkit authorization.
