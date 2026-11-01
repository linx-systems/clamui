use clamui_core::{scanner, Context, Event, Paths};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::ffi::OsString;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::{Arc, LazyLock, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};
use tempfile::TempDir;

static ENV_LOCK: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));

fn environment_lock() -> MutexGuard<'static, ()> {
    ENV_LOCK
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

struct EnvironmentGuard {
    saved: Vec<(OsString, Option<OsString>)>,
}

impl EnvironmentGuard {
    fn set(&mut self, key: &str, value: impl Into<OsString>) {
        let key = OsString::from(key);
        if !self.saved.iter().any(|(saved, _)| saved == &key) {
            self.saved.push((key.clone(), std::env::var_os(&key)));
        }
        std::env::set_var(&key, value.into());
    }
}

impl Drop for EnvironmentGuard {
    fn drop(&mut self) {
        for (key, value) in self.saved.drain(..).rev() {
            if let Some(value) = value {
                std::env::set_var(key, value);
            } else {
                std::env::remove_var(key);
            }
        }
    }
}

fn prepend_fixture_path(bin: &std::path::Path) -> EnvironmentGuard {
    let mut environment = EnvironmentGuard { saved: Vec::new() };
    let old_path = std::env::var_os("PATH");
    let mut paths = vec![bin.to_path_buf()];
    paths.extend(std::env::split_paths(&old_path.unwrap_or_default()));
    environment.set(
        "PATH",
        std::env::join_paths(paths).expect("joined fixture path"),
    );
    environment
}

fn install_daemon_fixture(temp: &TempDir) -> EnvironmentGuard {
    let bin = temp.path().join("bin");
    fs::create_dir_all(&bin).expect("bin directory");
    let executable = bin.join("clamdscan");
    fs::write(
        &executable,
        r#"#!/bin/sh
for argument in "$@"; do
    case "$argument" in
        --version) printf 'ClamAV fixture\n'; exit 0 ;;
        --ping) printf 'PONG\n'; exit 0 ;;
    esac
done

file_list=
stream=0
previous=
for argument; do
    if [ "$previous" = "--file-list" ]; then
        file_list=$argument
    fi
    if [ "$argument" = "--stream" ]; then
        stream=1
    fi
    previous=$argument
done

infected=0
errors=0
scanned=0
scan_file() {
    file=$1
    if [ ! -r "$file" ]; then
        printf '%s: Failed to open file ERROR\n' "$file"
        errors=$((errors + 1))
    elif grep -q INFECTED -- "$file"; then
        printf '%s: Fixture.Signature FOUND\n' "$file"
        infected=$((infected + 1))
    else
        printf '%s: OK\n' "$file"
    fi
    scanned=$((scanned + 1))
}

if [ -n "$file_list" ]; then
    while IFS= read -r file || [ -n "$file" ]; do
        scan_file "$file"
    done < "$file_list"
    if [ -n "${CLAMUI_FIXTURE_REPLACE_PATH:-}" ]; then
        rm -f -- "$CLAMUI_FIXTURE_REPLACE_PATH"
        mkfifo -- "$CLAMUI_FIXTURE_REPLACE_PATH"
    fi
else
    if [ -n "${CLAMUI_FIXTURE_REQUIRE_STREAM:-}" ] && [ "$stream" -ne 1 ]; then
        printf 'fixture requires stream mode\n' >&2
        exit 2
    fi
    if [ -n "${CLAMUI_FIXTURE_READY:-}" ]; then
        printf 'started\n' >> "$CLAMUI_FIXTURE_READY"
    fi
    if [ -n "${CLAMUI_FIXTURE_BLOCK:-}" ]; then
        while :; do sleep 1; done
    fi
    if grep -q INFECTED; then
        if [ "$stream" -eq 1 ]; then label=stream; else label=fd[0]; fi
        printf '%s: Fixture.Signature FOUND\n' "$label"
        infected=1
    else
        if [ "$stream" -eq 1 ]; then label=stream; else label=fd[0]; fi
        printf '%s: OK\n' "$label"
    fi
    scanned=1
fi

printf 'Scanned files: %s\nInfected files: %s\n' "$scanned" "$infected"
if [ "$errors" -gt 0 ]; then exit 2; fi
if [ "$infected" -gt 0 ]; then exit 1; fi
exit 0
"#,
    )
    .expect("daemon fixture scanner");
    fs::set_permissions(&executable, fs::Permissions::from_mode(0o700))
        .expect("daemon fixture mode");
    prepend_fixture_path(&bin)
}

fn scan_progress(events: &[Event]) -> Vec<&Value> {
    events
        .iter()
        .filter(|event| event.event == "scan-progress")
        .map(|event| &event.data)
        .collect()
}

fn progress_paths(events: &[Event]) -> BTreeSet<String> {
    scan_progress(events)
        .into_iter()
        .filter_map(|event| event["current_file"].as_str().map(str::to_owned))
        .collect()
}

fn wait_for_path(path: &std::path::Path) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !path.exists() {
        assert!(Instant::now() < deadline, "fixture did not become ready");
        thread::sleep(Duration::from_millis(10));
    }
}

fn disabled_default_exclusions() -> Value {
    json!([
        {"pattern": "node_modules", "type": "directory", "enabled": false},
        {"pattern": ".git", "type": "directory", "enabled": false},
        {"pattern": ".venv", "type": "directory", "enabled": false},
        {"pattern": "build", "type": "directory", "enabled": false},
        {"pattern": "dist", "type": "directory", "enabled": false},
        {"pattern": "__pycache__", "type": "directory", "enabled": false}
    ])
}

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
    let _environment = environment_lock();
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

    let _path = prepend_fixture_path(&bin);
    let result = scanner::dispatch(
        &context,
        "scan",
        json!({"id": "fixture-scan", "paths": [target], "recursive": false}),
    );

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

#[test]
fn daemon_crlf_paths_merge_file_list_and_stdin_results_losslessly() {
    let _environment = environment_lock();
    let (temp, context) = fixture_context();
    let events = Arc::new(Mutex::new(Vec::<Event>::new()));
    let captured_events = Arc::clone(&events);
    let context = context.with_emitter(move |event| {
        captured_events.lock().expect("event lock").push(event);
    });
    let target = temp.path().join("scan");
    fs::create_dir_all(&target).expect("scan directory");
    let clean = target.join("clean.txt");
    let infected = target.join("infected.txt");
    let excluded = target.join("ignored.infected");
    let carriage_return = target.join("carriage\rinfected.txt");
    let fake_found = target.join("fake: Fake.Signature FOUND\nrest.txt");
    fs::write(&clean, b"clean").expect("clean target");
    fs::write(&infected, b"INFECTED").expect("infected target");
    fs::write(&excluded, b"INFECTED").expect("excluded target");
    fs::write(&carriage_return, b"INFECTED").expect("carriage-return target");
    fs::write(&fake_found, b"clean").expect("fake-found target");
    context
        .update_settings(json!({
            "scan_backend": "daemon",
            "exclusion_patterns": disabled_default_exclusions(),
        }))
        .expect("settings");
    let _path = install_daemon_fixture(&temp);

    let result = scanner::dispatch(
        &context,
        "scan",
        json!({
            "id": "daemon-crlf-batch-and-stdin",
            "paths": [target],
            "exclusions": [{"type": "pattern", "pattern": "*.infected", "enabled": true}],
        }),
    )
    .expect("daemon scan result");

    let expected_threats = BTreeSet::from([
        infected.to_string_lossy().into_owned(),
        carriage_return.to_string_lossy().into_owned(),
    ]);
    let actual_threats = result["threat_details"]
        .as_array()
        .expect("threat details")
        .iter()
        .map(|threat| {
            threat["file_path"]
                .as_str()
                .expect("threat path")
                .to_owned()
        })
        .collect::<BTreeSet<_>>();
    assert_eq!(result["status"], "infected");
    assert_eq!(result["scanned_files"], 4);
    assert_eq!(result["infected_count"], 2);
    assert_eq!(actual_threats, expected_threats);
    assert!(!result["threat_details"]
        .as_array()
        .expect("threat details")
        .iter()
        .any(|threat| threat["threat_name"] == "Fake.Signature"));

    let events = events.lock().expect("event lock");
    let progress = scan_progress(&events);
    assert_eq!(progress.len(), 4);
    assert_eq!(
        progress
            .iter()
            .map(|event| event["files_scanned"].as_u64().expect("progress count"))
            .collect::<Vec<_>>(),
        vec![1, 2, 3, 4]
    );
    assert!(progress
        .iter()
        .all(|event| event["files_total"] == 4 && event["total_files"] == 4));
    assert_eq!(
        progress_paths(&events),
        BTreeSet::from([
            clean.to_string_lossy().into_owned(),
            infected.to_string_lossy().into_owned(),
            carriage_return.to_string_lossy().into_owned(),
            fake_found.to_string_lossy().into_owned(),
        ])
    );
    assert!(progress.iter().all(|event| {
        let path = event["current_file"].as_str().expect("progress path");
        !path.starts_with("fd[") && path != "stream"
    }));
}

#[test]
fn daemon_crlf_all_unsafe_stream_paths_keep_original_progress_identity() {
    let _environment = environment_lock();
    let (temp, context) = fixture_context();
    let events = Arc::new(Mutex::new(Vec::<Event>::new()));
    let captured_events = Arc::clone(&events);
    let context = context.with_emitter(move |event| {
        captured_events.lock().expect("event lock").push(event);
    });
    let target = temp.path().join("scan");
    fs::create_dir_all(&target).expect("scan directory");
    let clean = target.join("clean\rfile");
    let infected = target.join("infected\nfile");
    fs::write(&clean, b"clean").expect("clean target");
    fs::write(&infected, b"INFECTED").expect("infected target");
    context
        .update_settings(json!({
            "scan_backend": "daemon",
            "exclusion_patterns": disabled_default_exclusions(),
        }))
        .expect("settings");
    let mut environment = install_daemon_fixture(&temp);
    environment.set("CLAMUI_FIXTURE_REQUIRE_STREAM", "1");

    let result = scanner::dispatch(
        &context,
        "scan",
        json!({
            "id": "daemon-crlf-stream",
            "paths": [target],
            "force_stream": true,
        }),
    )
    .expect("stream scan result");

    assert_eq!(result["status"], "infected");
    assert_eq!(result["scanned_files"], 2);
    assert_eq!(result["scanned_dirs"], 1);
    assert_eq!(result["infected_count"], 1);
    assert_eq!(
        result["threat_details"][0]["file_path"],
        infected.to_string_lossy().as_ref()
    );

    let events = events.lock().expect("event lock");
    let progress = scan_progress(&events);
    assert_eq!(progress.len(), 2);
    assert_eq!(
        progress
            .iter()
            .map(|event| event["files_scanned"].as_u64().expect("progress count"))
            .collect::<Vec<_>>(),
        vec![1, 2]
    );
    assert!(progress
        .iter()
        .all(|event| event["files_total"] == 2 && event["total_files"] == 2));
    assert_eq!(
        progress_paths(&events),
        BTreeSet::from([
            clean.to_string_lossy().into_owned(),
            infected.to_string_lossy().into_owned(),
        ])
    );
}

#[test]
fn daemon_crlf_open_failure_retains_partial_results_and_original_path() {
    let _environment = environment_lock();
    let (temp, context) = fixture_context();
    let target = temp.path().join("scan");
    fs::create_dir_all(&target).expect("scan directory");
    let safe = target.join("safe.txt");
    let failed = target.join("replaced\rfifo");
    let infected = target.join("infected\nsibling");
    fs::write(&safe, b"clean").expect("safe target");
    fs::write(&failed, b"clean").expect("replaceable target");
    fs::write(&infected, b"INFECTED").expect("infected target");
    context
        .update_settings(json!({
            "scan_backend": "daemon",
            "exclusion_patterns": disabled_default_exclusions(),
        }))
        .expect("settings");
    let mut environment = install_daemon_fixture(&temp);
    environment.set(
        "CLAMUI_FIXTURE_REPLACE_PATH",
        failed.as_os_str().to_os_string(),
    );

    let result = scanner::dispatch(
        &context,
        "scan",
        json!({"id": "daemon-crlf-open-failure", "paths": [target]}),
    )
    .expect("partial daemon scan result");

    assert_eq!(result["status"], "infected");
    assert_eq!(result["scanned_files"], 2);
    assert_eq!(result["infected_count"], 1);
    assert_eq!(
        result["threat_details"][0]["file_path"],
        infected.to_string_lossy().as_ref()
    );
    assert!(result["error_message"]
        .as_str()
        .is_some_and(|message| !message.is_empty()));
    assert_eq!(result["skipped_count"], 1);
    assert_eq!(
        result["skipped_files"],
        json!([failed.to_string_lossy().as_ref()])
    );
}

#[test]
fn daemon_crlf_stdin_scan_cancels_before_later_unsafe_files() {
    let _environment = environment_lock();
    let (temp, context) = fixture_context();
    let target = temp.path().join("blocked-target");
    let batched = target.join("batched.txt");
    let first = target.join("first\nfile");
    let later = target.join("later\rfile");
    let independent = temp.path().join("independent.txt");
    let target_wire = target.to_string_lossy().into_owned();
    let batched_wire = batched.to_string_lossy().into_owned();
    fs::create_dir_all(&target).expect("blocked directory");
    fs::write(&batched, b"INFECTED").expect("batched target");
    fs::write(&first, b"clean").expect("first target");
    fs::write(&later, b"INFECTED").expect("later target");
    fs::write(&independent, b"INFECTED").expect("independent target");
    context
        .update_settings(json!({
            "scan_backend": "daemon",
            "exclusion_patterns": disabled_default_exclusions(),
        }))
        .expect("settings");
    let mut environment = install_daemon_fixture(&temp);
    let ready = temp.path().join("fixture-ready");
    environment.set("CLAMUI_FIXTURE_READY", ready.as_os_str().to_os_string());
    environment.set("CLAMUI_FIXTURE_BLOCK", "1");

    let scan_context = context.clone();
    let scan = thread::spawn(move || {
        scanner::dispatch(
            &scan_context,
            "scan",
            json!({
                "id": "daemon-crlf-cancel",
                "paths": [target, independent],
            }),
        )
    });
    wait_for_path(&ready);
    assert_eq!(
        scanner::dispatch(&context, "cancel", json!({"id": "daemon-crlf-cancel"}),)
            .expect("cancel result")["cancelled"],
        true
    );
    let result = scan
        .join()
        .expect("scan worker")
        .expect("cancelled scan result");
    assert_eq!(
        fs::read_to_string(&ready).expect("fixture invocation record"),
        "started\n"
    );

    assert_eq!(result["status"], "cancelled");
    assert_eq!(result["scanned_files"], 1);
    assert_eq!(result["infected_count"], 1);
    assert_eq!(result["per_target_results"][0]["path"], target_wire);
    assert_eq!(result["per_target_results"][0]["status"], "cancelled");
    assert_eq!(result["per_target_results"][0]["infected_count"], 1);
    assert_eq!(
        result["per_target_results"][0]["threat_details"],
        json!([{
            "file_path": batched_wire,
            "threat_name": "Fixture.Signature",
            "category": "Virus",
            "severity": "medium",
        }])
    );
    assert_eq!(result["per_target_results"][1]["status"], "cancelled");
}

#[test]
fn daemon_crlf_rejects_invalid_nul_wire_target() {
    let (_temp, context) = fixture_context();
    context
        .update_settings(json!({"scan_backend": "daemon"}))
        .expect("settings");

    let result = scanner::dispatch(
        &context,
        "scan",
        json!({"id": "daemon-nul-target", "paths": ["/scan/invalid\0target"]}),
    )
    .expect("nul target result");

    assert_eq!(result["status"], "error");
    assert_eq!(result["scanned_files"], 0);
    assert_eq!(result["infected_count"], 0);
    assert_eq!(result["per_target_results"][0]["status"], "error");
}
