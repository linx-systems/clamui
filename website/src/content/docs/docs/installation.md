---
title: Installation
description: Install ClamUI, its native desktop runtime, and host ClamAV.
---

## Choose a package

| System | Recommended package |
| --- | --- |
| Most Linux desktops (published stable) | Flathub Flatpak (currently the Python 0.4.1 release) |
| Debian-family host with matching release assets | The matching architecture-specific Debian application and helper pair |
| Fedora host with matching helper release assets | Flathub Flatpak or AppImage, plus the signed Fedora helper RPM for protected preferences |
| Portable x86_64 use | AppImage |
| Rust/Tauri development | Rust, Bun, and a `migration/rust-tauri` [source checkout](#source) |

Flathub and the v0.4.1 release assets currently publish the Python application. The Rust core, Tauri desktop, and React frontend live on `migration/rust-tauri` as a development checkout, not a stable release. Its native desktop build uses the system WebKitGTK 4.1 and GTK 3 runtime; its local Flatpak configuration targets GNOME Platform 51. The Rust/Tauri checkout is not a Python/PyGObject application.

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

Install Flatpak through your distribution package manager first. On Debian or Ubuntu:

```bash
sudo apt install flatpak
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub io.github.linx_systems.ClamUI
flatpak run io.github.linx_systems.ClamUI
```

The command above remains the valid way to install the published Flathub package, which is currently the Python 0.4.1 release. It does **not** install the Rust/Tauri development checkout. The published Flatpak calls host ClamAV through `flatpak-spawn --host`; the sandboxed UI does not replace the host engine. Its ClamUI data is under `~/.var/app/io.github.linx_systems.ClamUI/`. For local Rust/Tauri Flatpak development, see [Flatpak builds and Flathub releases](/docs/contributing/development/#flatpak-builds-and-flathub-releases).

For a directory outside the granted filesystem, grant only that directory:

```bash
flatpak override --user --filesystem=/path/to/directory io.github.linx_systems.ClamUI
```
Database, Scanner, and On-Access preferences target host ClamAV configuration, not sandbox copies. They require the trusted host helper and its polkit policy. On supported Debian-family and Fedora hosts, native packages, AppImages, source builds, and Flatpak may offer **Install Helper** when that helper is missing. This local diagnosis does not download release metadata, and nothing is downloaded or installed until you click the offer.

After you click, automatic installation can complete only when the official matching published package is available. Before requesting graphical administrator authorization through Polkit, ClamUI verifies its signature, identity, version, size, digest, and compatible architecture; a missing or invalid asset fails safely before authorization. On Debian, a signed same-version architecture-independent helper remains an accepted legacy fallback only when no exact-architecture helper exists. The UI never runs as root or collects an administrator password.

If authorization is cancelled or installation fails, the settings draft remains available and you can retry or use the manual repair guidance. After installation succeeds, explicitly choose **Save & Apply** again; ClamUI does not automatically apply the protected changes.

## Debian packages

The published Python v0.4.1 release provides an architecture-independent application and privileged-helper pair. After downloading and [verifying](/docs/contributing/signing/#debian-packages) both files, install them together. The application package provides `/usr/bin/clamui` and `/usr/bin/clamui-scheduled-scan`; the companion package provides `/usr/bin/clamui-apply-preferences` and its polkit policy.

```bash
sudo apt install ./clamui_0.4.1_all.deb ./clamui-privileged-helper_0.4.1_all.deb
```

Future native Rust/Tauri releases require matching published application and helper assets for the **same version and architecture**; none are published yet. Do not mix release versions or substitute a foreign-architecture package. A signed, same-version architecture-independent helper is acceptable only when the release publishes it as the legacy fallback. The canonical helper keeps the protected-host protocol and data rules intact.

## Fedora helper RPM

When an official release publishes them, Fedora assets are `clamui-privileged-helper-<VERSION>-1.<x86_64|aarch64>.rpm` and the required matching `.rpm.asc`. This is a **helper-only** package: it contains `/usr/bin/clamui-apply-preferences` and its polkit policy, not the ClamUI GUI or ClamAV engine. Verify both files first with the [package-signing guide](/docs/contributing/signing/#fedora-rpm-packages); unpublished or unsigned build artifacts are not installer assets. A published Python 0.4.1 helper is not a matching helper for a Rust/Tauri development checkout.

On Fedora Workstation or Server, the explicit native or Flatpak-host offer uses DNF only after you accept its notice that the pinned ClamUI public key will become persistent system RPM-key trust. On [Fedora Atomic desktops](https://docs.fedoraproject.org/en-US/atomic-desktops/getting-started/) (such as Silverblue or Kinoite), it uses [`rpm-ostree install -y --apply-live ./clamui-privileged-helper-<VERSION>-1.<ARCH>.rpm`](https://coreos.github.io/rpm-ostree/administrator-handbook/) only for an absent helper and no unrelated pending deployment. After a successful live install, it runs the bounded `systemctl try-restart polkit.service` refresh and verifies the ClamUI polkit action is available; it never imports a host RPM key or reboots automatically. An existing, outdated, corrupt, or unavailable live Atomic helper needs the verified manual layering-and-reboot repair in [troubleshooting](/docs/troubleshooting/#privileged-helper-is-not-trusted).

A native Tauri build needs WebKitGTK 4.1 and GTK 3. Build release artifacts on the Ubuntu 22.04-compatible baseline used by CI to preserve the glibc floor; a successful build on a newer host is not evidence of old-distribution compatibility.

## AppImage

Download the published v0.4.1 x86_64 AppImage from [GitHub Releases](https://github.com/linx-systems/clamui/releases), make it executable, then run it:

```bash
chmod +x ClamUI-0.4.1-x86_64.AppImage
./ClamUI-0.4.1-x86_64.AppImage
```

The current v0.4.1 AppImage is a Python-release package; it does not install the Rust/Tauri development checkout. The AppImage packages ClamUI but still uses host ClamAV. A `.zsync` file may be available with a published release.

## Source

The Rust/Tauri source is a development checkout, not a published release. Follow the [development prerequisites](/docs/contributing/development/#prerequisites), then clone the public migration branch and run the desktop application from the repository root:

```bash
git clone --branch migration/rust-tauri --single-branch https://github.com/linx-systems/clamui.git
cd clamui
( cd desktop && bun install --frozen-lockfile )
bun run --cwd desktop tauri dev
```

The headless CLI does not initialize the desktop runtime:

```bash
cargo run -p clamui-core --bin clamui-cli -- help
```

An unavailable or unpublished development release has no matching signed published helper package. The in-app offer may still appear, but automatic installation cannot complete and fails safely before administrator authorization. On a **mutable native host**, build the headless core binaries from the repository root and use the supported manual fallback:

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