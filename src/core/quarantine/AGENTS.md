# `src/core/quarantine/` — quarantine storage

Read the parent [`../AGENTS.md`](../AGENTS.md) first.

This package separates the public `QuarantineManager` facade, SQLite metadata, secure
file handling, and an optional SQLite connection pool.

## Navigation

| Task | Start here |
| --- | --- |
| Quarantine, restore, delete, list, and orphan cleanup | `manager.py` |
| Entry schema, migrations, and metadata queries | `database.py` |
| File copying, hashing, restore-path validation, and deletion | `file_handler.py` |
| SQLite connection lifetime and concurrency | `connection_pool.py` |

## API and threading

Use `QuarantineManager` for user-facing operations that coordinate a file with its
metadata. Its synchronous `quarantine_file`, `restore_file`, and `delete_file`
methods return `QuarantineResult`; inspect `status`, `entry`, and `error_message`
rather than inventing a parallel failure convention.

The manager supplies asynchronous wrappers for quarantine, restore, delete, listing,
and cleanup work. They use a daemon thread and deliver their callback through
`GLib.idle_add()`. Keep GTK work out of the worker; the callback is the main-loop
handoff for the synchronous operation's result.

## Storage and file safety

- The default quarantine directory is
  `$XDG_DATA_HOME/clamui/quarantine` (falling back to `~/.local/share`); an explicit
  manager argument takes precedence, otherwise the `quarantine_directory` setting
  can select a custom directory. The default database is
  `$XDG_DATA_HOME/clamui/quarantine.db`.
- Quarantine copies the source bytes into a uniquely named quarantine file and then
  unlinks the source. It is not encryption. It records a SHA-256 hash and verifies
  that hash before restoration.
- Preserve the fd-based `O_NOFOLLOW` operations, regular-file checks, and
  quarantine/restore-path validation. These protect against symlink and
  time-of-check/time-of-use attacks.
- The handler creates/sets the quarantine directory to `0o700` and quarantined
  files to `0o400`. SQLite setup attempts to restrict the database, WAL, and SHM
  files to `0o600`; inability to apply those database permissions is logged rather
  than made an unconditional operation failure.

## Consistency and database concurrency

File operations and SQLite metadata cannot share one atomic transaction. If adding
metadata after a successful quarantine move fails, the manager attempts to restore
the file. If metadata removal after a restore or delete fails, the operation reports
a database error and leaves an orphaned row for cleanup. Preserve these outcomes;
do not describe the file and database changes as a single transaction.

`QuarantineDatabase` enables a pool of three connections by default; passing zero
uses a fresh connection per operation. `ConnectionPool` itself defaults to five
connections, uses a queue and lock, configures SQLite with WAL and
`check_same_thread=False`, and commits on normal context-manager exit or rolls back
on an exception. WAL improves reader/writer concurrency but does not eliminate every
SQLite error, so retain timeout and error handling.

## Change safety

- Preserve SHA-256 verification before restore and preserve the original permissions
  only after the restore path passes validation.
- Keep `QuarantineEntry` permission masking and database migrations compatible with
  existing rows.
- Close the manager when its owning service shuts down so pooled connections are
  released.