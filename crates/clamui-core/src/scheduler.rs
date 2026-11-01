use crate::common::{host_command, is_flatpak, Context};
use crate::{host, i18n, logs, quarantine, scanner, AppResult};
use chrono::Local;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::env;
use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{Duration, Instant};

pub const SERVICE_NAME: &str = "clamui-scheduled-scan";
pub const TIMER_NAME: &str = "clamui-scheduled-scan";
pub const CRON_MARKER: &str = "# ClamUI Scheduled Scan";

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum SchedulerBackend {
    Systemd,
    Cron,
    None,
}

impl SchedulerBackend {
    fn as_str(self) -> &'static str {
        match self {
            Self::Systemd => "systemd",
            Self::Cron => "cron",
            Self::None => "none",
        }
    }
}
#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum ScheduleFrequency {
    Hourly,
    #[default]
    Daily,
    Weekly,
    Monthly,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ScheduleConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub frequency: ScheduleFrequency,
    #[serde(default = "default_time")]
    pub time: String,
    #[serde(default)]
    pub targets: Vec<String>,
    #[serde(default = "default_skip_on_battery")]
    pub skip_on_battery: bool,
    #[serde(default)]
    pub auto_quarantine: bool,
    #[serde(default)]
    pub day_of_week: i64,
    #[serde(default = "default_day_of_month")]
    pub day_of_month: i64,
}

fn default_time() -> String {
    "02:00".to_owned()
}
fn default_skip_on_battery() -> bool {
    true
}
fn default_day_of_month() -> i64 {
    1
}

impl Default for ScheduleConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            frequency: ScheduleFrequency::Daily,
            time: default_time(),
            targets: Vec::new(),
            skip_on_battery: true,
            auto_quarantine: false,
            day_of_week: 0,
            day_of_month: 1,
        }
    }
}

impl ScheduleConfig {
    /// Accept the persisted Python setting names as well as the normalized IPC names.
    pub fn from_value(value: &Value) -> AppResult<Self> {
        let object = value
            .as_object()
            .ok_or_else(|| "Schedule must be an object".to_string())?;
        let frequency = value_string(object, "frequency", "schedule_frequency")
            .unwrap_or_else(|| "daily".to_owned())
            .parse::<ScheduleFrequency>()?;
        Ok(Self {
            enabled: value_bool(object, "enabled", "scheduled_scans_enabled").unwrap_or(false),
            frequency,
            time: value_string(object, "time", "schedule_time").unwrap_or_else(default_time),
            targets: value_strings(object, "targets", "schedule_targets")?,
            skip_on_battery: value_bool(object, "skip_on_battery", "schedule_skip_on_battery")
                .unwrap_or(true),
            auto_quarantine: value_bool(object, "auto_quarantine", "schedule_auto_quarantine")
                .unwrap_or(false),
            day_of_week: value_integer(object, "day_of_week", "schedule_day_of_week").unwrap_or(0),
            day_of_month: value_integer(object, "day_of_month", "schedule_day_of_month")
                .unwrap_or(1),
        })
    }
}

impl std::str::FromStr for ScheduleFrequency {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.to_ascii_lowercase().as_str() {
            "hourly" => Ok(Self::Hourly),
            "daily" => Ok(Self::Daily),
            "weekly" => Ok(Self::Weekly),
            "monthly" => Ok(Self::Monthly),
            _ => Err(format!("Invalid frequency: {value}")),
        }
    }
}

pub fn dispatch(ctx: &Context, action: &str, args: Value) -> AppResult<Value> {
    match action {
        "status" => status(ctx),
        "preview" => {
            let schedule = schedule_argument(&args)?;
            preview(ctx, &schedule)
        }
        "apply" => {
            let schedule = schedule_argument(&args)?;
            apply(ctx, &schedule)
        }
        _ => Err(format!("Unknown scheduler action: {action}")),
    }
}

/// Parse aliases and validate a detached schedule without reading or writing
/// settings, scheduler state, configuration files, or host paths. Config save
/// calls this before its first durable mutation and passes the same typed
/// proposal to `apply`.
pub fn normalize_schedule(value: &Value) -> AppResult<ScheduleConfig> {
    let mut schedule = ScheduleConfig::from_value(value)?;
    let (hour, minute) = parse_time(&schedule.time);
    schedule.time = format!("{hour:02}:{minute:02}");
    schedule.day_of_week = schedule.day_of_week.rem_euclid(7);
    schedule.day_of_month = schedule.day_of_month.clamp(1, 28);
    validate_schedule(&schedule)?;
    Ok(schedule)
}

fn schedule_argument(args: &Value) -> AppResult<ScheduleConfig> {
    let schedule = args
        .as_object()
        .and_then(|object| object.get("schedule"))
        .unwrap_or(args);
    normalize_schedule(schedule)
}

pub fn status(_ctx: &Context) -> AppResult<Value> {
    let backend = detect_backend();
    let status = match backend {
        SchedulerBackend::Systemd => systemd_status(),
        SchedulerBackend::Cron => cron_status(),
        SchedulerBackend::None => {
            return Ok(json!({
                "backend": "none", "available": false, "active": false, "next_run": Value::Null,
                "error": "No scheduler backend available"
            }));
        }
    };
    status.or_else(|error| Ok(json!({
        "backend": backend.as_str(), "available": true, "active": false, "next_run": Value::Null,
        "error": error
    })))
}

pub fn preview(_ctx: &Context, schedule: &ScheduleConfig) -> AppResult<Value> {
    validate_schedule(schedule)?;
    let backend = detect_backend();
    let command = launcher_command()
        .ok_or_else(|| "Could not find clamui-scheduled-scan command".to_string())?;
    let calendar = on_calendar(
        schedule.frequency,
        &schedule.time,
        schedule.day_of_week,
        schedule.day_of_month,
    );
    let cron = cron_expression(
        schedule.frequency,
        &schedule.time,
        schedule.day_of_week,
        schedule.day_of_month,
    );
    Ok(json!({
        "backend": backend.as_str(),
        "available": backend != SchedulerBackend::None,
        "enabled": schedule.enabled,
        "calendar": calendar,
        "cron": cron,
        "service": service_file(&command, schedule),
        "timer": timer_file(&calendar),
    }))
}

/// Provision only the operating-system schedule. Settings persistence belongs to config.save/apply,
/// so a failed systemd/cron operation can never silently claim a durable preference update.
pub fn apply(ctx: &Context, schedule: &ScheduleConfig) -> AppResult<Value> {
    validate_schedule(schedule)?;
    let backend = detect_backend();
    if !schedule.enabled {
        return disable(ctx, backend);
    }
    if backend == SchedulerBackend::None {
        return Ok(provision_result(
            false,
            false,
            schedule.enabled,
            backend,
            Some("No scheduler backend available"),
        ));
    }
    let result = match backend {
        SchedulerBackend::Systemd => enable_systemd(ctx, schedule),
        SchedulerBackend::Cron => enable_cron(schedule),
        SchedulerBackend::None => unreachable!(),
    };
    match result {
        Ok(()) => Ok(provision_result(true, true, true, backend, None)),
        Err(error) => Ok(provision_result(false, false, true, backend, Some(&error))),
    }
}

fn disable(ctx: &Context, backend: SchedulerBackend) -> AppResult<Value> {
    let result = match backend {
        SchedulerBackend::Systemd => disable_systemd(ctx),
        SchedulerBackend::Cron => disable_cron(),
        SchedulerBackend::None => Ok(()),
    };
    match result {
        Ok(()) => Ok(provision_result(true, true, false, backend, None)),
        Err(error) => Ok(provision_result(false, false, false, backend, Some(&error))),
    }
}

fn provision_result(
    success: bool,
    durable: bool,
    enabled: bool,
    backend: SchedulerBackend,
    error: Option<&str>,
) -> Value {
    let mut value = json!({"success": success, "durable": durable, "enabled": enabled, "backend": backend.as_str()});
    if let Some(error) = error {
        value["error"] = Value::String(error.to_owned());
    }
    value
}

fn systemd_dir(ctx: &Context) -> PathBuf {
    if is_flatpak() {
        ctx.paths.home.join(".config/systemd/user")
    } else {
        ctx.paths
            .config_dir
            .parent()
            .unwrap_or(ctx.paths.config_dir.as_path())
            .join("systemd/user")
    }
}

fn detect_backend() -> SchedulerBackend {
    if is_flatpak() || systemctl_available() {
        SchedulerBackend::Systemd
    } else if host_program_available("crontab") {
        SchedulerBackend::Cron
    } else {
        SchedulerBackend::None
    }
}

fn systemctl_available() -> bool {
    if !host_program_available("systemctl") {
        return false;
    }
    run_host("systemctl", &["--user", "status"]).is_ok_and(|output| output.status.success())
}

fn host_program_available(program: &str) -> bool {
    if is_flatpak() {
        return true;
    }
    find_on_path(program).is_some()
}

fn run_host(program: &str, args: &[&str]) -> AppResult<std::process::Output> {
    let owned = args
        .iter()
        .map(|value| (*value).to_owned())
        .collect::<Vec<_>>();
    host_command(program, &owned)
        .stdin(Stdio::piped())
        .output()
        .map_err(|error| format!("Could not run {program}: {error}"))
}

fn enable_systemd(ctx: &Context, schedule: &ScheduleConfig) -> AppResult<()> {
    let command = launcher_command()
        .ok_or_else(|| "Could not find clamui-scheduled-scan command".to_string())?;
    let dir = systemd_dir(ctx);
    fs::create_dir_all(&dir).map_err(|error| format!("Error creating systemd files: {error}"))?;
    fs::write(
        dir.join(format!("{SERVICE_NAME}.service")),
        service_file(&command, schedule),
    )
    .map_err(|error| format!("Error creating systemd files: {error}"))?;
    fs::write(
        dir.join(format!("{TIMER_NAME}.timer")),
        timer_file(&on_calendar(
            schedule.frequency,
            &schedule.time,
            schedule.day_of_week,
            schedule.day_of_month,
        )),
    )
    .map_err(|error| format!("Error creating systemd files: {error}"))?;
    let _ = run_host("systemctl", &["--user", "daemon-reload"])?;
    let timer = format!("{TIMER_NAME}.timer");
    let output = run_host("systemctl", &["--user", "enable", "--now", &timer])?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "Failed to enable timer: {}",
            output_message(&output)
        ))
    }
}

fn disable_systemd(ctx: &Context) -> AppResult<()> {
    let timer = format!("{TIMER_NAME}.timer");
    let _ = run_host("systemctl", &["--user", "disable", "--now", &timer]);
    let dir = systemd_dir(ctx);
    for name in [
        format!("{SERVICE_NAME}.service"),
        format!("{TIMER_NAME}.timer"),
    ] {
        let path = dir.join(name);
        if path.exists() {
            fs::remove_file(&path)
                .map_err(|error| format!("Error removing systemd files: {error}"))?;
        }
    }
    let _ = run_host("systemctl", &["--user", "daemon-reload"])?;
    Ok(())
}

fn systemd_status() -> AppResult<Value> {
    let timer = format!("{TIMER_NAME}.timer");
    let active = run_host("systemctl", &["--user", "is-active", &timer])
        .is_ok_and(|output| output.status.success());
    if !active {
        return Ok(
            json!({"backend":"systemd", "available":true, "active":false, "next_run":Value::Null}),
        );
    }
    let next = run_host(
        "systemctl",
        &[
            "--user",
            "show",
            &timer,
            "--property=NextElapseUSecRealtime",
        ],
    )
    .ok()
    .filter(|output| output.status.success())
    .and_then(|output| String::from_utf8(output.stdout).ok())
    .and_then(|output| {
        output
            .trim()
            .split_once('=')
            .map(|(_, value)| value.to_owned())
    })
    .filter(|value| !value.is_empty());
    Ok(json!({"backend":"systemd", "available":true, "active":true, "next_run":next}))
}

fn cron_status() -> AppResult<Value> {
    let output = run_host("crontab", &["-l"])?;
    let active = output.status.success()
        && String::from_utf8_lossy(&output.stdout)
            .lines()
            .any(|line| line.trim() == CRON_MARKER);
    Ok(json!({"backend":"cron", "available":true, "active":active, "next_run":Value::Null}))
}

fn enable_cron(schedule: &ScheduleConfig) -> AppResult<()> {
    let command = launcher_command()
        .ok_or_else(|| "Could not find clamui-scheduled-scan command".to_string())?;
    let existing = run_host("crontab", &["-l"])
        .ok()
        .filter(|output| output.status.success())
        .map(|output| String::from_utf8_lossy(&output.stdout).into_owned())
        .unwrap_or_default();
    let mut lines = remove_our_cron_lines(&existing);
    lines.push(CRON_MARKER.to_owned());
    lines.push(format!(
        "{} {}",
        cron_expression(
            schedule.frequency,
            &schedule.time,
            schedule.day_of_week,
            schedule.day_of_month
        ),
        cron_command(&command, schedule)
    ));
    install_crontab(&format!("{}\n", lines.join("\n")))
}

fn disable_cron() -> AppResult<()> {
    let output = run_host("crontab", &["-l"])?;
    if !output.status.success() {
        return Ok(());
    }
    let existing = String::from_utf8_lossy(&output.stdout);
    let lines = remove_our_cron_lines(&existing);
    // Never invoke `crontab -r`: an unrelated/user-owned crontab must not be deleted.
    install_crontab(&format!("{}\n", lines.join("\n")))
}

fn install_crontab(content: &str) -> AppResult<()> {
    let owned: Vec<String> = vec!["-".to_owned()];
    let output = host_command("crontab", &owned)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("Could not run crontab: {error}"))?;
    let mut child = output;
    use std::io::Write;
    child
        .stdin
        .take()
        .ok_or_else(|| "Could not write crontab".to_string())?
        .write_all(content.as_bytes())
        .map_err(|error| format!("Could not write crontab: {error}"))?;
    let output = child
        .wait_with_output()
        .map_err(|error| format!("Could not update crontab: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "Failed to update crontab: {}",
            output_message(&output)
        ))
    }
}

pub fn validate_target_paths(targets: &[String]) -> AppResult<()> {
    for target in targets {
        if target.contains('\n') || target.contains('\r') {
            return Err(format!(
                "Invalid path contains newline characters: {target}"
            ));
        }
        if target.contains('\0') {
            return Err(format!("Invalid path contains null bytes: {target}"));
        }
    }
    Ok(())
}

pub fn on_calendar(
    frequency: ScheduleFrequency,
    time: &str,
    day_of_week: i64,
    day_of_month: i64,
) -> String {
    let (hour, minute) = parse_time(time);
    match frequency {
        ScheduleFrequency::Hourly => "*-*-* *:00:00".to_owned(),
        ScheduleFrequency::Daily => format!("*-*-* {hour:02}:{minute:02}:00"),
        ScheduleFrequency::Weekly => {
            let days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
            format!(
                "{} *-*-* {hour:02}:{minute:02}:00",
                days[day_of_week.rem_euclid(7) as usize]
            )
        }
        ScheduleFrequency::Monthly => format!(
            "*-*-{:02} {hour:02}:{minute:02}:00",
            day_of_month.clamp(1, 28)
        ),
    }
}

pub fn cron_expression(
    frequency: ScheduleFrequency,
    time: &str,
    day_of_week: i64,
    day_of_month: i64,
) -> String {
    let (hour, minute) = parse_time(time);
    match frequency {
        ScheduleFrequency::Hourly => "0 * * * *".to_owned(),
        ScheduleFrequency::Daily => format!("{minute} {hour} * * *"),
        ScheduleFrequency::Weekly => {
            format!("{minute} {hour} * * {}", (day_of_week + 1).rem_euclid(7))
        }
        ScheduleFrequency::Monthly => format!("{minute} {hour} {} * *", day_of_month.clamp(1, 28)),
    }
}

fn parse_time(time: &str) -> (u8, u8) {
    let Some((hour, minute)) = time.split_once(':') else {
        return (2, 0);
    };
    let (Ok(hour), Ok(minute)) = (hour.parse::<u8>(), minute.parse::<u8>()) else {
        return (2, 0);
    };
    if hour <= 23 && minute <= 59 {
        (hour, minute)
    } else {
        (2, 0)
    }
}

fn validate_schedule(schedule: &ScheduleConfig) -> AppResult<()> {
    // Match the existing scheduler: malformed times fall back to 02:00 during
    // calendar generation rather than preventing a user from repairing a
    // previously persisted setting.
    validate_target_paths(&schedule.targets)
}

pub fn service_file(command: &[String], schedule: &ScheduleConfig) -> String {
    let command = command
        .iter()
        .map(|part| shell_quote(part))
        .collect::<Vec<_>>()
        .join(" ");
    let mut arguments = String::new();
    if schedule.skip_on_battery {
        arguments.push_str(" --skip-on-battery");
    }
    if schedule.auto_quarantine {
        arguments.push_str(" --auto-quarantine");
    }
    for target in &schedule.targets {
        arguments.push_str(" --target ");
        arguments.push_str(&shell_quote(target));
    }
    // Systemd specifier expansion applies to the whole ExecStart line, while
    // environment expansion only changes arguments. Do not corrupt a launcher
    // path containing a literal dollar sign.
    let command = format!(
        "{}{}",
        command.replace('%', "%%"),
        arguments.replace('$', "$$").replace('%', "%%")
    );
    format!("[Unit]\nDescription=ClamUI Scheduled Antivirus Scan\nAfter=network.target\n\n[Service]\nType=oneshot\nExecStart={command}\nNice=19\nIOSchedulingClass=idle\n\n[Install]\nWantedBy=default.target\n")
}

pub fn timer_file(calendar: &str) -> String {
    format!("[Unit]\nDescription=ClamUI Scheduled Scan Timer\n\n[Timer]\nOnCalendar={calendar}\nPersistent=true\nRandomizedDelaySec=300\n\n[Install]\nWantedBy=timers.target\n")
}

pub fn cron_command(command: &[String], schedule: &ScheduleConfig) -> String {
    let mut command = command
        .iter()
        .map(|part| cron_quote(part))
        .collect::<Vec<_>>()
        .join(" ");
    if schedule.skip_on_battery {
        command.push_str(" --skip-on-battery");
    }
    if schedule.auto_quarantine {
        command.push_str(" --auto-quarantine");
    }
    for target in &schedule.targets {
        command.push_str(" --target ");
        command.push_str(&cron_quote(target));
    }
    command
}

fn shell_quote(word: &str) -> String {
    if !word.is_empty()
        && word
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"@%_+=:,./-".contains(&byte))
    {
        return word.to_owned();
    }
    format!("'{}'", word.replace('\'', "'\"'\"'"))
}

fn cron_quote(word: &str) -> String {
    word.split('%')
        .map(shell_quote)
        .collect::<Vec<_>>()
        .join("\\%")
}

pub fn remove_our_cron_lines(existing: &str) -> Vec<String> {
    let mut lines = Vec::new();
    let mut next_is_paired = false;
    for line in existing.lines() {
        if next_is_paired {
            next_is_paired = false;
            if !is_clamui_cron_command(line) {
                lines.push(line.to_owned());
            }
            continue;
        }
        if line.trim() == CRON_MARKER {
            next_is_paired = true;
        } else {
            lines.push(line.to_owned());
        }
    }
    lines
}

pub fn is_clamui_cron_command(line: &str) -> bool {
    let words = shell_words(line);
    if words.len() <= 5 {
        return false;
    }
    let command = &words[5..];
    // AppImage schedules the stable root dispatcher rather than the transient
    // helper mounted beneath /tmp/.mount*. Its original filename is user-owned,
    // so the explicit dispatcher flag is the durable identity.
    if command
        .get(1)
        .is_some_and(|argument| argument == "--scheduled-scan")
    {
        return true;
    }
    if Path::new(&command[0]).file_name() == Some(OsStr::new("clamui-scheduled-scan")) {
        return true;
    }
    if command[0] == "flatpak"
        && command[1..]
            .iter()
            .any(|word| word == "--command=clamui-scheduled-scan")
    {
        return true;
    }
    let interpreter = Path::new(&command[0])
        .file_name()
        .and_then(OsStr::to_str)
        .unwrap_or_default();
    if interpreter != "python"
        && !(interpreter.starts_with("python")
            && interpreter[6..]
                .chars()
                .all(|character| character.is_ascii_digit() || character == '.'))
    {
        return false;
    }
    command.windows(2).any(|window| {
        window == ["-m", "src.cli.scheduled_scan"] || window == ["-m", "clamui.cli.scheduled_scan"]
    })
}

#[derive(Clone, Copy)]
enum ShellQuote {
    Single,
    Double,
}

fn shell_words(input: &str) -> Vec<String> {
    let mut words = Vec::new();
    let mut word = String::new();
    let mut quote = None;
    let mut escaped = false;
    for character in input.chars() {
        if escaped {
            word.push(character);
            escaped = false;
            continue;
        }
        match (quote, character) {
            (Some(ShellQuote::Single), '\'') => quote = None,
            (Some(ShellQuote::Single), _) => word.push(character),
            (Some(ShellQuote::Double), '\"') => quote = None,
            (Some(ShellQuote::Double), '\\') => escaped = true,
            (Some(ShellQuote::Double), _) => word.push(character),
            (None, '\'') => quote = Some(ShellQuote::Single),
            (None, '\"') => quote = Some(ShellQuote::Double),
            (None, '\\') => escaped = true,
            (None, character) if character.is_whitespace() => {
                if !word.is_empty() {
                    words.push(std::mem::take(&mut word));
                }
            }
            (None, _) => word.push(character),
        }
    }
    if escaped {
        word.push('\\');
    }
    if !word.is_empty() {
        words.push(word);
    }
    words
}

fn launcher_command() -> Option<Vec<String>> {
    if is_flatpak() {
        let app_id =
            env::var("FLATPAK_ID").unwrap_or_else(|_| "io.github.linx_systems.ClamUI".to_owned());
        return Some(vec![
            "flatpak".to_owned(),
            "run".to_owned(),
            "--command=clamui-scheduled-scan".to_owned(),
            app_id,
        ]);
    }
    if let Some(appimage) = env::var_os("APPIMAGE")
        .map(PathBuf::from)
        .filter(|path| path.is_file())
    {
        // The helper inside an AppImage lives below a transient /tmp/.mount*
        // path. Persist the original image and enter its root CLI dispatcher.
        return Some(vec![
            appimage.display().to_string(),
            "--scheduled-scan".to_owned(),
        ]);
    }
    if let Some(path) = find_on_path("clamui-scheduled-scan") {
        return Some(vec![path.display().to_string()]);
    }
    if let Ok(current) = env::current_exe() {
        if let Some(parent) = current.parent() {
            let sibling = parent.join("clamui-scheduled-scan");
            if sibling.is_file() {
                return Some(vec![sibling.display().to_string()]);
            }
        }
    }
    let home = env::var_os("HOME").map(PathBuf::from);
    let candidates = [
        home.map(|home| home.join(".local/bin/clamui-scheduled-scan")),
        Some(PathBuf::from("/usr/local/bin/clamui-scheduled-scan")),
        Some(PathBuf::from("/usr/bin/clamui-scheduled-scan")),
    ];
    candidates
        .into_iter()
        .flatten()
        .find(|path| path.is_file())
        .map(|path| vec![path.display().to_string()])
}

fn find_on_path(program: &str) -> Option<PathBuf> {
    env::var_os("PATH")?
        .to_string_lossy()
        .split(':')
        .map(PathBuf::from)
        .map(|directory| directory.join(program))
        .find(|path| path.is_file())
}

fn output_message(output: &std::process::Output) -> String {
    String::from_utf8_lossy(&output.stderr).trim().to_owned()
}

fn trn(ctx: &Context, singular: &str, plural: &str, count: u64) -> String {
    i18n::translate_plural(ctx, singular, plural, count)
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

/// Standalone `clamui-scheduled-scan` implementation. Arguments omit argv0.
pub fn run_scheduled(args: &[String]) -> i32 {
    let headless = match crate::headless::HeadlessContext::new() {
        Ok(headless) => headless,
        Err(error) => {
            scheduled_log(&error, false);
            return 2;
        }
    };
    let result = run_scheduled_inner(args, headless.context().clone());
    if headless.context().interrupted() {
        scheduled_log(
            &i18n::translate(headless.context(), "Scheduled scan cancelled"),
            false,
        );
        return 130;
    }
    match result {
        Ok(code) => code,
        Err(error) => {
            scheduled_log(&error, false);
            2
        }
    }
}

fn run_scheduled_inner(args: &[String], ctx: Context) -> AppResult<i32> {
    let options = ScheduledOptions::parse(args)?;
    if options.help {
        println!(
            "{}",
            i18n::translate(
                &ctx,
                // Translators: Keep `clamui-scheduled-scan`, flags, `PATH`, and command syntax unchanged; translate the `Usage:` label.
                "Usage: clamui-scheduled-scan [--skip-on-battery] [--auto-quarantine] [--target PATH] [--dry-run] [--verbose|-v]",
            )
        );
        return Ok(0);
    }
    if ctx.interrupted() {
        return Ok(130);
    }
    let settings = ctx.settings()?;
    let skip_on_battery = options.skip_on_battery.unwrap_or_else(|| {
        settings
            .get("schedule_skip_on_battery")
            .and_then(Value::as_bool)
            .unwrap_or(true)
    });
    let auto_quarantine = options.auto_quarantine.unwrap_or_else(|| {
        settings
            .get("schedule_auto_quarantine")
            .and_then(Value::as_bool)
            .unwrap_or(false)
    });
    let targets = if options.targets.is_empty() {
        settings
            .get("schedule_targets")
            .and_then(Value::as_array)
            .map(|values| {
                values
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::to_owned)
                    .collect::<Vec<_>>()
            })
            .filter(|values| !values.is_empty())
            .unwrap_or_else(|| vec![ctx.paths.home.display().to_string()])
    } else {
        options.targets
    };
    scheduled_log(
        &i18n::translate(
            &ctx,
            // Translators: The ellipsis indicates that the scheduled scan is starting.
            "ClamUI scheduled scan starting…",
        ),
        false,
    );
    let battery = host::battery_observation();
    if skip_on_battery && battery.on_battery {
        let skipped_summary = i18n::translate(&ctx, "Scheduled scan skipped (on battery power)");
        let skipped_details = battery_skip_details(&ctx, battery.charge_percent);
        let skip_message = battery_skip_message(&ctx, battery.charge_percent);
        let _ = logs::dispatch(
            &ctx,
            "create",
            json!({"type":"scan", "status":"skipped", "summary":skipped_summary, "details":skipped_details, "path":targets.join(", "), "scheduled":true}),
        );
        scheduled_log(&skip_message, false);
        return Ok(0);
    }
    let valid = targets
        .into_iter()
        .filter(|target| {
            let expanded = expand_target(target);
            if !expanded.exists() {
                scheduled_log(
                    &i18n::translate(&ctx, "Warning: Target does not exist: {target}")
                        .replace("{target}", target),
                    false,
                );
                false
            } else {
                true
            }
        })
        .map(|target| expand_target(&target).display().to_string())
        .collect::<Vec<_>>();
    if valid.is_empty() {
        return Err(i18n::translate(&ctx, "Error: No valid scan targets found"));
    }
    if options.dry_run {
        scheduled_log(
            &i18n::translate(
                &ctx,
                // Translators: The em dash separates the dry-run state from its consequence.
                "Dry run mode — scan not executed",
            ),
            false,
        );
        scheduled_log(
            &i18n::translate(&ctx, "  Skip on battery: {value}")
                .replace("{value}", &skip_on_battery.to_string()),
            false,
        );
        scheduled_log(
            &i18n::translate(&ctx, "  Auto quarantine: {value}")
                .replace("{value}", &auto_quarantine.to_string()),
            false,
        );
        let target_count = valid.len() as u64;
        let target_count_text = target_count.to_string();
        let target_list = format!("{valid:?}");
        scheduled_log(
            &trnf(
                &ctx,
                "  {count} target: {targets:?}",
                "  {count} targets: {targets:?}",
                target_count,
                &[
                    ("{count}", &target_count_text),
                    ("{targets:?}", &target_list),
                ],
            ),
            false,
        );
        return Ok(0);
    }
    let availability = scanner::dispatch(&ctx, "status", json!({}))?;
    if !availability
        .get("available")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        let reason = availability
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("ClamAV is not installed or not accessible");
        let summary = i18n::translate(&ctx, "Scheduled scan failed: ClamAV not available");
        let _ = logs::dispatch(
            &ctx,
            "create",
            json!({
                "type": "scan", "status": "error", "summary": summary,
                "details": reason, "path": valid.join(", "), "scheduled": true,
            }),
        );
        scheduled_log(
            &i18n::translate(
                &ctx,
                // Translators: The em dash separates the unavailable component from `{error}`; preserve the raw diagnostic placeholder.
                "Error: ClamAV not available — {error}",
            )
            .replace("{error}", reason),
            false,
        );
        let _ = notify(
            &i18n::translate(&ctx, "Scheduled Scan Failed"),
            &i18n::translate(&ctx, "ClamAV is not available. Please install ClamAV."),
            "critical",
        );
        return Ok(2);
    }
    let target_summary = valid.join(", ");
    let result = scanner::dispatch(
        &ctx,
        "scan",
        json!({"paths": valid.clone(), "recursive":true, "scheduled":true}),
    )?;
    if ctx.interrupted() {
        return Ok(130);
    }
    let infected = result
        .get("infected_count")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let status = result
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("error");
    let mut quarantine_failures = Vec::new();
    let mut quarantined = 0_u64;
    if auto_quarantine && infected > 0 {
        for threat in result
            .get("threat_details")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let Some(path) = threat.get("file_path").and_then(Value::as_str) else {
                continue;
            };
            let Some(threat_name) = threat.get("threat_name").and_then(Value::as_str) else {
                continue;
            };
            let response = quarantine::dispatch(
                &ctx,
                "quarantine",
                json!({"path":path, "threat_name":threat_name}),
            )?;
            if response.get("status").and_then(Value::as_str) == Some("success") {
                quarantined += 1;
            } else {
                quarantine_failures.push(format!(
                    "{path}: {}",
                    response
                        .get("error_message")
                        .and_then(Value::as_str)
                        .unwrap_or("quarantine failed")
                ));
            }
        }
    }
    let scanned = result
        .get("scanned_files")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let summary = if infected > 0 {
        let infected_text = infected.to_string();
        if quarantined > 0 {
            let quarantined_text = quarantined.to_string();
            trnf(
                &ctx,
                "Scheduled scan found {infected} threat, {quarantined} quarantined",
                "Scheduled scan found {infected} threats, {quarantined} quarantined",
                infected,
                &[
                    ("{infected}", &infected_text),
                    ("{quarantined}", &quarantined_text),
                ],
            )
        } else {
            trnf(
                &ctx,
                "Scheduled scan found {count} threat",
                "Scheduled scan found {count} threats",
                infected,
                &[("{count}", &infected_text)],
            )
        }
    } else if status == "error" || status == "cancelled" {
        i18n::translate(&ctx, "Scheduled scan completed with errors")
    } else {
        let scanned_text = scanned.to_string();
        trnf(
            &ctx,
            // Translators: The em dash separates the summary from the count; preserve `{count}`.
            "Scheduled scan completed — {count} file scanned, no threats",
            // Translators: The em dash separates the summary from the count; preserve `{count}`.
            "Scheduled scan completed — {count} files scanned, no threats",
            scanned,
            &[("{count}", &scanned_text)],
        )
    };
    let duration = result
        .get("duration_seconds")
        .and_then(Value::as_f64)
        .unwrap_or(0.0);
    let mut details = vec![
        i18n::translate(&ctx, "Scan Duration: {duration:.1f} seconds")
            .replace("{duration:.1f}", &format!("{duration:.1}")),
        i18n::translate(&ctx, "Files Scanned: {count}").replace("{count}", &scanned.to_string()),
        i18n::translate(&ctx, "Threats Found: {count}").replace("{count}", &infected.to_string()),
        i18n::translate(&ctx, "Targets: {targets}").replace("{targets}", &target_summary),
    ];
    if auto_quarantine && infected > 0 {
        details.push(
            i18n::translate(&ctx, "Quarantined: {count}")
                .replace("{count}", &quarantined.to_string()),
        );
        if !quarantine_failures.is_empty() {
            details.push(
                i18n::translate(&ctx, "Quarantine Failed: {count}")
                    .replace("{count}", &quarantine_failures.len().to_string()),
            );
        }
    }
    let _ = logs::dispatch(
        &ctx,
        "create",
        json!({
            "type": "scan",
            "status": if infected > 0 { "infected" } else if status == "error" { "error" } else { status },
            "summary": summary.clone(),
            "details": details.join("\n"),
            "path": target_summary,
            "duration": duration,
            "scanned_files": scanned,
            "infected_count": infected,
            "scheduled": true,
        }),
    );
    scheduled_log(&summary, false);
    if settings
        .get("notifications_enabled")
        .and_then(Value::as_bool)
        .unwrap_or(true)
    {
        let (title, body, urgency) = if infected > 0 {
            (
                i18n::translate(&ctx, "Scheduled Scan: Threats Detected!"),
                summary.clone(),
                "critical",
            )
        } else if status == "error" || status == "cancelled" {
            (
                i18n::translate(&ctx, "Scheduled Scan Completed"),
                i18n::translate(
                    &ctx,
                    "Scan completed with some errors. Check logs for details.",
                ),
                "normal",
            )
        } else {
            (
                i18n::translate(&ctx, "Scheduled Scan Complete"),
                summary.clone(),
                "low",
            )
        };
        let _ = notify(&title, &body, urgency);
    }
    // Scanner persists the scheduled aggregate log; keep the old concise
    // failure count on stderr and reveal individual paths only in verbose mode.
    if !quarantine_failures.is_empty() {
        let failure_count = quarantine_failures.len() as u64;
        let failure_count_text = failure_count.to_string();
        scheduled_log(
            &trnf(
                &ctx,
                "Failed to quarantine: {count} file",
                "Failed to quarantine: {count} files",
                failure_count,
                &[("{count}", &failure_count_text)],
            ),
            false,
        );
        if options.verbose {
            for failure in quarantine_failures {
                scheduled_log(&format!("  - {failure}"), false);
            }
        }
    }
    Ok(if infected > 0 {
        1
    } else if status == "error" || status == "cancelled" {
        2
    } else {
        0
    })
}

fn battery_skip_details(ctx: &Context, charge_percent: Option<f64>) -> String {
    match charge_percent {
        Some(percent) => i18n::translate(
            ctx,
            "Battery level: {percent:.0f}%\nScan skipped due to battery-aware settings.",
        )
        .replace("{percent:.0f}", &format!("{percent:.0}")),
        None => i18n::translate(ctx, "Scan skipped due to battery-aware settings."),
    }
}

fn battery_skip_message(ctx: &Context, charge_percent: Option<f64>) -> String {
    match charge_percent {
        Some(percent) => i18n::translate(
            ctx,
            "Skipping scan: running on battery power ({percent:.0f}%)",
        )
        .replace("{percent:.0f}", &format!("{percent:.0}")),
        None => i18n::translate(ctx, "Skipping scan: running on battery power"),
    }
}

fn expand_target(target: &str) -> PathBuf {
    if target == "~" {
        return env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(target));
    }
    if let Some(rest) = target.strip_prefix("~/") {
        return env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("~"))
            .join(rest);
    }
    PathBuf::from(target)
}

struct ScheduledOptions {
    skip_on_battery: Option<bool>,
    auto_quarantine: Option<bool>,
    targets: Vec<String>,
    dry_run: bool,
    verbose: bool,
    help: bool,
}
impl ScheduledOptions {
    fn parse(args: &[String]) -> AppResult<Self> {
        let mut options = Self {
            skip_on_battery: None,
            auto_quarantine: None,
            targets: Vec::new(),
            dry_run: false,
            verbose: false,
            help: false,
        };
        let mut index = 0;
        while index < args.len() {
            match args[index].as_str() {
                "--skip-on-battery" => options.skip_on_battery = Some(true),
                "--auto-quarantine" => options.auto_quarantine = Some(true),
                "--dry-run" => options.dry_run = true,
                "--verbose" | "-v" => options.verbose = true,
                "--help" | "-h" => options.help = true,
                "--target" => {
                    index += 1;
                    options.targets.push(
                        args.get(index)
                            .ok_or_else(|| "--target requires a path".to_owned())?
                            .to_owned(),
                    );
                }
                value => return Err(format!("Unknown scheduled scan option: {value}")),
            }
            index += 1;
        }
        Ok(options)
    }
}
fn scheduled_log(message: &str, _verbose_only: bool) {
    eprintln!("[{}] {message}", Local::now().format("%Y-%m-%d %H:%M:%S"));
}

fn notify(title: &str, body: &str, urgency: &str) -> AppResult<()> {
    let mut args = vec![
        format!("--urgency={urgency}"),
        "--app-name=ClamUI".to_owned(),
    ];
    let user_icon = env::var_os("HOME").map(PathBuf::from).map(|home| {
        home.join(".local/share/icons/hicolor/scalable/apps/io.github.linx_systems.ClamUI.png")
    });
    let icon = [
        PathBuf::from("/app/share/icons/hicolor/scalable/apps/io.github.linx_systems.ClamUI.png"),
        PathBuf::from("/usr/share/icons/hicolor/scalable/apps/io.github.linx_systems.ClamUI.png"),
    ]
    .into_iter()
    .chain(user_icon)
    .find(|path| path.exists())
    .map(|path| path.display().to_string())
    .unwrap_or_else(|| "dialog-warning".to_owned());
    args.push(format!("--icon={icon}"));
    args.push(title.to_owned());
    args.push(body.to_owned());
    let mut child = host_command("notify-send", &args)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("Could not send notification: {error}"))?;
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("Could not send notification: {error}"))?
        {
            return if status.success() {
                Ok(())
            } else {
                Err("notify-send failed".to_owned())
            };
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err("notify-send timed out".to_owned());
        }
        std::thread::sleep(Duration::from_millis(25));
    }
}

fn value_string(object: &Map<String, Value>, normalized: &str, persisted: &str) -> Option<String> {
    object
        .get(normalized)
        .or_else(|| object.get(persisted))
        .and_then(Value::as_str)
        .map(str::to_owned)
}
fn value_bool(object: &Map<String, Value>, normalized: &str, persisted: &str) -> Option<bool> {
    object
        .get(normalized)
        .or_else(|| object.get(persisted))
        .and_then(Value::as_bool)
}
fn value_integer(object: &Map<String, Value>, normalized: &str, persisted: &str) -> Option<i64> {
    object
        .get(normalized)
        .or_else(|| object.get(persisted))
        .and_then(Value::as_i64)
}
fn value_strings(
    object: &Map<String, Value>,
    normalized: &str,
    persisted: &str,
) -> AppResult<Vec<String>> {
    match object.get(normalized).or_else(|| object.get(persisted)) {
        None => Ok(Vec::new()),
        Some(Value::Array(values)) => values
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| "Schedule targets must be strings".to_owned())
            })
            .collect(),
        Some(_) => Err("Schedule targets must be an array".to_owned()),
    }
}

#[cfg(test)]
mod tests {
    use super::battery_skip_details;
    use crate::common::{Context, Paths};
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn battery_skip_detail_retains_an_observed_percentage_unit() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "clamui-scheduler-battery-detail-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("temporary root");
        let context = Context::with_paths(Paths {
            home: root.join("home"),
            config_dir: root.join("config/clamui"),
            data_dir: root.join("data/clamui"),
        })
        .expect("context");
        let observed_details = battery_skip_details(&context, Some(57.0));
        assert!(
            observed_details.contains("57%"),
            "observed battery charge must retain its percent unit"
        );
        let unknown_details = battery_skip_details(&context, None);
        assert!(
            !unknown_details.chars().any(char::is_numeric),
            "unknown battery charge must not fabricate a numeric percentage"
        );

        drop(context);
        fs::remove_dir_all(root).expect("temporary root cleanup");
    }
}
