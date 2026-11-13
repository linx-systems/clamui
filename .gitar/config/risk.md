# ClamUI pull request risk policy

Assess the entire current PR, including generated changes, renames, deletions, and indirect effects through callers and tests. Use the highest applicable tier across all changes; mixed scope never lowers risk. Organization-level risk is a baseline and cannot be lowered by this policy. Assess impact independently of finding severity or review verdict: a clean review or green CI does not reduce risk. Missing information or inability to assess the impact is High; bounded uncertainty is at least Medium, and uncertainty involving a sensitive or unbounded impact is High. Never use author, bot identity, title, labels, or size as an exemption.

ClamUI uses a Rust core in `crates/clamui-core/`, a Tauri 2 runtime in `desktop/src-tauri/`, and a React frontend in `desktop/src/`. It relies on host-installed ClamAV, including via `flatpak-spawn --host` under Flatpak; it does not bundle an engine or database. Security has highest priority.

## High

Classify as High if any change affects, directly or indirectly:

- Scan execution, targets, results, progress, cancellation, scheduling, or database updates; host tool execution or the host-installed ClamAV boundary.
- Security boundaries: Rust IPC commands or events and argument validation, Tauri capabilities, CSP or navigation, filesystem/shell/network access, privileged helper or polkit, destination allowlists, or `PKEXEC_UID` checks.
- Persisted data or compatibility: XDG JSON or SQLite layouts, migrations, settings, profiles, logs, quarantine payloads or metadata, no-follow, integrity or rollback guarantees, keyring or VirusTotal secrets, or CLI schemas, flags, streams, and exit contracts. Include destructive changes and changes that can break compatibility or lose data.
- Dependencies, dependency manifests, lockfiles, build scripts, generated dependency sources or Flatpak sources; any other supply-chain change.
- CI, build, release, signing, installers or packaging, including changes in `.github/`, `scripts/`, `debian/`, `rpm/`, `flathub/`, or `appimage/`; application identity in `data/` or `icons/`; or runtime baselines.
- Bot, agent, review, approval, security, or repository governance policy, including `.gitar/`.

The sensitive file and path rules above apply even to seemingly tiny or comment-only edits to those configuration files. Changes to tests or callers that alter or weaken a sensitive behavior or its contract are High, not Low.

## Medium

Absent a High trigger, classify bounded non-sensitive application behavior, UI or accessibility changes, nontrivial refactors, substantial test restructuring, and uncertain but bounded impact as Medium.

## Low

Use Low only when every change is clearly inert and no High or Medium trigger applies:

- Prose, spelling, or link corrections that preserve behavior and security guidance and do not change installation commands, downloads, or privileged-operation instructions; no executable Astro/MDX changes.
- Gettext corrections in `po/` that preserve message IDs, placeholders, plurals, markup, protected literals, and existing locale coverage; generated catalog changes match the source changes.
- Inert comments or mechanical formatting with no behavioral change, excluding doctests, directives, attributes, generated output, and embedded commands.
- Focused, isolated tests that strengthen coverage of unchanged behavior without production changes, reduced coverage, weakened assertions, changed expected contracts, skips, or privileged/network side effects.

A documentation, translation, or test filename alone never establishes Low risk. Sensitive behavior affected indirectly through callers or tests is not Low.

Risk classification is not approval or merge authorization. The separate `approve.md` policy and its human-review restrictions still apply.

Reference: [Gitar Risk Triage](https://docs.gitar.ai/features/code-review/risk-triage.md).
