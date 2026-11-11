# ClamUI contributor guide

ClamUI is a Linux desktop frontend for **host-installed ClamAV**. The production application is Rust: a headless core, a Tauri 2 native runtime, and a React/TypeScript frontend. Preserve the public desktop, AppStream, and Flatpak ID `io.github.linx_systems.ClamUI`, persisted user data, and the `clamui` command family. Tauri's private bundle identifier is `io.github.linx-systems.ClamUI`; do not substitute it into public identity assets.

## Architecture and boundaries

| Area | Responsibility |
| --- | --- |
| `crates/clamui-core/` | Headless domain operations, XDG persistence, ClamAV host integration, scheduling, quarantine, i18n, and the privileged-helper protocol. It has no Tauri or widget dependency. |
| `desktop/src-tauri/` | Tauri commands, event bridge, native dialogs, single-instance handling, lifecycle, safe opening/export helpers, and the Rust SNI/DBusMenu tray. |
| `desktop/src/` | React pages, navigation, rendered translations, notifications, and the typed frontend API. |
| `data/` | Application identity, AppStream metadata, desktop integration, and icons. |
| `debian/`, `flathub/`, `appimage/` | Distribution-specific packaging; keep the same app identity and host-ClamAV boundary in every format. |
| `website/` | The published Astro/Starlight documentation site. |

The frontend has one request path to the native runtime; the runtime forwards only allowlisted operations to the core. Core events use `{ event, data }` on `clamui-event`. Do not add arbitrary frontend filesystem, shell, process, remote-navigation, or generic IPC access. Keep slow work off the UI thread and scope cancellation to its operation ID.

The Rust core and desktop are the only application implementation. Make behavior changes in their owned source boundaries and preserve the established core-to-runtime-to-frontend contract.

## Build and test entry points

Toolchain manifests are the source of truth. Typical local commands are:

```bash
cargo test --workspace --locked
cargo fmt --check --all
( cd desktop && bun install --frozen-lockfile )
bun run --cwd desktop check
bun run --cwd desktop build
cargo clippy --workspace --all-targets --locked -- -D warnings
bun run --cwd desktop tauri dev
cargo run -p clamui-core --bin clamui-cli -- help

```

`cargo clippy` compiles the production Tauri crate, whose `generate_context!` embeds `desktop/dist`; run the frozen frontend install and build first.

Rust core tests live under `crates/clamui-core/tests/` alongside module-local tests. Add focused consumer-visible, data-compatibility, or security invariants beside the owning module; avoid implementation-text or mock-only tests.

For gettext changes, validate extraction and catalogs with:

```bash
./scripts/update-pot.sh --check
./scripts/check-potfiles.sh
./scripts/check-translations.sh
```


The website is a separate Bun project:

```bash
cd website
bun install --frozen-lockfile
bun run check
bun run build
```

CI builds native artifacts on the Ubuntu 22.04-compatible baseline. A build on a newer host does not establish that compatibility.

## Coding-agent skills

Project-local coding-agent skills are optional development aids, not build or runtime dependencies. Their canonical imports are in `.agents/skills`; `.claude/skills` provides compatibility links. For installation details, see the published [Development guide](https://clamui.com/docs/contributing/development/).

Refresh only a deliberately selected upstream skill. `skills-lock.json` records its source, selected path, and content hash; it does not pin a commit. Start OMP from the repository root: `.omp/config.yml` applies its cwd-scoped `ignoredSkills` filter while preserving global skill payloads.

- Rust changes: use `rust-best-practices`.
- React client changes: use `vercel-react-best-practices`; apply it to `desktop/src/`, not Next.js or server patterns.
- Accessibility work: use `accessibility`, then validate the actual Tauri/WebKitGTK desktop rather than relying only on browser scores.
- Gettext messages, catalogs, plural forms, translator notes, or extraction: use `clamui-gettext` and the translation guide it points to.
- Globally managed IPC and release skills remain optional; contributors do not need them to work on ClamUI.

## Runtime, data, and security rules

- **Host ClamAV:** every package format uses the host `clamscan` and `freshclam`; daemon scanning additionally needs host `clamd` and `clamdscan`. Flatpak reaches host tools through `flatpak-spawn --host`. Never bundle or substitute the engine or its definition database.
- **Durable data:** retain the existing XDG JSON and SQLite layouts, including settings, profiles, logs, quarantine records/payloads, debug logs, and scheduler-owned system state. Writes must be atomic where the existing contract requires it; preserve unknown settings and existing migration behavior.
- **Privileges:** protected host configuration goes only through `/usr/bin/clamui-apply-preferences`, its polkit policy, destination allowlists, and `PKEXEC_UID` checks. Maintain protocol-v4 compatibility with a trusted installed helper during upgrades. Do not weaken the boundary or bootstrap trust.
- **Secrets and untrusted input:** keep VirusTotal keys out of settings payloads, errors, events, and logs; use the established keyring contract. Sanitize external process text before persistence or presentation. Keep quarantine file operations no-follow, integrity-checked, and rollback-safe.
- **Tauri:** preserve the strict CSP, reject untrusted webview/window navigation, and use native helpers only for explicit user-requested paths, exports, clipboard actions, and approved external URLs.

## User-facing compatibility

Preserve all seven `clamui` CLI subcommands, their flags, output schemas, stream destinations, and exit behavior. `clamui --help` and every CLI route must stay headless; `clamui-scheduled-scan` and `clamui-apply-preferences` are native entry points with their established contracts.

Reuse existing gettext message IDs and plural behavior from `po/`/`po/LINGUAS`; active locales are `de`, `en`, `es`, `fr`, `hu`, `it`, `nb`, `pt_BR`, `vi`, and `zh_CN`. All user-facing gettext calls need static literal arguments: choose conditional translated branches outside helpers, then interpolate after translation or plural selection. Use the existing plural API, never new `file(s)`-style pseudo-plurals. Write `—` (prose break), `–` (range), and `…` directly; do not use ASCII ` - ` or `--` as prose separators. For a literal containing a dash, range, quotation, markup, or quoted UI label/command/key/package/file literal, put a `// Translators:` comment immediately above that literal argument—not above a lone call opener. State whether a quoted UI label must match its label translation or whether a protected literal stays unchanged. See the published [translation guide](https://clamui.com/docs/contributing/translating/) for the detailed translator conventions. Do not add a Python runtime requirement to build or load catalogs.

## Packaging and documentation

Keep Flatpak builds for x86_64 and aarch64 on GNOME 51, the x86_64 AppImage, and architecture-specific Debian application and privileged-helper packages. Native Tauri packages require the system GTK 3 and WebKitGTK 4.1 runtime. Debian application and helper packages must have matching version and architecture. Use checked-in package scripts and manifests rather than copying packaging logic.

Published documentation lives in `website/src/content/docs/docs/`. Start with:

- [Installation](https://clamui.com/docs/installation/) for runtime and package requirements.
- [Development](https://clamui.com/docs/contributing/development/) for source, validation, and packaging workflows.
- [Architecture](https://clamui.com/docs/contributing/architecture/) for IPC, tray, and native-runtime boundaries.
- [Configuration](https://clamui.com/docs/reference/configuration/) for persistent data and privileged host settings.
- [Troubleshooting](https://clamui.com/docs/troubleshooting/) for user-facing recovery guidance.

Use root-relative `/docs/.../` links in website content. Keep root discoverability files concise, release content sourced from `CHANGELOG.md` and `RELEASE_NOTES.md`, and generated `website/public/` assets untouched.
