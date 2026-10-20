use clamui_core::common::{Context, Paths};
use clamui_core::quarantine::dispatch;
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::os::unix::fs::{symlink, PermissionsExt};
use std::path::{Path, PathBuf};
use tempfile::TempDir;

struct TestContext {
    root: TempDir,
    context: Context,
}

impl TestContext {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let home = root.path().join("home");
        let config_dir = root.path().join("config/clamui");
        let data_dir = root.path().join("data/clamui");
        fs::create_dir_all(&home).unwrap();
        Self {
            context: Context::with_paths(Paths {
                home,
                config_dir,
                data_dir,
            })
            .unwrap(),
            root,
        }
    }

    fn data_dir(&self) -> PathBuf {
        self.root.path().join("data/clamui")
    }

    fn quarantine_dir(&self) -> PathBuf {
        self.data_dir().join("quarantine")
    }
}

fn quarantine(context: &Context, path: &Path) -> Value {
    dispatch(
        context,
        "quarantine",
        json!({"path": path.to_string_lossy(), "threat_name": "Test.Signature"}),
    )
    .unwrap()
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[test]
fn quarantines_and_restores_with_hash_permissions_and_secure_payload_modes() {
    let test = TestContext::new();
    let source = test.root.path().join("infected.bin");
    fs::write(&source, b"malicious bytes").unwrap();
    fs::set_permissions(&source, fs::Permissions::from_mode(0o755)).unwrap();

    let quarantined = quarantine(&test.context, &source);
    assert_eq!(quarantined["status"], "success");
    assert!(!source.exists());
    let entry = quarantined["entry"].clone();
    let payload = PathBuf::from(entry["quarantine_path"].as_str().unwrap());
    assert_eq!(fs::read(&payload).unwrap(), b"malicious bytes");
    assert_eq!(
        fs::metadata(&payload).unwrap().permissions().mode() & 0o777,
        0o400
    );
    assert_eq!(
        fs::metadata(test.quarantine_dir())
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700
    );

    let restored = dispatch(&test.context, "restore", json!({"id": entry["id"]})).unwrap();
    assert_eq!(restored["status"], "success");
    assert_eq!(fs::read(&source).unwrap(), b"malicious bytes");
    assert_eq!(
        fs::metadata(&source).unwrap().permissions().mode() & 0o777,
        0o755
    );
    assert!(!payload.exists());
    assert_eq!(
        dispatch(&test.context, "list", json!({})).unwrap()["entry_count"],
        0
    );
}

#[test]
fn restores_legacy_blob_paths_and_in_place_schema_without_path_conversion() {
    let test = TestContext::new();
    let quarantine_dir = test.quarantine_dir();
    fs::create_dir_all(&quarantine_dir).unwrap();
    let original = test
        .root
        .path()
        .join(std::ffi::OsString::from_vec(b"restored-\xff.bin".to_vec()));
    let payload = quarantine_dir.join("legacy-payload.bin");
    let bytes = b"legacy bytes";
    fs::write(&payload, bytes).unwrap();
    fs::set_permissions(&payload, fs::Permissions::from_mode(0o400)).unwrap();

    let database = test.data_dir().join("quarantine.db");
    fs::create_dir_all(database.parent().unwrap()).unwrap();
    let connection = Connection::open(&database).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE quarantine (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_path TEXT NOT NULL,
            quarantine_path TEXT NOT NULL UNIQUE,
            threat_name TEXT NOT NULL,
            detection_date TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_hash TEXT NOT NULL
        );",
        )
        .unwrap();
    connection.execute(
        "INSERT INTO quarantine (original_path, quarantine_path, threat_name, detection_date, file_size, file_hash) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![
            original.as_os_str().as_bytes(),
            payload.to_string_lossy().to_string(),
            "Legacy.Signature",
            "2000-01-01T00:00:00",
            bytes.len() as i64,
            sha256(bytes),
        ],
    ).unwrap();
    drop(connection);

    let restored = dispatch(&test.context, "restore", json!({"id": 1})).unwrap();
    assert_eq!(restored["status"], "success");
    assert_eq!(fs::read(&original).unwrap(), bytes);
    assert_eq!(
        original.file_name().unwrap().as_bytes(),
        b"restored-\xff.bin"
    );
    assert!(!payload.exists());

    let connection = Connection::open(database).unwrap();
    let columns = connection
        .prepare("PRAGMA table_info(quarantine)")
        .unwrap()
        .query_map([], |row| row.get::<_, String>(1))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert!(columns
        .iter()
        .any(|column| column == "original_permissions"));
    assert!(columns.iter().any(|column| column == "state"));
}

#[test]
fn hash_tampering_blocks_restore_and_preserves_the_payload() {
    let test = TestContext::new();
    let source = test.root.path().join("infected.bin");
    fs::write(&source, b"original payload").unwrap();
    let quarantined = quarantine(&test.context, &source);
    let entry = &quarantined["entry"];
    let payload = PathBuf::from(entry["quarantine_path"].as_str().unwrap());
    fs::set_permissions(&payload, fs::Permissions::from_mode(0o600)).unwrap();
    fs::write(&payload, b"tampered payload").unwrap();

    let restored = dispatch(&test.context, "restore", json!({"id": entry["id"]})).unwrap();
    assert_eq!(restored["status"], "error");
    assert!(!source.exists());
    assert_eq!(fs::read(&payload).unwrap(), b"tampered payload");
    let listed = dispatch(&test.context, "list", json!({})).unwrap();
    assert_eq!(listed["entry_count"], 1);
    assert_eq!(listed["entries"][0]["id"], entry["id"]);
}

#[test]
fn restore_never_overwrites_an_existing_file_or_destination_symlink() {
    let test = TestContext::new();
    let source = test.root.path().join("infected.bin");
    let victim = test.root.path().join("victim.txt");
    fs::write(&source, b"quarantined payload").unwrap();
    fs::write(&victim, b"do not touch").unwrap();
    let quarantined = quarantine(&test.context, &source);
    let entry = &quarantined["entry"];
    let payload = PathBuf::from(entry["quarantine_path"].as_str().unwrap());

    symlink(&victim, &source).unwrap();
    let restored = dispatch(&test.context, "restore", json!({"id": entry["id"]})).unwrap();
    assert_eq!(restored["status"], "restore_destination_exists");
    assert_eq!(fs::read(&victim).unwrap(), b"do not touch");
    assert!(payload.exists());
}

#[test]
fn rejects_source_symlinks_without_touching_their_targets() {
    let test = TestContext::new();
    let target = test.root.path().join("target.bin");
    let link = test.root.path().join("infected-link.bin");
    fs::write(&target, b"target bytes").unwrap();
    symlink(&target, &link).unwrap();

    let result = quarantine(&test.context, &link);
    assert_eq!(result["status"], "error");
    assert_eq!(fs::read(&target).unwrap(), b"target bytes");
    assert!(link.symlink_metadata().unwrap().file_type().is_symlink());
}

#[test]
fn cleanup_removes_only_old_payloads_that_are_really_gone() {
    let test = TestContext::new();
    let source = test.root.path().join("old.bin");
    fs::write(&source, b"old payload").unwrap();
    let result = quarantine(&test.context, &source);
    let id = result["entry"]["id"].as_i64().unwrap();
    let payload = PathBuf::from(result["entry"]["quarantine_path"].as_str().unwrap());
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    connection
        .execute(
            "UPDATE quarantine SET detection_date = '2000-01-01T00:00:00' WHERE id = ?1",
            [id],
        )
        .unwrap();
    drop(connection);

    assert_eq!(
        dispatch(&test.context, "cleanup", json!({"days": 30})).unwrap()["removed"],
        1
    );
    assert!(!payload.exists());
    assert_eq!(
        dispatch(&test.context, "statistics", json!({})).unwrap()["entry_count"],
        0
    );
}

#[test]
fn restore_masks_tampered_permission_bits_before_creating_the_destination() {
    let test = TestContext::new();
    let source = test.root.path().join("permission-mask.bin");
    fs::write(&source, b"payload").unwrap();
    let quarantined = quarantine(&test.context, &source);
    let id = quarantined["entry"]["id"].as_i64().unwrap();
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    connection
        .execute_batch("PRAGMA ignore_check_constraints=ON")
        .unwrap();
    connection
        .execute(
            "UPDATE quarantine SET original_permissions = 3565 WHERE id = ?1",
            [id],
        )
        .unwrap();
    drop(connection);

    let restored = dispatch(&test.context, "restore", json!({"id": id})).unwrap();
    assert_eq!(restored["status"], "success");
    assert_eq!(
        fs::metadata(source).unwrap().permissions().mode() & 0o7777,
        0o755
    );
}

#[test]
fn startup_reconciles_durable_pending_intent_only_when_original_is_confirmed_missing() {
    let test = TestContext::new();
    let original = test.root.path().join("lost-before-finalize.bin");
    let payload = test.quarantine_dir().join("pending-payload");
    fs::create_dir_all(test.quarantine_dir()).unwrap();
    let bytes = b"pending payload";
    fs::write(&payload, bytes).unwrap();
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    connection.execute_batch(
        "CREATE TABLE quarantine_pending (
             quarantine_path TEXT PRIMARY KEY, original_path TEXT NOT NULL, threat_name TEXT NOT NULL,
             file_size INTEGER NOT NULL, file_hash TEXT NOT NULL, original_permissions INTEGER NOT NULL
         )",
    ).unwrap();
    connection
        .execute(
            "INSERT INTO quarantine_pending VALUES (?1, ?2, 'Crash.Test', ?3, ?4, 420)",
            params![
                payload.as_os_str().as_bytes(),
                original.as_os_str().as_bytes(),
                bytes.len() as i64,
                sha256(bytes)
            ],
        )
        .unwrap();
    drop(connection);

    let listed = dispatch(&test.context, "list", json!({})).unwrap();
    let expected_payload = payload.to_string_lossy().into_owned();
    assert_eq!(listed["entry_count"], 1);
    assert_eq!(
        listed["entries"][0]["quarantine_path"].as_str(),
        Some(expected_payload.as_str())
    );
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    assert_eq!(
        connection
            .query_row("SELECT COUNT(*) FROM quarantine_pending", [], |row| row
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}

#[test]
fn startup_preserves_pending_payload_when_an_original_replacement_exists() {
    let test = TestContext::new();
    let original = test.root.path().join("replacement.bin");
    let payload = test.quarantine_dir().join("pending-replacement");
    fs::create_dir_all(test.quarantine_dir()).unwrap();
    fs::write(&original, b"replacement").unwrap();
    let bytes = b"pending payload";
    fs::write(&payload, bytes).unwrap();
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    connection.execute_batch(
        "CREATE TABLE quarantine_pending (
             quarantine_path TEXT PRIMARY KEY, original_path TEXT NOT NULL, threat_name TEXT NOT NULL,
             file_size INTEGER NOT NULL, file_hash TEXT NOT NULL, original_permissions INTEGER NOT NULL
         )",
    ).unwrap();
    connection
        .execute(
            "INSERT INTO quarantine_pending VALUES (?1, ?2, 'Crash.Test', ?3, ?4, 420)",
            params![
                payload.as_os_str().as_bytes(),
                original.as_os_str().as_bytes(),
                bytes.len() as i64,
                sha256(bytes)
            ],
        )
        .unwrap();
    drop(connection);

    assert_eq!(
        dispatch(&test.context, "list", json!({})).unwrap()["entry_count"],
        0
    );
    assert_eq!(fs::read(&original).unwrap(), b"replacement");
    assert_eq!(fs::read(&payload).unwrap(), bytes);
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    assert_eq!(
        connection
            .query_row("SELECT COUNT(*) FROM quarantine_pending", [], |row| row
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
}

#[test]
fn cleanup_preserves_metadata_when_the_payload_root_is_unavailable() {
    let test = TestContext::new();
    let source = test.root.path().join("unavailable-root.bin");
    fs::write(&source, b"payload").unwrap();
    let quarantined = quarantine(&test.context, &source);
    let id = quarantined["entry"]["id"].as_i64().unwrap();
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    connection.execute(
        "UPDATE quarantine SET quarantine_path = ?1, detection_date = '2000-01-01T00:00:00' WHERE id = ?2",
        params![b"/proc/clamui-unavailable-payload".as_slice(), id],
    ).unwrap();
    drop(connection);

    assert_eq!(
        dispatch(&test.context, "cleanup", json!({"days": 30})).unwrap()["removed"],
        0
    );
    assert_eq!(
        dispatch(&test.context, "statistics", json!({})).unwrap()["entry_count"],
        1
    );
}

#[test]
fn passive_listing_preserves_an_entry_for_a_missing_historical_quarantine_root() {
    let test = TestContext::new();
    let source = test.root.path().join("historical-root.bin");
    fs::write(&source, b"payload").unwrap();
    let quarantined = quarantine(&test.context, &source);
    let id = quarantined["entry"]["id"].as_i64().unwrap();
    let unavailable_root = test.root.path().join("detached-volume/quarantine");
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    connection
        .execute(
            "UPDATE quarantine SET quarantine_path = ?1 WHERE id = ?2",
            params![
                unavailable_root
                    .join("historical-payload")
                    .as_os_str()
                    .as_bytes(),
                id
            ],
        )
        .unwrap();
    drop(connection);

    let listed = dispatch(&test.context, "list", json!({})).unwrap();
    assert_eq!(listed["entry_count"], 1);
    assert_eq!(listed["entries"][0]["id"], id);
}

#[test]
fn startup_preserves_an_unverified_pending_payload_for_manual_recovery() {
    let test = TestContext::new();
    let original = test.root.path().join("missing-original.bin");
    let payload = test.quarantine_dir().join("unverified-pending");
    fs::create_dir_all(test.quarantine_dir()).unwrap();
    fs::write(&payload, b"payload changed after crash").unwrap();
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    connection.execute_batch(
        "CREATE TABLE quarantine_pending (
             quarantine_path TEXT PRIMARY KEY, original_path TEXT NOT NULL, threat_name TEXT NOT NULL,
             file_size INTEGER NOT NULL, file_hash TEXT NOT NULL, original_permissions INTEGER NOT NULL
         )",
    ).unwrap();
    connection.execute(
        "INSERT INTO quarantine_pending VALUES (?1, ?2, 'Crash.Test', 1, 'not-a-valid-hash', 420)",
        params![payload.as_os_str().as_bytes(), original.as_os_str().as_bytes()],
    ).unwrap();
    drop(connection);

    assert_eq!(
        dispatch(&test.context, "list", json!({})).unwrap()["entry_count"],
        0
    );
    assert!(payload.exists());
    let connection = Connection::open(test.data_dir().join("quarantine.db")).unwrap();
    assert_eq!(
        connection
            .query_row("SELECT COUNT(*) FROM quarantine_pending", [], |row| row
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
}
