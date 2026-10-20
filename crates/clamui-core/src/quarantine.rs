use crate::common::{expand_path, now_iso, path_from_wire, Context};
use crate::AppResult;
use rusqlite::types::ValueRef;
use rusqlite::{params, Connection, OpenFlags, Row};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::ffi::{CStr, CString, OsStr, OsString};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Component, Path, PathBuf};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Mutex,
};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const DB_MODE: u32 = 0o600;
const QUARANTINE_DIR_MODE: u32 = 0o700;
const QUARANTINE_FILE_MODE: u32 = 0o400;
const BUFFER_SIZE: usize = 64 * 1024;
const SPACE_RESERVE: u64 = 10 * 1024 * 1024;
const CLEANUP_INTERVAL: Duration = Duration::from_secs(24 * 60 * 60);
const CLEANUP_CHECK_THROTTLE: Duration = Duration::from_secs(60);
static LAST_CLEANUP_CHECK: AtomicU64 = AtomicU64::new(0);

#[derive(Debug)]
struct HashMismatch;

impl std::fmt::Display for HashMismatch {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("file hash mismatch")
    }
}

impl std::error::Error for HashMismatch {}

#[derive(Clone, Debug)]
struct RawPath(Vec<u8>);

impl RawPath {
    fn from_path(path: &Path) -> Self {
        Self(path.as_os_str().as_bytes().to_vec())
    }

    fn as_path(&self) -> PathBuf {
        PathBuf::from(OsString::from_vec(self.0.clone()))
    }

    fn display(&self) -> String {
        String::from_utf8_lossy(&self.0).into_owned()
    }
}

#[derive(Clone, Debug)]
pub struct QuarantineEntry {
    pub id: i64,
    original_path: RawPath,
    quarantine_path: RawPath,
    pub threat_name: String,
    pub detection_date: String,
    pub file_size: u64,
    pub file_hash: String,
    pub original_permissions: u32,
}

impl QuarantineEntry {
    fn to_json(&self) -> Value {
        // The database retains raw bytes. JSON has no reversible representation for
        // arbitrary Unix filenames, so these fields are display-only; all mutations
        // use the stable database id and therefore never round-trip a lossy path.
        json!({
            "id": self.id,
            "original_path": self.original_path.display(),
            "quarantine_path": self.quarantine_path.display(),
            "threat_name": self.threat_name,
            "detection_date": self.detection_date,
            "file_size": self.file_size,
            "file_hash": self.file_hash,
            "original_permissions": self.original_permissions,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Status {
    Success,
    FileNotFound,
    PermissionDenied,
    DiskFull,
    DatabaseError,
    EntryNotFound,
    RestoreDestinationExists,
    InvalidRestorePath,
    Error,
}

impl Status {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::FileNotFound => "file_not_found",
            Self::PermissionDenied => "permission_denied",
            Self::DiskFull => "disk_full",
            Self::DatabaseError => "database_error",
            Self::EntryNotFound => "entry_not_found",
            Self::RestoreDestinationExists => "restore_destination_exists",
            Self::InvalidRestorePath => "invalid_restore_path",
            Self::Error => "error",
        }
    }
}

#[derive(Debug)]
struct OperationResult {
    status: Status,
    entry: Option<QuarantineEntry>,
    error_message: Option<String>,
}

impl OperationResult {
    fn success(entry: QuarantineEntry) -> Self {
        Self {
            status: Status::Success,
            entry: Some(entry),
            error_message: None,
        }
    }

    fn failure(status: Status, error_message: impl Into<String>) -> Self {
        Self {
            status,
            entry: None,
            error_message: Some(error_message.into()),
        }
    }

    fn with_entry(
        status: Status,
        entry: QuarantineEntry,
        error_message: impl Into<String>,
    ) -> Self {
        Self {
            status,
            entry: Some(entry),
            error_message: Some(error_message.into()),
        }
    }

    fn into_json(self) -> Value {
        let mut result = serde_json::Map::new();
        result.insert("status".into(), Value::String(self.status.as_str().into()));
        if let Some(entry) = self.entry {
            result.insert("entry".into(), entry.to_json());
        }
        if let Some(error_message) = self.error_message {
            result.insert("error_message".into(), Value::String(error_message));
        }
        Value::Object(result)
    }
}

#[derive(Debug)]
struct FileMove {
    destination: RawPath,
    file_size: u64,
    file_hash: String,
    original_permissions: u32,
}

#[derive(Debug)]
struct QuarantineManager {
    db_path: PathBuf,
    quarantine_dir: PathBuf,
}

#[derive(Default)]
struct QuarantineDatabaseState {
    initialized: Mutex<bool>,
}

impl QuarantineManager {
    fn from_context(ctx: &Context) -> AppResult<Self> {
        let configured = ctx
            .settings()?
            .get("quarantine_directory")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .map(expand_path);
        let quarantine_dir = configured.unwrap_or_else(|| ctx.paths.data_dir.join("quarantine"));
        let manager = Self {
            db_path: ctx.paths.data_dir.join("quarantine.db"),
            quarantine_dir,
        };
        manager
            .ensure_quarantine_dir()
            .map_err(|error| error.to_string())?;
        let database_state = ctx.shared_state(QuarantineDatabaseState::default)?;
        manager.initialize_database(&database_state)?;
        Ok(manager)
    }

    fn ensure_quarantine_dir(&self) -> io::Result<()> {
        fs::create_dir_all(&self.quarantine_dir)?;
        let dir = open_path(
            &self.quarantine_dir,
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW,
            0,
        )?;
        fchmod(dir.as_raw_fd(), QUARANTINE_DIR_MODE)?;
        Ok(())
    }

    fn initialize_database(&self, state: &QuarantineDatabaseState) -> AppResult<()> {
        let mut initialized = state
            .initialized
            .lock()
            .map_err(|_| "quarantine database initialization lock is poisoned".to_owned())?;
        if *initialized {
            return Ok(());
        }
        if let Some(parent) = self.db_path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Unable to create quarantine data directory: {error}"))?;
        }
        self.pin_database_file()?;
        let mut connection = self.connection()?;
        connection.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA foreign_keys=ON;
             CREATE TABLE IF NOT EXISTS quarantine (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 original_path TEXT NOT NULL,
                 quarantine_path TEXT NOT NULL UNIQUE,
                 threat_name TEXT NOT NULL,
                 detection_date TEXT NOT NULL,
                 file_size INTEGER NOT NULL,
                 file_hash TEXT NOT NULL,
                 original_permissions INTEGER NOT NULL DEFAULT 420 CHECK (original_permissions BETWEEN 0 AND 511),
                 state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'restored', 'deleted'))
             );
             CREATE INDEX IF NOT EXISTS idx_quarantine_detection_date ON quarantine(detection_date);
             CREATE INDEX IF NOT EXISTS idx_quarantine_original_path ON quarantine(original_path);
             CREATE TABLE IF NOT EXISTS quarantine_pending (
                 quarantine_path TEXT PRIMARY KEY,
                 original_path TEXT NOT NULL,
                 threat_name TEXT NOT NULL,
                 file_size INTEGER NOT NULL,
                 file_hash TEXT NOT NULL,
                 original_permissions INTEGER NOT NULL
             );",
        ).map_err(|error| format!("Unable to initialize quarantine database: {error}"))?;

        let mut has_permissions = false;
        let mut has_state = false;
        let mut statement = connection
            .prepare("PRAGMA table_info(quarantine)")
            .map_err(|error| error.to_string())?;
        let columns = statement
            .query_map([], |row| row.get::<_, String>(1))
            .map_err(|error| error.to_string())?;
        for column in columns {
            match column.map_err(|error| error.to_string())?.as_str() {
                "original_permissions" => has_permissions = true,
                "state" => has_state = true,
                _ => {}
            }
        }
        drop(statement);
        if !has_permissions {
            connection.execute_batch(
                "ALTER TABLE quarantine ADD COLUMN original_permissions INTEGER NOT NULL DEFAULT 420 CHECK (original_permissions BETWEEN 0 AND 511)",
            ).map_err(|error| format!("Unable to migrate quarantine permissions: {error}"))?;
        }
        if !has_state {
            connection.execute_batch(
                "ALTER TABLE quarantine ADD COLUMN state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'restored', 'deleted'))",
            ).map_err(|error| format!("Unable to migrate quarantine state: {error}"))?;
        }
        self.reconcile_pending(&mut connection)?;
        self.secure_database_files();
        *initialized = true;
        Ok(())
    }

    fn pin_database_file(&self) -> AppResult<()> {
        let file = open_path(
            &self.db_path,
            libc::O_RDWR | libc::O_CREAT | libc::O_NOFOLLOW,
            DB_MODE,
        )
        .map_err(|error| format!("Unable to securely create quarantine database: {error}"))?;
        let metadata = file.metadata().map_err(|error| error.to_string())?;
        if !metadata.is_file() {
            return Err("Quarantine database is not a regular file".into());
        }
        fchmod(file.as_raw_fd(), DB_MODE).map_err(|error| error.to_string())?;
        Ok(())
    }

    fn secure_database_files(&self) {
        let wal = sidecar_path(&self.db_path, b"-wal");
        let shm = sidecar_path(&self.db_path, b"-shm");
        for path in [&self.db_path, &wal, &shm] {
            if let Ok(file) = open_path(path, libc::O_RDONLY | libc::O_NOFOLLOW, 0) {
                let _ = fchmod(file.as_raw_fd(), DB_MODE);
            }
        }
    }

    fn connection(&self) -> AppResult<Connection> {
        let connection = Connection::open_with_flags(
            &self.db_path,
            OpenFlags::SQLITE_OPEN_READ_WRITE
                | OpenFlags::SQLITE_OPEN_CREATE
                | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .map_err(|error| format!("Unable to open quarantine database: {error}"))?;
        connection
            .busy_timeout(Duration::from_secs(30))
            .map_err(|error| error.to_string())?;
        connection
            .execute_batch("PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;")
            .map_err(|error| error.to_string())?;
        self.secure_database_files();
        Ok(connection)
    }

    fn quarantine(&self, ctx: &Context, source: &Path, threat_name: &str) -> OperationResult {
        let source_path = absolute_without_following(source);
        let moved = match self.move_to_quarantine(&source_path, threat_name) {
            Ok(moved) => moved,
            Err(error) => return file_error(ctx, &source_path, error),
        };
        let inserted = (|| -> AppResult<i64> {
            let mut connection = self.connection()?;
            let transaction = connection
                .transaction()
                .map_err(|error| error.to_string())?;
            transaction.execute(
                "INSERT INTO quarantine (original_path, quarantine_path, threat_name, detection_date, file_size, file_hash, original_permissions) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    source_path.as_os_str().as_bytes(),
                    &moved.destination.0,
                    threat_name,
                    now_iso(),
                    moved.file_size as i64,
                    &moved.file_hash,
                    (moved.original_permissions & 0o777) as i64,
                ],
            ).map_err(|error| error.to_string())?;
            let id = transaction.last_insert_rowid();
            transaction
                .execute(
                    "DELETE FROM quarantine_pending WHERE quarantine_path = ?1",
                    params![&moved.destination.0],
                )
                .map_err(|error| error.to_string())?;
            transaction.commit().map_err(|error| error.to_string())?;
            Ok(id)
        })();
        match inserted {
            Ok(id) => match self.get_entry(id) {
                Ok(Some(entry)) => OperationResult::success(entry),
                Ok(None) => OperationResult::failure(
                    Status::DatabaseError,
                    crate::i18n::translate(
                        ctx,
                        "Quarantine metadata was written but could not be read",
                    ),
                ),
                Err(error) => OperationResult::failure(Status::DatabaseError, error),
            },
            Err(_error) => {
                let rollback = self.restore_payload(
                    &moved.destination.as_path(),
                    &source_path,
                    moved.original_permissions,
                    &moved.file_hash,
                );
                let message = match rollback {
                    Ok(()) => {
                        if let Ok(connection) = self.connection() {
                            let _ = connection.execute(
                                "DELETE FROM quarantine_pending WHERE quarantine_path = ?1",
                                params![&moved.destination.0],
                            );
                        }
                        crate::i18n::translate(ctx, "Failed to record quarantine entry in database. File has been restored to original location.")
                    }
                    Err(rollback_error) => interpolate(
                        crate::i18n::translate(
                            ctx,
                            // Translators: Preserve `{error}` as a localized failure description and `{path}` as a user-provided file path.
                            "Failed to record quarantine entry in database. Rollback also failed: {error}. File may be orphaned at: {path}",
                        ),
                        &[
                            ("error", restore_error_message(ctx, &rollback_error)),
                            ("path", moved.destination.display()),
                        ],
                    ),
                };
                OperationResult::failure(Status::DatabaseError, message)
            }
        }
    }

    fn restore(&self, ctx: &Context, id: i64) -> OperationResult {
        let entry = match self.get_entry(id) {
            Ok(Some(entry)) => entry,
            Ok(None) => {
                return OperationResult::failure(
                    Status::EntryNotFound,
                    interpolate(
                        crate::i18n::translate(ctx, "Quarantine entry not found: {id}"),
                        &[("id", id.to_string())],
                    ),
                )
            }
            Err(error) => return OperationResult::failure(Status::DatabaseError, error),
        };
        let payload = entry.quarantine_path.as_path();
        if let Err(error) = self.validate_quarantine_path(&payload) {
            return OperationResult::with_entry(Status::Error, entry, error.to_string());
        }
        if let Err(error) = self.restore_payload(
            &payload,
            &entry.original_path.as_path(),
            entry.original_permissions,
            &entry.file_hash,
        ) {
            let status = restore_error_status(&error);
            return OperationResult::with_entry(status, entry, restore_error_message(ctx, &error));
        }
        match self.remove_entry(id) {
            Ok(true) => OperationResult::success(entry),
            Ok(false) | Err(_) => OperationResult::with_entry(
                Status::DatabaseError,
                entry,
                crate::i18n::translate(ctx, "File restored successfully, but the database entry could not be removed. It may still appear in the list until cleaned up."),
            ),
        }
    }

    fn delete(&self, ctx: &Context, id: i64) -> OperationResult {
        let entry = match self.get_entry(id) {
            Ok(Some(entry)) => entry,
            Ok(None) => {
                return OperationResult::failure(
                    Status::EntryNotFound,
                    interpolate(
                        crate::i18n::translate(ctx, "Quarantine entry not found: {id}"),
                        &[("id", id.to_string())],
                    ),
                )
            }
            Err(error) => return OperationResult::failure(Status::DatabaseError, error),
        };
        if let Err(error) = self.delete_payload(&entry.quarantine_path.as_path()) {
            return OperationResult::with_entry(file_status(&error), entry, error.to_string());
        }
        match self.remove_entry(id) {
            Ok(true) => OperationResult::success(entry),
            Ok(false) | Err(_) => OperationResult::with_entry(
                Status::DatabaseError,
                entry,
                crate::i18n::translate(ctx, "File deleted successfully, but the database entry could not be removed. It may still appear in the list until cleaned up."),
            ),
        }
    }

    fn list(&self) -> AppResult<Vec<QuarantineEntry>> {
        self.maybe_cleanup_orphans();
        let connection = self.connection()?;
        let mut statement = connection.prepare(
            "SELECT id, original_path, quarantine_path, threat_name, detection_date, file_size, file_hash, original_permissions FROM quarantine ORDER BY detection_date DESC",
        ).map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], entry_from_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    fn statistics(&self) -> AppResult<(u64, u64)> {
        let connection = self.connection()?;
        connection
            .query_row(
                "SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM quarantine",
                [],
                |row| Ok((row.get::<_, i64>(0)? as u64, row.get::<_, i64>(1)? as u64)),
            )
            .map_err(|error| error.to_string())
    }

    fn get_entry(&self, id: i64) -> AppResult<Option<QuarantineEntry>> {
        let connection = self.connection()?;
        let mut statement = connection.prepare(
            "SELECT id, original_path, quarantine_path, threat_name, detection_date, file_size, file_hash, original_permissions FROM quarantine WHERE id = ?1",
        ).map_err(|error| error.to_string())?;
        match statement.query_row([id], entry_from_row) {
            Ok(entry) => Ok(Some(entry)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(error) => Err(error.to_string()),
        }
    }

    fn remove_entry(&self, id: i64) -> AppResult<bool> {
        let connection = self.connection()?;
        Ok(connection
            .execute("DELETE FROM quarantine WHERE id = ?1", [id])
            .map_err(|error| error.to_string())?
            > 0)
    }

    fn reconcile_pending(&self, connection: &mut Connection) -> AppResult<()> {
        let mut statement = connection.prepare(
            "SELECT quarantine_path, original_path, threat_name, file_size, file_hash, original_permissions FROM quarantine_pending",
        ).map_err(|error| error.to_string())?;
        let pending = statement
            .query_map([], |row| {
                Ok((
                    RawPath(row.get::<_, Vec<u8>>(0)?),
                    RawPath(row.get::<_, Vec<u8>>(1)?),
                    row.get::<_, String>(2)?,
                    row.get::<_, i64>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, i64>(5)?,
                ))
            })
            .map_err(|error| error.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())?;
        drop(statement);
        for (payload, original, threat, size, hash, permissions) in pending {
            if !matches!(fs::symlink_metadata(original.as_path()), Err(error) if error.kind() == io::ErrorKind::NotFound)
            {
                continue;
            }
            if verify_hash(&payload.as_path(), &hash).is_err() {
                continue;
            }
            let transaction = connection
                .unchecked_transaction()
                .map_err(|error| error.to_string())?;
            transaction.execute(
                "INSERT OR IGNORE INTO quarantine (original_path, quarantine_path, threat_name, detection_date, file_size, file_hash, original_permissions) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![&original.0, &payload.0, threat, now_iso(), size, hash, permissions],
            ).map_err(|error| error.to_string())?;
            transaction
                .execute(
                    "DELETE FROM quarantine_pending WHERE quarantine_path = ?1",
                    params![&payload.0],
                )
                .map_err(|error| error.to_string())?;
            transaction.commit().map_err(|error| error.to_string())?;
        }
        Ok(())
    }

    fn add_pending(&self, source: &Path, moved: &FileMove, threat_name: &str) -> AppResult<()> {
        let connection = self.connection()?;
        connection.execute(
            "INSERT INTO quarantine_pending (quarantine_path, original_path, threat_name, file_size, file_hash, original_permissions) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![&moved.destination.0, source.as_os_str().as_bytes(), threat_name, moved.file_size as i64, &moved.file_hash, moved.original_permissions as i64],
        ).map_err(|error| error.to_string())?;
        Ok(())
    }

    fn move_to_quarantine(&self, source: &Path, threat_name: &str) -> Result<FileMove, io::Error> {
        self.ensure_quarantine_dir()?;
        let source_parent = pin_parent(source)?;
        let mut source_file = open_at(
            source_parent.directory.as_raw_fd(),
            &source_parent.name,
            libc::O_RDONLY | libc::O_NOFOLLOW,
            0,
        )?;
        let source_metadata = source_file.metadata()?;
        if !source_metadata.is_file() {
            return Err(io::Error::other("Source is not a regular file"));
        }
        let file_size = source_metadata.len();
        if available_space(&self.quarantine_dir)? < file_size.saturating_add(SPACE_RESERVE) {
            return Err(io::Error::from_raw_os_error(libc::ENOSPC));
        }
        let destination = self
            .quarantine_dir
            .join(OsString::from_vec(quarantine_name(source)));
        let destination_parent = pin_parent(&destination)?;
        let mut destination_file = open_at(
            destination_parent.directory.as_raw_fd(),
            &destination_parent.name,
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_NOFOLLOW,
            QUARANTINE_FILE_MODE,
        )?;
        let hash = match copy_hash_fsync(
            &mut source_file,
            &mut destination_file,
            QUARANTINE_FILE_MODE,
        ) {
            Ok(hash) => hash,
            Err(error) => {
                let _ = unlink_name(
                    destination_parent.directory.as_raw_fd(),
                    &destination_parent.name,
                );
                return Err(error);
            }
        };
        drop(destination_file);
        destination_parent.directory.sync_all()?;
        let moved = FileMove {
            destination: RawPath::from_path(&destination),
            file_size,
            file_hash: hash,
            original_permissions: source_metadata.mode() as u32 & 0o777,
        };
        if let Err(error) = self.add_pending(source, &moved, threat_name) {
            let _ = unlink_name(
                destination_parent.directory.as_raw_fd(),
                &destination_parent.name,
            );
            return Err(io::Error::other(error));
        }
        ensure_name_identity(&source_parent, &source_metadata)?;
        unlink_name(source_parent.directory.as_raw_fd(), &source_parent.name)?;
        source_parent.directory.sync_all()?;
        Ok(moved)
    }

    fn restore_payload(
        &self,
        payload: &Path,
        destination: &Path,
        permissions: u32,
        expected_hash: &str,
    ) -> Result<(), io::Error> {
        self.validate_quarantine_path(payload)?;
        let destination = absolute_without_following(destination);
        validate_restore_path(&destination)?;
        let payload_parent = pin_parent(payload)?;
        let mut source = open_at(
            payload_parent.directory.as_raw_fd(),
            &payload_parent.name,
            libc::O_RDONLY | libc::O_NOFOLLOW,
            0,
        )?;
        let source_metadata = source.metadata()?;
        if !source_metadata.is_file() {
            return Err(io::Error::other("Quarantined path is not a regular file"));
        }
        let (parent, name) = open_destination_parent(&destination)?;
        let mode = permissions & 0o777;
        let mut target = open_at(
            parent.as_raw_fd(),
            &name,
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_NOFOLLOW,
            mode,
        )?;
        let hash = match copy_hash_fsync(&mut source, &mut target, mode) {
            Ok(hash) => hash,
            Err(error) => {
                drop(target);
                let _ = unlink_name(parent.as_raw_fd(), &name);
                return Err(error);
            }
        };
        drop(target);
        if hash != expected_hash {
            let _ = unlink_name(parent.as_raw_fd(), &name);
            return Err(io::Error::other(HashMismatch));
        }
        parent.sync_all()?;
        ensure_name_identity(&payload_parent, &source_metadata)?;
        unlink_name(payload_parent.directory.as_raw_fd(), &payload_parent.name)?;
        payload_parent.directory.sync_all()
    }

    fn delete_payload(&self, payload: &Path) -> Result<(), io::Error> {
        self.validate_quarantine_path(payload)?;
        let parent = pin_parent(payload)?;
        let file = open_at(
            parent.directory.as_raw_fd(),
            &parent.name,
            libc::O_RDONLY | libc::O_NOFOLLOW,
            0,
        )?;
        let metadata = file.metadata()?;
        if !metadata.is_file() {
            return Err(io::Error::other("Quarantined path is not a regular file"));
        }
        fchmod(file.as_raw_fd(), 0)?;
        ensure_name_identity(&parent, &metadata)?;
        unlink_name(parent.directory.as_raw_fd(), &parent.name)?;
        parent.directory.sync_all()
    }

    fn validate_quarantine_path(&self, payload: &Path) -> Result<(), io::Error> {
        let root = self.quarantine_dir.canonicalize()?;
        let candidate = payload.canonicalize()?;
        if candidate.starts_with(&root) {
            Ok(())
        } else {
            Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "Path is not inside quarantine directory",
            ))
        }
    }

    fn cleanup_old(&self, days: i64) -> AppResult<u64> {
        let cutoff = unix_timestamp().saturating_sub(days.max(0) as u64 * 86_400);
        let connection = self.connection()?;
        let mut statement = connection.prepare(
            "SELECT id, original_path, quarantine_path, threat_name, detection_date, file_size, file_hash, original_permissions FROM quarantine WHERE replace(detection_date, 'T', ' ') < datetime(?1, 'unixepoch') ORDER BY detection_date ASC",
        ).map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([cutoff as i64], entry_from_row)
            .map_err(|error| error.to_string())?;
        let entries = rows
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())?;
        drop(statement);
        drop(connection);
        let mut removed = 0;
        for entry in entries {
            if self
                .delete_payload(&entry.quarantine_path.as_path())
                .is_ok()
                && self.remove_entry(entry.id)?
            {
                removed += 1;
            }
        }
        Ok(removed)
    }

    fn maybe_cleanup_orphans(&self) {
        let now = unix_timestamp();
        let previous = LAST_CLEANUP_CHECK.load(Ordering::Relaxed);
        if now.saturating_sub(previous) < CLEANUP_CHECK_THROTTLE.as_secs()
            || LAST_CLEANUP_CHECK
                .compare_exchange(previous, now, Ordering::Relaxed, Ordering::Relaxed)
                .is_err()
        {
            return;
        }
        let marker = self
            .db_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(".last_orphan_cleanup");
        let last_cleanup = fs::read_to_string(&marker)
            .ok()
            .and_then(|value| value.trim().parse::<u64>().ok())
            .unwrap_or(0);
        if now.saturating_sub(last_cleanup) < CLEANUP_INTERVAL.as_secs() {
            return;
        }
        if self.cleanup_orphans().is_ok() {
            let _ = write_marker(&marker, now);
        }
    }

    fn cleanup_orphans(&self) -> AppResult<u64> {
        // ENOENT does not establish that historical storage is available: an
        // unmounted quarantine volume presents the same way. Preserve metadata
        // until an explicit deletion has removed the pinned payload.
        Ok(0)
    }
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    let manager = QuarantineManager::from_context(ctx)?;
    match action {
        "quarantine" => {
            let path = path_from_wire(required_string(&args, "path")?)?;
            let threat_name = required_string(&args, "threat_name")?;
            Ok(manager.quarantine(ctx, &path, threat_name).into_json())
        }
        "restore" => Ok(manager.restore(ctx, required_id(&args)?).into_json()),
        "delete" => Ok(manager.delete(ctx, required_id(&args)?).into_json()),
        "list" => {
            let entries = manager.list()?;
            let (entry_count, total_size) = manager.statistics()?;
            Ok(json!({
                "entries": entries.into_iter().map(|entry| entry.to_json()).collect::<Vec<_>>(),
                "total_size": total_size,
                "entry_count": entry_count,
            }))
        }
        "statistics" => {
            let (entry_count, total_size) = manager.statistics()?;
            Ok(json!({"entry_count": entry_count, "total_size": total_size}))
        }
        "cleanup" => {
            let days = args.get("days").and_then(Value::as_i64).unwrap_or(30);
            if days < 0 {
                return Err("quarantine.cleanup days must be non-negative".into());
            }
            Ok(json!({"removed": manager.cleanup_old(days)?}))
        }
        _ => Err(format!("Unknown quarantine action: {action}")),
    }
}

fn required_string<'a>(args: &'a Value, key: &str) -> AppResult<&'a str> {
    args.get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("quarantine.{key} must be a non-empty string"))
}

fn required_id(args: &Value) -> AppResult<i64> {
    args.get("id")
        .and_then(Value::as_i64)
        .filter(|id| *id > 0)
        .ok_or_else(|| "quarantine id must be a positive integer".into())
}

fn entry_from_row(row: &Row<'_>) -> rusqlite::Result<QuarantineEntry> {
    Ok(QuarantineEntry {
        id: row.get(0)?,
        original_path: RawPath(value_bytes(row, 1)?),
        quarantine_path: RawPath(value_bytes(row, 2)?),
        threat_name: row.get(3)?,
        detection_date: row.get(4)?,
        file_size: row.get::<_, i64>(5)?.max(0) as u64,
        file_hash: row.get(6)?,
        original_permissions: (row.get::<_, Option<i64>>(7)?.unwrap_or(0o644) as u32) & 0o777,
    })
}

fn value_bytes(row: &Row<'_>, index: usize) -> rusqlite::Result<Vec<u8>> {
    match row.get_ref(index)? {
        ValueRef::Blob(value) | ValueRef::Text(value) => Ok(value.to_vec()),
        _ => Err(rusqlite::Error::FromSqlConversionFailure(
            index,
            rusqlite::types::Type::Blob,
            io::Error::other("quarantine path is neither BLOB nor TEXT").into(),
        )),
    }
}

fn open_path(path: &Path, flags: libc::c_int, mode: u32) -> io::Result<File> {
    let path = CString::new(path.as_os_str().as_bytes())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "path contains a NUL byte"))?;
    let fd = unsafe { libc::open(path.as_ptr(), flags, mode as libc::mode_t) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { File::from_raw_fd(fd) })
}

fn fchmod(fd: libc::c_int, mode: u32) -> io::Result<()> {
    if unsafe { libc::fchmod(fd, mode as libc::mode_t) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

fn open_at(
    directory_fd: libc::c_int,
    name: &CStr,
    flags: libc::c_int,
    mode: u32,
) -> io::Result<File> {
    let fd = unsafe { libc::openat(directory_fd, name.as_ptr(), flags, mode as libc::mode_t) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { File::from_raw_fd(fd) })
}

fn unlink_name(directory_fd: libc::c_int, name: &CStr) -> io::Result<()> {
    if unsafe { libc::unlinkat(directory_fd, name.as_ptr(), 0) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

struct PinnedParent {
    directory: File,
    name: CString,
}

fn pin_parent(path: &Path) -> io::Result<PinnedParent> {
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "path has no parent"))?;
    let directory = open_path(
        parent,
        libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW,
        0,
    )?;
    let name = CString::new(
        path.file_name()
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "path has no file name"))?
            .as_bytes(),
    )
    .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "path contains a NUL byte"))?;
    Ok(PinnedParent { directory, name })
}

fn ensure_name_identity(parent: &PinnedParent, pinned: &fs::Metadata) -> io::Result<()> {
    let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
    if unsafe {
        libc::fstatat(
            parent.directory.as_raw_fd(),
            parent.name.as_ptr(),
            stat.as_mut_ptr(),
            libc::AT_SYMLINK_NOFOLLOW,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    let stat = unsafe { stat.assume_init() };
    if stat.st_dev == pinned.dev() as libc::dev_t && stat.st_ino == pinned.ino() as libc::ino_t {
        Ok(())
    } else {
        Err(io::Error::other(
            "File was replaced during operation; refusing to unlink it",
        ))
    }
}

fn open_destination_parent(destination: &Path) -> io::Result<(File, CString)> {
    if !destination.is_absolute() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Restore destination must be absolute",
        ));
    }
    let mut directory = open_path(
        Path::new("/"),
        libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW,
        0,
    )?;
    let components = destination
        .components()
        .filter_map(|component| match component {
            Component::Normal(component) => Some(component),
            _ => None,
        })
        .collect::<Vec<_>>();
    let (leaf, parents) = components.split_last().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "Restore destination has no file name",
        )
    })?;
    for part in parents {
        let part = CString::new(part.as_bytes())
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "path contains a NUL byte"))?;
        let child = match open_at(
            directory.as_raw_fd(),
            &part,
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW,
            0,
        ) {
            Ok(child) => child,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                if unsafe { libc::mkdirat(directory.as_raw_fd(), part.as_ptr(), 0o777) } != 0 {
                    return Err(io::Error::last_os_error());
                }
                open_at(
                    directory.as_raw_fd(),
                    &part,
                    libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW,
                    0,
                )?
            }
            Err(error) => return Err(error),
        };
        directory = child;
    }
    let leaf = CString::new(leaf.as_bytes())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "path contains a NUL byte"))?;
    Ok((directory, leaf))
}

fn copy_hash_fsync(source: &mut File, destination: &mut File, mode: u32) -> io::Result<String> {
    let mut hash = Sha256::new();
    let mut buffer = [0_u8; BUFFER_SIZE];
    loop {
        let read = source.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
        destination.write_all(&buffer[..read])?;
    }
    destination.sync_all()?;
    fchmod(destination.as_raw_fd(), mode)?;
    Ok(format!("{:x}", hash.finalize()))
}

fn verify_hash(path: &Path, expected: &str) -> io::Result<()> {
    let mut file = open_path(path, libc::O_RDONLY | libc::O_NOFOLLOW, 0)?;
    if !file.metadata()?.is_file() {
        return Err(io::Error::other("Quarantined path is not a regular file"));
    }
    let actual = copy_hash(&mut file)?;
    if actual == expected {
        Ok(())
    } else {
        Err(io::Error::other(HashMismatch))
    }
}

fn copy_hash(file: &mut File) -> io::Result<String> {
    let mut hash = Sha256::new();
    let mut buffer = [0_u8; BUFFER_SIZE];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn quarantine_name(source: &Path) -> Vec<u8> {
    let mut random = [0_u8; 8];
    if File::open("/dev/urandom")
        .and_then(|mut file| file.read_exact(&mut random))
        .is_err()
    {
        random = unix_timestamp().to_le_bytes();
    }
    let mut result = hex::encode(random).into_bytes();
    result.push(b'_');
    result.extend_from_slice(
        source
            .file_name()
            .unwrap_or_else(|| OsStr::new("payload"))
            .as_bytes(),
    );
    result
}

fn available_space(path: &Path) -> io::Result<u64> {
    let path = CString::new(path.as_os_str().as_bytes())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "path contains a NUL byte"))?;
    let mut stats = std::mem::MaybeUninit::<libc::statvfs>::zeroed();
    if unsafe { libc::statvfs(path.as_ptr(), stats.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let stats = unsafe { stats.assume_init() };
    Ok(stats.f_bavail.saturating_mul(stats.f_frsize))
}

fn absolute_without_following(path: &Path) -> PathBuf {
    if path.is_absolute() {
        lexical_normalize(path)
    } else {
        lexical_normalize(
            &std::env::current_dir()
                .unwrap_or_else(|_| PathBuf::from("/"))
                .join(path),
        )
    }
}

fn lexical_normalize(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::RootDir => normalized.push(Path::new("/")),
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            Component::Normal(value) => normalized.push(value),
            Component::Prefix(_) => {}
        }
    }
    normalized
}

fn validate_restore_path(path: &Path) -> io::Result<()> {
    let bytes = path.as_os_str().as_bytes();
    if bytes.is_empty() || bytes.iter().any(|byte| matches!(byte, b'\n' | b'\r' | 0)) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Invalid restore path",
        ));
    }
    let absolute = absolute_without_following(path);
    let protected = [
        "/etc", "/var", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/boot", "/root", "/sys",
        "/proc",
    ];
    if protected.iter().any(|root| absolute.starts_with(root)) {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "Restore to protected system directory not allowed",
        ));
    }
    let mut current = PathBuf::from("/");
    for component in absolute.components() {
        if let Component::Normal(part) = component {
            current.push(part);
            if let Ok(metadata) = fs::symlink_metadata(&current) {
                if metadata.file_type().is_symlink() {
                    let target = current.canonicalize()?;
                    if protected.iter().any(|root| target.starts_with(root)) {
                        return Err(io::Error::new(
                            io::ErrorKind::PermissionDenied,
                            "Restore path contains symlink to protected directory",
                        ));
                    }
                }
            }
        }
    }
    Ok(())
}

fn sidecar_path(db_path: &Path, suffix: &[u8]) -> PathBuf {
    let mut raw = db_path.as_os_str().as_bytes().to_vec();
    raw.extend_from_slice(suffix);
    PathBuf::from(OsString::from_vec(raw))
}

fn unix_timestamp() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn write_marker(path: &Path, timestamp: u64) -> io::Result<()> {
    let mut options = OpenOptions::new();
    options
        .write(true)
        .create(true)
        .truncate(true)
        .mode(DB_MODE)
        .custom_flags(libc::O_NOFOLLOW);
    let mut file = options.open(path)?;
    file.write_all(timestamp.to_string().as_bytes())?;
    file.sync_all()?;
    fchmod(file.as_raw_fd(), DB_MODE)
}

fn file_error(ctx: &Context, path: &Path, error: io::Error) -> OperationResult {
    OperationResult::failure(
        file_status(&error),
        interpolate(
            crate::i18n::translate(
                ctx,
                // Translators: Preserve `{path}` as a user-provided file path and `{error}` as the filesystem diagnostic.
                "Cannot quarantine {path}: {error}",
            ),
            &[
                ("path", path.display().to_string()),
                ("error", error.to_string()),
            ],
        ),
    )
}

fn restore_error_message(ctx: &Context, error: &io::Error) -> String {
    if error
        .get_ref()
        .is_some_and(|cause| cause.is::<HashMismatch>())
    {
        crate::i18n::translate(
            ctx,
            // Translators: The em dash separates the integrity failure from its consequence.
            "File hash mismatch — file may be corrupted",
        )
    } else {
        error.to_string()
    }
}

fn interpolate(message: String, values: &[(&str, String)]) -> String {
    values.iter().fold(message, |rendered, (key, value)| {
        rendered.replace(&format!("{{{key}}}"), value)
    })
}

fn file_status(error: &io::Error) -> Status {
    match error.raw_os_error() {
        Some(libc::ENOENT) => Status::FileNotFound,
        Some(libc::EACCES) | Some(libc::EPERM) => Status::PermissionDenied,
        Some(libc::ENOSPC) => Status::DiskFull,
        _ => Status::Error,
    }
}

fn restore_error_status(error: &io::Error) -> Status {
    match error.raw_os_error() {
        Some(libc::EEXIST) => Status::RestoreDestinationExists,
        Some(libc::ELOOP) => Status::InvalidRestorePath,
        _ if matches!(
            error.kind(),
            io::ErrorKind::InvalidInput | io::ErrorKind::PermissionDenied
        ) && error.to_string().to_ascii_lowercase().contains("restore") =>
        {
            Status::InvalidRestorePath
        }
        _ => file_status(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    #[test]
    fn pinned_payload_parent_cannot_be_redirected_before_unlink() {
        let root = tempfile::tempdir().unwrap();
        let mutable_ancestor = root.path().join("a/swap");
        let payload = mutable_ancestor.join("quarantine/payload");
        let victim_root = root.path().join("victim/quarantine");
        fs::create_dir_all(payload.parent().unwrap()).unwrap();
        fs::create_dir_all(&victim_root).unwrap();
        fs::write(&payload, b"quarantine payload").unwrap();
        let victim = victim_root.join("payload");
        fs::write(&victim, b"must not be deleted").unwrap();

        let parent = pin_parent(&payload).unwrap();
        let payload_file = open_at(
            parent.directory.as_raw_fd(),
            &parent.name,
            libc::O_RDONLY | libc::O_NOFOLLOW,
            0,
        )
        .unwrap();
        let metadata = payload_file.metadata().unwrap();
        let moved_ancestor = root.path().join("a/swap-original");
        fs::rename(&mutable_ancestor, &moved_ancestor).unwrap();
        symlink(root.path().join("victim"), &mutable_ancestor).unwrap();

        ensure_name_identity(&parent, &metadata).unwrap();
        unlink_name(parent.directory.as_raw_fd(), &parent.name).unwrap();
        assert!(!moved_ancestor.join("quarantine/payload").exists());
        assert_eq!(fs::read(victim).unwrap(), b"must not be deleted");
    }
}
