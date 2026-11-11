# ClamUI v0.6.0 AppStream release description

```xml
<description>
  <p>ClamUI 0.6.0 adds Vietnamese and improves scan reliability and responsiveness.</p>
  <ul>
    <li>Load history and quarantine more efficiently, and reduce scan progress overhead.</li>
    <li>Preserve complete findings and counts for large scans and handle long daemon scan paths.</li>
    <li>Improve trusted helper and host virus database detection and Flatpak Wayland startup.</li>
    <li>Reject VirusTotal uploads if the original pathname is substituted after lookup.</li>
  </ul>
</description>
```

This description is prepared for Flathub submission; it does not state that the store has published v0.6.0. The Flatpak uses host ClamAV and targets GNOME Platform 51. Protected host settings require a trusted protocol-v4 helper and graphical Polkit authorization.
