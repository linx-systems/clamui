# Contributing to ClamUI

Thanks for your interest in ClamUI. Contributions of every size are welcome:

- Bug reports and reproduction steps
- Feature ideas and design feedback
- Code changes, from small fixes to new views
- Documentation improvements
- Translations into new or existing languages
- Testing on distributions and desktops we do not cover well

You do not need to be a GTK or ClamAV expert to help. If something is unclear, open an issue and ask.

## Code of Conduct

Participation in this project is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). By taking part, you agree to
uphold it.

## Reporting Issues

For bugs and feature requests, open a public issue on
[GitHub Issues](https://github.com/linx-systems/clamui/issues). A good bug report includes:

- What you expected to happen and what happened instead
- Steps to reproduce
- ClamUI version, installation method (Flatpak, Debian package, AppImage, source), distribution, and desktop environment
- Relevant log output or error messages

**Do not report security vulnerabilities in public issues.** Follow the private reporting process in
[SECURITY.md](SECURITY.md) instead.

## Development Setup

Full environment setup — system packages per distribution, running from source, and the architecture overview — is in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). The short version, once the system GTK4/PyGObject packages are installed:

```bash
uv sync --dev
./scripts/hooks/install-hooks.sh
```

ClamUI requires **Python 3.11 or newer**.

Installing the git hooks is **required**. The pre-commit hook blocks absolute `src.*` imports, which break when ClamUI
is installed as a package.

## Making a Change

1. Fork the repository and clone your fork.
2. Create a branch for your work. Branch names and commit message styles are not enforced — just make them descriptive.
3. Make your change, following the existing patterns in the code you are touching.
4. Validate your change (see below).
5. Push the branch and open a pull request against `master`.

## Validating Your Change

Run these before opening a pull request:

```bash
uv run ruff format src/ tests/
uv run ruff check src/ tests/ --fix
pytest
```

While developing, run focused tests instead of the whole suite for faster feedback:

```bash
pytest tests/core/test_scanner.py -v
pytest tests/core -v
```

## ClamUI-Specific Rules

These come up in almost every change and are worth knowing before you start:

- **Relative imports inside `src/`.** Use `from .module import Thing`, never `from src.module import Thing`. The
  package installs as `clamui`, so absolute `src.*` imports fail outside a source checkout.
- **Translatable user-facing text.** Wrap every user-visible string with gettext `_()`. Never put an f-string inside
  `_()` — use `_("Scanned {count} files").format(count=count)` so translators get a stable template. Log messages are
  not translated.
- **libadwaita 1.1 compatibility.** Ubuntu 22.04 is the baseline. Do not use APIs added after libadwaita 1.1; runtime
  fallbacks live in `src/ui/compat.py`.
- **GTK updates on the main thread.** Long-running work belongs on a background thread, and every widget update must be
  marshalled back with `GLib.idle_add()`.
- **Sanitize external data.** Run untrusted or user-supplied text through the helpers in `src/core/sanitize.py` before
  logging, and validate filesystem paths with `src/core/path_validation.py` before acting on them.
- **Test changed behavior.** If your change alters observable behavior, add or update tests. Tests mirror the source
  layout: `src/core/scanner.py` is covered by `tests/core/test_scanner.py`.
- **Regenerate the POT file** whenever you add, remove, or edit a translatable string:

  ```bash
  ./scripts/update-pot.sh
  ```

For translation work specifically, see [docs/TRANSLATING.md](docs/TRANSLATING.md). For a deeper tour of the
architecture, module reference, and coding patterns, see [AGENTS.md](AGENTS.md).

## Pull Requests

- Keep the scope focused — one fix or feature per pull request.
- Explain what changed, why, and how you verified it.
- Link the related issue where one exists (`Fixes #123`).
- Update documentation and translatable strings alongside the code they describe.
- Make sure CI is green. Formatting, linting, and the test suite all run automatically.

Review may ask for changes; that is normal and not a judgement of your work. Thanks for contributing.
