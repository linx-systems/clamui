use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::common::{host_command, is_flatpak, sanitize_line, sanitize_text, Context};
use crate::portmaster::{self, PortmasterStatus};
use crate::AppResult;

mod firewall;

const COMMAND_TIMEOUT: Duration = Duration::from_secs(10);
const DEEP_SCAN_TIMEOUT: Duration = Duration::from_secs(300);

const URL_CLAMAV: &str = "https://docs.clamav.net/";
const URL_FRESHCLAM: &str = "https://docs.clamav.net/manual/Usage/SignatureManagement.html";
const URL_CLAMD: &str = "https://docs.clamav.net/manual/Usage/Scanning.html#clamd";
const URL_UFW: &str = "https://wiki.archlinux.org/title/Uncomplicated_Firewall";
const URL_FIREWALLD: &str = "https://firewalld.org/documentation/";
const URL_NFTABLES: &str = "https://wiki.archlinux.org/title/Nftables";
const URL_APPARMOR: &str = "https://wiki.archlinux.org/title/AppArmor";
const URL_SELINUX: &str = "https://wiki.archlinux.org/title/SELinux";
const URL_UNATTENDED: &str = "https://wiki.debian.org/UnattendedUpgrades";
const URL_DNF: &str = "https://dnf.readthedocs.io/en/latest/automatic.html";
const URL_FAIL2BAN: &str = "https://github.com/fail2ban/fail2ban/wiki";
const URL_CROWDSEC: &str = "https://docs.crowdsec.net/";
const URL_SSH: &str = "https://wiki.archlinux.org/title/OpenSSH#Protection";
const URL_SSH_ROOT: &str = "https://man7.org/linux/man-pages/man5/sshd_config.5.html";
const URL_LYNIS: &str = "https://cisofy.com/lynis/";
const URL_CHKROOTKIT: &str = "https://www.chkrootkit.org/";
const URL_PORTS: &str = "https://wiki.archlinux.org/title/Security#Network_and_firewalls";
const URL_PORTMASTER: &str = "https://safing.io/portmaster/";
const URL_PORTMASTER_INSTALL: &str = "https://docs.safing.io/portmaster/install/linux";
const URL_PORTMASTER_API: &str = "https://docs.safing.io/portmaster/api";

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditStatus {
    Pass,
    Warning,
    Fail,
    Unknown,
    Skipped,
    Checking,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuditCategory {
    ClamavHealth,
    Firewall,
    MacFramework,
    AutoUpdates,
    IntrusionDetection,
    SshHardening,
    Portmaster,
    DeepScanLynis,
    DeepScanRootkit,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AuditCheck {
    pub name: String,
    pub status: AuditStatus,
    pub detail: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub recommendation: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub install_command: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub info_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub launch_command: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub launch_label: Option<String>,
}

impl AuditCheck {
    fn new(name: String, status: AuditStatus, detail: String) -> Self {
        Self {
            name,
            status,
            detail,
            recommendation: None,
            install_command: None,
            info_url: None,
            launch_command: None,
            launch_label: None,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AuditSection {
    pub category: AuditCategory,
    pub title: String,
    pub icon_name: String,
    pub checks: Vec<AuditCheck>,
    pub overall_status: AuditStatus,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct AuditReport {
    pub sections: Vec<AuditSection>,
    pub timestamp: f64,
}

fn tr(ctx: &Context, message: &str) -> String {
    crate::i18n::translate(ctx, message)
}

fn trn(ctx: &Context, singular: &str, plural: &str, count: u64) -> String {
    crate::i18n::translate_plural(ctx, singular, plural, count)
}

fn text(ctx: &Context, message: &str, replacements: &[(&str, String)]) -> String {
    let mut translated = tr(ctx, message);
    for (needle, value) in replacements {
        translated = translated.replace(needle, value);
    }
    translated
}

fn trnf(
    ctx: &Context,
    singular: &str,
    plural: &str,
    count: u64,
    replacements: &[(&str, String)],
) -> String {
    let mut translated = trn(ctx, singular, plural, count);
    for (needle, value) in replacements {
        translated = translated.replace(needle, value);
    }
    translated
}

impl AuditSection {
    fn new(ctx: &Context, category: AuditCategory, title: &str, icon_name: &str) -> Self {
        Self {
            category,
            title: tr(ctx, title),
            icon_name: icon_name.to_owned(),
            checks: Vec::new(),
            overall_status: AuditStatus::Unknown,
        }
    }

    fn push(&mut self, check: AuditCheck) {
        self.checks.push(check);
        self.overall_status = overall_status(&self.checks);
    }
}

fn check(ctx: &Context, name: &str, status: AuditStatus, detail: String) -> AuditCheck {
    AuditCheck::new(tr(ctx, name), status, detail)
}
pub fn overall_status(checks: &[AuditCheck]) -> AuditStatus {
    for candidate in [
        AuditStatus::Fail,
        AuditStatus::Warning,
        AuditStatus::Unknown,
        AuditStatus::Pass,
        AuditStatus::Skipped,
        AuditStatus::Checking,
    ] {
        if checks.iter().any(|check| check.status == candidate) {
            return candidate;
        }
    }
    AuditStatus::Unknown
}

#[derive(Debug)]
struct CommandOutput {
    code: Option<i32>,
    stdout: String,
    stderr: String,
}

fn run_command(program: &str, args: &[&str], timeout: Duration) -> CommandOutput {
    let arguments = args
        .iter()
        .map(|value| (*value).to_owned())
        .collect::<Vec<_>>();
    let mut command: Command = host_command(program, &arguments);
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let Ok(mut child) = command.spawn() else {
        return CommandOutput {
            code: None,
            stdout: String::new(),
            stderr: "command not found".to_owned(),
        };
    };
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    // Drain both pipes while the process runs. Waiting before draining can
    // deadlock a host command that fills either OS pipe buffer.
    let stdout_reader = std::thread::spawn(move || read_pipe(stdout));
    let stderr_reader = std::thread::spawn(move || read_pipe(stderr));
    let started = std::time::Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if started.elapsed() < timeout => {
                std::thread::sleep(Duration::from_millis(25));
            }
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
            Err(_) => break None,
        }
    };
    let stdout = stdout_reader.join().unwrap_or_default();
    let stderr = stderr_reader.join().unwrap_or_default();
    if status.is_none() && started.elapsed() >= timeout {
        return CommandOutput {
            code: None,
            stdout: String::new(),
            stderr: "command timed out".to_owned(),
        };
    }
    CommandOutput {
        code: status.and_then(|status| status.code()),
        stdout: sanitize_text(&String::from_utf8_lossy(&stdout)),
        stderr: sanitize_line(&String::from_utf8_lossy(&stderr)),
    }
}

fn read_pipe(pipe: Option<impl Read>) -> Vec<u8> {
    let mut bytes = Vec::new();
    if let Some(mut pipe) = pipe {
        let _ = pipe.read_to_end(&mut bytes);
    }
    bytes
}

fn command_ok(program: &str, args: &[&str]) -> bool {
    run_command(program, args, COMMAND_TIMEOUT).code == Some(0)
}

fn host_binary(binary: &str) -> Option<String> {
    crate::host::host_binary(binary)
}

fn service_active(service: &str) -> (bool, String) {
    let output = run_command("systemctl", &["is-active", service], COMMAND_TIMEOUT);
    let status = output.stdout.trim();
    if status.is_empty() {
        return (
            false,
            if output.stderr.contains("not found") {
                "systemctl not found".to_owned()
            } else {
                output.stderr
            },
        );
    }
    (status == "active", status.to_owned())
}

fn service_installed(service: &str) -> bool {
    command_ok("systemctl", &["cat", service])
}

fn install_command(target: &str) -> Option<String> {
    crate::host::install_command(target)
}

fn clamd_connection() -> bool {
    command_ok("clamdscan", &["--ping", "1"])
}

fn check_clamav_health(ctx: &Context) -> AuditSection {
    let mut section = AuditSection::new(
        ctx,
        AuditCategory::ClamavHealth,
        "ClamAV Health",
        "security-high-symbolic",
    );
    let version = run_command("clamscan", &["--version"], COMMAND_TIMEOUT);
    if version.code != Some(0) {
        let mut missing = check(
            ctx,
            "ClamAV Installation",
            AuditStatus::Fail,
            tr(ctx, "ClamAV is not installed"),
        );
        missing.recommendation = Some(tr(ctx, "Install ClamAV to enable virus scanning"));
        missing.install_command = install_command("clamav");
        missing.info_url = Some(URL_CLAMAV.to_owned());
        section.push(missing);
        return section;
    }
    let version_text = version
        .stdout
        .lines()
        .next()
        .unwrap_or("ClamAV")
        .trim()
        .to_owned();
    let mut installed = check(
        ctx,
        "ClamAV Installation",
        AuditStatus::Pass,
        text(ctx, "Installed: {version}", &[("{version}", version_text)]),
    );
    installed.info_url = Some(URL_CLAMAV.to_owned());
    section.push(installed);

    match database_age(ctx) {
        Some((days, date)) if days <= 3 => {
            let mut database = check(
                ctx,
                "Virus Database",
                AuditStatus::Pass,
                trnf(
                    ctx,
                    "Up to date ({days} day old, built {date})",
                    "Up to date ({days} days old, built {date})",
                    days as u64,
                    &[("{days}", days.to_string()), ("{date}", date)],
                ),
            );
            database.info_url = Some(URL_FRESHCLAM.to_owned());
            section.push(database);
        }
        Some((days, date)) if days <= 7 => {
            let mut database = check(
                ctx,
                "Virus Database",
                AuditStatus::Warning,
                trnf(
                    ctx,
                    "Database is {days} day old (built {date})",
                    "Database is {days} days old (built {date})",
                    days as u64,
                    &[("{days}", days.to_string()), ("{date}", date)],
                ),
            );
            database.recommendation = Some(tr(ctx, "Update virus database to ensure protection"));
            database.install_command = Some("sudo freshclam".to_owned());
            database.info_url = Some(URL_FRESHCLAM.to_owned());
            section.push(database);
        }
        Some((days, date)) => {
            let mut database = check(
                ctx,
                "Virus Database",
                AuditStatus::Fail,
                trnf(
                    ctx,
                    "Database is {days} day old (built {date})",
                    "Database is {days} days old (built {date})",
                    days as u64,
                    &[("{days}", days.to_string()), ("{date}", date)],
                ),
            );
            database.recommendation = Some(tr(
                ctx,
                "Database is critically outdated. Update immediately.",
            ));
            database.install_command = Some("sudo freshclam".to_owned());
            database.info_url = Some(URL_FRESHCLAM.to_owned());
            section.push(database);
        }
        None => {
            let found = find_daily_cvd(ctx).is_some();
            let mut database = check(
                ctx,
                "Virus Database",
                if found {
                    AuditStatus::Unknown
                } else {
                    AuditStatus::Fail
                },
                if found {
                    tr(ctx, "Database files exist but age could not be determined")
                } else {
                    tr(ctx, "No virus database found")
                },
            );
            if !found {
                database.recommendation = Some(tr(ctx, "Download virus database"));
                database.install_command = Some("sudo freshclam".to_owned());
            }
            database.info_url = Some(URL_FRESHCLAM.to_owned());
            section.push(database);
        }
    }

    let daemon_active = ["clamav-daemon", "clamd@scan", "clamd"]
        .iter()
        .find_map(|service| service_active(service).0.then_some(*service));
    let mut daemon = if let Some(service) = daemon_active {
        check(
            ctx,
            "ClamAV Daemon",
            AuditStatus::Pass,
            text(
                ctx,
                "Service {name} is running",
                &[("{name}", service.to_owned())],
            ),
        )
    } else if clamd_connection() {
        check(
            ctx,
            "ClamAV Daemon",
            AuditStatus::Pass,
            tr(ctx, "Daemon is responding"),
        )
    } else {
        let mut check = check(
            ctx,
            "ClamAV Daemon",
            AuditStatus::Warning,
            tr(ctx, "ClamAV daemon is not running"),
        );
        check.recommendation = Some(tr(ctx, "Start the daemon for faster scanning"));
        check.install_command = Some("sudo systemctl start clamav-daemon".to_owned());
        check
    };
    daemon.info_url = Some(URL_CLAMD.to_owned());
    section.push(daemon);

    let freshclam_active = ["clamav-freshclam", "clamav-freshclam.timer"]
        .iter()
        .any(|service| service_active(service).0);
    let mut freshclam = if freshclam_active {
        check(
            ctx,
            "Automatic Updates",
            AuditStatus::Pass,
            tr(ctx, "Freshclam service is active"),
        )
    } else {
        let mut check = check(
            ctx,
            "Automatic Updates",
            AuditStatus::Warning,
            tr(ctx, "Freshclam automatic update service is not running"),
        );
        check.recommendation = Some(tr(ctx, "Enable automatic database updates"));
        check.install_command = Some("sudo systemctl enable --now clamav-freshclam".to_owned());
        check
    };
    freshclam.info_url = Some(URL_FRESHCLAM.to_owned());
    section.push(freshclam);
    section
}

pub fn parse_cvd_age(bytes: &[u8], now: SystemTime) -> Option<(i64, String)> {
    let (timestamp, build_date) = parse_cvd_header(bytes)?;
    let age = now.duration_since(timestamp).ok()?.as_secs() as i64 / 86_400;
    Some((age, build_date))
}

fn parse_cvd_header(bytes: &[u8]) -> Option<(SystemTime, String)> {
    let header = String::from_utf8_lossy(&bytes[..bytes.len().min(512)]);
    let fields = header.split(':').collect::<Vec<_>>();
    if fields.len() < 9 || !fields[0].starts_with("ClamAV-VDB") {
        return None;
    }
    let stamp = fields[8]
        .chars()
        .take_while(|character| character.is_ascii_digit())
        .collect::<String>()
        .parse::<u64>()
        .ok()?;
    let timestamp = UNIX_EPOCH.checked_add(Duration::from_secs(stamp))?;
    Some((timestamp, fields[1].trim().to_owned()))
}

fn format_database_build_date(ctx: &Context, timestamp: SystemTime, header_date: &str) -> String {
    DateTime::parse_from_str(header_date, "%d %b %Y %H-%M %z")
        .ok()
        .or_else(|| {
            timestamp
                .duration_since(UNIX_EPOCH)
                .ok()
                .and_then(|duration| i64::try_from(duration.as_secs()).ok())
                .and_then(|seconds| DateTime::<Utc>::from_timestamp(seconds, 0))
                .map(|date| date.fixed_offset())
        })
        .map(|date| crate::i18n::format_local_date_time(ctx, date))
        .unwrap_or_else(|| header_date.to_owned())
}

fn database_dirs(ctx: &Context) -> Vec<String> {
    let configured = ctx.settings().ok().and_then(|settings| {
        settings
            .get("freshclam_conf_path")
            .and_then(Value::as_str)
            .filter(|path| !path.is_empty())
            .map(str::to_owned)
    });
    let config = crate::host::resolve_freshclam_conf_path(configured.as_deref());
    let configured_directory = config
        .as_deref()
        .and_then(|path| crate::host::read_host_file(path).ok())
        .and_then(|contents| {
            contents.lines().find_map(|line| {
                let line = line.trim();
                if line.is_empty() || line.starts_with('#') {
                    return None;
                }
                let (key, value) = line.split_once(char::is_whitespace)?;
                key.eq_ignore_ascii_case("DatabaseDirectory")
                    .then(|| value.trim().to_owned())
                    .filter(|directory| !directory.is_empty())
            })
        });
    let mut directories = configured_directory.into_iter().collect::<Vec<_>>();
    directories.extend([
        "/var/lib/clamav".to_owned(),
        "/usr/local/share/clamav".to_owned(),
    ]);
    let mut seen = std::collections::BTreeSet::new();
    directories.retain(|directory| seen.insert(directory.clone()));
    directories
}

fn find_daily_cvd(ctx: &Context) -> Option<String> {
    for directory in database_dirs(ctx) {
        if is_flatpak() {
            let output = run_command(
                "find",
                &[
                    &directory,
                    "-maxdepth",
                    "1",
                    "-type",
                    "f",
                    "(",
                    "-iname",
                    "daily.cvd",
                    "-o",
                    "-iname",
                    "daily.cld",
                    ")",
                    "-print",
                    "-quit",
                ],
                Duration::from_secs(5),
            );
            if output.code == Some(0) {
                if let Some(path) = output
                    .stdout
                    .lines()
                    .next()
                    .filter(|path| !path.trim().is_empty())
                {
                    return Some(path.trim().to_owned());
                }
            }
        } else {
            for extension in ["cvd", "cld"] {
                let path = format!("{directory}/daily.{extension}");
                if fs::metadata(&path).is_ok() {
                    return Some(path);
                }
            }
        }
    }
    None
}

fn database_age(ctx: &Context) -> Option<(i64, String)> {
    if let Some(path) = find_daily_cvd(ctx) {
        let bytes = if is_flatpak() {
            let output = run_command("head", &["-c", "512", &path], Duration::from_secs(5));
            (output.code == Some(0)).then_some(output.stdout.into_bytes())
        } else {
            fs::read(path).ok()
        };
        if let Some(bytes) = bytes {
            if let Some((timestamp, header_date)) = parse_cvd_header(&bytes) {
                let age =
                    SystemTime::now().duration_since(timestamp).ok()?.as_secs() as i64 / 86_400;
                return Some((
                    age,
                    format_database_build_date(ctx, timestamp, &header_date),
                ));
            }
        }
    }
    let output = run_command("clamdscan", &["--version"], COMMAND_TIMEOUT);
    let date = output.stdout.split('/').nth(2)?.trim();
    let parsed = chrono::NaiveDateTime::parse_from_str(date, "%a %b %e %H:%M:%S %Y").ok()?;
    let timestamp = DateTime::<Utc>::from_naive_utc_and_offset(parsed, Utc);
    let seconds = Utc::now().signed_duration_since(timestamp).num_seconds();
    Some((
        seconds / 86_400,
        crate::i18n::format_local_date_time(ctx, timestamp.fixed_offset()),
    ))
}
fn check_firewall(ctx: &Context) -> AuditSection {
    firewall::check_firewall(ctx)
}

fn check_open_ports(ctx: &Context, section: &mut AuditSection) {
    let output = run_command("ss", &["-tulnH"], COMMAND_TIMEOUT);
    if output.code != Some(0) {
        return;
    }
    let risky = BTreeMap::from([
        (23, "Telnet"),
        (3389, "RDP"),
        (445, "SMB"),
        (135, "RPC"),
        (139, "NetBIOS"),
        (5900, "VNC"),
    ]);
    let mut ports = std::collections::BTreeSet::new();
    let mut exposed = Vec::new();
    for line in output.stdout.lines() {
        let words = line.split_whitespace().collect::<Vec<_>>();
        let Some(address) = words.get(4) else {
            continue;
        };
        let Some(port) = address
            .rsplit_once(':')
            .and_then(|(_, value)| value.parse::<i32>().ok())
        else {
            continue;
        };
        ports.insert(port);
        if let Some(name) = risky.get(&port) {
            exposed.push(format!("{port} ({name})"));
        }
    }
    let count = ports.len() as u64;
    let mut row = if !exposed.is_empty() {
        let mut row = check(
            ctx,
            "Open Ports",
            AuditStatus::Fail,
            trnf(
                ctx,
                "{count} port listening, risky ports: {ports}",
                "{count} ports listening, risky ports: {ports}",
                count,
                &[
                    ("{count}", count.to_string()),
                    ("{ports}", exposed.join(", ")),
                ],
            ),
        );
        row.recommendation = Some(tr(ctx, "Review if these services need to be exposed"));
        row
    } else if !ports.is_empty() {
        let mut row = check(
            ctx,
            "Open Ports",
            AuditStatus::Warning,
            trnf(
                ctx,
                "{count} port listening",
                "{count} ports listening",
                count,
                &[("{count}", count.to_string())],
            ),
        );
        row.recommendation = Some(tr(ctx, "Review open ports and close unnecessary services"));
        row
    } else {
        check(
            ctx,
            "Open Ports",
            AuditStatus::Pass,
            tr(ctx, "No open ports detected"),
        )
    };
    row.info_url = Some(URL_PORTS.to_owned());
    section.push(row);
}

fn check_mac_framework(ctx: &Context) -> AuditSection {
    let mut section = AuditSection::new(
        ctx,
        AuditCategory::MacFramework,
        "Access Control",
        "system-lock-screen-symbolic",
    );
    let mut found = false;
    let apparmor = if is_flatpak() {
        let output = run_command(
            "cat",
            &["/sys/module/apparmor/parameters/enabled"],
            COMMAND_TIMEOUT,
        );
        (output.code == Some(0)).then_some(output.stdout)
    } else {
        fs::read_to_string("/sys/module/apparmor/parameters/enabled").ok()
    };
    if let Some(value) = apparmor {
        let mut row = if value.trim() == "Y" {
            check(
                ctx,
                "AppArmor",
                AuditStatus::Pass,
                tr(ctx, "AppArmor is enabled"),
            )
        } else {
            let mut row = check(
                ctx,
                "AppArmor",
                AuditStatus::Warning,
                tr(ctx, "AppArmor module is loaded but not enabled"),
            );
            row.recommendation = Some(tr(ctx, "Enable AppArmor for application sandboxing"));
            row
        };
        row.info_url = Some(URL_APPARMOR.to_owned());
        section.push(row);
        found = true;
    }
    let selinux = run_command("getenforce", &[], COMMAND_TIMEOUT);
    if selinux.code.is_some() {
        let mode = selinux.stdout.trim().to_ascii_lowercase();
        let mut row = match mode.as_str() {
            "enforcing" => check(
                ctx,
                "SELinux",
                AuditStatus::Pass,
                tr(ctx, "SELinux is enforcing"),
            ),
            "permissive" => {
                let mut row = check(
                    ctx,
                    "SELinux",
                    AuditStatus::Warning,
                    tr(ctx, "SELinux is in permissive mode"),
                );
                row.recommendation = Some(tr(
                    ctx,
                    "Consider switching to enforcing mode for stronger protection",
                ));
                row
            }
            "disabled" => {
                let mut row = check(
                    ctx,
                    "SELinux",
                    AuditStatus::Fail,
                    tr(ctx, "SELinux is disabled"),
                );
                row.recommendation = Some(tr(ctx, "Enable SELinux for mandatory access control"));
                row
            }
            _ => return section,
        };
        row.info_url = Some(URL_SELINUX.to_owned());
        section.push(row);
        found = true;
    }
    if !found {
        let mut row = check(
            ctx,
            "MAC Framework",
            AuditStatus::Unknown,
            tr(ctx, "No mandatory access control framework detected"),
        );
        row.recommendation = Some(tr(ctx, "Consider enabling AppArmor or SELinux"));
        section.push(row);
    }
    section
}

fn check_auto_updates(ctx: &Context) -> AuditSection {
    let mut section = AuditSection::new(
        ctx,
        AuditCategory::AutoUpdates,
        "Automatic Updates",
        "software-update-available-symbolic",
    );
    let mut found = false;
    let apt = run_command(
        "apt-config",
        &["dump", "APT::Periodic::Unattended-Upgrade"],
        COMMAND_TIMEOUT,
    );
    if apt.code == Some(0) && !apt.stdout.is_empty() {
        if apt.stdout.contains("\"1\"") || apt.stdout.to_ascii_lowercase().contains("\"true\"") {
            let mut row = check(
                ctx,
                "Unattended Upgrades",
                AuditStatus::Pass,
                tr(ctx, "Automatic security updates are enabled"),
            );
            row.info_url = Some(URL_UNATTENDED.to_owned());
            section.push(row);
            found = true;
        } else if apt.stdout.contains("\"0\"") {
            let mut row = check(
                ctx,
                "Unattended Upgrades",
                AuditStatus::Warning,
                tr(ctx, "Unattended upgrades is installed but disabled"),
            );
            row.recommendation = Some(tr(ctx, "Enable automatic security updates"));
            row.install_command = Some("sudo dpkg-reconfigure unattended-upgrades".to_owned());
            row.info_url = Some(URL_UNATTENDED.to_owned());
            section.push(row);
            found = true;
        }
    }
    if !found && host_binary("dnf").is_some() {
        if service_active("dnf-automatic.timer").0 {
            let mut row = check(
                ctx,
                "DNF Automatic",
                AuditStatus::Pass,
                tr(ctx, "DNF automatic updates are enabled"),
            );
            row.info_url = Some(URL_DNF.to_owned());
            section.push(row);
            found = true;
        } else if service_installed("dnf-automatic.timer") {
            let mut row = check(
                ctx,
                "DNF Automatic",
                AuditStatus::Warning,
                tr(ctx, "DNF automatic is installed but timer is not active"),
            );
            row.recommendation = Some(tr(ctx, "Enable automatic updates"));
            row.install_command =
                Some("sudo systemctl enable --now dnf-automatic.timer".to_owned());
            row.info_url = Some(URL_DNF.to_owned());
            section.push(row);
            found = true;
        }
    }
    if !found {
        let mut row = check(
            ctx,
            "Automatic Updates",
            AuditStatus::Unknown,
            tr(ctx, "Could not determine automatic update status"),
        );
        row.recommendation = Some(tr(ctx, "Configure automatic security updates"));
        row.install_command = install_command("automatic_updates");
        section.push(row);
    }
    let reboot_required = if is_flatpak() {
        command_ok("test", &["-f", "/var/run/reboot-required"])
    } else {
        fs::metadata("/var/run/reboot-required").is_ok()
    };
    if reboot_required {
        let mut row = check(
            ctx,
            "Pending Reboot",
            AuditStatus::Warning,
            tr(ctx, "System reboot required to apply updates"),
        );
        row.recommendation = Some(tr(
            ctx,
            "Reboot the system to apply pending security updates",
        ));
        section.push(row);
    }
    section
}

fn check_intrusion_detection(ctx: &Context) -> AuditSection {
    let mut section = AuditSection::new(
        ctx,
        AuditCategory::IntrusionDetection,
        "Intrusion Detection",
        "dialog-warning-symbolic",
    );
    let mut found = false;
    for (service, binary, name, detail, start, url) in [
        (
            "fail2ban",
            "fail2ban-client",
            "fail2ban",
            "fail2ban is active and protecting services",
            "Start fail2ban to protect against brute force attacks",
            URL_FAIL2BAN,
        ),
        (
            "crowdsec",
            "cscli",
            "CrowdSec",
            "CrowdSec is active with community threat intelligence",
            "Start CrowdSec for collaborative intrusion prevention",
            URL_CROWDSEC,
        ),
    ] {
        if service_active(service).0 {
            let mut row = check(ctx, name, AuditStatus::Pass, tr(ctx, detail));
            row.info_url = Some(url.to_owned());
            section.push(row);
            found = true;
        } else if host_binary(binary).is_some() {
            let mut row = check(
                ctx,
                name,
                AuditStatus::Warning,
                text(
                    ctx,
                    "{name} is installed but not running",
                    &[("{name}", name.to_owned())],
                ),
            );
            row.recommendation = Some(tr(ctx, start));
            row.install_command = Some(format!("sudo systemctl start {service}"));
            row.info_url = Some(url.to_owned());
            section.push(row);
            found = true;
        }
    }
    if !found {
        let mut row = check(
            ctx,
            "Intrusion Prevention",
            AuditStatus::Unknown,
            tr(ctx, "No intrusion detection system found"),
        );
        row.recommendation = Some(tr(
            ctx,
            "Install fail2ban or CrowdSec to protect against attacks",
        ));
        row.install_command = install_command("intrusion_prevention");
        row.info_url = Some(URL_FAIL2BAN.to_owned());
        section.push(row);
    }
    section
}

fn check_ssh_hardening(ctx: &Context) -> AuditSection {
    let mut section = AuditSection::new(
        ctx,
        AuditCategory::SshHardening,
        "SSH Security",
        "network-server-symbolic",
    );
    if !["sshd", "ssh"]
        .iter()
        .any(|service| service_active(service).0)
    {
        let mut row = check(
            ctx,
            "SSH Server",
            AuditStatus::Pass,
            tr(ctx, "SSH server is not running (no remote attack surface)"),
        );
        row.info_url = Some(URL_SSH.to_owned());
        section.push(row);
        return section;
    }
    let mut server = check(
        ctx,
        "SSH Server",
        AuditStatus::Pass,
        tr(ctx, "SSH server is running"),
    );
    server.info_url = Some(URL_SSH.to_owned());
    section.push(server);
    let Some(config) = effective_sshd_config() else {
        let mut row = check(
            ctx,
            "SSH Configuration",
            AuditStatus::Unknown,
            tr(ctx, "Could not read SSH configuration"),
        );
        row.info_url = Some(URL_SSH.to_owned());
        section.push(row);
        return section;
    };
    let root = config
        .get("permitrootlogin")
        .map(String::as_str)
        .unwrap_or("prohibit-password");
    let mut root_row = if matches!(
        root,
        "no" | "prohibit-password" | "without-password" | "forced-commands-only"
    ) {
        check(
            ctx,
            "Root Login",
            AuditStatus::Pass,
            text(ctx, "Root login: {value}", &[("{value}", root.to_owned())]),
        )
    } else {
        let mut row = check(
            ctx,
            "Root Login",
            AuditStatus::Fail,
            text(
                ctx,
                "Root login is allowed ({value})",
                &[("{value}", root.to_owned())],
            ),
        );
        row.recommendation = Some(tr(ctx, "Disable root SSH login for security"));
        row
    };
    root_row.info_url = Some(URL_SSH_ROOT.to_owned());
    section.push(root_row);
    let password = config
        .get("passwordauthentication")
        .map(String::as_str)
        .unwrap_or("yes");
    let mut password_row = if password == "no" {
        check(
            ctx,
            "Password Auth",
            AuditStatus::Pass,
            tr(ctx, "Password authentication is disabled (key-only)"),
        )
    } else {
        let mut row = check(
            ctx,
            "Password Auth",
            AuditStatus::Warning,
            tr(ctx, "Password authentication is enabled"),
        );
        row.recommendation = Some(tr(
            ctx,
            "Consider disabling password auth in favor of SSH keys",
        ));
        row
    };
    password_row.info_url = Some(URL_SSH_ROOT.to_owned());
    section.push(password_row);
    let x11 = config
        .get("x11forwarding")
        .map(String::as_str)
        .unwrap_or("no");
    let mut x11_row = if x11 == "no" {
        check(
            ctx,
            "X11 Forwarding",
            AuditStatus::Pass,
            tr(ctx, "X11 forwarding is disabled"),
        )
    } else {
        let mut row = check(
            ctx,
            "X11 Forwarding",
            AuditStatus::Warning,
            tr(ctx, "X11 forwarding is enabled"),
        );
        row.recommendation = Some(tr(ctx, "Disable X11 forwarding to reduce attack surface"));
        row
    };
    x11_row.info_url = Some(URL_SSH_ROOT.to_owned());
    section.push(x11_row);
    section
}

pub fn parse_sshd_output(content: &str) -> BTreeMap<String, String> {
    let mut settings = BTreeMap::new();
    for line in content.lines() {
        let mut parts = line.split_whitespace();
        let Some(key) = parts.next() else { continue };
        let value = parts.collect::<Vec<_>>().join(" ");
        if !value.is_empty() {
            settings.entry(key.to_ascii_lowercase()).or_insert(value);
        }
    }
    settings
}

pub fn parse_sshd_file(content: &str) -> BTreeMap<String, String> {
    let mut settings = BTreeMap::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let mut parts = line.split_whitespace();
        let Some(key) = parts.next() else { continue };
        if key.eq_ignore_ascii_case("match") {
            break;
        }
        let value = parts.collect::<Vec<_>>().join(" ");
        if !value.is_empty() {
            settings.entry(key.to_ascii_lowercase()).or_insert(value);
        }
    }
    settings
}

fn effective_sshd_config() -> Option<BTreeMap<String, String>> {
    if host_binary("sshd").is_some() {
        let output = run_command("sshd", &["-T"], COMMAND_TIMEOUT);
        if output.code == Some(0) && !output.stdout.is_empty() {
            return Some(parse_sshd_output(&output.stdout));
        }
    }
    let content = if is_flatpak() {
        let output = run_command("cat", &["/etc/ssh/sshd_config"], COMMAND_TIMEOUT);
        (output.code == Some(0)).then_some(output.stdout)
    } else {
        fs::read_to_string("/etc/ssh/sshd_config").ok()
    }?;
    Some(parse_sshd_file(&content))
}

fn check_portmaster(ctx: &Context) -> AuditSection {
    let mut section = AuditSection::new(
        ctx,
        AuditCategory::Portmaster,
        "Portmaster",
        "network-vpn-symbolic",
    );
    let token = crate::credentials::get_portmaster_token(ctx).ok().flatten();
    let result = portmaster::probe(token.as_deref());
    if result.modules_unauthorized {
        let _ = crate::credentials::delete_portmaster_token(ctx);
    }
    match result.status {
        PortmasterStatus::Running => {
            let mut running = check(
                ctx,
                "Portmaster",
                AuditStatus::Pass,
                tr(ctx, "Portmaster is running and protecting connections"),
            );
            running.info_url = Some(URL_PORTMASTER.to_owned());
            section.push(running);
            if !result.module_rows.is_empty() {
                for module in result.module_rows.into_iter().take(8) {
                    let mut row = AuditCheck {
                        name: module.name,
                        status: portmaster_module_status(&module.status),
                        detail: module.failure_msg.unwrap_or(module.status),
                        recommendation: None,
                        install_command: None,
                        info_url: Some(URL_PORTMASTER_API.to_owned()),
                        launch_command: None,
                        launch_label: None,
                    };
                    row.detail = sanitize_line(&row.detail);
                    section.push(row);
                }
            } else if token.is_none() || result.modules_unauthorized {
                let mut row = check(
                    ctx,
                    "Module Status",
                    AuditStatus::Skipped,
                    tr(ctx, "Authorize ClamUI in Portmaster for per-module health"),
                );
                row.launch_command = Some("__portmaster_authorize__".to_owned());
                row.launch_label = Some(tr(ctx, "Authorize"));
                row.info_url = Some(URL_PORTMASTER_API.to_owned());
                section.push(row);
            }
        }
        PortmasterStatus::InstalledNotRunning => {
            let mut row = check(
                ctx,
                "Portmaster",
                AuditStatus::Warning,
                tr(ctx, "Portmaster is installed but not running"),
            );
            row.recommendation = Some(tr(
                ctx,
                "Start the Portmaster service to enable network protection",
            ));
            row.install_command = Some("sudo systemctl start portmaster".to_owned());
            row.info_url = Some(URL_PORTMASTER.to_owned());
            section.push(row);
        }
        PortmasterStatus::NotInstalled => {
            let mut row = check(
                ctx,
                "Portmaster",
                AuditStatus::Skipped,
                tr(
                    ctx,
                    // Translators: The em dash separates the detection result from the component description.
                    "Not detected — optional network monitor and application firewall",
                ),
            );
            row.info_url = Some(URL_PORTMASTER_INSTALL.to_owned());
            section.push(row);
        }
        PortmasterStatus::Error => {
            let mut row = check(
                ctx,
                "Portmaster",
                AuditStatus::Unknown,
                text(
                    ctx,
                    "Could not probe Portmaster: {error}",
                    &[("{error}", result.error.unwrap_or_default())],
                ),
            );
            row.info_url = Some(URL_PORTMASTER_API.to_owned());
            section.push(row);
        }
    }
    section
}

pub fn portmaster_module_status(status: &str) -> AuditStatus {
    match status.trim().to_ascii_lowercase().as_str() {
        "online" | "ready" | "active" | "ok" => AuditStatus::Pass,
        "error" | "failed" | "failure" => AuditStatus::Fail,
        "warning" | "degraded" => AuditStatus::Warning,
        _ => AuditStatus::Unknown,
    }
}

fn run_deep(ctx: &Context, tool: &str) -> AuditSection {
    let (category, title, name, executable, arguments, target, url) = match tool {
        "lynis" => (
            AuditCategory::DeepScanLynis,
            "Lynis Security Audit",
            "Lynis",
            "lynis",
            vec!["audit", "system", "--cronjob", "--quiet"],
            "lynis",
            URL_LYNIS,
        ),
        "chkrootkit" => (
            AuditCategory::DeepScanRootkit,
            "Rootkit Detection",
            "chkrootkit",
            "chkrootkit",
            vec!["-q"],
            "chkrootkit",
            URL_CHKROOTKIT,
        ),
        _ => return unknown_deep(ctx, tool),
    };
    let mut section = AuditSection::new(ctx, category, title, "system-run-symbolic");
    let Some(path) = host_binary(executable) else {
        let mut row = check(
            ctx,
            name,
            AuditStatus::Unknown,
            text(
                ctx,
                "{name} is not installed",
                &[("{name}", name.to_owned())],
            ),
        );
        row.recommendation = Some(text(
            ctx,
            "Install {name} for comprehensive security auditing",
            &[("{name}", name.to_owned())],
        ));
        if tool == "chkrootkit" {
            row.recommendation = Some(tr(ctx, "Install chkrootkit for rootkit detection"));
        }
        row.install_command = install_command(target);
        row.info_url = Some(url.to_owned());
        section.push(row);
        return section;
    };
    let mut command = vec![path.as_str()];
    command.extend(arguments.iter().copied());
    let output = run_command("pkexec", &command, DEEP_SCAN_TIMEOUT);
    if matches!(output.code, Some(126 | 127)) {
        let mut row = check(
            ctx,
            if tool == "lynis" {
                "Lynis Audit"
            } else {
                "Rootkit Scan"
            },
            AuditStatus::Skipped,
            tr(ctx, "Authentication was cancelled"),
        );
        row.info_url = Some(url.to_owned());
        section.push(row);
        return section;
    }
    if output.code.is_none() && output.stderr == "command timed out" {
        let detail = if tool == "lynis" {
            tr(ctx, "Lynis audit timed out after 5 minutes")
        } else {
            tr(ctx, "Rootkit scan timed out after 5 minutes")
        };
        let mut row = check(
            ctx,
            if tool == "lynis" {
                "Lynis Audit"
            } else {
                "Rootkit Scan"
            },
            AuditStatus::Fail,
            detail,
        );
        row.info_url = Some(url.to_owned());
        section.push(row);
        return section;
    }
    if output.code.is_none() {
        let detail = if tool == "lynis" {
            text(
                ctx,
                "Failed to run Lynis: {error}",
                &[("{error}", output.stderr)],
            )
        } else {
            text(
                ctx,
                "Failed to run chkrootkit: {error}",
                &[("{error}", output.stderr)],
            )
        };
        let mut row = check(
            ctx,
            if tool == "lynis" {
                "Lynis Audit"
            } else {
                "Rootkit Scan"
            },
            AuditStatus::Unknown,
            detail,
        );
        row.info_url = Some(url.to_owned());
        section.push(row);
        return section;
    }
    if tool == "lynis" {
        deep_lynis(ctx, section, output, url)
    } else {
        deep_rootkit(ctx, section, output, url)
    }
}

fn unknown_deep(ctx: &Context, tool: &str) -> AuditSection {
    let mut section = AuditSection::new(
        ctx,
        AuditCategory::DeepScanLynis,
        "Lynis Security Audit",
        "system-run-symbolic",
    );
    section.push(check(
        ctx,
        "Lynis Audit",
        AuditStatus::Unknown,
        text(
            ctx,
            "Failed to run Lynis: {error}",
            &[("{error}", sanitize_line(tool))],
        ),
    ));
    section
}

fn deep_lynis(
    ctx: &Context,
    mut section: AuditSection,
    output: CommandOutput,
    url: &str,
) -> AuditSection {
    let score = lynis_score();
    let mut row = if let Some(score) = score {
        let status = if score >= 70 {
            AuditStatus::Pass
        } else if score >= 50 {
            AuditStatus::Warning
        } else {
            AuditStatus::Fail
        };
        let mut row = check(
            ctx,
            "Hardening Index",
            status,
            text(ctx, "Score: {score}/100", &[("{score}", score.to_string())]),
        );
        if status != AuditStatus::Pass {
            row.recommendation = Some(tr(
                ctx,
                // Translators: Keep the quoted shell command unchanged.
                "Run 'sudo lynis audit system' for detailed recommendations",
            ));
        }
        row
    } else {
        check(
            ctx,
            "Lynis Audit",
            if output.code == Some(0) {
                AuditStatus::Pass
            } else {
                AuditStatus::Warning
            },
            text(
                ctx,
                "Audit completed (exit code {code})",
                &[(
                    "{code}",
                    output
                        .code
                        .map(|code| code.to_string())
                        .unwrap_or_else(|| "unknown".to_owned()),
                )],
            ),
        )
    };
    row.info_url = Some(url.to_owned());
    section.push(row);
    section
}

fn lynis_score() -> Option<i32> {
    let content = if is_flatpak() {
        let output = run_command("cat", &["/var/log/lynis-report.dat"], COMMAND_TIMEOUT);
        (output.code == Some(0)).then_some(output.stdout)
    } else {
        fs::read_to_string("/var/log/lynis-report.dat").ok()
    }?;
    content
        .lines()
        .find_map(|line| line.strip_prefix("hardening_index=")?.trim().parse().ok())
}

fn deep_rootkit(
    ctx: &Context,
    mut section: AuditSection,
    output: CommandOutput,
    url: &str,
) -> AuditSection {
    if output.code != Some(0) {
        let detail = if output.stderr.is_empty() {
            text(
                ctx,
                "Rootkit scan could not be completed (exit {code})",
                &[(
                    "{code}",
                    output
                        .code
                        .map(|code| code.to_string())
                        .unwrap_or_else(|| "unknown".to_owned()),
                )],
            )
        } else {
            format!(
                "{}: {}",
                text(
                    ctx,
                    "Rootkit scan could not be completed (exit {code})",
                    &[(
                        "{code}",
                        output
                            .code
                            .map(|code| code.to_string())
                            .unwrap_or_else(|| "unknown".to_owned())
                    )]
                ),
                output.stderr
            )
        };
        let mut row = check(ctx, "Rootkit Scan", AuditStatus::Unknown, detail);
        row.info_url = Some(url.to_owned());
        section.push(row);
        return section;
    }
    let findings = output
        .stdout
        .lines()
        .filter(|line| line.contains("INFECTED"))
        .map(sanitize_line)
        .collect::<Vec<_>>();
    if findings.is_empty() {
        let mut row = check(
            ctx,
            "Rootkit Scan",
            AuditStatus::Pass,
            tr(ctx, "No rootkits detected"),
        );
        row.info_url = Some(url.to_owned());
        section.push(row);
        return section;
    }
    let count = findings.len() as u64;
    let mut row = check(
        ctx,
        "Rootkit Scan",
        AuditStatus::Fail,
        trnf(
            ctx,
            "{count} potential rootkit detected",
            "{count} potential rootkits detected",
            count,
            &[("{count}", count.to_string())],
        ),
    );
    row.recommendation = Some(tr(ctx, "Investigate the detected threats immediately"));
    row.info_url = Some(url.to_owned());
    section.push(row);
    for finding in findings.into_iter().take(5) {
        let mut row = check(ctx, "Finding", AuditStatus::Fail, finding);
        row.info_url = Some(url.to_owned());
        section.push(row);
    }
    section
}

fn run_tier1(ctx: &Context) -> AuditReport {
    let checks: [fn(&Context) -> AuditSection; 7] = [
        check_clamav_health,
        check_firewall,
        check_mac_framework,
        check_auto_updates,
        check_intrusion_detection,
        check_ssh_hardening,
        check_portmaster,
    ];
    let mut sections = Vec::with_capacity(checks.len());
    for (index, audit) in checks.into_iter().enumerate() {
        let section = audit(ctx);
        ctx.emit(
            "audit-progress",
            json!({"section": section, "index": index, "total": 7}),
        );
        sections.push(section);
    }
    AuditReport {
        sections,
        timestamp: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_secs_f64())
            .unwrap_or_default(),
    }
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "run" => serde_json::to_value(run_tier1(ctx)).map_err(|error| error.to_string()),
        "deep" => {
            let tool = args
                .get("tool")
                .and_then(Value::as_str)
                .ok_or_else(|| "audit.deep requires tool 'lynis' or 'chkrootkit'".to_owned())?;
            if !matches!(tool, "lynis" | "chkrootkit") {
                return Err("audit.deep requires tool 'lynis' or 'chkrootkit'".to_owned());
            }
            let section = run_deep(ctx, tool);
            ctx.emit(
                "audit-progress",
                json!({"section": section, "index": 0, "total": 1}),
            );
            serde_json::to_value(section).map_err(|error| error.to_string())
        }
        "portmaster_authorize" => {
            let authorization = portmaster::request_app_token();
            if authorization.cancelled {
                return Ok(json!({"authorized": false, "cancelled": true}));
            }
            if let Some(error) = authorization.error {
                return Ok(json!({"authorized": false, "cancelled": false, "message": error}));
            }
            if let Some(token) = authorization.token {
                crate::credentials::set_portmaster_token(ctx, &token)?;
                return Ok(json!({"authorized": true, "cancelled": false}));
            }
            Ok(json!({"authorized": false, "cancelled": false, "message": "No token in response"}))
        }
        "launch" => {
            let command = args
                .get("command")
                .and_then(Value::as_str)
                .ok_or_else(|| "audit.launch requires an allowlisted command".to_owned())?;
            portmaster::launch(command).map(|launched| json!({"launched": launched}))
        }
        _ => Err(format!("Unknown audit action: {action}")),
    }
}
