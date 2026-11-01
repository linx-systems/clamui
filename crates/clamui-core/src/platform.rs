use std::{
    collections::{HashMap, HashSet, VecDeque},
    ffi::{CStr, CString},
    fs,
    io::{self, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::ffi::OsStrExt,
    },
    path::{Component, Path, PathBuf},
    process::Stdio,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

use gio::prelude::*;
use serde::Serialize;
use serde_json::{json, Value};

use crate::{
    common::{host_command, is_flatpak, Context},
    AppResult,
};

const MAX_CONCURRENT_SCANS: usize = 2;
const RECENTLY_SCANNED_TTL: Duration = Duration::from_secs(60);
const RETRY_DELAY: Duration = Duration::from_secs(10);

const NEMO_SCAN: &[u8] =
    include_bytes!("../assets/integrations/io.github.linx_systems.ClamUI.nemo_action");
const NEMO_VIRUSTOTAL: &[u8] =
    include_bytes!("../assets/integrations/io.github.linx_systems.ClamUI-virustotal.nemo_action");
const NAUTILUS_SCAN: &[u8] = include_bytes!("../assets/integrations/clamui-scan-nautilus.sh");
const NAUTILUS_VIRUSTOTAL: &[u8] =
    include_bytes!("../assets/integrations/clamui-virustotal-nautilus.sh");
const DOLPHIN_SCAN: &[u8] =
    include_bytes!("../assets/integrations/io.github.linx_systems.ClamUI.service.desktop");
const DOLPHIN_VIRUSTOTAL: &[u8] =
    include_bytes!("../assets/integrations/io.github.linx_systems.ClamUI-virustotal.desktop");

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceType {
    Removable,
    External,
    Network,
    Internal,
    Unknown,
}

#[derive(Clone, Debug, Serialize)]
pub struct MountInfo {
    pub mount_point: String,
    pub device_name: String,
    pub device_type: DeviceType,
    pub volume_uuid: String,
    pub size_bytes: u64,
}

/// Returns the exact scanner job identity for one mount-generation. A UUID is
/// descriptive only; the mount path and generation prevent cloned media from
/// colliding even when a filesystem UUID is duplicated.
pub fn device_job_id(info: &MountInfo, generation: u64) -> String {
    let escape = |value: &str| {
        value
            .bytes()
            .map(|byte| match byte {
                b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'-' | b'_' | b'.' => {
                    (byte as char).to_string()
                }
                _ => format!("_{byte:02x}"),
            })
            .collect::<String>()
    };
    let identity = if info.volume_uuid.is_empty() {
        "no-uuid".to_owned()
    } else {
        escape(&info.volume_uuid)
    };
    format!(
        "device:{identity}:{}:{generation}",
        escape(&info.mount_point)
    )
}

/// A snapshot of the persisted device-monitor preferences. Keeping the
/// decision separate from Gio callbacks makes filtering deterministic and
/// prevents unknown filesystem sizes from being mistaken for zero-sized media.
#[derive(Clone, Debug)]
pub struct DeviceScanPolicy {
    pub enabled: bool,
    pub allowed_types: Vec<DeviceType>,
    pub max_size_gb: u64,
    pub skip_on_battery: bool,
    pub on_battery: bool,
}

impl DeviceScanPolicy {
    pub fn permits(&self, info: &MountInfo) -> bool {
        self.enabled
            && self.allowed_types.contains(&info.device_type)
            && (self.max_size_gb == 0
                || info.size_bytes == 0
                || info.size_bytes <= self.max_size_gb.saturating_mul(1024 * 1024 * 1024))
            && !(self.skip_on_battery && self.on_battery)
    }
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FileManager {
    Nemo,
    Nautilus,
    Dolphin,
}

impl FileManager {
    fn parse(value: &str) -> AppResult<Self> {
        match value {
            "nemo" => Ok(Self::Nemo),
            "nautilus" => Ok(Self::Nautilus),
            "dolphin" => Ok(Self::Dolphin),
            _ => Err(format!("Unknown file manager: {value}")),
        }
    }

    fn id(self) -> &'static str {
        match self {
            Self::Nemo => "nemo",
            Self::Nautilus => "nautilus",
            Self::Dolphin => "dolphin",
        }
    }

    fn display_name(self) -> &'static str {
        match self {
            Self::Nemo => "Nemo",
            Self::Nautilus => "Nautilus",
            Self::Dolphin => "Dolphin",
        }
    }

    fn description(self) -> &'static str {
        match self {
            Self::Nemo => "Linux Mint / Cinnamon file manager",
            Self::Nautilus => "GNOME Files",
            Self::Dolphin => "KDE file manager",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum IntegrationStatus {
    NotInstalled,
    Partial,
    Installed,
}

impl IntegrationStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::NotInstalled => "not_installed",
            Self::Partial => "partial",
            Self::Installed => "installed",
        }
    }
}

#[derive(Clone, Copy)]
struct IntegrationAsset {
    source: &'static str,
    destination: &'static str,
    bytes: &'static [u8],
    executable: bool,
}

const NEMO_ASSETS: &[IntegrationAsset] = &[
    IntegrationAsset {
        source: "io.github.linx_systems.ClamUI.nemo_action",
        destination: "nemo/actions/io.github.linx_systems.ClamUI.nemo_action",
        bytes: NEMO_SCAN,
        executable: false,
    },
    IntegrationAsset {
        source: "io.github.linx_systems.ClamUI-virustotal.nemo_action",
        destination: "nemo/actions/io.github.linx_systems.ClamUI-virustotal.nemo_action",
        bytes: NEMO_VIRUSTOTAL,
        executable: false,
    },
];
const NAUTILUS_ASSETS: &[IntegrationAsset] = &[
    IntegrationAsset {
        source: "clamui-scan-nautilus.sh",
        destination: "nautilus/scripts/Scan with ClamUI",
        bytes: NAUTILUS_SCAN,
        executable: true,
    },
    IntegrationAsset {
        source: "clamui-virustotal-nautilus.sh",
        destination: "nautilus/scripts/Scan with VirusTotal",
        bytes: NAUTILUS_VIRUSTOTAL,
        executable: true,
    },
];
const DOLPHIN_MODERN_ASSETS: &[IntegrationAsset] = &[
    IntegrationAsset {
        source: "io.github.linx_systems.ClamUI.service.desktop",
        destination: "kio/servicemenus/io.github.linx_systems.ClamUI.service.desktop",
        bytes: DOLPHIN_SCAN,
        executable: true,
    },
    IntegrationAsset {
        source: "io.github.linx_systems.ClamUI-virustotal.desktop",
        destination: "kio/servicemenus/io.github.linx_systems.ClamUI-virustotal.desktop",
        bytes: DOLPHIN_VIRUSTOTAL,
        executable: true,
    },
];
const DOLPHIN_LEGACY_ASSETS: &[IntegrationAsset] = &[
    IntegrationAsset {
        source: "io.github.linx_systems.ClamUI.service.desktop",
        destination: "kservices5/ServiceMenus/io.github.linx_systems.ClamUI.service.desktop",
        bytes: DOLPHIN_SCAN,
        executable: true,
    },
    IntegrationAsset {
        source: "io.github.linx_systems.ClamUI-virustotal.desktop",
        destination: "kservices5/ServiceMenus/io.github.linx_systems.ClamUI-virustotal.desktop",
        bytes: DOLPHIN_VIRUSTOTAL,
        executable: true,
    },
];

/// Runtime paths are injectable so the copy/repair/remove behavior is deterministic in tests.
#[derive(Clone, Debug)]
pub struct IntegrationPaths {
    pub local_share: PathBuf,
    pub flatpak: bool,
    pub kde_session_version: Option<String>,
}

impl IntegrationPaths {
    pub fn from_context(ctx: &Context) -> Self {
        let flatpak = is_flatpak();
        let local_share = if flatpak {
            ctx.paths.home.join(".local/share")
        } else if let Some(path) = std::env::var_os("XDG_DATA_HOME") {
            PathBuf::from(path)
        } else {
            ctx.paths.home.join(".local/share")
        };
        Self {
            local_share,
            flatpak,
            kde_session_version: std::env::var("KDE_SESSION_VERSION").ok(),
        }
    }

    fn dolphin_assets(&self) -> &'static [IntegrationAsset] {
        match self.dolphin_parent() {
            "kservices5" => DOLPHIN_LEGACY_ASSETS,
            _ => DOLPHIN_MODERN_ASSETS,
        }
    }

    fn dolphin_legacy_assets(&self) -> &'static [IntegrationAsset] {
        match self.dolphin_parent() {
            "kservices5" => DOLPHIN_MODERN_ASSETS,
            _ => DOLPHIN_LEGACY_ASSETS,
        }
    }

    fn dolphin_parent(&self) -> &'static str {
        match self.kde_session_version.as_deref() {
            Some("5") => "kservices5",
            Some("6") => "kio",
            _ if self.local_share.join("kio").is_dir() => "kio",
            _ if self.local_share.join("kservices5").is_dir() => "kservices5",
            _ => "kio",
        }
    }

    fn assets(&self, manager: FileManager) -> &'static [IntegrationAsset] {
        match manager {
            FileManager::Nemo => NEMO_ASSETS,
            FileManager::Nautilus => NAUTILUS_ASSETS,
            FileManager::Dolphin => self.dolphin_assets(),
        }
    }
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "system_info" => Ok(system_info()),
        "integrations_status" => Ok(integrations_status(ctx)),
        "integrations_install" => install_dispatch(ctx, args),
        "integrations_remove" => remove_dispatch(ctx, args),
        "mounts" => Ok(json!({ "mounts": current_mounts() })),
        _ => Err(format!("Unknown platform action: {action}")),
    }
}

fn system_info() -> Value {
    let flatpak = is_flatpak();
    let executable = std::env::current_exe().ok();
    let installation_type = if flatpak {
        "Flatpak".to_owned()
    } else if std::env::var_os("APPIMAGE").is_some() {
        "AppImage".to_owned()
    } else if executable
        .as_ref()
        .is_some_and(|path| path.components().any(|part| part.as_os_str() == "target"))
    {
        "Development (source)".to_owned()
    } else if package_owns_executable("dpkg", "-S", executable.as_deref()) {
        "Debian/Ubuntu Package".to_owned()
    } else if package_owns_executable("rpm", "-qf", executable.as_deref()) {
        "RPM Package".to_owned()
    } else {
        "Native".to_owned()
    };

    json!({
        "installation_type": installation_type,
        "distribution": distro_info(),
        "desktop_environment": desktop_environment(),
        "platform": platform_info(),
        "architecture": std::env::consts::ARCH,
        "is_flatpak": flatpak,
        "app_version": env!("CARGO_PKG_VERSION"),
        "rust_runtime": rust_runtime(),
        "tauri_runtime": std::env::var("CLAMUI_TAURI_VERSION").ok(),
    })
}

fn package_owns_executable(program: &str, flag: &str, executable: Option<&Path>) -> bool {
    let Some(executable) = executable else {
        return false;
    };
    let args = vec![flag.to_owned(), executable.display().to_string()];
    host_command(program, &args)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|status| status.success())
}

fn distro_info() -> String {
    let Ok(contents) = fs::read_to_string("/etc/os-release") else {
        return platform_info();
    };
    let fields = contents
        .lines()
        .filter_map(|line| line.split_once('='))
        .map(|(key, value)| (key, value.trim_matches('"')))
        .collect::<HashMap<_, _>>();
    fields
        .get("PRETTY_NAME")
        .map(|name| (*name).to_owned())
        .or_else(|| {
            fields.get("NAME").map(|name| {
                let version = fields
                    .get("VERSION")
                    .or_else(|| fields.get("VERSION_ID"))
                    .copied()
                    .unwrap_or_default();
                format!("{name} {version}").trim().to_owned()
            })
        })
        .unwrap_or_else(platform_info)
}

fn desktop_environment() -> String {
    for name in [
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_DESKTOP",
        "DESKTOP_SESSION",
    ] {
        if let Some(value) = std::env::var_os(name).filter(|value| !value.is_empty()) {
            return value.to_string_lossy().into_owned();
        }
    }
    if std::env::var_os("GNOME_DESKTOP_SESSION_ID").is_some() {
        return "GNOME".to_owned();
    }
    if std::env::var_os("KDE_FULL_SESSION").is_some() {
        return "KDE".to_owned();
    }
    "Unknown".to_owned()
}

fn platform_info() -> String {
    let args = vec!["-srvmo".to_owned()];
    host_command("uname", &args)
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_owned())
        .filter(|output| !output.is_empty())
        .unwrap_or_else(|| format!("{} {}", std::env::consts::OS, std::env::consts::ARCH))
}

fn rust_runtime() -> String {
    let args = vec!["--version".to_owned()];
    host_command("rustc", &args)
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_owned())
        .filter(|output| !output.is_empty())
        .unwrap_or_else(|| "Rust compiler unavailable at runtime".to_owned())
}

fn integrations_status(ctx: &Context) -> Value {
    let paths = IntegrationPaths::from_context(ctx);
    if !paths.flatpak {
        return json!({ "integrations": [] });
    }
    let integrations = [
        FileManager::Nemo,
        FileManager::Nautilus,
        FileManager::Dolphin,
    ]
    .into_iter()
    .map(|manager| integration_info(&paths, manager))
    .collect::<Vec<_>>();
    json!({ "integrations": integrations })
}

fn integration_info(paths: &IntegrationPaths, manager: FileManager) -> Value {
    let assets = paths.assets(manager);
    let (status, missing) = integration_status(paths, manager);
    json!({
        "file_manager": manager.id(),
        "display_name": manager.display_name(),
        "description": manager.description(),
        "source_files": assets.iter().map(|asset| json!({
            "source": asset.source,
            "destination": asset.destination,
        })).collect::<Vec<_>>(),
        "status": status.as_str(),
        "is_available": integration_available(paths, manager),
        "missing_files": missing,
    })
}
fn install_dispatch(ctx: &Context, args: Value) -> AppResult<Value> {
    let manager = manager_arg(&args)?;
    let paths = IntegrationPaths::from_context(ctx);
    if !paths.flatpak {
        return Err(crate::i18n::translate(ctx, "Not running as Flatpak"));
    }
    let repair = args.get("repair").and_then(Value::as_bool).unwrap_or(false);
    install_integration(&paths, manager, repair)
        .map_err(|error| localize_integration_error(ctx, error))?;
    let (status, _) = integration_status(&paths, manager);
    Ok(json!({
        "success": true,
        "file_manager": manager.id(),
        "status": status.as_str(),
    }))
}

fn remove_dispatch(ctx: &Context, args: Value) -> AppResult<Value> {
    let manager = manager_arg(&args)?;
    let paths = IntegrationPaths::from_context(ctx);
    remove_integration(&paths, manager).map_err(|error| localize_integration_error(ctx, error))?;
    let (status, _) = integration_status(&paths, manager);
    Ok(json!({
        "success": true,
        "file_manager": manager.id(),
        "status": status.as_str(),
    }))
}

fn manager_arg(args: &Value) -> AppResult<FileManager> {
    args.get("file_manager")
        .and_then(Value::as_str)
        .ok_or_else(|| "file_manager is required".to_owned())
        .and_then(FileManager::parse)
}

fn localize_integration_error(ctx: &Context, error: String) -> String {
    for (prefix, template) in [
        (
            "Invalid integration destination: ",
            "Invalid integration destination: {path}",
        ),
        (
            "Integration destination escapes ",
            "Integration destination escapes {path}",
        ),
        (
            "Integration destination contains a symlink: ",
            "Integration destination contains a symlink: {path}",
        ),
    ] {
        if let Some(path) = error.strip_prefix(prefix) {
            return localize_template(ctx, template, &[("path", path)]);
        }
    }
    for (prefix, template) in [
        ("Failed to create ", "Failed to create {path}: {error}"),
        ("Failed to write ", "Failed to write {path}: {error}"),
        ("Failed to inspect ", "Failed to inspect {path}: {error}"),
        (
            "Failed to set permissions on ",
            "Failed to set permissions on {path}: {error}",
        ),
        ("Failed to remove ", "Failed to remove {path}: {error}"),
    ] {
        if let Some(details) = error.strip_prefix(prefix) {
            if let Some((path, diagnostic)) = details.rsplit_once(": ") {
                return localize_template(ctx, template, &[("path", path), ("error", diagnostic)]);
            }
        }
    }
    error
}

fn localize_template(ctx: &Context, template: &str, replacements: &[(&str, &str)]) -> String {
    let mut translated = crate::i18n::translate(ctx, template);
    for (name, value) in replacements {
        translated = translated.replace(&format!("{{{name}}}"), value);
    }
    translated
}

fn integration_available(paths: &IntegrationPaths, manager: FileManager) -> bool {
    let directory = match manager {
        FileManager::Nemo => paths.local_share.join("nemo"),
        FileManager::Nautilus => paths.local_share.join("nautilus"),
        FileManager::Dolphin => paths.local_share.join(paths.dolphin_parent()),
    };
    directory.exists()
        || directory
            .parent()
            .is_some_and(|parent| parent.is_dir() && is_writable_directory(parent))
}

/// Inspect an explicit integration root. This is used by packaging checks and
/// keeps install/repair/remove behavior independently testable from a Flatpak.
pub fn integration_status_at(paths: &IntegrationPaths, file_manager: &str) -> AppResult<Value> {
    let manager = FileManager::parse(file_manager)?;
    Ok(integration_info(paths, manager))
}

/// Copy the embedded, version-matched integration files into an explicit root.
/// Callers that expose this to users must still require Flatpak mode.
pub fn install_integration_at(
    paths: &IntegrationPaths,
    file_manager: &str,
    repair: bool,
) -> AppResult<()> {
    install_integration(paths, FileManager::parse(file_manager)?, repair)
}

/// Remove integration files from an explicit root, including stale Dolphin
/// entries in the alternate KDE service-menu directory.
pub fn remove_integration_at(paths: &IntegrationPaths, file_manager: &str) -> AppResult<()> {
    remove_integration(paths, FileManager::parse(file_manager)?)
}

fn is_writable_directory(path: &Path) -> bool {
    fs::metadata(path)
        .map(|metadata| metadata.is_dir() && !metadata.permissions().readonly())
        .unwrap_or(false)
}

fn integration_status(
    paths: &IntegrationPaths,
    manager: FileManager,
) -> (IntegrationStatus, Vec<String>) {
    let assets = paths.assets(manager);
    let mut missing = assets
        .iter()
        .filter(|asset| !paths.local_share.join(asset.destination).is_file())
        .map(|asset| asset.destination.to_owned())
        .collect::<Vec<_>>();

    if manager == FileManager::Dolphin && missing.len() == assets.len() {
        let legacy = paths.dolphin_legacy_assets();
        if legacy
            .iter()
            .any(|asset| paths.local_share.join(asset.destination).is_file())
        {
            missing = assets
                .iter()
                .map(|asset| asset.destination.to_owned())
                .collect();
            return (IntegrationStatus::Partial, missing);
        }
    }

    match missing.len() {
        0 => (IntegrationStatus::Installed, missing),
        count if count == assets.len() => (IntegrationStatus::NotInstalled, missing),
        _ => (IntegrationStatus::Partial, missing),
    }
}

fn install_integration(
    paths: &IntegrationPaths,
    manager: FileManager,
    repair: bool,
) -> AppResult<()> {
    let (status, missing) = integration_status(paths, manager);
    if repair && status == IntegrationStatus::Installed {
        return Ok(());
    }
    let missing = missing.into_iter().collect::<HashSet<_>>();
    for asset in paths.assets(manager) {
        if repair && status == IntegrationStatus::Partial && !missing.contains(asset.destination) {
            continue;
        }
        write_asset(paths, asset)?;
    }
    if manager == FileManager::Dolphin {
        remove_assets(paths, paths.dolphin_legacy_assets())?;
        refresh_dolphin_cache();
    }
    Ok(())
}

fn remove_integration(paths: &IntegrationPaths, manager: FileManager) -> AppResult<()> {
    remove_assets(paths, paths.assets(manager))?;
    if manager == FileManager::Dolphin {
        remove_assets(paths, paths.dolphin_legacy_assets())?;
        refresh_dolphin_cache();
    }
    Ok(())
}

fn write_asset(paths: &IntegrationPaths, asset: &IntegrationAsset) -> AppResult<()> {
    let destination = paths.local_share.join(asset.destination);
    let (parent, leaf) = open_integration_parent(paths, asset.destination, true)
        .map_err(|error| format!("Failed to create {}: {error}", destination.display()))?;
    let mut output = open_at(
        parent.as_raw_fd(),
        &leaf,
        libc::O_WRONLY | libc::O_CREAT | libc::O_TRUNC | libc::O_NOFOLLOW,
        0o644,
    )
    .map_err(|error| format!("Failed to create {}: {error}", destination.display()))?;
    output
        .write_all(asset.bytes)
        .and_then(|()| output.sync_all())
        .map_err(|error| format!("Failed to write {}: {error}", destination.display()))?;
    if asset.executable {
        fchmod(output.as_raw_fd(), 0o755).map_err(|error| {
            format!(
                "Failed to set permissions on {}: {error}",
                destination.display()
            )
        })?;
    }
    Ok(())
}

fn open_integration_parent(
    paths: &IntegrationPaths,
    relative: &str,
    create: bool,
) -> io::Result<(fs::File, CString)> {
    let mut directory = open_root_directory(&paths.local_share, create)?;
    let components = Path::new(relative)
        .components()
        .map(|component| match component {
            Component::Normal(component) => Ok(component),
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "integration destination is not a normalized relative path",
            )),
        })
        .collect::<io::Result<Vec<_>>>()?;
    let (leaf, parents) = components.split_last().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "integration destination has no file name",
        )
    })?;
    for component in parents {
        let component = CString::new(component.as_bytes()).map_err(|_| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "integration path contains a NUL byte",
            )
        })?;
        directory = open_or_create_directory(directory.as_raw_fd(), &component, create)?;
    }
    let leaf = CString::new(leaf.as_bytes()).map_err(|_| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "integration path contains a NUL byte",
        )
    })?;
    Ok((directory, leaf))
}

fn open_root_directory(root: &Path, create: bool) -> io::Result<fs::File> {
    if !root.is_absolute() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "integration root must be absolute",
        ));
    }
    let mut directory = open_path(
        Path::new("/"),
        libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW,
        0,
    )?;
    for component in root.components() {
        let Component::Normal(component) = component else {
            continue;
        };
        let component = CString::new(component.as_bytes()).map_err(|_| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "integration root contains a NUL byte",
            )
        })?;
        directory = open_or_create_directory(directory.as_raw_fd(), &component, create)?;
    }
    Ok(directory)
}

fn open_or_create_directory(
    parent_fd: libc::c_int,
    name: &CStr,
    create: bool,
) -> io::Result<fs::File> {
    match open_at(
        parent_fd,
        name,
        libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW,
        0,
    ) {
        Ok(directory) => Ok(directory),
        Err(error) if create && error.kind() == io::ErrorKind::NotFound => {
            if unsafe { libc::mkdirat(parent_fd, name.as_ptr(), 0o755) } != 0 {
                let error = io::Error::last_os_error();
                if error.kind() != io::ErrorKind::AlreadyExists {
                    return Err(error);
                }
            }
            open_at(
                parent_fd,
                name,
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW,
                0,
            )
        }
        Err(error) => Err(error),
    }
}

fn open_path(path: &Path, flags: libc::c_int, mode: u32) -> io::Result<fs::File> {
    let path = CString::new(path.as_os_str().as_bytes())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "path contains a NUL byte"))?;
    let fd = unsafe { libc::open(path.as_ptr(), flags, mode as libc::mode_t) };
    if fd < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(unsafe { fs::File::from_raw_fd(fd) })
    }
}

fn open_at(
    parent_fd: libc::c_int,
    name: &CStr,
    flags: libc::c_int,
    mode: u32,
) -> io::Result<fs::File> {
    let fd = unsafe { libc::openat(parent_fd, name.as_ptr(), flags, mode as libc::mode_t) };
    if fd < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(unsafe { fs::File::from_raw_fd(fd) })
    }
}

fn fchmod(fd: libc::c_int, mode: u32) -> io::Result<()> {
    if unsafe { libc::fchmod(fd, mode as libc::mode_t) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

fn remove_assets(paths: &IntegrationPaths, assets: &[IntegrationAsset]) -> AppResult<()> {
    for asset in assets {
        let destination = paths.local_share.join(asset.destination);
        let (parent, leaf) = match open_integration_parent(paths, asset.destination, false) {
            Ok(parts) => parts,
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => {
                return Err(format!(
                    "Failed to remove {}: {error}",
                    destination.display()
                ))
            }
        };
        if unsafe { libc::unlinkat(parent.as_raw_fd(), leaf.as_ptr(), 0) } != 0 {
            let error = io::Error::last_os_error();
            if error.kind() != io::ErrorKind::NotFound {
                return Err(format!(
                    "Failed to remove {}: {error}",
                    destination.display()
                ));
            }
        }
    }
    Ok(())
}

fn refresh_dolphin_cache() {
    for program in ["kbuildsycoca6", "kbuildsycoca5"] {
        let args = vec!["--noincremental".to_owned()];
        let Ok(mut child) = host_command(program, &args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
        else {
            continue;
        };
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            match child.try_wait() {
                Ok(Some(status)) if status.success() => return,
                Ok(Some(_)) => break,
                Err(_) => break,
                Ok(None) if Instant::now() >= deadline => {
                    let _ = child.kill();
                    let _ = child.wait();
                    break;
                }
                Ok(None) => thread::sleep(Duration::from_millis(100)),
            }
        }
    }
}

fn current_mounts() -> Vec<MountInfo> {
    gio::VolumeMonitor::get()
        .mounts()
        .into_iter()
        .map(|mount| mount_info(&mount))
        .collect()
}

fn mount_info(mount: &gio::Mount) -> MountInfo {
    let volume = mount.volume();
    let device_type = classify_mount(mount);
    let root = mount.root();
    let mount_point = root
        .path()
        .map(|path| path.to_string_lossy().into_owned())
        .unwrap_or_default();
    let volume_uuid = volume
        .as_ref()
        .and_then(|volume| volume.uuid())
        .map(|uuid| uuid.to_string())
        .unwrap_or_default();
    let size_bytes = root
        .query_filesystem_info(
            gio::FILE_ATTRIBUTE_FILESYSTEM_SIZE,
            None::<&gio::Cancellable>,
        )
        .ok()
        .map(|info| info.attribute_uint64(gio::FILE_ATTRIBUTE_FILESYSTEM_SIZE))
        .unwrap_or_default();
    MountInfo {
        mount_point,
        device_name: mount.name().to_string(),
        device_type,
        volume_uuid,
        size_bytes,
    }
}

fn classify_mount(mount: &gio::Mount) -> DeviceType {
    let Some(volume) = mount.volume() else {
        return DeviceType::Network;
    };
    let Some(drive) = volume.drive() else {
        return DeviceType::Network;
    };
    if drive.is_removable() || drive.is_media_removable() {
        DeviceType::Removable
    } else if drive.can_eject() {
        DeviceType::External
    } else {
        DeviceType::Internal
    }
}

#[derive(Clone)]
struct ScanEntry {
    info: MountInfo,
    job_id: String,
    cancelled: Arc<AtomicBool>,
}

#[derive(Default)]
struct MonitorState {
    active: HashMap<String, ScanEntry>,
    queued: VecDeque<ScanEntry>,
    delayed: HashMap<String, Arc<AtomicBool>>,
    recent: HashMap<String, Instant>,
}

struct MonitorShared {
    ctx: Context,
    state: Mutex<MonitorState>,
    stopped: AtomicBool,
    generation: AtomicU64,
    workers: Mutex<Vec<JoinHandle<()>>>,
}

impl MonitorShared {
    fn new_entry(&self, info: MountInfo) -> ScanEntry {
        let generation = self.generation.fetch_add(1, Ordering::Relaxed);
        ScanEntry {
            job_id: device_job_id(&info, generation),
            info,
            cancelled: Arc::new(AtomicBool::new(false)),
        }
    }
    fn spawn_worker(self: &Arc<Self>, task: impl FnOnce(Arc<Self>) + Send + 'static) {
        let mut workers = self.workers.lock().expect("monitor workers poisoned");
        if self.stopped.load(Ordering::Acquire) {
            return;
        }
        let shared = Arc::clone(self);
        workers.push(thread::spawn(move || task(shared)));
    }

    fn join_workers(&self) {
        let workers = std::mem::take(&mut *self.workers.lock().expect("monitor workers poisoned"));
        for worker in workers {
            let _ = worker.join();
        }
    }

    fn on_added(self: &Arc<Self>, mount: gio::Mount) {
        let info = mount_info(&mount);
        self.ctx.emit("device-added", mount_event(&info));
        if info.mount_point.is_empty() || !self.should_scan(&info) {
            return;
        }
        self.schedule(info, self.delay());
    }

    fn on_removed(self: &Arc<Self>, mount: gio::Mount) {
        let info = mount_info(&mount);
        if info.mount_point.is_empty() {
            return;
        }
        let mut cancel_id = None;
        {
            let mut state = self.state.lock().expect("monitor state poisoned");
            if let Some(delayed) = state.delayed.remove(&info.mount_point) {
                delayed.store(true, Ordering::Release);
            }
            state
                .queued
                .retain(|entry| entry.info.mount_point != info.mount_point);
            if let Some(active) = state.active.remove(&info.mount_point) {
                active.cancelled.store(true, Ordering::Release);
                cancel_id = Some(active.job_id);
            }
        }
        if let Some(id) = cancel_id {
            let _ = crate::scanner::dispatch(&self.ctx, "cancel", json!({ "id": id }));
            self.ctx.emit(
                "device-scan-cancelled",
                json!({ "mount_point": info.mount_point }),
            );
        }
        self.ctx.emit("device-removed", mount_event(&info));
    }

    fn policy_permits(&self, info: &MountInfo) -> bool {
        let Ok(settings) = self.ctx.settings() else {
            return false;
        };
        let allowed_types = settings
            .get("device_auto_scan_types")
            .and_then(Value::as_array)
            .map(|types| {
                types
                    .iter()
                    .filter_map(Value::as_str)
                    .filter_map(device_type_from_name)
                    .collect()
            })
            .unwrap_or_else(|| vec![DeviceType::Removable, DeviceType::External]);
        DeviceScanPolicy {
            enabled: setting_bool(&settings, "device_auto_scan_enabled", false),
            allowed_types,
            max_size_gb: settings
                .get("device_auto_scan_max_size_gb")
                .and_then(Value::as_u64)
                .unwrap_or(32),
            skip_on_battery: setting_bool(&settings, "device_auto_scan_skip_on_battery", true),
            on_battery: crate::host::on_battery(),
        }
        .permits(info)
    }

    fn should_scan(&self, info: &MountInfo) -> bool {
        if !self.policy_permits(info) {
            return false;
        }
        let mut state = self.state.lock().expect("monitor state poisoned");
        state
            .recent
            .retain(|_, when| when.elapsed() <= RECENTLY_SCANNED_TTL);
        !state.recent.contains_key(&info.mount_point)
            && !state.active.contains_key(&info.mount_point)
            && !state
                .queued
                .iter()
                .any(|entry| entry.info.mount_point == info.mount_point)
            && !state.delayed.contains_key(&info.mount_point)
    }

    fn delay(&self) -> Duration {
        self.ctx
            .settings()
            .ok()
            .and_then(|settings| {
                settings
                    .get("device_auto_scan_delay_seconds")
                    .and_then(Value::as_u64)
            })
            .map(Duration::from_secs)
            .unwrap_or_else(|| Duration::from_secs(3))
    }

    fn device_notifications_enabled(&self) -> bool {
        self.ctx.settings().ok().is_some_and(|settings| {
            setting_bool(&settings, "notifications_enabled", true)
                && setting_bool(&settings, "device_auto_scan_notify", true)
        })
    }

    fn schedule(self: &Arc<Self>, info: MountInfo, delay: Duration) {
        if self.stopped.load(Ordering::Acquire) {
            return;
        }
        let cancelled = Arc::new(AtomicBool::new(false));
        {
            let mut state = self.state.lock().expect("monitor state poisoned");
            if state.delayed.contains_key(&info.mount_point)
                || state.active.contains_key(&info.mount_point)
                || state
                    .queued
                    .iter()
                    .any(|entry| entry.info.mount_point == info.mount_point)
            {
                return;
            }
            state
                .delayed
                .insert(info.mount_point.clone(), cancelled.clone());
        }
        self.spawn_worker(move |shared| {
            thread::sleep(delay);
            if cancelled.load(Ordering::Acquire) || shared.stopped.load(Ordering::Acquire) {
                return;
            }
            {
                let mut state = shared.state.lock().expect("monitor state poisoned");
                state.delayed.remove(&info.mount_point);
            }
            shared.start_or_queue(shared.new_entry(info));
        });
    }

    fn start_or_queue(self: &Arc<Self>, entry: ScanEntry) {
        if self.stopped.load(Ordering::Acquire) || !self.policy_permits(&entry.info) {
            return;
        }
        let mount_point = entry.info.mount_point.clone();
        let run_now = {
            let mut state = self.state.lock().expect("monitor state poisoned");
            if let Some(delayed) = state.delayed.remove(&mount_point) {
                delayed.store(true, Ordering::Release);
            }
            if state.active.contains_key(&mount_point) {
                return;
            }
            if state.active.len() >= MAX_CONCURRENT_SCANS {
                if !state
                    .queued
                    .iter()
                    .any(|queued| queued.info.mount_point == mount_point)
                {
                    state.queued.push_back(entry.clone());
                }
                false
            } else {
                state.active.insert(mount_point, entry.clone());
                true
            }
        };
        if run_now {
            self.run_scan(entry);
        } else {
            self.schedule_retry(entry);
        }
    }

    fn schedule_retry(self: &Arc<Self>, entry: ScanEntry) {
        let mount_point = entry.info.mount_point.clone();
        let cancelled = Arc::new(AtomicBool::new(false));
        {
            let mut state = self.state.lock().expect("monitor state poisoned");
            if state.delayed.contains_key(&mount_point) {
                return;
            }
            state.delayed.insert(mount_point.clone(), cancelled.clone());
        }
        self.spawn_worker(move |shared| {
            thread::sleep(RETRY_DELAY);
            if cancelled.load(Ordering::Acquire) || shared.stopped.load(Ordering::Acquire) {
                return;
            }
            let queued = {
                let mut state = shared.state.lock().expect("monitor state poisoned");
                state.delayed.remove(&mount_point);
                let index = state
                    .queued
                    .iter()
                    .position(|queued| queued.info.mount_point == mount_point);
                index.and_then(|index| state.queued.remove(index))
            };
            if let Some(queued) = queued {
                shared.start_or_queue(queued);
            }
        });
    }
    fn run_scan(self: &Arc<Self>, entry: ScanEntry) {
        self.spawn_worker(move |shared| {
            let id = entry.job_id.clone();
            let notifications_enabled = shared.device_notifications_enabled();
            shared.ctx.emit(
                "device-scan-start",
                json!({
                    "id": id,
                    "device_name": entry.info.device_name,
                    "mount_point": entry.info.mount_point,
                    "notifications_enabled": notifications_enabled,
                }),
            );
            let result = crate::scanner::dispatch(
                &shared.ctx,
                "scan",
                json!({
                    "id": id,
                    "paths": [entry.info.mount_point],
                    "recursive": true,
                    "scheduled": false,
                }),
            );
            let quarantined_count = if entry.cancelled.load(Ordering::Acquire) {
                0
            } else {
                shared.auto_quarantine(result.as_ref().ok())
            };
            let payload = match result {
                Ok(result) => json!({
                    "id": id,
                    "device_name": entry.info.device_name,
                    "mount_point": entry.info.mount_point,
                    "result": result,
                    "quarantined_count": quarantined_count,
                    "notifications_enabled": notifications_enabled,
                }),
                Err(error) => json!({
                    "id": id,
                    "device_name": entry.info.device_name,
                    "mount_point": entry.info.mount_point,
                    "error": error,
                    "quarantined_count": quarantined_count,
                    "notifications_enabled": notifications_enabled,
                }),
            };
            {
                let mut state = shared.state.lock().expect("monitor state poisoned");
                state.active.remove(&entry.info.mount_point);
                state
                    .recent
                    .insert(entry.info.mount_point.clone(), Instant::now());
            }
            shared.ctx.emit("device-scan-complete", payload);
            shared.start_next();
        });
    }

    fn auto_quarantine(&self, result: Option<&Value>) -> u64 {
        let Ok(settings) = self.ctx.settings() else {
            return 0;
        };
        if !setting_bool(&settings, "device_auto_scan_auto_quarantine", false) {
            return 0;
        }
        let Some(result) = result else {
            return 0;
        };

        threat_details(result)
            .into_iter()
            .filter_map(|threat| {
                let path = threat.get("path")?.as_str()?;
                let threat_name = threat.get("threat_name")?.as_str()?;
                let request = json!({ "path": path, "threat_name": threat_name });
                Some(
                    crate::quarantine::dispatch(&self.ctx, "quarantine", request)
                        .ok()
                        .and_then(|result| {
                            result
                                .get("status")
                                .and_then(Value::as_str)
                                .map(str::to_owned)
                        })
                        .is_some_and(|status| status == "success"),
                )
            })
            .filter(|success| *success)
            .count() as u64
    }

    fn start_next(self: &Arc<Self>) {
        let next = {
            let mut state = self.state.lock().expect("monitor state poisoned");
            if state.active.len() >= MAX_CONCURRENT_SCANS {
                None
            } else {
                state.queued.pop_front()
            }
        };
        if let Some(entry) = next {
            self.start_or_queue(entry);
        }
    }

    fn stop(&self) {
        self.stopped.store(true, Ordering::Release);
        let active = {
            let mut state = self.state.lock().expect("monitor state poisoned");
            for delayed in state.delayed.values() {
                delayed.store(true, Ordering::Release);
            }
            state.delayed.clear();
            state.queued.clear();
            state
                .active
                .drain()
                .map(|(_, entry)| entry)
                .collect::<Vec<_>>()
        };
        for entry in active {
            entry.cancelled.store(true, Ordering::Release);
            let _ = crate::scanner::dispatch(&self.ctx, "cancel", json!({ "id": entry.job_id }));
        }
    }
}

fn threat_details(result: &Value) -> Vec<Value> {
    let results = result
        .get("per_target_results")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .chain(std::iter::once(result));
    results
        .flat_map(|item| {
            item.get("threat_details")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
        })
        .filter_map(|threat| {
            let path = threat.get("file_path").and_then(Value::as_str)?;
            let threat_name = threat.get("threat_name").and_then(Value::as_str)?;
            Some(json!({ "path": path, "threat_name": threat_name }))
        })
        .collect()
}

fn setting_bool(settings: &Value, name: &str, default: bool) -> bool {
    settings
        .get(name)
        .and_then(Value::as_bool)
        .unwrap_or(default)
}

fn device_type_name(device_type: DeviceType) -> &'static str {
    match device_type {
        DeviceType::Removable => "removable",
        DeviceType::External => "external",
        DeviceType::Network => "network",
        DeviceType::Internal => "internal",
        DeviceType::Unknown => "unknown",
    }
}

fn device_type_from_name(name: &str) -> Option<DeviceType> {
    match name {
        "removable" => Some(DeviceType::Removable),
        "external" => Some(DeviceType::External),
        "network" => Some(DeviceType::Network),
        "internal" => Some(DeviceType::Internal),
        "unknown" => Some(DeviceType::Unknown),
        _ => None,
    }
}

fn mount_event(info: &MountInfo) -> Value {
    json!({
        "mount_point": info.mount_point,
        "device_name": info.device_name,
        "device_type": device_type_name(info.device_type),
        "volume_uuid": info.volume_uuid,
        "size_bytes": info.size_bytes,
    })
}

/// Owns the dedicated GLib monitor thread. `stop` is idempotent, stops
/// delivery before cancellation, and joins every monitor-owned worker.
pub struct MonitorHandle {
    main_context: glib::MainContext,
    main_loop: glib::MainLoop,
    shared: Arc<MonitorShared>,
    thread: Mutex<Option<JoinHandle<()>>>,
}

impl MonitorHandle {
    pub fn stop(&self) {
        self.shared.stop();
        let main_loop = self.main_loop.clone();
        self.main_context.invoke(move || main_loop.quit());
        if let Some(thread) = self.thread.lock().expect("monitor handle poisoned").take() {
            let _ = thread.join();
        }
        self.shared.join_workers();
    }
}

impl Drop for MonitorHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

pub fn start_monitor(ctx: Context) -> AppResult<MonitorHandle> {
    let shared = Arc::new(MonitorShared {
        ctx,
        state: Mutex::new(MonitorState::default()),
        stopped: AtomicBool::new(false),
        generation: AtomicU64::new(1),
        workers: Mutex::new(Vec::new()),
    });
    let main_context = glib::MainContext::new();
    let main_loop = glib::MainLoop::new(Some(&main_context), false);
    let handle_context = main_context.clone();
    let handle_loop = main_loop.clone();
    let shared_thread = Arc::clone(&shared);
    let thread = thread::Builder::new()
        .name("clamui-device-monitor".to_owned())
        .spawn(move || {
            let _ = main_context.with_thread_default(|| {
                let monitor = gio::VolumeMonitor::get();
                let added = Arc::clone(&shared_thread);
                let added_handler =
                    monitor.connect_mount_added(move |_, mount| added.on_added(mount.clone()));
                let removed = Arc::clone(&shared_thread);
                let removed_handler = monitor
                    .connect_mount_removed(move |_, mount| removed.on_removed(mount.clone()));
                main_loop.run();
                monitor.disconnect(added_handler);
                monitor.disconnect(removed_handler);
            });
        })
        .map_err(|error| format!("Failed to start device monitor: {error}"))?;
    Ok(MonitorHandle {
        main_context: handle_context,
        main_loop: handle_loop,
        shared,
        thread: Mutex::new(Some(thread)),
    })
}

#[cfg(test)]
mod monitor_lifecycle_tests {
    use super::*;
    use std::sync::mpsc;

    #[test]
    fn public_handle_stop_waits_for_active_registered_worker() {
        let temporary = tempfile::tempdir().expect("temporary monitor root");
        let paths = crate::Paths {
            home: temporary.path().join("home"),
            config_dir: temporary.path().join("config/clamui"),
            data_dir: temporary.path().join("data/clamui"),
        };
        let shared = Arc::new(MonitorShared {
            ctx: Context::with_paths(paths).expect("test context"),
            state: Mutex::new(MonitorState::default()),
            stopped: AtomicBool::new(false),
            generation: AtomicU64::new(1),
            workers: Mutex::new(Vec::new()),
        });
        let main_context = glib::MainContext::new();
        let handle = MonitorHandle {
            main_loop: glib::MainLoop::new(Some(&main_context), false),
            main_context,
            shared: Arc::clone(&shared),
            thread: Mutex::new(None),
        };
        let (started_tx, started_rx) = mpsc::sync_channel(0);
        let (stop_seen_tx, stop_seen_rx) = mpsc::sync_channel(0);
        let (release_tx, release_rx) = mpsc::sync_channel(0);
        let (completed_tx, completed_rx) = mpsc::sync_channel(0);
        shared.spawn_worker(move |shared| {
            started_tx.send(()).expect("report worker start");
            while !shared.stopped.load(Ordering::Acquire) {
                thread::yield_now();
            }
            stop_seen_tx.send(()).expect("report monitor stop");
            release_rx.recv().expect("release worker");
            completed_tx.send(()).expect("report worker completion");
        });
        started_rx.recv().expect("worker started");
        let (returned_tx, returned_rx) = mpsc::sync_channel(0);
        thread::spawn(move || {
            handle.stop();
            returned_tx.send(()).expect("report handle stop return");
        });
        stop_seen_rx.recv().expect("stop reached active worker");
        assert!(
            matches!(returned_rx.try_recv(), Err(mpsc::TryRecvError::Empty)),
            "public stop must remain blocked while a registered worker is active"
        );
        release_tx.send(()).expect("release active worker");
        completed_rx.recv().expect("worker completed");
        returned_rx.recv().expect("public handle stop returned");
    }
}
