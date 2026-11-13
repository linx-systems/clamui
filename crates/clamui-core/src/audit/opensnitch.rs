use std::process::Stdio;
use std::time::Duration;

use super::{tr, AuditCheck, AuditSection, AuditStatus, Context};
use crate::common::host_command;
use crate::host_probe::{run_limited_command, LimitedCommandOutput};
use crate::AppResult;

const PROBE_TIMEOUT: Duration = Duration::from_secs(2);
const PROBE_OUTPUT_LIMIT: usize = 4096;

// This fixed script only resolves commands and checks the fixed desktop-entry name.
// It never executes OpenSnitch or accepts a command or path from the frontend.
const GUI_INVENTORY: &str = r#"
if [ -z "${PATH:-}" ]; then
    printf 'unknown\n'
    exit 0
fi
if command -v opensnitch-ui >/dev/null 2>&1; then
    printf 'command\n'
    exit 0
fi
unknown=no
old_ifs=$IFS
IFS=:
set -f
set -- $PATH
IFS=$old_ifs
for dir do
    case $dir in /*) ;; *) unknown=yes; continue ;; esac
    if [ -d "$dir" ] && { [ ! -r "$dir" ] || [ ! -x "$dir" ]; }; then
        unknown=yes
    fi
done
if ! command -v gtk-launch >/dev/null 2>&1; then
    if [ "$unknown" = yes ]; then printf 'unknown\n'; else printf 'missing\n'; fi
    exit 0
fi
if [ -n "${XDG_DATA_HOME:-}" ]; then
    data_home=$XDG_DATA_HOME
elif [ -n "${HOME:-}" ]; then
    data_home=$HOME/.local/share
else
    printf 'unknown\n'
    exit 0
fi
case $data_home in /*) ;; *) printf 'unknown\n'; exit 0 ;; esac
data_dirs=${XDG_DATA_DIRS:-/usr/local/share:/usr/share}
old_ifs=$IFS
IFS=:
set -f
set -- $data_dirs
IFS=$old_ifs
set -- "$data_home" "$@"
for dir do
    case $dir in /*) ;; *) unknown=yes; continue ;; esac
    if [ -f "$dir/applications/opensnitch_ui.desktop" ] && [ -r "$dir/applications/opensnitch_ui.desktop" ]; then
        printf 'desktop\n'
        exit 0
    fi
    if [ -e "$dir/applications/opensnitch_ui.desktop" ] || { [ -d "$dir" ] && { [ ! -r "$dir" ] || [ ! -x "$dir" ]; }; } || { [ -d "$dir/applications" ] && { [ ! -r "$dir/applications" ] || [ ! -x "$dir/applications" ]; }; }; then
        unknown=yes
    fi
done
if [ "$unknown" = yes ]; then
    printf 'unknown\n'
else
    printf 'missing\n'
fi
"#;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ServiceState {
    Running,
    Inactive,
    Transitional,
    Missing,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum GuiTarget {
    Command,
    Desktop,
    Missing,
    Unknown,
}

fn usable(output: &LimitedCommandOutput) -> bool {
    output.code == Some(0) && !output.timed_out && !output.truncated && !output.invalid_utf8
}

fn inspect_service(output: &LimitedCommandOutput) -> ServiceState {
    if !usable(output) || !output.stdout.ends_with('\n') {
        return ServiceState::Unknown;
    }
    let mut load = None;
    let mut active = None;
    let mut sub = None;
    for line in output.stdout.lines() {
        let Some((key, value)) = line.split_once('=') else {
            return ServiceState::Unknown;
        };
        let slot = match key {
            "LoadState" => &mut load,
            "ActiveState" => &mut active,
            "SubState" => &mut sub,
            _ => return ServiceState::Unknown,
        };
        if value.is_empty() || slot.replace(value).is_some() {
            return ServiceState::Unknown;
        }
    }
    match (load, active, sub) {
        (Some("loaded"), Some("active"), Some("running")) => ServiceState::Running,
        (Some("loaded"), Some("inactive"), Some("dead"))
        | (Some("loaded"), Some("failed"), Some("failed")) => ServiceState::Inactive,
        (
            Some("loaded"),
            Some("activating" | "deactivating" | "reloading" | "refreshing"),
            Some(_),
        ) => ServiceState::Transitional,
        (Some("not-found"), Some("inactive"), Some("dead")) => ServiceState::Missing,
        _ => ServiceState::Unknown,
    }
}

fn combine_services(first: ServiceState, second: ServiceState) -> ServiceState {
    use ServiceState::{Inactive, Missing, Running, Transitional, Unknown};
    match (first, second) {
        (Running, _) | (_, Running) => Running,
        (Transitional, _) | (_, Transitional) => Transitional,
        (Inactive, _) | (_, Inactive) => Inactive,
        (Missing, Missing) => Missing,
        _ => Unknown,
    }
}

fn inspect_gui(output: &LimitedCommandOutput) -> GuiTarget {
    if !usable(output) {
        return GuiTarget::Unknown;
    }
    match output.stdout.as_str() {
        "command\n" => GuiTarget::Command,
        "desktop\n" => GuiTarget::Desktop,
        "missing\n" => GuiTarget::Missing,
        _ => GuiTarget::Unknown,
    }
}

fn resolve_gui() -> GuiTarget {
    inspect_gui(&run_limited_command(
        "sh",
        &["-c", GUI_INVENTORY],
        PROBE_TIMEOUT,
        PROBE_OUTPUT_LIMIT,
    ))
}

pub(super) fn append_checks(ctx: &Context, section: &mut AuditSection) {
    let service = |unit| {
        inspect_service(&run_limited_command(
            "systemctl",
            &[
                "show",
                "--no-pager",
                "--property=LoadState",
                "--property=ActiveState",
                "--property=SubState",
                unit,
            ],
            PROBE_TIMEOUT,
            PROBE_OUTPUT_LIMIT,
        ))
    };
    add_service(
        ctx,
        section,
        combine_services(
            service("opensnitch.service"),
            service("opensnitchd.service"),
        ),
    );
    add_gui(ctx, section, resolve_gui());
}

fn add_service(ctx: &Context, section: &mut AuditSection, state: ServiceState) {
    let name = tr(
        ctx,
        // Translators: Keep the product name OpenSnitch unchanged.
        "OpenSnitch service",
    );
    let (status, detail) = match state {
        ServiceState::Running => (AuditStatus::Pass, tr(ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "An OpenSnitch system service is active and running. This does not verify filtering.")),
        ServiceState::Inactive => (AuditStatus::Warning, tr(ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "An installed OpenSnitch system service is inactive or failed.")),
        ServiceState::Transitional => (AuditStatus::Unknown, tr(ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "An OpenSnitch system service is changing state; its status is unknown.")),
        ServiceState::Missing => (AuditStatus::Skipped, tr(ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "No local OpenSnitch system service was detected. A manually started daemon was not checked.")),
        ServiceState::Unknown => (AuditStatus::Unknown, tr(ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "OpenSnitch system service status could not be determined.")),
    };
    let mut row = AuditCheck::new(name, status, detail);
    row.optional_missing = state == ServiceState::Missing;
    section.push(row);
}

fn add_gui(ctx: &Context, section: &mut AuditSection, target: GuiTarget) {
    let name = tr(
        ctx,
        // Translators: Keep the product name OpenSnitch unchanged.
        "OpenSnitch graphical interface",
    );
    let (status, detail) = match target {
        GuiTarget::Command | GuiTarget::Desktop => (AuditStatus::Pass, tr(ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "The OpenSnitch graphical interface is available. Its connection status was not checked.")),
        GuiTarget::Missing => (AuditStatus::Skipped, tr(ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "No local OpenSnitch graphical interface launch target was detected.")),
        GuiTarget::Unknown => (AuditStatus::Unknown, tr(ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "OpenSnitch graphical interface availability could not be determined.")),
    };
    let mut row = AuditCheck::new(name, status, detail);
    row.optional_missing = target == GuiTarget::Missing;
    if matches!(target, GuiTarget::Command | GuiTarget::Desktop) {
        row.launch_command = Some("opensnitch-ui".to_owned());
        row.launch_label = Some(tr(
            ctx,
            // Translators: Keep the product name OpenSnitch unchanged.
            "Open OpenSnitch",
        ));
    }
    section.push(row);
}

pub(super) fn launch_gui(ctx: &Context) -> AppResult<bool> {
    let mut command = match resolve_gui() {
        GuiTarget::Command => host_command("opensnitch-ui", &[]),
        GuiTarget::Desktop => host_command("gtk-launch", &["opensnitch_ui".to_owned()]),
        GuiTarget::Missing => {
            return Err(tr(
                ctx,
                // Translators: Keep the product name OpenSnitch unchanged.
                "OpenSnitch graphical interface is not available.",
            ));
        }
        GuiTarget::Unknown => {
            return Err(tr(
                ctx,
                // Translators: Keep the product name OpenSnitch unchanged.
                "OpenSnitch graphical interface availability could not be determined.",
            ));
        }
    };
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| true)
        .map_err(|error| {
            super::text(
                ctx,
                // Translators: Keep the product name OpenSnitch and the {error} placeholder unchanged.
                "Could not launch OpenSnitch graphical interface: {error}",
                &[("{error}", crate::common::sanitize_line(&error.to_string()))],
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audit::AuditCategory;
    use crate::common::Paths;
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use std::path::Path;
    use std::process::Command;
    use tempfile::TempDir;

    fn output(text: &str) -> LimitedCommandOutput {
        LimitedCommandOutput {
            code: Some(0),
            stdout: text.to_owned(),
            timed_out: false,
            truncated: false,
            invalid_utf8: false,
        }
    }

    fn context(temp: &TempDir) -> Context {
        Context::with_paths(Paths {
            home: temp.path().join("home"),
            config_dir: temp.path().join("config"),
            data_dir: temp.path().join("data"),
        })
        .expect("create test context")
    }

    fn section(ctx: &Context) -> AuditSection {
        AuditSection::new(
            ctx,
            AuditCategory::Firewall,
            "Firewall",
            "security-medium-symbolic",
        )
    }

    fn executable(path: &Path) {
        fs::write(
            path,
            "#!/bin/sh\nprintf invoked > \"$INVENTORY_MARKER\"\nexit 99\n",
        )
        .expect("write executable fixture");
        fs::set_permissions(path, fs::Permissions::from_mode(0o755)).expect("mark executable");
    }

    fn inventory(path: &Path, home: &Path, data_dirs: &Path) -> GuiTarget {
        let result = Command::new("/bin/sh")
            .args(["-c", GUI_INVENTORY])
            .env_clear()
            .env("PATH", path)
            .env("HOME", home)
            .env("INVENTORY_MARKER", home.join("inventory-invoked"))
            .env("XDG_DATA_DIRS", data_dirs)
            .output()
            .expect("run inventory shell");
        inspect_gui(&LimitedCommandOutput {
            code: result.status.code(),
            stdout: String::from_utf8(result.stdout).expect("UTF-8 inventory"),
            timed_out: false,
            truncated: false,
            invalid_utf8: false,
        })
    }

    #[test]
    fn either_service_alias_running_wins_over_missing_or_unavailable_alias() {
        let running = inspect_service(&output(
            "LoadState=loaded\nActiveState=active\nSubState=running\n",
        ));
        let missing = inspect_service(&output(
            "LoadState=not-found\nActiveState=inactive\nSubState=dead\n",
        ));
        let unknown = inspect_service(&output(""));
        assert_eq!(combine_services(running, missing), ServiceState::Running);
        assert_eq!(combine_services(missing, running), ServiceState::Running);
        assert_eq!(combine_services(running, unknown), ServiceState::Running);
        assert_eq!(combine_services(unknown, running), ServiceState::Running);
    }

    #[test]
    fn installed_inactive_failed_and_transition_states_are_distinct() {
        let inactive = inspect_service(&output(
            "LoadState=loaded\nActiveState=inactive\nSubState=dead\n",
        ));
        let failed = inspect_service(&output(
            "LoadState=loaded\nActiveState=failed\nSubState=failed\n",
        ));
        let transitional = inspect_service(&output(
            "LoadState=loaded\nActiveState=activating\nSubState=start\n",
        ));
        assert_eq!(inactive, ServiceState::Inactive);
        assert_eq!(failed, ServiceState::Inactive);
        assert_eq!(transitional, ServiceState::Transitional);
        assert_eq!(
            combine_services(inactive, transitional),
            ServiceState::Transitional
        );
    }

    #[test]
    fn unavailable_or_incomplete_service_observations_never_prove_absence() {
        let text = "LoadState=not-found\nActiveState=inactive\nSubState=dead\n";
        let mut failed = output(text);
        failed.code = Some(1);
        let mut timeout = output(text);
        timeout.timed_out = true;
        let mut truncated = output(text);
        truncated.truncated = true;
        let mut invalid = output(text);
        invalid.invalid_utf8 = true;
        for observation in [
            failed,
            timeout,
            truncated,
            invalid,
            output("LoadState=not-found\nActiveState=inactive\n"),
            output("LoadState=not-found\nActiveState=inactive\nSubState=dead"),
            output(
                "LoadState=loaded\nActiveState=active\nSubState=running\nActiveState=inactive\n",
            ),
            output("LoadState=loaded\nActiveState=future\nSubState=running\n"),
        ] {
            assert_eq!(inspect_service(&observation), ServiceState::Unknown);
        }
        assert_eq!(
            combine_services(ServiceState::Missing, ServiceState::Unknown),
            ServiceState::Unknown
        );
        assert_eq!(
            combine_services(ServiceState::Missing, ServiceState::Missing),
            ServiceState::Missing
        );
    }

    #[test]
    fn gui_only_and_daemon_only_inventories_keep_independent_rows() {
        let temp = TempDir::new().expect("temporary directory");
        let ctx = context(&temp);
        let mut gui_only = section(&ctx);
        add_service(&ctx, &mut gui_only, ServiceState::Missing);
        add_gui(&ctx, &mut gui_only, GuiTarget::Desktop);
        assert_eq!(gui_only.checks[0].status, AuditStatus::Skipped);
        assert_eq!(gui_only.checks[1].status, AuditStatus::Pass);
        assert!(gui_only.checks[0].optional_missing);
        assert!(!gui_only.checks[1].optional_missing);
        assert_eq!(
            gui_only.checks[1].launch_command.as_deref(),
            Some("opensnitch-ui")
        );

        let mut daemon_only = section(&ctx);
        add_service(&ctx, &mut daemon_only, ServiceState::Running);
        add_gui(&ctx, &mut daemon_only, GuiTarget::Missing);
        assert_eq!(daemon_only.checks[0].status, AuditStatus::Pass);
        assert_eq!(daemon_only.checks[1].status, AuditStatus::Skipped);
        assert!(!daemon_only.checks[0].optional_missing);
        assert!(daemon_only.checks[1].optional_missing);
        assert!(daemon_only.checks[1].launch_command.is_none());
    }

    #[test]
    fn uncertain_and_inactive_observations_produce_honest_rows() {
        let temp = TempDir::new().expect("temporary directory");
        let ctx = context(&temp);
        let mut result = section(&ctx);
        add_service(&ctx, &mut result, ServiceState::Inactive);
        add_service(&ctx, &mut result, ServiceState::Transitional);
        add_service(&ctx, &mut result, ServiceState::Unknown);
        add_gui(&ctx, &mut result, GuiTarget::Unknown);
        assert_eq!(result.checks[0].status, AuditStatus::Warning);
        assert_eq!(result.checks[1].status, AuditStatus::Unknown);
        assert_eq!(result.checks[2].status, AuditStatus::Unknown);
        assert_eq!(result.checks[3].status, AuditStatus::Unknown);
        assert!(result.checks.iter().all(|check| !check.optional_missing));
        assert!(result.checks[3].launch_command.is_none());
    }

    #[test]
    fn gui_resolver_requires_complete_valid_output() {
        let mut failed = output("command\n");
        failed.code = None;
        let mut timeout = output("desktop\n");
        timeout.timed_out = true;
        let mut invalid = output("command\n");
        invalid.invalid_utf8 = true;
        let mut truncated = output("missing\n");
        truncated.truncated = true;
        for observation in [
            failed,
            timeout,
            invalid,
            truncated,
            output("command"),
            output("command\nmissing\n"),
            output("unknown\n"),
        ] {
            assert_eq!(inspect_gui(&observation), GuiTarget::Unknown);
        }
    }

    #[test]
    fn nix_profile_path_resolves_gui_without_executing_it() {
        let temp = TempDir::new().expect("temporary directory");
        let profile_bin = temp.path().join("nix-profile/bin");
        fs::create_dir_all(&profile_bin).expect("profile bin");
        executable(&profile_bin.join("opensnitch-ui"));
        assert_eq!(
            inventory(&profile_bin, temp.path(), temp.path()),
            GuiTarget::Command
        );
        assert!(!temp.path().join("inventory-invoked").exists());
    }

    #[test]
    fn desktop_entry_in_profile_data_dirs_is_detected_with_gtk_launch() {
        let temp = TempDir::new().expect("temporary directory");
        let bin = temp.path().join("bin");
        let profile = temp.path().join("nix-profile/share");
        fs::create_dir_all(&bin).expect("bin");
        fs::create_dir_all(profile.join("applications")).expect("applications");
        executable(&bin.join("gtk-launch"));
        let gui = temp.path().join("gui-fixture");
        executable(&gui);
        fs::write(
            profile.join("applications/opensnitch_ui.desktop"),
            format!(
                "[Desktop Entry]\nType=Application\nName=OpenSnitch\nExec={}\n",
                gui.display()
            ),
        )
        .expect("desktop entry");
        assert_eq!(inventory(&bin, temp.path(), &profile), GuiTarget::Desktop);
    }

    #[test]
    fn absent_gui_is_skipped_and_missing_shell_is_unknown() {
        let temp = TempDir::new().expect("temporary directory");
        let bin = temp.path().join("bin");
        fs::create_dir_all(&bin).expect("bin");
        executable(&bin.join("gtk-launch"));
        assert_eq!(
            inventory(&bin, temp.path(), temp.path()),
            GuiTarget::Missing
        );
        let unavailable = LimitedCommandOutput {
            code: None,
            stdout: String::new(),
            timed_out: false,
            truncated: false,
            invalid_utf8: false,
        };
        assert_eq!(inspect_gui(&unavailable), GuiTarget::Unknown);
    }
}
