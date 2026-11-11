use crate::common::{host_command, sanitize_line, sanitize_text, Context};
use crate::host::{
    check_tool, config_file_exists, database_status, detect_freshclam_conf_path,
    freshclam_database_dir, host_binary, resolve_freshclam_conf_path, run_host,
};
use crate::AppResult;
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const TERMINATE_GRACE: Duration = Duration::from_secs(5);
const KILL_WAIT: Duration = Duration::from_secs(2);
const OUTPUT_DRAIN_GRACE: Duration = Duration::from_secs(2);
const SERVICE_NAMES: [&str; 2] = ["clamav-freshclam.service", "freshclam.service"];

fn trn(ctx: &Context, singular: &str, plural: &str, count: u64) -> String {
    crate::i18n::translate_plural(ctx, singular, plural, count)
}

fn trnf(
    ctx: &Context,
    singular: &str,
    plural: &str,
    count: u64,
    replacements: &[(&str, &str)],
) -> String {
    let mut rendered = trn(ctx, singular, plural, count);
    for (placeholder, value) in replacements {
        rendered = rendered.replace(placeholder, value);
    }
    rendered
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum UpdateStatus {
    Success,
    UpToDate,
    Error,
    Cancelled,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum UpdateMethod {
    ServiceSignal,
    Manual,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FreshclamServiceStatus {
    Running,
    Stopped,
    NotFound,
    Unknown,
}

#[derive(Clone, Debug, Serialize)]
pub struct UpdateResult {
    pub status: UpdateStatus,
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
    pub databases_updated: usize,
    pub error_message: Option<String>,
    pub update_method: UpdateMethod,
    pub updated_databases: Vec<String>,
    pub up_to_date_databases: Vec<String>,
    pub rate_limited_databases: BTreeMap<String, Option<String>>,
}

impl UpdateResult {
    fn error(message: impl Into<String>) -> Self {
        let message = message.into();
        Self {
            status: UpdateStatus::Error,
            stdout: String::new(),
            stderr: message.clone(),
            exit_code: -1,
            databases_updated: 0,
            error_message: Some(message),
            update_method: UpdateMethod::Manual,
            updated_databases: Vec::new(),
            up_to_date_databases: Vec::new(),
            rate_limited_databases: BTreeMap::new(),
        }
    }

    fn cancelled(stdout: String, stderr: String, exit_code: i32) -> Self {
        Self {
            status: UpdateStatus::Cancelled,
            stdout,
            stderr,
            exit_code,
            databases_updated: 0,
            error_message: Some("Update cancelled by user".to_owned()),
            update_method: UpdateMethod::Manual,
            updated_databases: Vec::new(),
            up_to_date_databases: Vec::new(),
            rate_limited_databases: BTreeMap::new(),
        }
    }

    fn output_incomplete(stdout: String, stderr: String, exit_code: i32) -> Self {
        Self {
            status: UpdateStatus::Error,
            stdout,
            stderr,
            exit_code,
            databases_updated: 0,
            error_message: Some(
                "Update process output did not close after cleanup; result cannot be classified."
                    .to_owned(),
            ),
            update_method: UpdateMethod::Manual,
            updated_databases: Vec::new(),
            up_to_date_databases: Vec::new(),
            rate_limited_databases: BTreeMap::new(),
        }
    }
}

fn localize_result(ctx: &Context, result: &mut UpdateResult) {
    if result.status == UpdateStatus::Cancelled {
        result.error_message = Some(crate::i18n::translate(ctx, "Update cancelled by user"));
    }
    if let Some(message) = result.error_message.as_deref() {
        let translated = match message {
            "Update process output did not close after cleanup; result cannot be classified." => {
                Some(crate::i18n::translate(
                    ctx,
                    "Update process output did not close after cleanup; result cannot be classified.",
                ))
            }
            "Authentication cancelled. Database update requires administrator privileges."
            | "Authorization failed. You are not authorized to update the database."
            | "Update rate limited by mirror. Please wait a few minutes and try again."
            | "Update blocked by CDN. This may be due to rate limiting. Please wait and try again later."
            | "ClamAV mirror is currently unavailable. Please try again later."
            | "SSL/TLS certificate error. The mirror may have configuration issues."
            | "Connection timed out. Please check your network connection."
            | "Authorization failed. Please try again and enter your password."
            | "Database is locked. Another freshclam instance may be running."
            | "Permission denied. You may need elevated privileges to update the database."
            | "Connection error. Please check your network connection."
            | "DNS resolution failed. Please check your network settings."
            | "Update failed with an unknown error. Check the logs for details."
            | "Update cancelled by user" => Some(crate::i18n::translate(ctx, message)),
            _ => None,
        };
        if let Some(translated) = translated {
            result.error_message = Some(translated);
        }
    }
}

#[derive(Default)]
struct ParsedFreshclamOutput {
    updated: Vec<String>,
    up_to_date: Vec<String>,
    rate_limited: BTreeMap<String, Option<String>>,
}

fn append_unique(items: &mut Vec<String>, item: Option<String>) {
    if let Some(item) = item {
        if !items.contains(&item) {
            items.push(item);
        }
    }
}

fn database_in(line: &str) -> Option<String> {
    line.split(|character: char| {
        !(character.is_ascii_alphanumeric() || matches!(character, '.' | '_' | '-'))
    })
    .find(|word| {
        let lower = word.to_ascii_lowercase();
        lower.ends_with(".cvd") || lower.ends_with(".cld") || lower.ends_with(".cud")
    })
    .map(str::to_owned)
}

pub fn parse_output(
    stdout: &str,
    stderr: &str,
) -> (Vec<String>, Vec<String>, BTreeMap<String, Option<String>>) {
    let mut parsed = ParsedFreshclamOutput::default();
    let mut current_database = None;
    let mut pending_rate_limit = false;
    let mut pending_cooldown = None;
    let mut pending_database = None;
    for raw_line in stdout.lines().chain(stderr.lines()) {
        let line = raw_line.trim();
        if line.is_empty() {
            continue;
        }
        let lower = line.to_ascii_lowercase();
        let database = database_in(line);
        if database.is_some() {
            current_database = database.clone();
        }
        if lower.contains("updated (version:") && database.is_some() {
            append_unique(&mut parsed.updated, database.clone());
            if let Some(database) = database {
                parsed.rate_limited.remove(&database);
            }
            pending_rate_limit = false;
            pending_cooldown = None;
            pending_database = None;
            continue;
        }
        if (lower.contains("is up-to-date") || lower.contains("is up to date"))
            && database.is_some()
        {
            append_unique(&mut parsed.up_to_date, database.clone());
            if let Some(database) = database {
                parsed.rate_limited.remove(&database);
            }
            pending_rate_limit = false;
            pending_cooldown = None;
            pending_database = None;
            continue;
        }
        if let Some(cooldown) = lower
            .find("cool-down until after:")
            .or_else(|| lower.find("cooldown until after:"))
        {
            let value = line[cooldown..]
                .split_once(':')
                .map(|(_, value)| value.trim().to_owned())
                .filter(|value| !value.is_empty());
            pending_rate_limit = true;
            pending_cooldown = value;
            if let Some(database) = pending_database
                .clone()
                .or_else(|| current_database.clone())
            {
                parsed
                    .rate_limited
                    .insert(database.clone(), pending_cooldown.clone());
                pending_database = Some(database);
            }
            continue;
        }
        let rate_limited = [
            "rate limit",
            "rate-limit",
            "rate limited",
            "429",
            "too many requests",
            "temporarily blocked",
            "blocked temporarily",
            "cloudfront",
            "cloudflare",
        ]
        .iter()
        .any(|needle| lower.contains(needle));
        if rate_limited {
            pending_rate_limit = true;
            if let Some(database) = database.or_else(|| current_database.clone()) {
                parsed
                    .rate_limited
                    .entry(database.clone())
                    .or_insert_with(|| pending_cooldown.clone());
                pending_database = Some(database);
            }
            continue;
        }
        if pending_rate_limit
            && (lower.contains("can't download")
                || lower.contains("cannot download")
                || lower.contains("failed to update"))
        {
            if let Some(database) = database {
                parsed
                    .rate_limited
                    .insert(database.clone(), pending_cooldown.clone());
                pending_database = Some(database);
            }
        }
    }
    (parsed.updated, parsed.up_to_date, parsed.rate_limited)
}

fn error_message(
    stdout: &str,
    stderr: &str,
    exit_code: i32,
    rate_limited: &BTreeMap<String, Option<String>>,
    updated: &[String],
    current: &[String],
) -> String {
    let output = format!("{stdout}\n{stderr}");
    let lower = output.to_ascii_lowercase();
    if exit_code == 126 {
        return "Authentication cancelled. Database update requires administrator privileges."
            .to_owned();
    }
    if exit_code == 127 && lower.contains("pkexec") {
        return "Authorization failed. You are not authorized to update the database.".to_owned();
    }
    if !rate_limited.is_empty() {
        let rates = rate_limited
            .iter()
            .map(|(database, cooldown)| {
                cooldown
                    .as_ref()
                    .map(|cooldown| format!("{database} until {cooldown}"))
                    .unwrap_or_else(|| database.clone())
            })
            .collect::<Vec<_>>()
            .join(", ");
        let mut progress = Vec::new();
        if !updated.is_empty() {
            progress.push(format!("Updated: {}", updated.join(", ")));
        }
        if !current.is_empty() {
            progress.push(format!("Already current: {}", current.join(", ")));
        }
        return if progress.is_empty() {
            format!("Update rate limited for: {rates}.")
        } else {
            format!(
                "Database update partially completed. {}. Rate limited: {rates}.",
                progress.join(". ")
            )
        };
    }
    if [
        "rate limit",
        "rate-limit",
        "rate limited",
        "429",
        "too many requests",
        "temporarily blocked",
        "blocked temporarily",
    ]
    .iter()
    .any(|needle| lower.contains(needle))
    {
        return "Update rate limited by mirror. Please wait a few minutes and try again."
            .to_owned();
    }
    if lower.contains("cloudfront") || lower.contains("cloudflare") {
        return "Update blocked by CDN. This may be due to rate limiting. Please wait and try again later.".to_owned();
    }
    if lower.contains("mirror") && (lower.contains("down") || lower.contains("unavailable")) {
        return "ClamAV mirror is currently unavailable. Please try again later.".to_owned();
    }
    if ["certificate", "ssl error", "tls error", "verify failed"]
        .iter()
        .any(|needle| lower.contains(needle))
    {
        return "SSL/TLS certificate error. The mirror may have configuration issues.".to_owned();
    }
    if lower.contains("timeout") || lower.contains("timed out") {
        return "Connection timed out. Please check your network connection.".to_owned();
    }
    if lower.contains("not authorized") || lower.contains("authorization") {
        return "Authorization failed. Please try again and enter your password.".to_owned();
    }
    if lower.contains("locked") || lower.contains("lock") {
        return "Database is locked. Another freshclam instance may be running.".to_owned();
    }
    if lower.contains("permission denied") {
        return "Permission denied. You may need elevated privileges to update the database."
            .to_owned();
    }
    if lower.contains("can't connect") || lower.contains("connection") {
        return "Connection error. Please check your network connection.".to_owned();
    }
    if lower.contains("can't resolve") || lower.contains("host not found") {
        return "DNS resolution failed. Please check your network settings.".to_owned();
    }
    if !stderr.trim().is_empty() {
        return stderr.trim().to_owned();
    }
    "Update failed with an unknown error. Check the logs for details.".to_owned()
}

pub fn interpret_result(stdout: String, stderr: String, exit_code: i32) -> UpdateResult {
    let (updated_databases, up_to_date_databases, rate_limited_databases) =
        parse_output(&stdout, &stderr);
    let status = if exit_code == 0 {
        if updated_databases.is_empty() {
            UpdateStatus::UpToDate
        } else {
            UpdateStatus::Success
        }
    } else {
        UpdateStatus::Error
    };
    let error_message = (status == UpdateStatus::Error).then(|| {
        error_message(
            &stdout,
            &stderr,
            exit_code,
            &rate_limited_databases,
            &updated_databases,
            &up_to_date_databases,
        )
    });
    UpdateResult {
        status,
        stdout,
        stderr,
        exit_code,
        databases_updated: updated_databases.len(),
        error_message,
        update_method: UpdateMethod::Manual,
        updated_databases,
        up_to_date_databases,
        rate_limited_databases,
    }
}

fn systemd_unit_exists(name: &str) -> bool {
    run_host(
        "systemctl",
        &[
            "show".to_owned(),
            "-p".to_owned(),
            "LoadState".to_owned(),
            "--value".to_owned(),
            name.to_owned(),
        ],
        Some(5),
    )
    .map(|output| {
        output.status.success() && String::from_utf8_lossy(&output.stdout).trim() == "loaded"
    })
    .unwrap_or(false)
}

pub fn freshclam_service() -> (FreshclamServiceStatus, Option<String>) {
    let mut encountered_error = false;
    for name in SERVICE_NAMES {
        let output = run_host(
            "systemctl",
            &["is-active".to_owned(), name.to_owned()],
            Some(5),
        );
        let Ok(output) = output else {
            encountered_error = true;
            continue;
        };
        let state = String::from_utf8_lossy(&output.stdout)
            .trim()
            .to_ascii_lowercase();
        if output.status.success() && state == "active" {
            let pid = run_host("pidof", &["freshclam".to_owned()], Some(5))
                .ok()
                .filter(|output| output.status.success())
                .and_then(|output| {
                    String::from_utf8_lossy(&output.stdout)
                        .split_whitespace()
                        .next()
                        .map(str::to_owned)
                });
            return (FreshclamServiceStatus::Running, pid);
        }
        if matches!(
            state.as_str(),
            "inactive" | "failed" | "activating" | "deactivating"
        ) && systemd_unit_exists(name)
        {
            return (FreshclamServiceStatus::Stopped, None);
        }
    }
    if encountered_error {
        (FreshclamServiceStatus::Unknown, None)
    } else {
        (FreshclamServiceStatus::NotFound, None)
    }
}

fn pidof_freshclam() -> Option<String> {
    run_host("pidof", &["freshclam".to_owned()], Some(5))
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| {
            String::from_utf8_lossy(&output.stdout)
                .split_whitespace()
                .next()
                .map(str::to_owned)
        })
}

fn signal_service(ctx: &Context, pid: &str) -> AppResult<String> {
    let signal = run_host(
        "kill",
        &["-s".to_owned(), "SIGUSR1".to_owned(), pid.to_owned()],
        Some(5),
    )
    .map_err(|error| format!("Error sending signal: {error}"))?;
    let message = || {
        crate::i18n::translate(
            ctx,
            // Translators: Keep `freshclam` and `PID` unchanged; preserve `{pid}` as the process identifier.
            "Update signal sent to freshclam service (PID {pid})",
        )
        .replace("{pid}", pid)
    };
    if signal.status.success() {
        return Ok(message());
    }
    let stderr = String::from_utf8_lossy(&signal.stderr).trim().to_owned();
    let Some(pkexec) = host_binary("pkexec") else {
        return Err(format!("Failed to send signal: {stderr}"));
    };
    let signal = run_host(
        &pkexec,
        &[
            "kill".to_owned(),
            "-s".to_owned(),
            "SIGUSR1".to_owned(),
            pid.to_owned(),
        ],
        Some(30),
    )
    .map_err(|error| format!("Error sending elevated signal: {error}"))?;
    if signal.status.success() {
        Ok(message())
    } else {
        Err(format!(
            "Failed to send signal: {}",
            String::from_utf8_lossy(&signal.stderr).trim()
        ))
    }
}

pub fn force_update_script() -> &'static str {
    r#"set -eu
d=$1
freshclam=$2
config=${3:-}
staging=
backup=
staged_manifest=
original_manifest=
promoting=0
freshclam_pid=
rollback() {
  [ "$promoting" -eq 1 ] || return 0
  while IFS= read -r name; do [ -z "$name" ] || rm -f -- "$d/$name"; done < "$staged_manifest"
  if [ -f "$original_manifest" ]; then while IFS= read -r name; do [ -z "$name" ] || { mv -f -- "$backup/$name" "$d/$name" || cp -p -- "$backup/$name" "$d/$name"; }; done < "$original_manifest"; fi
}
cleanup() { rc=$?; trap '' HUP INT QUIT TERM; trap - 0; [ "$promoting" -eq 0 ] || rollback || rc=1; [ -z "$staging" ] || rm -rf -- "$staging"; exit "$rc"; }
trap cleanup 0
trap 'exit 130' INT TERM HUP QUIT
[ -d "$d" ] || exit 1
mode=$(stat -c '%a' "$d")
owner=$(stat -c '%u' "$d")
group=$(stat -c '%g' "$d")
staging=$(mktemp -d "$d/.clamui-force-update.XXXXXX")
chmod "$mode" "$staging"
chown "$owner:$group" "$staging"
if [ -n "$config" ]; then "$freshclam" "$config" --datadir="$staging" --verbose & else "$freshclam" --datadir="$staging" --verbose & fi
freshclam_pid=$!
wait "$freshclam_pid"
freshclam_pid=
for f in "$staging"/*.cvd "$staging"/*.cld "$staging"/*.cud; do [ -f "$f" ] && break; done
[ -f "$f" ] || exit 1
backup="$staging/.original"
original_manifest="$staging/.originals"
staged_manifest="$staging/.staged"
mkdir "$backup"
for f in "$d"/*.cvd "$d"/*.cld "$d"/*.cud; do [ -f "$f" ] || continue; name=${f##*/}; cp -p -- "$f" "$backup/$name"; printf '%s\n' "$name" >> "$original_manifest"; done
for f in "$staging"/*.cvd "$staging"/*.cld "$staging"/*.cud; do [ -f "$f" ] || continue; printf '%s\n' "${f##*/}" >> "$staged_manifest"; done
promoting=1
for f in "$staging"/*.cvd "$staging"/*.cld "$staging"/*.cud; do [ -f "$f" ] || continue; mv -f -- "$f" "$d/${f##*/}"; done
for f in "$d"/*.cvd "$d"/*.cld "$d"/*.cud; do [ -f "$f" ] || continue; grep -Fxq "${f##*/}" "$staged_manifest" || rm -f -- "$f"; done
promoting=0
command -v clamdscan >/dev/null 2>&1 && clamdscan --reload >/dev/null 2>&1 || :
"#
}

fn update_command(force: bool, config_path: Option<&str>) -> AppResult<Command> {
    let freshclam =
        host_binary("freshclam").ok_or_else(|| "freshclam executable not found".to_owned())?;
    let config = config_path.map(|path| format!("--config-file={path}"));
    if force {
        let database_dir = freshclam_database_dir(config_path);
        let mut args = vec![
            "-c".to_owned(),
            force_update_script().to_owned(),
            "clamui-force-update".to_owned(),
            database_dir,
            freshclam,
        ];
        args.push(config.unwrap_or_default());
        if let Some(pkexec) = host_binary("pkexec") {
            return Ok(host_command(
                &pkexec,
                &[
                    "sh".to_owned(),
                    args[0].clone(),
                    args[1].clone(),
                    args[2].clone(),
                    args[3].clone(),
                    args[4].clone(),
                    args[5].clone(),
                ],
            ));
        }
        return Ok(host_command("sh", &args));
    }
    let mut args = vec![freshclam];
    if let Some(config) = config {
        args.push(config);
    }
    args.push("--verbose".to_owned());
    if let Some(pkexec) = host_binary("pkexec") {
        Ok(host_command(&pkexec, &args))
    } else {
        Ok(host_command(&args[0], &args[1..]))
    }
}

#[cfg(unix)]
fn isolate_process_group(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    command.process_group(0);
}
#[cfg(not(unix))]
fn isolate_process_group(_command: &mut Command) {}

fn terminate_group(pid: u32, signal: &str) {
    let _ = run_host(
        "kill",
        &[
            "-s".to_owned(),
            signal.to_owned(),
            "--".to_owned(),
            format!("-{pid}"),
        ],
        Some(5),
    );
}

enum UpdateOutput {
    Bytes(bool, Vec<u8>),
    End(bool),
}

fn pipe_output<R: Read + Send + 'static>(
    mut reader: R,
    stderr: bool,
    sender: mpsc::Sender<UpdateOutput>,
    last_activity: Arc<Mutex<Instant>>,
) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let mut buffer = [0; 8192];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(count) => {
                    *last_activity
                        .lock()
                        .unwrap_or_else(|error| error.into_inner()) = Instant::now();
                    if sender
                        .send(UpdateOutput::Bytes(stderr, buffer[..count].to_vec()))
                        .is_err()
                    {
                        return;
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => break,
            }
        }
        let _ = sender.send(UpdateOutput::End(stderr));
    })
}

#[derive(Default)]
struct UpdateOutputBuffer {
    stdout: String,
    stderr: String,
    stdout_pending: Vec<u8>,
    stderr_pending: Vec<u8>,
}

impl UpdateOutputBuffer {
    fn receive(&mut self, ctx: &Context, id: &str, output: UpdateOutput) {
        let (is_stderr, bytes, finished) = match output {
            UpdateOutput::Bytes(is_stderr, bytes) => (is_stderr, bytes, false),
            UpdateOutput::End(is_stderr) => (is_stderr, Vec::new(), true),
        };
        let pending = if is_stderr {
            &mut self.stderr_pending
        } else {
            &mut self.stdout_pending
        };
        let search_from = pending.len();
        pending.extend_from_slice(&bytes);
        let mut start = 0;
        for (index, byte) in pending.iter().enumerate().skip(search_from) {
            if *byte == b'\n' {
                let mut line = &pending[start..index];
                if line.last() == Some(&b'\r') {
                    line = &line[..line.len() - 1];
                }
                append_update_line(
                    ctx,
                    id,
                    &mut self.stdout,
                    &mut self.stderr,
                    (is_stderr, String::from_utf8_lossy(line).as_ref()),
                );
                start = index + 1;
            }
        }
        if start != 0 {
            pending.drain(..start);
        }
        if finished && !pending.is_empty() {
            let line = String::from_utf8_lossy(pending);
            append_update_line(
                ctx,
                id,
                &mut self.stdout,
                &mut self.stderr,
                (is_stderr, line.as_ref()),
            );
            pending.clear();
        }
    }

    fn finish(&mut self, ctx: &Context, id: &str) {
        self.receive(ctx, id, UpdateOutput::End(false));
        self.receive(ctx, id, UpdateOutput::End(true));
    }
}

fn append_update_line(
    ctx: &Context,
    id: &str,
    stdout: &mut String,
    stderr: &mut String,
    (is_stderr, line): (bool, &str),
) {
    ctx.emit(
        "update-progress",
        json!({"id": id, "line": sanitize_line(line)}),
    );
    let target = if is_stderr { stderr } else { stdout };
    target.push_str(line);
    target.push('\n');
}

fn drain_update_output(
    ctx: &Context,
    id: &str,
    receiver: &mpsc::Receiver<UpdateOutput>,
    output: &mut UpdateOutputBuffer,
    wait: Duration,
) -> bool {
    let deadline = Instant::now() + wait;
    loop {
        if Instant::now() >= deadline {
            return false;
        }
        match receiver.recv_timeout(Duration::from_millis(50)) {
            Ok(chunk) => output.receive(ctx, id, chunk),
            Err(mpsc::RecvTimeoutError::Disconnected) => return true,
            Err(mpsc::RecvTimeoutError::Timeout) => {}
        }
    }
}

fn join_readers(readers: Vec<thread::JoinHandle<()>>) {
    for reader in readers {
        let _ = reader.join();
    }
}

fn run_manual(
    ctx: &Context,
    id: &str,
    force: bool,
    config_path: Option<&str>,
    cancelled: &std::sync::atomic::AtomicBool,
) -> UpdateResult {
    if let Some(pid) = pidof_freshclam() {
        return UpdateResult::error(
            crate::i18n::translate(
                ctx,
                // Translators: Keep `freshclam`, `PID`, and `sudo systemctl stop clamav-freshclam` unchanged; preserve `{pid}` as the process identifier.
                "Another freshclam instance is running (PID {pid}). Stop it first: sudo systemctl stop clamav-freshclam",
            )
            .replace("{pid}", &pid),
        );
    }
    let command = match update_command(force, config_path) {
        Ok(command) => command,
        Err(error) => return UpdateResult::error(error),
    };
    let settings = ctx.settings().unwrap_or(Value::Null);
    let minutes = crate::settings::update_inactivity_timeout_minutes(&settings);
    run_update_command(
        ctx,
        id,
        command,
        cancelled,
        Duration::from_secs(minutes * 60),
        minutes,
    )
}

fn timeout_result(
    ctx: &Context,
    output: UpdateOutputBuffer,
    exit_code: i32,
    minutes: u64,
) -> UpdateResult {
    let message = trnf(
        ctx,
        "Update timed out after {minutes} minute without output",
        "Update timed out after {minutes} minutes without output",
        minutes,
        &[("{minutes}", &minutes.to_string())],
    );
    let mut result = UpdateResult::error(message);
    result.stdout = sanitize_text(&output.stdout);
    result.stderr = sanitize_text(&output.stderr);
    result.exit_code = exit_code;
    result
}

fn run_update_command(
    ctx: &Context,
    id: &str,
    mut command: Command,
    cancelled: &std::sync::atomic::AtomicBool,
    inactivity_timeout: Duration,
    timeout_minutes: u64,
) -> UpdateResult {
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    isolate_process_group(&mut command);
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => return UpdateResult::error(format!("Update failed: {error}")),
    };
    let (sender, receiver) = mpsc::channel();
    let mut readers = Vec::new();
    let last_activity = Arc::new(Mutex::new(Instant::now()));
    if let Some(stdout) = child.stdout.take() {
        readers.push(pipe_output(
            stdout,
            false,
            sender.clone(),
            Arc::clone(&last_activity),
        ));
    }
    if let Some(stderr) = child.stderr.take() {
        readers.push(pipe_output(
            stderr,
            true,
            sender.clone(),
            Arc::clone(&last_activity),
        ));
    }
    drop(sender);
    let mut output = UpdateOutputBuffer::default();
    let mut terminated = None;
    let mut killed = false;
    let mut timed_out = false;
    loop {
        for _ in 0..256 {
            match receiver.try_recv() {
                Ok(chunk) => output.receive(ctx, id, chunk),
                Err(_) => break,
            }
        }
        let should_terminate = cancelled.load(std::sync::atomic::Ordering::Acquire)
            || last_activity
                .lock()
                .unwrap_or_else(|error| error.into_inner())
                .elapsed()
                >= inactivity_timeout;
        if should_terminate && terminated.is_none() {
            timed_out = !cancelled.load(std::sync::atomic::Ordering::Acquire);
            terminate_group(child.id(), "TERM");
            terminated = Some(Instant::now());
        }
        match child.try_wait() {
            Ok(Some(status)) => {
                let output_complete = if let Some(terminated_at) = terminated {
                    if !killed {
                        let remaining = TERMINATE_GRACE.saturating_sub(terminated_at.elapsed());
                        if !remaining.is_zero() {
                            thread::sleep(remaining);
                        }
                        terminate_group(child.id(), "KILL");
                    }
                    drain_update_output(ctx, id, &receiver, &mut output, KILL_WAIT)
                } else {
                    let drained =
                        drain_update_output(ctx, id, &receiver, &mut output, OUTPUT_DRAIN_GRACE);
                    if drained {
                        true
                    } else {
                        terminate_group(child.id(), "KILL");
                        drain_update_output(ctx, id, &receiver, &mut output, KILL_WAIT)
                    }
                };
                if output_complete {
                    join_readers(readers);
                }
                output.finish(ctx, id);
                let code = status.code().unwrap_or(-1);
                if cancelled.load(std::sync::atomic::Ordering::Acquire) {
                    return UpdateResult::cancelled(output.stdout, output.stderr, code);
                }
                if timed_out {
                    return timeout_result(ctx, output, code, timeout_minutes);
                }
                if !output_complete {
                    return UpdateResult::output_incomplete(output.stdout, output.stderr, code);
                }
                return interpret_result(output.stdout, output.stderr, code);
            }
            Ok(None) if terminated.is_some_and(|at| at.elapsed() >= TERMINATE_GRACE) && !killed => {
                terminate_group(child.id(), "KILL");
                killed = true;
                thread::sleep(KILL_WAIT);
                if child.try_wait().ok().flatten().is_none() {
                    if drain_update_output(ctx, id, &receiver, &mut output, KILL_WAIT) {
                        join_readers(readers);
                    }
                    output.finish(ctx, id);
                    return if cancelled.load(std::sync::atomic::Ordering::Acquire) {
                        UpdateResult::cancelled(output.stdout, output.stderr, -1)
                    } else {
                        timeout_result(ctx, output, -1, timeout_minutes)
                    };
                }
            }
            Ok(None) => thread::sleep(Duration::from_millis(50)),
            Err(error) => {
                terminate_group(child.id(), "KILL");
                if drain_update_output(ctx, id, &receiver, &mut output, KILL_WAIT) {
                    join_readers(readers);
                }
                return UpdateResult::error(format!("Update failed: {error}"));
            }
        }
    }
}

fn save_log(ctx: &Context, result: &UpdateResult, duration: Duration) {
    let summary = match result.status {
        UpdateStatus::Success => {
            let count = result.databases_updated.to_string();
            trnf(
                ctx,
                // Translators: The em dash separates the completion state from the count; preserve `{count}`.
                "Database update completed — {count} database updated",
                // Translators: The em dash separates the completion state from the count; preserve `{count}`.
                "Database update completed — {count} databases updated",
                result.databases_updated as u64,
                &[("{count}", &count)],
            )
        }
        UpdateStatus::UpToDate => crate::i18n::translate(
            ctx,
            // Translators: The em dash separates the completion state from the result.
            "Database update completed — Already up to date",
        ),
        UpdateStatus::Cancelled => "Database update cancelled".to_owned(),
        UpdateStatus::Error => format!(
            "Database update failed: {}",
            result.error_message.as_deref().unwrap_or("Unknown error")
        ),
    };
    let details = match (result.stdout.is_empty(), result.stderr.is_empty()) {
        (true, true) => "(No output)".to_owned(),
        (false, true) => result.stdout.clone(),
        (true, false) => format!("--- Errors ---\n{}", result.stderr),
        (false, false) => format!("{}\n--- Errors ---\n{}", result.stdout, result.stderr),
    };
    let _ = crate::logs::save(
        ctx,
        json!({"type":"update","status":result.status,"summary":sanitize_line(&summary),"details":sanitize_text(&details),"duration":duration.as_secs_f64(),"scheduled":false}),
    );
}

fn selected_config(ctx: &Context, requested: Option<&str>) -> Option<String> {
    if let Some(requested) = requested {
        return Some(requested.to_owned());
    }
    let configured = ctx.settings().ok().and_then(|settings| {
        settings
            .get("freshclam_conf_path")
            .and_then(Value::as_str)
            .filter(|path| !path.is_empty())
            .map(str::to_owned)
    });
    resolve_freshclam_conf_path(configured.as_deref())
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "status" => {
            let config = selected_config(ctx, args.get("config_path").and_then(Value::as_str));
            let probe = check_tool("freshclam");
            let (status, pid) = freshclam_service();
            Ok(json!({
                "freshclam":{"installed":probe.available,"version_or_error":probe.detail,"path":probe.path},
                "service":{"status":status,"pid":pid},
                "database":database_status(config.as_deref())
            }))
        }
        "cancel" => {
            let id = args.get("id").and_then(Value::as_str).unwrap_or("update");
            Ok(json!({"id":id,"cancelled":ctx.cancel(id)}))
        }
        "update" => {
            let id = args
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("update")
                .to_owned();
            let force = args.get("force").and_then(Value::as_bool).unwrap_or(false);
            let prefer_service = args
                .get("prefer_service")
                .and_then(Value::as_bool)
                .unwrap_or(true);
            let config = selected_config(ctx, args.get("config_path").and_then(Value::as_str));
            if let Some(path) = config.as_deref() {
                if !config_file_exists(path) {
                    return Err(crate::i18n::translate(
                        ctx,
                        "Selected freshclam config does not exist: {path}",
                    )
                    .replace("{path}", path));
                }
            }
            let job = ctx.job(&id)?;
            let started = Instant::now();
            let availability = check_tool("freshclam");
            if !availability.available {
                let mut result = UpdateResult::error(
                    availability
                        .detail
                        .unwrap_or_else(|| "freshclam not installed".to_owned()),
                );
                localize_result(ctx, &mut result);
                save_log(ctx, &result, started.elapsed());
                let value = serde_json::to_value(&result)
                    .map_err(|error| format!("Cannot serialize update result: {error}"))?;
                ctx.emit("update-complete", json!({"id":id,"result":value.clone()}));
                return Ok(value);
            }
            let service_default = detect_freshclam_conf_path();
            let custom_config = config.as_deref() != service_default.as_deref();
            let mut result = if !force && prefer_service && !custom_config {
                let (service, pid) = freshclam_service();
                if service == FreshclamServiceStatus::Running {
                    match pid
                        .or_else(pidof_freshclam)
                        .as_deref()
                        .ok_or_else(|| {
                            crate::i18n::translate(
                                ctx,
                                // Translators: Keep `freshclam` and `PID` unchanged; they name the service and its process identifier.
                                "Could not determine freshclam PID",
                            )
                        })
                        .and_then(|service_pid| signal_service(ctx, service_pid))
                    {
                        Ok(message) => UpdateResult { status: UpdateStatus::Success, stdout: message, stderr: String::new(), exit_code: 0, databases_updated: 0, error_message: None, update_method: UpdateMethod::ServiceSignal, updated_databases: Vec::new(), up_to_date_databases: Vec::new(), rate_limited_databases: BTreeMap::new() },
                        Err(error) => UpdateResult::error(
                            crate::i18n::translate(
                                ctx,
                                // Translators: Keep `sudo systemctl restart clamav-freshclam` unchanged and preserve `{error}` as the raw diagnostic.
                                "Could not trigger freshclam service update. Try restarting the service: sudo systemctl restart clamav-freshclam ({error})",
                            )
                            .replace("{error}", &error),
                        ),
                    }
                } else {
                    run_manual(ctx, &id, force, config.as_deref(), &job.cancelled)
                }
            } else {
                run_manual(ctx, &id, force, config.as_deref(), &job.cancelled)
            };
            if result.update_method == UpdateMethod::ServiceSignal {
                result.databases_updated = 0;
            }
            localize_result(ctx, &mut result);
            save_log(ctx, &result, started.elapsed());
            let value = serde_json::to_value(&result)
                .map_err(|error| format!("Cannot serialize update result: {error}"))?;
            ctx.emit("update-complete", json!({"id":id,"result":value.clone()}));
            Ok(value)
        }
        _ => Err(format!("Unknown updater action: {action}")),
    }
}

#[cfg(test)]
mod tests {
    use super::{pipe_output, run_update_command, UpdateOutputBuffer, UpdateStatus};
    use crate::{Context, Paths};
    use std::io::Cursor;
    use std::process::Command;
    use std::sync::atomic::AtomicBool;
    use std::sync::{mpsc, Arc, Mutex};
    use std::time::{Duration, Instant};

    fn context(root: &std::path::Path) -> Context {
        Context::with_paths(Paths {
            home: root.join("home"),
            config_dir: root.join("config"),
            data_dir: root.join("data"),
        })
        .unwrap()
    }

    #[test]
    fn pipe_reader_delivers_final_line_before_eof() {
        let root = tempfile::tempdir().unwrap();
        let ctx = context(root.path());
        let (sender, receiver) = mpsc::channel();
        let reader = pipe_output(
            Cursor::new(b"final update marker\n".to_vec()),
            false,
            sender,
            Arc::new(Mutex::new(Instant::now())),
        );
        let mut output = UpdateOutputBuffer::default();
        while let Ok(chunk) = receiver.recv() {
            output.receive(&ctx, "test", chunk);
        }
        reader.join().unwrap();
        assert_eq!(output.stdout, "final update marker\n");
    }

    #[test]
    fn raw_partial_stdout_and_stderr_keep_long_updates_alive() {
        let root = tempfile::tempdir().unwrap();
        let ctx = context(root.path());
        for (script, is_stderr) in [
            (
                "for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do printf 'part\\r'; sleep 0.1; done",
                false,
            ),
            (
                "for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do printf 'part\\r' >&2; sleep 0.1; done",
                true,
            ),
        ] {
            let mut command = Command::new("sh");
            command.args(["-c", script]);
            let started = Instant::now();
            let result = run_update_command(
                &ctx,
                "active",
                command,
                &AtomicBool::new(false),
                Duration::from_secs(1),
                1,
            );
            assert_eq!(result.status, UpdateStatus::UpToDate, "{result:?}");
            assert!(started.elapsed() > Duration::from_secs(1));
            let stream = if is_stderr {
                &result.stderr
            } else {
                &result.stdout
            };
            assert_eq!(stream, &format!("{}\n", "part\r".repeat(15)));
        }
    }

    #[test]
    fn inactivity_after_streams_close_stops_process_and_preserves_diagnostics() {
        let root = tempfile::tempdir().unwrap();
        let ctx = context(root.path());
        let mut command = Command::new("sh");
        command.args([
            "-c",
            "printf '\\033[31mpartial\\033[0m'; printf '\\033[31merror\\033[0m' >&2; exec 1>&- 2>&-; sleep 30",
        ]);
        let started = Instant::now();
        let result = run_update_command(
            &ctx,
            "idle",
            command,
            &AtomicBool::new(false),
            Duration::from_millis(300),
            2,
        );
        assert_eq!(result.status, UpdateStatus::Error);
        assert_ne!(result.exit_code, 0);
        assert!(started.elapsed() < Duration::from_secs(15));
        assert!(result.error_message.is_some());
        assert_eq!(result.stdout, "partial\n");
        assert_eq!(result.stderr, "error\n");
    }

    #[test]
    fn cancellation_is_scoped_and_kills_stubborn_process_group() {
        let root = tempfile::tempdir().unwrap();
        let ctx = context(root.path());
        let job = ctx.job("cancelled").unwrap();
        let other = ctx.job("other").unwrap();
        let marker = root.path().join("survived");
        let mut command = Command::new("sh");
        command
            .arg("-c")
            .arg("trap '' TERM; (sleep 7; printf leaked > \"$1\") & wait")
            .arg("sh")
            .arg(&marker);
        let cancelling = ctx.clone();
        let worker = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(300));
            assert!(cancelling.cancel("cancelled"));
        });
        let result = run_update_command(
            &ctx,
            "cancelled",
            command,
            &job.cancelled,
            Duration::from_secs(20),
            1,
        );
        worker.join().unwrap();
        assert_eq!(result.status, UpdateStatus::Cancelled);
        assert!(!other.cancelled.load(std::sync::atomic::Ordering::Acquire));
        assert!(!marker.exists());
    }

    #[test]
    fn incomplete_output_is_an_error_with_partial_diagnostics() {
        let result = super::UpdateResult::output_incomplete(
            "final marker was not observed".to_owned(),
            "reader remained open".to_owned(),
            0,
        );

        assert_eq!(result.status, super::UpdateStatus::Error);
        assert_eq!(result.exit_code, 0);
        assert_eq!(result.stdout, "final marker was not observed");
        assert_eq!(result.stderr, "reader remained open");
        assert!(result
            .error_message
            .as_deref()
            .is_some_and(|message| message.contains("cannot be classified")));
    }
}
