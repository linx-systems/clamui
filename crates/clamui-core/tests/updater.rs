use clamui_core::updater::{force_update_script, interpret_result, UpdateStatus};
use std::fs;
use std::process::Command;

#[test]
fn interprets_mixed_update_rate_limit_by_database() {
    let stdout = "daily.cvd updated (version: 1)\nmain.cvd database is up-to-date (version: 1)\nbytecode.cvd database available for download\nWARNING: FreshClam received error code 429 from the ClamAV CDN.\nWARNING: You are on cool-down until after: 2026-03-06 10:15:00\nWARNING: Can't download bytecode.cvd\n";
    let result = interpret_result(stdout.to_owned(), String::new(), 1);
    assert_eq!(result.status, UpdateStatus::Error);
    assert_eq!(result.updated_databases, vec!["daily.cvd".to_owned()]);
    assert_eq!(result.up_to_date_databases, vec!["main.cvd".to_owned()]);
    assert_eq!(
        result.rate_limited_databases.get("bytecode.cvd"),
        Some(&Some("2026-03-06 10:15:00".to_owned()))
    );
    assert!(result
        .error_message
        .as_deref()
        .is_some_and(|message| message.contains("partially completed")));
}

#[test]
fn successful_exit_without_a_download_is_up_to_date() {
    let result = interpret_result(
        "main.cvd database is up-to-date".to_owned(),
        String::new(),
        0,
    );
    assert_eq!(result.status, UpdateStatus::UpToDate);
    assert_eq!(result.databases_updated, 0);
}

#[cfg(unix)]
fn executable(path: &std::path::Path, content: &str) {
    use std::os::unix::fs::PermissionsExt;
    fs::write(path, content).unwrap();
    let mut permissions = fs::metadata(path).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(path, permissions).unwrap();
}

#[cfg(unix)]
#[test]
fn force_transaction_rolls_back_live_database_when_promotion_fails() {
    let temp = tempfile::tempdir().unwrap();
    let database_dir = temp.path().join("database");
    fs::create_dir(&database_dir).unwrap();
    let live = database_dir.join("main.cvd");
    fs::write(&live, b"original-live-database").unwrap();

    let bin = temp.path().join("bin");
    fs::create_dir(&bin).unwrap();
    let freshclam = bin.join("freshclam");
    executable(&freshclam, "#!/bin/sh\nset -eu\ndatadir=\nfor arg in \"$@\"; do case \"$arg\" in --datadir=*) datadir=${arg#--datadir=};; esac; done\n[ -n \"$datadir\" ]\nprintf staged > \"$datadir/main.cvd\"\n");
    let mv = bin.join("mv");
    executable(&mv, "#!/bin/sh\nset -eu\nif [ ! -e \"$FAIL_MARKER\" ] && printf '%s\\n' \"$@\" | grep -q '.clamui-force-update'; then : > \"$FAIL_MARKER\"; exit 1; fi\nexec /bin/mv \"$@\"\n");

    let marker = temp.path().join("promotion-failed");
    let path = format!(
        "{}:{}",
        bin.display(),
        std::env::var("PATH").unwrap_or_default()
    );
    let status = Command::new("sh")
        .arg("-c")
        .arg(force_update_script())
        .arg("clamui-force-update")
        .arg(&database_dir)
        .arg(&freshclam)
        .arg("")
        .env("PATH", path)
        .env("FAIL_MARKER", &marker)
        .status()
        .unwrap();

    assert!(!status.success());
    assert!(marker.exists());
    assert_eq!(fs::read(&live).unwrap(), b"original-live-database");
}
