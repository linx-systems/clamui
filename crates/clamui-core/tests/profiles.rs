use clamui_core::common::{Context, Paths};
use clamui_core::profiles::dispatch;
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use uuid::Uuid;

struct TestContext {
    root: PathBuf,
    context: Context,
}

impl TestContext {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!("clamui-profiles-{}", Uuid::new_v4()));
        let paths = Paths {
            home: root.join("home"),
            config_dir: root.join("config"),
            data_dir: root.join("data"),
        };
        fs::create_dir_all(&paths.config_dir).unwrap();
        Self {
            context: Context::with_paths(paths).unwrap(),
            root,
        }
    }

    fn profiles_path(&self) -> PathBuf {
        self.root.join("config/profiles.json")
    }
}

impl Drop for TestContext {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn profiles(context: &Context) -> Vec<Value> {
    dispatch(context, "list", json!({})).unwrap()["profiles"]
        .as_array()
        .unwrap()
        .clone()
}

#[test]
fn normalizes_legacy_descriptions_without_exposing_open_fields() {
    let test = TestContext::new();
    fs::write(
        test.profiles_path(),
        serde_json::to_vec_pretty(&json!([{
            "id": "legacy-profile-id",
            "name": "Legacy",
            "targets": ["~/Documents"],
            "exclusions": {"patterns": ["*.tmp"]},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-02T00:00:00+00:00",
            "description": 37,
            "options": {"recursive": false, "engine_extension": {"depth": 3}},
            "future_field": {"kept": true}
        }]))
        .unwrap(),
    )
    .unwrap();

    let legacy = profiles(&test.context)
        .into_iter()
        .find(|profile| profile["id"] == "legacy-profile-id")
        .unwrap();
    assert_eq!(legacy["name"], "Legacy");
    assert_eq!(legacy["description"], "37");
    assert_eq!(legacy["options"]["engine_extension"]["depth"], 3);
    assert!(legacy.get("future_field").is_none());

    let saved: Value = serde_json::from_slice(&fs::read(test.profiles_path()).unwrap()).unwrap();
    let saved_legacy = saved["profiles"]
        .as_array()
        .unwrap()
        .iter()
        .find(|profile| profile["id"] == "legacy-profile-id")
        .unwrap();
    assert_eq!(saved["version"], 1);
    assert_eq!(saved_legacy["description"], "37");
    assert_eq!(saved_legacy["future_field"]["kept"], true);
}

#[test]
fn corrupt_storage_is_backed_up_before_safe_defaults_are_written() {
    let test = TestContext::new();
    fs::write(test.profiles_path(), b"{not-json").unwrap();

    let loaded = profiles(&test.context);
    assert!(loaded.iter().any(|profile| profile["name"] == "Quick Scan"));
    assert_eq!(
        fs::read(test.root.join("config/profiles.json.corrupted")).unwrap(),
        b"{not-json"
    );

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(test.profiles_path())
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }
}

#[test]
fn exported_profile_imports_with_a_new_id_unique_name_and_full_options() {
    let test = TestContext::new();
    let created = dispatch(
        &test.context,
        "create",
        json!({
            "name": "Portable",
            "targets": ["~/Downloads"],
            "exclusions": {"paths": ["~/Downloads/cache"], "patterns": ["*.part"]},
            "description": "Transfer profile",
            "options": {"recursive": true, "max_depth": 7},
            "future_field": ["preserve", 1]
        }),
    )
    .unwrap();
    let export = dispatch(&test.context, "export", json!({"id": created["id"]})).unwrap();
    let exported: Value = serde_json::from_str(export["content"].as_str().unwrap()).unwrap();
    assert_eq!(exported["export_version"], 1);
    assert!(exported["profile"].get("future_field").is_none());

    let import_path = test.root.join("portable.json");
    fs::write(&import_path, export["content"].as_str().unwrap()).unwrap();
    let imported = dispatch(&test.context, "import", json!({"path": import_path})).unwrap();

    assert_ne!(imported["id"], created["id"]);
    assert_eq!(imported["name"], "Portable (2)");
    assert_eq!(imported["is_default"], false);
    assert_eq!(imported["options"], created["options"]);
}

#[test]
fn export_reimport_collision_uses_a_bounded_unique_name() {
    let test = TestContext::new();
    let name = "P".repeat(50);
    let created = dispatch(
        &test.context,
        "create",
        json!({"name": name, "targets": ["~/Documents"], "exclusions": {}, "options": {"recursive": true}}),
    )
    .unwrap();
    let exported = dispatch(&test.context, "export", json!({"id": created["id"]})).unwrap();
    let import_path = test.root.join("collision.json");
    fs::write(&import_path, exported["content"].as_str().unwrap()).unwrap();

    let imported = dispatch(&test.context, "import", json!({"path": import_path})).unwrap();
    let expected_name = format!("{} (2)", "P".repeat(46));
    assert_ne!(imported["id"], created["id"]);
    assert_eq!(imported["name"].as_str(), Some(expected_name.as_str()));
    assert_eq!(imported["name"].as_str().unwrap().chars().count(), 50);
    assert_eq!(imported["options"], created["options"]);
}

#[test]
fn imports_raw_legacy_profile_without_requiring_obsolete_identity_fields() {
    let test = TestContext::new();
    let import_path = test.root.join("raw-profile.json");
    fs::write(
        &import_path,
        serde_json::to_vec(&json!({
            "name": "Raw Import",
            "targets": ["~/Documents"],
            "exclusions": {"patterns": ["*.bak"]},
            "description": "Legacy portable profile",
            "options": {"recursive": true},
            "extension_field": {"still": "present"}
        }))
        .unwrap(),
    )
    .unwrap();

    let imported = dispatch(&test.context, "import", json!({"path": import_path})).unwrap();
    assert_eq!(imported["name"], "Raw Import");
    assert!(Uuid::parse_str(imported["id"].as_str().unwrap()).is_ok());
    assert_eq!(imported["options"]["recursive"], true);
    assert!(imported.get("extension_field").is_none());

    let saved: Value = serde_json::from_slice(&fs::read(test.profiles_path()).unwrap()).unwrap();
    assert!(saved["profiles"].as_array().unwrap().iter().any(|profile| {
        profile["id"] == imported["id"] && profile["extension_field"]["still"] == "present"
    }));
}

#[test]
fn imports_versioned_numeric_descriptions_and_keeps_duplicate_names_unique() {
    let test = TestContext::new();
    let import_path = test.root.join("numeric-profile.json");
    fs::write(
        &import_path,
        serde_json::to_vec(&json!({
            "export_version": 1,
            "profile": {
                "name": "Numeric import parity",
                "targets": ["/tmp"],
                "exclusions": {},
                "description": 37,
                "options": {"recursive": true}
            }
        }))
        .unwrap(),
    )
    .unwrap();

    let imported = dispatch(&test.context, "import", json!({"path": &import_path})).unwrap();
    let duplicate = dispatch(&test.context, "import", json!({"path": &import_path})).unwrap();
    assert_eq!(imported["description"], "37");
    assert_eq!(duplicate["name"], "Numeric import parity (2)");
    assert_eq!(duplicate["description"], "37");
}

#[test]
fn profile_transfer_paths_keep_a_literal_tilde() {
    let test = TestContext::new();
    let created = dispatch(
        &test.context,
        "create",
        json!({"name": "Literal path", "targets": ["/tmp"]}),
    )
    .unwrap();
    let literal_directory = PathBuf::from("~").join(format!("clamui-profile-{}", Uuid::new_v4()));
    let literal_path = literal_directory.join("profile.json");
    let literal_path_string = literal_path.to_string_lossy().into_owned();

    let exported = dispatch(
        &test.context,
        "export",
        json!({"id": created["id"], "path": &literal_path_string}),
    )
    .unwrap();
    assert_eq!(exported["path"], literal_path_string);
    assert!(literal_path.exists());
    if let Some(home) = std::env::var_os("HOME") {
        let expanded_path = PathBuf::from(home)
            .join(literal_directory.strip_prefix("~").unwrap())
            .join("profile.json");
        assert!(!expanded_path.exists());
    }

    let imported = dispatch(
        &test.context,
        "import",
        json!({"path": &literal_path_string}),
    )
    .unwrap();
    assert_eq!(imported["name"], "Literal path (2)");
    fs::remove_dir_all(literal_directory).unwrap();
}

#[test]
fn default_profiles_are_editable_but_cannot_be_renamed_or_deleted() {
    let test = TestContext::new();
    let quick = profiles(&test.context)
        .into_iter()
        .find(|profile| profile["name"] == "Quick Scan")
        .unwrap();
    let id = quick["id"].clone();

    let changed = dispatch(
        &test.context,
        "update",
        json!({"id": id.clone(), "description": "A local quick scan", "options": {"recursive": false}}),
    )
    .unwrap();
    assert_eq!(changed["description"], "A local quick scan");
    assert_eq!(changed["options"]["recursive"], false);
    assert!(dispatch(
        &test.context,
        "update",
        json!({"id": id.clone(), "name": "Renamed"})
    )
    .is_err());
    assert!(dispatch(&test.context, "delete", json!({"id": id})).is_err());
}
