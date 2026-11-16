use super::*;
use crate::common::Paths;
use std::os::unix::fs::PermissionsExt;

#[test]
fn noninteractive_audit_preserves_output_and_failure_status() {
    let output = run_command(
        "/bin/sh",
        &[
            "-c",
            "read -r answer; printf 'audit output\\n'; printf 'audit error\\n' >&2; exit 7",
        ],
        Duration::from_secs(5),
    );
    assert_eq!(output.code, Some(7));
    assert_eq!(output.stdout, "audit output\n");
    assert_eq!(output.stderr, "audit error ");
}

#[test]
fn lynis_runs_noninteractively_with_an_open_parent_stdin() {
    const FIXTURE_ROOT: &str = "CLAMUI_LYNIS_TEST_ROOT";
    if let Some(root) = std::env::var_os(FIXTURE_ROOT) {
        let root = std::path::PathBuf::from(root);
        let ctx = Context::with_paths(Paths {
            home: root.join("home"),
            config_dir: root.join("config"),
            data_dir: root.join("data"),
        })
        .unwrap();
        let section = run_deep(&ctx, "lynis");
        assert_eq!(section.category, AuditCategory::DeepScanLynis);
        assert_ne!(section.overall_status, AuditStatus::Unknown);
        assert!(!section
            .checks
            .iter()
            .any(|row| row.detail.contains("timed out")));
        return;
    }

    let temp = tempfile::TempDir::new().unwrap();
    let bin = temp.path().join("home/linuxbrew/.linuxbrew/bin");
    fs::create_dir_all(&bin).unwrap();
    for (name, script) in [
        (
            "which",
            "#!/bin/sh\n[ \"$1\" = lynis ] || exit 1\nprintf '%s/lynis\\n' \"${PATH%%:*}\"\n",
        ),
        ("pkexec", "#!/bin/sh\nexec \"$@\"\n"),
        (
            "lynis",
            concat!(
                "#!/bin/sh\n",
                "[ \"$*\" = 'audit system --cronjob --quiet' ] || exit 42\n",
                // Model the ownership warning that waits for ENTER even in cron mode.
                "read -r answer\n",
                "printf 'completed' > \"$CLAMUI_LYNIS_TEST_ROOT/result\"\n",
            ),
        ),
    ] {
        let path = bin.join(name);
        fs::write(&path, script).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    }
    // A separate test process avoids mutating PATH in parallel tests.
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "audit::tests::lynis_runs_noninteractively_with_an_open_parent_stdin",
            "--nocapture",
        ])
        .env(FIXTURE_ROOT, temp.path())
        .env("PATH", &bin)
        .env("LANGUAGE", "en")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let input = child.stdin.take().unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    let completed = loop {
        if child.try_wait().unwrap().is_some() {
            break true;
        }
        if std::time::Instant::now() >= deadline {
            break false;
        }
        std::thread::sleep(Duration::from_millis(25));
    };
    // Release a regressed process before collecting its failure output.
    drop(input);
    let output = child.wait_with_output().unwrap();
    assert!(completed, "Lynis waited for input from its parent");
    assert!(output.status.success(), "{output:?}");
    assert_eq!(
        fs::read_to_string(temp.path().join("result")).unwrap(),
        "completed"
    );
}
