//! Privileged ClamAV configuration boundary.
//!
//! This module owns both sides of the versioned pkexec protocol.  The caller
//! only ever invokes the canonical helper path; the helper independently
//! authenticates every staged descriptor before it replaces a destination.

use crate::{AppResult, Context};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::os::unix::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Child, ChildStderr, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

mod cli_install;

pub(crate) fn install_cli_helper(ctx: &Context, prefix: &Path) -> AppResult<String> {
    cli_install::install_cli_helper(ctx, prefix)
}

pub const PROTOCOL_VERSION: u8 = 4;
pub const MAX_CONFIG_READ_BYTES: usize = 1024 * 1024;
pub const HELPER_PATH: &str = "/usr/bin/clamui-apply-preferences";
pub const POLICY_PATH: &str = "/usr/share/polkit-1/actions/io.github.linx_systems.ClamUI.policy";
pub const POLICY_ACTION: &str = "io.github.linx_systems.clamui.apply-preferences";
pub const HELPER_PACKAGE: &str = "clamui-privileged-helper";

const ALLOWED_DEST_DIRS: [&str; 3] = ["/etc/clamav", "/etc/clamd.d", "/etc/clamav-unofficial-sigs"];
const ALLOWED_DEST_FILE: &str = "/etc/freshclam.conf";
const LEGACY_HELPER_LIB_DIR: &str = "/usr/lib/clamui";
const LEGACY_HELPER_MODULES: [&str; 2] = [
    "/usr/lib/clamui/clamui_apply_preferences.py",
    "/usr/lib/clamui/clamui_privileged_paths.py",
];
const PINNED_SIGNING_KEY: &[u8] = include_bytes!("../../../signing-key.asc");
const PINNED_SIGNING_FINGERPRINT: &str = "037273A518BE90BA6EA27B3CDEF2A3E473DE1E26";
const MAX_HELPER_METADATA_BYTES: usize = 256 * 1024;
const MAX_HELPER_PACKAGE_BYTES: u64 = 64 * 1024 * 1024;
const O_NOFOLLOW: i32 = 0o400000;
const O_DIRECTORY: i32 = 0o200000;
const O_NONBLOCK: i32 = 0o4000;
static UNIQUE_COUNTER: AtomicU64 = AtomicU64::new(0);
// A first-time Flatpak installation has no host helper yet. This fixed,
// argument-only POSIX shell transaction runs under pkexec using trusted host
// tools. It never evaluates user data and copies through GNU dd with
// O_NOFOLLOW before apt receives a root-owned package path.
const FIRST_INSTALL_SCRIPT: &str = r#"set -efu
src=$1 size=$2 digest=$3 version=$4 arch=$5
case "$size" in ''|*[!0-9]*) exit 2;; esac
case "$digest" in *[!0123456789abcdef]*) exit 2;; esac
[ "${#digest}" -eq 64 ] || exit 2
case "$version" in ''|*[!0-9A-Za-z.+:~_-]*) exit 2;; esac
case "$arch" in ''|*[!0-9A-Za-z-]*) exit 2;; esac
uid=${PKEXEC_UID-}
case "$uid" in ''|0|*[!0-9]*) exit 2;; esac
[ "$size" -gt 0 ] && [ "$size" -le 67108864 ] || exit 2
[ -f "$src" ] && [ ! -L "$src" ] || exit 3
[ "$(/usr/bin/stat -c %u -- "$src")" = "$uid" ] || exit 3
mode=$(/usr/bin/stat -c %a -- "$src")
case "$mode" in ???) writable=${mode#?};; ????) writable=${mode#??};; *) exit 3;; esac
case "$writable" in *[2367]*) exit 3;; esac
[ "$(/usr/bin/stat -c %s -- "$src")" = "$size" ] || exit 3
stage=$(/usr/bin/mktemp -d /var/tmp/clamui-helper.XXXXXX) || exit 4
trap 'rm -rf -- "$stage"' EXIT HUP INT TERM
/usr/bin/chmod 700 -- "$stage"
target=$stage/helper.deb
# dd's nofollow/nonblock open is the root-side descriptor trust boundary.
/usr/bin/timeout 300 /usr/bin/dd if="$src" of="$target" bs=1 count="$size" iflag=nofollow,nonblock conv=fsync status=none || exit 4
[ "$(/usr/bin/stat -c %s -- "$target")" = "$size" ] || exit 4
[ "$(/usr/bin/sha256sum -- "$target" | /usr/bin/cut -d' ' -f1)" = "$digest" ] || exit 4
fields=$(/usr/bin/timeout 300 /usr/bin/dpkg-deb --show '--showformat=${Package}\n${Version}\n${Architecture}\n' -- "$target") || exit 5
[ "$fields" = "clamui-privileged-helper
$version
$arch" ] || exit 5
set +e
/usr/bin/timeout 300 /usr/bin/apt-get install -y -- "$target"
status=$?
exit "$status"
"#;

// The only low-level operations here are scoped nonblocking pipe setup and
// polling for owned child output. The passwd database is queried through the
// system `getent` tool rather than FFI; root helper paths are always absolute
// and checked for immutable root ownership before execution.

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StagedConfig {
    pub staged_source: PathBuf,
    pub destination: PathBuf,
}

impl StagedConfig {
    pub fn destination(&self) -> &Path {
        &self.destination
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PrivilegedWriteFailure {
    pub destination: PathBuf,
    pub message: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PrivilegedWriteResult {
    pub applied_paths: Vec<PathBuf>,
    pub failures: Vec<PrivilegedWriteFailure>,
}

impl PrivilegedWriteResult {
    pub fn is_success(&self) -> bool {
        self.failures.is_empty()
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PrivilegedHelperStatus {
    pub state: String,
    pub package_name: String,
    pub version: String,
    pub detail: Option<String>,
    pub installed: bool,
    pub installable: bool,
    pub needs_onboarding: bool,
}

fn app_version() -> String {
    env!("CARGO_PKG_VERSION").to_owned()
}

fn flatpak() -> bool {
    env::var_os("FLATPAK_ID").is_some() || Path::new("/.flatpak-info").is_file()
}

fn current_uid() -> u32 {
    // The passwd lookup below is authoritative for all security decisions. UID
    // is obtained from /proc to avoid trusting an environment variable.
    std::fs::metadata("/proc/self")
        .map(|m| m.uid())
        .unwrap_or(u32::MAX)
}

fn passwd_home(uid: u32) -> AppResult<PathBuf> {
    let getent = ["/usr/bin/getent", "/bin/getent"]
        .into_iter()
        .find(|path| root_owned_regular(Path::new(path), true))
        .ok_or_else(|| "trusted getent is unavailable for passwd lookup".to_owned())?;
    let output = Command::new(getent)
        .args(["passwd", &uid.to_string()])
        .output()
        .map_err(|error| format!("cannot query passwd entry for uid {uid}: {error}"))?;
    if !output.status.success() {
        return Err(format!("no passwd home is available for uid {uid}"));
    }
    let entry = String::from_utf8(output.stdout)
        .map_err(|_| format!("passwd home for uid {uid} is not UTF-8"))?;
    let fields: Vec<_> = entry.trim_end().split(':').collect();
    let home = fields.get(5).copied().unwrap_or_default();
    if home.is_empty() || !Path::new(home).is_absolute() {
        return Err(format!("passwd home for uid {uid} is not an absolute path"));
    }
    Ok(PathBuf::from(home))
}

/// The only staging root accepted by both caller and helper. It never reads
/// HOME, XDG_CACHE_HOME, or a Flatpak-specific environment variable.
pub fn staging_root_for_uid(uid: u32) -> AppResult<PathBuf> {
    Ok(passwd_home(uid)?.join(".cache/clamui/privileged-staging"))
}

fn helper_download_root_for_uid(uid: u32) -> AppResult<PathBuf> {
    Ok(passwd_home(uid)?.join(".cache/clamui/privileged-helper"))
}

fn canonical_parent(path: &Path) -> AppResult<PathBuf> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("destination has no parent: {}", path.display()))?;
    match parent.canonicalize() {
        Ok(parent) => Ok(parent),
        Err(error)
            if error.kind() == io::ErrorKind::NotFound
                && ALLOWED_DEST_DIRS
                    .iter()
                    .any(|allowed| parent == Path::new(allowed)) =>
        {
            // An optional ClamAV configuration directory may be absent on a
            // fresh host. It is safe to create only this exact allowlisted
            // direct parent; no missing nested path is accepted.
            Ok(parent.to_owned())
        }
        Err(error) => Err(format!(
            "cannot resolve destination parent {}: {error}",
            path.display()
        )),
    }
}

/// Canonicalize and enforce the narrow ClamAV configuration destination list.
pub fn validate_destination(destination: &Path) -> AppResult<PathBuf> {
    if destination.file_name().is_none() {
        return Err(format!(
            "destination has no file name: {}",
            destination.display()
        ));
    }
    let parent = canonical_parent(destination)?;
    let name = destination.file_name().expect("checked above");
    let candidate = parent.join(name);
    if candidate == Path::new(ALLOWED_DEST_FILE) {
        return Ok(candidate);
    }
    let stem = candidate
        .file_stem()
        .and_then(|stem| stem.to_str())
        .unwrap_or_default();
    if candidate
        .extension()
        .and_then(|extension| extension.to_str())
        != Some("conf")
        || stem.is_empty()
    {
        return Err(format!(
            "destination must be a named .conf file: {}",
            destination.display()
        ));
    }
    if !ALLOWED_DEST_DIRS
        .iter()
        .any(|allowed| candidate.parent() == Some(Path::new(allowed)))
    {
        return Err(format!(
            "destination is not an allowed ClamAV config path: {}",
            destination.display()
        ));
    }
    Ok(candidate)
}

fn safe_metadata(path: &Path) -> AppResult<std::fs::Metadata> {
    fs::symlink_metadata(path)
        .map_err(|error| format!("cannot inspect {}: {error}", path.display()))
}

fn root_owned_regular(path: &Path, executable: bool) -> bool {
    let Ok(metadata) = safe_metadata(path) else {
        return false;
    };
    metadata.file_type().is_file()
        && metadata.uid() == 0
        && metadata.mode() & 0o022 == 0
        && (!executable || metadata.mode() & 0o100 != 0)
}

fn root_owned_directory(path: &Path) -> bool {
    let Ok(metadata) = safe_metadata(path) else {
        return false;
    };
    metadata.file_type().is_dir() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0
}

fn has_elf_magic(path: &Path) -> bool {
    let Ok(mut file) = open_read_nofollow(path) else {
        return false;
    };
    let mut magic = [0; 4];
    file.read_exact(&mut magic).is_ok() && magic == [0x7f, b'E', b'L', b'F']
}

/// On Flatpak, probe the exact host path that will be passed to pkexec.
///
/// PATH is deliberately not consulted: a pyenv, conda, or venv executable
/// earlier in the host PATH must not change whether the canonical helper is
/// available.
fn canonical_host_helper_exists() -> bool {
    host_command(
        "/usr/bin/test",
        &["-f", HELPER_PATH, "-a", "-x", HELPER_PATH],
    )
    .is_ok_and(|output| output.status.success())
}

/// Return the only executable that may be handed to pkexec. New native helpers
/// are trusted directly; legacy v4 Python wrappers remain accepted only when
/// every imported module is immutable and root-owned.
pub fn trusted_helper_path() -> AppResult<PathBuf> {
    let canonical = PathBuf::from(HELPER_PATH);
    if flatpak() {
        if canonical_host_helper_exists() {
            return Ok(canonical);
        }
        return Err("the canonical host privileged helper is unavailable".to_owned());
    }
    if !root_owned_regular(&canonical, true) {
        return Err(
            "the canonical privileged helper is not a root-owned immutable executable".to_owned(),
        );
    }
    if has_elf_magic(&canonical) {
        return Ok(canonical);
    }
    if !root_owned_directory(Path::new(LEGACY_HELPER_LIB_DIR))
        || !LEGACY_HELPER_MODULES
            .iter()
            .all(|path| root_owned_regular(Path::new(path), false))
    {
        return Err(
            "legacy privileged helper libraries are not root-owned and immutable".to_owned(),
        );
    }
    Ok(canonical)
}

fn open_read_nofollow(path: &Path) -> AppResult<File> {
    OpenOptions::new()
        .read(true)
        .custom_flags(O_NOFOLLOW | O_NONBLOCK)
        .open(path)
        .map_err(|error| format!("cannot safely open {}: {error}", path.display()))
}

fn verify_owned_tight_directory(file: &File, expected_uid: u32, label: &Path) -> AppResult<()> {
    let metadata = file
        .metadata()
        .map_err(|error| format!("cannot inspect {}: {error}", label.display()))?;
    if !metadata.is_dir() {
        return Err(format!(
            "staging path is not a directory: {}",
            label.display()
        ));
    }
    if metadata.uid() != expected_uid || metadata.mode() & 0o077 != 0 {
        return Err(format!(
            "staging path is not private and caller-owned: {}",
            label.display()
        ));
    }
    Ok(())
}

/// Verify the root with an O_NOFOLLOW descriptor. Config callers use this to
/// fail before spawning pkexec, while the helper repeats the check as root.
pub fn verify_staging_root(root: &Path, expected_uid: u32) -> AppResult<()> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(O_NOFOLLOW | O_DIRECTORY)
        .open(root)
        .map_err(|error| {
            format!(
                "cannot safely open staging root {}: {error}",
                root.display()
            )
        })?;
    verify_owned_tight_directory(&file, expected_uid, root)
}

/// Open and authenticate a staged source. O_NOFOLLOW binds the returned
/// descriptor to a regular non-symlink file; canonical containment is checked
/// against the independently verified private root before the descriptor is
/// used for any write.
pub fn open_verified_staged_source(
    source: &Path,
    expected_uid: u32,
    root: &Path,
) -> AppResult<File> {
    verify_staging_root(root, expected_uid)?;
    let relative = source.strip_prefix(root).map_err(|_| {
        format!(
            "staged source is outside the caller staging root: {}",
            source.display()
        )
    })?;
    if relative
        .components()
        .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(format!(
            "staged source has an unsafe path component: {}",
            source.display()
        ));
    }
    let file = open_read_nofollow(source)?;
    let metadata = file
        .metadata()
        .map_err(|error| format!("cannot inspect staged source {}: {error}", source.display()))?;
    if !metadata.is_file() || metadata.uid() != expected_uid || metadata.mode() & 0o022 != 0 {
        return Err(format!(
            "staged source is not a private regular caller-owned file: {}",
            source.display()
        ));
    }
    let canonical_root = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve staging root {}: {error}", root.display()))?;
    let canonical_source = source
        .canonicalize()
        .map_err(|error| format!("cannot resolve staged source {}: {error}", source.display()))?;
    canonical_source
        .strip_prefix(&canonical_root)
        .map_err(|_| {
            format!(
                "staged source is outside the caller staging root: {}",
                source.display()
            )
        })?;
    Ok(file)
}

fn private_directory(path: &Path, uid: u32) -> AppResult<()> {
    let existed = path.exists();
    fs::create_dir_all(path)
        .map_err(|error| format!("cannot create {}: {error}", path.display()))?;
    let metadata = safe_metadata(path)?;
    if !metadata.file_type().is_dir() || metadata.uid() != uid {
        return Err(format!(
            "refusing unsafe private directory {}",
            path.display()
        ));
    }
    if existed && metadata.mode() & 0o077 != 0 {
        return Err(format!(
            "refusing unsafe private directory {}",
            path.display()
        ));
    }
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))
        .map_err(|error| format!("cannot secure {}: {error}", path.display()))
}

fn unique_directory(parent: &Path, prefix: &str) -> AppResult<PathBuf> {
    for _ in 0..32 {
        let counter = UNIQUE_COUNTER.fetch_add(1, Ordering::Relaxed);
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |time| time.as_nanos());
        let candidate = parent.join(format!(
            "{prefix}-{}-{nonce:x}-{counter:x}",
            std::process::id()
        ));
        match fs::create_dir(&candidate) {
            Ok(()) => {
                fs::set_permissions(&candidate, fs::Permissions::from_mode(0o700))
                    .map_err(|error| format!("cannot secure {}: {error}", candidate.display()))?;
                return Ok(candidate);
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("cannot create {}: {error}", candidate.display())),
        }
    }
    Err("could not allocate a private staging directory".to_owned())
}

/// Stage one already-validated config in a passwd-home derived private path.
pub fn stage_config(bytes: &[u8], destination: &Path) -> AppResult<StagedConfig> {
    let destination = validate_destination(destination)?;
    let uid = current_uid();
    if uid == u32::MAX {
        return Err("cannot determine caller uid".to_owned());
    }
    let root = staging_root_for_uid(uid)?;
    private_directory(&root, uid)?;
    let directory = unique_directory(&root, "write")?;
    let source = directory.join("config.conf");
    let write_result = (|| -> AppResult<()> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(O_NOFOLLOW)
            .open(&source)
            .map_err(|error| format!("cannot stage {}: {error}", source.display()))?;
        file.write_all(bytes)
            .map_err(|error| format!("cannot stage config: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("cannot sync staged config: {error}"))?;
        fs::set_permissions(&source, fs::Permissions::from_mode(0o600))
            .map_err(|error| format!("cannot secure staged config: {error}"))?;
        Ok(())
    })();
    if let Err(error) = write_result {
        let _ = fs::remove_dir_all(&directory);
        return Err(error);
    }
    Ok(StagedConfig {
        staged_source: source,
        destination,
    })
}

fn helper_command(helper: &Path) -> Command {
    if flatpak() {
        let mut command = Command::new("flatpak-spawn");
        command.arg("--host").arg("pkexec").arg(helper);
        command
    } else {
        let mut command = Command::new("pkexec");
        command.arg(helper);
        command
    }
}

fn host_command(program: &str, args: &[&str]) -> AppResult<std::process::Output> {
    let mut command = if flatpak() {
        let mut command = Command::new("flatpak-spawn");
        command.arg("--host").arg(program);
        command
    } else {
        Command::new(program)
    };
    command.args(args);
    command
        .output()
        .map_err(|error| format!("cannot run {program}: {error}"))
}

fn host_bounded_output(
    program: &str,
    args: &[&str],
    max: usize,
    deadline: Duration,
) -> AppResult<(std::process::ExitStatus, Vec<u8>, Vec<u8>)> {
    let mut command = if flatpak() {
        let mut command = Command::new("flatpak-spawn");
        command.arg("--host").arg(program);
        command
    } else {
        Command::new(program)
    };
    command.args(args);
    bounded_child_output(command, max, deadline)
}

fn sanitized_helper_stderr(stderr: &[u8]) -> String {
    let mut detail = crate::common::sanitize_line(&String::from_utf8_lossy(stderr));
    crate::logs::redact_secrets(&mut detail);
    detail.truncate(detail.trim_end().len());
    let leading = detail.len() - detail.trim_start().len();
    if leading > 0 {
        detail.drain(..leading);
    }
    detail
}

fn helper_failure(return_code: Option<i32>, stderr: &[u8], operation: &str) -> String {
    let detail = sanitized_helper_stderr(stderr);
    match return_code {
        Some(126) => format!("authorization was cancelled while {operation}"),
        Some(127) => format!("the privileged helper is unavailable while {operation}"),
        Some(3) => format!("the privileged helper rejected PKEXEC_UID while {operation}"),
        Some(4) => format!("the privileged helper reported a protocol mismatch while {operation}"),
        Some(code) if !detail.is_empty() => {
            format!("privileged helper failed while {operation} (exit {code}): {detail}")
        }
        Some(code) => format!("privileged helper failed while {operation} (exit {code})"),
        None => format!("privileged helper was terminated while {operation}"),
    }
}

fn client_helper_failure(
    ctx: &Context,
    return_code: Option<i32>,
    stderr: &[u8],
    operation: &str,
) -> String {
    let detail = sanitized_helper_stderr(stderr);
    match return_code {
        Some(126) => crate::i18n::translate(
            ctx,
            // Translators: keep the {operation} placeholder; it is a localized operation name.
            "Authorization was cancelled while {operation}.",
        )
        .replace("{operation}", operation),
        Some(127) => crate::i18n::translate(
            ctx,
            // Translators: keep the {operation} placeholder; it is a localized operation name.
            "The privileged helper is unavailable while {operation}.",
        )
        .replace("{operation}", operation),
        Some(3) => crate::i18n::translate(
            ctx,
            // Translators: PKEXEC_UID is a technical environment-variable name; keep it unchanged.
            "The privileged helper rejected PKEXEC_UID while {operation}.",
        )
        .replace("{operation}", operation),
        Some(4) => crate::i18n::translate(
            ctx,
            // Translators: keep the {operation} placeholder; it is a localized operation name.
            "The privileged helper reported a protocol mismatch while {operation}.",
        )
        .replace("{operation}", operation),
        Some(code) if !detail.is_empty() => crate::i18n::translate(
            ctx,
            // Translators: keep {operation}, numeric {code}, and sanitized diagnostic {detail}.
            "The privileged helper failed while {operation} (exit {code}): {detail}.",
        )
        .replace("{operation}", operation)
        .replace("{code}", &code.to_string())
        .replace("{detail}", &detail),
        Some(code) => crate::i18n::translate(
            ctx,
            // Translators: keep the {operation} and numeric {code} placeholders.
            "The privileged helper failed while {operation} (exit {code}).",
        )
        .replace("{operation}", operation)
        .replace("{code}", &code.to_string()),
        None => crate::i18n::translate(
            ctx,
            // Translators: keep the {operation} placeholder; it is a localized operation name.
            "The privileged helper was terminated while {operation}.",
        )
        .replace("{operation}", operation),
    }
}

fn preflight_staged(config: &StagedConfig, uid: u32, root: &Path) -> AppResult<()> {
    validate_destination(&config.destination)?;
    let _source = open_verified_staged_source(&config.staged_source, uid, root)?;
    Ok(())
}

fn cleanup_staged(configs: &[StagedConfig]) {
    for config in configs {
        let _ = fs::remove_file(&config.staged_source);
        if let Some(parent) = config.staged_source.parent() {
            let _ = fs::remove_dir(parent);
        }
    }
}

/// Submit all protected writes through exactly one v4 pkexec request. A helper
/// error after preflight is intentionally reported as *possibly partial*: a
/// restart or later replace may fail after an earlier destination changed.
pub fn write_staged_configs(
    ctx: &Context,
    configs: &[StagedConfig],
) -> AppResult<PrivilegedWriteResult> {
    if configs.is_empty() {
        return Ok(PrivilegedWriteResult::default());
    }
    let uid = current_uid();
    let root = staging_root_for_uid(uid)?;
    let result = (|| -> AppResult<PrivilegedWriteResult> {
        verify_staging_root(&root, uid)?;
        for config in configs {
            preflight_staged(config, uid, &root)?;
        }
        let helper = trusted_helper_path()?;
        let mut command = helper_command(&helper);
        command.arg(format!("--protocol={PROTOCOL_VERSION}"));
        for config in configs {
            command.arg(&config.staged_source).arg(&config.destination);
        }
        let output = command
            .output()
            .map_err(|error| format!("cannot start privileged helper: {error}"))?;
        if output.status.success() {
            return Ok(PrivilegedWriteResult {
                applied_paths: configs
                    .iter()
                    .map(|config| config.destination.clone())
                    .collect(),
                failures: Vec::new(),
            });
        }
        let operation = crate::i18n::translate(ctx, "Applying configuration");
        let message = client_helper_failure(ctx, output.status.code(), &output.stderr, &operation);
        let partial_message = crate::i18n::translate(
            ctx,
            // Translators: keep {message}; it is the complete preceding helper error.
            "{message} One or more earlier replacements may have succeeded.",
        )
        .replace("{message}", &message);
        Ok(PrivilegedWriteResult {
            applied_paths: Vec::new(),
            failures: configs
                .iter()
                .map(|config| PrivilegedWriteFailure {
                    destination: config.destination.clone(),
                    message: partial_message.clone(),
                })
                .collect(),
        })
    })();
    cleanup_staged(configs);
    result
}

fn set_nonblocking<R: AsRawFd>(reader: &R) -> AppResult<()> {
    let descriptor = reader.as_raw_fd();
    let flags = unsafe { libc::fcntl(descriptor, libc::F_GETFL) };
    if flags < 0 {
        return Err(format!(
            "cannot inspect helper output descriptor: {}",
            io::Error::last_os_error()
        ));
    }
    if unsafe { libc::fcntl(descriptor, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        return Err(format!(
            "cannot make helper output descriptor nonblocking: {}",
            io::Error::last_os_error()
        ));
    }
    Ok(())
}

fn drain_stdout(reader: &mut ChildStdout, output: &mut Vec<u8>, max: usize) -> AppResult<bool> {
    let mut buffer = [0u8; 8192];
    match reader.read(&mut buffer) {
        Ok(0) => Ok(true),
        Ok(read) if read > max.saturating_sub(output.len()) => {
            Err(format!("helper output exceeds the {max} byte limit"))
        }
        Ok(read) => {
            output.extend_from_slice(&buffer[..read]);
            Ok(false)
        }
        Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(false),
        Err(error) => Err(format!("cannot read helper stdout: {error}")),
    }
}

fn drain_stderr(reader: &mut ChildStderr, output: &mut Vec<u8>) -> AppResult<bool> {
    let mut buffer = [0u8; 8192];
    match reader.read(&mut buffer) {
        Ok(0) => Ok(true),
        Ok(read) => {
            let retained = (64 * 1024usize).saturating_sub(output.len()).min(read);
            output.extend_from_slice(&buffer[..retained]);
            Ok(false)
        }
        Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(false),
        Err(error) => Err(format!("cannot read helper stderr: {error}")),
    }
}

fn poll_output(
    stdout: &ChildStdout,
    stderr: &ChildStderr,
    stdout_closed: bool,
    stderr_closed: bool,
    timeout: Duration,
) -> AppResult<(bool, bool)> {
    let mut descriptors = [
        libc::pollfd {
            fd: if stdout_closed {
                -1
            } else {
                stdout.as_raw_fd()
            },
            events: libc::POLLIN,
            revents: 0,
        },
        libc::pollfd {
            fd: if stderr_closed {
                -1
            } else {
                stderr.as_raw_fd()
            },
            events: libc::POLLIN,
            revents: 0,
        },
    ];
    let milliseconds = timeout.as_millis().min(i32::MAX as u128) as i32;
    let result = unsafe {
        libc::poll(
            descriptors.as_mut_ptr(),
            descriptors.len() as _,
            milliseconds,
        )
    };
    if result < 0 {
        return Err(format!(
            "cannot poll helper output: {}",
            io::Error::last_os_error()
        ));
    }
    let readable = libc::POLLIN | libc::POLLHUP | libc::POLLERR;
    Ok((
        !stdout_closed && descriptors[0].revents & readable != 0,
        !stderr_closed && descriptors[1].revents & readable != 0,
    ))
}

fn terminate_owned_process_group(child: &mut Child) {
    let group = format!("-{}", child.id());
    let _ = Command::new("/bin/kill")
        .args(["-TERM", "--", &group])
        .status();
    let _ = child.kill();
    let _ = Command::new("/bin/kill")
        .args(["-KILL", "--", &group])
        .status();

    let deadline = Instant::now() + Duration::from_secs(1);
    loop {
        match child.try_wait() {
            Ok(Some(_)) | Err(_) => return,
            Ok(None) if Instant::now() >= deadline => return,
            Ok(None) => thread::sleep(Duration::from_millis(10)),
        }
    }
}

fn bounded_child_output(
    mut command: Command,
    max: usize,
    deadline: Duration,
) -> AppResult<(std::process::ExitStatus, Vec<u8>, Vec<u8>)> {
    command
        .process_group(0)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|error| format!("cannot start command: {error}"))?;
    let mut stdout_reader = match child.stdout.take() {
        Some(reader) => reader,
        None => {
            terminate_owned_process_group(&mut child);
            return Err("helper stdout was not captured".to_owned());
        }
    };
    let mut stderr_reader = match child.stderr.take() {
        Some(reader) => reader,
        None => {
            terminate_owned_process_group(&mut child);
            return Err("helper stderr was not captured".to_owned());
        }
    };
    if let Err(error) =
        set_nonblocking(&stdout_reader).and_then(|()| set_nonblocking(&stderr_reader))
    {
        drop(stdout_reader);
        drop(stderr_reader);
        terminate_owned_process_group(&mut child);
        return Err(error);
    }

    let started = Instant::now();
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    let mut stdout_closed = false;
    let mut stderr_closed = false;
    let mut status = None;
    let outcome = loop {
        if started.elapsed() >= deadline {
            break Err("helper command exceeded its deadline".to_owned());
        }
        if status.is_none() {
            match child.try_wait() {
                Ok(current) => status = current,
                Err(error) => break Err(format!("cannot inspect helper command: {error}")),
            }
        }
        if stdout_closed && stderr_closed {
            if let Some(status) = status {
                break Ok((status, stdout, stderr));
            }
            thread::sleep(Duration::from_millis(10));
            continue;
        }
        let remaining = deadline.saturating_sub(started.elapsed());
        let (stdout_ready, stderr_ready) = match poll_output(
            &stdout_reader,
            &stderr_reader,
            stdout_closed,
            stderr_closed,
            remaining.min(Duration::from_millis(100)),
        ) {
            Ok(ready) => ready,
            Err(error) => break Err(error),
        };
        if stdout_ready && !stdout_closed {
            match drain_stdout(&mut stdout_reader, &mut stdout, max) {
                Ok(closed) => stdout_closed = closed,
                Err(error) => break Err(error),
            }
        }
        if stderr_ready && !stderr_closed {
            match drain_stderr(&mut stderr_reader, &mut stderr) {
                Ok(closed) => stderr_closed = closed,
                Err(error) => break Err(error),
            }
        }
    };
    drop(stdout_reader);
    drop(stderr_reader);
    if outcome.is_err() {
        terminate_owned_process_group(&mut child);
    }
    outcome
}

/// Explicit-only protected read. The helper's output is bounded again here so
/// an old or compromised helper cannot make the UI retain unbounded root data.
pub fn read_config(ctx: &Context, path: &Path) -> AppResult<Vec<u8>> {
    let path = validate_destination(path)?;
    let helper = trusted_helper_path()?;
    let mut command = helper_command(&helper);
    command
        .arg(format!("--protocol={PROTOCOL_VERSION}"))
        .arg("--read-config")
        .arg(path);
    let (status, stdout, stderr) =
        bounded_child_output(command, MAX_CONFIG_READ_BYTES, Duration::from_secs(300))?;
    if status.success() {
        Ok(stdout)
    } else {
        let operation = crate::i18n::translate(ctx, "Reading configuration");
        Err(client_helper_failure(
            ctx,
            status.code(),
            &stderr,
            &operation,
        ))
    }
}

fn existing_destination_metadata(destination: &Path) -> AppResult<Option<(u32, u32, u32)>> {
    match open_read_nofollow(destination) {
        Ok(file) => {
            let metadata = file
                .metadata()
                .map_err(|error| format!("cannot inspect {}: {error}", destination.display()))?;
            if !metadata.is_file() {
                return Err(format!(
                    "destination is not a regular file: {}",
                    destination.display()
                ));
            }
            Ok(Some((
                metadata.uid(),
                metadata.gid(),
                metadata.mode() & 0o777,
            )))
        }
        Err(_) if !destination.exists() => Ok(None),
        Err(error) => Err(error),
    }
}

fn ensure_destination_parent(parent: &Path) -> AppResult<()> {
    match fs::create_dir(parent) {
        Ok(()) => {
            fs::set_permissions(parent, fs::Permissions::from_mode(0o755)).map_err(|error| {
                format!(
                    "cannot secure destination directory {}: {error}",
                    parent.display()
                )
            })?
        }
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
        Err(error) => {
            return Err(format!(
                "cannot create destination directory {}: {error}",
                parent.display()
            ));
        }
    }
    if !root_owned_directory(parent) {
        return Err(format!(
            "destination directory is not root-owned and immutable: {}",
            parent.display()
        ));
    }
    Ok(())
}

fn fsync_directory(directory: &Path) -> AppResult<()> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(O_NOFOLLOW | O_DIRECTORY)
        .open(directory)
        .map_err(|error| {
            format!(
                "cannot open destination directory {}: {error}",
                directory.display()
            )
        })?;
    file.sync_all().map_err(|error| {
        format!(
            "cannot sync destination directory {}: {error}",
            directory.display()
        )
    })
}

fn atomic_replace(mut source: File, destination: &Path) -> AppResult<()> {
    let parent = destination
        .parent()
        .ok_or_else(|| format!("destination has no parent: {}", destination.display()))?;
    ensure_destination_parent(parent)?;
    let metadata = existing_destination_metadata(destination)?;
    let temporary = unique_file(
        parent,
        destination
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("clamui"),
    )?;
    let outcome = (|| -> AppResult<()> {
        let mut target = OpenOptions::new()
            .write(true)
            .truncate(true)
            .mode(0o600)
            .custom_flags(O_NOFOLLOW)
            .open(&temporary)
            .map_err(|error| format!("cannot open replacement {}: {error}", temporary.display()))?;
        io::copy(&mut source, &mut target)
            .map_err(|error| format!("cannot copy config: {error}"))?;
        target
            .sync_all()
            .map_err(|error| format!("cannot sync replacement: {error}"))?;
        if let Some((uid, gid, mode)) = metadata {
            let chown = canonical_tool(&["/usr/bin/chown", "/bin/chown"])?;
            let ownership = format!("{uid}:{gid}");
            let output = Command::new(chown)
                .arg(ownership)
                .arg(&temporary)
                .output()
                .map_err(|error| format!("cannot preserve destination ownership: {error}"))?;
            if !output.status.success() {
                return Err(format!(
                    "cannot preserve destination ownership: {}",
                    sanitized_helper_stderr(&output.stderr)
                ));
            }
            target
                .set_permissions(fs::Permissions::from_mode(mode))
                .map_err(|error| format!("cannot preserve destination mode: {error}"))?;
        } else {
            target
                .set_permissions(fs::Permissions::from_mode(0o600))
                .map_err(|error| format!("cannot secure new destination: {error}"))?;
        }
        target
            .sync_all()
            .map_err(|error| format!("cannot sync destination metadata: {error}"))?;
        fs::rename(&temporary, destination).map_err(|error| {
            format!(
                "cannot atomically replace {}: {error}",
                destination.display()
            )
        })?;
        fsync_directory(parent)?;
        Ok(())
    })();
    if outcome.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    outcome
}

fn unique_file(parent: &Path, name: &str) -> AppResult<PathBuf> {
    for _ in 0..32 {
        let counter = UNIQUE_COUNTER.fetch_add(1, Ordering::Relaxed);
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |time| time.as_nanos());
        let candidate = parent.join(format!(".{name}.clamui-{nonce:x}-{counter:x}.tmp"));
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(O_NOFOLLOW)
            .open(&candidate)
        {
            Ok(file) => {
                drop(file);
                return Ok(candidate);
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(format!(
                    "cannot create temporary replacement {}: {error}",
                    candidate.display()
                ))
            }
        }
    }
    Err("could not allocate replacement file".to_owned())
}

fn read_allowlisted_config(path: &Path) -> AppResult<Vec<u8>> {
    let path = validate_destination(path)?;
    let file = open_read_nofollow(&path)?;
    let metadata = file
        .metadata()
        .map_err(|error| format!("cannot inspect {}: {error}", path.display()))?;
    if !metadata.is_file() {
        return Err(format!(
            "configuration is not a regular file: {}",
            path.display()
        ));
    }
    if metadata.len() > MAX_CONFIG_READ_BYTES as u64 {
        return Err(format!(
            "configuration exceeds {MAX_CONFIG_READ_BYTES} byte read limit: {}",
            path.display()
        ));
    }
    let mut content = Vec::with_capacity(metadata.len() as usize);
    file.take((MAX_CONFIG_READ_BYTES + 1) as u64)
        .read_to_end(&mut content)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    if content.len() > MAX_CONFIG_READ_BYTES {
        return Err(format!(
            "configuration exceeds {MAX_CONFIG_READ_BYTES} byte read limit: {}",
            path.display()
        ));
    }
    Ok(content)
}

fn service_path() -> Option<&'static str> {
    ["/usr/bin/systemctl", "/bin/systemctl"]
        .into_iter()
        .find(|path| root_owned_regular(Path::new(path), true))
}

fn restart_services(destinations: &[PathBuf]) -> AppResult<()> {
    let Some(systemctl) = service_path() else {
        return Ok(());
    };
    let mut units = BTreeSet::new();
    for destination in destinations {
        if destination.file_name().and_then(|name| name.to_str()) == Some("freshclam.conf") {
            units.extend(["clamav-freshclam.service", "freshclam.service"]);
        } else if destination.file_name().and_then(|name| name.to_str()) == Some("clamd.conf")
            || destination.parent() == Some(Path::new("/etc/clamd.d"))
        {
            units.extend([
                "clamav-daemon.service",
                "clamd.service",
                "clamd@scan.service",
                "clamav-clamonacc.service",
            ]);
        }
    }
    for unit in units {
        let active = Command::new(systemctl)
            .args(["is-active", "--quiet", unit])
            .status()
            .map_err(|error| format!("cannot check {unit}: {error}"))?;
        if active.success() {
            let restarted = Command::new(systemctl)
                .args(["restart", unit])
                .output()
                .map_err(|error| format!("cannot restart {unit}: {error}"))?;
            if !restarted.status.success() {
                let detail = sanitized_helper_stderr(&restarted.stderr);
                return Err(format!("failed to restart {unit}: {detail}"));
            }
        }
    }
    Ok(())
}

fn parse_pkexec_uid() -> AppResult<u32> {
    let raw = env::var("PKEXEC_UID").map_err(|_| "PKEXEC_UID is missing".to_owned())?;
    let uid = raw
        .parse::<u32>()
        .map_err(|_| "PKEXEC_UID is invalid".to_owned())?;
    if uid == 0 {
        Err("PKEXEC_UID must be a non-root caller".to_owned())
    } else {
        Ok(uid)
    }
}

fn run_config_helper(args: &[String], uid: u32) -> AppResult<()> {
    if args.is_empty() || !args.len().is_multiple_of(2) {
        return Err("expected one or more staged-source/destination pairs".to_owned());
    }
    let root = staging_root_for_uid(uid)?;
    verify_staging_root(&root, uid)?;
    let mut pairs = Vec::with_capacity(args.len() / 2);
    for chunk in args.chunks_exact(2) {
        pairs.push((
            PathBuf::from(&chunk[0]),
            validate_destination(Path::new(&chunk[1]))?,
        ));
    }
    let mut prepared = Vec::with_capacity(pairs.len());
    for (source, destination) in pairs {
        prepared.push((
            open_verified_staged_source(&source, uid, &root)?,
            destination,
        ));
    }
    let mut replaced = Vec::new();
    for (source, destination) in prepared {
        atomic_replace(source, &destination)?;
        replaced.push(destination);
    }
    restart_services(&replaced)
}

fn hex_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn canonical_tool(names: &[&str]) -> AppResult<String> {
    for path in names {
        if root_owned_regular(Path::new(path), true) {
            return Ok((*path).to_owned());
        }
    }
    Err(format!(
        "required trusted tool is unavailable: {}",
        names.join(" or ")
    ))
}

fn sha256_file(path: &Path) -> AppResult<String> {
    let tool = canonical_tool(&["/usr/bin/sha256sum", "/bin/sha256sum"])?;
    let output = Command::new(tool)
        .arg(path)
        .output()
        .map_err(|error| format!("cannot hash helper package: {error}"))?;
    if !output.status.success() {
        return Err("cannot hash helper package".to_owned());
    }
    let digest = String::from_utf8_lossy(&output.stdout)
        .split_whitespace()
        .next()
        .unwrap_or_default()
        .to_owned();
    if !hex_digest(&digest) {
        return Err("sha256sum returned an invalid digest".to_owned());
    }
    Ok(digest)
}

fn dpkg_architecture() -> AppResult<String> {
    let output = host_command("/usr/bin/dpkg", &["--print-architecture"])?;
    if !output.status.success() {
        return Err("cannot determine Debian architecture".to_owned());
    }
    let architecture = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    if architecture.is_empty()
        || !architecture
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    {
        return Err("dpkg returned an invalid architecture".to_owned());
    }
    Ok(architecture)
}

fn package_name(architecture: &str) -> String {
    format!("{HELPER_PACKAGE}_{}_{}.deb", app_version(), architecture)
}

fn verify_deb_identity(path: &Path, architecture: &str) -> AppResult<()> {
    let path_text = path.to_string_lossy().into_owned();
    let output = host_command(
        "/usr/bin/dpkg-deb",
        &[
            "--show",
            "--showformat=${Package}\n${Version}\n${Architecture}\n",
            &path_text,
        ],
    )?;
    if !output.status.success() {
        return Err("cannot inspect helper package identity".to_owned());
    }
    let version = app_version();
    let decoded = String::from_utf8_lossy(&output.stdout);
    let fields: Vec<_> = decoded.lines().collect();
    if fields != [HELPER_PACKAGE, version.as_str(), architecture] {
        return Err("helper package identity, version, or architecture is unexpected".to_owned());
    }
    Ok(())
}

fn read_deb_members(path: &Path) -> AppResult<BTreeMap<String, Vec<u8>>> {
    let mut file = open_read_nofollow(path)?;
    let size = file
        .metadata()
        .map_err(|error| format!("cannot inspect package: {error}"))?
        .len();
    if size > MAX_HELPER_PACKAGE_BYTES {
        return Err("helper package exceeds size limit".to_owned());
    }
    let mut raw = Vec::with_capacity(size as usize);
    file.read_to_end(&mut raw)
        .map_err(|error| format!("cannot read helper package: {error}"))?;
    if !raw.starts_with(b"!<arch>\n") {
        return Err("helper package is not a Debian ar archive".to_owned());
    }
    let mut offset = 8usize;
    let mut members = BTreeMap::new();
    while offset < raw.len() {
        if raw.len() - offset < 60 || &raw[offset + 58..offset + 60] != b"`\n" {
            return Err("helper package has an invalid ar member".to_owned());
        }
        let raw_name = std::str::from_utf8(&raw[offset..offset + 16])
            .map_err(|_| "helper package member name is invalid".to_owned())?
            .trim();
        let name = raw_name.strip_suffix('/').unwrap_or(raw_name);
        let raw_size = std::str::from_utf8(&raw[offset + 48..offset + 58])
            .map_err(|_| "helper package member size is invalid".to_owned())?
            .trim();
        if name.is_empty()
            || name.contains('/')
            || name.starts_with("#1/")
            || !raw_size.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err("helper package has an unsafe ar member".to_owned());
        }
        let length = raw_size
            .parse::<usize>()
            .map_err(|_| "helper package member size overflows".to_owned())?;
        let start = offset + 60;
        let end = start
            .checked_add(length)
            .ok_or_else(|| "helper package member length overflows".to_owned())?;
        if end > raw.len()
            || members
                .insert(name.to_owned(), raw[start..end].to_vec())
                .is_some()
        {
            return Err("helper package contains duplicate or truncated members".to_owned());
        }
        if length % 2 == 1 && (end == raw.len() || raw[end] != b'\n') {
            return Err("helper package has an invalid ar padding byte".to_owned());
        }
        offset = end + length % 2;
        if offset > raw.len() {
            return Err("helper package has an invalid ar padding byte".to_owned());
        }
    }
    Ok(members)
}

fn hash_bytes(program: &str, bytes: &[u8]) -> AppResult<String> {
    let mut child = Command::new(program)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("cannot start digest tool: {error}"))?;
    child
        .stdin
        .take()
        .ok_or_else(|| "digest stdin unavailable".to_owned())?
        .write_all(bytes)
        .map_err(|error| format!("cannot feed digest tool: {error}"))?;
    let output = child
        .wait_with_output()
        .map_err(|error| format!("cannot read digest tool: {error}"))?;
    if !output.status.success() {
        return Err("digest tool failed".to_owned());
    }
    Ok(String::from_utf8_lossy(&output.stdout)
        .split_whitespace()
        .next()
        .unwrap_or_default()
        .to_owned())
}

fn signed_members_match(signature: &str, members: &BTreeMap<String, Vec<u8>>) -> AppResult<()> {
    let lines: Vec<_> = signature.lines().collect();
    if lines.iter().filter(|line| **line == "Version: 4").count() != 1
        || lines
            .iter()
            .filter(|line| **line == "Role: builder")
            .count()
            != 1
    {
        return Err("helper signature is not a dpkg-sig v4 builder signature".to_owned());
    }
    let start = lines
        .iter()
        .position(|line| *line == "Files:")
        .ok_or_else(|| "helper signature lacks signed members".to_owned())?
        + 1;
    let md5 = canonical_tool(&["/usr/bin/md5sum", "/bin/md5sum"])?;
    let sha1 = canonical_tool(&["/usr/bin/sha1sum", "/bin/sha1sum"])?;
    let mut signed = BTreeSet::new();
    for line in &lines[start..] {
        let fields: Vec<_> = line.split_whitespace().collect();
        if fields.len() != 4 || !signed.insert(fields[3].to_owned()) {
            return Err("helper signature has malformed signed members".to_owned());
        }
        let bytes = members
            .get(fields[3])
            .ok_or_else(|| "helper signature names a missing member".to_owned())?;
        if fields[2].parse::<usize>().ok() != Some(bytes.len())
            || hash_bytes(&md5, bytes)? != fields[0]
            || hash_bytes(&sha1, bytes)? != fields[1]
        {
            return Err("helper signature does not match archive members".to_owned());
        }
    }
    let control = members
        .keys()
        .filter(|name| name.starts_with("control.tar."))
        .collect::<Vec<_>>();
    let data = members
        .keys()
        .filter(|name| name.starts_with("data.tar."))
        .collect::<Vec<_>>();
    if control.len() != 1
        || data.len() != 1
        || members.len() != 4
        || !members.contains_key("_gpgbuilder")
    {
        return Err("helper package has an unexpected signed member set".to_owned());
    }
    let expected = BTreeSet::from([
        "debian-binary".to_owned(),
        (*control[0]).to_owned(),
        (*data[0]).to_owned(),
    ]);
    if signed != expected {
        return Err("helper package has an unexpected signed member set".to_owned());
    }
    Ok(())
}

fn verify_deb_signature(path: &Path) -> AppResult<()> {
    let members = read_deb_members(path)?;
    let signature = members
        .get("_gpgbuilder")
        .ok_or_else(|| "helper package has no builder signature".to_owned())?;
    let temporary_root = path
        .parent()
        .ok_or_else(|| "helper package has no parent directory".to_owned())?;
    let home = unique_directory(temporary_root, "clamui-gpg")?;
    let signature_path = home.join("builder.asc");
    let key_path = home.join("clamui-signing-key.asc");
    let outcome = (|| -> AppResult<()> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(O_NOFOLLOW)
            .open(&signature_path)
            .map_err(|error| format!("cannot create signature file: {error}"))?;
        file.write_all(signature)
            .map_err(|error| format!("cannot write signature file: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("cannot sync signature file: {error}"))?;
        let mut key_file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(O_NOFOLLOW)
            .open(&key_path)
            .map_err(|error| format!("cannot create pinned signing key file: {error}"))?;
        key_file
            .write_all(PINNED_SIGNING_KEY)
            .map_err(|error| format!("cannot write pinned signing key: {error}"))?;
        key_file
            .sync_all()
            .map_err(|error| format!("cannot sync pinned signing key: {error}"))?;
        let home_text = home.to_string_lossy().into_owned();
        let signature_text = signature_path.to_string_lossy().into_owned();
        let key_text = key_path.to_string_lossy().into_owned();
        let (import_status, _, _) = host_bounded_output(
            "/usr/bin/gpg",
            &[
                "--batch",
                "--no-options",
                "--homedir",
                &home_text,
                "--import",
                &key_text,
            ],
            MAX_HELPER_METADATA_BYTES,
            Duration::from_secs(30),
        )?;
        if !import_status.success() {
            return Err("cannot import ClamUI signing key".to_owned());
        }
        let (verify_status, verified_stdout, verified_stderr) = host_bounded_output(
            "/usr/bin/gpg",
            &[
                "--batch",
                "--no-options",
                "--homedir",
                &home_text,
                "--status-fd=2",
                "--decrypt",
                &signature_text,
            ],
            MAX_HELPER_METADATA_BYTES,
            Duration::from_secs(30),
        )?;
        if !verify_status.success() {
            return Err("helper package signature is invalid".to_owned());
        }
        if !String::from_utf8_lossy(&verified_stderr)
            .lines()
            .any(|line| {
                line.starts_with("[GNUPG:] VALIDSIG ")
                    && line.split_whitespace().nth(2) == Some(PINNED_SIGNING_FINGERPRINT)
            })
        {
            return Err("helper package signature uses an unexpected signing key".to_owned());
        }
        signed_members_match(&String::from_utf8_lossy(&verified_stdout), &members)
    })();
    let _ = fs::remove_dir_all(home);
    outcome
}

/// Core binary entry point for `/usr/bin/clamui-apply-preferences`.
/// Exit values preserve the installed Python helper's v4 contract.
pub fn run_helper(args: &[String]) -> i32 {
    let uid = match parse_pkexec_uid() {
        Ok(uid) => uid,
        Err(error) => {
            eprintln!("Error: {error}");
            return 3;
        }
    };
    let Some(protocol) = args.first() else {
        eprintln!("Error: missing --protocol=4");
        return 4;
    };
    if protocol != &format!("--protocol={PROTOCOL_VERSION}") {
        eprintln!("Error: missing --protocol=4");
        return 4;
    }
    let rest = &args[1..];
    let result = match rest.first().map(String::as_str) {
        Some("--read-config") if rest.len() == 2 => read_allowlisted_config(Path::new(&rest[1]))
            .and_then(|content| {
                io::stdout()
                    .write_all(&content)
                    .map_err(|error| format!("cannot write configuration: {error}"))
            }),
        Some("--read-config") => Err("expected exactly one configuration path to read".to_owned()),
        _ => run_config_helper(rest, uid),
    };
    match result {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("Error: {error}");
            if rest.first().map(String::as_str) == Some("--read-config") && rest.len() != 2
                || (rest.first().map(String::as_str) != Some("--read-config")
                    && (rest.is_empty() || !rest.len().is_multiple_of(2)))
            {
                2
            } else {
                1
            }
        }
    }
}

fn installed_version_matches(architecture: &str) -> AppResult<bool> {
    let output = host_command(
        "/usr/bin/dpkg-query",
        &[
            "--show",
            "--showformat=${db:Status-Abbrev}\n${Version}\n${Architecture}\n",
            HELPER_PACKAGE,
        ],
    )?;
    let version = app_version();
    let decoded = String::from_utf8_lossy(&output.stdout);
    let fields: Vec<_> = decoded.lines().collect();
    Ok(output.status.success() && fields == ["ii ", version.as_str(), architecture])
}

fn debian_host() -> bool {
    host_command("/usr/bin/dpkg", &["--version"]).is_ok_and(|output| output.status.success())
}

pub fn status() -> PrivilegedHelperStatus {
    let version = app_version();
    match trusted_helper_path() {
        Ok(_) => match dpkg_architecture().and_then(|arch| installed_version_matches(&arch)) {
            Ok(true) => PrivilegedHelperStatus {
                state: "installed".to_owned(), package_name: HELPER_PACKAGE.to_owned(), version,
                detail: None, installed: true, installable: false, needs_onboarding: false,
            },
            Ok(false) if flatpak() => PrivilegedHelperStatus {
                state: "installable".to_owned(), package_name: HELPER_PACKAGE.to_owned(), version,
                detail: None, installed: false, installable: true, needs_onboarding: true,
            },
            Ok(false) => PrivilegedHelperStatus {
                state: "outdated".to_owned(), package_name: HELPER_PACKAGE.to_owned(), version,
                detail: Some("The host helper package version does not match this ClamUI version.".to_owned()),
                installed: false, installable: false, needs_onboarding: true,
            },
            Err(_) => PrivilegedHelperStatus {
                state: "unsupported".to_owned(), package_name: HELPER_PACKAGE.to_owned(), version,
                detail: Some("The host helper was found, but its installed package version could not be verified.".to_owned()),
                installed: false, installable: false, needs_onboarding: true,
            },
        },
        Err(_) if !flatpak() => PrivilegedHelperStatus {
            state: "not_applicable".to_owned(), package_name: HELPER_PACKAGE.to_owned(), version,
            detail: Some("The privileged helper is only installed automatically for Flatpak ClamUI.".to_owned()),
            installed: false, installable: false, needs_onboarding: false,
        },
        Err(_) if !debian_host() => PrivilegedHelperStatus {
            state: "unsupported".to_owned(), package_name: HELPER_PACKAGE.to_owned(), version,
            detail: Some("Automatic privileged-helper installation is currently supported only on Debian-family hosts.".to_owned()),
            installed: false, installable: false, needs_onboarding: true,
        },
        Err(_) => PrivilegedHelperStatus {
            state: "installable".to_owned(), package_name: HELPER_PACKAGE.to_owned(), version,
            detail: None, installed: false, installable: true, needs_onboarding: true,
        },
    }
}

fn download_bounded(url: &str, destination: &Path, limit: usize) -> AppResult<()> {
    let result = (|| -> AppResult<()> {
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|error| format!("cannot configure helper download: {error}"))?;
        let mut response = client
            .get(url)
            .header(
                reqwest::header::USER_AGENT,
                concat!("ClamUI/", env!("CARGO_PKG_VERSION")),
            )
            .send()
            .and_then(reqwest::blocking::Response::error_for_status)
            .map_err(|error| format!("cannot download helper package: {error}"))?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(O_NOFOLLOW)
            .open(destination)
            .map_err(|error| format!("cannot create download destination: {error}"))?;
        let mut remaining = limit;
        let mut buffer = [0u8; 64 * 1024];
        loop {
            let bytes = response
                .read(&mut buffer)
                .map_err(|error| format!("cannot read helper download: {error}"))?;
            if bytes == 0 {
                break;
            }
            if bytes > remaining {
                return Err("helper download exceeds its verified bound".to_owned());
            }
            file.write_all(&buffer[..bytes])
                .map_err(|error| format!("cannot save helper download: {error}"))?;
            remaining -= bytes;
        }
        file.sync_all()
            .map_err(|error| format!("cannot sync helper download: {error}"))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(destination);
    }
    result
}

fn release_asset() -> AppResult<(u64, String, String)> {
    let release = format!(
        "https://api.github.com/repos/linx-systems/clamui/releases/tags/v{}",
        app_version()
    );
    let directory = unique_directory(&env::temp_dir(), "clamui-release")?;
    let temp = directory.join("release.json");
    let result = (|| -> AppResult<(u64, String, String)> {
        download_bounded(&release, &temp, MAX_HELPER_METADATA_BYTES)?;
        let metadata =
            fs::read(&temp).map_err(|error| format!("cannot read release metadata: {error}"))?;
        let release: Value = serde_json::from_slice(&metadata)
            .map_err(|_| "release metadata is not valid JSON".to_owned())?;
        if release.get("tag_name").and_then(Value::as_str) != Some(&format!("v{}", app_version()))
            || release.get("draft").and_then(Value::as_bool) != Some(false)
            || release.get("prerelease").and_then(Value::as_bool) != Some(false)
            || release
                .get("published_at")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .is_none()
        {
            return Err(
                "release metadata does not describe the exact published version".to_owned(),
            );
        }
        let architecture = dpkg_architecture()?;
        let expected_name = package_name(&architecture);
        let expected_url = format!(
            "https://github.com/linx-systems/clamui/releases/download/v{}/{expected_name}",
            app_version()
        );
        let matches = release
            .get("assets")
            .and_then(Value::as_array)
            .ok_or_else(|| "release metadata has no assets".to_owned())?
            .iter()
            .filter(|asset| {
                asset.get("name").and_then(Value::as_str) == Some(expected_name.as_str())
            })
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err("release metadata has no unique matching helper asset".to_owned());
        }
        let asset = matches[0];
        let size = asset
            .get("size")
            .and_then(Value::as_u64)
            .filter(|size| *size > 0 && *size <= MAX_HELPER_PACKAGE_BYTES)
            .ok_or_else(|| "matching helper asset has invalid size".to_owned())?;
        if asset.get("state").and_then(Value::as_str) != Some("uploaded")
            || asset.get("content_type").and_then(Value::as_str)
                != Some("application/x-debian-package")
            || asset.get("browser_download_url").and_then(Value::as_str)
                != Some(expected_url.as_str())
        {
            return Err("matching helper asset metadata is invalid".to_owned());
        }
        let digest = asset
            .get("digest")
            .and_then(Value::as_str)
            .and_then(|digest| digest.strip_prefix("sha256:"))
            .filter(|digest| hex_digest(digest))
            .ok_or_else(|| "matching helper asset has no SHA-256 digest".to_owned())?
            .to_owned();
        Ok((size, digest, expected_url))
    })();
    let _ = fs::remove_dir_all(directory);
    result
}

fn install_matching_helper() -> AppResult<PrivilegedHelperStatus> {
    let current = status();
    if current.installed {
        return Ok(current);
    }
    if !current.installable {
        return Err(current.detail.unwrap_or_else(|| {
            "the privileged helper cannot be installed automatically here".to_owned()
        }));
    }
    let (size, digest, url) = release_asset()?;
    let uid = current_uid();
    let root = helper_download_root_for_uid(uid)?;
    private_directory(&root, uid)?;
    let directory = unique_directory(&root, "install")?;
    let package = directory.join("helper.deb");
    let result = (|| -> AppResult<PrivilegedHelperStatus> {
        download_bounded(&url, &package, size as usize)?;
        if fs::metadata(&package)
            .map_err(|error| format!("cannot inspect helper package: {error}"))?
            .len()
            != size
            || sha256_file(&package)? != digest
        {
            return Err("downloaded helper package did not pass digest verification".to_owned());
        }
        let architecture = dpkg_architecture()?;
        verify_deb_identity(&package, &architecture)?;
        verify_deb_signature(&package)?;
        // v4 helpers intentionally know only config reads/writes. Every
        // first-install and version-mismatch package upgrade therefore uses
        // the same fixed, authenticated bootstrap rather than inventing an
        // incompatible helper subprotocol.
        let mut command = Command::new("flatpak-spawn");
        command.args([
            "--host",
            "pkexec",
            "/bin/sh",
            "-c",
            FIRST_INSTALL_SCRIPT,
            "clamui-first-install",
        ]);
        command
            .arg(&package)
            .arg(size.to_string())
            .arg(&digest)
            .arg(app_version())
            .arg(&architecture);
        let output = command
            .output()
            .map_err(|error| format!("cannot launch root package installer: {error}"))?;
        if !output.status.success() {
            return Err(helper_failure(
                output.status.code(),
                &output.stderr,
                "installing the privileged helper",
            ));
        }
        let checked = status();
        if !checked.installed {
            return Err("the privileged helper was installed but cannot be verified".to_owned());
        }
        Ok(checked)
    })();
    let _ = fs::remove_dir_all(directory);
    result
}

pub fn dispatch(ctx: &Context, action: &str, _args: Value) -> AppResult<Value> {
    match action {
        "status" => serde_json::to_value(status()).map_err(|error| error.to_string()),
        "install" => {
            let status = install_matching_helper().map_err(|error| {
                format!(
                    "{}: {error}",
                    crate::i18n::translate(
                        ctx,
                        // Translators: "privileged-helper" identifies the ClamUI helper component.
                        "The privileged-helper installation failed. Try again or install it manually.",
                    )
                )
            })?;
            serde_json::to_value(status).map_err(|error| error.to_string())
        }
        _ => Err(format!("unknown privileged action: {action}")),
    }
}

#[cfg(test)]
mod helper_failure_tests {
    use super::*;
    use crate::Paths;
    use tempfile::TempDir;

    struct TestContext {
        context: Context,
        _root: TempDir,
    }

    fn context() -> TestContext {
        let root = TempDir::new().expect("create formatter root");
        let context = Context::with_paths(Paths {
            home: root.path().join("home"),
            config_dir: root.path().join("config/clamui"),
            data_dir: root.path().join("data/clamui"),
        })
        .expect("create formatter context");
        TestContext {
            context,
            _root: root,
        }
    }

    #[test]
    fn helper_failure_formatters_sanitize_and_redact_credentials() {
        let fixture = context();
        let cases = [
            (
                "\u{1b}[31mE: token=untrusted-token diagnostics\u{1b}[0m\r\n\u{202e}",
                Some("untrusted-token"),
                "E: token=[REDACTED_SECRET] diagnostics",
            ),
            (
                "E: Bearer untrusted-bearer diagnostics",
                Some("untrusted-bearer"),
                "E: Bearer [REDACTED_SECRET] diagnostics",
            ),
            (
                "E: Authorization: Bearer untrusted-auth diagnostics",
                Some("untrusted-auth"),
                "E: Authorization: Bearer [REDACTED_SECRET] diagnostics",
            ),
            (
                "E: authorization: Basic untrusted-basic diagnostics",
                Some("untrusted-basic"),
                "E: authorization: Basic [REDACTED_SECRET] diagnostics",
            ),
            ("E: bearer ", None, "E: bearer"),
            ("E: Authorization: ", None, "E: Authorization:"),
        ];

        for (stderr, credential, useful_detail) in cases {
            let helper = helper_failure(Some(100), stderr.as_bytes(), "installing the helper");
            let client = client_helper_failure(
                &fixture.context,
                Some(100),
                stderr.as_bytes(),
                "Applying configuration",
            );
            for formatted in [helper, client] {
                assert!(
                    formatted.contains(useful_detail),
                    "useful diagnostic was lost: {formatted:?}"
                );
                if let Some(credential) = credential {
                    assert!(
                        !formatted.contains(credential),
                        "credential leaked: {formatted:?}"
                    );
                }
                assert!(!formatted.contains('\u{1b}'), "ANSI leaked: {formatted:?}");
                assert!(
                    !formatted.contains('\u{202e}'),
                    "bidi control leaked: {formatted:?}"
                );
            }
        }
    }
}

#[cfg(test)]
mod bounded_output_tests {
    use super::*;

    fn shell(script: &str) -> Command {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", script]);
        command
    }

    #[test]
    fn drains_stderr_while_waiting_for_stdout() {
        let started = Instant::now();
        let result = bounded_child_output(
            shell("dd if=/dev/zero bs=1024 count=256 1>&2; printf done"),
            1024,
            Duration::from_secs(2),
        );

        assert!(result.is_ok(), "{result:?}");
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn terminates_and_reaps_stdout_overflow() {
        let started = Instant::now();
        let result = bounded_child_output(
            shell("dd if=/dev/zero bs=1024 count=2 2>/dev/null"),
            1024,
            Duration::from_secs(2),
        );

        assert!(matches!(result, Err(error) if error.contains("exceeds")));
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn terminates_and_reaps_stalled_child_at_deadline() {
        let started = Instant::now();
        let result = bounded_child_output(shell("sleep 5"), 1024, Duration::from_millis(100));

        assert!(matches!(result, Err(error) if error.contains("deadline")));
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn enforces_deadline_after_both_output_streams_close() {
        let started = Instant::now();
        let result = bounded_child_output(
            shell("exec >/dev/null 2>&1; sleep 5"),
            1024,
            Duration::from_millis(100),
        );

        assert!(matches!(result, Err(error) if error.contains("deadline")));
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn returns_after_deadline_when_an_escaped_silent_writer_keeps_pipes_open() {
        let pid_file = format!(
            "/tmp/clamui-bounded-output-escaped-{}-{}.pid",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        );
        let script = format!(
            "/usr/bin/setsid /bin/sh -c 'echo $$ > {pid_file}; sleep 5' & exec >/dev/null 2>&1; sleep 5"
        );
        let started = Instant::now();
        let result = bounded_child_output(shell(&script), 1024, Duration::from_millis(100));

        let mut escaped_pid = None;
        for _ in 0..100 {
            if let Ok(pid) = std::fs::read_to_string(&pid_file) {
                let pid = pid.trim().to_owned();
                if !pid.is_empty() {
                    escaped_pid = Some(pid);
                    break;
                }
            }
            thread::sleep(Duration::from_millis(10));
        }
        if let Some(pid) = &escaped_pid {
            let _ = Command::new("/bin/kill").args(["-KILL", pid]).status();
        }
        let _ = std::fs::remove_file(&pid_file);

        assert!(escaped_pid.is_some(), "escaped pipe writer did not start");
        assert!(matches!(result, Err(error) if error.contains("deadline")));
        assert!(started.elapsed() < Duration::from_secs(2));
    }
}
