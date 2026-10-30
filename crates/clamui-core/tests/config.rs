use clamui_core::common::{Context, Paths};
use clamui_core::config::dispatch;
use serde_json::json;
use std::fs;
use std::path::PathBuf;
use uuid::Uuid;

struct TestContext {
    root: PathBuf,
    context: Context,
}

impl TestContext {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!("clamui-config-{}", Uuid::new_v4()));
        let paths = Paths {
            home: root.join("home"),
            config_dir: root.join("config/clamui"),
            data_dir: root.join("data/clamui"),
        };
        Self {
            context: Context::with_paths(paths).expect("context"),
            root,
        }
    }

    fn config(&self, name: &str) -> PathBuf {
        self.root.join(name)
    }
}

impl Drop for TestContext {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn load_and_save_retain_comments_order_and_repeated_directives() {
    let fixture = TestContext::new();
    let path = fixture.config("freshclam.conf");
    fs::create_dir_all(&fixture.root).expect("root");
    fs::write(
        &path,
        "# Keep this comment\nFutureClamavOption existing\nDatabaseMirror first.example\n\nDatabaseMirror second.example\nChecks 12\n",
    )
    .expect("config fixture");

    let loaded = dispatch(
        &fixture.context,
        "load",
        json!({"kind": "freshclam", "path": path}),
    )
    .expect("load");
    assert_eq!(
        loaded["values"]["DatabaseMirror"],
        json!(["first.example", "second.example"])
    );
    assert_eq!(loaded["values"]["FutureClamavOption"], json!(["existing"]));

    let saved = dispatch(
        &fixture.context,
        "save",
        json!({
            "configs": [{
                "kind": "freshclam",
                "path": path,
                "values": {
                    "FutureClamavOption": ["retained"],
                    "DatabaseMirror": ["first.example", "replacement.example"],
                    "Checks": ["24"]
                }
            }]
        }),
    )
    .expect("save");
    assert_eq!(saved["status"], "applied");
    assert_eq!(saved["config_paths"]["changed"], true);
    assert_eq!(saved["config_paths"]["durable"], true);
    assert_eq!(
        saved["config_paths"]["durable_keys"],
        json!(["freshclam_conf_path"])
    );
    assert_eq!(
        fs::read_to_string(path).expect("saved document"),
        "# Keep this comment\nFutureClamavOption retained\nDatabaseMirror first.example\n\nDatabaseMirror replacement.example\nChecks 24\n"
    );
}

#[test]
fn load_uses_latin1_fallback_without_losing_directive_values() {
    let fixture = TestContext::new();
    let path = fixture.config("latin1.conf");
    fs::create_dir_all(&fixture.root).expect("root");
    fs::write(&path, b"Banner \xff\n").expect("latin1 fixture");

    let loaded = dispatch(
        &fixture.context,
        "load",
        json!({"kind": "freshclam", "path": path}),
    )
    .expect("load");
    assert_eq!(loaded["encoding"], "latin-1");
    assert_eq!(loaded["values"]["Banner"], json!(["ÿ"]));
}

#[test]
fn clamd_size_unit_repair_is_reported_and_persisted_by_explicit_apply() {
    let fixture = TestContext::new();
    let path = fixture.config("clamd.conf");
    fs::create_dir_all(&fixture.root).expect("root");
    let original = "# Retain this comment\nFutureClamavOption retained\nMaxFileSize 10\nMaxScanSize 25\nOnAccessMaxFileSize 0\n";
    fs::write(&path, original).expect("config fixture");
    fixture
        .context
        .update_settings(json!({"clamd_size_limit_unit_migration_done": true}))
        .expect("seed obsolete migration flag");

    let loaded = dispatch(
        &fixture.context,
        "load",
        json!({"kind": "clamd", "path": path}),
    )
    .expect("load");

    assert_eq!(loaded["needs_size_unit_migration"], true);
    assert_eq!(loaded["values"]["MaxFileSize"], json!(["10M"]));
    assert_eq!(loaded["values"]["MaxScanSize"], json!(["25M"]));
    assert_eq!(loaded["values"]["OnAccessMaxFileSize"], json!(["0"]));
    assert_eq!(
        fs::read_to_string(&path).expect("load does not modify configuration"),
        original
    );

    let applied = dispatch(
        &fixture.context,
        "apply",
        json!({
            "configs": [{
                "kind": "clamd",
                "path": path,
                "values": loaded["values"]
            }]
        }),
    )
    .expect("explicit apply");
    assert_eq!(applied["status"], "applied");
    assert_eq!(applied["configs"][0]["changed"], true);
    assert_eq!(applied["configs"][0]["written"], true);
    assert_eq!(
        fs::read_to_string(&path).expect("repaired configuration"),
        "# Retain this comment\nFutureClamavOption retained\nMaxFileSize 10M\nMaxScanSize 25M\nOnAccessMaxFileSize 0\n"
    );

    let reloaded = dispatch(
        &fixture.context,
        "load",
        json!({"kind": "clamd", "path": path}),
    )
    .expect("reload");
    assert_eq!(reloaded["needs_size_unit_migration"], false);
}

#[test]
fn clamd_load_marks_only_positive_bare_size_limits_for_repair() {
    let fixture = TestContext::new();
    let normalized_path = fixture.config("normalized.conf");
    let unreadable_path = fixture.config("directory.conf");
    let missing_path = fixture.config("missing.conf");
    fs::create_dir_all(&fixture.root).expect("root");
    fs::write(
        &normalized_path,
        "MaxFileSize 0\nMaxScanSize 10K\nOnAccessMaxFileSize invalid\n",
    )
    .expect("normalized config fixture");
    fs::create_dir(&unreadable_path).expect("unreadable config fixture");

    let normalized = dispatch(
        &fixture.context,
        "load",
        json!({"kind": "clamd", "path": normalized_path}),
    )
    .expect("normalized load");
    assert_eq!(normalized["needs_size_unit_migration"], false);
    assert_eq!(normalized["values"]["MaxFileSize"], json!(["0"]));
    assert_eq!(normalized["values"]["MaxScanSize"], json!(["10K"]));
    assert_eq!(
        normalized["values"]["OnAccessMaxFileSize"],
        json!(["invalid"])
    );

    for path in [unreadable_path, missing_path] {
        let loaded = dispatch(
            &fixture.context,
            "load",
            json!({"kind": "clamd", "path": path}),
        )
        .expect("unreadable or missing load response");
        assert_eq!(loaded["readable"], false);
        assert_eq!(loaded["needs_size_unit_migration"], false);
    }
}

#[test]
fn validation_accepts_unknown_directives_and_rejects_isolated_invalid_inputs() {
    let fixture = TestContext::new();
    let accepted = dispatch(
        &fixture.context,
        "validate",
        json!({
            "kind": "clamd",
            "values": {
                "FutureClamavOption": ["retained"],
                "MaxRecursion": ["100"],
                "OnAccessIncludePath": ["/home/alice"],
                "OnAccessExcludeRootUID": ["yes"]
            }
        }),
    )
    .expect("accepted validation response");
    assert_eq!(accepted["valid"], true);
    assert_eq!(accepted["errors"], json!([]));

    let invalid_limit = dispatch(
        &fixture.context,
        "validate",
        json!({"kind": "clamd", "values": {"MaxRecursion": ["101"]}}),
    )
    .expect("limit validation response");
    assert_eq!(invalid_limit["valid"], false);
    assert!(!invalid_limit["errors"]
        .as_array()
        .expect("limit errors")
        .is_empty());

    let invalid_onaccess = dispatch(
        &fixture.context,
        "validate",
        json!({
            "kind": "clamd",
            "values": {
                "OnAccessIncludePath": ["/home/alice"],
                "OnAccessExcludeRootUID": ["no"]
            }
        }),
    )
    .expect("on-access validation response");
    assert_eq!(invalid_onaccess["valid"], false);
    assert!(!invalid_onaccess["errors"]
        .as_array()
        .expect("on-access errors")
        .is_empty());
}

#[test]
fn invalid_schedule_preflight_prevents_config_and_path_persistence() {
    let fixture = TestContext::new();
    let path = fixture.config("freshclam.conf");
    fs::create_dir_all(&fixture.root).expect("root");
    fs::write(&path, "Checks 12\n").expect("config fixture");
    fixture
        .context
        .update_settings(json!({
            "scheduled_scans_enabled": true,
            "schedule_frequency": "weekly",
            "schedule_time": "11:11",
            "schedule_targets": ["/existing-target"],
            "schedule_skip_on_battery": false,
            "schedule_auto_quarantine": true,
            "schedule_day_of_week": 3,
            "schedule_day_of_month": 17,
        }))
        .expect("seed existing schedule");
    let settings_before = fixture
        .context
        .settings()
        .expect("settings before rejection");

    let error = dispatch(
        &fixture.context,
        "apply",
        json!({
            "configs": [{
                "kind": "freshclam",
                "path": path,
                "values": {"Checks": ["24"]}
            }],
            "schedule": {
                "enabled": true,
                "frequency": "daily",
                "time": "02:00",
                "targets": ["/safe\ninjected"],
                "skip_on_battery": true,
                "auto_quarantine": false,
                "day_of_week": 0,
                "day_of_month": 1
            }
        }),
    )
    .expect_err("invalid schedule must fail before config persistence");

    assert!(error.contains("Invalid path contains newline characters"));
    assert!(
        !fs::read_dir(&fixture.root)
            .expect("config directory")
            .any(|entry| entry
                .expect("directory entry")
                .file_name()
                .to_string_lossy()
                .contains(".bak.")),
        "invalid schedule must not create a configuration backup",
    );
    assert_eq!(
        fs::read_to_string(&path).expect("original config"),
        "Checks 12\n"
    );
    let settings_after = fixture
        .context
        .settings()
        .expect("settings after rejection");
    assert_eq!(
        settings_after["freshclam_conf_path"], settings_before["freshclam_conf_path"],
        "invalid schedule must not persist the config path",
    );
    assert_eq!(
        settings_after, settings_before,
        "invalid schedule must not change persisted preferences",
    );
}

#[test]
fn invalid_proposal_does_not_switch_selected_config_path() {
    let fixture = TestContext::new();
    let path = fixture.config("freshclam.conf");
    fs::create_dir_all(&fixture.root).expect("root");
    fs::write(&path, "Checks 12\n").expect("config fixture");

    let error = dispatch(
        &fixture.context,
        "save",
        json!({
            "configs": [{
                "kind": "freshclam",
                "path": path,
                "values": {"Checks": ["51"]}
            }]
        }),
    )
    .expect_err("invalid update must fail before write");
    assert!(error.contains("Checks"));
    assert_eq!(
        fixture.context.settings().expect("settings")["freshclam_conf_path"],
        ""
    );
}
