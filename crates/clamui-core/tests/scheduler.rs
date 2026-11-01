use clamui_core::scheduler::{
    cron_command, cron_expression, is_clamui_cron_command, normalize_schedule, on_calendar,
    remove_our_cron_lines, service_file, timer_file, validate_target_paths, ScheduleConfig,
    ScheduleFrequency, CRON_MARKER,
};
use std::fs;
use std::process::Command;

use tempfile::tempdir;

fn schedule() -> ScheduleConfig {
    ScheduleConfig {
        enabled: true,
        frequency: ScheduleFrequency::Weekly,
        time: "14:30".to_owned(),
        targets: vec!["/home/alice/Documents".to_owned()],
        skip_on_battery: true,
        auto_quarantine: true,
        day_of_week: 2,
        day_of_month: 15,
    }
}

#[test]
fn calendar_and_cron_use_python_weekday_mapping_and_safe_month_days() {
    assert_eq!(
        on_calendar(ScheduleFrequency::Hourly, "bad", 0, 1),
        "*-*-* *:00:00"
    );
    assert_eq!(
        on_calendar(ScheduleFrequency::Daily, "bad", 0, 1),
        "*-*-* 02:00:00"
    );
    assert_eq!(
        on_calendar(ScheduleFrequency::Weekly, "14:30", 0, 1),
        "Mon *-*-* 14:30:00"
    );
    assert_eq!(
        on_calendar(ScheduleFrequency::Weekly, "14:30", 6, 1),
        "Sun *-*-* 14:30:00"
    );
    assert_eq!(
        on_calendar(ScheduleFrequency::Monthly, "14:30", 0, 99),
        "*-*-28 14:30:00"
    );
    assert_eq!(
        cron_expression(ScheduleFrequency::Weekly, "14:30", 0, 1),
        "30 14 * * 1"
    );
    assert_eq!(
        cron_expression(ScheduleFrequency::Weekly, "14:30", 6, 1),
        "30 14 * * 0"
    );
    assert_eq!(
        cron_expression(ScheduleFrequency::Monthly, "14:30", 0, 0),
        "30 14 1 * *"
    );
}

#[test]
fn service_escapes_systemd_specifiers_and_only_argument_dollars() {
    let mut schedule = schedule();
    schedule.targets = vec!["/scan/$HOME/%h/quote'file".to_owned()];
    let unit = service_file(
        &["/opt/$launcher/clamui-scheduled-scan".to_owned()],
        &schedule,
    );
    assert!(unit.contains("/opt/$launcher/clamui-scheduled-scan"));
    assert!(unit.contains("/scan/$$HOME/%%h/"));
    assert!(unit.contains("--skip-on-battery --auto-quarantine"));
    assert!(unit.contains("Nice=19\nIOSchedulingClass=idle"));
    assert!(timer_file("Mon *-*-* 02:00:00").contains("Persistent=true\nRandomizedDelaySec=300"));
}

fn cron_command_for_shell(command: &str) -> String {
    let mut result = String::new();
    let mut characters = command.chars();
    while let Some(character) = characters.next() {
        match character {
            '\\' => match characters.next() {
                Some('%') => result.push('%'),
                Some(next) => {
                    result.push('\\');
                    result.push(next);
                }
                None => result.push('\\'),
            },
            '%' => panic!("generated cron command contains an unescaped percent"),
            _ => result.push(character),
        }
    }
    result
}

#[test]
fn cron_preserves_an_adversarial_target_as_one_shell_argument() {
    let directory = tempdir().unwrap();
    let recorder = directory.path().join("record-argv");
    let recorded = directory.path().join("argv.txt");
    let sentinel = directory.path().join("must-not-exist");
    fs::write(
        &recorder,
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CLAMUI_ARGV_FILE\"\n",
    )
    .unwrap();

    let target = format!("/scan/a'b%c $HOME;$(touch {})", sentinel.display());
    let mut schedule = schedule();
    schedule.targets = vec![target.clone()];
    let command = cron_command(
        &["sh".to_owned(), recorder.display().to_string()],
        &schedule,
    );
    let status = Command::new("sh")
        .arg("-c")
        .arg(cron_command_for_shell(&command))
        .env("CLAMUI_ARGV_FILE", &recorded)
        .status()
        .unwrap();

    assert!(status.success());
    assert!(!sentinel.exists());
    let argv = fs::read_to_string(&recorded)
        .unwrap()
        .lines()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    assert_eq!(
        argv,
        vec![
            "--skip-on-battery".to_owned(),
            "--auto-quarantine".to_owned(),
            "--target".to_owned(),
            target,
        ]
    );
}

#[test]
fn validation_rejects_only_cron_and_path_injection_controls() {
    assert!(validate_target_paths(&["/safe/$(not-executed)%file".to_owned()]).is_ok());
    assert!(validate_target_paths(&["/safe\ninjected".to_owned()]).is_err());
    assert!(validate_target_paths(&["/safe\rinjected".to_owned()]).is_err());
    assert!(validate_target_paths(&["/safe\0truncated".to_owned()]).is_err());
}

#[test]
fn cron_cleanup_removes_only_a_marker_with_a_recognized_clamui_command() {
    let cron = format!(
        "0 1 * * * /usr/bin/backup\n{CRON_MARKER}\n0 2 * * * /usr/bin/clamui-scheduled-scan --target /home\n{CRON_MARKER}\n0 3 * * * /usr/bin/user-task\n# {CRON_MARKER}\n"
    );
    assert!(is_clamui_cron_command(
        "0 2 * * * /usr/bin/clamui-scheduled-scan --target /home"
    ));
    assert!(is_clamui_cron_command(
        "0 2 * * * flatpak run --command=clamui-scheduled-scan io.github.linx_systems.ClamUI"
    ));
    assert!(is_clamui_cron_command(
        "0 2 * * * python3 -m src.cli.scheduled_scan"
    ));
    assert!(is_clamui_cron_command(
        "0 2 * * * /home/alice/ClamUI.AppImage --scheduled-scan --target /home"
    ));
    assert!(!is_clamui_cron_command(
        "0 2 * * * /usr/bin/user-task clamui-scheduled-scan"
    ));
    assert_eq!(
        remove_our_cron_lines(&cron),
        vec![
            "0 1 * * * /usr/bin/backup".to_owned(),
            "0 3 * * * /usr/bin/user-task".to_owned(),
            format!("# {CRON_MARKER}"),
        ]
    );
}

#[test]
fn explicit_schedule_overrides_take_precedence_over_persisted_names() {
    let schedule = ScheduleConfig::from_value(&serde_json::json!({
        "scheduled_scans_enabled": false,
        "schedule_frequency": "monthly",
        "schedule_time": "02:00",
        "schedule_targets": ["/home/persisted"],
        "schedule_skip_on_battery": true,
        "schedule_auto_quarantine": false,
        "schedule_day_of_week": 0,
        "schedule_day_of_month": 1,
        "enabled": true,
        "frequency": "weekly",
        "time": "23:59",
        "targets": ["/home/explicit", "/srv"],
        "skip_on_battery": false,
        "auto_quarantine": true,
        "day_of_week": 6,
        "day_of_month": 30
    }))
    .unwrap();
    assert!(schedule.enabled);
    assert_eq!(schedule.frequency, ScheduleFrequency::Weekly);
    assert_eq!(schedule.time, "23:59");
    assert_eq!(
        schedule.targets,
        vec!["/home/explicit".to_owned(), "/srv".to_owned()]
    );
    assert!(!schedule.skip_on_battery);
    assert!(schedule.auto_quarantine);
    assert_eq!(schedule.day_of_week, 6);
    assert_eq!(schedule.day_of_month, 30);
}

#[test]
fn detached_schedule_preflight_rejects_invalid_input_without_context_or_host_io() {
    assert!(normalize_schedule(&serde_json::json!({
        "schedule_frequency": "annually",
        "schedule_targets": ["/home/alice"],
    }))
    .is_err());
    assert!(normalize_schedule(&serde_json::json!({
        "schedule_frequency": "daily",
        "schedule_targets": ["/home/alice\ninjected-cron"],
    }))
    .is_err());
    let normalized = normalize_schedule(&serde_json::json!({
        "schedule_frequency": "weekly",
        "schedule_time": "invalid-time",
        "schedule_targets": ["/home/alice"],
        "schedule_day_of_week": -1,
        "schedule_day_of_month": 35,
    }))
    .unwrap();
    assert_eq!(normalized.frequency, ScheduleFrequency::Weekly);
    assert_eq!(normalized.time, "02:00");
    assert_eq!(normalized.day_of_week, 6);
    assert_eq!(normalized.day_of_month, 28);
}
