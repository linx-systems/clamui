---
title: Installation
description: Install ClamUI, its native desktop runtime, and host ClamAV.
---

## Choose a package

| System | Recommended package |
| --- | --- |
| Most Linux desktops | GitHub v0.5.1 Flatpak bundle for the host architecture |
| Debian-family host | The matching v0.5.1 architecture-specific Debian application and helper pair |
| Fedora host | GitHub Flatpak bundle or AppImage, plus the matching signed v0.5.1 Fedora helper RPM for protected preferences |
| Portable x86_64 use | `ClamUI-0.5.1-x86_64.AppImage` |
| Rust/Tauri development | Rust, Bun, and a `master` [source checkout](#source) |

ClamUI v0.5.1 is a patch release. Its native desktop build uses the system WebKitGTK 4.1 and GTK 3 runtime; its Flatpak configuration targets GNOME Platform 51. The Rust/Tauri application is not a Python/PyGObject runtime. The separate Flathub store remains on the historical Python 0.4.1 release until a later submission and rollout.

## Required host software

Every format uses **host** `clamscan` and `freshclam`; ClamUI does not bundle the ClamAV engine or its definitions. Daemon scanning also needs host `clamd` and `clamdscan`.

```bash
# Debian or Ubuntu
sudo apt install clamav clamav-freshclam

# Fedora
sudo dnf install clamav clamav-freshclam

# Arch Linux
sudo pacman -S clamav
```

Update definitions before the first scan:

```bash
sudo freshclam
```

You can also update them from ClamUI's **Database** view. See [scan backends](/docs/reference/scan-backends/) for daemon setup.

## Flatpak

After the v0.5.1 GitHub Flatpak bundles are attached, choose `clamui-x86_64.flatpak` or `clamui-aarch64.flatpak` for your architecture:

```bash
flatpak install --user ./clamui-x86_64.flatpak
flatpak run io.github.linx_systems.ClamUI
```

The v0.5.1 GitHub bundle calls host ClamAV through `flatpak-spawn --host`; the sandboxed UI does not replace the host engine. Its ClamUI data is under `~/.var/app/io.github.linx_systems.ClamUI/`. The Flathub command below remains valid for its published Python 0.4.1 package, not for Rust/Tauri v0.5.1:

```bash
flatpak install flathub io.github.linx_systems.ClamUI
flatpak run io.github.linx_systems.ClamUI
```

For local Flatpak development, see [Flatpak builds and Flathub releases](/docs/contributing/development/#flatpak-builds-and-flathub-releases).

For a directory outside the granted filesystem, grant only that directory:

```bash
flatpak override --user --filesystem=/path/to/directory io.github.linx_systems.ClamUI
```
Database, Scanner, and On-Access preferences target host ClamAV configuration, not sandbox copies. They require the trusted host helper and its polkit policy. On supported Debian-family and Fedora hosts, native packages, AppImages, source builds, and Flatpak may offer **Install Helper** when that helper is missing. This local diagnosis does not download release metadata, and nothing is downloaded or installed until you click the offer.

After you click, automatic installation can complete only when the official matching published package is available. Before requesting graphical administrator authorization through Polkit, ClamUI verifies its signature, identity, version, size, digest, and compatible architecture; a missing or invalid asset fails safely before authorization. On Debian, a signed same-version architecture-independent helper remains an accepted legacy fallback only when no exact-architecture helper exists. The UI never runs as root or collects an administrator password.

If authorization is cancelled or installation fails, the settings draft remains available and you can retry or use the manual repair guidance. After installation succeeds, explicitly choose **Save & Apply** again; ClamUI does not automatically apply the protected changes.

## Debian packages

After the v0.5.1 GitHub application and privileged-helper packages are attached, download and [verify](/docs/contributing/signing/#debian-packages) the pair for the same Debian architecture. The asset patterns are `clamui_0.5.1_<debarch>.deb` and `clamui-privileged-helper_0.5.1_<debarch>.deb`; the application package provides `/usr/bin/clamui` and `/usr/bin/clamui-scheduled-scan`, while the companion package provides `/usr/bin/clamui-apply-preferences` and its polkit policy.

```bash
DEB_ARCH="$(dpkg --print-architecture)"
sudo apt install "./clamui_0.5.1_${DEB_ARCH}.deb" \
  "./clamui-privileged-helper_0.5.1_${DEB_ARCH}.deb"
```

Do not mix release versions or substitute a foreign-architecture package. The canonical helper keeps the protected-host protocol and data rules intact.

## Fedora helper RPM

The v0.5.1 helper-only RPM asset names are `clamui-privileged-helper-0.5.1-1.x86_64.rpm` and `clamui-privileged-helper-0.5.1-1.aarch64.rpm`, each with a matching `.rpm.asc`. After the matching asset is attached, it contains `/usr/bin/clamui-apply-preferences` and its polkit policy, not the ClamUI GUI or ClamAV engine. Verify the RPM and detached signature first with the [package-signing guide](/docs/contributing/signing/#fedora-rpm-packages).

On Fedora Workstation or Server, the explicit native or Flatpak-host offer uses DNF only after you accept its notice that the pinned ClamUI public key will become persistent system RPM-key trust. On [Fedora Atomic desktops](https://docs.fedoraproject.org/en-US/atomic-desktops/getting-started/) (such as Silverblue or Kinoite), it uses [`rpm-ostree install -y --apply-live ./clamui-privileged-helper-0.5.1-1.<ARCH>.rpm`](https://coreos.github.io/rpm-ostree/administrator-handbook/) only for an absent helper and no unrelated pending deployment. After a successful live install, it runs the bounded `systemctl try-restart polkit.service` refresh and verifies the ClamUI polkit action is available; it never imports a host RPM key or reboots automatically. An existing, outdated, corrupt, or unavailable live Atomic helper needs the verified manual layering-and-reboot repair in [troubleshooting](/docs/troubleshooting/#privileged-helper-is-not-trusted).

A native Tauri build needs WebKitGTK 4.1 and GTK 3. Build release artifacts on the Ubuntu 22.04-compatible baseline used by CI to preserve the glibc floor; a successful build on a newer host is not evidence of old-distribution compatibility.

## AppImage

After `ClamUI-0.5.1-x86_64.AppImage` is attached to [GitHub Releases](https://github.com/linx-systems/clamui/releases), verify it, make it executable, then run it:

```bash
chmod +x ClamUI-0.5.1-x86_64.AppImage
./ClamUI-0.5.1-x86_64.AppImage
```

The AppImage packages ClamUI but still uses host ClamAV. Its matching `.zsync` metadata is `ClamUI-0.5.1-x86_64.AppImage.zsync`.

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