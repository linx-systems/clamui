# `src/core/` — application services

Read the root [`AGENTS.md`](../../AGENTS.md) first. For quarantine work, also read
[`quarantine/AGENTS.md`](quarantine/AGENTS.md).

Core owns scanning, ClamAV integration, settings, persisted logs, security helpers,
and other non-widget services. Keep widget presentation in `src/ui/`; use the GTK
main loop when a core boundary must hand work back to it.

## Navigation

| Task | Start here |
| --- | --- |
| Scan execution, cancellation, and result parsing | `scanner.py`, `daemon_scanner.py`, `scanner_base.py`, `scanner_types.py` |
| ClamAV discovery or updates | `clamav_detection.py`, `updater.py` |
| Host execution in Flatpak | `flatpak.py` |
| ClamAV configuration and privileged writes | `clamav_config.py`, `privileged_paths.py`, `privileged_helper.py` |
| Settings, logs, or credentials | `settings_manager.py`, `log_manager.py`, `keyring_manager.py` |
| Quarantine metadata and files | `quarantine/` and its local guide |

## Public-service contracts

### Results and failures

Match the API you are changing; core has no universal error-return shape. Scan,
update, VirusTotal, and quarantine operations expose typed result objects with a
status and error detail. Availability checks and configuration helpers commonly
return `(success, value_or_error)` tuples. Preserve existing status values and
`error_message` fields rather than replacing them with a new exception or result
convention. Let explicitly documented programmer-error exceptions remain explicit
(for example, invalid connection-pool configuration).

### Async and GTK boundaries

Do not add a `_sync`/`_async` pair by default: only APIs that already need a
non-blocking UI entry point use that pattern. Existing scan, update, VirusTotal,
log retrieval, and quarantine async methods run their synchronous operation in a
daemon thread, then schedule the completion callback with `GLib.idle_add()`.

`Scanner.scan_sync()` and `DaemonScanner.scan_sync()` invoke a supplied progress
callback on their calling thread. A UI progress callback must schedule its own GTK
work on the main loop. Do not touch GTK widgets from the worker.

### Scanning and cancellation

`Scanner` and `DaemonScanner` clear their cancellation event at the start of a
scan. Their subprocess paths use the cancellation-aware helpers in
`scanner_base.py`; retain those checks when changing long-running scanner code.
Use the existing `cancel()` method and process lock rather than manipulating the
current process directly.

### Paths, logging, and persistence

Validate paths at the boundary appropriate to the operation, and sanitize
user-controlled or command-derived text before putting it in logs. Keep
`TYPE_CHECKING` imports and lazy imports where they break an existing import cycle.
Use XDG-aware settings/data helpers rather than hard-coding a home-directory path.

## Flatpak host-command ownership

`wrap_host_command()` is for commands that must execute on the host. In Flatpak,
ClamAV tools and host service commands are run through `flatpak-spawn --host`;
native execution is unchanged. Do not wrap a sandbox-local command merely because
the app is running in Flatpak. Flatpak does not bundle ClamAV, and current scanning
and update paths use the host tools and host configuration rather than a sandbox
database.

## Core safety checks

- Preserve relative imports within `src/`.
- Keep subprocess arguments as argument lists; use the existing Flatpak helper for
  host-owned commands.
- Preserve scanner cancellation and bounded subprocess-output handling.
- Treat config writes and privileged helper paths as security boundaries; keep their
  validation and elevation flow intact.
