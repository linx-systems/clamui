use crate::common::{host_command, is_flatpak};
use crate::AppResult;
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::process::Stdio;
use std::time::{Duration, Instant};

const DATABASE_SUFFIXES: [&str; 3] = ["cvd", "cld", "cud"];
const DEFAULT_DATABASE_DIRS: [&str; 2] = ["/var/lib/clamav", "/usr/local/share/clamav"];
const CLAMD_CONFIGS: [&str; 3] = [
    "/etc/clamav/clamd.conf",
    "/etc/clamd.d/scan.conf",
    "/etc/clamd.conf",
];
const FRESHCLAM_CONFIGS: [&str; 2] = ["/etc/clamav/freshclam.conf", "/etc/freshclam.conf"];

#[derive(Clone, Debug, Serialize)]
pub struct Probe {
    pub available: bool,
    pub detail: Option<String>,
    pub path: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct ComponentRow {
    pub id: &'static str,
    pub name: &'static str,
    pub status: String,
    pub detail: Option<String>,
    pub version: Option<String>,
    pub install_command: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct BatteryObservation {
    pub on_battery: bool,
    pub charge_percent: Option<f64>,
}

pub fn run_host(
    program: &str,
    args: &[String],
    timeout: Option<u64>,
) -> AppResult<std::process::Output> {
    let mut command = host_command(program, args);
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to run {program}: {error}"))?;
    let deadline = timeout.map(|seconds| Instant::now() + Duration::from_secs(seconds));
    loop {
        if child
            .try_wait()
            .map_err(|error| format!("Unable to wait for {program}: {error}"))?
            .is_some()
        {
            return child
                .wait_with_output()
                .map_err(|error| format!("Unable to read {program} output: {error}"));
        }
        if deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("{program} timed out"));
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

pub fn host_binary(binary: &str) -> Option<String> {
    if !binary
        .chars()
        .all(|character| character.is_ascii_alphanumeric() || character == '-' || character == '_')
    {
        return None;
    }
    let args = vec![binary.to_owned()];
    let output = run_host("which", &args, Some(5)).ok()?;
    if output.status.success() {
        let path = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        if !path.is_empty() {
            return Some(path);
        }
    }
    [format!("/usr/sbin/{binary}"), format!("/sbin/{binary}")]
        .into_iter()
        .find(|candidate| host_regular_executable(candidate))
}

fn host_regular_executable(path: &str) -> bool {
    let args = vec![
        "-f".to_owned(),
        path.to_owned(),
        "-a".to_owned(),
        "-x".to_owned(),
        path.to_owned(),
    ];
    run_host("test", &args, Some(5))
        .map(|output| output.status.success())
        .unwrap_or(false)
}

pub fn config_file_exists(path: &str) -> bool {
    if path.is_empty() || !Path::new(path).is_absolute() {
        return false;
    }
    if is_flatpak() {
        let args = vec!["-f".to_owned(), path.to_owned()];
        return run_host("test", &args, Some(5))
            .map(|output| output.status.success())
            .unwrap_or(false);
    }
    Path::new(path).is_file()
}

pub fn read_host_bytes(path: &str) -> AppResult<Vec<u8>> {
    if path.is_empty() || !Path::new(path).is_absolute() {
        return Err("Host path must be absolute".to_owned());
    }
    if !is_flatpak() {
        return fs::read(path).map_err(|error| format!("Cannot read {path}: {error}"));
    }
    let output = run_host("cat", &[path.to_owned()], Some(10))?;
    if !output.status.success() {
        return Err(format!(
            "Cannot read {path}: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(output.stdout)
}

pub fn read_host_file(path: &str) -> AppResult<String> {
    let bytes = read_host_bytes(path)?;
    match String::from_utf8(bytes) {
        Ok(content) => Ok(content),
        Err(error) => Ok(error.into_bytes().into_iter().map(char::from).collect()),
    }
}

fn directive(path: &str, key: &str) -> Option<String> {
    let content = read_host_file(path).ok()?;
    content.lines().find_map(|raw| {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            return None;
        }
        let mut parts = line.splitn(2, char::is_whitespace);
        let actual_key = parts.next()?;
        let value = parts.next()?.trim();
        (actual_key == key && !value.is_empty()).then(|| value.to_owned())
    })
}

pub fn detect_clamd_conf_path() -> Option<String> {
    CLAMD_CONFIGS
        .iter()
        .find(|path| config_file_exists(path))
        .map(|path| (*path).to_owned())
}

pub fn detect_freshclam_conf_path() -> Option<String> {
    FRESHCLAM_CONFIGS
        .iter()
        .find(|path| config_file_exists(path))
        .map(|path| (*path).to_owned())
}

pub fn resolve_clamd_conf_path(configured: Option<&str>) -> Option<String> {
    configured
        .filter(|path| !is_legacy_flatpak_config(path, "clamd.conf") && config_file_exists(path))
        .map(str::to_owned)
        .or_else(detect_clamd_conf_path)
}

pub fn is_legacy_flatpak_config(path: &str, name: &str) -> bool {
    is_flatpak()
        && std::env::var_os("HOME")
            .map(|home| Path::new(&home).join(".config/clamav").join(name) == Path::new(path))
            .unwrap_or(false)
}

pub fn resolve_freshclam_conf_path(configured: Option<&str>) -> Option<String> {
    configured
        .filter(|path| {
            !is_legacy_flatpak_config(path, "freshclam.conf") && config_file_exists(path)
        })
        .map(str::to_owned)
        .or_else(detect_freshclam_conf_path)
}

pub fn freshclam_database_dir(config_path: Option<&str>) -> String {
    config_path
        .and_then(|path| directive(path, "DatabaseDirectory"))
        .filter(|path| Path::new(path).is_absolute())
        .unwrap_or_else(|| DEFAULT_DATABASE_DIRS[0].to_owned())
}

pub fn clamd_socket_path(config_path: Option<&str>) -> Option<String> {
    if let Some(path) = config_path.and_then(|path| directive(path, "LocalSocket")) {
        if host_path_exists(&path) {
            return Some(path);
        }
    }
    [
        "/var/run/clamav/clamd.ctl",
        "/run/clamav/clamd.ctl",
        "/run/clamd.scan/clamd.sock",
        "/var/run/clamd.scan/clamd.sock",
    ]
    .into_iter()
    .find(|path| host_path_exists(path))
    .map(str::to_owned)
}

fn host_path_exists(path: &str) -> bool {
    if is_flatpak() {
        return run_host("test", &["-e".to_owned(), path.to_owned()], Some(5))
            .map(|output| output.status.success())
            .unwrap_or(false);
    }
    Path::new(path).exists()
}

pub fn check_clamd_connection(config_path: Option<&str>) -> Probe {
    let Some(binary) = host_binary("clamdscan") else {
        return Probe {
            available: false,
            detail: Some(missing_tool_message("clamdscan")),
            path: None,
        };
    };
    if !is_flatpak() && clamd_socket_path(config_path).is_none() {
        return Probe {
            available: false,
            detail: Some("Could not find clamd socket. Is clamav-daemon installed?".to_owned()),
            path: Some(binary),
        };
    }
    let mut args = Vec::new();
    if let Some(config_path) = config_path {
        args.push(format!("--config-file={config_path}"));
    }
    args.extend(["--ping".to_owned(), "3".to_owned()]);
    match run_host("clamdscan", &args, Some(10)) {
        Ok(output)
            if output.status.success()
                && String::from_utf8_lossy(&output.stdout).contains("PONG") =>
        {
            Probe {
                available: true,
                detail: Some("PONG".to_owned()),
                path: Some(binary),
            }
        }
        Ok(output) => Probe {
            available: false,
            detail: Some(format!("Daemon not responding: {}", output_text(&output))),
            path: Some(binary),
        },
        Err(error) => Probe {
            available: false,
            detail: Some(error),
            path: Some(binary),
        },
    }
}

fn output_text(output: &std::process::Output) -> String {
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    if !stderr.is_empty() {
        stderr
    } else {
        String::from_utf8_lossy(&output.stdout).trim().to_owned()
    }
}

pub fn check_tool(binary: &str) -> Probe {
    let Some(path) = host_binary(binary) else {
        return Probe {
            available: false,
            detail: Some(missing_tool_message(binary)),
            path: None,
        };
    };
    let mut args = vec!["--version".to_owned()];
    if binary == "freshclam" {
        args.push("--config-file=/dev/null".to_owned());
    }
    match run_host(binary, &args, Some(10)) {
        Ok(output) if output.status.success() => Probe {
            available: true,
            detail: Some(String::from_utf8_lossy(&output.stdout).trim().to_owned()),
            path: Some(path),
        },
        Ok(output) => Probe {
            available: false,
            detail: Some(format!(
                "{binary} found but returned error: {}",
                output_text(&output)
            )),
            path: Some(path),
        },
        Err(error) => Probe {
            available: false,
            detail: Some(error),
            path: Some(path),
        },
    }
}

fn host_systemd_unit_exists(name: &str) -> bool {
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

fn clamd_daemon_status() -> (String, Option<String>) {
    let mut saw_service = false;
    for service in [
        "clamav-daemon.service",
        "clamd@scan.service",
        "clamd.service",
    ] {
        let Ok(output) = run_host(
            "systemctl",
            &["is-active".to_owned(), service.to_owned()],
            Some(5),
        ) else {
            continue;
        };
        let state = String::from_utf8_lossy(&output.stdout)
            .trim()
            .to_ascii_lowercase();
        if state == "active" {
            return ("running".to_owned(), Some(format!("{service} is active")));
        }
        if matches!(
            state.as_str(),
            "inactive" | "failed" | "activating" | "deactivating"
        ) && host_systemd_unit_exists(service)
        {
            saw_service = true;
        }
    }
    if run_host("pgrep", &["-x".to_owned(), "clamd".to_owned()], Some(5))
        .map(|output| output.status.success())
        .unwrap_or(false)
    {
        return (
            "running".to_owned(),
            Some("clamd daemon is running".to_owned()),
        );
    }
    if saw_service {
        return (
            "stopped".to_owned(),
            Some("clamd service is installed but not active".to_owned()),
        );
    }
    if host_binary("clamd").is_none() {
        return (
            "not_installed".to_owned(),
            Some("clamd is not installed".to_owned()),
        );
    }
    (
        "stopped".to_owned(),
        Some("clamd daemon is not running".to_owned()),
    )
}

pub fn database_available(config_path: Option<&str>, require_readable: bool) -> Probe {
    let configured_dir = config_path.and_then(|path| directive(path, "DatabaseDirectory"));
    let mut dirs = configured_dir.into_iter().collect::<Vec<_>>();
    dirs.extend(DEFAULT_DATABASE_DIRS.iter().map(|path| (*path).to_owned()));
    dirs.sort();
    dirs.dedup();
    let mut errors = Vec::new();
    for dir in dirs {
        match database_in_dir(&dir, require_readable) {
            Ok(true) => {
                return Probe {
                    available: true,
                    detail: None,
                    path: Some(dir),
                }
            }
            Ok(false) => errors.push(format!("No virus database files found in {dir}")),
            Err(error) => errors.push(error),
        }
    }
    Probe {
        available: false,
        detail: Some(errors.join("; ")),
        path: None,
    }
}

fn database_in_dir(dir: &str, require_readable: bool) -> AppResult<bool> {
    if is_flatpak() {
        let script = "found=0; for f in \"$1\"/*.cvd \"$1\"/*.cld \"$1\"/*.cud; do [ -f \"$f\" ] || continue; found=1; if [ \"$2\" = 1 ]; then [ -r \"$f\" ] || continue; fi; exit 0; done; [ \"$found\" = 1 ] && exit 2; exit 1";
        let output = run_host(
            "sh",
            &[
                "-c".to_owned(),
                script.to_owned(),
                "clamui-db-probe".to_owned(),
                dir.to_owned(),
                if require_readable { "1" } else { "0" }.to_owned(),
            ],
            Some(5),
        )?;
        if output.status.code() == Some(2) {
            return Err("Virus database files exist but are not readable by this user. Use the ClamAV daemon backend or grant this user read access through your system's ClamAV configuration.".to_owned());
        }
        return Ok(output.status.success());
    }
    let directory = Path::new(dir);
    let entries = fs::read_dir(directory)
        .map_err(|error| format!("Error accessing database {dir}: {error}"))?;
    let mut unreadable = false;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_file()
            && path
                .extension()
                .and_then(|extension| extension.to_str())
                .is_some_and(|extension| {
                    DATABASE_SUFFIXES.contains(&extension.to_ascii_lowercase().as_str())
                })
        {
            if !require_readable || fs::File::open(&path).is_ok() {
                return Ok(true);
            }
            unreadable = true;
        }
    }
    if unreadable {
        return Err("Virus database files exist but are not readable by this user. Use the ClamAV daemon backend or grant this user read access through your system's ClamAV configuration.".to_owned());
    }
    Ok(false)
}

pub fn database_status(config_path: Option<&str>) -> Value {
    let probe = database_available(config_path, true);
    if !probe.available {
        return json!({"available": false, "detail": probe.detail, "path": probe.path, "age_days": Value::Null, "updated_at": Value::Null});
    }
    let Some(dir) = probe.path.clone() else {
        return json!({"available": true, "detail": probe.detail, "path": Value::Null, "age_days": Value::Null, "updated_at": Value::Null});
    };
    let newest = if is_flatpak() {
        let script = "find \"$1\" -maxdepth 1 -type f \\( -iname '*.cvd' -o -iname '*.cld' -o -iname '*.cud' \\) -printf '%T@ %p\\n' | sort -nr | head -n 1";
        run_host(
            "sh",
            &[
                "-c".to_owned(),
                script.to_owned(),
                "clamui-db-stat".to_owned(),
                dir.clone(),
            ],
            Some(5),
        )
        .ok()
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .and_then(|line| {
            line.split_once(' ').and_then(|(timestamp, path)| {
                timestamp
                    .parse::<f64>()
                    .ok()
                    .map(|timestamp| (timestamp as i64, path.trim().to_owned()))
            })
        })
    } else {
        fs::read_dir(&dir)
            .ok()
            .into_iter()
            .flatten()
            .flatten()
            .filter_map(|entry| {
                let path = entry.path();
                let extension = path.extension()?.to_str()?.to_ascii_lowercase();
                DATABASE_SUFFIXES
                    .contains(&extension.as_str())
                    .then_some(path)
            })
            .filter_map(|path| {
                path.metadata().ok()?.modified().ok().and_then(|modified| {
                    modified
                        .duration_since(std::time::UNIX_EPOCH)
                        .ok()
                        .map(|duration| (duration.as_secs() as i64, path.display().to_string()))
                })
            })
            .max_by_key(|(timestamp, _)| *timestamp)
    };
    match newest {
        Some((timestamp, path)) => {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|duration| duration.as_secs() as i64)
                .unwrap_or(timestamp);
            let age_days = ((now - timestamp).max(0) as f64 / 86_400.0).floor() as u64;
            let updated_at = chrono::DateTime::<chrono::Utc>::from_timestamp(timestamp, 0)
                .map(|time| time.to_rfc3339());
            json!({"available": true, "detail": probe.detail, "path": path, "age_days": age_days, "updated_at": updated_at})
        }
        None => {
            json!({"available": true, "detail": probe.detail, "path": dir, "age_days": Value::Null, "updated_at": Value::Null})
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Distro {
    Debian,
    Fedora,
    FedoraAtomic,
    Arch,
}

pub(crate) fn distro() -> Option<Distro> {
    let source = read_host_file("/etc/os-release").ok()?;
    let values = source
        .lines()
        .filter_map(|line| {
            line.split_once('=').map(|(key, value)| {
                (
                    key.trim(),
                    value.trim().trim_matches('"').to_ascii_lowercase(),
                )
            })
        })
        .collect::<BTreeMap<_, _>>();
    match values.get("ID").map(String::as_str) {
        Some("debian" | "ubuntu" | "linuxmint" | "pop") => Some(Distro::Debian),
        Some("fedora")
            if values.get("VARIANT_ID").is_some_and(|variant| {
                matches!(
                    variant.as_str(),
                    "silverblue"
                        | "kinoite"
                        | "sericea"
                        | "onyx"
                        | "sway-atomic"
                        | "budgie-atomic"
                        | "cosmic-atomic"
                ) || variant.ends_with("-atomic")
            }) =>
        {
            Some(Distro::FedoraAtomic)
        }
        Some("fedora") => Some(Distro::Fedora),
        Some("arch" | "manjaro") => Some(Distro::Arch),
        _ => None,
    }
}

pub fn install_command(target: &str) -> Option<String> {
    let command = match (distro()?, target) {
        (Distro::Debian, "clamav" | "clamscan") => "sudo apt install clamav clamav-daemon",
        (Distro::Debian, "freshclam") => "sudo apt install clamav-freshclam",
        (Distro::Debian, "clamdscan" | "clamd") => "sudo apt install clamav-daemon",
        (Distro::Debian, "firewall") => "sudo apt install ufw && sudo ufw enable",
        (Distro::Debian, "firewall_gui") => "sudo apt install gufw",
        (Distro::Debian, "automatic_updates") => "sudo apt install unattended-upgrades",
        (Distro::Debian, "intrusion_prevention") => "sudo apt install fail2ban",
        (Distro::Debian, "lynis") => "sudo apt install lynis",
        (Distro::Debian, "chkrootkit") => "sudo apt install chkrootkit",
        (Distro::Fedora, "clamav" | "clamscan") => "sudo dnf install clamav clamd",
        (Distro::Fedora, "freshclam") => "sudo dnf install clamav-freshclam",
        (Distro::Fedora, "clamdscan" | "clamd") => "sudo dnf install clamd",
        (Distro::Fedora, "firewall") => {
            "sudo dnf install firewalld && sudo systemctl enable --now firewalld"
        }
        (Distro::Fedora, "firewall_gui") => "sudo dnf install firewall-config",
        (Distro::Fedora, "automatic_updates") => "sudo dnf install dnf-automatic",
        (Distro::Fedora, "intrusion_prevention") => "sudo dnf install fail2ban",
        (Distro::Fedora, "lynis") => "sudo dnf install lynis",
        (Distro::Fedora, "chkrootkit") => "sudo dnf install chkrootkit",
        (Distro::Arch, "clamav" | "clamscan" | "freshclam" | "clamdscan" | "clamd") => {
            "sudo pacman -S clamav"
        }
        (Distro::Arch, "firewall") => {
            "sudo pacman -S firewalld && sudo systemctl enable --now firewalld"
        }
        (Distro::Arch, "firewall_gui") => "sudo pacman -S firewall-config",
        (Distro::Arch, "intrusion_prevention") => "sudo pacman -S fail2ban",
        (Distro::Arch, "lynis") => "sudo pacman -S lynis",
        (Distro::FedoraAtomic, "clamav" | "clamscan") => {
            "sudo rpm-ostree install clamav clamd\nsudo systemctl reboot"
        }
        (Distro::FedoraAtomic, "freshclam") => {
            "sudo rpm-ostree install clamav-freshclam\nsudo systemctl reboot"
        }
        (Distro::FedoraAtomic, "clamdscan" | "clamd") => {
            "sudo rpm-ostree install clamd\nsudo systemctl reboot"
        }
        (Distro::FedoraAtomic, "lynis") => "sudo rpm-ostree install lynis\nsudo systemctl reboot",
        (Distro::FedoraAtomic, "chkrootkit") => {
            "sudo rpm-ostree install chkrootkit\nsudo systemctl reboot"
        }
        _ => return None,
    };
    Some(command.to_owned())
}

fn missing_tool_message(binary: &str) -> String {
    match install_command(binary) {
        Some(command) => format!("{binary} is not installed. Please install it with: {command}"),
        None => format!(
            "{binary} is not installed. Install the required ClamAV package for your distribution."
        ),
    }
}

pub fn components_status(config_path: Option<&str>) -> Value {
    let clamscan = check_tool("clamscan");
    let freshclam = check_tool("freshclam");
    let clamdscan = check_tool("clamdscan");
    let (daemon_status, daemon_detail) = clamd_daemon_status();
    let mut rows = [
        ("clamscan", "ClamAV Scanner", clamscan),
        ("freshclam", "Virus Database Updater", freshclam),
        ("clamdscan", "ClamAV Daemon Scanner", clamdscan),
    ]
    .into_iter()
    .map(|(id, name, probe)| ComponentRow {
        id,
        name,
        status: if probe.available {
            "installed".to_owned()
        } else {
            "missing".to_owned()
        },
        version: probe.available.then(|| probe.detail.clone()).flatten(),
        detail: probe.detail,
        install_command: (!probe.available).then(|| install_command(id)).flatten(),
    })
    .collect::<Vec<_>>();
    rows.push(ComponentRow {
        id: "clamd",
        name: "ClamAV Daemon",
        status: daemon_status.clone(),
        detail: daemon_detail,
        version: None,
        install_command: (daemon_status != "running")
            .then(|| install_command("clamd"))
            .flatten(),
    });
    json!({"components": rows, "database": database_status(config_path)})
}

pub fn battery_observation() -> BatteryObservation {
    // Old psutil semantics are fail-open: no battery or unknown AC state means
    // "plugged in". A known online AC adapter always wins over a concurrently
    // stale Discharging battery status. Charge remains independently observed
    // so callers can accurately explain an actual battery skip.
    let root = Path::new("/sys/class/power_supply");
    let Ok(entries) = fs::read_dir(root) else {
        return BatteryObservation {
            on_battery: false,
            charge_percent: None,
        };
    };
    let mut battery_discharging = false;
    let mut ac_online = false;
    let mut charge_total = 0.0;
    let mut charge_count = 0_u32;
    for entry in entries.flatten() {
        let path = entry.path();
        let kind = fs::read_to_string(path.join("type"))
            .ok()
            .map(|value| value.trim().to_owned());
        match kind.as_deref() {
            Some("Mains" | "AC" | "USB") => {
                ac_online |= fs::read_to_string(path.join("online"))
                    .ok()
                    .is_some_and(|value| value.trim() == "1");
            }
            Some("Battery") => {
                battery_discharging |= fs::read_to_string(path.join("status"))
                    .ok()
                    .is_some_and(|value| value.trim().eq_ignore_ascii_case("discharging"));
                if let Some(charge) = fs::read_to_string(path.join("capacity"))
                    .ok()
                    .and_then(|value| value.trim().parse::<f64>().ok())
                    .filter(|charge| charge.is_finite() && (0.0..=100.0).contains(charge))
                {
                    charge_total += charge;
                    charge_count += 1;
                }
            }
            _ => {}
        }
    }
    BatteryObservation {
        on_battery: battery_discharging && !ac_online,
        charge_percent: (charge_count > 0).then(|| charge_total / f64::from(charge_count)),
    }
}

pub fn on_battery() -> bool {
    battery_observation().on_battery
}

fn tr(ctx: &crate::common::Context, message: &str) -> String {
    crate::i18n::translate(ctx, message)
}

fn localize_detail(ctx: &crate::common::Context, text: &str) -> String {
    if let Some(error) = text.strip_prefix("Daemon not responding: ") {
        return tr(ctx, "Daemon not responding: {error}").replace("{error}", error);
    }
    if let Some((binary, error)) = text.split_once(" found but returned error: ") {
        return tr(ctx, "{binary} found but returned error: {error}")
            .replace("{binary}", binary)
            .replace("{error}", error);
    }
    if let Some(service) = text.strip_suffix(" is active") {
        return tr(ctx, "{service} is active").replace("{service}", service);
    }
    if let Some(path) = text.strip_prefix("No virus database files found in ") {
        return tr(ctx, "No virus database files found in {path}").replace("{path}", path);
    }
    if let Some((path, error)) = text
        .strip_prefix("Error accessing database ")
        .and_then(|detail| detail.split_once(": "))
    {
        return tr(ctx, "Error accessing database {path}: {error}")
            .replace("{path}", path)
            .replace("{error}", error);
    }
    if let Some((binary, command)) = text.split_once(" is not installed. Please install it with: ")
    {
        return tr(
            ctx,
            "{binary} is not installed. Please install it with: {command}",
        )
        .replace("{binary}", binary)
        .replace("{command}", command);
    }
    if let Some(binary) = text.strip_suffix(
        " is not installed. Install the required ClamAV package for your distribution.",
    ) {
        return tr(
            ctx,
            "{binary} is not installed. Install the required ClamAV package for your distribution.",
        )
        .replace("{binary}", binary);
    }
    tr(ctx, text)
}

fn localize_status(ctx: &crate::common::Context, value: &mut Value) {
    if let Some(rows) = value.get_mut("components").and_then(Value::as_array_mut) {
        for row in rows {
            for key in ["detail", "version"] {
                if let Some(text) = row.get(key).and_then(Value::as_str) {
                    row[key] = Value::String(localize_detail(ctx, text));
                }
            }
        }
    }
    if let Some(text) = value
        .get("database")
        .and_then(|database| database.get("detail"))
        .and_then(Value::as_str)
    {
        value["database"]["detail"] = Value::String(localize_detail(ctx, text));
    }
}

pub fn dispatch(ctx: &crate::common::Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "status" => {
            let config_path = args
                .get("config_path")
                .and_then(Value::as_str)
                .or_else(|| args.get("clamd_conf_path").and_then(Value::as_str));
            let mut status = components_status(config_path);
            localize_status(ctx, &mut status);
            Ok(status)
        }
        "install_commands" => {
            let commands: BTreeMap<&str, String> = [
                "clamav",
                "freshclam",
                "clamd",
                "firewall",
                "firewall_gui",
                "automatic_updates",
                "intrusion_prevention",
                "lynis",
                "chkrootkit",
            ]
            .into_iter()
            .filter_map(|target| install_command(target).map(|command| (target, command)))
            .collect();
            let distro = match distro() {
                Some(Distro::Debian) => "debian",
                Some(Distro::Fedora) => "fedora",
                Some(Distro::FedoraAtomic) => "fedora_atomic",
                Some(Distro::Arch) => "arch",
                None => "unknown",
            };
            Ok(json!({"distro":distro,"commands":commands}))
        }
        _ => Err(format!("Unknown components action: {action}")),
    }
}
