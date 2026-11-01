use clamui_core::privileged::{
    open_verified_staged_source, staging_root_for_uid, validate_destination, verify_staging_root,
    MAX_CONFIG_READ_BYTES, POLICY_ACTION, PROTOCOL_VERSION,
};
use std::fs;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::Path;
use std::process::Command;

fn uid() -> u32 {
    fs::metadata("/proc/self")
        .expect("inspect current process")
        .uid()
}

fn temporary_directory(label: &str) -> std::path::PathBuf {
    let directory = std::env::temp_dir().join(format!(
        "clamui-privileged-test-{label}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ));
    fs::create_dir(&directory).expect("create private test directory");
    directory
}

fn host_passwd_home(uid: u32) -> std::path::PathBuf {
    let uid_text = uid.to_string();
    let mut command =
        if std::env::var_os("FLATPAK_ID").is_some() || Path::new("/.flatpak-info").is_file() {
            let mut command = Command::new("flatpak-spawn");
            command.args(["--host", "/usr/bin/getent"]);
            command
        } else {
            Command::new("/usr/bin/getent")
        };
    let output = command
        .args(["passwd", &uid_text])
        .output()
        .expect("query authoritative passwd database");
    assert!(output.status.success(), "getent passwd must succeed");
    let record = String::from_utf8(output.stdout).expect("passwd record is UTF-8");
    let home = record
        .trim_end()
        .split(':')
        .nth(5)
        .filter(|value| value.starts_with('/'))
        .expect("passwd record has an absolute home directory");
    std::path::PathBuf::from(home)
}

#[test]
fn protocol_and_policy_identity_are_stable() {
    assert_eq!(PROTOCOL_VERSION, 4);
    assert_eq!(MAX_CONFIG_READ_BYTES, 1024 * 1024);
    assert_eq!(
        POLICY_ACTION,
        "io.github.linx_systems.clamui.apply-preferences"
    );
}

#[test]
fn destination_allowlist_rejects_non_config_system_files() {
    assert!(validate_destination(Path::new("/etc/shadow")).is_err());
    assert!(validate_destination(Path::new("/etc/passwd")).is_err());
    assert!(validate_destination(Path::new("/tmp/clamd.conf")).is_err());
    assert!(validate_destination(Path::new("/etc/clamav/../../passwd")).is_err());
    assert!(validate_destination(Path::new("/etc/freshclam.txt")).is_err());
}

#[test]
fn staging_root_comes_from_passwd_not_environment() {
    const CHILD: &str = "CLAMUI_FORGED_STAGING_ENV_CHILD";
    if let Some(forged_home) = std::env::var_os(CHILD) {
        let forged_home = std::path::PathBuf::from(forged_home);
        let root = staging_root_for_uid(uid()).expect("derive passwd home staging root");
        let expected = host_passwd_home(uid()).join(".cache/clamui/privileged-staging");
        assert_eq!(root, expected);
        assert!(!root.starts_with(&forged_home));
        return;
    }

    let forged_home = std::env::temp_dir().join(format!(
        "clamui-forged-home-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ));
    let status = Command::new(std::env::current_exe().expect("locate test binary"))
        .args([
            "--exact",
            "staging_root_comes_from_passwd_not_environment",
            "--nocapture",
        ])
        .env(CHILD, &forged_home)
        .env("HOME", &forged_home)
        .env("XDG_CACHE_HOME", forged_home.join("cache"))
        .status()
        .expect("run isolated forged-environment child");
    assert!(
        status.success(),
        "forged environment child failed: {status}"
    );
}

#[test]
fn world_readable_staging_directory_is_rejected_before_any_write() {
    let directory = temporary_directory("unsafe-staging");
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o755))
        .expect("make test directory unsafe");

    let result = verify_staging_root(&directory, uid());

    let _ = fs::remove_dir(&directory);
    assert!(result.is_err());
}

#[test]
fn staging_directory_owned_by_another_uid_is_rejected_without_reading_contents() {
    let directory = temporary_directory("wrong-owner");
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o700))
        .expect("make test directory private");

    let result = verify_staging_root(&directory, uid().saturating_add(1));

    let _ = fs::remove_dir(&directory);
    assert!(result.is_err());
}

#[test]
fn symlinked_staged_source_is_rejected_without_opening_its_target() {
    let root = temporary_directory("symlink-source");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))
        .expect("make staging root private");
    let source = root.join("source.conf");
    std::os::unix::fs::symlink("/etc/passwd", &source).expect("create hostile symlink");

    let result = open_verified_staged_source(&source, uid(), &root);

    let _ = fs::remove_file(&source);
    let _ = fs::remove_dir(&root);
    assert!(result.is_err());
}
