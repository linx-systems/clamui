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

The Flatpak recipes use the GNOME Platform/SDK 51 and build for the host's native Flatpak architecture (`x86_64` or `aarch64`). Add Flathub and install the SDK plus the extensions into the explicit user installation before a local build:

```bash
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user --arch="$(flatpak --default-arch)" flathub \
  org.gnome.Sdk//51 \
  org.freedesktop.Sdk.Extension.node24//26.08 \
  org.freedesktop.Sdk.Extension.rust-stable//26.08
```

The Rust/Tauri tree is currently development source on `migration/rust-tauri`, not the released stable application: public `master` and `v0.4.1` still contain the Python release. Clone the development branch explicitly:

```bash
git clone --branch migration/rust-tauri --single-branch https://github.com/linx-systems/clamui.git
cd clamui
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

`install-privileged-helper` is the manual native/source-host path. Its real installation requires root and stages the co-bundled compiled helper with its canonical polkit policy; retain it for unavailable or unpublished development releases on **mutable** hosts. On supported Debian-family and Fedora hosts, a missing helper in native packages, AppImages, source builds, or Flatpak may show explicit in-app setup from the local capability check. Automatic setup can complete only with an exact matching signed published package; before graphical Polkit authorization, it validates that package's signature, identity, version, size, digest, and compatible architecture, otherwise failing safely without authorization. Debian alone can use its signed same-version architecture-independent fallback. Fedora Atomic contributors must use verified RPM layering and reboot for manual repair, never this source installer against immutable `/usr`. The Flatpak rejects this host command, so do not use `sudo flatpak`.

For source-host development, build only the headless binaries, then use the non-privileged staging mode in a directory you own:

```bash
cargo build --locked -p clamui-core --bins
stage_dir="$(mktemp -d)"
./target/debug/clamui-cli install-privileged-helper --prefix "$stage_dir"
```

On a mutable native host, the actual installation is a separate, privileged action; do not run Cargo as root:

```bash
sudo ./target/debug/clamui-cli install-privileged-helper
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

Protected configuration changes use the authenticated protocol-v4 helper at `/usr/bin/clamui-apply-preferences` and the `io.github.linx_systems.ClamUI.policy` polkit policy. Preserve its allowlists, `PKEXEC_UID` validation, exit codes, and compatibility with an already-installed helper. The helper is native Rust, not a Python wrapper. A Flatpak has no direct host-file access; its explicit missing-helper offer uses a verified published package and graphical Polkit authorization where supported: the Debian-family transaction or the Fedora DNF/Atomic transaction described in [installation](/docs/installation/#fedora-helper-rpm). Unavailable trust or authorization must fail without changes.

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

Recorded migration evidence includes Rust workspace tests and strict Clippy, real Tauri/AppImage/Flatpak EICAR scans through the host bridge, prior XDG JSON/SQLite/keyring compatibility, and desktop copy/ZIP-export coverage. It is not a zero-regression guarantee and does not claim exercised protected host writes, VirusTotal uploads, physical-device hardware, Wayland, or an aarch64 build of the current migration revision.

## Packaging boundaries

ClamUI preserves Debian, Flatpak, and x86_64 AppImage distribution formats. The Rust/Tauri packaging sources on the development branch live in [`debian/`](https://github.com/linx-systems/clamui/tree/migration/rust-tauri/debian), [`flathub/`](https://github.com/linx-systems/clamui/tree/migration/rust-tauri/flathub), and [`appimage/`](https://github.com/linx-systems/clamui/tree/migration/rust-tauri/appimage). Use their checked-in manifests and scripts rather than recreating package logic locally. An unpublished local checkout may additionally contain `rpm/` helper work; it is not part of the pushed `migration/rust-tauri` branch.

A Debian release is a version- and architecture-matched application/helper pair. Flatpak declares GNOME 51 and dependencies for `x86_64` and `aarch64`, but a local build validates only its native architecture. AppImage remains x86_64. Every format retains the host ClamAV boundary.

Build with the maintained native packaging entry points present on the development branch:

```bash
./debian/build-deb.sh
# Package the three binaries built on the Ubuntu 22.04-compatible baseline.
CLAMUI_ARTIFACT_DIR=/absolute/path/to/ubuntu22/target/release ./debian/build-deb.sh dist
UPDATE_INFORMATION='gh-releases-zsync|linx-systems|clamui|latest|ClamUI-*-x86_64.AppImage.zsync' ./appimage/build-appimage.sh
```

### Unpublished local RPM helper work

Only a checkout that already contains the unpublished `rpm/` directory can run these helper-only commands:

```bash
./rpm/build-privileged-helper-rpm.sh dist
CLAMUI_ARTIFACT_DIR=/absolute/path/to/ubuntu22/target/release CLAMUI_RPM_ARCH=x86_64 ./rpm/build-privileged-helper-rpm.sh dist
```

The scripts can produce local `x86_64` or `aarch64` helper artifacts when built for the matching target; they contain the Rust helper and canonical policy, not the GUI or ClamAV. A local RPM is unsigned and is not an eligible installer asset. Only a matching signed RPM published with its detached signature can be used by the in-app Fedora installer; an older package does not prove compatibility with this development source. The RPM builder requires Cargo, `readelf` from `binutils`, and the `rpm`/`rpmbuild` package tools; a local source compilation also needs the usual Rust C toolchain, `pkg-config`, and GLib development files. It builds only the helper, so it needs neither Python nor the Bun/Tauri GUI toolchain. `CLAMUI_ARTIFACT_DIR`, `CARGO_TARGET_DIR`, and `CARGO_BUILD_TARGET` select a prebuilt or nondefault Cargo artifact; `CLAMUI_RPM_ARCH` asserts `x86_64` or `aarch64` against the helper ELF. The RPM automation may be configured for additional architectures, but configuration or an unpublished local artifact is not release verification.

`debian/build-deb.sh` is the authoritative Debian entry point: it produces the application/helper pair and stages the policy and scheduled-scan payload. `CLAMUI_ARTIFACT_DIR` must contain executable `clamui`, `clamui-scheduled-scan`, and `clamui-apply-preferences` binaries from the baseline build. The AppImage build produces `ClamUI-<VERSION>-x86_64.AppImage` and its `.zsync` metadata.

## Flatpak builds and Flathub releases

### Local Flatpak checkout build

`flathub/io.github.linx_systems.ClamUI.local.yml` is a developer checkout recipe. It uses `type: dir`, includes the working tree, and is not an immutable release manifest. Use a fresh directory under the checkout so the build target, Builder state, and exported repository are owned by you and on the same filesystem. This command neither installs nor replaces an existing Flatpak, and it does not delete an existing build directory:

```bash
mkdir -p target
flatpak_workdir="$(mktemp -d "$PWD/target/flatpak.XXXXXX")"
flatpak-builder --user --arch="$(flatpak --default-arch)" \
  --state-dir="$flatpak_workdir/state" \
  --repo="$flatpak_workdir/repo" \
  "$flatpak_workdir/build" \
  flathub/io.github.linx_systems.ClamUI.local.yml
```

The checked-in `flathub/io.github.linx_systems.ClamUI.yml` currently has the same checkout-source form. It is useful for local development, but neither checkout YAML is the immutable manifest required for an official release.

### Immutable Flatpak release packaging

An official Rust Flatpak submission requires exactly three checked-in packaging inputs: a canonical YAML whose application source is a concrete public Git URL and full commit pin, `flathub/cargo-sources.json`, and `flathub/bun-sources.json`. The two source manifests must be generated from the settled `Cargo.lock` and the paired `desktop/bun.lock`/`desktop/yarn.lock`; do not hand-edit their checksums or retain legacy Python source JSON as a Rust packaging input.

The product lockfile remains `desktop/bun.lock`. Before generation, intentionally export its paired Yarn lockfile after settling frontend dependencies:

```bash
( cd desktop && bun install --frozen-lockfile --yarn )
```

Run the generator from a clean checkout whose intended source commit is already public and whose lockfiles match that commit. It requires `flatpak-cargo-generator.py` plus `flatpak-node-generator` (the node generator requires Python 3.11+):

```bash
release_commit="$(git rev-parse HEAD)"
scripts/generate-flatpak-sources.sh \
  --release-url https://github.com/linx-systems/clamui.git \
  --release-commit "$release_commit" \
  --release-output flathub/io.github.linx_systems.ClamUI.release.yml
```

This rewrites both checked-in source JSON files and writes the Git-pinned release manifest explicitly. Review all three files together: the generated manifest replaces the complete checkout `dir` source block, including its exclusions, with the URL and exact commit while retaining the other source entries and JSON includes. This produces release packaging input; it does not publish an application release or claim that the Rust/Tauri migration is on Flathub.

Build that generated manifest locally only in a fresh directory below the checkout, so Builder state, the build directory, and exported repository stay on the same filesystem and are owned by you:

```bash
mkdir -p target
flatpak_release_dir="$(mktemp -d "$PWD/target/flatpak-release.XXXXXX")"
flatpak-builder --user --arch="$(flatpak --default-arch)" \
  --state-dir="$flatpak_release_dir/state" \
  --repo="$flatpak_release_dir/repo" \
  "$flatpak_release_dir/build" \
  flathub/io.github.linx_systems.ClamUI.release.yml
```

This local build neither installs nor replaces an existing Flatpak, and it proves only the host architecture. Before any release, independently complete the offline build and metadata/package validation for both `x86_64` and `aarch64`, then complete the Flathub/release publication process. Automatic privileged-helper setup remains separately gated on matching signed published helper packages for the release and architecture (including Fedora RPM and `.rpm.asc` assets); neither those assets nor a public Rust/Tauri Flathub migration are claimed here. The Flatpak workflow triggers on `master` pushes, pull requests targeting `master`, `v*` tags, manual dispatch, or a workflow call; pushing `migration/rust-tauri` alone does not trigger it.

Before publishing, inspect package payloads for the right architecture, native command names, helper/policy paths, and absence of a Python application runtime. Build compatibility still requires proof from the baseline environment and target package/OS; do not infer it from this development guide.

## Write documentation

The Starlight source is `website/src/content/docs/docs/`. Reuse the existing focused pages, use root-relative `/docs/.../` links, and keep the existing sidebar structure unless navigation truly changes. Root `README.md` and `CONTRIBUTING.md` are short discovery pointers; `CHANGELOG.md` and `RELEASE_NOTES.md` remain canonical release sources rendered by MDX imports.

Website commands:

```bash
( cd website && bun install --frozen-lockfile )
bun run --cwd website check
bun run --cwd website build
```

Do not edit generated `website/public/` or `website/dist/`. Keep the active `de`, `en`, `es`, `fr`, `hu`, `it`, `nb`, `pt_BR`, and `zh_CN` gettext catalogs in `po/` and listed in `po/LINGUAS`; Rust build tooling and packaging export each catalog for the core and UI. Localized historical scan-summary recognition is embedded build data, not an archived catalog source, and catalog extraction, loading, and packaging have no Python runtime dependency. See [translation](/docs/contributing/translating/) for the catalog workflow.

## Update the application icon

`icons/io.github.linx_systems.ClamUI.svg` is the source icon; `icons/io.github.linx_systems.ClamUI.png` is its checked-in 128×128 rendering. When the SVG changes, regenerate and commit both files once. Builds install the committed PNG and never convert it at runtime.