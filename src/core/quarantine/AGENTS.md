# quarantine/ - SQLite Quarantine Subsystem

Self-contain subsystem: database + file handler + connection pool + manager facade.

Parent: [`../AGENTS.md`](../AGENTS.md)

## Structure

```
quarantine/
├── manager.py         # High-level API - quarantine, restore, delete, list
├── database.py        # SQLite metadata storage (threat name, hash, timestamps)
├── file_handler.py    # Secure file operations (move, encrypt, restore)
└── connection_pool.py # SQLite connection pooling (thread-safe)
```

## Architecture

```
QuarantineManager (facade)
├── QuarantineDatabase  - metadata CRUD (SQLite)
├── SecureFileHandler   - file move/restore with integrity checks
└── ConnectionPool      - thread-safe SQLite connections
```

- **Manager** boss database + file work in one transaction
- **Database** keep: file path, threat name, SHA-256 hash, quarantine time, old permissions
- **FileHandler** move file to `~/.local/share/clamui/quarantine/`, tight permissions
- **ConnectionPool** hold SQLite connections across threads (no "database is locked")

## Key Patterns

- **SHA-256 integrity**: Hash on quarantine, check on restore
- **Atomic operations**: File move + DB insert = same transaction
- **Thread safety**: `threading.Lock()` in manager, pool for DB
- **Async pair**: `quarantine_file_async()` / `restore_file_async()` / `delete_file_async()` / `get_all_entries_async()` with `GLib.idle_add()` callbacks
- **Permissions**: Quarantine file get `0o400` (owner read only), quarantine dir get `0o700`, DB file (and WAL/SHM) `0o600`
- **Outcome codes**: `QuarantineStatus` enum - `SUCCESS`, `FILE_NOT_FOUND`, `PERMISSION_DENIED`, `DISK_FULL`, `DATABASE_ERROR`, `ALREADY_QUARANTINED`, `ENTRY_NOT_FOUND`, `RESTORE_DESTINATION_EXISTS`, `INVALID_RESTORE_PATH`, `ERROR`
- **ConnectionPool**: WAL mode, default `pool_size=5`

## Where to Look

| Task | Module | Notes |
|------|--------|-------|
| Add quarantine metadata | `database.py` | Add column + migration |
| Change file storage | `file_handler.py` | Keep SHA-256 check |
| Add batch operation | `manager.py` | Use old lock pattern |
| Fix "database locked" | `connection_pool.py` | Check pool size, timeout |

## Anti-Patterns

- **Direct DB access**: Always go through `QuarantineManager` - it boss file + DB ops
- **Skipping hash verify**: Always check SHA-256 before restore (integrity check)
- **Missing permissions**: Quarantine file MUST be `0o400`, dir MUST be `0o700`, DB file MUST be `0o600`