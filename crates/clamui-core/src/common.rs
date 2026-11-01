use crate::{settings, AppResult};
use chrono::Utc;
use serde::Serialize;
use serde_json::Value;
use std::{
    any::{Any, TypeId},
    collections::HashMap,
    env,
    fs::{self, File, OpenOptions},
    io::Write,
    os::unix::{
        ffi::{OsStrExt, OsStringExt},
        fs::{OpenOptionsExt, PermissionsExt},
    },
    path::{Path, PathBuf},
    process::Command,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};
use uuid::Uuid;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Paths {
    pub home: PathBuf,
    pub config_dir: PathBuf,
    pub data_dir: PathBuf,
}

impl Paths {
    pub fn from_environment() -> AppResult<Self> {
        let home = env::var_os("HOME")
            .filter(|path| !path.is_empty())
            .map(PathBuf::from)
            .ok_or_else(|| "HOME is not set".to_owned())?;
        let config_home = env::var_os("XDG_CONFIG_HOME")
            .filter(|path| !path.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".config"));
        let data_home = env::var_os("XDG_DATA_HOME")
            .filter(|path| !path.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".local/share"));

        Ok(Self {
            home,
            config_dir: config_home.join("clamui"),
            data_dir: data_home.join("clamui"),
        })
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct Event {
    pub event: String,
    pub data: Value,
}

type EventSink = dyn Fn(Event) + Send + Sync + 'static;
type JobRegistry = Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>;
type SharedStateRegistry = Arc<Mutex<HashMap<TypeId, Arc<dyn Any + Send + Sync>>>>;

#[derive(Clone)]
pub struct Context {
    pub paths: Paths,
    emitter: Arc<EventSink>,
    settings_lock: Arc<Mutex<()>>,
    jobs: JobRegistry,
    shared_state: SharedStateRegistry,
    interrupt_latch: Option<Arc<AtomicBool>>,
}

impl Context {
    pub fn new() -> AppResult<Self> {
        Self::with_paths(Paths::from_environment()?)
    }

    pub fn with_paths(paths: Paths) -> AppResult<Self> {
        if paths.home.as_os_str().is_empty()
            || paths.config_dir.as_os_str().is_empty()
            || paths.data_dir.as_os_str().is_empty()
        {
            return Err("ClamUI paths must not be empty".to_owned());
        }
        Ok(Self {
            paths,
            emitter: Arc::new(|_| {}),
            settings_lock: Arc::new(Mutex::new(())),
            jobs: Arc::new(Mutex::new(HashMap::new())),
            shared_state: Arc::new(Mutex::new(HashMap::new())),
            interrupt_latch: None,
        })
    }

    pub fn with_emitter(self, emitter: impl Fn(Event) + Send + Sync + 'static) -> Self {
        Self {
            emitter: Arc::new(emitter),
            ..self
        }
    }

    /// Adds the CLI-owned interrupt latch to a headless context. GUI/native
    /// contexts keep the default `None` and are unaffected by process signals.
    pub fn with_interrupt_latch(self, interrupt_latch: Arc<AtomicBool>) -> Self {
        Self {
            interrupt_latch: Some(interrupt_latch),
            ..self
        }
    }

    pub fn interrupted(&self) -> bool {
        self.interrupt_latch
            .as_ref()
            .is_some_and(|latch| latch.load(Ordering::Acquire))
    }

    pub fn emit(&self, event: &str, data: Value) {
        (self.emitter)(Event {
            event: event.to_owned(),
            data,
        });
    }

    pub fn settings(&self) -> AppResult<Value> {
        let _guard = self
            .settings_lock
            .lock()
            .map_err(|_| "settings lock is poisoned".to_owned())?;
        settings::read(&self.paths)
    }

    pub fn update_settings(&self, patch: Value) -> AppResult<Value> {
        let _guard = self
            .settings_lock
            .lock()
            .map_err(|_| "settings lock is poisoned".to_owned())?;
        settings::update(&self.paths, patch)
    }

    /// Lazily stores one clone-shared, typed state value for this context.
    ///
    /// Domain modules use this for long-lived state such as per-context
    /// rate-limit counters without coupling `common` to a domain type.
    pub fn shared_state<T>(&self, create: impl FnOnce() -> T) -> AppResult<Arc<T>>
    where
        T: Send + Sync + 'static,
    {
        let mut registry = self
            .shared_state
            .lock()
            .map_err(|_| "shared state registry lock is poisoned".to_owned())?;
        let stored = registry
            .entry(TypeId::of::<T>())
            .or_insert_with(|| Arc::new(create()));
        Arc::downcast::<T>(Arc::clone(stored))
            .map_err(|_| "shared state registry type mismatch".to_owned())
    }

    pub fn job(&self, id: &str) -> AppResult<Job> {
        if id.is_empty() {
            return Err("operation id must not be empty".to_owned());
        }
        let mut jobs = self
            .jobs
            .lock()
            .map_err(|_| "operation registry lock is poisoned".to_owned())?;
        if jobs.contains_key(id) {
            return Err(format!("operation '{id}' is already running"));
        }

        // The signal worker stores the latch before taking this registry lock
        // for cancel_all. Reading it while the registration lock is held closes
        // the SIGINT-before-registration race without sharing flags between
        // unrelated jobs.
        let cancelled = Arc::new(AtomicBool::new(self.interrupted()));
        jobs.insert(id.to_owned(), Arc::clone(&cancelled));
        Ok(Job {
            id: id.to_owned(),
            cancelled,
            registry: Arc::clone(&self.jobs),
        })
    }

    pub fn cancel(&self, id: &str) -> bool {
        let Ok(jobs) = self.jobs.lock() else {
            return false;
        };
        let Some(cancelled) = jobs.get(id) else {
            return false;
        };
        cancelled.store(true, Ordering::Release);
        true
    }

    pub fn cancel_all(&self) {
        if let Ok(jobs) = self.jobs.lock() {
            for cancelled in jobs.values() {
                cancelled.store(true, Ordering::Release);
            }
        }
    }
}

pub struct Job {
    pub id: String,
    pub cancelled: Arc<AtomicBool>,
    registry: JobRegistry,
}

impl Drop for Job {
    fn drop(&mut self) {
        if let Ok(mut jobs) = self.registry.lock() {
            jobs.remove(&self.id);
        }
    }
}

pub fn new_operation_id(id: Option<&str>) -> String {
    id.filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| Uuid::new_v4().to_string())
}

pub fn atomic_write(path: &Path, bytes: &[u8], mode: u32) -> AppResult<()> {
    let parent = match path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        Some(parent) => parent,
        None if path.file_name().is_some() => Path::new("."),
        None => return Err(format!("{} has no parent directory", path.display())),
    };
    fs::create_dir_all(parent)
        .map_err(|error| format!("failed to create {}: {error}", parent.display()))?;

    let mut temporary = None;
    for _ in 0..32 {
        let candidate = parent.join(format!(
            ".{}.{}.tmp",
            path.file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("clamui"),
            Uuid::new_v4()
        ));
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(mode)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(&candidate);
        match file {
            Ok(file) => {
                temporary = Some((candidate, file));
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("failed to create temporary settings file: {error}")),
        }
    }

    let Some((temporary_path, mut file)) = temporary else {
        return Err("failed to allocate a temporary file".to_owned());
    };
    let write_result = (|| -> AppResult<()> {
        file.set_permissions(fs::Permissions::from_mode(mode))
            .map_err(|error| format!("failed to restrict temporary file permissions: {error}"))?;
        file.write_all(bytes)
            .map_err(|error| format!("failed to write {}: {error}", temporary_path.display()))?;
        file.sync_all()
            .map_err(|error| format!("failed to sync {}: {error}", temporary_path.display()))?;
        fs::rename(&temporary_path, path)
            .map_err(|error| format!("failed to replace {}: {error}", path.display()))?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| format!("failed to sync {}: {error}", parent.display()))?;
        Ok(())
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&temporary_path);
    }
    write_result
}

pub fn is_flatpak() -> bool {
    Path::new("/.flatpak-info").is_file()
}

pub fn host_command(program: &str, args: &[String]) -> Command {
    build_host_command(program, args, false)
}

pub(crate) fn watched_host_command(program: &str, args: &[String]) -> Command {
    build_host_command(program, args, true)
}

fn build_host_command(program: &str, args: &[String], watch_bus: bool) -> Command {
    let mut command = if is_flatpak() {
        let mut command = Command::new("flatpak-spawn");
        command.arg("--host");
        if watch_bus {
            command.arg("--watch-bus");
        }
        command.arg(program).args(args);
        command
    } else {
        let mut command = Command::new(program);
        command.args(args);
        command
    };
    command.env("LC_ALL", "C");
    for variable in [
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "GI_TYPELIB_PATH",
        "GTK_PATH",
        "GTK_EXE_PREFIX",
        "GTK_DATA_PREFIX",
        "GSETTINGS_SCHEMA_DIR",
        "GDK_PIXBUF_MODULE_FILE",
        "GDK_PIXBUF_MODULEDIR",
    ] {
        command.env_remove(variable);
    }
    for (key, _) in env::vars_os() {
        if key.to_string_lossy().starts_with("APPIMAGE")
            || key.to_string_lossy().starts_with("APPDIR")
        {
            command.env_remove(key);
        }
    }
    command
}

pub fn expand_path(path: &str) -> PathBuf {
    if path == "~" {
        return env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(path));
    }
    if let Some(rest) = path.strip_prefix("~/") {
        return env::var_os("HOME")
            .map(PathBuf::from)
            .map(|home| home.join(rest))
            .unwrap_or_else(|| PathBuf::from(path));
    }
    PathBuf::from(path)
}

/// Converts a local filesystem path to the JSON wire representation used by
/// native/frontend boundaries. UTF-8 paths remain unchanged; non-UTF-8 Unix
/// paths use a byte-preserving percent-encoded local file URI.
pub fn path_to_wire(path: &Path) -> String {
    let bytes = path.as_os_str().as_bytes();
    if let Ok(utf8) = std::str::from_utf8(bytes) {
        return utf8.to_owned();
    }

    let mut wire = if bytes.starts_with(b"/") {
        String::from("file://")
    } else {
        String::from("file:")
    };
    for &byte in bytes {
        if matches!(
            byte,
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'/' | b'.' | b'-' | b'_' | b'~'
        ) {
            wire.push(byte as char);
        } else {
            use std::fmt::Write as _;
            let _ = write!(wire, "%{byte:02X}");
        }
    }
    wire
}

/// Decodes a plain UTF-8 path or the byte-preserving local `file:` wire
/// representation. It never expands `~`, resolves symlinks, or accepts an
/// authority-bearing URI.
pub fn path_from_wire(wire: &str) -> AppResult<PathBuf> {
    let encoded = if let Some(encoded) = wire.strip_prefix("file://") {
        if !encoded.starts_with('/') {
            return Err("file URI authority is not permitted".to_owned());
        }
        encoded
    } else if let Some(encoded) = wire.strip_prefix("file:") {
        encoded
    } else {
        return Ok(PathBuf::from(wire));
    };

    fn hex(value: u8) -> Option<u8> {
        match value {
            b'0'..=b'9' => Some(value - b'0'),
            b'a'..=b'f' => Some(value - b'a' + 10),
            b'A'..=b'F' => Some(value - b'A' + 10),
            _ => None,
        }
    }

    let source = encoded.as_bytes();
    let mut decoded = Vec::with_capacity(source.len());
    let mut index = 0;
    while index < source.len() {
        if source[index] == b'%' {
            if index + 2 >= source.len() {
                return Err("file URI contains an incomplete percent escape".to_owned());
            }
            let high = hex(source[index + 1])
                .ok_or_else(|| "file URI contains an invalid percent escape".to_owned())?;
            let low = hex(source[index + 2])
                .ok_or_else(|| "file URI contains an invalid percent escape".to_owned())?;
            decoded.push((high << 4) | low);
            index += 3;
        } else {
            decoded.push(source[index]);
            index += 1;
        }
    }
    if decoded.contains(&0) {
        return Err("file URI contains a NUL byte".to_owned());
    }
    Ok(PathBuf::from(std::ffi::OsString::from_vec(decoded)))
}

fn strip_escape_sequences(input: &str) -> String {
    let mut output = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();
    while let Some(character) = chars.next() {
        if character == '\u{1b}' {
            if matches!(chars.peek(), Some('[')) {
                chars.next();
                for next in chars.by_ref() {
                    if next.is_ascii_alphabetic() {
                        break;
                    }
                }
            } else {
                chars.next();
            }
            continue;
        }
        output.push(character);
    }
    output
}

fn is_bidi_override(character: char) -> bool {
    matches!(character, '\u{061c}' | '\u{200e}' | '\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
}

pub fn sanitize_line(input: &str) -> String {
    strip_escape_sequences(input)
        .chars()
        .filter_map(|character| {
            let value = character as u32;
            if is_bidi_override(character)
                || (0xD800..=0xDFFF).contains(&value)
                || value == 0x7f
                || (0x80..=0x9f).contains(&value)
            {
                None
            } else if character == '\n'
                || character == '\r'
                || matches!(character, '\u{0085}' | '\u{2028}' | '\u{2029}')
            {
                Some(' ')
            } else if character == '\t' || value >= 0x20 {
                Some(character)
            } else {
                None
            }
        })
        .collect()
}

pub fn sanitize_text(input: &str) -> String {
    strip_escape_sequences(input)
        .chars()
        .filter(|character| {
            let value = *character as u32;
            !is_bidi_override(*character)
                && !(0xD800..=0xDFFF).contains(&value)
                && value != 0x7f
                && !(0x80..=0x9f).contains(&value)
                && (*character == '\n' || *character == '\r' || *character == '\t' || value >= 0x20)
        })
        .collect()
}

pub fn now_iso() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::Ordering;

    #[test]
    fn jobs_are_isolated_and_unregistered_on_drop() {
        let paths = Paths {
            home: PathBuf::from("/tmp"),
            config_dir: PathBuf::from("/tmp/clamui-test"),
            data_dir: PathBuf::from("/tmp/clamui-data"),
        };
        let context = Context::with_paths(paths).expect("context");
        let scan = context.job("scan-a").expect("scan job");
        let update = context.job("update-b").expect("update job");
        assert!(context.cancel("scan-a"));
        assert!(scan.cancelled.load(Ordering::Acquire));
        assert!(!update.cancelled.load(Ordering::Acquire));
        drop(scan);
        assert!(context.job("scan-a").is_ok());
    }

    #[test]
    fn interrupt_latch_cancels_jobs_registered_after_signal() {
        let latch = Arc::new(AtomicBool::new(true));
        let context = Context::with_paths(Paths {
            home: PathBuf::from("/tmp"),
            config_dir: PathBuf::from("/tmp/clamui-interrupt-test"),
            data_dir: PathBuf::from("/tmp/clamui-interrupt-data"),
        })
        .expect("context")
        .with_interrupt_latch(Arc::clone(&latch));

        let job = context.job("scan-after-sigint").expect("job");
        assert!(context.interrupted());
        assert!(latch.load(Ordering::Acquire));
        assert!(job.cancelled.load(Ordering::Acquire));
    }

    #[test]
    fn sanitizers_remove_control_sequences_without_collapsing_text() {
        assert_eq!(
            sanitize_line("safe\n\u{1b}[31mred\u{1b}[0m\u{202e}"),
            "safe red"
        );
        assert_eq!(sanitize_text("safe\n\u{1b}[31mred\u{1b}[0m"), "safe\nred");
    }

    #[test]
    fn non_utf8_paths_round_trip_through_wire_encoding() {
        let path = PathBuf::from(std::ffi::OsString::from_vec(vec![
            b'/', b't', b'm', b'p', b'/', 0xff, b' ', b'%', b'x',
        ]));
        let wire = path_to_wire(&path);
        assert_eq!(wire, "file:///tmp/%FF%20%25x");
        assert_eq!(
            path_from_wire(&wire)
                .expect("decoded path")
                .as_os_str()
                .as_bytes(),
            path.as_os_str().as_bytes()
        );
    }

    #[test]
    fn path_wire_rejects_uri_authorities() {
        assert!(path_from_wire("file://host/tmp/item").is_err());
    }
}
