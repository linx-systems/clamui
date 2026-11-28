---
title: Installation
description: Install ClamUI, its native desktop runtime, and host ClamAV.
---

## Choose a package

| System | Recommended package |
| --- | --- |
| Most Linux desktops | [Flathub](#flathub) (`io.github.linx_systems.ClamUI`), x86_64 and aarch64 |
| Offline Flatpak install | GitHub v0.6.1 Flatpak bundle for the host architecture |
| Debian-family host | The matching v0.6.1 architecture-specific Debian application and helper pair |
| Fedora host | Flathub or AppImage, plus the matching signed v0.6.1 Fedora helper RPM for protected preferences |
| Portable x86_64 use | `ClamUI-0.6.1-x86_64.AppImage` |
| Snap users (preview) | Classic-confinement [snap](#snap-preview) built from `snap/snapcraft.yaml` |
| Rust/Tauri development | Rust, Bun, and a `master` [source checkout](#source) |

The current release is ClamUI v0.6.1, available from [GitHub Releases](https://github.com/linx-systems/clamui/releases/tag/v0.6.1); Flathub is updated separately and can briefly show an older version. Its native desktop build uses the system WebKitGTK 4.1 and GTK 3 runtime; its Flatpak configuration targets GNOME Platform 51. The Rust/Tauri application is not a Python/PyGObject runtime.

## Required host software

Every format uses **host** `clamscan` and `freshclam`; ClamUI does not bundle the ClamAV engine or its definitions. The scan daemon (`clamd` with `clamdscan`) is optional: it keeps the engine loaded so repeat scans start faster, and ClamUI uses it automatically when it is running.

### Debian or Ubuntu

```bash
sudo apt install clamav clamav-freshclam
sudo systemctl enable --now clamav-freshclam

# Optional daemon, once the definitions have finished downloading
sudo apt install clamav-daemon
sudo systemctl enable --now clamav-daemon
```

The `clamav-freshclam` service downloads the definitions in the background. While it runs, a manual `sudo freshclam` reports a locked log file; that is expected.

### Fedora

```bash
sudo dnf install clamav clamav-freshclam
sudo freshclam
sudo systemctl enable --now clamav-freshclam

# Optional daemon: Fedora ships its socket switched off
sudo dnf install clamd
sudo sed -i 's/^#LocalSocket /LocalSocket /' /etc/clamd.d/scan.conf
sudo systemctl enable --now clamd@scan
```

On Fedora Atomic desktops (Silverblue, Kinoite), use `rpm-ostree install` with the same package names and reboot.

### Arch Linux

```bash
sudo pacman -S clamav
sudo freshclam
sudo systemctl enable --now clamav-freshclam

# Optional daemon (included in the clamav package)
sudo systemctl enable --now clamav-daemon
```

### openSUSE Tumbleweed or Leap

```bash
sudo zypper install clamav
sudo freshclam
sudo systemctl enable --now freshclam.timer

# Optional daemon (included in the clamav package)
sudo systemctl enable --now clamd
```

You can also update definitions from ClamUI's **Database** view, and the **Components** view shows what was found. See [scan backends](/docs/reference/scan-backends/) for daemon details.

## Flathub

Flathub is the recommended install for most desktops. It ships the current release for x86_64 and aarch64, and your software center or `flatpak update` keeps it current:

```bash
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub io.github.linx_systems.ClamUI
flatpak run io.github.linx_systems.ClamUI
```

The Flatpak calls host ClamAV through `flatpak-spawn --host`; the sandboxed UI does not replace the host engine. Its ClamUI data is under `~/.var/app/io.github.linx_systems.ClamUI/`.

## Flatpak bundle

For an offline install, download the v0.6.1 GitHub Flatpak bundle for your architecture, `clamui-x86_64.flatpak` or `clamui-aarch64.flatpak`, and check it against the release's `SHA256SUMS`. A bundle does not update on its own.

```bash
flatpak install --user ./clamui-x86_64.flatpak
flatpak run io.github.linx_systems.ClamUI
```

For local Flatpak development, see [Flatpak builds and Flathub releases](/docs/contributing/development/#flatpak-builds-and-flathub-releases).

For a directory outside the granted filesystem, grant only that directory:

```bash
flatpak override --user --filesystem=/path/to/directory io.github.linx_systems.ClamUI
```
Database, Scanner, and On-Access preferences target host ClamAV configuration, not sandbox copies. They require the trusted host helper and its polkit policy. On native systems, a trusted canonical helper remains ready if automatic installation is unsupported or its installed-package metadata cannot be inspected; this does not accept a successfully reported version or architecture mismatch. Flatpak continues to check host packages. On supported Debian-family and Fedora hosts, native packages, AppImages, source builds, and Flatpak may offer **Install Helper** when that helper is missing. This local diagnosis does not download release metadata, and nothing is downloaded or installed until you click the offer.

After you click, automatic installation can complete only when the official matching published package is available. Before requesting graphical administrator authorization through Polkit, ClamUI verifies its signature, identity, version, size, digest, and compatible architecture; a missing or invalid asset fails safely before authorization. On Debian, a signed same-version architecture-independent helper remains an accepted legacy fallback only when no exact-architecture helper exists. The UI never runs as root or collects an administrator password.

If authorization is cancelled or installation fails, the settings draft remains available and you can retry or use the manual repair guidance. After installation succeeds, leave the section again or click **Save** in the Preferences header to retry; ClamUI does not automatically apply the protected changes on its own.

## Debian packages

Download and [verify](/docs/contributing/signing/#debian-packages) the pair for the same Debian architecture. The asset patterns are `clamui_0.6.1_<debarch>.deb` and `clamui-privileged-helper_0.6.1_<debarch>.deb`; the application package provides `/usr/bin/clamui` and `/usr/bin/clamui-scheduled-scan`, while the companion package provides `/usr/bin/clamui-apply-preferences` and its polkit policy.

```bash
DEB_ARCH="$(dpkg --print-architecture)"
sudo apt install "./clamui_0.6.1_${DEB_ARCH}.deb" \
  "./clamui-privileged-helper_0.6.1_${DEB_ARCH}.deb"
```

Do not mix upstream release versions or substitute a foreign-architecture package. Installed Debian metadata accepts a conventional numeric-leading Debian revision after the exact application upstream version, such as `0.6.1-1`; other version or architecture mismatches need repair. The canonical helper keeps the protected-host protocol and data rules intact.

## Fedora helper RPM

The v0.6.1 helper-only RPM asset names are `clamui-privileged-helper-0.6.1-1.x86_64.rpm` and `clamui-privileged-helper-0.6.1-1.aarch64.rpm`, each with a matching `.rpm.asc`. It contains `/usr/bin/clamui-apply-preferences` and its polkit policy, not the ClamUI GUI or ClamAV engine. Verify the RPM and detached signature first with the [package-signing guide](/docs/contributing/signing/#fedora-rpm-packages).

On Fedora Workstation or Server, the explicit native or Flatpak-host offer uses DNF only after you accept its notice that the pinned ClamUI public key will become persistent system RPM-key trust. On [Fedora Atomic desktops](https://docs.fedoraproject.org/en-US/atomic-desktops/getting-started/) (such as Silverblue or Kinoite), it uses [`rpm-ostree install -y --apply-live ./clamui-privileged-helper-0.6.1-1.<ARCH>.rpm`](https://coreos.github.io/rpm-ostree/administrator-handbook/) only for an absent helper and no unrelated pending deployment. After a successful live install, it runs the bounded `systemctl try-restart polkit.service` refresh and verifies the ClamUI polkit action is available; it never imports a host RPM key or reboots automatically. An existing, outdated, corrupt, or unavailable live Atomic helper needs the verified manual layering-and-reboot repair in [troubleshooting](/docs/troubleshooting/#privileged-helper-is-not-trusted).

A native Tauri build needs WebKitGTK 4.1 and GTK 3. Build release artifacts on the Ubuntu 22.04-compatible baseline used by CI to preserve the glibc floor; a successful build on a newer host is not evidence of old-distribution compatibility.

## AppImage

Download `ClamUI-0.6.1-x86_64.AppImage` from [GitHub Releases](https://github.com/linx-systems/clamui/releases), verify it, make it executable, then run it:

```bash
chmod +x ClamUI-0.6.1-x86_64.AppImage
./ClamUI-0.6.1-x86_64.AppImage
```

The AppImage packages ClamUI but still uses host ClamAV. Its matching `.zsync` metadata is `ClamUI-0.6.1-x86_64.AppImage.zsync`.

## Snap (preview)

ClamUI is not yet published in the Snap Store. The `snap/snapcraft.yaml` recipe builds a classic-confinement snap for amd64 and arm64; CI uploads it as the `snap-<arch>` workflow artifact. Classic confinement is required because ClamUI runs the host `clamscan`, `clamdscan` and `freshclam`, edits the host ClamAV configuration through pkexec, and manages user systemd timers. The snap bundles its own GTK 3 and WebKitGTK 4.1 runtime but never ClamAV.

```bash
sudo apt install clamav clamav-freshclam
sudo snap install --dangerous --classic ./clamui_0.6.1_amd64.snap
```

Protected ClamAV preferences need the host helper. On Debian-family hosts, install the matching `clamui-privileged-helper_0.6.1_<debarch>.deb` from the [Debian packages](#debian-packages) section; ClamUI checks that package version. On other hosts, `sudo clamui install-privileged-helper` installs it from the snap.

Scheduled scans started from the snap call `/snap/bin/clamui.scheduled-scan`, which stays valid across snap refreshes. Parallel snap instances such as `clamui_beta` are not supported. To build the snap yourself, run `snapcraft pack` from the repository root.

## Source

Follow the [development prerequisites](/docs/contributing/development/#prerequisites), then clone `master` and run the desktop application from the repository root:

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
( cd desktop && bun install --frozen-lockfile )
bun run --cwd desktop tauri dev
```

The headless CLI does not initialize the desktop runtime:

```bash
cargo run -p clamui-core --bin clamui-cli -- help
```

Source builds are distinct from signed release artifacts. On a **mutable native host**, build the headless core binaries from the repository root and use the supported manual fallback:

```bash
cargo build --locked -p clamui-core --bins
sudo ./target/debug/clamui-cli install-privileged-helper
```

Do not use that source installer to modify an immutable Fedora Atomic deployment; use the verified RPM layering path in [troubleshooting](/docs/troubleshooting/#privileged-helper-is-not-trusted).

See [development](/docs/contributing/development/) for package builds and [Flatpak builds and Flathub releases](/docs/contributing/development/#flatpak-builds-and-flathub-releases) for local Flatpak development.

## File-manager and tray integration

ClamUI can install file-manager actions for Nautilus, Dolphin, and Nemo. In Flatpak, use **Preferences → Behavior → Configure Integration**. The system tray is optional and requires a StatusNotifierItem watcher; GNOME needs [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/). See [tray use](/docs/guides/tray/) and [troubleshooting](/docs/troubleshooting/).

## Verify downloads

Verify published release packages before installation. See [package signing](/docs/contributing/signing/) for Debian, Fedora RPM, and AppImage instructions.