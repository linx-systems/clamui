use rusqlite::{params, Connection};

use std::{
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    process::{Command, Output, Stdio},
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

fn cli() -> Command {
    Command::new(env!("CARGO_BIN_EXE_clamui-cli"))
}

fn scheduled() -> Command {
    Command::new(env!("CARGO_BIN_EXE_clamui-scheduled-scan"))
}

fn preferences_helper() -> Command {
    Command::new(env!("CARGO_BIN_EXE_clamui-apply-preferences"))
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn isolated_xdg(command: &mut Command) -> PathBuf {
    let root = std::env::temp_dir().join(format!(
        "clamui-cli-test-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("current time")
            .as_nanos(),
    ));
    std::fs::create_dir_all(&root).expect("create isolated CLI root");
    command.env("XDG_CONFIG_HOME", root.join("config"));
    command.env("XDG_DATA_HOME", root.join("data"));
    command.env("LANGUAGE", "en");
    root
}

fn cli_with_xdg(root: &std::path::Path) -> Command {
    let mut command = cli();
    command.env("XDG_CONFIG_HOME", root.join("config"));
    command.env("XDG_DATA_HOME", root.join("data"));
    command.env("LANGUAGE", "en");
    command
}

#[test]
fn root_help_is_headless_and_lists_all_documented_commands() {
    let mut command = cli();
    let root = isolated_xdg(&mut command);
    let output = command
        .arg("--help")
        .output()
        .expect("run clamui-cli --help");
    assert!(output.status.success(), "{}", stderr(&output));
    let output = stdout(&output);
    for command in [
        "scan",
        "quarantine",
        "profile",
        "status",
        "history",
        "help",
        "install-privileged-helper",
    ] {
        assert!(
            output.contains(command),
            "root help omitted {command}: {output}"
        );
    }
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn version_is_a_headless_success() {
    let mut command = cli();
    let root = isolated_xdg(&mut command);
    let output = command
        .arg("--version")
        .output()
        .expect("run clamui-cli --version");
    assert!(output.status.success(), "{}", stderr(&output));
    assert!(stdout(&output).contains(env!("CARGO_PKG_VERSION")));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn unknown_headless_command_is_a_parse_error() {
    let mut command = cli();
    let root = isolated_xdg(&mut command);
    let output = command
        .arg("not-a-command")
        .output()
        .expect("run unknown clamui-cli command");
    assert_eq!(output.status.code(), Some(2));
    assert!(stderr(&output).contains("Unknown command"));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn each_cli_topic_has_a_subprocess_help_path() {
    for (args, required) in [
        (
            &["scan", "--help"][..],
            &["Usage: clamui scan", "--no-recursive"][..],
        ),
        (&["quarantine", "--help"][..], &["list|restore|delete"][..]),
        (&["profile", "--help"][..], &["list|show|export|import"][..]),
        (
            &["status", "--help"][..],
            &["Usage: clamui status", "--json"][..],
        ),
        (
            &["history", "--help"][..],
            &["Usage: clamui history", "--limit"][..],
        ),
        (
            &["install-privileged-helper", "--help"][..],
            &["Usage: clamui install-privileged-helper"][..],
        ),
    ] {
        let mut command = cli();
        let root = isolated_xdg(&mut command);
        let output = command.args(args).output().expect("run command help");
        assert!(output.status.success(), "{args:?}: {}", stderr(&output));
        let rendered = stdout(&output);
        for expected in required {
            assert!(
                rendered.contains(expected),
                "{args:?} omitted documented help contract {expected}: {rendered}"
            );
        }
        assert!(stderr(&output).is_empty(), "{args:?}: {}", stderr(&output));
        let _ = std::fs::remove_dir_all(root);
    }
}

#[test]
fn scan_rejects_only_missing_targets_before_clamav_invocation() {
    let mut command = cli();
    let root = isolated_xdg(&mut command);
    let nonexistent = root.join("missing-target");
    let output = command
        .arg("scan")
        .arg(&nonexistent)
        .output()
        .expect("run scan missing target");
    assert_eq!(output.status.code(), Some(2));
    assert!(stderr(&output).contains("Path not found"));
    assert!(stderr(&output).contains("No valid paths to scan"));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn scan_consumes_profile_value_then_reaches_following_target() {
    let mut command = cli();
    let root = isolated_xdg(&mut command);
    let nonexistent = root.join("following-target");
    let target = nonexistent.display().to_string();
    let output = command
        .args(["scan", "--profile", "ignored-profile", target.as_str()])
        .output()
        .expect("run scan with profile and missing target");
    assert_eq!(output.status.code(), Some(2));
    assert!(
        stderr(&output).contains(&format!("Path not found: {}", target)),
        "following target was not parsed: {}",
        stderr(&output)
    );
    assert!(
        !stderr(&output).contains("Path not found: ignored-profile"),
        "profile value was parsed as a target: {}",
        stderr(&output)
    );
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn history_rejects_non_positive_limit() {
    let mut command = cli();
    let root = isolated_xdg(&mut command);
    let output = command
        .args(["history", "--limit", "0"])
        .output()
        .expect("run history invalid limit");
    assert_eq!(output.status.code(), Some(2));
    assert!(stderr(&output).contains("--limit must be a positive integer"));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn history_short_options_and_oversized_limit_preserve_filtered_history() {
    let mut setup = cli();
    let root = isolated_xdg(&mut setup);
    let logs = root.join("data/clamui/logs");
    std::fs::create_dir_all(&logs).expect("create history directory");
    for (file_name, entry) in [
        (
            "scan-entry.json",
            serde_json::json!({
                "id": "scan-entry",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "type": "scan",
                "status": "clean",
                "summary": "Scan complete",
                "details": "",
                "duration": 0.0,
                "scheduled": false,
            }),
        ),
        (
            "update-entry.json",
            serde_json::json!({
                "id": "update-entry",
                "timestamp": "2026-01-02T00:00:00+00:00",
                "type": "update",
                "status": "success",
                "summary": "Update complete",
                "details": "",
                "duration": 0.0,
                "scheduled": false,
            }),
        ),
    ] {
        std::fs::write(
            logs.join(file_name),
            serde_json::to_vec(&entry).expect("serialize history entry"),
        )
        .expect("write history entry");
    }

    let output = cli_with_xdg(&root)
        .args(["history", "-n", " 1 ", "--json"])
        .output()
        .expect("run history short limit");
    assert!(output.status.success(), "{}", stderr(&output));
    let entries: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("parse limited history JSON");
    assert_eq!(entries.as_array().map(Vec::len), Some(1));
    assert_eq!(entries[0]["type"], "update");

    let output = cli_with_xdg(&root)
        .args(["history", "-tupdate", "--json"])
        .output()
        .expect("run history short type");
    assert!(output.status.success(), "{}", stderr(&output));
    let entries: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("parse filtered history JSON");
    assert_eq!(entries.as_array().map(Vec::len), Some(1));
    assert_eq!(entries[0]["type"], "update");

    let output = cli_with_xdg(&root)
        .args(["history", "-n", "0_2", "--json"])
        .output()
        .expect("run history separated limit");
    assert!(output.status.success(), "{}", stderr(&output));
    let entries: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("parse separated-limit history JSON");
    assert_eq!(entries.as_array().map(Vec::len), Some(2));

    let output = cli_with_xdg(&root)
        .args(["history", "--limit", "18446744073709551616", "--json"])
        .output()
        .expect("run oversized history limit");
    assert!(output.status.success(), "{}", stderr(&output));
    let entries: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("parse oversized-limit history JSON");
    assert_eq!(entries.as_array().map(Vec::len), Some(2));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn profile_actions_honor_terminators_and_literal_tilde_paths() {
    let mut setup = cli();
    let root = isolated_xdg(&mut setup);
    let working_dir = root.join("working");
    let home = root.join("home");
    std::fs::create_dir_all(working_dir.join("~/exports")).expect("create literal export path");
    std::fs::write(
        working_dir.join("--json"),
        serde_json::to_vec(&serde_json::json!({
            "profile": {
                "name": "--json",
                "targets": [],
                "exclusions": {"paths": [], "patterns": []},
                "description": "",
                "options": {},
            }
        }))
        .expect("serialize profile import"),
    )
    .expect("write literal import file");
    std::fs::write(working_dir.join("profile.json"), b"replaced").expect("seed export file");

    let output = cli_with_xdg(&root)
        .current_dir(&working_dir)
        .env("HOME", &home)
        .args(["profile", "import", "--", "--json"])
        .output()
        .expect("import literal profile file");
    assert!(output.status.success(), "{}", stderr(&output));

    let output = cli_with_xdg(&root)
        .current_dir(&working_dir)
        .env("HOME", &home)
        .args(["profile", "show", "--", "--json"])
        .output()
        .expect("show literal profile name");
    assert!(output.status.success(), "{}", stderr(&output));

    let output = cli_with_xdg(&root)
        .current_dir(&working_dir)
        .env("HOME", &home)
        .args(["profile", "export", "--", "--json", "profile.json"])
        .output()
        .expect("export ordinary relative file");
    assert!(output.status.success(), "{}", stderr(&output));

    let output = cli_with_xdg(&root)
        .current_dir(&working_dir)
        .env("HOME", &home)
        .args(["profile", "export", "--", "--json", "--json"])
        .output()
        .expect("export literal flag-like file");
    assert!(output.status.success(), "{}", stderr(&output));

    for file_name in ["profile.json", "--json"] {
        let path = working_dir.join(file_name);
        let exported: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).expect("read exported profile"))
                .expect("parse exported profile");
        assert_eq!(exported["profile"]["name"], "--json");
        assert_eq!(
            std::fs::metadata(path)
                .expect("inspect exported profile mode")
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }

    let output = cli_with_xdg(&root)
        .current_dir(&working_dir)
        .env("HOME", &home)
        .args([
            "profile",
            "export",
            "--",
            "--json",
            "~/exports/profile.json",
        ])
        .output()
        .expect("export literal tilde path");
    assert!(output.status.success(), "{}", stderr(&output));
    assert!(working_dir.join("~/exports/profile.json").is_file());
    assert!(!home.join("exports/profile.json").exists());
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn quarantine_signed_or_oversized_ids_are_operational_failures_without_mutation() {
    let mut setup = cli();
    let root = isolated_xdg(&mut setup);
    let database = root.join("data/clamui/quarantine.db");
    std::fs::create_dir_all(database.parent().expect("quarantine data directory"))
        .expect("create quarantine data directory");
    let connection = Connection::open(&database).expect("open quarantine database");
    connection
        .execute_batch(
            "CREATE TABLE quarantine (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT NOT NULL,
                quarantine_path TEXT NOT NULL UNIQUE,
                threat_name TEXT NOT NULL,
                detection_date TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_hash TEXT NOT NULL,
                original_permissions INTEGER NOT NULL DEFAULT 420,
                state TEXT NOT NULL DEFAULT 'active'
            );",
        )
        .expect("create quarantine table");
    connection
        .execute(
            "INSERT INTO quarantine (
                original_path, quarantine_path, threat_name, detection_date,
                file_size, file_hash, original_permissions, state
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                "/original/seeded-file",
                "/quarantine/seeded-file",
                "Test.Signature",
                "2000-01-01T00:00:00",
                1,
                "seeded",
                0o644,
                "active",
            ],
        )
        .expect("seed quarantine entry");
    drop(connection);

    for args in [
        &["quarantine", "restore", "-1"][..],
        &["quarantine", "restore", " -1 "][..],
        &["quarantine", "restore", "--", "-1"][..],
        &["quarantine", "delete", "18446744073709551616"][..],
        &["quarantine", "delete", "1_844_674_407_370_955_161_6"][..],
    ] {
        let output = cli_with_xdg(&root)
            .args(args)
            .output()
            .expect("run quarantine action");
        assert_eq!(
            output.status.code(),
            Some(1),
            "{args:?}: {}",
            stderr(&output)
        );
    }

    let output = cli_with_xdg(&root)
        .args(["quarantine", "restore", "not-a-number"])
        .output()
        .expect("run malformed quarantine ID");
    assert_eq!(output.status.code(), Some(2), "{}", stderr(&output));

    let connection = Connection::open(&database).expect("reopen quarantine database");
    assert_eq!(
        connection
            .query_row("SELECT COUNT(*) FROM quarantine", [], |row| row
                .get::<_, i64>(0))
            .expect("count seeded quarantine rows"),
        1
    );
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn scheduled_wrapper_preserves_its_standalone_help_contract() {
    let mut command = scheduled();
    let root = isolated_xdg(&mut command);
    let output = command
        .arg("--help")
        .output()
        .expect("run scheduled scan help");
    assert!(output.status.success(), "{}", stderr(&output));
    let rendered = format!("{}{}", stdout(&output), stderr(&output));
    for flag in [
        "--skip-on-battery",
        "--auto-quarantine",
        "--target",
        "--dry-run",
        "--verbose",
    ] {
        assert!(
            rendered.contains(flag),
            "scheduled help omitted {flag}: {rendered}"
        );
    }
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn persistent_cli_json_contracts_are_machine_readable() {
    for args in [
        &["profile", "list", "--json"][..],
        &["history", "--json"][..],
        &["status", "--json"][..],
    ] {
        let mut command = cli();
        let root = isolated_xdg(&mut command);
        let output = command.args(args).output().expect("run JSON command");
        assert!(output.status.success(), "{args:?}: {}", stderr(&output));
        let json: serde_json::Value =
            serde_json::from_slice(&output.stdout).expect("command emitted JSON");
        match args[0] {
            "profile" | "history" => assert!(json.is_array(), "{args:?}: {json}"),
            "status" => {
                for key in ["clamav", "quarantine", "logs", "settings"] {
                    assert!(json.get(key).is_some(), "status omitted {key}: {json}");
                }
                assert!(
                    json["clamav"]["daemon_status"].is_string(),
                    "status must project daemon status to the legacy string: {json}"
                );
                assert!(
                    json["quarantine"]["entries"].is_u64(),
                    "status must project entry_count to legacy entries: {json}"
                );
            }
            _ => unreachable!(),
        }
        let _ = std::fs::remove_dir_all(root);
    }
}

#[test]
fn privileged_helper_wrapper_keeps_protocol_mismatch_exit_code() {
    let output = preferences_helper()
        .env("PKEXEC_UID", "1000")
        .output()
        .expect("run clamui-apply-preferences without protocol");
    assert_eq!(output.status.code(), Some(4));
}

#[test]
fn nested_command_help_exposes_its_action_operands() {
    for (args, required) in [
        (
            &["quarantine", "list", "--help"][..],
            "Usage: clamui quarantine list [--json]",
        ),
        (
            &["quarantine", "restore", "--help"][..],
            "Usage: clamui quarantine restore ID",
        ),
        (
            &["profile", "show", "--help"][..],
            "Usage: clamui profile show NAME [--json]",
        ),
        (
            &["profile", "export", "--help"][..],
            "Usage: clamui profile export NAME FILE",
        ),
    ] {
        let mut command = cli();
        let root = isolated_xdg(&mut command);
        let output = command.args(args).output().expect("run nested help");
        assert!(output.status.success(), "{args:?}: {}", stderr(&output));
        assert!(
            stdout(&output).contains(required),
            "{args:?} omitted action operand contract {required}: {}",
            stdout(&output)
        );
        assert!(stderr(&output).is_empty(), "{args:?}: {}", stderr(&output));
        let _ = std::fs::remove_dir_all(root);
    }
}

#[test]
fn scan_accepts_bare_dash_target_and_preserves_delimiter_paths() {
    let mut command = cli();
    let root = isolated_xdg(&mut command);
    let bin = root.join("bin");
    let target_root = root.join("targets");
    std::fs::create_dir_all(&bin).expect("create fake scanner directory");
    std::fs::create_dir_all(&target_root).expect("create target directory");
    let target = target_root.join("--help");
    let bare_dash_target = target_root.join("-");
    std::fs::write(&target, b"clean").expect("create literal help target");
    std::fs::write(&bare_dash_target, b"clean").expect("create bare dash target");

    let scanner = bin.join("clamscan");
    std::fs::write(
        &scanner,
        r#"#!/bin/sh
if [ "$1" = "--version" ]; then
  printf 'ClamAV 1.0\n'
  exit 0
fi
for argument do target="$argument"; done
printf '%s: OK\n' "$target"
printf 'Scanned files: 1\nScanned directories: 0\nInfected files: 0\nTotal errors: 0\n'
"#,
    )
    .expect("write fake scanner");
    std::fs::set_permissions(&scanner, std::fs::Permissions::from_mode(0o755))
        .expect("make fake scanner executable");

    let output = command
        .current_dir(&target_root)
        .env("PATH", &bin)
        .args(["scan", "--json", "--", "--help"])
        .output()
        .expect("scan literal --help target");

    assert!(output.status.success(), "{}", stderr(&output));
    let result: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("literal target scan JSON");
    assert_eq!(result["status"], "clean");
    assert_eq!(result["scanned_files"], 1);
    assert_eq!(
        result["targets"],
        serde_json::json!([target.canonicalize().expect("canonical target")])
    );

    let mut bare_dash_command = cli();
    let output = bare_dash_command
        .current_dir(&target_root)
        .env("PATH", &bin)
        .env("XDG_CONFIG_HOME", root.join("config"))
        .env("XDG_DATA_HOME", root.join("data"))
        .env("LANGUAGE", "en")
        .args(["scan", "--json", "-"])
        .output()
        .expect("scan bare dash target");
    assert!(output.status.success(), "{}", stderr(&output));
    let result: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("bare dash target scan JSON");
    assert_eq!(result["status"], "clean");
    assert_eq!(result["scanned_files"], 1);
    assert_eq!(
        result["targets"],
        serde_json::json!([bare_dash_target
            .canonicalize()
            .expect("canonical bare dash target")])
    );
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn scan_boolean_bundles_preserve_json_and_quarantine_behavior() {
    let mut setup = cli();
    let root = isolated_xdg(&mut setup);
    let bin = root.join("bin");
    std::fs::create_dir_all(&bin).expect("create fake scanner directory");
    let scanner = bin.join("clamscan");
    std::fs::write(
        &scanner,
        r#"#!/bin/sh
if [ "$1" = "--version" ]; then
  printf 'ClamAV 1.0\n'
  exit 0
fi
for argument do target="$argument"; done
printf '%s: Eicar-Test-Signature FOUND\n' "$target"
printf 'Scanned files: 1\nScanned directories: 0\nInfected files: 1\nTotal errors: 0\n'
exit 1
"#,
    )
    .expect("write infected fixture scanner");
    std::fs::set_permissions(&scanner, std::fs::Permissions::from_mode(0o755))
        .expect("make infected fixture scanner executable");

    for bundle in ["-vq", "-qv", "-vvq"] {
        let target = root.join(format!("infected-{bundle}"));
        std::fs::write(&target, b"infected").expect("create infected target");
        let mut command = cli_with_xdg(&root);
        let output = command
            .env("PATH", &bin)
            .args(["scan", bundle, "--json"])
            .arg(&target)
            .output()
            .expect("run bundled scan");
        assert_eq!(
            output.status.code(),
            Some(1),
            "{bundle}: {}",
            stderr(&output)
        );
        let result: serde_json::Value =
            serde_json::from_slice(&output.stdout).expect("parse bundled scan JSON");
        assert_eq!(result["status"], "infected");
        assert_eq!(result["quarantined"], 1);
        assert!(!target.exists(), "{bundle} did not quarantine its target");
    }
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn sigint_cancels_a_live_headless_scan_with_cancelled_json() {
    let mut command = cli();
    let root = isolated_xdg(&mut command);
    let bin = root.join("bin");
    let target = root.join("large-target");
    std::fs::create_dir_all(&bin).expect("create fake scanner directory");
    std::fs::write(&target, b"clean").expect("create scan target");

    let scanner = bin.join("clamscan");
    std::fs::write(
        &scanner,
        r#"#!/bin/sh
if [ "$1" = "--version" ]; then
  printf 'ClamAV 1.0\n'
  exit 0
fi
exec /bin/sleep 30
"#,
    )
    .expect("write blocking fake scanner");
    std::fs::set_permissions(&scanner, std::fs::Permissions::from_mode(0o755))
        .expect("make blocking fake scanner executable");

    let child = command
        .env("PATH", &bin)
        .args(["scan", "--json", target.to_str().expect("UTF-8 target")])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("start cancellable CLI scan");
    thread::sleep(Duration::from_millis(250));
    let signal_status = Command::new("/bin/kill")
        .args(["-INT", &child.id().to_string()])
        .status()
        .expect("send SIGINT to CLI scan");
    assert!(signal_status.success(), "send SIGINT");
    let output = child.wait_with_output().expect("reap CLI scan");

    assert_eq!(output.status.code(), Some(130), "{}", stderr(&output));
    let result: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("cancelled scan JSON");
    assert_eq!(result["status"], "cancelled");
    assert_eq!(
        result["targets"],
        serde_json::json!([target.canonicalize().expect("canonical target")])
    );
    let _ = std::fs::remove_dir_all(root);
}
