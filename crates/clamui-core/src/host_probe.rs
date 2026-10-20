//! Bounded, read-only host command execution shared by core probes.

use std::io::{self, Read};
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;
use std::process::{Child, ChildStderr, ChildStdout, Command, ExitStatus, Stdio};
use std::time::{Duration, Instant};

use crate::common::watched_host_command;

#[derive(Debug)]
pub(crate) struct LimitedCommandOutput {
    pub code: Option<i32>,
    pub stdout: String,
    pub timed_out: bool,
    pub truncated: bool,
    pub invalid_utf8: bool,
}

const LIMITED_READ_CHUNK: usize = 8192;
const LIMITED_POLL_INTERVAL: Duration = Duration::from_millis(25);

pub(crate) fn run_limited_command(
    program: &str,
    args: &[&str],
    timeout: Duration,
    output_limit: usize,
) -> LimitedCommandOutput {
    let arguments = args
        .iter()
        .map(|value| (*value).to_owned())
        .collect::<Vec<_>>();
    let mut command: Command = watched_host_command(program, &arguments);
    command
        .process_group(0)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let Ok(mut child) = command.spawn() else {
        return incomplete_limited_output();
    };
    let Some(mut stdout_reader) = child.stdout.take() else {
        terminate_limited_process_group(&mut child);
        return incomplete_limited_output();
    };
    let Some(mut stderr_reader) = child.stderr.take() else {
        drop(stdout_reader);
        terminate_limited_process_group(&mut child);
        return incomplete_limited_output();
    };
    if set_limited_nonblocking(&stdout_reader).is_err()
        || set_limited_nonblocking(&stderr_reader).is_err()
    {
        terminate_limited_process_group(&mut child);
        drop(stdout_reader);
        drop(stderr_reader);
        return incomplete_limited_output();
    }

    let started = Instant::now();
    let mut stdout = Vec::with_capacity(output_limit.min(LIMITED_READ_CHUNK));
    let mut stderr = Vec::with_capacity(output_limit.min(LIMITED_READ_CHUNK));
    let mut stdout_closed = false;
    let mut stderr_closed = false;
    let mut status = None;
    let mut timed_out = false;
    let mut truncated = false;
    let mut incomplete = false;

    loop {
        if started.elapsed() >= timeout {
            timed_out = true;
            break;
        }
        if status.is_none() {
            match child.try_wait() {
                Ok(current) => status = current,
                Err(_) => {
                    incomplete = true;
                    break;
                }
            }
        }
        if stdout_closed && stderr_closed {
            if status.is_some() {
                break;
            }
            std::thread::sleep(LIMITED_POLL_INTERVAL);
            continue;
        }

        let remaining = timeout.saturating_sub(started.elapsed());
        let (stdout_ready, stderr_ready) = match poll_limited_output(
            &stdout_reader,
            &stderr_reader,
            stdout_closed,
            stderr_closed,
            remaining.min(LIMITED_POLL_INTERVAL),
        ) {
            Ok(ready) => ready,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => {
                incomplete = true;
                break;
            }
        };
        if stdout_ready && !stdout_closed {
            match drain_limited_pipe(&mut stdout_reader, &mut stdout, output_limit) {
                Ok(closed) => stdout_closed = closed,
                Err(LimitedPipeError::ExceededLimit) => {
                    truncated = true;
                    break;
                }
                Err(LimitedPipeError::Io) => {
                    incomplete = true;
                    break;
                }
            }
        }
        if stderr_ready && !stderr_closed {
            match drain_limited_pipe(&mut stderr_reader, &mut stderr, output_limit) {
                Ok(closed) => stderr_closed = closed,
                Err(LimitedPipeError::ExceededLimit) => {
                    truncated = true;
                    break;
                }
                Err(LimitedPipeError::Io) => {
                    incomplete = true;
                    break;
                }
            }
        }
    }

    let complete = !timed_out && !truncated && !incomplete && status.is_some();
    if !complete {
        terminate_limited_process_group(&mut child);
    }
    drop(stdout_reader);
    drop(stderr_reader);
    let (stdout, stdout_invalid_utf8) = limited_output_text(stdout);
    let stderr_invalid_utf8 = std::str::from_utf8(&stderr).is_err();
    LimitedCommandOutput {
        code: complete
            .then(|| status.as_ref().and_then(ExitStatus::code))
            .flatten(),
        stdout,
        timed_out,
        truncated: truncated || incomplete,
        invalid_utf8: stdout_invalid_utf8 || stderr_invalid_utf8,
    }
}

fn incomplete_limited_output() -> LimitedCommandOutput {
    LimitedCommandOutput {
        code: None,
        stdout: String::new(),
        timed_out: false,
        truncated: true,
        invalid_utf8: false,
    }
}

fn set_limited_nonblocking<R: AsRawFd>(reader: &R) -> io::Result<()> {
    let descriptor = reader.as_raw_fd();
    let flags = unsafe { libc::fcntl(descriptor, libc::F_GETFL) };
    if flags < 0 {
        return Err(io::Error::last_os_error());
    }
    if unsafe { libc::fcntl(descriptor, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn poll_limited_output(
    stdout: &ChildStdout,
    stderr: &ChildStderr,
    stdout_closed: bool,
    stderr_closed: bool,
    timeout: Duration,
) -> io::Result<(bool, bool)> {
    let mut descriptors = [
        libc::pollfd {
            fd: if !stdout_closed {
                stdout.as_raw_fd()
            } else {
                -1
            },
            events: libc::POLLIN,
            revents: 0,
        },
        libc::pollfd {
            fd: if !stderr_closed {
                stderr.as_raw_fd()
            } else {
                -1
            },
            events: libc::POLLIN,
            revents: 0,
        },
    ];
    let milliseconds = timeout.as_millis().min(i32::MAX as u128) as i32;
    let result = unsafe {
        libc::poll(
            descriptors.as_mut_ptr(),
            descriptors.len() as libc::nfds_t,
            milliseconds,
        )
    };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    let ready = libc::POLLIN | libc::POLLHUP | libc::POLLERR | libc::POLLNVAL;
    Ok((
        !stdout_closed && descriptors[0].revents & ready != 0,
        !stderr_closed && descriptors[1].revents & ready != 0,
    ))
}

enum LimitedPipeError {
    ExceededLimit,
    Io,
}

fn drain_limited_pipe<R: Read>(
    reader: &mut R,
    output: &mut Vec<u8>,
    output_limit: usize,
) -> Result<bool, LimitedPipeError> {
    let mut buffer = [0_u8; LIMITED_READ_CHUNK];
    match reader.read(&mut buffer) {
        Ok(0) => Ok(true),
        Ok(read) if read > output_limit.saturating_sub(output.len()) => {
            let retained = output_limit.saturating_sub(output.len());
            output.extend_from_slice(&buffer[..retained]);
            Err(LimitedPipeError::ExceededLimit)
        }
        Ok(read) => {
            output.extend_from_slice(&buffer[..read]);
            Ok(false)
        }
        Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(false),
        Err(error) if error.kind() == io::ErrorKind::Interrupted => Ok(false),
        Err(_) => Err(LimitedPipeError::Io),
    }
}

fn terminate_limited_process_group(child: &mut Child) {
    let group = child.id() as libc::pid_t;
    let _ = unsafe { libc::kill(-group, libc::SIGKILL) };
    let _ = child.kill();
    let _ = child.wait();
}

pub(crate) fn limited_output_text(bytes: Vec<u8>) -> (String, bool) {
    match String::from_utf8(bytes) {
        Ok(text) => (text, false),
        Err(_) => (String::new(), true),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn limited_runner_times_out_when_a_descendant_holds_the_pipe() {
        let started = Instant::now();
        let output = run_limited_command(
            "/bin/sh",
            &["-c", "(/bin/sleep 2) &"],
            Duration::from_millis(150),
            1024,
        );

        assert!(output.timed_out);
        assert!(output.code.is_none());
        assert!(
            started.elapsed() < Duration::from_secs(1),
            "the inherited pipe must not outlive the bounded deadline"
        );
    }

    #[test]
    fn limited_runner_rejects_oversized_streams_without_retaining_them() {
        let output = run_limited_command(
            "/bin/sh",
            &[
                "-c",
                "printf '0123456789012345678901234567890123456789012345678901234567890123456789'",
            ],
            Duration::from_secs(1),
            32,
        );

        assert!(output.truncated);
        assert!(output.code.is_none());
        assert!(output.stdout.len() <= 32);
    }
}
