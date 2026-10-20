use clamui_core::{scanner, Context, Paths};
use serde_json::json;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::{LazyLock, Mutex};
use tempfile::TempDir;

fn fixture_context() -> (TempDir, Context) {
    let temp = tempfile::tempdir().expect("temporary workspace");
    let paths = Paths {
        home: temp.path().join("home"),
        config_dir: temp.path().join("config/clamui"),
        data_dir: temp.path().join("data/clamui"),
    };
    fs::create_dir_all(&paths.home).expect("home");
    let context = Context::with_paths(paths).expect("context");
    (temp, context)
}

#[test]
fn infection_wins_over_exit_two_and_preserves_warning_evidence() {
    let result = clamui_core::scan_parser::interpret_clamscan(
        "/scan",
        "/scan/eicar: Eicar-Test-Signature FOUND\n/root/locked: Failed to open file ERROR\nScanned files: 1\n",
        "",
        2,
        0,
    );
    assert_eq!(result.status, scanner::ScanStatus::Infected);
    assert_eq!(result.threat_details[0].category, "Test");
    assert_eq!(result.threat_details[0].severity, "low");
    assert_eq!(result.skipped_files, vec!["/root/locked"]);
}

#[test]
fn daemon_zero_precount_is_unknown_but_clamscan_zero_summary_is_all_failed() {
    let transcript = "WARNING: /scan/gone: Can't access file\nScanned files: 0\n";
    let daemon = clamui_core::scan_parser::interpret_daemon("/scan", transcript, "", 2, 0, 0);
    let standalone = clamui_core::scan_parser::interpret_clamscan("/scan", transcript, "", 2, 0);
    assert_eq!(daemon.status, scanner::ScanStatus::Clean);
    assert_eq!(standalone.status, scanner::ScanStatus::Error);
    assert_eq!(
        standalone.error_message.as_deref(),
        Some("No files could be scanned")
    );
}

#[test]
fn nonfatal_limit_warning_does_not_hide_a_real_error() {
    let result = clamui_core::scan_parser::interpret_clamscan(
        "/scan",
        "Scanned files: 4\n",
        "LibClamAV Warning: cli_scanxz: file size exceeds limits\nERROR: unable to initialize engine\n",
        2,
        0,
    );
    assert_eq!(result.status, scanner::ScanStatus::Error);
    assert_eq!(result.nonfatal_warnings.len(), 1);
    assert_eq!(result.error_message.as_deref(), Some("LibClamAV Warning: cli_scanxz: file size exceeds limits\nERROR: unable to initialize engine"));
}

#[test]
fn classifier_preserves_priority_and_all_user_visible_severity_levels() {
    for (name, category, severity) in [
        ("Trojan.Ransomware.Locky", "Trojan", "critical"),
        ("Ransomware.Trojan.Locky", "Ransomware", "critical"),
        ("Win.Trojan.Agent", "Trojan", "high"),
        ("PUA.Win.Adware.Generic", "Adware", "medium"),
        ("Eicar-Test-Signature", "Test", "low"),
        ("Unknown.Signature", "Virus", "medium"),
    ] {
        assert_eq!(clamui_core::threat::categorize(Some(name)), category);
        assert_eq!(
            clamui_core::threat::classify_severity(Some(name)).as_str(),
            severity
        );
    }
}

#[test]
fn scanner_process_fixture_drains_stderr_and_keeps_found_output() {
    static ENV_LOCK: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));
    let _environment = ENV_LOCK.lock().expect("environment lock");
    let (temp, context) = fixture_context();
    let bin = temp.path().join("bin");
    fs::create_dir_all(&bin).expect("bin directory");
    let executable = bin.join("clamscan");
    fs::write(
        &executable,
        "#!/bin/sh\ni=1\nwhile [ \"$i\" -le 4096 ]; do printf 'diagnostic %s\\n' \"$i\" >&2; i=$((i + 1)); done\nfor last; do :; done\nprintf 'Scanning %s\\n' \"$last\"\nprintf '%s: Eicar-Test-Signature FOUND\\n' \"$last\"\nprintf 'Scanned files: 1\\nInfected files: 1\\n'\nexit 2\n",
    ).expect("fixture scanner");
    fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).expect("fixture mode");
    let target = temp.path().join("target file");
    fs::write(&target, b"fixture").expect("target");
    context
        .update_settings(json!({"scan_backend": "clamscan"}))
        .expect("settings");

    let old_path = std::env::var_os("PATH");
    let mut paths = vec![bin.clone()];
    paths.extend(std::env::split_paths(&old_path.clone().unwrap_or_default()));
    std::env::set_var("PATH", std::env::join_paths(paths).expect("joined path"));
    let result = scanner::dispatch(
        &context,
        "scan",
        json!({"id": "fixture-scan", "paths": [target], "recursive": false}),
    );
    if let Some(path) = old_path {
        std::env::set_var("PATH", path);
    } else {
        std::env::remove_var("PATH");
    }

    let result = result.expect("scan result");
    assert_eq!(result["status"], "infected");
    assert_eq!(result["infected_count"], 1);
    assert!(result["stderr"]
        .as_str()
        .expect("stderr")
        .contains("diagnostic 4096"));
    assert_eq!(
        result["per_target_results"][0]["threat_details"][0]["file_path"],
        target.to_string_lossy().as_ref()
    );
}

#[test]
fn hard_warnings_keep_exit_two_scans_in_error() {
    let result = clamui_core::scan_parser::interpret_clamscan(
        "/scan",
        "WARNING: database metadata could not be read\nTotal errors: 1\nScanned files: 4\n",
        "",
        2,
        0,
    );
    assert_eq!(result.status, scanner::ScanStatus::Error);
    assert_eq!(
        result.error_message.as_deref(),
        Some("WARNING: database metadata could not be read")
    );
}

#[test]
fn benign_exit_two_evidence_downgrades_to_clean() {
    let result = clamui_core::scan_parser::interpret_clamscan(
        "/scan",
        "WARNING: /scan/gone: Can't access file\nScanned files: 4\n",
        "",
        2,
        0,
    );
    assert_eq!(result.status, scanner::ScanStatus::Clean);
}

#[test]
fn home_target_is_expanded_after_lossless_wire_decoding() {
    let (_temp, context) = fixture_context();
    fs::create_dir_all(context.paths.home.join("Downloads")).expect("downloads");
    context
        .update_settings(json!({"scan_backend": "daemon"}))
        .expect("settings");

    let result = scanner::dispatch(
        &context,
        "scan",
        json!({"paths": ["~", "file:~/Downloads"]}),
    )
    .expect("expanded home targets");

    assert_eq!(result["status"], "clean");
    assert_eq!(result["per_target_results"][0]["status"], "clean");
    assert_eq!(result["per_target_results"][1]["status"], "clean");
}

#[test]
fn directly_selected_daemon_file_respects_pattern_exclusions() {
    let (temp, context) = fixture_context();
    let target = temp.path().join("target.txt");
    fs::write(&target, b"fixture").expect("target");
    context
        .update_settings(json!({"scan_backend": "daemon"}))
        .expect("settings");

    let result = scanner::dispatch(
        &context,
        "scan",
        json!({
            "paths": [target],
            "exclusions": [{"type": "pattern", "pattern": "target[.]txt", "enabled": true}],
        }),
    )
    .expect("excluded direct target");

    assert_eq!(result["status"], "clean");
    assert_eq!(result["scanned_files"], 0);
}
