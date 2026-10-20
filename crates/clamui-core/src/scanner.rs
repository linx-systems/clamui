use crate::common::{host_command, path_to_wire, Context, Job};
use crate::scan_parser::{interpret_clamscan, interpret_daemon};
use crate::AppResult;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::ffi::OsStr;
use std::fs::{self, OpenOptions};
use std::io::{BufReader, Read, Write};
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::sync::{LazyLock, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const OUTPUT_LIMIT: usize = 64 * 1024 * 1024;
const EICAR: &[u8] = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*";
static REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct DaemonAvailability {
    checked_at: Instant,
    config_path: Option<String>,
    available: bool,
}

static DAEMON_AVAILABILITY: LazyLock<Mutex<Option<DaemonAvailability>>> =
    LazyLock::new(|| Mutex::new(None));

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ScanStatus {
    Clean,
    Infected,
    Error,
    Cancelled,
}

impl ScanStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Clean => "clean",
            Self::Infected => "infected",
            Self::Error => "error",
            Self::Cancelled => "cancelled",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ThreatDetail {
    pub file_path: String,
    pub threat_name: String,
    pub category: String,
    pub severity: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ScanProgress {
    pub current_file: String,
    pub files_scanned: u64,
    pub files_total: Option<u64>,
    /// Compatibility alias for consumers that adopted the UI wording.
    pub total_files: Option<u64>,
    pub infected_count: u64,
    pub new_threats: Vec<ThreatDetail>,
    pub bytes_scanned: u64,
    pub estimate_exceeded: bool,
    pub percentage: Option<f64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ScanResult {
    pub status: ScanStatus,
    pub path: String,
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
    pub infected_files: Vec<String>,
    pub scanned_files: u64,
    pub scanned_dirs: u64,
    pub infected_count: u64,
    pub error_message: Option<String>,
    pub threat_details: Vec<ThreatDetail>,
    pub skipped_files: Vec<String>,
    pub skipped_count: u64,
    pub warning_message: Option<String>,
    pub nonfatal_warnings: Vec<String>,
    pub backend: String,
}

impl ScanResult {
    fn error(path: impl Into<String>, message: impl Into<String>, backend: &str) -> Self {
        let message = message.into();
        Self {
            status: ScanStatus::Error,
            path: path.into(),
            stdout: String::new(),
            stderr: message.clone(),
            exit_code: -1,
            infected_files: Vec::new(),
            scanned_files: 0,
            scanned_dirs: 0,
            infected_count: 0,
            error_message: Some(message),
            threat_details: Vec::new(),
            skipped_files: Vec::new(),
            skipped_count: 0,
            warning_message: None,
            nonfatal_warnings: Vec::new(),
            backend: backend.into(),
        }
    }

    fn cancelled(
        path: impl Into<String>,
        output: CapturedOutput,
        backend: &str,
        progress: ProgressState,
    ) -> Self {
        Self {
            status: ScanStatus::Cancelled,
            path: path.into(),
            stdout: display_stdout(&output),
            stderr: output.stderr,
            exit_code: output.exit_code,
            infected_files: progress
                .threats
                .iter()
                .map(|threat| threat.file_path.clone())
                .collect(),
            scanned_files: progress.files_scanned,
            scanned_dirs: 0,
            infected_count: progress.threats.len() as u64,
            error_message: Some("Scan cancelled by user".into()),
            threat_details: progress.threats,
            skipped_files: Vec::new(),
            skipped_count: 0,
            warning_message: None,
            nonfatal_warnings: Vec::new(),
            backend: backend.into(),
        }
    }
}

#[derive(Deserialize)]
struct ScanRequest {
    id: Option<String>,
    paths: Vec<String>,
    #[serde(default = "default_recursive")]
    recursive: bool,
    profile_id: Option<String>,
    profile_name: Option<String>,
    backend_override: Option<String>,
    #[serde(default)]
    force_stream: bool,
    exclusions: Option<Value>,
    #[serde(default)]
    scheduled: bool,
}

fn default_recursive() -> bool {
    true
}

#[derive(Default)]
struct Exclusions {
    directories: Vec<String>,
    patterns: Vec<String>,
}

#[derive(Default)]
struct TargetCount {
    files: u64,
    directories: u64,
    file_paths: Vec<PathBuf>,
}

struct CapturedOutput {
    stdout_bytes: Vec<u8>,
    stdout_truncated: bool,
    stderr: String,
    exit_code: i32,
    cancelled: bool,
}

struct CapturedStream {
    bytes: Vec<u8>,
    truncated: bool,
}
#[derive(Default)]
struct ProgressState {
    files_scanned: u64,
    infected_paths: HashSet<String>,
    threats: Vec<ThreatDetail>,
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "status" => status(ctx),
        "scan" => scan(
            ctx,
            serde_json::from_value(args)
                .map_err(|error| format!("Invalid scanner.scan arguments: {error}"))?,
        ),
        "cancel" => {
            let id = args
                .get("id")
                .and_then(Value::as_str)
                .ok_or_else(|| "scanner.cancel requires id".to_owned())?;
            Ok(json!({"id": id, "cancelled": ctx.cancel(id)}))
        }
        "eicar" => eicar(ctx, args),
        _ => Err(format!("Unknown scanner action: {action}")),
    }
}

fn status(ctx: &Context) -> AppResult<Value> {
    let configured_backend = ctx
        .settings()?
        .get("scan_backend")
        .and_then(Value::as_str)
        .unwrap_or("auto")
        .to_owned();
    let clamscan = probe_program("clamscan", &["--version"]);
    let clamdscan = probe_program("clamdscan", &["--version"]);
    let daemon_ping = if clamdscan.available {
        probe_clamd(ctx, &["--ping", "1"])
    } else {
        ProgramProbe::unavailable(
            clamdscan
                .error
                .clone()
                .unwrap_or_else(|| "clamdscan unavailable".into()),
        )
    };
    let daemon_available = clamdscan.available && daemon_ping.available;
    let (backend, available, error) = match configured_backend.as_str() {
        "clamscan" => ("clamscan", clamscan.available, clamscan.error.clone()),
        "daemon" => (
            if daemon_available {
                "daemon"
            } else {
                "unavailable"
            },
            daemon_available,
            if daemon_available {
                None
            } else {
                daemon_ping.error.clone().or(clamdscan.error.clone())
            },
        ),
        _ => {
            if daemon_available {
                ("daemon", true, None)
            } else {
                ("clamscan", clamscan.available, clamscan.error.clone())
            }
        }
    };
    let database = database_status(ctx);
    let database_available = daemon_available
        || database
            .get("available")
            .and_then(Value::as_bool)
            .unwrap_or(false);
    let database_error = (!database_available).then(|| {
        crate::i18n::translate(
            ctx,
            "No ClamAV database files were found in standard host locations",
        )
    });
    Ok(json!({
        "available": available,
        "version": if backend == "daemon" { clamdscan.version.clone() } else { clamscan.version.clone() },
        "error": error,
        "backend": backend,
        "active_backend": backend,
        "configured_backend": configured_backend,
        "database_available": database_available,
        "database_error": database_error,
        "daemon_status": {
            "available": daemon_available,
            "connected": daemon_ping.available,
            "clamdscan_available": clamdscan.available,
            "version": clamdscan.version.clone(),
            "message": daemon_ping.error.clone().or(clamdscan.error.clone()),
        },
        "clamscan": {"available": clamscan.available, "version": clamscan.version.clone(), "error": clamscan.error.clone()},
        "database": database,
    }))
}

fn scan(ctx: &Context, request: ScanRequest) -> AppResult<Value> {
    if request.paths.is_empty() {
        return Err("scanner.scan requires at least one path".into());
    }
    let exclusions = merged_exclusions(ctx, &request)?;
    let id = request.id.unwrap_or_else(new_scan_id);
    let job = ctx.job(&id)?;
    let started = Instant::now();
    let configured = request
        .backend_override
        .clone()
        .unwrap_or_else(|| configured_backend(ctx));
    if !matches!(configured.as_str(), "auto" | "daemon" | "clamscan") {
        return Err("backend_override must be auto, daemon, or clamscan".into());
    }
    let selected_backend = select_backend(ctx, &configured);
    let mut results = Vec::with_capacity(request.paths.len());

    for (index, path) in request.paths.iter().enumerate() {
        if job.cancelled.load(Ordering::Acquire) {
            let mut result = ScanResult::cancelled(
                path,
                CapturedOutput {
                    stdout_bytes: Vec::new(),
                    stdout_truncated: false,
                    stderr: String::new(),
                    exit_code: -1,
                    cancelled: true,
                },
                &selected_backend,
                ProgressState::default(),
            );
            localize_result(ctx, &mut result);
            results.push(result);
            continue;
        }
        let mut result = scan_target(
            ctx,
            &job,
            path,
            request.recursive,
            &selected_backend,
            request.force_stream,
            &exclusions,
        );
        localize_result(ctx, &mut result);
        results.push(result);
        if job.cancelled.load(Ordering::Acquire) {
            for skipped in request.paths.iter().skip(index + 1) {
                let mut result = ScanResult::cancelled(
                    skipped,
                    CapturedOutput {
                        stdout_bytes: Vec::new(),
                        stdout_truncated: false,
                        stderr: String::new(),
                        exit_code: -1,
                        cancelled: true,
                    },
                    &selected_backend,
                    ProgressState::default(),
                );
                localize_result(ctx, &mut result);
                results.push(result);
            }
            break;
        }
    }
    let aggregate = aggregate_result(&id, results, started.elapsed(), request.scheduled);
    save_result(ctx, &aggregate, request.scheduled)?;
    let value = serde_json::to_value(&aggregate).map_err(|error| error.to_string())?;
    ctx.emit("scan-complete", json!({"id": id, "result": value}));
    Ok(value)
}

fn eicar(ctx: &Context, args: Value) -> AppResult<Value> {
    let id = args
        .get("id")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .unwrap_or_else(new_scan_id);
    fs::create_dir_all(&ctx.paths.data_dir)
        .map_err(|error| format!("Unable to create EICAR temporary directory: {error}"))?;
    let filename = ctx.paths.data_dir.join(format!(
        ".clamui-eicar-{}",
        REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&filename)
        .map_err(|error| format!("Unable to create temporary EICAR file: {error}"))?;
    let scan = (|| {
        file.write_all(EICAR)
            .map_err(|error| format!("Unable to write temporary EICAR file: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("Unable to sync temporary EICAR file: {error}"))?;
        drop(file);
        scan(
            ctx,
            ScanRequest {
                id: Some(id),
                paths: vec![filename.to_string_lossy().into_owned()],
                recursive: false,
                profile_id: None,
                profile_name: None,
                backend_override: args
                    .get("backend_override")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                force_stream: args
                    .get("force_stream")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                exclusions: None,
                scheduled: false,
            },
        )
    })();
    let _ = fs::remove_file(&filename);
    scan
}

fn scan_target(
    ctx: &Context,
    job: &Job,
    raw_path: &str,
    recursive: bool,
    backend: &str,
    force_stream: bool,
    exclusions: &Exclusions,
) -> ScanResult {
    let path = match scan_path_from_wire(ctx, raw_path) {
        Ok(path) => path,
        Err(error) => return ScanResult::error(raw_path, error, backend),
    };
    if raw_path.contains('\0') || !path.exists() {
        return ScanResult::error(
            raw_path,
            "Scan target does not exist or contains an invalid NUL byte",
            backend,
        );
    }
    let count = if backend != "daemon" && is_root_level(&path) {
        TargetCount::default()
    } else {
        match count_targets(&path, exclusions, &job.cancelled) {
            Ok(count) => count,
            Err(error) => return ScanResult::error(raw_path, error, backend),
        }
    };
    if job.cancelled.load(Ordering::Acquire) {
        return ScanResult::cancelled(
            raw_path,
            CapturedOutput {
                stdout_bytes: Vec::new(),
                stdout_truncated: false,
                stderr: String::new(),
                exit_code: -1,
                cancelled: true,
            },
            backend,
            ProgressState::default(),
        );
    }

    let (command, args) = if backend == "daemon" {
        if count.files == 0 {
            return ScanResult {
                status: ScanStatus::Clean,
                path: raw_path.into(),
                stdout: String::new(),
                stderr: String::new(),
                exit_code: 0,
                infected_files: Vec::new(),
                scanned_files: 0,
                scanned_dirs: count.directories,
                infected_count: 0,
                error_message: None,
                threat_details: Vec::new(),
                skipped_files: Vec::new(),
                skipped_count: 0,
                warning_message: None,
                nonfatal_warnings: Vec::new(),
                backend: backend.into(),
            };
        }
        match daemon_arguments(ctx, &path, &count, force_stream) {
            Ok((program, arguments)) => (program, arguments),
            Err(error) => return ScanResult::error(raw_path, error, backend),
        }
    } else {
        (
            "clamscan".to_owned(),
            clamscan_arguments(ctx, &path, recursive, exclusions),
        )
    };
    let file_list = args
        .windows(2)
        .find(|arguments| arguments[0] == "--file-list")
        .map(|arguments| PathBuf::from(&arguments[1]));
    let mut progress = ProgressState::default();
    let total = if backend == "daemon" {
        Some(count.files)
    } else {
        Some(count.files).filter(|total| *total > 0)
    };
    let output = execute(&command, &args, &job.cancelled, |line| {
        update_progress(line, backend, &mut progress, total, |event| {
            let mut data = serde_json::to_value(event).unwrap_or(Value::Null);
            if let Some(object) = data.as_object_mut() {
                object.insert("id".into(), Value::String(job.id.clone()));
                object.insert("path".into(), Value::String(raw_path.into()));
                object.insert("backend".into(), Value::String(backend.into()));
            }
            ctx.emit("scan-progress", data);
        });
    });
    if let Some(file_list) = file_list {
        let _ = fs::remove_file(file_list);
    }
    let output = match output {
        Ok(output) => output,
        Err(error) => return ScanResult::error(raw_path, error, backend),
    };
    let stdout = display_stdout(&output);

    if output.cancelled {
        let daemon_precount_fallback = backend == "daemon" && progress.files_scanned == 0;
        let mut partial = if backend == "daemon" {
            interpret_daemon(
                raw_path,
                &stdout,
                &output.stderr,
                output.exit_code,
                if daemon_precount_fallback {
                    count.files
                } else {
                    progress.files_scanned
                },
                if daemon_precount_fallback {
                    count.directories
                } else {
                    0
                },
            )
        } else {
            interpret_clamscan(
                raw_path,
                &stdout,
                &output.stderr,
                output.exit_code,
                progress.files_scanned,
            )
        };
        restore_threat_paths(&mut partial, &output.stdout_bytes);
        for threat in partial.threat_details {
            if progress.infected_paths.insert(threat.file_path.clone()) {
                progress.files_scanned += 1;
                progress.threats.push(threat);
            }
        }
        let observed_files = progress.files_scanned;
        drop(stdout);

        let mut result = ScanResult::cancelled(raw_path, output, backend, progress);
        result.scanned_files = if backend == "daemon" && observed_files > 0 {
            observed_files
        } else {
            result.scanned_files.max(partial.scanned_files)
        };
        result.scanned_dirs = if backend == "daemon" && observed_files == 0 {
            partial.scanned_dirs
        } else {
            0
        };
        result.skipped_files = partial.skipped_files;
        result.skipped_count = partial.skipped_count;
        result.warning_message = partial.warning_message;
        result.nonfatal_warnings = partial.nonfatal_warnings;
        return result;
    }
    let mut result = if backend == "daemon" {
        interpret_daemon(
            raw_path,
            &stdout,
            &output.stderr,
            output.exit_code,
            count.files,
            count.directories,
        )
    } else {
        interpret_clamscan(
            raw_path,
            &stdout,
            &output.stderr,
            output.exit_code,
            progress.files_scanned,
        )
    };
    restore_threat_paths(&mut result, &output.stdout_bytes);
    result
}

fn configured_backend(ctx: &Context) -> String {
    ctx.settings()
        .ok()
        .and_then(|settings| {
            settings
                .get("scan_backend")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .unwrap_or_else(|| "auto".into())
}

fn select_backend(ctx: &Context, configured: &str) -> String {
    match configured {
        "clamscan" => "clamscan".into(),
        "daemon" => "daemon".into(),
        _ if daemon_usable(ctx) => "daemon".into(),
        _ => "clamscan".into(),
    }
}

fn clamd_config_path(ctx: &Context) -> Option<String> {
    crate::dispatch(ctx, "config.load", json!({"kind": "clamd"}))
        .ok()?
        .get("path")
        .and_then(Value::as_str)
        .filter(|path| !path.is_empty())
        .map(str::to_owned)
}

fn probe_clamd(ctx: &Context, arguments: &[&str]) -> ProgramProbe {
    let mut owned = Vec::new();
    if let Some(path) = clamd_config_path(ctx) {
        owned.extend(["--config-file".to_owned(), path]);
    }
    owned.extend(arguments.iter().map(|argument| (*argument).to_owned()));
    probe_program_owned("clamdscan", &owned)
}

fn daemon_usable(ctx: &Context) -> bool {
    let config = clamd_config_path(ctx);
    if let Ok(cache) = DAEMON_AVAILABILITY.lock() {
        if let Some(cache) = cache.as_ref() {
            if cache.config_path == config && cache.checked_at.elapsed() < Duration::from_secs(60) {
                return cache.available;
            }
        }
    }
    let available = probe_program("clamdscan", &["--version"]).available
        && probe_clamd(ctx, &["--ping", "1"]).available;
    if let Ok(mut cache) = DAEMON_AVAILABILITY.lock() {
        *cache = Some(DaemonAvailability {
            checked_at: Instant::now(),
            config_path: config,
            available,
        });
    }
    available
}

fn clamscan_arguments(
    ctx: &Context,
    path: &Path,
    recursive: bool,
    exclusions: &Exclusions,
) -> Vec<String> {
    let mut args = Vec::new();
    if recursive && path.is_dir() {
        args.push("-r".into());
    }
    args.push("-v".into());
    for (key, flag) in [
        ("MaxFileSize", "--max-filesize"),
        ("MaxScanSize", "--max-scansize"),
        ("MaxRecursion", "--max-recursion"),
        ("MaxFiles", "--max-files"),
    ] {
        if let Some(value) = clamd_limit(ctx, key) {
            args.push(format!("{flag}={value}"));
        }
    }
    for directory in &exclusions.directories {
        args.extend(["--exclude-dir".into(), directory_regex(directory)]);
    }
    for pattern in &exclusions.patterns {
        args.extend(["--exclude".into(), glob_regex(pattern)]);
    }
    args.push("--".into());
    args.push(path.to_string_lossy().into_owned());
    args
}

fn daemon_arguments(
    ctx: &Context,
    _path: &Path,
    count: &TargetCount,
    force_stream: bool,
) -> AppResult<(String, Vec<String>)> {
    if !probe_program("clamdscan", &["--version"]).available {
        return Err("clamdscan is not installed".into());
    }
    if !probe_clamd(ctx, &["--ping", "1"]).available {
        return Err("clamd is not accessible".into());
    }
    let list = write_private_file_list(ctx, &count.file_paths)?;
    let mut args = Vec::new();
    if let Some(path) = clamd_config_path(ctx) {
        args.extend(["--config-file".into(), path]);
    }
    if force_stream {
        args.push("--stream".into());
    } else {
        args.push("--fdpass".into());
    }
    args.push("-v".into());
    args.extend(["--file-list".into(), list.to_string_lossy().into_owned()]);
    Ok(("clamdscan".into(), args))
}

fn write_private_file_list(ctx: &Context, paths: &[PathBuf]) -> AppResult<PathBuf> {
    fs::create_dir_all(&ctx.paths.data_dir)
        .map_err(|error| format!("Unable to create private scan-list directory: {error}"))?;
    let sequence = REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let path = ctx.paths.data_dir.join(format!(
        ".clamui-clamdscan-{}-{sequence}.list",
        std::process::id()
    ));
    let result = (|| -> AppResult<()> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&path)
            .map_err(|error| format!("Unable to create private clamd file list: {error}"))?;
        for target in paths {
            let bytes = target.as_os_str().as_bytes();
            if bytes.contains(&b'\n') || bytes.contains(&b'\r') || bytes.contains(&0) {
                return Err("Cannot scan paths containing newline, carriage return, or NUL with clamd file lists".into());
            }
            file.write_all(bytes)
                .and_then(|_| file.write_all(b"\n"))
                .map_err(|error| format!("Unable to write private clamd file list: {error}"))?;
        }
        file.sync_all()
            .map_err(|error| format!("Unable to sync private clamd file list: {error}"))
    })();
    if let Err(error) = result {
        let _ = fs::remove_file(&path);
        return Err(error);
    }
    Ok(path)
}

fn clamd_limit(ctx: &Context, key: &str) -> Option<String> {
    let loaded = crate::dispatch(ctx, "config.load", json!({"kind": "clamd"})).ok()?;
    loaded
        .get("values")?
        .get(key)?
        .as_array()?
        .first()?
        .as_str()
        .filter(|value| !value.trim().is_empty())
        .map(str::to_owned)
}

fn merged_exclusions(ctx: &Context, request: &ScanRequest) -> AppResult<Exclusions> {
    let mut exclusions = Exclusions::default();
    append_exclusions(
        &mut exclusions,
        ctx.settings()?
            .get("exclusion_patterns")
            .unwrap_or(&Value::Null),
    );
    if let Some(extra) = &request.exclusions {
        append_exclusions(&mut exclusions, extra);
    }
    if request.profile_id.is_some() || request.profile_name.is_some() {
        let profiles = crate::dispatch(ctx, "profiles.list", json!({}))?;
        let records = profiles
            .as_array()
            .cloned()
            .or_else(|| profiles.get("profiles").and_then(Value::as_array).cloned())
            .unwrap_or_default();
        if let Some(profile) = records.into_iter().find(|profile| {
            request
                .profile_id
                .as_deref()
                .is_some_and(|id| profile.get("id").and_then(Value::as_str) == Some(id))
                || request
                    .profile_name
                    .as_deref()
                    .is_some_and(|name| profile.get("name").and_then(Value::as_str) == Some(name))
        }) {
            append_exclusions(
                &mut exclusions,
                profile.get("exclusions").unwrap_or(&Value::Null),
            );
        } else {
            return Err("Requested scan profile was not found".into());
        }
    }
    Ok(exclusions)
}

fn append_exclusions(into: &mut Exclusions, value: &Value) {
    if let Some(records) = value.as_array() {
        for record in records {
            let enabled = record
                .get("enabled")
                .and_then(Value::as_bool)
                .unwrap_or(true);
            let pattern = record
                .get("pattern")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty());
            if !enabled {
                continue;
            }
            match (record.get("type").and_then(Value::as_str), pattern) {
                (Some("directory"), Some(pattern)) => into.directories.push(expand_home(pattern)),
                (_, Some(pattern)) => into.patterns.push(expand_home(pattern)),
                _ => {}
            }
        }
    }
    if let Some(paths) = value.get("paths").and_then(Value::as_array) {
        into.directories.extend(
            paths
                .iter()
                .filter_map(Value::as_str)
                .filter(|value| !value.is_empty())
                .map(expand_home),
        );
    }
    if let Some(patterns) = value.get("patterns").and_then(Value::as_array) {
        into.patterns.extend(
            patterns
                .iter()
                .filter_map(Value::as_str)
                .filter(|value| !value.is_empty())
                .map(expand_home),
        );
    }
}

fn count_targets(
    path: &Path,
    exclusions: &Exclusions,
    cancelled: &AtomicBool,
) -> AppResult<TargetCount> {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default();
    if path.is_file() {
        if is_excluded(path, name, &exclusions.directories)
            || is_excluded(path, name, &exclusions.patterns)
        {
            return Ok(TargetCount::default());
        }
        return Ok(TargetCount {
            files: 1,
            directories: 0,
            file_paths: vec![path.to_path_buf()],
        });
    }
    if !path.is_dir() {
        return Err("Scan target is not a regular file or directory".into());
    }
    if is_excluded(path, name, &exclusions.directories) {
        return Ok(TargetCount::default());
    }
    let mut count = TargetCount::default();
    walk_targets(path, exclusions, cancelled, &mut count, true)?;
    if count.files > 0 || count.directories > 0 {
        count.directories += 1;
    }
    Ok(count)
}

fn walk_targets(
    path: &Path,
    exclusions: &Exclusions,
    cancelled: &AtomicBool,
    count: &mut TargetCount,
    root: bool,
) -> AppResult<()> {
    if cancelled.load(Ordering::Acquire) {
        return Ok(());
    }
    let entries = match fs::read_dir(path) {
        Ok(entries) => entries,
        Err(error) if root => {
            return Err(format!(
                "Unable to enumerate scan target {}: {error}",
                path.display()
            ))
        }
        Err(_) => return Ok(()),
    };
    for entry in entries {
        if cancelled.load(Ordering::Acquire) {
            return Ok(());
        }
        let entry = match entry {
            Ok(entry) => entry,
            Err(_) => continue,
        };
        let entry_path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        let kind = match entry.file_type() {
            Ok(kind) => kind,
            Err(_) => continue,
        };
        if kind.is_dir() {
            if is_excluded(&entry_path, &name, &exclusions.directories) {
                continue;
            }
            count.directories += 1;
            let _ = walk_targets(&entry_path, exclusions, cancelled, count, false);
        } else if kind.is_file() && !is_excluded(&entry_path, &name, &exclusions.patterns) {
            count.files += 1;
            count.file_paths.push(entry_path);
        }
    }
    Ok(())
}

fn is_excluded(path: &Path, name: &str, exclusions: &[String]) -> bool {
    let full = path.to_string_lossy();
    exclusions.iter().any(|pattern| {
        let expanded = expand_home(pattern);
        if expanded.starts_with('/') {
            full == expanded || full.starts_with(&(expanded.trim_end_matches('/').to_owned() + "/"))
        } else {
            glob_matches(name, &expanded) || glob_matches(&full, &expanded)
        }
    })
}
fn restore_threat_paths(result: &mut ScanResult, stdout: &[u8]) {
    let raw_paths = stdout
        .split(|byte| *byte == b'\n')
        .filter_map(|line| {
            let line = trim_ascii(line);
            if !line.ends_with(b" FOUND") {
                return None;
            }
            let separator = line.iter().rposition(|byte| *byte == b':')?;
            let path = trim_ascii(&line[..separator]);
            (!path.is_empty()).then(|| path_to_wire(Path::new(OsStr::from_bytes(path))))
        })
        .collect::<Vec<_>>();
    if raw_paths.len() != result.threat_details.len() {
        return;
    }
    for (threat, path) in result.threat_details.iter_mut().zip(raw_paths) {
        threat.file_path = path;
    }
    result.infected_files = result
        .threat_details
        .iter()
        .map(|threat| threat.file_path.clone())
        .collect();
}

fn trim_ascii(mut value: &[u8]) -> &[u8] {
    while value.first().is_some_and(u8::is_ascii_whitespace) {
        value = &value[1..];
    }
    while value.last().is_some_and(u8::is_ascii_whitespace) {
        value = &value[..value.len() - 1];
    }
    value
}

fn display_stdout(output: &CapturedOutput) -> String {
    let mut text = String::from_utf8_lossy(&output.stdout_bytes).into_owned();
    if output.stdout_truncated {
        text.push_str("\n[stdout truncated at 67108864 bytes]\n");
    }
    text
}

fn update_progress(
    line: &str,
    backend: &str,
    state: &mut ProgressState,
    total: Option<u64>,
    emit: impl FnOnce(ScanProgress),
) {
    let line = line.trim();
    let mut current = None;
    let mut threat = None;
    if backend == "daemon" {
        if let Some(path) = line.strip_suffix(": OK") {
            current = Some(path.trim().to_owned());
        }
    } else if let Some(path) = line.strip_prefix("Scanning ") {
        current = Some(path.trim().to_owned());
    }
    if line.ends_with("FOUND") {
        if let Some((path, signature)) = line.rsplit_once(':') {
            let threat_name = signature
                .trim()
                .strip_suffix(" FOUND")
                .unwrap_or(signature.trim())
                .trim();
            if !path.trim().is_empty() && !threat_name.is_empty() {
                let detail = ThreatDetail {
                    file_path: path.trim().into(),
                    threat_name: threat_name.into(),
                    category: crate::threat::categorize(Some(threat_name)),
                    severity: crate::threat::classify_severity(Some(threat_name))
                        .as_str()
                        .into(),
                };
                current = Some(detail.file_path.clone());
                if state.infected_paths.insert(detail.file_path.clone()) {
                    state.files_scanned += 1;
                }
                state.threats.push(detail.clone());
                threat = Some(detail);
            }
        }
    } else if let Some(path) = current.as_ref() {
        if state.infected_paths.insert(path.clone()) {
            state.files_scanned += 1;
        }
    } else {
        return;
    }
    let percentage = total
        .filter(|total| *total > 0)
        .map(|total| ((state.files_scanned as f64 / total as f64) * 100.0).clamp(0.0, 100.0));
    emit(ScanProgress {
        current_file: current.unwrap_or_default(),
        files_scanned: state.files_scanned,
        files_total: total,
        total_files: total,
        infected_count: state.threats.len() as u64,
        new_threats: threat.into_iter().collect(),
        bytes_scanned: 0,
        estimate_exceeded: total.is_some_and(|total| state.files_scanned > total),
        percentage,
    });
}

fn execute(
    program: &str,
    args: &[String],
    cancelled: &AtomicBool,
    mut line: impl FnMut(&str),
) -> AppResult<CapturedOutput> {
    let mut command = host_command(program, args);
    command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0);
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start {program}: {error}"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Unable to capture scanner stdout".to_owned())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "Unable to capture scanner stderr".to_owned())?;
    let (sender, receiver) = mpsc::channel();
    let stdout_reader = spawn_reader(stdout, true, sender.clone());
    let stderr_reader = spawn_reader(stderr, false, sender);
    let cancelled_process = wait_with_cancel(&mut child, cancelled, &receiver, &mut line)?;
    let stdout = stdout_reader
        .join()
        .map_err(|_| "Scanner stdout reader panicked".to_owned())?;
    let stderr = stderr_reader
        .join()
        .map_err(|_| "Scanner stderr reader panicked".to_owned())?;
    let mut stderr_text = String::from_utf8_lossy(&stderr.bytes).into_owned();
    if stderr.truncated {
        stderr_text.push_str("\n[stderr truncated at 67108864 bytes]\n");
    }
    Ok(CapturedOutput {
        stdout_bytes: stdout.bytes,
        stdout_truncated: stdout.truncated,
        stderr: stderr_text,
        exit_code: child
            .try_wait()
            .ok()
            .flatten()
            .and_then(|status| status.code())
            .unwrap_or(-1),
        cancelled: cancelled_process,
    })
}

fn spawn_reader<R: Read + Send + 'static>(
    reader: R,
    is_stdout: bool,
    sender: mpsc::Sender<String>,
) -> thread::JoinHandle<CapturedStream> {
    thread::spawn(move || {
        let mut reader = BufReader::new(reader);
        let mut bytes = Vec::new();
        let mut truncated = false;
        let mut buffer = [0_u8; 8192];
        let mut pending = String::new();
        loop {
            let read = match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(read) => read,
            };
            if bytes.len() < OUTPUT_LIMIT {
                let remaining = OUTPUT_LIMIT - bytes.len();
                let retained = read.min(remaining);
                bytes.extend_from_slice(&buffer[..retained]);
                truncated |= retained < read;
            } else {
                truncated = true;
            }
            if is_stdout {
                pending.push_str(&String::from_utf8_lossy(&buffer[..read]));
                while let Some(index) = pending.find('\n') {
                    let emitted = pending[..index].to_owned();
                    pending.drain(..=index);
                    let _ = sender.send(emitted);
                }
            }
        }
        if is_stdout && !pending.is_empty() {
            let _ = sender.send(pending);
        }
        CapturedStream { bytes, truncated }
    })
}

fn wait_with_cancel(
    child: &mut Child,
    cancelled: &AtomicBool,
    receiver: &Receiver<String>,
    line: &mut impl FnMut(&str),
) -> AppResult<bool> {
    let mut terminated = false;
    loop {
        while let Ok(value) = receiver.try_recv() {
            line(&value);
        }
        if child
            .try_wait()
            .map_err(|error| format!("Unable to wait for scanner: {error}"))?
            .is_some()
        {
            return Ok(terminated);
        }
        if cancelled.load(Ordering::Acquire) && !terminated {
            terminate_group(child);
            terminated = true;
        }
        thread::sleep(Duration::from_millis(100));
    }
}

fn terminate_group(child: &mut Child) {
    #[cfg(target_family = "unix")]
    {
        let group = -(child.id() as i32);
        unsafe {
            let _ = libc::kill(group, libc::SIGTERM);
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            // Reap the leader so its zombie cannot keep an otherwise empty group alive.
            let _ = child.try_wait();
            if !process_group_alive(group) {
                return;
            }
            thread::sleep(Duration::from_millis(25));
        }
        if process_group_alive(group) {
            unsafe {
                let _ = libc::kill(group, libc::SIGKILL);
            }
        }
    }
    #[cfg(not(target_family = "unix"))]
    {
        let _ = child.kill();
    }
}

#[cfg(target_family = "unix")]
fn process_group_alive(group: i32) -> bool {
    (unsafe { libc::kill(group, 0) == 0 })
        || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

fn aggregate_result(
    id: &str,
    results: Vec<ScanResult>,
    duration: Duration,
    scheduled: bool,
) -> Value {
    let status = if results
        .iter()
        .any(|result| result.status == ScanStatus::Infected)
    {
        ScanStatus::Infected
    } else if results
        .iter()
        .any(|result| result.status == ScanStatus::Error)
    {
        ScanStatus::Error
    } else if results
        .iter()
        .any(|result| result.status == ScanStatus::Cancelled)
    {
        ScanStatus::Cancelled
    } else {
        ScanStatus::Clean
    };
    let threats = results
        .iter()
        .flat_map(|result| result.threat_details.clone())
        .collect::<Vec<_>>();
    let errors = results
        .iter()
        .filter_map(|result| result.error_message.clone())
        .collect::<Vec<_>>();
    json!({
        "id": id,
        "status": status.as_str(),
        "scanned_files": results.iter().map(|result| result.scanned_files).sum::<u64>(),
        "scanned_dirs": results.iter().map(|result| result.scanned_dirs).sum::<u64>(),
        "infected_count": threats.len(),
        "threat_details": threats,
        "infected_files": results.iter().flat_map(|result| result.infected_files.clone()).collect::<Vec<_>>(),
        "stdout": results.iter().map(|result| result.stdout.as_str()).collect::<Vec<_>>().join("\n"),
        "stderr": results.iter().map(|result| result.stderr.as_str()).collect::<Vec<_>>().join("\n"),
        "error_message": errors.first(),
        "errors": errors,
        "skipped_files": results.iter().flat_map(|result| result.skipped_files.clone()).collect::<Vec<_>>(),
        "skipped_count": results.iter().map(|result| result.skipped_count).sum::<u64>(),
        "warning_message": results.iter().find_map(|result| result.warning_message.clone()),
        "nonfatal_warnings": results.iter().flat_map(|result| result.nonfatal_warnings.clone()).collect::<Vec<_>>(),
        "duration_seconds": duration.as_secs_f64(),
        "scheduled": scheduled,
        "per_target_results": results,
    })
}

fn save_result(ctx: &Context, aggregate: &Value, scheduled: bool) -> AppResult<()> {
    crate::dispatch(
        ctx,
        "logs.save",
        json!({
            "type": "scan", "status": aggregate["status"], "path": Value::Null,
            "scanned_files": aggregate["scanned_files"], "scanned_dirs": aggregate["scanned_dirs"],
            "infected_count": aggregate["infected_count"], "threat_details": aggregate["threat_details"],
            "error_message": aggregate["error_message"], "duration": aggregate["duration_seconds"],
            "scheduled": scheduled,
            "backend_suffix": aggregate["per_target_results"].as_array().and_then(|results| results.first()).and_then(|result| result.get("backend")).and_then(Value::as_str).map(|backend| format!("({backend})")),
        }),
    )?;
    Ok(())
}

#[derive(Default)]
struct ProgramProbe {
    available: bool,
    version: Option<String>,
    error: Option<String>,
}
impl ProgramProbe {
    fn unavailable(error: String) -> Self {
        Self {
            available: false,
            version: None,
            error: Some(error),
        }
    }
}
fn probe_program(program: &str, arguments: &[&str]) -> ProgramProbe {
    let args = arguments
        .iter()
        .map(|argument| (*argument).to_owned())
        .collect::<Vec<_>>();
    probe_program_owned(program, &args)
}

fn probe_program_owned(program: &str, arguments: &[String]) -> ProgramProbe {
    let mut command = host_command(program, arguments);
    match command.output() {
        Ok(output) if output.status.success() => ProgramProbe {
            available: true,
            version: String::from_utf8_lossy(&output.stdout)
                .lines()
                .next()
                .map(str::to_owned),
            error: None,
        },
        Ok(output) => {
            ProgramProbe::unavailable(String::from_utf8_lossy(&output.stderr).trim().to_owned())
        }
        Err(error) => ProgramProbe::unavailable(format!("{program}: {error}")),
    }
}

fn database_status(ctx: &Context) -> Value {
    let mut locations = vec!["/var/lib/clamav".to_owned(), "/var/lib/ClamAV".to_owned()];
    for kind in ["clamd", "freshclam"] {
        if let Ok(config) = crate::dispatch(ctx, "config.load", json!({"kind": kind})) {
            if let Some(directory) = config
                .get("values")
                .and_then(|values| values.get("DatabaseDirectory"))
                .and_then(Value::as_array)
                .and_then(|values| values.first())
                .and_then(Value::as_str)
                .filter(|directory| !directory.is_empty())
            {
                let directory = expand_home(directory);
                if !locations.contains(&directory) {
                    locations.push(directory);
                }
            }
        }
    }

    let mut newest = None;
    let mut selected = None;
    let mut files = 0_u64;
    for location in locations {
        let path = Path::new(&location);
        let Ok(entries) = fs::read_dir(path) else {
            continue;
        };
        selected = Some(location);
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if !name.ends_with(".cvd") && !name.ends_with(".cld") && !name.ends_with(".cud") {
                continue;
            }
            files += 1;
            if let Ok(modified) = entry.metadata().and_then(|metadata| metadata.modified()) {
                if let Ok(modified) = modified.duration_since(UNIX_EPOCH) {
                    newest = Some(newest.map_or(modified.as_secs(), |current: u64| {
                        current.max(modified.as_secs())
                    }));
                }
            }
        }
    }
    json!({"available": files > 0, "path": selected, "files": files, "latest_modified_unix": newest})
}

fn new_scan_id() -> String {
    let sequence = REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let high = (nanos >> 64) as u64 ^ (std::process::id() as u64);
    let low = nanos as u64 ^ sequence;
    format!(
        "{:08x}-{:04x}-4{:03x}-a{:03x}-{:012x}",
        high as u32,
        (high >> 32) as u16,
        (low >> 48) as u16 & 0x0fff,
        (low >> 36) as u16 & 0x0fff,
        low & 0x0000_0fff_ffff_ffff
    )
}

fn is_root_level(path: &Path) -> bool {
    matches!(
        path.to_string_lossy().as_ref(),
        "/" | "/home" | "/usr" | "/var" | "/opt" | "/etc" | "/tmp" | "/root"
    )
}

fn expand_home(value: &str) -> String {
    value
        .strip_prefix("~/")
        .and_then(|tail| {
            std::env::var_os("HOME").map(|home| {
                PathBuf::from(home)
                    .join(tail)
                    .to_string_lossy()
                    .into_owned()
            })
        })
        .unwrap_or_else(|| value.to_owned())
}

fn scan_path_from_wire(ctx: &Context, wire: &str) -> AppResult<PathBuf> {
    let path = crate::common::path_from_wire(wire)?;
    let bytes = path.as_os_str().as_bytes();
    if bytes == b"~" {
        return Ok(ctx.paths.home.clone());
    }
    if let Some(rest) = bytes.strip_prefix(b"~/") {
        return Ok(ctx
            .paths
            .home
            .join(std::ffi::OsString::from_vec(rest.to_vec())));
    }
    Ok(path)
}

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

fn localize_result(ctx: &Context, result: &mut ScanResult) {
    if result.error_message.as_deref() == Some("Scan cancelled by user") {
        result.error_message = Some(crate::i18n::translate(ctx, "Scan cancelled by user"));
    } else if result.error_message.as_deref() == Some("No files could be scanned") {
        result.error_message = Some(crate::i18n::translate(ctx, "No files could be scanned"));
    } else if result.error_message.as_deref()
        == Some("Scan target does not exist or contains an invalid NUL byte")
    {
        result.error_message = Some(crate::i18n::translate(
            ctx,
            "Scan target does not exist or contains an invalid NUL byte",
        ));
    } else if result.error_message.as_deref()
        == Some("Scan target is not a regular file or directory")
    {
        result.error_message = Some(crate::i18n::translate(
            ctx,
            "Scan target is not a regular file or directory",
        ));
    }
    let Some(warning) = result.warning_message.as_deref() else {
        return;
    };
    if let Some(count) = warning
        .strip_suffix(" file could not be accessed")
        .or_else(|| warning.strip_suffix(" files could not be accessed"))
        .and_then(|count| count.parse::<u64>().ok())
    {
        let rendered_count = count.to_string();
        result.warning_message = Some(trnf(
            ctx,
            "{count} file could not be accessed",
            "{count} files could not be accessed",
            count,
            &[("{count}", &rendered_count)],
        ));
    } else if let Some(count) = warning
        .strip_suffix(" file could not be read")
        .or_else(|| warning.strip_suffix(" files could not be read"))
        .and_then(|count| count.parse::<u64>().ok())
    {
        let rendered_count = count.to_string();
        result.warning_message = Some(trnf(
            ctx,
            "{count} file could not be read",
            "{count} files could not be read",
            count,
            &[("{count}", &rendered_count)],
        ));
    } else if let Some(count) = warning
        .strip_suffix(
            " non-fatal warning during scan; some files may have been only partially scanned",
        )
        .or_else(|| {
            warning.strip_suffix(
                " non-fatal warnings during scan; some files may have been only partially scanned",
            )
        })
        .and_then(|count| count.parse::<u64>().ok())
    {
        let rendered_count = count.to_string();
        result.warning_message = Some(trnf(
            ctx,
            "{count} non-fatal warning during scan; some files may have been only partially scanned",
            "{count} non-fatal warnings during scan; some files may have been only partially scanned",
            count,
            &[("{count}", &rendered_count)],
        ));
    }
}

fn glob_matches(value: &str, pattern: &str) -> bool {
    fn matches(value: &[char], pattern: &[char], value_index: usize, pattern_index: usize) -> bool {
        if pattern_index == pattern.len() {
            return value_index == value.len();
        }
        match pattern[pattern_index] {
            '*' => {
                let mut next = pattern_index + 1;
                while next < pattern.len() && pattern[next] == '*' {
                    next += 1;
                }
                (value_index..=value.len()).any(|index| matches(value, pattern, index, next))
            }
            '?' => {
                value_index < value.len()
                    && matches(value, pattern, value_index + 1, pattern_index + 1)
            }
            '[' => match class_match(pattern, pattern_index, value.get(value_index).copied()) {
                Some((next, true)) => matches(value, pattern, value_index + 1, next),
                Some((_, false)) => false,
                None => {
                    value.get(value_index) == Some(&'[')
                        && matches(value, pattern, value_index + 1, pattern_index + 1)
                }
            },
            literal => {
                value.get(value_index) == Some(&literal)
                    && matches(value, pattern, value_index + 1, pattern_index + 1)
            }
        }
    }

    matches(
        &value.chars().collect::<Vec<_>>(),
        &pattern.chars().collect::<Vec<_>>(),
        0,
        0,
    )
}

fn class_end(pattern: &[char], open: usize) -> Option<usize> {
    let mut index = open + 1;
    if matches!(pattern.get(index), Some('!')) {
        index += 1;
    }
    if matches!(pattern.get(index), Some(']')) {
        index += 1;
    }
    while index < pattern.len() {
        if pattern[index] == ']' {
            return Some(index);
        }
        index += 1;
    }
    None
}

fn class_match(pattern: &[char], open: usize, value: Option<char>) -> Option<(usize, bool)> {
    let end = class_end(pattern, open)?;
    let value = value?;
    let mut index = open + 1;
    let negated = if pattern.get(index) == Some(&'!') {
        index += 1;
        true
    } else {
        false
    };
    let mut matched = false;
    while index < end {
        let start = pattern[index];
        if index + 2 < end && pattern[index + 1] == '-' {
            matched |= start <= value && value <= pattern[index + 2];
            index += 3;
        } else {
            matched |= start == value;
            index += 1;
        }
    }
    Some((end + 1, if negated { !matched } else { matched }))
}

fn glob_regex(pattern: &str) -> String {
    let characters = pattern.chars().collect::<Vec<_>>();
    let mut output = String::from("^");
    let mut index = 0;
    while index < characters.len() {
        match characters[index] {
            '*' => output.push_str(".*"),
            '?' => output.push('.'),
            '[' if class_end(&characters, index).is_some() => {
                let end = class_end(&characters, index).expect("checked class end");
                output.push('[');
                let mut class_index = index + 1;
                if characters.get(class_index) == Some(&'!') {
                    output.push('^');
                    class_index += 1;
                }
                for (offset, character) in characters[class_index..=end].iter().enumerate() {
                    if *character == '\\' || (*character == '^' && offset == 0) {
                        output.push('\\');
                    }
                    output.push(*character);
                }
                index = end;
            }
            '\\' | '.' | '+' | '(' | ')' | '|' | '^' | '$' | '{' | '}' | '[' | ']' => {
                output.push('\\');
                output.push(characters[index]);
            }
            character => output.push(character),
        }
        index += 1;
    }
    output.push('$');
    output
}
fn directory_regex(pattern: &str) -> String {
    if pattern.contains('/') || pattern.contains('\\') {
        glob_regex(pattern)
    } else {
        format!(
            "(^|.*/){}(/|$)",
            glob_regex(pattern)
                .trim_start_matches('^')
                .trim_end_matches('$')
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn caret_is_literal_in_fnmatch_character_classes_for_daemon_and_clamscan() {
        let expression = regex::Regex::new(&glob_regex("sample[^a].txt")).expect("regex");
        for (name, expected) in [
            ("samplea.txt", true),
            ("sample^.txt", true),
            ("sampleb.txt", false),
        ] {
            assert_eq!(
                glob_matches(name, "sample[^a].txt"),
                expected,
                "daemon: {name}"
            );
            assert_eq!(expression.is_match(name), expected, "clamscan: {name}");
        }
    }

    #[test]
    fn raw_found_path_identity_is_preserved_for_clamscan_and_daemon() {
        let raw = b"/tmp/eicar-\xff.com: Eicar-Test-Signature FOUND\nScanned files: 1\n";
        let stdout = String::from_utf8_lossy(raw);
        let expected = path_to_wire(Path::new(OsStr::from_bytes(b"/tmp/eicar-\xff.com")));

        let mut clamscan = interpret_clamscan("/tmp", &stdout, "", 1, 1);
        restore_threat_paths(&mut clamscan, raw);
        assert_eq!(clamscan.threat_details[0].file_path, expected);
        assert_eq!(clamscan.infected_files[0], expected);

        let mut daemon = interpret_daemon("/tmp", &stdout, "", 1, 1, 0);
        restore_threat_paths(&mut daemon, raw);
        assert_eq!(daemon.threat_details[0].file_path, expected);
        assert_eq!(daemon.infected_files[0], expected);
    }
}
