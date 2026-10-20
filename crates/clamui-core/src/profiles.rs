use crate::common::{atomic_write, expand_path, host_command, now_iso, Context};
use crate::AppResult;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use uuid::Uuid;

const STORAGE_VERSION: u64 = 1;
const EXPORT_VERSION: u64 = 1;
const XDG_MIGRATION_VERSION: u64 = 1;
const MAX_PROFILE_NAME_LENGTH: usize = 50;

static PROFILES_LOCK: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Profile {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub targets: Vec<String>,
    #[serde(default)]
    pub exclusions: Map<String, Value>,
    pub created_at: String,
    pub updated_at: String,
    #[serde(default)]
    pub is_default: bool,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub options: Map<String, Value>,
    #[serde(flatten, default)]
    pub extra: Map<String, Value>,
}

impl Profile {
    fn value(&self) -> AppResult<Value> {
        Ok(json!({
            "id": self.id,
            "name": self.name,
            "targets": self.targets,
            "exclusions": self.exclusions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_default": self.is_default,
            "description": self.description,
            "options": self.options,
        }))
    }

    fn stored_value(&self) -> AppResult<Value> {
        serde_json::to_value(self).map_err(|error| format!("Could not serialize profile: {error}"))
    }
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    let _guard = PROFILES_LOCK
        .lock()
        .map_err(|_| "Profile storage lock is unavailable".to_string())?;
    let mut manager = ProfileManager::load(ctx)?;

    match action {
        "list" => Ok(json!({"profiles": values(&manager.profiles)?})),
        "create" => {
            let profile = manager.create(require_object(args)?)?;
            Ok(profile.value()?)
        }
        "update" => {
            let arguments = require_object(args)?;
            let id = required_string(&arguments, "id")?;
            let profile = manager.update(&id, &arguments)?;
            Ok(profile.value()?)
        }
        "delete" => {
            let arguments = require_object(args)?;
            let id = required_string(&arguments, "id")?;
            manager.delete(&id)?;
            Ok(json!({"id": id, "deleted": true}))
        }
        "duplicate" => {
            let arguments = require_object(args)?;
            let id = required_string(&arguments, "id")?;
            let profile = manager.duplicate(&id, arguments.get("name"))?;
            Ok(profile.value()?)
        }
        "import" => {
            let arguments = require_object(args)?;
            let path = required_string(&arguments, "path")?;
            let profile = manager.import(&path)?;
            Ok(profile.value()?)
        }
        "restore_defaults" => {
            let restored = manager.restore_defaults()?;
            Ok(json!({"restored": restored, "profiles": values(&manager.profiles)?}))
        }
        "export" => {
            let arguments = require_object(args)?;
            let id = required_string(&arguments, "id")?;
            manager.export(&id, arguments.get("path"))
        }
        _ => Err(format!("Unknown profiles action: {action}")),
    }
}

struct ProfileManager<'a> {
    ctx: &'a Context,
    path: PathBuf,
    profiles: Vec<Profile>,
}

impl<'a> ProfileManager<'a> {
    fn load(ctx: &'a Context) -> AppResult<Self> {
        let path = ctx.paths.config_dir.join("profiles.json");
        let (profiles, normalized_descriptions) = load_profiles(&path)?;
        let mut manager = Self {
            ctx,
            profiles,
            path,
        };
        let defaults_added = manager.ensure_defaults()?;
        if normalized_descriptions || defaults_added {
            manager.save()?;
        }
        manager.migrate_quick_scan_target()?;
        Ok(manager)
    }

    fn save(&self) -> AppResult<()> {
        let stored: AppResult<Vec<_>> = self.profiles.iter().map(Profile::stored_value).collect();
        let data = json!({"version": STORAGE_VERSION, "profiles": stored?});
        let bytes = serde_json::to_vec_pretty(&data)
            .map_err(|error| format!("Could not serialize profile storage: {error}"))?;
        atomic_write(&self.path, &bytes, 0o600)
    }

    fn ensure_defaults(&mut self) -> AppResult<bool> {
        let mut changed = false;
        for definition in default_profiles() {
            let exists = self
                .profiles
                .iter()
                .any(|profile| profile.is_default && profile.name == definition.name);
            if !exists {
                let timestamp = now_iso();
                self.profiles.push(Profile {
                    id: Uuid::new_v4().to_string(),
                    name: definition.name.to_string(),
                    targets: definition.targets(),
                    exclusions: definition.exclusions(),
                    created_at: timestamp.clone(),
                    updated_at: timestamp,
                    is_default: true,
                    description: definition.description.to_string(),
                    options: Map::new(),
                    extra: Map::new(),
                });
                changed = true;
            }
        }
        Ok(changed)
    }

    fn migrate_quick_scan_target(&mut self) -> AppResult<()> {
        let settings = self.ctx.settings()?;
        let mut migrations = settings
            .get("_migrations")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        if migrations
            .get("xdg_migration_version")
            .and_then(Value::as_u64)
            .unwrap_or_default()
            >= XDG_MIGRATION_VERSION
        {
            return Ok(());
        }

        let downloads = xdg_downloads_dir();
        let mut changed = false;
        for profile in &mut self.profiles {
            if profile.is_default
                && profile.name == "Quick Scan"
                && profile.targets == ["~/Downloads"]
                && downloads != "~/Downloads"
            {
                profile.targets = vec![downloads.clone()];
                profile.updated_at = now_iso();
                changed = true;
            }
        }
        if changed {
            self.save()?;
        }
        migrations.insert(
            "xdg_migration_version".to_string(),
            Value::Number(XDG_MIGRATION_VERSION.into()),
        );
        self.ctx
            .update_settings(json!({"_migrations": migrations}))?;
        Ok(())
    }

    fn create(&mut self, arguments: Map<String, Value>) -> AppResult<Profile> {
        let name = normalized_name(required_string(&arguments, "name")?);
        let targets = optional_targets(&arguments, "targets")?.unwrap_or_default();
        let exclusions = optional_object(&arguments, "exclusions")?.unwrap_or_default();
        let description = optional_string(&arguments, "description")?.unwrap_or_default();
        let options = optional_object(&arguments, "options")?.unwrap_or_default();
        validate_profile(self.ctx, &self.profiles, &name, &targets, &exclusions, None)?;

        let timestamp = now_iso();
        let profile = Profile {
            id: Uuid::new_v4().to_string(),
            name,
            targets,
            exclusions,
            created_at: timestamp.clone(),
            updated_at: timestamp,
            is_default: false,
            description,
            options,
            extra: extra_fields(&arguments),
        };
        self.profiles.push(profile.clone());
        self.save()?;
        Ok(profile)
    }

    fn update(&mut self, id: &str, arguments: &Map<String, Value>) -> AppResult<Profile> {
        let position = self
            .profiles
            .iter()
            .position(|profile| profile.id == id)
            .ok_or_else(|| profile_not_found(self.ctx, id))?;
        let existing = self.profiles[position].clone();
        let name = match arguments.get("name") {
            Some(Value::String(name)) => normalized_name(name.clone()),
            Some(_) => return Err(tr(self.ctx, "Profile name must be a string")),
            None => existing.name.clone(),
        };
        if existing.is_default && name != existing.name {
            return Err(tr(self.ctx, "Cannot rename a default profile"));
        }
        if let Some(value) = arguments.get("is_default") {
            if value.as_bool() != Some(existing.is_default) {
                return Err(tr(self.ctx, "Cannot change whether a profile is default"));
            }
        }
        let targets =
            optional_targets(arguments, "targets")?.unwrap_or_else(|| existing.targets.clone());
        let exclusions = optional_object(arguments, "exclusions")?
            .unwrap_or_else(|| existing.exclusions.clone());
        let description = optional_string(arguments, "description")?
            .unwrap_or_else(|| existing.description.clone());
        let options =
            optional_object(arguments, "options")?.unwrap_or_else(|| existing.options.clone());
        validate_profile(
            self.ctx,
            &self.profiles,
            &name,
            &targets,
            &exclusions,
            Some(id),
        )?;

        let mut extra = existing.extra;
        for (key, value) in extra_fields(arguments) {
            extra.insert(key, value);
        }
        let profile = Profile {
            id: existing.id,
            name,
            targets,
            exclusions,
            created_at: existing.created_at,
            updated_at: now_iso(),
            is_default: existing.is_default,
            description,
            options,
            extra,
        };
        self.profiles[position] = profile.clone();
        self.save()?;
        Ok(profile)
    }

    fn delete(&mut self, id: &str) -> AppResult<()> {
        let position = self
            .profiles
            .iter()
            .position(|profile| profile.id == id)
            .ok_or_else(|| profile_not_found(self.ctx, id))?;
        if self.profiles[position].is_default {
            return Err(tr(self.ctx, "Cannot delete default profile"));
        }
        self.profiles.remove(position);
        self.save()
    }

    fn duplicate(&mut self, id: &str, requested_name: Option<&Value>) -> AppResult<Profile> {
        let source = self
            .profiles
            .iter()
            .find(|profile| profile.id == id)
            .cloned()
            .ok_or_else(|| profile_not_found(self.ctx, id))?;
        let proposed = match requested_name {
            Some(Value::String(name)) => normalized_name(name.clone()),
            Some(_) => return Err(tr(self.ctx, "Profile name must be a string")),
            None => source.name.clone(),
        };
        let name = unique_name(self.ctx, &self.profiles, &proposed)?;
        let timestamp = now_iso();
        let profile = Profile {
            id: Uuid::new_v4().to_string(),
            name,
            targets: source.targets,
            exclusions: source.exclusions,
            created_at: timestamp.clone(),
            updated_at: timestamp,
            is_default: false,
            description: source.description,
            options: source.options,
            extra: source.extra,
        };
        self.profiles.push(profile.clone());
        self.save()?;
        Ok(profile)
    }

    fn import(&mut self, path: &str) -> AppResult<Profile> {
        let path = PathBuf::from(path);
        let bytes = fs::read(&path).map_err(|error| {
            trf(
                self.ctx,
                // Translators: Preserve `{path}` exactly as a user-provided file path and `{error}` as the filesystem diagnostic.
                "Could not read import file '{path}': {error}",
                &[
                    ("path", &path.display().to_string()),
                    ("error", &error.to_string()),
                ],
            )
        })?;
        let value: Value = serde_json::from_slice(&bytes)
            .map_err(|error| format!("Invalid JSON format: {error}"))?;
        let profile_value = value.get("profile").cloned().unwrap_or(value);
        let source = require_object(profile_value)
            .map_err(|error| format!("Invalid export format: {error}"))?;
        let requested_name = normalized_name(required_string(&source, "name")?);
        let targets = optional_targets(&source, "targets")?.unwrap_or_default();
        let exclusions = optional_object(&source, "exclusions")?.unwrap_or_default();
        let description = source
            .get("description")
            .map(legacy_description)
            .unwrap_or_default();
        let options = optional_object(&source, "options")?.unwrap_or_default();
        let name = unique_name(self.ctx, &self.profiles, &requested_name)?;
        validate_profile(self.ctx, &self.profiles, &name, &targets, &exclusions, None)?;
        let timestamp = now_iso();
        let profile = Profile {
            id: Uuid::new_v4().to_string(),
            name,
            targets,
            exclusions,
            created_at: timestamp.clone(),
            updated_at: timestamp,
            is_default: false,
            description,
            options,
            extra: extra_fields(&source),
        };
        self.profiles.push(profile.clone());
        self.save()?;
        Ok(profile)
    }

    fn export(&self, id: &str, path: Option<&Value>) -> AppResult<Value> {
        let profile = self
            .profiles
            .iter()
            .find(|profile| profile.id == id)
            .ok_or_else(|| profile_not_found(self.ctx, id))?;
        let content = serde_json::to_string_pretty(&json!({
            "export_version": EXPORT_VERSION,
            "profile": profile.value()?,
        }))
        .map_err(|error| {
            trf(
                self.ctx,
                "Could not serialize profile export: {error}",
                &[("error", &error.to_string())],
            )
        })?;
        match path {
            None | Some(Value::Null) => Ok(json!({"id": id, "content": content})),
            Some(Value::String(path)) if !path.trim().is_empty() => {
                let path = PathBuf::from(path);
                atomic_write(&path, content.as_bytes(), 0o600)?;
                Ok(json!({"id": id, "path": path}))
            }
            Some(_) => Err(tr(self.ctx, "Export path must be a non-empty string")),
        }
    }

    fn restore_defaults(&mut self) -> AppResult<usize> {
        let restored = self
            .profiles
            .iter()
            .filter(|profile| profile.is_default)
            .count();
        self.profiles.retain(|profile| !profile.is_default);
        self.ensure_defaults()?;
        self.save()?;
        Ok(restored)
    }
}

fn values(profiles: &[Profile]) -> AppResult<Vec<Value>> {
    let mut ordered: Vec<_> = profiles.iter().collect();
    ordered.sort_by_key(|profile| profile.name.to_lowercase());
    ordered.into_iter().map(Profile::value).collect()
}

fn load_profiles(path: &Path) -> AppResult<(Vec<Profile>, bool)> {
    if !path.exists() {
        return Ok((Vec::new(), false));
    }
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) => {
            return Err(format!(
                "Could not read profile storage '{}': {error}",
                path.display()
            ))
        }
    };
    let value: Value = match serde_json::from_slice(&bytes) {
        Ok(value) => value,
        Err(_) => {
            backup_corrupt_file(path);
            return Ok((Vec::new(), false));
        }
    };
    let entries = match value {
        Value::Array(entries) => entries,
        Value::Object(mut object) => match object.remove("profiles") {
            Some(Value::Array(entries)) => entries,
            _ => return Ok((Vec::new(), false)),
        },
        _ => return Ok((Vec::new(), false)),
    };

    let mut normalized_descriptions = false;
    let profiles = entries
        .into_iter()
        .filter_map(|mut entry| {
            if let Some(profile) = entry.as_object_mut() {
                let description = profile
                    .get("description")
                    .filter(|value| !value.is_string())
                    .map(legacy_description);
                if let Some(description) = description {
                    // Legacy storage accepted arbitrary JSON here. Normalize it
                    // rather than discarding an otherwise valid user profile.
                    profile.insert("description".to_string(), Value::String(description));
                    normalized_descriptions = true;
                }
            }
            serde_json::from_value::<Profile>(entry).ok()
        })
        .collect();
    Ok((profiles, normalized_descriptions))
}

fn tr(ctx: &Context, message: &str) -> String {
    crate::i18n::translate(ctx, message)
}

fn trf(ctx: &Context, message: &str, replacements: &[(&str, &str)]) -> String {
    let mut translated = crate::i18n::translate(ctx, message);
    for (name, value) in replacements {
        translated = translated.replace(&format!("{{{name}}}"), value);
    }
    translated
}

fn profile_not_found(ctx: &Context, id: &str) -> String {
    trf(
        ctx,
        // Translators: Preserve `{id}` exactly; it is the profile's technical identifier.
        "Profile with ID '{id}' not found",
        &[("id", id)],
    )
}

fn backup_corrupt_file(path: &Path) {
    let backup = PathBuf::from(format!("{}.corrupted", path.display()));
    if !backup.exists() {
        let _ = fs::rename(path, backup);
    }
}

fn required_string(arguments: &Map<String, Value>, key: &str) -> AppResult<String> {
    arguments
        .get(key)
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
        .ok_or_else(|| format!("Missing or invalid '{key}'"))
}

fn optional_string(arguments: &Map<String, Value>, key: &str) -> AppResult<Option<String>> {
    match arguments.get(key) {
        None => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(_) => Err(format!("'{key}' must be a string")),
    }
}

fn optional_targets(arguments: &Map<String, Value>, key: &str) -> AppResult<Option<Vec<String>>> {
    match arguments.get(key) {
        None => Ok(None),
        Some(Value::Array(values)) => values
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(ToOwned::to_owned)
                    .ok_or_else(|| format!("'{key}' must contain only strings"))
            })
            .collect::<AppResult<Vec<_>>>()
            .map(Some),
        Some(_) => Err(format!("'{key}' must be an array")),
    }
}

fn optional_object(
    arguments: &Map<String, Value>,
    key: &str,
) -> AppResult<Option<Map<String, Value>>> {
    match arguments.get(key) {
        None => Ok(None),
        Some(Value::Object(value)) => Ok(Some(value.clone())),
        Some(_) => Err(format!("'{key}' must be an object")),
    }
}

fn require_object(value: Value) -> AppResult<Map<String, Value>> {
    value
        .as_object()
        .cloned()
        .ok_or_else(|| "Profile arguments must be an object".to_string())
}

fn normalized_name(name: String) -> String {
    name.trim().to_string()
}

fn validate_profile(
    ctx: &Context,
    profiles: &[Profile],
    name: &str,
    targets: &[String],
    exclusions: &Map<String, Value>,
    excluded_id: Option<&str>,
) -> AppResult<()> {
    if name.is_empty() {
        return Err(tr(ctx, "Profile name cannot be empty"));
    }
    if name.chars().count() > MAX_PROFILE_NAME_LENGTH {
        return Err(trf(
            ctx,
            "Profile name cannot exceed {max} characters",
            &[("max", &MAX_PROFILE_NAME_LENGTH.to_string())],
        ));
    }
    if profiles
        .iter()
        .any(|profile| profile.name == name && Some(profile.id.as_str()) != excluded_id)
    {
        return Err(trf(
            ctx,
            // Translators: Preserve `{name}` exactly; it is a user-provided profile name.
            "Profile name '{name}' already exists",
            &[("name", name)],
        ));
    }
    for target in targets {
        validate_path(ctx, target, "target")?;
    }
    if let Some(paths) = exclusions.get("paths") {
        let paths = paths.as_array().ok_or_else(|| {
            tr(
                ctx,
                // Translators: Keep `paths` unchanged; it is the configuration key.
                "Exclusions 'paths' must be a list",
            )
        })?;
        for path in paths {
            let path = path
                .as_str()
                .ok_or_else(|| tr(ctx, "Exclusion path must be a string"))?;
            validate_path(ctx, path, "exclusion path")?;
        }
    }
    if let Some(patterns) = exclusions.get("patterns") {
        let patterns = patterns.as_array().ok_or_else(|| {
            tr(
                ctx,
                // Translators: Keep `patterns` unchanged; it is the configuration key.
                "Exclusions 'patterns' must be a list",
            )
        })?;
        if patterns.iter().any(|pattern| {
            pattern
                .as_str()
                .is_none_or(|pattern| pattern.trim().is_empty())
        }) {
            return Err(tr(ctx, "Exclusion pattern cannot be empty"));
        }
    }
    Ok(())
}

fn validate_path(ctx: &Context, path: &str, kind: &str) -> AppResult<()> {
    let path = path.trim();
    if path.is_empty() {
        return Err(trf(ctx, "{kind} cannot be empty", &[("kind", kind)]));
    }
    if path.contains('\0') {
        return Err(trf(
            ctx,
            "Invalid {kind}: contains invalid characters",
            &[("kind", kind)],
        ));
    }
    let expanded = expand_path(path);
    let rendered = expanded.to_string_lossy();
    if rendered.get(1..).is_some_and(|rest| rest.contains("//")) || rendered.contains("\\\\") {
        return Err(trf(
            ctx,
            "Invalid {kind} path format: {path}",
            &[("kind", kind), ("path", path)],
        ));
    }
    Ok(())
}

fn unique_name(ctx: &Context, profiles: &[Profile], requested: &str) -> AppResult<String> {
    if !profiles.iter().any(|profile| profile.name == requested) {
        return Ok(requested.to_string());
    }
    for number in 2..=1000 {
        let suffix = format!(" ({number})");
        let base_length = MAX_PROFILE_NAME_LENGTH.saturating_sub(suffix.chars().count());
        let base = requested.chars().take(base_length).collect::<String>();
        let candidate = format!("{base}{suffix}");
        if !profiles.iter().any(|profile| profile.name == candidate) {
            return Ok(candidate);
        }
    }
    Err(trf(
        ctx,
        // Translators: Preserve `{name}` exactly; it is a user-provided profile name.
        "Could not generate unique name for '{name}'",
        &[("name", requested)],
    ))
}

fn extra_fields(arguments: &Map<String, Value>) -> Map<String, Value> {
    const KNOWN: [&str; 8] = [
        "id",
        "name",
        "targets",
        "exclusions",
        "created_at",
        "updated_at",
        "is_default",
        "description",
    ];
    arguments
        .iter()
        .filter(|(key, _)| !KNOWN.contains(&key.as_str()) && key.as_str() != "options")
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect()
}

fn legacy_description(value: &Value) -> String {
    if let Value::String(description) = value {
        return description.clone();
    }

    let mut description = String::new();
    write_legacy_value(value, &mut description);
    description
}

fn write_legacy_value(value: &Value, output: &mut String) {
    match value {
        Value::Null => output.push_str("None"),
        Value::Bool(value) => output.push_str(if *value { "True" } else { "False" }),
        Value::Number(value) => write_legacy_number(value, output),
        Value::String(value) => write_legacy_string(value, output),
        Value::Array(values) => {
            output.push('[');
            for (index, value) in values.iter().enumerate() {
                if index != 0 {
                    output.push_str(", ");
                }
                write_legacy_value(value, output);
            }
            output.push(']');
        }
        Value::Object(values) => {
            output.push('{');
            for (index, (key, value)) in values.iter().enumerate() {
                if index != 0 {
                    output.push_str(", ");
                }
                write_legacy_string(key, output);
                output.push_str(": ");
                write_legacy_value(value, output);
            }
            output.push('}');
        }
    }
}

fn write_legacy_number(value: &serde_json::Number, output: &mut String) {
    let rendered = match (value.as_i64(), value.as_u64()) {
        (Some(value), _) => value.to_string(),
        (_, Some(value)) => value.to_string(),
        _ => format!("{:?}", value.as_f64().expect("JSON numbers are finite")),
    };
    let Some((mantissa, exponent)) = rendered.split_once('e') else {
        output.push_str(&rendered);
        return;
    };
    let exponent = exponent
        .parse::<i32>()
        .expect("Rust float formatting uses a numeric exponent");
    output.push_str(mantissa);
    output.push('e');
    output.push_str(&format!("{exponent:+03}"));
}

fn write_legacy_string(value: &str, output: &mut String) {
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    output.push(quote);
    for character in value.chars() {
        match character {
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            '\x08' => output.push_str("\\x08"),
            '\x0c' => output.push_str("\\x0c"),
            character if character == quote => {
                output.push('\\');
                output.push(character);
            }
            character if character.is_control() => {
                output.push_str(&format!("\\x{:02x}", character as u32));
            }
            character => output.push(character),
        }
    }
    output.push(quote);
}

struct DefaultProfile {
    name: &'static str,
    description: &'static str,
    target: &'static str,
    exclusions: &'static [&'static str],
}

impl DefaultProfile {
    fn targets(&self) -> Vec<String> {
        if self.name == "Quick Scan" {
            vec![xdg_downloads_dir()]
        } else {
            vec![self.target.to_string()]
        }
    }

    fn exclusions(&self) -> Map<String, Value> {
        if self.exclusions.is_empty() {
            Map::new()
        } else {
            let mut exclusions = Map::new();
            exclusions.insert(
                "paths".to_string(),
                Value::Array(
                    self.exclusions
                        .iter()
                        .map(|path| Value::String((*path).to_string()))
                        .collect(),
                ),
            );
            exclusions
        }
    }
}

fn default_profiles() -> [DefaultProfile; 3] {
    [
        DefaultProfile {
            name: "Quick Scan",
            description: "Fast scan of the Downloads folder for quick threat detection",
            target: "~/Downloads",
            exclusions: &[],
        },
        DefaultProfile {
            name: "Full Scan",
            description: "Comprehensive system-wide scan of all accessible directories",
            target: "/",
            exclusions: &[
                "/proc",
                "/sys",
                "/dev",
                "/run",
                "/tmp",
                "/var/cache",
                "/var/tmp",
            ],
        },
        DefaultProfile {
            name: "Home Folder",
            description: "Scan of the user's home directory and personal files",
            target: "~",
            exclusions: &["~/.cache", "~/.local/share/Trash"],
        },
    ]
}

fn xdg_downloads_dir() -> String {
    let args = vec!["DOWNLOAD".to_string()];
    let output = host_command("xdg-user-dir", &args).output();
    match output {
        Ok(output) if output.status.success() => {
            let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if value.is_empty() || value.contains('\0') {
                "~/Downloads".to_string()
            } else {
                value
            }
        }
        _ => "~/Downloads".to_string(),
    }
}
