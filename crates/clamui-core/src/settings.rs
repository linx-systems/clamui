use crate::{
    common::{atomic_write, Paths},
    AppResult,
};
use fs2::FileExt;
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    fs::{self, OpenOptions},
    io::ErrorKind,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::Path,
};

const SETTINGS_FILE: &str = "settings.json";
const SETTINGS_LOCK_FILE: &str = ".settings.lock";
const SECRET_SETTING_KEYS: &[&str] = &["virustotal_api_key", "portmaster_api_token"];

pub fn dispatch(ctx: &crate::common::Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "get" => Ok(frontend_settings(ctx.settings()?)),
        "update" => {
            let mut patch = args
                .as_object()
                .cloned()
                .ok_or_else(|| "settings update must be a JSON object".to_owned())?;
            for key in SECRET_SETTING_KEYS {
                patch.remove(*key);
            }
            Ok(frontend_settings(
                ctx.update_settings(Value::Object(patch))?,
            ))
        }
        _ => Err(format!("unsupported settings action: {action}")),
    }
}

pub(crate) fn read(paths: &Paths) -> AppResult<Value> {
    with_settings_lock(paths, || {
        let (settings, normalized) = read_unlocked(paths)?;
        if normalized {
            write_unlocked(paths, &settings)?;
        }
        Ok(settings)
    })
}

pub(crate) fn update(paths: &Paths, patch: Value) -> AppResult<Value> {
    let patch = patch
        .as_object()
        .ok_or_else(|| "settings update must be a JSON object".to_owned())?;
    with_settings_lock(paths, || {
        let (mut settings, _) = read_unlocked(paths)?;
        let object = settings
            .as_object_mut()
            .ok_or_else(|| "settings storage is not an object".to_owned())?;
        for (key, value) in patch {
            object.insert(key.clone(), value.clone());
        }
        normalize_settings(&mut settings);
        write_unlocked(paths, &settings)?;
        Ok(settings)
    })
}

pub fn frontend_settings(mut settings: Value) -> Value {
    if let Some(object) = settings.as_object_mut() {
        for key in SECRET_SETTING_KEYS {
            object.remove(*key);
        }
    }
    settings
}

pub fn default_settings() -> Value {
    json!({
        "language": "auto",
        "notifications_enabled": true,
        "minimize_to_tray": false,
        "start_minimized": false,
        "close_behavior": null,
        "quarantine_directory": "",
        "scheduled_scans_enabled": false,
        "schedule_frequency": "weekly",
        "schedule_time": "02:00",
        "schedule_targets": [],
        "schedule_skip_on_battery": true,
        "schedule_auto_quarantine": false,
        "schedule_day_of_week": 0,
        "schedule_day_of_month": 1,
        "exclusion_patterns": default_exclusion_patterns(),
        "scan_backend": "auto",
        "daemon_socket_path": "",
        "clamd_conf_path": "",
        "freshclam_conf_path": "",
        "clamd_size_limit_unit_migration_done": false,
        "privileged_helper_prompt_skipped_version": "",
        "virustotal_api_key": null,
        "allow_plaintext_api_key_fallback": false,
        "virustotal_remember_no_key_action": "none",
        "debug_log_level": "WARNING",
        "debug_log_max_size_mb": 5,
        "debug_log_max_files": 3,
        "show_live_progress": true,
        "device_auto_scan_enabled": false,
        "device_auto_scan_types": ["removable", "external"],
        "device_auto_scan_notify": true,
        "device_auto_scan_max_size_gb": 32,
        "device_auto_scan_delay_seconds": 3,
        "device_auto_scan_auto_quarantine": false,
        "device_auto_scan_skip_on_battery": true
    })
}

pub fn default_exclusion_patterns() -> Value {
    json!([
        {"pattern": "node_modules", "type": "directory", "enabled": true},
        {"pattern": ".git", "type": "directory", "enabled": true},
        {"pattern": ".venv", "type": "directory", "enabled": true},
        {"pattern": "build", "type": "directory", "enabled": true},
        {"pattern": "dist", "type": "directory", "enabled": true},
        {"pattern": "__pycache__", "type": "directory", "enabled": true}
    ])
}

pub fn normalize_exclusion_patterns(exclusions: Option<&Value>) -> Value {
    let Some(exclusions) = exclusions.and_then(Value::as_array) else {
        return default_exclusion_patterns();
    };
    let presets = default_exclusion_patterns()
        .as_array()
        .expect("preset exclusions are an array")
        .clone();
    let preset_names: HashSet<&str> = presets
        .iter()
        .filter_map(|value| value.get("pattern").and_then(Value::as_str))
        .collect();
    let mut normalized = Vec::new();
    let mut seen = HashSet::new();

    for item in exclusions {
        let (pattern, kind, enabled) = match item {
            Value::String(pattern) if !pattern.is_empty() => {
                let kind = if Path::new(pattern).is_absolute() {
                    "file"
                } else {
                    "pattern"
                };
                (pattern.as_str(), kind, true)
            }
            Value::Object(object) => {
                let Some(pattern) = object
                    .get("pattern")
                    .and_then(Value::as_str)
                    .filter(|pattern| !pattern.is_empty())
                else {
                    continue;
                };
                let kind = object
                    .get("type")
                    .and_then(Value::as_str)
                    .filter(|kind| matches!(*kind, "directory" | "file" | "pattern"))
                    .unwrap_or_else(|| {
                        if Path::new(pattern).is_absolute() {
                            "file"
                        } else {
                            "pattern"
                        }
                    });
                let enabled = object
                    .get("enabled")
                    .and_then(Value::as_bool)
                    .unwrap_or(true);
                (pattern, kind, enabled)
            }
            _ => continue,
        };
        if !seen.insert(pattern.to_owned()) {
            continue;
        }
        if preset_names.contains(pattern) {
            normalized.push(json!({"pattern": pattern, "type": "directory", "enabled": enabled}));
        } else {
            normalized.push(json!({"pattern": pattern, "type": kind, "enabled": enabled}));
        }
    }

    for preset in presets {
        let pattern = preset
            .get("pattern")
            .and_then(Value::as_str)
            .expect("preset pattern");
        if !seen.contains(pattern) {
            normalized.push(preset);
        }
    }
    Value::Array(normalized)
}

fn read_unlocked(paths: &Paths) -> AppResult<(Value, bool)> {
    let settings_path = paths.config_dir.join(SETTINGS_FILE);
    let loaded = match fs::read(&settings_path) {
        Ok(contents) => match serde_json::from_slice::<Value>(&contents) {
            Ok(value) if value.is_object() => value,
            Ok(_) | Err(_) => {
                backup_corrupted_file(&settings_path)?;
                return Ok((default_settings(), false));
            }
        },
        Err(error) if error.kind() == ErrorKind::NotFound => {
            return Ok((default_settings(), false))
        }
        Err(error) => {
            return Err(format!(
                "failed to read {}: {error}",
                settings_path.display()
            ))
        }
    };
    let mut merged = default_settings();
    merged
        .as_object_mut()
        .expect("defaults are an object")
        .extend(loaded.as_object().expect("validated object").clone());
    let before = merged.get("exclusion_patterns").cloned();
    normalize_settings(&mut merged);
    let normalized = before.as_ref() != merged.get("exclusion_patterns");
    Ok((merged, normalized))
}

fn normalize_settings(settings: &mut Value) {
    let Some(object) = settings.as_object_mut() else {
        return;
    };
    let exclusions = normalize_exclusion_patterns(object.get("exclusion_patterns"));
    object.insert("exclusion_patterns".to_owned(), exclusions);
}

fn write_unlocked(paths: &Paths, settings: &Value) -> AppResult<()> {
    let bytes = serde_json::to_vec_pretty(settings)
        .map_err(|error| format!("failed to encode settings: {error}"))?;
    atomic_write(&paths.config_dir.join(SETTINGS_FILE), &bytes, 0o600)
}

fn with_settings_lock<T>(paths: &Paths, operation: impl FnOnce() -> AppResult<T>) -> AppResult<T> {
    fs::create_dir_all(&paths.config_dir)
        .map_err(|error| format!("failed to create {}: {error}", paths.config_dir.display()))?;
    let lock_path = paths.config_dir.join(SETTINGS_LOCK_FILE);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(&lock_path)
        .map_err(|error| format!("failed to open settings lock: {error}"))?;
    file.set_permissions(fs::Permissions::from_mode(0o600))
        .map_err(|error| format!("failed to restrict settings lock: {error}"))?;
    file.lock_exclusive()
        .map_err(|error| format!("failed to lock settings: {error}"))?;
    let result = operation();
    let unlock_result =
        fs2::FileExt::unlock(&file).map_err(|error| format!("failed to unlock settings: {error}"));
    match (result, unlock_result) {
        (Ok(value), Ok(())) => Ok(value),
        (Err(error), _) => Err(error),
        (_, Err(error)) => Err(error),
    }
}

fn backup_corrupted_file(path: &Path) -> AppResult<()> {
    let backup = Path::new(&format!("{}.corrupted", path.display())).to_path_buf();
    if backup.exists() {
        return Ok(());
    }
    fs::rename(path, &backup).map_err(|error| {
        format!(
            "failed to preserve corrupt settings {} as {}: {error}",
            path.display(),
            backup.display()
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::common::{Context, Paths};
    use std::{fs, sync::Arc, thread};
    use tempfile::TempDir;

    fn paths(temp: &TempDir) -> Paths {
        Paths {
            home: temp.path().join("home"),
            config_dir: temp.path().join("config/clamui"),
            data_dir: temp.path().join("data/clamui"),
        }
    }

    #[test]
    fn normalizes_legacy_exclusions_without_losing_unknown_settings() {
        let temp = TempDir::new().expect("temporary directory");
        let context = Context::with_paths(paths(&temp)).expect("context");
        context.update_settings(json!({
            "exclusion_patterns": ["/tmp/cache", {"pattern":"node_modules", "enabled":false}, {"pattern":"node_modules"}, {"pattern":"ignored", "type":"invalid"}],
            "future_setting": {"retained": true}
        })).expect("settings saved");
        let settings = context.settings().expect("settings read");
        assert_eq!(settings["future_setting"]["retained"], true);
        assert_eq!(
            settings["exclusion_patterns"][0],
            json!({"pattern":"/tmp/cache", "type":"file", "enabled":true})
        );
        assert_eq!(
            settings["exclusion_patterns"][1],
            json!({"pattern":"node_modules", "type":"directory", "enabled":false})
        );
        assert_eq!(
            settings["exclusion_patterns"][2],
            json!({"pattern":"ignored", "type":"pattern", "enabled":true})
        );
    }

    #[test]
    fn preserves_a_single_corrupt_backup_and_recovers_defaults() {
        let temp = TempDir::new().expect("temporary directory");
        let paths = paths(&temp);
        fs::create_dir_all(&paths.config_dir).expect("config directory");
        fs::write(paths.config_dir.join(SETTINGS_FILE), b"not json").expect("corrupt settings");
        let context = Context::with_paths(paths.clone()).expect("context");
        assert_eq!(context.settings().expect("recovered")["language"], "auto");
        assert_eq!(
            fs::read(paths.config_dir.join("settings.json.corrupted")).expect("backup"),
            b"not json"
        );
    }

    #[test]
    fn concurrent_context_updates_preserve_each_patch() {
        let temp = TempDir::new().expect("temporary directory");
        let paths = Arc::new(paths(&temp));
        let mut threads = Vec::new();
        for index in 0..12 {
            let paths = Arc::clone(&paths);
            let mut patch = serde_json::Map::new();
            patch.insert(format!("writer_{index}"), Value::from(index));
            threads.push(thread::spawn(move || {
                Context::with_paths((*paths).clone())
                    .expect("context")
                    .update_settings(Value::Object(patch))
                    .expect("update");
            }));
        }
        for thread in threads {
            thread.join().expect("writer completed");
        }
        let settings = Context::with_paths((*paths).clone())
            .expect("context")
            .settings()
            .expect("read");
        for index in 0..12 {
            assert_eq!(settings[format!("writer_{index}")], index);
        }
    }
}
