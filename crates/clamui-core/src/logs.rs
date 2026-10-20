use crate::{AppResult, Context};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use chrono::{DateTime, Duration, Local, NaiveDate, NaiveDateTime, TimeZone, Utc};
use regex::Regex;
use serde_json::{json, Map, Value};
use std::{
    fs,
    io::{Cursor, Write},
    path::{Component, Path, PathBuf},
    sync::LazyLock,
};
use uuid::Uuid;
use zip::write::SimpleFileOptions;

const INDEX_FILE: &str = "log_index.json";
const LOG_PRIVACY_MARKER: &str = ".log-privacy-version";
const DEBUG_PRIVACY_MARKER: &str = ".debug-log-privacy-version";
const PRIVACY_VERSION: &str = "1";
const DEBUG_FILE: &str = "clamui.log";
const MAX_HISTORY: usize = 10_000;
const DEBUG_MAX_BYTES: u64 = 5 * 1024 * 1024;
const DEBUG_BACKUPS: usize = 3;

static FILES_SCANNED: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(?:\b(\d+)\s*files?\s*scanned\b|\bscanned\s*:?\s*(\d+)\s*files?\b|\bfiles\s*:\s*(\d+)|\b(\d+)\s*files?\b)")
        .expect("valid file count pattern")
});
static THREATS_FOUND: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?i)(?:\b(\d+)\s*(?:threats?|infections?|infected)\b|\b(?:found|detected)\s*:?\s*(\d+))",
    )
    .expect("valid threat count pattern")
});
static URL: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"(?i)https?://[^\s<>'"]+"#).expect("valid URL pattern"));
static HASH: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[[:xdigit:]]{32,128}\b").expect("valid hash pattern"));

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
    let mut translated = trn(ctx, singular, plural, count);
    for (placeholder, value) in replacements {
        translated = translated.replace(placeholder, value);
    }
    translated
}

/// Dispatch history, statistics, daemon-log, and debug-log operations.
pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "save" | "create" => save(ctx, args),
        "list" => list(ctx, &args),
        "get" => get(ctx, &args),
        "delete" => delete(ctx, &args),
        "clear" => clear(ctx),
        "export" => export(ctx, &args),
        "statistics" => statistics(ctx, &args),
        "count" => Ok(json!({"total_entries": load_entries(ctx, &logs_dir(ctx))?.len()})),
        "daemon" => daemon(ctx, &args),
        "debug_info" => debug_info(ctx),
        "debug_list" => debug_list(ctx),
        "debug_read" => debug_read(ctx, &args),
        "debug_delete" => debug_delete(ctx, &args),
        "debug_clear" => debug_clear(ctx),
        "debug_export" => debug_export(ctx),
        _ => Err(format!("unknown logs action: {action}")),
    }
}

/// Persist an old `LogEntry`-shaped value after privacy sanitization.
///
/// The established fields remain compatible with the Python implementation:
/// `{id,timestamp,type,status,summary,details,path,duration,scheduled}`.
/// Scan entries also retain optional structured `scanned_files` and `infected_count` values.
/// `path` is always persisted as null, even when callers provide it.
pub fn save(ctx: &Context, entry: Value) -> AppResult<Value> {
    let raw = entry
        .as_object()
        .ok_or_else(|| "log entry must be an object".to_owned())?;
    let id = raw
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| valid_id(id))
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| Uuid::new_v4().to_string());
    let log_type = private_line(string_field(raw, "type", "unknown"));
    let status = private_line(string_field(raw, "status", "unknown"));
    let scheduled = raw
        .get("scheduled")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let duration = raw.get("duration").and_then(Value::as_f64).unwrap_or(0.0);
    let timestamp = raw
        .get("timestamp")
        .and_then(Value::as_str)
        .filter(|value| parse_time(value).is_some())
        .map(ToOwned::to_owned)
        .unwrap_or_else(now_iso);

    let scan_details = build_scan_fields(ctx, raw, &status);
    let summary = private_line(
        raw.get("summary")
            .and_then(Value::as_str)
            .unwrap_or(&scan_details.0),
    );
    let details = private_text(
        raw.get("details")
            .and_then(Value::as_str)
            .unwrap_or(&scan_details.1),
    );
    let scanned_files = (log_type == "scan")
        .then(|| raw.get("scanned_files").and_then(Value::as_u64))
        .flatten();
    let infected_count = (log_type == "scan")
        .then(|| raw.get("infected_count").and_then(Value::as_u64))
        .flatten();
    let mut stored = json!({
        "id": id,
        "timestamp": timestamp,
        "type": log_type,
        "status": status,
        "summary": summary,
        "details": details,
        "path": Value::Null,
        "duration": if duration.is_finite() { duration.max(0.0) } else { 0.0 },
        "scheduled": scheduled,
    });
    if let Some(scanned_files) = scanned_files {
        stored["scanned_files"] = json!(scanned_files);
    }
    if let Some(infected_count) = infected_count {
        stored["infected_count"] = json!(infected_count);
    }
    let dir = logs_dir(ctx);
    fs::create_dir_all(&dir).map_err(|error| format!("creating log directory: {error}"))?;
    migrate_logs(ctx, &dir)?;
    let path = log_path(&dir, stored["id"].as_str().expect("generated id"))?;
    let bytes = serde_json::to_vec_pretty(&stored).map_err(|error| error.to_string())?;
    crate::common::atomic_write(&path, &bytes, 0o600)?;

    // The entry is durable even if an index update fails; future reads rebuild it.
    let _ = rebuild_index(&dir);
    Ok(public_entry(stored))
}

fn public_entry(mut entry: Value) -> Value {
    if let Some(object) = entry.as_object_mut() {
        object.remove("scanned_files");
        object.remove("infected_count");
    }
    entry
}

/// Append a redacted diagnostic line. Settings are read on every call, so a
/// persisted debug-level change applies to all subsequent writes immediately.
pub fn write_debug(ctx: &Context, level: &str, target: &str, message: &str) -> AppResult<()> {
    let level = level.to_ascii_uppercase();
    let configured = ctx
        .settings()?
        .get("debug_log_level")
        .and_then(Value::as_str)
        .unwrap_or("WARNING")
        .to_ascii_uppercase();
    if level_rank(&level) < level_rank(&configured) {
        return Ok(());
    }
    let dir = debug_dir(ctx);
    fs::create_dir_all(&dir).map_err(|error| format!("creating debug directory: {error}"))?;
    restrict_dir(&dir)?;
    migrate_debug(&dir)?;
    let line = format!(
        "{} - {} - {} - {}\n",
        Local::now().format("%Y-%m-%d %H:%M:%S"),
        level,
        private_line(target),
        private_text(message).replace(['\n', '\r'], " ")
    );
    rotate_debug(&dir, line.len() as u64)?;
    let path = dir.join(DEBUG_FILE);
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|error| format!("opening debug log: {error}"))?;
    file.write_all(line.as_bytes())
        .and_then(|_| file.sync_data())
        .map_err(|error| format!("writing debug log: {error}"))?;
    restrict_file(&path)?;
    Ok(())
}

fn list(ctx: &Context, args: &Value) -> AppResult<Value> {
    let limit = args.get("limit").and_then(Value::as_u64).unwrap_or(100) as usize;
    let log_type = args.get("log_type").and_then(Value::as_str);
    let entries = load_entries(ctx, &logs_dir(ctx))?
        .into_iter()
        .filter(|entry| log_type.is_none_or(|kind| entry["type"] == kind))
        .take(limit)
        .map(public_entry)
        .collect::<Vec<_>>();
    Ok(Value::Array(entries))
}

fn get(ctx: &Context, args: &Value) -> AppResult<Value> {
    let id = required_id(args)?;
    let dir = logs_dir(ctx);
    if dir.exists() {
        migrate_logs(ctx, &dir)?;
    }
    let path = log_path(&dir, id)?;
    if !path.exists() {
        return Err("log entry not found".to_owned());
    }
    read_entry(&path).map(public_entry)
}

fn delete(ctx: &Context, args: &Value) -> AppResult<Value> {
    let dir = logs_dir(ctx);
    let id = required_id(args)?;
    let path = log_path(&dir, id)?;
    if !path.exists() {
        return Err("log entry not found".to_owned());
    }
    fs::remove_file(path).map_err(|error| format!("deleting log: {error}"))?;
    let _ = rebuild_index(&dir);
    Ok(json!({"deleted": true, "id": id}))
}

fn clear(ctx: &Context) -> AppResult<Value> {
    let dir = logs_dir(ctx);
    let mut cleared = 0_u64;
    let mut failures = Vec::new();
    if dir.exists() {
        for entry in fs::read_dir(&dir).map_err(|error| format!("reading logs: {error}"))? {
            let path = entry.map_err(|error| error.to_string())?.path();
            if path
                .extension()
                .is_some_and(|extension| extension == "json")
                && path.file_name().is_some_and(|name| name != INDEX_FILE)
            {
                match fs::remove_file(&path) {
                    Ok(()) => cleared += 1,
                    Err(error) => {
                        failures.push(json!({"name": safe_name(&path), "error": error.to_string()}))
                    }
                }
            }
        }
        let _ = fs::remove_file(dir.join(LOG_PRIVACY_MARKER));
        if failures.is_empty() {
            write_index(&dir, &[])?;
        } else {
            let _ = rebuild_index(&dir);
        }
    }
    Ok(json!({"cleared": cleared, "success": failures.is_empty(), "failures": failures}))
}

fn export(ctx: &Context, args: &Value) -> AppResult<Value> {
    let format = args.get("format").and_then(Value::as_str).unwrap_or("json");
    let ui_schema = args.get("schema").and_then(Value::as_str) == Some("ui");
    let mut entries = load_entries(ctx, &logs_dir(ctx))?
        .into_iter()
        .map(public_entry)
        .collect::<Vec<_>>();
    if let Some(ids) = args.get("ids").and_then(Value::as_array) {
        let wanted = ids.iter().filter_map(Value::as_str).collect::<Vec<_>>();
        entries.retain(|entry| entry["id"].as_str().is_some_and(|id| wanted.contains(&id)));
    }
    let content = match (ui_schema, format) {
        (false, "csv") => csv_export(&entries),
        (false, "json") => serde_json::to_string_pretty(
            &json!({"export_timestamp": now_iso(), "count": entries.len(), "entries": entries}),
        )
        .map_err(|error| error.to_string())?,
        (false, "text") => text_export(&entries),
        (true, "csv") => ui_csv_export(&entries),
        (true, "json") => {
            let value = if args
                .get("ids")
                .is_some_and(|ids| ids.as_array().is_some_and(|ids| ids.len() == 1))
            {
                entries.first().map(ui_entry).unwrap_or(Value::Null)
            } else {
                Value::Array(entries.iter().map(ui_entry).collect())
            };
            serde_json::to_string_pretty(&value).map_err(|error| error.to_string())?
        }
        (true, "text") => entries
            .iter()
            .map(|entry| ui_detail_text(ctx, entry))
            .collect::<Vec<_>>()
            .join("\n\n"),
        (_, _) => return Err("export format must be csv, json, or text".to_owned()),
    };
    Ok(Value::String(content))
}

fn statistics(ctx: &Context, args: &Value) -> AppResult<Value> {
    let requested = args
        .get("timeframe")
        .and_then(Value::as_str)
        .unwrap_or("all");
    let (timeframe, period) = timeframe(requested)?;
    let all_scans = load_entries(ctx, &logs_dir(ctx))?
        .into_iter()
        .filter(|entry| entry["type"] == "scan")
        .take(MAX_HISTORY)
        .collect::<Vec<_>>();
    let now = Local::now();
    let scans = all_scans
        .iter()
        .filter(|entry| {
            parse_time(entry["timestamp"].as_str().unwrap_or_default())
                .is_some_and(|time| period.is_none_or(|start| time >= start && time <= now))
        })
        .collect::<Vec<_>>();
    let total = scans.len() as u64;
    let files_scanned = scans.iter().map(|entry| scanned_files(entry)).sum::<u64>();
    let threats_detected = scans.iter().map(|entry| threats(entry)).sum::<u64>();
    let total_duration = scans
        .iter()
        .map(|entry| entry["duration"].as_f64().unwrap_or(0.0))
        .sum::<f64>();
    let clean_scans = scans
        .iter()
        .filter(|entry| entry["status"] == "clean")
        .count() as u64;
    let infected_scans = scans
        .iter()
        .filter(|entry| entry["status"] == "infected")
        .count() as u64;
    let error_scans = scans
        .iter()
        .filter(|entry| entry["status"] == "error")
        .count() as u64;
    let scheduled_scans = scans
        .iter()
        .filter(|entry| entry["scheduled"] == true)
        .count() as u64;
    let definition = args.get("last_definition_update").and_then(Value::as_str);
    let last_scan = all_scans.first().cloned().unwrap_or(Value::Null);
    let protection = protection_status(all_scans.first(), definition, now);
    Ok(json!({
        "timeframe": timeframe,
        "total_scans": total,
        "files_scanned": files_scanned,
        "threats_detected": threats_detected,
        "clean_scans": clean_scans,
        "infected_scans": infected_scans,
        "error_scans": error_scans,
        "average_duration": round2(if total == 0 { 0.0 } else { total_duration / total as f64 }),
        "total_duration": round2(total_duration),
        "scheduled_scans": scheduled_scans,
        "manual_scans": total - scheduled_scans,
        "start_date": period.map(|start| start.to_rfc3339()),
        "end_date": now.to_rfc3339(),
        "trends": trend_data(&all_scans, timeframe, now),
        "protection_status": protection,
        "last_scan": last_scan,
    }))
}

fn daemon(ctx: &Context, args: &Value) -> AppResult<Value> {
    let lines = args
        .get("lines")
        .and_then(Value::as_u64)
        .unwrap_or(100)
        .clamp(1, 10_000);
    let mut candidates = vec![
        "/var/log/clamav/clamd.log".to_owned(),
        "/var/log/clamd.log".to_owned(),
    ];
    let mut configs = vec![
        "/etc/clamav/clamd.conf".to_owned(),
        "/etc/clamd.conf".to_owned(),
        "/etc/clamd.d/scan.conf".to_owned(),
    ];
    if let Some(config) = ctx
        .settings()?
        .get("clamd_conf_path")
        .and_then(Value::as_str)
        .filter(|path| !path.is_empty())
    {
        configs.insert(0, config.to_owned());
    }
    configs.sort();
    configs.dedup();
    for config in configs {
        if let Ok(output) = crate::common::host_command("cat", &[config]).output() {
            if output.status.success() {
                candidates.extend(String::from_utf8_lossy(&output.stdout).lines().filter_map(
                    |line| {
                        let line = line.trim();
                        line.strip_prefix("LogFile")
                            .and_then(|value| value.split_whitespace().next())
                            .map(ToOwned::to_owned)
                    },
                ));
            }
        }
    }
    candidates.sort();
    candidates.dedup();
    for path in candidates {
        let output = crate::common::host_command("tail", &["-n".into(), lines.to_string(), path])
            .output()
            .map_err(|error| format!("reading daemon log: {error}"))?;
        if output.status.success() {
            let content = private_text(&String::from_utf8_lossy(&output.stdout));
            return Ok(
                json!({"success": true, "content": if content.trim().is_empty() { "(Log file is empty)" } else { &content }, "source": "file"}),
            );
        }
    }
    for unit in ["clamav-daemon", "clamd", "clamd@scan"] {
        let output = crate::common::host_command(
            "journalctl",
            &[
                "-u".into(),
                unit.into(),
                "-n".into(),
                lines.to_string(),
                "--no-pager".into(),
                "-q".into(),
            ],
        )
        .output()
        .map_err(|error| format!("reading daemon journal: {error}"))?;
        if output.status.success() && !output.stdout.is_empty() {
            return Ok(
                json!({"success": true, "content": private_text(&String::from_utf8_lossy(&output.stdout)), "source": "journal"}),
            );
        }
    }
    Ok(json!({"success": false, "content": "Daemon log file not found.", "source": Value::Null}))
}

fn debug_info(ctx: &Context) -> AppResult<Value> {
    let dir = debug_dir(ctx);
    let files = debug_files(&dir)?;
    let total_bytes = files
        .iter()
        .filter_map(|path| fs::metadata(path).ok())
        .map(|metadata| metadata.len())
        .sum::<u64>();
    let level = ctx
        .settings()?
        .get("debug_log_level")
        .and_then(Value::as_str)
        .unwrap_or("WARNING")
        .to_ascii_uppercase();
    Ok(
        json!({"log_dir": dir.to_string_lossy(), "total_bytes": total_bytes, "file_count": files.len(), "files": files.iter().map(|path| safe_name(path)).collect::<Vec<_>>(), "level": level}),
    )
}

fn debug_list(ctx: &Context) -> AppResult<Value> {
    Ok(Value::Array(
        debug_files(&debug_dir(ctx))?
            .into_iter()
            .filter_map(|path| {
                fs::metadata(&path)
                    .ok()
                    .map(|metadata| json!({"name": safe_name(&path), "size": metadata.len()}))
            })
            .collect(),
    ))
}

fn debug_read(ctx: &Context, args: &Value) -> AppResult<Value> {
    let name = required_debug_name(args)?;
    let path = debug_dir(ctx).join(name);
    let content =
        fs::read_to_string(&path).map_err(|error| format!("reading debug log: {error}"))?;
    Ok(json!({"name": name, "content": private_text(&content)}))
}

fn debug_delete(ctx: &Context, args: &Value) -> AppResult<Value> {
    let name = required_debug_name(args)?;
    fs::remove_file(debug_dir(ctx).join(name))
        .map_err(|error| format!("deleting debug log: {error}"))?;
    Ok(json!({"deleted": true, "name": name}))
}

fn debug_clear(ctx: &Context) -> AppResult<Value> {
    let dir = debug_dir(ctx);
    let mut cleared = 0_u64;
    let mut failures = Vec::new();
    for path in debug_files(&dir)? {
        match fs::remove_file(&path) {
            Ok(()) => cleared += 1,
            Err(error) => {
                failures.push(json!({"name": safe_name(&path), "error": error.to_string()}))
            }
        }
    }
    let _ = fs::remove_file(dir.join(DEBUG_PRIVACY_MARKER));
    Ok(
        json!({"cleared": cleared, "success": failures.is_empty(), "message": if failures.is_empty() { "Debug logs cleared" } else { "Some debug logs could not be cleared" }, "failures": failures}),
    )
}

fn debug_export(ctx: &Context) -> AppResult<Value> {
    let dir = debug_dir(ctx);
    let files = debug_files(&dir)?;
    if files.is_empty() {
        return Err("no debug logs available to export".to_owned());
    }
    migrate_debug(&dir)?;
    let mut archive = zip::ZipWriter::new(Cursor::new(Vec::new()));
    for path in files {
        archive
            .start_file(
                safe_name(&path),
                SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated),
            )
            .map_err(|error| error.to_string())?;
        archive
            .write_all(
                private_text(&fs::read_to_string(&path).map_err(|error| error.to_string())?)
                    .as_bytes(),
            )
            .map_err(|error| error.to_string())?;
    }
    let bytes = archive
        .finish()
        .map_err(|error| error.to_string())?
        .into_inner();
    Ok(
        json!({"content_base64": BASE64.encode(bytes), "filename": format!("clamui-logs-{}.zip", Local::now().format("%Y-%m-%d-%H%M%S"))}),
    )
}

fn logs_dir(ctx: &Context) -> PathBuf {
    ctx.paths.data_dir.join("logs")
}
fn debug_dir(ctx: &Context) -> PathBuf {
    ctx.paths.data_dir.join("debug")
}

fn load_entries(ctx: &Context, dir: &Path) -> AppResult<Vec<Value>> {
    if !dir.exists() {
        return Ok(Vec::new());
    }
    migrate_logs(ctx, dir)?;
    let mut entries = Vec::new();
    for entry in fs::read_dir(dir).map_err(|error| format!("reading logs: {error}"))? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path
            .extension()
            .is_some_and(|extension| extension == "json")
            && path.file_name().is_some_and(|name| name != INDEX_FILE)
        {
            if let Ok(value) = read_entry(&path) {
                entries.push(value);
            }
        }
    }
    entries.sort_by(|left, right| right["timestamp"].as_str().cmp(&left["timestamp"].as_str()));
    let _ = rebuild_index(dir);
    Ok(entries)
}

fn read_entry(path: &Path) -> AppResult<Value> {
    let parsed: Value =
        serde_json::from_slice(&fs::read(path).map_err(|error| format!("reading log: {error}"))?)
            .map_err(|error| format!("invalid log JSON: {error}"))?;
    let object = parsed
        .as_object()
        .ok_or_else(|| "log entry is not an object".to_owned())?;
    let id = object
        .get("id")
        .and_then(Value::as_str)
        .filter(|id| valid_id(id))
        .ok_or_else(|| "invalid log identifier".to_owned())?;
    let log_type = private_line(string_field(object, "type", "unknown"));
    let scanned_files = (log_type == "scan")
        .then(|| object.get("scanned_files").and_then(Value::as_u64))
        .flatten();
    let infected_count = (log_type == "scan")
        .then(|| object.get("infected_count").and_then(Value::as_u64))
        .flatten();
    let mut entry = json!({
        "id": id,
        "timestamp": object.get("timestamp").and_then(Value::as_str).filter(|value| parse_time(value).is_some()).map(ToOwned::to_owned).unwrap_or_else(now_iso),
        "type": log_type,
        "status": private_line(string_field(object, "status", "unknown")),
        "summary": private_line(string_field(object, "summary", "")),
        "details": private_text(string_field(object, "details", "")),
        "path": Value::Null,
        "duration": object.get("duration").and_then(Value::as_f64).filter(|duration| duration.is_finite() && *duration >= 0.0).unwrap_or(0.0),
        "scheduled": object.get("scheduled").and_then(Value::as_bool).unwrap_or(false),
    });
    if let Some(scanned_files) = scanned_files {
        entry["scanned_files"] = json!(scanned_files);
    }
    if let Some(infected_count) = infected_count {
        entry["infected_count"] = json!(infected_count);
    }
    Ok(entry)
}

fn migrate_logs(ctx: &Context, dir: &Path) -> AppResult<()> {
    if fs::read_to_string(dir.join(LOG_PRIVACY_MARKER))
        .ok()
        .as_deref()
        == Some(PRIVACY_VERSION)
    {
        return Ok(());
    }
    let legacy_paths = fs::read_dir(dir)
        .map_err(|error| format!("reading legacy logs: {error}"))?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.extension()
                .is_some_and(|extension| extension == "json")
                && path.file_name().is_some_and(|name| name != INDEX_FILE)
        })
        .collect::<Vec<_>>();
    let had_legacy_entries = !legacy_paths.is_empty();
    if had_legacy_entries {
        ctx.emit(
            "privacy-activity",
            json!({"message": "Protecting existing scan history"}),
        );
    }
    for path in legacy_paths {
        if let Ok(value) = read_entry(&path) {
            let bytes = serde_json::to_vec_pretty(&value).map_err(|error| error.to_string())?;
            crate::common::atomic_write(&path, &bytes, 0o600)?;
        }
    }
    crate::common::atomic_write(
        &dir.join(LOG_PRIVACY_MARKER),
        PRIVACY_VERSION.as_bytes(),
        0o600,
    )?;
    if had_legacy_entries {
        ctx.emit(
            "privacy-activity",
            json!({"message": "Existing scan history protected"}),
        );
    }
    Ok(())
}

fn rebuild_index(dir: &Path) -> AppResult<()> {
    let entries = load_index_entries(dir)?;
    write_index(dir, &entries)
}

fn load_index_entries(dir: &Path) -> AppResult<Vec<Value>> {
    let mut entries = Vec::new();
    if !dir.exists() {
        return Ok(entries);
    }
    for entry in fs::read_dir(dir).map_err(|error| error.to_string())? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path
            .extension()
            .is_some_and(|extension| extension == "json")
            && path.file_name().is_some_and(|name| name != INDEX_FILE)
        {
            if let Ok(value) = read_entry(&path) {
                entries.push(json!({"id": value["id"], "timestamp": value["timestamp"], "type": value["type"]}));
            }
        }
    }
    Ok(entries)
}

fn write_index(dir: &Path, entries: &[Value]) -> AppResult<()> {
    fs::create_dir_all(dir).map_err(|error| error.to_string())?;
    let bytes = serde_json::to_vec_pretty(&json!({"version": 1, "entries": entries}))
        .map_err(|error| error.to_string())?;
    crate::common::atomic_write(&dir.join(INDEX_FILE), &bytes, 0o600)
}

fn csv_export(entries: &[Value]) -> String {
    let mut output = String::from("id,timestamp,type,status,path,summary,duration,scheduled\n");
    for entry in entries {
        let fields = [
            entry["id"].as_str().unwrap_or_default().to_owned(),
            entry["timestamp"].as_str().unwrap_or_default().to_owned(),
            entry["type"].as_str().unwrap_or_default().to_owned(),
            entry["status"].as_str().unwrap_or_default().to_owned(),
            String::new(),
            entry["summary"].as_str().unwrap_or_default().to_owned(),
            if entry["duration"].as_f64().unwrap_or(0.0) > 0.0 {
                format!("{:.2}", entry["duration"].as_f64().unwrap_or_default())
            } else {
                "0".into()
            },
            if entry["scheduled"] == true {
                "true".into()
            } else {
                "false".into()
            },
        ];
        output.push_str(
            &fields
                .iter()
                .map(|field| csv_field(field))
                .collect::<Vec<_>>()
                .join(","),
        );
        output.push('\n');
    }
    output
}

fn text_export(entries: &[Value]) -> String {
    entries.iter().map(|entry| format!("Timestamp: {}\nType: {}\nStatus: {}\nSummary: {}\nDuration: {}\nScheduled: {}\n\n{}\n", entry["timestamp"].as_str().unwrap_or_default(), entry["type"].as_str().unwrap_or_default(), entry["status"].as_str().unwrap_or_default(), entry["summary"].as_str().unwrap_or_default(), entry["duration"], entry["scheduled"], entry["details"].as_str().unwrap_or_default())).collect()
}

fn ui_csv_export(entries: &[Value]) -> String {
    let mut output = String::from("timestamp,type,status,path,summary,duration\n");
    for entry in entries {
        let fields = [
            entry["timestamp"].as_str().unwrap_or_default().to_owned(),
            entry["type"].as_str().unwrap_or_default().to_owned(),
            entry["status"].as_str().unwrap_or_default().to_owned(),
            String::new(),
            entry["summary"].as_str().unwrap_or_default().to_owned(),
            export_duration(entry),
        ];
        output.push_str(
            &fields
                .iter()
                .map(|field| csv_field(field))
                .collect::<Vec<_>>()
                .join(","),
        );
        output.push('\n');
    }
    output
}

fn ui_entry(entry: &Value) -> Value {
    json!({
        "id": entry["id"],
        "timestamp": entry["timestamp"],
        "type": entry["type"],
        "status": entry["status"],
        "path": Value::Null,
        "summary": entry["summary"],
        "duration": entry["duration"],
        "details": entry["details"],
    })
}

fn ui_detail_text(ctx: &Context, entry: &Value) -> String {
    let translate = |message| crate::i18n::translate(ctx, message);
    let heading = if entry["type"] == "scan" {
        translate("SCAN LOG")
    } else {
        translate("UPDATE LOG")
    };
    let mut metadata = vec![
        format!(
            "{}: {}",
            translate("ID"),
            entry["id"].as_str().unwrap_or_default()
        ),
        format!(
            "{}: {}",
            translate("Timestamp"),
            entry["timestamp"].as_str().unwrap_or_default()
        ),
        format!(
            "{}: {}",
            translate("Type"),
            entry["type"].as_str().unwrap_or_default()
        ),
        format!(
            "{}: {}",
            translate("Status"),
            entry["status"].as_str().unwrap_or_default()
        ),
    ];
    if let Some(duration) = visible_duration(ctx, entry["duration"].as_f64().unwrap_or(0.0)) {
        metadata.push(format!("{}: {duration}", translate("Duration")));
    }
    let details = entry["details"].as_str().unwrap_or_default();
    let output = if details.is_empty() {
        String::new()
    } else {
        format!(
            "\n--------------------------------------------------\n{}:\n--------------------------------------------------\n{details}",
            translate("Full Output")
        )
    };
    format!(
        "{heading}\n==================================================\n\n{}\n\n{}:\n  {}{output}",
        metadata.join("\n"),
        translate("Summary"),
        entry["summary"].as_str().unwrap_or_default()
    )
}
fn export_duration(entry: &Value) -> String {
    let duration = entry["duration"].as_f64().unwrap_or(0.0);
    if duration > 0.0 {
        format!("{duration:.2}")
    } else {
        "0".to_owned()
    }
}

fn visible_duration(ctx: &Context, seconds: f64) -> Option<String> {
    if seconds <= 0.0 {
        None
    } else if seconds < 60.0 {
        let count = format!("{seconds:.2}");
        let plural_count = if seconds == 1.0 {
            1
        } else if seconds > 1.0 {
            2
        } else {
            0
        };
        Some(trnf(
            ctx,
            "{count} second",
            "{count} seconds",
            plural_count,
            &[("{count}", &count)],
        ))
    } else if seconds < 3600.0 {
        Some(format!(
            "{}m {}s",
            (seconds / 60.0).floor(),
            (seconds % 60.0).round()
        ))
    } else {
        Some(format!(
            "{}h {}m",
            (seconds / 3600.0).floor(),
            ((seconds % 3600.0) / 60.0).floor()
        ))
    }
}

fn csv_field(field: &str) -> String {
    if field.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", field.replace('"', "\"\""))
    } else {
        field.to_owned()
    }
}

fn timeframe(value: &str) -> AppResult<(&'static str, Option<DateTime<Local>>)> {
    let now = Local::now();
    match value {
        "day" | "daily" => Ok(("day", Some(now - Duration::days(1)))),
        "week" | "weekly" => Ok(("week", Some(now - Duration::weeks(1)))),
        "month" | "monthly" => Ok(("month", Some(now - Duration::days(30)))),
        "all" => Ok(("all", None)),
        _ => Err("timeframe must be day, week, month, or all".to_owned()),
    }
}

fn trend_data(scans: &[Value], timeframe: &str, now: DateTime<Local>) -> Vec<Value> {
    let today = now.date_naive();
    let (start, days_per_bucket) = match timeframe {
        "day" => (today - Duration::days(1), 1),
        "week" => (today - Duration::days(6), 1),
        "month" => (today - Duration::days(29), 3),
        _ => {
            let earliest = scans
                .iter()
                .filter_map(|entry| parse_time(entry["timestamp"].as_str().unwrap_or_default()))
                .map(|time| time.date_naive())
                .filter(|date| *date <= today)
                .min()
                .unwrap_or(today);
            let inclusive_days = (today - earliest).num_days() + 1;
            (earliest, (inclusive_days + 11) / 12)
        }
    };
    let mut bucket = start;
    let mut trends = Vec::new();
    while bucket <= today {
        let end = (bucket + Duration::days(days_per_bucket)).min(today + Duration::days(1));
        let selected = scans
            .iter()
            .filter(|entry| {
                parse_time(entry["timestamp"].as_str().unwrap_or_default())
                    .map(|time| time.date_naive())
                    .is_some_and(|date| date >= bucket && date < end)
            })
            .collect::<Vec<_>>();
        trends.push(json!({
            "date": bucket.format("%Y-%m-%d").to_string(),
            "scans": selected.len(),
            "threats": selected.iter().map(|entry| threats(entry)).sum::<u64>(),
        }));
        bucket = end;
    }
    trends
}
fn protection_status(
    last: Option<&Value>,
    definition: Option<&str>,
    now: DateTime<Local>,
) -> Value {
    let last_scan_timestamp = last.and_then(|entry| entry["timestamp"].as_str());
    let last_scan_age_hours = last_scan_timestamp
        .and_then(parse_time)
        .map(|time| (now - time).num_seconds() as f64 / 3600.0);
    let definition_age_hours = definition
        .and_then(parse_time)
        .map(|time| (now - time).num_seconds() as f64 / 3600.0);
    let (level, message, is_protected) = match last_scan_age_hours {
        None => ("unprotected", "No scans performed yet", false),
        Some(hours) if hours > 24.0 * 30.0 => {
            ("unprotected", "Last scan was over 30 days ago", false)
        }
        Some(hours) if hours > 24.0 * 7.0 => ("at_risk", "Last scan was over a week ago", false),
        _ if definition_age_hours.is_some_and(|hours| hours > 24.0 * 7.0) => {
            ("at_risk", "Virus definitions are over 7 days old", false)
        }
        _ if definition_age_hours.is_some_and(|hours| hours > 24.0) => {
            ("at_risk", "Virus definitions are over 1 day old", false)
        }
        _ => ("protected", "System is protected", true),
    };
    json!({"level": level, "last_scan_timestamp": last_scan_timestamp, "last_scan_age_hours": last_scan_age_hours.map(round2), "last_definition_update": definition, "definition_age_hours": definition_age_hours.map(round2), "message": message, "is_protected": is_protected})
}

fn scanned_files(entry: &Value) -> u64 {
    entry["scanned_files"]
        .as_u64()
        .or_else(|| {
            let summary = entry["summary"].as_str().unwrap_or_default();
            let details = entry["details"].as_str().unwrap_or_default();
            extracted_count(&FILES_SCANNED, summary)
                .or_else(|| extracted_count(&FILES_SCANNED, details))
                .or_else(|| localized_scanned_files(summary))
                .or_else(|| localized_scanned_files(details))
        })
        .unwrap_or(0)
}

fn localized_scanned_files(text: &str) -> Option<u64> {
    localized_count(
        text,
        "Scanned: {count} file",
        "Scanned: {count} files",
        "Files Scanned: {count}",
    )
}

fn extracted_template_count(template: &str, text: &str) -> Option<u64> {
    let (prefix, suffix) = template.split_once("{count}")?;
    let prefix = prefix.trim_end();
    let suffix = suffix.trim_start();
    if prefix.is_empty() {
        return None;
    }
    for (start, _) in text.match_indices(prefix) {
        let remainder = text[start + prefix.len()..]
            .trim_start_matches(|character: char| character.is_whitespace());
        let digits = remainder
            .find(|character: char| !character.is_ascii_digit())
            .unwrap_or(remainder.len());
        if digits == 0 {
            continue;
        }
        let trailing = &remainder[digits..];
        let matches_suffix = if suffix.is_empty() {
            trailing
                .chars()
                .next()
                .is_none_or(|character| !character.is_alphanumeric())
        } else {
            trailing
                .trim_start_matches(|character: char| character.is_whitespace())
                .starts_with(suffix)
        };
        if matches_suffix {
            return remainder[..digits].parse().ok();
        }
    }
    None
}
fn threats(entry: &Value) -> u64 {
    if entry["status"] != "infected" {
        return 0;
    }
    entry["infected_count"]
        .as_u64()
        .or_else(|| {
            let summary = entry["summary"].as_str().unwrap_or_default();
            let details = entry["details"].as_str().unwrap_or_default();
            extracted_count(&THREATS_FOUND, summary)
                .or_else(|| extracted_count(&THREATS_FOUND, details))
                .or_else(|| localized_threats(summary))
                .or_else(|| localized_threats(details))
        })
        .unwrap_or(1)
}

fn localized_threats(text: &str) -> Option<u64> {
    localized_count(
        text,
        "Threat found: {count}",
        "Threats found: {count}",
        "Threats Found: {count}",
    )
}

fn localized_count(text: &str, singular: &str, plural: &str, label: &str) -> Option<u64> {
    let mut count = None;
    crate::i18n::visit_historical_plural_translations(singular, plural, |template| {
        if count.is_none() {
            count = extracted_template_count(template, text);
        }
    });
    if count.is_none() {
        crate::i18n::visit_historical_translations(label, |template| {
            if count.is_none() {
                count = extracted_template_count(template, text);
            }
        });
    }
    count
}
fn extracted_count(pattern: &Regex, text: &str) -> Option<u64> {
    pattern.captures(text).and_then(|captures| {
        captures
            .iter()
            .skip(1)
            .flatten()
            .find_map(|capture| capture.as_str().parse().ok())
    })
}

fn build_scan_fields(ctx: &Context, raw: &Map<String, Value>, status: &str) -> (String, String) {
    let infected = raw
        .get("infected_count")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let suffix = raw
        .get("backend_suffix")
        .and_then(Value::as_str)
        .map(private_line)
        .filter(|suffix| !suffix.is_empty())
        .map(|suffix| format!(" {suffix}"))
        .unwrap_or_default();
    let summary = match status {
        "clean" => format!("{}{}", crate::i18n::translate(ctx, "Scan Complete"), suffix),
        "infected" if infected > 0 => {
            let count = infected.to_string();
            trnf(
                ctx,
                "Found {count} threat{suffix}",
                "Found {count} threats{suffix}",
                infected,
                &[("{count}", &count), ("{suffix}", &suffix)],
            )
        }
        "infected" => format!(
            "{}{}",
            crate::i18n::translate(ctx, "Threats Detected"),
            suffix
        ),
        "cancelled" => format!(
            "{}{}",
            crate::i18n::translate(ctx, "Scan Cancelled"),
            suffix
        ),
        _ => format!("{}{}", crate::i18n::translate(ctx, "Scan Error"), suffix),
    };
    let files = raw
        .get("scanned_files")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let dirs = raw.get("scanned_dirs").and_then(Value::as_u64).unwrap_or(0);
    let mut details = Vec::new();
    if files > 0 || dirs > 0 {
        let file_count = files.to_string();
        let directory_count = dirs.to_string();
        let scanned_files = trnf(
            ctx,
            "Scanned: {count} file",
            "Scanned: {count} files",
            files,
            &[("{count}", &file_count)],
        );
        let scanned_directories = trnf(
            ctx,
            "{count} directory",
            "{count} directories",
            dirs,
            &[("{count}", &directory_count)],
        );
        details.push(format!("{scanned_files}, {scanned_directories}"));
    }
    if infected > 0 {
        let count = infected.to_string();
        details.push(trnf(
            ctx,
            "Threat found: {count}",
            "Threats found: {count}",
            infected,
            &[("{count}", &count)],
        ));
        if let Some(threats) = raw.get("threat_details").and_then(Value::as_array) {
            for threat in threats {
                let Some(name) = threat
                    .as_object()
                    .and_then(|threat| threat.get("threat_name").or_else(|| threat.get("name")))
                    .and_then(Value::as_str)
                else {
                    continue;
                };
                let name = private_line(name);
                if !name.is_empty() {
                    details.push(format!("  - {name}"));
                }
            }
        }
    }
    if let Some(error) = raw.get("error_message").and_then(Value::as_str) {
        details.push(format!("Error: {}", private_line(error)));
    }
    (summary, details.join("\n"))
}

fn debug_files(dir: &Path) -> AppResult<Vec<PathBuf>> {
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut files = fs::read_dir(dir)
        .map_err(|error| format!("reading debug logs: {error}"))?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with(DEBUG_FILE))
        })
        .collect::<Vec<_>>();
    files.sort();
    Ok(files)
}

fn migrate_debug(dir: &Path) -> AppResult<()> {
    if fs::read_to_string(dir.join(DEBUG_PRIVACY_MARKER))
        .ok()
        .as_deref()
        == Some(PRIVACY_VERSION)
    {
        return Ok(());
    }
    for path in debug_files(dir)? {
        let redacted = private_text(&fs::read_to_string(&path).map_err(|error| error.to_string())?);
        crate::common::atomic_write(&path, redacted.as_bytes(), 0o600)?;
    }
    crate::common::atomic_write(
        &dir.join(DEBUG_PRIVACY_MARKER),
        PRIVACY_VERSION.as_bytes(),
        0o600,
    )
}

fn rotate_debug(dir: &Path, incoming_bytes: u64) -> AppResult<()> {
    let current = dir.join(DEBUG_FILE);
    if fs::metadata(&current)
        .map(|metadata| metadata.len().saturating_add(incoming_bytes) > DEBUG_MAX_BYTES)
        .unwrap_or(false)
    {
        let oldest = dir.join(format!("{DEBUG_FILE}.{DEBUG_BACKUPS}"));
        let _ = fs::remove_file(oldest);
        for index in (1..DEBUG_BACKUPS).rev() {
            let from = dir.join(format!("{DEBUG_FILE}.{index}"));
            let to = dir.join(format!("{DEBUG_FILE}.{}", index + 1));
            if from.exists() {
                fs::rename(from, to).map_err(|error| error.to_string())?;
            }
        }
        fs::rename(&current, dir.join(format!("{DEBUG_FILE}.1")))
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn private_line(value: &str) -> String {
    redact(&crate::common::sanitize_line(value))
}
fn private_text(value: &str) -> String {
    redact(&crate::common::sanitize_text(value))
}
fn redact(value: &str) -> String {
    let output = URL.replace_all(value, "[REDACTED_URL]");
    let output = HASH.replace_all(&output, "[REDACTED_HASH]");
    let mut output = redact_paths(&output);
    redact_secrets(&mut output);
    output
}

pub(crate) fn redact_secrets(output: &mut String) {
    for prefix in [
        "api_key=",
        "token=",
        "authorization:",
        "bearer ",
        "password=",
        "secret=",
        "key=",
        "x-api-key:",
    ] {
        let mut offset = 0;
        while let Some(relative) = find_ascii_case_insensitive(&output[offset..], prefix) {
            let index = offset + relative;
            let mut value_start = skip_whitespace(output, index + prefix.len());
            if prefix == "authorization:" {
                value_start = authorization_credential_start(output, value_start);
            }
            let end = output[value_start..]
                .find(char::is_whitespace)
                .map(|length| value_start + length)
                .unwrap_or(output.len());
            if value_start == end {
                offset = index + prefix.len();
                continue;
            }
            output.replace_range(value_start..end, "[REDACTED_SECRET]");
            offset = value_start + "[REDACTED_SECRET]".len();
        }
    }
}

fn find_ascii_case_insensitive(value: &str, needle: &str) -> Option<usize> {
    value.as_bytes().windows(needle.len()).position(|window| {
        window
            .iter()
            .zip(needle.bytes())
            .all(|(actual, expected)| actual.eq_ignore_ascii_case(&expected))
    })
}

fn skip_whitespace(value: &str, mut index: usize) -> usize {
    while let Some(character) = value[index..].chars().next() {
        if !character.is_whitespace() {
            break;
        }
        index += character.len_utf8();
    }
    index
}

fn authorization_credential_start(value: &str, start: usize) -> usize {
    for scheme in ["bearer", "basic"] {
        let end = start + scheme.len();
        if value
            .get(start..end)
            .is_some_and(|candidate| candidate.eq_ignore_ascii_case(scheme))
            && value.get(end..).is_some_and(|remaining| {
                remaining.is_empty() || remaining.chars().next().is_some_and(char::is_whitespace)
            })
        {
            return skip_whitespace(value, end);
        }
    }
    start
}

fn redact_paths(value: &str) -> String {
    let mut output = String::with_capacity(value.len());
    let mut copied_until = 0;
    for (index, _) in value.char_indices() {
        if index < copied_until || !path_starts_at(value, index) {
            continue;
        }
        let end = path_end(value, index);
        if end > index {
            output.push_str(&value[copied_until..index]);
            output.push_str("[REDACTED_PATH]");
            copied_until = end;
        }
    }
    output.push_str(&value[copied_until..]);
    output
}

fn path_starts_at(value: &str, index: usize) -> bool {
    let boundary = value[..index].chars().next_back().is_none_or(|character| {
        character.is_whitespace()
            || matches!(character, '"' | '\'' | '(' | '[' | '{' | '=' | ',' | ':')
    });
    if !boundary {
        return false;
    }
    let rest = &value[index..];
    rest.starts_with("file://")
        || rest.starts_with("~/")
        || rest.starts_with('/')
        || (rest.len() >= 3
            && rest.as_bytes()[0].is_ascii_alphabetic()
            && rest.as_bytes()[1] == b':'
            && matches!(rest.as_bytes()[2], b'/' | b'\\'))
}

fn path_end(value: &str, start: usize) -> usize {
    let mut cursor = start;
    while cursor < value.len() {
        let character = value[cursor..]
            .chars()
            .next()
            .expect("cursor remains at character boundary");
        if character.is_whitespace() {
            let next = cursor + character.len_utf8();
            if path_continues_after_space(&value[next..]) {
                cursor = next;
                continue;
            }
            break;
        }
        if character == ':'
            && ((value[start..].starts_with("file://") && cursor == start + 4)
                || (cursor == start + 1
                    && value[start..]
                        .chars()
                        .next()
                        .is_some_and(|character| character.is_ascii_alphabetic())))
        {
            cursor += character.len_utf8();
            continue;
        }
        if matches!(
            character,
            '"' | '\'' | '<' | '>' | '|' | ',' | ';' | ':' | ')' | ']' | '}'
        ) {
            break;
        }
        cursor += character.len_utf8();
    }
    cursor
}

fn path_continues_after_space(value: &str) -> bool {
    value
        .split_whitespace()
        .take(2)
        .any(|segment| segment.contains(['/', '\\', '.', '~']))
}
fn string_field<'a>(object: &'a Map<String, Value>, field: &str, fallback: &'a str) -> &'a str {
    object
        .get(field)
        .and_then(Value::as_str)
        .unwrap_or(fallback)
}
fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '_' | '-'))
}
fn required_id(args: &Value) -> AppResult<&str> {
    args.get("id")
        .and_then(Value::as_str)
        .filter(|id| valid_id(id))
        .ok_or_else(|| "a valid log id is required".to_owned())
}
fn log_path(dir: &Path, id: &str) -> AppResult<PathBuf> {
    if !valid_id(id) {
        return Err("invalid log identifier".to_owned());
    }
    let path = dir.join(format!("{id}.json"));
    if path
        .components()
        .any(|component| matches!(component, Component::ParentDir))
    {
        return Err("invalid log identifier".to_owned());
    }
    Ok(path)
}
fn safe_name(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default()
        .to_owned()
}
fn required_debug_name(args: &Value) -> AppResult<&str> {
    let name = args
        .get("name")
        .and_then(Value::as_str)
        .ok_or_else(|| "debug log name is required".to_owned())?;
    if name.starts_with(DEBUG_FILE)
        && !name.contains('/')
        && !name.contains('\\')
        && !name.contains("..")
    {
        Ok(name)
    } else {
        Err("invalid debug log name".to_owned())
    }
}
fn parse_time(value: &str) -> Option<DateTime<Local>> {
    DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|value| value.with_timezone(&Local))
        .or_else(|| {
            NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f")
                .ok()
                .and_then(|value| Local.from_local_datetime(&value).single())
        })
        .or_else(|| {
            NaiveDate::parse_from_str(value, "%Y-%m-%d")
                .ok()
                .and_then(|date| {
                    Local
                        .from_local_datetime(&date.and_hms_opt(0, 0, 0)?)
                        .single()
                })
        })
}
fn now_iso() -> String {
    Utc::now().to_rfc3339()
}
fn round2(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}
fn level_rank(level: &str) -> u8 {
    match level {
        "DEBUG" => 0,
        "INFO" => 1,
        "WARNING" | "WARN" => 2,
        "ERROR" => 3,
        _ => 2,
    }
}
fn restrict_dir(path: &Path) -> AppResult<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}
fn restrict_file(path: &Path) -> AppResult<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}
