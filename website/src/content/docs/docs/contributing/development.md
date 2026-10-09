---
title: Development and packaging
description: Set up ClamUI, test a change, work with packages, and maintain the docs site.
---

## Prerequisites

ClamUI supports Python 3.11+, GTK 4.6+, and libadwaita 1.1+. Source `PyGObject>=3.56.3` needs GLib 2.80+, so stock Ubuntu/Pop!_OS 22.04 (GLib 2.72) cannot satisfy the current source dependency floor even though the UI remains compatible with their GTK/libadwaita floor. Use Flatpak or a newer development host there.

### Debian or Ubuntu

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-dev libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev libjpeg-dev zlib1g-dev clamav gir1.2-dbusmenu-0.4
```

### Fedora

```bash
sudo dnf install python3-gobject python3-gobject-devel gtk4 libadwaita gobject-introspection-devel cairo-gobject-devel clamav libdbusmenu
```

### Arch Linux

```bash
sudo pacman -S python-gobject gtk4 libadwaita clamav libdbusmenu-glib
```

Use `libgirepository1.0-dev` rather than `libgirepository-2.0-dev` on Ubuntu releases before 24.04.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) before creating the environment:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new shell if the installer changes your `PATH`.

## Work on the app

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
uv sync --locked --extra dev
uv run clamui
uv run clamui /path/to/file-or-folder
uv run clamui scan /path/to/file
uv run clamui quarantine list
uv run clamui profile list
uv run clamui status
uv run clamui history
uv run clamui help
uv run clamui-scheduled-scan --help
```

Use relative imports inside `src/`; absolute `src.*` imports break installed packages. User-facing strings need gettext marking, and GTK/UI work must return to the main loop through `GLib.idle_add()`. Read the repository's [AI and contributor guide](https://github.com/linx-systems/clamui/blob/master/AGENTS.md) for detailed conventions.

The native-host-only `sudo clamui install-privileged-helper` installs the root-owned preference helper and polkit policy. Do not run it inside Flatpak; install the matching helper package on the host instead.

## Maintain local Repowise architecture guidance

Repowise indexes and configuration live in the ignored `.repowise/` directory. They are local machine state, so do not commit them or put provider credentials in them. After creating or recovering a local index, restore this guidance block in the root `.repowise/config.yaml` before generating architecture prose:

```yaml
generation_context:
  token_budget: 8000
  files:
    repo_overview:
      - src/ui/scan/AGENTS.md
      - src/app.py
    onboarding/getting_started:
      - src/ui/scan/AGENTS.md
      - src/app.py
    onboarding/key_concepts:
      - src/ui/scan/AGENTS.md
      - src/app.py
    onboarding/how_it_works:
      - src/ui/scan/AGENTS.md
      - src/app.py
    onboarding/active_landscape:
      - src/ui/scan/AGENTS.md
      - src/app.py
```

The indexed guidance records the current boundary: `src/ui/scan_view.py:ScanView`,
created by `ClamUIApp.scan_view` in `src/app.py`, is the active desktop scan
screen. `src/ui/scan/` is a modular alternative; its `ScanCoordinator` and
`ScanController` are not constructed by the current application route.

For an approved repair with the Claude CLI provider, first inspect the local
generation plan:

```bash
repowise generate --page repo_overview:clamui --cascade none --provider claude_cli --model claude-haiku-4-5 --dry-run
```

`claude_cli` uses the Claude subscription rather than a local Ollama model.
Only after the plan has been reviewed and the subscription use has explicit
approval, write the page:

```bash
repowise generate --page repo_overview:clamui --cascade none --provider claude_cli --model claude-haiku-4-5 --yes
```

Repowise records the selected guidance in the generated page metadata under
`source_evidence`; for the overview, confirm that it lists both
`src/ui/scan/AGENTS.md` and `src/app.py` as included. This grounding makes the
fact available on later regeneration, but generated prose still requires
review: an LLM cannot be guaranteed to reproduce every fact perfectly.

To pin a correction while prose is being regenerated, use the dashboard API's
`PATCH /api/pages/lookup/notes?page_id=<page-id>` endpoint with
`human_notes`. The note survives model regeneration and is returned by the
dashboard page APIs. It is not a retrieval guarantee: MCP `get_context`
includes it only for file pages, while `get_overview` and search do not expose
it. Keep the source guidance above as the durable correction.

## Restore local Repowise semantic search

Both the root repository and `website/` have separate ignored Repowise state.
In each local `.repowise/config.yaml`, set:

```yaml
embedder: ollama
embedding_model: embeddinggemma
```

In each corresponding ignored `.repowise/.env`, set the local embedding
connection values:

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=embeddinggemma
OLLAMA_EMBEDDING_DIMS=768
```

With Ollama and `embeddinggemma` available locally, rebuild both vector stores
from the repository root:

```bash
repowise reindex . --embedder ollama
repowise reindex website --embedder ollama
```

Reindexing embeds existing pages locally and does not generate prose. Restart
the Repowise MCP server and dashboard after reindexing so they reconnect to the
updated local semantic indexes.

## Validate before a pull request

```bash
uv run ruff check .
uv run ruff format --check .
pytest
pytest --cov=src --cov-report=term-missing
./scripts/hooks/install-hooks.sh
```

Tests mirror source beneath `tests/`; `tests/conftest.py` provides GTK fixtures. The project targets 50% total coverage, 80%+ for core/profiles, and 70%+ for UI. CI tests Python 3.11–3.14 and retains an Ubuntu 22.04/libadwaita 1.1 compatibility job.

## Packaging boundaries

Flatpak builds against GNOME 51, whose native Python runtime is 3.14; generated Flatpak wheel sources target `314-x86_64` and `314-aarch64`. This bundled runtime is independent of the host GTK/Python stack. Flatpak and AppImage carry Python and GUI dependencies but **never ClamAV**: all formats use host `clamscan`, `freshclam`, and optionally `clamd`/`clamdscan`. The full Debian application package requires host Python 3.11+ (stock Debian 12+ or Ubuntu 24.04+); use Flatpak on Ubuntu/Pop!_OS 22.04. Flatpak host calls and configuration at the selected distribution-specific paths remain explicit boundaries. The Debian application and matching privileged-helper packages must be version-matched.

Build paths and package metadata live in [`flathub/`](https://github.com/linx-systems/clamui/tree/master/flathub), [`appimage/`](https://github.com/linx-systems/clamui/tree/master/appimage), and [`debian/`](https://github.com/linx-systems/clamui/tree/master/debian). Use their checked-in scripts and manifests rather than duplicating package logic.

Install `flatpak-builder` from your distribution. On Debian or Ubuntu:

```bash
sudo apt install flatpak-builder
```

After [setting up Flathub](/docs/installation/#flatpak), install the matching SDK and runtime:

```bash
flatpak install flathub org.gnome.Sdk//51 org.gnome.Platform//51
```

Build package artifacts from the repository root:

```bash
flatpak-builder --user --install --force-clean build-dir flathub/io.github.linx_systems.ClamUI.local.yml
./appimage/build-appimage.sh
./debian/build-deb.sh
```

The Flatpak local manifest intentionally sources the working tree; its production manifest sources the pinned release. AppImage builds need Ubuntu 24.04+ GTK/libadwaita packages, Python, `wget`, and FUSE to run the artifact. Debian builds require `dpkg-deb` and `fakeroot` and produce both version-matched `.deb` files.

## Update the application icon

`icons/io.github.linx_systems.ClamUI.svg` is the source icon; `icons/io.github.linx_systems.ClamUI.png` is its checked-in 128×128 rendering. When the SVG changes, regenerate and commit both files once. Builds install the committed PNG and never convert it.

```bash
rsvg-convert --width=128 --height=128 --output=icons/io.github.linx_systems.ClamUI.png icons/io.github.linx_systems.ClamUI.svg
```

On Debian or Ubuntu, install the converter separately:

```bash
sudo apt install librsvg2-bin
```

## Write documentation

The website's Starlight documentation source is `website/src/content/docs/docs/`; add a focused Markdown/MDX page there, use root-relative `/docs/.../` links, and update the Starlight sidebar in `website/astro.config.mjs`. Keep root `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md` as short GitHub discoverability pointers, not parallel manuals. `CHANGELOG.md` and `RELEASE_NOTES.md` remain release inputs and are rendered by MDX imports rather than copied.

The project chose Starlight inside the existing Astro site at `/docs/` for stock navigation, search, and code-copy UI without a separate CMS, server, or search service. Website commands:

```bash
cd website
bun install --frozen-lockfile
bun run dev
bun run check
bun run build
```

Keep `pagefind` and `@pagefind/default-ui` pinned to 1.4.0. Pagefind 1.5 workers use root-relative URLs that fail in `WorkerGlobalScope` on static hosts. Lift the pin only after browser search passes both a direct docs load and the marketing-to-docs navigation path.

Do not edit generated `website/public/` asset copies; the website scripts synchronize root icons and screenshots. Keep release documentation sourced from the root files.