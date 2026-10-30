use crate::common::{atomic_write, is_flatpak, Context};
use crate::{host, AppResult};
use chrono::Local;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};

const SYSTEM_PATH_PREFIXES: [&str; 4] = ["/etc/", "/usr/", "/var/", "/opt/"];
const CLAMD_SIZE_DIRECTIVES: [&str; 3] = ["MaxFileSize", "MaxScanSize", "OnAccessMaxFileSize"];

static AUTHORIZED_DOCUMENTS: LazyLock<Mutex<BTreeMap<PathBuf, ConfigDocument>>> =
    LazyLock::new(|| Mutex::new(BTreeMap::new()));
const BOOLEAN_DIRECTIVES: &[&str] = &[
    "LogVerbose",
    "LogSyslog",
    "LogTime",
    "LogRotate",
    "Foreground",
    "ScanArchive",
    "ScanPDF",
    "ScanHTML",
    "ScanMail",
    "ScanOLE2",
    "ScanPE",
    "ScanELF",
    "ScanSWF",
    "DetectPUA",
    "AlertBrokenExecutables",
    "FollowDirectorySymlinks",
    "FollowFileSymlinks",
    "CrossFilesystems",
    "ScriptedUpdates",
    "OnAccessPrevention",
    "OnAccessExtraScanning",
    "OnAccessDenyOnError",
    "OnAccessDisableDDD",
    "OnAccessExcludeRootUID",
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ConfigKind {
    Clamd,
    Freshclam,
    Onaccess,
}

impl ConfigKind {
    fn parse(value: &str) -> AppResult<Self> {
        match value {
            "clamd" => Ok(Self::Clamd),
            "freshclam" => Ok(Self::Freshclam),
            "onaccess" => Ok(Self::Onaccess),
            _ => Err(format!("Unknown configuration kind: {value}")),
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Clamd => "clamd",
            Self::Freshclam => "freshclam",
            Self::Onaccess => "onaccess",
        }
    }

    fn settings_key(self) -> &'static str {
        match self {
            Self::Freshclam => "freshclam_conf_path",
            Self::Clamd | Self::Onaccess => "clamd_conf_path",
        }
    }

    fn resolved_kind(self) -> Self {
        match self {
            Self::Onaccess => Self::Clamd,
            other => other,
        }
    }
}

#[derive(Clone, Debug)]
struct ConfigDocument {
    raw_lines: Vec<String>,
    values: BTreeMap<String, Vec<String>>,
    line_numbers: BTreeMap<String, Vec<usize>>,
    key_order: Vec<String>,
    encoding: &'static str,
}

impl ConfigDocument {
    fn parse(bytes: &[u8]) -> Self {
        let (content, encoding) = match std::str::from_utf8(bytes) {
            Ok(content) => (content.to_owned(), "utf-8"),
            Err(_) => (
                bytes.iter().map(|byte| char::from(*byte)).collect(),
                "latin-1",
            ),
        };
        let raw_lines = content.lines().map(str::to_owned).collect::<Vec<_>>();
        let mut values = BTreeMap::<String, Vec<String>>::new();
        let mut line_numbers = BTreeMap::<String, Vec<usize>>::new();
        let mut key_order = Vec::new();
        for (index, raw) in raw_lines.iter().enumerate() {
            let stripped = raw.trim();
            if stripped.is_empty() || stripped.starts_with('#') {
                continue;
            }
            let mut pieces = stripped.splitn(2, char::is_whitespace);
            let key = pieces.next().unwrap_or_default().to_owned();
            let value = pieces.next().unwrap_or_default().trim().to_owned();
            if !values.contains_key(&key) {
                key_order.push(key.clone());
            }
            values.entry(key.clone()).or_default().push(value);
            line_numbers.entry(key).or_default().push(index);
        }
        Self {
            raw_lines,
            values,
            line_numbers,
            key_order,
            encoding,
        }
    }

    fn values_json(&self) -> Value {
        let values = self
            .values
            .iter()
            .map(|(key, entries)| {
                (
                    key.clone(),
                    Value::Array(entries.iter().cloned().map(Value::String).collect()),
                )
            })
            .collect::<Map<String, Value>>();
        Value::Object(values)
    }

    fn replace_values(&self, proposed: BTreeMap<String, Vec<String>>) -> Self {
        let mut updated = self.clone();
        let existing = updated.values.keys().cloned().collect::<Vec<_>>();
        for key in existing {
            if !proposed.contains_key(&key) {
                for line in updated.line_numbers.get(&key).into_iter().flatten() {
                    updated.raw_lines[*line].clear();
                }
                updated.values.remove(&key);
                updated.line_numbers.remove(&key);
            }
        }
        for (key, entries) in proposed {
            let old_lines = updated.line_numbers.remove(&key).unwrap_or_default();
            if entries.is_empty() {
                for line in old_lines {
                    updated.raw_lines[line].clear();
                }
                updated.values.remove(&key);
                continue;
            }
            if !updated.key_order.iter().any(|known| known == &key) {
                updated.key_order.push(key.clone());
            }
            let mut new_lines = Vec::new();
            for (index, value) in entries.iter().enumerate() {
                let rendered = render_directive(&key, value);
                if let Some(line) = old_lines.get(index) {
                    updated.raw_lines[*line] = rendered;
                    new_lines.push(*line);
                } else {
                    new_lines.push(usize::MAX);
                }
            }
            for stale in old_lines.iter().skip(entries.len()) {
                updated.raw_lines[*stale].clear();
            }
            updated.values.insert(key.clone(), entries);
            updated.line_numbers.insert(key, new_lines);
        }
        updated
    }

    fn normalize_size_units(&mut self) -> bool {
        let mut changed = false;
        for directive in CLAMD_SIZE_DIRECTIVES {
            let Some(entries) = self.values.get(directive) else {
                continue;
            };
            if !entries.iter().any(|value| {
                let trimmed = value.trim();
                trimmed.parse::<u64>().is_ok_and(|size| size > 0)
            }) {
                continue;
            }
            let normalized = entries
                .iter()
                .map(|value| normalize_size_value(value))
                .collect();
            self.apply_entries(directive, normalized);
            changed = true;
        }
        changed
    }

    fn apply_entries(&mut self, key: &str, entries: Vec<String>) {
        let old_lines = self.line_numbers.remove(key).unwrap_or_default();
        let mut new_lines = Vec::new();
        for (index, value) in entries.iter().enumerate() {
            let rendered = render_directive(key, value);
            if let Some(line) = old_lines.get(index) {
                self.raw_lines[*line] = rendered;
                new_lines.push(*line);
            } else {
                new_lines.push(usize::MAX);
            }
        }
        for stale in old_lines.iter().skip(entries.len()) {
            self.raw_lines[*stale].clear();
        }
        if entries.is_empty() {
            self.values.remove(key);
        } else {
            if !self.key_order.iter().any(|known| known == key) {
                self.key_order.push(key.to_owned());
            }
            self.values.insert(key.to_owned(), entries);
            self.line_numbers.insert(key.to_owned(), new_lines);
        }
    }

    fn serialize(&self) -> String {
        let mut lines = self.raw_lines.clone();
        let mut additions = Vec::new();
        for key in &self.key_order {
            let Some(values) = self.values.get(key) else {
                continue;
            };
            let locations = self.line_numbers.get(key).cloned().unwrap_or_default();
            for (index, value) in values.iter().enumerate() {
                if locations.get(index).copied() == Some(usize::MAX) {
                    additions.push(render_directive(key, value));
                }
            }
        }
        if !additions.is_empty() {
            if lines.last().is_some_and(|last| !last.trim().is_empty()) {
                lines.push(String::new());
            }
            lines.extend(additions);
        }
        if lines.is_empty() {
            String::new()
        } else {
            format!("{}\n", lines.join("\n"))
        }
    }
}

#[derive(Clone, Debug)]
struct Proposal {
    kind: ConfigKind,
    path: PathBuf,
    document: ConfigDocument,
    changed: bool,
}

#[derive(Clone, Debug)]
struct ConfigOutcome {
    kind: ConfigKind,
    path: PathBuf,
    changed: bool,
    written: bool,
    error: Option<String>,
}

impl ConfigOutcome {
    fn value(&self) -> Value {
        json!({
            "kind": self.kind.as_str(),
            "path": self.path,
            "changed": self.changed,
            "written": self.written,
            "error": self.error,
        })
    }
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "detect" => detect(ctx, args),
        "load" => load(ctx, args),
        "read_authorized" => read_authorized(ctx, args),
        "validate" => validate(ctx, args),
        "save" => save(ctx, args, false),
        "apply" => save(ctx, args, true),
        _ => Err(format!("Unknown config action: {action}")),
    }
}

fn detect(ctx: &Context, args: Value) -> AppResult<Value> {
    let object = object(args)?;
    let kind = ConfigKind::parse(required_string(&object, "kind")?.as_str())?;
    let explicit_path = optional_string(&object, "path")?;
    let path = explicit_path
        .or_else(|| configured_path(ctx, kind).ok().flatten())
        .or_else(|| detected_path(kind));
    let Some(path) = path else {
        return Ok(
            json!({"kind": kind.as_str(), "path": Value::Null, "exists": false, "readable": false}),
        );
    };
    let path = PathBuf::from(path);
    let exists = host::config_file_exists(path.to_string_lossy().as_ref());
    let read = if exists {
        read_config_bytes(ctx, &path)
    } else {
        Err(crate::i18n::translate(ctx, "Configuration file not found"))
    };
    Ok(json!({
        "kind": kind.as_str(),
        "path": path,
        "exists": exists,
        "readable": read.is_ok(),
        "error": read.err(),
    }))
}

fn load(ctx: &Context, args: Value) -> AppResult<Value> {
    let object = object(args)?;
    let kind = ConfigKind::parse(required_string(&object, "kind")?.as_str())?;
    let path = optional_string(&object, "path")?
        .or_else(|| configured_path(ctx, kind).ok().flatten())
        .or_else(|| detected_path(kind));
    let Some(path) = path else {
        return Ok(
            json!({"kind": kind.as_str(), "path": Value::Null, "values": {}, "readable": false, "needs_size_unit_migration": false, "error": crate::i18n::translate(ctx, "Configuration file not found")}),
        );
    };
    let path = absolute_path(&path)?;
    match read_config_bytes(ctx, &path) {
        Ok(bytes) => {
            let mut document = ConfigDocument::parse(&bytes);
            let needs_size_unit_migration = if kind.resolved_kind() == ConfigKind::Clamd {
                document.normalize_size_units()
            } else {
                false
            };
            Ok(json!({
                "kind": kind.as_str(),
                "path": path,
                "values": document.values_json(),
                "readable": true,
                "encoding": document.encoding,
                "needs_size_unit_migration": needs_size_unit_migration,
            }))
        }
        Err(error) => Ok(json!({
            "kind": kind.as_str(),
            "path": path,
            "values": {},
            "readable": false,
            "needs_size_unit_migration": false,
            "error": error,
        })),
    }
}

fn read_authorized(ctx: &Context, args: Value) -> AppResult<Value> {
    let object = object(args)?;
    let path = absolute_path(&required_string(&object, "path")?)?;
    // This operation is intentionally the only config entry point that can request pkexec.
    let bytes = crate::privileged::read_config(ctx, &path)?;
    let document = ConfigDocument::parse(&bytes);
    cache_authorized_document(path.clone(), document.clone());
    let mut display_document = document;
    let needs_size_unit_migration = display_document.normalize_size_units();
    Ok(json!({
        "path": path,
        "values": display_document.values_json(),
        "readable": true,
        "encoding": display_document.encoding,
        "needs_size_unit_migration": needs_size_unit_migration,
        "authorized": true,
    }))
}

fn validate(ctx: &Context, args: Value) -> AppResult<Value> {
    let object = object(args)?;
    let kind = ConfigKind::parse(required_string(&object, "kind")?.as_str())?;
    let values = values(&object)?;
    let errors = validate_values(ctx, kind, &values);
    Ok(json!({"valid": errors.is_empty(), "errors": errors}))
}

fn save(ctx: &Context, args: Value, apply_schedule: bool) -> AppResult<Value> {
    let object = object(args)?;
    let proposals = prepare_proposals(ctx, &object)?;
    let schedule = optional_object(&object, "schedule")?
        .map(|schedule| {
            crate::scheduler::normalize_schedule(&Value::Object(schedule)).map_err(|error| {
                crate::i18n::translate(ctx, "Invalid scheduled scan configuration: {error}")
                    .replace("{error}", &error)
            })
        })
        .transpose()?;
    let path_selection_changed = proposals.iter().any(|proposal| {
        configured_path(ctx, proposal.kind)
            .ok()
            .flatten()
            .as_deref()
            != Some(proposal.path.to_string_lossy().as_ref())
    });
    let mut outcomes = proposals
        .iter()
        .map(|proposal| ConfigOutcome {
            kind: proposal.kind,
            path: proposal.path.clone(),
            changed: proposal.changed,
            written: !proposal.changed,
            error: None,
        })
        .collect::<Vec<_>>();
    let mut durable_groups = Vec::<String>::new();
    let mut failures = Vec::<Value>::new();

    for proposal in proposals.iter().filter(|proposal| proposal.changed) {
        backup_config(&proposal.path);
    }

    let mut direct = Vec::new();
    let mut protected = Vec::new();
    for (index, proposal) in proposals.iter().enumerate() {
        if !proposal.changed {
            continue;
        }
        if needs_elevation(&proposal.path) {
            if let Err(error) = crate::privileged::validate_destination(&proposal.path) {
                outcomes[index].error = Some(error.clone());
                failures.push(failure("clamav_configs", &error, Some(&proposal.path)));
            } else {
                protected.push(index);
            }
        } else {
            direct.push(index);
        }
    }

    let mut direct_failed = !failures.is_empty();
    if !direct_failed {
        for position in 0..direct.len() {
            let index = direct[position];
            let proposal = &proposals[index];
            match write_direct(
                ctx,
                &proposal.path,
                proposal.document.serialize().as_bytes(),
            ) {
                Ok(()) => outcomes[index].written = true,
                Err(error) => {
                    outcomes[index].error = Some(error.clone());
                    failures.push(failure("clamav_configs", &error, Some(&proposal.path)));
                    direct_failed = true;
                    for skipped in direct.iter().skip(position + 1) {
                        let message = crate::i18n::translate(
                            ctx,
                            "Not attempted because an earlier direct configuration write failed",
                        );
                        outcomes[*skipped].error = Some(message.to_owned());
                        failures.push(failure(
                            "clamav_configs",
                            &message,
                            Some(&proposals[*skipped].path),
                        ));
                    }
                    break;
                }
            }
        }
    }

    if !direct_failed && !protected.is_empty() {
        let staged = protected
            .iter()
            .map(|index| {
                let proposal = &proposals[*index];
                crate::privileged::stage_config(
                    proposal.document.serialize().as_bytes(),
                    &proposal.path,
                )
            })
            .collect::<AppResult<Vec<_>>>();
        match staged.and_then(|writes| crate::privileged::write_staged_configs(ctx, &writes)) {
            Ok(result) => {
                for index in protected {
                    let path = &proposals[index].path;
                    if result.applied_paths.iter().any(|applied| applied == path) {
                        outcomes[index].written = true;
                    } else {
                        let error = result
                            .failures
                            .iter()
                            .find(|failure| failure.destination == *path)
                            .map(|failure| failure.message.clone())
                            .unwrap_or_else(|| {
                                crate::i18n::translate(ctx, "Protected configuration write failed")
                            });
                        outcomes[index].error = Some(error.clone());
                        failures.push(failure("clamav_configs", &error, Some(path)));
                    }
                }
            }
            Err(error) => {
                for index in protected {
                    outcomes[index].error = Some(error.clone());
                    failures.push(failure(
                        "clamav_configs",
                        &error,
                        Some(&proposals[index].path),
                    ));
                }
            }
        }
    } else if direct_failed {
        for index in protected {
            let error = crate::i18n::translate(
                ctx,
                "Not attempted because an earlier direct configuration write failed",
            );
            outcomes[index].error = Some(error.clone());
            failures.push(failure(
                "clamav_configs",
                &error,
                Some(&proposals[index].path),
            ));
        }
    }

    for (index, outcome) in outcomes.iter().enumerate() {
        if outcome.changed && outcome.written {
            cache_authorized_document(outcome.path.clone(), proposals[index].document.clone());
        }
    }
    if outcomes
        .iter()
        .any(|outcome| outcome.written && outcome.changed)
    {
        durable_groups.push("clamav_configs".to_owned());
    }

    let mut config_paths_durable = false;
    let mut successful_paths = outcomes
        .iter()
        .filter(|outcome| outcome.error.is_none())
        .map(|outcome| {
            (
                outcome.kind.settings_key().to_owned(),
                Value::String(outcome.path.to_string_lossy().into_owned()),
            )
        })
        .collect::<Map<String, Value>>();
    let config_path_keys = successful_paths.keys().cloned().collect::<Vec<_>>();
    if outcomes.iter().any(|outcome| {
        outcome.kind.resolved_kind() == ConfigKind::Clamd && outcome.changed && outcome.written
    }) {
        successful_paths.insert(
            "clamd_size_limit_unit_migration_done".to_owned(),
            Value::Bool(true),
        );
    }
    if !successful_paths.is_empty() {
        match ctx.update_settings(Value::Object(successful_paths)) {
            Ok(_) => {
                config_paths_durable = true;
                durable_groups.push("config_paths".to_owned());
            }
            Err(error) => {
                let message =
                    crate::i18n::translate(ctx, "Cannot save configuration paths: {error}")
                        .replace("{error}", &error);
                failures.push(failure("config_paths", &message, None));
            }
        }
    }

    if let Some(schedule) = schedule {
        let schedule_value = serde_json::to_value(&schedule).map_err(|error| error.to_string())?;
        let settings_patch = schedule_settings(
            schedule_value
                .as_object()
                .ok_or_else(|| "Normalized schedule is not an object".to_owned())?,
        )?;
        if apply_schedule {
            match crate::scheduler::apply(ctx, &schedule) {
                Ok(scheduler_result) => {
                    let scheduler_success = scheduler_result
                        .get("success")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    let scheduler_durable = scheduler_result
                        .get("durable")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    if scheduler_success && scheduler_durable {
                        durable_groups.push("scheduler".to_owned());
                        match ctx.update_settings(Value::Object(settings_patch)) {
                            Ok(_) => durable_groups.push("scheduled_preferences".to_owned()),
                            Err(error) => {
                                let message = crate::i18n::translate(
                                    ctx,
                                    "Cannot save scheduled scan preferences: {error}",
                                )
                                .replace("{error}", &error);
                                failures.push(failure("scheduled_preferences", &message, None));
                            }
                        }
                    } else {
                        let diagnostic = scheduler_result
                            .get("error")
                            .and_then(Value::as_str)
                            .unwrap_or("No scheduler failure detail was provided");
                        let error = crate::i18n::translate(
                            ctx,
                            "Failed to apply scheduled scan configuration: {error}",
                        )
                        .replace("{error}", diagnostic);
                        failures.push(failure("scheduler", &error, None));
                    }
                }
                Err(error) => {
                    let message = crate::i18n::translate(
                        ctx,
                        "Failed to apply scheduled scan configuration: {error}",
                    )
                    .replace("{error}", &error);
                    failures.push(failure("scheduler", &message, None));
                }
            }
        } else {
            match ctx.update_settings(Value::Object(settings_patch)) {
                Ok(_) => durable_groups.push("scheduled_preferences".to_owned()),
                Err(error) => {
                    let message = crate::i18n::translate(
                        ctx,
                        "Cannot save scheduled scan preferences: {error}",
                    )
                    .replace("{error}", &error);
                    failures.push(failure("scheduled_preferences", &message, None));
                }
            }
        }
    }

    let changed = outcomes.iter().any(|outcome| outcome.changed)
        || path_selection_changed
        || object.contains_key("schedule");
    let status = if failures.is_empty() {
        if changed {
            "applied"
        } else {
            "no_changes"
        }
    } else if durable_groups.is_empty() {
        "failed"
    } else {
        "partially_applied"
    };
    Ok(json!({
        "status": status,
        "durable_groups": durable_groups,
        "failures": failures,
        "configs": outcomes.iter().map(ConfigOutcome::value).collect::<Vec<_>>(),
        "config_paths": {
            "changed": path_selection_changed,
            "durable": config_paths_durable,
            "durable_keys": if config_paths_durable { config_path_keys } else { Vec::new() },
        },
    }))
}
fn prepare_proposals(ctx: &Context, arguments: &Map<String, Value>) -> AppResult<Vec<Proposal>> {
    let configs = arguments
        .get("configs")
        .and_then(Value::as_array)
        .ok_or_else(|| "config.save requires configs array".to_owned())?;
    let mut unique_paths = BTreeSet::new();
    let mut selected_paths = BTreeMap::<&str, PathBuf>::new();
    let mut proposals = Vec::new();
    for config in configs {
        let config = config
            .as_object()
            .ok_or_else(|| "Each config proposal must be an object".to_owned())?;
        let kind = ConfigKind::parse(required_string(config, "kind")?.as_str())?;
        let path = absolute_path(&required_string(config, "path")?)?;
        if !unique_paths.insert(path.clone()) {
            return Err(crate::i18n::translate(
                ctx,
                "Configuration path appears more than once: {path}",
            )
            .replace("{path}", &path.to_string_lossy()));
        }
        if let Some(selected) = selected_paths.insert(kind.settings_key(), path.clone()) {
            if selected != path {
                return Err(crate::i18n::translate(
                    ctx,
                    "Configuration kinds sharing {setting} must use the same path",
                )
                .replace("{setting}", kind.settings_key()));
            }
        }
        let proposed_values = values(config)?;
        let loaded = match read_config_bytes(ctx, &path) {
            Ok(bytes) => ConfigDocument::parse(&bytes),
            Err(error) => authorized_document(&path).ok_or(error).map_err(|error| {
                crate::i18n::translate(ctx, "Cannot prepare {path}: {error}")
                    .replace("{path}", &path.to_string_lossy())
                    .replace("{error}", &error)
            })?,
        };
        let mut proposal = loaded.replace_values(proposed_values);
        proposal.normalize_size_units();
        let errors = validate_values(ctx, kind, &proposal.values);
        if !errors.is_empty() {
            return Err(errors.join("\n"));
        }
        let changed = proposal.serialize() != loaded.serialize();
        proposals.push(Proposal {
            kind,
            path,
            document: proposal,
            changed,
        });
    }
    Ok(proposals)
}

fn schedule_settings(schedule: &Map<String, Value>) -> AppResult<Map<String, Value>> {
    let aliases = [
        ("enabled", "scheduled_scans_enabled"),
        ("frequency", "schedule_frequency"),
        ("time", "schedule_time"),
        ("targets", "schedule_targets"),
        ("skip_on_battery", "schedule_skip_on_battery"),
        ("auto_quarantine", "schedule_auto_quarantine"),
        ("day_of_week", "schedule_day_of_week"),
        ("day_of_month", "schedule_day_of_month"),
    ];
    let mut patch = Map::new();
    for (input, setting) in aliases {
        if let Some(value) = schedule.get(input).or_else(|| schedule.get(setting)) {
            patch.insert(setting.to_owned(), value.clone());
        }
    }
    if patch.is_empty() {
        return Err("Schedule must include at least one schedule field".to_owned());
    }
    Ok(patch)
}

fn configured_path(ctx: &Context, kind: ConfigKind) -> AppResult<Option<String>> {
    let settings = ctx.settings()?;
    Ok(settings
        .get(kind.settings_key())
        .and_then(Value::as_str)
        .filter(|path| !path.trim().is_empty())
        .map(str::to_owned))
}

fn detected_path(kind: ConfigKind) -> Option<String> {
    match kind.resolved_kind() {
        ConfigKind::Freshclam => host::detect_freshclam_conf_path(),
        ConfigKind::Clamd | ConfigKind::Onaccess => host::detect_clamd_conf_path(),
    }
}

fn read_config_bytes(ctx: &Context, path: &Path) -> AppResult<Vec<u8>> {
    let read = if is_flatpak() && is_system_path(path) {
        host::read_host_bytes(path.to_string_lossy().as_ref())
    } else {
        fs::read(path).map_err(|error| error.to_string())
    };
    read.map_err(|error| {
        crate::i18n::translate(ctx, "Cannot read {path}: {error}")
            .replace("{path}", &path.to_string_lossy())
            .replace("{error}", &error)
    })
}

fn write_direct(ctx: &Context, path: &Path, content: &[u8]) -> AppResult<()> {
    if let Ok(metadata) = fs::symlink_metadata(path) {
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(
                crate::i18n::translate(ctx, "Configuration is not a regular file: {path}")
                    .replace("{path}", &path.to_string_lossy()),
            );
        }
    } else if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| {
            crate::i18n::translate(ctx, "Cannot create {path}: {error}")
                .replace("{path}", &parent.to_string_lossy())
                .replace("{error}", &error.to_string())
        })?;
    }
    let mode = fs::metadata(path)
        .map(|metadata| permissions_mode(&metadata))
        .unwrap_or(0o600);
    atomic_write(path, content, mode).map_err(|error| {
        crate::i18n::translate(ctx, "Cannot write {path}: {error}")
            .replace("{path}", &path.to_string_lossy())
            .replace("{error}", &error)
    })
}

fn backup_config(path: &Path) {
    if (is_flatpak() && is_system_path(path))
        || !fs::symlink_metadata(path)
            .map(|metadata| metadata.is_file() && !metadata.file_type().is_symlink())
            .unwrap_or(false)
    {
        return;
    }
    let suffix = Local::now().format("%Y%m%d_%H%M%S");
    let backup = path.with_extension(format!("bak.{suffix}"));
    let _ = fs::copy(path, backup);
}

fn cache_authorized_document(path: PathBuf, document: ConfigDocument) {
    if let Ok(mut documents) = AUTHORIZED_DOCUMENTS.lock() {
        documents.insert(path, document);
    }
}

fn authorized_document(path: &Path) -> Option<ConfigDocument> {
    AUTHORIZED_DOCUMENTS.lock().ok()?.get(path).cloned()
}

fn needs_elevation(path: &Path) -> bool {
    if is_flatpak() && is_system_path(path) {
        return true;
    }
    if path.exists() {
        return fs::OpenOptions::new().write(true).open(path).is_err();
    }
    crate::privileged::validate_destination(path).is_ok()
}

fn is_system_path(path: &Path) -> bool {
    let rendered = path.to_string_lossy();
    SYSTEM_PATH_PREFIXES
        .iter()
        .any(|prefix| rendered.starts_with(prefix))
}

fn absolute_path(raw: &str) -> AppResult<PathBuf> {
    let path = PathBuf::from(raw);
    if raw.trim().is_empty() || !path.is_absolute() {
        return Err("Configuration path must be absolute".to_owned());
    }
    Ok(path)
}

fn values(arguments: &Map<String, Value>) -> AppResult<BTreeMap<String, Vec<String>>> {
    let source = arguments
        .get("values")
        .and_then(Value::as_object)
        .ok_or_else(|| "Configuration values must be an object".to_owned())?;
    source
        .iter()
        .map(|(key, value)| {
            if key.trim().is_empty() || key.chars().any(char::is_whitespace) {
                return Err(format!("Invalid configuration directive: {key}"));
            }
            let entries = value
                .as_array()
                .ok_or_else(|| format!("Configuration directive {key} must be a string array"))?
                .iter()
                .map(|entry| {
                    entry.as_str().map(str::to_owned).ok_or_else(|| {
                        format!("Configuration directive {key} contains a non-string value")
                    })
                })
                .collect::<AppResult<Vec<_>>>()?;
            Ok((key.clone(), entries))
        })
        .collect()
}

fn validate_values(
    ctx: &Context,
    kind: ConfigKind,
    values: &BTreeMap<String, Vec<String>>,
) -> Vec<String> {
    let mut errors = Vec::new();
    for (key, entries) in values {
        for value in entries {
            if let Some(error) = validate_option(ctx, key, value) {
                errors.push(error);
            }
        }
    }
    if kind.resolved_kind() == ConfigKind::Clamd
        && values
            .get("OnAccessIncludePath")
            .is_some_and(|paths| !paths.is_empty())
        && !has_onaccess_loop_prevention(values)
    {
        errors.push(crate::i18n::translate(
            ctx,
            "On-Access scanning requires at least one loop-prevention exclusion: Exclude Username, Exclude User ID, or Exclude Root User",
        ));
    }
    errors
}

fn has_onaccess_loop_prevention(values: &BTreeMap<String, Vec<String>>) -> bool {
    values
        .get("OnAccessExcludeUname")
        .is_some_and(|entries| entries.iter().any(|entry| !entry.trim().is_empty()))
        || values.get("OnAccessExcludeUID").is_some_and(|entries| {
            entries
                .iter()
                .any(|entry| entry.trim().parse::<u32>().is_ok())
        })
        || values
            .get("OnAccessExcludeRootUID")
            .is_some_and(|entries| entries.iter().any(|entry| boolean(entry) == Some(true)))
}

fn validate_option(ctx: &Context, key: &str, value: &str) -> Option<String> {
    if BOOLEAN_DIRECTIVES.contains(&key) && boolean(value).is_none() {
        return Some(
            crate::i18n::translate(ctx, "{key}: invalid boolean value: {value}")
                .replace("{key}", key)
                .replace("{value}", value),
        );
    }
    let (minimum, maximum) = match key {
        "Checks" => (Some(0), Some(50)),
        "HTTPProxyPort" | "TCPSocket" => (Some(1), Some(65535)),
        "MaxRecursion" => (Some(1), Some(100)),
        "MaxFiles" => (Some(0), Some(1_000_000)),
        "MaxThreads" => (Some(1), Some(256)),
        "MaxDirectoryRecursion"
        | "MaxPartitions"
        | "MaxIconsPE"
        | "IdleTimeout"
        | "ReadTimeout"
        | "CommandReadTimeout"
        | "SendBufTimeout"
        | "MaxScanTime" => (Some(0), None),
        "OnAccessMaxThreads" => (Some(1), Some(64)),
        "OnAccessCurlTimeout" => (Some(0), Some(3600)),
        "OnAccessRetryAttempts" => (Some(0), Some(10)),
        "OnAccessExcludeUID" => (Some(0), Some(65534)),
        _ => (None, None),
    };
    if minimum.is_some() || maximum.is_some() {
        match value.parse::<i64>() {
            Ok(number) if minimum.is_some_and(|minimum| number < minimum) => {
                return Some(
                    crate::i18n::translate(ctx, "{key}: value {value} is below minimum {minimum}")
                        .replace("{key}", key)
                        .replace("{value}", &number.to_string())
                        .replace("{minimum}", &minimum.unwrap().to_string()),
                );
            }
            Ok(number) if maximum.is_some_and(|maximum| number > maximum) => {
                return Some(
                    crate::i18n::translate(ctx, "{key}: value {value} exceeds maximum {maximum}")
                        .replace("{key}", key)
                        .replace("{value}", &number.to_string())
                        .replace("{maximum}", &maximum.unwrap().to_string()),
                );
            }
            Ok(_) => {}
            Err(_) => {
                return Some(
                    crate::i18n::translate(ctx, "{key}: not a valid integer: {value}")
                        .replace("{key}", key)
                        .replace("{value}", value),
                );
            }
        }
    }
    if is_size_directive(key) && !valid_size(value) {
        return Some(
            crate::i18n::translate(ctx, "{key}: size must start with a number: {value}")
                .replace("{key}", key)
                .replace("{value}", value),
        );
    }
    if matches!(
        key,
        "DatabaseDirectory"
            | "UpdateLogFile"
            | "LogFile"
            | "NotifyClamd"
            | "PidFile"
            | "LocalSocket"
            | "TemporaryDirectory"
    ) && value.trim().is_empty()
    {
        return Some(
            crate::i18n::translate(ctx, "{key}: path cannot be empty").replace("{key}", key),
        );
    }
    if matches!(
        key,
        "HTTPProxyServer"
            | "HTTPProxyUsername"
            | "HTTPProxyPassword"
            | "DatabaseMirror"
            | "DatabaseOwner"
            | "User"
            | "OnAccessExcludeUname"
    ) && value.trim().is_empty()
    {
        return Some(
            crate::i18n::translate(ctx, "{key}: string value cannot be empty")
                .replace("{key}", key),
        );
    }
    if matches!(key, "DatabaseCustomURL" | "PrivateMirror")
        && !value.trim().is_empty()
        && !["http://", "https://", "ftp://", "ftps://", "file://"]
            .iter()
            .any(|scheme| value.to_ascii_lowercase().starts_with(scheme))
    {
        return Some(
            crate::i18n::translate(
                ctx,
                "{key}: URL must start with http(s)://, ftp(s)://, or file://",
            )
            .replace("{key}", key),
        );
    }
    None
}

fn boolean(value: &str) -> Option<bool> {
    match value.trim().to_ascii_lowercase().as_str() {
        "yes" | "true" | "1" => Some(true),
        "no" | "false" | "0" => Some(false),
        _ => None,
    }
}

fn is_size_directive(key: &str) -> bool {
    matches!(
        key,
        "MaxEmbeddedPE"
            | "MaxHTMLNormalize"
            | "MaxHTMLNoTags"
            | "MaxScriptNormalize"
            | "MaxZipTypeRcg"
            | "MaxScanSize"
            | "MaxFileSize"
            | "StreamMaxLength"
            | "OnAccessMaxFileSize"
    )
}

fn valid_size(value: &str) -> bool {
    let value = value.trim();
    let Some(first) = value.chars().next() else {
        return false;
    };
    first.is_ascii_digit()
}

fn normalize_size_value(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.parse::<u64>().is_ok_and(|size| size > 0) {
        format!("{trimmed}M")
    } else {
        trimmed.to_owned()
    }
}

fn render_directive(key: &str, value: &str) -> String {
    if value.is_empty() {
        key.to_owned()
    } else {
        format!("{key} {value}")
    }
}

fn object(value: Value) -> AppResult<Map<String, Value>> {
    value
        .as_object()
        .cloned()
        .ok_or_else(|| "Configuration arguments must be an object".to_owned())
}

fn optional_object(
    arguments: &Map<String, Value>,
    key: &str,
) -> AppResult<Option<Map<String, Value>>> {
    match arguments.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Object(value)) => Ok(Some(value.clone())),
        Some(_) => Err(format!("{key} must be an object")),
    }
}

fn required_string(arguments: &Map<String, Value>, key: &str) -> AppResult<String> {
    optional_string(arguments, key)?
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| format!("{key} must be a non-empty string"))
}

fn optional_string(arguments: &Map<String, Value>, key: &str) -> AppResult<Option<String>> {
    match arguments.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(_) => Err(format!("{key} must be a string")),
    }
}

fn failure(group: &str, message: &str, path: Option<&Path>) -> Value {
    json!({"group": group, "message": message, "path": path.map(|path| path.to_string_lossy().into_owned())})
}

#[cfg(unix)]
fn permissions_mode(metadata: &fs::Metadata) -> u32 {
    use std::os::unix::fs::PermissionsExt;
    metadata.permissions().mode() & 0o777
}

#[cfg(not(unix))]
fn permissions_mode(_metadata: &fs::Metadata) -> u32 {
    0o600
}
