# ClamUI Development Guide

>New to ClamUI? Start with the **[Getting Started Guide](user-guide/getting-started.md)** to learn about installation and basic usage before diving into development.

This document provides instructions for setting up a development environment, running tests, and contributing to ClamUI.

## Table of Contents

1. [Development Environment Setup](#development-environment-setup)
2. [Running from Source](#running-from-source)
3. [Testing](#testing)
4. [Code Quality](#code-quality)
5. [Contributing](#contributing)
6. [Architecture Overview](#architecture-overview)

---

## Development Environment Setup

### Prerequisites

ClamUI requires system packages for GTK4/PyGObject bindings before installing Python dependencies.

#### Ubuntu/Debian

```bash
# GTK4 and Adwaita runtime libraries
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-dev

# Build dependencies (required for pip install)
sudo apt install libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev
# On Ubuntu < 24.04, use: libgirepository1.0-dev instead of libgirepository-2.0-dev

# Build dependencies for Pillow (tray icon support)
sudo apt install libjpeg-dev zlib1g-dev

# ClamAV antivirus (for testing scan functionality)
sudo apt install clamav

# System tray support (optional, for context menu)
sudo apt install gir1.2-dbusmenu-0.4
```

#### Fedora

```bash
sudo dnf install python3-gobject python3-gobject-devel gtk4 libadwaita \
    gobject-introspection-devel cairo-gobject-devel clamav libdbusmenu
```

#### Arch Linux

```bash
sudo pacman -S python-gobject gtk4 libadwaita clamav libdbusmenu-glib
```

### Clone the Repository

```bash
git clone https://github.com/linx-systems/clamui.git
cd clamui
```

### Install Python Dependencies

ClamUI uses [uv](https://github.com/astral-sh/uv) for dependency management (recommended):

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev dependencies)
uv sync --dev
```

> **Ubuntu/Pop!_OS 22.04 note:** `uv sync` may resolve `PyGObject 3.50+`, which needs
> GLib 2.80+. Jammy ships GLib 2.72, so create the venv manually and preinstall a
> compatible PyGObject first:
>
> ```bash
> uv venv --python 3.11
> uv pip install --python .venv/bin/python "PyGObject<3.50"
> uv pip install --python .venv/bin/python -e ".[dev]"
> ```

Alternatively, use pip:

```bash
pip install -e ".[dev]"
```

---

## Running from Source

### With uv (Recommended)

```bash
uv run clamui
```

### With pip installation

```bash
clamui
```

### With file arguments

```bash
# Open with files/folders pre-selected for scanning
uv run clamui /path/to/file1 /path/to/folder
```

### Scheduled Scan CLI

ClamUI includes a CLI tool for scheduled scans (used by systemd/cron):

```bash
uv run clamui-scheduled-scan --help
```
### CLI Subcommands

ClamUI provides headless subcommands that work without a display server:

```bash
uv run clamui scan /path/to/file      # One-shot scan
uv run clamui quarantine list          # List quarantined files
uv run clamui profile list             # List scan profiles
uv run clamui status                   # ClamAV status
uv run clamui history                  # Scan history
uv run clamui help                     # Command overview
uv run clamui install-privileged-helper # Install pkexec config helper (needs sudo)
```

Most subcommands support `--json` output for scripting integration.

---

## Testing

ClamUI includes a comprehensive test suite with pytest. The project enforces a minimum of **50% code coverage** with a
target of **80%+** for comprehensive coverage.

Plain `pytest` runs are optimized for local iteration and do not enable coverage by default. Run coverage explicitly
when you need it locally or for CI-style verification.

### Test Dependencies

Test dependencies are included in the `[dev]` optional dependencies:

```bash
# With uv
uv sync --dev

# With pip
pip install -e ".[dev]"
```

### Running Tests

| Command                             | Description                 |
|-------------------------------------|-----------------------------|
| `pytest`                            | Run all tests (fast local default, no coverage) |
| `pytest -v`                         | Run with verbose output     |
| `pytest tests/core/`                | Run specific test directory |
| `pytest tests/core/test_scanner.py` | Run specific test file      |
| `pytest -k "test_scanner"`          | Run tests matching pattern  |
| `pytest --ignore=tests/e2e`         | Run the default CI test scope without e2e        |

### Running Tests with Coverage

```bash
# Terminal coverage report
pytest --cov=src --cov-report=term-missing

# HTML coverage report
pytest --cov=src --cov-report=html
# Open htmlcov/index.html in your browser

# Both reports
pytest --cov=src --cov-report=term-missing --cov-report=html
```

### Coverage Targets

| Module          | Coverage Target | Description                            |
|-----------------|-----------------|----------------------------------------|
| `src/core/`     | 80%+            | Critical business logic                |
| `src/profiles/` | 80%+            | Profile management                     |
| `src/ui/`       | 70%+            | GTK components (some lines untestable) |
| Overall `src/`  | 50% minimum     | Enforced by CI                         |

### Test Organization

Tests mirror the source structure under `tests/`:

| Directory | Tests for |
|-----------|-----------|
| `tests/core/` | `src/core/` business logic |
| `tests/profiles/` | `src/profiles/` profile management |
| `tests/ui/` | `src/ui/` GTK components |
| `tests/ui/preferences/` | `src/ui/preferences/` pages |
| `tests/ui/scan/` | `src/ui/scan/` modular scan view |
| `tests/cli/` | `src/cli/` subcommands |
| `tests/packaging/` | Debian, Flatpak, desktop integration |
| `tests/integration/` | Cross-module integration |
| `tests/e2e/` | End-to-end workflows |

Shared fixtures and GTK mocking are in `tests/conftest.py`.

### Test Markers

Tests are categorized using pytest markers:

| Marker                     | Description                                           |
|----------------------------|-------------------------------------------------------|
| `@pytest.mark.integration` | Integration tests (may require external dependencies) |
| `@pytest.mark.ui`          | UI tests (require GTK/display environment)            |
| `@pytest.mark.slow`        | Slow-running tests                                    |
| `@pytest.mark.property`    | Property-based tests (Hypothesis)                     |

Run specific categories:

```bash
# Skip integration tests
pytest -m "not integration"

# Run only UI tests
pytest -m ui
```

### Headless/CI Testing

All tests are designed to run in headless CI environments without requiring a display server. GTK-dependent tests skip
gracefully when no display is available:

```bash
# Run in headless mode (no DISPLAY set)
unset DISPLAY
pytest

# GTK tests will show as skipped with a clear message
```

### Performance Verification

```bash
# Show slowest tests
pytest --durations=10

# Use this to spot runtime regressions across the full suite
pytest --durations=0
```

---

## Code Quality

### Linting with Ruff

ClamUI uses [Ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
# Ruff is included in dev dependencies (uv sync --dev)
# Run linting
uv run ruff check src/ tests/

# Run linting with auto-fix
uv run ruff check --fix src/ tests/

# Check formatting
uv run ruff format --check src/ tests/

# Apply formatting
uv run ruff format src/ tests/
```

### Configuration

Ruff is configured in `pyproject.toml`. See `[tool.ruff.lint]` for the full rule set, which includes pycodestyle, Pyflakes, isort, bugbear, comprehensions, pyupgrade, unused-arguments, simplify, gettext, bandit (security), print detection, pytest-style, and Ruff-native rules.

### Pre-commit Checks

Before committing, run:

```bash
# Lint and format
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/

# Run tests
pytest
```

A pre-commit hook (install via `./scripts/hooks/install-hooks.sh`) blocks absolute `src.*` imports which break when ClamUI is installed as a package.

---

## Contributing

Contributions are welcome! Please follow these guidelines.

### Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/clamui.git
   cd clamui
   ```
3. Set up the development environment (see above)
4. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

### Development Workflow

1. **Make your changes** following the existing code patterns
2. **Add tests** for new functionality
3. **Run the test suite** and ensure all tests pass:
   ```bash
   pytest
   ```
4. **Check code quality**:
   ```bash
   ruff check --fix src/ tests/
   ruff format src/ tests/
   ```
5. **Commit your changes** with a descriptive message:
   ```bash
   git commit -m "Add feature: description of what you added"
   ```

### Writing Tests

Follow these patterns when writing tests:

1. **Use fixtures** for common setup (`@pytest.fixture`)
2. **Mock external dependencies** (ClamAV, system paths, GTK)
3. **Use `tmp_path`** fixture for file I/O tests
4. **Add docstrings** to all test methods
5. **Test error paths** explicitly

Example test structure:

```python
import pytest
from unittest import mock

class TestMyFeature:
    """Tests for MyFeature class."""

    @pytest.fixture
    def my_instance(self, tmp_path):
        """Create instance for testing."""
        return MyFeature(data_dir=str(tmp_path))

    def test_basic_operation(self, my_instance):
        """Test basic operation succeeds."""
        result = my_instance.do_something()
        assert result is not None

    def test_error_handling(self, my_instance):
        """Test error case is handled gracefully."""
        with pytest.raises(ValueError):
            my_instance.do_something_invalid()
```

### Pull Request Guidelines

1. **Update documentation** if you change APIs or add features
2. **Keep changes focused** - one feature or fix per PR
3. **Describe your changes** in the PR description
4. **Link related issues** using `Fixes #123` or `Closes #123`
5. **Ensure CI passes** - all tests and linting must pass

### Code Style

- **Python**: Follow PEP 8 (enforced by Ruff)
- **Line length**: 100 characters maximum
- **Imports**: Sorted by isort (enforced by Ruff)
- **Type hints**: Use where practical (not required)
- **Docstrings**: Required for classes and public methods

---

## Architecture Overview

### Tech Stack

| Component    | Technology                |
|--------------|---------------------------|
| Language     | Python 3.11+              |
| UI Framework | GTK4 with PyGObject       |
| UI Styling   | libadwaita (GNOME design) |
| Testing      | pytest, pytest-cov        |
| Linting      | Ruff                      |
| Packaging    | Hatchling, Flatpak, AppImage, Debian |

### Key Design Patterns

- **Adw.Application**: Modern GNOME application lifecycle with service locator pattern (`AppContext`)
- **Async Scanning**: Background threads with `GLib.idle_add()` for thread-safe UI updates
- **Subprocess Integration**: `clamscan`/`clamdscan` for antivirus scanning
- **SNI Tray**: StatusNotifierItem via GIO D-Bus subprocess architecture
- **Modular Scan UI**: Coordinator pattern decomposing scan view into target selector, profile selector, progress, and results widgets

### Entry Points

```toml
clamui                    # GUI application (or CLI subcommands)
clamui-scheduled-scan     # Scheduled scan CLI (systemd/cron)
clamui-apply-preferences  # Privileged config applier (via pkexec)
```

For a detailed breakdown of all modules, see the [Repository Structure](../AGENTS.md#repository-structure-top-level) section in AGENTS.md.

---

## Continuous Integration

ClamUI uses GitHub Actions for CI with the following workflows:

| Workflow               | Trigger         | Purpose                              |
|------------------------|-----------------|--------------------------------------|
| `test.yml`             | Push/PR to main | Run tests on Python 3.11, 3.12, 3.13 |
| `lint.yml`             | Push/PR to main | Ruff linting and format checks       |
| `build-deb.yml`        | Manual/Release  | Build Debian packages                |
| `build-flatpak.yml`    | Manual/Release  | Build Flatpak packages               |
| `build-appimage.yml`   | Push/Tag/PR     | Build AppImage                       |
| `build-all.yml`        | Manual/Release  | Orchestrate all package builds       |
| `release.yml`          | Tag `v*`        | Draft GitHub release from RELEASE_NOTES.md |
| `codeql.yml`           | Push/PR/Schedule| CodeQL security analysis             |
| `dependency-audit.yml` | Schedule        | Dependency vulnerability audit       |
| `dependency-review.yml`| PR              | Review new dependency changes        |
| `i18n.yml`             | Push/PR         | Translation validation               |
| `deploy-website.yml`   | Push/Release/Schedule | Build and deploy website to GitHub Pages |

### CI Environment

- **Runner**: Ubuntu 24.04 (test matrix), Ubuntu 22.04 (libadwaita 1.1 compatibility check)
- **Display**: xvfb for headless GTK testing
- **Coverage**: Uploaded as artifact on Python 3.12

---

## See Also

- [README.md](../README.md) - Project overview and quick start
- [CONFIGURATION.md](./CONFIGURATION.md) - Configuration reference and settings guide
- [INSTALL.md](./INSTALL.md) - Installation guide
- [TRANSLATING.md](./TRANSLATING.md) - Translation contributing guide
