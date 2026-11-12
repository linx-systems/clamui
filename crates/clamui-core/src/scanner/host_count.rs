//! Host-side, bounded estimates for Flatpak clamscan targets.

use std::io::{self, Read};
use std::os::fd::AsRawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use super::{directory_regex, glob_regex, terminate_group, Exclusions};
use crate::common::watched_host_command;
use crate::AppResult;

const COUNT_TIMEOUT: Duration = Duration::from_secs(30);
const POLL_INTERVAL: Duration = Duration::from_millis(25);

/// Counts regular host files without collecting their names. This is only an
/// estimate: the filesystem and ClamAV's engine limits can change the result.
pub(super) fn count(
    path: &Path,
    recursive: bool,
    exclusions: &Exclusions,
    cancelled: &AtomicBool,
) -> AppResult<u64> {
    if cancelled.load(Ordering::Acquire) {
        return Err("Host file count cancelled".into());
    }
    // GNU find treats a starting point beginning with '-' as an expression.
    // Do not rewrite it: doing so would change the paths used by exclusions.
    if path.as_os_str().as_bytes().first() == Some(&b'-') {
        return Err("Host file count needs an unambiguous starting path".into());
    }

    let mut command = watched_host_command("find", &["-H".into()]);
    command
        .arg(path)
        .args(find_expression(recursive, exclusions));
    run_count(&mut command, cancelled, COUNT_TIMEOUT)
}

fn find_expression(recursive: bool, exclusions: &Exclusions) -> Vec<String> {
    let mut args = vec![
        "-regextype".into(),
        "posix-extended".into(),
        "-maxdepth".into(),
        if recursive { "15" } else { "1" }.into(),
    ];
    if !exclusions.directories.is_empty() {
        args.extend(["(".into(), "-type".into(), "d".into(), "(".into()]);
        for (index, directory) in exclusions.directories.iter().enumerate() {
            if index != 0 {
                args.push("-o".into());
            }
            args.extend([
                "-regex".into(),
                format!(".*({}).*", directory_regex(directory)),
            ]);
        }
        args.extend([")".into(), "-prune".into(), ")".into(), "-o".into()]);
    }
    args.extend(["(".into(), "-type".into(), "f".into()]);
    for pattern in &exclusions.patterns {
        args.extend([
            "!".into(),
            "-regex".into(),
            format!(".*({}).*", glob_regex(pattern)),
        ]);
    }
    args.extend(["-printf".into(), "1".into(), ")".into()]);
    args
}

fn add_markers(total: &mut u64, bytes: &[u8]) -> AppResult<()> {
    if bytes.iter().any(|byte| *byte != b'1') {
        return Err("Malformed host file count output".into());
    }
    *total = total
        .checked_add(bytes.len() as u64)
        .ok_or_else(|| "Host file count overflow".to_owned())?;
    Ok(())
}

fn run_count(command: &mut Command, cancelled: &AtomicBool, timeout: Duration) -> AppResult<u64> {
    command
        .process_group(0)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start host file count: {error}"))?;
    let result = (|| {
        let mut stdout = child
            .stdout
            .take()
            .ok_or_else(|| "Unable to capture host file count".to_owned())?;
        let fd = stdout.as_raw_fd();
        // Nonblocking reads keep cancellation and the deadline effective even
        // when find or a descendant keeps the pipe open without writing.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
            return Err(format!(
                "Unable to read host file count: {}",
                io::Error::last_os_error()
            ));
        }
        let started = Instant::now();
        let mut status = None;
        let mut closed = false;
        let mut total = 0_u64;
        let mut buffer = [0_u8; 8192];
        loop {
            if cancelled.load(Ordering::Acquire) {
                return Err("Host file count cancelled".into());
            }
            if started.elapsed() >= timeout {
                return Err("Host file count timed out".into());
            }
            if status.is_none() {
                status = child
                    .try_wait()
                    .map_err(|error| format!("Unable to wait for host file count: {error}"))?;
            }
            if let Some(exit) = status {
                // GNU find can report inaccessible paths while still counting other files.
                if !matches!(exit.code(), Some(0 | 1)) {
                    return Err(format!("Host file count failed: {exit}"));
                }
                if closed {
                    return Ok(total);
                }
            }
            let mut pollfd = libc::pollfd {
                fd: if closed { -1 } else { fd },
                events: libc::POLLIN,
                revents: 0,
            };
            let remaining = timeout.saturating_sub(started.elapsed()).min(POLL_INTERVAL);
            let ready = unsafe { libc::poll(&mut pollfd, 1, remaining.as_millis() as i32) };
            if ready < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(format!("Unable to poll host file count: {error}"));
            }
            if ready == 0 || closed {
                continue;
            }
            match stdout.read(&mut buffer) {
                Ok(0) => closed = true,
                Ok(length) => add_markers(&mut total, &buffer[..length])?,
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) => {}
                Err(error) => return Err(format!("Unable to read host file count: {error}")),
            }
        }
    })();
    if result.is_err() {
        terminate_group(&mut child);
        let _ = child.wait();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsString;
    use std::fs;
    use std::os::unix::ffi::OsStringExt;
    use std::os::unix::fs::{symlink, PermissionsExt};

    #[test]
    fn markers_stream_across_chunks_without_retaining_output() {
        let mut total = 0;

        add_markers(&mut total, b"111").unwrap();
        add_markers(&mut total, b"").unwrap();
        add_markers(&mut total, b"11").unwrap();
        assert_eq!(total, 5);
    }

    #[test]
    fn process_accepts_well_formed_output_with_exit_one() {
        let cancelled = AtomicBool::new(false);
        let mut partial = Command::new("sh");
        partial.args(["-c", "printf 111; exit 1"]);
        assert_eq!(
            run_count(&mut partial, &cancelled, Duration::from_secs(5)).unwrap(),
            3
        );
        assert_eq!(
            run_count(
                &mut Command::new("false"),
                &cancelled,
                Duration::from_secs(5)
            )
            .unwrap(),
            0
        );
    }

    #[test]
    fn process_rejects_malformed_output_with_exit_one() {
        let mut malformed = Command::new("sh");
        malformed.args(["-c", "printf 111; (sleep 0.1; printf x) & exit 1"]);
        assert!(run_count(
            &mut malformed,
            &AtomicBool::new(false),
            Duration::from_secs(5)
        )
        .is_err());
    }

    #[test]
    fn process_rejects_fatal_exit_signal_and_spawn_failure() {
        let cancelled = AtomicBool::new(false);
        let mut fatal = Command::new("sh");
        fatal.args(["-c", "printf 111; exit 2"]);
        assert!(run_count(&mut fatal, &cancelled, Duration::from_secs(5)).is_err());

        let mut signalled = Command::new("sh");
        signalled.args(["-c", "kill -TERM $$"]);
        assert!(run_count(&mut signalled, &cancelled, Duration::from_secs(5)).is_err());

        let fixture = tempfile::tempdir().unwrap();
        let mut missing = Command::new(fixture.path().join("missing-command"));
        assert!(run_count(&mut missing, &cancelled, Duration::from_secs(5)).is_err());
    }

    #[test]
    fn host_count_keeps_accessible_files_when_a_directory_is_unreadable() {
        let root_user = unsafe { libc::geteuid() } == 0;
        let fixture = if root_user {
            tempfile::tempdir_in("/tmp").unwrap()
        } else {
            tempfile::tempdir().unwrap()
        };
        fs::set_permissions(fixture.path(), fs::Permissions::from_mode(0o755)).unwrap();
        let root = fixture.path().join("root");
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o755)).unwrap();
        fs::write(root.join("before"), b"").unwrap();
        let restricted = root.join("restricted");
        fs::create_dir(&restricted).unwrap();
        fs::write(restricted.join("hidden"), b"").unwrap();
        fs::write(root.join("after"), b"").unwrap();
        fs::set_permissions(&restricted, fs::Permissions::from_mode(0o000)).unwrap();

        let mut command = Command::new("find");
        command
            .arg("-H")
            .arg(&root)
            .args(find_expression(true, &Exclusions::default()));
        if root_user {
            command.gid(65534).uid(65534);
        }
        let result = run_count(
            &mut command,
            &AtomicBool::new(false),
            Duration::from_secs(5),
        );
        fs::set_permissions(&restricted, fs::Permissions::from_mode(0o755)).unwrap();
        assert_eq!(result.unwrap(), 2);
    }

    #[test]
    fn process_timeout_terminates_a_silent_child() {
        let mut command = Command::new("sleep");
        command.arg("60");
        assert!(run_count(
            &mut command,
            &AtomicBool::new(false),
            Duration::from_millis(50)
        )
        .is_err());
    }

    #[test]
    fn process_cancellation_terminates_a_silent_child() {
        let cancelled = AtomicBool::new(false);
        std::thread::scope(|scope| {
            scope.spawn(|| {
                std::thread::sleep(Duration::from_millis(50));
                cancelled.store(true, Ordering::Release);
            });
            let mut command = Command::new("sleep");
            command.arg("60");
            assert!(run_count(&mut command, &cancelled, Duration::from_secs(5)).is_err());
        });
    }

    #[test]
    fn markers_reject_malformed_output_and_overflow() {
        assert!(add_markers(&mut 0, b"11\n").is_err());
        let mut total = u64::MAX;
        assert!(add_markers(&mut total, b"1").is_err());
    }

    #[test]
    fn host_count_respects_exclusions_hidden_files_and_symlinks() {
        let fixture = tempfile::tempdir().unwrap();
        let root = fixture.path().join("root");
        fs::create_dir_all(root.join(".hidden")).unwrap();
        fs::create_dir_all(root.join("skipdir")).unwrap();
        fs::write(root.join("plain"), b"").unwrap();
        fs::write(root.join("skip.tmp"), b"").unwrap();
        fs::write(root.join(".hidden/keep"), b"").unwrap();
        fs::write(root.join("skipdir/ignored"), b"").unwrap();
        fs::write(
            root.join(OsString::from_vec(b"raw-\xff\nname".to_vec())),
            b"",
        )
        .unwrap();
        symlink(root.join("plain"), root.join("child-link")).unwrap();
        let link = fixture.path().join("root-link");
        symlink(&root, &link).unwrap();
        let exclusions = Exclusions {
            directories: vec!["skipdir".into()],
            patterns: vec!["*.tmp".into()],
        };
        let cancelled = AtomicBool::new(false);
        assert_eq!(count(&link, true, &exclusions, &cancelled).unwrap(), 3);
        assert_eq!(count(&link, false, &exclusions, &cancelled).unwrap(), 2);
        assert_eq!(
            count(&root.join("child-link"), true, &exclusions, &cancelled).unwrap(),
            1
        );
    }

    #[test]
    fn non_utf8_starting_path_is_preserved() {
        let fixture = tempfile::tempdir().unwrap();
        let root = fixture
            .path()
            .join(OsString::from_vec(b"raw-\xff".to_vec()));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("file"), b"").unwrap();
        assert_eq!(
            count(&root, true, &Exclusions::default(), &AtomicBool::new(false)).unwrap(),
            1
        );
    }

    #[test]
    fn recursive_count_stops_at_clamscan_default_depth() {
        let fixture = tempfile::tempdir().unwrap();
        let mut dir = fixture.path().to_path_buf();
        for depth in 1..=15 {
            dir.push("d");
            fs::create_dir(&dir).unwrap();
            if depth == 14 || depth == 15 {
                fs::write(dir.join("file"), b"").unwrap();
            }
        }
        assert_eq!(
            count(
                fixture.path(),
                true,
                &Exclusions::default(),
                &AtomicBool::new(false)
            )
            .unwrap(),
            1
        );
    }

    #[test]
    fn missing_target_returns_zero_and_pre_cancelled_count_is_an_error() {
        let fixture = tempfile::tempdir().unwrap();
        assert_eq!(
            count(
                &fixture.path().join("missing"),
                true,
                &Exclusions::default(),
                &AtomicBool::new(false)
            )
            .unwrap(),
            0
        );
        assert!(count(
            fixture.path(),
            true,
            &Exclusions::default(),
            &AtomicBool::new(true)
        )
        .is_err());
    }
}
