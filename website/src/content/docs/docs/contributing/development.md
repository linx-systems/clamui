---
title: Development and packaging
description: Set up the Rust core, Tauri desktop, packages, tests, and docs site.
---

## Prerequisites

ClamUI has a headless Rust core (`crates/clamui-core`) and a Tauri 2 desktop (`desktop/src-tauri`) with a React/TypeScript frontend (`desktop/`). The desktop needs the Linux WebKitGTK **4.1** API and GTK 3 development libraries. Python is not an application build or runtime dependency.

### Debian or Ubuntu

```bash
sudo apt update
sudo apt install build-essential pkg-config libssl-dev libgtk-3-dev \
  libwebkit2gtk-4.1-dev librsvg2-dev libxdo-dev curl wget file \
  flatpak-builder
```

Install current stable Rust with `rustup` and Bun using your distribution package manager or their official installers. Confirm the tools before continuing:

```bash
rustc --version
cargo --version
bun --version
```

Flatpak builds use the GNOME Platform/SDK 51. Before a local Flatpak build, install the SDK extensions declared by the manifest:

```bash
flatpak install flathub org.gnome.Sdk//51 \
  org.freedesktop.Sdk.Extension.node24//26.08 \
  org.freedesktop.Sdk.Extension.rust-stable//26.08
```

Native release artifacts must be built on the Ubuntu 22.04-compatible baseline used by CI to retain the intended glibc floor. A local build on a newer distribution does **not** establish that the artifact supports Ubuntu 22.04 or another older host.

## Work on the app

From the repository root, install the locked frontend dependencies and start Tauri:

```bash
( cd desktop && bun install --frozen-lockfile )
bun run --cwd desktop tauri dev
```

Use the Tauri command for desktop development; do not substitute direct `cargo run`. Tauri development uses its configured `build.devUrl`, while the native custom-protocol production binary embeds `frontendDist`.

The GUI runs through Tauri/WebKitGTK. For the headless core CLI, use the native binary directly; this route must not initialize a WebKit window:

```bash
cargo run -p clamui-core --bin clamui-cli -- help
cargo run -p clamui-core --bin clamui-cli -- scan --help
cargo run -p clamui-core --bin clamui-scheduled-scan -- --dry-run
```

The `clamui` command preserves seven subcommands: `scan`, `quarantine`, `profile`, `status`, `history`, `help`, and `install-privileged-helper`. Keep their flags, JSON/text output, standard streams, and exit semantics compatible. `clamui-scheduled-scan` remains a separate executable.

The CLI accepts conventional bundled scan flags and compatible attached `history` arguments. Use `--` before a target whose name looks like an option, for example `clamui scan -- --virustotal`; this keeps it a scan target rather than treating it as a flag.

The installed command surface is:

```bash
clamui scan /path/to/target
clamui quarantine list --json
clamui profile list --json
clamui status --json
clamui history --limit 20 --json
clamui help scan
sudo clamui install-privileged-helper
clamui-scheduled-scan --dry-run
```

`install-privileged-helper` is for a native host only. Its real installation requires root and stages the co-bundled compiled helper with its canonical polkit policy. The Flatpak rejects this host command: use the matching published host helper package and its separate in-app signed installer instead. Contributors can use the hidden advanced staging mode without elevation in an owned temporary directory:

```bash
stage_dir="$(mktemp -d)"
clamui install-privileged-helper --prefix "$stage_dir"
```

### Debugging

Use structured Rust logging while starting the desktop:

```bash
RUST_LOG=clamui=debug bun run --cwd desktop tauri dev
```

Use the Tauri/WebKit developer tools for frontend state and the terminal for Rust/core diagnostics. Never replace native IPC with a browser filesystem, shell, or process permission. The only frontend request boundary is Tauri's allowlisted `request` command and `clamui-event` event stream.

### Data compatibility

Work against the existing XDG layouts, never ad-hoc project-local data:

```text
$XDG_CONFIG_HOME/clamui/settings.json
$XDG_CONFIG_HOME/clamui/profiles.json
$XDG_DATA_HOME/clamui/logs/
$XDG_DATA_HOME/clamui/quarantine.db
$XDG_DATA_HOME/clamui/quarantine/
$XDG_DATA_HOME/clamui/debug/
```

The Flatpak equivalents live beneath `~/.var/app/io.github.linx_systems.ClamUI/`. Preserve atomic settings writes, unknown settings keys, existing JSON/SQLite schemas, privacy migrations, restrictive file modes, and profile/import compatibility. The core must remain GTK-widget and Tauri independent so these behaviors also work through the CLI.

### Host and privilege boundaries

ClamUI uses host `clamscan` and `freshclam`; daemon mode also uses host `clamd` and `clamdscan`. Under Flatpak, calls cross the explicit `flatpak-spawn --host` boundary. Do not bundle or emulate ClamAV.

Protected configuration changes use the authenticated protocol-v4 helper at `/usr/bin/clamui-apply-preferences` and the `io.github.linx_systems.ClamUI.policy` polkit policy. Preserve its allowlists, `PKEXEC_UID` validation, exit codes, and compatibility with an already-installed helper. The helper is native Rust, not a Python wrapper. A Flatpak cannot install host files; unavailable trust or authorization must fail without changes.

## Test before a pull request

Run the applicable checks from the repository root:

```bash
bun run --cwd desktop check
bun run --cwd desktop build
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Exercise the real CLI and persisted compatibility fixtures in addition to unit tests. Test clean, EICAR, cancellation, scheduling dry-run, privileged-helper rejection, and compatible CLI output. For desktop work, manually verify Tauri startup, navigation, events, native dialogs, tray behavior, and file-argument forwarding.

The current migration proof exercised 122 Rust workspace tests and strict Clippy, actual Tauri, AppImage, and Flatpak EICAR scans through the host bridge, prior XDG JSON/SQLite/keyring compatibility, and the desktop's 1.114 MB copy and 18.55 MB ZIP-export paths. It is not a zero-regression guarantee and does not claim exercised protected host writes, VirusTotal uploads, physical-device hardware, Wayland, or aarch64 CI.

## Packaging boundaries

ClamUI preserves Debian, Flatpak, and x86_64 AppImage distribution formats. Packaging sources live in [`debian/`](https://github.com/linx-systems/clamui/tree/master/debian), [`flathub/`](https://github.com/linx-systems/clamui/tree/master/flathub), and [`appimage/`](https://github.com/linx-systems/clamui/tree/master/appimage). Use their checked-in manifests and scripts rather than recreating package logic locally.

A Debian release is a version- and architecture-matched pair: the application package and `clamui-privileged-helper` package. The pair ships native Rust binaries and the canonical polkit policy; it must not carry a Python app runtime. Flatpak targets GNOME 51 for x86_64 and aarch64. AppImage remains x86_64. Every format retains the host ClamAV boundary.

Build with the maintained packaging entry points:

```bash
./debian/build-deb.sh
# Package the three binaries built on the Ubuntu 22.04-compatible baseline.
CLAMUI_ARTIFACT_DIR=/absolute/path/to/ubuntu22/target/release ./debian/build-deb.sh dist
flatpak-builder --user --install --force-clean build-dir flathub/io.github.linx_systems.ClamUI.local.yml
UPDATE_INFORMATION='gh-releases-zsync|linx-systems|clamui|latest|ClamUI-*-x86_64.AppImage.zsync' ./appimage/build-appimage.sh
```

`debian/build-deb.sh` is the authoritative Debian entry point: it produces the application/helper pair and stages the policy and scheduled-scan payload. `CLAMUI_ARTIFACT_DIR` must contain executable `clamui`, `clamui-scheduled-scan`, and `clamui-apply-preferences` binaries from the baseline build. The AppImage build produces `ClamUI-<VERSION>-x86_64.AppImage` and its `.zsync` metadata. Flatpak production builds use the locked Cargo and Bun source manifests; the local manifest intentionally builds the checkout.

Before publishing, inspect package payloads for the right architecture, native command names, helper/policy paths, and absence of a Python application runtime. Build compatibility still requires proof from the baseline environment and target package/OS; do not infer it from this development guide.

## Write documentation

The Starlight source is `website/src/content/docs/docs/`. Reuse the existing focused pages, use root-relative `/docs/.../` links, and keep the existing sidebar structure unless navigation truly changes. Root `README.md` and `CONTRIBUTING.md` are short discovery pointers; `CHANGELOG.md` and `RELEASE_NOTES.md` remain canonical release sources rendered by MDX imports.

Website commands:

```bash
bun --cwd website install --frozen-lockfile
bun run --cwd website check
bun run --cwd website build
```

Do not edit generated `website/public/` or `website/dist/`. Keep the active `de`, `en`, `es`, `fr`, `hu`, `it`, `nb`, `pt_BR`, and `zh_CN` gettext catalogs in `po/` and listed in `po/LINGUAS`; Rust build tooling and packaging export each catalog for the core and UI. Localized historical scan-summary recognition is embedded build data, not an archived catalog source, and catalog extraction, loading, and packaging have no Python runtime dependency. See [translation](/docs/contributing/translating/) for the catalog workflow.

## Update the application icon

`icons/io.github.linx_systems.ClamUI.svg` is the source icon; `icons/io.github.linx_systems.ClamUI.png` is its checked-in 128×128 rendering. When the SVG changes, regenerate and commit both files once. Builds install the committed PNG and never convert it at runtime.