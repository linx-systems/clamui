# quarantine/ — SQLite Quarantine Subsystem

Self-contained subsystem: database + file handler + connection pool + manager facade.

Parent: [`../AGENTS.md`](../AGENTS.md)

## Structure

```
quarantine/
├── manager.py         # High-level API — quarantine, restore, delete, list
├── database.py        # SQLite metadata storage (threat name, hash, timestamps)
├── file_handler.py    # Secure file operations (move, encrypt, restore)
└── connection_pool.py # SQLite connection pooling (thread-safe)
```

## Architecture

```
QuarantineManager (facade)
├── QuarantineDatabase  — metadata CRUD (SQLite)
├── SecureFileHandler   — file move/restore with integrity checks
└── ConnectionPool      — thread-safe SQLite connections
```

- **Manager** orchestrates database + file operations in single transactions
- **Database** stores: file path, threat name, SHA-256 hash, quarantine timestamp, original permissions
- **FileHandler** moves files to `~/.local/share/clamui/quarantine/` with restricted permissions
- **ConnectionPool** manages SQLite connections across threads (avoids "database is locked")

## Key Patterns

- **SHA-256 integrity**: Hash computed on quarantine, verified on restore
- **Atomic operations**: File move + DB insert in same logical transaction
- **Thread safety**: `threading.Lock()` in manager, connection pool for DB
- **Async pair**: `quarantine_file_async()` / `restore_file_async()` / `delete_file_async()` / `get_all_entries_async()` with `GLib.idle_add()` callbacks
- **Permissions**: Quarantined files get `0o400` (owner read-only), quarantine dir gets `0o700`, DB file (and WAL/SHM) `0o600`
- **Outcome codes**: `QuarantineStatus` enum — `SUCCESS`, `FILE_NOT_FOUND`, `PERMISSION_DENIED`, `DISK_FULL`, `DATABASE_ERROR`, `ALREADY_QUARANTINED`, `ENTRY_NOT_FOUND`, `RESTORE_DESTINATION_EXISTS`, `INVALID_RESTORE_PATH`, `ERROR`
- **ConnectionPool**: WAL mode, default `pool_size=5`

## Where to Look

| Task | Module | Notes |
|------|--------|-------|
| Add quarantine metadata | `database.py` | Add column + migration |
| Change file storage | `file_handler.py` | Preserve SHA-256 verification |
| Add batch operation | `manager.py` | Use existing lock pattern |
| Fix "database locked" | `connection_pool.py` | Check pool size, timeout |

## Anti-Patterns

- **Direct DB access**: Always go through `QuarantineManager` — it coordinates file + DB ops
- **Skipping hash verify**: Always verify SHA-256 before restore (integrity check)
- **Missing permissions**: Quarantined files MUST be `0o400`, dir MUST be `0o700`, DB file MUST be `0o600`
